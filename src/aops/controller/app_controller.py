"""The application controller.

Owns the pipeline that turns a configuration into everything the views display:

    config -> probe matrix -> derive geometry -> validate -> compose draw lists

Debouncing is the reason the UI stays responsive. Two mechanisms are needed and
neither is sufficient alone:

* Spin boxes have keyboard tracking disabled, so typing "25" never transiently
  applies a pitch of 2.
* A single shared timer coalesces bursts, so holding a spinner arrow recomputes
  once rather than thirty times.

The derivation is memoised on the frozen config, so undo and redo cost nothing.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, Signal

from aops.controller.config_store import ConfigStore
from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList
from aops.core.enums import Symbology
from aops.core.errors import AopsError
from aops.core.layout.overview import compose_overview
from aops.core.layout.preview import compose_preview
from aops.core.matrix import ModuleMatrix
from aops.core.project_io import config_fingerprint
from aops.core.rules import ALL_RULES
from aops.core.stats import DerivedGeometry, derive
from aops.core.validation import ValidationReport, run_rules
from aops.symbols.cache import SymbolCache, probe_matrix_cols
from aops.symbols.registry import build_registry

#: Coalescing window for parameter changes, in milliseconds.
DEBOUNCE_MS = 120

#: How many derived geometries to memoise. Enough that undo/redo is free.
DERIVATION_CACHE = 8

PREVIEW_SYMBOLS = 10


class AppController(QObject):
    """Recomputes derived state and publishes it to the views."""

    derivedChanged = Signal(object)  # DerivedGeometry | None
    validationChanged = Signal(object)  # ValidationReport
    previewChanged = Signal(object)  # DrawList
    overviewChanged = Signal(object)  # DrawList
    errorRaised = Signal(str)

    def __init__(self, store: ConfigStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._cache = SymbolCache(build_registry(store.config.symbol))
        self._derivations: OrderedDict[AopsConfig, DerivedGeometry] = OrderedDict()

        self._derived: DerivedGeometry | None = None
        self._report = ValidationReport()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.recompute)

        store.configChanged.connect(self._on_config_changed)

    # -- accessors ----------------------------------------------------------

    @property
    def cache(self) -> SymbolCache:
        return self._cache

    @property
    def derived(self) -> DerivedGeometry | None:
        return self._derived

    @property
    def report(self) -> ValidationReport:
        return self._report

    @property
    def fingerprint(self) -> str:
        return config_fingerprint(self._store.config)

    # -- pipeline -----------------------------------------------------------

    def _on_config_changed(self, config: AopsConfig, changed: frozenset[str]) -> None:
        # A new symbology or QR parameter needs a fresh encoder registry.
        if any(path.startswith("symbol.") for path in changed):
            self._cache = SymbolCache(build_registry(config.symbol))
        self._timer.start()

    def request_recompute(self) -> None:
        self._timer.start()

    def recompute(self) -> None:
        """Run the full pipeline and publish the results."""
        cfg = self._store.config

        cached = self._derivations.get(cfg)
        if cached is not None:
            self._derivations.move_to_end(cfg)
            derived: DerivedGeometry | None = cached
        else:
            try:
                sample = cfg.payload.prefix + "0" * max(cfg.payload.digits, 1) + cfg.payload.suffix
                cols = probe_matrix_cols(self._cache, cfg.symbol.symbology, sample)
                derived = derive(cfg, matrix_cols=cols)
                self._derivations[cfg] = derived
                while len(self._derivations) > DERIVATION_CACHE:
                    self._derivations.popitem(last=False)
            except AopsError:
                derived = None
            except Exception as exc:  # pragma: no cover - defensive
                self.errorRaised.emit(str(exc))
                derived = None

        self._derived = derived
        self.derivedChanged.emit(derived)

        self._report = run_rules(ALL_RULES, cfg, derived)
        self.validationChanged.emit(self._report)

        if derived is not None:
            self.previewChanged.emit(self._build_preview(cfg, derived))
            self.overviewChanged.emit(compose_overview(cfg, derived))
        else:
            self.previewChanged.emit(DrawList(10.0, 10.0, ()))
            self.overviewChanged.emit(DrawList(10.0, 10.0, ()))

    def _build_preview(self, cfg: AopsConfig, derived: DerivedGeometry) -> DrawList:
        """Encode only the handful of symbols the preview actually shows.

        This bound is the whole interactive performance strategy: the cost is
        independent of whether the strip has 40 codes or 5000.
        """
        matrices: dict[str, ModuleMatrix] = {}
        for payload in derived.payloads[:PREVIEW_SYMBOLS]:
            try:
                matrices[payload] = self._cache.get(cfg.symbol.symbology, payload)
            except AopsError:
                break  # unimplemented or unavailable; preview shows outlines
            except Exception:
                break
        return compose_preview(cfg, derived, matrices, max_symbols=PREVIEW_SYMBOLS)

    # -- helpers for the export path ----------------------------------------

    def encode_all(self, cfg: AopsConfig, derived: DerivedGeometry) -> dict[str, ModuleMatrix]:
        """Encode every payload. Called from the export worker, not the GUI thread."""
        symbology: Symbology = cfg.symbol.symbology
        return {p: self._cache.get(symbology, p) for p in dict.fromkeys(derived.payloads)}
