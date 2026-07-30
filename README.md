# AOPS — Absolute Optical Position Strip Generator

An offline engineering utility that generates **industrial optical positioning strips** for
PLC-controlled machinery: long printed strips of Data Matrix codes at a fixed pitch, mounted along
a machine axis. A fixed-mount reader scans a symbol and the PLC derives absolute position from it.

This is commissioning tooling in the class of SICK / Keyence / Cognex / Leuze / Pepperl+Fuchs —
**not** a barcode label generator. That distinction drives the whole design: splice safety, print
calibration, scanner optics and traceability are first-class features rather than decoration.

![AOPS main window](docs/screenshot.png)

---

## Quick start

Python 3.12 or later is the only prerequisite.

**Windows** — double-click **`run.bat`**.

**Linux / macOS** — `./run.sh`

The first run creates `.venv`, installs the dependencies into it, and launches the GUI.
Every run after that starts immediately. The same launchers forward arguments for headless
use:

```
run.bat info                 (Windows)
./run.sh export -o ./out     (Linux / macOS)
```

If you already have an environment set up, `python run.py` does the same thing without the
venv bootstrap.

> **Do not run `python src/aops/app.py` directly.** The package uses a `src` layout, so
> running a file inside it puts `src/aops/` on `sys.path` rather than `src/`, and the import
> fails with `ModuleNotFoundError: No module named 'aops'`. `run.py` exists precisely to
> make that mistake impossible — it puts `src/` on the path first.

### Manual install

If you would rather manage the environment yourself:

```bash
# Native libdmtx (pylibdmtx is a ctypes binding and needs the shared library).
# Note: libdmtx0b has no install candidate on Ubuntu Noble; the runtime .so
# ships with the -dev package. On Windows the pylibdmtx wheel bundles the DLL,
# so this step is not needed there.
sudo apt-get update && sudo apt-get install -y libdmtx-dev

# Qt runtime, on a minimal or headless Linux host
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
    libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-render-util0

python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### pylibdmtx on Python 3.12+

pylibdmtx 0.1.10 imports `distutils.version.LooseVersion`, and `distutils` was removed from the
standard library in Python 3.12 (PEP 632), so importing it fails outright. AOPS installs a minimal
shim into `sys.modules` before pylibdmtx loads — see `src/aops/symbols/compat.py`. No setuptools
dependency is needed, and the shim never clobbers a real `distutils`.

## Run

Via the launcher (no activation needed):

```bash
./run.sh                       # GUI
./run.sh info                  # summarise a configuration
./run.sh export -o ./out       # export PDFs, no GUI required
./run.sh symbol 010500         # print one symbol as ASCII
```

Or directly against the virtual environment:

```bash
./.venv/bin/python -m aops                       # GUI
./.venv/bin/python -m aops.cli info              # summarise a configuration
./.venv/bin/python -m aops.cli export -o ./out   # export PDFs, no GUI required
./.venv/bin/python -m aops.cli symbol 010500     # print one symbol as ASCII
```

## Test

```bash
QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest
./.venv/bin/ruff check src tests
```

The whole suite runs headlessly, including the GUI smoke tests.

---

## Presets

A project file answers *"which strip is this?"*. A preset answers *"how do we build strips
here?"* — the geometry, substrate, printer and reader you use on every job. **Presets → Save
current settings as preset…** captures the second; the toolbar menu applies one in a single
undoable step.

The design decision that matters is what a preset **refuses** to carry:

| Carried | Held back (`PER_STRIP_FIELDS`) |
|---|---|
| Symbol, payload, dimensions, design, output, paper, printing, media, printer, scanner | Machine name, project, strip ID, revision, comments |
| Increment, pitch mode, direction, datum — house convention | Start/end index and origin — this axis's length |
| Engineer and company — house details | |

Without that split, applying "our standard 25 mm polyester setup" to a new job would also stamp it
with another machine's name, another axis's length and someone else's revision letter — and since
every change is applied live, the mistake would stay invisible until it reached a printed sheet.
Both `capture` and `apply` filter the list, so a preset that has been hand-edited to smuggle an
identity field in still cannot overwrite one.

Presets are JSON in a folder (`*.aopspreset`), for the same reasons project files are: readable,
diffable, and worth committing next to the PLC source or emailing to a colleague.

### Code sizes

A **Code size** submenu offers 20×20 mm through 50×50 mm in 5 mm steps. Symbol size on its own is
not a usable preset — three other values are forced to move with it, which is exactly why these are
worth shipping rather than leaving to hand-editing:

| Code | Spacing | Band | Clear border | Module | Reader window |
|---|---|---|---|---|---|
| 20×20 | 30 mm | 40 mm | 2.0 mm | 2.0 mm | 50 mm |
| 30×30 | 45 mm | 50 mm | 3.0 mm | 3.0 mm | 75 mm |
| 40×40 | 55 mm | 60 mm | 4.0 mm | 4.0 mm | 95 mm |
| 50×50 | 70 mm | 70 mm | 5.0 mm | 5.0 mm | 120 mm |

Enlarging the code enlarges its modules, so the **clear border must grow with it** (one module of a
10×10 Data Matrix); the **spacing** must clear the code plus both borders with cutting tolerance
left over; and the **band** has to be tall enough to hold both. Pitches are rounded to whole 5 mm
steps, because position is `index × pitch` and reading 0, 45, 90 off a strip beats reading 0, 42, 84.

The trade runs one way throughout: a bigger code reads from further away and survives more damage,
but position resolves only to the spacing, and the reader window you must buy grows with it. Each
preset's description states its own figures — generated from the values, so the text cannot drift
from what it sets. The size presets touch geometry only, so they leave your media, paper and printer
settings alone.

### Readers

A **Reader** submenu fills in a specific scanner's published optics. A datasheet quotes an *angular*
field of view, and from that the mounting distance follows exactly rather than being inferred from an
assumed sensor and lens:

```
distance = required view width / (2 · tan(angle / 2))
```

The focus window then decides whether that distance is usable. This catches a failure that is
otherwise silent: a reader that decodes a code perfectly on the bench but **cannot cover a whole
spacing plus one code from any distance it can focus at**, so the machine has blind spots where
position is lost (`SCN-003`, a hard error). `SCN-005` checks the code still fits the *vertical* view
at whatever distance the horizontal requirement dictates — easy to overlook, since the strip geometry
only drives the horizontal one.

#### Working backwards from a fixed mounting distance

Leaving **Mounting distance** at 0 keeps the forward calculation: pick a geometry, get told the
distance it demands. On a real machine that is the wrong way round — the distance is decided by a
bracket, a guard or a clearance long before anyone picks a spacing.

Setting it inverts the whole calculation. Distance and view angle fix the window, and the geometry
has to fit inside that budget:

```
window = distance · 2 · tan(angle / 2)          available
       ≥ N · pitch + code                        required
```

The panel then reports the window, the spare room, and what that room buys — *"spacing up to 68 mm,
or a code up to 49 mm"* — and **Fit spacing to mounting distance** widens or narrows the pitch to use
it exactly. For the NVF230-SR with a 10 mm code:

| Mount at | Window | Max spacing | Max code |
|---|---|---|---|
| 50 mm | 45 mm | 35 mm | 20 mm |
| 100 mm | 90 mm | 80 mm | 41 mm |
| 150 mm | 135 mm | 125 mm | 61 mm |
| 200 mm | 180 mm | 170 mm | 82 mm |

`SCN-009` blocks export when the geometry does not fit, with the pitch that would — but only when
that pitch is still a legal cell. Once the window cannot hold the code plus its quiet zones at all,
the pitch is not what is at fault and no suggestion is offered rather than a nonsensical one.
`SCN-008` catches a distance the reader cannot focus at, `SCN-010` reports unused window as available
resolution, `SCN-011` the vertical shortfall.

Currently shipped: **Newland NLS-NVF230-SR**. Adding another is one call to `_reader_preset()` in
`core/presets.py`, which **requires a `source`** — these are the only vendor figures in the project,
and `core/scanner.py` states plainly that it invents none, so each has to be traceable to the page it
came from and checkable against the unit actually bought. Every value stays user-editable.

### General presets

Three more ship with the tool, each encoding a recommendation this README argues for elsewhere:

- **Label roll, 4 inch continuous** — thermal transfer on continuous polyester with a resin ribbon,
  printed in one piece. Uses 3 mm margins, because a 4″ roll at the default 10 mm clips the band
  stack, and 203 dpi, which is 8 dots/mm and lands a 1.000 mm module on exactly 8 whole dots.
- **A4 sheets, commissioning set** — tiled A4 with the full engineering furniture.
- **Fine pitch, 12.5 mm** — twice the position resolution, encoding tenths of a millimetre because
  12.5 mm steps cannot be represented in whole ones.

## What the tool actually decides for you

### The field of view is set by the pitch, not the symbol size

The single most important number AOPS produces, and it is not obvious. Codes of width `S` repeat
with period `P`. A camera window of width `W` fully contains a given code over an interval of
length `W − S`, repeating every `P`. For **N** complete codes to be in view at *every* axis
position those intervals must overlap N deep, which requires:

```
W_min = N × P + S
```

At the default 25 mm pitch and 10 mm symbol that is **35 mm for N = 1** — not the ~12 mm an
engineer might infer from the symbol size. Below `W_min` there are **blind zones where no complete
code is visible and the machine loses absolute position**.

Real industrial readers (e.g. Pepperl+Fuchs PXV) read three codes at once so the tape can be damaged
without losing position. At N = 3 the requirement rises to 85 mm and buys `(N−1) × P` = 50 mm of
survivable occlusion. Both figures appear in the Engineering summary and on the installation guide.

### Butt-splicing accumulates error; datum alignment does not

If tiles are butt-spliced end to end, a systematic printer scale error compounds **linearly**: at
0.2 % over 10.5 m that is **21 mm**, fatal for a sub-millimetre positioning system. If each tile is
instead positioned against a measured datum, the error is bounded by one tile — about **0.6 mm**.

So every sheet prints the absolute X range of its own leading edge, and the guide instructs
alignment with a steel tape rather than by abutting. Both figures are shown side by side in the
Parameter summary so the reason is self-evident.

### The substrate outranks every software setting

| Medium | Change, 20 → 80 %RH | Over a 10.5 m strip |
|---|---|---|
| Paper | ~3 % | **~315 mm** — unusable |
| Coated film | ~0.5 % | ~52 mm |
| Polyester film | ~0.006 % | ~0.6 mm |

Paper is a hard validation error for any strip over a metre (`MED-001`), quoting the predicted drift
in millimetres.

### …but on the substrate you actually use, temperature beats humidity

Once paper is ruled out, humidity stops being the dominant term and almost everyone keeps optimising
it anyway. Polyester moves 0.004 % over a 40-point humidity swing and 0.051 % over a 30 °C one —
**twelve times more**. Over the default 10.565 m strip:

| Term | Movement | Modelled by |
|---|---|---|
| Humidity, 40 %RH | 0.42 mm | `media_drift_mm` |
| Datum-aligned print error | 0.54 mm | `bounded_error_mm` |
| **Thermal, 30 °C, polyester on steel** | **1.58 mm** | `thermal_drift_mm` |
| Thermal, same strip referenced to granite | 3.49 mm | `thermal_differential_mm` |

Two things make this more than a bigger number.

**Only the difference against the frame reaches the reading.** Polyester (17 ppm/°C) on steel
(12 ppm/°C) leaves 5 ppm; on aluminium (23 ppm/°C) it leaves −6 ppm and **the error changes sign**.
Compensating in the wrong direction doubles it, so `thermal_differential_mm` is reported signed.

**The mounting decides whether it reaches the reading at all.** A continuously bonded strip is
dragged along by the frame, so a code stays over the feature it was aligned to and the term very
largely cancels — against features on *that same frame*. The strain does not vanish; the adhesive
carries it, which is reported as `bond_strain_ppm` and warned about at `MED-008`. An end-anchored
strip expands freely and takes the whole differential (`MED-006`).

So the answer to "how accurate is my strip" depends on a question the tool previously never asked:
what is it stuck to, and how.

### Splice safety is proved, not hoped for

Page boundaries only ever fall in the white gap between symbols. The packer treats a cell as
**atomic**: only pure-white segments are ever divisible.

> If `symbol + 2 × quiet_zone ≤ pitch`, every page boundary is either inside a white segment (no ink
> at all) or at a cell junction, where the clearance on both sides is
> `margin_lr = (pitch − symbol) / 2 ≥ quiet_zone`.

At the default geometry that is **7.5 mm of clearance against a 1.0 mm requirement** — a 7.5×
margin on cutting accuracy. `verify_splices()` re-derives the property *independently* from the
placed geometry, and runs both in the test suite and again at export time, so a packer bug cannot
silently ship a strip with a symbol cut in half.

### Print styles

The defaults produce a *commissioning document* — ruler, calibration bar, header, footer,
registration and cut marks — all of which exist to make the strip verifiable. That is right for a
strip going onto a machine and wrong for a design proof. The **Design** section picks between:

| Style | What prints | Band stack |
|---|---|---|
| **Plain** | Symbols and nothing else | 43 mm |
| **Labelled** | Symbols with their position underneath | 43 mm |
| **Engineering** (default) | Everything, plus the installation guide | 92 mm |

The style is **derived from the individual switches, never stored alongside them** — storing both
would let them disagree, and the disagreement would be invisible (a combo reading "Plain" over a
sheet that prints a calibration bar). Selecting a style writes the switches; changing one by hand
reads as `Custom`. Old project files need no migration: they read as whatever style their switches
already describe.

Plain warns rather than refuses (`PAG-011`). The calibration bar is the only printed means of
proving the sheet came out 1:1, and a positioning strip that is silently 0.2 % short looks exactly
like a correct one — so the trade is stated, not assumed.

### …or avoid splices altogether, with a label printer

A thermal-transfer label printer running continuous polyester with a resin ribbon is arguably the
*right* device for this job rather than a fallback. The media is continuous, so the strip prints in
one piece: no page boundaries to cut, no per-tile datum alignment, and the 21 mm butt-splice error
simply does not arise. Roll widths are selectable as paper presets (2″–8″, stated as printable
width), and choosing one steers you towards continuous output (`PAG-008`/`PAG-009`).

The trap that catches people is quiet, so it is a hard error (`PAG-010`): **what has to fit across
the roll is the whole band stack, not the strip band.** Header, ruler, calibration bar and footer
take the default 40 mm strip to 92 mm — so a 4″ (104 mm) roll at the default 10 mm margins leaves
84 mm usable and clips the artwork, despite being nearly three times wider than the strip itself.

`Direct thermal` is also selectable and warns (`MED-009`): the image is heat-sensitive stock
reacting to heat, so the same heat keeps acting on it near a warm machine. Fine for a trial strip,
wrong for a multi-year fixture.

### Symbols are vector, and verified

The Data Matrix encoder returns a bitmap, so AOPS recovers the **module matrix** from it and draws
vector rectangles at exact millimetre positions — infinitely sharp at any RIP resolution, where an
embedded raster would be resampled. The recovered matrix is fed back through a real Data Matrix
decoder before the file is written (`VerifyMode.SAMPLE` checks sixteen codes in about half a
second), which turns "the PDF is probably right" into evidence.

### Continuous export beyond the PDF page limit

PDF caps a page at 14400 pt (5080 mm). A 10.565 m strip is 2.08× over. Three strategies, selectable:

| Strategy | Behaviour |
|---|---|
| `USER_UNIT` (default) | One true-size page via `/UserUnit` (PDF 1.6+). Honoured by Acrobat 7+ and modern RIPs. |
| `RAW_OVERSIZE` | Emits the real oversized MediaBox. Many large-format RIPs accept it; Acrobat refuses. |
| `SPLIT_ROLL` | N conformant files. Universally safe, must be spliced. |

ReportLab has no `/UserUnit` support, and the obvious implementation silently fails —
`PDFCatalog.__init__` pre-seeds every `__NoDefault__` key to `None` on the instance, shadowing any
class attribute. The value has to be set on the instance at format time; see
`src/aops/render/pdf/userunit.py`.

---

## Architecture

Dependencies point inward only, and this is **enforced by a test** (`tests/test_layering.py`,
which walks every module's AST):

```
ui ──▶ controller ──▶ render ──▶ symbols ──▶ core
core imports no PySide6, reportlab, qrcode, pylibdmtx or PIL
```

```
src/aops/
├── core/              PURE DOMAIN — no third-party imports at all
│   ├── units.py       mm↔pt↔µm; authored dims round(), capacities floor()
│   ├── config.py      frozen dataclasses; every float carries a unit suffix
│   ├── cell.py        CellSpec + the invariants splice safety rests on
│   ├── geometry.py    segments, paginate(), verify_splices()      ← highest risk
│   ├── positions.py   index → position, and the PLC formula string
│   ├── payload.py     absolute-millimetre payload construction
│   ├── scanner.py     field-of-view and working-distance model
│   ├── media.py       substrate drift, cumulative vs bounded splice error
│   ├── rules.py       ~50 validation rules across 10 prefixes
│   ├── drawlist.py    Painter protocol — the one layout abstraction
│   └── layout/        style, bands, elements, strip, guide, preview, overview
├── symbols/           may import qrcode/pylibdmtx/PIL; never Qt or ReportLab
├── render/pdf/        ReportLab backend, /UserUnit, exporters
├── render/qt/         QPainter backend, raster tier of the symbol cache
├── controller/        ConfigStore (undo/redo), AppController, ExportWorker
└── ui/                the only package importing PySide6 widgets
```

**Layout is written exactly once.** Both the on-screen preview and the exported PDF consume the same
`DrawList`, so they cannot drift apart. Adding SVG, PNG or DXF output means implementing `Painter`
and nothing else.

### Why integer micrometres

All packing arithmetic is `int` µm. Pagination asks "does one more 25.000 mm cell fit in
275.0000000001 mm?" thousands of times, and in binary floating point that question has no stable
answer. In integer micrometres it is decidable — which is what lets the splice property be *proved*
rather than approximated. Floats appear only at the emit boundary.

### Performance

| Work | Cost | When |
|---|---|---|
| Validation + pagination | ~200 µs @ 421 codes | every change, synchronous |
| Preview (first 10 symbols) | ~3 ms cold, ~0 cached | every change, synchronous |
| Overview (**zero encodes**) | ~0.7 ms | on repagination only |
| Export (421 symbols, vector) | ~0.4 s, ~130 KB | worker thread |

Everything on the interactive path is bounded by a constant independent of code count. Symbol cache
keys exclude all geometry, so zooming 100 % → 400 % re-encodes nothing.

---

## Extension points

Deliberately architected but **not implemented** in this build:

- **New output formats** — implement `core.drawlist.Painter`; layout code is untouched.
- **New symbologies** — one encoder module plus one line in `symbols/registry.py`. Code 128,
  Code 39 and Aztec are registered as `UnavailableEncoder`, which refuses at three independent
  layers rather than silently substituting another symbology.
- **Dual track, camera fiducials, CRC blocks** — register as non-splittable `Segment`s and inherit
  the splice guarantee from the packer with no changes to it.
- **Reverse numbering** — already implemented via `Direction.REVERSE`.

## Domain references

- [Pepperl+Fuchs PCV / PXV Data Matrix positioning](https://www.pepperl-fuchs.com/en/products/industrial-sensors/positioning-systems/camera-based-linear-positioning-pcv-pxv-gp31908)
- [Leuze barcode positioning systems (BPS)](https://www.leuze.com/en-int/products/measuring-sensors/sensors-for-positioning/bar-code-positioning-systems)
- [ISO/IEC 15415 — 2D print-quality grading](https://www.iso.org/standard/86390.html) (target grade A or B)
- [ISO/IEC 16022 — Data Matrix](https://www.iso.org/standard/44230.html)
