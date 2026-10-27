"""tests/test_threading_contract.py - Verifies threading contract, safety, and robustness.

Checks:
1. Static assertion: serit_v5.pyw has no direct calls to blocking audio/system/tray
   APIs (media.now_playing, media.get_volume, media.set_volume, media.media_control,
   popover_v2.top_processes, trayicons.list_tray_items) outside of worker lambdas/
   functions and outside render_preview.
2. Unit tests for sources.fmt_tr, sources.event_when, sources.fetch_calendar with
   malformed and invalid inputs.
3. Unit test for atomic save_settings and .bak recovery in serit_v5.pyw.
4. Unit test for stale-lock recovery using a dead PID child process lock.
"""

import ast
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil
from PySide6.QtCore import QLockFile

# Add repo to sys.path
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import sources


def test_static_threading_contract():
    serit_path = APP_DIR / "serit_v5.pyw"
    tree = ast.parse(serit_path.read_text(encoding="utf-8"))

    blocked_targets = {
        ("media", "now_playing"),
        ("media", "get_volume"),
        ("media", "set_volume"),
        ("media", "media_control"),
        ("popover_v2", "top_processes"),
        ("trayicons", "list_tray_items"),
    }

    class CallChecker(ast.NodeVisitor):
        def __init__(self):
            self.scope_stack = []
            self.violations = []
            self.allowed = []

        def visit_FunctionDef(self, node):
            self.scope_stack.append(("func", node.name))
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self.scope_stack.append(("func", node.name))
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_Lambda(self, node):
            self.scope_stack.append(("lambda", "<lambda>"))
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_Call(self, node):
            target = None
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in blocked_targets:
                    target = f"{pair[0]}.{pair[1]}"

            if target:
                is_preview = any(s[0] == "func" and s[1] == "render_preview" for s in self.scope_stack)
                is_worker_lambda = any(s[0] == "lambda" for s in self.scope_stack)
                is_inner_worker_fn = any(s[0] == "func" and s[1] in ("_apply", "_worker", "_fetch_tray_worker") for s in self.scope_stack)  # _fetch_tray_worker yalnız sources.submit havuzunda çalışır
                if is_preview or is_worker_lambda or is_inner_worker_fn:
                    self.allowed.append((node.lineno, target, [s[1] for s in self.scope_stack]))
                else:
                    self.violations.append((node.lineno, target, [s[1] for s in self.scope_stack]))
            self.generic_visit(node)

    checker = CallChecker()
    checker.visit(tree)
    assert not checker.violations, f"Forbidden synchronous calls found on UI thread: {checker.violations}"
    print(f"THREADING CONTRACT PASSED: {len(checker.allowed)} allowed background/preview calls, 0 UI violations.")


def test_sources_robustness():
    # 1. fmt_tr with bad / edge values
    assert sources.fmt_tr(None) == "—"
    assert sources.fmt_tr(float("nan")) == "—"
    assert sources.fmt_tr(float("inf")) == "—"
    assert sources.fmt_tr("bad_string") == "—"
    assert sources.fmt_tr([1, 2, 3]) == "—"
    assert sources.fmt_tr(1234.56, dec=2) == "1.234,56"

    # 2. event_when with malformed / invalid events
    assert sources.event_when(None) == ""
    assert sources.event_when({}) == ""
    assert sources.event_when({"start": None}) == ""
    assert sources.event_when({"start": "invalid_date_string"}) == ""
    assert sources.event_when({"start": 1234567}) == ""
    now = dt.datetime.now(sources.LOCAL_TZ)
    future = now + dt.timedelta(minutes=30)
    res_when = sources.event_when({"start": future}, now=now)
    assert "30 dk sonra" in res_when or "29 dk sonra" in res_when

    # 3. fetch_calendar with bad files / structures
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
        tmp_cal = Path(f.name)
    try:
        orig_cal = sources.CALENDAR_JSON
        sources.CALENDAR_JSON = tmp_cal

        # Corrupt JSON
        tmp_cal.write_text("{broken json", encoding="utf-8")
        res = sources.fetch_calendar()
        assert "err" in res

        # Not a dict
        tmp_cal.write_text("[\"list\", 1, 2]", encoding="utf-8")
        res = sources.fetch_calendar()
        assert res.get("err") == "Geçersiz veri"

        # Missing or malformed events
        tmp_cal.write_text(json.dumps({
            "zaman": "not-a-date",
            "etkinlikler": [
                None,
                "not-a-dict",
                {"bas": None, "bit": None},
                {"bas": "invalid", "baslik": "Invalid Time"},
                {"bas": (now + dt.timedelta(hours=2)).isoformat(), "baslik": "Valid Future Event"}
            ]
        }), encoding="utf-8")
        res = sources.fetch_calendar(now=now)
        assert "events" in res
        assert len(res["events"]) == 1
        assert res["events"][0]["title"] == "Valid Future Event"
    finally:
        sources.CALENDAR_JSON = orig_cal
        if tmp_cal.exists():
            tmp_cal.unlink()

    print("SOURCES ROBUSTNESS TESTS PASSED.")


def test_atomic_settings_and_backup():
    # Import load_settings and save_settings from serit_v5
    import importlib.util
    spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
    serit_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serit_mod)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_settings = Path(tmpdir) / "settings.json"
        bak_settings = Path(tmpdir) / "settings.json.bak"

        serit_mod.SETTINGS_FILE = tmp_settings

        # 1. Initial save & atomic write
        data = {"city": "Istanbul", "hide_taskbar": False, "pos": [500, 800]}
        serit_mod.save_settings(data)
        assert tmp_settings.exists()
        loaded = serit_mod.load_settings()
        assert loaded.get("city") == "Istanbul"

        # 2. Update to create .bak
        data2 = {"city": "Ankara", "hide_taskbar": True}
        serit_mod.save_settings(data2)
        assert bak_settings.exists()
        bak_content = json.loads(bak_settings.read_text(encoding="utf-8"))
        assert bak_content.get("city") == "Istanbul"
        assert serit_mod.load_settings().get("city") == "Ankara"

        # 3. Corrupt primary settings.json and verify recovery from .bak
        tmp_settings.write_text("{corrupt json ...", encoding="utf-8")
        recovered = serit_mod.load_settings()
        assert recovered.get("city") == "Istanbul", f"Expected Istanbul from .bak, got {recovered.get('city')}"

    print("ATOMIC SETTINGS AND BAK RECOVERY TESTS PASSED.")


def test_stale_lock_recovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = Path(tmpdir) / "test_app.lock"

        # Start child process that acquires the lock
        child_code = f"""
import time, sys, os
from PySide6.QtCore import QLockFile
lock = QLockFile({repr(str(lock_path))})
if lock.lock():
    print(os.getpid(), flush=True)
    time.sleep(30)
"""
        proc = subprocess.Popen([sys.executable, "-c", child_code], stdout=subprocess.PIPE, text=True)
        pid_line = proc.stdout.readline().strip()
        child_pid = int(pid_line)

        # 1. While child process is alive, tryLock must fail and report live process
        lock1 = QLockFile(str(lock_path))
        assert not lock1.tryLock(50)
        pid, host, app = lock1.getLockInfo()
        assert pid == child_pid
        assert psutil.pid_exists(pid)

        # 2. Kill the child process (simulating hard crash)
        proc.kill()
        proc.wait()
        time.sleep(0.1)
        assert not psutil.pid_exists(child_pid)

        # 3. Simulate recovery logic from serit_v5.pyw
        lock2 = QLockFile(str(lock_path))
        acquired = lock2.tryLock(50)
        # Even if tryLock failed because lock file is present
        if not acquired:
            pid2, host2, app2 = lock2.getLockInfo()
            assert not psutil.pid_exists(pid2)
            lock2.removeStaleLockFile()
            assert lock2.tryLock(100)
        lock2.unlock()

    print("STALE LOCK RECOVERY TEST PASSED.")


if __name__ == "__main__":
    test_static_threading_contract()
    test_sources_robustness()
    test_atomic_settings_and_backup()
    test_stale_lock_recovery()
    print("\nALL THREADING CONTRACT & ROBUSTNESS TESTS PASSED SUCCESSFULLY!")
