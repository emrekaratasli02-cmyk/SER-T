"""Modern animated acrylic glass popover window for the Şerit dock.

Provides rich flyout cards for Claude usage, system telemetry, weather,
and financial markets with zero-lag QVariantAnimation transitions, tabular numerals,
and bulletproof K4 focus-loss toggle coordination.
"""

import datetime as dt
import math
from pathlib import Path
import sys
import time
from typing import Optional, Tuple, Union

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
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

# Safe module imports
try:
    import sources
    import winapi
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    import sources
    import winapi

# Design tokens & color constants
WIDTH: int = 260
CORNER_RADIUS: float = 14.0

COLOR_BG = QColor(18, 22, 30, 235)
COLOR_TEXT_PRIMARY = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY = QColor(255, 255, 255, 175)
COLOR_TEXT_MUTED = QColor(255, 255, 255, 140)

COLOR_CLAUDE_S = QColor("#F08A5D")
COLOR_CLAUDE_W = QColor("#F6B38F")
COLOR_CLAUDE_OPUS = QColor("#E09F7D")

COLOR_CPU = QColor("#60B5FF")
COLOR_RAM = QColor("#B49CFF")
COLOR_DISK = QColor("#86EFAC")

COLOR_ALERT_WARN = QColor("#FFC45C")
COLOR_ALERT_CRIT = QColor("#FF6060")

COLOR_FX_UP = QColor("#78DC96")
COLOR_FX_DOWN = QColor("#FF6E6E")
COLOR_FX_FLAT = QColor(255, 255, 255, 160)

COLOR_BADGE_CLAUDE_BG = QColor(240, 138, 93, 56)
COLOR_BADGE_CLAUDE_TXT = QColor("#FFB08A")
COLOR_BADGE_STALE_BG = QColor(245, 158, 11, 55)
COLOR_BADGE_STALE_TXT = QColor("#FCD34D")
COLOR_BADGE_ERR_BG = QColor(239, 68, 68, 55)
COLOR_BADGE_ERR_TXT = QColor("#FCA5A5")


def make_font(
    size_px: int,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
) -> QFont:
    """Create a Segoe UI Variable Text font with anti-aliasing and optional tabular figures."""
    f = QFont("Segoe UI Variable Text")
    f.setPixelSize(size_px)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag.fromString("tnum"), 1)
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
    """Helper to create a rounded rectangle QPainterPath."""
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


def draw_weather_icon(p: QPainter, r: QRectF, icon: str) -> None:
    """Draw a vector weather icon inside rect r."""
    cx, cy = r.center().x(), r.center().y()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    def draw_cloud(
        base_x: float,
        base_y: float,
        w: float = 16,
        h: float = 10,
        col: QColor = QColor(230, 235, 245),
    ) -> None:
        left = base_x - w / 2
        base_h = h * 0.62
        base = QPainterPath()
        base.addRoundedRect(QRectF(left, base_y, w, base_h), base_h / 2, base_h / 2)
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
        p.setBrush(QColor("#fbbf24"))
        p.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))
        pen = QPen(QColor("#fbbf24"), 1.6, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        for i in range(8):
            ang = i * math.pi / 4
            p.drawLine(
                QPointF(cx + 7 * math.cos(ang), cy + 7 * math.sin(ang)),
                QPointF(cx + 9.5 * math.cos(ang), cy + 9.5 * math.sin(ang)),
            )
    elif icon == "partly":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#fbbf24"))
        p.drawEllipse(QRectF(cx, cy - 7, 8, 8))
        draw_cloud(cx - 2, cy - 2, 16, 10)
    elif icon in ("rain", "drizzle"):
        draw_cloud(cx, cy - 5, 16, 10)
        p.setPen(QPen(QColor("#60a5fa"), 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 4, cy + 5), QPointF(cx - 5, cy + 9))
        p.drawLine(QPointF(cx, cy + 5), QPointF(cx - 1, cy + 9))
        p.drawLine(QPointF(cx + 4, cy + 5), QPointF(cx + 3, cy + 9))
    elif icon == "snow":
        draw_cloud(cx, cy - 5, 16, 10)
        p.setPen(QPen(QColor("#e0f2fe"), 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawPoint(QPointF(cx - 4, cy + 7))
        p.drawPoint(QPointF(cx, cy + 6))
        p.drawPoint(QPointF(cx + 4, cy + 7))
    elif icon == "storm":
        draw_cloud(cx, cy - 5, 16, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#facc15"))
        poly = QPainterPath()
        poly.moveTo(cx - 1, cy + 3)
        poly.lineTo(cx + 3, cy + 3)
        poly.lineTo(cx, cy + 7)
        poly.lineTo(cx + 4, cy + 7)
        poly.lineTo(cx - 3, cy + 13)
        poly.lineTo(cx - 1, cy + 8)
        poly.lineTo(cx - 3, cy + 8)
        poly.closeSubpath()
        p.drawPath(poly)
    elif icon == "fog":
        draw_cloud(cx, cy - 5, 15, 9)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 7, cy + 6), QPointF(cx + 7, cy + 6))
        p.drawLine(QPointF(cx - 5, cy + 9), QPointF(cx + 5, cy + 9))
    else:
        draw_cloud(cx, cy - 3, 17, 11)

    p.restore()


# Content builders for 'claude', 'sys', 'wx', 'fx'
def build_claude_content(data: dict) -> dict:
    """Build standardized popover content dictionary for Claude quota."""
    raw_source = data.get("source", "Anthropic · Claude Code")
    # Compact common source label for high legibility
    source = raw_source.replace(" · Claude Code girişi", " · Claude Code")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    if err:
        return {
            "kind": "claude",
            "title": "Claude",
            "badge": "Hata",
            "badge_bg": COLOR_BADGE_ERR_BG,
            "badge_color": COLOR_BADGE_ERR_TXT,
            "stale": False,
            "error": str(err),
            "rows": [],
            "source_line": f"Kaynak: {source} · Hata",
        }

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

    rows = [
        {
            "type": "bar",
            "label": "Oturum",
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
                rows.append({
                    "type": "bar",
                    "label": "Opus (7 gün)",
                    "val": f"%{o_val:.0f}",
                    "pct": o_val,
                    "col": get_bar_color(o_val, COLOR_CLAUDE_OPUS),
                    "sub": "",
                })
        except (ValueError, TypeError):
            pass

    src_suffix = " (Bayat)" if stale else ""
    return {
        "kind": "claude",
        "title": "Claude",
        "badge": plan,
        "badge_bg": COLOR_BADGE_CLAUDE_BG,
        "badge_color": COLOR_BADGE_CLAUDE_TXT,
        "stale": stale,
        "error": None,
        "rows": rows,
        "source_line": f"Kaynak: {source} · {t_str}{src_suffix}",
    }


def build_sys_content(data: dict) -> dict:
    """Build standardized popover content dictionary for system telemetry."""
    source = data.get("source", "Bu bilgisayar (psutil)")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    if err:
        return {
            "kind": "sys",
            "title": "Sistem",
            "badge": "Hata",
            "badge_bg": COLOR_BADGE_ERR_BG,
            "badge_color": COLOR_BADGE_ERR_TXT,
            "stale": False,
            "error": str(err),
            "rows": [],
            "source_line": f"Kaynak: {source} · Hata",
        }

    cpu_val = float(data.get("cpu", 0.0))
    ram_val = float(data.get("ram", 0.0))
    ram_used = float(data.get("ram_used_gb", 0.0))
    ram_total = float(data.get("ram_total_gb", 0.0))

    ram_sub = f"{ram_used:.1f} GB / {ram_total:.1f} GB kullanılan" if ram_total > 0 else ""

    rows = [
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
            "label": "RAM",
            "val": f"%{ram_val:.0f}",
            "pct": ram_val,
            "col": get_bar_color(ram_val, COLOR_RAM),
            "sub": ram_sub,
        },
    ]

    if "disk_c" in data:
        disk_val = float(data["disk_c"])
        rows.append({
            "type": "bar",
            "label": "Disk (C:)",
            "val": f"%{disk_val:.0f}",
            "pct": disk_val,
            "col": get_bar_color(disk_val, COLOR_DISK),
            "sub": "",
        })

    src_suffix = " (Bayat veri)" if stale else ""
    return {
        "kind": "sys",
        "title": "Sistem",
        "badge": "Canlı" if not stale else None,
        "badge_bg": QColor(255, 255, 255, 20),
        "badge_color": QColor(255, 255, 255, 200),
        "stale": stale,
        "error": None,
        "rows": rows,
        "source_line": f"Kaynak: {source} · {t_str}{src_suffix}",
    }


def build_wx_content(data: dict, city: str = "Aksaray") -> dict:
    """Build standardized popover content dictionary for weather."""
    source = data.get("source", "open-meteo.com")
    t_str = format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    resolved_city = data.get("city", city)

    if err:
        return {
            "kind": "wx",
            "title": f"Hava Durumu · {resolved_city}",
            "badge": "Hata",
            "badge_bg": COLOR_BADGE_ERR_BG,
            "badge_color": COLOR_BADGE_ERR_TXT,
            "stale": False,
            "error": str(err),
            "rows": [],
            "source_line": f"Kaynak: {source} · Hata",
        }

    temp = data.get("temp")
    temp_str = f"{temp:.1f}°" if temp is not None else "--°"
    feel = data.get("feel")
    feel_str = f"{feel:.1f}°" if feel is not None else "--°"
    desc = data.get("desc", "Bilinmiyor")
    icon = data.get("icon", "cloud")
    min_t = data.get("min")
    max_t = data.get("max")
    wind = data.get("wind")

    sub1 = f"Hissedilen {feel_str}"
    sub2 = (
        f"En düşük {min_t:.1f}° · En yüksek {max_t:.1f}°"
        if (min_t is not None and max_t is not None)
        else None
    )
    sub3 = f"Rüzgar: {wind:.1f} km/sa" if wind is not None else None

    rows = [
        {
            "type": "wx",
            "icon": icon,
            "desc": desc,
            "temp": temp_str,
            "sub1": sub1,
            "sub2": sub2,
            "sub3": sub3,
        }
    ]

    src_suffix = " (Bayat veri)" if stale else ""
    return {
        "kind": "wx",
        "title": f"Hava Durumu · {resolved_city}",
        "badge": None,
        "stale": stale,
        "error": None,
        "rows": rows,
        "source_line": f"Kaynak: {source} · {t_str}{src_suffix}",
    }


def build_fx_content(data: dict) -> dict:
    """Build standardized popover content dictionary for foreign exchange & gold."""
    source = data.get("source", "finans.truncgil.com")
    t_str = data.get("updated") or format_source_time(data.get("fetched_at"))
    stale = bool(data.get("stale", False))
    err = data.get("err")

    if err:
        return {
            "kind": "fx",
            "title": "Piyasa (satış)",
            "badge": "Hata",
            "badge_bg": COLOR_BADGE_ERR_BG,
            "badge_color": COLOR_BADGE_ERR_TXT,
            "stale": False,
            "error": str(err),
            "rows": [],
            "source_line": f"Kaynak: {source} · Hata",
        }

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

    rows = [
        {
            "type": "fx",
            "label": "Dolar",
            "val": f"{sources.fmt_tr(usd, 2)} ₺",
            "chg": u_chg_str,
            "val_col": u_col,
        },
        {
            "type": "fx",
            "label": "Euro",
            "val": f"{sources.fmt_tr(eur, 2)} ₺",
            "chg": e_chg_str,
            "val_col": e_col,
        },
        {
            "type": "fx",
            "label": "Gram altın",
            "val": f"{sources.fmt_tr(gold, 0)} ₺",
            "chg": g_chg_str,
            "val_col": g_col,
        },
    ]

    src_suffix = " (Bayat veri)" if stale else ""
    return {
        "kind": "fx",
        "title": "Piyasa (satış)",
        "badge": None,
        "stale": stale,
        "error": None,
        "rows": rows,
        "source_line": f"Kaynak: {source} · {t_str}{src_suffix}",
    }


def build_content(kind: str, data: dict, **kwargs) -> dict:
    """Dispatcher to build content for any supported popover kind."""
    if kind == "claude":
        return build_claude_content(data)
    elif kind == "sys":
        return build_sys_content(data)
    elif kind == "wx":
        city = kwargs.get("city", "Aksaray")
        return build_wx_content(data, city=city)
    elif kind == "fx":
        return build_fx_content(data)
    else:
        # Fallback generic view
        return {
            "kind": kind,
            "title": str(kind).capitalize(),
            "badge": None,
            "stale": False,
            "error": None,
            "rows": [],
            "source_line": f"Kaynak: {data.get('source', 'Bilinmiyor')}",
        }


class Popover(QWidget):
    """Frameless acrylic popover window positioned dynamically above dock chips.

    Supports micro-interaction animations (open/close easing curves),
    high-DPI tabular typography, and fixes K4 focus-loss reopen glitch.
    """

    WIDTH: int = WIDTH
    RADIUS: float = CORNER_RADIUS

    def __init__(self, parent_dock: Optional[QWidget] = None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.parent_dock = parent_dock

        # Content state
        self._kind: str = ""
        self._content: dict = {}
        self._anchor_rect_global: Optional[QRectF] = None

        # K4 focus tracking and coordination
        self._last_close_time: float = 0.0
        self._last_close_kind: str = ""
        self._is_closing: bool = False

        # Fallback deactivation timer for anchor clicks
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Micro-interaction animation state
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0
        self._anim_scale: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Fonts
        self.f_title = make_font(14, QFont.Weight.DemiBold)
        self.f_badge = make_font(10, QFont.Weight.DemiBold)
        self.f_label = make_font(12, QFont.Weight.Normal)
        self.f_val = make_font(12, QFont.Weight.DemiBold, tabular=True)
        self.f_val_bold = make_font(13, QFont.Weight.Bold, tabular=True)
        self.f_sub = make_font(11, QFont.Weight.Normal)
        self.f_source = make_font(11, QFont.Weight.Normal)
        self.f_wx_desc = make_font(14, QFont.Weight.DemiBold)
        self.f_wx_temp = make_font(22, QFont.Weight.Bold, tabular=True)

        self.resize(self.WIDTH, 180)

    # Public API
    def is_open(self, kind: Optional[str] = None) -> bool:
        """Return True if popover is open (visible and not in process of closing)."""
        if not self.isVisible() or self._is_closing:
            return False
        if kind is not None:
            return self._kind == kind
        return True

    def recently_closed(self, kind: Optional[str] = None, threshold_ms: float = 250.0) -> bool:
        """Check if this popover kind was closed within threshold_ms to prevent K4 reopen."""
        if self._last_close_time <= 0.0:
            return False
        if kind is not None and self._last_close_kind != kind:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def show_for(
        self,
        kind: str,
        anchor_rect_global: Union[QRectF, QRect],
        content_dict: dict,
        **kwargs,
    ) -> None:
        """Populate content, position centered above anchor, apply acrylic blur, and animate in."""
        self._kind = kind
        self._anchor_rect_global = QRectF(anchor_rect_global) if anchor_rect_global is not None else None
        self._content = build_content(kind, content_dict, **kwargs)

        # Compute dynamic height and resize
        h = self.compute_height(self._content)
        self.resize(self.WIDTH, h)

        # Compute global position: centered above anchor with 10 px gap, clamped to screen
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
                    # If cramped above, position below anchor if possible
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

    def compute_height(self, content: dict) -> int:
        """Calculate dynamic content height in logical pixels."""
        # Top padding (14) + Header height (18) + Header bottom gap (12) = 44
        h = 44

        if content.get("error"):
            # Error card box: 54 px + gap 12
            h += 54 + 12
        else:
            for r in content.get("rows", []):
                rtype = r.get("type", "bar")
                if rtype == "bar":
                    # Label/val (16) + gap (6) + bar (5) = 27
                    h += 27
                    if r.get("sub"):
                        # gap (5) + sub text (14) = 19
                        h += 19
                    # row bottom margin
                    h += 10
                elif rtype == "fx":
                    # fx row height 24 px
                    h += 24
                elif rtype == "wx":
                    # Weather icon + temp block (30) + sub1 (18) + margins (8)
                    h += 30 + 18 + 8
                    if r.get("sub2"):
                        h += 18
                    if r.get("sub3"):
                        h += 18

        # Separator (1) + gap (8) + source line (16) + bottom padding (12) = 37
        h += 37
        return int(h)

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

        # Force full opacity and resting transforms for offscreen snapshot
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
                        # Record close timestamp so recently_closed() works, but do not
                        # auto-close immediately; allow dock's mouse release handler to toggle.
                        self._last_close_time = time.monotonic()
                        self._last_close_kind = self._kind
                        self._anchor_timer.start(300)
                        super().changeEvent(event)
                        return
                # Clicking anywhere else outside
                self.hide_animated()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        self._last_close_kind = self._kind
        super().hideEvent(event)

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

        # 3. Dual-stroke boundary & specular rim
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
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

        # 4. Header title & badges
        title = self._content.get("title", "")
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_t = QFontMetricsF(self.f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(16, 14, title_w + 4, 20), Qt.AlignLeft | Qt.AlignVCenter, title)

        cur_x = 16 + title_w + 8

        # Plan / status badge
        badge = self._content.get("badge")
        if badge:
            p.setFont(self.f_badge)
            fm_b = QFontMetricsF(self.f_badge)
            bw = fm_b.horizontalAdvance(badge) + 12
            badge_r = QRectF(cur_x, 15, bw, 18)
            bpath = rounded_path(badge_r, 5)
            badge_bg = self._content.get("badge_bg", COLOR_BADGE_CLAUDE_BG)
            badge_txt = self._content.get("badge_color", COLOR_BADGE_CLAUDE_TXT)
            p.fillPath(bpath, badge_bg)
            p.setPen(badge_txt)
            p.drawText(badge_r, Qt.AlignCenter, badge)
            cur_x += bw + 6

        # Stale indicator badge
        if self._content.get("stale"):
            p.setFont(self.f_badge)
            fm_s = QFontMetricsF(self.f_badge)
            sw = fm_s.horizontalAdvance("Bayat") + 10
            stale_r = QRectF(cur_x, 15, sw, 18)
            p.fillPath(rounded_path(stale_r, 5), COLOR_BADGE_STALE_BG)
            p.setPen(COLOR_BADGE_STALE_TXT)
            p.drawText(stale_r, Qt.AlignCenter, "Bayat")

        # 5. Content Rows or Error Banner
        y = 44.0
        err_msg = self._content.get("error")
        if err_msg:
            err_box = QRectF(16, y, w - 32, 54)
            p.fillPath(rounded_path(err_box, 8), QColor(239, 68, 68, 22))
            p.setPen(QPen(QColor(239, 68, 68, 75), 1))
            p.drawPath(rounded_path(err_box, 8))

            p.setFont(self.f_val_bold)
            p.setPen(QColor("#FCA5A5"))
            p.drawText(QRectF(26, y + 8, w - 52, 18), Qt.AlignLeft | Qt.AlignVCenter, "✕ Veri Alınamadı")

            p.setFont(self.f_sub)
            p.setPen(COLOR_TEXT_SECONDARY)
            fm_err = QFontMetricsF(self.f_sub)
            elided_err = fm_err.elidedText(str(err_msg), Qt.TextElideMode.ElideRight, w - 52)
            p.drawText(QRectF(26, y + 28, w - 52, 16), Qt.AlignLeft | Qt.AlignVCenter, elided_err)
        else:
            for r in self._content.get("rows", []):
                rtype = r.get("type", "bar")
                if rtype == "bar":
                    # Line 1: Label (left) + Percentage/Value (right)
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 120, 16), Qt.AlignLeft | Qt.AlignVCenter, r.get("label", ""))

                    p.setFont(self.f_val_bold)
                    val_col = r.get("col", COLOR_TEXT_PRIMARY)
                    p.setPen(val_col)
                    p.drawText(QRectF(w - 16 - 80, y, 80, 16), Qt.AlignRight | Qt.AlignVCenter, r.get("val", ""))

                    y += 20.0
                    # Line 2: Full-width progress bar
                    bar_w = w - 32.0
                    bar_r = QRectF(16, y, bar_w, 5)
                    p.fillPath(rounded_path(bar_r, 2.5), QColor(255, 255, 255, 25))

                    pct = max(0.0, min(100.0, float(r.get("pct", 0.0))))
                    if pct > 0.0:
                        fill_w = max(4.0, bar_w * (pct / 100.0))
                        fill_r = QRectF(16, y, fill_w, 5)
                        p.fillPath(rounded_path(fill_r, 2.5), val_col)

                    y += 11.0
                    # Line 3: Reset countdown / subtext if present
                    sub = r.get("sub")
                    if sub:
                        p.setFont(self.f_sub)
                        p.setPen(COLOR_TEXT_MUTED)
                        fm_sub = QFontMetricsF(self.f_sub)
                        elided_sub = fm_sub.elidedText(sub, Qt.TextElideMode.ElideRight, bar_w)
                        p.drawText(QRectF(16, y, bar_w, 14), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)
                        y += 18.0

                    y += 8.0

                elif rtype == "fx":
                    # Currency/asset row
                    p.setFont(self.f_label)
                    p.setPen(COLOR_TEXT_SECONDARY)
                    p.drawText(QRectF(16, y, 90, 20), Qt.AlignLeft | Qt.AlignVCenter, r.get("label", ""))

                    val_str = r.get("val", "")
                    chg_str = r.get("chg", "")
                    val_col = r.get("val_col", COLOR_TEXT_PRIMARY)

                    p.setFont(self.f_val_bold)
                    fm_v = QFontMetricsF(self.f_val_bold)
                    cw = fm_v.horizontalAdvance(chg_str)
                    vw = fm_v.horizontalAdvance(val_str)

                    # Draw change percentage
                    p.setPen(val_col)
                    p.drawText(QRectF(w - 16 - cw, y, cw, 20), Qt.AlignRight | Qt.AlignVCenter, chg_str)

                    # Draw price value
                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(w - 16 - cw - 8 - vw, y, vw, 20), Qt.AlignRight | Qt.AlignVCenter, val_str)

                    y += 24.0

                elif rtype == "wx":
                    # Weather condition block
                    icon = r.get("icon", "cloud")
                    draw_weather_icon(p, QRectF(16, y, 26, 26), icon)

                    desc = r.get("desc", "")
                    p.setFont(self.f_wx_desc)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(48, y, 110, 26), Qt.AlignLeft | Qt.AlignVCenter, desc)

                    temp_str = r.get("temp", "--°")
                    p.setFont(self.f_wx_temp)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    p.drawText(QRectF(w - 16 - 80, y, 80, 26), Qt.AlignRight | Qt.AlignVCenter, temp_str)

                    y += 32.0

                    p.setFont(self.f_sub)
                    p.setPen(COLOR_TEXT_MUTED)
                    fm_sub = QFontMetricsF(self.f_sub)

                    sub1 = r.get("sub1")
                    if sub1:
                        elided1 = fm_sub.elidedText(sub1, Qt.TextElideMode.ElideRight, w - 32)
                        p.drawText(QRectF(16, y, w - 32, 14), Qt.AlignLeft | Qt.AlignVCenter, elided1)
                        y += 18.0

                    sub2 = r.get("sub2")
                    if sub2:
                        elided2 = fm_sub.elidedText(sub2, Qt.TextElideMode.ElideRight, w - 32)
                        p.drawText(QRectF(16, y, w - 32, 14), Qt.AlignLeft | Qt.AlignVCenter, elided2)
                        y += 18.0

                    sub3 = r.get("sub3")
                    if sub3:
                        elided3 = fm_sub.elidedText(sub3, Qt.TextElideMode.ElideRight, w - 32)
                        p.drawText(QRectF(16, y, w - 32, 14), Qt.AlignLeft | Qt.AlignVCenter, elided3)
                        y += 18.0

                    y += 8.0

        # 6. Separator line & Source line
        y_sep = h - 28.0
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawLine(16, int(y_sep), int(w - 16), int(y_sep))

        source_line = self._content.get("source_line", "")
        p.setFont(self.f_source)
        p.setPen(COLOR_TEXT_MUTED)
        fm_src = QFontMetricsF(self.f_source)
        elided_src = fm_src.elidedText(source_line, Qt.TextElideMode.ElideRight, w - 32)
        p.drawText(QRectF(16, y_sep + 6, w - 32, 16), Qt.AlignLeft | Qt.AlignVCenter, elided_src)
