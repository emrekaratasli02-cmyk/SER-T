"""test_v24_tray_log.py - tepsi tıklamasının olağan satırları log'a yazılmaz, hatalar yazılır (v24).

Zero side effects: LOG_PATH points at a temp file; no tray item is clicked (only _info/_log are called).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

import trayicons  # noqa: E402


def _with_temp_log(fn) -> str:
    fd, name = tempfile.mkstemp(prefix="serit_v24_tray_", suffix=".log")
    os.close(fd)
    old = trayicons.LOG_PATH
    old_env = os.environ.pop("SERIT_DEBUG_TRAY", None)
    trayicons.LOG_PATH = Path(name)
    trayicons._last_log_msg = ""
    try:
        fn()
        return Path(name).read_text(encoding="utf-8")
    finally:
        trayicons.LOG_PATH = old
        if old_env is not None:
            os.environ["SERIT_DEBUG_TRAY"] = old_env
        else:
            os.environ.pop("SERIT_DEBUG_TRAY", None)
        Path(name).unlink(missing_ok=True)


def test_routine_lines_are_silent() -> None:
    text = _with_temp_log(lambda: trayicons._info("activate() called for 'Örnek' button='left'"))
    assert text == "", text


def test_errors_still_logged() -> None:
    text = _with_temp_log(lambda: trayicons._log("UIA InvokePattern failed for 'Örnek': deneme"))
    assert "[trayicons] UIA InvokePattern failed" in text, text


def test_debug_env_brings_routine_lines_back() -> None:
    def run() -> None:
        os.environ["SERIT_DEBUG_TRAY"] = "1"
        trayicons._info("Launched executable 'C:/ornek.exe' for 'Örnek'")

    text = _with_temp_log(run)
    assert "Launched executable" in text, text


def test_activate_uses_info_for_success_lines() -> None:
    import inspect
    src = inspect.getsource(trayicons.activate)
    for phrase in ("activate() called", "Successfully invoked", "Launched executable", "Focused window",
                   "Performed on-screen click"):
        line = next(ln for ln in src.splitlines() if phrase in ln)
        assert "_info(" in line, line
    for phrase in ("failed for", "Failed to launch", "Unexpected error"):
        line = next(ln for ln in src.splitlines() if phrase in ln)
        assert "_log(" in line, line


def run_all() -> None:
    for fn in (test_routine_lines_are_silent, test_errors_still_logged, test_debug_env_brings_routine_lines_back,
               test_activate_uses_info_for_success_lines):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_TRAY_LOG TESTS PASSED")


if __name__ == "__main__":
    run_all()
