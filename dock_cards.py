"""dock_cards.py - Modern dock v3 modular cards rendering for Şerit dock.

Implements approved 'dock v3' cards:
  - ClaudeCard: 40x40 coral tile (#D97757) with 6-spoke star, Oturum/time-left, %/Hafta %, progress bar
  - MediaCard: 40x40 purple gradient tile (#a2456f -> #4b2a7a) with equalizer bars, title, subtitle, controls
  - SysCard: Optional system telemetry card (İşlemci % / Bellek %)
  - MarketCard: Optional market/FX card (Dolar / Gram altın)
  - CalCard: Up next calendar card with relative day (BUGÜN / YARIN...), title, detail
  - ClockBlock: 70x52 split clock widget (top red HH:MM, bottom weekday + day + weather circle)
  - TrayColumn: 32px stacked tray column (volume button + hidden icons chevron)
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QImage,
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

import panel_style
import sources
import theme

# ==============================================================================
# DIMENSION & COLOR CONSTANTS (dock v3)
# ==============================================================================

CARD_HEIGHT: float = 52.0
CARD_RADIUS: float = 13.0
CARD_FILL: QColor = QColor(255, 255, 255, int(255 * 0.065))   # v24'ten beri bantta çizilmez (eski kutu)
CARD_FILL_HOVER: QColor = QColor(255, 255, 255, 18)           # v24 kutusuz kart: yalnız üzerine gelince
CARD_BORDER: QColor = QColor(255, 255, 255, int(255 * 0.08))
CARD_DIVIDER: QColor = QColor(255, 255, 255, 30)              # kartlar arası ince ayraç (1 cihaz pikseli)
CARD_DIVIDER_H: float = 28.0

# v24 renk düzeni (Emre: B + ortak değişiklikler): Claude turuncusu ve tek mavi vurgu.
COLOR_ACCENT_BLUE: QColor = QColor("#6EA8FE")
COLOR_CLAUDE_TILE: QColor = QColor("#D97757")
COLOR_CLAUDE_CORAL: QColor = QColor("#D97757")
COLOR_CLAUDE_SKY: QColor = QColor(COLOR_ACCENT_BLUE)
COLOR_GEMINI_BLUE: QColor = QColor(COLOR_ACCENT_BLUE)
COLOR_RING_CRITICAL: QColor = QColor("#F87171")
COLOR_CONCENTRIC_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.08))
COLOR_BAR_GREEN: QColor = QColor("#34C759")
COLOR_BAR_AMBER: QColor = QColor("#FF9F0A")
COLOR_BAR_RED: QColor = QColor("#FF453A")
COLOR_BAR_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.13))

COLOR_MEDIA_GRAD_START: QColor = QColor(255, 255, 255, 40)   # v24: pembe-mor yerine nötr medya karosu
COLOR_MEDIA_GRAD_END: QColor = QColor(255, 255, 255, 18)
COLOR_MEDIA_BTN_BG: QColor = QColor(255, 255, 255, int(255 * 0.09))
COLOR_MEDIA_PLAY_BG: QColor = QColor(COLOR_ACCENT_BLUE)

# İşlemci ve bellek aynı mavi; eşik ayrımı get_sys_ring_color(is_ram=...) ile yapılır.
COLOR_CPU_BAR: QColor = QColor(COLOR_ACCENT_BLUE)
COLOR_RAM_BAR: QColor = QColor(COLOR_ACCENT_BLUE)

COLOR_TXT_PRIMARY: QColor = QColor(255, 255, 255, int(255 * 0.95))
COLOR_TXT_MUTED: QColor = QColor(235, 238, 245, int(255 * 0.58))
COLOR_TXT_FAINT: QColor = QColor(235, 238, 245, 102)           # sıfırlanma saati gibi ikincil bilgi
COLOR_CAL_RED: QColor = QColor("#FF453A")

TR_DAYS_SHORT = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}

CLAUDE_CARD_WIDTH: float = 192.0
MEDIA_CARD_WIDTH: float = 314.0
MEDIA_CARD_WIDTH_COMPACT: float = 240.0
AG_CARD_WIDTH: float = 192.0
# Sol kanat sığmazsa Claude/Antigravity kartları bu genişliğe kadar daralır (sıfırlanma yazısı sığmazsa gizlenir)
CONC_CARD_MIN_WIDTH: float = 132.0
MAIL_CARD_MIN_WIDTH: float = 112.0
MAIL_CARD_MAX_WIDTH: float = 150.0
SYS_CARD_WIDTH: float = 96.0
SYS_RING_SIZE: float = 34.0
SYS_RING_STROKE: float = 3.5

_PEN_CARD_BORDER: QPen = QPen(CARD_BORDER, 1.0)
_PEN_BAR_TRACK_2: QPen = QPen(QColor(255, 255, 255, int(255 * 0.14)), 2.0, Qt.SolidLine, Qt.RoundCap)
_PEN_SYS_TRACK: QPen = QPen(COLOR_BAR_TRACK, SYS_RING_STROKE, Qt.SolidLine, Qt.FlatCap)
_PEN_ARC_ACCENT: QPen = QPen(COLOR_ACCENT_BLUE, 2.0, Qt.SolidLine, Qt.RoundCap)
_PEN_BAT_BOLT: QPen = QPen(QColor(13, 15, 19), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

_FM_CACHE: Dict[str, QFontMetricsF] = {}
_TEXT_WIDTH_CACHE: Dict[Tuple[int, str], float] = {}
_ELIDED_CACHE: Dict[Tuple[int, str, float], str] = {}


def _font_key(font: QFont) -> str:
    """Önbellek anahtarı: yazı tipinin tam tanımı + OpenType özellikleri (tnum gibi; toString bunları içermeyebilir)."""
    try:
        tags = ",".join(sorted(str(t.toString()) for t in font.featureTags()))
    except Exception:
        tags = ""
    return f"{font.toString()}|{tags}"


def _get_fm(font: QFont) -> QFontMetricsF:
    key = _font_key(font)
    fm = _FM_CACHE.get(key)
    if fm is None:
        fm = QFontMetricsF(font)
        _FM_CACHE[key] = fm
    return fm


def _text_width(fm: QFontMetricsF, text: str) -> float:
    key = (id(fm), text)
    w = _TEXT_WIDTH_CACHE.get(key)
    if w is None:
        w = fm.horizontalAdvance(text)
        if len(_TEXT_WIDTH_CACHE) > 512:
            _TEXT_WIDTH_CACHE.clear()
        _TEXT_WIDTH_CACHE[key] = w
    return w


def _elided_text(fm: QFontMetricsF, text: str, width: float) -> str:
    key = (id(fm), text, round(width, 1))
    s = _ELIDED_CACHE.get(key)
    if s is None:
        s = fm.elidedText(text, Qt.ElideRight, width)
        if len(_ELIDED_CACHE) > 256:
            _ELIDED_CACHE.clear()
        _ELIDED_CACHE[key] = s
    return s


_PATH_MEDIA_PREV = QPainterPath()
_PATH_MEDIA_PREV.addRoundedRect(QRectF(3.5, 4.0, 2.0, 12.0), 1.0, 1.0)
_PATH_MEDIA_PREV.moveTo(15.7, 5.4)
_PATH_MEDIA_PREV.lineTo(8.7, 9.9)
_PATH_MEDIA_PREV.lineTo(8.7, 10.1)
_PATH_MEDIA_PREV.lineTo(15.7, 14.6)
_PATH_MEDIA_PREV.closeSubpath()

_PATH_MEDIA_PAUSE = QPainterPath()
_PATH_MEDIA_PAUSE.addRoundedRect(QRectF(5.2, 4.0, 3.4, 12.0), 1.7, 1.7)
_PATH_MEDIA_PAUSE.addRoundedRect(QRectF(11.4, 4.0, 3.4, 12.0), 1.7, 1.7)

_PATH_MEDIA_PLAY = QPainterPath()
_PATH_MEDIA_PLAY.moveTo(7.0, 4.5)
_PATH_MEDIA_PLAY.lineTo(7.0, 15.5)
_PATH_MEDIA_PLAY.lineTo(16.0, 10.0)
_PATH_MEDIA_PLAY.closeSubpath()

_PATH_MEDIA_NEXT = QPainterPath()
_PATH_MEDIA_NEXT.addRoundedRect(QRectF(14.5, 4.0, 2.0, 12.0), 1.0, 1.0)
_PATH_MEDIA_NEXT.moveTo(4.3, 5.4)
_PATH_MEDIA_NEXT.lineTo(11.3, 9.9)
_PATH_MEDIA_NEXT.lineTo(11.3, 10.1)
_PATH_MEDIA_NEXT.lineTo(4.3, 14.6)
_PATH_MEDIA_NEXT.closeSubpath()

_EQUALIZER_GRAD_CACHE: Dict[Tuple[float, float, float, float], QLinearGradient] = {}


def _get_equalizer_grad(rect: QRectF) -> QLinearGradient:
    key = (rect.x(), rect.y(), rect.width(), rect.height())
    g = _EQUALIZER_GRAD_CACHE.get(key)
    if g is None:
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, COLOR_MEDIA_GRAD_START)
        g.setColorAt(1.0, COLOR_MEDIA_GRAD_END)
        _EQUALIZER_GRAD_CACHE[key] = g
    return g


def format_reset_display(
    reset_val: Any,
    now_utc: Optional[dt.datetime] = None,
) -> str:
    """Format reset time for D4 concentric card rows.

    If the reset is less than 24h away, returns remaining time like '47 dk', '1 sa 59 dk'.
    Otherwise returns short Turkish weekday + time like 'Per 16:40', 'Cmt 09:00'.
    Unknown -> '—'.
    """
    if not reset_val or not isinstance(reset_val, (str, dt.datetime)):
        return "—"

    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)

    target_dt: Optional[dt.datetime] = None
    if isinstance(reset_val, dt.datetime):
        target_dt = reset_val
    else:
        s = reset_val.strip()
        # 1. Direct relative time pattern like '47 dk', '1 sa 59 dk', '4sa 12dk'
        m_rel = re.match(r"^(\d+)\s*(sa|dk|g)(\s*(\d+)\s*dk)?$", s)
        if m_rel:
            parts = []
            g1, u1 = m_rel.group(1), m_rel.group(2)
            parts.append(f"{g1} {u1}")
            if m_rel.group(4):
                parts.append(f"{m_rel.group(4)} dk")
            return " ".join(parts)

        # 2. Try parsing ISO string
        try:
            clean = s.replace("Z", "+00:00")
            target_dt = dt.datetime.fromisoformat(clean)
        except Exception:
            target_dt = None

    if target_dt is not None:
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=dt.timezone.utc)
        diff_sec = (target_dt - now_utc).total_seconds()
        if diff_sec < 0:
            diff_sec = 0.0
        if diff_sec < 86400.0:  # less than 24h away
            sec = int(round(diff_sec))
            h, rem = divmod(sec, 3600)
            m = (rem % 3600) // 60
            if h > 0 and m > 0:
                return f"{h} sa {m} dk"
            elif h > 0:
                return f"{h} sa"
            else:
                return f"{m} dk"
        else:
            tz_tr = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            # Anthropic sıfırlamayı 05:59:59.79 UTC verir: yalnızca 59. saniyedeki değerler yukarı
            # yuvarlanır ('Cmt 09:00'); diğerleri kesilir (Antigravity 16:40:xx -> 'Per 16:40').
            bump = dt.timedelta(seconds=1) if target_dt.second >= 59 else dt.timedelta(0)
            local_dt = (target_dt + bump).astimezone(tz_tr)
            w_idx = local_dt.weekday()
            w_str = TR_DAYS_SHORT.get(w_idx, "")
            return f"{w_str} {local_dt.hour:02d}:{local_dt.minute:02d}".strip()

    # 3. Fallback for strings that already carry TR weekday and time (e.g. '29 Eki Per 16:40')
    m_tr = re.search(r"(Pzt|Sal|Çar|Per|Cum|Cmt|Paz)\s+(\d{1,2}:\d{2})", str(reset_val))
    if m_tr:
        return f"{m_tr.group(1)} {m_tr.group(2)}"

    return "—"


def draw_concentric_rings_slot(
    p: QPainter,
    slot_rect: QRectF,
    outer_pct: Optional[float],
    outer_color: QColor,
    inner_pct: Optional[float],
    inner_color: QColor,
    logo_pixmap: Optional[QPixmap],
    fallback_icon_fn: Optional[Any] = None,
) -> None:
    """Draw 40x40 concentric rings gauge with centred logo inside.

    viewBox 42x42: outer r=18, inner r=13, stroke 2.2 round caps, clockwise from 12 o'clock.
    Track: rgba(255, 255, 255, 0.08).
    Colours: identity colour below 90%, #F87171 at >= 90%. Missing -> empty track only.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    center = slot_rect.center()
    cx = center.x()
    cy = center.y()
    scale = slot_rect.width() / 42.0
    r_outer = 18.0 * scale
    r_inner = 13.0 * scale
    stroke_w = 2.2 * scale

    rect_outer = QRectF(cx - r_outer, cy - r_outer, 2.0 * r_outer, 2.0 * r_outer)
    rect_inner = QRectF(cx - r_inner, cy - r_inner, 2.0 * r_inner, 2.0 * r_inner)

    # 1. Background tracks
    pen_track = QPen(COLOR_CONCENTRIC_TRACK, stroke_w, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen_track)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(rect_outer)
    p.drawEllipse(rect_inner)

    # 2. Outer ring arc (start 12 o'clock = 90 deg, clockwise = negative span)
    if outer_pct is not None and outer_pct > 0.0:
        val_clamped = max(0.0, min(100.0, float(outer_pct)))
        fg_col = COLOR_RING_CRITICAL if val_clamped >= 90.0 else outer_color
        pen_outer = QPen(fg_col, stroke_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_outer)
        span_angle = -int(round((val_clamped / 100.0) * 360.0 * 16.0))
        p.drawArc(rect_outer, 90 * 16, span_angle)

    # 3. Inner ring arc
    if inner_pct is not None and inner_pct > 0.0:
        val_clamped = max(0.0, min(100.0, float(inner_pct)))
        fg_col = COLOR_RING_CRITICAL if val_clamped >= 90.0 else inner_color
        pen_inner = QPen(fg_col, stroke_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_inner)
        span_angle = -int(round((val_clamped / 100.0) * 360.0 * 16.0))
        p.drawArc(rect_inner, 90 * 16, span_angle)

    # 4. Centred logo
    if logo_pixmap is not None and not logo_pixmap.isNull():
        lw = logo_pixmap.width() / logo_pixmap.devicePixelRatioF()
        lh = logo_pixmap.height() / logo_pixmap.devicePixelRatioF()
        lx = cx - lw / 2.0
        ly = cy - lh / 2.0
        p.drawPixmap(QPointF(lx, ly), logo_pixmap)
    elif fallback_icon_fn is not None:
        fallback_icon_fn(p, slot_rect)

    p.restore()


def draw_concentric_text_rows(
    p: QPainter,
    text_rect: QRectF,
    row1: Tuple[Optional[float], QColor, str, str],
    row2: Tuple[Optional[float], QColor, str, str],
) -> None:
    """Draw two text rows for concentric card (v24):

    Each row: percentage 12.5 DemiBold tabular in ring colour, label 10.5 muted, reset time 9.5 faint
    right-aligned (only when it fits). All three share one baseline per row (different sizes centred
    vertically used to sit on different baselines).
    """
    f_pct = theme.make_font(12.5, QFont.Weight.DemiBold, tabular=True)
    f_lbl = theme.make_font(10.5, QFont.Weight.Normal)
    f_rst = theme.make_font(9.5, QFont.Weight.Normal)

    rx = text_rect.x()
    rw = text_rect.width()
    row_step = 19.0  # iki satırın taban çizgileri arası
    cap = _get_fm(f_pct).capHeight()
    base1 = text_rect.center().y() - (row_step - cap) / 2.0  # görsel blok tam ortada

    p.save()
    for (pct_val, base_col, lbl_text, rst_text), base_y in ((row1, base1), (row2, base1 + row_step)):
        if pct_val is not None:
            pct_num = int(round(float(pct_val)))
            pct_str = f"%{pct_num}"
            pct_col = COLOR_RING_CRITICAL if pct_num >= 90 else base_col
        else:
            pct_str = "—"
            pct_col = COLOR_TXT_MUTED

        # 1. Percent (sets the row baseline)
        p.setFont(f_pct)
        fm_pct = p.fontMetrics()  # cihaz ölçüsü (1.25 ölçekte çizimle aynı)
        p.setPen(pct_col)
        p.drawText(QPointF(rx, base_y), pct_str)
        wp = fm_pct.horizontalAdvance(pct_str)

        # 2. Label (same baseline)
        p.setFont(f_lbl)
        wl = p.fontMetrics().horizontalAdvance(lbl_text)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QPointF(rx + wp + 4.0, base_y), lbl_text)

        # 3. Reset time, right-aligned, only when it fits next to the label
        if rst_text:
            p.setFont(f_rst)
            wr = p.fontMetrics().horizontalAdvance(rst_text)
            if wp + 4.0 + wl + 5.0 + wr <= rw:
                p.setPen(COLOR_TXT_FAINT)
                p.drawText(QPointF(rx + rw - wr, base_y), rst_text)

    p.restore()


def get_progress_bar_color(pct: float) -> QColor:
    """Select green, amber (>=70%), or red (>=90%) for usage bar."""
    if pct >= 90.0:
        return COLOR_BAR_RED
    if pct >= 70.0:
        return COLOR_BAR_AMBER
    return COLOR_BAR_GREEN


def draw_card_base(
    p: QPainter,
    rect: QRectF,
    radius: float = CARD_RADIUS,
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """v24 kutusuz kart (Emre: B): zemin ve çerçeve yok, kart doğrudan bandın üstünde durur; kartlar
    arasını draw_card_divider ayırır. Üzerine gelince hafif zemin (tıklanabilir olduğu belli olsun)."""
    if not hover:
        return
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if press_scale != 1.0:
        pc = rect.center()
        p.translate(pc)
        p.scale(press_scale, press_scale)
        p.translate(-pc)
    p.fillPath(theme.rounded_path(rect, radius), CARD_FILL_HOVER)
    p.restore()


_WX_ICON_DY: Dict[str, float] = {}


def _weather_icon_dy(icon: str) -> float:
    """14x14 hava simgesinin mürekkep ortasının kutu ortasından farkı (aşağı +). Bir kez ölçülür."""
    key = str(icon or "cloud")
    if key in _WX_ICON_DY:
        return _WX_ICON_DY[key]
    dy = 0.0
    try:
        sc = 4.0
        img = QImage(int(24 * sc), int(24 * sc), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(sc)
        img.fill(Qt.transparent)
        pp = QPainter(img)
        theme.draw_weather_icon(pp, QRectF(5.0, 5.0, 14.0, 14.0), icon=key)
        pp.end()
        rows = [y for y in range(img.height()) if any((img.pixel(x, y) >> 24) & 0xFF > 60
                                                      for x in range(0, img.width(), 2))]
        if rows:
            ink_cy = (rows[0] + rows[-1] + 1) / 2.0 / sc
            dy = round((12.0 - ink_cy) * 4.0) / 4.0
    except Exception:
        dy = 0.0
    _WX_ICON_DY[key] = dy
    return dy


def draw_card_divider(p: QPainter, x: float, cy: float, height: float = CARD_DIVIDER_H) -> None:
    """Kartlar arası ince dikey ayraç: 1 cihaz pikseli kalın, cihaz pikseline oturur (1.25'te bulanmaz)."""
    dpr = _device_ratio(p)
    px = round(x * dpr) / dpr
    top = round((cy - height / 2.0) * dpr) / dpr
    bottom = round((cy + height / 2.0) * dpr) / dpr
    p.save()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.fillRect(QRectF(px, top, 1.0 / dpr, bottom - top), CARD_DIVIDER)
    p.restore()


# ==============================================================================
# 1. CLAUDE CARD
# ==============================================================================

APP_DIR = Path(__file__).resolve().parent
_CLAUDE_SVG_CACHE: Dict[Tuple[float, float], QPixmap] = {}


def get_claude_symbol_pixmap(target_size: float = 29.0, dpr: float = 1.0) -> Optional[QPixmap]:
    """Render and cache Claude official symbol Option C (#D97757)."""
    key = (target_size, dpr)
    if key in _CLAUDE_SVG_CACHE:
        return _CLAUDE_SVG_CACHE[key]

    svg_file = APP_DIR / "assets" / "claude-symbol.svg"
    if not svg_file.is_file():
        return None

    try:
        raw_svg = svg_file.read_text(encoding="utf-8")
        # Ensure fill colour is #D97757 (replacing hsl(...) or unset)
        fixed_svg = re.sub(r'fill="[^"]*"', 'fill="#D97757"', raw_svg)
        if 'fill="#D97757"' not in fixed_svg:
            fixed_svg = fixed_svg.replace("<path ", '<path fill="#D97757" ')

        renderer = QSvgRenderer(QByteArray(fixed_svg.encode("utf-8")))
        if not renderer.isValid():
            return None

        px_w = max(1, int(round(target_size * dpr)))
        px_h = max(1, int(round(target_size * dpr)))
        pm = QPixmap(px_w, px_h)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(dpr)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0.0, 0.0, target_size, target_size))
        p.end()

        _CLAUDE_SVG_CACHE[key] = pm
        return pm
    except Exception as exc:
        try:
            sources.log_err("claude_svg_render", exc)
        except Exception:
            pass
        return None


def draw_claude_star_glyph(p: QPainter, rect: QRectF, size: float = 16.0) -> None:
    """Draw 6-spoke rounded star glyph (#D97757) centered inside slot."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    star_lines = [
        (3.50, 12.00, 20.50, 12.00),
        (4.64, 7.75, 19.36, 16.25),
        (7.75, 4.64, 16.25, 19.36),
        (12.00, 3.50, 12.00, 20.50),
        (16.25, 4.64, 7.75, 19.36),
        (19.36, 7.75, 4.64, 16.25),
    ]
    scale = size / 24.0
    sx = rect.x() + (rect.width() - size) / 2.0
    sy = rect.y() + (rect.height() - size) / 2.0
    p.translate(sx, sy)
    p.scale(scale, scale)
    pen = QPen(COLOR_CLAUDE_CORAL, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    for x1, y1, x2, y2 in star_lines:
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.restore()


def draw_claude_tile_star(p: QPainter, rect: QRectF) -> None:
    """Draw 6-spoke rounded star glyph fallback."""
    draw_claude_star_glyph(p, rect, size=16.0)


def draw_claude_card(
    p: QPainter,
    rect: QRectF,
    claude_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders 184x52 Claude card according to D4 'Konsantrik çift halka' spec."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    # 40x40 Slot at left: padding 10px -> x = rect.x() + 10.0, y = rect.y() + 6.0
    slot_rect = QRectF(rect.x() + 10.0, rect.y() + 6.0, 40.0, 40.0)
    dev = p.device()
    dpr = dev.devicePixelRatioF() if dev is not None else 1.0
    claude_pm = get_claude_symbol_pixmap(16.0, dpr)

    # Data
    s_pct = claude_data.get("session")
    w_pct = claude_data.get("week")
    s_reset = claude_data.get("session_reset", "")
    w_reset = claude_data.get("week_reset", "")
    has_err = ("err" in claude_data) or (s_pct is None and w_pct is None and not s_reset and not w_reset)

    outer_pct = float(s_pct) if s_pct is not None else None
    inner_pct = float(w_pct) if w_pct is not None else None

    # Concentric rings slot (Outer: session, Inner: week)
    draw_concentric_rings_slot(
        p,
        slot_rect,
        outer_pct=outer_pct if not has_err else None,
        outer_color=COLOR_CLAUDE_CORAL,
        inner_pct=inner_pct if not has_err else None,
        inner_color=COLOR_CLAUDE_SKY,
        logo_pixmap=claude_pm,
        fallback_icon_fn=draw_claude_tile_star,
    )

    # Right side text area: gap 9px -> x = 10 + 40 + 9 = rect.x() + 59.0
    bx = rect.x() + 59.0
    bw = max(20.0, rect.right() - 10.0 - bx)

    p.save()
    if has_err:
        p.setOpacity(0.65)
        f_err = theme.make_font(10.5, QFont.Weight.Normal)
        p.setFont(f_err)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QRectF(bx, rect.y(), bw, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, "Claude okunamadı")
        p.setOpacity(1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_BAR_AMBER)
        p.drawEllipse(QPointF(rect.right() - 8.0, rect.top() + 8.0), 3.0, 3.0)
        p.restore()
        return

    # Reset strings
    s_reset_str = format_reset_display(s_reset)
    w_reset_str = format_reset_display(w_reset)

    text_rect = QRectF(bx, rect.y() + 8.0, bw, 36.0)
    row1 = (outer_pct, COLOR_CLAUDE_CORAL, "Oturum", s_reset_str)
    row2 = (inner_pct, COLOR_CLAUDE_SKY, "Hafta", w_reset_str)
    draw_concentric_text_rows(p, text_rect, row1, row2)

    p.restore()


# ==============================================================================
# 2. MEDIA CARD
# ==============================================================================

def draw_equalizer_tile(p: QPainter, rect: QRectF, playing: bool = True) -> None:
    """40x40 tile pink-to-purple gradient with 5 white rounded equalizer bars."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    tile_path = theme.rounded_path(rect, 10.0)

    grad = _get_equalizer_grad(rect)
    p.fillPath(tile_path, QBrush(grad))

    # 5 white equalizer bars: static heights 10, 18, 13, 20, 9
    # Width 3px, gap 2.4px (margin 1.2px)
    # Total width = 5 * 3 + 4 * 2.4 = 15 + 9.6 = 24.6px
    bar_w = 3.0
    bar_gap = 2.4
    heights = (10.0, 18.0, 13.0, 20.0, 9.0)
    total_w = len(heights) * bar_w + (len(heights) - 1) * bar_gap
    start_x = rect.x() + (rect.width() - total_w) / 2.0
    cy = rect.center().y()

    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    for i, bh in enumerate(heights):
        bx = start_x + i * (bar_w + bar_gap)
        by = cy - bh / 2.0
        p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 1.5, 1.5)

    p.restore()


def draw_media_card(
    p: QPainter,
    rect: QRectF,
    media_info: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
    hovered_control: Optional[str] = None,
) -> Dict[str, QRectF]:
    """Renders 314x52 media card with tile, title, sub, and playback control buttons.

    Returns hit rects dictionary: {'prev': QRectF, 'playpause': QRectF, 'next': QRectF}
    """
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    # 40x40 Tile at left + 6px padding
    tile_rect = QRectF(rect.x() + 6.0, rect.y() + 6.0, 40.0, 40.0)
    playing = bool(media_info.get("playing", True))
    draw_equalizer_tile(p, tile_rect, playing=playing)

    # Title & Subtitle text column (dynamically shrinks down to 240px compact mode)
    bx = rect.x() + 56.0
    by = rect.y() + 8.0  # ölçüldü: başlık büyük harf üstü .. alt satır tabanı kartın ortasına düşer
    # v24: kontroller (24+8+32+8+24 = 96 px) sağa yaslanır; başlık aradaki tüm boşluğu kullanır
    # (eskiden 314 px kartta başlık 128 px'de kesiliyordu, sağda boşluk kalıyordu).
    ctrl_x = rect.right() - 96.0 - 10.0
    bw = max(20.0, ctrl_x - 8.0 - bx)

    title = str(media_info.get("title") or "Bilinmeyen Başlık")
    app_name = str(media_info.get("app") or "Medya")
    artist = str(media_info.get("artist") or "web yayını")
    sub = f"{app_name} · {artist}"

    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal)

    fm_l = _get_fm(f_lbl)
    fm_s = _get_fm(f_sub)

    elided_title = _elided_text(fm_l, title, bw)
    elided_sub = _elided_text(fm_s, sub, bw)

    p.save()
    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by, bw, 18.0), Qt.AlignLeft | Qt.AlignVCenter, elided_title)

    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by + 18.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)
    p.restore()

    # Controls: prev (glyph), play/pause with B3 track progress ring (32x32), next (glyph)
    cy = rect.center().y()

    # Hit targets: prev (24x28), play (32x32), next (24x28)
    r_prev = QRectF(ctrl_x, cy - 14.0, 24.0, 28.0)
    r_play = QRectF(ctrl_x + 24.0 + 8.0, cy - 16.0, 32.0, 32.0)
    r_next = QRectF(ctrl_x + 24.0 + 8.0 + 32.0 + 8.0, cy - 14.0, 24.0, 28.0)

    # 1. Prev button (plain glyph without circle)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    prev_col = QColor(255, 255, 255) if hovered_control == "prev" else QColor(255, 255, 255, int(255 * 0.55))
    if hovered_control == "prev":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawRoundedRect(r_prev, 6.0, 6.0)

    p.translate(r_prev.center().x(), r_prev.center().y())
    p.scale(14.0 / 20.0, 14.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(prev_col)
    p.drawPath(_PATH_MEDIA_PREV)
    p.restore()

    # 2. Play/Pause button with B3 progress ring
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    pcx = r_play.center().x()
    pcy = r_play.center().y()
    ring_radius = 13.0

    # Hover background under ring
    if hovered_control == "playpause":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawEllipse(r_play)

    # Ring Track
    p.setPen(_PEN_BAR_TRACK_2)
    p.setBrush(Qt.NoBrush)
    ring_rect = QRectF(pcx - ring_radius, pcy - ring_radius, ring_radius * 2.0, ring_radius * 2.0)
    p.drawEllipse(ring_rect)

    pos_s = media_info.get("position_s")
    dur_s = media_info.get("duration_s")
    progress_frac: Optional[float] = None
    if dur_s is not None and float(dur_s) > 0.0:
        d_val = float(dur_s)
        p_val = float(pos_s) if pos_s is not None else 0.0
        # Interpolate if playing and updated_at available
        if playing and "updated_at" in media_info and media_info["updated_at"]:
            try:
                import time
                elapsed = max(0.0, time.monotonic() - float(media_info["updated_at"]))
                p_val += elapsed
            except Exception:
                pass
        progress_frac = max(0.0, min(1.0, p_val / d_val))

    if progress_frac is not None and progress_frac > 0.0:
        p.setPen(_PEN_ARC_ACCENT)
        start_angle = 90 * 16
        span_angle = -int(round(progress_frac * 360.0 * 16.0))
        p.drawArc(ring_rect, start_angle, span_angle)

    # Center Play / Pause Icon
    p.save()
    p.translate(pcx, pcy)
    p.scale(16.0 / 20.0, 16.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawPath(_PATH_MEDIA_PAUSE if playing else _PATH_MEDIA_PLAY)
    p.restore()
    p.restore()

    # 3. Next button (plain glyph without circle)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    next_col = QColor(255, 255, 255) if hovered_control == "next" else QColor(255, 255, 255, int(255 * 0.55))
    if hovered_control == "next":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawRoundedRect(r_next, 6.0, 6.0)

    p.translate(r_next.center().x(), r_next.center().y())
    p.scale(14.0 / 20.0, 14.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(next_col)
    p.drawPath(_PATH_MEDIA_NEXT)
    p.restore()

    return {"prev": r_prev, "playpause": r_play, "next": r_next}


# ==============================================================================
# 2B. MAIL CARD
# ==============================================================================

_GMAIL_SVG_CACHE: Dict[Tuple[float, float], QPixmap] = {}


def get_gmail_pixmap(target_size: float = 28.0, dpr: float = 1.0) -> Optional[QPixmap]:
    """Render and cache Gmail official SVG logo."""
    key = (target_size, dpr)
    if key in _GMAIL_SVG_CACHE:
        return _GMAIL_SVG_CACHE[key]

    svg_file = APP_DIR / "assets" / "gmail.svg"
    if not svg_file.is_file():
        return None

    try:
        renderer = QSvgRenderer(str(svg_file))
        if not renderer.isValid():
            return None

        px_w = max(1, int(round(target_size * dpr)))
        px_h = max(1, int(round(target_size * dpr)))
        pm = QPixmap(px_w, px_h)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(dpr)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # Preserve 88x66 aspect ratio (4:3) centered in square slot
        aspect = 88.0 / 66.0
        draw_w = target_size
        draw_h = draw_w / aspect
        draw_y = (target_size - draw_h) / 2.0
        renderer.render(p, QRectF(0.0, draw_y, draw_w, draw_h))
        p.end()

        _GMAIL_SVG_CACHE[key] = pm
        return pm
    except Exception as exc:
        sources.log_err("get_gmail_pixmap", exc)
        return None


def format_mail_card_text(mail_data: Dict[str, Any]) -> Tuple[str, str, bool, bool]:
    """Extract (val_str, lbl_str, has_err, is_stale) from mail data."""
    has_err = bool(mail_data.get("err")) or ("total_open" not in mail_data and "accounts" not in mail_data)
    is_stale = bool(mail_data.get("stale", False))
    if has_err:
        return "—", "Mail okunamadı", True, is_stale

    total_open = int(mail_data.get("total_open", 0))
    if total_open == 0:
        return "Yanıt yok", "Hepsi yanıtlandı", False, is_stale

    val_str = f"{total_open} bekliyor"
    accounts = mail_data.get("accounts") or []
    parts = [f"{a.get('label', '')} {a.get('open', 0)}" for a in accounts if int(a.get("open", 0)) > 0]
    lbl_str = " · ".join(parts) if parts else "Hepsi yanıtlandı"
    return val_str, lbl_str, False, is_stale


def measure_mail_card_width(mail_data: Dict[str, Any]) -> float:
    """Measure dynamic width for mail card based on content (clamped 112..150 px)."""
    val_str, lbl_str, _err, _stale = format_mail_card_text(mail_data)
    f_val = theme.make_font(14.5, QFont.Weight.DemiBold, tabular=True)
    f_lbl = theme.make_font(11.0, QFont.Weight.Normal)
    fm_v = QFontMetricsF(f_val)
    fm_l = QFontMetricsF(f_lbl)
    w_text = max(fm_v.horizontalAdvance(val_str), fm_l.horizontalAdvance(lbl_str))
    # 10px pad left + 28px logo + 8px gap + text + 10px pad right = 56px + w_text
    w_total = 56.0 + w_text
    return max(MAIL_CARD_MIN_WIDTH, min(MAIL_CARD_MAX_WIDTH, float(math.ceil(w_total))))


def draw_mail_card(
    p: QPainter,
    rect: QRectF,
    mail_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders Mail card (Gmail logo + pending counts) according to mockups v6 spec."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    val_str, lbl_str, has_err, is_stale = format_mail_card_text(mail_data)

    # 28x28 Slot at left with 10px padding
    slot_rect = QRectF(rect.x() + 10.0, rect.y() + (rect.height() - 28.0) / 2.0, 28.0, 28.0)
    dev = p.device()
    dpr = dev.devicePixelRatioF() if dev is not None else 1.0
    pm = get_gmail_pixmap(28.0, dpr)
    if pm is not None and not pm.isNull():
        p.drawPixmap(slot_rect.topLeft(), pm)

    # Body rect (x = rect.x() + 46px)
    bx = rect.x() + 46.0
    by = rect.y() + 8.0
    bw = max(20.0, rect.right() - 10.0 - bx)

    f_val = theme.make_font(14.5, QFont.Weight.DemiBold, tabular=True)
    f_lbl = theme.make_font(11.0, QFont.Weight.Normal)

    p.save()
    p.setFont(f_val)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by, bw, 18.0), Qt.AlignLeft | Qt.AlignVCenter, val_str)

    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by + 18.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, lbl_str)

    # Stale or error indicator: small amber dot top-right
    if is_stale or has_err:
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_BAR_AMBER)
        p.drawEllipse(QPointF(rect.right() - 8.0, rect.top() + 8.0), 3.0, 3.0)

    p.restore()


# ==============================================================================
# 2C. ANTIGRAVITY QUOTA CARD
# ==============================================================================

_AG_ICON_CACHE: Dict[Tuple[float, float], QPixmap] = {}


def get_antigravity_pixmap(target_size: float = 35.0, dpr: float = 1.0) -> Optional[QPixmap]:
    """Load and cache high-quality downscaled Antigravity PNG icon."""
    key = (target_size, dpr)
    if key in _AG_ICON_CACHE:
        return _AG_ICON_CACHE[key]

    png_file = APP_DIR / "assets" / "antigravity.png"
    if not png_file.is_file():
        return None

    try:
        orig = QPixmap(str(png_file))
        if orig.isNull():
            return None
        px = max(1, int(round(target_size * dpr)))
        scaled = orig.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        _AG_ICON_CACHE[key] = scaled
        return scaled
    except Exception as exc:
        sources.log_err("get_antigravity_pixmap", exc)
        return None


def draw_ag_card(
    p: QPainter,
    rect: QRectF,
    ag_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders 184x52 Antigravity quota card according to D4 'Konsantrik çift halka' spec."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    # 40x40 Slot at left: padding 10px -> x = rect.x() + 10.0, y = rect.y() + 6.0
    slot_rect = QRectF(rect.x() + 10.0, rect.y() + 6.0, 40.0, 40.0)
    dev = p.device()
    dpr = dev.devicePixelRatioF() if dev is not None else 1.0
    ag_pm = get_antigravity_pixmap(17.0, dpr)

    has_err = bool(ag_data.get("err")) or not ag_data.get("groups")

    groups = ag_data.get("groups") or []
    # Claude = group labelled 'Claude'
    claude_grp = next((g for g in groups if str(g.get("label", "")).lower() == "claude"), None)
    used_claude: Optional[float] = float(claude_grp["used"]) if (claude_grp and "used" in claude_grp) else None
    claude_reset_raw = (claude_grp.get("reset_at") or claude_grp.get("reset_tr")) if claude_grp else ""

    # Gemini = max 'used' among groups whose label starts with 'Gemini'
    gemini_grps = [g for g in groups if str(g.get("label", "")).startswith("Gemini")]
    used_gemini: Optional[float] = None
    gemini_reset_raw = ""
    if gemini_grps:
        max_grp = max(gemini_grps, key=lambda g: float(g.get("used", 0.0)))
        used_gemini = float(max_grp.get("used", 0.0))
        gemini_reset_raw = max_grp.get("reset_at") or max_grp.get("reset_tr") or ""

    # Concentric rings slot (Outer: Claude quota, Inner: Gemini quota)
    draw_concentric_rings_slot(
        p,
        slot_rect,
        outer_pct=used_claude if not has_err else None,
        outer_color=COLOR_CLAUDE_CORAL,
        inner_pct=used_gemini if not has_err else None,
        inner_color=COLOR_GEMINI_BLUE,
        logo_pixmap=ag_pm,
    )

    # Right side text area: gap 9px -> x = 10 + 40 + 9 = rect.x() + 59.0
    bx = rect.x() + 59.0
    bw = max(20.0, rect.right() - 10.0 - bx)

    p.save()
    if has_err:
        p.setOpacity(0.65)
        f_err = theme.make_font(10.5, QFont.Weight.Normal)
        p.setFont(f_err)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QRectF(bx, rect.y(), bw, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, "Antigravity okunamadı")
        p.setOpacity(1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_BAR_AMBER)
        p.drawEllipse(QPointF(rect.right() - 8.0, rect.top() + 8.0), 3.0, 3.0)
        p.restore()
        return

    # Reset strings
    claude_rst_str = format_reset_display(claude_reset_raw)
    gemini_rst_str = format_reset_display(gemini_reset_raw)

    text_rect = QRectF(bx, rect.y() + 8.0, bw, 36.0)
    row1 = (used_claude, COLOR_CLAUDE_CORAL, "Claude", claude_rst_str)
    row2 = (used_gemini, COLOR_GEMINI_BLUE, "Gemini", gemini_rst_str)
    draw_concentric_text_rows(p, text_rect, row1, row2)

    p.restore()


# ==============================================================================
# 3. SYSTEM CARD (RING GAUGES)
# ==============================================================================

def get_sys_ring_color(val: float, base_col: QColor, is_ram: Optional[bool] = None) -> QColor:
    """Select base, amber, or red for sys ring gauge.

    İşlemci: >=70 turuncu, >=90 kırmızı. Bellek: Emre'nin bilgisayarında normalde %74-77
    olduğu için (27 Eki 2026 ölçümü) >=85 turuncu, >=93 kırmızı; yoksa mor halka hiç görünmezdi.
    """
    if is_ram is None:  # v24'ten beri iki renk aynı: nesne kimliğine bak (eski çağrılar için)
        is_ram = base_col is COLOR_RAM_BAR
    red_at, amber_at = (93.0, 85.0) if is_ram else (90.0, 70.0)
    if val >= red_at:
        return COLOR_BAR_RED
    if val >= amber_at:
        return COLOR_BAR_AMBER
    return base_col


def _parse_sys_metric(val: Any) -> Optional[float]:
    """Safely coerce sys metric to float in [0, 100], returns None on invalid/missing/NaN/Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return max(0.0, min(100.0, f))
    except (TypeError, ValueError):
        return None


def draw_sys_card(
    p: QPainter,
    rect: QRectF,
    sys_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
    cpu_disp: Optional[float] = None,
    ram_disp: Optional[float] = None,
    opacity: float = 1.0,
) -> None:
    """Renders 100x52 System card with two circular ring gauges (İşlemci / Bellek)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    eff_op = max(0.0, min(1.0, opacity))
    if eff_op < 1.0:
        p.setOpacity(eff_op)

    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    has_err = bool(sys_data.get("err"))
    raw_cpu = None if has_err else sys_data.get("cpu")
    raw_ram = None if has_err else sys_data.get("ram")

    c_metric = cpu_disp if (cpu_disp is not None and not has_err and raw_cpu is not None) else raw_cpu
    r_metric = ram_disp if (ram_disp is not None and not has_err and raw_ram is not None) else raw_ram

    c_val = _parse_sys_metric(c_metric)
    r_val = _parse_sys_metric(r_metric)

    size = SYS_RING_SIZE
    stroke = SYS_RING_STROKE
    r = (size - stroke) / 2.0
    cy = rect.y() + rect.height() / 2.0

    pad_x = 9.0
    cx_cpu = rect.x() + pad_x + size / 2.0
    cx_ram = rect.x() + rect.width() - pad_x - size / 2.0

    f_num = theme.make_font(11.0, QFont.Weight.DemiBold, tabular=True)

    rings = [
        (cx_cpu, c_val, COLOR_CPU_BAR, False),
        (cx_ram, r_val, COLOR_RAM_BAR, True),
    ]

    for cx, val, base_col, is_ram in rings:
        arc_rect = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)

        # 1. Background full track circle (rgba(255, 255, 255, 0.13))
        p.setPen(_PEN_SYS_TRACK)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(arc_rect)

        # 2. Foreground active arc (clockwise from 12 o'clock)
        if val is not None and val > 0.0:
            fg_col = get_sys_ring_color(val, base_col, is_ram=is_ram)
            pen_fg = QPen(fg_col, stroke, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen_fg)
            span_angle = -int(round((val / 100.0) * 360.0 * 16.0))
            p.drawArc(arc_rect, 90 * 16, span_angle)

        # 3. Percentage number centred inside (no % sign, '–' for missing/err)
        p.setFont(f_num)
        p.setPen(COLOR_TXT_PRIMARY)
        num_str = f"{int(round(val))}" if val is not None else "–"
        text_rect = QRectF(cx - r, cy - r - 0.5, 2.0 * r, 2.0 * r)
        p.drawText(text_rect, Qt.AlignCenter, num_str)

    p.restore()


# ==============================================================================
# 4. MARKET CARD (OPTIONAL)
# ==============================================================================

def draw_market_card(
    p: QPainter,
    rect: QRectF,
    fx_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders 160x52 Market card with Dolar and Gram altın rows."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    raw_usd = fx_data.get("usd")
    if isinstance(raw_usd, dict):
        usd_rate = raw_usd.get("buying") or raw_usd.get("rate")
        usd_delta = raw_usd.get("change") or raw_usd.get("usd_chg")
    else:
        usd_rate = raw_usd
        usd_delta = fx_data.get("usd_chg")

    raw_gold = fx_data.get("gold")
    if isinstance(raw_gold, dict):
        gold_rate = raw_gold.get("buying") or raw_gold.get("rate")
        gold_delta = raw_gold.get("change") or raw_gold.get("gold_chg")
    else:
        gold_rate = raw_gold
        gold_delta = fx_data.get("gold_chg")

    usd_rate_f = sources._safe_float(usd_rate, None)
    usd_delta_f = sources._safe_float(usd_delta, None)
    gold_rate_f = sources._safe_float(gold_rate, None)
    gold_delta_f = sources._safe_float(gold_delta, None)

    usd_val_str = sources.fmt_tr(usd_rate_f, dec=2) if (usd_rate_f is not None and usd_rate_f > 0) else "—"
    gold_val_str = (
        sources.fmt_tr(gold_rate_f, dec=0 if gold_rate_f > 100 else 2)
        if (gold_rate_f is not None and gold_rate_f > 0)
        else "—"
    )

    if usd_delta_f is not None:
        usd_up = usd_delta_f >= 0.0
        usd_d_str = f"▲%{sources.fmt_tr(abs(usd_delta_f), dec=2)}" if usd_up else f"▼%{sources.fmt_tr(abs(usd_delta_f), dec=2)}"
    else:
        usd_up = True
        usd_d_str = "—"

    if gold_delta_f is not None:
        gold_up = gold_delta_f >= 0.0
        gold_d_str = f"▲%{sources.fmt_tr(abs(gold_delta_f), dec=2)}" if gold_up else f"▼%{sources.fmt_tr(abs(gold_delta_f), dec=2)}"
    else:
        gold_up = True
        gold_d_str = "—"

    f_sub = theme.make_font(11.0, QFont.Weight.Normal)
    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold, tabular=True)
    f_delta = theme.make_font(11.0, QFont.Weight.DemiBold, tabular=True)

    pad_x = 12.0
    bx = rect.x() + pad_x
    bw = rect.width() - pad_x * 2.0
    by = rect.y() + 8.0

    p.save()
    # Row 1: Dolar
    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by, 50.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, "Dolar")

    # Right portion
    p.setFont(f_delta)
    if usd_delta_f is None:
        p.setPen(COLOR_TXT_MUTED)
    else:
        p.setPen(COLOR_BAR_GREEN if usd_up else COLOR_BAR_RED)
    fm_d = QFontMetricsF(f_delta)
    dw1 = fm_d.horizontalAdvance(usd_d_str)
    p.drawText(QRectF(bx + bw - dw1, by, dw1, 16.0), Qt.AlignRight | Qt.AlignVCenter, usd_d_str)

    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    fm_l = QFontMetricsF(f_lbl)
    vw1 = fm_l.horizontalAdvance(usd_val_str)
    p.drawText(QRectF(bx + bw - dw1 - vw1 - 5.0, by, vw1, 16.0), Qt.AlignRight | Qt.AlignVCenter, usd_val_str)

    # Row 2: Gram altın
    by2 = by + 18.0
    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by2, 70.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, "Gram altın")

    p.setFont(f_delta)
    if gold_delta_f is None:
        p.setPen(COLOR_TXT_MUTED)
    else:
        p.setPen(COLOR_BAR_GREEN if gold_up else COLOR_BAR_RED)
    dw2 = fm_d.horizontalAdvance(gold_d_str)
    p.drawText(QRectF(bx + bw - dw2, by2, dw2, 16.0), Qt.AlignRight | Qt.AlignVCenter, gold_d_str)

    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    vw2 = fm_l.horizontalAdvance(gold_val_str)
    p.drawText(QRectF(bx + bw - dw2 - vw2 - 5.0, by2, vw2, 16.0), Qt.AlignRight | Qt.AlignVCenter, gold_val_str)

    p.restore()


# ==============================================================================
# 5. CALENDAR CARD
# ==============================================================================

def parse_calendar_event(cal_data: Dict[str, Any]) -> Tuple[str, str, str]:
    """Parse store['cal'] into (when_str, title_str, detail_str).

    Rule:
      - Line 1: sources.event_when(event) in UPPERCASE (e.g. 'BUGÜN', 'YARIN')
      - Line 2 & Line 3:
          Strip leading emoji/symbols from title.
          If title contains ' – ' or ' - ' and the last part contains a digit:
             head = Line 2, last part = Line 3 (e.g. 'Vergi: Örnek vergi' / '1.234,56 TL')
          Else:
             Line 2 = title, Line 3 = time range or 'Tüm gün'
      - If no events: ('TAKVİM', 'Bugün boş', '')
    """
    if cal_data.get("err"):
        return ("TAKVİM", "Takvim okunamadı", "")
    events = cal_data.get("events") or []
    nxt = cal_data.get("next")
    if not nxt and events:
        nxt = events[0]

    if not nxt:
        return ("TAKVİM", "Bugün boş", "")

    when = sources.event_when(nxt).upper()
    if not when:
        when = "TAKVİM"

    raw_title = str(nxt.get("title") or "Etkinlik").strip()
    # Strip leading non-alphanumeric / emoji characters
    # Baştaki tüm emoji/simgeleri at (💸, 🇫🇷, ✅ ...): harf, rakam veya '(' görene kadar
    import re
    clean_title = re.sub(r"^[^\w(]+", "", raw_title).strip()
    if not clean_title:
        clean_title = raw_title

    # Check separator ' – ' or ' - '
    line2 = clean_title
    line3 = ""

    sep = " – " if " – " in clean_title else (" - " if " - " in clean_title else None)
    if sep:
        parts = clean_title.split(sep)
        last_part = parts[-1].strip()
        if any(c.isdigit() for c in last_part):
            line2 = sep.join(parts[:-1]).strip()
            line3 = last_part

    if not line3:
        st = nxt.get("start")
        en = nxt.get("end")
        if nxt.get("all_day"):
            line3 = "Tüm gün"
        elif isinstance(st, dt.datetime) and isinstance(en, dt.datetime):
            line3 = f"{st.strftime('%H:%M')} – {en.strftime('%H:%M')}"
        elif isinstance(st, dt.datetime):
            line3 = st.strftime("%H:%M")
        else:
            line3 = ""

    return (when, line2, line3)


def measure_calendar_card_width(cal_data: Dict[str, Any]) -> float:
    """Measure dynamic width of Calendar card (min 96, max 170)."""
    when, line2, line3 = parse_calendar_event(cal_data)
    f_when = theme.make_font(11.0, QFont.Weight.Bold, letter_spacing=0.2)
    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal)

    fm_w = QFontMetricsF(f_when)
    fm_l = QFontMetricsF(f_lbl)
    fm_s = QFontMetricsF(f_sub)

    w_text = max(
        fm_w.horizontalAdvance(when),
        fm_l.horizontalAdvance(line2),
        fm_s.horizontalAdvance(line3) if line3 else 0.0,
    )
    clamped_w = max(96.0, min(170.0, w_text))
    return clamped_w + 24.0  # padding: 12px left + 12px right


def draw_calendar_card(
    p: QPainter,
    rect: QRectF,
    cal_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders Calendar card without tile."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    when, line2, line3 = parse_calendar_event(cal_data)

    f_when = theme.make_font(11.0, QFont.Weight.Bold, letter_spacing=0.2)
    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal)

    pad_x = 12.0
    bx = rect.x() + pad_x
    bw = rect.width() - pad_x * 2.0

    fm_l = QFontMetricsF(f_lbl)
    fm_s = QFontMetricsF(f_sub)
    elided_l2 = fm_l.elidedText(line2, Qt.ElideRight, bw)
    elided_l3 = fm_s.elidedText(line3, Qt.ElideRight, bw) if line3 else ""

    p.save()
    if elided_l3:
        # 3-line layout: when (14px) + title (16px) + detail (14px) = 44px
        by = rect.y() + (rect.height() - 44.0) / 2.0
        # Line 1: when in red
        p.setFont(f_when)
        p.setPen(COLOR_CAL_RED)
        p.drawText(QRectF(bx, by, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, when)

        # Line 2: title
        p.setFont(f_lbl)
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QRectF(bx, by + 14.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_l2)

        # Line 3: detail
        p.setFont(f_sub)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QRectF(bx, by + 30.0, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, elided_l3)
    else:
        # 2-line layout: vertically centered in 52px card (14px + 2px gap + 16px = 32px)
        by = rect.y() + (rect.height() - 32.0) / 2.0
        # Line 1: when in red
        p.setFont(f_when)
        p.setPen(COLOR_CAL_RED)
        p.drawText(QRectF(bx, by, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, when)

        # Line 2: title
        p.setFont(f_lbl)
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QRectF(bx, by + 16.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_l2)

    p.restore()


# ==============================================================================
# 6. CLOCK V1 'SADE'
# ==============================================================================

TR_MONTHS: Dict[int, str] = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}


def format_clock_v1_date(d: dt.date) -> str:
    """Format date for Clock V1, e.g. 'Sal, 27 Ekim'."""
    weekday = TR_DAYS_SHORT.get(d.weekday(), "")
    month_name = TR_MONTHS.get(d.month, "")
    return f"{weekday}, {d.day} {month_name}"


def measure_clock_v1_width(
    now: Optional[dt.datetime] = None,
    temp_str: Optional[str] = None,
    has_weather: bool = True,
) -> float:
    """Measure exact width for Clock V1 Sade based on typography metrics."""
    if now is None:
        now = dt.datetime.now(sources.LOCAL_TZ)
    time_str = now.strftime("%H:%M")
    date_str = format_clock_v1_date(now.date())

    f_time = theme.make_font(20.0, QFont.Weight.DemiBold, tabular=True, letter_spacing=-0.3)
    f_date = theme.make_font(11.0, QFont.Weight.Medium)

    fm_time = _get_fm(f_time)
    fm_date = _get_fm(f_date)
    w_time = _text_width(fm_time, time_str)
    w_date = _text_width(fm_date, date_str)
    w_left = max(w_time, w_date)

    w = 10.0 + w_left  # 10px left padding
    if has_weather and temp_str:
        f_temp = theme.make_font(13.0, QFont.Weight.DemiBold)
        fm_temp = _get_fm(f_temp)
        w_temp = _text_width(fm_temp, temp_str)
        # 10px gap + 1px separator + 10px gap + 14px icon + 5px gap + temp_w (v24: ayraç iki yana eşit)
        w += 10.0 + 1.0 + 10.0 + 14.0 + 5.0 + w_temp
    w += 10.0  # 10px right padding
    return float(math.ceil(w))


def draw_clock_v1(
    p: QPainter,
    rect: QRectF,
    temp_str: Optional[str] = None,
    hover: bool = False,
    press_scale: float = 1.0,
    wx_icon: str = "cloud",
    has_weather: bool = True,
    now: Optional[dt.datetime] = None,
) -> Tuple[QRectF, Optional[QRectF]]:
    """Renders Clock V1 'Sade' without box or background.

    Left (if weather available): 14px weather icon + 5px + temp '16°' 13px/600, 8px gap,
      1px separator rgba(255,255,255,.10) 24px high, 12px gap.
    Right (at the band's right edge): time 'HH:MM' 20px/600 tabular, 3px gap,
      date 'Sal, 27 Ekim' 11px/500 rgba(235,238,245,.58); both right-aligned.

    Hover: rounded rect rgba(255,255,255,.07) radius 11 behind whole clock.
    Returns (r_clock, r_wx).
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    if press_scale != 1.0:
        pc = rect.center()
        p.translate(pc)
        p.scale(press_scale, press_scale)
        p.translate(-pc)

    # Hover background: rounded rect rgba(255,255,255,.07) radius 11
    if hover:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.07)))
        p.drawRoundedRect(rect, 11.0, 11.0)

    if now is None:
        now = dt.datetime.now(sources.LOCAL_TZ)
    time_str = now.strftime("%H:%M")
    date_str = format_clock_v1_date(now.date())

    f_time = theme.make_font(20.0, QFont.Weight.DemiBold, tabular=True, letter_spacing=-0.3)
    f_date = theme.make_font(11.0, QFont.Weight.Medium)

    fm_time = _get_fm(f_time)
    fm_date = _get_fm(f_date)
    w_time = _text_width(fm_time, time_str)
    w_date = _text_width(fm_date, date_str)
    w_left = max(w_time, w_date)

    cur_x = rect.x() + 10.0
    r_wx: Optional[QRectF] = None
    cy = rect.center().y()

    # Hava durumu SOLDA, saat en sağ kenarda (27 Eki 2026, Emre: "saat en sağda olsun")
    if has_weather and temp_str:
        wx_left = rect.x()
        icon_y = cy - 7.0 + _weather_icon_dy(wx_icon or "cloud")
        r_icon = QRectF(cur_x, icon_y, 14.0, 14.0)
        p.save()
        p.setOpacity(0.85)
        theme.draw_weather_icon(p, r_icon, icon=wx_icon or "cloud")
        p.restore()
        cur_x += 14.0 + 5.0
        f_temp = theme.make_font(13.0, QFont.Weight.DemiBold)
        fm_temp = _get_fm(f_temp)
        w_temp = _text_width(fm_temp, temp_str)
        p.setFont(f_temp)
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QPointF(cur_x, cy + fm_temp.capHeight() / 2.0), temp_str)  # rakamlar tam ortada
        cur_x += w_temp + 10.0
        sep_x = cur_x
        draw_card_divider(p, sep_x, cy, 24.0)
        cur_x += 1.0 + 10.0
        # Hava durumu tıklama alanı: sol kenardan ayırıcıya kadar
        r_wx = QRectF(wx_left, rect.y(), max(0.0, sep_x + 1.0 - wx_left), rect.height())

    # Saat + tarih (sağa yaslı sütun). Görsel blok = saat rakamlarının üstü .. tarihin taban çizgisi;
    # kutu yüksekliğine göre ortalamak bloğu 1,5 px aşağıda bırakıyordu (v24 ölçümü).
    gap_td = 9.5  # saat tabanı -> tarih büyük harf üstü
    cap_t, cap_d = fm_time.capHeight(), fm_date.capHeight()
    time_base = cy - (cap_t + gap_td + cap_d) / 2.0 + cap_t
    date_base = time_base + gap_td + cap_d
    right_x = cur_x + w_left

    p.setFont(f_time)
    p.setPen(Qt.white)
    p.drawText(QPointF(right_x - p.fontMetrics().horizontalAdvance(time_str), time_base), time_str)

    p.setFont(f_date)
    p.setPen(QColor(235, 238, 245, int(255 * 0.58)))
    p.drawText(QPointF(right_x - p.fontMetrics().horizontalAdvance(date_str), date_base), date_str)

    p.restore()
    return rect, r_wx


def draw_clock_block(
    p: QPainter,
    rect: QRectF,
    temp_str: Optional[str] = None,
    hover: bool = False,
    press_scale: float = 1.0,
    wx_icon: str = "cloud",
    has_weather: bool = True,
    now: Optional[dt.datetime] = None,
) -> Tuple[QRectF, Optional[QRectF]]:
    """Backward-compatible clock block routing to draw_clock_v1."""
    return draw_clock_v1(
        p=p,
        rect=rect,
        temp_str=temp_str,
        hover=hover,
        press_scale=press_scale,
        wx_icon=wx_icon,
        has_weather=has_weather,
        now=now,
    )


# ==============================================================================
# 7. QUICK ACTION BUTTONS & TRAY CLUSTER
# ==============================================================================

PILL_W_2 = 74.0   # güneş | hoparlör
PILL_W_3 = 136.0  # güneş | hoparlör | pil
BATTERY_PILL_W: float = 80.0   # yalnız pil kapsülü (dock'ta tek parça)

# Pil glifi ölçüleri (mantıksal px; çizim cihaz pikseline hizalanır)
BATTERY_BODY_W: float = 20.0
BATTERY_BODY_H: float = 10.0
BATTERY_TIP_W: float = 2.0
BATTERY_TIP_H: float = 4.0
BATTERY_FILL_INSET: float = 2.0
BATTERY_GLYPH_W: float = 23.0   # v22-C yuvarlak pil gövdesi (kapsül)
BATTERY_GLYPH_H: float = 11.5


def pill_width(has_battery: bool) -> float:
    """Kapsül genişliği: pil bölümü yalnızca pil verisi bilindiğinde eklenir."""
    return PILL_W_3 if has_battery else PILL_W_2


def battery_color(percent: Optional[float], charging: bool) -> QColor:
    """Şarjda yeşil (OK), boşta beyaz; <=20 ve şarjda değilse DANGER kırmızısı."""
    if charging:
        return QColor(panel_style.OK)
    if percent is not None and percent <= 20:
        return QColor(panel_style.DANGER)
    return QColor(255, 255, 255)


def _device_ratio(p: QPainter) -> float:
    try:
        dev = p.device()
        if dev is not None:
            dpr = float(dev.devicePixelRatioF())
            if dpr > 0.0:
                return dpr
    except Exception:
        pass
    return 1.0


def _battery_metrics(dpr: float) -> Tuple[int, int, int, int, int]:
    """Glif ölçüleri cihaz pikselinde: gövde, uç, dolgu girintisi (tam sayı)."""
    bw = max(6, int(round(BATTERY_BODY_W * dpr)))
    bh = max(4, int(round(BATTERY_BODY_H * dpr)))
    tw = max(1, int(round(BATTERY_TIP_W * dpr)))
    th = max(2, int(round(BATTERY_TIP_H * dpr)))
    inset = max(1, int(round(BATTERY_FILL_INSET * dpr)))
    return bw, bh, tw, th, inset


def _bolt_path(bx: float, by: float, bw: float, bh: float) -> QPainterPath:
    pts = (
        (0.60, 0.0), (0.15, 0.55), (0.45, 0.55),
        (0.35, 1.0), (0.85, 0.42), (0.55, 0.42),
    )
    path = QPainterPath()
    for i, (px, py) in enumerate(pts):
        pt = QPointF(bx + px * bw, by + py * bh)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


def _paint_battery_bolt(p: QPainter, ix: int, iy: int, iw: int, ih: int, fw: int,
                        col: QColor, dpr: float) -> None:
    """Şimşek gövde içinde: dolgu üstünde PANEL_BG (kesip çıkar), boşlukta renkli."""
    if iw <= 0 or ih <= 0:
        return
    bw = max(3, int(round(4.5 * dpr)))
    bh = min(ih, max(4, int(round(7.0 * dpr))))
    bx = ix + (iw - bw) // 2
    by = iy + (ih - bh) // 2
    path = _bolt_path(bx / dpr, by / dpr, bw / dpr, bh / dpr)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    # dolgu üstünde koyu kesim
    if fw > 0:
        p.save()
        p.setClipRect(QRectF(ix / dpr, iy / dpr, fw / dpr, ih / dpr))
        p.setBrush(QColor(panel_style.PANEL_BG))
        p.drawPath(path)
        p.restore()
    # dolgusuz (koyu) alanda yeşil şimşek
    if fw < iw:
        p.save()
        p.setClipRect(QRectF((ix + fw) / dpr, iy / dpr, (iw - fw) / dpr, ih / dpr))
        p.setBrush(col)
        p.drawPath(path)
        p.restore()
    p.restore()


def _paint_battery_glyph(p: QPainter, left_dev: int, top_dev: int, percent: Optional[float],
                         charging: bool, col: QColor, dpr: float) -> int:
    """Pil glifini cihaz pikseline hizalı çizer; toplam cihaz pikseli genişliğini döndürür."""
    bw, bh, tw, th, inset = _battery_metrics(dpr)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    pen_w = 1.0 / dpr
    p.setPen(QPen(col, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF((left_dev + 0.5) / dpr, (top_dev + 0.5) / dpr,
                      (bw - 1) / dpr, (bh - 1) / dpr))
    # uç (dolu, tam cihaz pikseli)
    tip_top = top_dev + (bh - th) // 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    p.drawRect(QRectF((left_dev + bw) / dpr, tip_top / dpr, tw / dpr, th / dpr))
    # dolgu (tam cihaz pikseli)
    lvl = 0.0 if percent is None else max(0.0, min(100.0, float(percent)))
    iw = bw - 2 * inset
    ih = bh - 2 * inset
    fw = 0
    if lvl > 0.0 and iw > 0 and ih > 0:
        fw = int(round(iw * lvl / 100.0))
        fw = max(1, min(iw, fw))
        p.drawRect(QRectF((left_dev + inset) / dpr, (top_dev + inset) / dpr,
                          fw / dpr, ih / dpr))
        if charging:
            _paint_battery_bolt(p, left_dev + inset, top_dev + inset, iw, ih, fw, col, dpr)
    elif charging:
        # seviye bilinmiyor: yine de şarj işareti görünsün
        _paint_battery_bolt(p, left_dev + inset, top_dev + inset, iw, ih, 0, col, dpr)
    p.restore()
    return bw + tw


def _draw_battery_segment(p: QPainter, r: QRectF, percent: float, charging: bool, bright: bool) -> None:
    col = battery_color(percent, charging)
    if col == QColor(255, 255, 255) and not bright:
        col = QColor(255, 255, 255, int(255 * 0.85))
    dpr = _device_ratio(p)
    bw, bh, tw, _th, _inset = _battery_metrics(dpr)
    glyph_w = bw + tw
    f = theme.make_font(12.0, QFont.Weight.DemiBold, tabular=True)
    fm = _get_fm(f)
    lvl = max(0.0, min(100.0, float(percent)))
    txt = f"%{int(round(lvl))}"
    gap = 5.0
    content_w = glyph_w / dpr + gap + _text_width(fm, txt)
    left_log = r.center().x() - content_w / 2.0
    left_dev = int(round(left_log * dpr))
    cy_dev = int(round(r.center().y() * dpr))
    top_dev = cy_dev - bh // 2
    p.save()
    _paint_battery_glyph(p, left_dev, top_dev, lvl, charging, col, dpr)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setFont(f)
    p.setPen(col)
    tx = (left_dev + glyph_w) / dpr + gap
    p.drawText(QRectF(tx, r.top(), max(0.0, r.right() - tx - 1.0), r.height()),
               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
    p.restore()


def _snap_rect(r: QRectF, dpr: float) -> QRectF:
    """Dikdörtgen kenarlarını cihaz pikseline yuvarlar (kesirli ölçekte keskin kenar)."""
    left = round(r.left() * dpr) / dpr
    top = round(r.top() * dpr) / dpr
    right = round(r.right() * dpr) / dpr
    bottom = round(r.bottom() * dpr) / dpr
    return QRectF(left, top, right - left, bottom - top)


def _rounded_path(r: QRectF, radius: float) -> QPainterPath:
    return theme.rounded_path(r, radius)


_BOLT_PTS = ((0.62, 0.0), (0.12, 0.56), (0.46, 0.56), (0.36, 1.0), (0.88, 0.42), (0.54, 0.42))
_BOLT_PATH_CACHE: Dict[Tuple[float, float, float, float], QPainterPath] = {}


def _get_bolt_path(cx: float, cy: float, w_: float, h: float) -> QPainterPath:
    key = (round(cx, 2), round(cy, 2), round(w_, 2), round(h, 2))
    b = _BOLT_PATH_CACHE.get(key)
    if b is None:
        b = QPainterPath()
        for i, (px, py) in enumerate(_BOLT_PTS):
            pt = QPointF(cx - w_ / 2.0 + px * w_, cy - h / 2.0 + py * h)
            if i == 0:
                b.moveTo(pt)
            else:
                b.lineTo(pt)
        b.closeSubpath()
        if len(_BOLT_PATH_CACHE) > 64:
            _BOLT_PATH_CACHE.clear()
        _BOLT_PATH_CACHE[key] = b
    return b


def _paint_round_battery(p: QPainter, x: float, cy: float, percent: Optional[float], charging: bool,
                         fill_col: QColor, outline_col: QColor, dpr: float) -> float:
    """v22-C pil glifi: yuvarlak köşeli gövde + uç + yumuşak dolgu; şarjda gövdeye oyulmuş beyaz şimşek.

    Genişliği (mantıksal piksel) döndürür.
    """
    def snap(v: float) -> float:
        return round(v * dpr) / dpr

    bw, bh = BATTERY_GLYPH_W, BATTERY_GLYPH_H
    body = QRectF(snap(x), snap(cy - bh / 2.0), snap(bw), snap(bh))
    pen_w = 1.2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(outline_col, pen_w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_rounded_path(body.adjusted(pen_w / 2, pen_w / 2, -pen_w / 2, -pen_w / 2), 3.2))
    tip = QRectF(body.right() + 1.2, body.center().y() - 2.4, 1.8, 4.8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(outline_col)
    p.drawPath(_rounded_path(tip, 0.9))
    if percent is not None:
        lvl = max(0.0, min(100.0, float(percent)))
        inner = body.adjusted(2.6, 2.6, -2.6, -2.6)
        if lvl > 0.0 and inner.width() > 0 and inner.height() > 0:
            fw = max(inner.height() * 0.6, inner.width() * lvl / 100.0)  # %1 bile görünsün
            p.setBrush(fill_col)
            p.drawPath(_rounded_path(QRectF(inner.left(), inner.top(), fw, inner.height()), 1.6))
    if charging:
        h = bh + 3.0
        w_ = h * 0.62
        bolt = _get_bolt_path(body.center().x(), body.center().y(), w_, h)
        p.setPen(_PEN_BAT_BOLT)
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(bolt)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(bolt)
    p.restore()
    return body.width() + 3.0


def draw_battery_pill(
    p: QPainter,
    rect: QRectF,
    percent: Optional[float],
    charging: bool,
    hovered: bool = False,
    active: bool = False,
) -> QRectF:
    """Yalnız pil (v23 sade): zemin ve ışıma yok; renkli pil simgesi + yüzde doğrudan bantta.

    Renk: şarjda yeşil, <=%20 ve şarjda değilse kırmızı, aksi halde beyaz.
    Üzerine gelince / panel açıkken hafif gri hap zemin (tıklanabilir olduğu belli olsun).
    Tüm kapsül tek isabet alanıdır; kapsül dikdörtgeni döndürülür.
    """
    col = battery_color(percent, charging)
    dpr = _device_ratio(p)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if hovered or active:
        sr = _snap_rect(rect, dpr)  # kesirli ölçekte keskin kenar
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 34 if active else 22))
        p.drawPath(_rounded_path(sr, sr.height() / 2.0))

    f = theme.make_font(13.0, QFont.Weight.DemiBold, tabular=True)
    fm = _get_fm(f)
    txt = "—" if percent is None else f"%{int(round(max(0.0, min(100.0, float(percent)))))}"
    gap = 6.0
    glyph_w = BATTERY_GLYPH_W + 3.0
    content_w = glyph_w + gap + _text_width(fm, txt)
    x = rect.center().x() - content_w / 2.0
    outline = QColor(col)
    outline.setAlpha(150)
    gw = _paint_round_battery(p, x, rect.center().y(), percent, charging, col, outline, dpr)
    p.setFont(f)
    p.setPen(col)
    tx = x + gw + gap
    p.drawText(QRectF(tx, rect.top(), max(0.0, rect.right() - tx - 1.0), rect.height()),
               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
    p.restore()
    return QRectF(rect)


def draw_quick_settings_pill(
    p: QPainter,
    rect: QRectF,
    hovered_part: Optional[str] = None,
    active_part: Optional[str] = None,
    vol_level: float = 100.0,
    vol_muted: bool = False,
    bat_percent: Optional[float] = None,
    bat_charging: bool = False,
    bat_present: bool = False,
):
    """Hızlı ayar kapsülü: güneş | hoparlör [| pil].

    Pil bölümü yalnızca bat_present ve yüzde biliniyorsa çizilir (kapsül o zaman iki bölümlüdür).
    Güneş ve hoparlör 37 px, pil bölümü geri kalan genişliktir. Ayırıcılar 1 x 16 px rgba(255,255,255,.14).
    Döndürür: (r_sun, r_spk) iki bölümde, (r_sun, r_spk, r_bat) üç bölümde.
    """
    show_bat = bool(bat_present) and bat_percent is not None
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.08)), 1.0))
    p.setBrush(QColor(255, 255, 255, int(255 * 0.065)))
    p.drawRoundedRect(rect, 10.0, 10.0)

    if show_bat:
        seg = 37.0
        r_sun = QRectF(rect.x(), rect.y(), seg, rect.height())
        r_spk = QRectF(rect.x() + seg, rect.y(), seg, rect.height())
        r_bat = QRectF(rect.x() + 2 * seg, rect.y(), rect.width() - 2 * seg, rect.height())
    else:
        r_bat = None
        r_sun = QRectF(rect.x(), rect.y(), rect.width() / 2.0, rect.height())
        r_spk = QRectF(rect.x() + rect.width() / 2.0, rect.y(), rect.width() / 2.0, rect.height())
    mid_x = r_spk.x()

    def _inner(r: QRectF, first: bool, last: bool) -> QRectF:
        return r.adjusted(3.0 if first else 2.0, 3.0, -3.0 if last else -2.0, -3.0)

    parts = [("bright", r_sun, True, False), ("vol", r_spk, False, not show_bat)]
    if show_bat:
        parts.append(("bat", r_bat, False, True))
    for key, r, first, last in parts:
        if active_part == key:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(255 * 0.15)))
            p.drawRoundedRect(_inner(r, first, last), 6.0, 6.0)
        elif hovered_part == key:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
            p.drawRoundedRect(_inner(r, first, last), 6.0, 6.0)

    # ayırıcılar (1 x 16)
    div_y = rect.center().y() - 8.0
    p.setPen(QColor(255, 255, 255, int(255 * 0.14)))
    p.drawLine(QPointF(mid_x, div_y), QPointF(mid_x, div_y + 16.0))
    if show_bat:
        p.drawLine(QPointF(r_bat.x(), div_y), QPointF(r_bat.x(), div_y + 16.0))

    # 4. Draw Sun glyph (centered in r_sun)
    # Fluent Sun: viewBox 0 0 20 20, center (10,10) r=3.6, 8 radial lines
    sun_col = QColor(255, 255, 255) if (hovered_part == "bright" or active_part == "bright") else QColor(255, 255, 255, int(255 * 0.85))
    p.save()
    p.translate(r_sun.center().x(), r_sun.center().y())
    p.scale(16.0 / 20.0, 16.0 / 20.0)
    p.translate(-10.0, -10.0)
    pen_sun = QPen(sun_col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen_sun)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(10.0 - 3.6, 10.0 - 3.6, 7.2, 7.2))
    p.drawLine(QPointF(10.0, 2.0), QPointF(10.0, 4.2))
    p.drawLine(QPointF(10.0, 15.8), QPointF(10.0, 18.0))
    p.drawLine(QPointF(2.0, 10.0), QPointF(4.2, 10.0))
    p.drawLine(QPointF(15.8, 10.0), QPointF(18.0, 10.0))
    p.drawLine(QPointF(4.34, 4.34), QPointF(5.9, 5.9))
    p.drawLine(QPointF(14.1, 14.1), QPointF(15.66, 15.66))
    p.drawLine(QPointF(4.34, 15.66), QPointF(5.9, 14.1))
    p.drawLine(QPointF(14.1, 5.9), QPointF(15.66, 4.34))
    p.restore()

    # 5. Draw Speaker glyph (centered in r_spk)
    # Fluent Speaker: viewBox 0 0 20 20, path d="M4 7.2h2.8l4.2-3.7v13l-4.2-3.7H4V7.2z" fill="currentColor"
    # Waves: arc 1: M14.2 6.5c1.6 1.8 1.6 4.8 0 6.6
    #        arc 2: M16.6 4.2c2.8 3.1 2.8 7.9 0 11
    spk_col = QColor(255, 255, 255) if (hovered_part == "vol" or active_part == "vol") else QColor(255, 255, 255, int(255 * 0.85))
    p.save()
    p.translate(r_spk.center().x(), r_spk.center().y())
    p.scale(16.0 / 20.0, 16.0 / 20.0)
    p.translate(-10.0, -10.0)
    pen_spk = QPen(spk_col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen_spk)
    p.setBrush(spk_col)

    spk_body = QPainterPath()
    spk_body.moveTo(4.0, 7.2)
    spk_body.lineTo(6.8, 7.2)
    spk_body.lineTo(11.0, 3.5)
    spk_body.lineTo(11.0, 16.5)
    spk_body.lineTo(6.8, 12.8)
    spk_body.lineTo(4.0, 12.8)
    spk_body.closeSubpath()
    p.drawPath(spk_body)

    if vol_muted:
        # Diagonal slash across speaker
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(3.0, 3.0), QPointF(17.0, 17.0))
    else:
        p.setBrush(Qt.NoBrush)
        lvl = max(0.0, min(100.0, float(vol_level)))
        if lvl > 0.0:
            # 1 sound wave: M14.2 6.5c1.6 1.8 1.6 4.8 0 6.6
            w1 = QPainterPath()
            w1.moveTo(14.2, 6.5)
            w1.cubicTo(15.8, 8.3, 15.8, 11.3, 14.2, 13.1)
            p.drawPath(w1)
        if lvl >= 50.0:
            # 2nd sound wave: M16.6 4.2c2.8 3.1 2.8 7.9 0 11
            w2 = QPainterPath()
            w2.moveTo(16.6, 4.2)
            w2.cubicTo(19.4, 7.3, 19.4, 12.1, 16.6, 15.2)
            p.drawPath(w2)
    p.restore()

    if show_bat:
        _draw_battery_segment(p, r_bat, float(bat_percent), bool(bat_charging),
                              hovered_part == "bat" or active_part == "bat")

    p.restore()
    if show_bat:
        return (r_sun, r_spk, r_bat)
    return (r_sun, r_spk)




def draw_action_button(
    p: QPainter,
    rect: QRectF,
    kind: str,
    hover: bool = False,
    active: bool = False,
    vol_level: float = 100.0,
    vol_muted: bool = False,
) -> None:
    """Draw 30x30 action button: chevron ('tray'), sun ('bright'), or speaker ('vol').

    Radius 8, hover rgba(255,255,255,.10), active rgba(255,255,255,.15).
    Glyph: 18px line icon stroke 1.8-2.2, white 78% (100% on hover/active).
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    if active:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.15)))
        p.drawRoundedRect(rect, 8.0, 8.0)
    elif hover:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawRoundedRect(rect, 8.0, 8.0)

    glyph_col = QColor(255, 255, 255) if (hover or active) else QColor(255, 255, 255, int(255 * 0.78))
    pen = QPen(glyph_col, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()

    if kind == "tray":
        # Chevron-up (18px stroke glyph)
        path_chv = QPainterPath()
        path_chv.moveTo(cx - 5.0, cy + 2.5)
        path_chv.lineTo(cx, cy - 2.5)
        path_chv.lineTo(cx + 5.0, cy + 2.5)
        p.drawPath(path_chv)

    elif kind == "bright":
        # Sun: center circle r=3.5, 8 radial rays
        p.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7.0, 7.0))
        for i in range(8):
            ang = i * math.pi / 4.0
            r1 = 5.5
            r2 = 8.0
            p.drawLine(
                QPointF(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)),
                QPointF(cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)),
            )

    elif kind == "vol":
        # Speaker cone
        spk = QPainterPath()
        spk.moveTo(cx - 6.0, cy - 3.0)
        spk.lineTo(cx - 3.0, cy - 3.0)
        spk.lineTo(cx + 1.0, cy - 7.0)
        spk.lineTo(cx + 1.0, cy + 7.0)
        spk.lineTo(cx - 3.0, cy + 3.0)
        spk.lineTo(cx - 6.0, cy + 3.0)
        spk.closeSubpath()
        p.drawPath(spk)

        if vol_muted:
            # Diagonal slash across speaker
            p.drawLine(QPointF(cx - 4.0, cy - 7.0), QPointF(cx + 7.0, cy + 7.0))
        else:
            lvl = max(0.0, min(100.0, float(vol_level)))
            if lvl > 0.0:
                # 1 sound wave
                w1 = QPainterPath()
                w1.arcMoveTo(QRectF(cx - 1.0, cy - 5.0, 6.0, 10.0), -50.0)
                w1.arcTo(QRectF(cx - 1.0, cy - 5.0, 6.0, 10.0), -50.0, 100.0)
                p.drawPath(w1)
            if lvl >= 50.0:
                # 2 sound waves
                w2 = QPainterPath()
                w2.arcMoveTo(QRectF(cx + 1.0, cy - 8.0, 8.0, 16.0), -50.0)
                w2.arcTo(QRectF(cx + 1.0, cy - 8.0, 8.0, 16.0), -50.0, 100.0)
                p.drawPath(w2)

    p.restore()


# ==============================================================================
# 7. TRAY COLUMN
# ==============================================================================

def draw_tray_column(
    p: QPainter,
    rect: QRectF,
    vol_muted: bool = False,
    hovered_btn: Optional[str] = None,
) -> Tuple[QRectF, QRectF]:
    """Renders 32px wide tray column with stacked Speaker (26x22) and Chevron-up (26x22) buttons.

    Returns (r_speaker, r_chevron).
    """
    btn_w = 26.0
    btn_h = 22.0
    gap = 4.0
    total_h = btn_h * 2 + gap

    bx = rect.x() + (rect.width() - btn_w) / 2.0
    by = rect.y() + (rect.height() - total_h) / 2.0

    r_spk = QRectF(bx, by, btn_w, btn_h)
    r_chv = QRectF(bx, by + btn_h + gap, btn_w, btn_h)

    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    # Speaker button hover
    if hovered_btn == "spk":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawRoundedRect(r_spk, 7.0, 7.0)

    # Chevron button hover
    if hovered_btn == "chv":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.10)))
        p.drawRoundedRect(r_chv, 7.0, 7.0)

    # Draw Speaker icon
    # SVG 24x24: <path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/>
    p.save()
    scx = r_spk.center().x()
    scy = r_spk.center().y()
    p.translate(scx, scy)
    p.scale(14.0 / 24.0, 14.0 / 24.0)
    p.translate(-12.0, -12.0)

    pen = QPen(QColor(255, 255, 255, int(255 * 0.85)), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    spk_path = QPainterPath()
    spk_path.moveTo(4, 9)
    spk_path.lineTo(4, 15)
    spk_path.lineTo(8, 15)
    spk_path.lineTo(13, 19)
    spk_path.lineTo(13, 5)
    spk_path.lineTo(8, 9)
    spk_path.closeSubpath()
    p.drawPath(spk_path)

    if vol_muted:
        # Slash across speaker
        p.drawLine(QPointF(16.0, 8.0), QPointF(21.0, 16.0))
    else:
        # Sound wave arc
        wave_path = QPainterPath()
        wave_path.arcMoveTo(QRectF(11.5, 3.5, 10.0, 17.0), -60.0)
        wave_path.arcTo(QRectF(11.5, 3.5, 10.0, 17.0), -60.0, 120.0)
        p.drawPath(wave_path)
    p.restore()

    # Draw Chevron-up icon
    # SVG 24x24: <path d="M6 15l6-6 6 6"/>
    p.save()
    ccx = r_chv.center().x()
    ccy = r_chv.center().y()
    p.translate(ccx, ccy)
    p.scale(14.0 / 24.0, 14.0 / 24.0)
    p.translate(-12.0, -12.0)

    pen = QPen(QColor(255, 255, 255, int(255 * 0.85)), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    chv_path = QPainterPath()
    chv_path.moveTo(6, 15)
    chv_path.lineTo(12, 9)
    chv_path.lineTo(18, 15)
    p.drawPath(chv_path)
    p.restore()

    p.restore()
    return (r_spk, r_chv)
