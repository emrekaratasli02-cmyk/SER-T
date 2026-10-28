"""Windows integration module for Şerit dock application.

Provides Win32 API functions for window management, grouping, application icons,
Acrylic blur-behind composition, rounded window clipping regions, and taskbar
auto-hide control.
"""

from __future__ import annotations

import collections
import datetime
import os
from pathlib import Path
import ctypes
import ctypes.wintypes as w

import psutil
from typing import Optional
from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileIconProvider

__all__ = [
    "list_windows",
    "group_by_app",
    "get_app_name",
    "app_icon",
    "activate_or_minimize",
    "enable_acrylic",
    "set_round_region",
    "taskbar_autohide_get",
    "taskbar_autohide_set",
]

# --- Win32 Libraries ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
dwmapi = ctypes.windll.dwmapi
gdi32 = ctypes.windll.gdi32
version = ctypes.windll.version

# --- Win32 Constants ---
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
GWL_STYLE = -16
GW_OWNER = 4
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SW_RESTORE = 9
SW_MINIMIZE = 6

VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002

ABM_GETSTATE = 4
ABM_SETSTATE = 10
ABS_AUTOHIDE = 1

WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

try:
    from logpath import LOG_PATH
except ImportError:
    LOG_PATH = Path("D:/Apps/serit/serit.log")


# --- Win32 Structures ---
class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HWND),
        ("uCallbackMessage", w.UINT),
        ("uEdge", w.UINT),
        ("rc", w.RECT),
        ("lParam", w.LPARAM),
    ]


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint32),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

# --- Kernel32 Signatures ---
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, w.LPDWORD]
kernel32.QueryFullProcessImageNameW.restype = w.BOOL
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.CloseHandle.restype = w.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = w.DWORD

# --- User32 Signatures ---
user32.EnumWindows.argtypes = [WNDENUMPROC, w.LPARAM]
user32.EnumWindows.restype = w.BOOL
user32.IsWindow.argtypes = [w.HWND]
user32.IsWindow.restype = w.BOOL
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsWindowVisible.restype = w.BOOL
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [w.HWND, w.LPDWORD]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.GetWindow.argtypes = [w.HWND, w.UINT]
user32.GetWindow.restype = w.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = w.HWND
user32.IsIconic.argtypes = [w.HWND]
user32.IsIconic.restype = w.BOOL
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.ShowWindow.restype = w.BOOL
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.SetForegroundWindow.restype = w.BOOL
user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
user32.AttachThreadInput.restype = w.BOOL
user32.keybd_event.argtypes = [w.BYTE, w.BYTE, w.DWORD, ctypes.c_size_t]
user32.keybd_event.restype = None
user32.SetWindowRgn.argtypes = [w.HWND, w.HRGN, w.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int

if hasattr(user32, "SetWindowCompositionAttribute"):
    user32.SetWindowCompositionAttribute.argtypes = [
        w.HWND,
        ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA),
    ]
    user32.SetWindowCompositionAttribute.restype = w.BOOL

user32.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = w.LONG

GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW", getattr(user32, "GetWindowLongW", None))
if GetWindowLongPtrW is not None:
    GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
    GetWindowLongPtrW.restype = ctypes.c_ssize_t

# --- Gdi32 Signatures ---
gdi32.CreateRoundRectRgn.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
gdi32.CreateRoundRectRgn.restype = w.HRGN
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteObject.restype = w.BOOL

# --- Dwmapi Signatures ---
dwmapi.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, w.LPCVOID, w.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

# --- Shell32 Signatures ---
shell32.SHAppBarMessage.argtypes = [w.DWORD, ctypes.POINTER(APPBARDATA)]
shell32.SHAppBarMessage.restype = ctypes.c_uint64

# --- Version Signatures ---
version.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, w.LPDWORD]
version.GetFileVersionInfoSizeW.restype = w.DWORD
version.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID]
version.GetFileVersionInfoW.restype = w.BOOL
version.VerQueryValueW.argtypes = [
    w.LPCVOID,
    w.LPCWSTR,
    ctypes.POINTER(w.LPVOID),
    ctypes.POINTER(w.UINT),
]
version.VerQueryValueW.restype = w.BOOL


def _log(msg: str) -> None:
    """Append a timestamped message to D:/Apps/serit/serit.log."""
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} [winapi] {msg}\n")
    except OSError:
        pass


def list_windows() -> list[dict]:
    """Return a list of real taskbar-type top-level windows.

    Returned dict format:
        {
            'hwnd': int,
            'title': str,
            'exe': str (full path or ''),
            'pid': int,
            'active': bool,
            'minimized': bool
        }

    Filters applied:
      - Window is visible (user32.IsWindowVisible)
      - Has non-empty title (GetWindowTextLengthW > 0 and stripped title != '')
      - Not cloaked (DwmGetWindowAttribute DWMWA_CLOAKED == 0)
      - Not owned tool window (WS_EX_TOOLWINDOW without WS_EX_APPWINDOW)
      - No owner window unless WS_EX_APPWINDOW
      - Title is not 'Şerit' or 'Program Manager'

    Ordering:
      Windows are returned in Z-order (topmost to bottommost) as enumerated
      by EnumWindows.
    """
    windows: list[dict] = []
    try:
        fg_hwnd = int(user32.GetForegroundWindow() or 0)

        def enum_cb(hwnd_raw: int, _: int) -> bool:
            hwnd = int(hwnd_raw or 0)
            try:
                if not hwnd or not user32.IsWindowVisible(hwnd):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True

                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title or title in ("Şerit", "Program Manager"):
                    return True

                # Check cloaked status
                cloaked = w.DWORD(0)
                dwmapi.DwmGetWindowAttribute(
                    hwnd,
                    DWMWA_CLOAKED,
                    ctypes.byref(cloaked),
                    ctypes.sizeof(cloaked),
                )
                if cloaked.value != 0:
                    return True

                # Check window extended styles using GetWindowLongPtrW
                if GetWindowLongPtrW is not None:
                    ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                else:
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                    return True

                # Owner window check: no owner unless WS_EX_APPWINDOW
                owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
                if owner != 0 and not (ex_style & WS_EX_APPWINDOW):
                    return True

                pid = w.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pid_val = int(pid.value)

                exe = ""
                if pid_val > 0:
                    try:
                        exe = psutil.Process(pid_val).exe()
                    except Exception:
                        exe = ""

                active = (hwnd == fg_hwnd)
                minimized = bool(user32.IsIconic(hwnd))

                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "exe": exe,
                    "pid": pid_val,
                    "active": active,
                    "minimized": minimized,
                })
            except Exception as item_err:
                _log(f"enum_cb error for hwnd {hwnd}: {item_err}")
            return True

        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)
    except Exception as e:
        _log(f"list_windows error: {e}")
    return windows


_APP_NAME_CACHE: dict[str, str] = {}


def get_app_name(exe: str) -> str:
    """Retrieve friendly application name from FileDescription via version.dll.

    Falls back to capitalized executable stem; never returns empty string.
    Results are cached in memory.
    """
    if not exe:
        return "App"

    norm_key = (
        os.path.normcase(os.path.abspath(exe))
        if os.path.isabs(exe)
        else exe.lower()
    )
    if norm_key in _APP_NAME_CACHE:
        return _APP_NAME_CACHE[norm_key]

    desc = ""
    try:
        if os.path.exists(exe):
            size = version.GetFileVersionInfoSizeW(exe, None)
            if size > 0:
                buf = ctypes.create_string_buffer(size)
                if version.GetFileVersionInfoW(exe, 0, size, buf):
                    trans_ptr = w.LPVOID()
                    trans_len = w.UINT()
                    if (
                        version.VerQueryValueW(
                            buf,
                            r"\VarFileInfo\Translation",
                            ctypes.byref(trans_ptr),
                            ctypes.byref(trans_len),
                        )
                        and trans_len.value >= 4
                        and trans_ptr.value
                    ):
                        trans = ctypes.cast(trans_ptr, ctypes.POINTER(w.WORD))
                        lang = trans[0]
                        codepage = trans[1]
                        sub_block = (
                            fr"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
                        )
                        val_ptr = w.LPVOID()
                        val_len = w.UINT()
                        if (
                            version.VerQueryValueW(
                                buf,
                                sub_block,
                                ctypes.byref(val_ptr),
                                ctypes.byref(val_len),
                            )
                            and val_len.value
                            and val_ptr.value
                        ):
                            desc = ctypes.wstring_at(val_ptr.value).strip()

                    if not desc:
                        for lang_cp in ("040904b0", "040904e4", "041f04b0", "000004b0"):
                            sub_block = fr"\StringFileInfo\{lang_cp}\FileDescription"
                            val_ptr = w.LPVOID()
                            val_len = w.UINT()
                            if (
                                version.VerQueryValueW(
                                    buf,
                                    sub_block,
                                    ctypes.byref(val_ptr),
                                    ctypes.byref(val_len),
                                )
                                and val_len.value
                                and val_ptr.value
                            ):
                                desc = ctypes.wstring_at(val_ptr.value).strip()
                                if desc:
                                    break
    except Exception as exc:
        _log(f"get_app_name error for '{exe}': {exc}")

    if not desc:
        try:
            stem = Path(exe).stem
            desc = stem.capitalize() if stem else "App"
        except Exception:
            desc = "App"

    if not desc:
        desc = "App"

    _APP_NAME_CACHE[norm_key] = desc
    return desc


def group_by_app(windows: list[dict]) -> list[dict]:
    """Group windows by executable path (case-insensitive), preserving appearance order.

    Each group dictionary contains:
        {
            'name': str (friendly app name from version.dll or capitalized stem, never empty),
            'exe': str,
            'title': str (of the active window if any, else the topmost/most recent window),
            'hwnds': list[int],
            'active': bool (True if any window in group is active),
            'count': int (number of windows in group)
        }
    """
    groups: dict[str, dict] = {}
    order: list[str] = []

    for w_info in windows:
        exe = w_info.get("exe") or ""
        key = exe.lower()
        if key not in groups:
            groups[key] = {
                "exe": exe,
                "first_title": w_info.get("title", ""),
                "active_title": "",
                "hwnds": [],
                "active": False,
            }
            order.append(key)

        grp = groups[key]
        hwnd = w_info.get("hwnd")
        if hwnd is not None:
            grp["hwnds"].append(int(hwnd or 0))

        if w_info.get("active"):
            grp["active"] = True
            grp["active_title"] = w_info.get("title", "")

    result: list[dict] = []
    for key in order:
        grp = groups[key]
        title = (
            grp["active_title"]
            if grp["active"] and grp["active_title"]
            else grp["first_title"]
        )
        name = get_app_name(grp["exe"])
        result.append({
            "name": name,
            "exe": grp["exe"],
            "title": title,
            "hwnds": grp["hwnds"],
            "active": grp["active"],
            "count": len(grp["hwnds"]),
        })

    return result


_ICON_CACHE: collections.OrderedDict[tuple[str, int], QPixmap] = collections.OrderedDict()


def app_icon(exe: str, size: int = 64) -> QPixmap:
    """Retrieve real application icon via QFileIconProvider().

    Caches results in a dictionary. Returns a null QPixmap if exe is empty or missing.

    NOTE: Requires an active QApplication instance to exist before calling.
    """
    if not exe:
        return QPixmap()

    norm_key = (
        os.path.normcase(os.path.abspath(exe))
        if os.path.isabs(exe)
        else exe.lower(),
        size,
    )
    if norm_key in _ICON_CACHE:
        _ICON_CACHE.move_to_end(norm_key)
        return _ICON_CACHE[norm_key]

    try:
        if not os.path.exists(exe):
            return QPixmap()
        provider = QFileIconProvider()
        pix = provider.icon(QFileInfo(exe)).pixmap(size, size)
        if pix.isNull():
            return QPixmap()
        _ICON_CACHE[norm_key] = pix
        _ICON_CACHE.move_to_end(norm_key)
        if len(_ICON_CACHE) > 128:
            _ICON_CACHE.popitem(last=False)
        return pix
    except Exception as e:
        _log(f"app_icon error for '{exe}': {e}")
        return QPixmap()


def activate_or_minimize(hwnd: int) -> None:
    """Toggle window state:
    - If window is foreground and not minimized: minimize it (ShowWindow SW_MINIMIZE=6).
    - If minimized: restore window (SW_RESTORE=9) and bring to foreground.
    - Else: bring window to foreground.

    Uses a simulated ALT keypress and AttachThreadInput to ensure SetForegroundWindow
    succeeds even when called from a background process.
    """
    try:
        target_hwnd = int(hwnd or 0)
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return

        fg_hwnd = int(user32.GetForegroundWindow() or 0)
        minimized = bool(user32.IsIconic(target_hwnd))

        if fg_hwnd == target_hwnd and not minimized:
            user32.ShowWindow(target_hwnd, SW_MINIMIZE)
            return

        if minimized:
            user32.ShowWindow(target_hwnd, SW_RESTORE)

        # Bring to foreground using ALT trick + thread input attachment
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        cur_tid = kernel32.GetCurrentThreadId()
        attached = False
        if fg_tid and cur_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))

        try:
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.SetForegroundWindow(target_hwnd)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)

    except Exception as e:
        _log(f"activate_or_minimize error for hwnd {hwnd}: {e}")


def enable_acrylic(hwnd: int, tint_argb: int = 0x50201812) -> bool:
    """Disable Win32 rectangular SetWindowCompositionAttribute acrylic bleed.

    On Windows 11, SetWindowCompositionAttribute (WCA_ACCENT_POLICY) paints a dark
    rectangular backdrop across the entire HWND bounding box, leaving visible 90-degree
    square corners outside rounded capsule/pill shapes. Leaving DWM accent disabled
    allows Qt's per-pixel alpha channel (WA_TranslucentBackground) to render 100%
    clean, anti-aliased rounded corners with zero rectangular bleed.
    """
    try:
        target_hwnd = int(hwnd or 0)
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return False
        if hasattr(user32, "SetWindowCompositionAttribute"):
            policy = ACCENT_POLICY()
            policy.AccentState = 0  # ACCENT_DISABLED
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = WCA_ACCENT_POLICY
            data.Data = ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(policy)
            user32.SetWindowCompositionAttribute(target_hwnd, ctypes.byref(data))
        return True
    except Exception as e:
        _log(f"enable_acrylic error for hwnd {hwnd}: {e}")
        return False


def set_round_region(
    hwnd: int,
    w_logical: int,
    h_logical: int,
    radius_logical: int = 18,
    dpr: float = 1.0,
) -> bool:
    """Clear any jagged GDI window region so Qt's anti-aliased alpha channel clips the window."""
    try:
        target_hwnd = int(hwnd or 0)
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return False
        user32.SetWindowRgn(target_hwnd, 0, True)
        return True
    except Exception as e:
        _log(f"set_round_region error for hwnd {hwnd}: {e}")
        return False


VK_LWIN = 0x5B
VK_D = 0x44
WM_CLOSE = 0x0010
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.PostMessageW.restype = w.BOOL


# --- Pencere önizlemesi (PrintWindow) ---------------------------------------
# Ayrı DLL nesneleri: argtypes ayarları diğer modüllerin user32/gdi32 çağrılarını etkilemesin.
PW_RENDERFULLCONTENT = 0x00000002
DWMWA_EXTENDED_FRAME_BOUNDS = 9
_t_u32 = ctypes.WinDLL("user32")
_t_g32 = ctypes.WinDLL("gdi32")
_t_u32.GetDC.argtypes = [w.HWND]
_t_u32.GetDC.restype = w.HDC
_t_u32.ReleaseDC.argtypes = [w.HWND, w.HDC]
_t_u32.ReleaseDC.restype = ctypes.c_int
_t_u32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
_t_u32.GetWindowRect.restype = w.BOOL
_t_u32.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
_t_u32.PrintWindow.restype = w.BOOL
_t_u32.IsHungAppWindow.argtypes = [w.HWND]
_t_u32.IsHungAppWindow.restype = w.BOOL
_t_g32.CreateCompatibleDC.argtypes = [w.HDC]
_t_g32.CreateCompatibleDC.restype = w.HDC
_t_g32.CreateDIBSection.argtypes = [w.HDC, ctypes.c_void_p, w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
_t_g32.CreateDIBSection.restype = w.HBITMAP
_t_g32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
_t_g32.SelectObject.restype = w.HGDIOBJ
_t_g32.DeleteObject.argtypes = [w.HGDIOBJ]
_t_g32.DeleteObject.restype = w.BOOL
_t_g32.DeleteDC.argtypes = [w.HDC]
_t_g32.DeleteDC.restype = w.BOOL


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
        ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


def window_thumbnail(hwnd: int, max_w: int = 176, max_h: int = 110) -> Optional[QImage]:
    """Pencerenin küçük görüntüsü (yalnız bellekte; diske yazılmaz).

    Küçültülmüş, asılı, geçersiz ya da tamamen siyah çıkan pencerede None döner.
    Arka plan iş parçacığından çağrılabilir (QImage, QPixmap değil).
    """
    h = int(hwnd or 0)
    try:
        if not h or not user32.IsWindow(h) or user32.IsIconic(h) or _t_u32.IsHungAppWindow(h):
            return None
        r = w.RECT()
        if not _t_u32.GetWindowRect(h, ctypes.byref(r)):
            return None
        width, height = r.right - r.left, r.bottom - r.top
        if width < 16 or height < 16 or width > 12000 or height > 12000:
            return None
        crop = (0, 0, width, height)
        fr = w.RECT()  # görünmez yeniden boyutlandırma kenarlarını kes
        if dwmapi.DwmGetWindowAttribute(h, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(fr), ctypes.sizeof(fr)) == 0:
            cx, cy = fr.left - r.left, fr.top - r.top
            cw, ch = min(fr.right - fr.left, width - cx), min(fr.bottom - fr.top, height - cy)
            if 0 <= cx < width and 0 <= cy < height and cw > 16 and ch > 16:
                crop = (cx, cy, cw, ch)
    except Exception as e:
        _log(f"window_thumbnail rect error for hwnd {hwnd}: {e}")
        return None

    sdc = mdc = hbmp = old = None
    try:
        sdc = _t_u32.GetDC(None)
        mdc = _t_g32.CreateCompatibleDC(sdc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = width, -height  # üstten aşağı
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        bits = ctypes.c_void_p()
        hbmp = _t_g32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hbmp or not bits.value:
            return None
        old = _t_g32.SelectObject(mdc, hbmp)
        if not _t_u32.PrintWindow(h, mdc, PW_RENDERFULLCONTENT):
            return None
        raw = ctypes.string_at(bits.value, width * height * 4)
        full = QImage(raw, width, height, width * 4, QImage.Format.Format_RGB32).copy(*crop)
        img = full.scaled(int(max_w), int(max_h), Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        if img.isNull():
            return None
        lit = total = 0
        for sy in range(1, 12):
            for sx in range(1, 16):
                total += 1
                if img.pixel(int(img.width() * sx / 16), int(img.height() * sy / 12)) & 0xFFFFFF:
                    lit += 1
        return img if lit * 10 >= total else None  # %90'dan fazlası siyahsa görüntü alınamamıştır
    except Exception as e:
        _log(f"window_thumbnail error for hwnd {hwnd}: {e}")
        return None
    finally:
        try:
            if mdc and old:
                _t_g32.SelectObject(mdc, old)
            if hbmp:
                _t_g32.DeleteObject(hbmp)
            if mdc:
                _t_g32.DeleteDC(mdc)
            if sdc:
                _t_u32.ReleaseDC(None, sdc)
        except Exception:
            pass


# --- Tam ekran algılama ------------------------------------------------------
class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


_t_u32.GetForegroundWindow.argtypes = []
_t_u32.GetForegroundWindow.restype = w.HWND
_t_u32.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
_t_u32.MonitorFromWindow.restype = w.HMONITOR
_t_u32.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_t_u32.GetMonitorInfoW.restype = w.BOOL
_t_u32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
_t_u32.GetClassNameW.restype = ctypes.c_int
_t_u32.GetWindowThreadProcessId.argtypes = [w.HWND, w.LPDWORD]
_t_u32.GetWindowThreadProcessId.restype = w.DWORD
_t_u32.IsZoomed.argtypes = [w.HWND]
_t_u32.IsZoomed.restype = w.BOOL
MONITOR_DEFAULTTONEAREST = 2
# Masaüstü, kabuk, Alt+Tab ve görev görünümü ekranı kaplasa da "tam ekran uygulama" sayılmaz.
_SHELL_CLASSES = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "ForegroundStaging",
})


def covers_monitor(win: tuple, mon: tuple) -> bool:
    """(left, top, right, bottom) pencere monitörün tamamını kaplıyor mu? Büyütülmüş pencere kaplamaz
    (alt kenarı bar/görev çubuğu alanında biter)."""
    try:
        wl, wt, wr, wb = (int(v) for v in win)
        ml, mt, mr, mb = (int(v) for v in mon)
    except Exception:
        return False
    if mr - ml < 200 or mb - mt < 200:
        return False
    return wl <= ml and wt <= mt and wr >= mr and wb >= mb


def foreground_fullscreen(own_pid: Optional[int] = None, dock_hwnd: Optional[int] = None) -> bool:
    """Öndeki pencere bulunduğu monitörü tamamen kaplıyorsa (video, oyun, sunum) True.

    Masaüstü/kabuk/Alt+Tab, büyütülmüş pencereler ve Şerit'in kendi pencereleri hariç; dock_hwnd
    verilirse yalnız barın bulunduğu monitördeki tam ekran sayılır. Hata olursa False (bar görünür kalır).
    """
    try:
        h = _t_u32.GetForegroundWindow()
        if not h:
            return False
        buf = ctypes.create_unicode_buffer(64)
        _t_u32.GetClassNameW(h, buf, 64)
        if buf.value in _SHELL_CLASSES:
            return False
        if own_pid is not None:
            pid = w.DWORD(0)
            _t_u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if int(pid.value) == int(own_pid):
                return False
        if _t_u32.IsZoomed(h):
            return False  # büyütülmüş pencere tam ekran değildir (görev çubuğu otomatik gizliyken de)
        r = w.RECT()
        if not _t_u32.GetWindowRect(h, ctypes.byref(r)):
            return False
        hmon = _t_u32.MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return False
        if dock_hwnd:
            if _t_u32.MonitorFromWindow(int(dock_hwnd), MONITOR_DEFAULTTONEAREST) != hmon:
                return False  # tam ekran başka monitörde; barın ekranı etkilenmez
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _t_u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return covers_monitor((r.left, r.top, r.right, r.bottom), (m.left, m.top, m.right, m.bottom))
    except Exception as e:
        _log(f"foreground_fullscreen error: {e}")
        return False


def toggle_desktop() -> None:
    """Masaüstünü göster / pencereleri geri getir (Win+D ile aynı; ikinci çağrı geri getirir)."""
    try:
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        try:
            user32.keybd_event(VK_D, 0, 0, 0)
            user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
        finally:
            user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)  # Win tuşu asla basılı kalmasın
    except Exception as e:
        _log(f"toggle_desktop error: {e}")


def activate_window(hwnd: int) -> None:
    """Pencereyi öne getirir; zaten öndeyse küçültmez (pencere seçicisi için)."""
    try:
        target_hwnd = int(hwnd or 0)
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return
        if bool(user32.IsIconic(target_hwnd)):
            user32.ShowWindow(target_hwnd, SW_RESTORE)
        fg_hwnd = int(user32.GetForegroundWindow() or 0)
        if fg_hwnd == target_hwnd:
            return
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        cur_tid = kernel32.GetCurrentThreadId()
        attached = False
        if fg_tid and cur_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.SetForegroundWindow(target_hwnd)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
    except Exception as e:
        _log(f"activate_window error for hwnd {hwnd}: {e}")


def close_window(hwnd: int) -> bool:
    """Pencereye kibarca 'kapan' der (WM_CLOSE; uygulama kaydet sorusunu kendisi sorar)."""
    try:
        target_hwnd = int(hwnd or 0)
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return False
        return bool(user32.PostMessageW(target_hwnd, WM_CLOSE, 0, 0))
    except Exception as e:
        _log(f"close_window error for hwnd {hwnd}: {e}")
        return False


def taskbar_autohide_get() -> bool:
    """Check if the Windows taskbar has auto-hide enabled."""
    try:
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
        return bool(state & ABS_AUTOHIDE)
    except Exception as e:
        _log(f"taskbar_autohide_get error: {e}")
        return False


def taskbar_autohide_set(enable: bool) -> None:
    """Enable or disable Windows taskbar auto-hide while preserving other flags (e.g. ABS_ALWAYSONTOP)."""
    try:
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
        if enable:
            new_state = state | ABS_AUTOHIDE
        else:
            new_state = state & ~ABS_AUTOHIDE
        abd.lParam = new_state
        shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))
    except Exception as e:
        _log(f"taskbar_autohide_set error: {e}")
