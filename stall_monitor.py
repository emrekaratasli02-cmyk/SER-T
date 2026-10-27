"""GUI stall (freeze) detector for Şerit.

The GUI thread runs a lightweight QTimer heartbeat. A daemon watchdog thread
notices when that heartbeat stops advancing and, once per stall, writes the GUI
thread's Python stack (file:line function names only) to the log. Local
variables, arguments and source-line values are never read or logged.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Qt

import sources


def _make_clock() -> Callable[[], float]:
    """Seconds clock that does NOT advance while the PC sleeps or hibernates.

    time.monotonic() keeps counting through suspend on Windows, so closing the
    laptop lid would be logged as a giant fake GUI stall. QueryUnbiasedInterruptTime
    excludes suspend time (100 ns units, ~15.6 ms resolution, plenty for 300 ms).
    Falls back to time.monotonic() elsewhere.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            k32 = ctypes.WinDLL("kernel32")  # own instance: no global argtypes change
            fn = k32.QueryUnbiasedInterruptTime
            fn.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
            fn.restype = ctypes.c_int
            probe = ctypes.c_ulonglong(0)
            if fn(ctypes.byref(probe)):
                def _clock() -> float:
                    buf = ctypes.c_ulonglong(0)  # per call: GUI + watchdog threads
                    fn(ctypes.byref(buf))
                    return buf.value / 1e7

                return _clock
        except Exception:
            pass
    return time.monotonic


class UiStall(Exception):
    """Carries a GUI stall message to sources.log_err (never raised)."""


class UiStallStack(UiStall):
    """Carries a GUI stall stack message to sources.log_err (never raised)."""


class StallMonitor(QObject):
    """Detects GUI-thread stalls and logs evidence without measurable overhead."""

    def __init__(
        self,
        parent_qobject: Optional[QObject] = None,
        tick_ms: int = 250,
        stall_ms: int = 300,
        dump_after_ms: int = 1500,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        super().__init__(parent_qobject)
        self._tick_ms = max(1, int(tick_ms))
        self._stall_ms = max(0, int(stall_ms))
        self._dump_after_ms = max(1, int(dump_after_ms))
        self._clock = clock or _make_clock()

        self._lock = threading.Lock()
        self._heartbeat = self._clock()
        self._gui_thread_ident = threading.get_ident()
        self._pending_top: Optional[str] = None
        self._stack_logged = False
        self._stalls: Deque[Dict[str, Any]] = deque(maxlen=20)
        self._count = 0
        self._worst_ms = 0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(self._tick_ms)
        self._timer.timeout.connect(self._on_tick)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Start the GUI heartbeat and the watchdog thread."""
        if self._started:
            return
        self._started = True
        self._gui_thread_ident = threading.get_ident()
        with self._lock:
            self._heartbeat = self._clock()
            self._pending_top = None
            self._stack_logged = False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watchdog,
            name="serit-stall-watchdog",
            daemon=True,
        )
        self._thread.start()
        self._timer.start()

    def stop(self) -> None:
        """Stop the timer and join the watchdog with a short timeout."""
        if not self._started:
            return
        self._started = False
        self._timer.stop()
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def stats(self) -> Dict[str, Any]:
        """Return stall statistics for a future settings page."""
        with self._lock:
            return {
                "count": self._count,
                "worst_ms": self._worst_ms,
                "last": [dict(item) for item in self._stalls],
            }

    # -- GUI side ---------------------------------------------------------
    def _on_tick(self) -> None:
        if not self._started:
            return
        now = self._clock()
        with self._lock:
            gap = now - self._heartbeat
            self._heartbeat = now
            top = self._pending_top or "—"
            self._pending_top = None
            self._stack_logged = False
        stall_ms = int(round((gap - self._tick_ms / 1000.0) * 1000.0))
        if stall_ms >= self._stall_ms:
            self._record_stall(stall_ms, top)

    def _record_stall(self, ms: int, top: str) -> None:
        with self._lock:
            self._count += 1
            if ms > self._worst_ms:
                self._worst_ms = ms
            self._stalls.append({"ms": ms, "time": time.time(), "top": top})
        try:
            where = f" · {top}" if top and top != "—" else ""
            sources.log_err("ui_stall", UiStall(f"GUI {ms} ms durdu{where}"))
        except Exception:
            pass

    # -- watchdog side ----------------------------------------------------
    def _watchdog(self) -> None:
        while not self._stop_event.wait(0.25):
            now = self._clock()
            with self._lock:
                hb = self._heartbeat
                ident = self._gui_thread_ident
                already = self._stack_logged
                pending = self._pending_top
            age_ms = (now - hb) * 1000.0
            if age_ms < self._stall_ms:
                continue
            frame = sys._current_frames().get(ident)
            if frame is None:
                continue
            if pending is None:
                self._remember_top(frame, hb)
            if already or age_ms < self._dump_after_ms:
                continue
            self._log_stack(frame, hb, age_ms)

    def _remember_top(self, frame: Any, hb: float) -> None:
        top = self._frame_label(frame)
        with self._lock:
            if self._heartbeat == hb and self._pending_top is None:
                self._pending_top = top

    def _log_stack(self, frame: Any, hb: float, age_ms: float) -> None:
        with self._lock:
            if self._heartbeat != hb or self._stack_logged:
                return
            self._stack_logged = True
        try:
            frames = traceback.extract_stack(frame)
        except Exception:
            return
        labels = [self._summary_label(f) for f in reversed(frames[-8:])]
        ms = int(round(age_ms))
        try:
            sources.log_err(
                "ui_stall_stack",
                UiStallStack(f"GUI {ms} ms durdu; yığın: " + " <- ".join(labels)),
            )
        except Exception:
            pass

    @staticmethod
    def _frame_label(frame: Any) -> str:
        code = frame.f_code
        return f"{os.path.basename(code.co_filename)}:{frame.f_lineno} {code.co_name}"

    @staticmethod
    def _summary_label(summary: Any) -> str:
        return f"{os.path.basename(summary.filename)}:{summary.lineno} {summary.name}"
