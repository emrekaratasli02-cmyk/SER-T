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
import time
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
CARD_DIVIDER: QColor = QColor(255, 255, 255, 52)              # kartlar arası ince ayraç (1 cihaz pikseli)
CARD_DIVIDER_H: float = 28.0

FONT_SZ_LBL: float = 10.5
FONT_SZ_META: float = 9.5

# v24 renk düzeni (Emre: B + ortak değişiklikler): Claude turuncusu ve tek mavi vurgu.
COLOR_ACCENT_BLUE: QColor = QColor("#6EA8FE")
COLOR_CLAUDE_TILE: QColor = QColor("#D97757")
COLOR_CLAUDE_CORAL: QColor = QColor("#D97757")  # yalnız marka (logo yıldızı); halkalarda kullanılmaz
# v33 (4 Kas 2026): halka/yüzde renkleri anlam taşır. Normal = mavi (dış halka), açık mavi (iç halka);
# >=75 turuncu, >=90 kırmızı. Tek eşik fonksiyonu: usage_color().
COLOR_RING_OUTER: QColor = QColor(COLOR_ACCENT_BLUE)
COLOR_RING_INNER: QColor = QColor("#A9C8FF")
COLOR_CLAUDE_SKY: QColor = COLOR_RING_INNER
COLOR_GEMINI_BLUE: QColor = COLOR_RING_INNER
# OpenCode kartı: terminal/mavi ton (marka bağımsız, dock paletine uyumlu)
COLOR_OC_TILE: QColor = QColor("#2F6FEB")
COLOR_OC_GLYPH: QColor = QColor(255, 255, 255, 235)
COLOR_RING_WARN: QColor = QColor("#FF9F0A")
COLOR_RING_CRITICAL: QColor = QColor("#F87171")
RING_WARN_AT: float = 75.0
RING_CRIT_AT: float = 90.0
# Tüm bant halkaları için ortak çizgi kalınlığı ve iz rengi
RING_STROKE: float = 3.0
COLOR_RING_TRACK: QColor = QColor(255, 255, 255, int(255 * 0.12))
COLOR_CONCENTRIC_TRACK: QColor = COLOR_RING_TRACK
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
COLOR_TXT_MUTED: QColor = QColor(235, 238, 245, int(255 * 0.74))  # v33: .58 -> .74 (okunurluk)
COLOR_TXT_FAINT: QColor = QColor(235, 238, 245, 168)           # sıfırlanma saati (v33: .52 -> .66)
COLOR_TXT_LABEL: QColor = QColor(235, 238, 245, 180)           # v34: kart etiketi (Medium 10.5)
COLOR_CAL_RED: QColor = QColor("#FF453A")

TR_DAYS_SHORT = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}

CLAUDE_CARD_WIDTH: float = 204.0  # v24: %100 + Oturum + '23 sa 59 dk' sığsın (metin alanı 135)
MEDIA_CARD_WIDTH: float = 314.0
MEDIA_CARD_WIDTH_COMPACT: float = 240.0
AG_CARD_WIDTH: float = 204.0
# Sol kanat sığmazsa Claude/Antigravity kartları bu genişliğe kadar daralır (sıfırlanma yazısı sığmazsa gizlenir)
CONC_CARD_MIN_WIDTH: float = 132.0
MAIL_CARD_MIN_WIDTH: float = 112.0
MAIL_CARD_MAX_WIDTH: float = 150.0
SYS_CARD_WIDTH: float = 96.0
SYS_RING_SIZE: float = 34.0
SYS_RING_STROKE: float = RING_STROKE

_PEN_CARD_BORDER: QPen = QPen(CARD_BORDER, 1.0)
_PEN_BAR_TRACK_2: QPen = QPen(QColor(255, 255, 255, int(255 * 0.14)), 2.0, Qt.SolidLine, Qt.RoundCap)
_PEN_SYS_TRACK: QPen = QPen(COLOR_RING_TRACK, SYS_RING_STROKE, Qt.SolidLine, Qt.FlatCap)
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
        if diff_sec <= 0:
            return "yenilendi"
        if diff_sec < 86400.0:  # less than 24h away
            sec = int(round(diff_sec))
            h, rem = divmod(sec, 3600)
            m = (rem % 3600) // 60
            if h > 0 and m > 0:
                return f"{h} sa {m} dk"
            elif h > 0:
                return f"{h} sa"
            else:
                return f"{max(1, m)} dk"
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


def usage_color(val: Optional[float], base_col: QColor, warn_at: float = RING_WARN_AT,
                crit_at: float = RING_CRIT_AT) -> QColor:
    """Bant halkaları ve yüzdeleri için tek renk kuralı: normal -> base, >=warn turuncu, >=crit kırmızı."""
    if val is None:
        return base_col
    v = float(val)
    if v >= crit_at:
        return COLOR_RING_CRITICAL
    if v >= warn_at:
        return COLOR_RING_WARN
    return base_col


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

    Refined concentric layout:
    - Balanced radii & stroke: r_outer=17.6, r_inner=11.4, stroke=2.6 (optimal inter-ring rhythm).
    - Subtle tinted identity tracks for enhanced contrast & depth against dark dock background.
    - True round caps on active progress arcs, seamless full circle at 100%.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    center = slot_rect.center()
    cx = center.x()
    cy = center.y()
    scale = slot_rect.width() / 40.0
    r_outer = 17.6 * scale
    r_inner = 11.4 * scale
    stroke_w = 2.6 * scale

    rect_outer = QRectF(cx - r_outer, cy - r_outer, 2.0 * r_outer, 2.0 * r_outer)
    rect_inner = QRectF(cx - r_inner, cy - r_inner, 2.0 * r_inner, 2.0 * r_inner)

    # 1. Background tracks (tinted with respective ring identity color for depth & contrast)
    track_outer = QColor(outer_color.red(), outer_color.green(), outer_color.blue(), 58)
    track_inner = QColor(inner_color.red(), inner_color.green(), inner_color.blue(), 52)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(track_outer, stroke_w, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(rect_outer)
    p.setPen(QPen(track_inner, stroke_w, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(rect_inner)

    # 2. Outer ring arc (start 12 o'clock = 90 deg, clockwise = negative span)
    if outer_pct is not None and outer_pct > 0.0:
        val_clamped = max(0.0, min(100.0, float(outer_pct)))
        fg_col = usage_color(val_clamped, outer_color)
        pen_outer = QPen(fg_col, stroke_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_outer)
        if val_clamped >= 99.8:
            p.drawEllipse(rect_outer)
        else:
            span_angle = -int(round((val_clamped / 100.0) * 360.0 * 16.0))
            if span_angle != 0:
                p.drawArc(rect_outer, 90 * 16, span_angle)

    # 3. Inner ring arc
    if inner_pct is not None and inner_pct > 0.0:
        val_clamped = max(0.0, min(100.0, float(inner_pct)))
        fg_col = usage_color(val_clamped, inner_color)
        pen_inner = QPen(fg_col, stroke_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_inner)
        if val_clamped >= 99.8:
            p.drawEllipse(rect_inner)
        else:
            span_angle = -int(round((val_clamped / 100.0) * 360.0 * 16.0))
            if span_angle != 0:
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

    Each row: percentage 12 Bold tabular in ring colour, label 10.5 Medium, reset time 10 faint
    right-aligned (only when it fits). All three share one baseline per row.
    """
    f_pct = theme.make_font(12.0, QFont.Weight.Bold, tabular=True, letter_spacing=-0.2)
    f_lbl = theme.make_font(FONT_SZ_LBL, QFont.Weight.Medium)
    f_rst = theme.make_font(10.0, QFont.Weight.Normal)

    rx = text_rect.x()
    rw = text_rect.width()
    # Sabit yüzde sütunu (%100 genişliği): tüm nokta etiketleri kartlarda aynı hizada dizilir
    f_pct_probe = QFontMetricsF(f_pct)
    col_w = f_pct_probe.horizontalAdvance("%100")
    row_step = 18.5  # iki satırın taban çizgileri arası (optik ritim: 18.5px)
    cap = _get_fm(f_pct).capHeight()
    base1 = text_rect.center().y() - (row_step - cap) / 2.0  # görsel blok tam optik ortada (mid=32.0)

    fm_lbl = QFontMetricsF(f_lbl)
    fm_rst = QFontMetricsF(f_rst)
    rows = ((row1, base1), (row2, base1 + row_step))

    # Her iki satır sütun kuralına sığıyor mu? Sığmıyorsa ama flush (sola dayalı) sığıyorsa
    # dar kart istisnası: yüzde flush çizilir — tam etiket kurtarılır, kırpmaktan iyidir.
    _pre = []
    for (pct_val, _bc, lbl_text, _rs), _by in rows:
        if pct_val is not None:
            _pct = f"%{int(round(float(pct_val)))}"
        else:
            _pct = "—"
        _wl = fm_lbl.horizontalAdvance(lbl_text) if lbl_text else 0.0
        _wp = f_pct_probe.horizontalAdvance(_pct)
        _pre.append((_wl, _wp))
    col_total = col_w + 6.0
    fits_col = all(_wl == 0 or _wl <= rw - col_total for _wl, _wp in _pre)
    fits_flush = all(_wl == 0 or _wl <= rw - _wp - 6.0 for _wl, _wp in _pre)
    use_flush = (not fits_col) and fits_flush

    p.save()
    for (pct_val, base_col, lbl_text, rst_text), base_y in rows:
        if pct_val is not None:
            pct_num = int(round(float(pct_val)))
            pct_str = f"%{pct_num}"
            pct_col = usage_color(pct_num, base_col)
        else:
            pct_str = "—"
            pct_col = COLOR_TXT_MUTED

        # 1. Percent — sabit sütuna sağa hizalı; dar kartta istisna ile flush
        p.setFont(f_pct)
        fm_pct = p.fontMetrics()  # cihaz ölçüsü (1.25 ölçekte çizimle aynı)
        p.setPen(pct_col)
        wp = fm_pct.horizontalAdvance(pct_str)
        if use_flush:
            label_x = rx + wp + 6.0
            p.drawText(QPointF(rx, base_y), pct_str)
            space = rw - wp - 6.0
        else:
            label_x = rx + col_w + 6.0
            p.drawText(QPointF(rx + col_w - wp, base_y), pct_str)
            space = rw - (col_w + 6.0)
        # Yerleşim önceliği: tam etiket + saat sığıyorsa ikisi de; sığmıyorsa saat düşer,
        # etiket tam kalır; etiket de sığmıyorsa kırpılır. Hiçbir durumda üst üste binmez.
        wl = fm_lbl.horizontalAdvance(lbl_text) if lbl_text else 0.0
        wr = fm_rst.horizontalAdvance(rst_text) if rst_text else 0.0
        show_rst = bool(rst_text) and (space - wl) >= (wr + 6.0)
        if show_rst:
            label_w = wl
        elif wl and wl <= space:
            label_w = wl
        else:
            label_w = max(0.0, space)
        if lbl_text and label_w >= 14.0:
            elided_lbl = _elided_text(fm_lbl, lbl_text, label_w)
            if elided_lbl:
                p.setFont(f_lbl)
                p.setPen(COLOR_TXT_LABEL)
                p.drawText(QPointF(label_x, base_y), elided_lbl)
        if show_rst:
            p.setFont(f_rst)
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
    """v24 kutusuz kart: yalnız üzerine gelince zarif akrilik vurgu ve ince specular üst kenar."""
    if not hover:
        return
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if press_scale != 1.0:
        pc = rect.center()
        p.translate(pc)
        p.scale(press_scale, press_scale)
        p.translate(-pc)
    c_path = theme.rounded_path(rect, radius)
    # Akrilik gövde: tepede hafif aydınlık, gövdede pürüzsüzce eriyen yumuşak gradyan
    hover_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    hover_grad.setColorAt(0.00, QColor(255, 255, 255, 28))
    hover_grad.setColorAt(0.35, QColor(255, 255, 255, 18))
    hover_grad.setColorAt(0.70, QColor(255, 255, 255, 12))
    hover_grad.setColorAt(1.00, QColor(255, 255, 255, 7))
    p.fillPath(c_path, hover_grad)

    # İnce specular üst kenar ve akrilik rim: üst kenarda parlaklık, yan ve alt kenarda sönümlenme
    stroke_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    stroke_grad.setColorAt(0.00, QColor(255, 255, 255, 56))
    stroke_grad.setColorAt(0.25, QColor(255, 255, 255, 28))
    stroke_grad.setColorAt(0.70, QColor(255, 255, 255, 12))
    stroke_grad.setColorAt(1.00, QColor(255, 255, 255, 6))
    p.setPen(QPen(QBrush(stroke_grad), 0.8))
    p.drawPath(c_path)
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
    # Dock genelinde sakin ve eşit görünüm: standart CARD_DIVIDER_H yüksekliği ve sakin ayraç rengi
    h = CARD_DIVIDER_H if (height is None or height <= 0 or abs(height - CARD_DIVIDER_H) <= 4.0) else height
    dpr = _device_ratio(p)
    px = round(x * dpr) / dpr
    top = round((cy - h / 2.0) * dpr) / dpr
    bottom = round((cy + h / 2.0) * dpr) / dpr
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


def draw_claude_star_glyph(p: QPainter, rect: QRectF, size: float = 18.0) -> None:
    """Draw crisp Claude star glyph (#D97757) centered inside slot."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()
    stroke_w = 2.1
    r = (size - stroke_w) / 2.0
    d = r * 0.7071
    pen = QPen(COLOR_CLAUDE_CORAL, stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
    p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
    p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    p.restore()


def draw_claude_tile_star(p: QPainter, rect: QRectF) -> None:
    """Draw Claude star glyph fallback."""
    draw_claude_star_glyph(p, rect, size=18.0)


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
    claude_pm = get_claude_symbol_pixmap(18.0, dpr)

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
        outer_color=COLOR_RING_OUTER,
        inner_pct=inner_pct if not has_err else None,
        inner_color=COLOR_CLAUDE_SKY,
        logo_pixmap=claude_pm,
        fallback_icon_fn=draw_claude_tile_star,
    )

    # Right side text area: gap 7px -> x = 10 + 40 + 7 = rect.x() + 57.0, right pad 8px
    bx = rect.x() + 57.0
    bw = max(20.0, rect.right() - 8.0 - bx)

    p.save()
    if has_err:
        p.setRenderHint(QPainter.Antialiasing, True)
        f_title = theme.make_font(FONT_SZ_LBL, QFont.Weight.Medium)
        f_sub = theme.make_font(10.0, QFont.Weight.Normal)
        fm_sub = QFontMetricsF(f_sub)
        p.setFont(f_title)
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QRectF(bx, rect.y() + 9.0, bw - 10.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, "Claude")
        p.setFont(f_sub)
        p.setPen(COLOR_TXT_MUTED)
        p.drawText(QRectF(bx, rect.y() + 27.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, _elided_text(fm_sub, "Okunamadı", bw))
        p.setPen(Qt.NoPen)
        p.setBrush(COLOR_BAR_AMBER)
        p.drawEllipse(QPointF(rect.right() - 8.0, rect.top() + 8.0), 3.0, 3.0)
        p.restore()
        return

    # Reset strings
    s_reset_str = format_reset_display(s_reset)
    w_reset_str = format_reset_display(w_reset)

    text_rect = QRectF(bx, rect.y() + 8.0, bw, 36.0)
    row1 = (outer_pct, COLOR_RING_OUTER, "Oturum", s_reset_str)
    row2 = (inner_pct, COLOR_CLAUDE_SKY, "Hafta", w_reset_str)
    draw_concentric_text_rows(p, text_rect, row1, row2)

    p.restore()


# ==============================================================================
# 2. MEDIA CARD
# ==============================================================================

_ART_DECODE_CACHE: Dict[int, Tuple[Optional[QImage], Optional[QColor]]] = {}


def _decode_media_art(art_bytes: Any) -> Tuple[Optional[QImage], Optional[QColor]]:
    """Decode raw SMTC thumbnail bytes into QImage and extract vibrant dominant accent color."""
    if not isinstance(art_bytes, (bytes, bytearray)) or len(art_bytes) < 16:
        return None, None
    key = hash(bytes(art_bytes[:64])) ^ len(art_bytes)
    cached = _ART_DECODE_CACHE.get(key)
    if cached is not None:
        return cached
    img = QImage.fromData(bytes(art_bytes))
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        _ART_DECODE_CACHE[key] = (None, None)
        return None, None
    # Küçük 16x16 örneklemeden en canlı/doygun rengi bul
    small = img.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    best_r, best_g, best_b, best_w = 10.0, 132.0, 255.0, 0.0
    r_sum = g_sum = b_sum = w_sum = 0.0
    for y in range(small.height()):
        for x in range(small.width()):
            c = QColor(small.pixel(x, y))
            h, s, v, _ = c.getHsvF()
            if v < 0.18 or v > 0.96:
                continue
            w = (s + 0.15) * v
            r_sum += c.red() * w
            g_sum += c.green() * w
            b_sum += c.blue() * w
            w_sum += w
    if w_sum > 0.5:
        avg = QColor(int(r_sum / w_sum), int(g_sum / w_sum), int(b_sum / w_sum))
        h, s, v, _ = avg.getHsvF()
        # Koyu zeminde okunaklı ve canlı olması için doygunluk ve parlaklık dengelenir
        accent = QColor.fromHsvF(max(0.0, h), max(0.55, min(0.90, s * 1.25)), max(0.78, min(0.96, v * 1.15)))
    else:
        accent = None
    if len(_ART_DECODE_CACHE) >= 16:
        _ART_DECODE_CACHE.clear()
    _ART_DECODE_CACHE[key] = (img, accent)
    return img, accent


def draw_equalizer_tile(
    p: QPainter,
    rect: QRectF,
    playing: bool = True,
    phase: Optional[float] = None,
    art_img: Optional[QImage] = None,
    accent_color: Optional[QColor] = None,
    corner_radius: float = 6.0,
) -> None:
    """Recessed well tile with cover art (if available) and 5 symmetric Dynamic Edge equalizer bars."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    tile_path = theme.rounded_path(rect, corner_radius)

    if art_img is not None and not art_img.isNull():
        p.save()
        p.setClipPath(tile_path)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # Kare kırpma (ortadan)
        iw, ih = art_img.width(), art_img.height()
        sz = min(iw, ih)
        src = QRectF((iw - sz) / 2.0, (ih - sz) / 2.0, float(sz), float(sz))
        p.drawImage(rect, art_img, src)
        # Yumuşak dikey scrim: kapağın üstü aydınlık, barlar alt-orta kısımda net okunur
        scrim = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if playing:
            scrim.setColorAt(0.0, QColor(8, 10, 14, 45))
            scrim.setColorAt(0.55, QColor(8, 10, 14, 95))
            scrim.setColorAt(1.0, QColor(8, 10, 14, 135))
        else:
            scrim.setColorAt(0.0, QColor(8, 10, 14, 75))
            scrim.setColorAt(1.0, QColor(8, 10, 14, 140))
        p.fillRect(rect, scrim)
        p.restore()
    else:
        grad = _get_equalizer_grad(rect)
        p.fillPath(tile_path, QBrush(grad))

    # İnce iç kenarlık (vurgu rengi varsa hafif renkli)
    rim_col = QColor(accent_color) if accent_color is not None else QColor(255, 255, 255, 28)
    rim_col.setAlpha(90 if accent_color is not None else 28)
    p.setPen(QPen(rim_col, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(theme.rounded_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), max(1.0, corner_radius - 0.5)))

    # 5 symmetric equalizer bars: Dynamic Edge style [25%, 65%, 100%, 65%, 25%]
    scale = min(rect.width(), rect.height()) / 40.0
    bar_w = 2.6 * scale
    bar_gap = 2.2 * scale
    bar_r = 1.3 * scale
    if not playing:
        heights = (3.2 * scale, 3.2 * scale, 3.2 * scale, 3.2 * scale, 3.2 * scale)
        bar_col = QColor(255, 255, 255, 115)
    else:
        t = time.monotonic() if phase is None else float(phase)
        # Simetrik canlı salınım (merkez bar en yüksek, yanlar simetrik eşlenik)
        w0 = 0.5 + 0.5 * math.sin(t * 3.2)
        w1 = 0.5 + 0.5 * math.sin(t * 4.1 + 1.1)
        w2 = 0.5 + 0.5 * math.sin(t * 5.0 + 2.2)
        h_outer = (6.0 + 4.5 * w0) * scale
        h_mid = (11.5 + 6.0 * w1) * scale
        h_center = (16.0 + 6.0 * w2) * scale
        heights = (h_outer, h_mid, h_center, h_mid, h_outer)
        bar_col = QColor(255, 255, 255, 245)

    total_w = len(heights) * bar_w + (len(heights) - 1) * bar_gap
    start_x = rect.x() + (rect.width() - total_w) / 2.0
    cy = rect.center().y()

    p.setPen(Qt.NoPen)
    # Kapak resmi varsa barların arkasına hafif gölge, kontrastı kusursuzlaştırır
    if art_img is not None and not art_img.isNull() and playing:
        p.setBrush(QColor(0, 0, 0, 80))
        for i, bh in enumerate(heights):
            bx = start_x + i * (bar_w + bar_gap)
            by = cy - bh / 2.0 + 1.0 * scale
            p.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_r, bar_r)

    p.setBrush(bar_col)
    for i, bh in enumerate(heights):
        bx = start_x + i * (bar_w + bar_gap)
        by = cy - bh / 2.0
        p.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_r, bar_r)

    p.restore()


def fmt_media_time(seconds: Any) -> str:
    """Format seconds into 'm:ss' or 'h:mm:ss'. Returns '--:--' if None, NaN or invalid."""
    if seconds is None:
        return "--:--"
    try:
        val = float(seconds)
    except (TypeError, ValueError):
        return "--:--"
    if math.isnan(val) or math.isinf(val):
        return "--:--"
    s = max(0, int(val))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def media_progress_fraction(
    media_info: Dict[str, Any],
    now_monotonic: Optional[float] = None,
) -> Optional[float]:
    """Calculate normalized media playback progress fraction [0.0, 1.0].

    Returns None if duration is unknown, non-positive, or invalid.
    Interpolates position when playing and updated_at timestamp is present.
    """
    if not isinstance(media_info, dict):
        return None
    dur_raw = media_info.get("duration_s")
    if dur_raw is None:
        return None
    try:
        dur = float(dur_raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(dur) or math.isinf(dur) or dur <= 0.0:
        return None

    pos_raw = media_info.get("position_s")
    try:
        pos = float(pos_raw) if pos_raw is not None else 0.0
        if math.isnan(pos) or math.isinf(pos):
            pos = 0.0
    except (TypeError, ValueError):
        pos = 0.0

    playing = bool(media_info.get("playing", True))
    if playing and media_info.get("updated_at") is not None:
        try:
            upd = float(media_info["updated_at"])
            now = time.monotonic() if now_monotonic is None else float(now_monotonic)
            elapsed = max(0.0, now - upd)
            pos += elapsed
        except Exception:
            pass

    return max(0.0, min(1.0, pos / dur))


def media_current_position(
    media_info: Dict[str, Any],
    now_monotonic: Optional[float] = None,
) -> Optional[float]:
    """Returns interpolated current playback position in seconds, or None if unknown."""
    if not isinstance(media_info, dict):
        return None
    pos_raw = media_info.get("position_s")
    if pos_raw is None:
        return None
    try:
        pos = float(pos_raw)
        if math.isnan(pos) or math.isinf(pos):
            return None
    except (TypeError, ValueError):
        return None

    playing = bool(media_info.get("playing", True))
    if playing and media_info.get("updated_at") is not None:
        try:
            upd = float(media_info["updated_at"])
            now = time.monotonic() if now_monotonic is None else float(now_monotonic)
            pos += max(0.0, now - upd)
        except Exception:
            pass

    dur_raw = media_info.get("duration_s")
    if dur_raw is not None:
        try:
            dur = float(dur_raw)
            if not (math.isnan(dur) or math.isinf(dur)) and dur > 0.0:
                pos = min(dur, pos)
        except (TypeError, ValueError):
            pass

    return max(0.0, pos)


MARQUEE_SPEED_PX_S: float = 32.0   # kayan başlık hızı
MARQUEE_PAUSE_S: float = 1.2       # başta ve sonda bekleme
MARQUEE_FADE_PX: float = 10.0      # kenar solma genişliği


def media_title_layout(rect: QRectF) -> Tuple[float, float]:
    """Başlık sütununun (x, genişlik) değeri; draw_media_card ile aynı hesap."""
    bx = rect.x() + 56.0
    ctrl_x = rect.right() - 88.0 - 6.0
    return bx, max(20.0, ctrl_x - 8.0 - bx)


def media_title_overflow(rect: QRectF, title: str) -> float:
    """Başlık sütuna sığmıyorsa taşan piksel miktarı (0 = sığıyor, kayan yazı gerekmez)."""
    _bx, bw = media_title_layout(rect)
    fm = _get_fm(theme.make_font(13.0, QFont.Weight.DemiBold))
    return max(0.0, fm.horizontalAdvance(title or "") - bw)


def marquee_offset(elapsed_s: float, overflow_px: float) -> float:
    """Git-gel kayan yazı ofseti: bekle -> sola kay -> bekle -> geri kay (döngü)."""
    if overflow_px <= 0.0:
        return 0.0
    travel = overflow_px / MARQUEE_SPEED_PX_S
    cycle = 2.0 * (MARQUEE_PAUSE_S + travel)
    t = elapsed_s % cycle
    if t < MARQUEE_PAUSE_S:
        return 0.0
    t -= MARQUEE_PAUSE_S
    if t < travel:
        return overflow_px * _ease_in_out(t / travel)
    t -= travel
    if t < MARQUEE_PAUSE_S:
        return overflow_px
    t -= MARQUEE_PAUSE_S
    return overflow_px * (1.0 - _ease_in_out(min(1.0, t / travel)))


def _ease_in_out(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


def draw_media_card(
    p: QPainter,
    rect: QRectF,
    media_info: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
    hovered_control: Optional[str] = None,
    title_offset: Optional[float] = None,
) -> Dict[str, QRectF]:
    """Renders 314x52 media card with tile, title, sub, and playback control buttons.

    Returns hit rects dictionary: {'prev': QRectF, 'playpause': QRectF, 'next': QRectF}
    """
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    art_img, art_accent = _decode_media_art(media_info.get("art_bytes"))
    # Eğer kapak resmi yoksa ama uygulama biliniyorsa (Spotify = zümrüt, YouTube = kırmızı-mercan) hafif ambient renk
    if art_accent is None and media_info.get("ambient_hex"):
        art_accent = QColor(str(media_info["ambient_hex"]))

    # 40x40 Tile at left + 6px padding
    tile_rect = QRectF(rect.x() + 6.0, rect.y() + 6.0, 40.0, 40.0)
    playing = bool(media_info.get("playing", True))
    draw_equalizer_tile(p, tile_rect, playing=playing, art_img=art_img, accent_color=art_accent)

    # Title & Subtitle text column (dynamically shrinks down to 240px compact mode)
    bx = rect.x() + 56.0
    by = rect.y() + 8.0  # ölçüldü: başlık büyük harf üstü .. alt satır tabanı kartın ortasına düşer
    # v24: kontroller (24+8+32+8+24 = 96 px) sağa yaslanır; başlık aradaki tüm boşluğu kullanır
    # (eskiden 314 px kartta başlık 128 px'de kesiliyordu, sağda boşluk kalıyordu).
    # Estetik: kontroller 24+4+32+4+24 = 88 px, sağ pay 6 -> başlığa ~16 px daha yer.
    ctrl_x = rect.right() - 88.0 - 6.0
    bw = max(20.0, ctrl_x - 8.0 - bx)

    progress_frac = media_progress_fraction(media_info)

    title = str(media_info.get("title") or "Bilinmeyen Başlık")
    tabular_sub = False
    if hover and hovered_control is None:
        cur_pos = media_current_position(media_info)
        dur_s = media_info.get("duration_s")
        sub = f"{fmt_media_time(cur_pos)} / {fmt_media_time(dur_s)}"
        tabular_sub = True
    else:
        app_name = str(media_info.get("app") or "Medya")
        artist_raw = str(media_info.get("artist") or "").strip()
        # v33: YouTube / web yayını başlığı sanatçıyla aynı döndüğünde tekrarı önle ('Chrome · Başlık' yerine sadece 'Chrome')
        if not artist_raw or artist_raw.lower() == "web yayını" or artist_raw.lower() == title.strip().lower():
            sub = app_name
        else:
            sub = f"{app_name} · {artist_raw}"

    f_lbl = theme.make_font(13.0, QFont.Weight.DemiBold)
    f_sub = theme.make_font(11.0, QFont.Weight.Normal, tabular=tabular_sub)

    fm_l = _get_fm(f_lbl)
    fm_s = _get_fm(f_sub)

    elided_sub = _elided_text(fm_s, sub, bw)
    title_w = fm_l.horizontalAdvance(title)
    scrolling = title_offset is not None and title_w > bw

    p.save()
    p.setFont(f_lbl)
    if scrolling:
        # Kayan yazı: sütuna kırp, kenarlarda yumuşak solma (kesik kenar görünmesin)
        off = max(0.0, min(float(title_offset or 0.0), title_w - bw))
        r_title = QRectF(bx, by, bw, 18.0)
        fade = MARQUEE_FADE_PX / bw
        grad = QLinearGradient(bx, 0.0, bx + bw, 0.0)
        c_on = QColor(COLOR_TXT_PRIMARY)
        c_off = QColor(c_on.red(), c_on.green(), c_on.blue(), 0)
        grad.setColorAt(0.0, c_off if off > 0.5 else c_on)
        grad.setColorAt(fade, c_on)
        grad.setColorAt(1.0 - fade, c_on)
        grad.setColorAt(1.0, c_off if off < title_w - bw - 0.5 else c_on)
        p.setClipRect(r_title.adjusted(0.0, -2.0, 0.0, 2.0))
        p.setPen(QPen(QBrush(grad), 1.0))
        p.drawText(QRectF(bx - off, by, title_w + 2.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setClipping(False)
    else:
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QRectF(bx, by, bw, 18.0), Qt.AlignLeft | Qt.AlignVCenter, _elided_text(fm_l, title, bw))

    p.setFont(f_sub)
    sub_col = QColor(255, 255, 255, 205) if tabular_sub else COLOR_TXT_MUTED
    p.setPen(sub_col)
    p.drawText(QRectF(bx, by + 18.0, bw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)
    p.restore()

    # Controls: prev (glyph), play/pause hero button (32x32), next (glyph)
    cy = rect.center().y()

    # Hit targets: prev (24x28), play (32x32), next (24x28)
    r_prev = QRectF(ctrl_x, cy - 14.0, 24.0, 28.0)
    r_play = QRectF(ctrl_x + 24.0 + 4.0, cy - 16.0, 32.0, 32.0)
    r_next = QRectF(ctrl_x + 24.0 + 4.0 + 32.0 + 4.0, cy - 14.0, 24.0, 28.0)

    # 1. Prev button (ikincil kontrol: rölantide sakin, üzerine gelince yumuşak çip)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    prev_hover = (hovered_control == "prev")
    if prev_hover:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r_prev.adjusted(1.0, 2.0, -1.0, -2.0), 6.0, 6.0)

    p.translate(r_prev.center().x(), r_prev.center().y())
    p.scale(13.0 / 20.0, 13.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235 if prev_hover else 125))
    p.drawPath(_PATH_MEDIA_PREV)
    p.restore()

    # 2. Play/Pause button (birincil kahraman kontrol: dairesel gövde + sakin ince ilerleme halkası)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    pcx = r_play.center().x()
    pcy = r_play.center().y()
    play_hover = (hovered_control == "playpause")
    disc_r = 14.0
    disc_rect = QRectF(pcx - disc_r, pcy - disc_r, disc_r * 2.0, disc_r * 2.0)

    # Birincil dairesel buton gövdesi (rölantide varlığını hissettirir, hover'da aydınlanır)
    disc_bg = QColor(255, 255, 255, 48 if play_hover else 22)
    p.setPen(Qt.NoPen)
    p.setBrush(disc_bg)
    p.drawEllipse(disc_rect)

    # İnce, sakin halka izi (1.5px)
    p.setPen(QPen(QColor(255, 255, 255, 18), 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(disc_rect)

    arc_col = QColor(art_accent) if art_accent is not None else QColor(COLOR_ACCENT_BLUE)
    arc_col.setAlpha(180)
    if progress_frac is not None and progress_frac > 0.0:
        arc_pen = QPen(arc_col, 1.5, Qt.SolidLine, Qt.RoundCap)
        p.setPen(arc_pen)
        start_angle = 90 * 16
        span_angle = -int(round(progress_frac * 360.0 * 16.0))
        p.drawArc(disc_rect, start_angle, span_angle)

    # Center Play / Pause Icon
    p.save()
    p.translate(pcx, pcy)
    p.scale(15.0 / 20.0, 15.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawPath(_PATH_MEDIA_PAUSE if playing else _PATH_MEDIA_PLAY)
    p.restore()
    p.restore()

    # 3. Next button (ikincil kontrol: rölantide sakin, üzerine gelince yumuşak çip)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    next_hover = (hovered_control == "next")
    if next_hover:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r_next.adjusted(1.0, 2.0, -1.0, -2.0), 6.0, 6.0)

    p.translate(r_next.center().x(), r_next.center().y())
    p.scale(13.0 / 20.0, 13.0 / 20.0)
    p.translate(-10.0, -10.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235 if next_hover else 125))
    p.drawPath(_PATH_MEDIA_NEXT)
    p.restore()

    # 4. Canlı ilerleme çizgisi: metin sütununun altında ince, sakin gösterge (bx .. ctrl_x - 4)
    if progress_frac is not None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        lx1 = bx
        lx2 = max(bx + 20.0, ctrl_x - 4.0)
        ly = rect.bottom() - 4.0
        p.setPen(QPen(QColor(255, 255, 255, 16), 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(lx1, ly), QPointF(lx2, ly))
        if progress_frac > 0.0:
            fill_col = QColor(art_accent) if art_accent is not None else QColor(COLOR_ACCENT_BLUE)
            fill_col.setAlpha(180)
            p.setPen(QPen(fill_col, 1.5, Qt.SolidLine, Qt.RoundCap))
            fill_x2 = lx1 + (lx2 - lx1) * progress_frac
            p.drawLine(QPointF(lx1, ly), QPointF(fill_x2, ly))
        p.restore()

    return {"prev": r_prev, "playpause": r_play, "next": r_next}


MEDIA_ICON_W: float = 52.0


def draw_media_icon_button(
    p: QPainter,
    rect: QRectF,
    media_info: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
    active: bool = False,
) -> Dict[str, QRectF]:
    """Renders a compact 52x52 icon-only media button (40x40 cover/equalizer tile + bottom progress line).
    Clicking opens the MediaPanel mini-popover.
    """
    draw_card_base(p, rect, CARD_RADIUS, hover=(hover or active), press_scale=press_scale)

    art_img, art_accent = _decode_media_art(media_info.get("art_bytes"))
    if art_accent is None and media_info.get("ambient_hex"):
        art_accent = QColor(str(media_info["ambient_hex"]))

    tile_rect = QRectF(rect.center().x() - 20.0, rect.y() + 6.0, 40.0, 40.0)
    playing = bool(media_info.get("playing", True))
    draw_equalizer_tile(p, tile_rect, playing=playing, art_img=art_img, accent_color=art_accent)

    progress_frac = media_progress_fraction(media_info)
    if progress_frac is not None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        lx1 = tile_rect.left() + 4.0
        lx2 = tile_rect.right() - 4.0
        ly = rect.bottom() - 3.5
        p.setPen(QPen(QColor(255, 255, 255, 16), 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(lx1, ly), QPointF(lx2, ly))
        if progress_frac > 0.0:
            fill_col = QColor(art_accent) if art_accent is not None else QColor(COLOR_ACCENT_BLUE)
            fill_col.setAlpha(180)
            p.setPen(QPen(fill_col, 1.5, Qt.SolidLine, Qt.RoundCap))
            fill_x2 = lx1 + (lx2 - lx1) * progress_frac
            p.drawLine(QPointF(lx1, ly), QPointF(fill_x2, ly))
        p.restore()

    return {}


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
    f_val = theme.make_font(13.0, QFont.Weight.DemiBold, tabular=True)
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

    f_val = theme.make_font(13.0, QFont.Weight.DemiBold, tabular=True)
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
    active_account: Optional[str] = None,
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
    req_acc = str(active_account if active_account is not None else ag_data.get("active_account") or "emre").lower()
    want_busra = ("bus" in req_acc or "büş" in req_acc)

    def _matches_acc(lbl_str: str) -> bool:
        low = lbl_str.lower()
        if want_busra:
            return "bus" in low or "büş" in low
        return "emre" in low

    multi_accounts = any(" · " in str(g.get("label", "")) for g in groups)

    # Claude: prefer requested account's group if present, otherwise any group with 'claude'
    claude_grp = next((g for g in groups if _matches_acc(str(g.get("label", ""))) and "claude" in str(g.get("label", "")).lower()), None)
    if not claude_grp:
        claude_grp = next((g for g in groups if "claude" in str(g.get("label", "")).lower()), None)
    used_claude: Optional[float] = float(claude_grp["used"]) if (claude_grp and "used" in claude_grp) else None
    claude_reset_raw = (claude_grp.get("reset_at") or claude_grp.get("reset_tr")) if claude_grp else ""

    # Gemini: prefer requested account's group if present, otherwise max among groups with 'gemini'
    acc_gemini_grps = [g for g in groups if _matches_acc(str(g.get("label", ""))) and "gemini" in str(g.get("label", "")).lower()]
    gemini_grps = acc_gemini_grps if acc_gemini_grps else [g for g in groups if "gemini" in str(g.get("label", "")).lower()]
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
        outer_color=COLOR_RING_OUTER,
        inner_pct=used_gemini if not has_err else None,
        inner_color=COLOR_GEMINI_BLUE,
        logo_pixmap=ag_pm,
    )

    if not has_err and (multi_accounts or active_account is not None):
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        badge_r = QRectF(slot_rect.right() - 13.0, slot_rect.top() - 1.0, 14.0, 14.0)
        p.setPen(QPen(QColor(13, 15, 19), 1.5))
        p.setBrush(COLOR_CLAUDE_CORAL if want_busra else COLOR_GEMINI_BLUE)
        p.drawEllipse(badge_r)
        p.setPen(QColor(13, 15, 19))
        p.setFont(theme.make_font(9.0, QFont.Weight.Bold))
        p.drawText(badge_r, Qt.AlignCenter, "B" if want_busra else "E")
        p.restore()

    # Right side text area: gap 9px -> x = 10 + 40 + 9 = rect.x() + 59.0
    bx = rect.x() + 59.0
    bw = max(20.0, rect.right() - 10.0 - bx)

    p.save()
    if has_err:
        p.setOpacity(0.65)
        f_err = theme.make_font(11.0, QFont.Weight.Normal)
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
    row1 = (used_claude, COLOR_RING_OUTER, "Claude", claude_rst_str)
    row2 = (used_gemini, COLOR_GEMINI_BLUE, "Gemini", gemini_rst_str)
    draw_concentric_text_rows(p, text_rect, row1, row2)

    p.restore()


# ==============================================================================
# 2b. OPENCODE CARD (LOCAL TOKEN/COST USAGE)
# ==============================================================================

def format_token_count(n: Any) -> str:
    """Token sayısını kısa, okunur biçime çevirir: 999 / 12.3K / 1.5M."""
    try:
        val = int(n)
    except (TypeError, ValueError):
        return "—"
    if val < 0:
        return "—"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M".replace(".", ",")
    if val >= 1_000:
        return f"{val / 1_000:.1f}K".replace(".", ",")
    return str(val)


def draw_opencode_glyph(p: QPainter, rect: QRectF) -> None:
    """OpenCode terminal glifi (>_) halka göbeğinde zarif ve net vektörel form."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    center = rect.center()
    cx, cy = center.x(), center.y()
    pen = QPen(COLOR_TXT_PRIMARY, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(cx - 5.5, cy - 4.5)
    path.lineTo(cx - 1.0, cy)
    path.lineTo(cx - 5.5, cy + 4.5)
    p.drawPath(path)
    p.drawLine(QPointF(cx + 2.0, cy + 4.5), QPointF(cx + 6.5, cy + 4.5))
    p.restore()


def draw_opencode_card(
    p: QPainter,
    rect: QRectF,
    oc_data: Dict[str, Any],
    hover: bool = False,
    press_scale: float = 1.0,
) -> None:
    """Renders OpenCode quota card according to D4 concentric card spec (same as Claude/AG)."""
    draw_card_base(p, rect, CARD_RADIUS, hover=hover, press_scale=press_scale)

    # 40x40 Slot at left: padding 10px -> x = rect.x() + 10.0, y = rect.y() + 6.0
    slot_rect = QRectF(rect.x() + 10.0, rect.y() + 6.0, 40.0, 40.0)

    available = bool(oc_data.get("available"))
    has_err = bool(oc_data.get("err")) or not available

    if "recent_tokens" in oc_data:
        tokens_io = _as_nonneg(oc_data.get("recent_input")) + _as_nonneg(oc_data.get("recent_output"))
        cost_val = _as_cost(oc_data.get("recent_cost"))
        sessions = _as_nonneg(oc_data.get("recent_sessions")) or _as_nonneg(oc_data.get("total_sessions"))
        by_model = oc_data.get("recent_by_model") or {}
    else:
        tokens_io = _as_nonneg(oc_data.get("today_input")) + _as_nonneg(oc_data.get("today_output"))
        cost_val = _as_cost(oc_data.get("today_cost"))
        sessions = _as_nonneg(oc_data.get("today_sessions")) or _as_nonneg(oc_data.get("total_sessions"))
        by_model = oc_data.get("today_by_model") or {}

    primary_model = "OpenCode"
    if by_model and isinstance(by_model, dict):
        top_k = sorted(by_model.items(), key=lambda kv: kv[1], reverse=True)
        if top_k:
            raw_m = str(top_k[0][0]).lower()
            if "deepseek" in raw_m:
                primary_model = "DeepSeek"
            elif "claude" in raw_m:
                primary_model = "Claude"
            elif "gpt" in raw_m:
                primary_model = "GPT"
            elif "gemini" in raw_m:
                primary_model = "Gemini"

    pct = min(100.0, max(0.0, (tokens_io / 1_000_000.0) * 100.0)) if not has_err else None
    sess_pct = min(100.0, (sessions / 10.0) * 100.0) if (not has_err and sessions > 0) else None

    # Sol Slot: Konsantrik çift halka (Dış: Token kotası, İç: Oturum, Merkez: >_)
    draw_concentric_rings_slot(
        p,
        slot_rect,
        outer_pct=pct if not has_err else None,
        outer_color=COLOR_RING_OUTER,
        inner_pct=sess_pct if not has_err else None,
        inner_color=COLOR_RING_INNER,
        logo_pixmap=None,
        fallback_icon_fn=draw_opencode_glyph,
    )

    # Sağ taraf metin alanı: halka ile metin arası 7px, sağ boşluk 8px (dar kartta tam model adı sığsın)
    bx = rect.x() + 57.0
    bw = max(20.0, rect.right() - 8.0 - bx)

    p.save()
    if has_err:
        p.setOpacity(0.65)
        f_err = theme.make_font(11.0, QFont.Weight.Normal)
        p.setFont(f_err)
        p.setPen(COLOR_TXT_MUTED)
        msg = "OpenCode veri yok" if not available else "OpenCode okunamadı"
        p.drawText(QRectF(bx, rect.y(), bw, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, msg)
        p.restore()
        return

    # Claude ve Antigravity ile birebir aynı çift satır hizalama ve fontlar
    f_pct1 = theme.make_font(12.0, QFont.Weight.Bold, tabular=True, letter_spacing=-0.2)
    f_lbl1 = theme.make_font(FONT_SZ_LBL, QFont.Weight.Medium)
    f_lbl2 = theme.make_font(FONT_SZ_LBL, QFont.Weight.Normal)
    f_meta = theme.make_font(FONT_SZ_META, QFont.Weight.Normal)

    rx = bx
    rw = bw
    row_step = 19.0
    cap = _get_fm(f_pct1).capHeight()
    base1 = (rect.y() + 8.0 + 18.0) - (row_step - cap) / 2.0
    base2 = base1 + row_step

    fm_lbl1 = QFontMetricsF(f_lbl1)
    fm_lbl2 = QFontMetricsF(f_lbl2)
    fm_meta = QFontMetricsF(f_meta)

    # 1. Satır: %34 DeepSeek [sağda: 339K]
    pct_num = int(round(pct)) if pct is not None else 0
    pct_str = f"%{pct_num}" if pct is not None else "—"
    pct_col = usage_color(pct_num, COLOR_RING_OUTER) if pct is not None else COLOR_TXT_MUTED

    # Claude/AG kartlarıyla aynı sabit yüzde sütunu (col_w = '%100' genişliği) kuralı KORUNMALI
    col_w = QFontMetricsF(f_pct1).horizontalAdvance("%100")
    col_total = col_w + 6.0
    p.setFont(f_pct1)
    fm_pct = p.fontMetrics()
    wp1 = fm_pct.horizontalAdvance(pct_str)
    wl1_tmp = fm_lbl1.horizontalAdvance(primary_model) if primary_model else 0.0
    fits_col1 = (not wl1_tmp) or wl1_tmp <= (rw - col_total)
    fits_flush1 = (not wl1_tmp) or wl1_tmp <= (rw - wp1 - 6.0)
    use_flush1 = (not fits_col1) and fits_flush1
    if use_flush1:
        label_x = rx + wp1 + 6.0
        p.setPen(pct_col)
        p.drawText(QPointF(rx, base1), pct_str)
        space1 = rw - wp1 - 6.0
    else:
        label_x = rx + col_total
        p.setPen(pct_col)
        p.drawText(QPointF(rx + col_w - wp1, base1), pct_str)
        space1 = rw - col_total

    rst1 = format_token_count(tokens_io) if tokens_io > 0 else ""
    wr1 = fm_meta.horizontalAdvance(rst1) if rst1 else 0.0
    show_rst1 = bool(rst1) and (space1 - wl1_tmp) >= (wr1 + 6.0)
    label_w1 = wl1_tmp if (show_rst1 or (wl1_tmp and wl1_tmp <= space1)) else max(0.0, space1)

    if primary_model and label_w1 >= 14.0:
        elided_m = _elided_text(fm_lbl1, primary_model, label_w1)
        if elided_m:
            p.setFont(f_lbl1)
            p.setPen(COLOR_TXT_LABEL)
            p.drawText(QPointF(label_x, base1), elided_m)

    if show_rst1:
        p.setFont(f_meta)
        p.setPen(COLOR_TXT_FAINT)
        p.drawText(QPointF(rx + rw - wr1, base1), rst1)

    # 2. Satır: 3 Oturum [sağda: Ücretsiz ($0)] — etiket sütununa hizalı
    sess_text = f"{sessions} Oturum"
    cost_info = "Ücretsiz" if cost_val == 0.0 else f"${cost_val:.2f}"
    space2 = max(0.0, rw - (label_x - rx))
    wl2 = fm_lbl2.horizontalAdvance(sess_text) if sess_text else 0.0
    wr2 = fm_meta.horizontalAdvance(cost_info) if cost_info else 0.0
    show_rst2 = bool(cost_info) and (space2 - wl2) >= (wr2 + 6.0)
    label_w2 = wl2 if (show_rst2 or wl2 <= space2) else space2

    if sess_text and label_w2 >= 14.0:
        elided_sess = _elided_text(fm_lbl2, sess_text, label_w2)
        if elided_sess:
            p.setFont(f_lbl2)
            p.setPen(COLOR_TXT_MUTED)
            p.drawText(QPointF(label_x, base2), elided_sess)

    if show_rst2:
        p.setFont(f_meta)
        p.setPen(COLOR_TXT_FAINT)
        p.drawText(QPointF(rx + rw - wr2, base2), cost_info)

    p.restore()


def _as_nonneg(val: Any) -> int:
    try:
        v = int(val)
    except (TypeError, ValueError):
        return 0
    return v if v > 0 else 0


def _as_cost(val: Any) -> float:
    try:
        f = float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f if f > 0.0 else 0.0


# ==============================================================================
# 3. SYSTEM CARD (RING GAUGES)
# ==============================================================================

def get_sys_ring_color(val: float, base_col: QColor, is_ram: Optional[bool] = None) -> QColor:
    """Select base, amber, or red for sys ring gauge.

    İşlemci: >=75 turuncu, >=90 kırmızı (v33 ortak kural). Bellek: Emre'nin bilgisayarında normalde %74-77
    olduğu için (27 Eki 2026 ölçümü) >=85 turuncu, >=93 kırmızı; yoksa mor halka hiç görünmezdi.
    """
    if is_ram is None:  # v24'ten beri iki renk aynı: nesne kimliğine bak (eski çağrılar için)
        is_ram = base_col is COLOR_RAM_BAR
    red_at, amber_at = (93.0, 85.0) if is_ram else (RING_CRIT_AT, RING_WARN_AT)
    return usage_color(val, base_col, warn_at=amber_at, crit_at=red_at)


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
    # Estetik: halka (34) + 2 px boşluk + etiket (10) grubu 52 px karta eşit payla sığsın.
    # Toplam 46 -> üst/alt 3 px nefes payı; cy = üst + 17 = 20.
    cy = rect.y() + 20.0

    pad_x = 10.0
    cx_cpu = rect.x() + pad_x + size / 2.0
    cx_ram = rect.x() + rect.width() - pad_x - size / 2.0

    f_num = theme.make_font(11.0, QFont.Weight.DemiBold, tabular=True)
    f_num_sm = theme.make_font(10.0, QFont.Weight.DemiBold, tabular=True)
    f_lbl = theme.make_font(9.0, QFont.Weight.DemiBold, letter_spacing=0.5)

    rings = [
        (cx_cpu, c_val, COLOR_CPU_BAR, False, "CPU"),
        (cx_ram, r_val, COLOR_RAM_BAR, True, "RAM"),
    ]

    pen_track = QPen(COLOR_RING_TRACK, stroke, Qt.SolidLine, Qt.RoundCap)

    for cx, val, base_col, is_ram, lbl in rings:
        arc_rect = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)

        # 1. Background full track circle (sol kartlarla aynı iz dili)
        p.setPen(pen_track)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(arc_rect)

        fg_col = get_sys_ring_color(val, base_col, is_ram=is_ram) if (val is not None and val > 0.0) else base_col

        # 2. Foreground active arc (clockwise from 12 o'clock)
        if val is not None and val > 0.0:
            pen_fg = QPen(fg_col, stroke, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen_fg)
            span_angle = -int(round((val / 100.0) * 360.0 * 16.0))
            p.drawArc(arc_rect, 90 * 16, span_angle)

        # 3. Percentage number centred inside (no % sign, '–' for missing/err)
        num_str = f"{int(round(val))}" if val is not None else "–"
        p.setFont(f_num_sm if len(num_str) >= 3 else f_num)
        p.setPen(fg_col if (val is not None and val > 0.0) else COLOR_TXT_PRIMARY)
        text_y_off = -1.2 if val is None else -0.5
        text_rect = QRectF(cx - r, cy - r + text_y_off, 2.0 * r, 2.0 * r)
        p.drawText(text_rect, Qt.AlignCenter, num_str)

        # 4. Alt etiket: CPU / RAM (halkaya ortalı, halka altı ve kart tabanı arasında dengeli)
        p.setFont(f_lbl)
        p.setPen(COLOR_TXT_MUTED)
        y_lbl = cy + size / 2.0
        lbl_rect = QRectF(cx - size / 2.0 - 4.0, y_lbl, size + 8.0, rect.bottom() - y_lbl)
        p.drawText(lbl_rect, Qt.AlignCenter, lbl)

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
    f_lbl = theme.make_font(13.0, QFont.Weight.DemiBold, tabular=True)
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
    f_lbl = theme.make_font(13.0, QFont.Weight.DemiBold)
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
    f_lbl = theme.make_font(13.0, QFont.Weight.DemiBold)
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


CLOCK_DATE_FONT_SIZE: float = 10.5


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

    f_time = theme.make_font(13.5, QFont.Weight.DemiBold, tabular=True, letter_spacing=-0.2)
    f_date = theme.make_font(CLOCK_DATE_FONT_SIZE, QFont.Weight.Normal)

    fm_time = _get_fm(f_time)
    fm_date = _get_fm(f_date)
    w_time = _text_width(fm_time, time_str)
    w_date = _text_width(fm_date, date_str)
    w_clock_text = max(w_time, w_date)

    w = 10.0 + w_clock_text  # 10px left padding + clock/date text
    if has_weather and temp_str:
        f_temp = theme.make_font(12.0, QFont.Weight.DemiBold)
        fm_temp = _get_fm(f_temp)
        w_temp = _text_width(fm_temp, temp_str)
        # 14px icon + 5px gap + temp_w + 10px gap + 1px separator + 10px gap
        w += 14.0 + 5.0 + w_temp + 10.0 + 1.0 + 10.0
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

    Left (if weather available): 14px weather icon + 5px + temp '16°' 12px/600 on harmonized baseline,
      1px separator rgba(255,255,255,52) 24px high.
    Right: time 'HH:MM' 13.5px/600 tabular, 2.5px gap,
      date 'Sal, 27 Ekim' 10.5px Regular; both aligned to exact same left x.

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

    f_time = theme.make_font(13.5, QFont.Weight.DemiBold, tabular=True, letter_spacing=-0.2)
    f_date = theme.make_font(CLOCK_DATE_FONT_SIZE, QFont.Weight.Normal)

    fm_time = _get_fm(f_time)
    fm_date = _get_fm(f_date)

    cur_x = rect.x() + 10.0
    r_wx: Optional[QRectF] = None
    cy = rect.center().y()

    # Hava durumu SOLDA, saat sağda (27 Eki 2026, Emre: "saat en sağda olsun")
    if has_weather and temp_str:
        wx_left = rect.x()
        f_temp = theme.make_font(12.0, QFont.Weight.DemiBold)
        fm_temp = _get_fm(f_temp)
        w_temp = _text_width(fm_temp, temp_str)
        temp_base = cy + fm_temp.capHeight() / 2.0

        # İkon ile sıcaklık yazısı optik baseline uyumu:
        # Bulut gövdesi tüm hava durumlarında aynı yatay hatta sabitlenir;
        # yağış/yıldırım/sis sarkmaları tipografik uzantı gibi doğal taşar,
        # güneş ise rakamların optik merkeziyle dengelenir.
        target_cloud_base = temp_base - 1.5
        if wx_icon == "cloud":
            cy_box = target_cloud_base - 3.82
        elif wx_icon == "partly":
            cy_box = target_cloud_base - 4.20
        elif wx_icon in ("rain", "drizzle", "snow", "storm"):
            cy_box = target_cloud_base - 1.20
        elif wx_icon == "fog":
            cy_box = target_cloud_base - 0.58
        elif wx_icon == "sun":
            cy_box = cy - 0.5
        else:
            cy_box = cy

        icon_y = cy_box - 7.0
        r_icon = QRectF(cur_x, icon_y, 14.0, 14.0)
        p.save()
        p.setOpacity(0.85)
        theme.draw_weather_icon(p, r_icon, icon=wx_icon or "cloud")
        p.restore()
        cur_x += 14.0 + 5.0
        p.setFont(f_temp)
        p.setPen(COLOR_TXT_PRIMARY)
        p.drawText(QPointF(cur_x, temp_base), temp_str)
        cur_x += w_temp + 10.0
        sep_x = cur_x
        draw_card_divider(p, sep_x, cy, 24.0)
        cur_x += 1.0 + 10.0
        # Hava durumu tıklama alanı: sol kenardan ayırıcıya kadar
        r_wx = QRectF(wx_left, rect.y(), max(0.0, sep_x + 1.0 - wx_left), rect.height())

    # Saat üst satır Semibold/13.5px, Tarih alt satır Regular 10.5px
    # aralarını 2.5px nefesli hizala; iki footer satırının sol kenarları BİREBİR AYNI x'te olacak.
    gap_td = 2.5
    cap_t = fm_time.capHeight()
    cap_d = fm_date.capHeight()
    total_h = cap_t + gap_td + cap_d
    time_base = cy - total_h / 2.0 + cap_t
    date_base = time_base + gap_td + cap_d
    text_x = cur_x

    # Dar alanda taşmayı önle: önce ikincil bilgi (tarih) elide edilir
    avail_w = max(0.0, rect.right() - 10.0 - text_x)
    w_time = _text_width(fm_time, time_str)
    w_date = _text_width(fm_date, date_str)

    p.setFont(f_time)
    p.setPen(Qt.white)
    time_to_draw = _elided_text(fm_time, time_str, avail_w) if (w_time > avail_w and avail_w > 0.0) else time_str
    p.drawText(QPointF(text_x, time_base), time_to_draw)

    p.setFont(f_date)
    p.setPen(COLOR_TXT_MUTED)
    if avail_w >= 18.0:
        date_to_draw = _elided_text(fm_date, date_str, avail_w) if w_date > avail_w else date_str
        p.drawText(QPointF(text_x, date_base), date_to_draw)

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
    f = theme.make_font(13.0, QFont.Weight.DemiBold, tabular=True)
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


PLUG_GLYPH_W: float = 20.0  # v24 fiş simgesi (kablo 6 + gövde 9 + uçlar 5), yükseklik 12


def _paint_plug(p: QPainter, x: float, cy: float, col: QColor, dpr: float) -> float:
    """Yatay fiş, pil simgesiyle aynı ağırlıkta: kablo, 9x12 gövde (r2.6), iki uç 5.5x2. Genişliği döndürür."""
    def snap(v: float) -> float:
        return round(v * dpr) / dpr

    body = QRectF(snap(x + 6.0), snap(cy - 6.0), snap(9.0), snap(12.0))
    path = QPainterPath()
    path.addRoundedRect(body, 2.6, 2.6)
    for py in (cy - 4.0, cy + 2.0):
        path.addRoundedRect(QRectF(body.right() - 0.5, snap(py), 5.5, 2.0), 0.9, 0.9)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(col, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(x + 1.0, snap(cy)), QPointF(body.left() + 0.5, snap(cy)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    p.drawPath(path)
    p.restore()
    return PLUG_GLYPH_W


def draw_battery_pill(
    p: QPainter,
    rect: QRectF,
    percent: Optional[float],
    charging: bool,
    hovered: bool = False,
    active: bool = False,
    on_ac_full: bool = False,
) -> QRectF:
    """Sol kanat pil halkası: CPU/RAM ile aynı 34 px halka, merkezde şimşek veya yüzde.

    Renk: şarjda/prizde yeşil, <=%20 ve şarjda değilse kırmızı, aksi halde beyaz.
    Şarjda / prizde merkezde keskin yeşil şimşek; pildeyken tabular yüzde.
    Üzerine gelince / panel açıkken yumuşak kart zemini.
    Tüm kart tek isabet alanıdır; dikdörtgen döndürülür.
    """
    is_ac = charging or on_ac_full
    col = battery_color(percent, is_ac)
    lvl = 100.0 if percent is None else max(0.0, min(100.0, float(percent)))
    cx = rect.center().x()
    # 52 px kart yüksekliğinde 34 px halka; 32 px gibi dar bir rect geçilirse sığacak çap kullanılır
    avail_h = rect.height()
    dia = min(SYS_RING_SIZE, avail_h - 2.0)
    stroke = min(RING_STROKE, dia / 8.0)
    cy = rect.center().y()
    r = (dia - stroke) / 2.0
    r_ring = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    if hovered:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        c_path = theme.rounded_path(rect, CARD_RADIUS)
        hover_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        hover_grad.setColorAt(0.0, QColor(255, 255, 255, 26))
        hover_grad.setColorAt(1.0, QColor(255, 255, 255, 13))
        p.fillPath(c_path, hover_grad)
        p.setPen(QPen(QColor(255, 255, 255, 34), 0.8))
        p.drawPath(c_path)
        p.restore()
    elif active:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawPath(_rounded_path(rect, CARD_RADIUS))

    # Arka iz + aktif yay (12 yönünden saat yönünde, sol kartlarla aynı iz dili)
    p.setPen(QPen(COLOR_RING_TRACK, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r_ring)
    if lvl > 0.0:
        p.setPen(QPen(col, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r_ring, 90 * 16, -int(round((lvl / 100.0) * 360 * 16)))

    if is_ac:
        bolt_w = max(6.0, dia * (10.0 / 34.0))
        bolt_h = max(9.0, dia * (16.0 / 34.0))
        bolt = _get_bolt_path(cx, cy, bolt_w, bolt_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(panel_style.OK))
        p.drawPath(bolt)
    else:
        txt = f"{int(round(lvl))}" if percent is not None else "—"
        f_sz = (10.0 if dia >= 30.0 else 9.0) if len(txt) >= 3 else (11.0 if dia >= 30.0 else 9.0)
        f = theme.make_font(f_sz, QFont.Weight.DemiBold, tabular=True)
        p.setFont(f)
        txt_col = col if (percent is not None and percent <= 20) else COLOR_TXT_PRIMARY
        p.setPen(txt_col)
        text_y_off = -1.2 if percent is None else -0.5
        text_rect = QRectF(cx - r, cy - r + text_y_off, 2.0 * r, 2.0 * r)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, txt)
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

    # 1. Taban kapsül
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

    # 2. Hover / aktif bölme vurgusu (kapsül kavisini pürüzsüz takip eder, iç kutu eklemez)
    pill_clip = QPainterPath()
    pill_clip.addRoundedRect(rect, 10.0, 10.0)
    p.save()
    p.setClipPath(pill_clip)
    parts = [("bright", r_sun), ("vol", r_spk)]
    if show_bat:
        parts.append(("bat", r_bat))
    for key, r in parts:
        if active_part == key:
            p.fillRect(r, QColor(255, 255, 255, int(255 * 0.16)))
        elif hovered_part == key:
            p.fillRect(r, QColor(255, 255, 255, int(255 * 0.10)))
    p.restore()

    # 3. Ayırıcılar (boşta sakin, aktif/hover bölme kenarında otomatik gizlenir)
    div_y = rect.center().y() - 7.0
    p.setPen(QPen(CARD_DIVIDER, 1.0))
    if not (hovered_part in ("bright", "vol") or active_part in ("bright", "vol")):
        p.drawLine(QPointF(mid_x, div_y), QPointF(mid_x, div_y + 14.0))
    if r_bat is not None and not (hovered_part in ("vol", "bat") or active_part in ("vol", "bat")):
        p.drawLine(QPointF(r_bat.x(), div_y), QPointF(r_bat.x(), div_y + 14.0))

    # 4. Sun glifi (18px kutu, optik dengeli dolu çekirdek ve 1.7px eşit çizgi)
    sun_col = QColor(255, 255, 255) if (hovered_part == "bright" or active_part == "bright") else QColor(255, 255, 255, int(255 * 0.85))
    p.save()
    p.translate(r_sun.center().x(), r_sun.center().y())
    p.scale(18.0 / 20.0, 18.0 / 20.0)
    p.translate(-10.0, -10.0)
    pen_sun = QPen(sun_col, 1.75, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen_sun)
    p.setBrush(sun_col)
    p.drawEllipse(QRectF(10.0 - 3.3, 10.0 - 3.3, 6.6, 6.6))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(10.0, 2.2), QPointF(10.0, 5.0))
    p.drawLine(QPointF(10.0, 15.0), QPointF(10.0, 17.8))
    p.drawLine(QPointF(2.2, 10.0), QPointF(5.0, 10.0))
    p.drawLine(QPointF(15.0, 10.0), QPointF(17.8, 10.0))
    p.drawLine(QPointF(4.48, 4.48), QPointF(6.46, 6.46))
    p.drawLine(QPointF(15.52, 15.52), QPointF(13.54, 13.54))
    p.drawLine(QPointF(4.48, 15.52), QPointF(6.46, 13.54))
    p.drawLine(QPointF(15.52, 4.48), QPointF(13.54, 6.46))
    p.restore()

    # 5. Speaker glifi (güneşle eşit optik ağırlık: %86 ölçek, 1.7px eşit çizgi)
    spk_col = QColor(255, 255, 255) if (hovered_part == "vol" or active_part == "vol") else QColor(255, 255, 255, int(255 * 0.85))
    p.save()
    p.translate(r_spk.center().x(), r_spk.center().y())
    p.scale(17.2 / 20.0, 17.2 / 20.0)
    p.translate(-10.2, -10.0)
    pen_spk = QPen(spk_col, 1.75, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen_spk)
    p.setBrush(spk_col)

    spk_body = QPainterPath()
    spk_body.moveTo(4.4, 7.4)
    spk_body.lineTo(7.0, 7.4)
    spk_body.lineTo(11.0, 3.8)
    spk_body.lineTo(11.0, 16.2)
    spk_body.lineTo(7.0, 12.6)
    spk_body.lineTo(4.4, 12.6)
    spk_body.closeSubpath()
    p.drawPath(spk_body)

    if vol_muted:
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(3.2, 3.2), QPointF(16.8, 16.8))
    else:
        p.setBrush(Qt.NoBrush)
        lvl = max(0.0, min(100.0, float(vol_level)))
        if lvl > 0.0:
            w1 = QPainterPath()
            w1.moveTo(14.2, 6.5)
            w1.cubicTo(15.8, 8.3, 15.8, 11.3, 14.2, 13.1)
            p.drawPath(w1)
        if lvl >= 50.0:
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

    # Estetik: gizli simgeler oku (tray) boştayken komşu sağ küme simgeleriyle aynı sönüklükte
    # (güncellemeler simgesi .65) ve aynı inceliktedir; üzerine gelince tam beyaz.
    rest_a = 0.65 if kind == "tray" else 0.78
    glyph_col = QColor(255, 255, 255) if (hover or active) else QColor(255, 255, 255, int(255 * rest_a))
    pen = QPen(glyph_col, 1.75, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()

    if kind == "tray":
        # Chevron-up (18px glyph box, optik dikey merkezleme: üst tepe cy - 3.25, taban cy + 2.25)
        path_chv = QPainterPath()
        path_chv.moveTo(cx - 5.5, cy + 2.25)
        path_chv.lineTo(cx, cy - 3.25)
        path_chv.lineTo(cx + 5.5, cy + 2.25)
        p.drawPath(path_chv)

    elif kind == "bright":
        # Sun: center circle r=3.6, 8 radial rays (18px glyph box)
        p.drawEllipse(QRectF(cx - 3.6, cy - 3.6, 7.2, 7.2))
        for i in range(8):
            ang = i * math.pi / 4.0
            r1 = 5.5
            r2 = 9.0
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

    spk_col = QColor(255, 255, 255) if hovered_btn == "spk" else QColor(255, 255, 255, int(255 * 0.85))
    pen = QPen(spk_col, 1.75, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
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

    chv_col = QColor(255, 255, 255) if hovered_btn == "chv" else QColor(255, 255, 255, int(255 * 0.85))
    pen = QPen(chv_col, 1.75, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    chv_path = QPainterPath()
    chv_path.moveTo(6, 14.5)
    chv_path.lineTo(12, 8.5)
    chv_path.lineTo(18, 14.5)
    p.drawPath(chv_path)
    p.restore()

    p.restore()
    return (r_spk, r_chv)


# ==============================================================================
# 8. V29 SMART ACTION CHIP & DOCKFLOW FOCUS PROFILE
# ==============================================================================

ACTION_CHIP_MAX_W: float = 210.0
ACTION_CHIP_H: float = 28.0


def measure_action_chip_width(text: str) -> float:
    """Measure width of contextual smart action chip (clamped to ACTION_CHIP_MAX_W)."""
    if not text:
        return 0.0
    f = theme.make_font(11.0, QFont.Weight.DemiBold)
    fm = _get_fm(f)
    # Sol renkli nokta (16) + metin + sağ ok/boşluk (14)
    w = 30.0 + _text_width(fm, text)
    return max(76.0, min(ACTION_CHIP_MAX_W, w))


def draw_action_chip(
    p: QPainter,
    rect: QRectF,
    text: str,
    accent_hex: str = "#0A84FF",
    hover: bool = False,
) -> None:
    """Draw a contextual Smart Action Chip (e.g. 'rapor.xlsx indi · Aç ›', 'Mola vakti ›')."""
    if not text or rect.width() <= 0.0:
        return
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    cy = rect.center().y()
    chip_r = QRectF(rect.x(), cy - ACTION_CHIP_H / 2.0, rect.width(), ACTION_CHIP_H)
    accent = QColor(accent_hex)
    if not accent.isValid():
        accent = QColor("#0A84FF")

    bg_col = QColor(accent)
    bg_col.setAlpha(48 if hover else 30)
    border_col = QColor(accent)
    border_col.setAlpha(155 if hover else 105)

    p.setPen(QPen(border_col, 1.0))
    p.setBrush(bg_col)
    p.drawRoundedRect(chip_r.adjusted(0.5, 0.5, -0.5, -0.5), ACTION_CHIP_H / 2.0, ACTION_CHIP_H / 2.0)

    # Sol canlı durum noktası
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    p.drawEllipse(QPointF(chip_r.x() + 12.0, cy), 3.4, 3.4)

    # Metin
    f = theme.make_font(11.0, QFont.Weight.DemiBold)
    fm = _get_fm(f)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 245 if hover else 230))
    txt_r = QRectF(chip_r.x() + 21.0, chip_r.y(), max(10.0, chip_r.width() - 29.0), chip_r.height())
    p.drawText(txt_r, Qt.AlignVCenter | Qt.AlignLeft, _elided_text(fm, text, txt_r.width()))
    p.restore()

