"""Frozen-build helpers: paths and the crash handler.

Nothing here can test an actual PyInstaller bundle - that is what
packaging/build.py's smoke test is for. What CAN be pinned from source is the
part that must not be wrong in either world: the unfrozen path resolution,
and a crash handler that logs, chains, and never raises.
"""

from __future__ import annotations

import sys

from aops import runtime


def test_source_runs_are_not_frozen():
    assert runtime.is_frozen() is False


def test_resource_path_finds_the_bundled_theme():
    """The one data file the spec collects must resolve from source with the
    same relative path the frozen bundle uses."""
    path = runtime.resource_path("aops/ui/theme/aops.qss")
    assert path.is_file()


def test_crash_log_dir_is_per_user(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert str(runtime.crash_log_dir()).startswith(str(tmp_path))


def test_write_crash_log_records_the_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        raise ValueError("boom for the log")
    except ValueError as exc:
        path = runtime.write_crash_log(type(exc), exc, exc.__traceback__)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "boom for the log" in text
    assert "ValueError" in text


def test_crash_handler_chains_the_previous_hook(monkeypatch, tmp_path):
    """The handler adds logging; it must not swallow the original hook -
    console launches and test harnesses keep their tracebacks."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    seen = {}
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: seen.update(exc=e))

    runtime.install_crash_handler()
    try:
        raise RuntimeError("handled")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)

    assert isinstance(seen.get("exc"), RuntimeError)
    logs = list(runtime.crash_log_dir().glob("crash-*.log"))
    assert logs and "handled" in logs[0].read_text(encoding="utf-8")
