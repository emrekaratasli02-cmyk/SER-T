"""Şerit açılır panelleri için ortak görsel dil v2 — Yön A "Lumabar Disiplini" (27 Eki 2026, Emre onayladı).

Tek kaynak: tüm paneller (Claude, Sistem, Mail, Antigravity, Takvim, Parlaklık, Ses, Pil/Hızlı Ayar)
renk, köşe, boşluk, yazı boyutları ve saf QPainter çizim yardımcılarını buradan alır.
Şartname: hermes/cache/scratch/serit-mockups/v18/A_ortak_dil.html ve B_pil_hizli_ayar.html.

Kurallar: panel tamamen opak (#141518), dış köşe 16, iç kart 12 (#1D1F24), düğme 8, rozet hap.
Eksik değerler (None) her zaman boş iz veya '—' olarak çizilir; uydurma sayı üretilmez.
"""
from __future__ import annotations

from typing import Callable
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

# --- Yüzeyler -------------------------------------------------------------------------------
PANEL_BG = QColor(0x14, 0x15, 0x18)            # #141518 opak, alfa yok
PANEL_BORDER = QColor(255, 255, 255, 23)       # rgba(255,255,255,.09)
TILE_BG = QColor(0x1D, 0x1F, 0x24)             # #1D1F24
CARD_BG = TILE_BG
TILE_BORDER = QColor(255, 255, 255, 15)        # rgba(255,255,255,.06)
CARD_BORDER = TILE_BORDER
TILE_HOVER = QColor(0x23, 0x26, 0x2C)
CARD_HOVER = TILE_HOVER
BUTTON_BG = QColor(255, 255, 255, 18)          # rgba(255,255,255,.07)
BUTTON_BORDER = QColor(255, 255, 255, 20)      # rgba(255,255,255,.08)
BUTTON_HOVER = QColor(255, 255, 255, 32)       # rgba(255,255,255,.125)
CHIP_BG = QColor(255, 255, 255, 18)            # rgba(255,255,255,.07)
CHIP_BORDER = QColor(255, 255, 255, 20)        # rgba(255,255,255,.08)
FOOTER_LINE = QColor(255, 255, 255, 13)        # rgba(255,255,255,.05)

# --- Metin ----------------------------------------------------------------------------------
TEXT = QColor(255, 255, 255)
TEXT_BODY = QColor(255, 255, 255, 217)         # .85
TEXT_SLIDER = QColor(255, 255, 255, 230)       # .90
TEXT_CHIP = QColor(255, 255, 255, 166)         # .65
TEXT_BTN = QColor(255, 255, 255, 191)          # .75
TEXT_MUTED = QColor(255, 255, 255, 128)        # .50
TEXT_CLOSE = QColor(255, 255, 255, 115)        # .45
TEXT_LABEL = QColor(255, 255, 255, 107)        # .42 (BÜYÜK HARF bölüm etiketi / alt kaynak)
TEXT_META = QColor(255, 255, 255, 102)         # .40

# --- Anlamlı renkler ------------------------------------------------------------------------
CLAUDE = QColor("#D97757")
CPU = QColor("#64D2FF")
RAM = QColor("#BF5AF2")
DISK = QColor("#30D158")
BRIGHT = QColor("#FFB020")
BRIGHT_FILL = QColor(255, 255, 255)
SOUND = QColor("#0A84FF")
ACCENT = QColor("#0A84FF")
WARN = QColor("#FF9F0A")
DANGER = QColor("#FF453A")
OK = QColor("#30D158")
TRACK = QColor(255, 255, 255, 26)              # rgba(255,255,255,.10)
RING_TRACK = QColor(255, 255, 255, 20)         # rgba(255,255,255,.08)
SLIDER_TRACK = QColor(255, 255, 255, 31)       # rgba(255,255,255,.12)

# --- Ölçüler --------------------------------------------------------------------------------
R_PANEL = 16.0
R_TILE = 12.0
R_CARD = 12.0
R_BUTTON = 8.0
R_ICON_BOX = 6.0
R_CLOSE = 6.0
R_TOGGLE = 10.0
PAD = 16.0            # panel iç boşluğu
TILE_PAD = 13.0       # kart iç boşluğu (eski ad)
CARD_PAD = 13.0       # kart iç boşluğu (v2 ad)
CARD_GAP = 10.0       # kart içi öğeler arası boşluk
GAP = 12.0            # kartlar / bölümler arası dikey boşluk
HEADER_H = 32.0       # v2 standart başlık yüksekliği (32 px)
FOOTER_H = 32.0       # v2 standart alt bilgi yüksekliği (32 px)
ICON_BOX_SZ = 22.0
CLOSE_SZ = 24.0
SLIDER_TRACK_H = 18.0
SLIDER_KNOB_SZ = 20.0
RING_SZ = 64.0
RING_STROKE = 5.0
THIN_BAR_H = 6.0
PRESET_PILL_H = 28.0
TOGGLE_H = 38.0
ANCHOR_GAP = 8.0      # panel ile şerit arası

WIDTH = {"mail": 380, "cal": 440, "claude": 360, "ag": 360, "sys": 360, "bright": 340, "vol": 340}

FONT_FAMILY = "Segoe UI Variable Text"

_TR_UPPER_MAP = str.maketrans({
    "i": "İ",
    "ı": "I",
    "ğ": "Ğ",
    "ü": "Ü",
    "ş": "Ş",
    "ö": "Ö",
    "ç": "Ç",
})


def turkish_upper(text: str) -> str:
    """Türkçe kurallarına uygun büyük harfe çevirme (i -> İ, ı -> I)."""
    if not text:
        return ""
    return str(text).translate(_TR_UPPER_MAP).upper()


def font(px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
    """Piksel boyutlu yazı tipi (Segoe UI Variable, yoksa Segoe UI)."""
    f = QFont(FONT_FAMILY)
    f.setFamilies([FONT_FAMILY, "Segoe UI"])
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)  # Qt 6.7+
        except Exception:
            pass
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# Hazır hiyerarşi
def f_hero(px: float = 34.0) -> QFont:
    return font(px, QFont.Weight.Bold, tabular=True)


def f_title() -> QFont:
    return font(15.0, QFont.Weight.DemiBold)


def f_label() -> QFont:
    f = font(10.5, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.84)
    return f


def f_body() -> QFont:
    return font(12.5, QFont.Weight.Medium)


def f_small() -> QFont:
    return font(11.0)


def rounded(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def draw_panel_shell(p: QPainter, r: QRectF) -> None:
    """Opak panel gövdesi + saç teli kenar. Gölgeyi pencere (DWM) verir; burada çizilmez."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PANEL_BG)
    p.drawPath(rounded(r, R_PANEL))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(PANEL_BORDER, 1.0))
    p.drawPath(rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), R_PANEL - 0.5))
    p.restore()


def draw_tile(p: QPainter, r: QRectF, hover: bool = False) -> None:
    """Yükseltilmiş iç kart."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(TILE_BORDER, 1.0))
    p.setBrush(TILE_HOVER if hover else TILE_BG)
    p.drawPath(rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), R_TILE))
    p.setBrush(Qt.BrushStyle.NoBrush)  # fırça sızıntısını önle
    p.restore()


def draw_ring(p: QPainter, center_x: float, center_y: float, diameter: float, stroke: float,
              value: float | None, color: QColor) -> None:
    """Halka gösterge; value None ise yalnız iz çizilir (uydurma değer yok)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = QRectF(center_x - diameter / 2.0 + stroke / 2.0, center_y - diameter / 2.0 + stroke / 2.0,
               diameter - stroke, diameter - stroke)
    pen = QPen(RING_TRACK, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r)
    if value is not None and value > 0:
        pen.setColor(color)
        p.setPen(pen)
        span = -int(round(max(0.0, min(100.0, float(value))) / 100.0 * 360 * 16))
        p.drawArc(r, 90 * 16, span)
    p.restore()


def pct(value: float | None) -> str:
    """Türkçe yüzde: %25; veri yoksa uzun çizgi."""
    if value is None:
        return "—"
    return f"%{int(round(float(value)))}"


# =============================================================================================
# v2 ORTAK PANEL KİTİ YARDIMCILARI (Sheet A & B)
# =============================================================================================

def _paint_icon(p: QPainter, rect: QRectF, icon: QPixmap | Callable | None) -> None:
    if icon is None:
        return
    if isinstance(icon, QPixmap):
        if not icon.isNull():
            p.drawPixmap(rect.toRect(), icon)
    elif callable(icon):
        p.save()
        try:
            icon(p, rect)
        finally:
            p.restore()


def draw_header(
    p: QPainter,
    rect: QRectF,
    title: str,
    icon: QPixmap | Callable[[QPainter, QRectF], None] | None = None,
    chip: str | None = None,
    chip_dot: QColor | None = None,
    close_hover: bool = False,
) -> dict[str, QRectF | None]:
    """Standart 32 px panel başlığı: sol 22x22 ikon kutusu + 15 px başlık, sağ hap rozet + 24x24 kapat."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    cy = rect.center().y()
    cur_x = rect.left()

    if icon is not None:
        icon_box = QRectF(cur_x, cy - ICON_BOX_SZ / 2.0, ICON_BOX_SZ, ICON_BOX_SZ)
        _paint_icon(p, icon_box, icon)
        cur_x = icon_box.right() + 10.0

    # Kapat düğmesi (sağda 24x24, radius 6)
    close_sz = min(CLOSE_SZ, rect.height())
    close_rect = QRectF(rect.right() - close_sz, cy - close_sz / 2.0, close_sz, close_sz)
    if close_hover:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BUTTON_HOVER)
        p.drawPath(rounded(close_rect, R_CLOSE))

    # Kapat '✕' çizimi
    cross_col = TEXT if close_hover else TEXT_CLOSE
    pen_x = QPen(cross_col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen_x)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx_close, cy_close = close_rect.center().x(), close_rect.center().y()
    d = 4.2
    p.drawLine(QPointF(cx_close - d, cy_close - d), QPointF(cx_close + d, cy_close + d))
    p.drawLine(QPointF(cx_close + d, cy_close - d), QPointF(cx_close - d, cy_close + d))

    right_limit = close_rect.left() - 8.0
    chip_rect: QRectF | None = None

    if chip:
        f_chip = font(11.0, QFont.Weight.Medium)
        fm_chip = QFontMetricsF(f_chip)
        tw = fm_chip.horizontalAdvance(chip)
        dot_space = 11.0 if chip_dot is not None else 0.0
        chip_w = min(tw + 16.0 + dot_space, max(24.0, right_limit - cur_x - 8.0))
        chip_h = min(22.0, rect.height())
        chip_rect = QRectF(right_limit - chip_w, cy - chip_h / 2.0, chip_w, chip_h)

        is_interactive = "›" in chip or "▾" in chip
        p.setPen(QPen(CHIP_BORDER, 1.0))
        p.setBrush(QColor(255, 255, 255, 23) if is_interactive else CHIP_BG)
        p.drawPath(rounded(chip_rect.adjusted(0.5, 0.5, -0.5, -0.5), chip_h / 2.0))

        text_left = chip_rect.left() + 8.0
        if chip_dot is not None:
            dot_r = 3.0
            dot_cx = text_left + dot_r
            dot_cy = chip_rect.center().y()
            glow = QColor(chip_dot)
            glow.setAlpha(90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(dot_cx, dot_cy), dot_r + 2.0, dot_r + 2.0)
            p.setBrush(chip_dot)
            p.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)
            text_left += 11.0

        p.setFont(f_chip)
        p.setPen(TEXT_BODY if is_interactive else TEXT_CHIP)
        t_rect = QRectF(text_left, chip_rect.top(), max(0.0, chip_rect.right() - 8.0 - text_left), chip_h)
        p.drawText(t_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, chip)
        right_limit = chip_rect.left() - 8.0

    # Başlık metni (15 px DemiBold)
    f_t = f_title()
    p.setFont(f_t)
    p.setPen(TEXT)
    title_w = max(0.0, right_limit - cur_x)
    title_rect = QRectF(cur_x, rect.top(), title_w, rect.height())
    fm_t = QFontMetricsF(f_t)
    elided_title = fm_t.elidedText(title, Qt.TextElideMode.ElideRight, max(10.0, title_w))
    p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_title)

    p.restore()
    return {"close": close_rect, "chip": chip_rect}


def draw_card(
    p: QPainter,
    rect: QRectF,
    overline: str | None = None,
    overline_right: str | None = None,
    hover: bool = False,
) -> QRectF:
    """İç kart (#1D1F24, 12px köşe, 13px iç boşluk) + isteğe bağlı Türkçe büyük harf üst başlık.
    İçeriğin çizileceği iç QRectF alanını döndürür.
    """
    draw_tile(p, rect, hover=hover)
    inner = rect.adjusted(CARD_PAD, CARD_PAD, -CARD_PAD, -CARD_PAD)
    if inner.width() <= 0 or inner.height() <= 0:
        return QRectF(rect.center().x(), rect.center().y(), 0.0, 0.0)

    if overline is None and overline_right is None:
        return inner

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    over_h = min(15.0, inner.height())
    over_rect = QRectF(inner.left(), inner.top(), inner.width(), over_h)

    if overline:
        f_ov = f_label()
        p.setFont(f_ov)
        p.setPen(TEXT_LABEL)
        p.drawText(
            over_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            turkish_upper(overline),
        )

    if overline_right:
        f_ovr = font(10.5, QFont.Weight.DemiBold)
        p.setFont(f_ovr)
        p.setPen(ACCENT if "›" in overline_right else TEXT_MUTED)
        p.drawText(
            over_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            overline_right,
        )

    p.restore()
    top_offset = min(inner.height(), over_h + CARD_GAP)
    return QRectF(inner.left(), inner.top() + top_offset, inner.width(), max(0.0, inner.height() - top_offset))


def draw_footer(
    p: QPainter,
    rect: QRectF,
    source_text: str,
    button_text: str | None = None,
    button_hover: bool = False,
) -> QRectF | None:
    """Standart 32 px alt bilgi: üstte 1 px çizgi, solda kaynak metni, sağda hayalet eylem düğmesi."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Üst 1 px ayırıcı çizgi
    line_y = rect.top() + 0.5
    p.setPen(QPen(FOOTER_LINE, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(rect.left(), line_y), QPointF(rect.right(), line_y))

    content_rect = QRectF(rect.left(), rect.top() + 3.0, rect.width(), max(0.0, rect.height() - 3.0))
    cy = content_rect.center().y()
    right_limit = content_rect.right()
    btn_rect: QRectF | None = None

    if button_text:
        f_btn = font(11.5, QFont.Weight.Medium)
        fm_btn = QFontMetricsF(f_btn)
        tw = fm_btn.horizontalAdvance(button_text)
        btn_w = min(tw + 20.0, max(28.0, content_rect.width() * 0.55))
        btn_h = min(24.0, content_rect.height())
        btn_rect = QRectF(content_rect.right() - btn_w, cy - btn_h / 2.0, btn_w, btn_h)

        p.setPen(QPen(BUTTON_BORDER, 1.0))
        p.setBrush(BUTTON_HOVER if button_hover else BUTTON_BG)
        p.drawPath(rounded(btn_rect.adjusted(0.5, 0.5, -0.5, -0.5), R_BUTTON))

        p.setFont(f_btn)
        p.setPen(TEXT if button_hover else TEXT_BTN)
        p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, button_text)
        right_limit = btn_rect.left() - 8.0

    # Sol kaynak metni (11.5 px, rgba .42)
    f_src = font(11.5, QFont.Weight.Normal)
    p.setFont(f_src)
    p.setPen(TEXT_LABEL)
    src_w = max(0.0, right_limit - content_rect.left())
    src_rect = QRectF(content_rect.left(), content_rect.top(), src_w, content_rect.height())
    fm_src = QFontMetricsF(f_src)
    elided_src = fm_src.elidedText(source_text or "—", Qt.TextElideMode.ElideRight, max(10.0, src_w))
    p.drawText(src_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_src)

    p.restore()
    return btn_rect


def slider_value_at(track_rect: QRectF, x: float) -> int:
    """Kaydırıcı izi üzerindeki x koordinatını [0, 100] tam sayısına eşler ve sınırlar."""
    w = track_rect.width()
    if w <= 0.0:
        return 0
    ratio = (float(x) - track_rect.left()) / w
    clamped = max(0.0, min(1.0, ratio))
    return int(round(clamped * 100.0))


def draw_slider(
    p: QPainter,
    rect: QRectF,
    label: str,
    value: float | None,
    fill: QColor = ACCENT,
    icon: QPixmap | Callable[[QPainter, QRectF], None] | None = None,
    hover: bool = False,
    muted: bool = False,
) -> dict[str, QRectF]:
    """Lumabar yatay kalın hap kaydırıcı: üstte etiket + Türkçe %, altta 18 px hap iz + 20 px beyaz tutaç.
    value None ise dolum ve tutaç çizilmez, sağda '—' yazar.
    """
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    track_h = min(SLIDER_TRACK_H, max(6.0, rect.height() * 0.48))
    knob_sz = min(SLIDER_KNOB_SZ, rect.height())
    track_y = rect.bottom() - track_h - max(0.0, (knob_sz - track_h) / 2.0)
    track_rect = QRectF(rect.left(), track_y, rect.width(), track_h)

    # Üst etiket satırı
    label_h = max(14.0, track_rect.top() - rect.top() - 4.0)
    label_rect = QRectF(rect.left(), rect.top(), rect.width(), label_h)

    cur_x = label_rect.left()
    if icon is not None:
        ic_sz = min(14.0, label_h)
        ic_rect = QRectF(cur_x, label_rect.center().y() - ic_sz / 2.0, ic_sz, ic_sz)
        _paint_icon(p, ic_rect, icon)
        cur_x = ic_rect.right() + 7.0

    # Sağ yüzde / durum metni
    f_val = font(13.0, QFont.Weight.DemiBold, tabular=True)
    p.setFont(f_val)
    if muted:
        val_str = "Sessiz"
        val_col = DANGER
    elif value is None:
        val_str = "—"
        val_col = TEXT_LABEL
    else:
        val_str = pct(value)
        val_col = fill if fill.rgb() != QColor(255, 255, 255).rgb() else TEXT

    fm_val = QFontMetricsF(f_val)
    val_w = fm_val.horizontalAdvance(val_str)
    p.setPen(val_col)
    p.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, val_str)

    # Sol isim metni
    f_name = font(13.0, QFont.Weight.Medium)
    p.setFont(f_name)
    p.setPen(TEXT_MUTED if (muted or value is None) else TEXT_SLIDER)
    name_w = max(0.0, label_rect.right() - val_w - 8.0 - cur_x)
    name_rect = QRectF(cur_x, label_rect.top(), name_w, label_h)
    fm_name = QFontMetricsF(f_name)
    p.drawText(
        name_rect,
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        fm_name.elidedText(label, Qt.TextElideMode.ElideRight, max(10.0, name_w)),
    )

    # Hap iz (track)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 38) if hover else SLIDER_TRACK)
    p.drawPath(rounded(track_rect, track_h / 2.0))

    knob_rect = QRectF(track_rect.left(), track_rect.center().y() - knob_sz / 2.0, 0.0, 0.0)

    if value is not None and not muted:
        clamped = max(0.0, min(100.0, float(value)))
        ratio = clamped / 100.0
        if clamped > 0.0:
            fill_w = max(track_h, track_rect.width() * ratio)
            fill_w = min(track_rect.width(), fill_w)
            fill_rect = QRectF(track_rect.left(), track_rect.top(), fill_w, track_h)
            p.setBrush(fill)
            p.drawPath(rounded(fill_rect, track_h / 2.0))

        # Yuvarlak beyaz tutaç (knob) — iz sınırları içinde kalacak şekilde konumlanır
        knob_cx = track_rect.left() + knob_sz / 2.0 + ratio * max(0.0, track_rect.width() - knob_sz)
        knob_cy = track_rect.center().y()
        knob_rect = QRectF(knob_cx - knob_sz / 2.0, knob_cy - knob_sz / 2.0, knob_sz, knob_sz)

        # Yumuşak gölge
        shadow_grad = QRadialGradient(QPointF(knob_cx, knob_cy + 1.0), knob_sz * 0.65)
        shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 120))
        shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(shadow_grad)
        p.drawEllipse(knob_rect.adjusted(-2.0, -1.0, 2.0, 3.0))

        # Beyaz tutaç gövdesi
        p.setBrush(TEXT)
        p.drawEllipse(knob_rect)

    p.restore()
    return {"track": track_rect, "knob": knob_rect}


def draw_ring_with_text(
    p: QPainter,
    cx: float,
    cy: float,
    value: float | None,
    color: QColor,
    size: float = RING_SZ,
    stroke: float = RING_STROKE,
    text: str | None = None,
    sub: str | None = None,
    meta: str | None = None,
) -> None:
    """64 px halka sayaç + merkezde 13.5 px tabular yüzde + altta sub ve meta etiketleri."""
    draw_ring(p, cx, cy, size, stroke, value, color)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    center_str = text if text is not None else pct(value)
    f_center = font(13.5, QFont.Weight.Bold, tabular=True)
    p.setFont(f_center)
    p.setPen(TEXT if value is not None else TEXT_LABEL)
    ring_box = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)
    p.drawText(ring_box, Qt.AlignmentFlag.AlignCenter, center_str)

    cur_y = cy + size / 2.0 + 5.0
    col_w = max(size + 36.0, 96.0)

    if sub:
        f_sub = font(11.0, QFont.Weight.Medium)
        p.setFont(f_sub)
        p.setPen(TEXT_CHIP)
        sub_rect = QRectF(cx - col_w / 2.0, cur_y, col_w, 15.0)
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, sub)
        cur_y += 15.0

    if meta:
        f_meta = font(10.0, QFont.Weight.Normal)
        p.setFont(f_meta)
        p.setPen(TEXT_META)
        meta_rect = QRectF(cx - col_w / 2.0, cur_y, col_w, 14.0)
        p.drawText(meta_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, meta)

    p.restore()


def draw_thin_bar(p: QPainter, rect: QRectF, value: float | None, color: QColor) -> None:
    """6 px ince durum çubuğu; value None veya <= 0 ise yalnız iz çizilir."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    h = min(THIN_BAR_H, rect.height())
    bar_rect = QRectF(rect.left(), rect.center().y() - h / 2.0, rect.width(), h)
    r = h / 2.0

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(TRACK)
    p.drawPath(rounded(bar_rect, r))

    if value is not None and value > 0:
        clamped = max(0.0, min(100.0, float(value)))
        fill_w = max(h, bar_rect.width() * (clamped / 100.0))
        fill_w = min(bar_rect.width(), fill_w)
        fill_rect = QRectF(bar_rect.left(), bar_rect.top(), fill_w, h)
        p.setBrush(color)
        p.drawPath(rounded(fill_rect, r))

    p.restore()


def draw_preset_pills(
    p: QPainter,
    rect: QRectF,
    labels: list[str] | tuple[str, ...],
    active_index: int | None = None,
    hover_index: int | None = None,
) -> list[QRectF]:
    """Eşit genişlikte 28 px yüksekliğinde önayar hapları (%25, %50, %75, %100). Aktif: #0A84FF."""
    n = len(labels)
    if n == 0:
        return []

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    gap = 8.0 if rect.width() > n * 36.0 else 4.0
    total_gap = gap * (n - 1)
    pill_w = max(4.0, (rect.width() - total_gap) / n)
    pill_h = min(PRESET_PILL_H, rect.height())
    y = rect.center().y() - pill_h / 2.0

    rects: list[QRectF] = []
    for i, lbl in enumerate(labels):
        x = rect.left() + i * (pill_w + gap)
        pr = QRectF(x, y, pill_w, pill_h)
        rects.append(pr)

        is_active = (i == active_index)
        is_hover = (i == hover_index)

        if is_active:
            p.setPen(QPen(ACCENT, 1.0))
            p.setBrush(ACCENT)
            f_p = font(12.0, QFont.Weight.DemiBold)
            txt_col = TEXT
        else:
            p.setPen(QPen(BUTTON_BORDER, 1.0))
            p.setBrush(BUTTON_HOVER if is_hover else BUTTON_BG)
            f_p = font(12.0, QFont.Weight.Medium)
            txt_col = TEXT if is_hover else QColor(255, 255, 255, 204)

        p.drawPath(rounded(pr.adjusted(0.5, 0.5, -0.5, -0.5), pill_h / 2.0))
        p.setFont(f_p)
        p.setPen(txt_col)
        p.drawText(pr, Qt.AlignmentFlag.AlignCenter, str(lbl))

    p.restore()
    return rects


def draw_toggle_button(
    p: QPainter,
    rect: QRectF,
    title: str,
    subtitle: str | None = None,
    icon: QPixmap | Callable[[QPainter, QRectF], None] | None = None,
    state: str = "off",
    hover_part: str | None = None,
    has_chevron: bool = True,
) -> dict[str, QRectF | None]:
    """Hızlı ayar / bağlantı anahtarı (on/off/unavailable/busy) + isteğe bağlı sağ bölünmüş ok ('›')."""
    if state not in {"on", "off", "unavailable", "busy"}:
        state = "off"

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    is_on = (state == "on")
    is_unavail = (state == "unavailable")
    is_busy = (state == "busy")

    if is_on:
        bg = QColor(10, 132, 255, 52 if hover_part == "main" else 38)  # rgba(10,132,255,.15)
        border = ACCENT
    elif is_unavail:
        bg = QColor(255, 255, 255, 8)
        border = QColor(255, 255, 255, 12)
    else:
        bg = QColor(255, 255, 255, 26 if hover_part == "main" else 15)  # rgba(255,255,255,.06)
        border = BUTTON_BORDER

    p.setPen(QPen(border, 1.0))
    p.setBrush(bg)
    p.drawPath(rounded(rect.adjusted(0.5, 0.5, -0.5, -0.5), R_TOGGLE))

    chev_rect: QRectF | None = None
    main_rect = QRectF(rect)

    if has_chevron:
        chev_w = min(26.0, max(18.0, rect.width() * 0.22))
        chev_rect = QRectF(rect.right() - chev_w, rect.top(), chev_w, rect.height())
        main_rect = QRectF(rect.left(), rect.top(), max(0.0, rect.width() - chev_w), rect.height())

        if hover_part == "chevron" and not is_unavail:
            p.save()
            p.setClipPath(rounded(rect.adjusted(0.5, 0.5, -0.5, -0.5), R_TOGGLE))
            p.fillRect(chev_rect, QColor(255, 255, 255, 22))
            p.restore()

        # İnce dikey ayırıcı
        div_col = QColor(10, 132, 255, 90) if is_on else QColor(255, 255, 255, 18)
        p.setPen(QPen(div_col, 1.0))
        p.drawLine(
            QPointF(chev_rect.left(), rect.top() + 7.0),
            QPointF(chev_rect.left(), rect.bottom() - 7.0),
        )

        # Sağ ok '›' (vektör çizgi — her platformda/fontta kusursuz görünür)
        ch_col = ACCENT if is_on else (TEXT_META if is_unavail else QColor(255, 255, 255, 115))
        pen_ch = QPen(ch_col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen_ch)
        p.setBrush(Qt.BrushStyle.NoBrush)
        ccx, ccy = chev_rect.center().x(), chev_rect.center().y()
        p.drawLine(QPointF(ccx - 1.8, ccy - 3.5), QPointF(ccx + 1.8, ccy))
        p.drawLine(QPointF(ccx + 1.8, ccy), QPointF(ccx - 1.8, ccy + 3.5))

    cur_x = main_rect.left() + 10.0
    cy = main_rect.center().y()

    if icon is not None:
        ic_sz = min(15.0, main_rect.height() - 8.0)
        ic_rect = QRectF(cur_x, cy - ic_sz / 2.0, ic_sz, ic_sz)
        _paint_icon(p, ic_rect, icon)
        cur_x = ic_rect.right() + 8.0

    text_w = max(0.0, main_rect.right() - 6.0 - cur_x)
    primary_col = TEXT if is_on else (TEXT_META if is_unavail else TEXT_BODY)
    sub_col = QColor(255, 255, 255, 190) if is_on else TEXT_MUTED

    sub_str = subtitle
    if is_busy and not sub_str:
        sub_str = "..."

    if sub_str and title and rect.height() >= 34.0:
        f_t = font(11.5, QFont.Weight.DemiBold if is_on else QFont.Weight.Medium)
        f_s = font(10.0, QFont.Weight.Normal)
        fm_t = QFontMetricsF(f_t)
        fm_s = QFontMetricsF(f_s)

        t_box = QRectF(cur_x, cy - 13.0, text_w, 13.0)
        s_box = QRectF(cur_x, cy + 0.5, text_w, 12.0)

        p.setFont(f_t)
        p.setPen(primary_col)
        p.drawText(
            t_box,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_t.elidedText(title, Qt.TextElideMode.ElideRight, max(8.0, text_w)),
        )

        p.setFont(f_s)
        p.setPen(sub_col)
        p.drawText(
            s_box,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_s.elidedText(sub_str, Qt.TextElideMode.ElideRight, max(8.0, text_w)),
        )
    else:
        label_str = sub_str if (sub_str and is_on) else (title or sub_str or "—")
        f_single = font(12.0, QFont.Weight.DemiBold if is_on else QFont.Weight.Medium)
        fm_single = QFontMetricsF(f_single)
        p.setFont(f_single)
        p.setPen(primary_col)
        t_box = QRectF(cur_x, main_rect.top(), text_w, main_rect.height())
        p.drawText(
            t_box,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_single.elidedText(label_str, Qt.TextElideMode.ElideRight, max(8.0, text_w)),
        )

    p.restore()
    return {"main": main_rect, "chevron": chev_rect}


_BADGE_STYLES: dict[str, tuple[QColor, QColor, QColor]] = {
    "danger": (QColor(255, 69, 58, 51), QColor(255, 69, 58, 89), DANGER),
    "ok": (QColor(48, 209, 88, 46), QColor(48, 209, 88, 77), OK),
    "info": (QColor(10, 132, 255, 51), QColor(10, 132, 255, 89), ACCENT),
    "muted": (QColor(255, 255, 255, 18), QColor(255, 255, 255, 20), TEXT_CHIP),
}


def draw_badge(
    p: QPainter,
    rect_or_point: QRectF | QPointF | tuple[float, float],
    text: str,
    kind: str = "muted",
) -> QRectF:
    """Durum rozeti (danger/ok/info/muted): DOLU, AKTİF, Kapalı vb. Çizilen QRectF'i döndürür."""
    bg, border, fg = _BADGE_STYLES.get(kind, _BADGE_STYLES["muted"])

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    f_b = font(10.0, QFont.Weight.Bold if kind in {"danger", "info", "ok"} else QFont.Weight.Medium)
    f_b.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.35)
    fm = QFontMetricsF(f_b)
    tw = fm.horizontalAdvance(text)

    if isinstance(rect_or_point, QRectF):
        if rect_or_point.width() > 0 and rect_or_point.height() > 0:
            w = min(rect_or_point.width(), tw + 12.0)
            h = min(rect_or_point.height(), 18.0)
            badge_rect = QRectF(rect_or_point.left(), rect_or_point.center().y() - h / 2.0, w, h)
        else:
            badge_rect = QRectF(rect_or_point.left(), rect_or_point.top(), tw + 12.0, 18.0)
    elif isinstance(rect_or_point, QPointF):
        badge_rect = QRectF(rect_or_point.x(), rect_or_point.y(), tw + 12.0, 18.0)
    else:
        px, py = float(rect_or_point[0]), float(rect_or_point[1])
        badge_rect = QRectF(px, py, tw + 12.0, 18.0)

    radius = 4.0 if kind in {"danger", "info", "ok"} else badge_rect.height() / 2.0
    p.setPen(QPen(border, 1.0))
    p.setBrush(bg)
    p.drawPath(rounded(badge_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius))

    p.setFont(f_b)
    p.setPen(fg)
    p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)

    p.restore()
    return badge_rect
