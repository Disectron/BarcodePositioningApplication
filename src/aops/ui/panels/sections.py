"""The nine configuration sections of the left-hand panel."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from aops.core.config import AopsConfig
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


class PositionPanel(ConfigPanel):
    section = "position"

    def build(self) -> None:
        cfg = self._store.config
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

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        if derived is not None:
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


class OutputPanel(ConfigPanel):
    section = "output"

    def build(self) -> None:
        cfg = self._store.config
        self.add_row("tiled_pages", "", make_check("A4 / sheet tiles", cfg.output.tiled_pages))
        self.add_row("continuous", "", make_check("Continuous PDF", cfg.output.continuous))
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
        self.add_row("instruction_page", "", make_check("Installation guide page", cfg.output.instruction_page))
        self.add_row("calibration_bar", "", make_check("Calibration bar", cfg.output.calibration_bar))
        self.add_row(
            "calibration_scope", "Calibration on",
            make_combo(
                [("Every page", PageScope.EVERY_PAGE), ("First page only", PageScope.FIRST_PAGE)],
                cfg.output.calibration_scope,
            ),
        )
        self.add_row("engineering_ruler", "", make_check("Engineering ruler", cfg.output.engineering_ruler))
        self.add_row(
            "ruler_position", "Ruler position",
            make_combo([("Below strip", RulerPosition.BELOW), ("Above strip", RulerPosition.ABOVE)],
                       cfg.output.ruler_position),
        )
        self.add_row("human_readable", "", make_check("Human-readable index", cfg.output.human_readable))
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
            make_combo([(m.value.upper(), m) for m in PaperPreset], cfg.paper.preset),
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
        self.add_row("registration_marks", "", make_check("Registration marks", cfg.printing.registration_marks))
        self.add_row("cut_marks", "", make_check("Cut marks", cfg.printing.cut_marks))
        self.add_row(
            "cut_line_across_strip", "",
            make_check("Cut line across strip", cfg.printing.cut_line_across_strip),
            tooltip="Off by default: ink drawn through the strip band can confuse a reader.",
        )
        self.add_row("alignment_arrows", "", make_check("Alignment arrows", cfg.printing.alignment_arrows))
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

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
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

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        super().load(cfg, derived)
        if derived is not None:
            self.fov.setText(f"{derived.scanner.fov_continuous_mm:.1f}")
        else:
            self.fov.setText("-")


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
    ("output", "Output options", OutputPanel),
    ("paper", "Paper", PaperPanel),
    ("printing", "Print", PrintPanel),
    ("media", "Media and printer", MediaPanel),
    ("scanner", "Scanner", ScannerPanel),
    ("project", "Project", ProjectPanel),
)
