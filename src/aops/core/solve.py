"""Design the strip from the job, instead of asking for the strip.

Eighty-six settings describe a finished strip. But the person making one does
not know eighty-six things - they know perhaps eight: which machine, how far it
travels, how fast, where the reader bracket is, and which devices they bought.
Everything else is a *consequence* of those facts, and a consequence the
software can compute is a question the user should never have been asked.

This module is that computation. Given the job, it derives the geometry:

    module size   = the largest of three floors, then snapped to the dot grid
                      - the printer needs >= 5 dots per module to print cleanly
                      - the scanner needs >= 5 pixels per module at the
                        mounting distance to resolve it
                      - motion needs the module to outrun the smear at a
                        usable exposure
    symbol        = module x matrix columns
    quiet zone    = the symbology's own rule (1 module for Data Matrix)
    pitch         = symbol + quiet zones + cutting tolerance, rounded up to a
                    clean number, checked against the reader's window
    exposure      = module / speed  (the vendor's formula, rearranged)
    end index     = from the travel
    digits        = from the largest position

Every derived value carries a sentence saying which constraint decided it,
because a number that appears without a reason teaches nobody anything and
cannot be argued with.

WHAT THIS DELIBERATELY IS NOT
-----------------------------
It is not a second validator. The solver *proposes*; the existing rule engine
then judges the proposal with the same ~70 rules it applies to hand-entered
configurations, and a property test asserts the proposals come out clean
across the whole grid of speeds, distances and printers. Solver and validator
reaching the same geometry independently is the check - the same philosophy as
the splice guarantee, which is re-derived at export rather than trusted.

It also refuses to guess what it cannot know. The mounting distance is set by
a bracket, the calibration factor by a measurement on real paper; both remain
inputs. And where the job is genuinely infeasible - a speed no exposure can
freeze, a window too small for the redundancy asked of it - the solver says so
in `problems` rather than delivering a config that quietly fails validation.
"""

from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from math import ceil, floor, radians, tan

from aops.core.cell import MIN_MODULE_UM, resolve_cell
from aops.core.config import AopsConfig
from aops.core.dotgrid import symbol_mm_for_dots
from aops.core.enums import Symbology
from aops.core.media import max_calibration_length_mm
from aops.core.motion import EXPOSURE_MIN_US, frame_limited_speed
from aops.core.payload import required_digits
from aops.core.positions import end_index_for_travel
from aops.core.units import mm_per_dot

#: Dots per module the solver designs for. The printable minimum is 3; five is
#: the comfortable industrial target the validation rules already praise.
DESIGN_MODULE_DOTS: int = 5

#: Pixels per module the reader should get. Matches ScannerConfig's default.
DESIGN_PX_PER_MODULE: float = 5.0

#: Exposure the solver designs the module around when the axis moves. Longer
#: than the 60 us floor by a wide margin, because an exposure at the floor has
#: no headroom for the lighting to be less than perfect. At 500 us the module
#: comes out large enough that the final exposure lands at or above this.
COMFORT_EXPOSURE_US: int = 500

#: Ceiling on the exposure the solver will set. The NVF230 accepts up to
#: 60000 us, but past a few milliseconds ambient vibration blurs the image as
#: surely as travel does, so the solver never designs above the reader default.
EXPOSURE_MAX_SAFE_US: int = 1_000

#: Total white the guillotine gets at each cell boundary - the gap between the
#: ink of two adjacent codes, quiet zones included. 3 mm is rule GEO-013's own
#: floor: 1.5 mm of cutting tolerance each side. Counting the quiet zones in,
#: rather than adding this on top of them, matches the rule exactly - the first
#: version added it on top and so demanded a 15 mm pitch where the validator
#: itself was happy with 10, producing a clumsier position formula for no
#: safety the checker recognised.
CUT_TOLERANCE_MM: float = 3.0

#: Pitches are rounded up to a multiple of this. "Codes every 15 mm" is a
#: number a commissioning engineer can carry in their head and type into a PLC
#: comment; "codes every 13.7 mm" is not.
PITCH_STEP_MM: float = 5.0

#: Vertical clearance added above and below the symbol band for the printed
#: index text and general margin, before rounding the strip height up.
HEIGHT_ALLOWANCE_MM: float = 8.0

#: Quiet zone each symbology mandates, in modules. Data Matrix specifies one;
#: QR specifies four. Mirrors the table the validation rules use.
QUIET_MODULES: dict[Symbology, int] = {Symbology.DATA_MATRIX: 1, Symbology.QR: 4}


@dataclass(frozen=True, slots=True)
class Decision:
    """One derived value and the sentence that justifies it."""

    field: str  #: dotted config path
    value: object
    reason: str


@dataclass(frozen=True, slots=True)
class Solution:
    """A proposed configuration, its reasoning, and anything infeasible.

    `problems` non-empty means the job as stated cannot be fully satisfied.
    The config is still the best available proposal - the validator will flag
    the same problems on it, with the fields to change.
    """

    config: AopsConfig
    decisions: tuple[Decision, ...]
    problems: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.problems


def _fov_at(cfg: AopsConfig, distance_mm: float) -> tuple[float, float]:
    """Reader window (horizontal, vertical) at a distance, from its angles."""
    scn = cfg.scanner
    if distance_mm <= 0.0 or scn.fov_angle_deg <= 0.0:
        return 0.0, 0.0
    h = 2.0 * distance_mm * tan(radians(scn.fov_angle_deg / 2.0))
    v = (
        2.0 * distance_mm * tan(radians(scn.fov_vertical_deg / 2.0))
        if scn.fov_vertical_deg > 0.0
        else 0.0
    )
    return h, v


def _round_up_mm(value: float, step: float) -> float:
    """Round a dimension up to the next multiple of `step`."""
    return ceil(value / step - 1e-9) * step


def solve(
    base: AopsConfig,
    *,
    travel_mm: float,
    matrix_cols: int = 10,
) -> Solution:
    """Derive the strip geometry from the job described by `base`.

    The job inputs are read from the configuration itself - axis speed,
    mounting distance, redundancy and reader optics from `scanner`, resolution
    from `printer` - because that is where the device presets already put them.
    `travel_mm` comes in separately: travel is not a stored field, it is the
    question the index range answers.

    Everything untouched by the derivation (project identity, media, output
    style, calibration) passes through from `base` unchanged.
    """
    scn = base.scanner
    dpi = base.printer.dpi
    decisions: list[Decision] = []
    problems: list[str] = []

    # -- module size: three floors, loudest wins ---------------------------
    floors: list[tuple[float, str]] = []

    if dpi > 0:
        print_floor = DESIGN_MODULE_DOTS * mm_per_dot(dpi)
        floors.append((
            print_floor,
            f"the printer: {DESIGN_MODULE_DOTS} dots per module at {dpi} dpi "
            f"is {print_floor:.3f} mm",
        ))

    fov_h, fov_v = _fov_at(base, scn.mount_distance_mm)
    if fov_h > 0.0 and scn.sensor_px_h > 0:
        mm_per_px = fov_h / scn.sensor_px_h
        scan_floor = DESIGN_PX_PER_MODULE * mm_per_px
        floors.append((
            scan_floor,
            f"the reader: {DESIGN_PX_PER_MODULE:.0f} pixels per module at "
            f"{scn.mount_distance_mm:.0f} mm ({mm_per_px * 1000:.0f} um/pixel) "
            f"is {scan_floor:.3f} mm",
        ))

    if scn.reads_in_motion:
        motion_floor = scn.axis_speed_mm_per_s * (COMFORT_EXPOSURE_US / 1e6)
        floors.append((
            motion_floor,
            f"motion: {scn.axis_speed_mm_per_s:.0f} mm/s smears "
            f"{motion_floor:.3f} mm during a {COMFORT_EXPOSURE_US} us exposure",
        ))

    floors.append((
        MIN_MODULE_UM / 1000.0,
        f"the practical printing floor of {MIN_MODULE_UM / 1000.0:.2f} mm",
    ))

    module_mm, binding = max(floors, key=lambda f: f[0])

    # -- snap the symbol up to the dot grid --------------------------------
    if dpi > 0:
        dots = max(1, ceil(module_mm / mm_per_dot(dpi) - 1e-9))
        symbol_mm = symbol_mm_for_dots(dots, matrix_cols, dpi)
        grid_note = f", snapped up to {dots} whole printer dots"
    else:
        symbol_mm = module_mm * matrix_cols
        grid_note = ""
    # Stored at three decimals like every other authored dimension - but
    # rounded UP, not to nearest. Round-to-nearest can shave half a thousandth
    # off, and a symbol stored a hair below "five dots per module" fails the
    # very floor it was designed to sit on.
    symbol_mm = ceil(symbol_mm * 1000.0 - 1e-9) / 1000.0
    module_mm = symbol_mm / matrix_cols
    decisions.append(Decision(
        "dimensions.symbol_size_mm", round(symbol_mm, 3),
        f"Code size {symbol_mm:.3f} mm: the binding constraint was {binding}"
        f"{grid_note}. {matrix_cols} modules across.",
    ))

    # -- quiet zone: the symbology's own rule ------------------------------
    quiet_modules = QUIET_MODULES.get(base.symbol.symbology, 1)
    quiet_mm = _round_up_mm(quiet_modules * module_mm, 0.1)
    decisions.append(Decision(
        "dimensions.quiet_zone_mm", round(quiet_mm, 3),
        f"Quiet zone {quiet_mm:.1f} mm: {base.symbol.symbology.display_name} "
        f"mandates {quiet_modules} module(s) of clear border.",
    ))

    # -- pitch: as fine as the splice allows, in clean numbers -------------
    # The white gap between two codes must hold the larger of the quiet zones
    # and the guillotine's tolerance - not their sum. A cut may wander into
    # quiet-zone *territory* so long as the code keeps its quiet width of
    # white to the new edge, which is exactly how rule GEO-013 counts it.
    pitch_floor = symbol_mm + max(2.0 * quiet_mm, CUT_TOLERANCE_MM)
    pitch_mm = _round_up_mm(pitch_floor, PITCH_STEP_MM)
    decisions.append(Decision(
        "dimensions.pitch_mm", round(pitch_mm, 3),
        f"Code spacing {pitch_mm:.0f} mm: the code plus a {CUT_TOLERANCE_MM:.0f} mm "
        f"white gap for quiet zones and cutting needs {pitch_floor:.1f} mm, "
        f"rounded up to a clean multiple of {PITCH_STEP_MM:.0f} so the position "
        f"formula stays a number to carry in your head.",
    ))

    # -- does the redundancy asked for fit the window? ---------------------
    n = max(1, scn.min_codes_in_view)
    if fov_h > 0.0:
        needed = n * pitch_mm + symbol_mm
        if needed > fov_h:
            problems.append(
                f"At {scn.mount_distance_mm:.0f} mm the reader sees "
                f"{fov_h:.0f} mm, but {n} code(s) in view needs {needed:.0f} mm. "
                f"Mount further back, or reduce the codes-in-view requirement."
            )

    # -- strip height ------------------------------------------------------
    height_mm = _round_up_mm(
        symbol_mm + 2.0 * quiet_mm + HEIGHT_ALLOWANCE_MM, PITCH_STEP_MM
    )
    if fov_v > 0.0 and height_mm > fov_v:
        # The reader's vertical window bounds what it can see, not what can be
        # printed - but a band taller than the window is wasted tape.
        height_mm = max(
            _round_up_mm(symbol_mm + 2.0 * quiet_mm, 1.0),
            floor(fov_v),
        )
    decisions.append(Decision(
        "dimensions.strip_height_mm", round(height_mm, 3),
        f"Strip height {height_mm:.0f} mm: code plus borders plus room for the "
        f"printed index text.",
    ))

    # -- index range from the travel ---------------------------------------
    dims = dc.replace(
        base.dimensions,
        pitch_mm=round(pitch_mm, 3),
        symbol_size_mm=round(symbol_mm, 3),
        quiet_zone_mm=round(quiet_mm, 3),
        strip_height_mm=round(height_mm, 3),
    )
    cell = resolve_cell(dims)
    pos = dc.replace(base.position, end_index=base.position.start_index)
    end_index = end_index_for_travel(travel_mm, pos, cell)
    pos = dc.replace(pos, end_index=end_index)
    decisions.append(Decision(
        "position.end_index", end_index,
        f"End index {end_index}: covers {travel_mm:.0f} mm of travel at "
        f"{pitch_mm:.0f} mm per code, rounded up so the end of the axis "
        f"stays coded.",
    ))

    # -- payload digits from the largest position --------------------------
    digits = required_digits(pos, cell, base.payload)
    decisions.append(Decision(
        "payload.digits", digits,
        f"{digits} digits: enough for the largest position on the strip.",
    ))

    # -- exposure from the module and the speed ----------------------------
    scanner = scn
    if scn.reads_in_motion:
        exposure_us = int(
            min(module_mm / scn.axis_speed_mm_per_s * 1e6, EXPOSURE_MAX_SAFE_US)
        )
        if exposure_us < EXPOSURE_MIN_US:
            problems.append(
                f"No exposure freezes {scn.axis_speed_mm_per_s:.0f} mm/s at this "
                f"module size - the reader's floor is {EXPOSURE_MIN_US} us. "
                f"Slow the axis or accept a larger code."
            )
            exposure_us = EXPOSURE_MIN_US
        scanner = dc.replace(scanner, exposure_us=exposure_us)
        decisions.append(Decision(
            "scanner.exposure_us", exposure_us,
            f"Exposure {exposure_us} us: the longest that keeps motion smear "
            f"within one module at {scn.axis_speed_mm_per_s:.0f} mm/s.",
        ))

        # The frame-rate ceiling depends on nothing the solver can change
        # except the window, so it is checked rather than designed around.
        if fov_h > 0.0:
            frame_limit = frame_limited_speed(
                fov_h, max(1, scn.frames_per_code), scn.frame_interval_ms
            )
            if 0.0 < frame_limit < scn.axis_speed_mm_per_s:
                problems.append(
                    f"At {scn.axis_speed_mm_per_s:.0f} mm/s a code cannot be "
                    f"caught in {scn.frames_per_code} frame(s) - the reader's "
                    f"frame rate caps this window at {frame_limit:.0f} mm/s. "
                    f"Mount further back or slow the axis."
                )

    # -- calibration bar: as long as the sheet allows ----------------------
    printing = base.printing
    if base.output.calibration_bar:
        bar = max_calibration_length_mm(
            base.paper.usable_width_mm(), base.printing.scale_factor
        )
        if bar > 0 and abs(bar - printing.calibration_length_mm) > 1e-9:
            printing = dc.replace(printing, calibration_length_mm=bar)
            decisions.append(Decision(
                "printing.calibration_length_mm", bar,
                f"Calibration bar {bar:.0f} mm: the longest whole-centimetre bar "
                f"this sheet carries. Its length is the calibration's accuracy - "
                f"measured to 0.5 mm, the residual is {0.5 / bar * 100:.2f}%.",
            ))

    config = dc.replace(
        base,
        dimensions=dims,
        position=pos,
        payload=dc.replace(base.payload, digits=digits),
        scanner=scanner,
        printing=printing,
    )
    return Solution(config=config, decisions=tuple(decisions), problems=tuple(problems))
