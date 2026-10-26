"""theme.py - Design tokens, typography, and pure QPainter drawing primitives for Şerit dock.

Provides pixel-precise, hardware-accelerated drawing primitives adhering to the
approved glass dock specification (Variant A). Zero internal application state.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

# ==============================================================================
# 1. GEOMETRY & DIMENSION TOKENS
# ==============================================================================

# Dock capsule
DOCK_HEIGHT: float = 56.0
DOCK_RADIUS: float = 28.0  # Continuous capsule / pill: R = H / 2
DOCK_PAD_X: float = 14.0
GAP_MODULE: float = 6.0  # Gap between adjacent chips
GAP_SEPARATOR: float = 10.0  # Gap flanking vertical separators
ITEM_GAP: float = 2.0  # Gap between running app icons

# Chips / modules
CHIP_HEIGHT: float = 40.0
CHIP_Y: float = 8.0  # (DOCK_HEIGHT - CHIP_HEIGHT) / 2
CHIP_PAD_X: float = 8.0
CHIP_PAD_Y: float = 6.0
CHIP_RADIUS: float = 14.0

# Ring gauges
RING_SIZE: float = 34.0
RING_STROKE: float = 3.5
RING_RADIUS: float = 13.5  # (34 - 3.5) / 2 = Center of stroke
RING_TEXT_OFFSET_Y: float = -0.75  # Optical alignment offset for cap-height

# App indicators (y=50.0 is fixed baseline, 6px above dock bottom)
INDICATOR_Y: float = 50.0
INDICATOR_ACTIVE_W: float = 12.0
INDICATOR_ACTIVE_H: float = 3.0
INDICATOR_ACTIVE_R: float = 1.5
INDICATOR_DOT_SIZE: float = 4.0

# Separator hairline
SEP_WIDTH: float = 1.0
SEP_HEIGHT: float = 22.0
SEP_Y: float = 17.0  # (56 - 22) / 2

# App icons
ICON_SIZE: float = 28.0
ICON_PREFILTER_SIZE: float = 56.0

# Hover, lift & press
HOVER_LIFT_Y: float = -3.5
HOVER_SCALE_MAX: float = 1.20
HOVER_SCALE_NEIGHBOR: float = 1.07
PRESS_SCALE: float = 0.94

# Popover flyout card
POP_WIDTH: float = 272.0
POP_RADIUS: float = 18.0
POP_GAP: float = 8.0
POP_BAR_HEIGHT: float = 5.0
POP_BAR_RADIUS: float = 2.5

# ==============================================================================
# 2. COLOR & MATERIAL TOKENS
# ==============================================================================

# Ring and status accents
COLOR_CLAUDE_SESSION: QColor = QColor("#F08A5D")  # Anthropic Coral
COLOR_CLAUDE_WEEK: QColor = QColor("#F6B38F")  # Soft Peach
COLOR_CPU: QColor = QColor("#60B5FF")  # Vibrant Cyan-Blue
COLOR_RAM: QColor = QColor("#B49CFF")  # Lavender Purple

# Ring alert thresholds
COLOR_ALERT_WARN: QColor = QColor("#FFC45C")  # >= 80% (Amber)
COLOR_ALERT_CRIT: QColor = QColor("#FF6E6E")  # >= 95% (Coral Red)

# Base glass material (Dark theme composite over Windows Acrylic blur)
COLOR_GLASS_TINT: QColor = QColor(16, 20, 28, int(255 * 0.38))
COLOR_GLASS_OUTER_STROKE: QColor = QColor(0, 0, 0, int(255 * 0.35))

# Specular rim gradient stops (top to bottom) - refined glass edge catch
COLOR_GLASS_INNER_RIM_0: QColor = QColor(255, 255, 255, int(255 * 0.48))
COLOR_GLASS_INNER_RIM_25: QColor = QColor(255, 255, 255, int(255 * 0.18))
COLOR_GLASS_INNER_RIM_80: QColor = QColor(255, 255, 255, int(255 * 0.04))
COLOR_GLASS_INNER_RIM_100: QColor = QColor(255, 255, 255, int(255 * 0.12))

# Text colors
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(255, 255, 255, int(255 * 0.72))
COLOR_TEXT_MUTED: QColor = QColor(255, 255, 255, int(255 * 0.38))

# Interactive fills
COLOR_CHIP_HOVER: QColor = QColor(255, 255, 255, int(255 * 0.08))
COLOR_CHIP_PRESS: QColor = QColor(255, 255, 255, int(255 * 0.14))

# Ring track & progress bar track
COLOR_RING_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.12))
COLOR_PROGRESS_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.14))

# Indicators
COLOR_INDICATOR_ACTIVE: QColor = QColor(255, 255, 255, 255)
COLOR_INDICATOR_INACTIVE: QColor = QColor(255, 255, 255, int(255 * 0.60))

# Popover badge
COLOR_BADGE_BG: QColor = QColor(240, 138, 93, int(255 * 0.22))
COLOR_BADGE_TEXT: QColor = QColor("#FFB08A")

# Weather icon colors
COLOR_WX_SUN: QColor = QColor("#FBBF24")
COLOR_WX_CLOUD: QColor = QColor(230, 235, 245, 220)
COLOR_WX_RAIN: QColor = QColor("#60A5FA")
COLOR_WX_SNOW: QColor = QColor("#E0F2FE")
COLOR_WX_LIGHTNING: QColor = QColor("#FACC15")

# ==============================================================================
# 3. DURATION TOKENS (milliseconds)
# ==============================================================================

DUR_HOVER_ENTER: float = 180.0
DUR_HOVER_EXIT: float = 220.0
DUR_RING_SWEEP_FAST: float = 350.0
DUR_RING_SWEEP_SLOW: float = 550.0
DUR_POP_OPEN: float = 200.0
DUR_POP_CLOSE: float = 150.0
DUR_PILL_GLIDE: float = 260.0
DUR_APP_SLOT: float = 300.0
DUR_DOCK_RESIZE: float = 320.0
DUR_PRESS: float = 70.0
DUR_RELEASE: float = 180.0
DUR_STALE_FADE: float = 600.0

# ==============================================================================
# 4. TYPOGRAPHY TOKENS & FONT FACTORY
# ==============================================================================

FONT_FAMILY: str = "Segoe UI Variable Text"
FONT_FALLBACKS: List[str] = ["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"]

FONT_SIZE_CLOCK: float = 15.0
FONT_SIZE_VAL: float = 13.0
FONT_SIZE_LBL: float = 10.5
FONT_SIZE_RING: float = 11.0
FONT_SIZE_RING_SMALL: float = 9.5
FONT_SIZE_POP_TITLE: float = 14.0
FONT_SIZE_POP_SUB: float = 11.0
FONT_SIZE_BADGE: float = 10.5


def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
) -> QFont:
    """Creates a high-DPI Segoe UI Variable font instance with OpenType feature support."""
    f = QFont(FONT_FAMILY)
    f.setFamilies(FONT_FALLBACKS)
    f.setPixelSize(max(1, int(round(size_px))))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.PreferAntialias)

    if tabular:
        try:
            f.setFeature(QFont.Tag.fromString("tnum"), 1)
        except Exception:
            pass

    if letter_spacing is not None:
        try:
            f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
        except Exception:
            pass

    return f


# ==============================================================================
# 5. NOISE GRAIN & ICON CACHE (Drawing Caches Only, No App State)
# ==============================================================================

_NOISE_BRUSH: Optional[QBrush] = None
_ICON_CACHE: Dict[Tuple[int, int, int], QPixmap] = {}


def get_noise_brush() -> QBrush:
    """Returns a cached 64x64 seamless monochrome noise tile with ~3% alpha."""
    global _NOISE_BRUSH
    if _NOISE_BRUSH is not None:
        return _NOISE_BRUSH

    rng = random.Random(42)  # Deterministic seed for identical grain tile
    buf = bytearray(64 * 64 * 4)
    for i in range(0, 64 * 64 * 4, 4):
        # 3% average of 255 is ~8. Sample random variations in [0, 16]
        a = rng.randint(0, 16)
        buf[i] = a      # B
        buf[i + 1] = a  # G
        buf[i + 2] = a  # R
        buf[i + 3] = a  # A (Premultiplied ARGB32)

    img = QImage(bytes(buf), 64, 64, 64 * 4, QImage.Format.Format_ARGB32_Premultiplied)
    pm = QPixmap.fromImage(img)
    _NOISE_BRUSH = QBrush(pm)
    return _NOISE_BRUSH


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Constructs a rounded rectangle QPainterPath."""
    path = QPainterPath()
    r = max(0.0, min(radius, min(rect.width(), rect.height()) / 2.0))
    path.addRoundedRect(rect, r, r)
    return path


def get_ring_threshold_color(value: float, default_color: QColor) -> QColor:
    """Returns the warning/critical alert color if value reaches thresholds, else default."""
    if value >= 95.0:
        return COLOR_ALERT_CRIT
    if value >= 80.0:
        return COLOR_ALERT_WARN
    return default_color


# ==============================================================================
# 6. PURE DRAWING PRIMITIVES
# ==============================================================================


def draw_glass_capsule(
    p: QPainter,
    rect: QRectF,
    radius: float = DOCK_RADIUS,
    is_hovered: bool = False,
    hover_opacity: float = 0.0,
    bg_tint: Optional[QColor] = None,
    show_grain: bool = False,
    show_specular: bool = True,
    show_outer_stroke: bool = True,
) -> None:
    """Draws a physical acrylic glass capsule with grain texture and specular rim highlights.

    Layer stack:
      1. Base dark tint fill
      2. 64x64 monochrome noise grain tile clipped to path (~3% alpha)
      3. Hover / interaction fill overlay (if hovered or hover_opacity > 0)
      4. Inner top specular highlight rim (linear gradient along inner contour)
      5. 1px outer perimeter boundary stroke
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    path = rounded_path(rect, radius)

    # 1. Base tint fill
    tint = bg_tint if bg_tint is not None else COLOR_GLASS_TINT
    p.fillPath(path, tint)

    # 2. Subtle noise grain
    if show_grain:
        p.save()
        p.setClipPath(path)
        p.fillRect(rect, get_noise_brush())
        p.restore()

    # 3. Interactive hover overlay
    eff_hover = max(0.0, min(1.0, hover_opacity if hover_opacity > 0.0 else (1.0 if is_hovered else 0.0)))
    if eff_hover > 0.0:
        h_col = QColor(COLOR_CHIP_HOVER.red(), COLOR_CHIP_HOVER.green(), COLOR_CHIP_HOVER.blue(),
                       int(COLOR_CHIP_HOVER.alpha() * eff_hover))
        p.fillPath(path, h_col)

    # 4. Inner specular highlight rim
    if show_specular and rect.width() > 2 and rect.height() > 2:
        inner_r = rect.adjusted(0.75, 0.75, -0.75, -0.75)
        inner_radius = max(0.0, radius - 0.75)
        inner_path = rounded_path(inner_r, inner_radius)

        rim_grad = QLinearGradient(inner_r.left(), inner_r.top(), inner_r.left(), inner_r.bottom())
        rim_grad.setColorAt(0.00, COLOR_GLASS_INNER_RIM_0)
        rim_grad.setColorAt(0.25, COLOR_GLASS_INNER_RIM_25)
        rim_grad.setColorAt(0.80, COLOR_GLASS_INNER_RIM_80)
        rim_grad.setColorAt(1.00, COLOR_GLASS_INNER_RIM_100)

        p.setPen(QPen(QBrush(rim_grad), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(inner_path)

    # 5. Outer dark boundary stroke
    if show_outer_stroke and rect.width() > 1 and rect.height() > 1:
        outer_r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        outer_radius = max(0.0, radius - 0.5)
        outer_path = rounded_path(outer_r, outer_radius)

        p.setPen(QPen(COLOR_GLASS_OUTER_STROKE, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(outer_path)

    p.restore()


def draw_dual_stroke(
    p: QPainter,
    rect: QRectF,
    radius: float = CHIP_RADIUS,
) -> None:
    """Draws outer dark boundary and inner specular highlight strokes on a rounded rect."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    # Inner specular
    if rect.width() > 2 and rect.height() > 2:
        inner_r = rect.adjusted(0.75, 0.75, -0.75, -0.75)
        inner_path = rounded_path(inner_r, max(0.0, radius - 0.75))
        rim_grad = QLinearGradient(inner_r.left(), inner_r.top(), inner_r.left(), inner_r.bottom())
        rim_grad.setColorAt(0.00, COLOR_GLASS_INNER_RIM_0)
        rim_grad.setColorAt(0.25, COLOR_GLASS_INNER_RIM_25)
        rim_grad.setColorAt(0.80, COLOR_GLASS_INNER_RIM_80)
        rim_grad.setColorAt(1.00, COLOR_GLASS_INNER_RIM_100)
        p.setPen(QPen(QBrush(rim_grad), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(inner_path)

    # Outer border
    if rect.width() > 1 and rect.height() > 1:
        outer_r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        outer_path = rounded_path(outer_r, max(0.0, radius - 0.5))
        p.setPen(QPen(COLOR_GLASS_OUTER_STROKE, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(outer_path)

    p.restore()


def draw_ring_gauge(
    p: QPainter,
    center: QPointF,
    size: float = RING_SIZE,
    stroke: float = RING_STROKE,
    value_0_100: float = 0.0,
    colour: Optional[QColor] = None,
    text: Optional[str] = None,
    opacity: float = 1.0,
    glow_tip: bool = True,
) -> None:
    """Draws a calibrated ring gauge with soft background track, round caps, and optical centering."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    eff_op = max(0.0, min(1.0, opacity))
    if eff_op < 1.0:
        p.setOpacity(eff_op)

    cx = center.x()
    cy = center.y()
    r = (size - stroke) / 2.0
    arc_rect = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)

    # 1. Background full track circle
    p.setPen(QPen(COLOR_RING_TRACK, stroke, Qt.SolidLine, Qt.FlatCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(arc_rect)

    # 2. Foreground active arc
    val = max(0.0, min(100.0, value_0_100))
    base_col = colour if colour is not None else COLOR_CPU
    fg_col = get_ring_threshold_color(val, base_col)

    if val > 0.0:
        pen_fg = QPen(fg_col, stroke, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_fg)
        # Clockwise arc starting at 12 o'clock (90 deg in standard Qt angles)
        span_angle = -int(round((val / 100.0) * 360.0 * 16.0))
        p.drawArc(arc_rect, 90 * 16, span_angle)

        # 3. Specular glow at arc tip
        if glow_tip and val > 1.5:
            # Angle clockwise from 12 o'clock
            angle_rad = math.radians(90.0 - (val / 100.0) * 360.0)
            tip_x = cx + r * math.cos(angle_rad)
            tip_y = cy - r * math.sin(angle_rad)

            glow_grad = QRadialGradient(tip_x, tip_y, stroke * 1.2)
            glow_grad.setColorAt(0.0, QColor(255, 255, 255, int(255 * 0.80)))
            glow_grad.setColorAt(0.5, QColor(fg_col.red(), fg_col.green(), fg_col.blue(), int(255 * 0.40)))
            glow_grad.setColorAt(1.0, QColor(fg_col.red(), fg_col.green(), fg_col.blue(), 0))

            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow_grad))
            p.drawEllipse(QRectF(tip_x - stroke * 1.2, tip_y - stroke * 1.2, stroke * 2.4, stroke * 2.4))

    # 4. Numerals centered with optical baseline adjustment
    num_str = text if text is not None else f"{int(round(val))}"
    if num_str:
        font_size = FONT_SIZE_RING_SMALL if len(num_str) >= 3 else FONT_SIZE_RING
        f_num = make_font(font_size, QFont.Weight.Bold, tabular=True)
        p.setFont(f_num)
        p.setPen(COLOR_TEXT_PRIMARY)

        # Apply optical vertical offset to align cap-height center to geometric arc center
        text_rect = QRectF(cx - r, cy - r + RING_TEXT_OFFSET_Y, 2.0 * r, 2.0 * r)
        p.drawText(text_rect, Qt.AlignCenter, num_str)

    p.restore()


def draw_separator(
    p: QPainter,
    x: float,
    y: float = SEP_Y,
    height: float = SEP_HEIGHT,
    opacity: float = 1.0,
) -> None:
    """Draws a vertical hairline separator with smooth top and bottom fade."""
    p.save()
    eff_op = max(0.0, min(1.0, opacity))
    rect = QRectF(x, y, SEP_WIDTH, height)

    grad = QLinearGradient(x, y, x, y + height)
    grad.setColorAt(0.0, QColor(255, 255, 255, int(255 * 0.02 * eff_op)))
    grad.setColorAt(0.5, QColor(255, 255, 255, int(255 * 0.20 * eff_op)))
    grad.setColorAt(1.0, QColor(255, 255, 255, int(255 * 0.02 * eff_op)))

    p.fillRect(rect, grad)
    p.restore()


def draw_app_indicator(
    p: QPainter,
    center_x: float,
    center_y: float = INDICATOR_Y,
    width: float = INDICATOR_ACTIVE_W,
    height: float = INDICATOR_ACTIVE_H,
    radius: float = INDICATOR_ACTIVE_R,
    opacity: float = 1.0,
    is_active: bool = True,
    color: Optional[QColor] = None,
) -> None:
    """Draws an application state indicator (active pill or inactive running dot).

    x, width, and opacity parameters allow smooth continuous tweening between states.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    eff_op = max(0.0, min(1.0, opacity))
    if eff_op <= 0.0:
        p.restore()
        return

    if is_active:
        base_col = color if color is not None else COLOR_INDICATOR_ACTIVE
        pill_rect = QRectF(center_x - width / 2.0, center_y - height / 2.0, width, height)
        c = QColor(base_col.red(), base_col.green(), base_col.blue(), int(base_col.alpha() * eff_op))
        p.fillPath(rounded_path(pill_rect, radius), c)
    else:
        base_col = color if color is not None else COLOR_INDICATOR_INACTIVE
        dot_d = min(width, INDICATOR_DOT_SIZE)
        dot_rect = QRectF(center_x - dot_d / 2.0, center_y - dot_d / 2.0, dot_d, dot_d)
        c = QColor(base_col.red(), base_col.green(), base_col.blue(), int(base_col.alpha() * eff_op))
        p.fillPath(rounded_path(dot_rect, dot_d / 2.0), c)

    p.restore()


def draw_icon_crisp(
    p: QPainter,
    pixmap: QPixmap,
    target_rect: QRectF,
    opacity: float = 1.0,
) -> None:
    """Renders high-DPI application icons tack-sharp by pre-filtering to device pixel size."""
    if pixmap.isNull():
        return

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    eff_op = max(0.0, min(1.0, opacity))
    if eff_op < 1.0:
        p.setOpacity(eff_op)

    # Determine device pixel ratio from painter or target rect
    device = p.device()
    dpr = device.devicePixelRatioF() if device is not None else 1.0
    pw = max(1, int(round(target_rect.width() * dpr)))
    ph = max(1, int(round(target_rect.height() * dpr)))

    cache_key = (pixmap.cacheKey(), pw, ph)
    cached_pm = _ICON_CACHE.get(cache_key)

    if cached_pm is None:
        if pixmap.width() > pw or pixmap.height() > ph:
            cached_pm = pixmap.scaled(
                QSize(pw, ph),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            cached_pm.setDevicePixelRatio(dpr)
        else:
            cached_pm = pixmap
        _ICON_CACHE[cache_key] = cached_pm

    p.drawPixmap(target_rect.topLeft(), cached_pm)
    p.restore()


def draw_label(
    p: QPainter,
    rect: QRectF,
    text: str,
    opacity: float = 1.0,
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter,
) -> None:
    """Renders secondary chip text (label, e.g. 'Oturum', 'Hafta', weather desc)."""
    p.save()
    p.setRenderHint(QPainter.TextAntialiasing)
    eff_op = max(0.0, min(1.0, opacity))
    col = QColor(COLOR_TEXT_SECONDARY.red(), COLOR_TEXT_SECONDARY.green(), COLOR_TEXT_SECONDARY.blue(),
                 int(COLOR_TEXT_SECONDARY.alpha() * eff_op))
    p.setPen(col)
    p.setFont(make_font(FONT_SIZE_LBL, QFont.Weight.Normal, letter_spacing=0.2))
    p.drawText(rect, align, text)
    p.restore()


def draw_value(
    p: QPainter,
    rect: QRectF,
    text: str,
    opacity: float = 1.0,
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter,
) -> None:
    """Renders primary chip text (value, e.g. remaining countdown, temperature)."""
    p.save()
    p.setRenderHint(QPainter.TextAntialiasing)
    eff_op = max(0.0, min(1.0, opacity))
    col = QColor(COLOR_TEXT_PRIMARY.red(), COLOR_TEXT_PRIMARY.green(), COLOR_TEXT_PRIMARY.blue(),
                 int(COLOR_TEXT_PRIMARY.alpha() * eff_op))
    p.setPen(col)
    p.setFont(make_font(FONT_SIZE_VAL, QFont.Weight.DemiBold, tabular=True))
    p.drawText(rect, align, text)
    p.restore()


def draw_chip_text(
    p: QPainter,
    x: float,
    y: float = 0.0,
    label: str = "",
    value: str = "",
    label_w: float = 0.0,
    value_w: float = 0.0,
    opacity: float = 1.0,
) -> None:
    """Convenience helper to render the standard 2-line label/value chip stack.

    Adheres to the exact optical baselines from Section A:
      - Label: top at y + 11, height=12 (baseline at y + 23)
      - Value: top at y + 24, height=16 (baseline at y + 39)
    """
    f_lbl = make_font(FONT_SIZE_LBL, QFont.Weight.Normal, letter_spacing=0.2)
    f_val = make_font(FONT_SIZE_VAL, QFont.Weight.DemiBold, tabular=True)

    fm_l = QFontMetricsF(f_lbl)
    fm_v = QFontMetricsF(f_val)

    w_l = label_w if label_w > 0.0 else fm_l.horizontalAdvance(label)
    w_v = value_w if value_w > 0.0 else fm_v.horizontalAdvance(value)
    w_max = max(w_l, w_v) + 4.0

    draw_label(p, QRectF(x, y + 11.0, w_max, 12.0), label, opacity=opacity)
    draw_value(p, QRectF(x, y + 24.0, w_max, 16.0), value, opacity=opacity)


def draw_weather_icon(p: QPainter, rect: QRectF, icon: str = "cloud") -> None:
    """Renders crisp vector weather iconography (sun, cloud, partly, rain, snow, storm, fog)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    cx = rect.center().x()
    cy = rect.center().y()

    def _draw_cloud_path(base_x: float, base_y: float, w: float = 16.0, h: float = 10.0, col: QColor = COLOR_WX_CLOUD) -> None:
        left = base_x - w / 2.0
        base_h = h * 0.62
        base = QPainterPath()
        base.addRoundedRect(QRectF(left, base_y, w, base_h), base_h / 2.0, base_h / 2.0)

        small = QPainterPath()
        d1 = h * 0.78
        small.addEllipse(QRectF(left + w * 0.12, base_y + base_h * 0.55 - d1, d1, d1))

        big = QPainterPath()
        d2 = h * 1.05
        big.addEllipse(QRectF(left + w * 0.36, base_y + base_h * 0.62 - d2, d2, d2))

        cloud = base.united(small).united(big)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPath(cloud)

    if icon == "sun":
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_WX_SUN)
        p.drawEllipse(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0))
        pen = QPen(COLOR_WX_SUN, 1.6, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        for i in range(8):
            ang = i * math.pi / 4.0
            p.drawLine(
                QPointF(cx + 7.0 * math.cos(ang), cy + 7.0 * math.sin(ang)),
                QPointF(cx + 9.5 * math.cos(ang), cy + 9.5 * math.sin(ang)),
            )
    elif icon == "partly":
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_WX_SUN)
        p.drawEllipse(QRectF(cx, cy - 7.0, 8.0, 8.0))
        _draw_cloud_path(cx - 2.0, cy - 2.0, 16.0, 10.0)
    elif icon in ("rain", "drizzle"):
        _draw_cloud_path(cx, cy - 5.0, 16.0, 10.0)
        p.setPen(QPen(COLOR_WX_RAIN, 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 4.0, cy + 5.0), QPointF(cx - 5.0, cy + 9.0))
        p.drawLine(QPointF(cx, cy + 5.0), QPointF(cx - 1.0, cy + 9.0))
        p.drawLine(QPointF(cx + 4.0, cy + 5.0), QPointF(cx + 3.0, cy + 9.0))
    elif icon == "snow":
        _draw_cloud_path(cx, cy - 5.0, 16.0, 10.0)
        p.setPen(QPen(COLOR_WX_SNOW, 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawPoint(QPointF(cx - 4.0, cy + 7.0))
        p.drawPoint(QPointF(cx, cy + 6.0))
        p.drawPoint(QPointF(cx + 4.0, cy + 7.0))
    elif icon == "storm":
        _draw_cloud_path(cx, cy - 5.0, 16.0, 10.0)
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_WX_LIGHTNING)
        poly = QPainterPath()
        poly.moveTo(cx - 1.0, cy + 3.0)
        poly.lineTo(cx + 3.0, cy + 3.0)
        poly.lineTo(cx, cy + 7.0)
        poly.lineTo(cx + 4.0, cy + 7.0)
        poly.lineTo(cx - 3.0, cy + 13.0)
        poly.lineTo(cx - 1.0, cy + 8.0)
        poly.lineTo(cx - 3.0, cy + 8.0)
        poly.closeSubpath()
        p.drawPath(poly)
    elif icon == "fog":
        _draw_cloud_path(cx, cy - 5.0, 15.0, 9.0)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 7.0, cy + 6.0), QPointF(cx + 7.0, cy + 6.0))
        p.drawLine(QPointF(cx - 5.0, cy + 9.0), QPointF(cx + 5.0, cy + 9.0))
    else:
        _draw_cloud_path(cx, cy - 3.0, 17.0, 11.0)

    p.restore()
