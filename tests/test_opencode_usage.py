"""opencode_usage testleri - saf özet + geçici SQLite üzerinden okuma.

Gerçek OpenCode veritabanına dokunulmaz; tüm veriler tempfile içinde üretilir.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

import opencode_usage as ou  # noqa: E402

LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 11, 4, 12, 0, tzinfo=LOCAL_TZ)


def _ms(d: dt.datetime) -> int:
    return int(d.timestamp() * 1000)


def _rec(created: dt.datetime, sid: str = "s1", inp: int = 0, out: int = 0,
         cache_read: int = 0, cost: float = 0.0) -> dict:
    return {
        "session_id": sid,
        "created_ms": _ms(created),
        "cost": cost,
        "tokens": {
            "input": inp,
            "output": out,
            "reasoning": 0,
            "cache": {"read": cache_read, "write": 0},
        },
    }


def test_summarize_today_only():
    today = NOW.replace(hour=9)
    old = NOW - dt.timedelta(hours=25)
    records = [
        _rec(today, "a", inp=100, out=20, cache_read=1000),
        _rec(today, "b", inp=50, out=10),
        _rec(old, "old", inp=999, out=999, cache_read=999),
    ]
    s = ou.summarize(records, NOW, days=1)
    assert s["today_input"] == 150
    assert s["today_output"] == 30
    assert s["today_cache_read"] == 1000
    assert s["today_tokens"] == 150 + 30 + 1000
    assert s["today_sessions"] == 2
    assert s["today_cost"] == 0.0
    # Son 24 saat: 25 saat öncesi hariç, bugünkü kayıtlar dahil
    assert s["recent_input"] == 150
    assert s["recent_sessions"] == 2


def test_recent_window_survives_midnight():
    """Gece yarısından hemen sonra 'bugün' 0 olur ama kart son 24 saati gösterir."""
    now = dt.datetime(2026, 11, 5, 0, 30, tzinfo=LOCAL_TZ)
    late = dt.datetime(2026, 11, 4, 23, 50, tzinfo=LOCAL_TZ)
    s = ou.summarize([_rec(late, "a", inp=100, out=20)], now, days=1)
    assert s["today_input"] == 0 and s["today_output"] == 0
    assert s["recent_input"] == 100 and s["recent_output"] == 20
    assert s["recent_sessions"] == 1


def test_summarize_multi_day_window():
    today = NOW.replace(hour=9)
    two_days_ago = NOW - dt.timedelta(days=2)
    records = [
        _rec(today, "a", inp=10),
        _rec(two_days_ago, "b", inp=20),
    ]
    assert ou.summarize(records, NOW, days=1)["today_input"] == 10
    assert ou.summarize(records, NOW, days=3)["today_input"] == 30


def test_summarize_bad_records_are_ignored():
    records = [
        None,
        {"created_ms": "x", "tokens": {"input": 10}},
        {"created_ms": _ms(NOW), "tokens": "oops"},
        {"created_ms": _ms(NOW), "tokens": {"input": "5", "output": -3, "cache": None}},
    ]
    s = ou.summarize(records, NOW, days=1)
    assert s["today_input"] == 5
    assert s["today_output"] == 0


def test_read_usage_missing_db():
    missing = Path(tempfile.gettempdir()) / "serit_no_such_opencode.db"
    try:
        missing.unlink()
    except FileNotFoundError:
        pass
    s = ou.read_usage(db_path=missing, now=NOW)
    assert s["available"] is False
    assert s["today_tokens"] == 0
    assert s["total_tokens"] == 0
    assert s["err"] is None


def test_read_usage_temp_db():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "opencode.db"
        con = sqlite3.connect(db)
        con.execute(
            "create table session (cost real, tokens_input int, tokens_output int, tokens_cache_read int)"
        )
        con.execute("create table message (session_id text, time_created int, data text)")
        con.execute("insert into session values (0.0, 1000, 200, 5000)")
        con.execute("insert into session values (0.0, 500, 100, 1000)")
        today = NOW.replace(hour=8)
        old = NOW - dt.timedelta(days=5)
        for sid, when, inp, out, cache in (
            ("s1", today, 300, 40, 2000),
            ("s1", today, 100, 10, 500),
            ("s2", old, 999, 999, 999),
        ):
            payload = {
                "tokens": {"input": inp, "output": out, "reasoning": 0,
                           "cache": {"read": cache, "write": 0}},
                "cost": 0.0,
            }
            con.execute(
                "insert into message values (?, ?, ?)",
                (sid, _ms(when), json.dumps(payload)),
            )
        con.commit()
        con.close()

        s = ou.read_usage(db_path=db, now=NOW, days=1)
        assert s["available"] is True
        assert s["today_input"] == 400
        assert s["today_output"] == 50
        assert s["today_cache_read"] == 2500
        assert s["today_sessions"] == 1
        # Son 24 sa: bugünkü kayıtlar (5 gün öncesi hariç)
        assert s["recent_input"] == 400
        assert s["recent_sessions"] == 1
        # Toplamlar session tablosundan
        assert s["total_tokens"] == 7800
        assert s["total_sessions"] == 2
        assert s["updated"] == "12:00"


def test_format_token_count():
    import dock_cards
    assert dock_cards.format_token_count(999) == "999"
    assert dock_cards.format_token_count(1500) == "1,5K"
    assert dock_cards.format_token_count(2_400_000) == "2,4M"
    assert dock_cards.format_token_count(None) == "—"


if __name__ == "__main__":
    test_summarize_today_only()
    test_recent_window_survives_midnight()
    test_summarize_multi_day_window()
    test_summarize_bad_records_are_ignored()
    test_read_usage_missing_db()
    test_read_usage_temp_db()
    test_format_token_count()
    print("opencode_usage tests PASSED")
