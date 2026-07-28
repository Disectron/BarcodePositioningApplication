"""Parameter, engineering and output summary panels.

These are read-only readouts of `DerivedGeometry`. Everything shown here is
computed, never entered, which is why they are visually flattened relative to
the editable panel on the left.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from aops.core.config import AopsConfig
from aops.core.stats import DerivedGeometry
from aops.ui.theme.palette import ERROR, OK, TEXT_DIM, WARNING
from aops.ui.widgets.field_row import SummaryGroup


class ParameterSummary(QWidget):
    """Identification and the headline strip numbers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(24)

        left = QVBoxLayout()
        right = QVBoxLayout()
        left.setSpacing(0)
        right.setSpacing(0)

        self.ident = SummaryGroup("Identification")
        for key, label in (
            ("machine", "Machine"),
            ("project", "Project"),
            ("strip", "Strip ID"),
            ("revision", "Revision"),
            ("fingerprint", "Fingerprint"),
        ):
            self.ident.add(key, label)
        left.addWidget(self.ident)

        self.geom = SummaryGroup("Geometry")
        for key, label in (
            ("symbology", "Code type"),
            ("pitch", "Cell pitch"),
            ("symbol", "Symbol size"),
            ("margin", "White margin"),
            ("quiet", "Quiet zone"),
            ("height", "Strip height"),
        ):
            self.geom.add(key, label)
        left.addWidget(self.geom)
        left.addStretch(1)

        self.output = SummaryGroup("Output")
        for key, label in (
            ("codes", "Number of codes"),
            ("length", "Strip length"),
            ("sheets", "Estimated pages"),
            ("files", "Output files"),
            ("size", "Estimated PDF size"),
            ("payload", "Payload example"),
        ):
            self.output.add(key, label)
        right.addWidget(self.output)

        self.accuracy = SummaryGroup("Print accuracy")
        for key, label in (
            ("dots", "Module in dots"),
            ("drift", "Humidity drift"),
            ("thermal", "Thermal drift"),
            ("cumulative", "Butt-splice error"),
            ("bounded", "Datum-aligned error"),
        ):
            self.accuracy.add(key, label)
        right.addWidget(self.accuracy)
        right.addStretch(1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 1)

    def update_from(
        self, cfg: AopsConfig, derived: DerivedGeometry | None, fingerprint: str
    ) -> None:
        p = cfg.project
        self.ident.set("machine", p.machine or "-")
        self.ident.set("project", p.project or "-")
        self.ident.set("strip", p.strip_id or "-")
        self.ident.set("revision", p.revision or "-")
        self.ident.set("fingerprint", fingerprint)

        if derived is None:
            for group in (self.geom, self.output, self.accuracy):
                for key in list(group._rows):
                    group.set(key, "-", TEXT_DIM)
            return

        c, acc = derived.cell, derived.accuracy
        self.geom.set("symbology", cfg.symbol.symbology.display_name)
        self.geom.set("pitch", f"{c.pitch_mm:.3f} mm")
        self.geom.set("symbol", f"{c.symbol_mm:.3f} mm")
        self.geom.set("margin", f"{c.margin_lr_mm:.3f} mm each side")
        self.geom.set("quiet", f"{c.quiet_zone_mm:.3f} mm")
        self.geom.set("height", f"{c.strip_height_mm:.3f} mm")

        files = []
        if cfg.output.tiled_pages:
            files.append(f"barcode_strip_{cfg.paper.preset.value}_tiles.pdf")
        if cfg.output.continuous:
            n = derived.continuous.roll_count
            name = "barcode_strip_continuous_signshop.pdf"
            files.append(f"{name} (x{n})" if n > 1 else name)

        self.output.set("codes", f"{derived.code_count}")
        self.output.set(
            "length", f"{derived.total_length_mm:.1f} mm  ({derived.total_length_mm / 1000:.3f} m)"
        )
        self.output.set("sheets", f"{derived.total_pdf_pages} ({len(derived.pages)} strip)")
        self.output.set("files", "\n".join(files) if files else "none selected",
                        None if files else WARNING)
        self.output.set("size", f"~{derived.estimated_pdf_bytes() / 1024:.0f} KB")
        self.output.set("payload", derived.payloads[0] if derived.payloads else "-")

        dots_colour = OK if acc.module_dots >= 5 else (WARNING if acc.module_dots >= 3 else ERROR)
        self.accuracy.set("dots", f"{acc.module_dots:.1f} dots @ {cfg.printer.dpi} dpi", dots_colour)
        drift_colour = OK if acc.media_drift_mm < c.pitch_mm / 4 else WARNING
        self.accuracy.set("drift", f"{acc.media_drift_mm:.2f} mm over strip", drift_colour)
        if acc.thermal_drift_mm <= 0.0:
            # Bonded: the differential is carried by the adhesive, not the reading.
            self.accuracy.set(
                "thermal", f"cancelled by bonding ({acc.bond_strain_ppm:.0f} ppm strain)", OK
            )
        else:
            thermal_colour = (
                ERROR
                if acc.thermal_drift_mm > c.pitch_mm / 2
                else (WARNING if acc.thermal_drift_mm > 1.0 else OK)
            )
            self.accuracy.set(
                "thermal", f"{acc.thermal_drift_mm:.2f} mm over strip", thermal_colour
            )
        self.accuracy.set(
            "cumulative",
            f"{acc.cumulative_error_mm:.1f} mm accumulated",
            ERROR if acc.cumulative_error_mm > 1.0 else OK,
        )
        self.accuracy.set("bounded", f"{acc.bounded_error_mm:.2f} mm per tile", OK)


class EngineeringSummary(QWidget):
    """Position mathematics and the reader-optics recommendation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(24)

        left = QVBoxLayout()
        right = QVBoxLayout()
        left.setSpacing(0)
        right.setSpacing(0)

        self.position = SummaryGroup("Position")
        for key, label in (
            ("formula", "Position formula"),
            ("per_code", "Distance per code"),
            ("max", "Maximum position"),
            ("resolution", "Resolution"),
            ("digits", "Payload digits"),
        ):
            self.position.add(key, label)
        left.addWidget(self.position)
        left.addStretch(1)

        self.scanner = SummaryGroup("Scanner recommendation")
        for key, label in (
            ("fov", "Required field of view"),
            ("static", "Static read window"),
            ("occlusion", "Occlusion tolerance"),
            ("sensor", "Sensor class"),
            ("wd", "Working distance"),
            ("mount", "Mount height"),
        ):
            self.scanner.add(key, label)
        right.addWidget(self.scanner)
        right.addStretch(1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 1)

    def update_from(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        if derived is None:
            for group in (self.position, self.scanner):
                for key in list(group._rows):
                    group.set(key, "-", TEXT_DIM)
            return

        rec = derived.scanner
        self.position.set("formula", derived.position_formula)
        self.position.set("per_code", f"{derived.distance_per_code_mm:.3f} mm")
        self.position.set("max", f"{derived.max_position_mm:.1f} mm")
        self.position.set(
            "resolution",
            f"{derived.cell.pitch_mm:.3f} mm per code"
            + (f" ({1.0 / cfg.payload.unit_scale:.2f} mm payload step)"
               if cfg.payload.unit_scale > 1 else ""),
        )
        digits_colour = ERROR if cfg.payload.digits < derived.required_digits else OK
        self.position.set(
            "digits",
            f"{cfg.payload.digits} (minimum {derived.required_digits})",
            digits_colour,
        )

        self.scanner.set(
            "fov",
            f"{rec.fov_continuous_mm:.1f} mm  ({cfg.scanner.min_codes_in_view} code(s) in view)",
        )
        self.scanner.set("static", f"{rec.fov_static_mm:.1f} mm")
        self.scanner.set(
            "occlusion",
            f"{rec.occlusion_tolerance_mm:.0f} mm" if rec.occlusion_tolerance_mm > 0
            else "none (single code in view)",
            None if rec.occlusion_tolerance_mm > 0 else WARNING,
        )
        self.scanner.set("sensor", f"{rec.sensor_class} (~{rec.required_sensor_px} px)")
        self.scanner.set(
            "wd", ", ".join(f"f{f:.0f}={w:.0f}mm" for f, w in rec.working_distances) or "-"
        )
        self.scanner.set(
            "mount",
            f"{rec.mount_height_mm:.0f} mm at {cfg.scanner.mount_tilt_deg:.0f} deg tilt",
        )
