"""test_v23_logpath.py - gerçek serit.log / claude_cache.json'a yalnız kurulu bar ve bekçisi yazar (v23).

Zero side effects: only path decisions are checked; no file is written.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import logpath  # noqa: E402


def test_production_entry_points() -> None:
    assert logpath.is_production_process("D:/Apps/serit/serit_v5.pyw")
    assert logpath.is_production_process(r"D:\Apps\serit\serit_bekci.pyw")
    assert logpath.is_production_process(r"d:\apps\SERIT\Serit_V5.pyw")  # Windows: büyük/küçük harf fark etmez


def test_everything_else_is_not_production() -> None:
    temp = tempfile.gettempdir()
    for f in (
        os.path.join(temp, "serit-oc23-opt", "serit_v5.pyw"),   # ajan kopyası
        os.path.join(temp, "bench.py"),                           # deneme betiği
        "D:/Apps/serit/tests/test_x.py",
        "D:/Apps/serit/settings_window.py",
        "",
        None,
    ):
        assert not logpath.is_production_process(f) if f is not None else True, f


def test_paths_in_this_test_process() -> None:
    """Bu süreç tests/ altında: log ve önbellek gerçek dosyalara gitmez."""
    old = os.environ.pop("SERIT_LOG", None)
    try:
        assert logpath.get_log_path() != logpath.DEFAULT_LOG_PATH
        assert logpath.get_claude_cache_path() != logpath.DEFAULT_CACHE_DIR / "claude_cache.json"
    finally:
        if old is not None:
            os.environ["SERIT_LOG"] = old


def test_dev_script_redirect(monkey_main: str = "C:/scratch/probe.py") -> None:
    """tests/ dışındaki bir betik (ajan yoklaması) de gerçek log'a yazmaz."""
    main = sys.modules["__main__"]
    old_file = getattr(main, "__file__", None)
    old_env = os.environ.pop("SERIT_LOG", None)
    old_cache = os.environ.pop("SERIT_CACHE_DIR", None)  # run_all bunu ayarlar; karar mantığını ölçmek için kaldır
    try:
        main.__file__ = monkey_main
        assert not logpath.is_running_under_test()
        assert logpath.get_log_path().name == "serit-dev.log"
        assert logpath.get_claude_cache_path().name == "serit-dev-claude_cache.json"
        main.__file__ = "D:/Apps/serit/serit_v5.pyw"
        assert logpath.get_log_path() == logpath.DEFAULT_LOG_PATH
        assert logpath.get_claude_cache_path() == logpath.DEFAULT_CACHE_DIR / "claude_cache.json"
        os.environ["SERIT_LOG"] = os.path.join(tempfile.gettempdir(), "x.log")
        assert logpath.get_log_path().name == "x.log"  # açık yönlendirme her zaman kazanır
    finally:
        main.__file__ = old_file
        os.environ.pop("SERIT_LOG", None)
        if old_env is not None:
            os.environ["SERIT_LOG"] = old_env
        if old_cache is not None:
            os.environ["SERIT_CACHE_DIR"] = old_cache


def run_all() -> None:
    for fn in (test_production_entry_points, test_everything_else_is_not_production,
               test_paths_in_this_test_process, test_dev_script_redirect):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V23_LOGPATH TESTS PASSED")


if __name__ == "__main__":
    run_all()
