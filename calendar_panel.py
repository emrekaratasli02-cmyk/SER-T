"""Modern dark-mode card-layered calendar popover panel for Şerit dock (Direction C).

Displays:
- Hero card split into Today status (big 42px day number, blue weekday, month/year, status chip)
  and Upcoming Events list (dots for Holiday red, Tax amber with bold amber amount, Google blue).
- Month grid tile with month navigation (< >), Pzt..Paz headers, today in solid blue circle,
  event category dots under dates.
- Footer with category legend (Google / Vergi / Tatil) and event count / sync status.
"""

from __future__ import annotations

import calendar
import datetime as dt
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import unicodedata

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
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

# Safe imports from serit package
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

try:
    import panel_style
    import sources
    import winapi
except ImportError:
    import panel_style  # type: ignore
    sources = None
    winapi = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


TR_MONTHS_FULL = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

TR_MONTHS_SHORT = {
    1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
    7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara",
}

TR_DAYS_FULL = {
    0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
    4: "Cuma", 5: "Cumartesi", 6: "Pazar",
}

TR_DAYS_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

# Turkish Public Holidays (2026-2027)
TURKISH_HOLIDAYS_TABLE: Dict[dt.date, List[Tuple[str, bool]]] = {
    dt.date(2026, 1, 1): [("Yılbaşı", False)],
    dt.date(2026, 3, 19): [("Ramazan Bayramı Arifesi (tahmini)", True)],
    dt.date(2026, 3, 20): [("Ramazan Bayramı 1. Gün (tahmini)", False)],
    dt.date(2026, 3, 21): [("Ramazan Bayramı 2. Gün (tahmini)", False)],
    dt.date(2026, 3, 22): [("Ramazan Bayramı 3. Gün (tahmini)", False)],
    dt.date(2026, 4, 23): [("Ulusal Egemenlik ve Çocuk Bayramı", False)],
    dt.date(2026, 5, 1): [("Emek ve Dayanışma Günü", False)],
    dt.date(2026, 5, 19): [("Atatürk'ü Anma, Gençlik ve Spor Bayramı", False)],
    dt.date(2026, 5, 26): [("Kurban Bayramı Arifesi (tahmini)", True)],
    dt.date(2026, 5, 27): [("Kurban Bayramı 1. Gün (tahmini)", False)],
    dt.date(2026, 5, 28): [("Kurban Bayramı 2. Gün (tahmini)", False)],
    dt.date(2026, 5, 29): [("Kurban Bayramı 3. Gün (tahmini)", False)],
    dt.date(2026, 5, 30): [("Kurban Bayramı 4. Gün (tahmini)", False)],
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

    week_reset = claude_data.get("week_reset")
    if isinstance(week_reset, str) and week_reset.strip():
        try:
            wr_dt = dt.datetime.fromisoformat(week_reset.strip())
            local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            local_wr = wr_dt.astimezone(local_tz) if wr_dt.tzinfo else wr_dt.replace(tzinfo=local_tz)
            time_str = local_wr.strftime("%H:%M")
            target_dow = local_wr.weekday()
            _, days_in_month = calendar.monthrange(year, month)
            for day in range(1, days_in_month + 1):
                cur_date = dt.date(year, month, day)
                if cur_date.weekday() == target_dow:
                    markers.append({
                        "title": f"Claude haftalık sıfırlama {time_str}",
                        "start": dt.datetime.combine(cur_date, local_wr.time()).replace(tzinfo=local_tz),
                        "end": dt.datetime.combine(cur_date, local_wr.time()).replace(tzinfo=local_tz),
                        "all_day": False,
                        "link": "",
                        "category": "Claude",
                        "sub": time_str,
                    })
        except Exception as exc:
            _log_err("claude_marker_week", exc)

    subscribed_at = claude_data.get("subscribed_at")
    if isinstance(subscribed_at, str) and subscribed_at.strip():
        try:
            sub_dt = dt.datetime.fromisoformat(subscribed_at.strip())
            local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            local_sub = sub_dt.astimezone(local_tz) if sub_dt.tzinfo else sub_dt.replace(tzinfo=local_tz)
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
            _log_err("claude_marker_sub", exc)

    return markers


def draw_calendar_icon(p: QPainter, rect: QRectF, day_num: int) -> None:
    """Draw high-DPI vector calendar tear-sheet mark with blue header and date number."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()
    w = 18.0
    h = 18.0
    box_r = QRectF(cx - w / 2.0, cy - h / 2.0, w, h)

    # White card body
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    path = QPainterPath()
    path.addRoundedRect(box_r, 4.0, 4.0)
    p.drawPath(path)

    # Blue top header band
    p.setBrush(panel_style.ACCENT)
    p.setClipPath(path)
    header_r = QRectF(box_r.left(), box_r.top(), box_r.width(), 5.0)
    p.fillRect(header_r, panel_style.ACCENT)
    p.setClipping(False)

    # Two blue pins on top
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(panel_style.ACCENT)
    p.drawEllipse(QRectF(box_r.left() + 3.5, box_r.top() - 1.0, 2.4, 2.4))
    p.drawEllipse(QRectF(box_r.right() - 5.9, box_r.top() - 1.0, 2.4, 2.4))

    # Day number inside card
    p.setFont(panel_style.font(8.5, QFont.Weight.Bold, tabular=True))
    p.setPen(panel_style.ACCENT)
    text_r = QRectF(box_r.left(), box_r.top() + 4.5, box_r.width(), box_r.height() - 4.5)
    p.drawText(text_r, Qt.AlignmentFlag.AlignCenter, str(day_num))
    p.restore()


# ---------------------------------------------------------------------------
# CalendarPanel Widget
# ---------------------------------------------------------------------------

class CalendarPanel(QWidget):
    """Modern dark-mode card-layered calendar popover panel for Şerit dock (Direction C)."""

    WIDTH: int = 440
    HEIGHT: int = 490
    RADIUS: float = panel_style.R_PANEL

    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Frameless opaque window flags
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Internal state
        self._anchor_rect_global: Optional[QRectF] = None
        self._month_data: Dict[str, Any] = {}
        self._claude_data: Dict[str, Any] = {}

        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        now_local = dt.datetime.now(local_tz)
        self.today: dt.date = now_local.date()
        self.selected_date: dt.date = self.today
        self.view_year: int = self.today.year
        self.view_month: int = self.today.month

        # Focus / bounce tracking
        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Animations (180ms OutCubic open, 150ms InQuad close)
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0
        self._anim_scale: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Interactive states & hit regions
        self._hover_close: bool = False
        self._hover_prev: bool = False
        self._hover_next: bool = False
        self._hover_cell_idx: int = -1
        self._hover_upcoming_idx: int = -1

        # Fixed Hit Rects
        self._rect_close = QRectF(self.WIDTH - 14.0 - 26.0, 10.0, 26.0, 26.0)
        self._rect_btn_prev = QRectF(self.WIDTH - 14.0 - 58.0, 216.0, 22.0, 22.0)
        self._rect_btn_next = QRectF(self.WIDTH - 14.0 - 30.0, 216.0, 22.0, 22.0)
        self._rect_btn_refresh = QRectF(self.WIDTH - 14.0 - 150.0, self.HEIGHT - 32.0, 150.0, 24.0)

        # Layout Cache
        self._cached_cells: List[Dict[str, Any]] = []
        self._cached_selected_cards: List[Dict[str, Any]] = []
        self._cached_upcoming: List[Dict[str, Any]] = []
        self._cached_month_event_count: int = 0
        self._cached_selected_header_text: str = ""
        self._cached_footer_sync_text: str = ""

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
        anchor_global: Optional[Union[QRectF, Any]] = None,
        month_data: Optional[Dict[str, Any]] = None,
        claude_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Position centered above anchor, apply physical round region, and animate in."""
        try:
            self._anchor_rect_global = QRectF(anchor_global) if anchor_global is not None else None
            self._month_data = month_data if isinstance(month_data, dict) else {}
            self._claude_data = claude_data if isinstance(claude_data, dict) else {}

            local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            now_local = dt.datetime.now(local_tz)
            self.today = now_local.date()
            if not hasattr(self, "selected_date") or self.selected_date is None:
                self.selected_date = self.today

            self._rebuild_cache()

            # Positioning above anchor (8px gap), clamped inside screen geometry
            dpr = 1.0
            if self._anchor_rect_global is not None:
                anchor_cx = self._anchor_rect_global.center().x()
                target_x = int(anchor_cx - self.width() / 2.0)
                target_y = int(self._anchor_rect_global.top() - self.height() - panel_style.ANCHOR_GAP)

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
                        below_y = int(self._anchor_rect_global.bottom() + panel_style.ANCHOR_GAP)
                        if below_y + self.height() <= geom.bottom() - margin:
                            target_y = below_y
                        else:
                            target_y = min_y
                    elif target_y > max_y:
                        target_y = max_y

                self.move(target_x, target_y)

            # Apply Windows physical rounded region without acrylic (opaque panel)
            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(panel_style.R_PANEL), dpr)
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
            _log_err("calendar_show_for", exc)

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
        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        now_local = dt.datetime.now(local_tz)
        self.today = now_local.date()
        self.selected_date = self.today
        self.view_year = self.today.year
        self.view_month = self.today.month
        self._rebuild_cache()
        self.update()

    def trigger_refresh(self) -> None:
        """Execute refresh action and emit refresh_requested signal."""
        try:
            self.refresh_requested.emit()
        except Exception as exc:
            _log_err("calendar_refresh_emit", exc)
        self.update()

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current calendar panel offscreen to a high-DPI ARGB32 QImage."""
        w_phys = int(self.width() * dpr)
        h_phys = int(self.height() * dpr)
        img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

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

    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    # Event Handlers
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        elif key == Qt.Key.Key_Left:
            self.select_date(self.selected_date - dt.timedelta(days=1))
            event.accept()
            return
        elif key == Qt.Key.Key_Right:
            self.select_date(self.selected_date + dt.timedelta(days=1))
            event.accept()
            return
        elif key == Qt.Key.Key_Up:
            self.select_date(self.selected_date - dt.timedelta(days=7))
            event.accept()
            return
        elif key == Qt.Key.Key_Down:
            self.select_date(self.selected_date + dt.timedelta(days=7))
            event.accept()
            return
        elif key == Qt.Key.Key_PageUp:
            self.prev_month()
            event.accept()
            return
        elif key == Qt.Key.Key_PageDown:
            self.next_month()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
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
        old_close = self._hover_close
        old_prev = self._hover_prev
        old_next = self._hover_next
        old_cell = self._hover_cell_idx
        old_up = self._hover_upcoming_idx

        self._hover_close = self._rect_close.contains(pos)
        self._hover_prev = self._rect_btn_prev.contains(pos)
        self._hover_next = self._rect_btn_next.contains(pos)

        # Check cell hits
        self._hover_cell_idx = -1
        for idx, cell in enumerate(self._cached_cells):
            if cell["rect"].contains(pos):
                self._hover_cell_idx = idx
                break

        # Check upcoming / card hits
        self._hover_upcoming_idx = -1
        for idx, up in enumerate(self._cached_upcoming):
            if up["rect"].contains(pos):
                self._hover_upcoming_idx = idx
                break

        if (
            self._hover_close != old_close
            or self._hover_prev != old_prev
            or self._hover_next != old_next
            or self._hover_cell_idx != old_cell
            or self._hover_upcoming_idx != old_up
        ):
            self.update()

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()

            if self._rect_close.contains(pos):
                self.hide_animated()
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

            # Click on day cell
            for cell in self._cached_cells:
                if cell["rect"].contains(pos):
                    self.select_date(cell["date"])
                    event.accept()
                    return

            # Click on upcoming item (if it has a link open it, else select its date)
            for up in self._cached_upcoming:
                if up["rect"].contains(pos):
                    link = up.get("link")
                    if link and isinstance(link, str) and link.startswith("http"):
                        try:
                            QDesktopServices.openUrl(QUrl(link))
                        except Exception as exc:
                            _log_err("calendar_open_url", exc)
                    target = up.get("target_date")
                    if target:
                        self.select_date(target)
                    event.accept()
                    return

            # Also check selected cards for link click
            for card in self._cached_selected_cards:
                if card["rect"].contains(pos):
                    link = card.get("link")
                    if link and isinstance(link, str) and link.startswith("http"):
                        try:
                            QDesktopServices.openUrl(QUrl(link))
                        except Exception as exc:
                            _log_err("calendar_open_url", exc)
                    event.accept()
                    return

        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_close = False
        self._hover_prev = False
        self._hover_next = False
        self._hover_cell_idx = -1
        self._hover_upcoming_idx = -1
        self.update()
        super().leaveEvent(event)

    # Cache Builder
    def _rebuild_cache(self) -> None:
        """Compute month grid, upcoming events, and hit rects for fast painting."""
        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        now_local = dt.datetime.now(local_tz)
        self.today = now_local.date()

        # 1. Collect all events (Google + Holidays + Claude)
        events_list: List[Dict[str, Any]] = []
        raw_events = self._month_data.get("events")
        if isinstance(raw_events, list):
            for ev in raw_events:
                if isinstance(ev, dict):
                    events_list.append(ev)

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

        pad_x = 14.0
        avail_w = self.WIDTH - 2 * pad_x
        tile2_y = 204.0
        grid_pad_x = 12.0
        grid_x = pad_x + grid_pad_x
        grid_y = tile2_y + 54.0
        col_w = (avail_w - 2 * grid_pad_x) / 7.0
        row_h = 26.0

        cached_cells: List[Dict[str, Any]] = []
        month_event_count: int = 0

        for idx in range(42):
            cell_date = grid_start_date + dt.timedelta(days=idx)
            row = idx // 7
            col = idx % 7
            c_rect = QRectF(grid_x + col * col_w, grid_y + row * row_h, col_w, row_h)

            is_current = (cell_date.month == self.view_month)
            is_today = (cell_date == self.today)
            is_selected = (cell_date == self.selected_date)

            day_events = self._match_events_for_date(cell_date, events_list, claude_markers)
            if is_current:
                month_event_count += len(day_events)

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

        # 4. Hero Card Left: Events for selected day
        sel_day_events = self._match_events_for_date(self.selected_date, events_list, claude_markers)

        # 5. Hero Card Right: Upcoming Events
        # Collect distinct days >= today (or selected_date)
        ref_start_date = min(self.today, self.selected_date)
        all_future_days = [ref_start_date + dt.timedelta(days=i) for i in range(45)]
        upcoming_items: List[Dict[str, Any]] = []

        cat_prio = {"Resmi tatil": 0, "Vergi/ödeme": 1, "Google Takvim": 2, "Claude": 3}
        for f_date in all_future_days:
            # Skip today if today has no events
            if f_date == self.today and not sel_day_events and f_date != self.selected_date:
                pass
            matches = self._match_events_for_date(f_date, events_list, claude_markers)
            matches.sort(key=lambda ev: cat_prio.get(ev.get("category", "Google Takvim"), 9))
            for ev in matches:
                cat = ev.get("category", "Google Takvim")
                if cat == "Resmi tatil":
                    dot_color = panel_style.DANGER  # #FF453A
                elif cat == "Vergi/ödeme":
                    dot_color = panel_style.WARN    # #FF9F0A
                elif cat == "Claude":
                    dot_color = panel_style.CLAUDE  # #D97757
                else:
                    dot_color = panel_style.ACCENT  # #0A84FF

                t_clean = clean_title(ev.get("title", ""))
                # Detect amount in title (e.g. 791,00 TL)
                amount_match = re.search(r"(\d+(?:\.\d+)?,\d{2}\s*TL)", t_clean)
                amount_str = amount_match.group(1) if amount_match else ""

                upcoming_items.append({
                    "title": t_clean,
                    "target_date": f_date,
                    "date_label": f"{f_date.day} {TR_MONTHS_SHORT.get(f_date.month, '')}",
                    "dot_color": dot_color,
                    "category": cat,
                    "link": ev.get("link", ""),
                    "amount": amount_str,
                })
                if len(upcoming_items) >= 4:
                    break
            if len(upcoming_items) >= 4:
                break

        # Calculate coordinates for 4 upcoming rows inside right column of Hero Tile
        tile1_y = 54.0
        tile1_x = pad_x
        right_col_x = tile1_x + 130.0
        right_col_w = avail_w - 130.0 - 12.0
        row_start_y = tile1_y + 30.0
        row_gap_y = 23.0

        cached_upcoming: List[Dict[str, Any]] = []
        cached_cards: List[Dict[str, Any]] = []

        for idx, up in enumerate(upcoming_items[:4]):
            r_rect = QRectF(right_col_x, row_start_y + idx * row_gap_y, right_col_w, 20.0)
            up_item = dict(up)
            up_item["rect"] = r_rect
            cached_upcoming.append(up_item)

            if up["target_date"] == self.selected_date:
                cached_cards.append(up_item)

        # Fallback card rect for selected cards test if empty
        if not cached_cards and sel_day_events:
            for idx, ev in enumerate(sel_day_events[:4]):
                c_rect = QRectF(right_col_x, row_start_y + idx * row_gap_y, right_col_w, 20.0)
                cached_cards.append({
                    "title": clean_title(ev.get("title", "")),
                    "rect": c_rect,
                    "link": ev.get("link", ""),
                    "category": ev.get("category", "Google Takvim"),
                    "target_date": self.selected_date,
                    "dot_color": panel_style.ACCENT,
                    "date_label": f"{self.selected_date.day} {TR_MONTHS_SHORT.get(self.selected_date.month, '')}",
                    "amount": "",
                })

        self._cached_upcoming = cached_upcoming
        self._cached_selected_cards = cached_cards if cached_cards else cached_upcoming[:1]

        # 6. Footer sync text
        self._cached_footer_sync_text = f"{self._cached_month_event_count} etkinlik · Senkronize"

    def _match_events_for_date(
        self,
        d: dt.date,
        events: List[Dict[str, Any]],
        claude_markers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return all events covering target date d."""
        matched: List[Dict[str, Any]] = []

        # 1. Google / JSON events
        for ev in events:
            if not isinstance(ev, dict):
                continue
            st = ev.get("start")
            en = ev.get("end")
            is_all_day = bool(ev.get("all_day", False))

            st_date = st.date() if isinstance(st, dt.datetime) else st if isinstance(st, dt.date) else None
            en_date = en.date() if isinstance(en, dt.datetime) else en if isinstance(en, dt.date) else st_date

            if st_date is None:
                continue

            if is_all_day:
                if en_date and en_date > st_date:
                    if st_date <= d < en_date:
                        matched.append(ev)
                else:
                    if d == st_date:
                        matched.append(ev)
            else:
                if en_date and en_date > st_date:
                    if st_date <= d <= en_date:
                        matched.append(ev)
                else:
                    if d == st_date:
                        matched.append(ev)

        # 2. Turkish Holidays
        matched.extend(get_holiday_events_for_date(d))

        # 3. Claude markers
        for cm in claude_markers:
            c_st = cm.get("start")
            c_date = c_st.date() if isinstance(c_st, dt.datetime) else c_st if isinstance(c_st, dt.date) else None
            if c_date == d:
                matched.append(cm)

        return matched

    # -----------------------------------------------------------------------
    # Painting
    # -----------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if self._anim_opacity <= 0.001:
            return

        try:
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                p.setOpacity(self._anim_opacity)

                cx = self.width() / 2.0
                cy = self.height() / 2.0
                p.translate(cx, cy + self._anim_offset_y)
                p.scale(self._anim_scale, self._anim_scale)
                p.translate(-cx, -cy)

                self._paint_panel(p)
            finally:
                p.end()
        except Exception as e:
            _log_err("CalendarPanel.paintEvent", e)

    def _paint_panel(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        r_full = QRectF(0.0, 0.0, w, h)

        # 1. Base Opaque Shell (Direction C Dark Obsidian)
        panel_style.draw_panel_shell(p, r_full)

        # 2. Header: Vector Calendar Icon + Title ('Takvim') + Badge ('N etkinlik') + Close ('✕')
        cal_icon_r = QRectF(16.0, 14.0, 18.0, 18.0)
        draw_calendar_icon(p, cal_icon_r, self.today.day)

        title = "Takvim"
        f_title = panel_style.f_title()
        p.setFont(f_title)
        p.setPen(panel_style.TEXT)
        fm_t = QFontMetricsF(f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(42.0, 12.0, title_w + 4.0, 22.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Badge: e.g. "20 etkinlik"
        badge_text = f"{self._cached_month_event_count} etkinlik"
        f_badge = panel_style.font(11.0, QFont.Weight.Medium)
        p.setFont(f_badge)
        fm_b = QFontMetricsF(f_badge)
        badge_w = fm_b.horizontalAdvance(badge_text) + 16.0
        badge_r = QRectF(42.0 + title_w + 10.0, 14.5, badge_w, 18.0)

        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawPath(panel_style.rounded(badge_r, 9.0))
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(badge_r, Qt.AlignmentFlag.AlignCenter, badge_text)
        p.restore()

        # Close button ('✕')
        self._rect_close = QRectF(w - 14.0 - 26.0, 10.0, 26.0, 26.0)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel_style.BUTTON_HOVER if self._hover_close else panel_style.BUTTON_BG)
        p.drawPath(panel_style.rounded(self._rect_close, panel_style.R_BUTTON))
        p.setPen(QPen(panel_style.TEXT if self._hover_close else panel_style.TEXT_MUTED, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx_c = self._rect_close.center().x()
        cy_c = self._rect_close.center().y()
        p.drawLine(QPointF(cx_c - 4.0, cy_c - 4.0), QPointF(cx_c + 4.0, cy_c + 4.0))
        p.drawLine(QPointF(cx_c + 4.0, cy_c - 4.0), QPointF(cx_c - 4.0, cy_c + 4.0))
        p.restore()

        # Separator line under header
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(QPointF(0.0, 46.0), QPointF(w, 46.0))

        # 3. Upper Tile (Hero Card: Today & Upcoming Split)
        pad_x = 14.0
        avail_w = w - 2 * pad_x
        tile1_y = 54.0
        tile1_h = 138.0
        tile1_r = QRectF(pad_x, tile1_y, avail_w, tile1_h)
        panel_style.draw_tile(p, tile1_r, hover=False)

        # Left Column (Date Hero: 27 / Salı / Ekim 2026 / Bugün boş)
        left_col_w = 115.0
        display_day = self.selected_date.day
        display_dow = TR_DAYS_FULL.get(self.selected_date.weekday(), "")
        display_my = f"{TR_MONTHS_FULL.get(self.selected_date.month, '')} {self.selected_date.year}"

        # Big Day number (42px bold)
        p.setFont(panel_style.font(42.0, QFont.Weight.ExtraBold, tabular=True))
        p.setPen(panel_style.TEXT)
        p.drawText(QRectF(pad_x + 10.0, tile1_y + 10.0, left_col_w, 44.0), Qt.AlignmentFlag.AlignCenter, str(display_day))

        # Weekday in Blue (#0A84FF)
        p.setFont(panel_style.font(15.0, QFont.Weight.Bold))
        p.setPen(panel_style.ACCENT)
        p.drawText(QRectF(pad_x + 10.0, tile1_y + 54.0, left_col_w, 20.0), Qt.AlignmentFlag.AlignCenter, display_dow)

        # Month & Year
        p.setFont(panel_style.font(11.0, QFont.Weight.Normal))
        p.setPen(panel_style.TEXT_MUTED)
        p.drawText(QRectF(pad_x + 10.0, tile1_y + 75.0, left_col_w, 16.0), Qt.AlignmentFlag.AlignCenter, display_my)

        # Status Pill: "Bugün boş" or "N etkinlik"
        sel_count = len(self._match_events_for_date(self.selected_date, self._cached_upcoming, []))
        if sel_count == 0:
            chip_text = "Bugün boş" if self.selected_date == self.today else "Boş gün"
        else:
            chip_text = f"{sel_count} etkinlik"

        f_chip = panel_style.font(10.0, QFont.Weight.Medium)
        p.setFont(f_chip)
        fm_cp = QFontMetricsF(f_chip)
        chip_w = fm_cp.horizontalAdvance(chip_text) + 16.0
        chip_r = QRectF(pad_x + 10.0 + (left_col_w - chip_w) / 2.0, tile1_y + 98.0, chip_w, 20.0)

        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawPath(panel_style.rounded(chip_r, 6.0))
        p.setPen(panel_style.TEXT_MUTED)
        p.drawText(chip_r, Qt.AlignmentFlag.AlignCenter, chip_text)
        p.restore()

        # Vertical Divider
        div_x = pad_x + 130.0
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        p.drawLine(QPointF(div_x, tile1_y + 12.0), QPointF(div_x, tile1_y + tile1_h - 12.0))

        # Right Column: Upcoming Events List
        right_x = div_x + 14.0
        p.setFont(panel_style.font(10.5, QFont.Weight.Bold))
        p.setPen(panel_style.TEXT_LABEL)
        p.drawText(QRectF(right_x, tile1_y + 11.0, avail_w - 150.0, 16.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "YAKLAŞAN ETKİNLİKLER")

        # Upcoming Event Rows
        for idx, up in enumerate(self._cached_upcoming):
            u_r: QRectF = up["rect"]
            is_hover = (self._hover_upcoming_idx == idx)

            # Dot indicator (6x6)
            dot_cx = u_r.left() + 4.0
            dot_cy = u_r.center().y()
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(up["dot_color"])
            p.drawEllipse(QPointF(dot_cx, dot_cy), 3.0, 3.0)
            p.restore()

            # Date Label (e.g. "28 Eki")
            p.setFont(panel_style.font(11.5, QFont.Weight.DemiBold))
            p.setPen(panel_style.TEXT_MUTED)
            date_r = QRectF(u_r.left() + 14.0, u_r.top(), 48.0, u_r.height())
            p.drawText(date_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, up["date_label"])

            # Title & Amount
            title_x = u_r.left() + 66.0
            title_avail_w = u_r.right() - title_x

            amount = up.get("amount", "")
            raw_title = up["title"]

            f_body = panel_style.font(11.5, QFont.Weight.Normal)
            p.setFont(f_body)

            if amount:
                # Split prefix and amount, keeping connector
                idx_amt = raw_title.find(amount)
                if idx_amt > 0:
                    prefix_display = raw_title[:idx_amt]
                else:
                    prefix_display = "Vergi / ödeme: "
                fm_p = QFontMetricsF(f_body)
                p_w = fm_p.horizontalAdvance(prefix_display)

                p.setPen(panel_style.TEXT if is_hover else panel_style.TEXT_BODY)
                p.drawText(QRectF(title_x, u_r.top(), p_w, u_r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, prefix_display)

                # Bold amber amount
                f_amt = panel_style.font(11.5, QFont.Weight.Bold)
                p.setFont(f_amt)
                p.setPen(panel_style.WARN)
                p.drawText(QRectF(title_x + p_w, u_r.top(), title_avail_w - p_w, u_r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, amount)
            else:
                p.setPen(panel_style.TEXT if is_hover else panel_style.TEXT_BODY)
                fm_t = QFontMetricsF(f_body)
                elided_title = fm_t.elidedText(raw_title, Qt.TextElideMode.ElideRight, title_avail_w)
                p.drawText(QRectF(title_x, u_r.top(), title_avail_w, u_r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # 4. Lower Tile (Month Calendar Grid Tile)
        tile2_y = tile1_y + tile1_h + 12.0
        tile2_h = 236.0
        tile2_r = QRectF(pad_x, tile2_y, avail_w, tile2_h)
        panel_style.draw_tile(p, tile2_r, hover=False)

        # Month & Year title: "Ekim 2026"
        p.setFont(panel_style.font(13.0, QFont.Weight.Bold))
        p.setPen(panel_style.TEXT)
        month_str = f"{TR_MONTHS_FULL.get(self.view_month, '')} {self.view_year}"
        p.drawText(QRectF(pad_x + 14.0, tile2_y + 11.0, 160.0, 22.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, month_str)

        # Navigation Buttons: < and >
        self._rect_btn_prev = QRectF(tile2_r.right() - 56.0, tile2_y + 11.0, 22.0, 22.0)
        self._rect_btn_next = QRectF(tile2_r.right() - 28.0, tile2_y + 11.0, 22.0, 22.0)

        for btn_r, is_h, label in [
            (self._rect_btn_prev, self._hover_prev, "<"),
            (self._rect_btn_next, self._hover_next, ">"),
        ]:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(panel_style.BUTTON_HOVER if is_h else panel_style.BUTTON_BG)
            p.drawPath(panel_style.rounded(btn_r, 6.0))
            p.setFont(panel_style.font(11.0, QFont.Weight.Bold))
            p.setPen(panel_style.TEXT if is_h else panel_style.TEXT_MUTED)
            p.drawText(btn_r, Qt.AlignmentFlag.AlignCenter, label)
            p.restore()

        # Weekday Headers: Pzt Sal Çar Per Cum Cmt Paz
        grid_pad_x = 12.0
        grid_x = pad_x + grid_pad_x
        col_w = (avail_w - 2 * grid_pad_x) / 7.0
        hdr_y = tile2_y + 36.0

        p.setFont(panel_style.font(10.5, QFont.Weight.DemiBold))
        p.setPen(panel_style.TEXT_MUTED)
        for c_idx, dow_str in enumerate(TR_DAYS_SHORT):
            cx_cell = grid_x + c_idx * col_w
            p.drawText(QRectF(cx_cell, hdr_y, col_w, 16.0), Qt.AlignmentFlag.AlignCenter, dow_str)

        # 6x7 Month Grid Cells
        for idx, cell in enumerate(self._cached_cells):
            c_rect: QRectF = cell["rect"]
            is_cur = cell["is_current"]
            is_tod = cell["is_today"]
            is_sel = cell["is_selected"]
            day_text = cell["day_num"]
            dots = cell["dots"]

            cx_c = c_rect.center().x()
            cy_c = c_rect.center().y() - 1.0

            # Today filled bright blue circle (#0A84FF)
            if is_tod:
                circle_r = QRectF(cx_c - 11.5, cy_c - 11.0, 23.0, 23.0)
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(panel_style.ACCENT)
                p.drawEllipse(circle_r)
                p.setFont(panel_style.font(11.5, QFont.Weight.Bold, tabular=True))
                p.setPen(QColor(255, 255, 255))
                p.drawText(circle_r, Qt.AlignmentFlag.AlignCenter, day_text)
                p.restore()
            else:
                # Selected Day subtle ring if not today
                if is_sel:
                    circle_r = QRectF(cx_c - 11.5, cy_c - 11.0, 23.0, 23.0)
                    p.save()
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(panel_style.ACCENT, 1.5))
                    p.drawEllipse(circle_r)
                    p.restore()

                p.setFont(panel_style.font(11.5, QFont.Weight.Medium, tabular=True))
                if is_cur:
                    p.setPen(panel_style.TEXT)
                else:
                    p.setPen(QColor(255, 255, 255, 80))  # dimmed opacity 0.35
                p.drawText(QRectF(c_rect.left(), c_rect.top() + 1.0, c_rect.width(), 16.0), Qt.AlignmentFlag.AlignCenter, day_text)

            # Micro category dots underneath date number
            if dots and not is_tod:
                n_dots = len(dots)
                dot_size = 3.5
                dot_gap = 2.5
                total_dots_w = n_dots * dot_size + (n_dots - 1) * dot_gap
                start_dot_x = cx_c - total_dots_w / 2.0
                dot_y = c_rect.bottom() - 3.5

                for d_i, cat_name in enumerate(dots):
                    d_x = start_dot_x + d_i * (dot_size + dot_gap)
                    if cat_name == "Resmi tatil":
                        d_col = panel_style.DANGER  # #FF453A
                    elif cat_name == "Vergi/ödeme":
                        d_col = panel_style.WARN    # #FF9F0A
                    elif cat_name == "Claude":
                        d_col = panel_style.CLAUDE  # #D97757
                    else:
                        d_col = panel_style.ACCENT  # #0A84FF

                    p.save()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(d_col)
                    p.drawEllipse(QRectF(d_x, dot_y, dot_size, dot_size))
                    p.restore()

        # 5. Footer: Category Legend + Sync Status
        y_footer = tile2_y + tile2_h + 10.0
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(QPointF(0.0, y_footer - 2.0), QPointF(w, y_footer - 2.0))

        # Left Legend: Google, Vergi, Tatil
        legend_items = [
            (panel_style.ACCENT, "Google"),
            (panel_style.WARN, "Vergi"),
            (panel_style.DANGER, "Tatil"),
        ]
        f_leg = panel_style.font(10.0, QFont.Weight.Normal)
        p.setFont(f_leg)
        leg_x = pad_x + 2.0
        leg_y = y_footer + 5.0

        for col, name in legend_items:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QRectF(leg_x, leg_y + 4.5, 5.0, 5.0))
            p.restore()
            p.setPen(panel_style.TEXT_MUTED)
            fm_leg = QFontMetricsF(f_leg)
            text_w = fm_leg.horizontalAdvance(name)
            p.drawText(QRectF(leg_x + 9.0, leg_y, text_w + 4.0, 16.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            leg_x += text_w + 18.0

        # Right Status: "20 etkinlik · Senkronize"
        p.setFont(panel_style.font(10.5, QFont.Weight.Normal))
        p.setPen(panel_style.TEXT_MUTED)
        sync_text = self._cached_footer_sync_text
        self._rect_btn_refresh = QRectF(w - pad_x - 170.0, y_footer + 5.0, 170.0, 16.0)
        p.drawText(self._rect_btn_refresh, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, sync_text)
