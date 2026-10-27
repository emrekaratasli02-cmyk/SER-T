"""Data-source module for Şerit. Pure Python, no Qt dependencies."""

import concurrent.futures
import datetime as dt
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
import psutil

CRED_PATH = Path.home() / ".claude" / ".credentials.json"
from logpath import CLAUDE_CACHE, LOG_PATH

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=3)
_IN_FLIGHT: set[str] = set()
_LOCK = threading.Lock()


def submit(key: str, fn: Callable[[], Any], callback: Optional[Callable[..., None]] = None) -> bool:
    """Submit a fetch task to the thread pool in a thread-safe way.

    If a task with the same key is already running/in flight, skips submission
    and returns False. Returns True if the task was successfully submitted.
    Callback is invoked with (key, result) or (result,) when finished.
    """
    with _LOCK:
        if key in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(key)

    def _worker() -> None:
        res: Any = None
        try:
            try:
                res = fn()
            except Exception as exc:
                log_err(key, exc)
                res = {"err": "Bağlantı yok"}

            if callback is not None:
                try:
                    callback(key, res)
                except TypeError:
                    try:
                        callback(res)
                    except Exception as cb_exc:
                        log_err(f"{key}_cb", cb_exc)
                except Exception as cb_exc:
                    log_err(f"{key}_cb", cb_exc)
        finally:
            with _LOCK:
                _IN_FLIGHT.discard(key)

    try:
        _EXECUTOR.submit(_worker)
        return True
    except Exception as exc:
        with _LOCK:
            _IN_FLIGHT.discard(key)
        log_err(f"submit_{key}", exc)
        return False


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely coerce value to float; returns default on None/NaN/Inf/ValueError."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


REFRESH = {
    "claude": 300,
    "fx": 300,
    "wx": 900,
    "sys": 2,
    "cal": 60,  # yerel dosya okuması, Google'a gitmez
}

# WMO Weather interpretation codes
WMO_DESC = {
    0: "Açık",
    1: "Az bulutlu",
    2: "Parçalı bulutlu",
    3: "Kapalı",
    45: "Sis",
    48: "Sis",
    51: "Hafif çisenti",
    53: "Orta çisenti",
    55: "Yoğun çisenti",
    56: "Hafif donan çisenti",
    57: "Yoğun donan çisenti",
    61: "Hafif yağmur",
    63: "Orta şiddette yağmur",
    65: "Kuvvetli yağmur",
    66: "Hafif donan yağmur",
    67: "Kuvvetli donan yağmur",
    71: "Hafif kar",
    73: "Orta şiddette kar",
    75: "Yoğun kar",
    77: "Kar taneleri",
    80: "Hafif sağanak",
    81: "Orta şiddette sağanak",
    82: "Kuvvetli sağanak",
    85: "Hafif kar sağanağı",
    86: "Yoğun kar sağanağı",
    95: "Fırtına",
    96: "Hafif dolu fırtınası",
    99: "Kuvvetli dolu fırtınası",
}

WMO_ICON = {
    0: "sun",
    1: "partly",
    2: "partly",
    3: "cloud",
    45: "fog",
    48: "fog",
    51: "rain",
    53: "rain",
    55: "rain",
    56: "rain",
    57: "rain",
    61: "rain",
    63: "rain",
    65: "rain",
    66: "rain",
    67: "rain",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "rain",
    81: "rain",
    82: "rain",
    85: "snow",
    86: "snow",
    95: "storm",
    96: "storm",
    99: "storm",
}

TR_MONTHS = {
    1: "Oca",
    2: "Şub",
    3: "Mar",
    4: "Nis",
    5: "May",
    6: "Haz",
    7: "Tem",
    8: "Ağu",
    9: "Eyl",
    10: "Eki",
    11: "Kas",
    12: "Ara",
}

try:
    import zoneinfo

    LOCAL_TZ = zoneinfo.ZoneInfo("Europe/Istanbul")
except Exception:
    LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))


def rotate_log_if_needed() -> None:
    """Rotate serit.log to serit.log.1 if it exceeds 1 MB."""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1024 * 1024:
            log1 = LOG_PATH.with_name(LOG_PATH.name + ".1")
            if log1.exists():
                try:
                    log1.unlink()
                except OSError:
                    pass
            os.replace(LOG_PATH, log1)
    except Exception:
        pass


rotate_log_if_needed()


def log_err(source: str, exc: Exception) -> None:
    """Log network/source exception without sensitive tokens."""
    try:
        rotate_log_if_needed()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} [{source}] {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def tr_num(s: Any) -> float:
    """Convert Turkish or plain formatted number string or numeric value to float.

    Rules:
      - Numeric types (int, float) pass through directly (NaN/Inf return 0.0).
      - Strings with commas: Turkish format, e.g. '6.397,04' -> 6397.04, '49,77' -> 49.77.
        Dots are removed as thousands separators, comma replaced by dot.
      - Strings without commas:
          - Multiple dots (e.g. '1.234.567'): dots removed as thousands separators.
          - Exactly one dot:
              - Ambiguous case: if exactly 3 digits follow the dot (e.g. '1.234'),
                treated as thousands separator only when no comma is present (returns 1234.0).
              - Otherwise (e.g. <=2 decimals like '49.77', or >3 decimals):
                treated as standard decimal point (returns 49.77).
          - No dots: plain integer string.
      - Returns 0.0 on invalid string or conversion error.
    """
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        if math.isnan(s) or math.isinf(s):
            return 0.0
        return float(s)

    try:
        clean = str(s).strip().replace("%", "")
        if not clean:
            return 0.0

        if "," in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "." in clean:
            dot_count = clean.count(".")
            if dot_count > 1:
                clean = clean.replace(".", "")
            else:
                parts = clean.split(".")
                if len(parts[1]) == 3 and parts[1].isdigit():
                    clean = parts[0] + parts[1]

        val = float(clean)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return val
    except (ValueError, TypeError):
        return 0.0


def fmt_tr(x: Any, dec: int = 2) -> str:
    """Format float into Turkish number format (e.g. 6423.18 -> '6.423,18').

    Returns '—' on None, NaN, inf, or non-numeric values.
    """
    if x is None:
        return "—"
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return "—"
        fmt = f"{f:,.{dec}f}"
        return fmt.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "—"


def fetch_media() -> Dict[str, Any]:
    """Fetch current media playback and volume state off the GUI thread."""
    try:
        import media
        np = media.now_playing()
    except Exception as exc:
        log_err("fetch_media_np", exc)
        np = None

    try:
        import media
        vol = media.get_volume()
    except Exception as exc:
        log_err("fetch_media_vol", exc)
        vol = {"level": 0, "muted": False, "device": ""}

    return {"np": np, "vol": vol}


def left_text(iso: str) -> str:
    """Calculate remaining time until iso UTC timestamp like '4sa 35dk' / '4g 18sa' / '12dk'."""
    try:
        end = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.timezone.utc)
    sec = max(0, (end - dt.datetime.now(dt.timezone.utc)).total_seconds())
    d, rem = divmod(int(sec), 86400)
    h, m = rem // 3600, (rem % 3600) // 60
    if d:
        return f"{d}g {h}sa"
    if h:
        return f"{h}sa {m}dk"
    return f"{m}dk"


def reset_clock(iso: str) -> str:
    """Format iso timestamp to local Europe/Istanbul time like '19:09' or '31 Eki 08:59' if not today."""
    try:
        t = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    loc = t.astimezone(LOCAL_TZ)
    now_loc = dt.datetime.now(LOCAL_TZ)
    if loc.date() == now_loc.date():
        return f"{loc.hour:02d}:{loc.minute:02d}"
    m = TR_MONTHS.get(loc.month, f"{loc.month:02d}")
    return f"{loc.day} {m} {loc.hour:02d}:{loc.minute:02d}"


_claude_cooldown_until = 0.0


def _claude_cached(reason: str) -> Dict[str, Any]:
    """Son iyi Claude değerini döndür (kaynak satırında önbellek saati yazar); yoksa hata."""
    try:
        c = json.loads(CLAUDE_CACHE.read_text(encoding="utf-8"))
        at = dt.datetime.fromtimestamp(float(c.pop("cached_at"))).strftime("%H:%M")
        c["source"] = f"Anthropic · önbellek {at} ({reason})"
        return c
    except (OSError, ValueError, KeyError, TypeError):
        return {"err": reason}


def fetch_claude() -> Dict[str, Any]:
    """429/ağ hatasında bekleme süresine uyar ve son iyi değeri gösterir."""
    global _claude_cooldown_until
    if time.time() < _claude_cooldown_until:
        return _claude_cached("Anthropic limiti, bekleniyor")
    res = _fetch_claude_live()
    if "err" not in res:
        try:
            CLAUDE_CACHE.write_text(json.dumps({**res, "cached_at": time.time()}, ensure_ascii=False),
                                    encoding="utf-8")
        except OSError:
            pass
        return res
    if res.get("err") == "Hata 429":
        _claude_cooldown_until = time.time() + res.pop("_retry_after", 600)
        return _claude_cached("Anthropic limiti, bekleniyor")
    if res.get("err") in ("Bağlantı yok",) or str(res.get("err", "")).startswith("Hata 5"):
        return _claude_cached(res["err"])
    return res


def _fetch_claude_live() -> Dict[str, Any]:
    """Fetch Claude usage from Anthropic OAuth usage endpoint."""
    try:
        if not CRED_PATH.exists():
            return {"err": "Claude Code girişi yok"}
        creds_json = json.loads(CRED_PATH.read_text(encoding="utf-8"))
        c = creds_json.get("claudeAiOauth")
        if not isinstance(c, dict):
            return {"err": "Claude Code girişi yok"}

        token = c.get("accessToken")
        expires_at = c.get("expiresAt", 0)
        plan = c.get("subscriptionType", "")

        if not token:
            return {"err": "Claude Code girişi yok"}

        # expiresAt is in milliseconds
        if (expires_at / 1000.0) < time.time():
            return {"err": "Giriş süresi doldu, Claude Code’u bir kez aç"}

        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        }
        resp = httpx.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 429:
            try:
                ra = max(120.0, min(float(resp.headers.get("retry-after", 600)), 3600.0))
            except ValueError:
                ra = 600.0
            return {"err": "Hata 429", "_retry_after": ra}
        if resp.status_code != 200:
            return {"err": f"Hata {resp.status_code}"}

        data = resp.json()
        if not isinstance(data, dict):
            return {"err": "Geçersiz veri"}

        fh = data.get("five_hour")
        if not isinstance(fh, dict):
            fh = {}
        sd = data.get("seven_day")
        if not isinstance(sd, dict):
            sd = {}
        opus_data = data.get("seven_day_opus")

        opus_val = None
        if isinstance(opus_data, dict):
            opus_raw = opus_data.get("utilization")
            opus_val = _safe_float(opus_raw, None)
        elif opus_data is not None:
            opus_val = _safe_float(opus_data, None)

        session_raw = fh.get("utilization")
        week_raw = sd.get("utilization")

        session_val = _safe_float(session_raw, None)
        week_val = _safe_float(week_raw, None)

        # Read subscription metadata from ~/.claude.json (same as Lumabar)
        sub_since = ""
        tier_label = str(plan or "")
        try:
            claude_cfg = Path.home() / ".claude.json"
            if claude_cfg.exists():
                cfg_j = json.loads(claude_cfg.read_text(encoding="utf-8"))
                acct = cfg_j.get("oauthAccount") or {}
                raw_tier = str(acct.get("organizationRateLimitTier") or "")
                if "max_20x" in raw_tier:
                    tier_label = "Max 20x"
                elif "max_5x" in raw_tier:
                    tier_label = "Max 5x"
                elif "max" in raw_tier or acct.get("organizationType") == "claude_max":
                    tier_label = "Max"
                sub_iso = str(acct.get("subscriptionCreatedAt") or "")
                if sub_iso:
                    sub_since = sub_iso
        except Exception:
            pass

        extra_obj = data.get("extra_usage") or {}
        extra_enabled = bool(extra_obj.get("is_enabled", False)) if isinstance(extra_obj, dict) else False

        return {
            "session": session_val,
            "session_reset": str(fh.get("resets_at", "") or ""),
            "week": week_val,
            "week_reset": str(sd.get("resets_at", "") or ""),
            "opus": opus_val,
            "plan": tier_label or "",
            "subscribed_at": sub_since,
            "extra_usage": extra_enabled,
            "source": "Anthropic · Claude Code girişi",
        }
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log_err("claude", exc)
        return {"err": "Bağlantı yok"}
    except Exception as exc:
        log_err("claude", exc)
        return {"err": "Bağlantı yok"}


def fetch_fx() -> Dict[str, Any]:
    """Fetch exchange rates and gold prices from finans.truncgil.com."""
    try:
        resp = httpx.get("https://finans.truncgil.com/today.json", timeout=15)
        if resp.status_code != 200:
            return {"err": f"Hata {resp.status_code}"}
        j = resp.json()
        if not isinstance(j, dict):
            return {"err": "Geçersiz veri"}
        usd = j.get("USD")
        eur = j.get("EUR")
        gold = j.get("gram-altin")
        if not isinstance(usd, dict) or not isinstance(eur, dict) or not isinstance(gold, dict):
            return {"err": "Geçersiz veri"}

        usd_val = tr_num(usd.get("Satış", "0"))
        usd_chg = tr_num(usd.get("Değişim", "0"))
        eur_val = tr_num(eur.get("Satış", "0"))
        eur_chg = tr_num(eur.get("Değişim", "0"))
        gold_val = tr_num(gold.get("Satış", "0"))
        gold_chg = tr_num(gold.get("Değişim", "0"))

        if usd_val <= 0:
            return {"err": "Geçersiz veri"}

        return {
            "usd": usd_val,
            "usd_chg": usd_chg,
            "eur": eur_val,
            "eur_chg": eur_chg,
            "gold": gold_val,
            "gold_chg": gold_chg,
            "updated": str(j.get("Update_Date", "")),
            "source": "finans.truncgil.com",
        }
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log_err("fx", exc)
        return {"err": "Bağlantı yok"}
    except Exception as exc:
        log_err("fx", exc)
        return {"err": "Bağlantı yok"}


def fetch_weather(lat: float = 38.37, lon: float = 34.03) -> Dict[str, Any]:
    """Fetch weather forecast from open-meteo."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=Europe/Istanbul"
        )
        resp = httpx.get(url, timeout=15)
        if resp.status_code != 200:
            return {"err": f"Hata {resp.status_code}"}
        j = resp.json()
        if not isinstance(j, dict):
            return {"err": "Geçersiz veri"}
        cur = j.get("current")
        daily = j.get("daily")
        if not isinstance(cur, dict) or not isinstance(daily, dict):
            return {"err": "Geçersiz veri"}

        temp_val = _safe_float(cur.get("temperature_2m"), None)
        feel_val = _safe_float(cur.get("apparent_temperature"), None)
        if temp_val is None or feel_val is None:
            return {"err": "Geçersiz veri"}

        wind_val = _safe_float(cur.get("wind_speed_10m"), 0.0)

        code_raw = cur.get("weather_code")
        try:
            code = int(code_raw) if code_raw is not None else 0
        except (ValueError, TypeError):
            code = 0

        desc = WMO_DESC.get(code, "Bilinmiyor")
        icon = WMO_ICON.get(code, "cloud")

        max_list = daily.get("temperature_2m_max")
        min_list = daily.get("temperature_2m_min")
        max_raw = max_list[0] if isinstance(max_list, list) and max_list else None
        min_raw = min_list[0] if isinstance(min_list, list) and min_list else None
        max_val = _safe_float(max_raw, temp_val)
        min_val = _safe_float(min_raw, temp_val)

        return {
            "temp": temp_val,
            "feel": feel_val,
            "code": code,
            "desc": desc,
            "icon": icon,
            "max": max_val if max_val is not None else temp_val,
            "min": min_val if min_val is not None else temp_val,
            "wind": wind_val if wind_val is not None else 0.0,
            "source": "open-meteo.com",
        }
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log_err("wx", exc)
        return {"err": "Bağlantı yok"}
    except Exception as exc:
        log_err("wx", exc)
        return {"err": "Bağlantı yok"}


def fetch_system() -> Dict[str, Any]:
    """Fetch current system statistics: cpu, ram, disk_c."""
    try:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("C:/")

        cpu = _safe_float(psutil.cpu_percent(None), None)
        ram = _safe_float(vm.percent, None)
        ram_used = _safe_float(vm.used / (1024**3), None)
        ram_total = _safe_float(vm.total / (1024**3), None)
        disk_c = _safe_float(disk.percent, None)

        return {
            "cpu": cpu,
            "ram": ram,
            "ram_used_gb": ram_used,
            "ram_total_gb": ram_total,
            "disk_c": disk_c,
            "source": "Bu bilgisayar",
        }
    except Exception as exc:
        log_err("sys", exc)
        return {"err": "Bağlantı yok"}


class Store:
    """Holds latest value per key ('claude','fx','wx','sys'), with timestamps and stale caching."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def update(self, key: str, result: Any) -> None:
        now = time.time()
        if not isinstance(result, dict):
            self._data[key] = {"data": result, "fetched_at": now, "stale": False}
            return
        prev = self._data.get(key)
        # 'err': None hata değildir (fetch_month_calendar her zaman 'err' anahtarı döndürür);
        # eskiden anahtarın varlığı hata sayılıyor, takvim boşuna "eski veri" gösteriyordu.
        has_err = bool(result.get("err"))

        if has_err and prev and not prev.get("err"):
            prev["stale"] = True
            prev["last_error"] = result["err"]
            return

        entry = dict(result)
        entry["fetched_at"] = now
        # Kaynağın kendi 'stale' bilgisini (ör. ay.json 3 saatten eski) ezme.
        entry["stale"] = has_err or bool(result.get("stale", False))
        if has_err and "last_error" not in entry:
            entry["last_error"] = result["err"]
        self._data[key] = entry

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._data.get(key)


# --- Takvim (kişisel 02) -------------------------------------------------------
# Şerit Google'a hiç bağlanmaz: Hermes'in "Takvim yakın etkinlikler (panel)" zamanlanmış işi
# (her 15 dk, 07-23) 02 takvimini salt-okunur çekip bu dosyaya yazıyor. Biz sadece dosyayı okuruz.
CALENDAR_JSON = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/takvim-02/yakin.json")
CALENDAR_MONTH_JSON = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/takvim-02/ay.json")

_LAST_GOOD_CALENDAR: Optional[Dict[str, Any]] = None
_LAST_GOOD_MONTH_CALENDAR: Optional[Dict[str, Any]] = None


def _safe_read_json_file(path: Path) -> Tuple[Optional[Any], Optional[Exception]]:
    """Read and parse JSON file, retrying once after 150ms on JSONDecodeError."""
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except json.JSONDecodeError:
        time.sleep(0.15)
        try:
            text = path.read_text(encoding="utf-8")
            return json.loads(text), None
        except json.JSONDecodeError as retry_exc:
            return None, retry_exc
    except Exception as exc:
        return None, exc


def classify_calendar_category(title: Any) -> str:
    """Classify calendar event category based on title keywords and emoji."""
    if not title:
        return "Google Takvim"
    s = str(title).strip()
    if s.startswith("💸"):
        return "Vergi/ödeme"
    lower = s.casefold()
    for kw in ("vergi", "kdv", "öde", "sgk", "fatura"):
        if kw in lower:
            return "Vergi/ödeme"
    return "Google Takvim"


def _parse_month_date_or_dt(val: Any) -> Tuple[Optional[Union[dt.date, dt.datetime]], bool]:
    """Parse date string/object. Returns (date_or_datetime, is_all_day)."""
    if isinstance(val, dt.datetime):
        t = val if val.tzinfo else val.replace(tzinfo=LOCAL_TZ)
        return t, False
    if isinstance(val, dt.date):
        return val, True
    if not isinstance(val, str) or not val.strip():
        return None, False
    s = val.strip()
    if len(s) == 10:
        try:
            return dt.date.fromisoformat(s), True
        except (ValueError, TypeError):
            return None, False
    try:
        t = dt.datetime.fromisoformat(s)
        return (t if t.tzinfo else t.replace(tzinfo=LOCAL_TZ)), False
    except (ValueError, TypeError):
        return None, False


def fetch_month_calendar(
    path: Optional[Path] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Read and parse month calendar data from ay.json.

    Returns:
        {'events': [{title, start, end, all_day, link, category}],
         'updated': 'HH:MM',
         'stale': bool,
         'range': (date_from, date_to),
         'err': str|None}
    """
    global _LAST_GOOD_MONTH_CALENDAR
    target_path = path or CALENDAR_MONTH_JSON
    raw, err = _safe_read_json_file(target_path)
    if err is not None:
        if isinstance(err, FileNotFoundError):
            return {
                "events": [],
                "updated": "",
                "stale": True,
                "range": (None, None),
                "err": "Takvim dosyası yok",
            }
        if isinstance(err, json.JSONDecodeError):
            if _LAST_GOOD_MONTH_CALENDAR is not None:
                res = dict(_LAST_GOOD_MONTH_CALENDAR)
                res["stale"] = True
                return res
            return {
                "events": [],
                "updated": "",
                "stale": True,
                "range": (None, None),
                "err": "Takvim okunamadı",
            }
        log_err("month_calendar_read", err)
        return {
            "events": [],
            "updated": "",
            "stale": True,
            "range": (None, None),
            "err": "Takvim okunamadı",
        }

    if not isinstance(raw, dict):
        return {
            "events": [],
            "updated": "",
            "stale": True,
            "range": (None, None),
            "err": "Geçersiz veri",
        }

    if raw.get("hata"):
        return {
            "events": [],
            "updated": "",
            "stale": True,
            "range": (None, None),
            "err": "Takvim güncellenemedi",
        }

    try:
        now = now or dt.datetime.now(LOCAL_TZ)
        upd_raw = raw.get("zaman")
        upd = None
        if isinstance(upd_raw, str) and upd_raw.strip():
            try:
                t = dt.datetime.fromisoformat(upd_raw.strip())
                upd = t if t.tzinfo else t.replace(tzinfo=LOCAL_TZ)
            except (ValueError, TypeError):
                upd = None

        updated_str = upd.strftime("%H:%M") if upd else ""
        stale = bool(not upd or (now - upd).total_seconds() > 3 * 3600)

        # Range extraction from top-level bas and bit
        range_from, _ = _parse_month_date_or_dt(raw.get("bas"))
        range_to, _ = _parse_month_date_or_dt(raw.get("bit"))
        rf_date = range_from.date() if isinstance(range_from, dt.datetime) else range_from
        rt_date = range_to.date() if isinstance(range_to, dt.datetime) else range_to
        data_range = (rf_date, rt_date)

        events: List[Dict[str, Any]] = []
        raw_events = raw.get("etkinlikler")
        if isinstance(raw_events, list):
            for e in raw_events:
                if not isinstance(e, dict):
                    continue
                start_val, all_day = _parse_month_date_or_dt(e.get("bas"))
                if start_val is None:
                    continue

                end_val, _ = _parse_month_date_or_dt(e.get("bit"))
                if end_val is None:
                    if all_day and isinstance(start_val, dt.date):
                        end_val = start_val + dt.timedelta(days=1)
                    else:
                        end_val = start_val
                elif all_day and isinstance(end_val, dt.datetime):
                    end_val = end_val.date()

                title_str = str(e.get("baslik") or "(başlıksız)")
                cat = classify_calendar_category(title_str)

                events.append({
                    "title": title_str,
                    "start": start_val,
                    "end": end_val,
                    "all_day": all_day,
                    "link": str(e.get("link") or ""),
                    "category": cat,
                })

        # Sort events by start date/time
        def _sort_key(ev: Dict[str, Any]) -> Tuple[dt.date, int, dt.time]:
            s = ev["start"]
            if isinstance(s, dt.datetime):
                return s.date(), 1, s.time()
            return s, 0, dt.time.min

        events.sort(key=_sort_key)

        res = {
            "events": events,
            "updated": updated_str,
            "stale": stale,
            "range": data_range,
            "err": None,
        }
        _LAST_GOOD_MONTH_CALENDAR = dict(res)
        return res
    except Exception as exc:
        log_err("month_calendar_parse", exc)
        return {
            "events": [],
            "updated": "",
            "stale": True,
            "range": (None, None),
            "err": "Takvim okunamadı",
        }


def _parse_event_time(s: Any) -> Optional[dt.datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        if len(s) == 10:  # tüm gün: YYYY-MM-DD
            return dt.datetime.fromisoformat(s).replace(tzinfo=LOCAL_TZ)
        t = dt.datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=LOCAL_TZ)
    except (TypeError, ValueError):
        return None


def fetch_calendar(now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Döner: {'next': {...}|None, 'events': [...], 'updated': 'HH:MM', 'source': ...} veya {'err': ...}."""
    global _LAST_GOOD_CALENDAR
    raw, err = _safe_read_json_file(CALENDAR_JSON)
    if err is not None:
        if isinstance(err, FileNotFoundError):
            return {"err": "Takvim dosyası yok"}
        if isinstance(err, json.JSONDecodeError):
            if _LAST_GOOD_CALENDAR is not None:
                res = dict(_LAST_GOOD_CALENDAR)
                res["stale"] = True
                res["stale_file"] = True
                return res
            return {"err": "Takvim okunamadı"}
        log_err("calendar", err)
        return {"err": "Takvim okunamadı"}
    if not isinstance(raw, dict):
        return {"err": "Geçersiz veri"}
    if raw.get("hata"):
        return {"err": "Takvim güncellenemedi"}
    try:
        now = now or dt.datetime.now(LOCAL_TZ)
        upd = _parse_event_time(raw.get("zaman"))
        events = []
        for e in raw.get("etkinlikler") or []:
            if not isinstance(e, dict):
                continue
            start_raw = e.get("bas")
            if isinstance(start_raw, dt.datetime):
                start = start_raw if start_raw.tzinfo else start_raw.replace(tzinfo=LOCAL_TZ)
            else:
                start = _parse_event_time(start_raw)

            end_raw = e.get("bit")
            if isinstance(end_raw, dt.datetime):
                end = end_raw if end_raw.tzinfo else end_raw.replace(tzinfo=LOCAL_TZ)
            else:
                end = _parse_event_time(end_raw)

            all_day = bool(e.get("tum_gun")) or (isinstance(start_raw, str) and len(start_raw) == 10)
            if start is None:
                continue
            if end is None:
                end = (start + dt.timedelta(days=1)) if all_day else (start + dt.timedelta(hours=1))

            if end <= now:
                continue  # geçmiş etkinlik veya geçersiz başlangıç

            events.append({
                "title": str(e.get("baslik") or "(başlıksız)"),
                "start": start,
                "end": end,
                "all_day": all_day,
                "where": str(e.get("yer") or ""),
                "link": str(e.get("link") or ""),
                "now": start <= now < end,
            })
        events.sort(key=lambda x: x["start"])
        timed = [x for x in events if not x["all_day"]]
        nxt = (timed or events or [None])[0]
        res = {
            "next": nxt,
            "events": events,
            "updated": upd.strftime("%H:%M") if upd else "",
            "stale_file": bool(upd and (now - upd).total_seconds() > 3 * 3600),
            "source": "Google Takvim (kişisel 02)",
        }
        _LAST_GOOD_CALENDAR = dict(res)
        return res
    except Exception as exc:
        log_err("calendar_parse", exc)
        return {"err": "Takvim okunamadı"}


def event_when(ev: Any, now: Optional[dt.datetime] = None) -> str:
    """'şimdi', '35 dk sonra', '2 sa 10 dk sonra', 'yarın 09:30', 'Çar 28 Eki', 'bugün', 'bitti'."""
    try:
        if not isinstance(ev, dict):
            return ""
        st = ev.get("start")
        if isinstance(st, str):
            st = _parse_event_time(st)
        if not isinstance(st, dt.datetime):
            return ""
        now = now or dt.datetime.now(LOCAL_TZ)
        if st.tzinfo is None:
            st = st.replace(tzinfo=LOCAL_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=LOCAL_TZ)

        end = ev.get("end")
        if isinstance(end, str):
            end = _parse_event_time(end)
        if isinstance(end, dt.datetime) and end.tzinfo is None:
            end = end.replace(tzinfo=LOCAL_TZ)

        if ev.get("all_day"):
            days = (st.date() - now.date()).days
            days = max(days, 0)
            return "bugün" if days == 0 else ("yarın" if days == 1 else f"{st.day} {TR_MONTHS.get(st.month, '')}")

        # Timed events
        if end and end <= now:
            return "bitti"
        if st <= now:
            return "şimdi"

        days = (st.date() - now.date()).days
        mins = int((st - now).total_seconds() // 60)
        if days == 0 and mins < 60:
            return f"{max(mins, 1)} dk sonra"
        if days == 0 and mins < 6 * 60:
            return f"{mins // 60} sa {mins % 60} dk sonra"
        if days == 0:
            return f"bugün {st:%H:%M}"
        if days == 1:
            return f"yarın {st:%H:%M}"
        return f"{st.day} {TR_MONTHS.get(st.month, '')} {st:%H:%M}"
    except Exception as exc:
        log_err("event_when", exc)
        return ""
