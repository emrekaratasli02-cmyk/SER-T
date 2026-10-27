"""tests/test_v20_stall.py - GUI stall detector and log de-duplication.

Plain script (no pytest). Run with:
    .venv/Scripts/python.exe tests/test_v20_stall.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DIR = ROOT / "_ref" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = TMP_DIR / "test_v20_stall.log"
REAL_LOG = ROOT / "serit.log"

os.environ["SERIT_LOG"] = str(LOG_FILE)
os.environ["SERIT_CACHE_DIR"] = str(TMP_DIR)

import sources  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from stall_monitor import StallMonitor  # noqa: E402

_REAL_LOG_BEFORE = (
    REAL_LOG.exists(),
    REAL_LOG.stat().st_mtime_ns if REAL_LOG.exists() else 0,
    REAL_LOG.stat().st_size if REAL_LOG.exists() else 0,
)


def _reset_log() -> None:
    LOG_FILE.write_text("", encoding="utf-8")
    with sources._LOG_DEDUP_LOCK:
        sources._LOG_DEDUP.clear()


def _lines() -> list[str]:
    if not LOG_FILE.exists():
        return []
    return [ln for ln in LOG_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_log_dedup() -> None:
    _reset_log()
    clock = [1000.0]
    original_now = sources._log_now
    sources._log_now = lambda: clock[0]
    try:
        err = RuntimeError("aynı hata")
        for _ in range(50):
            sources.log_err("test", err)
        assert len(_lines()) == 1, _lines()

        clock[0] += 601.0
        sources.log_err("test", err)
        lines = _lines()
        assert len(lines) == 2, lines
        assert "(×49 tekrar)" in lines[-1], lines

        sources.log_err("test", RuntimeError("farklı bir hata"))
        sources.log_err("test", RuntimeError("başka bir hata"))
        lines = _lines()
        assert len(lines) == 4, lines

        for i in range(300):
            sources.log_err("bulk", RuntimeError(f"hata {i}"))
        with sources._LOG_DEDUP_LOCK:
            cached = len(sources._LOG_DEDUP)
        assert cached <= 200, cached
    finally:
        sources._log_now = original_now
        _reset_log()
    print("[PASS] log de-duplication")


def test_short_stall_logged() -> None:
    app = _qapp()
    _reset_log()
    monitor = StallMonitor(None)
    monitor.start()
    try:
        QTimer.singleShot(50, lambda: time.sleep(0.8))
        _pump(app, 2.0)
    finally:
        monitor.stop()

    lines = _lines()
    stalls = [ln for ln in lines if "[ui_stall]" in ln]
    stacks = [ln for ln in lines if "[ui_stall_stack]" in ln]
    assert len(stalls) == 1, lines
    assert not stacks, lines
    match = re.search(r"GUI (\d+) ms durdu", stalls[0])
    assert match is not None, stalls[0]
    assert int(match.group(1)) >= 500, stalls[0]
    stats = monitor.stats()
    assert stats["count"] == 1 and stats["worst_ms"] >= 500, stats
    print("[PASS] short GUI stall logged")


def test_long_stall_dumps_stack() -> None:
    app = _qapp()
    _reset_log()
    monitor = StallMonitor(None)
    monitor.start()
    try:
        QTimer.singleShot(50, lambda: time.sleep(2.0))
        _pump(app, 3.0)
    finally:
        monitor.stop()

    lines = _lines()
    stacks = [ln for ln in lines if "[ui_stall_stack]" in ln]
    assert len(stacks) == 1, lines
    assert "test_v20_stall.py" in stacks[0], stacks[0]
    assert len([ln for ln in lines if "[ui_stall]" in ln]) == 1, lines
    for line in lines:
        assert "=" not in line, line
    print("[PASS] long GUI stall dumps stack (no locals)")


def test_idle_no_false_stalls() -> None:
    app = _qapp()
    _reset_log()
    monitor = StallMonitor(None)
    monitor.start()
    try:
        _pump(app, 3.0)
    finally:
        monitor.stop()

    lines = _lines()
    assert not [ln for ln in lines if "ui_stall" in ln], lines
    assert monitor.stats()["count"] == 0, monitor.stats()
    print("[PASS] 3 s idle produces no stall lines")


def test_real_log_untouched() -> None:
    after = (
        REAL_LOG.exists(),
        REAL_LOG.stat().st_mtime_ns if REAL_LOG.exists() else 0,
        REAL_LOG.stat().st_size if REAL_LOG.exists() else 0,
    )
    assert after == _REAL_LOG_BEFORE, (after, _REAL_LOG_BEFORE)
    assert LOG_FILE.resolve() != REAL_LOG.resolve()
    print("[PASS] real serit.log untouched")


def test_clock_excludes_sleep() -> None:
    """Saat uyku süresini saymayan Windows sayacından gelir ve ileri akar."""
    import stall_monitor

    clk = stall_monitor._make_clock()
    if sys.platform == "win32":
        assert clk is not time.monotonic, "Windows'ta QueryUnbiasedInterruptTime kullanılmalı"
    a = clk()
    time.sleep(0.05)
    b = clk()
    assert 0.02 <= b - a <= 1.0, (a, b)
    # Uyku benzetimi: saat 30 dk atlarsa donma sayılır; uykusuz saatte atlama olmaz
    fake = {"t": 1000.0}
    mon = StallMonitor(None, clock=lambda: fake["t"])
    mon._heartbeat = fake["t"]
    mon._started = True
    fake["t"] += 0.25
    mon._on_tick()
    assert mon.stats()["count"] == 0
    mon._started = False
    print("  [PASS] clock excludes sleep, injectable clock works")


def run_all() -> None:
    test_clock_excludes_sleep()
    print("Running test_v20_stall.py...")
    test_log_dedup()
    test_short_stall_logged()
    test_long_stall_dumps_stack()
    test_idle_no_false_stalls()
    test_real_log_untouched()
    print("ALL TEST_V20_STALL TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all()
