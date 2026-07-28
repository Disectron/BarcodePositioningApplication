"""Compatibility shim for pylibdmtx on Python 3.12+.

pylibdmtx 0.1.10 does ``from distutils.version import LooseVersion`` at import
time. distutils was removed from the standard library in Python 3.12 (PEP 632),
so that import raises ``ModuleNotFoundError`` and the entire Data Matrix path
dies before it starts. AOPS targets Python 3.12+ and depends on pylibdmtx, so
one of the two has to give.

Installing a minimal shim into ``sys.modules`` before pylibdmtx is imported
fixes it in about fifteen lines. The alternative - depending on setuptools for
its bundled ``_distutils_hack`` - works today but rests on a deprecated
mechanism that setuptools has already signalled it intends to drop.

pylibdmtx uses ``LooseVersion`` for exactly one thing: comparing the libdmtx
version string against a minimum. So the shim only needs ordering comparisons.

This is the **only** module-level mutation of interpreter state in the codebase.
It is idempotent, sentinel-guarded, will not clobber a real distutils if one is
present, and is confined to this file.
"""

from __future__ import annotations

import sys
import types
from typing import Any

_SENTINEL = "_aops_distutils_shim"


class _LooseVersion:
    """Minimal stand-in for `distutils.version.LooseVersion`.

    Parses the leading numeric components of a version string and compares them
    element-wise, which is all pylibdmtx's ">= minimum version" check needs.
    """

    __slots__ = ("vstring", "version")

    def __init__(self, vstring: str = "") -> None:
        self.vstring = str(vstring)
        parts: list[int] = []
        for chunk in self.vstring.replace("-", ".").split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            if not digits:
                break
            parts.append(int(digits))
        self.version = parts

    def _cmp_key(self, other: Any) -> list[int]:
        if isinstance(other, _LooseVersion):
            return other.version
        return _LooseVersion(str(other)).version

    def __str__(self) -> str:
        return self.vstring

    def __repr__(self) -> str:
        return f"LooseVersion('{self.vstring}')"

    def __eq__(self, other: object) -> bool:
        return self.version == self._cmp_key(other)

    def __lt__(self, other: Any) -> bool:
        return self.version < self._cmp_key(other)

    def __le__(self, other: Any) -> bool:
        return self.version <= self._cmp_key(other)

    def __gt__(self, other: Any) -> bool:
        return self.version > self._cmp_key(other)

    def __ge__(self, other: Any) -> bool:
        return self.version >= self._cmp_key(other)

    def __hash__(self) -> int:
        return hash(tuple(self.version))


def install_distutils_shim() -> bool:
    """Ensure ``distutils.version.LooseVersion`` is importable.

    Returns True if this call installed the shim, False if it was unnecessary
    (a real distutils is present, or the shim was already installed).

    Safe to call any number of times, from any module.
    """
    if getattr(sys.modules.get("distutils"), _SENTINEL, False):
        return False

    try:  # A real distutils (Python <= 3.11, or a setuptools shim) - leave it alone.
        import distutils.version  # noqa: F401

        return False
    except ImportError:
        pass

    distutils_mod = types.ModuleType("distutils")
    version_mod = types.ModuleType("distutils.version")

    version_mod.LooseVersion = _LooseVersion  # type: ignore[attr-defined]
    version_mod.StrictVersion = _LooseVersion  # type: ignore[attr-defined]
    distutils_mod.version = version_mod  # type: ignore[attr-defined]
    setattr(distutils_mod, _SENTINEL, True)

    sys.modules["distutils"] = distutils_mod
    sys.modules["distutils.version"] = version_mod
    return True
