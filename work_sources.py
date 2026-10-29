"""work_sources.py - Read-only, worker-thread-safe data fetchers for Şerit dock cards.

Data fetchers:
1) fetch_mail_waiting: Waiting email summary from Hermes cron scans (IAS, Kişisel, Logaritma).
2) fetch_tasks: Active tasks from Google Tasks (kişisel 02).
3) fetch_antigravity: Antigravity model quota usage and reset windows.

Shared helpers:
- tr_relative_hours(h): '13 g' / '5 sa' / '40 dk'
- tr_days_left(n): 'bugün' / 'yarın' / '4 gün' / 'gecikti 2 gün'
- tr_short_date(date): '31 Eki Cum'
- tr_reset_time(val): '29 Eki Per 16:40'
"""

import datetime as dt
import email.utils
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import sources
except ImportError:
    sources = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available, never raising."""
    if sources is not None and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Path & Environment Defaults (Overridable via env or module vars for tests)
# ---------------------------------------------------------------------------
DEFAULT_HERMES_BASE = Path(os.environ.get("HERMES_BASE", r"C:\Users\Emre Karatasli\AppData\Local\hermes"))
HERMES_PYTHON = Path(os.environ.get("HERMES_PYTHON", r"C:\Users\Emre Karatasli\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"))
SERIT_DIR = Path(os.environ.get("SERIT_DIR", r"D:\Apps\serit"))

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

TR_MONTHS = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
TR_WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

# Account configurations for waiting mail
MAIL_ACCOUNT_CONFIGS = [
    ("ias", "IAS", "ias.json"),
    ("kisisel02", "Kişisel", "kisisel02.json"),
    ("logaritma", "Logaritma", "logaritma.json"),
]


# ---------------------------------------------------------------------------
# Shared Formatting Helpers
# ---------------------------------------------------------------------------
def tr_relative_hours(h: Any) -> str:
    """Format elapsed hours into Turkish relative duration string.

    Examples:
        >= 24 h -> '13 g'
        1..23 h -> '5 sa'
        < 1 h   -> '40 dk'
    """
    if h is None:
        return ""
    try:
        val = float(h)
    except (ValueError, TypeError):
        return ""
    if val >= 24:
        return f"{int(val // 24)} g"
    if val >= 1:
        return f"{int(val)} sa"
    if val > 0:
        return f"{max(1, int(round(val * 60)))} dk"
    return "0 dk"


def tr_days_left(n: Any) -> str:
    """Format days remaining into Turkish relative day label.

    Examples:
        0 -> 'bugün'
        1 -> 'yarın'
        4 -> '4 gün'
        -2 -> 'gecikti 2 gün'
    """
    if n is None:
        return ""
    try:
        val = int(round(float(n)))
    except (ValueError, TypeError):
        return ""
    if val == 0:
        return "bugün"
    if val == 1:
        return "yarın"
    if val > 1:
        return f"{val} gün"
    return f"gecikti {abs(val)} gün"


def tr_short_date(date_val: Union[dt.date, dt.datetime, str, None]) -> str:
    """Format date to Turkish short representation (e.g. '31 Eki Cum')."""
    if date_val is None:
        return ""
    d: Optional[dt.date] = None
    if isinstance(date_val, str):
        clean = date_val.strip()
        if not clean:
            return ""
        try:
            if "T" in clean:
                d = dt.datetime.fromisoformat(clean.replace("Z", "+00:00")).date()
            else:
                d = dt.date.fromisoformat(clean[:10])
        except Exception:
            return clean
    elif isinstance(date_val, dt.datetime):
        d = date_val.date()
    elif isinstance(date_val, dt.date):
        d = date_val

    if d is None:
        return ""
    day = d.day
    m_idx = d.month
    w_idx = d.weekday()
    m_str = TR_MONTHS[m_idx] if 1 <= m_idx <= 12 else str(m_idx)
    w_str = TR_WEEKDAYS[w_idx] if 0 <= w_idx < 7 else ""
    return f"{day} {m_str} {w_str}".strip()


def tr_reset_time(val: Union[dt.datetime, str, None]) -> Optional[str]:
    """Convert UTC or ISO timestamp to local Turkish reset label (e.g. '29 Eki Per 16:40')."""
    if not val:
        return None
    d: Optional[dt.datetime] = None
    if isinstance(val, str):
        try:
            clean = val.replace("Z", "+00:00")
            d = dt.datetime.fromisoformat(clean)
        except Exception:
            return None
    elif isinstance(val, dt.datetime):
        d = val
    if d is None:
        return None

    # Ensure timezone conversion to local time
    if d.tzinfo is None:
        local_d = d.astimezone()
    else:
        local_d = d.astimezone()

    day = local_d.day
    m_idx = local_d.month
    w_idx = local_d.weekday()
    m_str = TR_MONTHS[m_idx] if 1 <= m_idx <= 12 else str(m_idx)
    w_str = TR_WEEKDAYS[w_idx] if 0 <= w_idx < 7 else ""
    time_str = local_d.strftime("%H:%M")
    return f"{day} {m_str} {w_str} {time_str}"


def clean_sender_name(kimden: Any) -> str:
    """Extract display name without email address, or fallback to cleaned address."""
    if not kimden:
        return ""
    text = str(kimden).strip()
    if "<" not in text and "@" not in text:
        return text.strip(" \"'")
    name, addr = email.utils.parseaddr(text)
    clean_name = name.strip(" \"'")
    if clean_name:
        return clean_name
    if "<" in text:
        before = text.split("<")[0].strip(" \"'")
        if before:
            return before
    clean_addr = addr.strip(" \"'")
    if clean_addr:
        return clean_addr
    return text.strip(" \"'")


def shorten_ag_label(raw_label: Any) -> str:
    """Shorten Antigravity model family labels for dock display."""
    s = str(raw_label or "").strip()
    if s == "Claude (Opus/Sonnet)" or s.startswith("Claude ("):
        return "Claude"
    if s in ("Gemini …", "Gemini ...") or s.startswith("Gemini (") or s.startswith("Gemini …") or s.startswith("Gemini ..."):
        return "Gemini"
    # Keep others short (max 24 chars)
    if len(s) > 24:
        return s[:23] + "…"
    return s


# ---------------------------------------------------------------------------
# Automated Mail Filter (Notification / Transactional Email Filtering)
# ---------------------------------------------------------------------------
AUTO_LOCAL_REGEX = re.compile(
    r"^(?:noreply|no-reply|donotreply|do-not-reply|notifications?|mailer-daemon|appleid|accounts?|security|alerts?|newsletter)(?:[-_.+].*)?$",
    re.IGNORECASE,
)

KNOWN_AUTO_ADDRS = {
    "appleid@apple.com",
    "account@nvidia.com",
}

KNOWN_AUTO_DOMAINS = {
    "accounts.google.com",
    "mail.instagram.com",
    "facebookmail.com",
    "linkedin.com",
}


def extract_sender_address(kimden: Any) -> str:
    """Extract clean lowercase email address from sender string."""
    if not kimden:
        return ""
    text = str(kimden).strip()
    _, addr = email.utils.parseaddr(text)
    if addr:
        return addr.strip().lower()
    m = re.search(r"[\w\.-]+@[\w\.-]+", text)
    if m:
        return m.group(0).strip().lower()
    return ""


def is_auto_sender(kimden: Any, ignore_substrings: Optional[List[str]] = None) -> bool:
    """Determine whether an email is an automated notification based on sender address.

    Checks:
    1) Local part matches noreply / no-reply / donotreply / do-not-reply /
       notification(s) / mailer-daemon / appleid / account(s) / security / alerts / newsletter
    2) Known exact addresses/domains (appleid@apple.com, account@nvidia.com,
       accounts.google.com, *.mail.instagram.com, *.facebookmail.com, *.linkedin.com, *@email.*)
    3) Optional user ignore substrings from settings.json ('mail_ignore_senders')

    Preserves human senders (e.g. fle@is-dba.com, hello@team-brain.com,
    hello@lumen-research.com, people at dentsu/havas/integralads).
    """
    addr = extract_sender_address(kimden)
    if not addr:
        return False

    local_part, _, domain = addr.partition("@")

    if AUTO_LOCAL_REGEX.match(local_part):
        return True

    if addr in KNOWN_AUTO_ADDRS:
        return True

    if domain in KNOWN_AUTO_DOMAINS or any(domain.endswith("." + d) for d in KNOWN_AUTO_DOMAINS):
        return True

    if domain.startswith("email.") or domain == "email":
        return True

    if ignore_substrings:
        for s in ignore_substrings:
            if s and str(s).lower() in addr:
                return True

    return False


def _get_mail_ignore_senders() -> List[str]:
    """Read optional 'mail_ignore_senders' list from settings.json (read-only)."""
    try:
        settings_file = SERIT_DIR / "settings.json"
        if settings_file.is_file():
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            val = data.get("mail_ignore_senders")
            if isinstance(val, list):
                return [str(s).strip().lower() for s in val if s]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# 1) fetch_mail_waiting
# ---------------------------------------------------------------------------
_MAIL_CACHE_LOCK = threading.Lock()
_MAIL_CACHE_MTIMES: Dict[str, float] = {}
_MAIL_CACHE_RESULT: Optional[Dict[str, Any]] = None


def fetch_mail_waiting(mail_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Read waiting email summaries from Hermes cron scans.

    Thread-safe, read-only, cached by file mtime.
    Never exposes email summary or body text.
    """
    global _MAIL_CACHE_RESULT, _MAIL_CACHE_MTIMES
    try:
        base_dir = Path(mail_dir) if mail_dir else (DEFAULT_HERMES_BASE / "mail-bekleyen")
        if not base_dir.is_dir():
            return {
                "accounts": [],
                "total_open": 0,
                "hidden_auto": 0,
                "oldest_h": None,
                "scanned_at": None,
                "stale": True,
                "source": "Hermes mail taraması",
                "warnings": [f"Dizin bulunamadı: {base_dir}"],
            }

        # Check mtimes for caching
        tracked_files = [f for _, _, f in MAIL_ACCOUNT_CONFIGS] + ["_durum.json"]
        current_mtimes: Dict[str, float] = {}
        for fname in tracked_files:
            fpath = base_dir / fname
            try:
                current_mtimes[fname] = fpath.stat().st_mtime if fpath.is_file() else -1.0
            except OSError:
                current_mtimes[fname] = -1.0

        with _MAIL_CACHE_LOCK:
            if _MAIL_CACHE_RESULT is not None and current_mtimes == _MAIL_CACHE_MTIMES:
                return _MAIL_CACHE_RESULT.copy()

        accounts: List[Dict[str, Any]] = []
        warnings: List[str] = []
        newest_scan_dt: Optional[dt.datetime] = None
        user_ignores = _get_mail_ignore_senders()

        # Check _durum.json for latest scan timestamp
        durum_file = base_dir / "_durum.json"
        if durum_file.is_file():
            try:
                durum_data = json.loads(durum_file.read_text(encoding="utf-8"))
                zaman_str = durum_data.get("zaman")
                if zaman_str:
                    zaman_dt = dt.datetime.fromisoformat(zaman_str.replace("Z", "+00:00"))
                    newest_scan_dt = zaman_dt
            except Exception as d_exc:
                _log_err("mail_durum_parse", d_exc)

        for key, label, fname in MAIL_ACCOUNT_CONFIGS:
            fpath = base_dir / fname
            if not fpath.is_file():
                warnings.append(f"{label} hesabı dosyası eksik ({fname})")
                continue

            try:
                raw_json = fpath.read_text(encoding="utf-8")
                data = json.loads(raw_json)
            except Exception as f_exc:
                _log_err(f"mail_parse_{key}", f_exc)
                warnings.append(f"{label} dosyası okunamadı")
                continue

            adres = str(data.get("adres") or "").strip()
            olusturma_str = data.get("olusturma")
            scanned_at_iso = None
            if olusturma_str:
                try:
                    scan_dt = dt.datetime.fromisoformat(str(olusturma_str).replace("Z", "+00:00"))
                    local_scan = scan_dt.astimezone()
                    scanned_at_iso = local_scan.isoformat()
                    if newest_scan_dt is None or scan_dt > newest_scan_dt:
                        newest_scan_dt = scan_dt
                except Exception:
                    scanned_at_iso = str(olusturma_str)

            raw_items = data.get("bekleyen") or []
            cleaned_items: List[Dict[str, Any]] = []
            open_count = 0
            auto_count = 0

            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                raw_kimden = it.get("kimden")
                is_auto = is_auto_sender(raw_kimden, user_ignores)
                kapanis_tahmini = bool(it.get("kapanis_tahmini", False))

                if is_auto:
                    auto_count += 1
                elif not kapanis_tahmini:
                    open_count += 1

                try:
                    bekleme_saat = int(it.get("bekleme_saat") or 0)
                except (ValueError, TypeError):
                    bekleme_saat = 0

                thread_id = str(it.get("thread_id") or "").strip()
                url = f"https://mail.google.com/mail/u/?authuser={adres}#all/{thread_id}" if (adres and thread_id) else ""

                # Strictly keep only allowed keys, NEVER ozet or message_id or body
                cleaned_item = {
                    "kimden": clean_sender_name(raw_kimden),
                    "konu": str(it.get("konu") or "").strip(),
                    "bekleme_saat": bekleme_saat,
                    "okunmamis": bool(it.get("okunmamis", False)),
                    "kapanis_tahmini": kapanis_tahmini,
                    "auto": is_auto,
                    "rol": str(it.get("rol") or "").strip(),
                    "thread_id": thread_id,
                    "url": url,
                }
                cleaned_items.append(cleaned_item)

            # Sort items: active open first (not kapanis_tahmini and not auto), then kapanis_tahmini, then auto; by bekleme_saat desc
            cleaned_items.sort(
                key=lambda x: (
                    2 if x["auto"] else (1 if x["kapanis_tahmini"] else 0),
                    -x["bekleme_saat"],
                )
            )

            accounts.append({
                "key": key,
                "label": label,
                "adres": adres,
                "scanned_at": scanned_at_iso,
                "open": open_count,
                "hidden_auto": auto_count,
                "items": cleaned_items,
            })

        total_open = sum(a["open"] for a in accounts)
        total_hidden_auto = sum(a.get("hidden_auto", 0) for a in accounts)

        # Oldest waiting hours among open items (excluding auto and closed)
        open_hours = [
            it["bekleme_saat"]
            for a in accounts
            for it in a["items"]
            if not it.get("kapanis_tahmini") and not it.get("auto")
        ]
        oldest_h = max(open_hours) if open_hours else None

        # Determine overall scanned_at and stale status (> 14 h)
        overall_scanned_iso = newest_scan_dt.astimezone().isoformat() if newest_scan_dt else None
        now_utc = dt.datetime.now(dt.timezone.utc)
        if newest_scan_dt is not None:
            utc_scan = newest_scan_dt if newest_scan_dt.tzinfo else newest_scan_dt.replace(tzinfo=dt.timezone.utc)
            diff_h = (now_utc - utc_scan).total_seconds() / 3600.0
            stale = diff_h > 14.0
        else:
            stale = True

        result: Dict[str, Any] = {
            "accounts": accounts,
            "total_open": total_open,
            "hidden_auto": total_hidden_auto,
            "oldest_h": oldest_h,
            "scanned_at": overall_scanned_iso,
            "stale": stale,
            "source": "Hermes mail taraması",
        }
        if warnings:
            result["warnings"] = warnings

        with _MAIL_CACHE_LOCK:
            _MAIL_CACHE_MTIMES = current_mtimes
            _MAIL_CACHE_RESULT = result

        return result

    except Exception as exc:
        _log_err("fetch_mail_waiting", exc)
        return {"err": "Mail verisi okunamadı"}


# ---------------------------------------------------------------------------
# 2) fetch_tasks
# ---------------------------------------------------------------------------
def fetch_tasks(
    hermes_py: Optional[Union[str, Path]] = None,
    base_dir: Optional[Union[str, Path]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Fetch open tasks from Google Tasks CLI (kişisel 02).

    Runs read-only 'list' command. Never runs 'add' or 'done'.
    Do not print or log task notes.
    """
    try:
        h_py = str(hermes_py or HERMES_PYTHON)
        h_base = Path(base_dir or DEFAULT_HERMES_BASE)
        tasks_script = str(h_base / "scripts" / "google_tasks.py")

        if not Path(h_py).is_file() or not Path(tasks_script).is_file():
            _log_err("fetch_tasks", FileNotFoundError(f"Tasks binary or script missing: {h_py}, {tasks_script}"))
            return {"err": "Google Görevler CLI bulunamadı"}

        env = os.environ.copy()
        env["HERMES_HOME"] = str(h_base / "takvim-02")
        env["PYTHONPATH"] = str(h_base / "hermes-agent")

        # Strictly 'list' only
        cmd = [h_py, tasks_script, "list"]
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        if proc.returncode != 0:
            _log_err("fetch_tasks", RuntimeError(f"Tasks CLI exited with {proc.returncode}"))
            return {"err": "Google Görevler okunamadı"}

        try:
            raw_tasks = json.loads(proc.stdout)
        except json.JSONDecodeError as j_exc:
            _log_err("fetch_tasks_json", j_exc)
            return {"err": "Google Görevler çıktısı bozuk"}

        if not isinstance(raw_tasks, list):
            return {"err": "Google Görevler çıktısı geçersiz"}

        today = dt.date.today()
        items: List[Dict[str, Any]] = []
        open_count = 0

        for t in raw_tasks:
            if not isinstance(t, dict):
                continue

            status = str(t.get("status") or "")
            if status != "completed":
                open_count += 1

            due_raw = t.get("due")
            due_str: Optional[str] = None
            days_left: Optional[int] = None

            if due_raw:
                try:
                    due_clean = str(due_raw).strip()
                    if "T" in due_clean:
                        due_date = dt.datetime.fromisoformat(due_clean.replace("Z", "+00:00")).date()
                    else:
                        due_date = dt.date.fromisoformat(due_clean[:10])
                    due_str = due_date.isoformat()
                    days_left = (due_date - today).days
                except Exception:
                    due_str = None
                    days_left = None

            overdue = bool(days_left is not None and days_left < 0)

            # Extract first line of notes max 60 chars, never log or print notes
            notes_raw = str(t.get("notes") or "")
            first_line = notes_raw.splitlines()[0].strip() if notes_raw else ""
            notes_short = first_line[:60]

            item = {
                "id": str(t.get("id") or ""),
                "title": str(t.get("title") or ""),
                "due": due_str,
                "days_left": days_left,
                "overdue": overdue,
                "notes_short": notes_short,
            }
            items.append(item)

        # Sort: items with due date first (ascending), then None due date, then title
        def _sort_key(it: Dict[str, Any]) -> Tuple[int, str, str]:
            due_val = it.get("due")
            return (1 if due_val is None else 0, due_val or "", (it.get("title") or "").lower())

        items.sort(key=_sort_key)

        # First item with a due date
        next_item = next((it for it in items if it.get("due") is not None), None)

        now_local = dt.datetime.now().astimezone().isoformat()
        return {
            "items": items,
            "open": open_count,
            "next": next_item,
            "fetched_at": now_local,
            "source": "Google Görevler (02)",
            "url": "https://tasks.google.com/",
        }

    except subprocess.TimeoutExpired as t_exc:
        _log_err("fetch_tasks_timeout", t_exc)
        return {"err": "Google Görevler zaman aşımı"}
    except Exception as exc:
        _log_err("fetch_tasks", exc)
        return {"err": "Google Görevler okunamadı"}


# ---------------------------------------------------------------------------
# 3) fetch_antigravity
# ---------------------------------------------------------------------------
def _argon_group() -> Optional[Dict[str, Any]]:
    """Argon grubunu (ag_local) fetch_antigravity grup biçimine çevirir; okuma yoksa None."""
    try:
        import ag_local
        g = ag_local.fetch_argon()
    except Exception as exc:
        _log_err("fetch_argon", exc)
        return None
    if not g:
        return None
    reset_at_iso = None
    reset_tr_str = None
    if g.get("reset_at"):
        try:
            reset_dt = dt.datetime.fromisoformat(str(g["reset_at"]).replace("Z", "+00:00"))
            reset_at_iso = reset_dt.astimezone().isoformat()
            reset_tr_str = tr_reset_time(reset_dt)
        except Exception:
            reset_at_iso = None
    used = g.get("used")
    return {
        "label": str(g.get("label") or "Argon"),
        "used": None if used is None else max(0.0, min(100.0, round(float(used), 1))),
        "reset_at": reset_at_iso,
        "reset_tr": reset_tr_str,
        "stale": bool(g.get("stale")),
    }


def fetch_antigravity(
    hermes_py: Optional[Union[str, Path]] = None,
    tool_script: Optional[Union[str, Path]] = None,
    timeout: int = 40,
    local_argon: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fetch Antigravity model quotas and reset windows.

    Runs tools/ag_quota.py with Hermes Python. v24: Gemini 4 Argon is not in the account model list,
    so its quota is read from the running Antigravity app (ag_local) and appended as an "Argon" group.
    local_argon=None -> on, except under tests (keeps fixtures deterministic).
    """
    try:
        h_py = str(hermes_py or HERMES_PYTHON)
        script = str(tool_script or (SERIT_DIR / "tools" / "ag_quota.py"))

        if not Path(h_py).is_file() or not Path(script).is_file():
            _log_err("fetch_antigravity", FileNotFoundError(f"AG binary or helper script missing: {h_py}, {script}"))
            return {"err": "Antigravity okunamadı"}

        cmd = [h_py, script]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        if proc.returncode != 0:
            _log_err("fetch_antigravity", RuntimeError(f"ag_quota.py exited with {proc.returncode}"))
            return {"err": "Antigravity okunamadı"}

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as j_exc:
            _log_err("fetch_antigravity_json", j_exc)
            return {"err": "Antigravity okunamadı"}

        if not isinstance(data, dict) or not data.get("available"):
            return {"err": "Antigravity okunamadı"}

        raw_windows = data.get("windows") or []
        groups: List[Dict[str, Any]] = []

        for w in raw_windows:
            if not isinstance(w, dict):
                continue
            lbl = shorten_ag_label(w.get("label"))
            try:
                used = float(w.get("used_percent") or 0.0)
                used = max(0.0, min(100.0, round(used, 1)))
            except (ValueError, TypeError):
                used = 0.0

            reset_raw = w.get("reset_at")
            reset_at_iso = None
            reset_tr_str = None
            if reset_raw:
                try:
                    reset_clean = str(reset_raw).replace("Z", "+00:00")
                    reset_dt = dt.datetime.fromisoformat(reset_clean)
                    reset_at_iso = reset_dt.astimezone().isoformat()
                    reset_tr_str = tr_reset_time(reset_dt)
                except Exception:
                    reset_at_iso = None
                    reset_tr_str = None

            groups.append({
                "label": lbl,
                "used": used,
                "reset_at": reset_at_iso,
                "reset_tr": reset_tr_str,
            })

        if local_argon is None:
            try:
                import logpath
                local_argon = not logpath.is_running_under_test()
            except Exception:
                local_argon = False
        if local_argon:
            argon = _argon_group()
            if argon:
                groups.append(argon)

        now_local = dt.datetime.now().astimezone().isoformat()
        return {
            "groups": groups,
            "fetched_at": now_local,
            "source": "Antigravity",
        }

    except subprocess.TimeoutExpired as t_exc:
        _log_err("fetch_antigravity_timeout", t_exc)
        return {"err": "Antigravity okunamadı"}
    except Exception as exc:
        _log_err("fetch_antigravity", exc)
        return {"err": "Antigravity okunamadı"}
