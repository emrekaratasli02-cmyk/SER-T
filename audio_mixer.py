"""audio_mixer.py - Per-application audio mixer backend for Şerit dock.

Provides:
  - list_sessions: list active/inactive per-application audio sessions merged by app.
  - set_session_level: set volume level (0-100) for all sessions of a specific app.
  - set_session_mute: mute or unmute all sessions of a specific app.
  - get_file_description: extract FileDescription resource from PE executables.
  - get_display_name: format user-friendly app/script names.

Rules:
  - All public functions run on a WORKER thread; CoInitializeEx(0x2) is ensured per thread.
  - Never raises unhandled exceptions from public functions; logs throttled errors to LOG_PATH.
  - Excludes sessions whose process has terminated or expired.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import datetime
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Union

import comtypes
import psutil
from pycaw.pycaw import AudioUtilities

from logpath import LOG_PATH

__all__ = [
    "list_sessions",
    "set_session_level",
    "set_session_mute",
    "get_file_description",
    "get_display_name",
    "is_system_sounds_session",
    "is_session_valid",
]

# ==============================================================================
# 0. LOGGING & COM INITIALIZATION
# ==============================================================================

_last_log_msg: str = ""
_last_log_time: float = 0.0
_log_lock = threading.Lock()


def _log(msg: str) -> None:
    """Append a timestamped message to LOG_PATH with 60s duplicate throttle."""
    global _last_log_msg, _last_log_time
    now = time.monotonic()
    with _log_lock:
        if msg == _last_log_msg and (now - _last_log_time) < 60.0:
            return
        _last_log_msg = msg
        _last_log_time = now
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} [audio_mixer] {msg}\n")
    except OSError:
        pass


_tls = threading.local()


def _ensure_com_initialized() -> None:
    """Initialize COM on the calling thread once (safe for thread pool reuse)."""
    if getattr(_tls, "com_initialized", False):
        return
    try:
        # COINIT_APARTMENTTHREADED = 0x2
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        if hr in (0, 1) or (hr & 0xFFFFFFFF) == 0x80010106:
            _tls.com_initialized = True
            return
    except Exception:
        pass
    try:
        comtypes.CoInitialize()
        _tls.com_initialized = True
    except Exception:
        pass


# ==============================================================================
# 1. DISPLAY NAME RESOLUTION & VERSION RESOURCE CACHE
# ==============================================================================

KNOWN_APP_NAMES: Dict[str, str] = {
    "chrome.exe": "Chrome",
    "chrome": "Chrome",
    "msedge.exe": "Edge",
    "msedge": "Edge",
    "spotify.exe": "Spotify",
    "spotify": "Spotify",
    "zoom.exe": "Zoom",
    "zoom": "Zoom",
    "whatsapp.root.exe": "WhatsApp",
    "whatsapp.exe": "WhatsApp",
    "whatsapp": "WhatsApp",
    "discord.exe": "Discord",
    "discord": "Discord",
    "hermes.exe": "Hermes",
    "hermes": "Hermes",
    "teams.exe": "Teams",
    "teams": "Teams",
}

_file_description_cache: Dict[str, str] = {}
_file_desc_lock = threading.Lock()
_proc_meta_cache: Dict[tuple[int, float], tuple[str, str, List[str]]] = {}
_proc_meta_lock = threading.Lock()


def _get_proc_meta(proc: psutil.Process) -> tuple[str, str, List[str]]:
    """Get (name, exe, cmdline) with caching by (pid, create_time)."""
    pid = getattr(proc, "pid", 0)
    try:
        ctime = proc.create_time()
    except Exception:
        ctime = 0.0
    cache_key = (pid, ctime)
    with _proc_meta_lock:
        if cache_key in _proc_meta_cache:
            return _proc_meta_cache[cache_key]

    try:
        pname = proc.name()
    except Exception:
        pname = ""
    try:
        exe_path = proc.exe() or ""
    except Exception:
        exe_path = ""
    try:
        cmdline = proc.cmdline() or []
    except Exception:
        cmdline = []

    meta = (pname, exe_path, cmdline)
    with _proc_meta_lock:
        if len(_proc_meta_cache) > 256:
            _proc_meta_cache.clear()
        _proc_meta_cache[cache_key] = meta
    return meta


def get_file_description(filepath: str) -> str:
    """Extract FileDescription from Win32 version resource via ctypes."""
    if not filepath:
        return ""

    with _file_desc_lock:
        if filepath in _file_description_cache:
            return _file_description_cache[filepath]

    desc = ""
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(filepath, None)
        if size > 0:
            buf = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(filepath, 0, size, buf):
                # 1. Query translation table
                p_trans = ctypes.c_void_p()
                u_len = w.UINT()
                if (
                    version.VerQueryValueW(
                        buf,
                        r"\\VarFileInfo\\Translation",
                        ctypes.byref(p_trans),
                        ctypes.byref(u_len),
                    )
                    and p_trans.value
                    and u_len.value >= 4
                ):
                    count = u_len.value // 4
                    words = ctypes.cast(p_trans, ctypes.POINTER(w.WORD))
                    for i in range(count):
                        lang = words[i * 2]
                        cp = words[i * 2 + 1]
                        for fmt in (f"{lang:04x}{cp:04x}", f"{lang:04X}{cp:04X}"):
                            sub = f"\\\\StringFileInfo\\\\{fmt}\\\\FileDescription"
                            p_val = ctypes.c_wchar_p()
                            val_len = w.UINT()
                            if (
                                version.VerQueryValueW(
                                    buf, sub, ctypes.byref(p_val), ctypes.byref(val_len)
                                )
                                and p_val.value
                            ):
                                desc = p_val.value.strip()
                                break
                        if desc:
                            break

                # 2. Well-known fallback codepages
                if not desc:
                    for cp_hex in (
                        "040904b0",
                        "040904B0",
                        "040904e4",
                        "040904E4",
                        "04090000",
                        "000004b0",
                        "000004B0",
                        "041f04b0",
                        "041F04B0",
                    ):
                        sub = f"\\\\StringFileInfo\\\\{cp_hex}\\\\FileDescription"
                        p_val = ctypes.c_wchar_p()
                        val_len = w.UINT()
                        if (
                            version.VerQueryValueW(
                                buf, sub, ctypes.byref(p_val), ctypes.byref(val_len)
                            )
                            and p_val.value
                        ):
                            desc = p_val.value.strip()
                            break
    except Exception as e:
        _log(f"get_file_description error for {filepath}: {e}")

    with _file_desc_lock:
        _file_description_cache[filepath] = desc
    return desc


def _resolve_python_name(cmdline: Optional[List[str]]) -> str:
    """Identify script from python/pythonw command line arguments."""
    if not cmdline:
        return "Python"

    # Direct match for known Serit scripts
    for arg in cmdline[1:]:
        base = Path(arg).name.lower()
        if base in ("dikte.pyw", "dikte.py"):
            return "Dikte"
        if base in ("serit_v5.pyw", "serit.pyw", "serit_v5.py", "serit.py"):
            return "Şerit"

    # General .py/.pyw file argument
    for arg in cmdline[1:]:
        if arg.startswith("-"):
            continue
        p = Path(arg)
        if p.suffix.lower() in (".py", ".pyw"):
            stem = p.stem
            if stem.lower() == "dikte":
                return "Dikte"
            if stem.lower() in ("serit_v5", "serit"):
                return "Şerit"
            return stem

    # Module run (-m module_name)
    for i, arg in enumerate(cmdline[1:], 1):
        if arg == "-m" and i + 1 < len(cmdline):
            return cmdline[i + 1]

    return "Python"


def get_display_name(
    proc_name: str,
    exe_path: str = "",
    cmdline: Optional[List[str]] = None,
) -> str:
    """Resolve user-facing display name for an audio session."""
    p_lower = proc_name.lower() if proc_name else ""
    if p_lower in ("python.exe", "pythonw.exe", "python", "pythonw"):
        return _resolve_python_name(cmdline)

    if p_lower in KNOWN_APP_NAMES:
        return KNOWN_APP_NAMES[p_lower]

    if exe_path:
        desc = get_file_description(exe_path)
        if desc:
            return desc

    if proc_name:
        stem = Path(proc_name).stem
        if stem.lower() in KNOWN_APP_NAMES:
            return KNOWN_APP_NAMES[stem.lower()]
        return stem.title()

    if exe_path:
        return Path(exe_path).stem.title()

    return "Unknown"


# ==============================================================================
# 2. SESSION VALIDATION & KEY EXTRACTION
# ==============================================================================

def is_system_sounds_session(s: Any) -> bool:
    """Determine whether an AudioSession represents Windows System Sounds."""
    try:
        ctl = getattr(s, "_ctl", None)
        if ctl is not None and hasattr(ctl, "IsSystemSoundsSession"):
            # S_OK = 0 in COM indicates TRUE
            if ctl.IsSystemSoundsSession() == 0:
                return True
    except Exception:
        pass

    if getattr(s, "Process", None) is None:
        dn = getattr(s, "DisplayName", "") or ""
        ident = getattr(s, "Identifier", "") or ""
        pid = getattr(s, "ProcessId", 0)
        if "audiosrv" in dn.lower() or "#%" in ident or pid == 0:
            return True

    return False


def is_session_valid(s: Any) -> bool:
    """Check if session is alive (not expired, process hasn't exited)."""
    if is_system_sounds_session(s):
        return True

    # AudioSessionStateExpired = 2
    if getattr(s, "State", 0) == 2:
        return False

    proc = getattr(s, "Process", None)
    if proc is None:
        return False

    try:
        if not proc.is_running():
            return False
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    except Exception:
        pass

    return True


def get_session_key(s: Any) -> str:
    """Return stable string key (exe lowercase or 'system')."""
    if is_system_sounds_session(s):
        return "system"

    proc = getattr(s, "Process", None)
    if proc is not None:
        pname, exe, _ = _get_proc_meta(proc)
        if pname:
            return pname.lower()
        if exe:
            return Path(exe).name.lower()

    pid = getattr(s, "ProcessId", 0)
    return f"pid_{pid}" if pid else "unknown"


# ==============================================================================
# 3. PUBLIC API
# ==============================================================================

def list_sessions() -> List[Dict[str, Any]]:
    """List audio sessions merged by app key.

    Returns:
        List of dicts:
          - 'key': stable str (exe lowercase or 'system')
          - 'pids': list[int]
          - 'name': display name str
          - 'exe': full exe path str or ''
          - 'level': int 0-100 (max of sessions for this app)
          - 'muted': bool (True only if all sessions of this app are muted)
          - 'active': bool (True if any session is in active playback state)
        Sorted with active sessions first, then alphabetically by display name.
    """
    _ensure_com_initialized()
    try:
        raw_sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        _log(f"GetAllSessions error in list_sessions: {e}")
        return []

    if not raw_sessions:
        return []

    groups: Dict[str, Dict[str, Any]] = {}

    for s in raw_sessions:
        try:
            if not is_session_valid(s):
                continue

            vol_ctl = getattr(s, "SimpleAudioVolume", None)
            if vol_ctl is None:
                continue

            try:
                raw_vol = float(vol_ctl.GetMasterVolume())
                level = max(0, min(100, int(round(raw_vol * 100))))
            except Exception:
                level = 100

            try:
                muted = bool(vol_ctl.GetMute())
            except Exception:
                muted = False

            active = getattr(s, "State", 0) == 1

            if is_system_sounds_session(s):
                key = "system"
                name = "Sistem sesleri"
                exe_path = ""
                pids: List[int] = []
            else:
                proc = getattr(s, "Process", None)
                pname = ""
                exe_path = ""
                cmdline: List[str] = []
                pid = getattr(s, "ProcessId", 0)
                if proc is not None:
                    pname, exe_path, cmdline = _get_proc_meta(proc)
                    if not pid and hasattr(proc, "pid"):
                        pid = proc.pid
                pids = [pid] if pid else []
                key = (
                    pname.lower()
                    if pname
                    else (Path(exe_path).name.lower() if exe_path else f"pid_{pid}")
                )
                name = get_display_name(pname, exe_path, cmdline)

            if key not in groups:
                groups[key] = {
                    "key": key,
                    "pids": list(pids),
                    "name": name,
                    "exe": exe_path,
                    "levels": [level],
                    "mutes": [muted],
                    "actives": [active],
                }
            else:
                g = groups[key]
                for p in pids:
                    if p not in g["pids"]:
                        g["pids"].append(p)
                if not g["exe"] and exe_path:
                    g["exe"] = exe_path
                g["levels"].append(level)
                g["mutes"].append(muted)
                g["actives"].append(active)
        except Exception as err:
            _log(f"Error inspecting audio session: {err}")
            continue

    result: List[Dict[str, Any]] = []
    for g in groups.values():
        result.append({
            "key": g["key"],
            "pids": sorted(g["pids"]),
            "name": g["name"],
            "exe": g["exe"],
            "level": max(g["levels"]) if g["levels"] else 100,
            "muted": all(g["mutes"]) if g["mutes"] else False,
            "active": any(g["actives"]) if g["actives"] else False,
        })

    result.sort(key=lambda item: (not item["active"], item["name"].lower()))
    return result



def _guard_real_audio(what: str) -> None:
    """Testler gerçek sese ASLA dokunamaz (27 Eki 2026: bir test Chrome'u sessize aldı).

    Test altında (pytest veya tests/ klasöründen çalışan betik) gerçek ses yazımı engellenir;
    yalnızca SERIT_ALLOW_REAL_AUDIO=1 açıkça verilirse izin var.
    """
    import os
    try:
        from logpath import is_running_under_test
    except Exception:
        return
    if is_running_under_test() and os.environ.get("SERIT_ALLOW_REAL_AUDIO") != "1":
        raise RuntimeError(f"Test sırasında gerçek ses değiştirilemez: {what}")

def set_session_level(key: str, level: Union[int, float]) -> bool:
    """Set master volume level (0-100) for all sessions of given key.

    Returns True if at least one matching session was updated, False otherwise.
    Never raises unhandled exceptions.
    """
    _guard_real_audio("set_session_level")
    if not isinstance(key, str) or not key.strip():
        return False
    try:
        lvl_num = float(level)
        lvl_num = max(0.0, min(100.0, lvl_num))
        f_level = lvl_num / 100.0
    except (ValueError, TypeError):
        return False

    _ensure_com_initialized()
    target = key.strip().lower()
    updated = False

    try:
        raw_sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        _log(f"GetAllSessions error in set_session_level: {e}")
        return False

    for s in raw_sessions:
        try:
            if not is_session_valid(s):
                continue
            s_key = get_session_key(s)
            matched = (
                s_key == target
                or (s_key.endswith(".exe") and s_key[:-4] == target)
                or (target.endswith(".exe") and target[:-4] == s_key)
            )
            if matched:
                vol_ctl = getattr(s, "SimpleAudioVolume", None)
                if vol_ctl is not None:
                    vol_ctl.SetMasterVolume(f_level, None)
                    updated = True
        except Exception as e:
            _log(f"set_session_level error for key '{key}': {e}")

    return updated


def set_session_mute(key: str, muted: bool) -> bool:
    """Set mute state for all sessions of given key.

    Returns True if at least one matching session was updated, False otherwise.
    Never raises unhandled exceptions.
    """
    _guard_real_audio("set_session_mute")
    if not isinstance(key, str) or not key.strip():
        return False

    _ensure_com_initialized()
    target = key.strip().lower()
    b_mute = 1 if bool(muted) else 0
    updated = False

    try:
        raw_sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        _log(f"GetAllSessions error in set_session_mute: {e}")
        return False

    for s in raw_sessions:
        try:
            if not is_session_valid(s):
                continue
            s_key = get_session_key(s)
            matched = (
                s_key == target
                or (s_key.endswith(".exe") and s_key[:-4] == target)
                or (target.endswith(".exe") and target[:-4] == s_key)
            )
            if matched:
                vol_ctl = getattr(s, "SimpleAudioVolume", None)
                if vol_ctl is not None:
                    vol_ctl.SetMute(b_mute, None)
                    updated = True
        except Exception as e:
            _log(f"set_session_mute error for key '{key}': {e}")

    return updated
