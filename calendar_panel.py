"""Wide month-view calendar panel for the Şerit dock.

Provides an acrylic high-DPI popover card displaying:
- A full 6x7 monthly calendar view with month navigation and 'Bugün' action
- Category dots under days with scheduled events
- Selected date agenda with styled event cards and direct Google links
- Upcoming events quick-select agenda
- Turkish public holidays and computed Claude usage markers
- Legend, sync status, and interactive Yenile action
"""

from __future__ import annotations

import calendar
import datetime as dt
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import unicodedata

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Serit imports
try:
    import sources
    import winapi
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    import sources
    import winapi

try:
    from popover_v2 import draw_cal_icon, draw_refresh_icon, make_font, rounded_path
except ImportError:
    def make_font(
        size_px: int,
        weight: QFont.Weight = QFont.Weight.Normal,
        tabular: bool = False,
        letter_spacing: float = 0.0,
    ) -> QFont:
        font = QFont("Segoe UI Variable Display", int(size_px))
        if not font.exactMatch():
            font = QFont("Segoe UI", int(size_px))
        font.setWeight(weight)
        if tabular:
            font.setStyleStrategy(QFont.PreferAntialias)
        if letter_spacing != 0.0:
            font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
        return font

    def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(rect, radius, radius)
        return p

    def draw_cal_icon(p: QPainter, rect: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(rect.x() + 0.5, rect.y() + 1.5, rect.width() - 1.0, rect.height() - 2.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(242, 244, 248))
        p.drawRoundedRect(body, 3.5, 3.5)
        p.setBrush(QColor("#F97316"))
        top = QPainterPath()
        top.addRoundedRect(QRectF(body.x(), body.y(), body.width(), 5.0), 3.5, 3.5)
        top.addRect(QRectF(body.x(), body.y() + 2.5, body.width(), 2.5))
        p.drawPath(top)
        p.restore()

    def draw_refresh_icon(p: QPainter, rect: QRectF, angle: float = 0.0) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = rect.center().x(), rect.center().y()
        p.translate(cx, cy)
        p.rotate(angle)
        r = min(rect.width(), rect.height()) * 0.40
        pen = QPen(QColor(255, 255, 255, 245), 1.3, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        arc_box = QRectF(-r, -r, 2 * r, 2 * r)
        p.drawArc(arc_box, int(35 * 16), int(285 * 16))
        p.restore()

# Dimensions & Geometry
PANEL_WIDTH: int = 620
PANEL_HEIGHT: int = 440
CORNER_RADIUS: float = 14.0

# Base Material & Typography Colors
COLOR_BG: QColor = QColor(20, 21, 25, 248)
COLOR_BORDER: QColor = QColor(255, 255, 255, 20)  # rgba(255, 255, 255, 0.08)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 22)
COLOR_DIVIDER: QColor = QColor(255, 255, 255, 32)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(225, 228, 235, 240)
COLOR_TEXT_MUTED: QColor = QColor(148, 154, 166, 220)
COLOR_SECTION_TITLE: QColor = QColor(135, 140, 152, 230)

# Category Semantic Accent Colors
COLOR_CAT_GCAL: QColor = QColor("#0A84FF")
COLOR_CAT_TAX: QColor = QColor("#FF9F0A")
COLOR_CAT_HOLIDAY: QColor = QColor("#FF453A")
COLOR_CAT_CLAUDE: QColor = QColor("#D97757")

CATEGORY_COLORS: Dict[str, QColor] = {
    "Google Takvim": COLOR_CAT_GCAL,
    "Vergi/ödeme": COLOR_CAT_TAX,
    "Resmi tatil": COLOR_CAT_HOLIDAY,
    "Claude": COLOR_CAT_CLAUDE,
}

# Day Highlights & Interactions
COLOR_TODAY_CIRCLE: QColor = QColor("#FF453A")
COLOR_SELECTED_RING: QColor = QColor(255, 255, 255, 220)
COLOR_HOVER_CELL: QColor = QColor(255, 255, 255, 18)

# Cards & Badges
COLOR_CARD_BG: QColor = QColor(255, 255, 255, 13)       # rgba(255, 255, 255, 0.05)
COLOR_CARD_HOVER: QColor = QColor(255, 255, 255, 23)    # rgba(255, 255, 255, 0.09)
COLOR_CARD_BORDER: QColor = QColor(255, 255, 255, 15)

COLOR_BADGE_BG: QColor = QColor(255, 255, 255, 22)
COLOR_BADGE_TXT: QColor = QColor(200, 205, 215, 235)
COLOR_STALE_TXT: QColor = QColor("#FFC45C")

# Refresh Button Colors
COLOR_REFRESH_BG: QColor = QColor(255, 255, 255, 22)
COLOR_REFRESH_BG_HOVER: QColor = QColor(255, 255, 255, 38)
COLOR_REFRESH_BG_PRESS: QColor = QColor(255, 255, 255, 55)
COLOR_REFRESH_BORDER: QColor = QColor(255, 255, 255, 24)
COLOR_REFRESH_TXT: QColor = QColor(255, 255, 255, 245)

# Turkish Localization Tables
TR_MONTHS_SHORT: Dict[int, str] = {
    1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
    7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara",
}

TR_MONTHS_FULL: Dict[int, str] = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

TR_DAYS_SHORT: List[str] = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

TR_DAYS_FULL: Dict[int, str] = {
    0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
    4: "Cuma", 5: "Cumartesi", 6: "Pazar",
}

# Turkish Public Holidays (Source: date.nager.at)
# Republic of Turkey official public holidays and half-day eves (arife).
TURKISH_HOLIDAYS_TABLE: Dict[dt.date, List[Tuple[str, bool]]] = {
    # 2026
    dt.date(2026, 1, 1): [("Yılbaşı", False)],
    dt.date(2026, 3, 19): [("Ramazan Bayramı Arifesi", True)],
    dt.date(2026, 3, 20): [("Ramazan Bayramı 1. Gün", False)],
    dt.date(2026, 3, 21): [("Ramazan Bayramı 2. Gün", False)],
    dt.date(2026, 3, 22): [("Ramazan Bayramı 3. Gün", False)],
    dt.date(2026, 4, 23): [("Ulusal Egemenlik ve Çocuk Bayramı", False)],
    dt.date(2026, 5, 1): [("Emek ve Dayanışma Günü", False)],
    dt.date(2026, 5, 19): [("Atatürk'ü Anma, Gençlik ve Spor Bayramı", False)],
    dt.date(2026, 5, 26): [("Kurban Bayramı Arifesi", True)],
    dt.date(2026, 5, 27): [("Kurban Bayramı 1. Gün", False)],
    dt.date(2026, 5, 28): [("Kurban Bayramı 2. Gün", False)],
    dt.date(2026, 5, 29): [("Kurban Bayramı 3. Gün", False)],
    dt.date(2026, 5, 30): [("Kurban Bayramı 4. Gün", False)],
    dt.date(2026, 7, 15): [("Demokrasi ve Millî Birlik Günü", False)],
    dt.date(2026, 8, 30): [("Zafer Bayramı", False)],
    dt.date(2026, 10, 28): [("Cumhuriyet Bayramı Arifesi", True)],
    dt.date(2026, 10, 29): [("Cumhuriyet Bayramı", False)],
    # 2027
    dt.date(2027, 1, 1): [("Yılbaşı", False)],
    dt.date(2027, 3, 9): [("Ramazan Bayramı Arifesi (tahmini)", True)],
    dt.date(2027, 3, 10): [("Ramazan Bayramı 1. Gün (tahmini)", False)],
    dt.date(2027, 3, 11): [("Ramazan Bayramı 2. Gün (tahmini)", False)],
    dt.date(2027, 3, 12): [("Ramazan Bayramı 3. Gün (tahmini)", False)],
    dt.date(2027, 4, 23): [("Ulusal Egemenlik ve Çocuk Bayramı", False)],
    dt.date(2027, 5, 1): [("Emek ve Dayanışma Günü", False)],
    dt.date(2027, 5, 15): [("Kurban Bayramı Arifesi (tahmini)", True)],
    dt.date(2027, 5, 16): [("Kurban Bayramı 1. Gün (tahmini)", False)],
    dt.date(2027, 5, 17): [("Kurban Bayramı 2. Gün (tahmini)", False)],
    dt.date(2027, 5, 18): [("Kurban Bayramı 3. Gün (tahmini)", False)],
    dt.date(2027, 5, 19): [
        ("Atatürk'ü Anma, Gençlik ve Spor Bayramı", False),
        ("Kurban Bayramı 4. Gün (tahmini)", False),
    ],
    dt.date(2027, 7, 15): [("Demokrasi ve Millî Birlik Günü", False)],
    dt.date(2027, 8, 30): [("Zafer Bayramı", False)],
    dt.date(2027, 10, 28): [("Cumhuriyet Bayramı Arifesi", True)],
    dt.date(2027, 10, 29): [("Cumhuriyet Bayramı", False)],
}


def clean_title(raw_title: Any) -> str:
    """Strip leading decorative emojis/symbols, keeping Turkish text and words intact."""
    if not raw_title:
        return "(Başlıksız)"
    s = str(raw_title).strip()
    while s:
        ch = s[0]
        cat = unicodedata.category(ch)
        if cat in ("So", "Sk", "Sm", "Cn") or ord(ch) >= 0x2600:
            s = s[1:].strip()
        else:
            break
    s = s.strip()
    return s if s else "(Başlıksız)"


def get_holiday_events_for_date(d: dt.date) -> List[Dict[str, Any]]:
    """Return Turkish public holiday items for a specific date."""
    items = TURKISH_HOLIDAYS_TABLE.get(d)
    if not items:
        return []
    res = []
    for title, is_half in items:
        res.append({
            "title": title,
            "start": d,
            "end": d + dt.timedelta(days=1),
            "all_day": True,
            "link": "",
            "category": "Resmi tatil",
            "sub": "Yarım gün" if is_half else "Tüm gün",
            "half_day": is_half,
        })
    return res


def get_claude_markers_for_month(
    claude_data: Dict[str, Any],
    year: int,
    month: int,
) -> List[Dict[str, Any]]:
    """Compute Claude reset and renewal markers for the visible month."""
    if not isinstance(claude_data, dict):
        return []
    markers: List[Dict[str, Any]] = []

    # 1. Weekly reset marker
    week_reset = claude_data.get("week_reset")
    if isinstance(week_reset, str) and week_reset.strip():
        try:
            wr_dt = dt.datetime.fromisoformat(week_reset.strip())
            local_wr = wr_dt.astimezone(sources.LOCAL_TZ) if wr_dt.tzinfo else wr_dt.replace(tzinfo=sources.LOCAL_TZ)
            time_str = local_wr.strftime("%H:%M")
            target_dow = local_wr.weekday()
            _, days_in_month = calendar.monthrange(year, month)
            for day in range(1, days_in_month + 1):
                cur_date = dt.date(year, month, day)
                if cur_date.weekday() == target_dow:
                    markers.append({
                        "title": f"Claude haftalık sıfırlama {time_str}",
                        "start": dt.datetime.combine(cur_date, local_wr.time()).replace(tzinfo=sources.LOCAL_TZ),
                        "end": dt.datetime.combine(cur_date, local_wr.time()).replace(tzinfo=sources.LOCAL_TZ),
                        "all_day": False,
                        "link": "",
                        "category": "Claude",
                        "sub": time_str,
                    })
        except Exception as exc:
            sources.log_err("claude_marker_week", exc)

    # 2. Subscription renewal marker
    subscribed_at = claude_data.get("subscribed_at")
    if isinstance(subscribed_at, str) and subscribed_at.strip():
        try:
            sub_dt = dt.datetime.fromisoformat(subscribed_at.strip())
            local_sub = sub_dt.astimezone(sources.LOCAL_TZ) if sub_dt.tzinfo else sub_dt.replace(tzinfo=sources.LOCAL_TZ)
            sub_day = local_sub.day
            _, days_in_month = calendar.monthrange(year, month)
            clamped_day = min(sub_day, days_in_month)
            ren_date = dt.date(year, month, clamped_day)
            markers.append({
                "title": "Claude yenileme ≈",
                "start": ren_date,
                "end": ren_date + dt.timedelta(days=1),
                "all_day": True,
                "link": "",
                "category": "Claude",
                "sub": "Tüm gün",
            })
        except Exception as exc:
            sources.log_err("claude_marker_sub", exc)

    return markers


class CalendarPanel(QWidget):
    """Wide month-view calendar panel for the Şerit dock."""

    refresh_requested = Signal()

    WIDTH: int = PANEL_WIDTH
    HEIGHT: int = PANEL_HEIGHT
    RADIUS: float = CORNER_RADIUS

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Frameless tool window flags
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        # Internal state
        self._anchor_rect_global: Optional[QRectF] = None
        self._month_data: Dict[str, Any] = {}
        self._claude_data: Dict[str, Any] = {}

        now_local = dt.datetime.now(sources.LOCAL_TZ)
        self.today: dt.date = now_local.date()
        self.selected_date: dt.date = self.today
        self.view_year: int = self.today.year
        self.view_month: int = self.today.month

        # K4 focus coordination tracking
        self._last_close_time: float = 0.0
        self._is_closing: bool = False

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Animation state: 180ms OutCubic open, 150ms InQuad close
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0
        self._anim_scale: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Refresh spinner
        self._refresh_spinning: bool = False
        self._spin_angle: float = 0.0
        self._spin_anim = QVariantAnimation(self)
        self._spin_anim.setDuration(600)
        self._spin_anim.setStartValue(0.0)
        self._spin_anim.setEndValue(360.0)
        self._spin_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._spin_anim.valueChanged.connect(self._on_spin_value_changed)
        self._spin_anim.finished.connect(self._on_spin_finished)

        # Interactive states & hit regions
        self._hovered_cell_idx: int = -1
        self._hovered_btn: str = ""       # "prev", "next", "today", "close", "refresh"
        self._hovered_card_idx: int = -1
        self._hovered_upcoming_idx: int = -1
        self._refresh_pressed: bool = False

        # Fonts
        self.f_title = make_font(13, QFont.Weight.DemiBold)
        self.f_badge = make_font(10, QFont.Weight.DemiBold)
        self.f_nav_month = make_font(14, QFont.Weight.Bold)
        self.f_weekday = make_font(10, QFont.Weight.DemiBold)
        self.f_day_num = make_font(11, QFont.Weight.DemiBold, tabular=True)
        self.f_day_today = make_font(11, QFont.Weight.Bold, tabular=True)
        self.f_sec_title = make_font(9, QFont.Weight.Bold, letter_spacing=1.0)
        self.f_day_hdr = make_font(13, QFont.Weight.Bold)
        self.f_card_title = make_font(12, QFont.Weight.DemiBold)
        self.f_card_sub = make_font(11, QFont.Weight.Normal)
        self.f_up_date = make_font(10, QFont.Weight.DemiBold)
        self.f_up_title = make_font(11, QFont.Weight.Normal)
        self.f_footer = make_font(10, QFont.Weight.Normal)
        self.f_btn = make_font(10, QFont.Weight.DemiBold)

        # Layout Cache
        self._cache_valid: bool = False
        self._cached_cells: List[Dict[str, Any]] = []
        self._cached_selected_cards: List[Dict[str, Any]] = []
        self._cached_upcoming: List[Dict[str, Any]] = []
        self._cached_month_event_count: int = 0
        self._cached_selected_header_text: str = ""
        self._cached_footer_sync_text: str = ""
        self._cached_footer_stale: bool = False

        # Fixed Hit Rects
        self._rect_close = QRectF(self.WIDTH - 16.0 - 22.0, 8.0, 22.0, 22.0)
        self._rect_btn_prev = QRectF(216.0, 46.0, 22.0, 22.0)
        self._rect_btn_next = QRectF(242.0, 46.0, 22.0, 22.0)
        self._rect_btn_today = QRectF(268.0, 46.0, 42.0, 22.0)
        self._rect_btn_refresh = QRectF(self.WIDTH - 16.0 - 62.0, self.HEIGHT - 36.0 + 7.0, 62.0, 22.0)

        self.resize(self.WIDTH, self.HEIGHT)
        self._rebuild_cache()

    # Public API
    def is_open(self) -> bool:
        """Return True if panel is visible and not in close transition."""
        return bool(self.isVisible() and not self._is_closing)

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        """Check if panel closed within threshold_ms to prevent reopen bounce."""
        if self._last_close_time <= 0.0:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def show_for(
        self,
        anchor_global: Union[QRectF, QRect],
        month_data: Optional[Dict[str, Any]] = None,
        claude_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Position centered above anchor, apply acrylic blur-behind, and animate in."""
        try:
            self._anchor_rect_global = QRectF(anchor_global) if anchor_global is not None else None
            self._month_data = month_data if isinstance(month_data, dict) else {}
            self._claude_data = claude_data if isinstance(claude_data, dict) else {}

            now_local = dt.datetime.now(sources.LOCAL_TZ)
            self.today = now_local.date()
            if not hasattr(self, "selected_date") or self.selected_date is None:
                self.selected_date = self.today

            self._rebuild_cache()

            # Positioning above anchor (8px gap), clamped inside screen availableGeometry
            dpr = 1.25
            if self._anchor_rect_global is not None:
                anchor_cx = self._anchor_rect_global.center().x()
                target_x = int(anchor_cx - self.width() / 2.0)
                target_y = int(self._anchor_rect_global.top() - self.height() - 8)

                center_pt = self._anchor_rect_global.center().toPoint()
                screen = QGuiApplication.screenAt(center_pt)
                if screen is None:
                    screen = QGuiApplication.primaryScreen()

                if screen is not None:
                    geom = screen.availableGeometry()
                    dpr = screen.devicePixelRatio()
                    margin = 8
                    min_x = geom.left() + margin
                    max_x = geom.right() - self.width() - margin
                    if max_x >= min_x:
                        target_x = max(min_x, min(max_x, target_x))
                    else:
                        target_x = min_x

                    min_y = geom.top() + margin
                    max_y = geom.bottom() - self.height() - margin
                    if target_y < min_y:
                        below_y = int(self._anchor_rect_global.bottom() + 8)
                        if below_y + self.height() <= geom.bottom() - margin:
                            target_y = below_y
                        else:
                            target_y = min_y
                    elif target_y > max_y:
                        target_y = max_y

                self.move(target_x, target_y)

            # Acrylic blur-behind & rounded shape
            hwnd = int(self.winId())
            try:
                winapi.enable_acrylic(hwnd, 0x50181612)
                winapi.set_round_region(hwnd, self.width(), self.height(), int(self.RADIUS), dpr)
            except Exception:
                pass

            # Open animation: 180 ms OutCubic
            self._is_closing = False
            self._anim.stop()
            self._anim.setDuration(180)
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
        except Exception as exc:
            sources.log_err("calendar_show_for", exc)

    def hide_animated(self) -> None:
        """Trigger close transition: fade 1->0, slide 6px in 150ms InQuad, then hide."""
        if not self.isVisible() or self._is_closing:
            return

        self._is_closing = True
        self._last_close_time = time.monotonic()

        self._anim.stop()
        start_val = self._anim_progress
        duration = max(40, int(150 * start_val))

        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim.setStartValue(start_val)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def select_date(self, target_date: dt.date) -> None:
        """Change selected date and synchronize visible month if needed."""
        self.selected_date = target_date
        if self.view_year != target_date.year or self.view_month != target_date.month:
            self.view_year = target_date.year
            self.view_month = target_date.month
        self._rebuild_cache()
        self.update()

    def prev_month(self) -> None:
        """Navigate to preceding month."""
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self._rebuild_cache()
        self.update()

    def next_month(self) -> None:
        """Navigate to following month."""
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self._rebuild_cache()
        self.update()

    def go_today(self) -> None:
        """Jump view to current month and select today."""
        now_local = dt.datetime.now(sources.LOCAL_TZ)
        self.today = now_local.date()
        self.selected_date = self.today
        self.view_year = self.today.year
        self.view_month = self.today.month
        self._rebuild_cache()
        self.update()

    def trigger_refresh(self) -> None:
        """Execute refresh action: spin animation & emit refresh_requested signal."""
        if not self._refresh_spinning:
            self._refresh_spinning = True
            self._spin_angle = 0.0
            self._spin_anim.stop()
            self._spin_anim.start()
        self.update()
        try:
            self.refresh_requested.emit()
        except Exception as exc:
            sources.log_err("calendar_refresh_emit", exc)

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current calendar panel offscreen to a high-DPI ARGB32 QImage."""
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

        self._paint_panel(p)

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
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    # Event Handlers
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        elif key == Qt.Key_Left:
            self.select_date(self.selected_date - dt.timedelta(days=1))
            event.accept()
            return
        elif key == Qt.Key_Right:
            self.select_date(self.selected_date + dt.timedelta(days=1))
            event.accept()
            return
        elif key == Qt.Key_Up:
            self.select_date(self.selected_date - dt.timedelta(days=7))
            event.accept()
            return
        elif key == Qt.Key_Down:
            self.select_date(self.selected_date + dt.timedelta(days=7))
            event.accept()
            return
        elif key == Qt.Key_PageUp:
            self.prev_month()
            event.accept()
            return
        elif key == Qt.Key_PageDown:
            self.next_month()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                cursor_pos = QCursor.pos()
                if self._anchor_rect_global is not None:
                    if self._anchor_rect_global.contains(QPointF(cursor_pos)):
                        self._last_close_time = time.monotonic()
                        self._anchor_timer.start(300)
                        super().changeEvent(event)
                        return
                self.hide_animated()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        old_btn = self._hovered_btn
        old_cell = self._hovered_cell_idx
        old_card = self._hovered_card_idx
        old_up = self._hovered_upcoming_idx

        # Check button hits
        if self._rect_close.contains(pos):
            self._hovered_btn = "close"
        elif self._rect_btn_prev.contains(pos):
            self._hovered_btn = "prev"
        elif self._rect_btn_next.contains(pos):
            self._hovered_btn = "next"
        elif self._rect_btn_today.contains(pos):
            self._hovered_btn = "today"
        elif self._rect_btn_refresh.contains(pos):
            self._hovered_btn = "refresh"
        else:
            self._hovered_btn = ""

        # Check cell hits
        self._hovered_cell_idx = -1
        for idx, cell in enumerate(self._cached_cells):
            if cell["rect"].contains(pos):
                self._hovered_cell_idx = idx
                break

        # Check card hits
        self._hovered_card_idx = -1
        for idx, card in enumerate(self._cached_selected_cards):
            if card["rect"].contains(pos):
                self._hovered_card_idx = idx
                break

        # Check upcoming hits
        self._hovered_upcoming_idx = -1
        for idx, up in enumerate(self._cached_upcoming):
            if up["rect"].contains(pos):
                self._hovered_upcoming_idx = idx
                break

        # Cursor feedback
        needs_hand = bool(
            self._hovered_btn
            or self._hovered_cell_idx >= 0
            or (self._hovered_card_idx >= 0 and self._cached_selected_cards[self._hovered_card_idx].get("link"))
            or self._hovered_upcoming_idx >= 0
        )
        if needs_hand:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()

        if (
            self._hovered_btn != old_btn
            or self._hovered_cell_idx != old_cell
            or self._hovered_card_idx != old_card
            or self._hovered_upcoming_idx != old_up
        ):
            self.update()

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._rect_close.contains(pos):
                self.hide_animated()
                event.accept()
                return
            if self._rect_btn_refresh.contains(pos):
                self._refresh_pressed = True
                self.update()
                event.accept()
                return
            if self._rect_btn_prev.contains(pos):
                self.prev_month()
                event.accept()
                return
            if self._rect_btn_next.contains(pos):
                self.next_month()
                event.accept()
                return
            if self._rect_btn_today.contains(pos):
                self.go_today()
                event.accept()
                return

            # Click on day cell
            for cell in self._cached_cells:
                if cell["rect"].contains(pos):
                    self.select_date(cell["date"])
                    event.accept()
                    return

            # Click on selected day event card (open link if present)
            for card in self._cached_selected_cards:
                if card["rect"].contains(pos):
                    link = card.get("link")
                    if link and isinstance(link, str) and link.startswith("http"):
                        try:
                            QDesktopServices.openUrl(QUrl(link))
                        except Exception as exc:
                            sources.log_err("calendar_open_url", exc)
                    event.accept()
                    return

            # Click on upcoming item (jump to that day)
            for up in self._cached_upcoming:
                if up["rect"].contains(pos):
                    self.select_date(up["target_date"])
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._refresh_pressed:
            self._refresh_pressed = False
            pos = event.position()
            if self._rect_btn_refresh.contains(pos):
                self.trigger_refresh()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered_btn = ""
        self._hovered_cell_idx = -1
        self._hovered_card_idx = -1
        self._hovered_upcoming_idx = -1
        self._refresh_pressed = False
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    # Cache Builder (Runs on state change; Paint uses cached coordinates)
    def _rebuild_cache(self) -> None:
        """Compute grid layout, event allocations, and hit boxes once per state update."""
        now_local = dt.datetime.now(sources.LOCAL_TZ)
        self.today = now_local.date()

        # 1. Collect all events (Google + Holidays + Claude)
        events_list: List[Dict[str, Any]] = []
        raw_events = self._month_data.get("events")
        if isinstance(raw_events, list):
            for ev in raw_events:
                if isinstance(ev, dict):
                    events_list.append(ev)

        # Merge Claude markers for current, prev and next visible month
        claude_markers: List[Dict[str, Any]] = []
        for offset_m in (-1, 0, 1):
            m = self.view_month + offset_m
            y = self.view_year
            if m < 1:
                m = 12
                y -= 1
            elif m > 12:
                m = 1
                y += 1
            claude_markers.extend(get_claude_markers_for_month(self._claude_data, y, m))

        # 2. Build 6x7 Month Grid (42 cells)
        first_day = dt.date(self.view_year, self.view_month, 1)
        start_dow = first_day.weekday()  # Monday = 0
        grid_start_date = first_day - dt.timedelta(days=start_dow)

        grid_x = 16.0
        grid_y = 98.0
        cell_w = 42.0
        cell_h = 49.0

        cached_cells: List[Dict[str, Any]] = []
        month_event_count: int = 0

        for idx in range(42):
            cell_date = grid_start_date + dt.timedelta(days=idx)
            row = idx // 7
            col = idx % 7
            c_rect = QRectF(grid_x + col * cell_w, grid_y + row * cell_h, cell_w, cell_h)

            is_current = (cell_date.month == self.view_month)
            is_today = (cell_date == self.today)
            is_selected = (cell_date == self.selected_date)
            is_weekend = (cell_date.weekday() in (5, 6))

            # Match events that cover cell_date
            day_events = self._match_events_for_date(cell_date, events_list, claude_markers)
            if is_current:
                month_event_count += len(day_events)

            # Extract distinct category dots (up to 3)
            cat_order = ["Vergi/ödeme", "Resmi tatil", "Claude", "Google Takvim"]
            cats_present: Set[str] = {ev.get("category", "Google Takvim") for ev in day_events}
            ordered_cats = [c for c in cat_order if c in cats_present]
            dots = ordered_cats[:3]

            cached_cells.append({
                "date": cell_date,
                "rect": c_rect,
                "day_num": str(cell_date.day),
                "is_current": is_current,
                "is_today": is_today,
                "is_selected": is_selected,
                "is_weekend": is_weekend,
                "dots": dots,
            })

        self._cached_cells = cached_cells
        self._cached_month_event_count = month_event_count

        # 3. Selected Day Header text
        if self.selected_date == self.today:
            hdr_prefix = "Bugün · "
        elif self.selected_date == (self.today + dt.timedelta(days=1)):
            hdr_prefix = "Yarın · "
        else:
            hdr_prefix = ""
        dow_name = TR_DAYS_FULL.get(self.selected_date.weekday(), "")
        m_name = TR_MONTHS_FULL.get(self.selected_date.month, "")
        self._cached_selected_header_text = f"{hdr_prefix}{dow_name}, {self.selected_date.day} {m_name}"

        # 4. Selected Day Cards
        sel_events = self._match_events_for_date(self.selected_date, events_list, claude_markers)
        card_start_y = 74.0
        card_h = 42.0
        card_gap = 6.0
        card_w = 278.0
        card_x = 326.0

        cached_cards: List[Dict[str, Any]] = []
        for idx, ev in enumerate(sel_events[:3]):
            c_y = card_start_y + idx * (card_h + card_gap)
            c_rect = QRectF(card_x, c_y, card_w, card_h)
            cat_name = ev.get("category", "Google Takvim")
            cat_col = CATEGORY_COLORS.get(cat_name, COLOR_CAT_GCAL)

            raw_t = ev.get("title", "(Başlıksız)")
            disp_title = clean_title(raw_t)

            # Sub text determination
            sub_text = ev.get("sub")
            if not sub_text:
                if ev.get("all_day"):
                    sub_text = "Yarım gün" if ev.get("half_day") else "Tüm gün"
                else:
                    st = ev.get("start")
                    et = ev.get("end")
                    if isinstance(st, dt.datetime) and isinstance(et, dt.datetime):
                        sub_text = f"{st.strftime('%H:%M')}–{et.strftime('%H:%M')}"
                    elif isinstance(st, dt.datetime):
                        sub_text = st.strftime("%H:%M")
                    else:
                        sub_text = "Tüm gün"

            cached_cards.append({
                "rect": c_rect,
                "title": disp_title,
                "sub": sub_text,
                "color": cat_col,
                "link": str(ev.get("link") or ""),
            })

        self._cached_selected_cards = cached_cards

        # 5. Upcoming events section (next 4 upcoming events strictly after now/today)
        all_future_candidates: List[Tuple[dt.date, Dict[str, Any]]] = []
        check_start = self.today
        check_end = self.today + dt.timedelta(days=60)
        cur_d = check_start
        while cur_d <= check_end:
            day_matches = self._match_events_for_date(cur_d, events_list, claude_markers)
            for dev in day_matches:
                # If event is on today, only include if timed and ends in future or keep
                all_future_candidates.append((cur_d, dev))
            cur_d += dt.timedelta(days=1)

        # Filter out events strictly before now/today
        upcoming_items: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[dt.date, str]] = set()

        for ev_date, ev in all_future_candidates:
            if ev_date < self.today:
                continue
            if ev_date == self.today:
                # Skip today's all-day events or passed timed events so they do not duplicate today's active card
                if ev.get("all_day"):
                    continue
                st = ev.get("start")
                if isinstance(st, dt.datetime) and st <= now_local:
                    continue
            t_clean = clean_title(ev.get("title", ""))
            key = (ev_date, t_clean)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            cat_name = ev.get("category", "Google Takvim")
            cat_col = CATEGORY_COLORS.get(cat_name, COLOR_CAT_GCAL)
            date_lbl = f"{ev_date.day} {TR_MONTHS_SHORT.get(ev_date.month, '')}"

            upcoming_items.append({
                "target_date": ev_date,
                "date_label": date_lbl,
                "title": t_clean,
                "color": cat_col,
            })
            if len(upcoming_items) >= 4:
                break

        # Compute bounding rects for upcoming rows dynamically below selected cards
        card_count = max(1, len(self._cached_selected_cards))
        up_start_y = 74.0 + card_count * (card_h + card_gap) + 14.0
        up_row_h = 24.0
        up_row_gap = 4.0
        cached_up: List[Dict[str, Any]] = []
        for idx, up in enumerate(upcoming_items):
            row_y = up_start_y + 18.0 + idx * (up_row_h + up_row_gap)
            r = QRectF(card_x, row_y, card_w, up_row_h)
            cached_up.append({
                "rect": r,
                "target_date": up["target_date"],
                "date_label": up["date_label"],
                "title": up["title"],
                "color": up["color"],
            })
        self._cached_upcoming = cached_up

        # 6. Footer sync metadata
        upd = self._month_data.get("updated") or ""
        stale = bool(self._month_data.get("stale", False))
        if upd:
            if stale:
                self._cached_footer_sync_text = f"Google Takvim · {upd} (eski veri)"
            else:
                self._cached_footer_sync_text = f"Google Takvim · {upd}"
        else:
            self._cached_footer_sync_text = "Google Takvim · —"
        self._cached_footer_stale = stale

        self._cache_valid = True

    def _match_events_for_date(
        self,
        target_date: dt.date,
        gcal_events: List[Dict[str, Any]],
        claude_events: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Collect all Google, Holiday, and Claude items matching target_date."""
        matched: List[Dict[str, Any]] = []

        # 1. Holidays
        matched.extend(get_holiday_events_for_date(target_date))

        # 2. Google Takvim events
        for ev in gcal_events:
            st = ev.get("start")
            et = ev.get("end") or st
            all_day = bool(ev.get("all_day"))

            start_d = st.date() if isinstance(st, dt.datetime) else st
            end_d = et.date() if isinstance(et, dt.datetime) else et

            if not isinstance(start_d, dt.date):
                continue

            if all_day:
                # Exclusive end
                if isinstance(end_d, dt.date) and end_d > start_d:
                    if start_d <= target_date < end_d:
                        matched.append(ev)
                else:
                    if start_d == target_date:
                        matched.append(ev)
            else:
                # Timed
                if isinstance(end_d, dt.date):
                    if start_d <= target_date <= end_d:
                        matched.append(ev)
                elif start_d == target_date:
                    matched.append(ev)

        # 3. Claude events
        for cev in claude_events:
            st = cev.get("start")
            c_d = st.date() if isinstance(st, dt.datetime) else st
            if c_d == target_date:
                matched.append(cev)

        # Sort: all-day / holidays first, then timed
        def _sort_ev(item: Dict[str, Any]) -> Tuple[int, dt.time]:
            if item.get("all_day"):
                return 0, dt.time.min
            st = item.get("start")
            if isinstance(st, dt.datetime):
                return 1, st.time()
            return 1, dt.time.min

        matched.sort(key=_sort_ev)
        return matched

    # Painting (Sub-millisecond execution using cached primitives)
    def paintEvent(self, _event) -> None:
        if self._anim_opacity <= 0.001:
            return
        try:
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.Antialiasing)
                p.setRenderHint(QPainter.TextAntialiasing)
                p.setOpacity(self._anim_opacity)

                cx = self.width() / 2.0
                cy = self.height() / 2.0
                p.translate(cx, cy + self._anim_offset_y)
                p.scale(self._anim_scale, self._anim_scale)
                p.translate(-cx, -cy)

                self._paint_panel(p)
            finally:
                p.end()
        except Exception as exc:
            sources.log_err("calendar_paintEvent", exc)

    def _paint_panel(self, p: QPainter) -> None:
        """Render complete calendar panel card."""
        w = float(self.width())
        h = float(self.height())
        full_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        panel_path = rounded_path(full_rect, self.RADIUS)

        # 1. Base Material Glass & Border
        p.fillPath(panel_path, COLOR_BG)
        p.setPen(QPen(COLOR_BORDER, 1))
        p.drawPath(panel_path)

        # 2. Header
        # Calendar Icon
        icon_box = QRectF(16.0, 10.0, 18.0, 18.0)
        draw_cal_icon(p, icon_box)

        # Title "Takvim"
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_title = QFontMetricsF(self.f_title)
        p.drawText(QRectF(40.0, 9.0, 60.0, 20.0), Qt.AlignLeft | Qt.AlignVCenter, "Takvim")
        title_w = fm_title.horizontalAdvance("Takvim")

        # Pill Badge: "N etkinlik"
        badge_text = f"{self._cached_month_event_count} etkinlik"
        p.setFont(self.f_badge)
        fm_badge = QFontMetricsF(self.f_badge)
        bw = fm_badge.horizontalAdvance(badge_text) + 16.0
        badge_rect = QRectF(40.0 + title_w + 10.0, 10.0, bw, 18.0)
        p.fillPath(rounded_path(badge_rect, 9.0), COLOR_BADGE_BG)
        p.setPen(COLOR_BADGE_TXT)
        p.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # Close Button ✕
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY if self._hovered_btn == "close" else COLOR_TEXT_MUTED)
        p.drawText(self._rect_close, Qt.AlignCenter, "✕")

        # Header Separator
        p.setPen(QPen(COLOR_HAIRLINE, 1))
        p.drawLine(16, 38, int(w - 16), 38)

        # 3. Column Separator (Left 308px, Right remainder)
        p.setPen(QPen(COLOR_DIVIDER, 1))
        p.drawLine(314, 46, 314, int(h - 44))

        # 4. Left Column: Month Navigation
        # Month Label e.g. "Ekim 2026"
        month_label = f"{TR_MONTHS_FULL.get(self.view_month, '')} {self.view_year}"
        p.setFont(self.f_nav_month)
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(16.0, 46.0, 190.0, 22.0), Qt.AlignLeft | Qt.AlignVCenter, month_label)

        # ‹ Button
        p.fillPath(
            rounded_path(self._rect_btn_prev, 5.0),
            COLOR_CARD_HOVER if self._hovered_btn == "prev" else COLOR_CARD_BG,
        )
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY if self._hovered_btn == "prev" else COLOR_TEXT_SECONDARY)
        p.drawText(self._rect_btn_prev, Qt.AlignCenter, "‹")

        # › Button
        p.fillPath(
            rounded_path(self._rect_btn_next, 5.0),
            COLOR_CARD_HOVER if self._hovered_btn == "next" else COLOR_CARD_BG,
        )
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY if self._hovered_btn == "next" else COLOR_TEXT_SECONDARY)
        p.drawText(self._rect_btn_next, Qt.AlignCenter, "›")

        # 'Bugün' Button
        p.fillPath(
            rounded_path(self._rect_btn_today, 5.0),
            COLOR_CARD_HOVER if self._hovered_btn == "today" else COLOR_CARD_BG,
        )
        p.setFont(self.f_btn)
        p.setPen(COLOR_TEXT_PRIMARY if self._hovered_btn == "today" else COLOR_TEXT_SECONDARY)
        p.drawText(self._rect_btn_today, Qt.AlignCenter, "Bugün")

        # Weekday Headers: Pzt Sal Çar Per Cum Cmt Paz
        p.setFont(self.f_weekday)
        p.setPen(COLOR_TEXT_MUTED)
        grid_x = 16.0
        cell_w = 42.0
        for i, day_name in enumerate(TR_DAYS_SHORT):
            hdr_rect = QRectF(grid_x + i * cell_w, 76.0, cell_w, 18.0)
            p.drawText(hdr_rect, Qt.AlignCenter, day_name)

        # Day Grid (6x7 = 42 cells)
        for idx, cell in enumerate(self._cached_cells):
            rect: QRectF = cell["rect"]
            cx = rect.center().x()
            cy = rect.top() + 15.0
            is_hovered = (self._hovered_cell_idx == idx)

            # Cell Hover background
            if is_hovered and not cell["is_today"]:
                p.fillPath(rounded_path(QRectF(cx - 13.0, cy - 13.0, 26.0, 26.0), 13.0), COLOR_HOVER_CELL)

            # Today filled circle (#FF453A)
            if cell["is_today"]:
                p.setPen(Qt.NoPen)
                p.setBrush(COLOR_TODAY_CIRCLE)
                p.drawEllipse(QPointF(cx, cy), 12.0, 12.0)

            # Selected ring (1.5px)
            if cell["is_selected"]:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(COLOR_SELECTED_RING, 1.5))
                p.drawEllipse(QPointF(cx, cy), 13.5, 13.5)

            # Day Number Text
            if cell["is_today"]:
                p.setFont(self.f_day_today)
                p.setPen(COLOR_TEXT_PRIMARY)
            else:
                p.setFont(self.f_day_num)
                if not cell["is_current"]:
                    # Other-month days dimmed 35%
                    p.setPen(QColor(255, 255, 255, 65))
                elif cell["is_weekend"]:
                    p.setPen(COLOR_TEXT_MUTED)
                else:
                    p.setPen(COLOR_TEXT_SECONDARY)

            num_box = QRectF(cx - 14.0, cy - 11.0, 28.0, 22.0)
            p.drawText(num_box, Qt.AlignCenter, cell["day_num"])

            # Category Dots under the day number (up to 3, 4px diameter)
            dots = cell["dots"]
            if dots:
                dot_r = 2.0
                dot_gap = 3.0
                total_w = len(dots) * (2 * dot_r) + (len(dots) - 1) * dot_gap
                start_dot_x = cx - total_w / 2.0 + dot_r
                dot_y = cy + 18.0
                for d_i, cat_name in enumerate(dots):
                    c_col = CATEGORY_COLORS.get(cat_name, COLOR_CAT_GCAL)
                    p.setPen(Qt.NoPen)
                    p.setBrush(c_col)
                    dx = start_dot_x + d_i * (2 * dot_r + dot_gap)
                    p.drawEllipse(QPointF(dx, dot_y), dot_r, dot_r)

        # 5. Right Column: Selected Day Agenda & Upcoming
        card_x = 326.0
        card_w = 278.0

        # Selected Day Header
        p.setFont(self.f_day_hdr)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_hdr = QFontMetricsF(self.f_day_hdr)
        elided_hdr = fm_hdr.elidedText(self._cached_selected_header_text, Qt.ElideRight, card_w)
        p.drawText(QRectF(card_x, 46.0, card_w, 22.0), Qt.AlignLeft | Qt.AlignVCenter, elided_hdr)

        # Selected Day Event Cards
        if self._cached_selected_cards:
            for c_i, card in enumerate(self._cached_selected_cards):
                c_rect: QRectF = card["rect"]
                is_c_hover = (self._hovered_card_idx == c_i)
                card_path = rounded_path(c_rect, 8.0)

                # Card background fill & border
                p.fillPath(card_path, COLOR_CARD_HOVER if is_c_hover else COLOR_CARD_BG)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(COLOR_CARD_BORDER, 1))
                p.drawPath(card_path)

                # 3.5px Left Accent Bar
                bar_rect = QRectF(c_rect.left() + 1.0, c_rect.top() + 4.0, 3.5, c_rect.height() - 8.0)
                p.setPen(Qt.NoPen)
                p.setBrush(card["color"])
                p.drawRoundedRect(bar_rect, 1.75, 1.75)

                # Title (12px SemiBold, elided)
                p.setFont(self.f_card_title)
                p.setPen(COLOR_TEXT_PRIMARY)
                fm_ct = QFontMetricsF(self.f_card_title)
                max_tw = card_w - 24.0
                t_elided = fm_ct.elidedText(card["title"], Qt.ElideRight, max_tw)
                p.drawText(QRectF(c_rect.left() + 12.0, c_rect.top() + 4.0, max_tw, 18.0), Qt.AlignLeft | Qt.AlignVCenter, t_elided)

                # Sub (11px Muted)
                p.setFont(self.f_card_sub)
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(QRectF(c_rect.left() + 12.0, c_rect.top() + 22.0, max_tw, 16.0), Qt.AlignLeft | Qt.AlignVCenter, card["sub"])
        else:
            # Empty state
            empty_rect = QRectF(card_x, 74.0, card_w, 42.0)
            empty_path = rounded_path(empty_rect, 8.0)
            p.fillPath(empty_path, COLOR_CARD_BG)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(COLOR_CARD_BORDER, 1))
            p.drawPath(empty_path)
            p.setFont(self.f_card_sub)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(empty_rect, Qt.AlignCenter, "Etkinlik yok")

        # Upcoming Section Header: "YAKLAŞAN"
        card_count = max(1, len(self._cached_selected_cards))
        up_hdr_y = 74.0 + card_count * (42.0 + 6.0) + 14.0
        p.setFont(self.f_sec_title)
        p.setPen(COLOR_SECTION_TITLE)
        p.drawText(QRectF(card_x, up_hdr_y, card_w, 16.0), Qt.AlignLeft | Qt.AlignVCenter, "YAKLAŞAN")

        # Upcoming Items
        if self._cached_upcoming:
            for u_i, up in enumerate(self._cached_upcoming):
                u_rect: QRectF = up["rect"]
                is_u_hover = (self._hovered_upcoming_idx == u_i)
                if is_u_hover:
                    p.fillPath(rounded_path(u_rect, 5.0), COLOR_CARD_HOVER)

                # Date Label
                p.setFont(self.f_up_date)
                p.setPen(up["color"])
                p.drawText(QRectF(u_rect.left() + 4.0, u_rect.top(), 52.0, u_rect.height()), Qt.AlignLeft | Qt.AlignVCenter, up["date_label"])

                # Event Title
                p.setFont(self.f_up_title)
                p.setPen(COLOR_TEXT_PRIMARY if is_u_hover else COLOR_TEXT_SECONDARY)
                fm_ut = QFontMetricsF(self.f_up_title)
                tw = card_w - 64.0
                elided_ut = fm_ut.elidedText(up["title"], Qt.ElideRight, tw)
                p.drawText(QRectF(u_rect.left() + 58.0, u_rect.top(), tw, u_rect.height()), Qt.AlignLeft | Qt.AlignVCenter, elided_ut)
        else:
            p.setFont(self.f_up_title)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(QRectF(card_x + 4.0, up_hdr_y + 20.0, card_w, 20.0), Qt.AlignLeft | Qt.AlignVCenter, "Yaklaşan etkinlik yok")

        # 6. Footer (Legend + Sync + Yenile Button)
        y_sep = h - 36.0
        p.setPen(QPen(COLOR_HAIRLINE, 1))
        p.drawLine(16, int(y_sep), int(w - 16), int(y_sep))

        # Legend Chips (Google Takvim, Vergi/ödeme, Resmi tatil, Claude)
        legends = [
            ("Google Takvim", COLOR_CAT_GCAL),
            ("Vergi/ödeme", COLOR_CAT_TAX),
            ("Resmi tatil", COLOR_CAT_HOLIDAY),
            ("Claude", COLOR_CAT_CLAUDE),
        ]
        leg_x = 16.0
        leg_y = y_sep + 10.0
        p.setFont(self.f_footer)
        fm_leg = QFontMetricsF(self.f_footer)

        for name, col in legends:
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(leg_x + 3.0, leg_y + 8.0), 3.0, 3.0)

            p.setPen(COLOR_TEXT_MUTED)
            txt_w = fm_leg.horizontalAdvance(name)
            p.drawText(QRectF(leg_x + 9.0, leg_y, txt_w, 16.0), Qt.AlignLeft | Qt.AlignVCenter, name)
            leg_x += 9.0 + txt_w + 10.0

        # Sync text: 'Google Takvim · HH:MM'
        p.setFont(self.f_footer)
        p.setPen(COLOR_STALE_TXT if self._cached_footer_stale else COLOR_TEXT_MUTED)
        sync_txt = self._cached_footer_sync_text
        fm_sync = QFontMetricsF(self.f_footer)
        sync_w = fm_sync.horizontalAdvance(sync_txt)
        sync_x = self._rect_btn_refresh.left() - 14.0 - sync_w
        p.drawText(QRectF(sync_x, y_sep + 6.0, sync_w, 24.0), Qt.AlignRight | Qt.AlignVCenter, sync_txt)

        # Yenile Button
        btn_r = self._rect_btn_refresh
        btn_path = rounded_path(btn_r, 6.0)

        if self._refresh_pressed:
            btn_bg = COLOR_REFRESH_BG_PRESS
        elif self._hovered_btn == "refresh":
            btn_bg = COLOR_REFRESH_BG_HOVER
        else:
            btn_bg = COLOR_REFRESH_BG

        p.fillPath(btn_path, btn_bg)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(COLOR_REFRESH_BORDER, 1))
        p.drawPath(btn_path)

        p.setFont(self.f_btn)
        p.setPen(COLOR_REFRESH_TXT)
        if self._refresh_spinning:
            icon_box = QRectF(btn_r.center().x() - 6.0, btn_r.center().y() - 6.0, 12.0, 12.0)
            draw_refresh_icon(p, icon_box, angle=self._spin_angle)
        else:
            p.drawText(btn_r, Qt.AlignCenter, "Yenile")
