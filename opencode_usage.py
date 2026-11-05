"""opencode_usage.py - OpenCode yerel kullanım istatistikleri (token / maliyet).

Yalnızca OKUR: ``~/.local/share/opencode/opencode.db`` SQLite veritabanını
readonly modda açar. Ağ, kimlik doğrulama veya yazma yoktur. Veritabanı yoksa,
kilitliyse veya şeması beklenenden farklıysa boş durum döner; uydurma değer
üretilmez (dock'un genel "—" politikası).

Veri kaynağı:
  * ``session`` tablosu: toplam maliyet ve toplam token (hızlı toplam).
  * ``message`` tablosu: assistant mesajlarının ``tokens``/``cost`` alanları ve
    ``time_created`` (epoch ms) — bugünün kullanımı için.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_DATA_HOME = Path(
    os.environ.get("XDG_DATA_HOME")
    or (Path.home() / ".local" / "share")
)
DEFAULT_DB = _DATA_HOME / "opencode" / "opencode.db"


def _as_int(val: Any) -> int:
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return 0


def _as_float(val: Any) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if (f != f or f in (float("inf"), float("-inf"))) else max(0.0, f)


def _local_tz(now: dt.datetime) -> dt.tzinfo:
    return now.tzinfo or dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def _day_start_ms(day: dt.date, tz: dt.tzinfo) -> int:
    return int(dt.datetime.combine(day, dt.time.min, tzinfo=tz).timestamp() * 1000)


def empty_state(now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Veri yokken dönen nötr durum."""
    now = now or dt.datetime.now().astimezone()
    return {
        "available": False,
        "today_tokens": 0,
        "today_input": 0,
        "today_output": 0,
        "today_reasoning": 0,
        "today_cache_read": 0,
        "today_cache_write": 0,
        "today_cost": 0.0,
        "today_sessions": 0,
        # Kayan 24 saatlik pencere (gece yarısı sıfırlanmasını önler)
        "recent_tokens": 0,
        "recent_input": 0,
        "recent_output": 0,
        "recent_reasoning": 0,
        "recent_cache_read": 0,
        "recent_cost": 0.0,
        "recent_sessions": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "total_sessions": 0,
        "updated": now.strftime("%H:%M"),
        "err": None,
    }


def summarize(records: Iterable[Dict[str, Any]], now: dt.datetime, days: int = 1) -> Dict[str, Any]:
    """Saf özet: kayıtlardan son ``days`` günün token/maliyet toplamını çıkarır.

    Her kayıt: ``{"session_id": str, "created_ms": int, "cost": float, "model": str,
    "tokens": {"input": int, "output": int, "reasoning": int,
               "cache": {"read": int, "write": int}}}``
    """
    tz = _local_tz(now)
    start_day = now.date() - dt.timedelta(days=max(0, int(days) - 1))
    since_ms = _day_start_ms(start_day, tz)
    since24_ms = int((now - dt.timedelta(hours=24)).timestamp() * 1000)

    inp = out = reason = cache_r = cache_w = tokens_total = 0
    cost = 0.0
    sessions = set()
    r_in = r_out = r_reason = r_cr = r_cw = 0
    r_cost = 0.0
    r_sessions = set()
    r_models: Dict[str, int] = {}
    t_models: Dict[str, int] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue
        try:
            created = int(rec.get("created_ms"))
        except (TypeError, ValueError):
            continue
        tokens = rec.get("tokens")
        if not isinstance(tokens, dict):
            continue
        t_in = _as_int(tokens.get("input"))
        t_out = _as_int(tokens.get("output"))
        t_reason = _as_int(tokens.get("reasoning"))
        cache = tokens.get("cache")
        c_read = _as_int(cache.get("read")) if isinstance(cache, dict) else 0
        c_write = _as_int(cache.get("write")) if isinstance(cache, dict) else 0
        t_total = _as_int(tokens.get("total")) or (t_in + t_out + t_reason + c_read + c_write)
        c_cost = _as_float(rec.get("cost"))

        tokens_total += t_total
        cost += c_cost
        sid = rec.get("session_id")
        model = str(rec.get("model") or "")

        if created >= since24_ms:
            r_in += t_in
            r_out += t_out
            r_reason += t_reason
            r_cr += c_read
            r_cw += c_write
            r_cost += c_cost
            if sid:
                r_sessions.add(str(sid))
            if model:
                r_models[model] = r_models.get(model, 0) + t_total

        if created < since_ms:
            continue
        inp += t_in
        out += t_out
        reason += t_reason
        cache_r += c_read
        cache_w += c_write
        if sid:
            sessions.add(str(sid))
        if model:
            t_models[model] = t_models.get(model, 0) + t_total

    return {
        "today_tokens": inp + out + reason + cache_r + cache_w,
        "today_input": inp,
        "today_output": out,
        "today_reasoning": reason,
        "today_cache_read": cache_r,
        "today_cache_write": cache_w,
        "today_cost": round(cost, 4),
        "today_sessions": len(sessions),
        "recent_tokens": r_in + r_out + r_reason + r_cr + r_cw,
        "recent_input": r_in,
        "recent_output": r_out,
        "recent_reasoning": r_reason,
        "recent_cache_read": r_cr,
        "recent_cost": round(r_cost, 4),
        "recent_sessions": len(r_sessions),
        "recent_by_model": r_models,
        "today_by_model": t_models,
        "_msg_tokens_all": tokens_total,
        "_msg_cost_all": round(cost, 4),
    }


# Günlük kullanım için taranacak en fazla mesaj. Mesajlar kronolojik eklendiğinden
# rowid azalan sırada okunur; kesimden eski ilk satırda durulur. Böylece 60 s'lik
# tazeleme, veritabanı büyüdükçe tüm tabloyu JSON-parse etmez.
_MAX_SCAN_MESSAGES = 1500


def _load_message_records(con: sqlite3.Connection, since_ms: int) -> List[Dict[str, Any]]:
    # 1) Yalnız hafif sütunlarla son N mesajın zamanını oku (JSON parse yok).
    meta = con.execute(
        "select rowid, session_id, time_created from message order by rowid desc limit ?",
        (_MAX_SCAN_MESSAGES,),
    ).fetchall()
    wanted = [(int(rowid), str(sid or ""), _as_int(created))
              for rowid, sid, created in meta if _as_int(created) >= since_ms]
    if not wanted:
        return []

    # 2) Yalnız o satırların JSON gövdesini getir (SQLite parametre sınırı için 500'lük parçalar).
    by_rowid = {rowid: (sid, created) for rowid, sid, created in wanted}
    ids = list(by_rowid.keys())
    out: List[Dict[str, Any]] = []
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = con.execute(
            f"select rowid, data from message where rowid in ({placeholders})",
            tuple(chunk),
        )
        for rowid, data in rows:
            try:
                payload = json.loads(data) if isinstance(data, (str, bytes)) else data
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            tokens = payload.get("tokens")
            if not isinstance(tokens, dict):
                continue
            sid, created_ms = by_rowid[int(rowid)]
            out.append({
                "session_id": sid,
                "created_ms": created_ms,
                "cost": _as_float(payload.get("cost")),
                "model": str(payload.get("modelID") or ""),
                "tokens": tokens,
            })
    return out


def read_usage(
    db_path: Optional[Path] = None,
    now: Optional[dt.datetime] = None,
    days: int = 1,
) -> Dict[str, Any]:
    """OpenCode veritabanından son ``days`` günün kullanımını okur.

    Asla istisna fırlatmaz; hata durumunda ``empty_state`` benzeri bir sözlük döner.
    """
    now = now or dt.datetime.now().astimezone()
    path = Path(db_path) if db_path is not None else DEFAULT_DB
    state = empty_state(now)

    if not path.exists():
        return state

    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1.0)
        con.execute("pragma query_only = on")

        row = con.execute(
            "select coalesce(sum(cost), 0), "
            "coalesce(sum(tokens_input + tokens_output + tokens_cache_read), 0), "
            "count(*) from session"
        ).fetchone()
        if row is not None:
            state["total_cost"] = round(_as_float(row[0]), 4)
            state["total_tokens"] = _as_int(row[1])
            state["total_sessions"] = _as_int(row[2])

        tz = _local_tz(now)
        start_day = now.date() - dt.timedelta(days=max(0, int(days) - 1))
        since_ms = _day_start_ms(start_day, tz)
        # "recent" (son 24 sa) penceresi için gün başından daha geriye gidebiliriz.
        load_since = min(since_ms, int((now - dt.timedelta(hours=24)).timestamp() * 1000))
        records = _load_message_records(con, load_since)
        summary = summarize(records, now, days=days)
        summary.pop("_msg_tokens_all", None)
        summary.pop("_msg_cost_all", None)
        state.update(summary)
        state["available"] = True
        state["updated"] = now.strftime("%H:%M")
        state["err"] = None
        return state
    except Exception:
        # Bozuk/kilitli/şeması farklı veritabanı: sessizce boş durum.
        state["err"] = None
        return state
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
