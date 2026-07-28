"""About and Help dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aops import __app_name__, __version__

HELP_HTML = """
<h2>Absolute Optical Position Strip Generator</h2>
<p>AOPS generates printed optical positioning strips for PLC-controlled machinery.
A fixed-mount reader scans a symbol and derives absolute machine position from it.</p>

<h3>Workflow</h3>
<ol>
<li>Set the index range and cell pitch. The pitch is the machine resolution.</li>
<li>Check the <b>required field of view</b> in the Engineering summary. It is
    <code>N x pitch + symbol</code>, not the symbol size. A reader with a smaller
    window has blind zones where absolute position is lost.</li>
<li>Choose the substrate. This matters more than any software setting.</li>
<li>Export, print one proof sheet at <b>exactly 100 % scale</b>, and measure the
    calibration bar.</li>
<li>If the bar is not exactly its nominal length, enter what you measured in
    <i>Media and printer</i> and press <b>Apply measurement</b>. Re-export.</li>
<li>Mount each tile against a measured datum - never butt tiles together.</li>
</ol>

<h3>Why datum alignment matters</h3>
<p>Butt-splicing makes a systematic printer scale error accumulate along the whole
strip. At 0.2 % over 10 m that is 20 mm. Aligning each tile to its own printed
absolute position bounds the error at a single tile, typically well under a
millimetre. Every sheet prints the absolute X range of its leading edge for
exactly this purpose.</p>

<h3>Splice safety</h3>
<p>Page boundaries only ever fall in the white gap between symbols. The geometry
engine treats a cell as indivisible, so no symbol, quiet zone or margin is ever
cut. The clearance is shown in <i>Strip dimensions</i>.</p>

<h3>Continuous export</h3>
<p>A strip longer than 5080 mm exceeds the PDF page limit. <b>UserUnit</b> keeps a
single page that still measures true size and is honoured by Acrobat 7+ and modern
RIPs. <b>Raw oversize</b> is accepted by many large-format RIPs but refused by
Acrobat. <b>Split rolls</b> is universally safe but must be spliced.</p>

<h3>Keyboard</h3>
<table>
<tr><td><b>Ctrl+N / O / S</b></td><td>New, open, save project</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Export PDF</td></tr>
<tr><td><b>Ctrl+Z / Y</b></td><td>Undo, redo</td></tr>
<tr><td><b>Ctrl+wheel</b></td><td>Zoom the preview</td></tr>
<tr><td><b>Ctrl+0</b></td><td>Fit width</td></tr>
</table>
"""


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About AOPS")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(8)

        title = QLabel(__app_name__, self)
        title.setProperty("heading", True)
        title.setStyleSheet("font-size: 15px;")
        layout.addWidget(title)

        body = QLabel(
            f"<p>Version {__version__}</p>"
            "<p>An offline engineering utility for generating industrial optical "
            "positioning strips.</p>"
            "<p>Symbols are emitted as <b>vector</b> geometry at exact millimetre "
            "dimensions, so module edges stay sharp at any RIP resolution. Exported "
            "symbols are decode-verified through a real Data Matrix decoder before "
            "the file is written.</p>"
            "<p>Data Matrix ECC200 via libdmtx; QR via the qrcode library; "
            "PDF via ReportLab; interface in PySide6.</p>",
            self,
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AOPS Help")
        self.resize(680, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        browser = QTextBrowser(self)
        browser.setHtml(HELP_HTML)
        browser.setOpenExternalLinks(False)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
