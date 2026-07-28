#!/usr/bin/env python3
"""Zero-install launcher for AOPS.

The package lives under ``src/``, which is the standard "src layout". It keeps
the test suite honest - tests import the installed package rather than
accidentally picking up the working directory - but it has one sharp edge:

    python src/aops/app.py          <-- ModuleNotFoundError: No module named 'aops'

Running a file directly puts *that file's own directory* on ``sys.path``, i.e.
``src/aops/``, not ``src/``. So ``import aops`` finds nothing. This launcher puts
``src/`` on the path first, so it works from a plain checkout with nothing
installed and no environment variables set:

    python run.py                   GUI
    python run.py info              same as: python -m aops.cli info
    python run.py export -o ./out   same as: python -m aops.cli export -o ./out
    python run.py symbol 010500     same as: python -m aops.cli symbol 010500

Deliberately written for old Python syntax so that the "you need 3.12+" message
can actually print on 3.8 instead of dying with a SyntaxError first.
"""

import os
import sys

MIN_PYTHON = (3, 12)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")

#: import name -> (pip name, needed for the GUI only?)
REQUIREMENTS = [
    ("PySide6", "PySide6", True),
    ("reportlab", "reportlab", False),
    ("PIL", "Pillow", False),
    ("qrcode", "qrcode", False),
    ("pylibdmtx", "pylibdmtx", False),
]

RULE = "=" * 70


def _box(title, lines):
    """Print a plain-English error block. Returns 1 so callers can `return _box(...)`."""
    out = ["", RULE, "  " + title, RULE]
    out.extend(lines)
    out.append("")
    sys.stderr.write("\n".join(out) + "\n")
    return 1


def _pip_command(missing):
    """The exact command to install what is missing, for this interpreter."""
    return '"%s" -m pip install %s' % (sys.executable, " ".join(missing))


def check_python():
    """Refuse early, with a useful message, on an unsupported interpreter."""
    if sys.version_info >= MIN_PYTHON:
        return 0
    running = "%d.%d.%d" % sys.version_info[:3]
    needed = "%d.%d" % MIN_PYTHON
    return _box(
        "AOPS needs Python %s or newer" % needed,
        [
            "  You are running Python %s from:" % running,
            "    %s" % sys.executable,
            "",
            "  Install Python %s+ from https://www.python.org/downloads/" % needed,
            "  On Windows, tick 'Add python.exe to PATH' in the installer, then",
            "  run this launcher with the version-specific launcher:",
            "",
            "    py -3.12 run.py",
        ],
    )


def check_dependencies(need_gui):
    """Report every missing package at once, rather than one traceback at a time."""
    import importlib.util

    missing = []
    for module_name, pip_name, gui_only in REQUIREMENTS:
        if gui_only and not need_gui:
            continue
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_name)

    if not missing:
        return 0

    lines = [
        "  These packages are not installed for this interpreter:",
        "",
    ]
    lines.extend("    - %s" % name for name in missing)
    lines.extend(
        [
            "",
            "  Install them with:",
            "",
            "    %s" % _pip_command(missing),
            "",
            "  Or install everything at once:",
            "",
            # Absolute: this box is meant to be copy-pasteable from any cwd,
            # and run.py never assumes it is running from the project root.
            '    "%s" -m pip install -r "%s"'
            % (sys.executable, os.path.join(HERE, "requirements.txt")),
        ]
    )
    if "pylibdmtx" in missing and not sys.platform.startswith("win"):
        lines.extend(
            [
                "",
                "  NOTE: pylibdmtx is a binding to the native libdmtx library, which pip",
                "  cannot install on Linux/macOS. Install it with your system package",
                "  manager first:",
                "",
                "    Debian/Ubuntu:  sudo apt-get install -y libdmtx-dev",
                "    macOS:          brew install libdmtx",
            ]
        )
    return _box("Missing dependencies", lines)


def check_layout():
    """Catch a broken or partial copy of the project before it confuses anyone."""
    if os.path.isdir(os.path.join(SRC, "aops")):
        return 0
    return _box(
        "Could not find the AOPS package",
        [
            "  Expected to find:",
            "    %s" % os.path.join(SRC, "aops"),
            "",
            "  This launcher must stay in the project root, next to the src/ folder.",
            "  If you extracted an archive, make sure you extracted all of it.",
        ],
    )


def _qt_platform_hint(exc):
    """Qt fails differently per platform, so the advice has to differ too.

    On Linux this is nearly always a missing runtime library on a headless host.
    On Windows it is a broken PySide6 install - a missing MSVC redistributable,
    an antivirus-quarantined DLL - and apt-get advice would be useless noise to
    the very user this launcher exists to help.
    """
    lines = ["  %s" % exc, ""]

    if sys.platform.startswith("win"):
        lines.extend(
            [
                "  Qt failed to load. This is usually a broken or incomplete PySide6",
                "  installation rather than a problem with AOPS itself.",
                "",
                "  Try, in order:",
                "",
                "    1. Install the Microsoft Visual C++ Redistributable (x64):",
                "       https://aka.ms/vs/17/release/vc_redist.x64.exe",
                "       Then run run.bat again.",
                "",
                "    2. Delete the .venv folder next to run.bat and run run.bat again.",
                "       That rebuilds the environment and reinstalls PySide6.",
                "",
                "    3. If your antivirus quarantined a file, restore it or add an",
                "       exclusion for this folder.",
            ]
        )
    else:
        lines.extend(
            [
                "  This usually means Qt cannot open a display, or a Qt runtime",
                "  library is missing.",
                "",
                "  On a desktop, make sure you are running from a normal graphical session.",
                "  On a headless Linux host, install the Qt runtime libraries:",
                "",
                "    sudo apt-get install -y libegl1 libxkbcommon-x11-0 libxcb-cursor0 \\",
                "        libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-render-util0",
            ]
        )

    lines.extend(
        [
            "",
            "  Or skip the GUI entirely and use the command line:",
            "",
            "    python run.py info",
            "    python run.py export -o ./out",
        ]
    )
    return _box("The GUI could not start", lines)


def main(argv):
    status = check_python()
    if status:
        return status

    status = check_layout()
    if status:
        return status

    # Ahead of any installed copy, so a checkout always runs its own source.
    if SRC not in sys.path:
        sys.path.insert(0, SRC)

    args = list(argv[1:])
    want_gui = not args

    status = check_dependencies(need_gui=want_gui)
    if status:
        return status

    if want_gui:
        try:
            # Importing aops.app pulls in PySide6, which is where a missing Qt
            # runtime library (libEGL.so.1 and friends) surfaces. That happens on
            # the import itself, so the import has to be inside the try.
            from aops.app import main as gui_main

            return gui_main()
        except ImportError as exc:
            return _qt_platform_hint(exc)

    from aops.cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
