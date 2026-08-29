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


#: Hover explanations for editable fields, keyed by dotted config path.
#: `ConfigPanel.add_row` falls back to these, so a field gets its hint from
#: here unless the panel passes something more contextual inline.
#:
#: Each says what the setting *is* and why you would touch it. A hint that only
#: restates the label ("Cell pitch: the cell pitch") is worse than none.
FIELD_HINTS: dict[str, str] = {
    # -- 1. symbol ---------------------------------------------------------
    "symbol.symbology": (
        "Which kind of 2-D barcode to encode.\n\n"
        "Data Matrix stores the same number in about half the width of a QR "
        "code (10x10 squares against 21x21), so it needs less strip length for "
        "the same reading distance. That is why industrial position tape uses "
        "it."
    ),
    # -- 2. position -------------------------------------------------------
    "position.start_index": (
        "The number of the first code on the strip.\n\n"
        "Leave at 0 unless you are printing a section of a longer strip, or "
        "continuing one that already exists."
    ),
    "position.end_index": (
        "The number of the last code.\n\n"
        "This is what sets the strip length: roughly (end - start + 1) times "
        "the spacing between codes."
    ),
    "position.increment": (
        "Step between printed code numbers.\n\n"
        "1 prints every code. 2 prints every other one, which halves the "
        "number of codes and the file size - but also halves how finely the "
        "machine can resolve position."
    ),
    "position.direction": (
        "Whether position counts up or down as you move along the strip.\n\n"
        "Use Reverse when the machine's zero is at the far end from where the "
        "strip begins."
    ),
    # -- 3. payload --------------------------------------------------------
    "payload.digits": (
        "How many characters each code carries, zero-padded to a fixed width.\n\n"
        "Fixed width matters because controllers parse fixed-width fields far "
        "more easily than variable ones. Too few and the largest position "
        "cannot be represented; too many and the symbol grows to a bigger grid "
        "than it needs."
    ),
    "payload.prefix": (
        "Optional text placed before the number inside every code.\n\n"
        "Use it if your controller expects a marker identifying which strip it "
        "is reading. Every extra character has to fit in the symbol, so keep "
        "it short."
    ),
    "payload.suffix": (
        "Optional text placed after the number inside every code.\n\n"
        "Same cost as a prefix: every character makes the symbol grid larger."
    ),
    # -- 4. dimensions -----------------------------------------------------
    "dimensions.pitch_mm": (
        "Centre-to-centre distance from one code to the next.\n\n"
        "The most consequential number here. It sets how finely the machine "
        "can resolve position - between two codes there is nothing new to read "
        "- and it sets the reader window you must buy, which is roughly one "
        "spacing plus one code."
    ),
    "dimensions.symbol_size_mm": (
        "Width and height of the printed square code.\n\n"
        "Bigger reads more reliably and tolerates more dirt and damage, but "
        "leaves less white space between codes for cutting, and forces a wider "
        "reader window."
    ),
    "dimensions.strip_height_mm": (
        "How tall the printed tape is, across the direction of travel.\n\n"
        "It must fit your paper or roll width, and it gives the reader room to "
        "sit slightly off-line without losing the code."
    ),
    "dimensions.symbol_v_offset_mm": (
        "Shifts the codes up or down within the strip band.\n\n"
        "Leave at 0 to keep them centred. Use it only when the reader is "
        "mounted off-centre and cannot be moved."
    ),
    # -- 5. design ---------------------------------------------------------
    "output.human_readable": (
        "Prints each code's position as plain digits beside the symbol.\n\n"
        "It is the same text the scanner decodes, so what you read by eye is "
        "exactly what the machine reads - there is no second numbering that "
        "can drift out of step. Useful during installation and fault-finding."
    ),
    "output.hr_position": (
        "Whether the printed number sits above or below its code.\n\n"
        "Below is conventional. Above can help if something covers the lower "
        "part of the strip once installed."
    ),
    "output.hr_font_pt": (
        "Size of the printed number.\n\n"
        "Small enough not to crowd the codes, large enough to read from where "
        "you stand at the machine."
    ),
    "output.engineering_ruler": (
        "Prints a millimetre scale alongside the strip.\n\n"
        "Useful for checking the print came out at the right size and for "
        "measuring by eye during installation. Turn it off for clean artwork."
    ),
    "output.ruler_position": "Whether the scale prints above or below the strip band.",
    "output.calibration_scope": (
        "Whether the calibration bar prints on every sheet or only the first.\n\n"
        "Every sheet is safer: it lets you spot a printer that drifts partway "
        "through a long run, which one bar at the start cannot show."
    ),
    "output.instruction_page": (
        "Adds the installation guide to the front of the PDF.\n\n"
        "It is generated from these exact settings, so it can never describe a "
        "different strip from the one printed behind it. It carries the "
        "formula to program into the controller."
    ),
    "printing.registration_marks": (
        "Small crosses at the sheet corners.\n\n"
        "They give a visual check that the sheet printed square and complete, "
        "and a reference to work from if the sheet is trimmed."
    ),
    "printing.cut_marks": (
        "Marks showing where to cut, plus a faint outline of the strip band.\n\n"
        "Every cut line falls in white space by design, so cutting on them can "
        "never damage a code."
    ),
    "printing.alignment_arrows": (
        "Arrows showing the direction of travel.\n\n"
        "A strip fitted the wrong way round reads positions in reverse. That "
        "is easy to do and unpleasant to discover once it is stuck down."
    ),
    # -- 6. output ---------------------------------------------------------
    "output.tiled_pages": (
        "Prints the strip across ordinary sheets, which you cut and join.\n\n"
        "Use this with a normal printer. Each sheet carries its own absolute "
        "position range so you can place it from the machine datum instead of "
        "against the previous sheet."
    ),
    "output.continuous": (
        "Prints the whole strip as one long page.\n\n"
        "Needs roll media or a large-format printer. It removes splices "
        "entirely - nothing to cut, nothing to align, and no error that can "
        "accumulate along the strip."
    ),
    "output.continuous_max_length_mm": (
        "Longest single piece to produce when a continuous strip is split into "
        "rolls.\n\nSet it to what your printer and media can actually handle "
        "in one pass."
    ),
    "output.verify_sample_count": (
        "How many codes to decode-check before the file is written.\n\n"
        "Sixteen costs about half a second and turns 'the file is probably "
        "right' into evidence."
    ),
    # -- 7. paper ----------------------------------------------------------
    "paper.orientation": (
        "Landscape runs the strip along the long edge of the sheet, fitting "
        "more codes per sheet and so needing fewer joins.\n\n"
        "Portrait is rarely the right choice for a strip."
    ),
    "paper.custom_width_mm": "Sheet width. Used only when the size is set to Custom.",
    "paper.custom_height_mm": "Sheet height. Used only when the size is set to Custom.",
    "paper.margin_left_mm": (
        "Blank border at the left edge.\n\n"
        "In landscape this runs along the strip, so it directly reduces how "
        "many codes fit on each sheet. Keep it as small as your printer allows."
    ),
    "paper.margin_right_mm": (
        "Blank border at the right edge.\n\n"
        "In landscape this runs along the strip, so it directly reduces how "
        "many codes fit on each sheet."
    ),
    "paper.margin_top_mm": (
        "Blank border at the top edge.\n\n"
        "In landscape this runs across the strip, so it limits the strip "
        "height and the room available for the ruler and calibration bar."
    ),
    "paper.margin_bottom_mm": (
        "Blank border at the bottom edge.\n\n"
        "In landscape this runs across the strip, so it limits the strip "
        "height and the room available for the ruler and calibration bar."
    ),
    # -- 8. print ----------------------------------------------------------
    "printing.calibration_length_mm": (
        "Nominal length of the printed calibration bar.\n\n"
        "After printing, measure the bar with a steel rule. If it does not "
        "measure exactly this, the printer is not at 1:1 and the scaling needs "
        "correcting. 200 mm is long enough to measure accurately and still "
        "fits any sheet."
    ),
    "printing.leading_margin_mm": (
        "Blank tape before the first code.\n\n"
        "Gives you something to hold and stick down without covering a code, "
        "and room for the reader to sit before position zero."
    ),
    "printing.trailing_margin_mm": (
        "Blank tape after the last code. Same purpose as the leading margin, "
        "at the far end."
    ),
    "printing.registration_mark_size_mm": "Size of the corner registration crosses.",
    "printing.cut_mark_length_mm": "Length of the cut marks at the sheet edges.",
    "printing.splice_mode": (
        "How consecutive sheets are meant to meet: butted edge to edge, or "
        "overlapped.\n\n"
        "This describes the artwork only. However they meet, place each sheet "
        "by measuring from the machine datum rather than against the previous "
        "sheet, or the error accumulates down the whole strip."
    ),
    "printing.splice_overlap_mm": (
        "How far one sheet overlaps the next, in Overlap mode.\n\n"
        "It must stay within the white space, or the overlap will cover a "
        "code's clear border and stop it reading."
    ),
    "printer.max_label_length_mm": (
        "The longest single piece this printer can print, in millimetres.\n\n"
        "Zero means 'not stated'. Label printers have a real firmware limit - "
        "a Zebra ZD230 stops at 990 mm - and the ZPL export splits the strip "
        "at it rather than letting the printer truncate a piece mid-code. "
        "Device presets fill it in."
    ),
    "printer.label_length_mm": (
        "For die-cut sticker rolls: the length of one sticker along the "
        "feed.\n\n"
        "Zero means continuous media. When set, the ZPL export packs the "
        "strip one sticker at a time and the printer's gap sensor registers "
        "each label at its die-cut edge. A length that is a whole multiple "
        "of the code spacing lets stickers butt-splice with no spacing "
        "error at the joints."
    ),
    "printer.label_gap_mm": (
        "The liner gap between die-cut stickers: default or measured.\n\n"
        "'Default' (the 0 position) assumes the 3 mm (1/8 in) de facto "
        "industry norm. It is not a standard - converters run roughly 2 to "
        "5 mm - so once the roll is in hand, measure the gap and enter the "
        "value. Either way the printer calibrates per roll: the gap is its "
        "registration mark and never becomes part of the strip's geometry."
    ),
    "printing.splice_labels": (
        "Labelled trim boundaries at every row joint.\n\n"
        "Each joint prints the same SPLICE number on the two edges that mate, "
        "and the strip's outer ends say START and END - so after cutting, "
        "every row states where it ends and which edge joins which. The line "
        "sits in guaranteed white and a correct cut removes it. Turned off "
        "only by the Plain style."
    ),
    # -- 9. media and printer ---------------------------------------------
    "media.method": (
        "How the image is put onto the material.\n\n"
        "Thermal transfer melts resin from a ribbon onto the surface and is "
        "the durable industrial choice. Direct thermal uses no ribbon and "
        "fades. Laser and inkjet are fine for proofs but need stock rated for "
        "them."
    ),
    "media.adhesive_backed": (
        "Whether the material has adhesive backing.\n\n"
        "It changes the mounting advice on the guide, and whether the strip is "
        "bonded along its length - which is what decides how much thermal "
        "expansion reaches the position reading."
    ),
    "printer.dpi": (
        "Your printer's resolution.\n\n"
        "It decides how many printer dots make up each small square of a code. "
        "Below 3 dots per square the edges break up and scanners start "
        "failing; 5 or more is comfortable."
    ),
    "printer.unprintable_margin_mm": (
        "How close to the paper edge your printer can actually print.\n\n"
        "Used to warn you when the page margins fall inside it and content "
        "would be clipped. Set it to 0 for a label printer, which prints the "
        "full width of the roll."
    ),
    # -- 10. scanner -------------------------------------------------------
    "scanner.px_per_module": (
        "How many camera pixels should cover each small square of a code.\n\n"
        "About 5 is the usual industrial target. This is what turns your "
        "geometry into a sensor resolution you can specify when buying."
    ),
    "scanner.fov_angle_deg": (
        "How wide an angle your reader sees, from its datasheet.\n\n"
        "This is the most useful number a reader datasheet gives you. With it "
        "the mounting distance is exact rather than estimated from an assumed "
        "lens and sensor. Leave at 0 to keep the generic estimate."
    ),
    "scanner.fov_vertical_deg": (
        "How tall an angle your reader sees.\n\n"
        "Easy to overlook, because the strip geometry drives the horizontal "
        "requirement - but the code and its clear borders still have to fit "
        "top to bottom at whatever distance the horizontal view dictates."
    ),
    "scanner.dof_min_mm": (
        "Closest distance your reader can focus at.\n\n"
        "If the required view is reached nearer than this, mount at this "
        "distance instead - the view is only wider there, which is harmless."
    ),
    "scanner.dof_max_mm": (
        "Furthest distance your reader can focus at.\n\n"
        "If covering a full spacing plus one code needs more distance than "
        "this, the reader cannot do it from anywhere it can focus, and there "
        "will be blind spots. That is a hard error, not a warning."
    ),
    "scanner.sensor_px_h": (
        "Pixels across your reader's sensor, from its datasheet.\n\n"
        "Used to check how many pixels actually land on one module at the "
        "required distance, against the target above. Leave at 0 if unknown."
    ),
    "scanner.mount_distance_mm": (
        "Where the reader can actually be mounted.\n\n"
        "Leave at 0 and the tool works forwards: pick a geometry and it reports "
        "the distance that geometry demands.\n\n"
        "Set it and the calculation inverts. On a real machine the distance is "
        "decided by a bracket, a guard or a clearance long before anyone picks "
        "a spacing - so the distance and the view angle fix how much window "
        "there is, and the geometry has to fit inside that budget instead of "
        "dictating it."
    ),
    # -- 11. project -------------------------------------------------------
    "project.machine": (
        "Which machine this strip is for. Printed on every sheet, so a strip "
        "found loose on a bench can be traced back."
    ),
    "project.project": (
        "The job or installation this strip belongs to. Printed on every sheet."
    ),
    "project.strip_id": (
        "Your own reference for this strip, such as AX1-POS-001.\n\n"
        "Worth setting: a machine with several axes has several strips, and "
        "they are very hard to tell apart once printed."
    ),
    "project.revision": (
        "Which version of this design was printed.\n\n"
        "Raise it whenever you reprint after changing anything, so an old "
        "strip still on the machine can be told apart from the new one."
    ),
    "project.engineer": "Who prepared this strip. Printed on the guide page for traceability.",
    "project.company": "Your organisation. Printed on the guide page.",
    "project.comments": (
        "Free notes printed on the installation guide.\n\n"
        "Use it for whatever the next person needs to know - mounting quirks, "
        "which reader was fitted, why a value was chosen."
    ),
}


def hint_for(path: str) -> str:
    """Hover explanation for an editable field, or empty if none is registered."""
    return FIELD_HINTS.get(path, "")


def label_for(key: str, fallback: str) -> str:
    """Plain-language label for a row key."""
    term = TERMS.get(key)
    return term.label if term is not None else fallback


def tooltip_for(key: str) -> str:
    """Explanation for a row key, or empty when there is nothing useful to add."""
    term = TERMS.get(key)
    return term.tooltip if term is not None else ""
