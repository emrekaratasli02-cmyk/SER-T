"""Takvim açılır paneli — ortak panel kiti (panel_style v2) üzerinde yeniden yazıldı.

İçerik korunur: ay ızgarası (bugün + etkinlik noktaları), seçili gün listesi, Hermes
takvim dosyalarından gelen yaklaşan etkinlikler, ay gezinme, "Bugün", klavye ve yenileme.
Yeni: son 48 saat içindeki vergi/ödeme etkinliği için tutar kopyalama çipi.

Panel yalnızca önbellekteki veriyi çizer; ağır okuma/yenileme işi dock'un arka plan
işçisindedir. Veri yoksa '—' gösterilir, sayı uydurulmaz.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import unicodedata

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
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

try:
    import logpath
except ImportError:  # pragma: no cover
    logpath = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


def _under_test() -> bool:
    """True inside pytest / test scripts (real clipboard must never be touched)."""
    if logpath is None:
        return False
    try:
        return bool(logpath.is_running_under_test())
    except Exception:
        return False


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

CAT_GOOGLE = "Google Takvim"
CAT_TAX = "Vergi/ödeme"
CAT_HOLIDAY = "Resmi tatil"
CAT_CLAUDE = "Claude"

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

# Layout ölçüleri (kit dışında kalan takvime özel değerler)
ROW_H = 32.0              # etkinlik satırı (3 x 28 px şerit + iki metin satırı)
ROW_GAP = 6.0
EMPTY_ROW_H = 24.0
GRID_HEADER_H = 18.0
GRID_ROW_H = 30.0         # gün hücresi yüksekliği (istenen: 30 px)
TAX_CHIP_H = 38.0
MONTH_CARD_OVER_H = 25.0  # draw_card üst başlık (15) + boşluk (10)
TAX_KEYWORDS = ("kdv", "vergi", "sgk", "bağ-kur", "bag-kur")

_AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2})\s*TL\b", re.IGNORECASE)


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


def _amount_match(text: Any):
    """Return the regex match for a Turkish amount followed by TL, else None."""
    if text is None:
        return None
    return _AMOUNT_RE.search(str(text))


def parse_turkish_amount(title: Any) -> Optional[str]:
    """'1.234,56 TL' -> '1.234,56'; '6.432,80 TL' -> '6.432,80'; yoksa None."""
    m = _amount_match(title)
    return m.group(1) if m else None


def is_tax_item(title: Any, category: Any = None) -> bool:
    """Mevcut 'Vergi/ödeme' kategorisi veya KDV/Vergi/SGK/Bağ-Kur geçen başlık."""
    if category == CAT_TAX:
        return True
    low = str(title or "").casefold()
    return any(kw in low for kw in TAX_KEYWORDS)


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
            "category": CAT_HOLIDAY,
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
                        "category": CAT_CLAUDE,
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
                "category": CAT_CLAUDE,
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
    path = panel_style.rounded(box_r, 4.0)
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


def _category_color(category: str) -> QColor:
    if category == CAT_HOLIDAY:
        return panel_style.DANGER
    if category == CAT_TAX:
        return panel_style.WARN
    if category == CAT_CLAUDE:
        return panel_style.CLAUDE
    return panel_style.ACCENT


def _event_start_local(st: Any, local_tz: dt.tzinfo) -> Optional[dt.datetime]:
    """Event start as timezone-aware local datetime (all-day -> 00:00)."""
    if isinstance(st, dt.datetime):
        return st.astimezone(local_tz) if st.tzinfo else st.replace(tzinfo=local_tz)
    if isinstance(st, dt.date):
        return dt.datetime.combine(st, dt.time.min).replace(tzinfo=local_tz)
    return None


def _write_clipboard(text: str) -> bool:
    """Write to the real clipboard. Under tests this is a no-op (owner's clipboard safe)."""
    if _under_test():
        return False
    try:
        QGuiApplication.clipboard().setText(text)
        return True
    except Exception as exc:
        _log_err("calendar_clipboard", exc)
        return False


class CalendarPanel(QWidget):
    """Takvim paneli: 440 px geniş, çok sütunlu ay ızgarası + gündem + vergi kopyalama çipi."""

    WIDTH: int = int(panel_style.WIDTH["cal"])
    HEIGHT: int = 660
    RADIUS: float = panel_style.R_PANEL

    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Internal state
        self._anchor_global: Optional[QRectF] = None
        self._anchor_rect_global: Optional[QRectF] = None
        self._month_data: Dict[str, Any] = {}
        self._claude_data: Dict[str, Any] = {}

        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        now_local = dt.datetime.now(local_tz)
        self._now_override: Optional[dt.datetime] = None
        self.today: dt.date = now_local.date()
        self.selected_date: dt.date = self.today
        self.view_year: int = self.today.year
        self.view_month: int = self.today.month

        # Focus / close tracking
        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Hover states
        self._hover_close: bool = False
        self._hover_prev: bool = False
        self._hover_today: bool = False
        self._hover_next: bool = False
        self._hover_tax: bool = False
        self._hover_footer: bool = False
        self._hover_cell_idx: int = -1
        self._hover_selected_idx: int = -1
        self._hover_upcoming_idx: int = -1

        # Fixed hit rects (layout bunları her rebuild'de tazeler)
        self._rect_close = QRectF()
        self._rect_btn_prev = QRectF()
        self._rect_btn_today = QRectF()
        self._rect_btn_next = QRectF()
        self._rect_btn_refresh = QRectF()
        self._tax_chip_rect = QRectF()

        # Layout / data caches
        self._layout: Dict[str, Any] = {}
        self._cached_cells: List[Dict[str, Any]] = []
        self._cached_selected_events: List[Dict[str, Any]] = []
        self._cached_selected_cards: List[Dict[str, Any]] = []
        self._cached_upcoming: List[Dict[str, Any]] = []
        self._cached_month_event_count: int = 0
        self._cached_selected_header_text: str = ""
        self._cached_footer_source: str = "Google Takvim · —"
        self._tax_chip: Optional[Dict[str, Any]] = None
        self._tax_copied: bool = False

        self._tax_copy_timer = QTimer(self)
        self._tax_copy_timer.setSingleShot(True)
        self._tax_copy_timer.timeout.connect(self._reset_tax_copied)

        self.resize(self.WIDTH, self.HEIGHT)
        self._rebuild_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
        switch_from_x: Optional[int] = None,
    ) -> None:
        """Position centered above anchor, apply rounded region, and animate in."""
        try:
            self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
            self._anchor_rect_global = self._anchor_global
            self._month_data = month_data if isinstance(month_data, dict) else {}
            self._claude_data = claude_data if isinstance(claude_data, dict) else {}

            if not hasattr(self, "selected_date") or self.selected_date is None:
                local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
                self.selected_date = dt.datetime.now(local_tz).date()

            self._rebuild_cache()

            # Positioning above anchor (8px gap), clamped inside screen geometry
            dpr = 1.0
            target = QPoint(int(self.x()), int(self.y()))
            if self._anchor_global is not None:
                anchor_cx = self._anchor_global.center().x()
                target_x = int(anchor_cx - self.width() / 2.0)
                target_y = int(self._anchor_global.top() - self.height() - panel_style.ANCHOR_GAP)

                center_pt = self._anchor_global.center().toPoint()
                screen = QGuiApplication.screenAt(center_pt) or QGuiApplication.primaryScreen()
                if screen is not None:
                    geom = screen.availableGeometry()
                    dpr = screen.devicePixelRatio()
                    margin = 8
                    min_x = geom.left() + margin
                    max_x = geom.right() - self.width() - margin
                    target_x = max(min_x, min(max_x, target_x)) if max_x >= min_x else min_x

                    min_y = geom.top() + margin
                    max_y = geom.bottom() - self.height() - margin
                    if target_y < min_y:
                        below_y = int(self._anchor_global.bottom() + panel_style.ANCHOR_GAP)
                        if below_y + self.height() <= geom.bottom() - margin:
                            target_y = below_y
                        else:
                            target_y = min_y
                    elif target_y > max_y:
                        target_y = max_y
                target = QPoint(int(target_x), int(target_y))

            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(panel_style.R_PANEL), dpr)
                except Exception:
                    pass

            self._is_closing = False
            panel_style.animate_in(self, target, switch_from_x=switch_from_x)
            self.activateWindow()
            self.setFocus()
        except Exception as exc:
            _log_err("calendar_show_for", exc)

    def hide_animated(self) -> None:
        """Trigger the shared close animation, then hide."""
        if not self.isVisible() or self._is_closing:
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()
        panel_style.animate_out(self, on_done=self._on_closed)

    def hide_instant(self) -> None:
        """Close without animation (e.g. switching to another capsule panel)."""
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._is_closing = False
        panel_style.animate_out(self, instant=True)

    def _on_closed(self) -> None:
        self._is_closing = False

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
        now_local = self._now_override or dt.datetime.now(local_tz)
        if now_local.tzinfo is None:
            now_local = now_local.replace(tzinfo=local_tz)
        else:
            now_local = now_local.astimezone(local_tz)
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

    def copy_tax_amount(self) -> None:
        """Copy the tax amount exactly as written (skipped under tests)."""
        if not self._tax_chip:
            return
        _write_clipboard(str(self._tax_chip.get("amount") or ""))
        self._tax_copied = True
        self._tax_copy_timer.start(1500)
        self.update()

    def _reset_tax_copied(self) -> None:
        self._tax_copied = False
        self.update()

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current calendar panel offscreen to a high-DPI ARGB32 QImage."""
        w_phys = max(1, int(self.width() * dpr))
        h_phys = max(1, int(self.height() * dpr))
        img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint_panel(p)
        p.end()
        return img

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    def wheelEvent(self, event) -> None:
        """Tekerlek: yukarı = önceki ay, aşağı = sonraki ay. Dokunmatik yüzeyde küçük adımlar
        biriktirilir; bir çentik (120) dolunca tek ay ilerler, tek harekette en fazla 1 ay."""
        dy = event.angleDelta().y()
        if not dy:
            dy = event.pixelDelta().y() * 4
        if not dy:
            super().wheelEvent(event)
            return
        acc = getattr(self, "_wheel_acc", 0) + dy
        if (acc > 0) != (dy > 0):
            acc = dy
        if acc >= 120:
            self.prev_month()
            acc = 0
        elif acc <= -120:
            self.next_month()
            acc = 0
        self._wheel_acc = acc
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self.select_date(self.selected_date - dt.timedelta(days=1))
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self.select_date(self.selected_date + dt.timedelta(days=1))
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.select_date(self.selected_date - dt.timedelta(days=7))
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self.select_date(self.selected_date + dt.timedelta(days=7))
            event.accept()
            return
        if key == Qt.Key.Key_PageUp:
            self.prev_month()
            event.accept()
            return
        if key == Qt.Key.Key_PageDown:
            self.next_month()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                cursor_pos = QCursor.pos()
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(cursor_pos)):
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

    def _hit(self, pos: QPointF) -> Optional[str]:
        if self._rect_close.contains(pos):
            return "close"
        if self._tax_chip_rect.contains(pos) and self._tax_chip:
            return "tax"
        if self._rect_btn_prev.contains(pos):
            return "prev"
        if self._rect_btn_today.contains(pos):
            return "today"
        if self._rect_btn_next.contains(pos):
            return "next"
        for idx, item in enumerate(self._cached_selected_events):
            if item["rect"].contains(pos):
                return f"selected:{idx}"
        for idx, item in enumerate(self._cached_upcoming):
            if item["rect"].contains(pos):
                return f"upcoming:{idx}"
        for idx, cell in enumerate(self._cached_cells):
            if cell["rect"].contains(pos):
                return f"cell:{idx}"
        if self._rect_btn_refresh.contains(pos):
            return "footer"
        return None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        close = self._rect_close.contains(pos)
        tax = bool(self._tax_chip) and self._tax_chip_rect.contains(pos)
        prev = self._rect_btn_prev.contains(pos)
        today = self._rect_btn_today.contains(pos)
        nxt = self._rect_btn_next.contains(pos)
        footer = self._rect_btn_refresh.contains(pos)

        sel_idx = -1
        for idx, item in enumerate(self._cached_selected_events):
            if item["rect"].contains(pos):
                sel_idx = idx
                break
        up_idx = -1
        for idx, item in enumerate(self._cached_upcoming):
            if item["rect"].contains(pos):
                up_idx = idx
                break
        cell_idx = -1
        for idx, cell in enumerate(self._cached_cells):
            if cell["rect"].contains(pos):
                cell_idx = idx
                break

        if (close, tax, prev, today, nxt, footer, sel_idx, up_idx, cell_idx) != (
            self._hover_close, self._hover_tax, self._hover_prev, self._hover_today,
            self._hover_next, self._hover_footer, self._hover_selected_idx,
            self._hover_upcoming_idx, self._hover_cell_idx,
        ):
            self._hover_close = close
            self._hover_tax = tax
            self._hover_prev = prev
            self._hover_today = today
            self._hover_next = nxt
            self._hover_footer = footer
            self._hover_selected_idx = sel_idx
            self._hover_upcoming_idx = up_idx
            self._hover_cell_idx = cell_idx
            self.update()

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit(event.position())
            if hit == "close":
                self.hide_animated()
                event.accept()
                return
            if hit == "tax":
                self.copy_tax_amount()
                event.accept()
                return
            if hit == "prev":
                self.prev_month()
                event.accept()
                return
            if hit == "today":
                self.go_today()
                event.accept()
                return
            if hit == "next":
                self.next_month()
                event.accept()
                return
            if hit == "footer":
                self.trigger_refresh()
                event.accept()
                return
            if hit and hit.startswith("cell:"):
                idx = int(hit.split(":", 1)[1])
                self.select_date(self._cached_cells[idx]["date"])
                event.accept()
                return
            if hit and hit.startswith("selected:"):
                idx = int(hit.split(":", 1)[1])
                self._open_event_link(self._cached_selected_events[idx])
                event.accept()
                return
            if hit and hit.startswith("upcoming:"):
                idx = int(hit.split(":", 1)[1])
                item = self._cached_upcoming[idx]
                self._open_event_link(item)
                target = item.get("target_date")
                if isinstance(target, dt.date):
                    self.select_date(target)
                event.accept()
                return
        super().mousePressEvent(event)

    def _open_event_link(self, item: Dict[str, Any]) -> None:
        link = item.get("link")
        if isinstance(link, str) and link.startswith("http"):
            try:
                QDesktopServices.openUrl(QUrl(link))
            except Exception as exc:
                _log_err("calendar_open_url", exc)

    def leaveEvent(self, event) -> None:
        self._hover_close = False
        self._hover_prev = False
        self._hover_today = False
        self._hover_next = False
        self._hover_tax = False
        self._hover_footer = False
        self._hover_cell_idx = -1
        self._hover_selected_idx = -1
        self._hover_upcoming_idx = -1
        self.update()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Cache / layout
    # ------------------------------------------------------------------
    def _now(self) -> dt.datetime:
        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        if isinstance(self._now_override, dt.datetime):
            now = self._now_override
            return now.astimezone(local_tz) if now.tzinfo else now.replace(tzinfo=local_tz)
        return dt.datetime.now(local_tz)

    def _selected_header(self) -> str:
        if self.selected_date == self.today:
            prefix = "Bugün · "
        elif self.selected_date == (self.today + dt.timedelta(days=1)):
            prefix = "Yarın · "
        else:
            prefix = ""
        dow = TR_DAYS_FULL.get(self.selected_date.weekday(), "")
        month = TR_MONTHS_FULL.get(self.selected_date.month, "")
        return f"{prefix}{dow}, {self.selected_date.day} {month}"

    def _date_label(self, d: dt.date) -> str:
        return f"{d.day} {TR_MONTHS_SHORT.get(d.month, '')} {TR_DAYS_SHORT[d.weekday()]}"

    def _event_time_label(self, ev: Dict[str, Any]) -> str:
        sub = ev.get("sub")
        if isinstance(sub, str) and sub:
            return sub
        st = ev.get("start")
        if isinstance(st, dt.datetime):
            local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            local_st = st.astimezone(local_tz) if st.tzinfo else st.replace(tzinfo=local_tz)
            return local_st.strftime("%H:%M")
        return "Tüm gün"

    def _display_row(self, ev: Dict[str, Any], target_date: dt.date, date_label: str) -> Dict[str, Any]:
        title = clean_title(ev.get("title", ""))
        category = str(ev.get("category") or CAT_GOOGLE)
        m = _amount_match(title)
        amount = m.group(0).strip() if m else ""
        return {
            "title": title,
            "category": category,
            "start": ev.get("start"),
            "all_day": bool(ev.get("all_day", False)),
            "link": ev.get("link", ""),
            "target_date": target_date,
            "date_label": date_label,
            "amount": amount,
            "dot_color": _category_color(category),
            "strip_color": _category_color(category),
            "sub": f"{self._event_time_label(ev)} · {category}",
            "rect": QRectF(),
        }

    def _find_tax_chip(self, events: List[Dict[str, Any]], now_local: dt.datetime) -> Optional[Dict[str, Any]]:
        """First tax event within the next 48 h whose title carries a Turkish TL amount."""
        candidates: List[Tuple[dt.datetime, Dict[str, Any], str, str]] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            title = clean_title(ev.get("title", ""))
            if not is_tax_item(title, ev.get("category")):
                continue
            m = _amount_match(title)
            if not m:
                continue
            start = _event_start_local(ev.get("start"), now_local.tzinfo or dt.timezone.utc)
            if start is None:
                continue
            delta = (start - now_local).total_seconds()
            if delta < 0.0 or delta > 48.0 * 3600.0:
                continue
            candidates.append((start, ev, m.group(1), m.group(0).strip()))

        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0])
        start, _ev, amount, _amount_text = candidates[0]

        # Chip metni: emoji ve "Vergi:" ön eki atılır, tutar sonda tek kez kalır.
        title = re.sub(r"^\s*vergi\s*:\s*", "", clean_title(_ev.get("title", "")), flags=re.IGNORECASE)
        m = _amount_match(title)
        base = title
        if m:
            base = re.sub(r"\s{2,}", " ", (title[:m.start()] + title[m.end():])).strip(" -–—·:,")
        label = f"{base} · {amount} TL" if base else f"{amount} TL"
        return {
            "label": label,
            "amount": amount,
            "start": start,
            "event": _ev,
        }

    def _compute_layout(self) -> Dict[str, Any]:
        cw = float(self.WIDTH) - 2.0 * panel_style.PAD
        y = panel_style.PAD + panel_style.HEADER_H + panel_style.GAP

        tax_rect: Optional[QRectF] = None
        if self._tax_chip:
            tax_rect = QRectF(panel_style.PAD, y, cw, TAX_CHIP_H)
            y += TAX_CHIP_H + panel_style.GAP

        n_sel = len(self._cached_selected_events)
        sel_rows_h = (n_sel * ROW_H + max(0, n_sel - 1) * ROW_GAP) if n_sel else EMPTY_ROW_H
        sel_card_h = 2.0 * panel_style.CARD_PAD + MONTH_CARD_OVER_H + sel_rows_h
        sel_rect = QRectF(panel_style.PAD, y, cw, sel_card_h)
        y += sel_card_h + panel_style.GAP

        n_up = len(self._cached_upcoming)
        up_rows_h = (n_up * ROW_H + max(0, n_up - 1) * ROW_GAP) if n_up else EMPTY_ROW_H
        up_card_h = 2.0 * panel_style.CARD_PAD + MONTH_CARD_OVER_H + up_rows_h
        up_rect = QRectF(panel_style.PAD, y, cw, up_card_h)
        y += up_card_h + panel_style.GAP

        month_card_h = (2.0 * panel_style.CARD_PAD + MONTH_CARD_OVER_H
                        + GRID_HEADER_H + 6.0 * GRID_ROW_H)
        month_rect = QRectF(panel_style.PAD, y, cw, month_card_h)
        y += month_card_h + panel_style.GAP

        footer_rect = QRectF(panel_style.PAD, y, cw, panel_style.FOOTER_H)
        total = y + panel_style.FOOTER_H + panel_style.PAD * 0.5

        row_x = panel_style.PAD + panel_style.CARD_PAD
        row_w = cw - 2.0 * panel_style.CARD_PAD
        sel_content_top = sel_rect.top() + panel_style.CARD_PAD + MONTH_CARD_OVER_H
        up_content_top = up_rect.top() + panel_style.CARD_PAD + MONTH_CARD_OVER_H
        sel_rows = [QRectF(row_x, sel_content_top + i * (ROW_H + ROW_GAP), row_w, ROW_H)
                    for i in range(n_sel)]
        up_rows = [QRectF(row_x, up_content_top + i * (ROW_H + ROW_GAP), row_w, ROW_H)
                   for i in range(n_up)]

        grid_y = month_rect.top() + panel_style.CARD_PAD + MONTH_CARD_OVER_H + GRID_HEADER_H
        col_w = row_w / 7.0

        layout = {
            "tax": tax_rect,
            "selected_card": sel_rect,
            "upcoming_card": up_rect,
            "month_card": month_rect,
            "footer": footer_rect,
            "selected_rows": sel_rows,
            "upcoming_rows": up_rows,
            "grid_y": grid_y,
            "grid_x": row_x,
            "col_w": col_w,
            "total": total,
        }

        # Header close (draw_header ile aynı hesap)
        close_sz = min(panel_style.CLOSE_SZ, panel_style.HEADER_H)
        self._rect_close = QRectF(
            self.WIDTH - panel_style.PAD - close_sz,
            panel_style.PAD + (panel_style.HEADER_H - close_sz) / 2.0,
            close_sz, close_sz,
        )
        self._tax_chip_rect = QRectF(tax_rect) if tax_rect is not None else QRectF()
        self._rect_btn_prev, self._rect_btn_today, self._rect_btn_next = self._nav_rects(month_rect)
        self._rect_btn_refresh = self._footer_button_rect(footer_rect)
        return layout

    def _nav_rects(self, month_rect: QRectF) -> Tuple[QRectF, QRectF, QRectF]:
        f = panel_style.font(10.5, QFont.Weight.DemiBold)
        fm = QFontMetricsF(f)
        over_top = month_rect.top() + panel_style.CARD_PAD
        right = month_rect.right() - panel_style.CARD_PAD
        nav = "‹  Bugün  ›"
        x = right - fm.horizontalAdvance(nav)
        w_prev = fm.horizontalAdvance("‹")
        w_today = fm.horizontalAdvance("Bugün")
        x_prev = x
        x_today = x + fm.horizontalAdvance("‹  ")
        x_next = x + fm.horizontalAdvance("‹  Bugün  ")
        h = 15.0
        pad_y = 5.0
        return (
            QRectF(x_prev - 3.0, over_top - pad_y, w_prev + 6.0, h + 2 * pad_y),
            QRectF(x_today - 4.0, over_top - pad_y, w_today + 8.0, h + 2 * pad_y),
            QRectF(x_next - 3.0, over_top - pad_y, fm.horizontalAdvance("›") + 6.0, h + 2 * pad_y),
        )

    def _footer_button_rect(self, footer_rect: QRectF) -> QRectF:
        f = panel_style.font(11.5, QFont.Weight.Medium)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance("Senkronize")
        content_h = max(0.0, footer_rect.height() - 3.0)
        btn_w = min(tw + 20.0, max(28.0, footer_rect.width() * 0.55))
        btn_h = min(24.0, content_h)
        cy = footer_rect.top() + 3.0 + content_h / 2.0
        return QRectF(footer_rect.right() - btn_w, cy - btn_h / 2.0, btn_w, btn_h)

    def compute_height(self) -> int:
        layout = self._compute_layout()
        return int(math.ceil(layout["total"]))

    def _rebuild_cache(self) -> None:
        """Compute month grid, agenda rows, tax chip and hit rects for fast painting."""
        now_local = self._now()
        self.today = now_local.date()

        # 1. All events: Google month events + holidays + Claude markers
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

        cat_prio = {CAT_HOLIDAY: 0, CAT_TAX: 1, CAT_CLAUDE: 2, CAT_GOOGLE: 3}

        # 2. Selected day agenda
        sel_events = self._match_events_for_date(self.selected_date, events_list, claude_markers)
        sel_events.sort(key=lambda ev: (cat_prio.get(str(ev.get("category") or CAT_GOOGLE), 9),
                                        self._event_time_label(ev)))
        sel_label = self._date_label(self.selected_date)
        self._cached_selected_events = [
            self._display_row(ev, self.selected_date, sel_label) for ev in sel_events[:4]
        ]

        # 3. Upcoming events (from today / selected date, max 4). v24: the selected day is already listed in
        # its own card above, so "Yaklaşan" skips it (it used to repeat e.g. a holiday in both cards).
        ref_start_date = min(self.today, self.selected_date)
        upcoming_items: List[Dict[str, Any]] = []
        for i in range(45):
            f_date = ref_start_date + dt.timedelta(days=i)
            if f_date == self.selected_date:
                continue
            matches = self._match_events_for_date(f_date, events_list, claude_markers)
            matches.sort(key=lambda ev: cat_prio.get(str(ev.get("category") or CAT_GOOGLE), 9))
            for ev in matches:
                upcoming_items.append(
                    self._display_row(ev, f_date, self._date_label(f_date))
                )
                if len(upcoming_items) >= 4:
                    break
            if len(upcoming_items) >= 4:
                break
        self._cached_upcoming = upcoming_items

        # 4. Tax copy chip (next 48 h, tax/payment with a Turkish TL amount)
        self._tax_chip = self._find_tax_chip(events_list, now_local)
        if not self._tax_chip:
            self._tax_copied = False

        # 5. Layout + row hit rects
        self._cached_selected_header_text = self._selected_header()
        self._layout = self._compute_layout()
        for item, rect in zip(self._cached_selected_events, self._layout["selected_rows"]):
            item["rect"] = QRectF(rect)
        for item, rect in zip(self._cached_upcoming, self._layout["upcoming_rows"]):
            item["rect"] = QRectF(rect)
        self._cached_selected_cards = self._cached_selected_events

        # 6. Month grid (6x7 cells) + month event count
        first_day = dt.date(self.view_year, self.view_month, 1)
        grid_start_date = first_day - dt.timedelta(days=first_day.weekday())
        grid_x = self._layout["grid_x"]
        grid_y = self._layout["grid_y"]
        col_w = self._layout["col_w"]

        cells: List[Dict[str, Any]] = []
        month_event_count = 0
        cat_order = [CAT_TAX, CAT_HOLIDAY, CAT_CLAUDE, CAT_GOOGLE]
        for idx in range(42):
            cell_date = grid_start_date + dt.timedelta(days=idx)
            row = idx // 7
            col = idx % 7
            c_rect = QRectF(grid_x + col * col_w, grid_y + row * GRID_ROW_H, col_w, GRID_ROW_H)
            day_events = self._match_events_for_date(cell_date, events_list, claude_markers)
            if cell_date.month == self.view_month:
                month_event_count += len(day_events)
            cats_present: Set[str] = {str(ev.get("category") or CAT_GOOGLE) for ev in day_events}
            dots = [c for c in cat_order if c in cats_present][:3]
            cells.append({
                "date": cell_date,
                "rect": c_rect,
                "day_num": str(cell_date.day),
                "is_current": cell_date.month == self.view_month,
                "is_today": cell_date == self.today,
                "is_selected": cell_date == self.selected_date,
                "dots": dots,
            })
        self._cached_cells = cells
        self._cached_month_event_count = month_event_count

        # 7. Footer source ("Google Takvim · HH:MM")
        updated = self._month_data.get("updated")
        stamp = "—"
        if isinstance(updated, str) and updated.strip():
            stamp = updated.strip()
            if "T" in stamp:
                try:
                    stamp = dt.datetime.fromisoformat(stamp).strftime("%H:%M")
                except (ValueError, TypeError):
                    stamp = "—"
        self._cached_footer_source = f"Google Takvim · {stamp}"

        # 8. Keep the window tightly sized to its content
        new_h = int(math.ceil(self._layout["total"]))
        if self.height() != new_h:
            self.resize(self.WIDTH, new_h)

    def _match_events_for_date(
        self,
        d: dt.date,
        events: List[Dict[str, Any]],
        claude_markers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return all events covering target date d."""
        matched: List[Dict[str, Any]] = []

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
                elif d == st_date:
                    matched.append(ev)
            else:
                if en_date and en_date > st_date:
                    if st_date <= d <= en_date:
                        matched.append(ev)
                elif d == st_date:
                    matched.append(ev)

        matched.extend(get_holiday_events_for_date(d))

        for cm in claude_markers:
            c_st = cm.get("start")
            c_date = c_st.date() if isinstance(c_st, dt.datetime) else c_st if isinstance(c_st, dt.date) else None
            if c_date == d:
                matched.append(cm)

        return matched

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        try:
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                self._paint_panel(p)
            finally:
                p.end()
        except Exception as e:
            _log_err("CalendarPanel.paintEvent", e)

    def _paint_panel(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        panel_style.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))

        # Header: icon + "Takvim" + one chip (event count) + ×
        chip = (f"{self._cached_month_event_count} etkinlik"
                if self._cached_month_event_count else "Etkinlik yok")
        panel_style.draw_header(
            p,
            QRectF(panel_style.PAD, panel_style.PAD,
                   w - 2.0 * panel_style.PAD, panel_style.HEADER_H),
            "Takvim",
            icon=self._header_icon,
            chip=chip,
            close_hover=self._hover_close,
        )

        self._paint_tax_chip(p)
        self._paint_selected_card(p)
        self._paint_upcoming_card(p)
        self._paint_month_card(p)
        self._paint_footer(p)

    def _header_icon(self, p: QPainter, r: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(110, 168, 254, 38))
        p.drawPath(panel_style.rounded(r, panel_style.R_ICON_BOX))
        draw_calendar_icon(p, r.adjusted(2.0, 2.0, -2.0, -2.0), self.today.day)
        p.restore()

    def _paint_tax_chip(self, p: QPainter) -> None:
        chip = self._tax_chip
        if not chip:
            return
        r = self._layout.get("tax")
        if not isinstance(r, QRectF):
            return

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor(255, 159, 10, 44 if self._hover_tax else 28)
        border = QColor(255, 159, 10, 115 if self._hover_tax else 80)
        p.setPen(QPen(border, 1.0))
        p.setBrush(bg)
        p.drawPath(panel_style.rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), 10.0))

        # Sol kehribar işaret
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel_style.WARN)
        p.drawPath(panel_style.rounded(
            QRectF(r.left() + 12.0, r.center().y() - 8.0, 3.0, 16.0), 1.5))

        # Sağ eylem: Kopyala / Kopyalandı ✓
        f_right = panel_style.font(11.5, QFont.Weight.DemiBold)
        fm_r = QFontMetricsF(f_right)
        right_text = "Kopyalandı ✓" if self._tax_copied else "Kopyala"
        right_w = fm_r.horizontalAdvance(right_text)
        right_rect = QRectF(r.right() - 12.0 - right_w, r.top(), right_w, r.height())
        p.setFont(f_right)
        p.setPen(panel_style.OK if self._tax_copied else panel_style.WARN)
        p.drawText(right_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right_text)

        # Sol metin: başlık · tutar TL
        f_left = panel_style.font(11.5, QFont.Weight.Medium)
        fm_l = QFontMetricsF(f_left)
        left_x = r.left() + 23.0
        avail = max(10.0, right_rect.left() - 10.0 - left_x)
        p.setFont(f_left)
        p.setPen(panel_style.TEXT if self._hover_tax else panel_style.TEXT_BODY)
        p.drawText(
            QRectF(left_x, r.top(), avail, r.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_l.elidedText(str(chip.get("label") or "—"), Qt.TextElideMode.ElideRight, avail),
        )
        p.restore()

    def _paint_selected_card(self, p: QPainter) -> None:
        rect = self._layout.get("selected_card")
        if not isinstance(rect, QRectF):
            return
        count = len(self._cached_selected_events)
        status = f"{count} etkinlik" if count else "Boş"
        inner = panel_style.draw_card(p, rect, self._cached_selected_header_text, status)
        if not self._cached_selected_events:
            p.save()
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            text = "Bugün boş" if self.selected_date == self.today else "Etkinlik yok"
            p.drawText(inner, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            p.restore()
            return
        for idx, item in enumerate(self._cached_selected_events):
            self._paint_event_row(p, item["rect"], item, self._hover_selected_idx == idx)

    def _paint_upcoming_card(self, p: QPainter) -> None:
        rect = self._layout.get("upcoming_card")
        if not isinstance(rect, QRectF):
            return
        count = len(self._cached_upcoming)
        inner = panel_style.draw_card(
            p, rect, "Yaklaşan etkinlikler", f"{count} etkinlik" if count else None)
        if not self._cached_upcoming:
            p.save()
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            p.drawText(inner, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Yaklaşan etkinlik yok")
            p.restore()
            return
        for idx, item in enumerate(self._cached_upcoming):
            self._paint_event_row(p, item["rect"], item, self._hover_upcoming_idx == idx)

    def _paint_event_row(self, p: QPainter, rect: QRectF, item: Dict[str, Any], hover: bool) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawPath(panel_style.rounded(rect.adjusted(0.0, 1.0, 0.0, -1.0), 8.0))

        # 3 x 28 px renkli sol şerit
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(item.get("strip_color") or panel_style.ACCENT)
        p.drawPath(panel_style.rounded(
            QRectF(rect.left() + 2.0, rect.center().y() - 14.0, 3.0, 28.0), 1.5))

        text_x = rect.left() + 12.0
        text_w = max(10.0, rect.right() - text_x)
        title = str(item.get("title") or "(Başlıksız)")
        amount = str(item.get("amount") or "")

        f_title = panel_style.font(12.0, QFont.Weight.Medium)
        fm_t = QFontMetricsF(f_title)
        title_rect = QRectF(text_x, rect.top() + 3.0, text_w, 16.0)
        p.setFont(f_title)

        idx_amt = title.find(amount) if amount else -1
        if amount and idx_amt > 0:
            prefix = title[:idx_amt]
            f_amt = panel_style.font(12.0, QFont.Weight.Bold)
            fm_amt = QFontMetricsF(f_amt)
            amt_w = fm_amt.horizontalAdvance(amount)
            prefix = fm_t.elidedText(prefix, Qt.TextElideMode.ElideRight, max(10.0, text_w - amt_w))
            p.setPen(panel_style.TEXT_BODY)
            p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, prefix)
            prefix_w = fm_t.horizontalAdvance(prefix)
            p.setFont(f_amt)
            p.setPen(panel_style.WARN)
            p.drawText(QRectF(text_x + prefix_w, title_rect.top(), amt_w + 2.0, title_rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, amount)
        else:
            p.setPen(panel_style.TEXT_BODY)
            p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm_t.elidedText(title, Qt.TextElideMode.ElideRight, text_w))

        f_sub = panel_style.font(10.5, QFont.Weight.Normal)
        fm_s = QFontMetricsF(f_sub)
        p.setFont(f_sub)
        p.setPen(panel_style.TEXT_MUTED)
        p.drawText(QRectF(text_x, rect.top() + 17.0, text_w, 12.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm_s.elidedText(str(item.get("sub") or "—"), Qt.TextElideMode.ElideRight, text_w))
        p.restore()

    def _paint_month_card(self, p: QPainter) -> None:
        rect = self._layout.get("month_card")
        if not isinstance(rect, QRectF):
            return
        month_name = f"{TR_MONTHS_FULL.get(self.view_month, '')} {self.view_year}"
        inner = panel_style.draw_card(
            p, rect, f"Aylık takvim · {month_name}", "‹  Bugün  ›")

        # Gezinme hover göstergesi (draw_card metni zaten çizdi)
        over_top = rect.top() + panel_style.CARD_PAD
        for hovered, nav_rect in (
            (self._hover_prev, self._rect_btn_prev),
            (self._hover_today, self._rect_btn_today),
            (self._hover_next, self._rect_btn_next),
        ):
            if hovered:
                p.save()
                p.setPen(QPen(panel_style.ACCENT, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(nav_rect.left() + 3.0, over_top + 14.0),
                           QPointF(nav_rect.right() - 3.0, over_top + 14.0))
                p.restore()

        # Hafta günleri
        weekday_y = inner.top()
        f_wd = panel_style.font(10.0, QFont.Weight.DemiBold)
        p.setFont(f_wd)
        for c_idx, dow_str in enumerate(TR_DAYS_SHORT):
            is_current_dow = (
                self.view_year == self.today.year
                and self.view_month == self.today.month
                and c_idx == self.today.weekday()
            )
            p.setPen(panel_style.ACCENT if is_current_dow else panel_style.TEXT_LABEL)
            p.drawText(QRectF(inner.left() + c_idx * self._layout["col_w"], weekday_y,
                              self._layout["col_w"], GRID_HEADER_H),
                       Qt.AlignmentFlag.AlignCenter, dow_str)

        # 6 x 7 gün hücreleri
        for idx, cell in enumerate(self._cached_cells):
            c_rect: QRectF = cell["rect"]
            is_cur = bool(cell["is_current"])
            is_tod = bool(cell["is_today"])
            is_sel = bool(cell["is_selected"])
            hovered = self._hover_cell_idx == idx
            dots = cell.get("dots") or []

            if is_tod:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(panel_style.ACCENT)
                p.drawPath(panel_style.rounded(
                    QRectF(c_rect.left() + 2.0, c_rect.top() + 1.0,
                           c_rect.width() - 4.0, c_rect.height() - 2.0), 7.0))
                p.restore()
            elif is_sel:
                p.save()
                p.setPen(QPen(panel_style.ACCENT, 1.2))
                p.setBrush(QColor(110, 168, 254, 38))
                p.drawPath(panel_style.rounded(
                    QRectF(c_rect.left() + 2.0, c_rect.top() + 1.0,
                           c_rect.width() - 4.0, c_rect.height() - 2.0), 7.0))
                p.restore()
            elif hovered:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 12))
                p.drawPath(panel_style.rounded(
                    QRectF(c_rect.left() + 2.0, c_rect.top() + 1.0,
                           c_rect.width() - 4.0, c_rect.height() - 2.0), 7.0))
                p.restore()

            if is_tod:
                p.setPen(QColor(255, 255, 255))
            elif is_cur:
                p.setPen(panel_style.TEXT)
            else:
                p.setPen(QColor(255, 255, 255, 76))
            p.setFont(panel_style.font(11.5, QFont.Weight.Bold if is_tod else QFont.Weight.Medium,
                                       tabular=True))
            p.drawText(QRectF(c_rect.left(), c_rect.top() + 4.0, c_rect.width(), 14.0),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, cell["day_num"])

            if dots:
                dot_size = 4.0
                dot_gap = 2.0
                total_w = len(dots) * dot_size + (len(dots) - 1) * dot_gap
                start_x = c_rect.center().x() - total_w / 2.0
                dot_y = c_rect.bottom() - 3.0 - dot_size
                for d_i, cat_name in enumerate(dots):
                    dot_col = QColor(255, 255, 255) if is_tod else _category_color(cat_name)
                    p.save()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(dot_col)
                    p.drawEllipse(QRectF(start_x + d_i * (dot_size + dot_gap), dot_y,
                                         dot_size, dot_size))
                    p.restore()

    def _paint_footer(self, p: QPainter) -> None:
        rect = self._layout.get("footer")
        if not isinstance(rect, QRectF):
            return
        btn = panel_style.draw_footer(
            p, rect, self._cached_footer_source, "Senkronize", button_hover=self._hover_footer)
        self._rect_btn_refresh = QRectF(btn) if btn is not None else QRectF()
