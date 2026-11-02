"""test_v27_window_flash.py - Unit tests and optional live test for window_flash.py.

Demonstrates:
  1. start() is inert under test mode (no real Win32 hook/window created).
  2. stop() on never-started watcher is a safe no-op.
  3. _on_shell_event:
     - HSHELL_FLASH adds HWND
     - HSHELL_WINDOWACTIVATED removes HWND
     - HSHELL_RUDEAPPACTIVATED removes HWND
     - HSHELL_WINDOWDESTROYED removes HWND
     - Unknown event codes are ignored
  4. snapshot_by_exe groups two HWNDs of the same fake exe (case-insensitive) into count 2.
  5. Thread-safety: 4 threads hammering add/remove/snapshot for 1.0 s without exceptions.
  6. OPT-IN Live Test (only when SERIT_ALLOW_REAL_FLASH=1): creates an offscreen helper window,
     calls FlashWindowEx, asserts it appears in flashing_hwnds within 3 s, and cleans up.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import random
import sys
import tempfile
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SERIT_TEST"] = "1"
_tmp_dir = tempfile.mkdtemp(prefix="serit-test-windowflash-")
os.environ["SERIT_LOG"] = str(Path(_tmp_dir) / "test.log")
os.environ["SERIT_CACHE_DIR"] = _tmp_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logpath  # noqa: E402
import window_flash  # noqa: E402
from window_flash import (  # noqa: E402
    FlashWatcher,
    HSHELL_FLASH,
    HSHELL_RUDEAPPACTIVATED,
    HSHELL_WINDOWACTIVATED,
    HSHELL_WINDOWDESTROYED,
)


def test_inert_under_test() -> None:
    """start() under test without SERIT_ALLOW_REAL_FLASH=1 must not create real hooks."""
    assert logpath.is_running_under_test() is True
    old_env = os.environ.pop("SERIT_ALLOW_REAL_FLASH", None)
    try:
        watcher = FlashWatcher()
        watcher.start()
        try:
            # Internal thread and hwnd must not exist
            assert watcher._thread is None
            assert watcher._hwnd == 0
            assert watcher.is_flashing(12345) is False
            assert watcher.flashing_hwnds() == set()
        finally:
            watcher.stop()
    finally:
        if old_env is not None:
            os.environ["SERIT_ALLOW_REAL_FLASH"] = old_env


def test_stop_never_started_is_noop() -> None:
    """stop() on a never-started watcher must be a safe no-op."""
    watcher = FlashWatcher()
    watcher.stop()
    assert watcher.is_flashing(100) is False
    assert watcher.flashing_hwnds() == set()


def test_on_shell_event_lifecycle() -> None:
    """Internal shell events drive addition, removal, and ignore unknowns."""
    watcher = FlashWatcher()
    watcher.start()
    try:
        # 1. Unknown events ignored
        watcher._on_shell_event(99999, 1001)
        watcher._on_shell_event(0, 1001)
        assert watcher.is_flashing(1001) is False
        assert watcher.flashing_hwnds() == set()

        # 2. HSHELL_FLASH adds
        watcher._on_shell_event(HSHELL_FLASH, 1001)
        assert watcher.is_flashing(1001) is True
        assert watcher.flashing_hwnds() == {1001}

        # Adding a second window
        watcher._on_shell_event(HSHELL_FLASH, 1002)
        assert watcher.is_flashing(1001) is True
        assert watcher.is_flashing(1002) is True
        assert watcher.flashing_hwnds() == {1001, 1002}

        # Unknown event doesn't disturb existing hwnds
        watcher._on_shell_event(8888, 1001)
        assert watcher.is_flashing(1001) is True

        # 3. HSHELL_WINDOWACTIVATED removes
        watcher._on_shell_event(HSHELL_WINDOWACTIVATED, 1001)
        assert watcher.is_flashing(1001) is False
        assert watcher.is_flashing(1002) is True
        assert watcher.flashing_hwnds() == {1002}

        # 4. HSHELL_RUDEAPPACTIVATED removes
        watcher._on_shell_event(HSHELL_RUDEAPPACTIVATED, 1002)
        assert watcher.is_flashing(1002) is False
        assert watcher.flashing_hwnds() == set()

        # 5. HSHELL_WINDOWDESTROYED removes
        watcher._on_shell_event(HSHELL_FLASH, 1003)
        assert watcher.is_flashing(1003) is True
        watcher._on_shell_event(HSHELL_WINDOWDESTROYED, 1003)
        assert watcher.is_flashing(1003) is False
        assert watcher.flashing_hwnds() == set()

    finally:
        watcher.stop()


def test_snapshot_by_exe_grouping() -> None:
    """snapshot_by_exe groups two HWNDs of the same fake exe (case-insensitive) into count 2."""
    watcher = FlashWatcher()
    watcher.start()
    try:
        watcher._on_shell_event(HSHELL_FLASH, 2001)
        watcher._on_shell_event(HSHELL_FLASH, 2002)
        watcher._on_shell_event(HSHELL_FLASH, 3001)

        def fake_resolve(hwnd: int) -> str:
            # Fake synthetic executable paths only
            if hwnd == 2001:
                return r"C:\fake\apps\TerminalApp.exe"
            elif hwnd == 2002:
                return r"c:\fake\apps\terminalapp.exe"
            elif hwnd == 3001:
                return r"C:\fake\apps\Browser.exe"
            return ""

        snapshot = watcher.snapshot_by_exe(resolve=fake_resolve)
        assert snapshot.get(r"c:\fake\apps\terminalapp.exe") == 2
        assert snapshot.get(r"c:\fake\apps\browser.exe") == 1
        assert len(snapshot) == 2

    finally:
        watcher.stop()


def test_thread_safety_hammering() -> None:
    """Hammer FlashWatcher add/remove/snapshot with 4 threads for 1.0 second without exceptions."""
    watcher = FlashWatcher()
    watcher.start()
    stop_flag = threading.Event()
    errors: list[Exception] = []

    def worker(worker_id: int) -> None:
        random.seed(worker_id + 42)
        hwnds = [worker_id * 1000 + i for i in range(20)]
        while not stop_flag.is_set():
            try:
                target_hwnd = random.choice(hwnds)
                action = random.random()
                if action < 0.4:
                    watcher._on_shell_event(HSHELL_FLASH, target_hwnd)
                elif action < 0.6:
                    watcher._on_shell_event(HSHELL_WINDOWACTIVATED, target_hwnd)
                elif action < 0.7:
                    watcher._on_shell_event(HSHELL_WINDOWDESTROYED, target_hwnd)
                elif action < 0.85:
                    _ = watcher.is_flashing(target_hwnd)
                    _ = watcher.flashing_hwnds()
                else:
                    _ = watcher.snapshot_by_exe(
                        resolve=lambda h: f"c:\\fake\\hammer_{h % 3}.exe"
                    )
            except Exception as exc:
                errors.append(exc)
                break

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()

    time.sleep(1.0)
    stop_flag.set()

    for t in threads:
        t.join(timeout=2.0)

    watcher.stop()
    assert not errors, f"Hammering encountered errors: {errors}"


def test_live_opt_in() -> bool:
    """OPT-IN live test when SERIT_ALLOW_REAL_FLASH=1."""
    if os.environ.get("SERIT_ALLOW_REAL_FLASH") != "1":
        print("  [LIVE-OPT-IN] Skipped (SERIT_ALLOW_REAL_FLASH != '1')")
        return False

    print("  [LIVE-OPT-IN] Running real Windows ShellHook live test...")
    user32 = ctypes.windll.user32

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", w.UINT),
            ("hwnd", w.HWND),
            ("dwFlags", w.DWORD),
            ("uCount", w.UINT),
            ("dwTimeout", w.DWORD),
        ]

    user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
    user32.FlashWindowEx.restype = w.BOOL

    # Start watcher with real hook
    watcher = FlashWatcher()
    watcher.start()
    assert watcher._hwnd != 0, "Watcher failed to create message window"
    assert watcher._thread is not None and watcher._thread.is_alive()

    # Create an off-screen helper window (-10000, -10000) so no visual disturbance occurs
    WS_POPUP = 0x80000000
    WS_VISIBLE = 0x10000000
    h_helper = user32.CreateWindowExW(
        0,
        window_flash._CLASS_NAME,
        "SeritLiveHelperWindow",
        WS_POPUP | WS_VISIBLE,
        -10000,
        -10000,
        10,
        10,
        0,
        0,
        ctypes.windll.kernel32.GetModuleHandleW(None),
        0,
    )
    assert h_helper != 0, "Failed to create helper window for live flash test"

    try:
        finfo = FLASHWINFO()
        finfo.cbSize = ctypes.sizeof(FLASHWINFO)
        finfo.hwnd = w.HWND(h_helper)
        finfo.dwFlags = 3 | 12  # FLASHW_ALL | FLASHW_TIMERNOFG
        finfo.uCount = 3
        finfo.dwTimeout = 0

        res = user32.FlashWindowEx(ctypes.byref(finfo))
        print(f"  [LIVE-OPT-IN] FlashWindowEx returned: {res}")

        # Wait up to 3 seconds for HSHELL_FLASH delivery
        deadline = time.time() + 3.0
        delivered = False
        while time.time() < deadline:
            if watcher.is_flashing(h_helper):
                delivered = True
                break
            time.sleep(0.05)

        print(f"  [LIVE-OPT-IN] Delivered to watcher: {delivered}")
        assert delivered is True, "Windows Shell failed to deliver HSHELL_FLASH within 3.0s"
        assert h_helper in watcher.flashing_hwnds()
        return True

    finally:
        user32.DestroyWindow(w.HWND(h_helper))
        watcher.stop()


def main() -> None:
    print("=== Running test_v27_window_flash.py ===")
    test_inert_under_test()
    print("  ✓ test_inert_under_test passed")

    test_stop_never_started_is_noop()
    print("  ✓ test_stop_never_started_is_noop passed")

    test_on_shell_event_lifecycle()
    print("  ✓ test_on_shell_event_lifecycle passed")

    test_snapshot_by_exe_grouping()
    print("  ✓ test_snapshot_by_exe_grouping passed")

    test_thread_safety_hammering()
    print("  ✓ test_thread_safety_hammering passed (4 threads, 1.0s)")

    live_ran = test_live_opt_in()
    if live_ran:
        print("  ✓ test_live_opt_in passed (Real Windows Shell delivered HSHELL_FLASH)")

    print("=== All tests finished successfully ===")


if __name__ == "__main__":
    main()
