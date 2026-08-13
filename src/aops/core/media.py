"""Substrate behaviour and print accuracy - why a strip fails in the field.

A positioning strip can be geometrically perfect in the PDF and still be wrong
on the machine. Two effects dominate, and neither is under the software's
control unless the software asks about them.

1. SUBSTRATE MOVEMENT
   Paper moves roughly 3 % between 20 % and 80 % relative humidity. Over a
   10.5 m strip that is ~315 mm - three orders of magnitude worse than the
   sub-millimetre accuracy the whole system exists to deliver. Polyester film
   moves ~0.006 % over the same range. Media choice therefore outranks every
   software setting, which is why `MediaConfig` exists and why paper on a long
   strip is a hard validation error.

2. TEMPERATURE, WHICH USUALLY OUTWEIGHS HUMIDITY
   For the substrate a positioning strip actually uses, this is the larger of
   the two environmental terms, which is the opposite of the common assumption.
   Polyester moves 0.004 % over a 40-point humidity swing but 0.051 % over a
   30 C one - twelve times more. On a 10.5 m strip that is 0.42 mm against
   5.4 mm of free expansion.

   Only the *difference* between substrate and frame reaches the reading, so
   the frame is part of the error budget: polyester (17 ppm) on steel (12 ppm)
   leaves 5 ppm, but on aluminium (23 ppm) it leaves -6 ppm, and the error
   changes sign.

   The mounting then decides whether that difference reaches the reading at
   all. A continuously bonded tape is forced to follow the frame, so a code
   stays over the feature it was aligned to and the term very largely cancels -
   the strain is carried by the adhesive instead, which turns a position
   problem into a bond-durability one. An end-anchored tape expands freely and
   takes the full differential.

3. CUMULATIVE vs BOUNDED SPLICE ERROR
   This is the insight that changes how the strip is installed.

   If tiles are **butt-spliced** - each one aligned against the previous - a
   systematic printer scale error compounds *linearly*. At 0.2 % over 10.5 m
   that is 21 mm of accumulated drift, fatal for a sub-millimetre system.

   If each tile is instead **positioned independently against a measured
   datum**, the error never accumulates: it is bounded by one tile's own error,
   about 0.6 mm for a 277 mm tile at the same 0.2 %.

   So every tile prints the absolute X position of its leading edge, and the
   installation guide instructs alignment by steel tape rather than by abutting.
   The two figures are shown side by side so the reason is self-evident.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from aops.core.config import MediaConfig, PrinterConfig
from aops.core.enums import Media, PrintMethod, Ribbon, TapeMounting
from aops.core.units import MM_PER_INCH


@dataclass(frozen=True, slots=True)
class AccuracyReport:
    """Predicted real-world dimensional accuracy of the printed strip."""

    strip_length_mm: float
    #: Movement of the substrate over the full strip for the expected RH swing.
    media_drift_mm: float
    #: Positioning error from thermal expansion, after the mounting is taken
    #: into account. Near zero for a continuously bonded tape.
    thermal_drift_mm: float
    #: Substrate-vs-frame differential over the strip, before mounting. Signed:
    #: positive means the tape grows faster than what it is stuck to.
    thermal_differential_mm: float
    #: Free expansion of the substrate alone, ignoring the frame entirely. The
    #: figure that applies when position is referenced to something that does
    #: not share the frame's temperature.
    thermal_free_mm: float
    #: Strain the adhesive must carry when the tape is bonded, in ppm.
    bond_strain_ppm: float
    #: Residual scale error after calibration, as a fraction (0.002 = 0.2 %).
    residual_scale_error: float
    #: Worst-case drift if tiles are butt-spliced end to end.
    cumulative_error_mm: float
    #: Worst-case error if each tile is placed against a measured datum.
    bounded_error_mm: float
    tile_length_mm: float
    #: Module size expressed in printer dots - the print-resolution criterion.
    module_dots: float
    dot_size_mm: float

    @property
    def datum_alignment_is_required(self) -> bool:
        """True when butt-splicing would exceed a millimetre of drift."""
        return self.cumulative_error_mm > 1.0

    @property
    def environmental_drift_mm(self) -> float:
        """Combined humidity and temperature movement reaching the reading.

        Added in quadrature rather than summed: the two swings are independent,
        and a worst-case sum would overstate the realistic error.
        """
        return (self.media_drift_mm**2 + self.thermal_drift_mm**2) ** 0.5

    @property
    def thermal_dominates(self) -> bool:
        """True when temperature moves the strip further than humidity does."""
        return abs(self.thermal_drift_mm) > self.media_drift_mm


def media_drift_mm(media: MediaConfig, strip_length_mm: float) -> float:
    """Substrate movement over `strip_length_mm` for the expected humidity swing."""
    pct = media.effective_stability_pct_per_rh * media.rh_swing_percent
    return strip_length_mm * pct / 100.0


def thermal_free_mm(media: MediaConfig, strip_length_mm: float) -> float:
    """Unconstrained expansion of the substrate itself over the strip."""
    return strip_length_mm * media.effective_cte_ppm_per_c * 1e-6 * media.temp_swing_deg_c


def thermal_differential_mm(media: MediaConfig, strip_length_mm: float) -> float:
    """Substrate-vs-frame differential expansion over the strip.

    Signed: positive means the tape grows faster than the frame it is on.
    """
    return strip_length_mm * media.cte_mismatch_ppm_per_c * 1e-6 * media.temp_swing_deg_c


def thermal_drift_mm(media: MediaConfig, strip_length_mm: float) -> float:
    """Thermal error that actually reaches the position reading.

    A continuously bonded tape is dragged along by the frame, so a code stays
    over the machine feature it was aligned to and the differential does not
    reach the reading. That cancellation is only valid against features on the
    *same* frame; `thermal_free_mm` is the figure to use when position is
    referenced to something that does not share the frame's temperature.
    """
    if media.mounting is TapeMounting.CONTINUOUS_BOND:
        return 0.0
    return abs(thermal_differential_mm(media, strip_length_mm))


def bond_strain_ppm(media: MediaConfig) -> float:
    """Strain the adhesive carries when a bonded tape is held to the frame."""
    if media.mounting is not TapeMounting.CONTINUOUS_BOND:
        return 0.0
    return abs(media.cte_mismatch_ppm_per_c) * media.temp_swing_deg_c


#: Calibration bars are sized in whole centimetres: "measure 270.0 mm" is a
#: number a steel rule answers cleanly, "measure 276.3 mm" is not.
CALIBRATION_ROUND_MM: float = 10.0


def max_calibration_length_mm(usable_width_mm: float, scale_factor: float) -> float:
    """Longest clean calibration bar the sheet can carry.

    The bar is the instrument that measures the printer, and its accuracy
    scales with its length: the residual after reading a steel rule to 0.5 mm
    is 0.5/length, so a bar spanning the page calibrates finer than a short
    one for free. Floored to a whole centimetre, and computed against the
    *drawn* length (the bar scales with the printer correction), so the answer
    still fits after a calibration is applied.
    """
    if usable_width_mm <= 0.0 or scale_factor <= 0.0:
        return 0.0
    return floor(usable_width_mm / scale_factor / CALIBRATION_ROUND_MM) * CALIBRATION_ROUND_MM


def residual_scale_error(printer: PrinterConfig, nominal_mm: float) -> float:
    """Scale error remaining after calibration, as a fraction.

    If the operator has measured the calibration bar and entered the result, the
    residual is what one least-count of their measurement implies - a 0.5 mm
    reading resolution on a 200 mm bar leaves 0.25 %. If they have not measured,
    assume an uncalibrated printer at 0.2 %, which is typical of consumer laser
    hardware.
    """
    if nominal_mm <= 0:
        return 0.002
    measured = printer.measured_calibration_mm
    if measured <= 0 or abs(measured - nominal_mm) < 1e-9:
        return 0.002  # uncalibrated / assumed nominal
    # Residual is one measurement least-count (0.5 mm) over the bar length.
    return 0.5 / nominal_mm


def accuracy_report(
    media: MediaConfig,
    printer: PrinterConfig,
    *,
    strip_length_mm: float,
    tile_length_mm: float,
    calibration_length_mm: float,
    module_size_mm: float,
) -> AccuracyReport:
    """Full accuracy prediction for the configured media, printer and geometry."""
    residual = residual_scale_error(printer, calibration_length_mm)
    dot_mm = MM_PER_INCH / printer.dpi if printer.dpi > 0 else 0.0
    return AccuracyReport(
        strip_length_mm=strip_length_mm,
        media_drift_mm=media_drift_mm(media, strip_length_mm),
        thermal_drift_mm=thermal_drift_mm(media, strip_length_mm),
        thermal_differential_mm=thermal_differential_mm(media, strip_length_mm),
        thermal_free_mm=thermal_free_mm(media, strip_length_mm),
        bond_strain_ppm=bond_strain_ppm(media),
        residual_scale_error=residual,
        cumulative_error_mm=strip_length_mm * residual,
        bounded_error_mm=tile_length_mm * residual,
        tile_length_mm=tile_length_mm,
        module_dots=(module_size_mm / dot_mm) if dot_mm > 0 else 0.0,
        dot_size_mm=dot_mm,
    )


def durability_advice(media: MediaConfig) -> tuple[str, ...]:
    """Plain-language notes on the chosen media/process combination."""
    notes: list[str] = []

    if media.method is PrintMethod.THERMAL_TRANSFER:
        if media.ribbon is Ribbon.RESIN:
            notes.append(
                "Resin ribbon on synthetic stock is the durable industrial choice: "
                "5+ years with resistance to abrasion, chemicals and UV."
            )
        elif media.ribbon is Ribbon.WAX:
            notes.append(
                "Wax ribbon scratches off synthetic stock within weeks in a machine "
                "environment. Use wax-resin as a minimum, resin for direct contact."
            )
        elif media.ribbon is Ribbon.WAX_RESIN:
            notes.append(
                "Wax-resin is the practical minimum for machinery. Move to full resin "
                "where the strip sees oil, solvent or regular wiping."
            )
    elif media.method is PrintMethod.LASER:
        notes.append(
            "Laser toner is fused to the surface and remains prone to scratching and "
            "fading. Consider over-laminating, or move to thermal transfer."
        )
    elif media.method is PrintMethod.INKJET:
        notes.append(
            "Inkjet output needs a receptive coating and should be laminated; "
            "unprotected dye inks fade under UV."
        )

    if media.media is Media.PAPER:
        notes.append(
            "Paper is dimensionally unstable with humidity and is not suitable for a "
            "positioning strip of any real length."
        )

    if media.media in (Media.POLYESTER, Media.VINYL) and media.method is PrintMethod.LASER:
        notes.append(
            "Confirm the media is rated for laser fuser temperatures; unrated film "
            "shrinks or delaminates in the fuser."
        )

    if media.adhesive_backed:
        notes.append(
            "Clean the mounting surface with isopropyl alcohol and apply from one end, "
            "squeegeeing forward to avoid trapped air and longitudinal stretch."
        )

    mismatch = abs(media.cte_mismatch_ppm_per_c)
    if media.mounting is TapeMounting.CONTINUOUS_BOND:
        notes.append(
            f"Bonded along its full length, the strip is forced to follow the "
            f"{media.frame_material.display_name.lower()} and thermal error largely "
            f"cancels against features on that same frame. This does not hold if "
            f"position is referenced to a separate base that does not share its "
            f"temperature."
        )
        if mismatch > 10.0:
            notes.append(
                f"The {mismatch:.0f} ppm/C expansion mismatch is carried by the adhesive "
                f"rather than by the reading. Use a permanent acrylic adhesive rated for "
                f"the temperature range and inspect the ends, where shear peaks."
            )
    else:
        notes.append(
            "Anchored at one end, the strip expands at its own rate, so the full "
            "substrate-to-frame difference reaches the position reading. Anchor at the "
            "datum end so error grows away from zero rather than through it."
        )

    return tuple(notes)
