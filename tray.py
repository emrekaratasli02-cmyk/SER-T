"""tray.py - System notification area overflow button and helper for Şerit dock.

Provides Win32 SendInput automation to trigger the native Windows 11 'Show hidden icons'
notification-area overflow flyout, taskbar reveal helpers, and a hardware-rendered
glass pill chevron button matching the Şerit theme.py specification.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import time
import ctypes
import ctypes.wintypes as w
from typing import Union

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

try:
    import theme
except ImportError:
    from . import theme  # type: ignore[no-redef]

__all__ = [
    "open_hidden_icons",
    "reveal_taskbar",
    "draw_chevron_button",
    "INPUT",
    "KEYBDINPUT",
    "MOUSEINPUT",
    "HARDWAREINPUT",
]

# --- Win32 Libraries ---
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

# --- Win32 Constants ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_B = 0x42
VK_LWIN = 0x5B

SW_SHOWNA = 8

LOG_PATH = Path("D:/Apps/serit/serit.log")


def _log(msg: str) -> None:
    """Append a timestamped message to serit.log without raising exceptions."""
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [tray] {msg}\n")
    except Exception:
        pass


# --- Win32 Structures (64-bit precise alignment) ---
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", w.DWORD),
        ("wParamL", w.WORD),
        ("wParamH", w.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_u",)
    _fields_ = [
        ("type", w.DWORD),
        ("_u", _INPUT_UNION),
    ]


# --- Explicit Win32 Function Signatures ---
user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT

user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.FindWindowW.restype = w.HWND

user32.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
user32.ShowWindowAsync.restype = w.BOOL


def _make_key_input(vk: int, keyup: bool = False) -> INPUT:
    """Helper to construct a single keyboard INPUT structure."""
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if keyup else 0,
        time=0,
        dwExtraInfo=0,
    )
    return inp


def reveal_taskbar() -> bool:
    """Ensure Windows taskbar (Shell_TrayWnd) is made visible if auto-hidden."""
    try:
        hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if not hwnd:
            _log("reveal_taskbar: Shell_TrayWnd window not found")
            return False
        res = user32.ShowWindowAsync(hwnd, SW_SHOWNA)
        return bool(res)
    except Exception as e:
        _log(f"reveal_taskbar error: {e}")
        return False


def open_hidden_icons() -> bool:
    """Programmatically toggle/open the Windows 11 notification area overflow flyout.

    On Windows 11 (build 22621+ through 26300+), the taskbar and tray are hosted in
    XAML islands (TopLevelWindowForOverflowXamlIsland). Win+B is the native Windows
    shell accessibility shortcut that moves focus to the 'Show hidden icons' chevron
    (and reveals the taskbar if auto-hidden). Sending Enter (VK_RETURN) then triggers
    the native flyout activation without requiring brittle UIA COM interfaces.

    Returns:
        True if all input events were successfully dispatched by user32.SendInput.
    """
    try:
        reveal_taskbar()

        # 1. Dispatch Win + B chord (Down LWIN, Down B, Up B, Up LWIN)
        chord = (INPUT * 4)(
            _make_key_input(VK_LWIN, keyup=False),
            _make_key_input(VK_B, keyup=False),
            _make_key_input(VK_B, keyup=True),
            _make_key_input(VK_LWIN, keyup=True),
        )
        sent_chord = user32.SendInput(4, chord, ctypes.sizeof(INPUT))
        if sent_chord != 4:
            _log(f"open_hidden_icons: SendInput Win+B partial dispatch ({sent_chord}/4)")
            return False

        # 2. Allow Explorer shell brief focus animation to settle
        time.sleep(0.050)

        # 3. Dispatch Enter (VK_RETURN) to activate the focused chevron
        enter_press = (INPUT * 2)(
            _make_key_input(VK_RETURN, keyup=False),
            _make_key_input(VK_RETURN, keyup=True),
        )
        sent_enter = user32.SendInput(2, enter_press, ctypes.sizeof(INPUT))
        if sent_enter != 2:
            _log(f"open_hidden_icons: SendInput Enter partial dispatch ({sent_enter}/2)")
            return False

        return True
    except Exception as e:
        _log(f"open_hidden_icons error: {e}")
        return False


def draw_chevron_button(
    p: QPainter,
    rect: Union[QRectF, QRect],
    hover_t: float = 0.0,
    open_state: bool = False,
) -> None:
    """Draw a glass pill button with a '^' chevron icon matching Şerit theme.py style.

    Args:
        p: Active QPainter instance.
        rect: Bounding rectangle (QRectF or QRect).
        hover_t: Hover interpolation value in [0.0, 1.0].
        open_state: Whether the tray overflow flyout is active / open.
    """
    rf = QRectF(rect)
    if rf.width() <= 2.0 or rf.height() <= 2.0:
        return

    # Pill radius = half of minor axis
    radius = min(rf.width(), rf.height()) / 2.0

    # 1. Glass capsule background & specular highlights
    theme.draw_glass_capsule(
        p,
        rf,
        radius=radius,
        is_hovered=(hover_t > 0.0),
        hover_opacity=hover_t,
        show_grain=False,
    )

    # 2. Active pressed fill overlay when open_state is active
    if open_state:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active_path = theme.rounded_path(rf, radius)
        p.fillPath(active_path, theme.COLOR_CHIP_PRESS)
        p.restore()

    # 3. Chevron stroke path
    cx = rf.center().x()
    cy = rf.center().y()

    # Chevron proportional sizing
    cw = min(10.0, max(6.0, rf.width() * 0.40))
    ch = min(5.0, max(3.0, cw * 0.50))
    dx = cw / 2.0
    dy = ch / 2.0

    # Slight optical adjustment
    cy_opt = cy + (0.5 if not open_state else -0.5)

    path = QPainterPath()
    if not open_state:
        # Caret pointing UP (^)
        path.moveTo(cx - dx, cy_opt + dy)
        path.lineTo(cx, cy_opt - dy)
        path.lineTo(cx + dx, cy_opt + dy)
    else:
        # Caret pointing DOWN (v) when flyout is open
        path.moveTo(cx - dx, cy_opt - dy)
        path.lineTo(cx, cy_opt + dy)
        path.lineTo(cx + dx, cy_opt - dy)

    # Chevron stroke color interpolates between secondary (alpha 184) and primary (alpha 255)
    t_clamped = max(0.0, min(1.0, hover_t))
    alpha = 255 if open_state else int(184 + (255 - 184) * t_clamped)
    stroke_col = QColor(255, 255, 255, alpha)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(stroke_col, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()
