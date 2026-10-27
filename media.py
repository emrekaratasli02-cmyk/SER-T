"""media.py - Volume control, now-playing heuristics, media keys, and glass drawing for Şerit dock.

Provides:
  1. Core Audio master volume control via pycaw (get_volume, set_volume, toggle_mute, list_output_devices).
  2. Hardware media key dispatch via Win32 SendInput (send_media_key).
  3. Now-playing detection without WinRT via window title heuristics & Core Audio session activity (now_playing).
  4. Design-system matched QPainter drawing primitives (draw_volume_chip, draw_media_chip, draw_volume_slider_panel).

Rules:
  - Calls must happen on the UI thread (CoInitialize invoked per COM call).
  - Never raises unhandled exceptions from public functions; logs to D:/Apps/serit/serit.log.
  - Title parsing is a heuristic; WinRT GSMTC would be the robust path if 'winrt-Windows.Media.Control'
    were installed. An optional import re
import detects WinRT if installed, otherwise safely falls back.
"""

from __future__ import annotations

import ctypes
import re
import ctypes.wintypes as w
import datetime
import os
import threading
import time
from typing import Dict, List, Optional, Tuple, Union

import comtypes
from pycaw.constants import AudioDeviceState
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

import theme
import winapi

__all__ = [
    # Volume control
    "get_volume",
    "set_volume",
    "toggle_mute",
    "list_output_devices",
    # Media keys
    "send_media_key",
    "INPUT",
    "KEYBDINPUT",
    # Now playing & audio sessions
    "now_playing",
    "parse_media_title",
    "get_active_audio_sessions",
    # Drawing helpers
    "draw_volume_chip",
    "draw_media_chip",
    "draw_volume_slider_panel",
]

# ==============================================================================
# 0. LOGGING & CONSTANTS
# ==============================================================================

from logpath import LOG_PATH

_last_log_msg: str = ""
_last_log_time: float = 0.0
_log_lock = threading.Lock()


def _log(msg: str) -> None:
    """Append a timestamped message to D:/Apps/serit/serit.log with 60s duplicate throttle."""
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
            f.write(f"{now_str} [media] {msg}\n")
    except OSError:
        pass


# ==============================================================================
# 1. WIN32 INPUT STRUCTURES & MEDIA KEYS
# ==============================================================================

user32 = ctypes.windll.user32

ULONG_PTR = getattr(w, "ULONG_PTR", ctypes.c_size_t)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", w.DWORD),
        ("wParamL", w.WORD),
        ("wParamH", w.WORD),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", w.DWORD),
        ("union", _INPUT_UNION),
    ]


INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT

VK_KEY_MAP: Dict[str, int] = {
    "playpause": VK_MEDIA_PLAY_PAUSE,
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "next_track": VK_MEDIA_NEXT_TRACK,
    "prev": VK_MEDIA_PREV_TRACK,
    "prev_track": VK_MEDIA_PREV_TRACK,
    "previous": VK_MEDIA_PREV_TRACK,
}


def send_media_key(key: str) -> bool:
    """Send a hardware media key press (keydown + keyup) via SendInput.

    Supported keys:
      'playpause' (0xB3), 'next' (0xB0), 'prev' (0xB1), plus aliases.

    Returns:
      True if SendInput accepted both inputs, False otherwise.
    """
    try:
        norm = key.strip().lower().replace("-", "_")
        vk = VK_KEY_MAP.get(norm)
        if vk is None:
            _log(f"send_media_key: unsupported key '{key}'")
            return False

        inputs = (INPUT * 2)(
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=vk,
                        wScan=0,
                        dwFlags=KEYEVENTF_EXTENDEDKEY,
                        time=0,
                        dwExtraInfo=0,
                    )
                ),
            ),
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=vk,
                        wScan=0,
                        dwFlags=KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=0,
                    )
                ),
            ),
        )
        sent = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        if sent != 2:
            _log(f"send_media_key: SendInput delivered {sent}/2 events")
            return False
        return True
    except Exception as e:
        _log(f"send_media_key error for key '{key}': {e}")
        return False


# ==============================================================================
# 2. CORE AUDIO VOLUME CONTROL (pycaw)
# ==============================================================================

_tls = threading.local()


def _ensure_com_initialized() -> None:
    """Initialize COM on the calling thread once (safe for ThreadPoolExecutor reuse)."""
    if getattr(_tls, "com_initialized", False):
        return
    try:
        # COINIT_APARTMENTTHREADED = 0x2: comtypes ile aynı kip (MTA seçilince comtypes importu RPC_E_CHANGED_MODE ile çöküyordu)
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        # S_OK = 0, S_FALSE = 1, RPC_E_CHANGED_MODE = 0x80010106
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


def _get_endpoint() -> Tuple[Optional[IAudioEndpointVolume], str]:
    """Retrieve or re-acquire the default render endpoint volume interface.

    Thread-safe: caches endpoint per thread to avoid cross-apartment COM violations.
    """
    _ensure_com_initialized()
    cached_endpoint = getattr(_tls, "cached_endpoint", None)
    cached_device_name = getattr(_tls, "cached_device_name", "")

    if cached_endpoint is not None:
        try:
            # Probe endpoint to verify validity
            cached_endpoint.GetMute()
            return cached_endpoint, cached_device_name
        except Exception as err:
            _log(f"Cached audio endpoint stale, re-acquiring: {err}")
            _tls.cached_endpoint = None
            _tls.cached_device_name = ""

    try:
        speakers = AudioUtilities.GetSpeakers()
        if speakers is None:
            return None, "Default Audio"
        dev_name = getattr(speakers, "FriendlyName", "Speakers")
        endpoint = speakers.EndpointVolume
        _tls.cached_endpoint = endpoint
        _tls.cached_device_name = dev_name
        return endpoint, dev_name
    except Exception as e:
        _log(f"_get_endpoint error: {e}")
        return None, "Default Audio"


def get_volume() -> Dict[str, Union[int, bool, str]]:
    """Return current master volume level, mute state, and friendly device name.

    Returns:
      {'level': int (0-100), 'muted': bool, 'device': str}
    """
    endpoint, dev_name = _get_endpoint()
    if endpoint is None:
        return {"level": 0, "muted": False, "device": dev_name or "Default Audio"}
    try:
        muted = bool(endpoint.GetMute())
        scalar = float(endpoint.GetMasterVolumeLevelScalar())
        level = int(round(scalar * 100.0))
        return {
            "level": max(0, min(100, level)),
            "muted": muted,
            "device": dev_name,
        }
    except Exception as e:
        _log(f"get_volume error: {e}")
        return {"level": 0, "muted": False, "device": dev_name or "Default Audio"}



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

def set_volume(level: Union[int, float]) -> bool:
    """Set master volume level scalar (0 to 100).

    Returns:
      True if successful, False otherwise.
    """
    _guard_real_audio("set_volume")
    endpoint, _ = _get_endpoint()
    if endpoint is None:
        return False
    try:
        clamped = max(0.0, min(100.0, float(level)))
        scalar = clamped / 100.0
        endpoint.SetMasterVolumeLevelScalar(scalar, None)
        return True
    except Exception as e:
        _log(f"set_volume error for level {level}: {e}")
        return False


def toggle_mute() -> bool:
    """Toggle master mute state on the default audio endpoint.

    Returns:
      The new muted state (True = muted, False = unmuted).
    """
    _guard_real_audio("toggle_mute")
    endpoint, _ = _get_endpoint()
    if endpoint is None:
        return False
    try:
        current = bool(endpoint.GetMute())
        new_state = 0 if current else 1
        endpoint.SetMute(new_state, None)
        return bool(new_state)
    except Exception as e:
        _log(f"toggle_mute error: {e}")
        return False


def list_output_devices(active_only: bool = True) -> List[Dict[str, Union[str, bool]]]:
    """List audio output (render) endpoints.

    Parameters:
      active_only: If True, only return currently active devices.

    Returns:
      List of dicts: [{'id': str, 'name': str, 'default': bool}]
    """
    devices: List[Dict[str, Union[str, bool]]] = []
    try:
        _ensure_com_initialized()

        speakers = AudioUtilities.GetSpeakers()
        default_id = getattr(speakers, "id", "") if speakers else ""

        for dev in AudioUtilities.GetAllDevices():
            dev_id = getattr(dev, "id", "")
            # Windows Core Audio render endpoints start with '{0.0.0.'
            if not dev_id.startswith("{0.0.0."):
                continue

            state = getattr(dev, "state", None)
            is_active = (state == AudioDeviceState.Active)
            if active_only and not is_active:
                continue

            name = getattr(dev, "FriendlyName", "Audio Device")
            devices.append({
                "id": dev_id,
                "name": name,
                "default": (dev_id == default_id),
            })
    except Exception as e:
        _log(f"list_output_devices error: {e}")
    return devices


# ==============================================================================
# 3. NOW PLAYING & AUDIO SESSION DETECTION
# ==============================================================================
# Optional WinRT GSMTC (Global System Media Transport Controls) import.
# Note: WinRT GSMTC is the robust, official Windows 10/11 API for reading media
# metadata (track, artist, album art, playback status) across all registered
# media apps without title scraping heuristics.
# It requires the 'winrt-Windows.Media.Control' package. If installed in the
# future, media.py can bind to it. In this environment, we gracefully fall back
# to window title parsing + pycaw audio session activity.
try:
    from winrt.windows.media.control import (  # type: ignore
        GlobalSystemMediaTransportControlsSessionManager as _WinrtMediaManager,
    )
    _HAS_WINRT = True
except ImportError:
    _WinrtMediaManager = None
    _HAS_WINRT = False

_WINRT_STUCK = None  # takılı kalan son WinRT iş parçacığı (birikmeyi önlemek için)
_cached_winrt_mgr = None
# 26 Eki 2026: sorgu artık sources.fetch_media ile arka plan havuzunda çalışıyor (UI beklemiyor);
# önbellekli yöneticiyle 15 denemede 2-65 ms, zaman aşımı yok. Bu yüzden yeniden açıldı.
_WINRT_NOW_PLAYING_ENABLED = True



def timeline_now(position, start_time, end_time, last_updated, playing: bool,
                 now_utc: Optional[datetime.datetime] = None) -> Tuple[Optional[float], Optional[float]]:
    """WinRT zaman çizelgesini 'şu an'a çevir: (konum_sn, süre_sn).

    Windows konumu SON GÜNCELLEME anındaki haliyle verir (27 Eki 2026 ölçümü: konum 3:03,
    last_updated 10 dk önce). Çalıyorsa geçen süre eklenir; süre bilinmiyorsa (0) None döner,
    uydurma ilerleme gösterilmez.
    """
    def secs(td) -> Optional[float]:
        return float(td.total_seconds()) if td is not None and hasattr(td, "total_seconds") else None
    start = secs(start_time) or 0.0
    end = secs(end_time)
    pos = secs(position)
    dur = (end - start) if end is not None else None
    if dur is None or dur <= 0.0:
        return (None, None)
    if pos is None:
        return (None, dur)
    pos -= start
    if playing and isinstance(last_updated, datetime.datetime) and last_updated.year > 1601:
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        lu = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=datetime.timezone.utc)
        pos += max(0.0, (now - lu).total_seconds())
    return (min(max(0.0, pos), dur), dur)

def clean_media_title(title: str) -> str:
    """Tarayıcı sekme başlığını okunur hale getirir.
    'The Mentalist 2. Sezon 17. Bölüm izle | Hdfilmcehennemi' -> 'The Mentalist · 2. Sezon 17. Bölüm'."""
    import re
    t = (title or "").strip()
    # ' | Site', ' - Site', ' – Site' gibi son ekleri at (yalnızca son ayırıcıdan sonrası kısa ise)
    for sep in (" | ", " – ", " — ", " - "):
        if sep in t:
            head, tail = t.rsplit(sep, 1)
            if head and len(tail) <= 40:
                t = head.strip()
    t = re.sub(r"\s+(izle|full hd izle|hd izle|online izle)$", "", t, flags=re.IGNORECASE).strip()
    m = re.match(r"^(.*?)\s+(\d+\.\s*Sezon\s+\d+\.\s*Bölüm)$", t, flags=re.IGNORECASE)
    if m and m.group(1):
        t = f"{m.group(1).strip()} · {m.group(2)}"
    return t or (title or "").strip()
_WINRT_APP_NAMES = {"chrome": "Chrome", "msedge": "Edge", "spotify": "Spotify", "firefox": "Firefox"}


def _now_playing_winrt() -> Optional[Dict[str, object]]:
    """Windows medya oturumundan (GSMTC) çalan parçayı okur. Arka sekmede çalan YouTube'u da görür.
    Döner: dict | None (oturum yok) | {'_fail': True} (WinRT hatası -> başlık yöntemine düş)."""
    if not _HAS_WINRT or not _WINRT_NOW_PLAYING_ENABLED:
        return {"_fail": True}
    import asyncio

    async def _read():
        global _cached_winrt_mgr
        if _WinrtMediaManager is None:
            return None
        mgr = _cached_winrt_mgr
        if mgr is None:
            mgr = await _WinrtMediaManager.request_async()
            _cached_winrt_mgr = mgr
        try:
            s = mgr.get_current_session()
        except Exception:
            _cached_winrt_mgr = None
            mgr = await _WinrtMediaManager.request_async()
            _cached_winrt_mgr = mgr
            s = mgr.get_current_session()
        if s is None:
            return None
        props = await s.try_get_media_properties_async()
        status = int(s.get_playback_info().playback_status)  # 4 = çalıyor, 5 = duraklatıldı
        aumid = s.source_app_user_model_id or ""
        key = aumid.lower().split("!")[0].split(".")[0].replace(".exe", "")
        title = (props.title or "").strip()
        if not title:
            return None
        raw_artist = (props.artist or "").strip()
        # Web video/yayın adreslerini (hdfilmcehennemi, .com, http vb.) temizle
        art_lower = raw_artist.lower()
        if any(art_lower.startswith(x) for x in ("http", "www.")) or any(x in art_lower for x in (".com", ".net", ".org", "hdfilm", ".me", ".tv")):
            cleaned_artist = "Web Yayını"
        elif not raw_artist:
            cleaned_artist = "Çalıyor"
        else:
            cleaned_artist = raw_artist

        pos_s: Optional[float] = None
        dur_s: Optional[float] = None
        try:
            tl = s.get_timeline_properties()
            if tl is not None:
                pos_s, dur_s = timeline_now(
                    getattr(tl, "position", None), getattr(tl, "start_time", None),
                    getattr(tl, "end_time", None), getattr(tl, "last_updated_time", None),
                    playing=(status == 4))
        except Exception as tl_exc:
            _log(f"timeline read: {tl_exc}")

        return {
            "title": clean_media_title(title),
            "artist": cleaned_artist,
            "app": _WINRT_APP_NAMES.get(key, aumid.split("!")[0] or "Medya"),
            "exe": aumid,
            "playing": status == 4,
            "status": status,
            "session_exes": [],
            "source": "Windows medya oturumu",
            "position_s": pos_s,
            "duration_s": dur_s,
            "updated_at": time.monotonic(),
        }

    # WinRT bazen hiç dönmüyor (açılışta bar'ı kilitliyordu): ayrı iş parçacığında, 1.5 sn sınırla çalıştır.
    import threading
    global _WINRT_STUCK
    if _WINRT_STUCK is not None and _WINRT_STUCK.is_alive():
        return {"_fail": True}  # önceki çağrı hâlâ takılı: yeni iş parçacığı açma, başlık yöntemine düş
    box: Dict[str, object] = {}

    def _worker() -> None:
        try:
            box["r"] = asyncio.run(_read())
        except Exception as exc:  # WinRT/COM hatası: çökme yok, yedek yönteme düş
            box["e"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(1.5)
    if t.is_alive():
        _WINRT_STUCK = t
        _log("now_playing winrt: zaman aşımı (1.5 sn)")
        return {"_fail": True}
    if "e" in box:
        exc = box["e"]
        _log(f"now_playing winrt: {type(exc).__name__}: {exc}")
        return {"_fail": True}
    return box.get("r")  # type: ignore[return-value]


def media_control(action: str) -> bool:
    """Oynat/duraklat/ileri/geri: önce Windows medya oturumuna doğrudan komut, olmazsa medya tuşu."""
    _ensure_com_initialized()
    if _HAS_WINRT and _WinrtMediaManager is not None:
        import asyncio

        async def _do():
            global _cached_winrt_mgr
            mgr = _cached_winrt_mgr
            if mgr is None:
                assert _WinrtMediaManager is not None
                mgr = await _WinrtMediaManager.request_async()
                _cached_winrt_mgr = mgr
            s = mgr.get_current_session()
            if s is None:
                return False
            fn = {"playpause": s.try_toggle_play_pause_async, "next": s.try_skip_next_async,
                  "prev": s.try_skip_previous_async}.get(action)
            return bool(await fn()) if fn else False

        import threading
        box: Dict[str, object] = {}

        def _worker() -> None:
            try:
                box["r"] = asyncio.run(_do())
            except Exception as exc:
                box["e"] = exc

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(1.5)
        if t.is_alive():
            _log("media_control winrt: zaman aşımı (1.5 sn)")
        elif "e" in box:
            exc = box["e"]
            _log(f"media_control winrt: {type(exc).__name__}: {exc}")
        elif box.get("r"):
            return True
    return send_media_key(action)

_BROWSER_SUFFIXES = [
    " - Google Chrome",
    " - Microsoft Edge",
    " — Mozilla Firefox",
    " - Mozilla Firefox",
    " - Brave",
    " - Opera",
    " - Zen Browser",
    " - Vivaldi",
]


def parse_media_title(title: str, exe: str = "") -> Optional[Dict[str, str]]:
    """Parse media information from a window title and executable path.

    Handles:
      - Spotify desktop: 'Artist - Song' (exe Spotify.exe; 'Spotify'/'Spotify Premium' -> None)
      - YouTube in browsers: '<title> - YouTube - Google Chrome' -> app 'YouTube'
      - YouTube Music: '<title> - YouTube Music - ...' -> app 'YouTube Music'

    Returns:
      {'title': str, 'artist': str, 'app': str, 'exe': str} or None.
    """
    if not title:
        return None

    t = title.strip()
    if not t:
        return None

    exe_name = os.path.basename(exe).lower() if exe else ""

    # 1. Spotify desktop client
    if exe_name == "spotify.exe" or "spotify" in exe_name:
        if t in ("Spotify", "Spotify Premium", "Spotify Free", "Advertisement"):
            return None
        if " - " in t:
            parts = t.split(" - ", 1)
            artist = parts[0].strip()
            song_title = parts[1].strip()
            return {
                "title": song_title,
                "artist": artist,
                "app": "Spotify",
                "exe": exe or "Spotify.exe",
            }
        return {
            "title": t,
            "artist": "Spotify",
            "app": "Spotify",
            "exe": exe or "Spotify.exe",
        }

    # 2. Browser window titles
    raw = t
    for sfx in _BROWSER_SUFFIXES:
        if raw.endswith(sfx):
            raw = raw[: -len(sfx)].strip()
            break

    # YouTube güncel başlıkları " | YouTube Music" / " | YouTube" ayıracı da kullanıyor
    for sep in (" | YouTube Music", " | YouTube"):
        if raw.endswith(sep):
            raw = raw[: -len(sep)] + sep.replace(" | ", " - ")
            break

    # 2a. YouTube Music
    if raw.endswith(" - YouTube Music"):
        body = raw[: -len(" - YouTube Music")].strip()
        if not body:
            return None
        if " - " in body:
            parts = body.split(" - ", 1)
            return {
                "title": parts[0].strip(),
                "artist": parts[1].strip(),
                "app": "YouTube Music",
                "exe": exe,
            }
        return {
            "title": body,
            "artist": "YouTube Music",
            "app": "YouTube Music",
            "exe": exe,
        }
    elif raw == "YouTube Music":
        return None

    # 2b. YouTube
    if raw.endswith(" - YouTube"):
        body = raw[: -len(" - YouTube")].strip()
        if not body:
            return None
        return {
            "title": body,
            "artist": "YouTube",
            "app": "YouTube",
            "exe": exe,
        }
    elif raw == "YouTube":
        return None

    return None


def get_active_audio_sessions() -> List[str]:
    """Return a list of executable names currently actively producing audio.

    Uses pycaw AudioSessionManager (State == 1 indicates active playback).
    """
    active_exes: List[str] = []
    try:
        _ensure_com_initialized()

        sessions = AudioUtilities.GetAllSessions()
        for s in sessions:
            try:
                # State 1 is AudioSessionStateActive
                if getattr(s, "State", 0) == 1 and s.Process:
                    name = s.Process.name()
                    if name and name not in active_exes:
                        active_exes.append(name)
            except Exception:
                pass
    except Exception as e:
        _log(f"get_active_audio_sessions error: {e}")
    return active_exes


def now_playing() -> Optional[Dict[str, Union[str, bool, List[str]]]]:
    """Determine currently playing media without WinRT via heuristics.

    Inspects top-level window titles (via winapi.list_windows()) and Core Audio
    active sessions (via pycaw).

    Returns:
      {
        'title': str,
        'artist': str,
        'app': str,
        'exe': str,
        'playing': bool,
        'session_exes': list[str]
      } or None if no media window detected.
    """
    w = _now_playing_winrt()
    if not (isinstance(w, dict) and w.get("_fail")):
        return w  # Windows medya oturumu: güvenilir yol (None = çalan yok)
    try:
        active_sessions = get_active_audio_sessions()
        active_sessions_lower = [e.lower() for e in active_sessions]

        windows = winapi.list_windows()
        best_candidate: Optional[Dict[str, str]] = None
        best_playing: bool = False

        for w_item in windows:
            title = w_item.get("title", "")
            exe = w_item.get("exe", "")
            parsed = parse_media_title(title, exe)
            if parsed is None:
                continue

            target_exe = os.path.basename(parsed.get("exe", "")).lower()
            is_producing_audio = target_exe in active_sessions_lower

            # If actively producing audio, prioritize immediately
            if is_producing_audio:
                return {
                    "title": parsed["title"],
                    "artist": parsed["artist"],
                    "app": parsed["app"],
                    "exe": parsed["exe"],
                    "playing": True,
                    "session_exes": active_sessions,
                }

            # Otherwise save the topmost media window candidate
            if best_candidate is None:
                best_candidate = parsed
                best_playing = False

        if best_candidate is not None:
            return {
                "title": best_candidate["title"],
                "artist": best_candidate["artist"],
                "app": best_candidate["app"],
                "exe": best_candidate["exe"],
                "playing": best_playing,
                "session_exes": active_sessions,
            }

        return None
    except Exception as e:
        _log(f"now_playing error: {e}")
        return None


# ==============================================================================
# 4. PURE DRAWING PRIMITIVES (Matching theme.py)
# ==============================================================================


def draw_volume_chip(
    p: QPainter,
    rect: QRectF,
    level: float,
    muted: bool,
    hover_t: float = 0.0,
) -> None:
    """Draw a glass volume chip with speaker glyph, waves, and level ring.

    Elements:
      - Glass capsule styling with hover fill overlay.
      - Vector speaker cone and horn drawn via QPainterPath.
      - 0 to 3 sound waves matching volume level (or muted slash/cross).
      - Calibrated mini ring gauge on right with exact percentage readout.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # 1. Hover overlay
    eff_hover = max(0.0, min(1.0, hover_t))
    if eff_hover > 0.0:
        h_col = QColor(
            theme.COLOR_CHIP_HOVER.red(),
            theme.COLOR_CHIP_HOVER.green(),
            theme.COLOR_CHIP_HOVER.blue(),
            int(theme.COLOR_CHIP_HOVER.alpha() * eff_hover),
        )
        p.fillPath(theme.rounded_path(rect, theme.CHIP_RADIUS), h_col)

    cy = rect.center().y()
    val = max(0.0, min(100.0, float(level)))

    # 2. Speaker Glyph Geometry
    # Base center for speaker
    sx = rect.left() + 17.5

    cone_path = QPainterPath()
    # Back box
    cone_path.addRect(QRectF(sx - 6.5, cy - 3.2, 3.2, 6.4))
    # Flare / horn
    horn = QPainterPath()
    horn.moveTo(sx - 3.3, cy - 3.2)
    horn.lineTo(sx - 0.2, cy - 7.0)
    horn.lineTo(sx - 0.2, cy + 7.0)
    horn.lineTo(sx - 3.3, cy + 3.2)
    horn.closeSubpath()
    speaker_path = cone_path.united(horn)

    p.setPen(Qt.NoPen)
    p.setBrush(theme.COLOR_TEXT_MUTED if muted else theme.COLOR_TEXT_PRIMARY)
    p.drawPath(speaker_path)

    # 3. Sound Waves or Muted Diagonal Slash
    if muted:
        # Elegant diagonal slash across the speaker body (macOS / Windows 11 style)
        p.setPen(QPen(theme.COLOR_ALERT_CRIT, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(sx - 7.5, cy + 6.5), QPointF(sx + 3.0, cy - 6.5))
    else:
        # 0-3 waves depending on volume level
        # Level 0: 0 waves
        # 1-33: 1 wave
        # 34-66: 2 waves
        # 67-100: 3 waves
        num_active = 0
        if val > 66.0:
            num_active = 3
        elif val > 33.0:
            num_active = 2
        elif val > 0.0:
            num_active = 1

        wave_radii = [4.5, 8.0, 11.5]
        for idx, r in enumerate(wave_radii):
            is_active = idx < num_active
            pen_col = (
                theme.COLOR_TEXT_PRIMARY
                if is_active
                else QColor(255, 255, 255, 28)
            )
            pen_w = 1.4 if is_active else 1.0
            p.setPen(QPen(pen_col, pen_w, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)

            arc_rect = QRectF(sx - 0.8 - r, cy - r, 2.0 * r, 2.0 * r)
            # Draw an arc opening to the right: -35 deg to +35 deg
            p.drawArc(arc_rect, -35 * 16, 70 * 16)

    # 4. Small Level Ring Gauge on right side
    rx = rect.right() - 20.0
    ring_size = 24.0
    ring_stroke = 2.4
    ring_r = (ring_size - ring_stroke) / 2.0
    arc_rect = QRectF(rx - ring_r, cy - ring_r, 2.0 * ring_r, 2.0 * ring_r)

    # Track
    p.setPen(QPen(theme.COLOR_RING_TRACK, ring_stroke, Qt.SolidLine, Qt.FlatCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(arc_rect)

    # Foreground Arc
    if not muted and val > 0.0:
        fg_col = theme.COLOR_CPU  # ses için uyarı rengi yok: %100 ses hata değil
        p.setPen(QPen(fg_col, ring_stroke, Qt.SolidLine, Qt.RoundCap))
        span = -int(round((val / 100.0) * 360.0 * 16.0))
        p.drawArc(arc_rect, 90 * 16, span)

    # Readout text
    readout = "0" if muted else f"{int(round(val))}"
    readout_size = 8.5 if len(readout) >= 3 else 9.5
    f_num = theme.make_font(readout_size, QFont.Weight.Bold, tabular=True)
    p.setFont(f_num)
    p.setPen(theme.COLOR_TEXT_MUTED if muted else theme.COLOR_TEXT_PRIMARY)
    text_rect = QRectF(rx - ring_r, cy - ring_r - 0.5, 2.0 * ring_r, 2.0 * ring_r)
    p.drawText(text_rect, Qt.AlignCenter, readout)

    p.restore()


def draw_media_chip(
    p: QPainter,
    rect: QRectF,
    info: Optional[Dict[str, Union[str, bool, List[str]]]],
    playing: bool,
    hover_t: float = 0.0,
) -> Dict[str, QRectF]:
    """Draw a media player chip with app badge, track details, and control buttons.

    Parameters:
      p: Target QPainter.
      rect: Bounding QRectF of the chip.
      info: Media info dict (title, artist, app, exe) or None.
      playing: Whether media is actively playing.
      hover_t: Hover tween factor (0.0 to 1.0).

    Returns:
      Hit rect dictionary: {'prev': QRectF, 'playpause': QRectF, 'next': QRectF, 'chip': QRectF}
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # 1. Hover overlay
    eff_hover = max(0.0, min(1.0, hover_t))
    if eff_hover > 0.0:
        h_col = QColor(
            theme.COLOR_CHIP_HOVER.red(),
            theme.COLOR_CHIP_HOVER.green(),
            theme.COLOR_CHIP_HOVER.blue(),
            int(theme.COLOR_CHIP_HOVER.alpha() * eff_hover),
        )
        p.fillPath(theme.rounded_path(rect, theme.CHIP_RADIUS), h_col)

    cy = rect.center().y()
    app_name = str((info or {}).get("app", "")).lower()

    # 2. App Glyph Badge Circle on left
    bx = rect.left() + 19.0
    badge_radius = 11.0
    badge_rect = QRectF(bx - badge_radius, cy - badge_radius, badge_radius * 2, badge_radius * 2)

    if "spotify" in app_name:
        badge_bg = QColor("#1DB954")
    elif "youtube" in app_name:
        badge_bg = QColor("#FF0000")
    else:
        badge_bg = QColor("#8B5CF6")

    p.setPen(Qt.NoPen)
    p.setBrush(badge_bg)
    p.drawEllipse(badge_rect)

    # Inner vector glyph for the app
    if "spotify" in app_name:
        # 3 curved audio lines in dark charcoal
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#121212"), 1.3, Qt.SolidLine, Qt.RoundCap))
        for dy, r, span in [(-2.5, 7.5, 55), (0.2, 6.2, 50), (2.8, 5.0, 45)]:
            arc_r = QRectF(bx - r, cy + dy - r, r * 2, r * 2)
            p.drawArc(arc_r, (90 - span // 2) * 16, span * 16)
    elif "youtube" in app_name:
        # Crisp white play triangle
        tri = QPainterPath()
        tri.moveTo(bx - 2.5, cy - 4.5)
        tri.lineTo(bx + 4.5, cy)
        tri.lineTo(bx - 2.5, cy + 4.5)
        tri.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.white)
        p.drawPath(tri)
    else:
        # Music note glyph
        note_pen = QPen(Qt.white, 1.2, Qt.SolidLine, Qt.RoundCap)
        p.setPen(note_pen)
        p.setBrush(Qt.white)
        p.drawEllipse(QRectF(bx - 3.5, cy + 1.0, 3.5, 2.5))
        p.drawLine(QPointF(bx, cy + 2.0), QPointF(bx, cy - 4.0))
        p.drawLine(QPointF(bx, cy - 4.0), QPointF(bx + 3.0, cy - 2.5))

    # 3. Control Buttons on Right
    # Buttons: Prev, Play/Pause, Next
    btn_w = 20.0
    btn_h = 24.0
    btn_gap = 2.0
    total_btns_w = btn_w * 3 + btn_gap * 2
    btns_start_x = rect.right() - total_btns_w - 6.0

    r_prev = QRectF(btns_start_x, cy - btn_h / 2.0, btn_w, btn_h)
    r_play = QRectF(btns_start_x + btn_w + btn_gap, cy - btn_h / 2.0, btn_w, btn_h)
    r_next = QRectF(btns_start_x + (btn_w + btn_gap) * 2, cy - btn_h / 2.0, btn_w, btn_h)

    # 3a. Prev button (|◀)
    px = r_prev.center().x()
    p.setPen(Qt.NoPen)
    p.setBrush(theme.COLOR_TEXT_PRIMARY)
    prev_tri = QPainterPath()
    prev_tri.moveTo(px + 2.5, cy - 4.5)
    prev_tri.lineTo(px - 3.0, cy)
    prev_tri.lineTo(px + 2.5, cy + 4.5)
    prev_tri.closeSubpath()
    p.drawPath(prev_tri)
    p.fillRect(QRectF(px - 4.5, cy - 4.5, 1.4, 9.0), theme.COLOR_TEXT_PRIMARY)

    # 3b. Play/Pause button
    plx = r_play.center().x()
    if playing:
        # Pause bars (❚❚)
        bar_w = 2.2
        bar_h = 9.0
        p.fillRect(QRectF(plx - 3.2, cy - bar_h / 2.0, bar_w, bar_h), theme.COLOR_TEXT_PRIMARY)
        p.fillRect(QRectF(plx + 1.0, cy - bar_h / 2.0, bar_w, bar_h), theme.COLOR_TEXT_PRIMARY)
    else:
        # Play triangle (▶)
        play_tri = QPainterPath()
        play_tri.moveTo(plx - 3.0, cy - 5.0)
        play_tri.lineTo(plx + 4.5, cy)
        play_tri.lineTo(plx - 3.0, cy + 5.0)
        play_tri.closeSubpath()
        p.drawPath(play_tri)

    # 3c. Next button (▶|)
    nx = r_next.center().x()
    next_tri = QPainterPath()
    next_tri.moveTo(nx - 2.5, cy - 4.5)
    next_tri.lineTo(nx + 3.0, cy)
    next_tri.lineTo(nx - 2.5, cy + 4.5)
    next_tri.closeSubpath()
    p.drawPath(next_tri)
    p.fillRect(QRectF(nx + 3.2, cy - 4.5, 1.4, 9.0), theme.COLOR_TEXT_PRIMARY)

    # 4. Two-Line Elided Title & Artist in the middle
    text_left = bx + badge_radius + 8.0
    text_right = btns_start_x - 6.0
    avail_w = max(20.0, text_right - text_left)

    raw_title = str((info or {}).get("title", "")).strip() or "Medya Yok"
    raw_artist = str((info or {}).get("artist", "")).strip() or "Duraklatıldı"

    f_title = theme.make_font(11.0, QFont.Weight.DemiBold)
    f_artist = theme.make_font(10.0, QFont.Weight.Normal)

    fm_t = QFontMetricsF(f_title)
    fm_a = QFontMetricsF(f_artist)

    elided_title = fm_t.elidedText(raw_title, Qt.ElideRight, avail_w)
    elided_artist = fm_a.elidedText(raw_artist, Qt.ElideRight, avail_w)

    r_title = QRectF(text_left, rect.top() + 6.0, avail_w, 14.0)
    r_artist = QRectF(text_left, rect.top() + 20.0, avail_w, 14.0)

    p.setFont(f_title)
    p.setPen(theme.COLOR_TEXT_PRIMARY)
    p.drawText(r_title, Qt.AlignLeft | Qt.AlignVCenter, elided_title)

    p.setFont(f_artist)
    p.setPen(theme.COLOR_TEXT_SECONDARY)
    p.drawText(r_artist, Qt.AlignLeft | Qt.AlignVCenter, elided_artist)

    p.restore()

    return {
        "prev": r_prev,
        "playpause": r_play,
        "next": r_next,
        "chip": rect,
    }



# Windows ses aygıtı adlarını ekranda Türkçe göstermek için (yalnız görüntü; veri ham kalır)
_DEVICE_WORDS_TR = (
    ("Speakers", "Hoparlör"),
    ("Headphones", "Kulaklık"),
    ("Headset Earphone", "Kulaklık"),
    ("Headset", "Kulaklık seti"),
    ("Earphones", "Kulaklık"),
    ("Microphone", "Mikrofon"),
    ("Digital Audio", "Dijital ses"),
    ("Line Out", "Hat çıkışı"),
    ("Audio Device", "Ses aygıtı"),
)


PRESET_W = 40.0
PRESET_GAP = 4.0


def tr_device_name(name: str) -> str:
    """'Speakers (Realtek(R) Audio)' -> 'Hoparlör · Realtek Audio'. Bilinmeyen ad olduğu gibi kalır."""
    raw = str(name or "").strip()
    if not raw or raw == "Default Audio":
        return ""
    if raw == "Speakers":
        return "Hoparlör"
    raw = re.sub(r"\((?:R|TM|C)\)", "", raw, flags=re.IGNORECASE)
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", raw)
    kind, vendor = (m.group(1), m.group(2)) if m else (raw, "")
    for en, tr in _DEVICE_WORDS_TR:
        if kind.strip().lower() == en.lower():
            kind = tr
            break
    else:
        for en, tr in _DEVICE_WORDS_TR:
            kind = re.sub(r"\b" + re.escape(en) + r"\b", tr, kind, flags=re.IGNORECASE)
    kind = re.sub(r"\s{2,}", " ", kind).strip()
    vendor = re.sub(r"\s{2,}", " ", vendor).strip()
    return f"{kind} · {vendor}" if vendor else kind


def draw_volume_slider_panel(
    p: QPainter,
    rect: QRectF,
    level: float,
    muted: bool,
    device: str = "",
) -> Dict[str, QRectF]:
    """Draw an interactive volume flyout popover card matching Serit glass styling.

    Includes:
      - Specular glass capsule container.
      - Header with 'Ses Düzeyi' title and mute/level pill badge.
      - Device subtitle.
      - Interactive horizontal volume slider bar with cyan gradient and circular thumb.
      - Mute toggle button and quick percentage preset buttons.

    Returns:
      Hit rect dictionary: {'slider': QRectF, 'mute_btn': QRectF, 'card': QRectF}
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    val = max(0.0, min(100.0, float(level)))

    # 1. Base Glass Material
    theme.draw_glass_capsule(
        p,
        rect,
        radius=theme.POP_RADIUS,
        show_grain=True,
        show_specular=True,
        show_outer_stroke=True,
    )

    pad_x = 16.0
    card_w = rect.width()

    # 2. Header Row
    top_y = rect.top() + 14.0
    f_title = theme.make_font(13.0, QFont.Weight.DemiBold)
    p.setFont(f_title)
    p.setPen(theme.COLOR_TEXT_PRIMARY)
    p.drawText(QRectF(rect.left() + pad_x, top_y, 120.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, "Ses Düzeyi")

    # Readout Badge on top-right
    badge_w = 54.0
    badge_h = 20.0
    r_badge = QRectF(rect.right() - pad_x - badge_w, top_y - 1.0, badge_w, badge_h)
    p.setPen(Qt.NoPen)
    if muted:
        p.setBrush(theme.COLOR_BADGE_BG)
        p.drawRoundedRect(r_badge, 5.0, 5.0)
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(theme.COLOR_ALERT_CRIT)
        p.drawText(r_badge, Qt.AlignCenter, "Sessiz")
    else:
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r_badge, 5.0, 5.0)
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold, tabular=True))
        p.setPen(theme.COLOR_TEXT_PRIMARY)
        p.drawText(r_badge, Qt.AlignCenter, f"%{int(round(val))}")

    # 3. Device Subtitle Row
    dev_y = top_y + 20.0
    f_sub = theme.make_font(10.5, QFont.Weight.Normal)
    fm_sub = QFontMetricsF(f_sub)
    dev_str = tr_device_name(device) or "Varsayılan ses aygıtı"
    elided_dev = fm_sub.elidedText(dev_str, Qt.ElideRight, card_w - pad_x * 2 - 10.0)
    p.setFont(f_sub)
    p.setPen(theme.COLOR_TEXT_MUTED)
    p.drawText(QRectF(rect.left() + pad_x, dev_y, card_w - pad_x * 2, 14.0), Qt.AlignLeft | Qt.AlignVCenter, elided_dev)

    # 4. Volume Slider Bar
    slider_y = dev_y + 22.0
    slider_w = card_w - pad_x * 2
    slider_h = 8.0
    r_track = QRectF(rect.left() + pad_x, slider_y, slider_w, slider_h)

    # Background Track
    p.setPen(Qt.NoPen)
    p.setBrush(theme.COLOR_PROGRESS_TRACK)
    p.drawRoundedRect(r_track, 4.0, 4.0)

    # Active Fill
    pct = (val / 100.0) if not muted else 0.0
    fill_w = max(0.0, slider_w * pct)
    if fill_w > 0.0:
        r_fill = QRectF(r_track.left(), r_track.top(), fill_w, slider_h)
        fill_grad = QLinearGradient(r_track.left(), 0, r_track.right(), 0)
        fill_grad.setColorAt(0.0, QColor("#60B5FF"))
        fill_grad.setColorAt(1.0, QColor("#90D5FF"))
        p.setBrush(fill_grad)
        p.drawRoundedRect(r_fill, 4.0, 4.0)

    # Slider Thumb Handle
    thumb_x = r_track.left() + fill_w
    thumb_y = r_track.center().y()
    thumb_r = 7.0
    r_thumb = QRectF(thumb_x - thumb_r, thumb_y - thumb_r, thumb_r * 2, thumb_r * 2)

    # Outer glow halo around thumb
    halo_r = 10.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(96, 181, 255, 38))
    p.drawEllipse(QRectF(thumb_x - halo_r, thumb_y - halo_r, halo_r * 2, halo_r * 2))

    # Subtle drop shadow behind thumb
    p.setBrush(QColor(0, 0, 0, 90))
    p.drawEllipse(r_thumb.adjusted(0, 1.0, 0, 1.0))

    # Thumb body
    p.setBrush(QColor(255, 255, 255, 250))
    p.drawEllipse(r_thumb)
    p.setPen(QPen(QColor(0, 0, 0, 35), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(r_thumb)

    # 5. Quick Controls Footer Row
    footer_y = slider_y + 18.0
    btn_mute_w = 82.0
    btn_mute_h = 24.0
    r_mute = QRectF(rect.left() + pad_x, footer_y, btn_mute_w, btn_mute_h)

    # Mute Toggle Button
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 20) if not muted else QColor(255, 110, 110, 38))
    p.drawRoundedRect(r_mute, 6.0, 6.0)

    p.setFont(theme.make_font(10.5, QFont.Weight.Medium))
    p.setPen(theme.COLOR_ALERT_CRIT if muted else theme.COLOR_TEXT_PRIMARY)
    mute_txt = "Sesi Aç" if muted else "Sessiz Yap"
    p.drawText(r_mute, Qt.AlignCenter, mute_txt)

    # Hızlı seçim düğmeleri (%25, %50, %75, %100) — Türkçe yüzde biçimi
    presets = [("%25", 25), ("%50", 50), ("%75", 75), ("%100", 100)]
    preset_w = PRESET_W
    preset_h = 24.0
    preset_gap = PRESET_GAP
    preset_rects = []
    presets_total = len(presets) * preset_w + (len(presets) - 1) * preset_gap
    start_px = rect.right() - pad_x - presets_total

    for idx, (p_txt, _) in enumerate(presets):
        r_p = QRectF(start_px + idx * (preset_w + preset_gap), footer_y, preset_w, preset_h)
        preset_rects.append((r_p, float(_)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(r_p, 5.0, 5.0)

        p.setFont(theme.make_font(10.0, QFont.Weight.DemiBold, tabular=True))
        p.setPen(theme.COLOR_TEXT_PRIMARY)
        p.drawText(r_p, Qt.AlignCenter, p_txt)

    p.restore()

    return {
        "slider": r_track,
        "mute_btn": r_mute,
        "presets": preset_rects,
        "card": rect,
    }
