"""test_v23_calendar_fallback.py - takvim güncelleyicisi bir kez hata yazınca kart boşalmaz (v23).

Zero side effects: only temp JSON files with sample events are read; the real ay.json / yakin.json are
never opened; log goes to the test redirect (logpath).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import sources  # noqa: E402

TZ = sources.LOCAL_TZ
NOW = dt.datetime(2026, 10, 14, 10, 0, tzinfo=TZ)
TMP = Path(tempfile.mkdtemp(prefix="serit_v23cal_"))


def _write(name: str, data: dict) -> Path:
    p = TMP / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


GOOD_MONTH = {
    "zaman": "2026-10-14T09:45:00+03:00", "bas": "2026-10-01T00:00:00+03:00", "bit": "2026-12-01T00:00:00+03:00",
    "etkinlikler": [{"baslik": "Örnek toplantı", "bas": "2026-10-15T09:30:00+03:00",
                     "bit": "2026-10-15T10:00:00+03:00", "tum_gun": False, "yer": "", "link": ""}],
    "hata": None,
}
BAD = {"zaman": "2026-10-14T10:00:00+03:00", "etkinlikler": [], "hata": "httpx.ConnectError: [Errno 11001] getaddrinfo failed"}


def test_month_falls_back_to_last_good() -> None:
    sources._LAST_GOOD_MONTH_CALENDAR = None
    # hiç iyi veri yokken: eskisi gibi hata
    r0 = sources.fetch_month_calendar(path=_write("ay_bad0.json", dict(BAD, bas=None, bit=None)), now=NOW)
    assert r0["err"] == "Takvim güncellenemedi" and r0["events"] == []
    good = sources.fetch_month_calendar(path=_write("ay_good.json", GOOD_MONTH), now=NOW)
    assert good["err"] is None and len(good["events"]) == 1 and not good["stale"]
    bad = sources.fetch_month_calendar(path=_write("ay_bad.json", dict(BAD, bas=None, bit=None)), now=NOW)
    assert bad["err"] is None, bad
    assert bad["stale"] is True
    assert [e["title"] for e in bad["events"]] == ["Örnek toplantı"]
    # son iyi veri değişmedi (soluk kopya önbelleği bozmadı)
    assert sources._LAST_GOOD_MONTH_CALENDAR["stale"] is False


def test_near_falls_back_to_last_good() -> None:
    sources._LAST_GOOD_CALENDAR = None
    assert sources.fetch_calendar.__code__.co_argcount >= 1
    orig = sources.CALENDAR_JSON
    try:
        sources.CALENDAR_JSON = _write("yakin_bad0.json", BAD)
        assert sources.fetch_calendar(now=NOW).get("err") == "Takvim güncellenemedi"
        sources.CALENDAR_JSON = _write("yakin_good.json", dict(GOOD_MONTH))
        good = sources.fetch_calendar(now=NOW)
        assert not good.get("err") and good["next"]["title"] == "Örnek toplantı"
        sources.CALENDAR_JSON = _write("yakin_bad.json", BAD)
        bad = sources.fetch_calendar(now=NOW)
        assert not bad.get("err"), bad
        assert bad["stale"] is True and bad["stale_file"] is True
        assert bad["next"]["title"] == "Örnek toplantı"
    finally:
        sources.CALENDAR_JSON = orig


def test_source_error_log_is_short_and_has_no_events() -> None:
    seen = []
    orig = sources.log_err
    try:
        sources.log_err = lambda src, exc: seen.append((src, str(exc)))
        sources._log_calendar_source_error("calendar_source", "satır 1\n" + "x" * 500)
        sources._log_calendar_source_error("calendar_source", None)
    finally:
        sources.log_err = orig
    assert seen[0][0] == "calendar_source" and len(seen[0][1]) < 220 and "satır 1" not in seen[0][1]
    assert "bilinmeyen hata" in seen[1][1]


def run_all() -> None:
    for fn in (test_month_falls_back_to_last_good, test_near_falls_back_to_last_good,
               test_source_error_log_is_short_and_has_no_events):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V23_CALENDAR_FALLBACK TESTS PASSED")


if __name__ == "__main__":
    run_all()
