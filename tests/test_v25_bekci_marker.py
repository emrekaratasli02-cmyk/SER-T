"""Tests for the bekci .clean_exit marker rules and logpath.write_clean_exit_marker."""

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

import logpath
import serit_bekci
import winapi

VENV_PY = Path("D:/Apps/serit/.venv/Scripts/python.exe")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="serit_marker_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.marker = self.tmp / ".clean_exit"
        self.settings = self.tmp / "settings.json"
        self.settings.write_text(json.dumps({"hide_taskbar": True}), encoding="utf-8")
        self.bekci = serit_bekci.SeritBekci(
            poll_interval=0.05, settings_path=self.settings, marker_path=self.marker,
            app_dir=self.tmp,
        )
        self.bekci.running = True
        self.bekci.started_at = time.time() - 60
        self.fdp = patch("serit_bekci.find_dock_process", return_value=None)
        self.fdp.start()
        self.addCleanup(self.fdp.stop)
        for target in (
            patch.object(winapi, "taskbar_autohide_set"),
            patch.object(winapi.shell32, "SHAppBarMessage"),
        ):
            target.start()
            self.addCleanup(target.stop)
        lp = patch("serit_bekci.launch_dock")
        self.launch = lp.start()
        self.addCleanup(lp.stop)
        self.launch.return_value = MagicMock(pid=9999)

    def child(self, pid: int, code: int) -> MagicMock:
        c = MagicMock()
        c.pid = pid
        c.poll.return_value = code
        self.bekci.child_proc = c
        self.bekci.watched_pids = {pid}
        return c

    def write_marker(self, **kw) -> None:
        data = {"pid": 0, "ppid": 0, "t": time.time()}
        data.update(kw)
        self.marker.write_text(json.dumps(data), encoding="utf-8")


class TestMarkerRules(_Base):
    def test_valid_marker_ppid_stops(self) -> None:
        self.child(1000, 0)
        self.write_marker(pid=1001, ppid=1000)
        self.bekci.step()
        self.assertFalse(self.bekci.running)
        self.launch.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_valid_marker_stops_even_with_exit_code_1(self) -> None:
        self.child(1000, 1)
        self.write_marker(pid=1000)
        self.bekci.step()
        self.assertFalse(self.bekci.running)
        self.launch.assert_not_called()

    def test_marker_from_recorded_grandchild_pid_stops(self) -> None:
        self.child(1000, 0)
        self.bekci.watched_pids = {1000, 1001}
        self.write_marker(pid=1001, ppid=555)
        self.bekci.step()
        self.assertFalse(self.bekci.running)

    def test_foreign_pid_marker_restarts_and_is_deleted(self) -> None:
        self.child(1000, 0)
        self.write_marker(pid=4242, ppid=4141)
        self.bekci.step()
        self.assertTrue(self.bekci.running)
        self.launch.assert_called_once()
        self.assertFalse(self.marker.exists())

    def test_marker_older_than_start_restarts(self) -> None:
        self.child(1000, 0)
        self.write_marker(pid=1000, t=self.bekci.started_at - 100)
        self.bekci.step()
        self.assertTrue(self.bekci.running)
        self.launch.assert_called_once()
        self.assertFalse(self.marker.exists())

    def test_empty_marker_restarts(self) -> None:
        self.child(1000, 0)
        self.marker.touch()
        self.bekci.step()
        self.launch.assert_called_once()
        self.assertFalse(self.marker.exists())

    def test_no_marker_code_1_restarts(self) -> None:
        self.child(1000, 1)
        self.bekci.step()
        self.launch.assert_called_once()
        self.assertTrue(self.bekci.running)

    def test_no_marker_code_0_restarts(self) -> None:
        self.child(1000, 0)
        self.bekci.step()
        self.launch.assert_called_once()
        self.assertTrue(self.bekci.running)

    def test_no_marker_code_0_attaches_to_other_dock(self) -> None:
        other = MagicMock()
        other.pid = 7777
        other.create_time.return_value = time.time() - 5
        self.fdp.stop()
        with patch("serit_bekci.find_dock_process", return_value=other), \
                patch("serit_bekci.find_dock_hwnd", return_value=0):
            self.child(1000, 0)
            self.bekci.step()
        self.fdp.start()
        self.launch.assert_not_called()
        self.assertEqual(self.bekci.monitored_pid, 7777)
        self.assertTrue(self.bekci.running)
        self.assertEqual(len(self.bekci.crash_timestamps), 0)

    def test_external_process_stale_marker_restarts(self) -> None:
        self.bekci.monitored_pid = 31337
        self.bekci.watched_pids = {31337}
        self.write_marker(pid=1, ppid=2)
        with patch("serit_bekci.psutil.Process", side_effect=serit_bekci.psutil.NoSuchProcess(31337)):
            self.bekci.step()
        self.launch.assert_called_once()

    def test_external_process_valid_marker_stops(self) -> None:
        self.bekci.monitored_pid = 31337
        self.bekci.watched_pids = {31337}
        self.write_marker(pid=31337)
        with patch("serit_bekci.psutil.Process", side_effect=serit_bekci.psutil.NoSuchProcess(31337)):
            self.bekci.step()
        self.assertFalse(self.bekci.running)
        self.launch.assert_not_called()

    def test_external_process_no_marker_hide_taskbar_false_still_crash(self) -> None:
        self.settings.write_text(json.dumps({"hide_taskbar": False}), encoding="utf-8")
        self.bekci.monitored_pid = 31337
        self.bekci.watched_pids = {31337}
        with patch("serit_bekci.psutil.Process", side_effect=serit_bekci.psutil.NoSuchProcess(31337)):
            self.bekci.step()
        self.launch.assert_called_once()

    def test_run_startup_clears_stale_marker(self) -> None:
        self.write_marker(pid=1, ppid=2)
        self.bekci.child_proc = None
        with patch.object(serit_bekci.time, "sleep"), \
                patch.object(self.bekci, "step", side_effect=lambda: setattr(self.bekci, "running", False)):
            self.bekci.run()
        self.assertFalse(self.marker.exists())

    def test_start_dock_clears_marker_before_launch(self) -> None:
        self.write_marker(pid=1, ppid=2)
        seen = []
        self.launch.side_effect = lambda **kw: seen.append(self.marker.exists()) or MagicMock(pid=5)
        self.bekci.start_dock()
        self.assertEqual(seen, [False])


class TestWriteCleanExitMarker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="serit_wmarker_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_noop_under_test(self) -> None:
        self.assertTrue(logpath.is_running_under_test())
        self.assertFalse(logpath.write_clean_exit_marker(self.tmp))
        self.assertFalse((self.tmp / ".clean_exit").exists())

    def test_noop_for_non_production_main(self) -> None:
        with patch.object(logpath, "is_running_under_test", return_value=False):
            self.assertFalse(logpath.is_production_process(str(self.tmp / "serit_v5.pyw")))
            self.assertFalse(logpath.write_clean_exit_marker(self.tmp))
        self.assertFalse((self.tmp / ".clean_exit").exists())

    def test_writes_json_when_forced_production(self) -> None:
        with patch.object(logpath, "is_running_under_test", return_value=False), \
                patch.object(logpath, "is_production_process", return_value=True):
            before = time.time()
            self.assertTrue(logpath.write_clean_exit_marker(self.tmp))
        data = json.loads((self.tmp / ".clean_exit").read_text(encoding="utf-8"))
        import os
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["ppid"], os.getppid())
        self.assertGreaterEqual(data["t"], before - 1)
        self.assertFalse((self.tmp / ".clean_exit.tmp").exists())


DOCK_CRASH_THEN_CLEAN = """
import os, sys, time, json
from pathlib import Path
here = Path(__file__).resolve().parent
counter = here / "runs.txt"
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
time.sleep(0.4)
if MODE == "crash_then_clean" and n == 1:
    sys.exit(1)
(here / ".clean_exit").write_text(json.dumps(
    {"pid": os.getpid(), "ppid": os.getppid(), "t": time.time()}))
sys.exit(0)
"""


@unittest.skipUnless(VENV_PY.exists(), "venv python missing")
class TestEndToEnd(unittest.TestCase):
    def _run(self, mode: str):
        tmp = Path(tempfile.mkdtemp(prefix="serit_e2e_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        script = tmp / "dummy_dock.py"
        script.write_text(f"MODE = {mode!r}\n" + DOCK_CRASH_THEN_CLEAN, encoding="utf-8")
        log = tmp / "e2e.log"
        settings = tmp / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        b = serit_bekci.SeritBekci(
            poll_interval=0.1, settings_path=settings, marker_path=tmp / ".clean_exit",
            pythonw_path=VENV_PY, dock_script=script, app_dir=tmp,
        )
        with patch.object(serit_bekci, "LOG_PATH", log), \
                patch("serit_bekci.find_dock_process", return_value=None), \
                patch.object(winapi, "taskbar_autohide_set"), \
                patch.object(winapi.shell32, "SHAppBarMessage"):
            t0 = time.time()
            b.run()
            self.assertLess(time.time() - t0, 30)
        runs = int((tmp / "runs.txt").read_text())
        text = log.read_text(encoding="utf-8")
        print("\n--- e2e log (%s) ---\n%s" % (mode, text))
        return runs, text

    def test_e2e_crash_restarts_then_clean_stops(self) -> None:
        runs, text = self._run("crash_then_clean")
        self.assertEqual(runs, 2)
        self.assertIn("without valid marker", text)
        self.assertIn("Restarting dock", text)
        self.assertIn("exited cleanly", text)
        self.assertIn("marker matched pid", text)

    def test_e2e_valid_marker_stops_without_restart(self) -> None:
        runs, text = self._run("clean")
        self.assertEqual(runs, 1)
        self.assertNotIn("Restarting dock", text)
        self.assertIn("marker matched pid", text)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
