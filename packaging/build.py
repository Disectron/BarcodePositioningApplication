"""One-command Windows build: freeze, smoke-test, and optionally wrap in an
installer.

    python packaging/build.py               -> dist/AOPS/  (AOPS.exe + aops-cli.exe)
    python packaging/build.py --installer   -> dist/AOPS-Setup-<version>.exe

Run from anywhere; the script anchors itself to the repository root. It
expects the project and PyInstaller installed into the current Python
(``pip install . pyinstaller``), and - for --installer - Inno Setup 6
(``ISCC`` on PATH or in its default install directory).

The smoke test is not optional. Freezing fails in ways that compile fine:
a DLL not collected, a Qt plugin trimmed too far, a lazy import missed by
static analysis. Every one of those is caught by actually running the frozen
executables before anything gets shipped.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "AOPS"
EXE = ".exe" if sys.platform == "win32" else ""


def version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from aops import __version__

    return __version__


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kw)


def freeze() -> None:
    run([sys.executable, "-m", "PyInstaller", "packaging/aops.spec", "--noconfirm", "--clean"])


def smoke() -> None:
    """Exercise every fragile seam of the frozen build."""
    cli = DIST / f"aops-cli{EXE}"
    gui = DIST / f"AOPS{EXE}"

    run([cli, "--version"])
    # `symbol` encodes through the bundled libdmtx DLL - the one native
    # dependency static analysis cannot see.
    run([cli, "symbol", "000000"])

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "smoke.aops"
        run([cli, "new", "--out", project])
        run([cli, "info", "--project", project])
        # A real export: pagination, symbol rendering, ReportLab, decode
        # verification - the whole output path, frozen.
        run([cli, "export", "--project", project, "--out", tmp, "--quiet"])
        wrote = list(Path(tmp).glob("*.pdf"))
        if not wrote:
            raise SystemExit("smoke: export produced no PDF")
        print(f"smoke: export wrote {len(wrote)} PDF(s)")

    # Constructing the full window proves Qt plugins, theme and panels
    # survived freezing; offscreen so no display is needed.
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([str(gui), "--selftest"], check=True, cwd=ROOT, env=env)
    print("smoke: GUI self-test passed")


def find_iscc() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for candidate in (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def installer() -> None:
    if sys.platform != "win32":
        raise SystemExit("--installer needs Windows (Inno Setup).")
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit(
            "Inno Setup 6 not found. Install it from jrsoftware.org (or "
            "'choco install innosetup') and re-run."
        )
    run([iscc, "packaging/installer.iss", f"/DAppVersion={version()}"])
    setup = ROOT / "dist" / f"AOPS-Setup-{version()}.exe"
    print(f"installer: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", action="store_true",
                        help="also compile the Inno Setup installer")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="skip the frozen-build smoke test (CI debugging only)")
    args = parser.parse_args()

    freeze()
    if not args.skip_smoke:
        smoke()
    if args.installer:
        installer()
    print(f"done: {DIST}")


if __name__ == "__main__":
    main()
