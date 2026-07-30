"""The configuration model.

Every dataclass here is ``frozen=True, slots=True``. That is a design decision
with four separate payoffs:

1. **Hashable** - the whole pure pipeline (resolve -> paginate -> compose) can be
   memoised on the config itself, so undo/redo costs no recomputation.
2. **Safe to hand to a worker thread** - an export snapshot is a free reference
   with no aliasing risk, because nothing can mutate it mid-export.
3. **Undo/redo for free** - `dataclasses.replace` produces the next state.
4. **No global mutable state** - the config lives in exactly one place
   (`controller.config_store.ConfigStore`) and is passed down explicitly.

Unit convention: every ``float`` field carries a unit suffix (``_mm``, ``_pt``,
``_percent``, ``_deg``, ``_deg_c``). This is enforced by a test, not by
convention alone - see ``test_every_float_field_carries_a_unit_suffix`` in
``tests/core/test_config_and_rules.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aops.core.enums import (
    ContinuousStrategy,
    Datum,
    Direction,
    FrameMaterial,
    HrPosition,
    LrMarginMode,
    Media,
    Orientation,
    PageScope,
    PaperPreset,
    PayloadSource,
    PitchMode,
    PrintMethod,
    QrEcc,
    Ribbon,
    RulerPosition,
    SpliceMode,
    Symbology,
    TapeMounting,
    VerifyMode,
)


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    """Which symbology to encode with, and its symbology-specific options."""

    symbology: Symbology = Symbology.DATA_MATRIX
    qr_ecc: QrEcc = QrEcc.M
    qr_version: int = 0  # 0 = automatic


@dataclass(frozen=True, slots=True)
class PositionConfig:
    """The index range and how indices map to machine positions."""

    start_index: int = 0
    end_index: int = 420
    increment: int = 1
    pitch_mode: PitchMode = PitchMode.PER_CELL
    direction: Direction = Direction.FORWARD
    origin_mm: float = 0.0
    datum: Datum = Datum.SYMBOL_CENTRE


@dataclass(frozen=True, slots=True)
class PayloadConfig:
    """What each symbol encodes.

    ``unit_scale`` exists because a fractional pitch (12.5 mm, say) makes an
    integer-millimetre payload lossy. Encoding in tenths or hundredths of a
    millimetre keeps the payload an integer, which PLCs parse far more happily
    than a decimal string.

    ``digits`` is validated against the maximum *position*, not the maximum
    index - encoding 10500 needs five digits even if the largest index is 420.
    """

    source: PayloadSource = PayloadSource.POSITION_MM
    unit_scale: int = 1  # 1 = mm, 10 = 0.1 mm, 100 = 0.01 mm
    digits: int = 6
    prefix: str = ""
    suffix: str = ""


@dataclass(frozen=True, slots=True)
class DimensionConfig:
    """Physical geometry of one cell and of the strip band.

    ``margin_lr_mm`` is authoritative only when
    ``lr_margin_mode is LrMarginMode.DRIVES_PITCH``; otherwise it is derived as
    ``(pitch - symbol) / 2`` and shown read-only.
    """

    pitch_mm: float = 25.0
    symbol_size_mm: float = 10.0
    quiet_zone_mm: float = 1.0
    strip_height_mm: float = 40.0
    lr_margin_mode: LrMarginMode = LrMarginMode.DERIVED_FROM_PITCH
    margin_lr_mm: float = 7.5
    symbol_v_offset_mm: float = 0.0


@dataclass(frozen=True, slots=True)
class OutputConfig:
    """Which artefacts to emit and which optional page furniture to include."""

    tiled_pages: bool = True
    continuous: bool = False
    continuous_strategy: ContinuousStrategy = ContinuousStrategy.USER_UNIT
    continuous_max_length_mm: float = 5000.0
    instruction_page: bool = True
    calibration_bar: bool = True
    calibration_scope: PageScope = PageScope.EVERY_PAGE
    #: Title band above the strip and the identification band below it. Off for
    #: a plain artwork print; on whenever the sheet has to be traceable.
    page_header_footer: bool = True
    engineering_ruler: bool = True
    ruler_position: RulerPosition = RulerPosition.BELOW
    human_readable: bool = True
    hr_position: HrPosition = HrPosition.BELOW
    hr_font_pt: float = 7.0
    verify_mode: VerifyMode = VerifyMode.SAMPLE
    verify_sample_count: int = 16


@dataclass(frozen=True, slots=True)
class PaperConfig:
    """Sheet size, orientation and non-printing margins."""

    preset: PaperPreset = PaperPreset.A4
    orientation: Orientation = Orientation.LANDSCAPE
    custom_width_mm: float = 297.0
    custom_height_mm: float = 210.0
    margin_top_mm: float = 10.0
    margin_bottom_mm: float = 10.0
    margin_left_mm: float = 10.0
    margin_right_mm: float = 10.0

    def sheet_size_mm(self) -> tuple[float, float]:
        """Return (width, height) in mm honouring preset and orientation."""
        if self.preset is PaperPreset.CUSTOM:
            width, height = self.custom_width_mm, self.custom_height_mm
        else:
            width, height = self.preset.portrait_mm
        if self.orientation is Orientation.LANDSCAPE:
            width, height = max(width, height), min(width, height)
        else:
            width, height = min(width, height), max(width, height)
        return width, height

    def usable_width_mm(self) -> float:
        return self.sheet_size_mm()[0] - self.margin_left_mm - self.margin_right_mm

    def usable_height_mm(self) -> float:
        return self.sheet_size_mm()[1] - self.margin_top_mm - self.margin_bottom_mm


@dataclass(frozen=True, slots=True)
class PrintConfig:
    """Print-time compensation and registration furniture.

    ``scale_percent`` multiplies *all* emitted artwork including the calibration
    bar, which is what closes the calibration loop: print at 100 %, measure the
    bar, set the scale to ``200 / measured * 100``, and reprint.
    """

    scale_percent: float = 100.0
    calibration_length_mm: float = 200.0
    leading_margin_mm: float = 20.0
    trailing_margin_mm: float = 20.0
    registration_marks: bool = True
    registration_mark_size_mm: float = 5.0
    cut_marks: bool = True
    cut_mark_length_mm: float = 4.0
    #: Off by default: ink drawn across the strip band confuses a scanner.
    cut_line_across_strip: bool = False
    alignment_arrows: bool = True
    splice_mode: SpliceMode = SpliceMode.BUTT
    splice_overlap_mm: float = 0.0

    @property
    def scale_factor(self) -> float:
        return self.scale_percent / 100.0


@dataclass(frozen=True, slots=True)
class MediaConfig:
    """Substrate, process and mounting. Dominates 1:1 accuracy and service life.

    ``dim_stability_pct_per_rh`` and ``cte_ppm_per_c`` default to 0.0 meaning
    "take the published figure for the selected media"; a non-zero value
    overrides it with a measured one from the media datasheet.

    ``frame_material`` and ``mounting`` are properties of the *machine*, not of
    the media, but they live here because they are inseparable from the media
    question: only the difference between substrate and frame expansion reaches
    the position reading, and the mounting decides whether it reaches it at all.
    """

    media: Media = Media.POLYESTER
    method: PrintMethod = PrintMethod.THERMAL_TRANSFER
    ribbon: Ribbon = Ribbon.RESIN
    adhesive_backed: bool = True
    rh_swing_percent: float = 40.0
    dim_stability_pct_per_rh: float = 0.0
    temp_swing_deg_c: float = 30.0
    frame_material: FrameMaterial = FrameMaterial.STEEL
    mounting: TapeMounting = TapeMounting.CONTINUOUS_BOND
    cte_ppm_per_c: float = 0.0

    @property
    def effective_stability_pct_per_rh(self) -> float:
        """User override if set, otherwise the published figure for the media."""
        if self.dim_stability_pct_per_rh > 0.0:
            return self.dim_stability_pct_per_rh
        return self.media.dim_stability_pct_per_rh

    @property
    def effective_cte_ppm_per_c(self) -> float:
        """User override if set, otherwise the published figure for the media."""
        if self.cte_ppm_per_c > 0.0:
            return self.cte_ppm_per_c
        return self.media.cte_ppm_per_c

    @property
    def cte_mismatch_ppm_per_c(self) -> float:
        """Substrate CTE minus frame CTE. Signed: positive means the tape grows faster."""
        return self.effective_cte_ppm_per_c - self.frame_material.cte_ppm_per_c


@dataclass(frozen=True, slots=True)
class PrinterConfig:
    """Output device characteristics.

    ``measured_calibration_mm`` is what the operator physically measured on the
    printed calibration bar. The UI derives ``PrintConfig.scale_percent`` from
    it so nobody has to do the arithmetic by hand.
    """

    dpi: int = 600
    unprintable_margin_mm: float = 5.0
    measured_calibration_mm: float = 200.0

    def derived_scale_percent(self, nominal_mm: float) -> float:
        """Scale percentage that would make a bar measuring `measured` come out at `nominal`."""
        if self.measured_calibration_mm <= 0.0:
            return 100.0
        return nominal_mm / self.measured_calibration_mm * 100.0


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    """Reader optics and redundancy requirements.

    ``min_codes_in_view`` is the number of *complete* codes that must be visible
    at every axis position. Real industrial heads (e.g. Pepperl+Fuchs PXV) read
    three at once so the tape can be damaged or obscured without losing
    position. It drives the required field of view: ``W >= N * pitch + symbol``.
    """

    min_codes_in_view: int = 1
    px_per_module: float = 5.0
    sensor_width_mm: float = 4.8  # 1/3" sensor
    focal_lengths_mm: tuple[float, ...] = (6.0, 8.0, 12.0, 16.0, 25.0)
    mount_tilt_deg: float = 12.0  # tilt away from specular return

    #: Figures from a specific reader's datasheet. All default to 0 meaning
    #: "not stated", which leaves the generic lens estimate above in charge.
    #: Filling them in replaces the estimate with the real thing: a datasheet
    #: quotes an angular field of view, from which the mounting distance
    #: follows exactly, rather than being inferred from an assumed sensor size.
    fov_angle_deg: float = 0.0
    fov_vertical_deg: float = 0.0
    #: The reader's focus window - the range over which it can resolve at all.
    dof_min_mm: float = 0.0
    dof_max_mm: float = 0.0
    #: Pixels across the sensor's long axis.
    sensor_px_h: int = 0

    #: Where the reader can actually be mounted, in mm. Zero means "wherever
    #: the geometry needs", which is how the tool worked originally: pick a
    #: pitch and a code size, and it reports the distance those demand.
    #:
    #: On a real machine that is backwards. The distance is set by a bracket, a
    #: guard or a clearance, and is not negotiable - so setting it here inverts
    #: the calculation. The distance and the reader's view angle together fix
    #: how much window is available, and the geometry then has to fit inside
    #: that budget rather than dictate it.
    mount_distance_mm: float = 0.0

    @property
    def has_reader_spec(self) -> bool:
        """True once a real reader's field of view has been entered."""
        return self.fov_angle_deg > 0.0

    @property
    def distance_is_fixed(self) -> bool:
        """True when a mounting distance constrains the geometry."""
        return self.has_reader_spec and self.mount_distance_mm > 0.0


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Traceability metadata printed on every page."""

    machine: str = ""
    project: str = ""
    strip_id: str = ""
    revision: str = "A"
    engineer: str = ""
    company: str = ""
    comments: str = ""


@dataclass(frozen=True, slots=True)
class AopsConfig:
    """Root configuration aggregate.

    ``extra`` preserves keys written by a newer version of AOPS so that opening
    and re-saving a file in an older build does not silently destroy data.
    """

    symbol: SymbolConfig = field(default_factory=SymbolConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    payload: PayloadConfig = field(default_factory=PayloadConfig)
    dimensions: DimensionConfig = field(default_factory=DimensionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    printing: PrintConfig = field(default_factory=PrintConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    printer: PrinterConfig = field(default_factory=PrinterConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    extra: tuple[tuple[str, str], ...] = ()


#: Section attribute names on `AopsConfig`, in the order the UI presents them.
CONFIG_SECTIONS: tuple[str, ...] = (
    "symbol",
    "position",
    "payload",
    "dimensions",
    "output",
    "paper",
    "printing",
    "media",
    "printer",
    "scanner",
    "project",
)
