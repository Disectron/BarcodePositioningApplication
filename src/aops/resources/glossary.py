"""Plain-language names and explanations for everything the UI displays.

Two rules govern the wording here.

**Say it in plain words, but name the jargon.** A label that reads "Joined end
to end" is understandable without any background; its tooltip then says the
trade calls this *butt-splicing*. The user is never blocked by a term they do
not know, and never left unable to look one up or discuss it with a supplier.

**Explain the consequence, not the definition.** "Quiet zone: the clear border
around a code" is a dictionary entry. "Ink inside this band makes the code
unreadable, and it is carved out of the margin rather than added to the cell"
is what the user actually needs to know. Every entry below states what happens
if you get it wrong, because that is the only reason any of these numbers are
on screen.

Held as data, in one place, so the same wording reaches the summary panels and
the configuration rows without drifting between them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Term:
    """A display label and the explanation shown when hovering it."""

    label: str
    tooltip: str


#: Keyed by the identifier the panels already use for each row.
TERMS: dict[str, Term] = {
    # -- identification ----------------------------------------------------
    "machine": Term(
        "Machine",
        "Which machine this strip belongs to. Printed on every sheet so a "
        "strip found loose on a bench can be traced back.",
    ),
    "project": Term(
        "Project",
        "The job or installation this strip was made for. Printed on every "
        "sheet.",
    ),
    "strip": Term(
        "Strip ID",
        "Your own reference for this particular strip, such as AX1-POS-001.\n\n"
        "Worth setting: a machine with several axes will have several strips, "
        "and they are hard to tell apart once printed.",
    ),
    "revision": Term(
        "Revision",
        "Which version of this strip design was printed.\n\n"
        "Raise it whenever you reprint after changing anything, so an old "
        "strip still on the machine can be distinguished from the new one.",
    ),
    "fingerprint": Term(
        "Fingerprint",
        "A short code derived from every setting in this project.\n\n"
        "It is printed on every sheet. Years from now it lets you prove that a "
        "strip in your hand was produced by the project file you have, and not "
        "by some edited version of it.",
    ),
    # -- geometry ----------------------------------------------------------
    "symbology": Term(
        "Code type",
        "Which kind of 2-D barcode is printed.\n\n"
        "Data Matrix holds the same number in about half the width of a QR code "
        "(10x10 squares against 21x21), which is why industrial position tape "
        "uses it.",
    ),
    "pitch": Term(
        "Spacing between codes",
        "Centre-to-centre distance from one code to the next. The trade calls "
        "this the pitch.\n\n"
        "It sets how finely the machine can resolve position: between two codes "
        "the reader has nothing new to read, so this is the size of the step "
        "the position jumps in.",
    ),
    "symbol": Term(
        "Code size",
        "Width and height of the printed square code itself, not counting the "
        "white space around it.\n\n"
        "Bigger is easier to read and more tolerant of dirt, but leaves less "
        "white between codes for cutting.",
    ),
    "margin": Term(
        "White space each side",
        "Blank space between the edge of a code and the edge of its slot.\n\n"
        "This is what a cut has to land inside, so it is also your cutting "
        "tolerance. At the default settings it is 7.5 mm against a 1 mm "
        "requirement - a very forgiving target.",
    ),
    "quiet": Term(
        "Clear border needed",
        "The minimum blank border a scanner needs around a code to find its "
        "edges. The standard calls it the quiet zone.\n\n"
        "Any ink inside this band makes the code unreadable. It is taken out of "
        "the white space each side, never added to the slot, which is what "
        "keeps a cut at any slot boundary automatically safe.",
    ),
    "height": Term(
        "Strip height",
        "How tall the printed tape is, across the direction of travel.\n\n"
        "It must fit the width of your paper or roll, and it gives the reader "
        "room to be slightly misaligned without losing the code.",
    ),
    # -- print accuracy ----------------------------------------------------
    "dots": Term(
        "Printer dots per square",
        "A code is a grid of small black and white squares - each one is called "
        "a module. This is how many printer dots are used to draw one square.\n\n"
        "Below 3 the edges break up and scanners start failing. 5 or more is "
        "comfortable. Too few is the most common cause of a code that looks "
        "fine but will not read.",
    ),
    "drift": Term(
        "Movement from humidity",
        "How much the tape stretches or shrinks along its whole length as the "
        "air gets damper or drier.\n\n"
        "Paper moves about 3% between a dry and a humid day - hundreds of "
        "millimetres over a long strip, which is why it is refused. Polyester "
        "film moves about 0.006%.",
    ),
    "thermal": Term(
        "Movement from temperature",
        "How much the tape grows or shrinks along its length as the temperature "
        "changes.\n\n"
        "Only the difference between the tape and whatever it is stuck to "
        "reaches the reading, because the machine frame expands too. Bonded "
        "along its full length the tape is dragged along by the frame and this "
        "largely cancels - the strain goes into the adhesive instead.",
    ),
    "cumulative": Term(
        "Joined end to end",
        "The error you get if each printed sheet is laid hard against the end "
        "of the one before. The trade calls this butt-splicing.\n\n"
        "Every sheet comes out very slightly short, and because each one starts "
        "where the last ended, that shortfall is inherited and added to all the "
        "way down the strip. 39 sheets means 39 times the error of one.\n\n"
        "This is the same reason you never chain-measure with a ruler.",
    ),
    "bounded": Term(
        "Measured from datum",
        "The error you get if each sheet is instead positioned by measuring "
        "from the machine's zero point with a steel tape. This is called datum "
        "alignment.\n\n"
        "Each sheet still has its own small error, but it is never inherited by "
        "the next one, so it cannot build up. The error stops growing at one "
        "sheet's worth however long the strip is.\n\n"
        "Compare the two figures: same printer, same error per sheet, and the "
        "installation method alone changes the result by a factor of 39.",
    ),
    # -- output ------------------------------------------------------------
    "codes": Term("Number of codes", "How many individual codes will be printed."),
    "length": Term(
        "Strip length",
        "Total printed length, including the blank lead-in and lead-out at the "
        "ends.",
    ),
    "sheets": Term(
        "Pages",
        "How many pages the PDF will contain, and how many of those are strip "
        "rather than the installation guide.",
    ),
    "files": Term("Output files", "The files that will be written when you export."),
    "size": Term("Estimated PDF size", "Roughly how large the exported file will be."),
    "payload": Term(
        "What a code contains",
        "The exact text stored inside one code - its payload.\n\n"
        "Here it is the absolute position in millimetres, zero-padded to a "
        "fixed width. The strip describes itself, so the reader hands the "
        "controller a real machine coordinate and no conversion is needed.",
    ),
    # -- position ----------------------------------------------------------
    "formula": Term(
        "Position formula",
        "The expression to program into the controller.\n\n"
        "It is generated from the same geometry that produced the printed "
        "strip, so the two cannot disagree. Type it in exactly as shown.",
    ),
    "per_code": Term(
        "Distance per code",
        "How far the machine moves between one code and the next.\n\n"
        "This is the finest position step the strip can report.",
    ),
    "max": Term(
        "Furthest position",
        "The largest position value printed on the strip. It must fit within "
        "the number of digits each code carries.",
    ),
    "resolution": Term(
        "Resolution",
        "How finely position is reported: the distance between codes, and the "
        "smallest step the encoded number itself can express.",
    ),
    "digits": Term(
        "Digits per code",
        "How many characters each code carries, and the minimum needed for the "
        "largest position on this strip.\n\n"
        "A fixed width matters because controllers parse fixed-width fields far "
        "more easily than variable ones.",
    ),
    # -- scanner -----------------------------------------------------------
    "fov": Term(
        "Reader window needed",
        "How wide a view the reader must have. Officially, the field of view.\n\n"
        "This is the single most misjudged number here. It is NOT the size of a "
        "code - it is the spacing between codes plus one code. At the default "
        "settings that is 35 mm, not the 12 mm the code size suggests.\n\n"
        "A reader with a narrower window has blind spots where no complete code "
        "is visible and the machine loses its position entirely.",
    ),
    "static": Term(
        "Window to read one code",
        "How wide a view is needed to read a single code while stopped.\n\n"
        "Much smaller than the window needed to never lose position while "
        "moving.",
    ),
    "occlusion": Term(
        "Damage tolerated",
        "How much of the tape can be covered, scratched or destroyed while the "
        "machine still knows where it is. Officially, occlusion tolerance.\n\n"
        "It comes from asking the reader to see more than one code at a time: "
        "with a spare code always in view, losing one does not matter. Reading "
        "only one code at a time gives no tolerance at all.",
    ),
    "sensor": Term(
        "Camera needed",
        "How many pixels the reader's sensor must have across its view to "
        "resolve the small squares that make up each code.",
    ),
    "wd": Term(
        "Mounting distance",
        "How far the reader sits from the tape, for each lens focal length.\n\n"
        "Estimated from the lens geometry. Check it against the datasheet of "
        "the reader you actually buy.",
    ),
    "mount": Term(
        "Mount height",
        "Suggested vertical distance from the tape to the reader.\n\n"
        "Shorter than the mounting distance because the reader is tilted. The "
        "tilt matters: pointed straight at a glossy tape, the reader sees its "
        "own reflection instead of the code.",
    ),
}

#: Explanations for whole configuration sections, shown on the header.
SECTION_TERMS: dict[str, str] = {
    "symbol": "Which kind of 2-D barcode to print.",
    "position": (
        "How code numbers map to real machine positions, and the formula the "
        "controller will use."
    ),
    "payload": "What is stored inside each code.",
    "dimensions": (
        "Physical size of one code and the spacing between them. These decide "
        "both how finely position is reported and how safe the strip is to cut."
    ),
    "design": (
        "What the printed page looks like: rulers, calibration bar, marks and "
        "labels. Choose Plain for artwork, Engineering for a strip going onto "
        "a machine."
    ),
    "output": "Which files to produce, and how thoroughly to check them.",
    "paper": (
        "Sheet size, or a label-printer roll. A roll prints the strip in one "
        "piece with nothing to cut or align."
    ),
    "printing": (
        "Print-time scale correction and the marks used to register and cut "
        "each sheet."
    ),
    "media": (
        "What the strip is printed on, printed with, and stuck to. This "
        "outranks every software setting for real-world accuracy."
    ),
    "scanner": (
        "The reader's optics. Sets the window width the reader must have to "
        "never lose position."
    ),
    "project": "Identification printed on every sheet, for traceability.",
}


def label_for(key: str, fallback: str) -> str:
    """Plain-language label for a row key."""
    term = TERMS.get(key)
    return term.label if term is not None else fallback


def tooltip_for(key: str) -> str:
    """Explanation for a row key, or empty when there is nothing useful to add."""
    term = TERMS.get(key)
    return term.tooltip if term is not None else ""
