"""Modern sectioned acrylic glass popover card with refresh action for Şerit dock.

Provides high-DPI acrylic flyout panels for Claude quotas, system telemetry,
weather conditions, and financial market rates with sectioned layouts, hairline
separators, dimmed error states, tabular figures, and an interactive refresh button.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import psutil
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Safe imports from serit package
try:
    import sources
    import theme
    import winapi
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    import sources
    import theme
    import winapi

# Geometry tokens
WIDTH: int = 280
CORNER_RADIUS: float = 14.0

# Base Material & Typography Colors
COLOR_BG: QColor = QColor(16, 20, 28, 238)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(255, 255, 255, 185)
COLOR_TEXT_MUTED: QColor = QColor(255, 255, 255, 130)

# Section Titles & Hairlines
COLOR_SECTION_TITLE: QColor = QColor(255, 255, 255, 115)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 20)  # rgba(255, 255, 255, 0.08)
COLOR_PROGRESS_TRACK: QColor = QColor(255, 255, 255, 22)

# Semantic Accent Colors
COLOR_CLAUDE_S: QColor = QColor("#F08A5D")
COLOR_CLAUDE_W: QColor = QColor("#F6B38F")
COLOR_CLAUDE_OPUS: QColor = QColor("#E09F7D")

COLOR_CPU: QColor = QColor("#60B5FF")
COLOR_RAM: QColor = QColor("#B49CFF")
COLOR_DISK: QColor = QColor("#86EFAC")

COLOR_ALERT_WARN: QColor = QColor("#FFC45C")
COLOR_ALERT_CRIT: QColor = QColor("#FF6060")

COLOR_FX_UP: QColor = QColor("#78DC96")
COLOR_FX_DOWN: QColor = QColor("#FF6E6E")
COLOR_FX_FLAT: QColor = QColor(255, 255, 255, 160)

# Badge Colors
COLOR_BADGE_CLAUDE_BG: QColor = QColor(240, 138, 93, 45)
COLOR_BADGE_CLAUDE_TXT: QColor = QColor("#FFB08A")
COLOR_BADGE_STALE_BG: QColor = QColor(245, 158, 11, 45)
COLOR_BADGE_STALE_TXT: QColor = QColor("#FCD34D")
COLOR_BADGE_ERR_BG: QColor = QColor(239, 68, 68, 45)
COLOR_BADGE_ERR_TXT: QColor = QColor("#FCA5A5")
COLOR_BADGE_LIVE_BG: QColor = QColor(255, 255, 255, 24)
COLOR_BADGE_LIVE_TXT: QColor = QColor(255, 255, 255, 210)

# Refresh Button Colors
COLOR_REFRESH_BG: QColor = QColor(255, 255, 255, 16)
COLOR_REFRESH_BG_HOVER: QColor = QColor(255, 255, 255, 34)
COLOR_REFRESH_BG_PRESS: QColor = QColor(255, 255, 255, 54)
COLOR_REFRESH_BORDER: QColor = QColor(255, 255, 255, 36)
COLOR_REFRESH_TXT: QColor = QColor(255, 255, 255, 220)


def make_font(
    size_px: int,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
) -> QFont:
    """Create a high-DPI Segoe UI Variable font instance with tabular numerals."""
    f = QFont("Segoe UI Variable Text")
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    f.setPixelSize(size_px)
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


def get_bar_color(pct: float, default_col: QColor) -> QColor:
    """Determine progress bar color based on warning/critical thresholds."""
    if pct >= 95.0:
        return COLOR_ALERT_CRIT
    if pct >= 80.0:
        return COLOR_ALERT_WARN
    return default_col


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def format_source_time(fetched_at: Optional[float] = None) -> str:
    """Format timestamp into HH:MM in Europe/Istanbul timezone."""
    now_dt = dt.datetime.now(sources.LOCAL_TZ)
    if fetched_at:
        try:
            return dt.datetime.fromtimestamp(fetched_at, tz=sources.LOCAL_TZ).strftime("%H:%M")
        except Exception:
            pass
    return now_dt.strftime("%H:%M")


def top_processes(n: int = 3) -> List[Dict[str, Any]]:
    """Return top n processes by RSS memory in MB, aggregated by process name, skipping system/idle."""
    skip = {
        "system idle process",
        "system",
        "svchost.exe",
        "registry",
        "memory compression",
        "idle",
    }
    agg: Dict[str, float] = {}
    try:
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                name = p.info.get("name")
                if not name:
                    continue
                if name.lower() in skip:
                    continue
                mem = p.info.get("memory_info")
                if mem and hasattr(mem, "rss"):
                    agg[name] = agg.get(name, 0.0) + (mem.rss / (1024.0 * 1024.0))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        pass

    sorted_procs = sorted(
        [{"name": k, "mb": round(v, 1)} for k, v in agg.items()],
        key=lambda x: x["mb"],
        reverse=True,
    )
    return sorted_procs[:n]


# Vector Icon Drawing Primitives
def draw_claude_icon(p: QPainter, rect: QRectF) -> None:
    """Draw Anthropic Claude spark mark in Coral accent."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.46

    path = QPainterPath()
    # 8-point subtle starburst
    points: List[QPointF] = []
    for i in range(8):
        ang = i * math.pi / 4.0
        rad = r if (i % 2 == 0) else (r * 0.40)
        points.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))

    path.moveTo(points[0])
    for pt in points[1:]:
        path.lineTo(pt)
    path.closeSubpath()

    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_CLAUDE_S)
    p.drawPath(path)
    p.restore()


def draw_sys_icon(p: QPainter, rect: QRectF) -> None:
    """Draw system chip icon in Cyan accent."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.42

    chip_r = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    p.setPen(QPen(COLOR_CPU, 1.2))
    p.setBrush(QColor(96, 181, 255, 30))
    p.drawRoundedRect(chip_r, 2.5, 2.5)

    # Core indicator
    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_CPU)
    p.drawRoundedRect(QRectF(cx - r * 0.45, cy - r * 0.45, r * 0.9, r * 0.9), 1.5, 1.5)

    # Pins
    p.setPen(QPen(COLOR_CPU, 1.0))
    p.drawLine(QPointF(cx - r * 0.5, cy - r - 2), QPointF(cx - r * 0.5, cy - r))
    p.drawLine(QPointF(cx + r * 0.5, cy - r - 2), QPointF(cx + r * 0.5, cy - r))
    p.drawLine(QPointF(cx - r * 0.5, cy + r), QPointF(cx - r * 0.5, cy + r + 2))
    p.drawLine(QPointF(cx + r * 0.5, cy + r), QPointF(cx + r * 0.5, cy + r + 2))
    p.restore()


def draw_fx_icon(p: QPainter, rect: QRectF) -> None:
    """Draw currency / market trending icon in Fresh Green accent."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) * 0.42

    p.setPen(QPen(COLOR_FX_UP, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    # Trending zigzag
    path = QPainterPath()
    path.moveTo(cx - r, cy + r * 0.4)
    path.lineTo(cx - r * 0.2, cy - r * 0.2)
    path.lineTo(cx + r * 0.2, cy + r * 0.2)
    path.lineTo(cx + r, cy - r * 0.6)
    p.drawPath(path)

    # Arrow head
    p.drawLine(QPointF(cx + r * 0.5, cy - r * 0.6), QPointF(cx + r, cy - r * 0.6))
    p.drawLine(QPointF(cx + r, cy - r * 0.1), QPointF(cx + r, cy - r * 0.6))
    p.restore()


def draw_refresh_icon(p: QPainter, rect: QRectF, angle: float = 0.0) -> None:
    """Draw circular reload arrow icon with rotation support."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    p.translate(cx, cy)
    p.rotate(angle)

    r = min(rect.width(), rect.height()) * 0.40
    pen = QPen(COLOR_REFRESH_TXT, 1.3, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    arc_box = QRectF(-r, -r, 2 * r, 2 * r)
    p.drawArc(arc_box, int(35 * 16), int(285 * 16))

    tip_ang = math.radians(35)
    tx = r * math.cos(tip_ang)
    ty = -r * math.sin(tip_ang)
    p.drawLine(QPointF(tx, ty), QPointF(tx + 2.5, ty + 2.5))
    p.drawLine(QPointF(tx, ty), QPointF(tx - 2.5, ty + 2.5))
    p.restore()


# Content Builders
def build_claude_content(data: dict) -> dict:
    """Build sectioned popover content dictionary for Claude usage."""
    raw_source = data.get("source", "Anthropic · Claude Code")
    source = raw_source.replace(" · Claude Code girişi", "")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    plan = (data.get("plan") or "Max").capitalize()
    s_val = float(data.get("session", 0.0))
    w_val = float(data.get("week", 0.0))
    s_reset = data.get("session_reset", "")
    w_reset = data.get("week_reset", "")

    s_clock = sources.reset_clock(s_reset) if s_reset else ""
    w_clock = sources.reset_clock(w_reset) if w_reset else ""
    s_left = sources.left_text(s_reset) if s_reset else ""
    w_left = sources.left_text(w_reset) if w_reset else ""

    s_sub = f"{s_left} sonra sıfırlanır ({s_clock})" if (s_left or s_clock) else ""
    w_sub = f"{w_left} sonra ({w_clock})" if (w_left or w_clock) else ""

    usage_rows = [
        {
            "type": "bar",
            "label": "Oturum (5 sa)",
            "val": f"%{s_val:.0f}",
            "pct": s_val,
            "col": get_bar_color(s_val, COLOR_CLAUDE_S),
            "sub": s_sub,
        },
        {
            "type": "bar",
            "label": "Haftalık",
            "val": f"%{w_val:.0f}",
            "pct": w_val,
            "col": get_bar_color(w_val, COLOR_CLAUDE_W),
            "sub": w_sub,
        },
    ]

    opus = data.get("opus")
    if opus is not None:
        try:
            o_val = float(opus)
            if o_val > 0.0:
                usage_rows.append({
                    "type": "bar",
                    "label": "Opus (7 gün)",
                    "val": f"%{o_val:.0f}",
                    "pct": o_val,
                    "col": get_bar_color(o_val, COLOR_CLAUDE_OPUS),
                    "sub": "",
                })
        except (ValueError, TypeError):
            pass

    sonnet = data.get("sonnet")
    if sonnet is not None:
        try:
            sn_val = float(sonnet)
            if sn_val > 0.0:
                usage_rows.append({
                    "type": "bar",
                    "label": "Sonnet (7 gün)",
                    "val": f"%{sn_val:.0f}",
                    "pct": sn_val,
                    "col": get_bar_color(sn_val, COLOR_CLAUDE_S),
                    "sub": "",
                })
        except (ValueError, TypeError):
            pass

    sections = [{"title": "KULLANIM", "rows": usage_rows}]

    if stale:
        footer_note = f"Claude Code girişinden okunur · önbellek {t_str}"
    else:
        footer_note = f"Claude Code girişinden okunur · {t_str}"

    return {
        "kind": "claude",
        "title": "Claude",
        "badge": plan if not err else "Hata",
        "badge_bg": COLOR_BADGE_ERR_BG if err else COLOR_BADGE_CLAUDE_BG,
        "badge_color": COLOR_BADGE_ERR_TXT if err else COLOR_BADGE_CLAUDE_TXT,
        "stale": stale,
        "error": str(err) if err else None,
        "sections": sections,
        "footer_note": footer_note,
        "source": source,
    }


def build_sys_content(data: dict) -> dict:
    """Build sectioned popover content dictionary for system telemetry."""
    source = data.get("source", "Bu bilgisayar")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    cpu_val = float(data.get("cpu", 0.0))
    ram_val = float(data.get("ram", 0.0))
    ram_used = float(data.get("ram_used_gb", 0.0))
    ram_total = float(data.get("ram_total_gb", 0.0))
    disk_val = float(data.get("disk_c", 0.0))

    ram_label = (
        f"RAM ({sources.fmt_tr(ram_used, 1)} / {sources.fmt_tr(ram_total, 1)} GB)"
        if ram_total > 0
        else "RAM"
    )

    sys_rows = [
        {
            "type": "bar",
            "label": "İşlemci",
            "val": f"%{cpu_val:.0f}",
            "pct": cpu_val,
            "col": get_bar_color(cpu_val, COLOR_CPU),
            "sub": "",
        },
        {
            "type": "bar",
            "label": ram_label,
            "val": f"%{ram_val:.0f}",
            "pct": ram_val,
            "col": get_bar_color(ram_val, COLOR_RAM),
            "sub": "",
        },
        {
            "type": "bar",
            "label": "Disk C:",
            "val": f"%{disk_val:.0f}",
            "pct": disk_val,
            "col": get_bar_color(disk_val, COLOR_DISK),
            "sub": "",
        },
    ]

    sections = [{"title": "SİSTEM", "rows": sys_rows}]

    top = data.get("top")
    if top and isinstance(top, list):
        proc_rows = []
        for p_item in top[:3]:
            proc_rows.append({
                "type": "proc",
                "name": str(p_item.get("name", "")),
                "mb": float(p_item.get("mb", 0.0)),
            })
        if proc_rows:
            sections.append({"title": "EN ÇOK BELLEK", "rows": proc_rows})

    footer_note = f"Bu bilgisayar · {t_str}"

    return {
        "kind": "sys",
        "title": "Sistem",
        "badge": "Hata" if err else ("Canlı" if not stale else None),
        "badge_bg": COLOR_BADGE_ERR_BG if err else COLOR_BADGE_LIVE_BG,
        "badge_color": COLOR_BADGE_ERR_TXT if err else COLOR_BADGE_LIVE_TXT,
        "stale": stale,
        "error": str(err) if err else None,
        "sections": sections,
        "footer_note": footer_note,
        "source": source,
    }


def build_wx_content(data: dict, city: str = "Aksaray") -> dict:
    """Build sectioned popover content dictionary for weather conditions."""
    source = data.get("source", "open-meteo.com")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    resolved_city = data.get("city", city)

    temp = data.get("temp")
    temp_str = f"{sources.fmt_tr(temp, 1)}°" if temp is not None else "--°"
    feel = data.get("feel")
    feel_str = f"{sources.fmt_tr(feel, 1)}°" if feel is not None else "--°"
    desc = data.get("desc", "Bilinmiyor")
    icon = data.get("icon", "cloud")
    min_t = data.get("min")
    max_t = data.get("max")
    wind = data.get("wind")

    hero = {
        "icon": icon,
        "desc": desc,
        "temp": temp_str,
        "feel_str": feel_str,
    }

    min_max_str = (
        f"{sources.fmt_tr(min_t, 1)}° / {sources.fmt_tr(max_t, 1)}°"
        if (min_t is not None and max_t is not None)
        else "--"
    )
    wind_str = f"{sources.fmt_tr(wind, 1)} km/sa" if wind is not None else "--"

    detail_rows = [
        {"type": "wx_detail", "label": "Hissedilen", "val": feel_str},
        {"type": "wx_detail", "label": "En düşük / En yüksek", "val": min_max_str},
        {"type": "wx_detail", "label": "Rüzgâr", "val": wind_str},
    ]

    sections = [{"title": "DETAYLAR", "rows": detail_rows}]
    footer_note = f"open-meteo.com · {t_str}"

    return {
        "kind": "wx",
        "title": "Hava Durumu",
        "badge": "Hata" if err else resolved_city,
        "badge_bg": COLOR_BADGE_ERR_BG if err else COLOR_BADGE_LIVE_BG,
        "badge_color": COLOR_BADGE_ERR_TXT if err else COLOR_BADGE_LIVE_TXT,
        "stale": stale,
        "error": str(err) if err else None,
        "hero": hero,
        "sections": sections,
        "footer_note": footer_note,
        "source": source,
    }


def build_fx_content(data: dict) -> dict:
    """Build sectioned popover content dictionary for financial exchange rates."""
    source = data.get("source", "finans.truncgil.com")
    raw_updated = data.get("updated")
    if raw_updated and isinstance(raw_updated, str) and " " in raw_updated:
        t_str = raw_updated.split(" ")[1][:5]
    else:
        t_str = format_source_time(data.get("fetched_at"))

    stale = bool(data.get("stale", False))
    err = data.get("err")

    usd = float(data.get("usd", 0.0))
    usd_chg = float(data.get("usd_chg", 0.0))
    eur = float(data.get("eur", 0.0))
    eur_chg = float(data.get("eur_chg", 0.0))
    gold = float(data.get("gold", 0.0))
    gold_chg = float(data.get("gold_chg", 0.0))

    def format_fx_change(chg: float) -> Tuple[str, QColor]:
        chg_fmt = sources.fmt_tr(chg, 2)
        if chg > 0:
            return f"%+{chg_fmt}", COLOR_FX_UP
        if chg < 0:
            return f"%{chg_fmt}", COLOR_FX_DOWN
        return f"%{chg_fmt}", COLOR_FX_FLAT

    u_chg_str, u_col = format_fx_change(usd_chg)
    e_chg_str, e_col = format_fx_change(eur_chg)
    g_chg_str, g_col = format_fx_change(gold_chg)

    fx_rows = [
        {
            "type": "fx",
            "label": "Dolar",
            "val": f"{sources.fmt_tr(usd, 2)} ₺",
            "chg": u_chg_str,
            "chg_col": u_col,
        },
        {
            "type": "fx",
            "label": "Euro",
            "val": f"{sources.fmt_tr(eur, 2)} ₺",
            "chg": e_chg_str,
            "chg_col": e_col,
        },
        {
            "type": "fx",
            "label": "Gram altın",
            "val": f"{sources.fmt_tr(gold, 2)} ₺",
            "chg": g_chg_str,
            "chg_col": g_col,
        },
    ]

    sections = [{"title": "DÖVİZ VE ALTIN", "rows": fx_rows}]
    footer_note = f"Veri saati {t_str} · {source}"

    return {
        "kind": "fx",
        "title": "Piyasa",
        "badge": "Hata" if err else "Satış",
        "badge_bg": COLOR_BADGE_ERR_BG if err else COLOR_BADGE_LIVE_BG,
        "badge_color": COLOR_BADGE_ERR_TXT if err else COLOR_BADGE_LIVE_TXT,
        "stale": stale,
        "error": str(err) if err else None,
        "sections": sections,
        "footer_note": footer_note,
        "source": source,
    }


def build_content(kind: str, data: dict, **kwargs) -> dict:
    """Route data payload to appropriate builder or return pre-built schema."""
    if "sections" in data and "footer_note" in data:
        return data

    if kind == "claude":
        return build_claude_content(data)
    elif kind == "sys":
        return build_sys_content(data)
    elif kind == "wx":
        return build_wx_content(data, **kwargs)
    elif kind == "fx":
        return build_fx_content(data)
    return build_claude_content(data)


# PopoverV2 Widget Implementation
class PopoverV2(QWidget):
    """Modern sectioned acrylic glass popover card with refresh button."""

    WIDTH: int = WIDTH
    RADIUS: float = CORNER_RADIUS

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_refresh: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)

        # Frameless translucent acrylic window setup
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        # Internal state
        self._kind: str = ""
        self._anchor_rect_global: Optional[QRectF] = None
        self._content: dict = {}
        self.on_refresh: Optional[Callable[[str], None]] = on_refresh

        # K4 focus coordination tracking
        self._last_close_time: float = 0.0
        self._last_close_kind: str = ""
        self._is_closing: bool = False

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Open / Close animation state
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0
        self._anim_scale: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Refresh button interaction & spinner state
        self._refresh_rect: QRectF = QRectF(self.WIDTH - 16.0 - 66.0, 150.0, 66.0, 22.0)
        self._refresh_hovered: bool = False
        self._refresh_pressed: bool = False
        self._refresh_spinning: bool = False
        self._spin_angle: float = 0.0

        self._spin_anim = QVariantAnimation(self)
        self._spin_anim.setDuration(600)
        self._spin_anim.setStartValue(0.0)
        self._spin_anim.setEndValue(360.0)
        self._spin_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._spin_anim.valueChanged.connect(self._on_spin_value_changed)
        self._spin_anim.finished.connect(self._on_spin_finished)

        # Font instances
        self.f_title = make_font(13, QFont.Weight.DemiBold)
        self.f_badge = make_font(10, QFont.Weight.DemiBold)
        self.f_sec_title = make_font(9, QFont.Weight.Bold, letter_spacing=1.0)
        self.f_label = make_font(12, QFont.Weight.Normal)
        self.f_val = make_font(12, QFont.Weight.DemiBold, tabular=True)
        self.f_val_bold = make_font(12, QFont.Weight.Bold, tabular=True)
        self.f_sub = make_font(10, QFont.Weight.Normal)
        self.f_footer = make_font(10, QFont.Weight.Normal)
        self.f_btn = make_font(10, QFont.Weight.DemiBold)
        self.f_wx_desc = make_font(13, QFont.Weight.DemiBold)
        self.f_wx_temp = make_font(24, QFont.Weight.Bold, tabular=True)

        self.resize(self.WIDTH, 200)

    # Public API
    def is_open(self, kind: Optional[str] = None) -> bool:
        """Return True if popover is open (visible and not closing)."""
        if not self.isVisible() or self._is_closing:
            return False
        if kind is not None:
            return self._kind == kind
        return True

    def recently_closed(self, kind: Optional[str] = None, threshold_ms: float = 250.0) -> bool:
        """Check if this popover kind was closed within threshold_ms to prevent K4 reopen bounce."""
        if self._last_close_time <= 0.0:
            return False
        if kind is not None and self._last_close_kind != kind:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def refresh_button_rect(self) -> QRectF:
        """Return global/local coordinates of the footer refresh button."""
        return self._refresh_rect

    def is_refresh_hit(self, pos: Union[QPointF, QPoint]) -> bool:
        """Hit test cursor against the footer refresh button."""
        return self._refresh_rect.contains(QPointF(pos))

    def trigger_refresh(self) -> None:
        """Execute refresh action: initiate spinner micro-animation and invoke callback."""
        if not self._refresh_spinning:
            self._refresh_spinning = True
            self._spin_angle = 0.0
            self._spin_anim.stop()
            self._spin_anim.start()
        self.update()

        if callable(self.on_refresh):
            try:
                self.on_refresh(self._kind)
            except Exception as exc:
                try:
                    sources.log_err("on_refresh", exc)
                except Exception:
                    pass

    def compute_height(self, content: dict) -> int:
        """Calculate dynamic popover height based on content sections and error banner."""
        # Top padding (14) + Header height (18) + Gap (10) = 42
        h = 42.0

        if content.get("error"):
            # Error banner box: 48px + 10px margin = 58px
            h += 58.0

        if content.get("hero"):
            # Weather hero block: 46px + 8px margin = 54px
            h += 54.0

        for sec in content.get("sections", []):
            if sec.get("title"):
                h += 20.0
            rows = sec.get("rows", [])
            for r in rows:
                rtype = r.get("type", "bar")
                if rtype == "bar":
                    # Label (16) + gap (6) + bar (4) + gap (6) = 32
                    h += 32.0
                    if r.get("sub"):
                        # Subtext line: 14 + gap (4) = 18
                        h += 18.0
                    h += 6.0
                elif rtype == "proc":
                    h += 24.0
                elif rtype == "fx":
                    h += 28.0
                elif rtype == "wx_detail":
                    h += 24.0
            # Section bottom padding
            h += 4.0

        # Footer separator (1) + height (34) = 35
        h += 35.0
        return max(150, int(math.ceil(h)))

    def show_for(
        self,
        kind: str,
        anchor_rect_global: Union[QRectF, QRect],
        content_dict: dict,
        **kwargs,
    ) -> None:
        """Position centered above anchor, apply acrylic blur-behind, and animate in."""
        self._kind = kind
        self._anchor_rect_global = (
            QRectF(anchor_rect_global) if anchor_rect_global is not None else None
        )
        self._content = build_content(kind, content_dict, **kwargs)

        h = self.compute_height(self._content)
        self.resize(self.WIDTH, h)
        self._refresh_rect = QRectF(self.WIDTH - 16.0 - 66.0, float(h - 28), 66.0, 22.0)

        # Coordinate positioning
        dpr = 1.25
        if self._anchor_rect_global is not None:
            anchor_cx = self._anchor_rect_global.center().x()
            target_x = int(anchor_cx - self.width() / 2.0)
            target_y = int(self._anchor_rect_global.top() - self.height() - 10)

            center_pt = self._anchor_rect_global.center().toPoint()
            screen = QGuiApplication.screenAt(center_pt)
            if screen is None:
                screen = QGuiApplication.primaryScreen()

            if screen is not None:
                geom = screen.availableGeometry()
                dpr = screen.devicePixelRatio()
                margin = 10
                min_x = geom.left() + margin
                max_x = geom.right() - self.width() - margin
                if max_x >= min_x:
                    target_x = max(min_x, min(max_x, target_x))
                else:
                    target_x = min_x

                min_y = geom.top() + margin
                max_y = geom.bottom() - self.height() - margin
                if target_y < min_y:
                    below_y = int(self._anchor_rect_global.bottom() + 10)
                    if below_y + self.height() <= geom.bottom() - margin:
                        target_y = below_y
                    else:
                        target_y = min_y
                elif target_y > max_y:
                    target_y = max_y

            self.move(target_x, target_y)

        # Apply Windows acrylic composition & physical rounded region
        hwnd = int(self.winId())
        try:
            winapi.enable_acrylic(hwnd, 0x50181612)
            winapi.set_round_region(hwnd, self.width(), self.height(), int(self.RADIUS), dpr)
        except Exception:
            pass

        # Trigger open transition: fade 0->1, slide 8px, scale 0.96->1 in 200ms OutCubic
        self._is_closing = False
        self._anim.stop()
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)

        self._anim_progress = 0.0
        self._anim_opacity = 0.0
        self._anim_offset_y = 8.0
        self._anim_scale = 0.96

        self.show()
        self.activateWindow()
        self._anim.start()

    def hide_animated(self) -> None:
        """Trigger close transition: fade 1->0, slide 6px in 150ms InQuad, then hide."""
        if not self.isVisible() or self._is_closing:
            return

        self._is_closing = True
        self._last_close_time = time.monotonic()
        self._last_close_kind = self._kind

        self._anim.stop()
        start_val = self._anim_progress
        duration = max(40, int(150 * start_val))

        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim.setStartValue(start_val)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current popover view offscreen to a high-DPI ARGB32 QImage."""
        w_phys = int(self.width() * dpr)
        h_phys = int(self.height() * dpr)
        img = QImage(w_phys, h_phys, QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        saved_op = self._anim_opacity
        saved_off = self._anim_offset_y
        saved_scale = self._anim_scale
        self._anim_opacity = 1.0
        self._anim_offset_y = 0.0
        self._anim_scale = 1.0

        self._paint_card(p)

        self._anim_opacity = saved_op
        self._anim_offset_y = saved_off
        self._anim_scale = saved_scale

        p.end()
        return img

    # Animation Callbacks
    def _on_anim_value_changed(self, val: float) -> None:
        self._anim_progress = float(val)
        self._anim_opacity = max(0.0, min(1.0, float(val)))
        if self._is_closing:
            self._anim_offset_y = 6.0 * (1.0 - self._anim_opacity)
            self._anim_scale = 0.96 + 0.04 * self._anim_opacity
        else:
            self._anim_offset_y = 8.0 * (1.0 - self._anim_opacity)
            self._anim_scale = 0.96 + 0.04 * self._anim_opacity
        self.update()

    def _on_anim_finished(self) -> None:
        if self._is_closing:
            self.hide()
            self._is_closing = False
            self._anim_opacity = 0.0
            self.update()

    def _on_spin_value_changed(self, val: float) -> None:
        self._spin_angle = float(val)
        self.update()

    def _on_spin_finished(self) -> None:
        self._refresh_spinning = False
        self._spin_angle = 0.0
        self.update()

    def _on_anchor_timeout(self) -> None:
        """Close popover if dock toggle was not clicked after focus transfer."""
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    # Event Handlers
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                cursor_pos = QCursor.pos()
                if self._anchor_rect_global is not None:
                    if self._anchor_rect_global.contains(QPointF(cursor_pos)):
                        # K4 Fix: Clicking on the same anchor chip caused deactivation.
                        # Record close timestamp so recently_closed() works, but allow dock click.
                        self._last_close_time = time.monotonic()
                        self._last_close_kind = self._kind
                        self._anchor_timer.start(300)
                        super().changeEvent(event)
                        return
                self.hide_animated()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        self._last_close_kind = self._kind
        super().hideEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        is_hit = self._refresh_rect.contains(pos)
        if is_hit != self._refresh_hovered:
            self._refresh_hovered = is_hit
            if is_hit:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._refresh_rect.contains(pos):
                self._refresh_pressed = True
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._refresh_pressed:
            self._refresh_pressed = False
            pos = event.position()
            if self._refresh_rect.contains(pos):
                self.trigger_refresh()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._refresh_hovered or self._refresh_pressed:
            self._refresh_hovered = False
            self._refresh_pressed = False
            self.unsetCursor()
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        if self._anim_opacity <= 0.001:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setOpacity(self._anim_opacity)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        p.translate(cx, cy + self._anim_offset_y)
        p.scale(self._anim_scale, self._anim_scale)
        p.translate(-cx, -cy)

        self._paint_card(p)
        p.end()

    # Painting Internal Implementation
    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = rounded_path(r, self.RADIUS)

        # 1. Base acrylic dark glass
        p.fillPath(path, COLOR_BG)

        # 2. Specular top sheen
        p.save()
        p.setClipPath(path)
        hl = QLinearGradient(0, 0, 0, 5)
        hl.setColorAt(0.0, QColor(255, 255, 255, 55))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, w - 2, 5), hl)
        p.restore()

        # 3. Outer boundary & specular rim
        p.setPen(QPen(QColor(0, 0, 0, 95), 1))
        p.drawPath(path)

        inner_r = r.adjusted(0.75, 0.75, -0.75, -0.75)
        inner_path = rounded_path(inner_r, self.RADIUS - 0.75)
        rim_grad = QLinearGradient(0, 0, 0, h)
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 95))
        rim_grad.setColorAt(0.20, QColor(255, 255, 255, 38))
        rim_grad.setColorAt(0.80, QColor(255, 255, 255, 10))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 25))
        p.setPen(QPen(rim_grad, 1))
        p.drawPath(inner_path)

        # 4. Header (App Icon + Title + Plan Badge + Stale Badge)
        cur_kind = self._content.get("kind", self._kind)
        icon_rect = QRectF(16, 14, 18, 18)
        if cur_kind == "claude":
            draw_claude_icon(p, icon_rect)
        elif cur_kind == "sys":
            draw_sys_icon(p, icon_rect)
        elif cur_kind == "wx":
            hero_icon = (self._content.get("hero") or {}).get("icon", "cloud")
            try:
                theme.draw_weather_icon(p, icon_rect, hero_icon)
            except Exception:
                draw_claude_icon(p, icon_rect)
        elif cur_kind == "fx":
            draw_fx_icon(p, icon_rect)

        title = self._content.get("title", "")
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_t = QFontMetricsF(self.f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(40, 14, title_w + 4, 18), Qt.AlignLeft | Qt.AlignVCenter, title)

        cur_x = 40 + title_w + 8.0

        # Plan / Status Badge
        badge = self._content.get("badge")
        if badge:
            p.setFont(self.f_badge)
            fm_b = QFontMetricsF(self.f_badge)
            bw = fm_b.horizontalAdvance(badge) + 12.0
            badge_r = QRectF(cur_x, 14, bw, 18)
            bpath = rounded_path(badge_r, 5)
            badge_bg = self._content.get("badge_bg", COLOR_BADGE_CLAUDE_BG)
            badge_txt = self._content.get("badge_color", COLOR_BADGE_CLAUDE_TXT)
            p.fillPath(bpath, badge_bg)
            p.setPen(badge_txt)
            p.drawText(badge_r, Qt.AlignCenter, badge)
            cur_x += bw + 6.0

        # Stale indicator badge
        if self._content.get("stale"):
            p.setFont(self.f_badge)
            fm_s = QFontMetricsF(self.f_badge)
            sw = fm_s.horizontalAdvance("Bayat") + 10.0
            stale_r = QRectF(cur_x, 14, sw, 18)
            p.fillPath(rounded_path(stale_r, 5), COLOR_BADGE_STALE_BG)
            p.setPen(COLOR_BADGE_STALE_TXT)
            p.drawText(stale_r, Qt.AlignCenter, "Bayat")

        # 5. Content Layout (Error Banner, Weather Hero, Sections)
        y = 42.0

        err_msg = self._content.get("error")
        has_sections = bool(self._content.get("sections"))
        has_hero = bool(self._content.get("hero"))

        if err_msg:
            # Clear red-tinted banner with reason
            err_box = QRectF(16, y, w - 32, 48)
            p.fillPath(rounded_path(err_box, 7), QColor(239, 68, 68, 26))
            p.setPen(QPen(QColor(239, 68, 68, 85), 1))
            p.drawPath(rounded_path(err_box, 7))

            # Warning icon / bullet
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EF4444"))
            p.drawEllipse(QRectF(26, y + 16, 16, 16))
            p.setPen(QColor(255, 255, 255))
            p.setFont(make_font(10, QFont.Weight.Bold))
            p.drawText(QRectF(26, y + 16, 16, 16), Qt.AlignCenter, "!")

            p.setFont(make_font(11, QFont.Weight.Bold))
            p.setPen(QColor("#FCA5A5"))
            p.drawText(QRectF(48, y + 8, w - 80, 16), Qt.AlignLeft | Qt.AlignVCenter, "Bağlantı Hatası")

            p.setFont(self.f_sub)
            p.setPen(COLOR_TEXT_SECONDARY)
            fm_err = QFontMetricsF(self.f_sub)
            elided_err = fm_err.elidedText(str(err_msg), Qt.TextElideMode.ElideRight, w - 80)
            p.drawText(QRectF(48, y + 25, w - 80, 16), Qt.AlignLeft | Qt.AlignVCenter, elided_err)

            y += 58.0

        # If error is present, still show last values dimmed if present
        is_dimmed = bool(err_msg and (has_sections or has_hero))
        if is_dimmed:
            p.save()
            p.setOpacity(self._anim_opacity * 0.45)

        # Weather Hero Block
        hero = self._content.get("hero")
        if hero:
            h_icon = hero.get("icon", "cloud")
            try:
                theme.draw_weather_icon(p, QRectF(16, y + 4, 32, 32), h_icon)
            except Exception:
                pass

            p.setFont(self.f_wx_desc)
            p.setPen(COLOR_TEXT_PRIMARY)
            p.drawText(QRectF(56, y + 2, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, hero.get("desc", ""))

            p.setFont(self.f_sub)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(
                QRectF(56, y + 22, 120, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"Hissedilen {hero.get('feel_str', '')}",
            )

            p.setFont(self.f_wx_temp)
            p.setPen(COLOR_TEXT_PRIMARY)
            p.drawText(
                QRectF(w - 16 - 90, y + 2, 90, 36),
                Qt.AlignRight | Qt.AlignVCenter,
                hero.get("temp", "--°"),
            )

            y += 46.0
            p.setPen(QPen(COLOR_HAIRLINE, 1))
            p.drawLine(16, int(y), int(w - 16), int(y))
            y += 8.0

        # Sections & Rows
        sections = self._content.get("sections", [])
        for s_idx, sec in enumerate(sections):
            sec_title = sec.get("title")
            if sec_title:
                p.setFont(self.f_sec_title)
                p.setPen(COLOR_SECTION_TITLE)
                p.drawText(QRectF(16, y, w - 32, 16), Qt.AlignLeft | Qt.AlignVCenter, sec_title.upper())
                y += 20.0

            rows = sec.get("rows", [])
            for r_idx, r in enumerate(rows):
                rtype = r.get("type", "bar")
                if rtype == "bar":
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 140, 16), Qt.AlignLeft | Qt.AlignVCenter, r.get("label", ""))

                    p.setFont(self.f_val_bold)
                    val_col = r.get("col", COLOR_TEXT_PRIMARY)
                    p.setPen(val_col)
                    p.drawText(QRectF(w - 16 - 100, y, 100, 16), Qt.AlignRight | Qt.AlignVCenter, r.get("val", ""))

                    y += 22.0
                    bar_w = w - 32.0
                    bar_r = QRectF(16, y, bar_w, 4)
                    p.fillPath(rounded_path(bar_r, 2), COLOR_PROGRESS_TRACK)

                    pct = max(0.0, min(100.0, float(r.get("pct", 0.0))))
                    if pct > 0.0:
                        fill_w = max(4.0, bar_w * (pct / 100.0))
                        fill_r = QRectF(16, y, fill_w, 4)
                        p.fillPath(rounded_path(fill_r, 2), val_col)

                    y += 10.0
                    sub = r.get("sub")
                    if sub:
                        p.setFont(self.f_sub)
                        p.setPen(COLOR_TEXT_MUTED)
                        fm_sub = QFontMetricsF(self.f_sub)
                        elided_sub = fm_sub.elidedText(sub, Qt.TextElideMode.ElideRight, bar_w)
                        p.drawText(QRectF(16, y, bar_w, 14), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)
                        y += 18.0

                    y += 4.0

                elif rtype == "proc":
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 150, 20), Qt.AlignLeft | Qt.AlignVCenter, r.get("name", ""))

                    mb_val = float(r.get("mb", 0.0))
                    mb_str = f"{sources.fmt_tr(mb_val, 1)} MB"
                    p.setFont(self.f_val)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(w - 16 - 90, y, 90, 20), Qt.AlignRight | Qt.AlignVCenter, mb_str)
                    y += 24.0

                elif rtype == "fx":
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 90, 24), Qt.AlignLeft | Qt.AlignVCenter, r.get("label", ""))

                    val_str = r.get("val", "")
                    chg_str = r.get("chg", "")
                    chg_col = r.get("chg_col", COLOR_TEXT_PRIMARY)

                    p.setFont(self.f_val_bold)
                    fm_v = QFontMetricsF(self.f_val_bold)
                    cw = fm_v.horizontalAdvance(chg_str)
                    vw = fm_v.horizontalAdvance(val_str)

                    p.setPen(chg_col)
                    p.drawText(QRectF(w - 16 - cw, y, cw, 24), Qt.AlignRight | Qt.AlignVCenter, chg_str)

                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(w - 16 - cw - 8 - vw, y, vw, 24), Qt.AlignRight | Qt.AlignVCenter, val_str)
                    y += 28.0

                elif rtype == "wx_detail":
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 140, 20), Qt.AlignLeft | Qt.AlignVCenter, r.get("label", ""))

                    val_str = r.get("val", "")
                    p.setFont(self.f_val_bold)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(w - 16 - 110, y, 110, 20), Qt.AlignRight | Qt.AlignVCenter, val_str)
                    y += 24.0

                # 1px hairline between rows in a section
                if r_idx < len(rows) - 1:
                    p.setPen(QPen(COLOR_HAIRLINE, 1))
                    p.drawLine(16, int(y - 2), int(w - 16), int(y - 2))

            # 1px hairline between sections
            if s_idx < len(sections) - 1:
                p.setPen(QPen(COLOR_HAIRLINE, 1))
                p.drawLine(16, int(y + 2), int(w - 16), int(y + 2))
                y += 8.0

        if is_dimmed:
            p.restore()

        # 6. Footer Line & Refresh Button
        y_sep = h - 34.0
        p.setPen(QPen(COLOR_HAIRLINE, 1))
        p.drawLine(16, int(y_sep), int(w - 16), int(y_sep))

        # Footer Left Note
        footer_note = self._content.get("footer_note", "")
        p.setFont(self.f_footer)
        p.setPen(COLOR_TEXT_MUTED)
        fm_ft = QFontMetricsF(self.f_footer)
        note_w = w - 32.0 - 74.0
        elided_note = fm_ft.elidedText(footer_note, Qt.TextElideMode.ElideRight, note_w)
        p.drawText(QRectF(16, y_sep, note_w, 34), Qt.AlignLeft | Qt.AlignVCenter, elided_note)

        # Footer Right "Yenile" Pill Button
        self._refresh_rect = QRectF(w - 16.0 - 66.0, h - 28.0, 66.0, 22.0)
        btn_r = self._refresh_rect
        btn_path = rounded_path(btn_r, 11)

        if self._refresh_pressed:
            btn_bg = COLOR_REFRESH_BG_PRESS
        elif self._refresh_hovered:
            btn_bg = COLOR_REFRESH_BG_HOVER
        else:
            btn_bg = COLOR_REFRESH_BG

        p.fillPath(btn_path, btn_bg)
        p.setPen(QPen(COLOR_REFRESH_BORDER, 1))
        p.drawPath(btn_path)

        # Refresh Spinner / Arrow Icon
        icon_box = QRectF(btn_r.x() + 8.0, btn_r.y() + 5.0, 12.0, 12.0)
        draw_refresh_icon(p, icon_box, angle=self._spin_angle)

        # Refresh Button Label
        p.setFont(self.f_btn)
        p.setPen(COLOR_REFRESH_TXT)
        p.drawText(
            QRectF(btn_r.x() + 24.0, btn_r.y(), btn_r.width() - 28.0, btn_r.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Yenile",
        )
