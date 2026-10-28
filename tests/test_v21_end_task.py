"""test_v21_end_task.py - 'Görevi sonlandır' Turkish failure reasons (v21).

Covers the 28 Oct case: ending a tray item whose process runs elevated (a vendor
control-center daemon) raised psutil.AccessDenied inside psutil.wait_procs, and the
user saw nothing while the log got a raw English line.
All processes here are fakes, except one harmless child python process that this test
starts itself, only to check that _terminate_access says True for our own process.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SERIT_TEST", "1")

import psutil  # noqa: E402

import tray_actions  # noqa: E402


class FakeProc:
    def __init__(self, pid: int, exe: str, deny_terminate: bool = False, deny_kill: bool = False,
                 dies_on_terminate: bool = True) -> None:
        self.pid = pid
        self._exe = exe
        self.deny_terminate = deny_terminate
        self.deny_kill = deny_kill
        self.dies_on_terminate = dies_on_terminate
        self.terminated = False
        self.killed = False
        self.info = {"pid": pid, "name": Path(exe).name, "exe": exe, "cmdline": [exe],
                     "username": getpass.getuser()}

    def create_time(self) -> float:
        return 1000.0

    def exe(self) -> str:
        return self._exe

    def name(self) -> str:
        return Path(self._exe).name

    def cmdline(self) -> List[str]:
        return [self._exe]

    def username(self) -> str:
        return getpass.getuser()

    def ppid(self) -> int:
        return 1

    def children(self, recursive: bool = False) -> list:
        return []

    def terminate(self) -> None:
        if self.deny_terminate:
            raise psutil.AccessDenied(pid=self.pid, name=self.name())
        self.terminated = True

    def kill(self) -> None:
        if self.deny_kill:
            raise psutil.AccessDenied(pid=self.pid, name=self.name())
        self.killed = True

    def is_running(self) -> bool:
        return not (self.terminated and self.dies_on_terminate) and not self.killed

    def status(self) -> str:
        return psutil.STATUS_RUNNING

    def wait(self, timeout: Any = None) -> Any:
        # what the real psutil.wait_procs calls
        if self.is_running():
            raise psutil.TimeoutExpired(timeout, self.pid)
        return 0


def _resolved(pids: List[int]) -> dict:
    return {
        "ok": True,
        "entries": [tray_actions.ProcessEntry(pid, 1000.0) for pid in pids],
        "pids": pids,
        "roots": pids[:1],
        "count": len(pids),
        "label": f"Örnek · {len(pids)} işlem",
        "reason": None,
    }


class EndTaskTurkishReasons(unittest.TestCase):
    def setUp(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        self.log = Path(name)
        self._old_log = tray_actions.LOG_PATH
        tray_actions.LOG_PATH = self.log

    def tearDown(self) -> None:
        tray_actions.LOG_PATH = self._old_log
        try:
            self.log.unlink()
        except Exception:
            pass

    def _run(self, procs: List[FakeProc], wait_side_effect: Any = None) -> dict:
        exe = procs[0]._exe
        by_pid = {p.pid: p for p in procs}
        with patch("tray_actions.resolve_processes", return_value=_resolved(list(by_pid))), \
             patch("tray_actions.psutil.Process", side_effect=lambda pid: by_pid[pid]), \
             patch("tray_actions._get_self_pids", return_value=set()):
            if wait_side_effect is not None:
                with patch("tray_actions.psutil.wait_procs", side_effect=wait_side_effect):
                    return tray_actions.end_task({"name": "Control Center", "exe": exe}, timeout=0.3)
            return tray_actions.end_task({"name": "Control Center", "exe": exe}, timeout=0.3)

    def test_terminate_access_denied_gives_turkish_reason(self) -> None:
        p = FakeProc(16612, r"C:\Vendor\ControlCenterDaemon.exe", deny_terminate=True, deny_kill=True)
        res = self._run([p])
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "Yönetici izni gerekiyor")
        self.assertEqual(res["killed"], 0)
        self.assertEqual(res["survivors"], 1)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("kapatıldı 0", text)
        self.assertIn("yönetici izni gerekiyor", text)
        self.assertNotIn("AccessDenied", text)

    def test_wait_procs_access_denied_falls_back_to_polling(self) -> None:
        # The 28 Oct path: terminate() itself passed, psutil.wait_procs raised AccessDenied.
        p = FakeProc(16612, r"C:\Vendor\ControlCenterDaemon.exe")
        res = self._run([p], wait_side_effect=psutil.AccessDenied(pid=16612, name="ControlCenterDaemon.exe"))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["killed"], 1)
        self.assertNotIn("AccessDenied", self.log.read_text(encoding="utf-8"))

    def test_mixed_denied_and_closed(self) -> None:
        exe = r"C:\Vendor\Mixed.exe"
        ok = FakeProc(501, exe)
        bad = FakeProc(502, exe, deny_terminate=True, deny_kill=True)
        res = self._run([ok, bad])
        self.assertFalse(res["ok"])
        self.assertEqual(res["killed"], 1)
        self.assertEqual(res["survivors"], 1)
        self.assertEqual(res["reason"], "Yönetici izni gerekiyor")

    def test_unexpected_error_reason_is_turkish(self) -> None:
        with patch("tray_actions.resolve_processes", side_effect=RuntimeError("boom internal")):
            res = tray_actions.end_task({"name": "X", "exe": r"C:\x.exe"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "Görev sonlandırılamadı")
        self.assertNotIn("boom", res["reason"])

    def test_access_denied_escaping_is_turkish(self) -> None:
        with patch("tray_actions.resolve_processes", side_effect=psutil.AccessDenied(pid=7, name="a.exe")):
            res = tray_actions.end_task({"name": "X", "exe": r"C:\x.exe"})
        self.assertEqual(res["reason"], "Yönetici izni gerekiyor")
        self.assertIn("yönetici izni gerekiyor", self.log.read_text(encoding="utf-8"))


class ResolveSkipsElevated(unittest.TestCase):
    def test_same_user_but_no_terminate_right_is_admin_reason(self) -> None:
        exe = r"C:\Vendor\ControlCenterDaemon.exe"
        p = FakeProc(16612, exe)
        with patch("tray_actions.psutil.process_iter", return_value=[p]), \
             patch("tray_actions._terminate_access", return_value=False):
            res = tray_actions.resolve_processes({"name": "Control Center", "exe": exe})
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "Yönetici izni gerekiyor")

    def test_unknown_access_does_not_block(self) -> None:
        exe = r"C:\Apps\Normal.exe"
        p = FakeProc(700, exe)
        with patch("tray_actions.psutil.process_iter", return_value=[p]):
            res = tray_actions.resolve_processes({"name": "Normal", "exe": exe})
        self.assertTrue(res["ok"], res)

    def test_terminate_access_fakes_are_unknown(self) -> None:
        self.assertIsNone(tray_actions._terminate_access(MagicMock()))
        self.assertIsNone(tray_actions._terminate_access(FakeProc(1, r"C:\a.exe")))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_terminate_access_real_own_child_is_true(self) -> None:
        # Harmless child we start ourselves: only a handle is opened and closed, nothing is ended by the check.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            time.sleep(0.3)
            self.assertIs(tray_actions._terminate_access(psutil.Process(child.pid)), True)
        finally:
            child.kill()
            child.wait(5)


class DockToastOnFailure(unittest.TestCase):
    def test_dock_wiring_exists(self) -> None:
        src = (Path(__file__).resolve().parent.parent / "serit_v5.pyw").read_text(encoding="utf-8")
        self.assertIn("end_task_done = Signal(object, object)", src)
        self.assertIn("self.dispatcher.end_task_done.connect(self._on_end_task_done)", src)
        self.assertIn("def _on_end_task_done", src)
        self.assertIn('kind="tray"', src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
