"""Scanner optics recommendations, derived from first principles.

No vendor datasheet figures are invented here. Every number is computed from
stated, user-editable assumptions, and those assumptions are printed alongside
the result so the engineer can check them against the reader they actually buy.

THE FIELD-OF-VIEW RESULT
------------------------
This is the single most important number the tool produces, and it is not
obvious. Codes of width ``S`` repeat with period ``P``. A camera window of width
``W`` fully contains code ``k`` exactly when

    k*P + m + S - W  <=  x  <=  k*P + m

which is an interval of length ``W - S`` repeating every ``P``. For at least
``N`` complete codes to be visible at *every* axis position, these intervals
must overlap ``N`` deep, which requires

    W  >=  N * P + S

At the default 25 mm pitch / 10 mm symbol that is **35 mm for N=1** - not the
~12 mm an engineer might guess from the symbol size. Below that threshold there
are blind zones where no complete code is in view and the machine loses absolute
position entirely.

Real industrial readers (e.g. Pepperl+Fuchs PXV) read three codes at once so the
tape can be damaged or obscured without losing position; at N=3 the requirement
rises to 85 mm. Choosing N also buys a stated occlusion tolerance of
``(N-1) * P`` millimetres of continuous damage.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, floor, radians, tan

from aops.core.cell import CellSpec
from aops.core.config import ScannerConfig


@dataclass(frozen=True, slots=True)
class ScannerRecommendation:
    """Computed optical requirements for reading the configured strip."""

    module_size_mm: float
    fov_continuous_mm: float  # N*P + S: gap-free absolute positioning
    fov_static_mm: float  # S + 2*qz: one code readable at rest
    occlusion_tolerance_mm: float  # (N-1)*P of continuous damage survivable
    required_sensor_px: int
    sensor_class: str
    working_distances: tuple[tuple[float, float], ...]  # (focal_mm, wd_mm)
    mount_height_mm: float
    notes: tuple[str, ...]
    #: Distance a reader of stated angular field of view must sit at to see
    #: `fov_continuous_mm`. Zero when no reader spec has been entered.
    required_wd_mm: float = 0.0
    #: Height of that reader's view at `required_wd_mm`. The code and both its
    #: quiet zones have to fit inside it, which is easy to overlook because the
    #: interesting constraint is nearly always the horizontal one.
    vertical_fov_mm: float = 0.0
    #: Pixels the stated sensor actually puts across one module at that
    #: distance, against `px_per_module` as the target.
    available_px_per_module: float = 0.0

    #: --- when a mounting distance is fixed, the budget it allows -----------
    #: Window the reader actually has at the chosen mounting distance.
    available_fov_mm: float = 0.0
    available_fov_v_mm: float = 0.0
    #: Available minus required. Negative means the geometry does not fit.
    fov_headroom_mm: float = 0.0
    #: Largest pitch that still fits, keeping the current code size.
    max_pitch_mm: float = 0.0
    #: Largest code that fits, if the pitch were reduced to its minimum.
    max_symbol_mm: float = 0.0

    @property
    def has_reader_spec(self) -> bool:
        return self.required_wd_mm > 0.0

    @property
    def distance_is_fixed(self) -> bool:
        return self.available_fov_mm > 0.0

    @property
    def fits_at_distance(self) -> bool:
        return self.fov_headroom_mm >= 0.0


def _floor_um(mm: float) -> float:
    """Round a suggested dimension down to the micrometre grid.

    These bounds are exact solutions to an inequality, so a geometry built from
    one sits precisely on the boundary. The cell model then rounds to whole
    micrometres, which can tip it a thousandth of a millimetre over and make
    the suggestion fail the very check it was meant to satisfy. Flooring first
    keeps a suggestion something that actually fits.
    """
    return floor(mm * 1000.0) / 1000.0


def _sensor_class(px: int) -> str:
    """Coarse sensor requirement, stated as a class rather than a product."""
    if px <= 640:
        return "VGA (640 x 480) sufficient"
    if px <= 1280:
        return ">= 1.3 MP (1280 x 1024)"
    if px <= 1600:
        return ">= 2 MP (1600 x 1200)"
    if px <= 2048:
        return ">= 3 MP (2048 x 1536)"
    return f">= {px} px across the field of view - consider reducing pitch"


def recommend(
    cell: CellSpec, matrix_cols: int, cfg: ScannerConfig
) -> ScannerRecommendation:
    """Compute optical requirements for the configured geometry.

    `matrix_cols` is the symbol's module count across, which sets the module
    size and therefore the resolution the sensor must deliver.
    """
    n = max(1, cfg.min_codes_in_view)
    module_mm = cell.module_mm(matrix_cols) if matrix_cols > 0 else 0.0

    fov_continuous = n * cell.pitch_mm + cell.symbol_mm
    fov_static = cell.symbol_mm + 2 * cell.quiet_zone_mm
    occlusion = (n - 1) * cell.pitch_mm

    # The sensor must resolve px_per_module across the whole field of view.
    if module_mm > 0:
        required_px = int(round(fov_continuous / module_mm * cfg.px_per_module))
    else:
        required_px = 0

    # Pinhole approximation: WD = FOV * f / sensor_width.
    working: list[tuple[float, float]] = []
    for focal in cfg.focal_lengths_mm:
        if cfg.sensor_width_mm > 0:
            working.append((focal, fov_continuous * focal / cfg.sensor_width_mm))

    # Mounting the head tilted off-normal avoids specular return from the tape;
    # the vertical drop is therefore shorter than the optical path.
    mid_wd = working[len(working) // 2][1] if working else 0.0
    mount_height = mid_wd * cos(radians(cfg.mount_tilt_deg))

    # With a stated angular field of view the mounting distance is exact rather
    # than estimated: a view of angle t is (2 tan(t/2)) wide per unit distance,
    # so the distance needed to span the required width follows directly.
    required_wd = 0.0
    vertical_fov = 0.0
    available_px = 0.0
    if cfg.has_reader_spec:
        spread = 2.0 * tan(radians(cfg.fov_angle_deg / 2.0))
        if spread > 0:
            required_wd = fov_continuous / spread
        if cfg.fov_vertical_deg > 0:
            vertical_fov = required_wd * 2.0 * tan(radians(cfg.fov_vertical_deg / 2.0))
        if cfg.sensor_px_h > 0 and fov_continuous > 0:
            available_px = cfg.sensor_px_h / fov_continuous * module_mm

    # A fixed mounting distance turns the calculation around: distance and view
    # angle fix the window, and the geometry has to fit inside it.
    avail_fov = avail_fov_v = headroom = max_pitch = max_symbol = 0.0
    if cfg.distance_is_fixed:
        wd = cfg.mount_distance_mm
        avail_fov = wd * 2.0 * tan(radians(cfg.fov_angle_deg / 2.0))
        if cfg.fov_vertical_deg > 0:
            avail_fov_v = wd * 2.0 * tan(radians(cfg.fov_vertical_deg / 2.0))
        headroom = avail_fov - fov_continuous

        # N*pitch + symbol <= window, solved for pitch with the code as given.
        max_pitch = _floor_um(max(0.0, (avail_fov - cell.symbol_mm) / n))

        # The largest code that fits at all, which is a different question: it
        # assumes the pitch drops to its own minimum of symbol + 2 quiet zones,
        # and a quiet zone is one module, so both scale with the code.
        #   window >= N*(S + 2*S/cols) + S  =>  S <= window / (N*(1 + 2/cols) + 1)
        if matrix_cols > 0:
            max_symbol = _floor_um(avail_fov / (n * (1.0 + 2.0 / matrix_cols) + 1.0))

    notes = (
        f"Assumes {cfg.px_per_module:.1f} pixels per module.",
        f"Assumes a {cfg.sensor_width_mm:.1f} mm wide sensor.",
        "Working distance from the pinhole relation WD = FOV x f / sensor width.",
        f"Mount height assumes a {cfg.mount_tilt_deg:.0f} deg tilt off normal to "
        f"avoid specular reflection.",
        "These are engineering estimates. Verify against the datasheet of the "
        "reader actually selected.",
    )

    return ScannerRecommendation(
        module_size_mm=module_mm,
        fov_continuous_mm=fov_continuous,
        fov_static_mm=fov_static,
        occlusion_tolerance_mm=occlusion,
        required_sensor_px=required_px,
        sensor_class=_sensor_class(required_px),
        working_distances=tuple(working),
        mount_height_mm=mount_height,
        notes=notes,
        required_wd_mm=required_wd,
        vertical_fov_mm=vertical_fov,
        available_px_per_module=available_px,
        available_fov_mm=avail_fov,
        available_fov_v_mm=avail_fov_v,
        fov_headroom_mm=headroom,
        max_pitch_mm=max_pitch,
        max_symbol_mm=max_symbol,
    )
