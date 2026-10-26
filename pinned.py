"""pinned.py - Pinned application management and tile drawing for Şerit dock.

Provides:
  - load_default_pins(): Resolves default pinned shortcuts from Windows TaskBar.
  - merge_tiles(pins, groups): Unifies pinned apps and running app groups into a consistent tile list.
  - reorder(pins, from_idx, to_idx): Pure list reordering helper.
  - pin(pins, tile): Pure helper adding a tile to pinned list without duplicates.
  - unpin(pins, key): Pure helper removing a pinned item by path key.
  - drag_target_index(tile_centers_x, mouse_x): Calculates target slot index for drag operations.
  - launch(path): Launches not-running pinned applications.
  - draw_tile(p, rect, tile, pixmap, hover_t, press_scale, dot_count): Renders a 46x46 dark glass tile.
  - draw_label_bubble(p, anchor_center_top, text): Renders dark glass tooltip bubble above tile.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import QFileInfo, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QPainter,
    QPen,
    QPixmap,
)

import theme
import winapi

# ==============================================================================
# 1. GEOMETRY & DIMENSION TOKENS
# ==============================================================================

TILE: float = 46.0
ICON: float = 30.0
TILE_SIZE: float = 46.0
ICON_SIZE: float = 30.0
TILE_RADIUS: float = 12.0
GAP: float = 6.0
BORDER_WIDTH: float = 1.0

# Bubble tooltip tokens
BUBBLE_RADIUS: float = 8.0
BUBBLE_PAD_V: float = 6.0
BUBBLE_PAD_H: float = 10.0
BUBBLE_FONT_SIZE: float = 11.0
BUBBLE_GAP: float = 6.0

# Indicator tokens (matching theme.py metrics)
INDICATOR_ACTIVE_W: float = 12.0
INDICATOR_ACTIVE_H: float = 3.0
INDICATOR_ACTIVE_R: float = 1.5
INDICATOR_DOT_SIZE: float = 4.0
INDICATOR_DOT_SPACING: float = 3.5
INDICATOR_GAP: float = 3.5

# ==============================================================================
# 2. COLOR & MATERIAL TOKENS
# ==============================================================================

COLOR_TILE_DARK_BASE: QColor = QColor(15, 18, 24, int(255 * 0.45))
COLOR_TILE_FILL_BASE: QColor = QColor(255, 255, 255, int(255 * 0.07))
COLOR_TILE_FILL_HOVER: QColor = QColor(255, 255, 255, int(255 * 0.13))
COLOR_TILE_BORDER: QColor = QColor(255, 255, 255, int(255 * 0.10))
COLOR_TILE_BORDER_HOVER: QColor = QColor(255, 255, 255, int(255 * 0.14))

COLOR_BUBBLE_BG: QColor = QColor(18, 22, 30, int(255 * 0.94))
COLOR_BUBBLE_BORDER: QColor = QColor(255, 255, 255, int(255 * 0.15))


# ==============================================================================
# 3. INTERNAL HELPERS
# ==============================================================================


def _norm_key(path: str) -> str:
    """Normalize file path for robust case-insensitive matching."""
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(path))


# ==============================================================================
# 4. PIN MODEL HELPERS
# ==============================================================================


def load_default_pins() -> List[Dict[str, str]]:
    """Resolve default pinned applications from Windows TaskBar shortcuts folder.

    Scans %APPDATA%/Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar/*.lnk
    and resolves target path with QFileInfo(lnk).symLinkTarget().
    File Explorer.lnk typically resolves empty in Windows, so it is mapped to
    C:/Windows/explorer.exe.

    Returns:
        list of dicts [{'path': str, 'name': str}]
    """
    taskbar_dir = os.path.expandvars(
        r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
    )
    pins: List[Dict[str, str]] = []
    if not os.path.isdir(taskbar_dir):
        return pins

    import glob

    pattern = os.path.join(taskbar_dir, "*.lnk")
    seen_keys: set[str] = set()

    for lnk in sorted(glob.glob(pattern)):
        fi = QFileInfo(lnk)
        target = fi.symLinkTarget()
        name = fi.baseName()

        if not target:
            # File Explorer resolves empty on Windows TaskBar shortcut
            base_low = name.lower()
            fn_low = fi.fileName().lower()
            if "explorer" in base_low or "explorer" in fn_low or "gezgin" in base_low:
                windir = os.environ.get("WINDIR", "C:\\Windows")
                target = os.path.join(windir, "explorer.exe")

        if target:
            norm_target = os.path.normpath(target)
            k = _norm_key(norm_target)
            if k not in seen_keys:
                seen_keys.add(k)
                pins.append({"path": norm_target, "name": name})

    return pins


def merge_tiles(
    pins: List[Dict[str, str]],
    groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge pinned apps and running app groups into unified tile list.

    Pinned apps appear first in their defined pin order, with running state
    filled in if the application is currently open. Running apps that
    are not pinned follow in their original group order.
    Path matching is case-insensitive.

    Returns:
        list of tile dicts:
            {
                'key': str (lowercased exe path),
                'exe': str,
                'name': str,
                'pinned': bool,
                'running': bool,
                'active': bool,
                'hwnds': list[int],
                'count': int,
            }
    """
    running_by_key: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        exe = g.get("exe") or ""
        k = _norm_key(exe)
        if k and k not in running_by_key:
            running_by_key[k] = g

    tiles: List[Dict[str, Any]] = []
    claimed_keys: set[str] = set()
    seen_pin_keys: set[str] = set()

    # 1. Pinned apps in pin order
    for p in pins:
        p_path = p.get("path") or p.get("exe") or ""
        p_key = _norm_key(p_path)
        if not p_key or p_key in seen_pin_keys:
            continue
        seen_pin_keys.add(p_key)

        matched_grp = running_by_key.get(p_key)
        if matched_grp is not None:
            claimed_keys.add(p_key)
            name = p.get("name") or matched_grp.get("name") or ""
            if not name:
                name = winapi.get_app_name(matched_grp.get("exe") or p_path)
            tiles.append({
                "key": p_key,
                "exe": matched_grp.get("exe") or p_path,
                "name": name,
                "pinned": True,
                "running": True,
                "active": bool(matched_grp.get("active", False)),
                "hwnds": list(matched_grp.get("hwnds", [])),
                "count": int(matched_grp.get("count", len(matched_grp.get("hwnds", [])))),
            })
        else:
            name = p.get("name") or ""
            if not name:
                name = winapi.get_app_name(p_path)
            tiles.append({
                "key": p_key,
                "exe": p_path,
                "name": name,
                "pinned": True,
                "running": False,
                "active": False,
                "hwnds": [],
                "count": 0,
            })

    # 2. Running unpinned apps in their original group order
    for g in groups:
        exe = g.get("exe") or ""
        k = _norm_key(exe)
        if not k or k in claimed_keys:
            continue
        claimed_keys.add(k)
        name = g.get("name") or ""
        if not name:
            name = winapi.get_app_name(exe)
        tiles.append({
            "key": k,
            "exe": exe,
            "name": name,
            "pinned": False,
            "running": True,
            "active": bool(g.get("active", False)),
            "hwnds": list(g.get("hwnds", [])),
            "count": int(g.get("count", len(g.get("hwnds", [])))),
        })

    return tiles


def reorder(pins: List[Dict[str, str]], from_idx: int, to_idx: int) -> List[Dict[str, str]]:
    """Pure reordering helper: returns a new list with element moved from from_idx to to_idx."""
    if not pins:
        return []
    res = list(pins)
    n = len(res)
    if 0 <= from_idx < n and 0 <= to_idx < n:
        item = res.pop(from_idx)
        res.insert(to_idx, item)
    return res


def pin(pins: List[Dict[str, str]], tile: Dict[str, Any]) -> List[Dict[str, str]]:
    """Pure helper: returns new pins list with tile added if not already pinned."""
    path = tile.get("path") or tile.get("exe") or ""
    k = _norm_key(path)
    if not k:
        return list(pins)

    # Check if already present
    for p in pins:
        pk = _norm_key(p.get("path") or p.get("exe") or "")
        if pk == k:
            return list(pins)

    name = tile.get("name") or ""
    if not name:
        name = winapi.get_app_name(path)

    new_pin = {"path": path, "name": name}
    return list(pins) + [new_pin]


def unpin(pins: List[Dict[str, str]], key: str) -> List[Dict[str, str]]:
    """Pure helper: returns new pins list with item matching key removed."""
    target_k = _norm_key(key)
    if not target_k:
        return list(pins)
    return [
        p for p in pins
        if _norm_key(p.get("path") or p.get("exe") or "") != target_k
    ]


def drag_target_index(tile_centers_x: List[float], mouse_x: float) -> int:
    """Calculate the target tile slot index for drag operations given centers and mouse x."""
    if not tile_centers_x:
        return 0
    best_idx = 0
    best_dist = abs(tile_centers_x[0] - mouse_x)
    for i in range(1, len(tile_centers_x)):
        d = abs(tile_centers_x[i] - mouse_x)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def launch(path: str) -> bool:
    """Launch application at path using QDesktopServices.openUrl."""
    if not path:
        return False
    url = QUrl.fromLocalFile(path)
    return QDesktopServices.openUrl(url)


# ==============================================================================
# 5. DRAWING PRIMITIVES
# ==============================================================================


def draw_tile(
    p: QPainter,
    rect: QRectF,
    tile: Dict[str, Any],
    pixmap: QPixmap,
    hover_t: float = 0.0,
    press_scale: float = 1.0,
    dot_count: Optional[int] = None,
    indicator_y: Optional[float] = None,
) -> None:
    """Draw a 46x46 dark rounded square application tile with crisp icon and indicator.

    Specifications:
      - 46x46 dark rounded square (radius 12, fill rgba(255,255,255,0.07) + 1px rgba(255,255,255,0.10) border, hover brightens to 0.13)
      - Icon 30 logical px crisp via theme.draw_icon_crisp
      - Indicators under the tile:
          active = pill
          running = up to 3 dots (count)
          pinned-not-running = nothing
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    eff_hover = max(0.0, min(1.0, hover_t))

    # Base: 0.07 -> Hover: 0.13
    fill_alpha = int(255.0 * (0.07 + 0.06 * eff_hover))
    # Base: 0.10 -> Hover: 0.14
    border_alpha = int(255.0 * (0.10 + 0.04 * eff_hover))

    fill_color = QColor(255, 255, 255, fill_alpha)
    border_color = QColor(255, 255, 255, border_alpha)

    cx = rect.center().x()
    cy = rect.center().y()

    # Draw rounded tile square and icon, applying press_scale if active
    p.save()
    if press_scale != 1.0:
        p.translate(cx, cy)
        p.scale(press_scale, press_scale)
        p.translate(-cx, -cy)

    tile_path = theme.rounded_path(rect, TILE_RADIUS)
    # 1. Dark glass base for depth
    p.fillPath(tile_path, COLOR_TILE_DARK_BASE)
    # 2. Semi-translucent white surface (brightens on hover)
    p.fillPath(tile_path, fill_color)

    # 3. 1px crisp outer border
    border_rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    border_radius = max(0.0, TILE_RADIUS - 0.5)
    p.setPen(QPen(border_color, BORDER_WIDTH))
    p.setBrush(Qt.NoBrush)
    p.drawPath(theme.rounded_path(border_rect, border_radius))

    # 4. Icon (30 logical px centered)
    icon_rect = QRectF(
        rect.x() + (rect.width() - ICON_SIZE) / 2.0,
        rect.y() + (rect.height() - ICON_SIZE) / 2.0,
        ICON_SIZE,
        ICON_SIZE,
    )
    if pixmap is not None and not pixmap.isNull():
        theme.draw_icon_crisp(p, pixmap, icon_rect)
    else:
        # High quality fallback icon with app initial
        fb_path = theme.rounded_path(icon_rect, 6.0)
        p.fillPath(fb_path, QColor(45, 52, 68))
        p.setFont(theme.make_font(12.0, QFont.Weight.Bold))
        p.setPen(Qt.white)
        name_str = tile.get("name") or tile.get("exe") or "A"
        p.drawText(icon_rect, Qt.AlignCenter, name_str[:1].upper())

    p.restore()

    # 5. Indicators under the tile
    ind_y = indicator_y if indicator_y is not None else (rect.bottom() + INDICATOR_GAP)

    is_running = bool(tile.get("running", False)) or (dot_count is not None and dot_count > 0)
    is_active = bool(tile.get("active", False))
    cnt = dot_count if dot_count is not None else int(tile.get("count", 1) or 1)

    if is_running:
        if is_active:
            theme.draw_app_indicator(
                p,
                center_x=cx,
                center_y=ind_y,
                width=INDICATOR_ACTIVE_W,
                height=INDICATOR_ACTIVE_H,
                radius=INDICATOR_ACTIVE_R,
                is_active=True,
            )
        else:
            dots = min(3, max(1, cnt))
            if dots == 1:
                theme.draw_app_indicator(p, center_x=cx, center_y=ind_y, is_active=False)
            elif dots == 2:
                theme.draw_app_indicator(p, center_x=cx - INDICATOR_DOT_SPACING, center_y=ind_y, is_active=False)
                theme.draw_app_indicator(p, center_x=cx + INDICATOR_DOT_SPACING, center_y=ind_y, is_active=False)
            elif dots >= 3:
                theme.draw_app_indicator(p, center_x=cx - 6.0, center_y=ind_y, is_active=False)
                theme.draw_app_indicator(p, center_x=cx, center_y=ind_y, is_active=False)
                theme.draw_app_indicator(p, center_x=cx + 6.0, center_y=ind_y, is_active=False)

    p.restore()


def draw_label_bubble(
    p: QPainter,
    anchor_center_top: Union[QPointF, Tuple[float, float]],
    text: str,
    gap: float = BUBBLE_GAP,
    opacity: float = 1.0,
) -> QRectF:
    """Draw a dark glass tooltip bubble with app name above the tile.

    Specifications:
      - 11px Segoe UI font
      - Padding: 6px vertical x 10px horizontal
      - Radius: 8px
      - Dark glass background with subtle 1px border
      - Positioned above anchor_center_top
    """
    if not text:
        return QRectF()

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    eff_op = max(0.0, min(1.0, opacity))
    if eff_op <= 0.0:
        p.restore()
        return QRectF()

    if eff_op < 1.0:
        p.setOpacity(eff_op)

    font = theme.make_font(BUBBLE_FONT_SIZE, QFont.Weight.Medium)
    fm = QFontMetricsF(font)
    text_w = fm.horizontalAdvance(text)
    text_h = fm.height()

    bubble_w = text_w + 2.0 * BUBBLE_PAD_H
    bubble_h = text_h + 2.0 * BUBBLE_PAD_V

    if isinstance(anchor_center_top, tuple):
        ax = float(anchor_center_top[0])
        ay = float(anchor_center_top[1])
    else:
        ax = float(anchor_center_top.x())
        ay = float(anchor_center_top.y())

    bubble_x = ax - bubble_w / 2.0
    bubble_y = ay - gap - bubble_h
    bubble_rect = QRectF(bubble_x, bubble_y, bubble_w, bubble_h)

    # 1. Dark glass background
    path = theme.rounded_path(bubble_rect, BUBBLE_RADIUS)
    p.fillPath(path, COLOR_BUBBLE_BG)

    # 2. 1px outer stroke
    border_r = bubble_rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setPen(QPen(COLOR_BUBBLE_BORDER, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(theme.rounded_path(border_r, max(0.0, BUBBLE_RADIUS - 0.5)))

    # 3. Label text
    p.setFont(font)
    p.setPen(theme.COLOR_TEXT_PRIMARY)
    p.drawText(bubble_rect, Qt.AlignCenter, text)

    p.restore()
    return bubble_rect
