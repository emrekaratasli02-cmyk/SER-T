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

    # Direct error when no previous good value
    store.update("fx", {"err": "Bağlantı yok"})
    fx_val = store.get("fx")
    assert fx_val is not None
    assert fx_val.get("err") == "Bağlantı yok"
    assert fx_val.get("stale") is False

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


if __name__ == "__main__":
    test_helpers()
    test_store()
    test_live_fetches()
