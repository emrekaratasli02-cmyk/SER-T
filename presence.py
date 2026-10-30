"""presence.py - uyku engelleme (güç isteği) + mikrofon/kamera kullanım algılama + bant simgeleri.

Saf Python + QPainter; iş parçacığı güvenli okuma/güç işlevleri.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

import logpath
from panel_style import ACCENT, WARN

try:  # Windows dışında import yine çalışsın
    import winreg as _real_winreg
except ImportError:  # pragma: no cover
    _real_winreg = None

KEEP_AWAKE_ICON_W = 28.0
PRESENCE_ICON_W = 24.0
REASON_TEXT = "Şerit: uyku engelleme"

_STROKE = 1.8
_GLYPH = 18.0
_WHITE_55 = QColor(255, 255, 255, 140)
_WHITE_85 = QColor(255, 255, 255, 217)
_WHITE_HOVER = QColor(255, 255, 255, 230)

# ---------------------------------------------------------------- güç isteği

_lock = threading.Lock()
_handle = None  # gerçek HANDLE ya da sahte
_kernel32 = None  # test dikişi: sahte kernel32 nesnesi
_real_k32 = None

POWER_REQUEST_CONTEXT_VERSION = 0
POWER_REQUEST_CONTEXT_SIMPLE_STRING = 1
PowerRequestDisplayRequired = 0
PowerRequestSystemRequired = 1


class _REASON_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("Flags", wintypes.DWORD),
        ("SimpleReasonString", wintypes.LPWSTR),
    ]


def _load_real_kernel32():
    global _real_k32
    if _real_k32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.PowerCreateRequest.argtypes = [ctypes.POINTER(_REASON_CONTEXT)]
        k.PowerCreateRequest.restype = wintypes.HANDLE
        k.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k.PowerSetRequest.restype = wintypes.BOOL
        k.PowerClearRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k.PowerClearRequest.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _real_k32 = k
    return _real_k32


def _get_k32():
    """Sahte (test dikişi) ya da gerçek kernel32; testte gerçeğe izin yoksa None."""
    if _kernel32 is not None:
        return _kernel32
    if logpath.is_running_under_test() and os.environ.get("SERIT_ALLOW_REAL_POWER") != "1":
        return None
    try:
        return _load_real_kernel32()
    except Exception:
        return None


_INVALID = (None, 0, -1, ctypes.c_void_p(-1).value)


def _release_locked(k) -> None:
    global _handle
    h = _handle
    _handle = None
    if h is None:
        return
    if k is None:
        return
    for kind in (PowerRequestDisplayRequired, PowerRequestSystemRequired):
        try:
            k.PowerClearRequest(h, kind)
        except Exception:
            pass
    try:
        k.CloseHandle(h)
    except Exception:
        pass


def set_keep_awake(on: bool) -> bool:
    """Ekran + sistem uyku engelini aç/kapat; yeni durumu döndürür."""
    global _handle
    with _lock:
        k = _get_k32()
        if on:
            if _handle is not None:
                return True
            if k is None:
                # Testte gerçek çağrı yok ve sahte de yok: durumu sembolik tut.
                _handle = "guarded"
                return True
            try:
                ctx = _REASON_CONTEXT(POWER_REQUEST_CONTEXT_VERSION,
                                      POWER_REQUEST_CONTEXT_SIMPLE_STRING, REASON_TEXT)
                h = k.PowerCreateRequest(ctypes.byref(ctx))
            except Exception:
                return False
            if h in _INVALID:
                return False
            ok = True
            for kind in (PowerRequestDisplayRequired, PowerRequestSystemRequired):
                try:
                    if not k.PowerSetRequest(h, kind):
                        ok = False
                except Exception:
                    ok = False
            if not ok:
                _handle = h
                _release_locked(k)
                return False
            _handle = h
            return True
        # off
        if _handle == "guarded":
            _handle = None
        else:
            _release_locked(k)
        return False


def keep_awake_active() -> bool:
    with _lock:
        return _handle is not None


def release_all() -> None:
    """Idempotent: kapanış/atexit için."""
    global _handle
    with _lock:
        if _handle == "guarded":
            _handle = None
            return
        if _handle is None:
            return
        _release_locked(_get_k32())


# ------------------------------------------------- mikrofon / kamera okuma

_winreg = _real_winreg  # test dikişi
_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"

_KNOWN = {
    "microsoft.windowscamera": "Kamera",
    "msteams": "Teams",
    "microsoft.teams": "Teams",
    "microsoft.skypeapp": "Skype",
    "microsoft.windows.soundrecorder": "Ses Kaydedici",
    "microsoft.windowssoundrecorder": "Ses Kaydedici",
    "microsoft.windows.cortana": "Cortana",
    "microsoft.549981c3f5f10": "Cortana",
    "microsoft.people": "Kişiler",
    "microsoft.microsoftedge": "Edge",
    "microsoft.microsoftedge.stable": "Edge",
    "whatsappdesktop": "WhatsApp",
    "5319275a.whatsappdesktop": "WhatsApp",
    "microsoft.gamingapp": "Xbox",
    "microsoft.xboxgamingoverlay": "Xbox Game Bar",
    "microsoft.windows.client.cbs": "Windows",
    "microsoftwindows.client.cbs": "Windows",
    "microsoft.windows.searchhost": "Windows Arama",
}
_EXE_NAMES = {
    "msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "zoom": "Zoom",
    "teams": "Teams", "discord": "Discord", "obs64": "OBS", "obs32": "OBS",
    "slack": "Slack", "skype": "Skype", "telegram": "Telegram", "whatsapp": "WhatsApp",
    "zen": "Zen", "brave": "Brave", "opera": "Opera", "vlc": "VLC",
}


def _friendly_package(key: str) -> str:
    base = key.split("_", 1)[0]  # yayıncı özetini at
    low = base.lower()
    if low in _KNOWN:
        return _KNOWN[low]
    for k, v in _KNOWN.items():
        if low.startswith(k):
            return v
    parts = [s for s in base.split(".") if s]
    name = parts[-1] if parts else base
    if name and name[0].isdigit() and len(parts) > 1:
        name = parts[-2]
    return name or key


def _friendly_exe(key: str) -> str:
    path = key.replace("#", "\\")
    stem = path.replace("/", "\\").rsplit("\\", 1)[-1]
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    if stem.lower() in _EXE_NAMES:
        return _EXE_NAMES[stem.lower()]
    return stem[:1].upper() + stem[1:] if stem else key


def _in_use(w, hkey) -> bool:
    try:
        start = w.QueryValueEx(hkey, "LastUsedTimeStart")[0]
        stop = w.QueryValueEx(hkey, "LastUsedTimeStop")[0]
    except OSError:
        return False
    try:
        return int(start) != 0 and int(stop) == 0
    except (TypeError, ValueError):
        return False


def _enum_subkeys(w, hkey):
    i = 0
    while True:
        try:
            yield w.EnumKey(hkey, i)
        except OSError:
            return
        i += 1


def _scan_capability(w, cap: str) -> list:
    names: list = []

    def add(n):
        if n and n not in names:
            names.append(n)

    root = w.OpenKey(w.HKEY_CURRENT_USER, _CONSENT + "\\" + cap)
    try:
        for sub in list(_enum_subkeys(w, root)):
            if sub == "NonPackaged":
                try:
                    npk = w.OpenKey(root, sub)
                except OSError:
                    continue
                try:
                    for ex in list(_enum_subkeys(w, npk)):
                        try:
                            k = w.OpenKey(npk, ex)
                        except OSError:
                            continue
                        try:
                            if _in_use(w, k):
                                add(_friendly_exe(ex))
                        finally:
                            w.CloseKey(k)
                finally:
                    w.CloseKey(npk)
                continue
            try:
                k = w.OpenKey(root, sub)
            except OSError:
                continue
            try:
                if _in_use(w, k):
                    add(_friendly_package(sub))
            finally:
                w.CloseKey(k)
    finally:
        w.CloseKey(root)
    return names


def read_capability_usage() -> dict:
    """{"mic": [...], "cam": [...]} kullanımdaki uygulamalar; asla fırlatmaz."""
    w = _winreg
    if w is None:
        return {"mic": [], "cam": [], "err": "winreg yok"}
    try:
        return {"mic": _scan_capability(w, "microphone"),
                "cam": _scan_capability(w, "webcam")}
    except Exception as exc:
        return {"mic": [], "cam": [], "err": f"{type(exc).__name__}: {exc}"}


def presence_tooltip(usage: dict) -> str:
    usage = usage or {}
    parts = []
    if usage.get("mic"):
        parts.append("Mikrofon: " + ", ".join(usage["mic"]))
    if usage.get("cam"):
        parts.append("Kamera: " + ", ".join(usage["cam"]))
    return " · ".join(parts)


# ------------------------------------------------------------------ simgeler

def _pen(col: QColor) -> QPen:
    pen = QPen(col, _STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _glyph_box(rect: QRectF, w: float, h: float) -> QRectF:
    c = rect.center()
    return QRectF(c.x() - w / 2.0, c.y() - h / 2.0, w, h)


def _cup_path(b: QRectF) -> QPainterPath:
    s = b.width() / 18.0
    ox, oy = b.left(), b.top()

    def pt(x, y):
        return QPointF(ox + x * s, oy + y * s)

    path = QPainterPath()
    # gövde
    path.moveTo(pt(2.5, 7.5))
    path.lineTo(pt(2.5, 12.5))
    path.cubicTo(pt(2.5, 15), pt(4.2, 16.5), pt(6.5, 16.5))
    path.lineTo(pt(8.5, 16.5))
    path.cubicTo(pt(10.8, 16.5), pt(12.5, 15), pt(12.5, 12.5))
    path.lineTo(pt(12.5, 7.5))
    path.closeSubpath()
    # kulp
    path.moveTo(pt(12.5, 9))
    path.lineTo(pt(14, 9))
    path.cubicTo(pt(15.6, 9), pt(16, 10), pt(16, 11))
    path.cubicTo(pt(16, 12.2), pt(15.4, 13.2), pt(14, 13.2))
    path.lineTo(pt(12.3, 13.2))
    # buhar
    path.moveTo(pt(5.5, 2.2))
    path.cubicTo(pt(4.5, 3.4), pt(6.5, 4.4), pt(5.5, 5.6))
    path.moveTo(pt(9.5, 2.2))
    path.cubicTo(pt(8.5, 3.4), pt(10.5, 4.4), pt(9.5, 5.6))
    return path


def draw_keep_awake_icon(p: QPainter, rect: QRectF, active: bool, hover: bool = False) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    if active:
        col = ACCENT
    else:
        col = _WHITE_HOVER if hover else _WHITE_55
    box = _glyph_box(rect, _GLYPH, _GLYPH)
    p.setPen(_pen(col))
    p.setBrush(Qt.NoBrush)
    p.drawPath(_cup_path(box))
    p.restore()


def _mic_path(b: QRectF) -> QPainterPath:
    s = b.height() / 16.0
    cx = b.center().x()
    top = b.top()

    path = QPainterPath()
    cap = QRectF(cx - 2.6 * s, top, 5.2 * s, 9.2 * s)
    path.addRoundedRect(cap, 2.6 * s, 2.6 * s)
    # yay
    arc = QRectF(cx - 5.2 * s, top + 2.8 * s, 10.4 * s, 9.2 * s)
    path.moveTo(arc.left(), arc.center().y())
    path.arcTo(arc, 180, 180)
    path.moveTo(cx, top + 12.0 * s)
    path.lineTo(cx, top + 15.2 * s)
    return path


def _cam_path(b: QRectF) -> QPainterPath:
    s = b.width() / 18.0
    ox = b.left()
    cy = b.center().y()
    path = QPainterPath()
    body = QRectF(ox + 0.5 * s, cy - 4.0 * s, 11.0 * s, 8.0 * s)
    path.addRoundedRect(body, 2.0 * s, 2.0 * s)
    path.moveTo(ox + 11.5 * s, cy - 1.2 * s)
    path.lineTo(ox + 16.5 * s, cy - 3.6 * s)
    path.lineTo(ox + 16.5 * s, cy + 3.6 * s)
    path.lineTo(ox + 11.5 * s, cy + 1.2 * s)
    return path


def draw_presence_icon(p: QPainter, rect: QRectF, usage: dict, hover: bool = False) -> None:
    usage = usage or {}
    mic = bool(usage.get("mic"))
    cam = bool(usage.get("cam"))
    if not (mic or cam):
        return
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    col = QColor(255, 255, 255, 255 if hover else 217)
    p.setPen(_pen(col))
    p.setBrush(Qt.NoBrush)
    n = int(mic) + int(cam)
    # Tek glif: 14 px; ikisi birlikte: 24 px kutuya iki küçük glif
    if n == 1:
        if mic:
            p.drawPath(_mic_path(_glyph_box(rect, 12.0, 15.0)))
        else:
            p.drawPath(_cam_path(_glyph_box(rect, 17.0, 13.0)))
    else:
        cx = rect.center().x()
        mrect = QRectF(cx - 11.0, rect.center().y() - 6.0, 9.0, 12.0)
        crect = QRectF(cx - 0.5, rect.center().y() - 5.0, 12.0, 10.0)
        p.drawPath(_mic_path(mrect))
        p.setPen(_pen(col))
        p.drawPath(_cam_path(crect))
    # turuncu nokta (macOS/KDE tarzı)
    p.setPen(Qt.NoPen)
    p.setBrush(WARN)
    p.drawEllipse(QPointF(rect.right() - 3.0, rect.top() + 6.0), 2.6, 2.6)
    p.restore()
