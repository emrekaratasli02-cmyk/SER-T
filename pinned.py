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

import uwp
from PySide6.QtCore import QFileInfo, QPointF, QProcess, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

import theme
import winapi

# ==============================================================================
# 1. GEOMETRY & DIMENSION TOKENS (dock v3: cell 44x46, icon 32x32, gap 4)
# ==============================================================================

TILE_WIDTH: float = 44.0
TILE_HEIGHT: float = 46.0
TILE: float = 44.0
ICON: float = 32.0
TILE_SIZE: float = 44.0
ICON_SIZE: float = 32.0
TILE_RADIUS: float = 11.0
GAP: float = 4.0
BORDER_WIDTH: float = 1.0

# Bubble tooltip tokens
BUBBLE_RADIUS: float = 8.0
BUBBLE_PAD_V: float = 6.0
BUBBLE_PAD_H: float = 10.0
BUBBLE_FONT_SIZE: float = 11.0
BUBBLE_GAP: float = 6.0

# Indicator tokens (matching theme.py metrics: running dot 4x4 white 85% centred 2px from cell bottom)
INDICATOR_ACTIVE_W: float = 12.0
INDICATOR_ACTIVE_H: float = 3.0
INDICATOR_ACTIVE_R: float = 1.5
INDICATOR_DOT_SIZE: float = 4.0
INDICATOR_DOT_SPACING: float = 3.5
INDICATOR_GAP: float = 2.0

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


def launch(path: str, args: Optional[List[str]] = None) -> bool:
    """Launch application at path (Store apps via their AUMID, others via shell/QProcess)."""
    if not path:
        return False
    if uwp.is_uwp_path(path):
        # WindowsApps exe'leri doğrudan çalıştırılamaz; paket kimliğiyle açılır
        return uwp.launch(path)
    if args:
        try:
            return QProcess.startDetached(path, args)
        except Exception:
            pass
    url = QUrl.fromLocalFile(path)
    return QDesktopServices.openUrl(url)


# ==============================================================================
# 5. DRAWING PRIMITIVES
# ==============================================================================

_OPTICAL_SIZE_CACHE: Dict[int, Tuple[float, float]] = {}


def _optical_icon_size(pixmap: Optional[QPixmap], base_size: float = 32.0) -> Tuple[float, float]:
    """Hesaplanan optik boyut: Katı kare/squircle ikonlar (WhatsApp, Excel) dairesel
    ikonlara (Chrome) göre %25 daha fazla optik alan kaplar. Bu nedenle katı kareler ~29.8px,
    daireler ve yatay/klasör ikonları 32px olarak dengelenir."""
    if pixmap is None or pixmap.isNull():
        return (base_size, base_size)
    key = pixmap.cacheKey()
    cached = _OPTICAL_SIZE_CACHE.get(key)
    if cached is not None:
        return cached

    pw, ph = pixmap.width(), pixmap.height()
    if pw <= 0 or ph <= 0:
        return (base_size, base_size)

    try:
        img = pixmap.toImage()
        step = max(1, min(pw, ph) // 32)
        min_x, max_x = pw, -1
        min_y, max_y = ph, -1
        filled = 0

        for y in range(0, ph, step):
            for x in range(0, pw, step):
                if img.pixelColor(x, y).alpha() > 25:
                    filled += 1
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y

        if max_x < min_x or max_y < min_y:
            res = (base_size, base_size)
        else:
            cw = max_x - min_x + 1
            ch = max_y - min_y + 1
            aspect = cw / max(1, ch)
            bbox_samples = ((cw // step) + 1) * ((ch // step) + 1)
            fill_ratio = filled / max(1, bbox_samples)

            if 0.88 <= aspect <= 1.14 and fill_ratio >= 0.82:
                target = round(base_size * 0.93, 1)  # ~29.8px
                res = (target, target)
            elif aspect > 1.15:
                target_h = round(min(base_size, base_size / aspect), 1)
                res = (base_size, target_h)
            elif aspect < 0.85:
                target_w = round(min(base_size, base_size * aspect), 1)
                res = (target_w, base_size)
            else:
                res = (base_size, base_size)
    except Exception:
        res = (base_size, base_size)

    _OPTICAL_SIZE_CACHE[key] = res
    return res


def draw_tile(
    p: QPainter,
    rect: QRectF,
    tile: Dict[str, Any],
    pixmap: QPixmap,
    hover_t: float = 0.0,
    press_scale: float = 1.0,
    dot_count: Optional[int] = None,
    indicator_y: Optional[float] = None,
    launch_phase: Optional[float] = None,
    flash_phase: Optional[float] = None,
    badge: Optional[Union[str, int]] = None,
) -> None:
    """Draw a 44x46 cell application tile with crisp 32x32 icon and running dot.

    Specifications (dock v3):
      - Cell 44x46, icon 32x32, 4px gap
      - Hover fill rgba(255,255,255,0.09) radius 11
      - Icon lift -2px scale 1.10
      - Running dot 4x4 white 85% centred 2px from cell bottom
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    eff_hover = max(0.0, min(1.0, hover_t))

    cx = rect.center().x()
    cy = rect.center().y()

    is_running = bool(tile.get("running", False)) or (dot_count is not None and dot_count > 0)
    is_active = bool(tile.get("active", False))

    # Draw rounded tile hover fill, active capsule, or orange attention flash
    if flash_phase is not None and flash_phase > 0.0:
        # Turuncu dikkat parlaması (RGBA 255, 140, 0)
        flash_alpha = int(255 * 0.35 * max(0.0, min(1.0, flash_phase)))
        tile_path = theme.rounded_path(rect, TILE_RADIUS)
        p.fillPath(tile_path, QColor(255, 140, 0, flash_alpha))
        p.setPen(QPen(QColor(255, 160, 20, int(255 * 0.70 * flash_phase)), 1.2))
        p.drawPath(tile_path)
    elif is_active:
        # Aktif pencere: zarif cam kapsül (kutusuz dille uyumlu)
        tile_path = theme.rounded_path(rect, TILE_RADIUS)
        p.fillPath(tile_path, QColor(255, 255, 255, int(255 * (0.08 + 0.04 * eff_hover))))
        p.setPen(QPen(QColor(255, 255, 255, 26), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawPath(theme.rounded_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), TILE_RADIUS - 0.5))
    elif eff_hover > 0.0:
        hover_bg = QColor(255, 255, 255, int(255 * 0.10 * eff_hover))
        tile_path = theme.rounded_path(rect, TILE_RADIUS)
        p.fillPath(tile_path, hover_bg)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.08 * eff_hover)), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawPath(theme.rounded_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), TILE_RADIUS - 0.5))
    # Rölantide kutusuz: Açık arka plan veya çerçeve yok

    # Draw icon with lift and scale
    p.save()
    if launch_phase is not None:  # v24: açılıyor, ikon soluk
        p.setOpacity(0.55)
    # Smooth lift: -2px * eff_hover, scale: 1.0 + 0.10 * eff_hover
    lift_y = -2.0 * eff_hover
    scale_hover = 1.0 + 0.10 * eff_hover
    tot_scale = press_scale * scale_hover

    p.translate(cx, cy + lift_y)
    if tot_scale != 1.0:
        p.scale(tot_scale, tot_scale)
    p.translate(-cx, -(cy + lift_y))

    # Icon (optik dengeli ve ortalı)
    ICON_SIZE_RENDER = 32.0
    opt_w, opt_h = _optical_icon_size(pixmap, ICON_SIZE_RENDER)
    icon_rect = QRectF(
        cx - opt_w / 2.0,
        cy + lift_y - opt_h / 2.0,
        opt_w,
        opt_h,
    )
    if pixmap is not None and not pixmap.isNull():
        theme.draw_icon_crisp(p, pixmap, icon_rect)
    else:
        # High quality fallback icon with app initial
        fb_rect = QRectF(cx - 15.0, cy + lift_y - 15.0, 30.0, 30.0)
        fb_path = theme.rounded_path(fb_rect, 6.0)
        p.fillPath(fb_path, QColor(45, 52, 68))
        p.setFont(theme.make_font(12.0, QFont.Weight.Bold))
        p.setPen(Qt.white)
        name_str = tile.get("name") or tile.get("exe") or "A"
        p.drawText(fb_rect, Qt.AlignCenter, name_str[:1].upper())

    p.restore()

    # 4.5. Notification Badge (sağ üst köşe kırmızı/turuncu şık rozet)
    if badge is not None and str(badge).strip():
        badge_str = str(badge).strip()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        f_b = theme.make_font(8.5, QFont.Weight.Bold, tabular=True)
        p.setFont(f_b)
        fm_b = QFontMetricsF(f_b)
        txt_w = fm_b.horizontalAdvance(badge_str)
        bw = max(14.0, txt_w + 6.0)
        bh = 14.0
        bx = icon_rect.right() - bw + 4.0
        by = icon_rect.top() - 3.0
        badge_box = QRectF(bx, by, bw, bh)
        b_path = theme.rounded_path(badge_box, bh / 2.0)
        # İndirme ise canlı mavi, okunmamış mesaj ise kırmızı-mercan rozet
        is_dl = badge_str.startswith("↓")
        badge_bg = QColor(10, 132, 255) if is_dl else QColor(255, 59, 48)
        p.fillPath(b_path, badge_bg)
        p.setPen(QPen(QColor(13, 15, 19, 220), 1.0))
        p.drawPath(b_path)
        p.setPen(QColor(255, 255, 255))
        p.drawText(badge_box, Qt.AlignCenter, badge_str)
        p.restore()

    # 5. Indicators under the tile (centred 2px from cell bottom: y = rect.bottom() - 2.0 - 2.0 = rect.bottom() - 4.0)
    ind_y = indicator_y if indicator_y is not None else (rect.bottom() - 4.0)

    is_running = bool(tile.get("running", False)) or (dot_count is not None and dot_count > 0)
    is_active = bool(tile.get("active", False))

    if is_running:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if is_active:
            # Öndeki aktif uygulama: Işıldayan 13x2.8 beyaz hap gösterge
            pill_w = 13.0
            pill_h = 2.8
            pill_rect = QRectF(cx - pill_w / 2.0, ind_y - pill_h / 2.0, pill_w, pill_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 240))
            p.drawRoundedRect(pill_rect, 1.4, 1.4)
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(pill_rect.adjusted(-0.4, -0.4, 0.4, 0.4), 1.8, 1.8)
        elif dot_count is not None and dot_count > 1:
            # Çoklu pencere: İki zarif net nokta (macOS tarzı)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 190))
            p.drawEllipse(QPointF(cx - 3.2, ind_y), 1.7, 1.7)
            p.drawEllipse(QPointF(cx + 3.2, ind_y), 1.7, 1.7)
        else:
            # Arka plan tek pencere: Yumuşak, net tek nokta
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 190))
            p.drawEllipse(QPointF(cx, ind_y), 1.85, 1.85)
        p.restore()
    elif launch_phase is not None:  # v24: açılıyor, nabız gibi atan nokta
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(220 * max(0.0, min(1.0, launch_phase)))))
        p.drawEllipse(QPointF(cx, ind_y), 1.85, 1.85)
        p.restore()

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
