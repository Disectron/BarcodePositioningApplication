"""Installation-guide copy, held as data rather than embedded in layout code.

Everything here is generated from the actual configuration, so the guide can
never describe a strip other than the one printed behind it.
"""

from __future__ import annotations

from aops.core.config import AopsConfig
from aops.core.media import durability_advice
from aops.core.stats import DerivedGeometry

#: Print-settings checklist. Wrong scaling is the single most common cause of a
#: barcode coming out the wrong size, so this is item one.
PRINT_CHECKLIST: tuple[str, ...] = (
    "Set print scale to EXACTLY 100 % (or 'Actual Size'). This is the most common failure.",
    "Turn OFF 'Fit to Page', 'Shrink oversized pages' and 'Scale to fit media'.",
    "Turn OFF any 'Print as image' downsampling; this strip is vector artwork.",
    "Match the driver resolution to the resolution stated below.",
    "Print one proof sheet and measure the calibration bar before printing the run.",
    "Use the same printer, driver and media for every sheet of the run.",
)

CALIBRATION_STEPS: tuple[str, ...] = (
    "Print page 2 (the first strip sheet) at 100 % scale.",
    "Measure the calibration bar end-to-end with a steel rule. Do not use a tape measure.",
    "If it measures exactly the nominal length, no correction is needed.",
    "Otherwise set Printer Scaling = nominal / measured x 100 % in AOPS and re-export.",
    "Re-print and re-measure. The bar must be correct before printing the full run.",
)

VERIFICATION_STEPS: tuple[str, ...] = (
    "Verify print quality to ISO/IEC 15415; target grade A or B.",
    "Check that every symbol decodes with the production reader, not a phone.",
    "Confirm the first and last code on each sheet match the printed code range.",
    "Confirm the configuration fingerprint on each sheet matches the project file.",
)


def mounting_steps(cfg: AopsConfig, derived: DerivedGeometry) -> tuple[str, ...]:
    """Installation sequence, built around datum alignment.

    The critical instruction is step 3. Butting tiles against one another makes
    a systematic scale error accumulate along the whole strip; aligning each
    tile to its own printed absolute position bounds the error at one tile.
    """
    acc = derived.accuracy
    return (
        "Clean the mounting surface with isopropyl alcohol and let it dry fully.",
        "Establish the machine datum (position 0.000 mm) and mark it clearly on the rail.",
        "ALIGN EACH TILE TO ITS PRINTED ABSOLUTE POSITION WITH A STEEL TAPE. "
        "Do NOT butt tiles against each other.",
        f"Butt-splicing would accumulate up to {acc.cumulative_error_mm:.1f} mm over "
        f"{acc.strip_length_mm / 1000:.3f} m; datum alignment bounds the error at "
        f"{acc.bounded_error_mm:.2f} mm per tile.",
        "Each sheet footer prints the absolute X range of that tile - use the leading "
        "edge value as the alignment target.",
        "Apply from one end, squeegeeing forward, so no air is trapped and the strip "
        "is not stretched lengthwise.",
        "Keep the strip straight and parallel to the axis of travel within the "
        "reader's stated Y tolerance.",
        "Leave a deliberate gap at any rail expansion joint; never bridge one with "
        "a continuous strip.",
    )


def scanner_notes(cfg: AopsConfig, derived: DerivedGeometry) -> tuple[str, ...]:
    """Reader selection and mounting guidance, derived from the geometry."""
    rec = derived.scanner
    n = max(1, cfg.scanner.min_codes_in_view)
    lines = [
        f"Required field of view: {rec.fov_continuous_mm:.1f} mm "
        f"({n} x pitch + symbol). Below this there are blind zones in which no "
        f"complete code is visible and absolute position is lost.",
        f"Static read window (one code at rest): {rec.fov_static_mm:.1f} mm.",
        f"Module size: {rec.module_size_mm:.3f} mm. Sensor: {rec.sensor_class} "
        f"(about {rec.required_sensor_px} px across the field of view).",
    ]
    if rec.occlusion_tolerance_mm > 0:
        lines.append(
            f"Reading {n} codes at once tolerates {rec.occlusion_tolerance_mm:.0f} mm "
            f"of continuous tape damage or obscuration without loss of position."
        )
    if rec.working_distances:
        table = ", ".join(f"f={f:.0f} mm -> {w:.0f} mm" for f, w in rec.working_distances)
        lines.append(f"Working distance by lens: {table}.")
        lines.append(
            f"Suggested mount height {rec.mount_height_mm:.0f} mm at "
            f"{cfg.scanner.mount_tilt_deg:.0f} deg tilt off normal, to avoid specular return."
        )
    lines.extend(rec.notes)
    return tuple(lines)


def media_notes(cfg: AopsConfig, derived: DerivedGeometry) -> tuple[str, ...]:
    """Substrate guidance including the predicted humidity movement."""
    acc = derived.accuracy
    lines = [
        f"Media: {cfg.media.media.display_name}, printed by "
        f"{cfg.media.method.display_name}.",
        f"Predicted substrate movement: {acc.media_drift_mm:.2f} mm over "
        f"{acc.strip_length_mm / 1000:.3f} m across a "
        f"{cfg.media.rh_swing_percent:.0f} % humidity swing.",
        f"One symbol module spans {acc.module_dots:.1f} printer dots at "
        f"{cfg.printer.dpi} dpi (dot size {acc.dot_size_mm:.4f} mm). "
        f"At least 3 dots per module is required; 5 or more is preferred.",
    ]
    lines.extend(durability_advice(cfg.media))
    return tuple(lines)


def warnings(cfg: AopsConfig, derived: DerivedGeometry) -> tuple[str, ...]:
    """Safety and correctness warnings for the printed strip."""
    cell = derived.cell
    return (
        "Do not scale, resample or re-export this PDF in any other application.",
        "Do not photocopy the strip. Copiers do not hold scale.",
        f"Cut only in the white gaps. Every page boundary is at least "
        f"{cell.splice_clearance_um / 1000:.1f} mm from any symbol ink "
        f"(quiet zone required: {cell.quiet_zone_mm:.1f} mm).",
        f"The position formula is {derived.position_formula}. Program the PLC with "
        f"exactly this expression.",
        "Verify the first and last positions physically before releasing the axis "
        "to automatic operation.",
    )
