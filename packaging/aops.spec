# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for AOPS.

Run from the repository root, inside an environment where `pip install .`
and `pip install pyinstaller` have already happened:

    pyinstaller packaging/aops.spec --noconfirm

Produces ``dist/AOPS/`` - one folder holding both executables:

    AOPS.exe       the GUI (windowed - no console flashes up behind it)
    aops-cli.exe   the headless interface, for build servers and scripts

One-folder rather than one-file, deliberately: one-file unpacks itself to a
temp directory on every launch (slow, and quarantine-prone under antivirus),
and the installer wraps the folder anyway so the user never sees it.

The native piece that needs explicit care is libdmtx: pylibdmtx loads its
DLL via ctypes at import time, which static analysis cannot see, so the DLL
is collected explicitly. The qrcode package is pure Python and needs only a
hidden-import nudge for the same reason.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
SRC = str(ROOT / "src")

BINARIES = collect_dynamic_libs("pylibdmtx")
DATAS = [(str(ROOT / "src" / "aops" / "ui" / "theme" / "aops.qss"), "aops/ui/theme")]
HIDDEN = ["qrcode", "pylibdmtx.pylibdmtx"]

# Qt ships far more than a Widgets app uses. Everything here is unrelated to
# AOPS (no QML, no web, no multimedia, no 3D); trimming it roughly halves the
# install. The GUI self-test in packaging/build.py is what proves the trim
# did not cut a load-bearing module.
QT_EXCLUDES = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets",
    "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
]
EXCLUDES = ["tkinter", *QT_EXCLUDES]

ICON = str(ROOT / "packaging" / "aops.ico")


def analyse(script: str):
    return Analysis(  # noqa: F821
        [str(ROOT / "packaging" / script)],
        pathex=[SRC],
        binaries=BINARIES,
        datas=DATAS,
        hiddenimports=HIDDEN,
        excludes=EXCLUDES,
        noarchive=False,
    )


gui = analyse("launch_gui.py")
cli = analyse("launch_cli.py")

gui_exe = EXE(  # noqa: F821
    PYZ(gui.pure),  # noqa: F821
    gui.scripts,
    [],
    exclude_binaries=True,
    name="AOPS",
    icon=ICON,
    console=False,
    upx=False,
)

cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    [],
    exclude_binaries=True,
    name="aops-cli",
    icon=ICON,
    console=True,
    upx=False,
)

COLLECT(  # noqa: F821
    gui_exe, gui.binaries, gui.datas,
    cli_exe, cli.binaries, cli.datas,
    name="AOPS",
    upx=False,
)
