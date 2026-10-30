"""test_bekci.py - Unit tests for Şerit dock crash watchdog (serit_bekci.pyw).

Covers all required watchdog behaviors with full mocking:
1. Crash -> restore taskbar + release AppBar + restart dock.
2. 4th crash within 10 minutes -> no restart, taskbar visible (autohide off), watchdog stops.
3. Valid .clean_exit marker -> no restart, watchdog stops (exit code alone never counts).
4. Dikte (dikte.pyw / bekci.pyw) process with same pythonw.exe is ignored.
5. Single-instance named mutex enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import psutil
import serit_bekci
import winapi


class TestBekciIsolationAndFiltering(unittest.TestCase):
    """Test Case 4: Process identification and Dikte isolation."""

    def test_dikte_pyw_process_is_ignored(self) -> None:
        """Processes running dikte.pyw or bekci.pyw with pythonw.exe must NOT match."""
        # Process running dikte.pyw
        proc_dikte = MagicMock(spec=psutil.Process)
        proc_dikte.pid = 9991
        proc_dikte.cmdline.return_value = [
            r"D:\Apps\dikte\.venv\Scripts\pythonw.exe",
            r"D:\Apps\dikte\dikte.pyw",
        ]
        self.assertFalse(serit_bekci.is_dock_process(proc_dikte))

        # Process running dikte bekci.pyw
        proc_dikte_bekci = MagicMock(spec=psutil.Process)
        proc_dikte_bekci.pid = 9992
        proc_dikte_bekci.cmdline.return_value = [
            r"D:\Apps\dikte\.venv\Scripts\pythonw.exe",
            r"D:\Apps\dikte\bekci.pyw",
        ]
        self.assertFalse(serit_bekci.is_dock_process(proc_dikte_bekci))

        # Random python process
        proc_other = MagicMock(spec=psutil.Process)
        proc_other.pid = 9993
        proc_other.cmdline.return_value = [r"python.exe", r"-m", r"pytest"]
        self.assertFalse(serit_bekci.is_dock_process(proc_other))

    def test_serit_v5_is_identified(self) -> None:
        """Only process with an argument ending in serit_v5.pyw is identified."""
        proc_serit = MagicMock(spec=psutil.Process)
        proc_serit.pid = 9994
        proc_serit.cmdline.return_value = [
            r"D:\Apps\dikte\.venv\Scripts\pythonw.exe",
            r"D:\Apps\serit\serit_v5.pyw",
        ]
        self.assertTrue(serit_bekci.is_dock_process(proc_serit))

        # Relative or forward-slash path also matches
        proc_serit_fwd = MagicMock(spec=psutil.Process)
        proc_serit_fwd.pid = 9995
        proc_serit_fwd.cmdline.return_value = [
            r"pythonw.exe",
            "D:/Apps/serit/serit_v5.pyw",
        ]
        self.assertTrue(serit_bekci.is_dock_process(proc_serit_fwd))

    def test_find_dock_process_skips_dikte(self) -> None:
        """find_dock_process() finds only serit_v5, skipping dikte processes."""
        proc_dikte = MagicMock(spec=psutil.Process)
        proc_dikte.pid = 1001
        proc_dikte.cmdline.return_value = [r"D:\Apps\dikte\.venv\Scripts\pythonw.exe", r"D:\Apps\dikte\dikte.pyw"]

        proc_serit = MagicMock(spec=psutil.Process)
        proc_serit.pid = 1002
        proc_serit.cmdline.return_value = [r"D:\Apps\dikte\.venv\Scripts\pythonw.exe", r"D:\Apps\serit\serit_v5.pyw"]

        with patch("serit_bekci.psutil.process_iter", return_value=[proc_dikte, proc_serit]):
            found = serit_bekci.find_dock_process()
            self.assertIsNotNone(found)
            self.assertEqual(found.pid, 1002)


class TestSingleInstance(unittest.TestCase):
    """Test Case 5: Single-instance mutex enforcement."""

    def test_single_instance_acquisition_and_conflict(self) -> None:
        """First instance acquires named mutex, second instance fails and flags already_running."""
        test_mutex_name = f"Local\\SeritBekci_Test_{int(time.time() * 1000)}"

        m1 = serit_bekci.SingleInstance(name=test_mutex_name)
        acquired1 = m1.acquire()
        self.assertTrue(acquired1)
        self.assertFalse(m1.already_running)

        try:
            m2 = serit_bekci.SingleInstance(name=test_mutex_name)
            acquired2 = m2.acquire()
            self.assertFalse(acquired2)
            self.assertTrue(m2.already_running)
        finally:
            m1.release()

        # After m1 is released, acquiring on the same name should succeed
        m3 = serit_bekci.SingleInstance(name=test_mutex_name)
        acquired3 = m3.acquire()
        self.assertTrue(acquired3)
        m3.release()

    def test_single_instance_mocked(self) -> None:
        """Test acquire logic when GetLastError returns ERROR_ALREADY_EXISTS (183)."""
        with patch.object(serit_bekci.ctypes.windll.kernel32, "CreateMutexW", return_value=12345), \
             patch.object(serit_bekci.ctypes.windll.kernel32, "GetLastError", return_value=183), \
             patch.object(serit_bekci.ctypes.windll.kernel32, "CloseHandle") as mock_close:
            si = serit_bekci.SingleInstance("Local\\TestMocked")
            self.assertFalse(si.acquire())
            self.assertTrue(si.already_running)
            mock_close.assert_called_once_with(12345)


class TestCleanExitDetection(unittest.TestCase):
    """Test clean exit detection vs crash classification."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_bekci_test_")
        self.tmp_path = Path(self.tmp_dir)
        self.settings_file = self.tmp_path / "settings.json"
        self.marker_file = self.tmp_path / ".clean_exit"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


class TestWatchdogCore(unittest.TestCase):
    """Core watchdog tests covering Crash 1, 2, 3, 4 and state restoration."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_bekci_core_")
        self.tmp_path = Path(self.tmp_dir)
        self.settings_file = self.tmp_path / "settings.json"
        self.marker_file = self.tmp_path / ".clean_exit"

        # Default settings: hide_taskbar=True, taskbar_original=False
        self.settings_file.write_text(
            json.dumps({"hide_taskbar": True, "taskbar_original": False}),
            encoding="utf-8",
        )

        self.bekci = serit_bekci.SeritBekci(
            poll_interval=0.1,
            max_restarts=3,
            window_seconds=600.0,
            settings_path=self.settings_file,
            marker_path=self.marker_file,
            app_dir=self.tmp_path,
        )
        self.bekci.running = True
        # Never look at the real machine's processes (a live dock must not be "attached").
        p = patch("serit_bekci.find_dock_process", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("serit_bekci.launch_dock")
    @patch.object(winapi, "taskbar_autohide_set")
    @patch.object(winapi.shell32, "SHAppBarMessage")
    def test_case_1_crash_restores_and_restarts(
        self,
        mock_sh_appbar: MagicMock,
        mock_autohide: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """Test Case 1: Dock crash restores taskbar, releases AppBar, and restarts dock."""
        mock_new_child = MagicMock()
        mock_new_child.pid = 5002
        mock_new_child.poll.return_value = None
        mock_launch.return_value = mock_new_child

        # Simulate currently running child that crashes with exit code 1
        crashed_child = MagicMock()
        crashed_child.pid = 5001
        crashed_child.poll.return_value = 1  # exited with error

        self.bekci.child_proc = crashed_child
        self.bekci.dock_hwnd = 12345

        # Execute monitoring tick
        self.bekci.step()

        # 1. Taskbar restored respecting taskbar_original=False (autohide off)
        mock_autohide.assert_called_once_with(False)

        # 2. AppBar released via SHAppBarMessage(1, ...)
        mock_sh_appbar.assert_called_once()
        call_msg_id = mock_sh_appbar.call_args[0][0]
        self.assertEqual(call_msg_id, serit_bekci.ABM_REMOVE)

        # 3. Dock restarted
        mock_launch.assert_called_once()
        self.assertEqual(len(self.bekci.crash_timestamps), 1)
        self.assertTrue(self.bekci.running)
        self.assertEqual(self.bekci.child_proc, mock_new_child)

    @patch("serit_bekci.launch_dock")
    @patch.object(winapi, "taskbar_autohide_set")
    @patch.object(winapi.shell32, "SHAppBarMessage")
    def test_case_2_fourth_crash_within_10min_stops_with_taskbar_visible(
        self,
        mock_sh_appbar: MagicMock,
        mock_autohide: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """Test Case 2: 4th crash within 10 minutes stops watchdog, leaves taskbar visible, no restart."""
        # Preload 3 crash timestamps within last 2 minutes
        now = time.time()
        self.bekci.crash_timestamps = [now - 120, now - 60, now - 10]

        # 4th crash occurs
        crashed_child = MagicMock()
        crashed_child.pid = 6001
        crashed_child.poll.return_value = 3221225477  # Access violation crash code

        self.bekci.child_proc = crashed_child
        self.bekci.dock_hwnd = 22222

        self.bekci.step()

        # Assertions for 4th crash:
        # 1. 4 crashes recorded
        self.assertEqual(len(self.bekci.crash_timestamps), 4)

        # 2. Taskbar restored with autohide=False (visible)
        mock_autohide.assert_called_with(False)

        # 3. AppBar released
        mock_sh_appbar.assert_called_once()

        # 4. Dock was NOT restarted on 4th crash
        mock_launch.assert_not_called()

        # 5. Watchdog has stopped running
        self.assertFalse(self.bekci.running)

    @patch("serit_bekci.launch_dock")
    @patch.object(winapi, "taskbar_autohide_set")
    @patch.object(winapi.shell32, "SHAppBarMessage")
    def test_case_3_exit_code_zero_child_no_restart(
        self,
        mock_sh_appbar: MagicMock,
        mock_autohide: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """Test Case 3: child exits after writing a valid marker: no restart, watchdog stops."""
        clean_child = MagicMock()
        clean_child.pid = 7001
        clean_child.poll.return_value = 0  # Clean normal exit
        self.bekci.started_at = time.time() - 30
        self.marker_file.write_text(
            json.dumps({"pid": 7002, "ppid": 7001, "t": time.time()}), encoding="utf-8"
        )

        self.bekci.child_proc = clean_child
        self.bekci.dock_hwnd = 33333

        self.bekci.step()

        # Assertions:
        # 1. Dock NOT restarted
        mock_launch.assert_not_called()

        # 2. Watchdog stopped
        self.assertFalse(self.bekci.running)

        # 3. No crash recorded
        self.assertEqual(len(self.bekci.crash_timestamps), 0)

        # 4. Did not trigger crash recovery
        mock_autohide.assert_not_called()
        mock_sh_appbar.assert_not_called()

    @patch("serit_bekci.launch_dock")
    @patch.object(winapi, "taskbar_autohide_set")
    @patch.object(winapi.shell32, "SHAppBarMessage")
    def test_crashes_expire_after_window(
        self,
        mock_sh_appbar: MagicMock,
        mock_autohide: MagicMock,
        mock_launch: MagicMock,
    ) -> None:
        """Crashes older than window_seconds (600s) expire and do not count toward limit."""
        now = time.time()
        # 3 crashes that occurred 15, 14, and 12 minutes ago (> 600s ago)
        self.bekci.crash_timestamps = [now - 900, now - 840, now - 720]

        # New crash occurs now
        crashed_child = MagicMock()
        crashed_child.pid = 8001
        crashed_child.poll.return_value = 1

        self.bekci.child_proc = crashed_child

        self.bekci.step()

        # Old crashes expired, only 1 recent crash remains
        self.assertEqual(len(self.bekci.crash_timestamps), 1)

        # Dock was restarted because it was under the budget
        mock_launch.assert_called_once()
        self.assertTrue(self.bekci.running)

    def test_settings_json_is_never_written(self) -> None:
        """Watchdog reads settings but must NEVER write to settings.json."""
        orig_content = self.settings_file.read_text(encoding="utf-8")
        orig_mtime = self.settings_file.stat().st_mtime_ns

        # Run multiple operations (restore taskbar, clean exit checks, etc.)
        with patch.object(winapi, "taskbar_autohide_set"):
            serit_bekci.restore_taskbar(settings_path=self.settings_file)
            serit_bekci.is_clean_exit(marker_path=self.marker_file, watched_pids=[1])

        new_content = self.settings_file.read_text(encoding="utf-8")
        new_mtime = self.settings_file.stat().st_mtime_ns

        self.assertEqual(orig_content, new_content)
        self.assertEqual(orig_mtime, new_mtime)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
