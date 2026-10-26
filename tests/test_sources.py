"""Self-test for sources.py."""

import datetime as dt
import json
import sys
from pathlib import Path

# Ensure sources can be imported from parent directory or current directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources import (
    REFRESH,
    Store,
    fetch_claude,
    fetch_fx,
    fetch_system,
    fetch_weather,
    fmt_tr,
    left_text,
    reset_clock,
    submit,
    tr_num,
)


def test_helpers():
    # tr_num tests
    assert tr_num("49,7644") == 49.7644
    assert tr_num("6.423,18") == 6423.18
    assert tr_num("%0,14") == 0.14
    assert tr_num("%-0,20") == -0.20

    # fmt_tr tests
    assert fmt_tr(6423.18, 2) == "6.423,18"
    assert fmt_tr(49.7644, 4) == "49,7644"
    assert fmt_tr(15.0, 0) == "15"

    # left_text tests
    now = dt.datetime.now(dt.timezone.utc)
    target_30m = (now + dt.timedelta(minutes=30)).isoformat()
    assert left_text(target_30m) in ("29dk", "30dk")

    target_4h35m = (now + dt.timedelta(hours=4, minutes=35)).isoformat()
    # Depending on seconds elapsed
    res_4h = left_text(target_4h35m)
    assert "4sa" in res_4h

    target_4d18h = (now + dt.timedelta(days=4, hours=18)).isoformat()
    res_4d = left_text(target_4d18h)
    assert "4g" in res_4d

    # reset_clock tests
    # Today
    now_today = now.replace(hour=16, minute=9, second=0).isoformat()
    # Turkish time will be +3 hours -> 19:09
    assert reset_clock(now_today) == "19:09"

    # Future date
    future_date = dt.datetime(2026, 10, 31, 5, 59, 0, tzinfo=dt.timezone.utc).isoformat()
    # 05:59 UTC -> 08:59 TR
    assert reset_clock(future_date) == "31 Eki 08:59"

    print("ALL HELPER ASSERTIONS PASSED")


def test_store():
    store = Store()
    assert store.get("sys") is None

    # Normal update
    initial_val = {"cpu": 12.5, "source": "Bu bilgisayar"}
    store.update("sys", initial_val)
    val = store.get("sys")
    assert val is not None
    assert val["cpu"] == 12.5
    assert val["stale"] is False
    assert "fetched_at" in val

    # Stale update on error
    store.update("sys", {"err": "Bağlantı yok"})
    val_stale = store.get("sys")
    assert val_stale is not None
    assert val_stale["cpu"] == 12.5
    assert val_stale["stale"] is True
    assert val_stale["last_error"] == "Bağlantı yok"

    # Direct error when no previous good value (Y1 fix: must carry err + stale=True)
    store.update("fx", {"err": "Bağlantı yok"})
    fx_val = store.get("fx")
    assert fx_val is not None
    assert fx_val.get("err") == "Bağlantı yok"
    assert fx_val.get("stale") is True

    print("ALL STORE ASSERTIONS PASSED")


def test_live_fetches():
    print("--- LIVE FETCH CALLS ---")

    print("\n1. fetch_claude:")
    claude = fetch_claude()
    # Redact any accidental secret if present (though sources.py never includes tokens)
    clean_claude = {k: v for k, v in claude.items() if "token" not in k.lower()}
    print(json.dumps(clean_claude, indent=2, ensure_ascii=False))

    print("\n2. fetch_fx:")
    fx = fetch_fx()
    print(json.dumps(fx, indent=2, ensure_ascii=False))
    assert "usd" in fx or "err" in fx

    print("\n3. fetch_weather:")
    wx = fetch_weather()
    print(json.dumps(wx, indent=2, ensure_ascii=False))
    assert "temp" in wx or "err" in wx

    print("\n4. fetch_system:")
    sys_data = fetch_system()
    print(json.dumps(sys_data, indent=2, ensure_ascii=False))
    assert "cpu" in sys_data or "err" in sys_data

    print("\nREFRESH config:", REFRESH)


def test_type_validation():
    # Test tr_num invalid/safe
    assert tr_num(None) == 0.0
    assert tr_num("nan") == 0.0
    assert tr_num("inf") == 0.0
    assert tr_num("invalid_string") == 0.0

    # Test Store with initial error (Y1)
    s = Store()
    s.update("k1", {"err": "first_fail"})
    res = s.get("k1")
    assert res is not None
    assert res.get("err") == "first_fail"
    assert res.get("stale") is True
    assert res.get("last_error") == "first_fail"

    print("ALL TYPE VALIDATION AND Y1 ASSERTIONS PASSED")


def test_submit_pool():
    import time

    def slow_task():
        time.sleep(0.15)
        return {"done": 1}

    results = []
    # Submit first task
    s1 = submit("test_key", slow_task, lambda k, r: results.append((k, r)))
    assert s1 is True

    # In flight -> second submission for same key must be skipped
    s2 = submit("test_key", slow_task, lambda k, r: results.append((k, r)))
    assert s2 is False

    # Wait for completion
    time.sleep(0.25)
    assert len(results) == 1
    assert results[0] == ("test_key", {"done": 1})

    # Key is now free again
    s3 = submit("test_key", lambda: {"done": 2}, lambda k, r: results.append((k, r)))
    assert s3 is True
    time.sleep(0.05)
    assert len(results) == 2
    assert results[1] == ("test_key", {"done": 2})

    print("ALL SUBMIT POOL ASSERTIONS PASSED")


if __name__ == "__main__":
    test_helpers()
    test_store()
    test_type_validation()
    test_submit_pool()
    test_live_fetches()
