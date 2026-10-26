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
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

import sources
import theme

# ==============================================================================
# DIMENSION & COLOR CONSTANTS (dock v3)
# ==============================================================================

CARD_HEIGHT: float = 52.0
CARD_RADIUS: float = 13.0
CARD_FILL: QColor = QColor(255, 255, 255, int(255 * 0.065))
CARD_FILL_HOVER: QColor = QColor(255, 255, 255, int(255 * 0.11))
CARD_BORDER: QColor = QColor(255, 255, 255, int(255 * 0.08))

COLOR_CLAUDE_TILE: QColor = QColor("#D97757")
COLOR_BAR_GREEN: QColor = QColor("#34C759")
COLOR_BAR_AMBER: QColor = QColor("#FF9F0A")
COLOR_BAR_RED: QColor = QColor("#FF453A")
COLOR_BAR_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.13))

COLOR_MEDIA_GRAD_START: QColor = QColor("#a2456f")
COLOR_MEDIA_GRAD_END: QColor = QColor("#4b2a7a")
COLOR_MEDIA_BTN_BG: QColor = QColor(255, 255, 255, int(255 * 0.09))
COLOR_MEDIA_PLAY_BG: QColor = QColor("#0A84FF")

COLOR_CPU_BAR: QColor = QColor("#64D2FF")
COLOR_RAM_BAR: QColor = QColor("#BF5AF2")

COLOR_TXT_PRIMARY: QColor = QColor(255, 255, 255, int(255 * 0.95))
COLOR_TXT_MUTED: QColor = QColor(235, 238, 245, int(255 * 0.58))
COLOR_CAL_RED: QColor = QColor("#FF453A")

TR_DAYS_SHORT = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}


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
    """Draw standard dark glass card background and border."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if press_scale != 1.0:
        pc = rect.center()
        p.translate(pc)
        p.scale(press_scale, press_scale)
        p.translate(-pc)

    path = theme.rounded_path(rect, radius)
    p.fillPath(path, CARD_FILL_HOVER if hover else CARD_FILL)

    border_r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setPen(QPen(CARD_BORDER, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(theme.rounded_path(border_r, max(0.0, radius - 0.5)))
    p.restore()


# ==============================================================================
# 1. CLAUDE CARD
# ==============================================================================

def draw_claude_tile_star(p: QPainter, rect: QRectF) -> None:
    """Draw 40x40 tile radius 10 fill #D97757 with 6-spoke rounded star (colour #1d1410)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    tile_path = theme.rounded_path(rect, 10.0)
    p.fillPath(tile_path, COLOR_CLAUDE_TILE)

    # 6-spoke star matching HTML mockup:
    # 12 lines from center or 6 diametrical lines through center
    # SVG viewBox 0 0 24 24, stroke 2.6, stroke-linecap round
    # The mockup uses:
    # (3.50,12) to (20.50,12)
    # (4.64,7.75) to (19.36,16.25)
    # (7.75,4.64) to (16.25,19.36)
    # (12,3.5) to (12,20.5)
    # (16.25,4.64) to (7.75,19.36)
    # (19.36,7.75) to (4.64,16.25)
    star_lines = [
        (3.50, 12.00, 20.50, 12.00),
        (4.64, 7.75, 19.36, 16.25),
        (7.75, 4.64, 16.25, 19.36),
        (12.00, 3.50, 12.00, 20.50),
        (16.25, 4.64, 7.75, 19.36),
        (19.36, 7.75, 4.64, 16.25),
    ]

    p.save()
    # Star is 28x28 centered in 40x40 rect (mockup: .claude .tile svg { width: 28px; height: 28px; })
    star_size = 28.0
    scale = star_size / 24.0
    sx = rect.x() + (rect.width() - star_size) / 2.0
    sy = rect.y() + (rect.height() - star_size) / 2.0
    p.translate(sx, sy)
    p.scale(scale, scale)

    pen = QPen(QColor("#1d1410"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    for x1, y1, x2, y2 in star_lines:
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.restore()

    p.restore()


def draw_claude_card(
    p: QPainter,
    rect: QRectF,
    claude_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders 182x52 Claude card according to dock v3 spec."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    # 40x40 Tile at left + 6px padding
    tile_rect = QRectF(rect.x() + 6.0, rect.y() + 6.0, 40.0, 40.0)
    draw_claude_tile_star(p, tile_rect)

    # Data
    s_pct = claude_data.get("session")
    w_pct = claude_data.get("week")
    s_reset = claude_data.get("session_reset", "")
    has_err = ("err" in claude_data) or (s_pct is None and w_pct is None and not s_reset)

    time_left = sources.left_text(s_reset) if (s_reset and isinstance(s_reset, str)) else "--"
    if has_err and (not s_reset or time_left == "--"):
        time_left = "–"

    s_pct_val = float(s_pct) if s_pct is not None else 0.0
    w_pct_val = float(w_pct) if w_pct is not None else 0.0

    s_str = f"%{int(round(s_pct_val))}" if s_pct is not None else "–"
    w_str = f"Hafta %{int(round(w_pct_val))}" if w_pct is not None else "Hafta –"

    # Body rect (112px wide, x = tile_right + 10px = rect.x() + 56px)
    bx = rect.x() + 56.0
    by = rect.y() + 7.0
    bw = 112.0

    # Fonts
    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal, tabular=True)
    f_big = theme.make_font(17.0, QFont.Weight.Bold, tabular=True)

    # Row 1: Oturum left + time_left right
    p.save()
    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, "Oturum")

    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by, bw, 14.0), Qt.AlignRight | Qt.AlignVCenter, time_left)

    # Row 2: %XX big left + Hafta %XX right
    p.setFont(f_big)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by + 14.0, bw, 20.0), Qt.AlignLeft | Qt.AlignVCenter, s_str)

    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by + 16.0, bw, 18.0), Qt.AlignRight | Qt.AlignVCenter, w_str)

    # Row 3: 4px progress bar radius 2 (track rgba(255,255,255,0.13))
    bar_y = by + 34.0
    bar_rect = QRectF(bx, bar_y, bw, 4.0)
    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_BAR_TRACK)
    p.drawRoundedRect(bar_rect, 2.0, 2.0)

    # Fill
    fill_w = max(0.0, min(bw, bw * (s_pct_val / 100.0)))
    if fill_w > 0.0 and s_pct is not None:
        fill_color = get_progress_bar_color(s_pct_val)
        p.setBrush(fill_color)
        p.drawRoundedRect(QRectF(bx, bar_y, fill_w, 4.0), 2.0, 2.0)

    # If error / stale, draw a small amber dot in the top right
    if has_err:
        p.setBrush(COLOR_BAR_AMBER)
        p.drawEllipse(QPointF(rect.right() - 8.0, rect.top() + 8.0), 3.0, 3.0)

    p.restore()


# ==============================================================================
# 2. MEDIA CARD
# ==============================================================================

def draw_equalizer_tile(p: QPainter, rect: QRectF, playing: bool = True) -> None:
    """40x40 tile pink-to-purple gradient with 5 white rounded equalizer bars."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    tile_path = theme.rounded_path(rect, 10.0)

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, COLOR_MEDIA_GRAD_START)
    grad.setColorAt(1.0, COLOR_MEDIA_GRAD_END)
    p.fillPath(tile_path, QBrush(grad))

    # 5 white equalizer bars: static heights 10, 18, 13, 20, 9
    # Width 3px, gap 2.4px (margin 1.2px)
    # Total width = 5 * 3 + 4 * 2.4 = 15 + 9.6 = 24.6px
    bar_w = 3.0
    bar_gap = 2.4
    heights = [10.0, 18.0, 13.0, 20.0, 9.0]
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

    # Title & Subtitle text column (128px wide, x = tile_right + 10px = rect.x() + 56px)
    bx = rect.x() + 56.0
    by = rect.y() + 8.0
    bw = 128.0

    title = str(media_info.get("title") or "Bilinmeyen Başlık")
    app_name = str(media_info.get("app") or "Medya")
    artist = str(media_info.get("artist") or "web yayını")
    sub = f"{app_name} · {artist}"

    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal)

    fm_l = QFontMetricsF(f_lbl)
    fm_s = QFontMetricsF(f_sub)

    elided_title = fm_l.elidedText(title, Qt.ElideRight, bw)
    elided_sub = fm_s.elidedText(sub, Qt.ElideRight, bw)

    p.save()
    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by, bw, 18.0), Qt.AlignLeft | Qt.AlignVCenter, elided_title)

    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(bx, by + 18.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)
    p.restore()

    # Controls: prev (30px circle), play/pause (32px circle), next (30px circle)
    # Gap 6px, aligned vertically
    ctrl_x = bx + bw + 4.0
    cy = rect.center().y()

    r_prev = QRectF(ctrl_x, cy - 15.0, 30.0, 30.0)
    r_play = QRectF(ctrl_x + 30.0 + 6.0, cy - 16.0, 32.0, 32.0)
    r_next = QRectF(ctrl_x + 30.0 + 6.0 + 32.0 + 6.0, cy - 15.0, 30.0, 30.0)

    # Prev button
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    prev_bg = QColor(255, 255, 255, int(255 * 0.17)) if hovered_control == "prev" else COLOR_MEDIA_BTN_BG
    p.setPen(Qt.NoPen)
    p.setBrush(prev_bg)
    p.drawEllipse(r_prev)

    # Prev glyph (<svg viewBox="0 0 24 24"><path d="M7 6h2v12H7zM20 6v12l-9-6z"/></svg>)
    pcx = r_prev.center().x()
    pcy = r_prev.center().y()
    p.translate(pcx, pcy)
    p.scale(13.0 / 24.0, 13.0 / 24.0)
    p.translate(-12.0, -12.0)
    p.setBrush(Qt.white)
    path_prev = QPainterPath()
    path_prev.addRect(QRectF(7, 6, 2, 12))
    path_prev.moveTo(20, 6)
    path_prev.lineTo(20, 18)
    path_prev.lineTo(11, 12)
    path_prev.closeSubpath()
    p.drawPath(path_prev)
    p.restore()

    # Play/Pause button
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    play_bg = QColor("#2b95ff") if hovered_control == "playpause" else COLOR_MEDIA_PLAY_BG
    p.setPen(Qt.NoPen)
    p.setBrush(play_bg)
    p.drawEllipse(r_play)

    pcx = r_play.center().x()
    pcy = r_play.center().y()
    p.translate(pcx, pcy)
    p.scale(13.0 / 24.0, 13.0 / 24.0)
    p.translate(-12.0, -12.0)
    p.setBrush(Qt.white)
    path_pp = QPainterPath()
    if playing:
        # Pause: two vertical bars M7 5h4v14H7z M13 5h4v14h-4z
        path_pp.addRect(QRectF(7, 5, 4, 14))
        path_pp.addRect(QRectF(13, 5, 4, 14))
    else:
        # Play: triangle M8 5v14l11-7z
        path_pp.moveTo(8, 5)
        path_pp.lineTo(8, 19)
        path_pp.lineTo(19, 12)
        path_pp.closeSubpath()
    p.drawPath(path_pp)
    p.restore()

    # Next button
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    next_bg = QColor(255, 255, 255, int(255 * 0.17)) if hovered_control == "next" else COLOR_MEDIA_BTN_BG
    p.setPen(Qt.NoPen)
    p.setBrush(next_bg)
    p.drawEllipse(r_next)

    pcx = r_next.center().x()
    pcy = r_next.center().y()
    p.translate(pcx, pcy)
    p.scale(13.0 / 24.0, 13.0 / 24.0)
    p.translate(-12.0, -12.0)
    p.setBrush(Qt.white)
    path_next = QPainterPath()
    path_next.addRect(QRectF(15, 6, 2, 12))
    path_next.moveTo(4, 6)
    path_next.lineTo(4, 18)
    path_next.lineTo(13, 12)
    path_next.closeSubpath()
    p.drawPath(path_next)
    p.restore()

    return {"prev": r_prev, "playpause": r_play, "next": r_next}


# ==============================================================================
# 3. SYSTEM CARD (OPTIONAL)
# ==============================================================================

def draw_sys_card(
    p: QPainter,
    rect: QRectF,
    sys_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders 166x52 System card with two 64px meters (İşlemci / Bellek)."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    cpu_val = float(sys_data.get("cpu", 0.0) or 0.0)
    ram_val = float(sys_data.get("ram", 0.0) or 0.0)

    f_sub = theme.make_font(11.0, QFont.Weight.Normal)
    f_lbl = theme.make_font(12.0, QFont.Weight.DemiBold, tabular=True)

    pad_x = 12.0
    gap = 12.0
    meter_w = 64.0
    by = rect.y() + 11.0

    # Meter 1: CPU
    m1_x = rect.x() + pad_x
    p.save()
    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(m1_x, by, meter_w, 14.0), Qt.AlignLeft | Qt.AlignVCenter, "İşlemci")

    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(m1_x, by, meter_w, 14.0), Qt.AlignRight | Qt.AlignVCenter, f"%{int(round(cpu_val))}")

    # CPU bar
    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_BAR_TRACK)
    p.drawRoundedRect(QRectF(m1_x, by + 16.0, meter_w, 4.0), 2.0, 2.0)
    c_fill = max(0.0, min(meter_w, meter_w * (cpu_val / 100.0)))
    if c_fill > 0.0:
        p.setBrush(COLOR_CPU_BAR)
        p.drawRoundedRect(QRectF(m1_x, by + 16.0, c_fill, 4.0), 2.0, 2.0)

    # Meter 2: RAM
    m2_x = m1_x + meter_w + gap
    p.setFont(f_sub)
    p.setPen(COLOR_TXT_MUTED)
    p.drawText(QRectF(m2_x, by, meter_w, 14.0), Qt.AlignLeft | Qt.AlignVCenter, "Bellek")

    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(m2_x, by, meter_w, 14.0), Qt.AlignRight | Qt.AlignVCenter, f"%{int(round(ram_val))}")

    # RAM bar
    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_BAR_TRACK)
    p.drawRoundedRect(QRectF(m2_x, by + 16.0, meter_w, 4.0), 2.0, 2.0)
    r_fill = max(0.0, min(meter_w, meter_w * (ram_val / 100.0)))
    if r_fill > 0.0:
        p.setBrush(COLOR_RAM_BAR)
        p.drawRoundedRect(QRectF(m2_x, by + 16.0, r_fill, 4.0), 2.0, 2.0)

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

    usd = fx_data.get("usd") or {}
    gold = fx_data.get("gold") or {}

    usd_rate = usd.get("buying") or usd.get("rate") or 49.77
    usd_delta = usd.get("change") or 0.14

    gold_rate = gold.get("buying") or gold.get("rate") or 6419.0
    gold_delta = gold.get("change") or 0.54

    usd_val_str = sources.fmt_tr(usd_rate, dec=2)
    gold_val_str = sources.fmt_tr(gold_rate, dec=0 if gold_rate > 100 else 2)

    usd_up = usd_delta >= 0.0
    gold_up = gold_delta >= 0.0

    usd_d_str = f"▲%{sources.fmt_tr(abs(usd_delta), dec=2)}" if usd_up else f"▼%{sources.fmt_tr(abs(usd_delta), dec=2)}"
    gold_d_str = f"▲%{sources.fmt_tr(abs(gold_delta), dec=2)}" if gold_up else f"▼%{sources.fmt_tr(abs(gold_delta), dec=2)}"

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
             head = Line 2, last part = Line 3 (e.g. 'Vergi: Gelir vergisi' / '1.739,70 TL')
          Else:
             Line 2 = title, Line 3 = time range or 'Tüm gün'
      - If no events: ('TAKVİM', 'Bugün boş', '')
    """
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
    by = rect.y() + 6.0

    fm_l = QFontMetricsF(f_lbl)
    fm_s = QFontMetricsF(f_sub)
    elided_l2 = fm_l.elidedText(line2, Qt.ElideRight, bw)
    elided_l3 = fm_s.elidedText(line3, Qt.ElideRight, bw) if line3 else ""

    p.save()
    # Line 1: when in red
    p.setFont(f_when)
    p.setPen(COLOR_CAL_RED)
    p.drawText(QRectF(bx, by, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, when)

    # Line 2: title
    p.setFont(f_lbl)
    p.setPen(COLOR_TXT_PRIMARY)
    p.drawText(QRectF(bx, by + 14.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_l2)

    # Line 3: detail
    if elided_l3:
        p.setFont(f_sub)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QRectF(bx, by + 28.0, bw, 14.0), Qt.AlignLeft | Qt.AlignVCenter, elided_l3)

    p.restore()


# ==============================================================================
# 6. CLOCK BLOCK
# ==============================================================================

def draw_clock_block(
    p: QPainter,
    rect: QRectF,
    temp_str: str = "12°",
    hover: bool = False,
    press_scale: float = 1.0,
) -> QRectF:
    """Renders 70x52 clipped clock block.

    Top 26px: red gradient (#ff4d2e -> #f23a1d) with HH:MM bold tabular white.
    Bottom 26px: #0f1013 with short weekday (Pzt) over day number (26) left,
                 and 21px light circle #e9e9ec with temperature (9.5px bold dark text) right.

    Returns the QRectF of the temperature circle for hit testing.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    if press_scale != 1.0:
        pc = rect.center()
        p.translate(pc)
        p.scale(press_scale, press_scale)
        p.translate(-pc)

    # Capsule clipping
    clip_path = theme.rounded_path(rect, 13.0)
    p.save()
    p.setClipPath(clip_path)

    # Top 26px
    top_rect = QRectF(rect.x(), rect.y(), rect.width(), 26.0)
    top_grad = QLinearGradient(top_rect.topLeft(), top_rect.bottomLeft())
    top_grad.setColorAt(0.0, QColor("#ff4d2e"))
    top_grad.setColorAt(1.0, QColor("#f23a1d"))
    p.fillRect(top_rect, top_grad)

    now = dt.datetime.now(sources.LOCAL_TZ)
    time_str = now.strftime("%H:%M")

    f_time = theme.make_font(16.0, QFont.Weight.Bold, tabular=True, letter_spacing=0.3)
    p.setFont(f_time)
    p.setPen(Qt.white)
    p.drawText(top_rect, Qt.AlignCenter, time_str)

    # Bottom 26px
    bot_rect = QRectF(rect.x(), rect.y() + 26.0, rect.width(), 26.0)
    p.fillRect(bot_rect, QColor("#0f1013"))

    # Left: Short weekday ('Pzt') and Day ('26')
    weekday_str = TR_DAYS_SHORT.get(now.weekday(), "Pzt")
    day_str = str(now.day)

    f_day_lbl = theme.make_font(8.5, QFont.Weight.Normal)
    f_day_num = theme.make_font(12.5, QFont.Weight.Bold, tabular=True)

    d_x = bot_rect.x() + 7.0
    p.setFont(f_day_lbl)
    p.setPen(QColor(255, 255, 255, int(255 * 0.70)))
    p.drawText(QRectF(d_x, bot_rect.y() + 2.0, 32.0, 10.0), Qt.AlignLeft | Qt.AlignVCenter, weekday_str)

    p.setFont(f_day_num)
    p.setPen(Qt.white)
    p.drawText(QRectF(d_x, bot_rect.y() + 11.0, 32.0, 14.0), Qt.AlignLeft | Qt.AlignVCenter, day_str)

    # Right: 21px light circle #e9e9ec with temperature
    tmp_size = 21.0
    tmp_x = bot_rect.right() - tmp_size - 5.0
    tmp_y = bot_rect.y() + (bot_rect.height() - tmp_size) / 2.0
    r_tmp = QRectF(tmp_x, tmp_y, tmp_size, tmp_size)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e9e9ec"))
    p.drawEllipse(r_tmp)

    f_tmp = theme.make_font(9.5, QFont.Weight.Bold, tabular=True)
    p.setFont(f_tmp)
    p.setPen(QColor("#111111"))
    p.drawText(r_tmp, Qt.AlignCenter, temp_str)

    p.restore()  # End clip

    # Border: 1px solid rgba(255,255,255,0.10)
    border_r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.10)), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(theme.rounded_path(border_r, 12.5))

    p.restore()
    return r_tmp


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
