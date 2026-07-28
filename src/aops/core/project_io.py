"""Reading and writing `.aops` project files.

Format is UTF-8 JSON with sorted keys. Chosen deliberately over pickle (which
executes arbitrary code on load - unacceptable for a file an engineer might
receive by email) and over a binary format (commissioning data gets committed
next to PLC source, and a reviewer needs to see what changed).

Two forward-compatibility guarantees:

* A file from a **newer** schema is refused with an explicit message rather than
  being partially understood. Guessing at a format you do not know produces a
  strip that is subtly wrong, which is the worst possible failure here.
* Unknown keys from a newer build are **preserved** into ``AopsConfig.extra``
  and written back out on save, so a round trip through an older build does not
  destroy data.

The ``fingerprint`` is a short hash of the canonical configuration, printed in
every page footer and on the guide page. It lets a commissioning engineer prove
that a printed strip in their hand corresponds to a stored project file - a
genuine traceability requirement when a machine is re-commissioned years later.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Final, get_args, get_origin, get_type_hints

from aops.core.config import AopsConfig
from aops.core.errors import ProjectFileError

#: Bump when a field is renamed/removed and add a migration below.
CURRENT_SCHEMA_VERSION: Final[int] = 1

FORMAT_TAG: Final[str] = "aops-project"

PROJECT_FILE_SUFFIX: Final[str] = ".aops"

#: Maps schema version N to a function producing a version N+1 payload.
MIGRATIONS: Final[dict[int, Any]] = {}


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedProject:
    """Result of reading a project file."""

    config: AopsConfig
    schema_version: int
    warnings: tuple[str, ...] = ()


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_value(value: Any) -> Any:
    """Recursively convert a dataclass field value into JSON-safe data."""
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _encode_dataclass(value)
    if isinstance(value, tuple):
        return [_encode_value(item) for item in value]
    return value


def _encode_dataclass(obj: Any) -> dict[str, Any]:
    return {f.name: _encode_value(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


def _decode_value(raw: Any, target: Any) -> Any:
    """Convert raw JSON data into the type annotated on a dataclass field."""
    origin = get_origin(target)

    if origin is tuple:
        args = get_args(target)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_value(item, args[0]) for item in raw)
        return tuple(_decode_value(item, arg) for item, arg in zip(raw, args, strict=False))

    if isinstance(target, type):
        if issubclass(target, Enum):
            try:
                return target(raw)
            except ValueError as exc:
                raise ProjectFileError(
                    f"{raw!r} is not a valid {target.__name__}. "
                    f"Valid values: {', '.join(str(m.value) for m in target)}"
                ) from exc
        if dataclasses.is_dataclass(target):
            return _decode_dataclass(raw, target)
        if target is bool:
            return bool(raw)
        if target is int:
            return int(raw)
        if target is float:
            return float(raw)
        if target is str:
            return str(raw)
    return raw


def _decode_dataclass(raw: dict[str, Any], target: type) -> Any:
    if not isinstance(raw, dict):
        raise ProjectFileError(f"Expected an object for {target.__name__}, got {type(raw).__name__}")
    hints = get_type_hints(target)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(target):
        if f.name in raw:
            kwargs[f.name] = _decode_value(raw[f.name], hints[f.name])
    return target(**kwargs)


def encode_value(value: Any) -> Any:
    """Convert one field value into JSON-safe data.

    Public so that presets, which serialise a *subset* of a configuration, can
    use exactly the same encoding as a whole project file rather than a second
    implementation that could drift from it.
    """
    return _encode_value(value)


def decode_value(raw: Any, target: Any) -> Any:
    """Convert raw JSON data back into the type annotated on a field."""
    return _decode_value(raw, target)


def _canonical_json(cfg: AopsConfig) -> str:
    """Stable serialisation used for fingerprinting.

    ``extra`` is excluded: unknown keys from a future build must not change the
    identity of a configuration this build fully understands.
    """
    payload = _encode_dataclass(cfg)
    payload.pop("extra", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def config_fingerprint(cfg: AopsConfig) -> str:
    """Short stable hash of a configuration, printed on every page."""
    return hashlib.sha256(_canonical_json(cfg).encode("utf-8")).hexdigest()[:8]


def dump_project(
    cfg: AopsConfig,
    *,
    app_version: str,
    created_utc: str | None = None,
) -> str:
    """Serialise a configuration to `.aops` JSON text."""
    now = _utc_now_iso()
    envelope: dict[str, Any] = {
        "format": FORMAT_TAG,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "app_version": app_version,
        "created_utc": created_utc or now,
        "modified_utc": now,
        "fingerprint": config_fingerprint(cfg),
        "config": _encode_dataclass(cfg),
    }
    for key, value in cfg.extra:
        envelope.setdefault(key, value)
    return json.dumps(envelope, indent=2, sort_keys=True) + "\n"


def load_project(text: str) -> LoadedProject:
    """Parse `.aops` JSON text into a configuration.

    Raises `ProjectFileError` on malformed input or a future schema version.
    """
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectFileError(f"Not valid JSON: {exc}") from exc

    if not isinstance(envelope, dict):
        raise ProjectFileError("Project file must contain a JSON object.")

    if envelope.get("format") != FORMAT_TAG:
        raise ProjectFileError(
            f"Not an AOPS project file (expected format {FORMAT_TAG!r}, "
            f"found {envelope.get('format')!r})."
        )

    raw_version = envelope.get("schema_version")
    if not isinstance(raw_version, int):
        raise ProjectFileError("Project file has no valid 'schema_version'.")

    warnings: list[str] = []

    if raw_version > CURRENT_SCHEMA_VERSION:
        raise ProjectFileError(
            f"This file was written by AOPS {envelope.get('app_version', '(unknown)')} "
            f"using schema {raw_version}; this build supports schema "
            f"{CURRENT_SCHEMA_VERSION}. Upgrade AOPS to open it."
        )

    version = raw_version
    while version < CURRENT_SCHEMA_VERSION:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            raise ProjectFileError(
                f"No migration available from schema {version} to {version + 1}."
            )
        envelope = migrate(envelope)
        warnings.append(f"Migrated project from schema {version} to {version + 1}.")
        version += 1

    raw_config = envelope.get("config")
    if not isinstance(raw_config, dict):
        raise ProjectFileError("Project file has no 'config' object.")

    config = _decode_dataclass(raw_config, AopsConfig)

    # Preserve envelope keys this build does not recognise, so that saving does
    # not silently discard data written by a newer version.
    known = {
        "format",
        "schema_version",
        "app_version",
        "created_utc",
        "modified_utc",
        "fingerprint",
        "config",
    }
    unknown = tuple(
        (key, json.dumps(value)) for key, value in sorted(envelope.items()) if key not in known
    )
    if unknown:
        config = dataclasses.replace(config, extra=unknown)
        warnings.append(
            f"Preserved {len(unknown)} unrecognised key(s) from a newer AOPS version."
        )

    return LoadedProject(config=config, schema_version=raw_version, warnings=tuple(warnings))
