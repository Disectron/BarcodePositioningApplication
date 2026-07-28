#!/usr/bin/env bash
# ===================================================================
#  AOPS - Linux / macOS launcher.
#
#      ./run.sh                 GUI
#      ./run.sh info            headless summary
#      ./run.sh export -o out   headless export
#
#  On the FIRST run it creates .venv and installs dependencies.
#  Every run after that starts immediately.
#
#  Note: pylibdmtx binds to the native libdmtx library, which pip
#  cannot install. Install it first:
#      Debian/Ubuntu:  sudo apt-get install -y libdmtx-dev
#      macOS:          brew install libdmtx
# ===================================================================
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
VPY="$VENV/bin/python"
# Written only after a successful install. Its presence - not the mere
# existence of the venv - is what marks setup as complete. "python -m venv"
# creates bin/python BEFORE installing anything, so gating on the interpreter
# would strand an interrupted install in a half-built venv forever.
STAMP="$VENV/.aops-install-complete"

die() {
    printf '\n  %s\n\n' "$*" >&2
    exit 1
}

find_python() {
    for candidate in python3.13 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)' 2>/dev/null; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

# Short-circuits so the probe never runs when the stamp is absent, and sits
# inside an `if` condition so `set -e` does not fire on a non-zero probe.
if [ ! -f "$STAMP" ] || ! "$VPY" -c '' >/dev/null 2>&1; then
    printf '\n  First run - setting up. This happens once.\n\n'

    basepy="$(find_python)" || die "Python 3.12 or newer was not found. Install it and try again."

    # Required, not merely tidy: re-running venv over an existing tree leaves a
    # dangling bin/python symlink in place (CPython skips an existing symlink),
    # so a stale venv would never repair itself.
    rm -rf "$VENV"

    printf '  Using %s\n' "$basepy"
    printf '  Creating virtual environment in %s ...\n' "$VENV"
    "$basepy" -m venv "$VENV" || die "Could not create the virtual environment."

    printf '  Installing dependencies, please wait ...\n\n'
    # `|| true`: a failed self-upgrade is harmless, but under `set -e` it would
    # abort before the friendly handler on the real install below could run.
    "$VPY" -m pip install --upgrade pip --quiet || true
    "$VPY" -m pip install -r requirements.txt ||
        die "Dependency installation failed. Check your connection and run this again - setup will start over."

    touch "$STAMP"

    printf '\n  Setup complete.\n\n'
fi

exec "$VPY" run.py "$@"
