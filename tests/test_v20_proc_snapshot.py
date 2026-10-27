"""tests/test_v20_proc_snapshot.py - hızlı süreç bellek anlık görüntüsü.

Yalnız okuma yapar (NtQuerySystemInformation); hiçbir süreç açılmaz ya da değiştirilmez.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402

import proc_snapshot  # noqa: E402


def test_snapshot_matches_psutil() -> None:
    snap = proc_snapshot.snapshot()
    assert snap is not None and len(snap) > 20, "anlık görüntü alınamadı"
    by_pid = {pid: (name, ws) for pid, name, ws in snap}
    me = os.getpid()
    assert me in by_pid
    name, ws = by_pid[me]
    assert name.lower().startswith("python"), name
    rss = psutil.Process(me).memory_info().rss
    assert abs(ws - rss) <= max(8 * 2**20, 0.1 * rss), (ws, rss)
    print("  [PASS] snapshot kendi sürecimizi psutil ile uyumlu okuyor")


def test_snapshot_is_fast() -> None:
    best = min(_timed(proc_snapshot.snapshot) for _ in range(5))
    assert best < 60.0, f"anlık görüntü yavaş: {best:.1f} ms"
    print(f"  [PASS] snapshot hızlı ({best:.1f} ms)")


def test_top_processes_uses_fast_path() -> None:
    import popover_v2

    t0 = time.perf_counter()
    rows = popover_v2.top_processes(3)
    ms = (time.perf_counter() - t0) * 1000
    assert len(rows) == 3, rows
    assert all(set(r) == {"name", "mb"} and r["mb"] > 0 for r in rows), rows
    assert rows[0]["mb"] >= rows[1]["mb"] >= rows[2]["mb"], rows
    assert all(r["name"].lower() not in ("svchost.exe", "system", "registry", "memory compression") for r in rows)
    assert ms < 150.0, f"top_processes yavaş: {ms:.0f} ms"
    print(f"  [PASS] top_processes hızlı yol ({ms:.0f} ms)")


def _timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


if __name__ == "__main__":
    test_snapshot_matches_psutil()
    test_snapshot_is_fast()
    test_top_processes_uses_fast_path()
    print("ALL TEST_V20_PROC_SNAPSHOT TESTS PASSED")
