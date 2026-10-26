"""trayicons.py - Windows 11 notification-area (system tray) integration for Şerit dock.

Provides live discovery, icon extraction, physical and UIA activation, and acrylic
glass panel rendering for system tray icons (visible and overflow) inside Şerit dock.

Implementation notes:
- Windows 11 Build 22000+ hosts tray overflow icons inside
  `TopLevelWindowForOverflowXamlIsland` -> `Windows.UI.Composition.DesktopWindowContentBridge`.
  UI Automation (UIA) enumerates these elements without opening the native flyout.
- Registry `HKCU\\Control Panel\\NotifyIconSettings` stores `UIOrderList`, executable paths
  (with known folder GUIDs), tooltips, and raw cached PNG `IconSnapshot` bytes.
- Left-click uses UIA `InvokePattern` directly on the item's automation peer.
- Right-click works on-screen for promoted taskbar icons. Off-screen overflow icons
  fall back to window activation / executable launching due to Windows 11 XAML
  input routing constraints (documented limitation).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime
import os
from pathlib import Path
import struct
import sys
from typing import Any, Dict, List, Optional, Union
import winreg

import psutil
from PySide6.QtCore import QFileInfo, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QFileIconProvider

# Optional imports from serit package
try:
    import theme
except ImportError:
    theme = None

try:
    import winapi
except ImportError:
    winapi = None

# Fallback UI tokens if theme.py is not in path
COLOR_GLASS_TINT = getattr(theme, "COLOR_GLASS_TINT", QColor(15, 18, 24, int(255 * 0.70)))
COLOR_GLASS_OUTER_STROKE = getattr(theme, "COLOR_GLASS_OUTER_STROKE", QColor(0, 0, 0, int(255 * 0.45)))
COLOR_TEXT_PRIMARY = getattr(theme, "COLOR_TEXT_PRIMARY", QColor(255, 255, 255, 255))
COLOR_TEXT_SECONDARY = getattr(theme, "COLOR_TEXT_SECONDARY", QColor(255, 255, 255, int(255 * 0.72)))
COLOR_TEXT_MUTED = getattr(theme, "COLOR_TEXT_MUTED", QColor(255, 255, 255, int(255 * 0.40)))
COLOR_CHIP_HOVER = getattr(theme, "COLOR_CHIP_HOVER", QColor(255, 255, 255, int(255 * 0.12)))
COLOR_INDICATOR_PROMOTED = QColor("#60B5FF")

LOG_PATH = Path("D:/Apps/serit/serit.log")

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32

# Known folder GUIDs used in Windows 11 NotifyIconSettings
GUID_KNOWN_FOLDERS: Dict[str, str] = {
    "{6D809377-6AF0-444B-8957-A3773F02200E}": os.environ.get("ProgramFiles", r"C:\Program Files"),
    "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": os.environ.get("SystemRoot", r"C:\Windows"),
}

UIA_AUTOMATION_ID_PROPERTY_ID = 30011
UIA_INVOKE_PATTERN_ID = 10000

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


def _log(msg: str) -> None:
    """Append a timestamped message to D:/Apps/serit/serit.log without raising."""
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} [trayicons] {msg}\n")
    except Exception:
        pass


def _resolve_guid_path(path: str) -> str:
    """Resolve Windows KnownFolder GUID prefix in an executable path."""
    if not path:
        return ""
    for guid, target in GUID_KNOWN_FOLDERS.items():
        if path.startswith(guid):
            return target + path[len(guid):]
    return path


def _get_qapp() -> Optional[QApplication]:
    """Ensure a Q(Gui)Application instance exists for QPixmap operations."""
    app = QApplication.instance()
    if app is None:
        try:
            app = QApplication(sys.argv if sys.argv else ["serit"])
        except Exception as e:
            _log(f"Failed to create QApplication: {e}")
    return app


def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    path = QPainterPath()
    r = max(0.0, min(radius, min(rect.width(), rect.height()) / 2.0))
    path.addRoundedRect(rect, r, r)
    return path


def _read_registry_tray_settings() -> List[Dict[str, Any]]:
    """Read registered tray items from HKCU\\Control Panel\\NotifyIconSettings.

    Ordered according to UIOrderList.
    """
    entries: List[Dict[str, Any]] = []
    key_path = r"Control Panel\NotifyIconSettings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            try:
                raw_order, _ = winreg.QueryValueEx(key, "UIOrderList")
                chunks = [raw_order[i:i + 8] for i in range(0, len(raw_order), 8)]
                subkeys = [str(struct.unpack("<Q", c)[0]) for c in chunks if len(c) == 8]
            except Exception:
                num_subkeys, _, _ = winreg.QueryInfoKey(key)
                subkeys = [winreg.EnumKey(key, i) for i in range(num_subkeys)]

            for k in subkeys:
                try:
                    with winreg.OpenKey(key, k) as sk:
                        _, num_values, _ = winreg.QueryInfoKey(sk)
                        d = dict(winreg.EnumValue(sk, j)[:2] for j in range(num_values))
                        ep = _resolve_guid_path(d.get("ExecutablePath", ""))
                        entries.append({
                            "key": k,
                            "exe": ep,
                            "tooltip": str(d.get("InitialTooltip", "") or ""),
                            "icon_bytes": d.get("IconSnapshot") if isinstance(d.get("IconSnapshot"), bytes) else None,
                            "guid": str(d.get("IconGuid", "") or ""),
                            "uid": d.get("UID"),
                        })
                except Exception:
                    pass
    except Exception as e:
        _log(f"Registry query error: {e}")
    return entries


def _get_active_uia_tray_elements() -> List[Dict[str, Any]]:
    """Enumerate live tray icon elements via UIAutomationCore without opening any flyouts.

    Searches:
    1. TopLevelWindowForOverflowXamlIsland (hidden / overflow icons)
    2. Shell_TrayWnd (promoted taskbar notification icons)
    """
    items: List[Dict[str, Any]] = []
    try:
        try:
            ole32.CoInitialize(None)
        except Exception:
            pass

        import comtypes.client
        uia = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)

        # 1. Overflow Window (TopLevelWindowForOverflowXamlIsland)
        hwnd_overflow = user32.FindWindowW("TopLevelWindowForOverflowXamlIsland", None)
        if hwnd_overflow:
            child_hwnds: List[int] = []

            def _enum_child(hwnd: int, _lparam: int) -> bool:
                child_hwnds.append(hwnd)
                return True

            enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_enum_child)
            user32.EnumChildWindows(hwnd_overflow, enum_proc, 0)

            for ch in child_hwnds:
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(ch, cls_buf, 256)
                cls_name = cls_buf.value
                if "DesktopWindowContentBridge" in cls_name or "InputSite" in cls_name:
                    try:
                        el = automation.ElementFromHandle(ch)
                        cond = automation.CreatePropertyCondition(
                            UIA_AUTOMATION_ID_PROPERTY_ID, "NotifyItemIcon"
                        )
                        arr = el.FindAll(uia.TreeScope_Descendants, cond)
                        for i in range(arr.Length):
                            it = arr.GetElement(i)
                            raw_name = it.CurrentName or ""
                            clean_name = raw_name.strip()
                            rect = it.CurrentBoundingRectangle
                            items.append({
                                "name": clean_name,
                                "raw_name": raw_name,
                                "promoted": False,
                                "rect": (rect.left, rect.top, rect.right, rect.bottom),
                                "is_offscreen": bool(it.CurrentIsOffscreen),
                                "uia_element": it,
                            })
                        break
                    except Exception as e:
                        _log(f"Error reading overflow UIA elements: {e}")

        # 2. Promoted Icons on Main Taskbar (Shell_TrayWnd)
        hwnd_tray = user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd_tray:
            try:
                el_tray = automation.ElementFromHandle(hwnd_tray)
                cond = automation.CreatePropertyCondition(
                    UIA_AUTOMATION_ID_PROPERTY_ID, "NotifyItemIcon"
                )
                arr_tray = el_tray.FindAll(uia.TreeScope_Descendants, cond)
                for i in range(arr_tray.Length):
                    it = arr_tray.GetElement(i)
                    raw_name = it.CurrentName or ""
                    clean_name = raw_name.strip()
                    rect = it.CurrentBoundingRectangle
                    items.append({
                        "name": clean_name,
                        "raw_name": raw_name,
                        "promoted": True,
                        "rect": (rect.left, rect.top, rect.right, rect.bottom),
                        "is_offscreen": bool(it.CurrentIsOffscreen),
                        "uia_element": it,
                    })
            except Exception as e:
                _log(f"Error reading Shell_TrayWnd promoted UIA elements: {e}")

    except Exception as e:
        _log(f"UI Automation query failed: {e}")

    return items


def list_tray_items() -> List[Dict[str, Any]]:
    """Enumerate system tray items on Windows 11.

    Returns:
        List of item dictionaries:
        [{
            'name': str,
            'exe': str,
            'running': bool,
            'promoted': bool,
            'uia_available': bool,
            'tooltip': str,
            'icon_bytes': Optional[bytes],
            'rect': Tuple[int, int, int, int],
            'is_offscreen': bool,
            'uia_element': Optional[Any]
        }]
    """
    _get_qapp()
    registry_items = _read_registry_tray_settings()
    active_uia = _get_active_uia_tray_elements()

    # Pre-map running processes for quick matching
    running_procs: Dict[str, Any] = {}
    try:
        for p in psutil.process_iter(["name", "exe", "pid"]):
            try:
                info = p.info
                if info.get("exe"):
                    running_procs[info["exe"].lower()] = info
                if info.get("name"):
                    running_procs[info["name"].lower()] = info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        _log(f"psutil process enumeration error: {e}")

    results: List[Dict[str, Any]] = []

    # Match each live UIA item with registry metadata
    for uia_item in active_uia:
        clean_name = uia_item.get("name", "")
        first_line = clean_name.split("\n")[0].strip()
        low_name = clean_name.lower()

        matched_reg: Optional[Dict[str, Any]] = None

        # Custom / special app aliases
        if "dikte" in low_name:
            for r in registry_items:
                if "pythonw" in r["exe"].lower() or "dikte" in r["exe"].lower():
                    matched_reg = r
                    break
        elif "cmdpal" in low_name:
            for r in registry_items:
                if "autohotkey" in r["exe"].lower() or "tapaj" in r["tooltip"].lower():
                    matched_reg = r
                    break
        elif "security" in low_name:
            for r in registry_items:
                if "security" in r["exe"].lower():
                    matched_reg = r
                    break
        elif "awake" in low_name:
            for r in registry_items:
                if "awake" in r["exe"].lower():
                    matched_reg = r
                    break
        elif "powertoys" in low_name:
            for r in registry_items:
                if "powertoys.exe" in r["exe"].lower() or "powertoys v" in r["tooltip"].lower():
                    matched_reg = r
                    break

        if not matched_reg:
            # First pass: direct substring match on tooltip or base exe name
            for r in registry_items:
                rexe_name = os.path.basename(r["exe"]).lower()
                rexe_base = os.path.splitext(rexe_name)[0]
                rtip = r["tooltip"].lower()
                if (rtip and (rtip in low_name or low_name in rtip)) or (rexe_base and rexe_base in low_name):
                    matched_reg = r
                    if os.path.exists(r["exe"]):
                        break

            # Second pass: token match excluding common stopwords
            if not matched_reg:
                stopwords = {"not", "and", "the", "for", "with", "app", "application", "windows", "desktop"}
                tokens = [tok for tok in low_name.split() if len(tok) >= 3 and tok not in stopwords]
                for r in registry_items:
                    rexe_name = os.path.basename(r["exe"]).lower()
                    rexe_base = os.path.splitext(rexe_name)[0]
                    if any(tok in rexe_base for tok in tokens):
                        matched_reg = r
                        if os.path.exists(r["exe"]):
                            break

        exe_path = matched_reg["exe"] if matched_reg else ""
        icon_bytes = matched_reg["icon_bytes"] if matched_reg else None
        tooltip = matched_reg["tooltip"] if matched_reg and matched_reg.get("tooltip") else clean_name

        # Check running state via psutil or presence in UIA
        running = True
        if exe_path:
            running = (exe_path.lower() in running_procs) or \
                      (os.path.basename(exe_path).lower() in running_procs)

        results.append({
            "name": first_line or clean_name,
            "full_name": clean_name,
            "exe": exe_path,
            "running": running,
            "promoted": bool(uia_item.get("promoted", False)),
            "uia_available": True,
            "tooltip": tooltip,
            "icon_bytes": icon_bytes,
            "rect": uia_item.get("rect", (0, 0, 0, 0)),
            "is_offscreen": bool(uia_item.get("is_offscreen", True)),
            "uia_element": uia_item.get("uia_element"),
        })

    return results


def _crop_transparent_borders(img: QImage) -> QImage:
    """Trim empty transparent margins so the icon graphic centers and scales uniformly."""
    w, h = img.width(), img.height()
    if w <= 4 or h <= 4:
        return img

    if img.format() not in (QImage.Format.Format_ARGB32, QImage.Format.Format_ARGB32_Premultiplied):
        img = img.convertToFormat(QImage.Format.Format_ARGB32)

    try:
        b = img.constBits()
        b_len = img.sizeInBytes()
        mv = memoryview(b).cast("B")[:b_len]
        bpl = img.bytesPerLine()

        # ARGB32 byte layout on Windows x64 is B, G, R, A (alpha at byte index 3)
        min_y = 0
        while min_y < h:
            row = mv[min_y * bpl: (min_y + 1) * bpl]
            if any(a > 15 for a in row[3::4]):
                break
            min_y += 1

        if min_y >= h:
            return img

        max_y = h - 1
        while max_y > min_y:
            row = mv[max_y * bpl: (max_y + 1) * bpl]
            if any(a > 15 for a in row[3::4]):
                break
            max_y -= 1

        min_x = w
        max_x = 0
        for y in range(min_y, max_y + 1):
            alphas = mv[y * bpl + 3: (y + 1) * bpl: 4]
            for x, a in enumerate(alphas):
                if a > 15:
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x

        if max_x < min_x:
            return img

        content_w = max_x - min_x + 1
        content_h = max_y - min_y + 1
        # Avoid cropping if content already fills >= 90% of the image
        if content_w >= int(w * 0.90) and content_h >= int(h * 0.90):
            return img

        return img.copy(min_x, min_y, content_w, content_h)
    except Exception:
        return img


def get_tray_icons(items: List[Dict[str, Any]]) -> Dict[str, QPixmap]:
    """Load or extract high-DPI QPixmap icons for the provided tray items."""
    _get_qapp()
    provider = QFileIconProvider()
    icons: Dict[str, QPixmap] = {}

    for it in items:
        name = it.get("name", "")
        exe = it.get("exe", "")
        icon_bytes = it.get("icon_bytes")
        pm = QPixmap()

        # 1. Dedicated custom icon files (e.g. Dikte)
        if "dikte" in name.lower():
            known_dikte_ico = "D:/Apps/dikte/dikte.ico"
            if os.path.exists(known_dikte_ico):
                pm = QFileIconProvider().icon(QFileInfo(known_dikte_ico)).pixmap(64, 64)

        # 2. Dynamic tray status snapshots (e.g. PowerToys Awake coffee cup status)
        if pm.isNull() and "awake" in name.lower() and icon_bytes:
            try:
                img = QImage()
                if img.loadFromData(icon_bytes):
                    pm = QPixmap.fromImage(img)
            except Exception:
                pass

        # 3. WindowsApps package assets (e.g. WhatsApp, Store apps)
        if pm.isNull() and exe and "windowsapps" in exe.lower():
            try:
                pkg_dir = os.path.dirname(os.path.dirname(exe)) if os.path.basename(os.path.dirname(exe)).lower() == "app" else os.path.dirname(exe)
                assets_dir = os.path.join(pkg_dir, "Assets")
                if os.path.isdir(assets_dir):
                    for cand in [
                        "AppList.targetsize-256.png",
                        "AppList.targetsize-256_altform-unplated.png",
                        "AppList.scale-200.png",
                        "logo.ico",
                        "StoreLogo.scale-200.png",
                    ]:
                        cand_path = os.path.join(assets_dir, cand)
                        if os.path.exists(cand_path):
                            cand_pm = QPixmap(cand_path)
                            if not cand_pm.isNull() and cand_pm.width() >= 32:
                                pm = cand_pm
                                break
            except Exception:
                pass

        # 4. High-resolution executable icon (up to 256x256)
        if pm.isNull() and exe and os.path.exists(exe):
            exe_name = os.path.basename(exe).lower()
            if "python" not in exe_name:
                try:
                    ico = provider.icon(QFileInfo(exe))
                    pm_hi = ico.pixmap(64, 64)
                    if not pm_hi.isNull() and pm_hi.width() >= 32:
                        pm = pm_hi
                except Exception:
                    pass

        # 4. Fallback to raw PNG IconSnapshot cached in Windows registry
        if pm.isNull() and icon_bytes and isinstance(icon_bytes, bytes):
            try:
                img = QImage()
                if img.loadFromData(icon_bytes):
                    pm = QPixmap.fromImage(img)
            except Exception:
                pass

        # 5. Last resort: Standard executable file icon
        if pm.isNull() and exe and os.path.exists(exe):
            try:
                pm = provider.icon(QFileInfo(exe)).pixmap(32, 32)
            except Exception:
                pass

        # Normalize boundaries (trim disproportionate transparent margins from legacy icons)
        if not pm.isNull():
            cropped_img = _crop_transparent_borders(pm.toImage())
            pm = QPixmap.fromImage(cropped_img)

        icons[name] = pm

    return icons


def activate(item: Dict[str, Any], button: str = "left") -> bool:
    """Activate or interact with a system tray item.

    Best effort:
    - Left-click:
      1. Tries UIA InvokePattern on the item's automation peer.
      2. If on-screen (promoted), simulates mouse click.
      3. Fallback: Brings app's main window to foreground via winapi.activate_or_minimize.
    - Right-click:
      1. If on-screen (promoted): Simulates physical right-click.
      2. If off-screen (in overflow): Documents limitation and focuses window.

    Never raises; logs actions and errors to serit.log.
    """
    btn = (button or "left").lower()
    name = item.get("name", "Unknown")
    _log(f"activate() called for {name!r} button={btn!r}")

    try:
        rect = item.get("rect", (0, 0, 0, 0))
        is_offscreen = item.get("is_offscreen", True)
        on_screen = (not is_offscreen) and (rect[2] > rect[0]) and (rect[3] > rect[1])

        # 1. On-screen simulated click (promoted icons)
        if on_screen:
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            user32.SetCursorPos(cx, cy)
            if btn == "right":
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            else:
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            _log(f"Performed on-screen click for {name!r} at ({cx}, {cy})")
            return True

        # 2. UIA Invoke Pattern (works for off-screen overflow items on left-click)
        if btn == "left" and item.get("uia_element"):
            try:
                it = item["uia_element"]
                pat = it.GetCurrentPattern(UIA_INVOKE_PATTERN_ID)
                if pat:
                    import comtypes.client
                    uia = comtypes.client.GetModule("UIAutomationCore.dll")
                    invoker = pat.QueryInterface(uia.IUIAutomationInvokePattern)
                    invoker.Invoke()
                    _log(f"Successfully invoked UIA InvokePattern for {name!r}")
                    return True
            except Exception as e:
                _log(f"UIA InvokePattern failed for {name!r}: {e}")

        # 3. Off-screen right-click limitation or fallback
        if btn == "right" and not on_screen:
            _log(
                f"Right-click on off-screen overflow item {name!r} cannot receive Win32 "
                f"clicks without opening native flyout. Falling back to window focus."
            )

        # 4. Fallback: activate / restore top-level application window
        exe = item.get("exe", "")
        if exe and winapi:
            try:
                exe_lower = exe.lower()
                exe_base = os.path.basename(exe).lower()
                for w in winapi.list_windows():
                    w_exe = str(w.get("exe", "")).lower()
                    if w_exe == exe_lower or os.path.basename(w_exe) == exe_base:
                        winapi.activate_or_minimize(w["hwnd"])
                        _log(f"Focused window HWND {w['hwnd']:#x} for {name!r}")
                        return True
            except Exception as e:
                _log(f"Window search failed for {name!r}: {e}")

        # 5. Last resort: launch executable via QDesktopServices
        if exe and os.path.exists(exe):
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(exe))
                _log(f"Launched executable {exe!r} for {name!r}")
                return True
            except Exception as e:
                _log(f"Failed to launch executable {exe!r}: {e}")

    except Exception as e:
        _log(f"Unexpected error activating {name!r}: {e}")

    return False


def draw_tray_panel(
    p: QPainter,
    rect: QRectF,
    items: List[Dict[str, Any]],
    icons: Union[Dict[str, QPixmap], List[QPixmap], None],
    hover_index: int = -1,
) -> List[QRectF]:
    """Render the acrylic glass grid of tray icons matching Şerit dock theme style.

    Args:
        p: Target QPainter.
        rect: Bounding rect of the panel card.
        items: List of tray item dictionaries from list_tray_items().
        icons: Mapping of item name -> QPixmap or list of QPixmaps aligned with items.
        hover_index: Index of currently hovered tile (-1 if none).

    Returns:
        List of QRectF hit boxes for each tray item tile.
    """
    hit_rects: List[QRectF] = []
    if not items or rect.width() <= 10 or rect.height() <= 10:
        return hit_rects

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    try:
        w = float(rect.width())
        h = float(rect.height())
        rx = float(rect.x())
        ry = float(rect.y())
        panel_rect = QRectF(rx + 0.5, ry + 0.5, w - 1.0, h - 1.0)
        card_radius = 18.0

        panel_path = _rounded_path(panel_rect, card_radius)

        # 1. Base dark acrylic glass fill
        p.fillPath(panel_path, COLOR_GLASS_TINT)

        # 2. Specular top sheen
        p.save()
        p.setClipPath(panel_path)
        sheen_grad = QLinearGradient(rx, ry, rx, ry + 6.0)
        sheen_grad.setColorAt(0.0, QColor(255, 255, 255, 55))
        sheen_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(rx + 1.0, ry + 1.0, w - 2.0, 6.0), sheen_grad)
        p.restore()

        # 3. Dual boundary stroke (inner specular rim + outer hairline)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        p.drawPath(panel_path)

        # 4. Header / Tooltip Bar (Top 34px)
        header_h = 34.0
        header_rect = QRectF(rx + 14.0, ry + 8.0, w - 28.0, 20.0)

        # Choose header text based on hover_index
        hovered_item = items[hover_index] if (0 <= hover_index < len(items)) else None
        if hovered_item:
            title_text = hovered_item.get("name", "")
            sub_text = hovered_item.get("tooltip", "")
            if sub_text and sub_text != title_text:
                display_text = f"{title_text} — {sub_text}"
            else:
                display_text = title_text
        else:
            display_text = f"Gizli simgeler ({len(items)})"

        # Render Header text
        header_font = QFont("Segoe UI Variable Display, Segoe UI, sans-serif")
        header_font.setPixelSize(12)
        header_font.setWeight(QFont.Weight.DemiBold if hovered_item else QFont.Weight.Medium)
        p.setFont(header_font)
        p.setPen(COLOR_TEXT_PRIMARY if hovered_item else COLOR_TEXT_MUTED)

        fm = QFontMetricsF(header_font)
        elided_header = fm.elidedText(display_text, Qt.TextElideMode.ElideRight, header_rect.width())
        p.drawText(header_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_header)

        # Hairline separator beneath header
        sep_y = ry + header_h
        sep_pen = QPen(QColor(255, 255, 255, 20), 1.0)
        p.setPen(sep_pen)
        p.drawLine(QPointF(rx + 12.0, sep_y), QPointF(rx + w - 12.0, sep_y))

        # 5. Grid of Icon Tiles (Tile box 42x42, icon 28x28 centered)
        tile_w = 42.0
        tile_h = 42.0
        target_icon_size = 28.0
        gap = 6.0
        pad_x = 12.0
        grid_top = sep_y + 8.0

        available_w = w - 2 * pad_x
        cols = max(1, int((available_w + gap) / (tile_w + gap)))
        total_grid_w = cols * tile_w + (cols - 1) * gap
        offset_x = rx + pad_x + max(0.0, (available_w - total_grid_w) / 2.0)

        for i, item in enumerate(items):
            row = i // cols
            col = i % cols
            tx = offset_x + col * (tile_w + gap)
            ty = grid_top + row * (tile_h + gap)

            tile_rect = QRectF(tx, ty, tile_w, tile_h)
            hit_rects.append(tile_rect)

            is_hov = (i == hover_index)
            tile_path = _rounded_path(tile_rect, 10.0)

            # Uniform glass tile base for consistent visual weight
            if is_hov:
                p.fillPath(tile_path, COLOR_CHIP_HOVER)
                p.setPen(QPen(QColor(255, 255, 255, 80), 1.0))
            else:
                p.fillPath(tile_path, QColor(255, 255, 255, 10))
                p.setPen(QPen(QColor(255, 255, 255, 16), 1.0))
            p.drawPath(tile_path)

            # Retrieve Icon
            name = item.get("name", "")
            pm = None
            if isinstance(icons, dict):
                pm = icons.get(name) or icons.get(item.get("exe", ""))
            elif isinstance(icons, list) and i < len(icons):
                pm = icons[i]

            # Fallback icon extraction from item directly
            if (pm is None or pm.isNull()) and item.get("icon_bytes"):
                try:
                    img = QImage()
                    if img.loadFromData(item["icon_bytes"]):
                        pm = QPixmap.fromImage(img)
                except Exception:
                    pass

            if pm is not None and not pm.isNull():
                img = pm.toImage()
                img_w = float(img.width())
                img_h = float(img.height())
                if img_w > 0 and img_h > 0:
                    scale = min(target_icon_size / img_w, target_icon_size / img_h)
                    draw_w = round(img_w * scale, 1)
                    draw_h = round(img_h * scale, 1)
                    cx = tx + (tile_w - draw_w) / 2.0
                    cy = ty + (tile_h - draw_h) / 2.0
                    dest_rect = QRectF(cx, cy, draw_w, draw_h)
                    p.drawImage(dest_rect, img)
            else:
                # Fallback placeholder glyph centered
                icon_rect = QRectF(
                    tx + (tile_w - target_icon_size) / 2.0,
                    ty + (tile_h - target_icon_size) / 2.0,
                    target_icon_size,
                    target_icon_size,
                )
                fallback_path = _rounded_path(icon_rect, 6.0)
                p.fillPath(fallback_path, QColor(255, 255, 255, 25))
                p.setPen(COLOR_TEXT_MUTED)
                p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                glyph = name[:1].upper() if name else "?"
                p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, glyph)

            # Promoted status micro-indicator dot
            if item.get("promoted"):
                dot_x = tx + tile_w - 6.0
                dot_y = ty + 6.0
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(COLOR_INDICATOR_PROMOTED))
                p.drawEllipse(QPointF(dot_x, dot_y), 2.5, 2.5)

    except Exception as e:
        _log(f"draw_tray_panel error: {e}")
    finally:
        p.restore()

    return hit_rects
