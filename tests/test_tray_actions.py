"""test_tray_actions.py - Unit and regression tests for tray_actions module.

Includes:
- psutil mocking for exe matching
- Generic-host cmdline filtering (Dikte vs Şerit dock vs other scripts)
- Protected process sets (self, parents, children, serit_v5, explorer, SystemRoot, hermes)
- Other-user / AccessDenied handling (Admin permission required)
- Process tree descent and root detection
- Terminate -> Kill escalation and NoSuchProcess race tolerance
- Garbage input matrix
- Real end-to-end test with harmless isolated dummy subprocesses
"""

import getpass
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import List, Optional
import unittest
from unittest.mock import MagicMock, patch

import psutil

# Add serit root to sys.path
SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

import tray_actions


class FakeProcess:
    """Mock psutil.Process with controllable attributes and methods."""

    def __init__(
        self,
        pid: int,
        name: str = "app.exe",
        exe: str = r"C:\Apps\test\app.exe",
        cmdline: Optional[List[str]] = None,
        username: Optional[str] = None,
        ppid: int = 1,
        children: Optional[List["FakeProcess"]] = None,
        create_time: float = 1000.0,
    ) -> None:
        self.pid = pid
        self._name = name
        self._exe = exe
        self._cmdline = cmdline or [exe]
        self._username = username or getpass.getuser()
        self._ppid = ppid
        self._children = children or []
        self._create_time = create_time
        self.info = {
            "pid": self.pid,
            "name": self._name,
            "exe": self._exe,
            "cmdline": self._cmdline,
            "username": self._username,
        }
        self.terminated = False
        self.killed = False

    def create_time(self) -> float:
        return self._create_time

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return self._exe

    def cmdline(self) -> List[str]:
        return list(self._cmdline)

    def username(self) -> str:
        return self._username

    def ppid(self) -> int:
        return self._ppid

    def children(self, recursive: bool = False) -> List["FakeProcess"]:
        res: List["FakeProcess"] = []
        for c in self._children:
            res.append(c)
            if recursive:
                res.extend(c.children(recursive=True))
        return res

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class TestTrayActionsUnit(unittest.TestCase):
    """Unit tests with mocked psutil."""

    def test_garbage_items(self) -> None:
        """Matrix of malformed or empty items."""
        bad_items = [
            None,
            {},
            [],
            "not a dict",
            12345,
            {"exe": None},
            {"exe": ""},
            {"exe": "   "},
            {"exe": 123},
            {"name": "No exe item"},
            {"tooltip": "Still no exe"},
        ]
        for item in bad_items:
            res = tray_actions.resolve_processes(item)
            self.assertFalse(res["ok"])
            self.assertEqual(res["pids"], [])
            self.assertEqual(res["roots"], [])
            self.assertEqual(res["count"], 0)
            self.assertEqual(res["reason"], "İşlem bulunamadı")

    def test_windows_system_protected(self) -> None:
        """Core Windows executables in %SystemRoot% must never be targeted."""
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        cases = [
            os.path.join(sys_root, "System32", "SecurityHealthSystray.exe"),
            os.path.join(sys_root, "explorer.exe"),
            os.path.join(sys_root, "System32", "svchost.exe"),
        ]
        for exe in cases:
            item = {"name": "Windows Comp", "exe": exe}
            res = tray_actions.resolve_processes(item)
            self.assertFalse(res["ok"])
            self.assertEqual(res["reason"], "Windows bileşeni sonlandırılamaz")

    @patch("tray_actions.psutil.process_iter")
    def test_exe_matching_mocked(self, mock_iter: MagicMock) -> None:
        """Standard application matching by exe path."""
        target_exe = r"C:\Program Files\Zoom\bin\Zoom.exe"
        p1 = FakeProcess(pid=1001, exe=target_exe, ppid=500)
        p2 = FakeProcess(pid=1002, exe=target_exe, ppid=1001)
        p3 = FakeProcess(pid=2001, exe=r"C:\Program Files\Other\other.exe")
        mock_iter.return_value = [p1, p2, p3]

        item = {"name": "Zoom Workplace", "exe": target_exe}
        res = tray_actions.resolve_processes(item)

        self.assertTrue(res["ok"])
        self.assertEqual(res["pids"], [1001, 1002])
        self.assertEqual(res["roots"], [1001])
        self.assertEqual(res["count"], 2)
        self.assertIn("2 işlem", res["label"])
        self.assertIsNone(res["reason"])

    @patch("tray_actions.psutil.process_iter")
    def test_generic_host_dikte_vs_dock(self, mock_iter: MagicMock) -> None:
        """Generic host pythonw.exe: Dikte + watchdog selected, Şerit dock NEVER selected."""
        pyw = r"C:\Python312\pythonw.exe"
        curr_user = getpass.getuser()

        # Dikte app
        p_dikte = FakeProcess(
            pid=501,
            exe=pyw,
            cmdline=[pyw, "dikte.pyw"],
            username=curr_user,
        )
        # Dikte bekci / watchdog
        p_bekci = FakeProcess(
            pid=502,
            exe=pyw,
            cmdline=[pyw, r"D:\Apps\dikte\bekci.pyw"],
            username=curr_user,
        )
        # The Serit dock itself (MUST BE PROTECTED)
        p_dock = FakeProcess(
            pid=503,
            exe=pyw,
            cmdline=[pyw, r"D:\Apps\serit\serit_v5.pyw"],
            username=curr_user,
        )
        # Random unrelated python script
        p_other = FakeProcess(
            pid=504,
            exe=pyw,
            cmdline=[pyw, "myscript.py"],
            username=curr_user,
        )

        mock_iter.return_value = [p_dikte, p_bekci, p_dock, p_other]

        item = {
            "name": "Dikte · Türkçe",
            "tooltip": "Dikte · Türkçe",
            "exe": pyw,
        }
        res = tray_actions.resolve_processes(item)

        self.assertTrue(res["ok"])
        self.assertEqual(set(res["pids"]), {501, 502})
        self.assertNotIn(503, res["pids"], "Dock process 503 must never be targeted!")
        self.assertNotIn(504, res["pids"], "Unrelated python process 504 must not be targeted!")

    @patch("tray_actions.psutil.process_iter")
    def test_generic_host_autohotkey(self, mock_iter: MagicMock) -> None:
        """Generic host AutoHotkey64: only the script matching the tray item is selected."""
        ahk_exe = r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
        p_tab = FakeProcess(
            pid=601,
            exe=ahk_exe,
            cmdline=[ahk_exe, r"D:\Apps\AutoHotkey\cmdpal-tab.ahk"],
        )
        p_other = FakeProcess(
            pid=602,
            exe=ahk_exe,
            cmdline=[ahk_exe, r"C:\Scripts\other_macro.ahk"],
        )
        mock_iter.return_value = [p_tab, p_other]

        item = {
            "name": "cmdpal-tab.ahk",
            "exe": ahk_exe,
        }
        res = tray_actions.resolve_processes(item)
        self.assertTrue(res["ok"])
        self.assertEqual(res["pids"], [601])

    @patch("tray_actions.psutil.process_iter")
    @patch("tray_actions._get_self_pids")
    def test_protected_sets(self, mock_self_pids: MagicMock, mock_iter: MagicMock) -> None:
        """Verify protection of self, ancestors, children, hermes, and explorer."""
        mock_self_pids.return_value = {999, 998}
        target_exe = r"C:\Tools\tool.exe"

        p_self = FakeProcess(pid=999, exe=target_exe)
        p_hermes = FakeProcess(
            pid=701,
            exe=target_exe,
            cmdline=[target_exe, "--agent", "hermes-agent"],
        )
        p_hermes_dir = FakeProcess(
            pid=702,
            exe=r"C:\Users\User\AppData\Local\hermes\tool.exe",
        )
        p_serit = FakeProcess(
            pid=703,
            exe=target_exe,
            cmdline=[target_exe, "serit_v5.pyw"],
        )

        mock_iter.return_value = [p_self, p_hermes, p_hermes_dir, p_serit]

        item = {"name": "Tool", "exe": target_exe}
        res = tray_actions.resolve_processes(item)
        self.assertFalse(res["ok"])
        self.assertEqual(res["pids"], [])
        self.assertIn("korumalı", res["reason"])

    @patch("tray_actions.psutil.process_iter")
    def test_other_user_and_access_denied(self, mock_iter: MagicMock) -> None:
        """Processes owned by SYSTEM or other users require admin privileges."""
        target_exe = r"C:\Driver\nv.exe"
        p_sys = FakeProcess(pid=801, exe=target_exe, username="NT AUTHORITY\\SYSTEM")
        mock_iter.return_value = [p_sys]

        item = {"name": "NV Settings", "exe": target_exe}
        res = tray_actions.resolve_processes(item)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "Yönetici izni gerekiyor")

    @patch("tray_actions.psutil.process_iter")
    def test_tree_roots_and_descendants(self, mock_iter: MagicMock) -> None:
        """Candidate roots should include all owned child processes recursively."""
        target_exe = r"C:\Apps\tree\main.exe"
        curr_user = getpass.getuser()

        p_child2 = FakeProcess(pid=903, exe=r"C:\Apps\tree\sub.exe", username=curr_user, ppid=902)
        p_child1 = FakeProcess(pid=902, exe=r"C:\Apps\tree\sub.exe", username=curr_user, ppid=901, children=[p_child2])
        p_root = FakeProcess(pid=901, exe=target_exe, username=curr_user, ppid=1, children=[p_child1])

        mock_iter.return_value = [p_root]

        item = {"name": "Tree App", "exe": target_exe}
        res = tray_actions.resolve_processes(item)

        self.assertTrue(res["ok"])
        self.assertEqual(set(res["pids"]), {901, 902, 903})
        self.assertEqual(res["roots"], [901])
        self.assertEqual(res["count"], 3)

    @patch("tray_actions.psutil.wait_procs")
    @patch("tray_actions.psutil.Process")
    @patch("tray_actions.resolve_processes")
    def test_terminate_and_kill_escalation(
        self,
        mock_resolve: MagicMock,
        mock_proc_cls: MagicMock,
        mock_wait: MagicMock,
    ) -> None:
        """end_task terminates first, then escalates to kill on survivors."""
        item = {"name": "Stubborn App", "exe": r"C:\app.exe"}
        mock_resolve.return_value = {
            "ok": True,
            "pids": [111, 222],
            "roots": [111],
            "count": 2,
            "label": "App · 2 işlem",
            "reason": None,
        }

        p1 = FakeProcess(pid=111, exe=r"C:\app.exe")
        p2 = FakeProcess(pid=222, exe=r"C:\app.exe")
        proc_dict = {111: p1, 222: p2}
        mock_proc_cls.side_effect = lambda pid: proc_dict[pid]

        # First wait: p1 is gone, p2 is stubborn survivor
        # Second wait: p2 is gone
        mock_wait.side_effect = [
            ([p1], [p2]),  # after terminate: p2 alive
            ([p2], []),    # after kill: p2 gone
        ]

        res = tray_actions.end_task(item, timeout=1.0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["killed"], 2)
        self.assertEqual(res["survivors"], 0)
        self.assertTrue(p1.terminated)
        self.assertTrue(p2.terminated)
        self.assertTrue(p2.killed)

    @patch("tray_actions.psutil.Process")
    @patch("tray_actions.resolve_processes")
    def test_nosuchprocess_race(
        self,
        mock_resolve: MagicMock,
        mock_proc_cls: MagicMock,
    ) -> None:
        """Handle process dying on its own before terminate() can be called."""
        item = {"name": "Disappearing App", "exe": r"C:\app.exe"}
        mock_resolve.return_value = {
            "ok": True,
            "pids": [333],
            "roots": [333],
            "count": 1,
            "label": "App · 1 işlem",
            "reason": None,
        }
        mock_proc_cls.side_effect = psutil.NoSuchProcess(pid=333)

        res = tray_actions.end_task(item)
        self.assertTrue(res["ok"])
        self.assertEqual(res["killed"], 0)
        self.assertEqual(res["survivors"], 0)

    @patch("tray_actions.psutil.process_iter")
    def test_blacklist_and_crafted_items_match_nothing(self, mock_iter: MagicMock) -> None:
        """Crafted items named 'AutoHotkey', tooltip 'user settings', name 'python' must match NOTHING."""
        py_exe = r"C:\Python312\python.exe"
        ahk_exe = r"C:\AutoHotkey\AutoHotkey64.exe"
        curr_user = getpass.getuser()

        p_py = FakeProcess(
            pid=7001,
            exe=py_exe,
            cmdline=[py_exe, r"C:\Users\Emre Karatasli\AppData\Local\Programs\script.py"],
            username=curr_user,
        )
        p_ahk = FakeProcess(
            pid=7002,
            exe=ahk_exe,
            cmdline=[ahk_exe, r"C:\Users\Emre Karatasli\AppData\Local\user_settings.ahk"],
            username=curr_user,
        )
        mock_iter.return_value = [p_py, p_ahk]

        crafted_cases = [
            {"name": "AutoHotkey", "exe": ahk_exe},
            {"name": "SomeApp", "tooltip": "user settings", "exe": ahk_exe},
            {"name": "python", "exe": py_exe},
            {"name": "pythonw", "tooltip": "settings", "exe": py_exe},
            {"name": "programs", "tooltip": "users local appdata", "exe": py_exe},
        ]
        for item in crafted_cases:
            res = tray_actions.resolve_processes(item)
            self.assertFalse(res["ok"], f"Crafted item {item} should not match anything! Got: {res}")
            self.assertEqual(res["pids"], [])

    @patch("tray_actions.psutil.Process")
    @patch("tray_actions.resolve_processes")
    def test_pid_reuse_simulation(
        self,
        mock_resolve: MagicMock,
        mock_proc_cls: MagicMock,
    ) -> None:
        """If create_time changes between resolve and end_task, process must NOT be killed."""
        target_exe = r"C:\app.exe"
        item = {"name": "TestApp", "exe": target_exe}
        mock_resolve.return_value = {
            "ok": True,
            "entries": [tray_actions.ProcessEntry(5555, 1000.0)],
            "pids": [5555],
            "roots": [5555],
            "count": 1,
            "label": "App · 1 işlem",
            "reason": None,
        }

        # The process now has a different create_time (e.g. 2000.0), simulating PID reuse
        reused_proc = FakeProcess(pid=5555, exe=target_exe, create_time=2000.0)
        mock_proc_cls.return_value = reused_proc

        res = tray_actions.end_task(item)
        self.assertTrue(res["ok"])
        self.assertEqual(res["killed"], 0)
        self.assertFalse(reused_proc.terminated)
        self.assertFalse(reused_proc.killed)

    @patch("tray_actions._get_self_pids", return_value=set())
    @patch("tray_actions.psutil.wait_procs")
    @patch("tray_actions.psutil.Process")
    @patch("tray_actions.resolve_processes")
    def test_audit_logging_to_temp_file(
        self,
        mock_resolve: MagicMock,
        mock_proc_cls: MagicMock,
        mock_wait: MagicMock,
        mock_self: MagicMock,
    ) -> None:
        """end_task writes exactly formatted audit lines to LOG_PATH without full cmdlines."""
        import tempfile
        target_exe = r"C:\app.exe"
        item = {"name": "AuditApp", "exe": target_exe}
        mock_resolve.return_value = {
            "ok": True,
            "entries": [tray_actions.ProcessEntry(4444, 1000.0)],
            "pids": [4444],
            "roots": [4444],
            "count": 1,
            "label": "AuditApp · 1 işlem",
            "reason": None,
        }
        p = FakeProcess(pid=4444, exe=target_exe, create_time=1000.0)
        mock_proc_cls.return_value = p
        mock_wait.return_value = ([p], [])

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
            temp_log = Path(tf.name)

        old_log = tray_actions.LOG_PATH
        try:
            tray_actions.LOG_PATH = temp_log
            res = tray_actions.end_task(item)
            self.assertTrue(res["ok"])
            content = temp_log.read_text(encoding="utf-8")
            self.assertIn("[tray_actions.end_task] AuditApp: kapatıldı 1 (PID 4444 app.exe), hayatta kalan 0, atlanan 0 (yok)", content)
        finally:
            tray_actions.LOG_PATH = old_log
            try:
                temp_log.unlink()
            except Exception:
                pass


class TestTrayActionsRealE2E(unittest.TestCase):
    """Real end-to-end test with harmless isolated dummy subprocesses."""

    def test_real_isolated_dummy_kill(self) -> None:
        """Spawn two dummy python processes. Resolve & kill only the marked one."""
        marker = f"serit_kill_probe_{int(time.time())}_{os.getpid()}"
        py_exe = sys.executable

        # 1. Target dummy process (with marker argument)
        target_code = "import time; time.sleep(120)"
        target_proc = subprocess.Popen([py_exe, "-c", target_code, marker])

        # 2. Innocuous dummy process (WITHOUT marker argument)
        innocuous_proc = subprocess.Popen([py_exe, "-c", target_code])

        try:
            # Allow processes to start up
            time.sleep(0.5)

            self.assertIsNone(target_proc.poll(), "Target process should be running")
            self.assertIsNone(innocuous_proc.poll(), "Innocuous process should be running")

            item = {
                "name": marker,
                "tooltip": marker,
                "full_name": marker,
                "exe": py_exe,
            }

            # Resolve
            res = tray_actions.resolve_processes(item)
            self.assertTrue(res["ok"], f"resolve_processes failed: {res}")
            self.assertIn(target_proc.pid, res["pids"])
            self.assertNotIn(innocuous_proc.pid, res["pids"], "Innocuous process must NOT be resolved!")

            # End task
            kill_res = tray_actions.end_task(item, timeout=2.0)
            self.assertTrue(kill_res["ok"], f"end_task failed: {kill_res}")
            self.assertGreaterEqual(kill_res["killed"], 1)
            self.assertEqual(kill_res["survivors"], 0)

            # Wait briefly to confirm exit
            time.sleep(0.3)
            self.assertIsNotNone(target_proc.poll(), "Target process should have been terminated")
            self.assertIsNone(innocuous_proc.poll(), "Innocuous process MUST still be alive!")

        finally:
            # Guaranteed cleanup in finally
            for proc in (target_proc, innocuous_proc):
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


if __name__ == "__main__":
    unittest.main()
