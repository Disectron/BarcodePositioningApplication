"""The nine configuration sections of the left-hand panel."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from aops.core.config import AopsConfig
from aops.core.design import STYLE_FLAGS, detect_style
from aops.core.enums import (
    Climate,
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
    PitchMode,
    PrintMethod,
    PrintStyle,
    QrEcc,
    Ribbon,
    RulerPosition,
    SpliceMode,
    Symbology,
    TapeMounting,
    VerifyMode,
)
from aops.core.media import CLIMATE_SWINGS, detect_climate
from aops.core.motion import frames_on_a_code, motion_limits
from aops.core.positions import end_index_for_travel, travel_mm
from aops.core.stats import DerivedGeometry
from aops.symbols.placeholders import PLACEHOLDER_REASONS
from aops.ui.panels.base import ConfigPanel, enum_items
from aops.ui.widgets.field_row import (
    COMBO_VALUES,
    make_check,
    make_combo,
    make_double,
    make_int,
    make_line,
    make_readonly,
    make_text,
)


class SymbolPanel(ConfigPanel):
    section = "symbol"

    def build(self) -> None:
        cfg = self._store.config
        combo = make_combo(enum_items(Symbology), cfg.symbol.symbology)
        # Unimplemented symbologies stay visible but are disabled and explain
        # themselves - a silent substitution would be far worse than a refusal.
        model = combo.model()
        for i, member in enumerate(getattr(combo, COMBO_VALUES, [])):
            if member.implemented:
                continue
            combo.setItemText(i, f"{member.display_name}  (not implemented)")
            item = model.item(i)
            if item is not None:
                item.setEnabled(False)
                item.setToolTip(PLACEHOLDER_REASONS.get(member, ""))
        self.add_row("symbology", "Code type", combo)

        self.add_row(
            "qr_ecc", "QR error correction",
            make_combo([(m.value, m) for m in QrEcc], cfg.symbol.qr_ecc),
            tooltip="QR only. Level M is the usual choice for a clean printed strip.",
        )
        self.add_row(
            "qr_version", "QR version",
            make_int(cfg.symbol.qr_version, minimum=0, maximum=40),
            tooltip="0 selects the smallest version that fits the payload.",
        )
        self.add_note(
            "Data Matrix is roughly twice as coarse as QR for the same payload "
            "(10x10 vs 21x21 modules), which is why industrial position tape uses it."
        )

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        # The two QR parameters do nothing under Data Matrix, which is the
        # default. Left live they invite the user to set an error-correction
        # level, watch nothing change, and conclude the setting is broken.
        is_qr = cfg.symbol.symbology is Symbology.QR
        for field in ("symbol.qr_ecc", "symbol.qr_version"):
            self.set_row_enabled(field, is_qr)


class PositionPanel(ConfigPanel):
    section = "position"

    def build(self) -> None:
        cfg = self._store.config
        #: Set by load(); None until the first derive lands, and the length
        #: handler needs the cell, so it stays inert until then.
        self._derived: DerivedGeometry | None = None

        # The length row comes first: it is the number the user actually has,
        # and in Simple mode it is the only editable thing in this section -
        # the index range below is derived from it. Same mechanism as the job
        # bar's travel box, and the two mirror each other.
        self.travel = make_double(0.0, minimum=0.0, maximum=1_000_000.0, step=10.0,
                                  decimals=1)
        self.add_virtual_row(
            "position.travel_mm", "Length to cover", self.travel,
            self._on_travel_edited,
            suffix="mm",
            tooltip=(
                "How much of the axis the strip must cover - the number you "
                "measured on the machine.\n\n"
                "Type it and the number of codes adjusts itself: the range is "
                "rounded up to the next whole code, because stopping short "
                "would leave the end of the axis with no code over it. The "
                "readouts below show what it produced. Same value as the "
                "Axis travel box in the bar above; edit either."
            ),
        )

        self.add_row("start_index", "Start index", make_int(cfg.position.start_index, maximum=999999))
        self.add_row("end_index", "End index", make_int(cfg.position.end_index, maximum=999999))
        self.add_row(
            "increment", "Increment",
            make_int(cfg.position.increment, minimum=1, maximum=10000),
        )
        self.add_row(
            "pitch_mode", "Pitch mode",
            make_combo(
                [("Per cell (contiguous)", PitchMode.PER_CELL),
                 ("Per index (blanks inserted)", PitchMode.PER_INDEX)],
                cfg.position.pitch_mode,
            ),
            tooltip=(
                "With an increment above 1 these differ. Per cell keeps the tape "
                "contiguous and derives position from the cell ordinal; per index "
                "inserts blank cells so Position = Index x Pitch holds literally."
            ),
        )
        self.add_row(
            "direction", "Direction",
            make_combo(enum_items(Direction), cfg.position.direction),
        )
        self.add_row(
            "origin_mm", "Origin offset",
            make_double(cfg.position.origin_mm, minimum=-1e6, maximum=1e6),
            suffix="mm",
            tooltip="Machine position of the first printed index.",
        )
        self.add_row(
            "datum", "Position datum",
            make_combo(
                [("Symbol centre", Datum.SYMBOL_CENTRE),
                 ("Cell leading edge", Datum.CELL_LEADING_EDGE)],
                cfg.position.datum,
            ),
            tooltip="Affects the mounting diagram on the guide page.",
        )

        self.formula = make_readonly("")
        self.add_readout("Position formula", self.formula)

        self.codes = make_readonly("")
        self.add_readout("Number of codes", self.codes)

        self.length = make_readonly("")
        self.add_readout("Strip length", self.length, suffix="mm")

    def _on_travel_edited(self, value: float) -> None:
        """Turn the length into an index range, exactly as the job bar does."""
        derived = self._derived
        if derived is None:
            return
        pos = self._store.config.position
        end = end_index_for_travel(value, pos, derived.cell)
        if end != pos.end_index:
            self._store.update_section("position", end_index=end)

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        #: Kept so the length row can convert against the current cell.
        self._derived = derived
        if derived is not None:
            # Mirror the achieved travel, guarded by refresh()'s loading flag
            # so the write-back cannot re-trigger the edit handler.
            achieved = travel_mm(cfg.position, derived.cell)
            if abs(self.travel.value() - achieved) > 5e-2:
                self.travel.setValue(achieved)
            self.formula.setText(derived.position_formula)
            self.codes.setText(str(derived.code_count))
            self.length.setText(f"{derived.total_length_mm:.1f}")
        else:
            for editor in (self.formula, self.codes, self.length):
                editor.setText("-")


class PayloadPanel(ConfigPanel):
    section = "payload"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "digits", "Digits (zero padding)",
            make_int(cfg.payload.digits, minimum=1, maximum=18),
        )
        self.add_row(
            "unit_scale", "Payload resolution",
            make_combo(
                [("1 mm", 1), ("0.1 mm", 10), ("0.01 mm", 100)], cfg.payload.unit_scale
            ),
            tooltip=(
                "A fractional pitch cannot be represented in whole millimetres. "
                "Encoding tenths or hundredths keeps the payload an integer, which "
                "a PLC parses far more easily than a decimal string."
            ),
        )
        self.add_row("prefix", "Prefix", make_line(cfg.payload.prefix, "optional"))
        self.add_row("suffix", "Suffix", make_line(cfg.payload.suffix, "optional"))

        self.example = make_readonly("")
        self.add_readout("Example payload", self.example)
        self.add_note(
            "Each symbol encodes its own absolute position in millimetres, so the "
            "strip is self-describing and the human-readable text is exactly what "
            "the reader decodes."
        )

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        if derived is not None and derived.payloads:
            sample = ", ".join(derived.payloads[:3])
            self.example.setText(f"{sample} ... {derived.payloads[-1]}")
        else:
            self.example.setText("-")


class DimensionPanel(ConfigPanel):
    section = "dimensions"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "lr_margin_mode", "Margin mode",
            make_combo(
                [("Margin derived from pitch", LrMarginMode.DERIVED_FROM_PITCH),
                 ("Margin drives pitch", LrMarginMode.DRIVES_PITCH)],
                cfg.dimensions.lr_margin_mode,
            ),
            tooltip=(
                "Pitch, symbol size and margin are related by "
                "pitch = symbol + 2 x margin, so one of them must be derived."
            ),
        )
        self.pitch = make_double(cfg.dimensions.pitch_mm, minimum=0.1, maximum=1000.0)
        self.add_row("pitch_mm", "Cell pitch", self.pitch, suffix="mm")
        self.add_row(
            "symbol_size_mm", "Symbol size",
            make_double(cfg.dimensions.symbol_size_mm, minimum=0.1, maximum=1000.0),
            suffix="mm",
        )
        self.margin = make_double(cfg.dimensions.margin_lr_mm, minimum=0.0, maximum=500.0)
        self.add_row(
            "margin_lr_mm", "White margin L/R", self.margin, suffix="mm",
            tooltip="Read-only while the margin is derived from the pitch.",
        )
        self.add_row(
            "quiet_zone_mm", "Quiet zone",
            make_double(cfg.dimensions.quiet_zone_mm, minimum=0.0, maximum=100.0),
            suffix="mm",
            tooltip=(
                "Carved out of the white margin, never added to the cell. Data Matrix "
                "requires 1 module; QR requires 4."
            ),
        )
        self.add_row(
            "strip_height_mm", "Strip height",
            make_double(cfg.dimensions.strip_height_mm, minimum=1.0, maximum=1000.0),
            suffix="mm",
        )
        self.add_row(
            "symbol_v_offset_mm", "Symbol V offset",
            make_double(cfg.dimensions.symbol_v_offset_mm, minimum=-500.0, maximum=500.0),
            suffix="mm",
        )
        self.clearance = make_readonly("")
        self.add_readout("Splice clearance", self.clearance, suffix="mm")

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        derived_margin = cfg.dimensions.lr_margin_mode is LrMarginMode.DERIVED_FROM_PITCH
        self.margin.setReadOnly(derived_margin)
        self.margin.setEnabled(not derived_margin)
        self.pitch.setEnabled(derived_margin)
        if derived is not None:
            self.margin.setValue(derived.cell.margin_lr_mm)
            if not derived_margin:
                self.pitch.setValue(derived.cell.pitch_mm)
            self.clearance.setText(
                f"{derived.cell.splice_clearance_um / 1000:.2f} "
                f"(need {derived.cell.quiet_zone_mm:.2f})"
            )
        else:
            self.clearance.setText("-")


class DesignPanel(ConfigPanel):
    """What the printed page looks like, as opposed to which files come out.

    The style combo is deliberately *not* bound to a config field. There is no
    stored style - it is derived from the switches below by `detect_style`, so
    the two can never drift apart. Selecting a style writes the switches;
    touching a switch moves the combo to Custom on the next refresh.
    """

    section = "output"

    def build(self) -> None:
        cfg = self._store.config

        # A virtual row so Simple mode can carry it: there is no stored style
        # field, but "plain codes or full furniture" is a Simple-grade choice.
        self.style_combo = make_combo(
            [(s.display_name, s) for s in PrintStyle], detect_style(cfg)
        )
        self.add_virtual_row(
            "design.style", "Print style", self.style_combo, self._apply_style_choice,
            tooltip=(
                "What the printed page carries besides the codes themselves.\n\n"
                "Labelled prints the position under every code; Plain is codes "
                "only; Engineering adds the ruler and full page furniture. "
                "Picking one sets all the switches below in a single undoable "
                "step; changing any switch by hand shows as Custom."
            ),
        )

        self.style_note = self.add_note("")

        self.add_row("human_readable", "", make_check("Position printed under each symbol",
                                                      cfg.output.human_readable))
        self.add_row(
            "hr_position", "Text position",
            make_combo([("Below symbol", HrPosition.BELOW), ("Above symbol", HrPosition.ABOVE)],
                       cfg.output.hr_position),
        )
        self.add_row(
            "hr_font_pt", "Text size",
            make_double(cfg.output.hr_font_pt, minimum=3.0, maximum=24.0, step=0.5, decimals=1),
            suffix="pt",
        )
        self.add_row("engineering_ruler", "", make_check("Engineering ruler (scale)",
                                                         cfg.output.engineering_ruler))
        self.add_row(
            "ruler_position", "Ruler position",
            make_combo([("Below strip", RulerPosition.BELOW), ("Above strip", RulerPosition.ABOVE)],
                       cfg.output.ruler_position),
        )
        self.add_row("calibration_bar", "", make_check("Calibration bar",
                                                       cfg.output.calibration_bar),
                     tooltip=(
                         "The only printed means of proving the sheet came out at true "
                         "size. Without it a strip that is silently 0.2 % short looks "
                         "exactly like a correct one."
                     ))
        self.add_row(
            "calibration_scope", "Calibration on",
            make_combo(
                [("Every page", PageScope.EVERY_PAGE), ("First page only", PageScope.FIRST_PAGE)],
                cfg.output.calibration_scope,
            ),
        )
        self.add_row("page_header_footer", "", make_check("Page header and footer",
                                                          cfg.output.page_header_footer),
                     tooltip=(
                         "Title band above the strip, and the identification band below "
                         "it carrying the sheet number, absolute X range, revision and "
                         "fingerprint."
                     ))
        self.add_row("instruction_page", "", make_check("Installation guide page",
                                                        cfg.output.instruction_page))
        self.add_row("registration_marks", "", make_check("Registration marks",
                                                          cfg.printing.registration_marks),
                     section="printing")
        self.add_row("cut_marks", "", make_check("Cut marks and strip outline",
                                                 cfg.printing.cut_marks), section="printing")
        self.add_row("splice_labels", "", make_check("Splice boundary labels",
                                                     cfg.printing.splice_labels),
                     section="printing")
        self.add_row("alignment_arrows", "", make_check("Alignment arrows",
                                                        cfg.printing.alignment_arrows),
                     section="printing")

    def _apply_style_choice(self, style: object) -> None:
        """Write every switch the chosen style controls, as one undo step.

        The loading guard lives in the virtual row's wiring; Custom is what a
        configuration reports, not a preset, so choosing it changes nothing.
        """
        flags = STYLE_FLAGS.get(style)
        if flags is not None:
            self._store.update_sections(**flags)

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        style = detect_style(cfg)
        values = getattr(self.style_combo, COMBO_VALUES, [])
        if style in values:
            index = values.index(style)
            if index != self.style_combo.currentIndex():
                self.style_combo.setCurrentIndex(index)
        self.style_note.setText(style.description)

        # Options belonging to a switch that is off.
        self.set_row_enabled("output.hr_position", cfg.output.human_readable)
        self.set_row_enabled("output.hr_font_pt", cfg.output.human_readable)
        self.set_row_enabled("output.ruler_position", cfg.output.engineering_ruler)
        self.set_row_enabled("output.calibration_scope", cfg.output.calibration_bar)


class OutputPanel(ConfigPanel):
    section = "output"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row("tiled_pages", "", make_check("A4 / sheet tiles", cfg.output.tiled_pages))
        self.add_row("continuous", "", make_check("Continuous PDF", cfg.output.continuous))
        rows_spin = make_int(cfg.output.rows_per_sheet, minimum=0, maximum=40)
        rows_spin.setSpecialValueText("Auto - fill the sheet")
        self.add_row(
            "rows_per_sheet", "Rows per sheet", rows_spin,
            tooltip=(
                "How many strip rows the Multi-Row export stacks on each "
                "sheet. Auto fills the page - a 20 mm band fits five or six "
                "rows on A4, so a 2 m strip lands on 2 sheets instead of 9.\n\n"
                "Only the Export Multi-Row button uses this; Export PDF always "
                "prints the classic one row per sheet."
            ),
        )
        self.add_row(
            "continuous_strategy", "Oversize strategy",
            make_combo(
                [("UserUnit (one true-size page)", ContinuousStrategy.USER_UNIT),
                 ("Raw oversize page", ContinuousStrategy.RAW_OVERSIZE),
                 ("Split into rolls", ContinuousStrategy.SPLIT_ROLL)],
                cfg.output.continuous_strategy,
            ),
            tooltip=(
                "A strip longer than 5080 mm exceeds the PDF page limit. UserUnit "
                "keeps one page that still measures true size; raw oversize is "
                "accepted by many large-format RIPs but refused by Acrobat; split "
                "rolls are universally safe but must be spliced."
            ),
        )
        self.add_row(
            "continuous_max_length_mm", "Max roll length",
            make_double(cfg.output.continuous_max_length_mm, minimum=100.0, maximum=50000.0,
                        step=100.0, decimals=1),
            suffix="mm",
        )
        self.add_note("Page furniture - rulers, calibration bar, marks - is in Design.")
        self.add_row(
            "verify_mode", "Decode verification",
            make_combo(
                [("Sample (recommended)", VerifyMode.SAMPLE), ("Every symbol", VerifyMode.ALL),
                 ("Off", VerifyMode.OFF)],
                cfg.output.verify_mode,
            ),
            tooltip=(
                "Re-reads exported symbols through a real decoder before the file is "
                "written. Sampling sixteen codes costs about half a second and turns "
                "'probably right' into evidence."
            ),
        )
        self.add_row(
            "verify_sample_count", "Verify sample size",
            make_int(cfg.output.verify_sample_count, minimum=2, maximum=500),
        )


class PaperPanel(ConfigPanel):
    section = "paper"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "preset", "Paper size",
            make_combo([(m.display_name, m) for m in PaperPreset], cfg.paper.preset),
            tooltip=(
                "Sheet sizes tile the strip across pages. A label-printer roll prints "
                "it continuously instead, with no page boundaries to cut or align - "
                "which is why a thermal-transfer label printer on continuous polyester "
                "is the best match for this job."
            ),
        )
        self.add_row(
            "orientation", "Orientation",
            make_combo([("Landscape", Orientation.LANDSCAPE), ("Portrait", Orientation.PORTRAIT)],
                       cfg.paper.orientation),
        )
        self.width = make_double(cfg.paper.custom_width_mm, minimum=10.0, maximum=10000.0, decimals=1)
        self.height = make_double(cfg.paper.custom_height_mm, minimum=10.0, maximum=10000.0, decimals=1)
        self.add_row("custom_width_mm", "Custom width", self.width, suffix="mm")
        self.add_row("custom_height_mm", "Custom height", self.height, suffix="mm")
        for field, label in (
            ("margin_top_mm", "Margin top"),
            ("margin_bottom_mm", "Margin bottom"),
            ("margin_left_mm", "Margin left"),
            ("margin_right_mm", "Margin right"),
        ):
            self.add_row(
                field, label,
                make_double(getattr(cfg.paper, field), minimum=0.0, maximum=200.0, decimals=1),
                suffix="mm",
            )
        self.usable = make_readonly("")
        self.add_readout("Usable area", self.usable)

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        custom = cfg.paper.preset is PaperPreset.CUSTOM
        self.width.setEnabled(custom)
        self.height.setEnabled(custom)
        w, h = cfg.paper.sheet_size_mm()
        if cfg.paper.preset.is_roll:
            # Roll length is unbounded, so a "sheet size" readout would be a
            # fiction; the width across the roll is the real constraint.
            self.usable.setText(
                f"{cfg.paper.usable_height_mm():.1f} mm across a "
                f"{cfg.paper.preset.roll_width_mm:.0f} mm roll, continuous length"
            )
        else:
            self.usable.setText(
                f"{cfg.paper.usable_width_mm():.1f} x {cfg.paper.usable_height_mm():.1f} "
                f"of {w:.0f} x {h:.0f} mm"
            )


class PrintPanel(ConfigPanel):
    section = "printing"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "scale_percent", "Printer scaling",
            make_double(cfg.printing.scale_percent, minimum=1.0, maximum=200.0, step=0.1),
            suffix="%",
            tooltip="Scales all artwork including the calibration bar.",
        )
        self.add_row(
            "calibration_length_mm", "Calibration length",
            make_double(cfg.printing.calibration_length_mm, minimum=10.0, maximum=1000.0,
                        step=10.0, decimals=1),
            suffix="mm",
        )
        self.add_row(
            "leading_margin_mm", "Leading margin",
            make_double(cfg.printing.leading_margin_mm, maximum=5000.0, decimals=1), suffix="mm",
        )
        self.add_row(
            "trailing_margin_mm", "Trailing margin",
            make_double(cfg.printing.trailing_margin_mm, maximum=5000.0, decimals=1), suffix="mm",
        )
        # The on/off switches for these live in Design, with the print style
        # that owns them; what belongs here is their size.
        self.add_row(
            "registration_mark_size_mm", "Registration mark size",
            make_double(cfg.printing.registration_mark_size_mm, minimum=1.0, maximum=50.0,
                        step=0.5, decimals=1),
            suffix="mm",
        )
        self.add_row(
            "cut_mark_length_mm", "Cut mark length",
            make_double(cfg.printing.cut_mark_length_mm, minimum=1.0, maximum=50.0,
                        step=0.5, decimals=1),
            suffix="mm",
        )
        self.add_row(
            "cut_line_across_strip", "",
            make_check("Cut line across strip", cfg.printing.cut_line_across_strip),
            tooltip="Off by default: ink drawn through the strip band can confuse a reader.",
        )
        self.add_row(
            "splice_mode", "Splice mode",
            make_combo([("Butt", SpliceMode.BUTT), ("Overlap", SpliceMode.OVERLAP)],
                       cfg.printing.splice_mode),
        )
        self.add_row(
            "splice_overlap_mm", "Splice overlap",
            make_double(cfg.printing.splice_overlap_mm, maximum=100.0, step=0.5), suffix="mm",
        )


class MediaPanel(ConfigPanel):
    section = "media"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "media", "Substrate",
            make_combo(enum_items(Media), cfg.media.media),
            tooltip=(
                "Paper moves about 3 % between 20 % and 80 % relative humidity - "
                "hundreds of millimetres over a long strip. Polyester film moves "
                "about 0.006 %."
            ),
        )
        self.add_row(
            "method", "Print method",
            make_combo(enum_items(PrintMethod), cfg.media.method),
        )
        self.add_row(
            "ribbon", "Ribbon",
            make_combo([(m.value.replace("_", "-").capitalize(), m) for m in Ribbon],
                       cfg.media.ribbon),
            tooltip="Thermal transfer only. Resin on polyester is the 5+ year choice.",
        )
        self.add_row("adhesive_backed", "", make_check("Self-adhesive backing", cfg.media.adhesive_backed))

        # The plain question the two swing fields below actually ask. A
        # virtual row, like the print style: nothing is stored, the choice
        # writes the numbers and hand-tuned numbers read back as Custom.
        self.climate_combo = make_combo(
            [(c.display_name, c) for c in Climate], detect_climate(cfg.media)
        )
        self.add_virtual_row(
            "media.climate", "Environment", self.climate_combo,
            self._apply_climate_choice,
            tooltip=(
                "Where the machine stands. Sets the temperature and humidity "
                "swings the accuracy model uses - a climate-controlled room "
                "moves the strip a fraction of what an unconditioned shed "
                "does.\n\nThe exact numbers live in Advanced; editing them by "
                "hand shows here as Custom."
            ),
        )
        self.climate_note = self.add_note("")

        self.add_row(
            "rh_swing_percent", "Humidity swing",
            make_double(cfg.media.rh_swing_percent, minimum=0.0, maximum=100.0, step=5.0, decimals=0),
            suffix="%",
            tooltip="Expected in-service relative humidity range.",
        )
        self.add_row(
            "dim_stability_pct_per_rh", "Stability override",
            make_double(cfg.media.dim_stability_pct_per_rh, minimum=0.0, maximum=1.0,
                        step=0.001, decimals=4),
            suffix="%/%RH",
            tooltip="0 uses the published figure for the selected substrate.",
        )
        self.add_row(
            "temp_swing_deg_c", "Temperature swing",
            make_double(cfg.media.temp_swing_deg_c, minimum=0.0, maximum=200.0, step=5.0, decimals=0),
            suffix="C",
            tooltip=(
                "Expected in-service temperature range. On polyester this moves the "
                "strip about twelve times further than humidity does."
            ),
        )
        self.add_row(
            "frame_material", "Mounted on",
            make_combo([(m.display_name, m) for m in FrameMaterial], cfg.media.frame_material),
            tooltip=(
                "Only the difference between substrate and frame expansion reaches the "
                "reading. Aluminium expands faster than polyester, steel slower, so the "
                "error changes sign between them."
            ),
        )
        self.add_row(
            "mounting", "Mounting",
            make_combo([(m.display_name, m) for m in TapeMounting], cfg.media.mounting),
            tooltip=(
                "Bonded along its full length, the strip follows the frame and thermal "
                "error largely cancels - the strain goes into the adhesive instead. "
                "Anchored at one end, it expands freely and the full difference reaches "
                "the reading."
            ),
        )
        self.add_row(
            "cte_ppm_per_c", "Expansion override",
            make_double(cfg.media.cte_ppm_per_c, minimum=0.0, maximum=500.0,
                        step=1.0, decimals=1),
            suffix="ppm/C",
            tooltip="0 uses the published figure for the selected substrate.",
        )
        self.add_row("dpi", "Printer resolution",
                     make_combo([("203 dpi", 203), ("300 dpi", 300), ("600 dpi", 600),
                                 ("1200 dpi", 1200), ("2400 dpi", 2400)], cfg.printer.dpi),
                     section="printer")
        self.add_row(
            "unprintable_margin_mm", "Unprintable border",
            make_double(cfg.printer.unprintable_margin_mm, maximum=50.0, decimals=1),
            suffix="mm", section="printer",
        )
        max_piece = make_double(cfg.printer.max_label_length_mm, minimum=0.0,
                                maximum=20000.0, step=10.0, decimals=0)
        max_piece.setSpecialValueText("Not stated")
        self.add_row(
            "max_label_length_mm", "Max piece length", max_piece, suffix="mm",
            section="printer",
            tooltip=(
                "The longest single piece the printer can print - a label "
                "printer's firmware limit (a Zebra ZD230 stops at 990 mm). "
                "The ZPL export splits the strip at it; device presets fill "
                "it in. 0 = not stated."
            ),
        )
        self.measured = make_double(
            cfg.printer.measured_calibration_mm, minimum=1.0, maximum=1000.0, step=0.1
        )
        self.add_row(
            "measured_calibration_mm", "Measured bar", self.measured, suffix="mm",
            section="printer",
            tooltip="What the calibration bar actually measured on the proof print.",
        )

        self.apply_button = QPushButton("Apply measurement -> printer scaling", self)
        self.apply_button.clicked.connect(self._apply_calibration)
        self.add_widget(self.apply_button)

        self.dots = make_readonly("")
        self.add_readout("Module in dots", self.dots)

    def _apply_calibration(self) -> None:
        """Derive the scaling percentage so the engineer does not do the arithmetic."""
        cfg = self._store.config
        nominal = cfg.printing.calibration_length_mm
        scale = cfg.printer.derived_scale_percent(nominal)
        self._store.update_section("printing", scale_percent=round(scale, 3))

    def _apply_climate_choice(self, climate: object) -> None:
        """Write the swings the chosen climate stands for, as one undo step."""
        swings = CLIMATE_SWINGS.get(climate)
        if swings is not None:
            self._store.update_section("media", **swings)

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        climate = detect_climate(cfg.media)
        values = getattr(self.climate_combo, COMBO_VALUES, [])
        if climate in values:
            index = values.index(climate)
            if index != self.climate_combo.currentIndex():
                self.climate_combo.setCurrentIndex(index)
        self.climate_note.setText(climate.description)

        self.apply_button.setEnabled(
            abs(cfg.printer.measured_calibration_mm - cfg.printing.calibration_length_mm) > 1e-6
        )
        if derived is not None:
            acc = derived.accuracy
            verdict = "OK" if acc.module_dots >= 5 else ("marginal" if acc.module_dots >= 3 else "TOO FINE")
            self.dots.setText(f"{acc.module_dots:.1f} dots ({verdict})")
        else:
            self.dots.setText("-")


class ScannerPanel(ConfigPanel):
    section = "scanner"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row(
            "min_codes_in_view", "Codes in view",
            make_int(cfg.scanner.min_codes_in_view, minimum=1, maximum=10),
            tooltip=(
                "How many complete codes must be visible at every position. "
                "Industrial readers commonly use 3 so the tape can be damaged "
                "without losing position. Required field of view = N x pitch + symbol."
            ),
        )
        self.add_row(
            "px_per_module", "Pixels per module",
            make_double(cfg.scanner.px_per_module, minimum=1.0, maximum=40.0, step=0.5, decimals=1),
        )
        self.add_row(
            "sensor_width_mm", "Sensor width",
            make_double(cfg.scanner.sensor_width_mm, minimum=1.0, maximum=60.0, step=0.1, decimals=2),
            suffix="mm",
            tooltip="4.8 mm is a 1/3 inch sensor.",
        )
        self.add_row(
            "mount_tilt_deg", "Mount tilt",
            make_double(cfg.scanner.mount_tilt_deg, minimum=0.0, maximum=45.0, step=1.0, decimals=0),
            suffix="deg",
            tooltip="Tilt off normal to avoid specular return from the tape.",
        )
        self.fov = make_readonly("")
        self.add_readout("Required FOV", self.fov, suffix="mm")
        self.add_note(
            "Field of view is set by the pitch, not the symbol size. Below the "
            "required value there are blind zones where no complete code is visible "
            "and absolute position is lost."
        )

        for field, label, maximum, suffix in (
            ("fov_angle_deg", "View angle across", 170.0, "deg"),
            ("fov_vertical_deg", "View angle down", 170.0, "deg"),
            ("dof_min_mm", "Focuses from", 10000.0, "mm"),
            ("dof_max_mm", "Focuses to", 10000.0, "mm"),
        ):
            self.add_row(
                field, label,
                make_double(getattr(cfg.scanner, field), minimum=0.0, maximum=maximum,
                            step=1.0, decimals=1),
                suffix=suffix,
            )
        self.add_row(
            "sensor_px_h", "Sensor pixels across",
            make_int(cfg.scanner.sensor_px_h, minimum=0, maximum=20000, step=64),
        )
        self.add_row(
            "mount_distance_mm", "Mounting distance",
            make_double(cfg.scanner.mount_distance_mm, minimum=0.0, maximum=10000.0,
                        step=5.0, decimals=1),
            suffix="mm",
        )

        self.mount = make_readonly("")
        self.add_readout("Mount this far away", self.mount, suffix="mm")
        self.window = make_readonly("")
        self.add_readout("Window at that distance", self.window)
        self.budget = make_readonly("")
        self.add_readout("Room for", self.budget)

        self.fit_button = QPushButton("Fit spacing to mounting distance", self)
        self.fit_button.clicked.connect(self._fit_to_distance)
        self.add_widget(self.fit_button)

        self.add_note(
            "Leave the mounting distance at 0 and the tool works forwards: pick a "
            "geometry, and it reports the distance that geometry demands. Set it, "
            "and the calculation inverts - the distance and the view angle fix how "
            "much window there is, and the geometry has to fit inside it."
        )

        # -- reading while the axis moves ----------------------------------
        self.add_row(
            "axis_speed_mm_per_s", "Axis speed",
            make_double(cfg.scanner.axis_speed_mm_per_s, minimum=0.0, maximum=100000.0,
                        step=50.0, decimals=0),
            suffix="mm/s",
            tooltip=(
                "How fast the axis travels while the reader is working.\n\n"
                "Leave at 0 if the strip is only read standing still - the motion "
                "checks switch off entirely rather than quoting a speed limit for a "
                "machine that has no speed.\n\n"
                "Enter a speed and two things get checked that the geometry alone "
                "cannot tell you: whether the image smears further than one module "
                "during the exposure, and whether a code stays in the window long "
                "enough for the camera to catch a frame of it."
            ),
        )
        self.add_row(
            "exposure_us", "Reader exposure",
            make_int(cfg.scanner.exposure_us, minimum=0, maximum=60000, step=50),
            suffix="us",
            tooltip=(
                "How long the reader's shutter stays open, in microseconds.\n\n"
                "This is the number that decides how fast you can go. The code "
                "travels while the shutter is open, and the image smears by that "
                "distance - so a 1.000 mm module at the NVF230's default 1000 us "
                "tolerates 1.0 m/s and no more.\n\n"
                "Shortening it buys speed but needs more light or more gain to stay "
                "bright enough to decode. The NVF230 accepts 60 to 60000 us."
            ),
        )
        self.add_row(
            "frames_per_code", "Frames per code",
            make_int(cfg.scanner.frames_per_code, minimum=1, maximum=16),
            tooltip=(
                "How many camera frames must catch each code before the read is "
                "trusted.\n\n"
                "One is the bare minimum and no redundancy at all - a single dropped "
                "frame is a lost code. Two or three is what makes it reliable, and it "
                "costs speed in direct proportion."
            ),
        )
        self.add_row(
            "frame_interval_ms", "Frame interval",
            make_double(cfg.scanner.frame_interval_ms, minimum=1.0, maximum=1000.0,
                        step=1.0, decimals=1),
            suffix="ms",
            tooltip=(
                "Time between the reader's captures. 20 ms means 50 frames a "
                "second, which is the NVF230's rate.\n\n"
                "Together with the window width this sets the hard speed ceiling: a "
                "code that crosses the field of view in less than one interval can "
                "pass through without any frame catching it, however sharp the image "
                "would have been."
            ),
        )
        self.speed_limit = make_readonly("")
        self.add_readout("Speed limit", self.speed_limit, suffix="mm/s")
        self.smear = make_readonly("")
        self.add_readout("Smear at that speed", self.smear)
        self.add_note(
            "Module size is a motion decision as well as a printing one: the "
            "tolerable speed scales directly with it. Doubling the code size "
            "doubles how fast the axis can run."
        )

    def _fit_to_distance(self) -> None:
        """Widen or narrow the spacing to use the window exactly."""
        derived = self._derived
        if derived is None or not derived.scanner.distance_is_fixed:
            return
        target = derived.scanner.max_pitch_mm
        floor = derived.cell.symbol_mm + 2 * derived.cell.quiet_zone_mm
        if target >= floor:
            self._store.update_section("dimensions", pitch_mm=round(target, 3))

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        #: Kept so the Fit button can act on the current derived geometry.
        self._derived = derived

        if derived is None:
            for editor in (self.fov, self.mount, self.window, self.budget):
                editor.setText("-")
            self.fit_button.setEnabled(False)
            return

        rec = derived.scanner
        self.fov.setText(f"{rec.fov_continuous_mm:.1f}")

        if not rec.has_reader_spec:
            self.mount.setText("- (enter a view angle)")
        elif rec.distance_is_fixed:
            self.mount.setText("fixed below")
        else:
            # Below the near focus limit the view is only wider, which is safe;
            # say so rather than quoting a distance the reader cannot focus at.
            floor = cfg.scanner.dof_min_mm
            if floor > 0 and rec.required_wd_mm < floor:
                self.mount.setText(f"{floor:.0f} or more (nearest focus)")
            else:
                self.mount.setText(f"{rec.required_wd_mm:.0f}")

        if rec.distance_is_fixed:
            sign = "+" if rec.fov_headroom_mm >= 0 else ""
            self.window.setText(
                f"{rec.available_fov_mm:.0f} mm  ({sign}{rec.fov_headroom_mm:.0f} mm spare)"
            )
            self.budget.setText(
                f"spacing up to {rec.max_pitch_mm:.0f} mm, or a code up to "
                f"{rec.max_symbol_mm:.0f} mm"
            )
            floor = derived.cell.symbol_mm + 2 * derived.cell.quiet_zone_mm
            self.fit_button.setEnabled(rec.max_pitch_mm >= floor)
        else:
            self.window.setText("- (set a mounting distance)")
            self.budget.setText("-")
            self.fit_button.setEnabled(False)

        self._show_motion(cfg, derived)

    def _show_motion(self, cfg: AopsConfig, derived: DerivedGeometry) -> None:
        """Report the speed ceiling and what the stated speed spends against it."""
        limits = motion_limits(
            module_mm=derived.cell.module_mm(derived.matrix_cols),
            # Only the window actually established by a mounting distance; the
            # required FOV is a demand, not a measurement, and treating it as
            # the window would invent a frame-rate limit nobody is subject to.
            fov_mm=derived.scanner.available_fov_mm,
            exposure_us=cfg.scanner.exposure_us,
            frames_wanted=cfg.scanner.frames_per_code,
            frame_interval_ms=cfg.scanner.frame_interval_ms,
            requested_speed_mm_per_s=cfg.scanner.axis_speed_mm_per_s,
        )
        top = limits.max_speed_mm_per_s
        if top <= 0.0:
            self.speed_limit.setText("-")
            self.smear.setText("-")
            return

        self.speed_limit.setText(f"{top:.0f}   (set by the {limits.limited_by})")
        if not limits.is_specified:
            self.smear.setText("- (enter an axis speed)")
            return

        verdict = "fits" if limits.fits else "too fast"
        text = f"{limits.smear_mm:.3f} mm = {limits.smear_modules:.1f} modules"
        if limits.fov_mm > 0.0:
            frames = frames_on_a_code(
                limits.fov_mm, limits.requested_speed_mm_per_s, cfg.scanner.frame_interval_ms
            )
            text += f", {frames:.1f} frames per code"
        self.smear.setText(f"{text} - {verdict}")


class ProjectPanel(ConfigPanel):
    section = "project"

    def build(self) -> None:
        cfg = self._store.config
        for field, label, placeholder in (
            ("machine", "Machine name", "e.g. GANTRY-01"),
            ("project", "Project name", "e.g. LINE 4 RETROFIT"),
            ("strip_id", "Strip ID", "e.g. AX1-POS-001"),
            ("revision", "Revision", "A"),
            ("engineer", "Engineer", ""),
            ("company", "Company", ""),
        ):
            self.add_row(field, label, make_line(getattr(cfg.project, field), placeholder))
        self.add_row("comments", "Comments", make_text(cfg.project.comments, rows=3))


#: (accordion key, title, panel class) in display order.
PANEL_SPECS: tuple[tuple[str, str, type[ConfigPanel]], ...] = (
    ("symbol", "Symbol type", SymbolPanel),
    ("position", "Position parameters", PositionPanel),
    ("payload", "Payload encoding", PayloadPanel),
    ("dimensions", "Strip dimensions", DimensionPanel),
    ("design", "Design and page furniture", DesignPanel),
    ("output", "Output options", OutputPanel),
    ("paper", "Paper", PaperPanel),
    ("printing", "Print", PrintPanel),
    ("media", "Media and printer", MediaPanel),
    ("scanner", "Scanner", ScannerPanel),
    ("project", "Project", ProjectPanel),
)
