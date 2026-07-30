"""The concrete validation rules.

Grouped by prefix:

    GEO  cell geometry and the splice invariant
    POS  index range and position mapping
    PAY  payload encoding
    SYM  symbology availability and consistency
    PAG  pagination and page fit
    CON  continuous (single-page) export
    PRN  printer and print process
    MED  substrate fitness
    SCN  scanner optics
    PRJ  project traceability

Every rule is a plain function of `(cfg, derived)`. `derived` is None when
geometry resolution itself failed, so cell-level rules must not assume it
exists - they run first and unconditionally.
"""

from __future__ import annotations

from collections.abc import Iterable

from aops.core.cell import GENEROUS_MODULE_UM, MIN_MODULE_UM, resolve_cell
from aops.core.config import AopsConfig
from aops.core.design import detect_style
from aops.core.enums import (
    ContinuousStrategy,
    LrMarginMode,
    Media,
    PitchMode,
    PrintMethod,
    PrintStyle,
    Ribbon,
    Severity,
    SpliceMode,
    Symbology,
)
from aops.core.errors import GeometryError
from aops.core.layout.bands import solve_bands
from aops.core.stats import DerivedGeometry
from aops.core.units import PDF_MAX_PT, PDF_MAX_USER_UNIT, mm_per_dot
from aops.core.validation import Finding, Fix, Rule

#: Minimum printer dots per symbol module for clean edge definition. Below 3 the
#: module edges break up; 5 is the comfortable industrial target.
MIN_MODULE_DOTS: float = 3.0
GOOD_MODULE_DOTS: float = 5.0

#: Symbology-mandated quiet zones, in modules.
QUIET_MODULES = {Symbology.DATA_MATRIX: 1, Symbology.QR: 4}


def _f(
    rule_id: str,
    sev: Severity,
    msg: str,
    field: str | None = None,
    hint: str | None = None,
    fix: Fix | None = None,
) -> Finding:
    return Finding(rule_id=rule_id, severity=sev, message=msg, field=field, hint=hint, fix=fix)


def _mm_fix(field: str, value: float, what: str) -> Fix:
    """A one-click correction expressed in millimetres."""
    return Fix(field=field, value=round(value, 3), label=f"Set {what} to {value:.3f} mm")


# --------------------------------------------------------------------------
# GEO - cell geometry
# --------------------------------------------------------------------------


def geo_cell(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Cell geometry, including the master splice invariant."""
    dim = cfg.dimensions

    if dim.pitch_mm <= 0:
        yield _f("GEO-001", Severity.ERROR, f"Cell pitch must be positive (got {dim.pitch_mm:.3f} mm).",
                 "dimensions.pitch_mm", "Set a pitch greater than zero.")
    if dim.symbol_size_mm <= 0:
        yield _f("GEO-002", Severity.ERROR, f"Symbol size must be positive (got {dim.symbol_size_mm:.3f} mm).",
                 "dimensions.symbol_size_mm", "Set a symbol size greater than zero.")
    if dim.quiet_zone_mm < 0:
        yield _f("GEO-005", Severity.ERROR, f"Quiet zone cannot be negative (got {dim.quiet_zone_mm:.3f} mm).",
                 "dimensions.quiet_zone_mm")
    if dim.strip_height_mm <= 0:
        yield _f("GEO-008", Severity.ERROR, f"Strip height must be positive (got {dim.strip_height_mm:.3f} mm).",
                 "dimensions.strip_height_mm")

    if dim.pitch_mm <= 0 or dim.symbol_size_mm <= 0:
        return

    if dim.symbol_size_mm > dim.pitch_mm:
        # Raise the pitch far enough to clear the quiet zones too, so applying
        # this does not simply surface GEO-004 on the next recompute.
        target = dim.symbol_size_mm + 2 * dim.quiet_zone_mm
        yield _f("GEO-003", Severity.ERROR,
                 f"Symbol ({dim.symbol_size_mm:.3f} mm) is larger than the cell pitch "
                 f"({dim.pitch_mm:.3f} mm); symbols would overlap.",
                 "dimensions.symbol_size_mm",
                 f"Reduce the symbol below {dim.pitch_mm:.3f} mm, or raise the pitch to "
                 f"{target:.3f} mm.",
                 _mm_fix("dimensions.pitch_mm", target, "cell pitch"))
        return

    needed = dim.symbol_size_mm + 2 * dim.quiet_zone_mm
    if needed > dim.pitch_mm:
        yield _f("GEO-004", Severity.ERROR,
                 f"Symbol plus both quiet zones ({needed:.3f} mm) exceeds the pitch "
                 f"({dim.pitch_mm:.3f} mm); adjacent quiet zones overlap and splice "
                 f"safety is lost.",
                 "dimensions.quiet_zone_mm",
                 f"Raise the pitch to at least {needed:.3f} mm, or reduce the symbol "
                 f"or quiet zone.",
                 _mm_fix("dimensions.pitch_mm", needed, "cell pitch"))

    if needed > dim.strip_height_mm:
        yield _f("GEO-007", Severity.ERROR,
                 f"Symbol plus quiet zones ({needed:.3f} mm) does not fit the strip height "
                 f"({dim.strip_height_mm:.3f} mm).",
                 "dimensions.strip_height_mm",
                 f"Increase the strip height to at least {needed:.3f} mm.",
                 _mm_fix("dimensions.strip_height_mm", needed, "strip height"))

    if dim.lr_margin_mode is LrMarginMode.DRIVES_PITCH:
        implied = dim.symbol_size_mm + 2 * dim.margin_lr_mm
        if abs(implied - dim.pitch_mm) > 0.001:
            yield _f("GEO-009", Severity.INFO,
                     f"Pitch is derived from symbol + 2 x margin = {implied:.3f} mm "
                     f"(the pitch field shows {dim.pitch_mm:.3f} mm and is ignored in this mode).",
                     "dimensions.margin_lr_mm")

    gap = dim.pitch_mm - dim.symbol_size_mm
    if 0 < gap < 3.0:
        target = dim.symbol_size_mm + 3.0
        yield _f("GEO-013", Severity.WARNING,
                 f"White gap between symbols is only {gap:.3f} mm, leaving "
                 f"{gap / 2:.3f} mm of cutting tolerance at each splice.",
                 "dimensions.pitch_mm",
                 f"Raise the pitch to {target:.3f} mm for 1.5 mm of tolerance each side, "
                 f"or reduce the symbol.",
                 _mm_fix("dimensions.pitch_mm", target, "cell pitch"))


def geo_module(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Module size sanity, independent of the printer."""
    if derived is None:
        return
    module_um = derived.cell.module_um(derived.matrix_cols)
    if module_um <= 0:
        return
    if module_um < MIN_MODULE_UM:
        yield _f("GEO-010", Severity.WARNING,
                 f"Module size is {module_um / 1000:.3f} mm, below the "
                 f"{MIN_MODULE_UM / 1000:.2f} mm practical limit for reliable printing "
                 f"and imaging.",
                 "dimensions.symbol_size_mm",
                 "Increase the symbol size or shorten the payload.")
    elif module_um >= GENEROUS_MODULE_UM:
        yield _f("GEO-011", Severity.INFO,
                 f"Module size is {module_um / 1000:.3f} mm - generous. The symbol could "
                 f"be made smaller, or the pitch reduced for finer resolution.",
                 "dimensions.symbol_size_mm")


def geo_length(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None:
        return
    if derived.total_length_mm <= 0:
        yield _f("GEO-012", Severity.ERROR, "Strip length is zero - nothing would be printed.",
                 "position.end_index")


def geo_overlap(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Splice overlap must stay inside white on both sheets."""
    if cfg.printing.splice_mode is not SpliceMode.OVERLAP:
        return
    if derived is None:
        return
    limit = derived.cell.margin_lr_mm - derived.cell.quiet_zone_mm
    if cfg.printing.splice_overlap_mm > limit:
        yield _f("GEO-014", Severity.ERROR,
                 f"Splice overlap {cfg.printing.splice_overlap_mm:.3f} mm exceeds the "
                 f"{limit:.3f} mm of white available; the overlap would cover a quiet zone.",
                 "printing.splice_overlap_mm",
                 f"Reduce the overlap to at most {limit:.3f} mm.")
    if cfg.printing.splice_overlap_mm < 0:
        yield _f("GEO-014", Severity.ERROR, "Splice overlap cannot be negative.",
                 "printing.splice_overlap_mm")


# --------------------------------------------------------------------------
# POS - index range
# --------------------------------------------------------------------------


def pos_range(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    pos = cfg.position
    if pos.increment <= 0:
        yield _f("POS-002", Severity.ERROR, f"Increment must be positive (got {pos.increment}).",
                 "position.increment")
        return
    if pos.end_index < pos.start_index:
        yield _f("POS-001", Severity.ERROR,
                 f"End index ({pos.end_index}) is below the start index ({pos.start_index}).",
                 "position.end_index", "Set the end index at or above the start index.")
        return
    count = derived.code_count if derived else 0
    if count == 0:
        yield _f("POS-007", Severity.ERROR, "The index range produces no codes.",
                 "position.end_index")
    elif count > 5000:
        yield _f("POS-006", Severity.WARNING,
                 f"{count} codes is a very large strip; export and preview will be slower.",
                 "position.end_index")


def pos_increment_semantics(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Explain the pitch-mode consequence whenever increment != 1.

    This is INFO, not a warning - but it is the most important INFO in the
    application. Getting it wrong sends the axis to the wrong place.
    """
    if cfg.position.increment == 1 or derived is None:
        return
    if cfg.position.pitch_mode is PitchMode.PER_CELL:
        yield _f("POS-005", Severity.INFO,
                 f"Increment is {cfg.position.increment} with contiguous cells, so position "
                 f"follows the cell ordinal: {derived.position_formula}. Each printed code "
                 f"is {derived.distance_per_code_mm:.3f} mm from the next.",
                 "position.pitch_mode",
                 "Switch to 'per index' if the PLC must use Position = Index x Pitch.")
    else:
        yield _f("POS-005", Severity.INFO,
                 f"Increment is {cfg.position.increment} in per-index mode: blank cells are "
                 f"inserted for skipped indices so that {derived.position_formula} holds "
                 f"literally.",
                 "position.pitch_mode")


# --------------------------------------------------------------------------
# PAY - payload
# --------------------------------------------------------------------------


def pay_digits(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None:
        return
    need = derived.required_digits
    have = cfg.payload.digits
    if have < need:
        yield _f("PAY-001", Severity.ERROR,
                 f"{have} digits cannot represent the largest payload, which needs {need} "
                 f"(maximum position {derived.max_position_mm:.3f} mm). Payloads would be "
                 f"truncated and ambiguous.",
                 "payload.digits", f"Set digits to at least {need}.",
                 Fix("payload.digits", need, f"Set digits to {need}"))
    elif have > need + 2:
        yield _f("PAY-003", Severity.WARNING,
                 f"{have} digits is {have - need} more than needed; the extra characters "
                 f"may push the symbol to a larger matrix than necessary.",
                 "payload.digits", f"{need} digits would suffice.",
                 Fix("payload.digits", need, f"Set digits to {need}"))


def pay_precision(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None or derived.precision_loss_mm <= 1e-9:
        return
    yield _f("PAY-002", Severity.WARNING,
             f"The payload scale rounds positions by up to {derived.precision_loss_mm:.4f} mm "
             f"(pitch {derived.cell.pitch_mm:.3f} mm is not a whole number of payload units).",
             "payload.unit_scale",
             "Increase the payload resolution to 0.1 mm or 0.01 mm.")


def pay_charset(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Prefix/suffix must be encodable by the chosen symbology."""
    text = cfg.payload.prefix + cfg.payload.suffix
    if not text:
        return
    if not text.isascii():
        yield _f("PAY-004", Severity.ERROR,
                 "Payload prefix/suffix contains non-ASCII characters, which cannot be "
                 "encoded reliably.",
                 "payload.prefix")


# --------------------------------------------------------------------------
# SYM - symbology
# --------------------------------------------------------------------------


def sym_available(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    sym = cfg.symbol.symbology
    if not sym.implemented:
        yield _f("SYM-001", Severity.FATAL,
                 f"{sym.display_name} is not implemented in this build. Export is blocked - "
                 f"AOPS will not silently substitute a different symbology.",
                 "symbol.symbology",
                 "Select Data Matrix ECC200 or QR Code.")


def sym_quiet_zone(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Quiet zone must meet the symbology's mandated minimum in modules."""
    if derived is None:
        return
    sym = cfg.symbol.symbology
    modules = QUIET_MODULES.get(sym)
    if modules is None:
        return
    module_mm = derived.cell.module_mm(derived.matrix_cols)
    required_mm = modules * module_mm
    if module_mm > 0 and cfg.dimensions.quiet_zone_mm < required_mm - 1e-9:
        yield _f("GEO-006", Severity.WARNING,
                 f"{sym.display_name} requires a quiet zone of {modules} module(s) "
                 f"= {required_mm:.3f} mm; configured value is "
                 f"{cfg.dimensions.quiet_zone_mm:.3f} mm.",
                 "dimensions.quiet_zone_mm",
                 f"Increase the quiet zone to {required_mm:.3f} mm.",
                 _mm_fix("dimensions.quiet_zone_mm", required_mm, "quiet zone"))


def sym_qr_ecc(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if cfg.symbol.symbology is not Symbology.QR:
        return
    if cfg.symbol.qr_ecc.value == "H" and cfg.payload.digits <= 8:
        yield _f("SYM-004", Severity.WARNING,
                 "QR error correction H on a short numeric payload inflates the symbol for "
                 "little benefit on a clean printed strip.",
                 "symbol.qr_ecc", "Level M is usually the right trade-off here.")


# --------------------------------------------------------------------------
# PAG - pagination
# --------------------------------------------------------------------------


def pag_fit(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """The one cell must fit a page, or nothing can be produced."""
    if not cfg.output.tiled_pages:
        return
    try:
        cell = resolve_cell(cfg.dimensions)
    except GeometryError:
        return
    usable_mm = cfg.paper.usable_width_mm()
    k = cfg.printing.scale_factor
    if k <= 0:
        return
    scaled_pitch = cell.pitch_mm * k
    if scaled_pitch > usable_mm:
        yield _f("PAG-001", Severity.FATAL,
                 f"One cell ({cell.pitch_mm:.3f} mm x {cfg.printing.scale_percent:.1f}% = "
                 f"{scaled_pitch:.3f} mm) does not fit the usable page width "
                 f"({usable_mm:.3f} mm).",
                 "paper.preset",
                 "Increase the page size, reduce the cell pitch, reduce page margins, "
                 "or reduce printer scaling.")


def pag_height(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if not cfg.output.tiled_pages:
        return
    usable_h = cfg.paper.usable_height_mm()
    k = cfg.printing.scale_factor
    # Strip band, plus ruler, plus calibration bar, plus header and footer.
    needed = cfg.dimensions.strip_height_mm * k
    if cfg.output.engineering_ruler:
        needed += 12.0
    if cfg.output.calibration_bar:
        needed += 16.0
    needed += 26.0  # header + footer bands
    if needed > usable_h:
        yield _f("PAG-002", Severity.ERROR,
                 f"Page content needs about {needed:.1f} mm of height but only "
                 f"{usable_h:.1f} mm is usable.",
                 "paper.orientation",
                 "Reduce the strip height, disable the ruler or calibration bar, "
                 "or use a larger/landscape sheet.")


def pag_calibration_fits(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """A clipped calibration bar produces a *wrong* calibration - worse than none."""
    if not cfg.output.calibration_bar:
        return
    length = cfg.printing.calibration_length_mm * cfg.printing.scale_factor
    usable_w = cfg.paper.usable_width_mm()
    usable_h = cfg.paper.usable_height_mm()
    if length > usable_w:
        if length <= usable_h:
            yield _f("PAG-003", Severity.ERROR,
                     f"The {cfg.printing.calibration_length_mm:.0f} mm calibration bar "
                     f"(drawn at {length:.1f} mm) does not fit the {usable_w:.1f} mm usable "
                     f"page width, but would fit vertically ({usable_h:.1f} mm).",
                     "printing.calibration_length_mm",
                     "Rotate the sheet to landscape, or rotate the calibration bar 90 deg. "
                     "Never shorten it - a bar of unknown length cannot calibrate anything.")
        else:
            yield _f("PAG-003", Severity.ERROR,
                     f"The {cfg.printing.calibration_length_mm:.0f} mm calibration bar does "
                     f"not fit this page in either orientation.",
                     "printing.calibration_length_mm",
                     "Use a larger sheet or shorten the calibration length "
                     "(and record the new length).")


def pag_count(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None or not cfg.output.tiled_pages:
        return
    n = len(derived.pages)
    if n > 500:
        yield _f("PAG-004", Severity.ERROR,
                 f"{n} pages is impractical to print and splice.",
                 "paper.preset", "Use a larger sheet or the continuous export.")
    elif n > 50:
        yield _f("PAG-004", Severity.WARNING,
                 f"{n} pages will need careful handling; each tile must be positioned "
                 f"against a measured datum.",
                 "paper.preset", "A larger sheet or the continuous export reduces splices.")


def pag_last_page(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None or len(derived.pages) < 2:
        return
    last = derived.pages[-1]
    if last.cell_count == 0:
        return
    if last.cell_count < 2:
        yield _f("PAG-005", Severity.WARNING,
                 f"The last page carries only {last.cell_count} cell. A small change to the "
                 f"margins would balance the run.",
                 "paper.margin_left_mm")


def pag_margins(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    limit = cfg.printer.unprintable_margin_mm
    for name, value in (
        ("paper.margin_left_mm", cfg.paper.margin_left_mm),
        ("paper.margin_right_mm", cfg.paper.margin_right_mm),
        ("paper.margin_top_mm", cfg.paper.margin_top_mm),
        ("paper.margin_bottom_mm", cfg.paper.margin_bottom_mm),
    ):
        if value < 0:
            yield _f("PAG-007", Severity.ERROR, f"Page margin {name.split('.')[-1]} is negative.", name)
        elif value < limit:
            yield _f("PAG-007", Severity.WARNING,
                     f"Margin {value:.1f} mm is inside the printer's stated unprintable "
                     f"border of {limit:.1f} mm; content may be clipped.",
                     name, f"Use at least {limit:.1f} mm.")


def pag_leading(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None or not cfg.output.tiled_pages or not derived.pages:
        return
    if derived.pages[0].cell_count == 0 and len(derived.pages) > 1:
        yield _f("PAG-006", Severity.WARNING,
                 f"The leading margin of {cfg.printing.leading_margin_mm:.1f} mm fills the "
                 f"whole first page, leaving no room for a cell.",
                 "printing.leading_margin_mm", "Reduce the leading margin.")


# --------------------------------------------------------------------------
# CON - continuous export
# --------------------------------------------------------------------------


def pag_roll_media(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Roll media removes the splice problem, but only if continuous is used.

    Tiling onto a continuous roll is the worst of both worlds: the operator
    still has to cut and datum-align every tile, having bought media that made
    neither necessary.
    """
    preset = cfg.paper.preset
    if not preset.is_roll:
        return

    if cfg.output.tiled_pages and not cfg.output.continuous:
        yield _f("PAG-008", Severity.WARNING,
                 "Roll media is selected but the output is tiled sheets, so the strip "
                 "is still cut into pieces that each need datum alignment.",
                 "output.continuous",
                 "Turn on continuous output to print the strip in one piece - roll media "
                 "removes splices entirely.")
    elif cfg.output.continuous:
        yield _f("PAG-009", Severity.INFO,
                 f"Continuous roll output: the strip prints in one piece with no page "
                 f"boundaries, so there is nothing to cut or datum-align and the "
                 f"{derived.accuracy.cumulative_error_mm:.1f} mm butt-splice error does "
                 f"not arise." if derived else
                 "Continuous roll output: the strip prints in one piece with no splices.",
                 "output.continuous")

    # The printed page is the whole band stack - header, ruler, calibration bar
    # and footer as well as the strip band - which at the defaults is over twice
    # the strip height. Measuring the strip band alone would let a job that
    # overflows the roll pass. `pag_height` covers the same ground for tiled
    # output only, so continuous roll jobs would otherwise go unchecked.
    bands = solve_bands(cfg, with_calibration=cfg.output.calibration_bar)
    needed = max(bands.total_height_mm, cfg.dimensions.strip_height_mm)
    available = cfg.paper.usable_height_mm()
    if needed > available:
        yield _f("PAG-010", Severity.ERROR,
                 f"The printed band stack is {needed:.1f} mm across but only "
                 f"{available:.1f} mm of the {preset.roll_width_mm:.0f} mm roll is usable "
                 f"after margins. The edges would be clipped.",
                 "paper.preset",
                 "Use a wider roll, reduce the strip height, turn off the ruler or "
                 "calibration bar, or reduce the margins.")


def pag_print_style(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """What a plain print gives up.

    Not an error - artwork and design proofs are a legitimate output, and the
    tool should not refuse to make one. But the calibration bar is the *only*
    printed means of proving the sheet came out 1:1, and a positioning strip
    that is silently 0.2 % short is worse than one that obviously failed. So
    the trade is stated rather than assumed.
    """
    style = detect_style(cfg)
    if style is PrintStyle.ENGINEERING:
        return

    if not cfg.output.calibration_bar:
        yield _f("PAG-011", Severity.WARNING,
                 f"'{style.display_name}' prints no calibration bar, so there is no way "
                 f"to check on paper that the strip came out at true size.",
                 "output.calibration_bar",
                 "Fine for artwork and proofs. Turn the calibration bar back on - or "
                 "choose the Engineering style - before printing a strip that will go "
                 "on a machine.")

    if not cfg.output.page_header_footer and derived is not None and len(derived.pages) > 1:
        yield _f("PAG-012", Severity.WARNING,
                 f"With no header or footer, the {len(derived.pages)} sheets carry no "
                 f"page number, absolute X range or fingerprint, so they cannot be told "
                 f"apart or matched to this project once printed.",
                 "output.page_header_footer",
                 "Turn the header and footer on for multi-sheet output, or export "
                 "continuously so there is only one piece.")


def con_selected(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if not cfg.output.tiled_pages and not cfg.output.continuous:
        yield _f("CON-004", Severity.WARNING,
                 "Neither tiled pages nor continuous output is selected - there is nothing "
                 "to export.",
                 "output.tiled_pages")


def con_limits(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None or not cfg.output.continuous:
        return
    spec = derived.continuous

    if spec.strategy is ContinuousStrategy.USER_UNIT and spec.over_limit:
        if spec.user_unit > PDF_MAX_USER_UNIT:
            yield _f("CON-002", Severity.ERROR,
                     f"The strip needs /UserUnit {spec.user_unit:.2f}, beyond the PDF maximum "
                     f"of {PDF_MAX_USER_UNIT:.0f}.",
                     "output.continuous_strategy", "Use the split-roll strategy instead.")
        else:
            yield _f("CON-001", Severity.WARNING,
                     f"The strip is {spec.width_mm / 1000:.3f} m ({spec.width_pt:.0f} pt), "
                     f"beyond the {PDF_MAX_PT:.0f} pt PDF page limit. AOPS will declare "
                     f"/UserUnit {spec.user_unit:.2f} so the page still measures true size.",
                     "output.continuous_strategy",
                     "Acrobat 7+ and modern RIPs honour /UserUnit. Confirm with your shop, "
                     "and always check the 200 mm calibration bar on the proof.")

    if spec.strategy is ContinuousStrategy.RAW_OVERSIZE and spec.over_limit:
        yield _f("CON-005", Severity.WARNING,
                 f"Raw oversize emits a {spec.width_pt:.0f} pt page, "
                 f"{spec.width_pt / PDF_MAX_PT:.2f}x the PDF limit. Many large-format RIPs "
                 f"accept this; Acrobat will refuse or clamp it.",
                 "output.continuous_strategy",
                 "Use /UserUnit for a conformant single page.")

    if spec.strategy is ContinuousStrategy.SPLIT_ROLL and spec.roll_count > 1:
        yield _f("CON-003", Severity.INFO,
                 f"Split-roll produces {spec.roll_count} files of "
                 f"{spec.roll_length_mm / 1000:.3f} m each, which the shop must splice.",
                 "output.continuous_strategy")

    if spec.width_mm > cfg.output.continuous_max_length_mm and spec.strategy is not ContinuousStrategy.SPLIT_ROLL:
        yield _f("CON-003", Severity.WARNING,
                 f"{spec.width_mm / 1000:.3f} m exceeds the stated roll-media limit of "
                 f"{cfg.output.continuous_max_length_mm / 1000:.3f} m.",
                 "output.continuous_max_length_mm")


# --------------------------------------------------------------------------
# PRN - printer and process
# --------------------------------------------------------------------------


def prn_scaling(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    pct = cfg.printing.scale_percent
    if pct <= 0 or pct > 200:
        yield _f("PRN-002", Severity.ERROR,
                 f"Printer scaling of {pct:.3f}% is out of the usable range (0-200%).",
                 "printing.scale_percent")
        return
    if abs(pct - 100.0) > 1e-9:
        yield _f("PRN-001", Severity.INFO,
                 f"All geometry, including the calibration bar, is scaled by {pct:.3f}%.",
                 "printing.scale_percent")
    if abs(pct - 100.0) > 2.0:
        yield _f("PRN-003", Severity.WARNING,
                 f"A {abs(pct - 100.0):.2f}% correction is large. Recalibrate the printer "
                 f"itself rather than compensating this far in software.",
                 "printing.scale_percent")


def prn_calibration(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if cfg.printing.calibration_length_mm <= 0:
        yield _f("PRN-004", Severity.ERROR, "Calibration length must be positive.",
                 "printing.calibration_length_mm")


def prn_module_dots(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """The print-resolution criterion: a module must span enough printer dots."""
    if derived is None:
        return
    dpi = cfg.printer.dpi
    if dpi <= 0:
        yield _f("PRN-009", Severity.ERROR, f"Printer resolution must be positive (got {dpi}).",
                 "printer.dpi")
        return
    dots = derived.accuracy.module_dots
    if dots <= 0:
        return
    if dots < MIN_MODULE_DOTS:
        yield _f("PRN-005", Severity.ERROR,
                 f"One module is only {dots:.1f} printer dots at {dpi} dpi "
                 f"(module {derived.cell.module_mm(derived.matrix_cols):.4f} mm, dot "
                 f"{mm_per_dot(dpi):.4f} mm). Module edges will not render cleanly.",
                 "printer.dpi",
                 f"Use at least {MIN_MODULE_DOTS:.0f} dots per module: raise the printer "
                 f"resolution or increase the symbol size.")
    elif dots < GOOD_MODULE_DOTS:
        yield _f("PRN-006", Severity.WARNING,
                 f"One module is {dots:.1f} printer dots at {dpi} dpi. This prints, but "
                 f"{GOOD_MODULE_DOTS:.0f}+ dots gives noticeably better edge definition "
                 f"and a higher ISO/IEC 15415 grade.",
                 "printer.dpi")


def prn_splice_error(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Surface the cumulative-vs-bounded error difference."""
    if derived is None or not cfg.output.tiled_pages or len(derived.pages) < 2:
        return
    acc = derived.accuracy
    if acc.cumulative_error_mm > 1.0:
        yield _f("PRN-008", Severity.INFO,
                 f"Butt-splicing {len(derived.pages)} tiles would accumulate up to "
                 f"{acc.cumulative_error_mm:.1f} mm of drift over "
                 f"{acc.strip_length_mm / 1000:.3f} m. Positioning each tile against a "
                 f"measured datum bounds the error at {acc.bounded_error_mm:.2f} mm per tile.",
                 "printing.splice_mode",
                 "Align every tile to its printed absolute position with a steel tape - "
                 "do not butt tiles against each other.")


# --------------------------------------------------------------------------
# MED - substrate
# --------------------------------------------------------------------------


def med_paper(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if cfg.media.media is not Media.PAPER or derived is None:
        return
    drift = derived.accuracy.media_drift_mm
    if derived.total_length_mm > 1000.0:
        yield _f("MED-001", Severity.ERROR,
                 f"Paper moves about {drift:.1f} mm over this {derived.total_length_mm / 1000:.3f} m "
                 f"strip across a {cfg.media.rh_swing_percent:.0f}% humidity swing. That is far "
                 f"beyond any positioning tolerance.",
                 "media.media",
                 "Use polyester film or synthetic stock for any strip over about a metre.")


def med_drift(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None:
        return
    drift = derived.accuracy.media_drift_mm
    if cfg.media.media is Media.PAPER:
        return  # already reported as MED-001
    if drift > derived.cell.pitch_mm / 2:
        yield _f("MED-002", Severity.WARNING,
                 f"Predicted substrate movement of {drift:.2f} mm over the strip exceeds "
                 f"half a pitch. Position readings will drift with humidity.",
                 "media.media", "Choose a more stable substrate or control the environment.")


def med_thermal(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Temperature, which on polyester outweighs humidity by an order of magnitude."""
    if derived is None:
        return
    acc = derived.accuracy
    m = cfg.media

    if m.temp_swing_deg_c <= 0.0:
        yield _f("MED-006", Severity.INFO,
                 "Temperature swing is zero, so no thermal error is modelled. Set the "
                 "expected in-service range to include it in the budget.",
                 "media.temp_swing_deg_c")
        return

    if acc.thermal_drift_mm > derived.cell.pitch_mm / 2:
        yield _f("MED-006", Severity.ERROR,
                 f"Thermal expansion moves the strip {acc.thermal_drift_mm:.2f} mm over its "
                 f"length across a {m.temp_swing_deg_c:.0f} C swing - more than half a pitch, so "
                 f"the reader can land on the wrong code.",
                 "media.temp_swing_deg_c",
                 "Bond the strip along its full length, match the substrate to the frame, "
                 "or control the temperature.")
    elif acc.thermal_drift_mm > 1.0:
        yield _f("MED-006", Severity.WARNING,
                 f"Thermal expansion moves the strip {acc.thermal_drift_mm:.2f} mm over its "
                 f"length across a {m.temp_swing_deg_c:.0f} C swing "
                 f"({m.cte_mismatch_ppm_per_c:+.0f} ppm/C against "
                 f"{m.frame_material.display_name.lower()}).",
                 "media.mounting",
                 "Bonding along the full length makes the strip follow the frame and largely "
                 "cancels this.")

    # Worth saying out loud: the tool has always reported humidity prominently,
    # and for the substrate this application actually uses it is the smaller term.
    if acc.thermal_dominates and acc.thermal_drift_mm > 0.1:
        yield _f("MED-007", Severity.INFO,
                 f"Temperature moves this strip further than humidity does "
                 f"({acc.thermal_drift_mm:.2f} mm against {acc.media_drift_mm:.2f} mm). "
                 f"Substrate choice alone will not fix it.",
                 "media.temp_swing_deg_c")


def med_bond_stress(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """A bonded tape trades a position error for a shear load on the adhesive."""
    if derived is None:
        return
    strain = derived.accuracy.bond_strain_ppm
    if strain <= 0.0:
        return
    if strain > 400.0:
        yield _f("MED-008", Severity.WARNING,
                 f"Bonding {cfg.media.media.display_name.lower()} to "
                 f"{cfg.media.frame_material.display_name.lower()} forces the adhesive to "
                 f"carry {strain:.0f} ppm of strain over a {cfg.media.temp_swing_deg_c:.0f} C "
                 f"swing. Thermal error is cancelled at the cost of long-term bond stress.",
                 "media.frame_material",
                 "Use a permanent acrylic adhesive rated for the range, or match the "
                 "substrate more closely to the frame.")


def med_process(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    m = cfg.media
    if m.method is PrintMethod.LASER and m.media in (Media.POLYESTER, Media.VINYL):
        yield _f("MED-003", Severity.WARNING,
                 f"{m.media.display_name} through a laser fuser must be rated for fuser "
                 f"temperature; unrated film shrinks or delaminates.",
                 "media.method", "Confirm the media datasheet, or use thermal transfer.")
    if m.method is PrintMethod.THERMAL_TRANSFER and m.ribbon is Ribbon.WAX:
        yield _f("MED-004", Severity.WARNING,
                 "Wax ribbon scratches off synthetic stock within weeks in a machine "
                 "environment.",
                 "media.ribbon", "Use wax-resin as a minimum, or resin for best durability.")
    if m.method is PrintMethod.THERMAL_TRANSFER and m.ribbon is Ribbon.NONE:
        yield _f("MED-004", Severity.ERROR,
                 "Thermal transfer requires a ribbon.", "media.ribbon")
    if m.method is PrintMethod.DIRECT_THERMAL:
        # The one print method that is wrong for this application on its own
        # terms: the image is the substrate reacting to heat, so the same heat
        # keeps acting on it for the rest of its life.
        yield _f("MED-009", Severity.WARNING,
                 "Direct thermal images fade with heat, sunlight and abrasion, and "
                 "darken wholesale near a warm machine. A positioning strip is a "
                 "multi-year fixture; this is only suitable for a temporary or trial "
                 "strip.",
                 "media.method",
                 "Use thermal transfer with a resin ribbon on polyester for anything "
                 "left on a machine.")
        if m.ribbon is not Ribbon.NONE:
            yield _f("MED-010", Severity.INFO,
                     "Direct thermal takes no ribbon; the ribbon setting is ignored.",
                     "media.ribbon", "Set the ribbon to None.")
    if not (m.method is PrintMethod.THERMAL_TRANSFER and m.ribbon is Ribbon.RESIN):
        yield _f("MED-005", Severity.INFO,
                 "For a long-service industrial strip, resin ribbon on polyester is the "
                 "durable combination: 5+ years resisting abrasion, chemicals and UV.",
                 "media.method")


# --------------------------------------------------------------------------
# SCN - scanner
# --------------------------------------------------------------------------


def scn_fov(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """State the required field of view. Non-obvious and safety-relevant."""
    if derived is None:
        return
    rec = derived.scanner
    n = max(1, cfg.scanner.min_codes_in_view)
    detail = (
        f"The reader needs a field of view of at least {rec.fov_continuous_mm:.1f} mm "
        f"({n} x pitch {derived.cell.pitch_mm:.1f} mm + symbol {derived.cell.symbol_mm:.1f} mm) "
        f"to keep {n} complete code(s) in view at every position."
    )
    if n > 1:
        detail += f" This tolerates {rec.occlusion_tolerance_mm:.0f} mm of continuous tape damage."
    else:
        detail += " Below this there are blind zones where absolute position is lost."
    yield _f("SCN-001", Severity.INFO, detail, "scanner.min_codes_in_view")


def scn_sensor(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    if derived is None:
        return
    px = derived.scanner.required_sensor_px
    if px > 2048:
        yield _f("SCN-002", Severity.WARNING,
                 f"Resolving {cfg.scanner.px_per_module:.0f} px per module across the "
                 f"{derived.scanner.fov_continuous_mm:.0f} mm field of view needs about "
                 f"{px} pixels - a demanding sensor.",
                 "scanner.min_codes_in_view",
                 "Reduce the pitch, increase the module size, or lower the redundancy.")


# --------------------------------------------------------------------------
# PRJ - traceability
# --------------------------------------------------------------------------


def scn_reader_fit(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    """Whether the reader you actually chose can see this strip.

    Only runs once a real reader's angular field of view has been entered.
    Until then the generic lens estimate stands and there is nothing to check
    against.
    """
    if derived is None or not cfg.scanner.has_reader_spec:
        return
    rec = derived.scanner
    scn = cfg.scanner
    wd = rec.required_wd_mm

    if scn.dof_max_mm > 0 and wd > scn.dof_max_mm:
        yield _f("SCN-003", Severity.ERROR,
                 f"Seeing {rec.fov_continuous_mm:.0f} mm at once needs the reader "
                 f"{wd:.0f} mm away, beyond its {scn.dof_min_mm:.0f}-{scn.dof_max_mm:.0f} mm "
                 f"focus range. It cannot cover a full pitch plus a code from anywhere "
                 f"it can focus, so there will be blind spots.",
                 "scanner.fov_angle_deg",
                 "Reduce the pitch or the code size, or choose a reader with a wider "
                 "field of view.")
    elif scn.dof_min_mm > 0 and wd < scn.dof_min_mm:
        yield _f("SCN-004", Severity.INFO,
                 f"The required {rec.fov_continuous_mm:.0f} mm view is reached at "
                 f"{wd:.0f} mm, closer than the reader's {scn.dof_min_mm:.0f} mm minimum. "
                 f"Mount at {scn.dof_min_mm:.0f} mm or more - the view is only wider "
                 f"there, which is harmless.",
                 "scanner.dof_min_mm")

    # Vertical is the constraint people forget: the horizontal view is the one
    # the strip geometry drives, but the code still has to fit top to bottom.
    if rec.vertical_fov_mm > 0:
        needed_v = derived.cell.symbol_mm + 2 * derived.cell.quiet_zone_mm
        effective_wd = max(wd, scn.dof_min_mm) if scn.dof_min_mm > 0 else wd
        v_at = rec.vertical_fov_mm / wd * effective_wd if wd > 0 else 0.0
        if v_at < needed_v:
            yield _f("SCN-005", Severity.ERROR,
                     f"At {effective_wd:.0f} mm the reader sees {v_at:.0f} mm vertically, "
                     f"but the code plus its clear borders is {needed_v:.0f} mm tall.",
                     "scanner.fov_vertical_deg",
                     "Reduce the code size, or choose a reader with a taller field of view.")

    if rec.available_px_per_module > 0 and rec.available_px_per_module < cfg.scanner.px_per_module:
        yield _f("SCN-006", Severity.WARNING,
                 f"The reader puts {rec.available_px_per_module:.1f} pixels across one "
                 f"module, short of the {cfg.scanner.px_per_module:.1f} target.",
                 "scanner.sensor_px_h",
                 "Increase the code size, reduce the pitch, or choose a higher-resolution "
                 "reader.")

    if cfg.scanner.min_codes_in_view <= 1:
        yield _f("SCN-007", Severity.INFO,
                 "Reading one code at a time gives no damage tolerance: a single "
                 "obscured or scratched code loses position until the next one is "
                 "reached. Dedicated position readers see several at once for exactly "
                 "this reason.",
                 "scanner.min_codes_in_view")


def prj_metadata(cfg: AopsConfig, derived: DerivedGeometry | None) -> Iterable[Finding]:
    p = cfg.project
    if not p.strip_id.strip():
        yield _f("PRJ-001", Severity.WARNING,
                 "No strip ID. Printed pages will lack a traceable identifier.",
                 "project.strip_id", "Give the strip an ID such as 'AX1-POS-001'.")
    if not p.revision.strip():
        yield _f("PRJ-002", Severity.WARNING, "No revision recorded.", "project.revision")
    if not p.machine.strip():
        yield _f("PRJ-004", Severity.INFO, "No machine name recorded.", "project.machine")
    if len(p.comments) > 400:
        yield _f("PRJ-003", Severity.INFO,
                 f"Comments are {len(p.comments)} characters; the guide page shows the "
                 f"first 400.",
                 "project.comments")


#: Rules in evaluation order. Cell-level rules come first because they run even
#: when geometry resolution failed and `derived` is None.
ALL_RULES: tuple[Rule, ...] = (
    geo_cell,
    geo_module,
    geo_length,
    geo_overlap,
    pos_range,
    pos_increment_semantics,
    pay_digits,
    pay_precision,
    pay_charset,
    sym_available,
    sym_quiet_zone,
    sym_qr_ecc,
    pag_fit,
    pag_height,
    pag_calibration_fits,
    pag_count,
    pag_last_page,
    pag_margins,
    pag_leading,
    pag_roll_media,
    pag_print_style,
    con_selected,
    con_limits,
    prn_scaling,
    prn_calibration,
    prn_module_dots,
    prn_splice_error,
    med_paper,
    med_drift,
    med_thermal,
    med_bond_stress,
    med_process,
    scn_fov,
    scn_sensor,
    scn_reader_fit,
    prj_metadata,
)
