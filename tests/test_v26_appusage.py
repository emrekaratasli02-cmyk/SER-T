"""test_v26_appusage.py - Süreç kaynak kullanımı (CPU/Bellek) birim testleri.

Testler yapay (sentetik) verilerle çalışır. Tek bir canlı duman (smoke) testi
yalnızca dönen sonucun boş olmayan bir sözlük olduğunu doğrular; hiçbir gerçek
süreç adını veya verisini yazdırmaz.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SERIT_TEST"] = "1"
_tmp_dir = tempfile.mkdtemp(prefix="serit-test-appusage-")
os.environ["SERIT_LOG"] = str(Path(_tmp_dir) / "test.log")
os.environ["SERIT_CACHE_DIR"] = _tmp_dir

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import appusage  # noqa: E402


def test_grouping_by_exe() -> None:
    # 3 chrome.exe süreci + 1 notepad.exe süreci
    rows = [
        # (pid, name, ws_priv, create_time, user_time, kernel_time)
        (101, "chrome.exe", 100 * 1024 * 1024, 1000, 10_000, 5_000),
        (102, "CHROME.EXE", 200 * 1024 * 1024, 1000, 20_000, 10_000),
        (103, "chrome.exe", 300 * 1024 * 1024, 1000, 30_000, 15_000),
        (201, "notepad.exe", 50 * 1024 * 1024, 1000, 5_000, 2_000),
    ]

    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: 100.0,
        cpu_count=4,
    )
    res = sampler.sample()

    assert "chrome.exe" in res
    assert "notepad.exe" in res
    assert res["chrome.exe"]["procs"] == 3
    assert res["chrome.exe"]["mem_mb"] == 600.0
    assert res["notepad.exe"]["procs"] == 1
    assert res["notepad.exe"]["mem_mb"] == 50.0


def test_first_call_returns_cpu_none() -> None:
    rows = [
        (101, "demo.exe", 100 * 1024 * 1024, 1000, 10_000_000, 5_000_000),
    ]
    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: 100.0,
        cpu_count=2,
    )
    res = sampler.sample()
    assert res["demo.exe"]["cpu"] is None


def test_cpu_math_with_cpu_count() -> None:
    t = 100.0
    # 1. örnek: cpu_time = 0
    rows = [(101, "worker.exe", 100 * 1024 * 1024, 1000, 0, 0)]
    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: t,
        cpu_count=4,
    )
    sampler.sample()

    # 2. örnek: 1 sn sonra (dt = 1.0 s)
    # 1 çekirdek tam yüklü çalıştı: delta = 10_000_000 (100-ns biriminde 1 saniye)
    # 4 çekirdekli makinede tüm sistemin %25'i olmalı
    t = 101.0
    rows = [(101, "worker.exe", 100 * 1024 * 1024, 1000, 7_000_000, 3_000_000)]
    res = sampler.sample()
    assert res["worker.exe"]["cpu"] == 25.0

    # Aynı hesabı 8 çekirdekle test et: %12.5 olmalı
    t = 200.0
    rows_8 = [(201, "worker.exe", 100 * 1024 * 1024, 2000, 0, 0)]
    sampler_8 = appusage.AppUsageSampler(
        query_fn=lambda: rows_8,
        clock=lambda: t,
        cpu_count=8,
    )
    sampler_8.sample()

    t = 201.0
    rows_8 = [(201, "worker.exe", 100 * 1024 * 1024, 2000, 10_000_000, 0)]
    res_8 = sampler_8.sample()
    assert res_8["worker.exe"]["cpu"] == 12.5


def test_pid_reuse_same_pid_new_create_time() -> None:
    t = 100.0
    # PID 500 ilk başta old.exe olarak çalışıyor
    rows = [(500, "old.exe", 100 * 1024 * 1024, 1000, 50_000_000, 0)]
    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: t,
        cpu_count=2,
    )
    sampler.sample()

    # old.exe kapandı; Windows aynı PID 500'ü new.exe için yeniden kullandı (farklı create_time)
    t = 101.0
    rows = [(500, "new.exe", 80 * 1024 * 1024, 2000, 5_000_000, 0)]
    res = sampler.sample()

    assert "old.exe" not in res
    assert "new.exe" in res
    # new.exe yeni süreç olduğu için ilk örneğinde cpu None dönmeli (yanlış delta hesaplanmamalı)
    assert res["new.exe"]["cpu"] is None


def test_process_exit() -> None:
    t = 100.0
    # İki worker süreci
    rows = [
        (101, "worker.exe", 100 * 1024 * 1024, 1000, 0, 0),
        (102, "worker.exe", 100 * 1024 * 1024, 1000, 0, 0),
    ]
    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: t,
        cpu_count=2,
    )
    sampler.sample()

    # 102 kapandı, yalnızca 101 devam ediyor
    t = 101.0
    rows = [
        (101, "worker.exe", 100 * 1024 * 1024, 1000, 10_000_000, 0),
    ]
    res = sampler.sample()
    assert res["worker.exe"]["procs"] == 1
    assert res["worker.exe"]["cpu"] == 50.0

    # 101 de kapandı
    t = 102.0
    rows = []
    res = sampler.sample()
    assert "worker.exe" not in res


def test_clamp() -> None:
    t = 100.0
    rows = [(101, "burst.exe", 50 * 1024 * 1024, 1000, 0, 0)]
    sampler = appusage.AppUsageSampler(
        query_fn=lambda: rows,
        clock=lambda: t,
        cpu_count=1,
    )
    sampler.sample()

    # İmkânsız büyük delta (ör. saat sıçraması) 100'e kırpılmalı
    t = 101.0
    rows = [(101, "burst.exe", 50 * 1024 * 1024, 1000, 500_000_000, 0)]
    res = sampler.sample()
    assert res["burst.exe"]["cpu"] == 100.0


def test_fmt_table() -> None:
    assert appusage.fmt_usage(None) == "CPU — · Bellek —"
    assert appusage.fmt_usage({}) == "CPU — · Bellek —"

    # CPU None
    assert appusage.fmt_usage({"cpu": None, "mem_mb": 640.0}) == "CPU — · Bellek 640 MB"

    # CPU < 1 (tek ondalık, virgül)
    assert appusage.fmt_usage({"cpu": 0.3, "mem_mb": 640.0}) == "CPU %0,3 · Bellek 640 MB"
    assert appusage.fmt_usage({"cpu": 0.0, "mem_mb": 50.0}) == "CPU %0,0 · Bellek 50 MB"

    # CPU >= 1 (tam sayı) ve Bellek >= 1000 MB (GB tek ondalık)
    # 1433.6 MB / 1024.0 = 1.4 GB
    assert appusage.fmt_usage({"cpu": 12.0, "mem_mb": 1433.6}) == "CPU %12 · Bellek 1,4 GB"
    assert appusage.fmt_usage({"cpu": 99.8, "mem_mb": 2048.0}) == "CPU %100 · Bellek 2,0 GB"


def test_usage_for_tile() -> None:
    data = {
        "chrome.exe": {"cpu": 12.0, "mem_mb": 1433.6, "procs": 5},
        "code.exe": {"cpu": 3.0, "mem_mb": 800.0, "procs": 2},
    }

    tile1 = {"exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe"}
    u1 = appusage.usage_for_tile(data, tile1)
    assert u1 is not None
    assert u1["procs"] == 5

    tile_upper = {"exe": r"C:\TOOLS\CODE.EXE"}
    u2 = appusage.usage_for_tile(data, tile_upper)
    assert u2 is not None
    assert u2["cpu"] == 3.0

    tile_none = {"exe": r"C:\NonExistent\app.exe"}
    assert appusage.usage_for_tile(data, tile_none) is None

    assert appusage.usage_for_tile(data, None) is None
    assert appusage.usage_for_tile(None, tile1) is None


def test_live_smoke() -> None:
    # Gerçek NtQuerySystemInformation sorgusunu salt-okunur olarak sına.
    # Gizlilik kuralı: Süreç adı, başlık veya kullanım ASLA yazdırılmaz/loglanmaz.
    sampler = appusage.AppUsageSampler()
    res = sampler.sample()
    assert isinstance(res, dict)
    assert len(res) > 0


def main() -> int:
    tests = [
        test_grouping_by_exe,
        test_first_call_returns_cpu_none,
        test_cpu_math_with_cpu_count,
        test_pid_reuse_same_pid_new_create_time,
        test_process_exit,
        test_clamp,
        test_fmt_table,
        test_usage_for_tile,
        test_live_smoke,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
