# Building the Windows executable and installer

Two executables come out of one build, in one folder (`dist/AOPS/`):

| File          | What it is                                            |
|---------------|-------------------------------------------------------|
| `AOPS.exe`    | The GUI, windowed - double-click and design strips.   |
| `aops-cli.exe`| The headless interface, for scripts and build servers.|

`AOPS-Setup-<version>.exe` wraps that folder into a normal Windows
installer: Program Files, Start-menu entry, optional desktop icon, `.aops`
file association (double-clicking a project opens it in AOPS), clean
uninstall via Windows Settings.

## Option A - build on your Windows machine

1. Install Python 3.12+ from python.org (tick "Add to PATH").
2. From the repository root:

       py -m pip install . pyinstaller
       py packaging\build.py

   This freezes the app into `dist\AOPS\` **and smoke-tests it**: the frozen
   CLI encodes a symbol through the bundled libdmtx DLL, writes and exports a
   project end to end, and the GUI constructs its full window offscreen. If
   the smoke test passes, the folder is shippable as-is (portable app).

3. For the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php)
   (or `choco install innosetup`), then:

       py packaging\build.py --installer

   Result: `dist\AOPS-Setup-<version>.exe`.

## Option B - no Windows machine: let GitHub build it

The `Windows build` workflow (Actions tab -> "Windows build" -> Run
workflow) runs the exact same `build.py` on a GitHub Windows runner and
uploads two artifacts: the installer and the portable folder. Pushing a tag
like `v1.0.0` triggers it automatically.

## What the pieces are

- `aops.spec` - the PyInstaller recipe. One-folder build (fast start, no
  antivirus-provoking self-extraction), both executables, the libdmtx DLL
  collected explicitly (ctypes loads it at import; static analysis cannot
  see that), the theme stylesheet bundled, and the unused half of Qt
  excluded.
- `installer.iss` - the Inno Setup recipe (version passed in by build.py).
- `build.py` - freeze, smoke-test, compile installer. The smoke test is the
  point: freezing fails in ways that compile fine, and every historic
  failure mode here (missing DLL, over-trimmed Qt, lazy import) is caught by
  actually running the frozen executables.
- `launch_gui.py` / `launch_cli.py` - entry shims the spec points at.
- `aops.ico` - the app icon: the Data Matrix for position 000000, rendered
  by AOPS itself.
- `src/aops/runtime.py` - frozen-build awareness: crash logs go to
  `%LOCALAPPDATA%\AOPS\logs` (a windowed exe has no console, so unhandled
  errors must land somewhere the user can find and send back).

## Version bumps

The single source of truth is `__version__` in `src/aops/__init__.py`
(mirrored in `pyproject.toml`). The installer name, the setup's displayed
version and the CLI's `--version` all read from it.
