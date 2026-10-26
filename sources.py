"""Data-source module for Şerit. Pure Python, no Qt dependencies."""

import datetime as dt
import json
from pathlib import Path
import time
from typing import Any, Dict, Optional

import httpx
import psutil

CRED_PATH = Path.home() / ".claude" / ".credentials.json"
LOG_PATH = Path("D:/Apps/serit/serit.log")

REFRESH = {
    "claude": 120,
    "fx": 300,
    "wx": 900,
    "sys": 2,
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


def log_err(source: str, exc: Exception) -> None:
    """Log network/source exception without sensitive tokens."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} [{source}] {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def tr_num(s: Any) -> float:
    """Convert Turkish formatted number string (e.g. '6.423,18' or '%0,14') to float."""
    clean = str(s).strip().replace(".", "").replace(",", ".").replace("%", "")
    return float(clean)


def fmt_tr(x: float, dec: int = 2) -> str:
    """Format float into Turkish number format (e.g. 6423.18 -> '6.423,18')."""
    fmt = f"{x:,.{dec}f}"
    return fmt.replace(",", "X").replace(".", ",").replace("X", ".")


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


def fetch_claude() -> Dict[str, Any]:
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
        if resp.status_code != 200:
            return {"err": f"Hata {resp.status_code}"}

        data = resp.json()
        fh = data.get("five_hour") or {}
        sd = data.get("seven_day") or {}
        opus_data = data.get("seven_day_opus")

        opus_val = None
        if isinstance(opus_data, dict):
            opus_val = opus_data.get("utilization")
        elif isinstance(opus_data, (int, float)):
            opus_val = float(opus_data)

        session_val = fh.get("utilization")
        week_val = sd.get("utilization")

        return {
            "session": float(session_val) if session_val is not None else 0.0,
            "session_reset": fh.get("resets_at", ""),
            "week": float(week_val) if week_val is not None else 0.0,
            "week_reset": sd.get("resets_at", ""),
            "opus": opus_val,
            "plan": plan,
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
        usd = j.get("USD") or {}
        eur = j.get("EUR") or {}
        gold = j.get("gram-altin") or {}

        return {
            "usd": tr_num(usd.get("Satış", "0")),
            "usd_chg": tr_num(usd.get("Değişim", "0")),
            "eur": tr_num(eur.get("Satış", "0")),
            "eur_chg": tr_num(eur.get("Değişim", "0")),
            "gold": tr_num(gold.get("Satış", "0")),
            "gold_chg": tr_num(gold.get("Değişim", "0")),
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
        cur = j.get("current") or {}
        daily = j.get("daily") or {}

        code = cur.get("weather_code")
        desc = WMO_DESC.get(code, "Bilinmiyor") if code is not None else "Bilinmiyor"
        icon = WMO_ICON.get(code, "cloud") if code is not None else "cloud"

        max_list = daily.get("temperature_2m_max") or [None]
        min_list = daily.get("temperature_2m_min") or [None]

        return {
            "temp": cur.get("temperature_2m"),
            "feel": cur.get("apparent_temperature"),
            "code": code,
            "desc": desc,
            "icon": icon,
            "max": max_list[0],
            "min": min_list[0],
            "wind": cur.get("wind_speed_10m"),
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
        return {
            "cpu": psutil.cpu_percent(None),
            "ram": vm.percent,
            "ram_used_gb": vm.used / (1024**3),
            "ram_total_gb": vm.total / (1024**3),
            "disk_c": disk.percent,
            "source": "Bu bilgisayar",
        }
    except Exception as exc:
        log_err("sys", exc)
        return {"err": "Bağlantı yok"}


class Store:
    """Holds latest value per key ('claude','fx','wx','sys'), with timestamps and stale caching."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def update(self, key: str, result: Dict[str, Any]) -> None:
        now = time.time()
        prev = self._data.get(key)
        has_err = "err" in result

        if has_err and prev and "err" not in prev:
            prev["stale"] = True
            prev["last_error"] = result["err"]
            return

        entry = dict(result)
        entry["fetched_at"] = now
        entry["stale"] = False
        self._data[key] = entry

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._data.get(key)
