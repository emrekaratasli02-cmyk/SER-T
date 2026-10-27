"""Şerit açılır panelleri için ortak görsel dil — Yön C "Kart katmanlı" (27 Eki 2026, Emre seçti).

Tek kaynak: tüm paneller (Claude, Sistem, Mail, Antigravity, Takvim, Parlaklık, Ses) renk, köşe,
boşluk ve yazı boyutlarını buradan alır. Şartname:
hermes/cache/scratch/serit-mockups/v12/C/spec.md ve panels.html.

Kurallar: panel tamamen opak (arkadaki yazı görünmez), dış köşe 16, iç kart 12, düğme 8, rozet hap.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

# --- Yüzeyler -------------------------------------------------------------------------------
PANEL_BG = QColor(0x14, 0x15, 0x18)            # opak, alfa yok
PANEL_BORDER = QColor(255, 255, 255, 20)       # rgba(255,255,255,.08)
TILE_BG = QColor(0x1D, 0x1F, 0x24)
TILE_BORDER = QColor(255, 255, 255, 15)        # rgba(255,255,255,.06)
TILE_HOVER = QColor(0x23, 0x26, 0x2C)
BUTTON_BG = QColor(255, 255, 255, 18)
BUTTON_HOVER = QColor(255, 255, 255, 32)

# --- Metin ----------------------------------------------------------------------------------
TEXT = QColor(255, 255, 255)
TEXT_BODY = QColor(255, 255, 255, 217)         # .85
TEXT_MUTED = QColor(255, 255, 255, 128)        # .50
TEXT_LABEL = QColor(255, 255, 255, 115)        # .45 (BÜYÜK HARF bölüm etiketi)

# --- Anlamlı renkler ------------------------------------------------------------------------
CLAUDE = QColor("#D97757")
CPU = QColor("#64D2FF")
RAM = QColor("#BF5AF2")
DISK = QColor("#30D158")
BRIGHT = QColor("#FFB020")
SOUND = QColor("#0A84FF")
ACCENT = QColor("#0A84FF")
WARN = QColor("#FF9F0A")
DANGER = QColor("#FF453A")
OK = QColor("#30D158")
TRACK = QColor(255, 255, 255, 26)

# --- Ölçüler --------------------------------------------------------------------------------
R_PANEL = 16.0
R_TILE = 12.0
R_BUTTON = 8.0
PAD = 16.0            # panel iç boşluğu
TILE_PAD = 13.0       # kart iç boşluğu
GAP = 12.0            # öğeler arası
HEADER_H = 44.0
FOOTER_H = 40.0
ANCHOR_GAP = 8.0      # panel ile şerit arası

WIDTH = {"mail": 380, "cal": 440, "claude": 360, "ag": 360, "sys": 360, "bright": 340, "vol": 340}

FONT_FAMILY = "Segoe UI Variable Text"


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
    return font(14.0, QFont.Weight.DemiBold)


def f_label() -> QFont:
    f = font(11.0, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
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
    r = QRectF(center_x - diameter / 2 + stroke / 2, center_y - diameter / 2 + stroke / 2,
               diameter - stroke, diameter - stroke)
    pen = QPen(TRACK, stroke)
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
