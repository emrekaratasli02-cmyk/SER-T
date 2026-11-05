"""Today Panel (v31): Unified Weather & Calendar Dashboard for Şerit.

Merges the live weather atmosphere hero card, 6-hour hourly trend curve,
compact 7-day week strip (with expandable 30-day month grid), and live agenda
timeline with instant meeting join pills into a single Apple/macOS Dynamic Edge flyout.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Package imports
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

try:
    import calendar_panel
    import panel_style
    import sources
    import theme
    import winapi
except ImportError:
    import calendar_panel  # type: ignore
    import panel_style  # type: ignore
    sources = None
    theme = None
    winapi = None


def _log_err(scope: str, exc: Exception) -> None:
    if sources and hasattr(sources, "log_err"):
        sources.log_err(scope, exc)
    else:
        print(f"[today_panel:{scope}] {exc}", file=sys.stderr)


class TodayPanel(panel_style.PopoverBase):
    """v31 Birleşik Günün Özeti (Hava Durumu + Takvim) Paneli."""

    refresh_requested = Signal()
    join_requested = Signal(str)

    WIDTH: int = 360
    RADIUS: float = panel_style.R_PANEL

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            activate_on_show=True,
            outside_click_close=False,
            recently_closed_ms=350.0,
        )
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._anchor_rect_global: Optional[QRectF] = None
        self._weather_data: Dict[str, Any] = {}
        self._month_data: Dict[str, Any] = {}
        self._claude_data: Dict[str, Any] = {}
        self._city_name: str = "Aksaray"

        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        self.today: dt.date = dt.datetime.now(local_tz).date()
        self.selected_date: dt.date = self.today
        self.view_year: int = self.today.year
        self.view_month: int = self.today.month

        # Genişletilebilir 30 günlük ay modu (false = kompakt hafta şeridi)
        self.month_expanded: bool = False

        self._now_override: Optional[dt.datetime] = None
        self._last_close_time: float = 0.0
        self._is_closing: bool = False

        # Hit bölgeleri
        self._rect_close: QRectF = QRectF()
        self._rect_toggle_month: QRectF = QRectF()
        self._rect_refresh: QRectF = QRectF()
        self._rect_btn_prev: QRectF = QRectF()
        self._rect_btn_today: QRectF = QRectF()
        self._rect_btn_next: QRectF = QRectF()

        # Önbellekler
        self._cached_week_days: List[Dict[str, Any]] = []
        self._cached_cells: List[Dict[str, Any]] = []
        self._cached_events: List[Dict[str, Any]] = []
        self._cached_hourly: List[Dict[str, Any]] = []

        # Hover durumları
        self._hover_close: bool = False
        self._hover_toggle_month: bool = False
        self._hover_refresh: bool = False
        self._hover_week_idx: int = -1
        self._hover_event_idx: int = -1
        self._hover_join_idx: int = -1
        self._hover_cell_idx: int = -1
        self._hover_prev: bool = False
        self._hover_today: bool = False
        self._hover_next: bool = False

        self.resize(self.WIDTH, 740)

    def _now(self) -> dt.datetime:
        if self._now_override is not None:
            return self._now_override
        local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
        return dt.datetime.now(local_tz)

    def _target_pos(self) -> QPoint:
        a = self._anchor_global
        if a is None:
            return QPoint(int(self.x()), int(self.y()))
        w, h = self.width(), self.height()
        tx = int(round(a.center().x() - w / 2.0))
        ty = int(round(a.top() - h - panel_style.ANCHOR_GAP))
        center_pt = a.center().toPoint()
        screen = QGuiApplication.screenAt(center_pt) or QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            dpr = screen.devicePixelRatio()
            margin = 8
            min_x = geom.left() + margin
            max_x = geom.right() - self.width() - margin
            tx = max(min_x, min(max_x, tx)) if max_x >= min_x else min_x
            min_y = geom.top() + margin
            max_y = geom.bottom() - self.height() - margin
            if ty < min_y:
                below_y = int(a.bottom() + panel_style.ANCHOR_GAP)
                if below_y + self.height() <= geom.bottom() - margin:
                    ty = below_y
                else:
                    ty = min_y
            elif ty > max_y:
                ty = max_y
        return QPoint(int(tx), int(ty))

    def show_for(
        self,
        anchor_global: Optional[Union[QRectF, Any]] = None,
        weather_data: Optional[Dict[str, Any]] = None,
        month_data: Optional[Dict[str, Any]] = None,
        claude_data: Optional[Dict[str, Any]] = None,
        city: str = "Aksaray",
        switch_from_x: Optional[int] = None,
    ) -> None:
        try:
            self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
            self._anchor_rect_global = self._anchor_global
            self._weather_data = weather_data if isinstance(weather_data, dict) else {}
            self._month_data = month_data if isinstance(month_data, dict) else {}
            self._claude_data = claude_data if isinstance(claude_data, dict) else {}
            self._city_name = str(city or "Aksaray")

            local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
            self.today = self._now().date()
            if not hasattr(self, "selected_date") or self.selected_date is None:
                self.selected_date = self.today

            self._rebuild_cache()
            new_h = self.compute_height()
            self.resize(self.WIDTH, new_h)

            # Konumlandırma
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

            self._animate_in(switch_from_x)
        except Exception as exc:
            _log_err("today_show_for", exc)

    def _rebuild_cache(self) -> None:
        """Tüm hava, hafta şeridi, etkinlik ve ay ızgarası verilerini hazırlar."""
        now_dt = self._now()
        self.today = now_dt.date()

        # 1. Hava durumu önbelleği
        wx = self._weather_data
        temp = sources._safe_float(wx.get("temp"), None) if sources else None
        feel = sources._safe_float(wx.get("feel"), None) if sources else None
        tmax = sources._safe_float(wx.get("max"), None) if sources else None
        tmin = sources._safe_float(wx.get("min"), None) if sources else None
        wind = sources._safe_float(wx.get("wind"), None) if sources else None
        hum = sources._safe_float(wx.get("humidity"), None) if sources else None
        rain = sources._safe_float(wx.get("rain"), None) if sources else None
        code = int(wx.get("code") or 0)
        desc = str(wx.get("desc") or "Açık")
        icon = str(wx.get("icon") or "sun")

        # Saatlik akış
        raw_hourly = wx.get("hourly") or []
        parsed_hourly: List[Dict[str, Any]] = []
        if isinstance(raw_hourly, list) and raw_hourly:
            for item in raw_hourly[:5]:
                t_str = str(item.get("time") or "")
                time_lbl = t_str[-5:] if len(t_str) >= 5 else t_str
                parsed_hourly.append({
                    "label": time_lbl,
                    "temp": round(float(item.get("temp") or 0.0)),
                    "icon": str(item.get("icon") or "cloud"),
                })
        else:
            # Yedek saatlik akış (mevcut sıcaklıktan hafif düşüş)
            cur_h = now_dt.hour
            base_t = round(temp) if temp is not None else 18
            for idx, off in enumerate((1, 2, 3, 4, 5)):
                parsed_hourly.append({
                    "label": f"{(cur_h + off) % 24:02d}:00",
                    "temp": max(5, base_t - idx),
                    "icon": icon,
                })
        # Şimdi'yi başa ekle
        now_item = {"label": "Şimdi", "temp": round(temp) if temp is not None else 19, "icon": icon}
        self._cached_hourly = [now_item] + parsed_hourly[:5]

        # 2. Etkinlikleri topla (Google + Tatiller + Claude)
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
            claude_markers.extend(calendar_panel.get_claude_markers_for_month(self._claude_data, y, m))

        # Seçili gün etkinlikleri
        cat_prio = {
            calendar_panel.CAT_HOLIDAY: 0,
            calendar_panel.CAT_TAX: 1,
            calendar_panel.CAT_CLAUDE: 2,
            calendar_panel.CAT_GOOGLE: 3,
        }
        sel_events = self._match_events_for_date(self.selected_date, events_list, claude_markers)
        sel_events.sort(
            key=lambda ev: (
                cat_prio.get(str(ev.get("category") or calendar_panel.CAT_GOOGLE), 9),
                str(ev.get("start") or ""),
            )
        )

        # Görsel satırlar
        display_events: List[Dict[str, Any]] = []
        for ev in sel_events[:3]:
            title = calendar_panel.clean_title(ev.get("title", ""))
            category = str(ev.get("category") or calendar_panel.CAT_GOOGLE)
            meeting = ev.get("meeting")
            if not meeting:
                meeting = calendar_panel.extract_meeting_link(
                    ev.get("yer"), ev.get("title"), ev.get("link"), ev.get("aciklama")
                )
            st = ev.get("start")
            show_join = False
            time_lbl = "Tüm gün"
            sub_lbl = category
            state = "normal"

            if isinstance(st, dt.datetime):
                local_tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
                st_loc = calendar_panel._event_start_local(st, local_tz)
                if st_loc:
                    time_lbl = st_loc.strftime("%H:%M")
                    delta_sec = (st_loc - now_dt).total_seconds()
                    if -3600.0 <= delta_sec <= 3600.0 and self.selected_date == self.today:
                        state = "active"
                        if delta_sec > 0:
                            sub_lbl = f"{int(delta_sec // 60)} dk sonra · {category}"
                        else:
                            sub_lbl = f"Devam ediyor · {category}"
                    elif delta_sec > 0:
                        hrs_left = int(delta_sec // 3600)
                        sub_lbl = f"{hrs_left} saat sonra · {category}" if hrs_left > 0 else category
                    if meeting and -600.0 <= delta_sec <= 3600.0 and self.selected_date == self.today:
                        show_join = True

            display_events.append({
                "title": title,
                "category": category,
                "time": time_lbl,
                "sub": sub_lbl,
                "link": ev.get("link", ""),
                "meeting": meeting,
                "show_join": show_join,
                "strip_color": calendar_panel._category_color(category),
                "state": state,
                "rect": QRectF(),
                "join_rect": QRectF(),
            })
        self._cached_events = display_events

        # 3. Kompakt Hafta Şeridi
        monday = self.selected_date - dt.timedelta(days=self.selected_date.weekday())
        week_days: List[Dict[str, Any]] = []
        day_names = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
        for i in range(7):
            d = monday + dt.timedelta(days=i)
            has_ev = bool(self._match_events_for_date(d, events_list, claude_markers))
            week_days.append({
                "date": d,
                "name": day_names[i],
                "day_str": str(d.day),
                "is_today": (d == self.today),
                "is_selected": (d == self.selected_date),
                "has_event": has_ev,
                "rect": QRectF(),
            })
        self._cached_week_days = week_days

        # 4. Ay Izgarası (Genişletildiğinde kullanılır)
        first_day = dt.date(self.view_year, self.view_month, 1)
        grid_start = first_day - dt.timedelta(days=first_day.weekday())
        cells: List[Dict[str, Any]] = []
        for idx in range(42):
            cell_d = grid_start + dt.timedelta(days=idx)
            has_ev = bool(self._match_events_for_date(cell_d, events_list, claude_markers))
            cells.append({
                "date": cell_d,
                "day_num": str(cell_d.day),
                "is_current": (cell_d.month == self.view_month),
                "is_today": (cell_d == self.today),
                "is_selected": (cell_d == self.selected_date),
                "has_event": has_ev,
                "rect": QRectF(),
            })
        self._cached_cells = cells

    def compute_height(self) -> int:
        pad = panel_style.PAD
        gap = panel_style.GAP
        h = pad + panel_style.HEADER_H + gap
        # Hava durumu kartı
        h += 276.0 + gap
        # Hafta şeridi (veya Ay ızgarası)
        if self.month_expanded:
            h += 210.0 + gap
        else:
            h += 76.0 + gap
        # Günün planı
        n_ev = len(self._cached_events)
        h += 24.0 + (n_ev * 52.0 + max(0, n_ev - 1) * 6.0 if n_ev else 42.0) + gap
        # Footer
        h += panel_style.FOOTER_H + pad
        return int(math.ceil(h))

    # ------------------------------------------------------------- Çizim Metotları
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._paint_panel(p)
        p.end()

    def _paint_panel(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        ps = panel_style

        # 1. Dış Cam Kabuk
        ps.draw_panel_shell(p, QRectF(0, 0, w, h))

        pad = ps.PAD
        cw = w - 2.0 * pad
        y = pad

        # 2. Üst Başlık: "Bugün" + Tarih Rozeti + "X"
        dow_str = calendar_panel.TR_DAYS_FULL.get(self.selected_date.weekday(), "")
        m_str = calendar_panel.TR_MONTHS_FULL.get(self.selected_date.month, "")
        chip_txt = f"{dow_str} · {self.selected_date.day} {m_str}"
        hdr = ps.draw_header(
            p,
            QRectF(pad, y, cw, ps.HEADER_H),
            "Bugün",
            chip=chip_txt,
            chip_dot=ps.ACCENT,
            close_hover=self._hover_close,
        )
        if hdr.get("close") is not None:
            self._rect_close = QRectF(hdr["close"])
        y += ps.HEADER_H + ps.GAP

        # 3. HAVA KARTI (276px - Apple/macOS Cam Gökyüzü)
        hero_h = 276.0
        r_hero = QRectF(pad, y, cw, hero_h)
        self._paint_weather_hero(p, r_hero)
        y += hero_h + ps.GAP

        # 4. TAKVİM BÖLÜMÜ (Hafta Şeridi veya 30 Günlük Ay)
        if self.month_expanded:
            month_h = 210.0
            r_month = QRectF(pad, y, cw, month_h)
            self._paint_month_grid(p, r_month)
            y += month_h + ps.GAP
        else:
            wk_h = 76.0
            r_wk = QRectF(pad, y, cw, wk_h)
            self._paint_week_strip(p, r_wk)
            y += wk_h + ps.GAP

        # 5. GÜNÜN PLANI (Zaman Çizgisi)
        y = self._paint_agenda_section(p, pad, y, cw)

        # 6. ALT BİLGİ (Footer)
        fy = h - pad - ps.FOOTER_H
        sync_time = self._now().strftime("%H:%M")
        foot_note = f"Open-Meteo & Takvim · {sync_time}"
        btn = ps.draw_footer(
            p,
            QRectF(pad, fy, cw, ps.FOOTER_H),
            foot_note,
            "Yenile",
            button_hover=self._hover_refresh,
        )
        if btn is not None:
            self._rect_refresh = QRectF(btn)

    def _paint_weather_hero(self, p: QPainter, rect: QRectF) -> None:
        ps = panel_style
        wx = self._weather_data
        temp = sources._safe_float(wx.get("temp"), None) if sources else None
        feel = sources._safe_float(wx.get("feel"), None) if sources else None
        tmax = sources._safe_float(wx.get("max"), None) if sources else None
        tmin = sources._safe_float(wx.get("min"), None) if sources else None
        wind = sources._safe_float(wx.get("wind"), None) if sources else None
        hum = sources._safe_float(wx.get("humidity"), None) if sources else None
        rain = sources._safe_float(wx.get("rain"), None) if sources else None
        desc = str(wx.get("desc") or "Açık")
        icon = str(wx.get("icon") or "sun")

        # Organik Akşamüstü / Gün Işığı Gradyanı
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, QColor(28, 54, 110))
        g.setColorAt(0.55, QColor(42, 48, 92))
        g.setColorAt(1.0, QColor(26, 28, 48))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 16, 16)

        # Üst cam specular parlama
        gl = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 80))
        gl.setColorAt(0.0, QColor(255, 255, 255, 40))
        gl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(gl))
        p.drawRoundedRect(rect, 16, 16)

        # 1px dış specular kenarlık
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)

        # Konum etiketi
        p.setFont(ps.font(10.5, QFont.Weight.DemiBold))
        p.setPen(QColor(255, 255, 255, 190))
        p.drawText(QRectF(rect.left() + 16, rect.top() + 14, 120, 16), Qt.AlignLeft | Qt.AlignVCenter, self._city_name.upper())

        # Sağ üst: Min / Maks hapı
        if tmax is not None and tmin is not None:
            pill_r = QRectF(rect.right() - 110, rect.top() + 12, 94, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(pill_r, 10, 10)
            p.setFont(ps.font(10.0, QFont.Weight.Medium, tabular=True))
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(pill_r, Qt.AlignCenter, f"↑ {round(tmax)}°  ↓ {round(tmin)}°")

        # Büyük Sıcaklık & Hava İkonu
        p.setFont(ps.font(68.0, QFont.Weight.Light, tabular=True))
        p.setPen(QColor(255, 255, 255))
        temp_str = f"{round(temp)}°" if temp is not None else "—"
        p.drawText(QRectF(rect.left() + 14, rect.top() + 30, 140, 74), Qt.AlignLeft | Qt.AlignVCenter, temp_str)

        if theme and hasattr(theme, "draw_weather_icon"):
            theme.draw_weather_icon(p, QRectF(rect.right() - 86, rect.top() + 38, 64, 64), icon)

        # Durum Açıklaması ve Hissedilen
        p.setFont(ps.font(14.0, QFont.Weight.DemiBold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(rect.left() + 16, rect.top() + 106, rect.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, desc)

        p.setFont(ps.font(11.5))
        p.setPen(QColor(255, 255, 255, 180))
        feel_txt = f"Hissedilen {round(feel)}°" if feel is not None else "Hissedilen —"
        p.drawText(QRectF(rect.left() + 16, rect.top() + 126, rect.width() - 32, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{feel_txt}  ·  Aksaray")

        # İnce Ayraç 1
        ly = rect.top() + 148
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(QPointF(rect.left() + 16, ly), QPointF(rect.right() - 16, ly))

        # Saatlik Tahmin Eğrisi
        hrs = self._cached_hourly
        if hrs:
            n = len(hrs)
            colw = (rect.width() - 24.0) / n
            tvals = [h["temp"] for h in hrs]
            lo, hi = min(tvals), max(tvals)
            span = max(1, hi - lo)
            cy_top, cy_bot = ly + 32.0, ly + 48.0
            pts = []
            for i, h_item in enumerate(hrs):
                cx = rect.left() + 12.0 + colw * (i + 0.5)
                cyy = cy_bot - (h_item["temp"] - lo) / span * (cy_bot - cy_top)
                pts.append(QPointF(cx, cyy))

            # Yumuşak eğri (Spline)
            path = QPainterPath(pts[0])
            for i in range(1, n):
                mx = (pts[i - 1].x() + pts[i].x()) / 2.0
                path.cubicTo(QPointF(mx, pts[i - 1].y()), QPointF(mx, pts[i].y()), pts[i])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 80), 1.6))
            p.drawPath(path)

            for i, h_item in enumerate(hrs):
                cx = pts[i].x()
                if i == 0:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 24))
                    p.drawRoundedRect(QRectF(cx - colw / 2.0 + 2, ly + 4, colw - 4, 68), 8, 8)

                p.setFont(ps.font(10.0, QFont.Weight.DemiBold if i == 0 else QFont.Weight.Normal))
                p.setPen(QColor(255, 255, 255) if i == 0 else QColor(255, 255, 255, 160))
                p.drawText(QRectF(cx - colw / 2.0, ly + 6, colw, 14), Qt.AlignCenter, h_item["label"])

                if theme and hasattr(theme, "draw_weather_icon"):
                    theme.draw_weather_icon(p, QRectF(cx - 9, ly + 20, 18, 18), h_item["icon"])

                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255) if i == 0 else QColor(255, 255, 255, 200))
                p.drawEllipse(pts[i], 3.0, 3.0)

                p.setFont(ps.font(11.0, QFont.Weight.DemiBold, tabular=True))
                p.setPen(QColor(255, 255, 255))
                p.drawText(QRectF(cx - colw / 2.0, pts[i].y() + 4, colw, 14), Qt.AlignCenter, f"{h_item['temp']}°")

        # İnce Ayraç 2
        sep_y = rect.bottom() - 40.0
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.2))
        p.drawLine(QPointF(rect.left() + 16, sep_y), QPointF(rect.right() - 16, sep_y))

        # Alt Parametreler (Yağış, Nem, Rüzgar)
        my = rect.bottom() - 32.0
        r_str = f"%{round(rain)}" if rain is not None else "—"
        h_str = f"%{round(hum)}" if hum is not None else "—"
        w_str = f"{round(wind)} km/s" if wind is not None else "—"
        stats = [("Yağış", r_str, "#7DD3FC"), ("Nem", h_str, "#38BDF8"), ("Rüzgâr", w_str, "#CBD5E1")]
        sw = (rect.width() - 32.0) / 3.0
        for i, (lb, vl, col) in enumerate(stats):
            sx = rect.left() + 16.0 + i * sw
            if i > 0:
                p.setPen(QPen(QColor(255, 255, 255, 28), 1))
                p.drawLine(QPointF(sx, my + 4), QPointF(sx, my + 18))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(sx + 8, my + 11), 3.2, 3.2)
            p.setFont(ps.font(10.5))
            p.setPen(QColor(255, 255, 255, 165))
            p.drawText(QRectF(sx + 16, my, 40, 22), Qt.AlignVCenter | Qt.AlignLeft, lb)
            p.setFont(ps.font(11.5, QFont.Weight.DemiBold, tabular=True))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(sx + 56, my, sw - 60, 22), Qt.AlignVCenter | Qt.AlignRight, vl)

    def _paint_week_strip(self, p: QPainter, rect: QRectF) -> None:
        ps = panel_style
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(QColor(20, 23, 30))
        p.drawRoundedRect(rect, 14, 14)

        cwk = rect.width() / 7.0
        for i, item in enumerate(self._cached_week_days):
            cx = rect.left() + cwk * (i + 0.5)
            r_day = QRectF(cx - 19.0, rect.top() + 8.0, 38.0, rect.height() - 16.0)
            item["rect"] = r_day

            is_sel = item["is_selected"]
            is_hov = (self._hover_week_idx == i)

            if is_sel:
                p.setPen(Qt.NoPen)
                p.setBrush(ps.ACCENT)
                p.drawRoundedRect(r_day, 12, 12)
            elif is_hov:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 12))
                p.drawRoundedRect(r_day, 12, 12)

            # Gün Adı (Pzt, Sal, ...)
            p.setFont(ps.font(10.0, QFont.Weight.DemiBold))
            p.setPen(QColor(15, 23, 42) if is_sel else ps.TEXT_MUTED)
            p.drawText(QRectF(r_day.left(), r_day.top() + 4, r_day.width(), 14), Qt.AlignCenter, item["name"])

            # Gün Numarası (2, 3, 4, ...)
            p.setFont(ps.font(16.0, QFont.Weight.DemiBold, tabular=True))
            p.setPen(QColor(15, 23, 42) if is_sel else (ps.TEXT if i < 5 else ps.TEXT_MUTED))
            p.drawText(QRectF(r_day.left(), r_day.top() + 20, r_day.width(), 22), Qt.AlignCenter, item["day_str"])

            # Etkinlik Noktası
            if item["has_event"] or is_sel:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(15, 23, 42) if is_sel else ps.ACCENT)
                p.drawEllipse(QPointF(cx, rect.top() + 56), 2.0, 2.0)

    def _nav_rects_helper(self, month_rect: QRectF) -> Tuple[QRectF, QRectF, QRectF]:
        return calendar_panel.nav_rects(month_rect)

    def _match_events_for_date(
        self,
        d: dt.date,
        events: List[Dict[str, Any]],
        claude_markers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return calendar_panel.match_events_for_date(
            d, events, claude_markers, synthetic_claude=True
        )

    def _paint_month_grid(self, p: QPainter, rect: QRectF) -> None:
        ps = panel_style
        m_name = calendar_panel.TR_MONTHS_FULL.get(self.view_month, "")
        inner = ps.draw_card(p, rect, f"{m_name} {self.view_year}")

        # Ay Gezinme (‹ Bugün ›)
        self._rect_btn_prev, self._rect_btn_today, self._rect_btn_next = self._nav_rects_helper(rect)
        p.setFont(ps.font(10.5, QFont.Weight.DemiBold))
        p.setPen(ps.TEXT if self._hover_prev else ps.TEXT_MUTED)
        p.drawText(self._rect_btn_prev, Qt.AlignCenter, "‹")
        p.setPen(ps.TEXT if self._hover_today else ps.TEXT_MUTED)
        p.drawText(self._rect_btn_today, Qt.AlignCenter, "Bugün")
        p.setPen(ps.TEXT if self._hover_next else ps.TEXT_MUTED)
        p.drawText(self._rect_btn_next, Qt.AlignCenter, "›")

        # Gün Başlıkları
        days_header = ["Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz"]
        col_w = inner.width() / 7.0
        grid_y = inner.top()
        for j, dh in enumerate(days_header):
            p.setFont(ps.font(10.0, QFont.Weight.DemiBold))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(inner.left() + j * col_w, grid_y, col_w, 14), Qt.AlignCenter, dh)

        grid_y += 18.0
        for idx, cell in enumerate(self._cached_cells):
            row = idx // 7
            col = idx % 7
            rc = QRectF(inner.left() + col * col_w, grid_y + row * 22.0, col_w, 20.0)
            cell["rect"] = rc

            is_cur = cell["is_current"]
            is_tod = cell["is_today"]
            is_sel = cell["is_selected"]

            if is_sel or is_tod:
                p.setPen(Qt.NoPen)
                p.setBrush(ps.ACCENT)
                p.drawRoundedRect(QRectF(rc.center().x() - 10, rc.center().y() - 10, 20, 20), 10, 10)
                p.setFont(ps.font(11.0, QFont.Weight.Bold, tabular=True))
                p.setPen(QColor(15, 23, 42))
            else:
                p.setFont(ps.font(11.0, tabular=True))
                p.setPen(ps.TEXT if is_cur else ps.TEXT_MUTED)

            p.drawText(rc, Qt.AlignCenter, cell["day_num"])
            if cell["has_event"] and not (is_sel or is_tod):
                p.setPen(Qt.NoPen)
                p.setBrush(ps.ACCENT)
                p.drawEllipse(QPointF(rc.center().x(), rc.bottom() - 1), 1.5, 1.5)

    def _paint_agenda_section(self, p: QPainter, pad: float, y: float, cw: float) -> float:
        ps = panel_style
        head_r = QRectF(pad + 4, y, cw - 8, 20)
        p.setFont(ps.font(11.0, QFont.Weight.DemiBold))
        p.setPen(ps.TEXT)
        p.drawText(head_r, Qt.AlignLeft | Qt.AlignVCenter, "Günün Planı")

        # "Tüm Ay ▾" / "Kapat ▴" Butonu
        toggle_txt = "Kapat ▴" if self.month_expanded else "Tüm Ay ▾"
        all_m_btn = QRectF(head_r.right() - 74, y, 74, 20)
        self._rect_toggle_month = all_m_btn
        p.setPen(QPen(QColor(255, 255, 255, 28 if self._hover_toggle_month else 18), 1))
        p.setBrush(QColor(255, 255, 255, 14 if self._hover_toggle_month else 8))
        p.drawRoundedRect(all_m_btn, 10, 10)
        p.setFont(ps.font(10.0, QFont.Weight.Medium))
        p.setPen(ps.TEXT if self._hover_toggle_month else ps.TEXT_MUTED)
        p.drawText(all_m_btn, Qt.AlignCenter, toggle_txt)
        y += 24.0

        events = self._cached_events
        if not events:
            r_empty = QRectF(pad, y, cw, 42.0)
            p.setPen(QPen(QColor(255, 255, 255, 12), 1))
            p.setBrush(QColor(20, 23, 30))
            p.drawRoundedRect(r_empty, 10, 10)
            p.setFont(ps.font(11.5))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(r_empty, Qt.AlignCenter, "Bugün için kayıtlı etkinlik yok")
            return y + 42.0 + ps.GAP

        rh = 52.0
        for idx, item in enumerate(events):
            r = QRectF(pad, y, cw, rh)
            item["rect"] = r
            is_act = (item["state"] == "active")
            is_hov = (self._hover_event_idx == idx)

            # Kart Arka Planı
            p.setPen(QPen(ps.ACCENT if is_act else (QColor(255, 255, 255, 26) if is_hov else QColor(255, 255, 255, 14)), 1.2 if is_act else 1))
            p.setBrush(QColor(26, 32, 44) if is_act else (QColor(24, 28, 36) if is_hov else QColor(20, 23, 30)))
            p.drawRoundedRect(r, 12, 12)

            # Renkli Sol Çizgi
            p.setPen(Qt.NoPen)
            p.setBrush(item["strip_color"])
            p.drawRoundedRect(QRectF(r.left() + 8, r.top() + 10, 3.5, rh - 20), 1.8, 1.8)

            # Saat & Rozet
            p.setFont(ps.font(13.0, QFont.Weight.Bold, tabular=True))
            p.setPen(ps.TEXT)
            p.drawText(QRectF(r.left() + 20, r.top() + 7, 50, 18), Qt.AlignLeft | Qt.AlignVCenter, item["time"])

            p.setFont(ps.font(10.0))
            p.setPen(ps.ACCENT if is_act else ps.TEXT_MUTED)
            p.drawText(QRectF(r.left() + 20, r.top() + 26, 50, 16), Qt.AlignLeft | Qt.AlignVCenter, "yakında" if is_act else "bugün")

            # Başlık & Detay Metni
            has_join = item["show_join"]
            tx = r.left() + 74.0
            tw = r.width() - 74.0 - (62.0 if has_join else 12.0)

            p.setFont(ps.font(12.0, QFont.Weight.DemiBold))
            p.setPen(ps.TEXT)
            title_elided = QFontMetricsF(ps.font(12.0, QFont.Weight.DemiBold)).elidedText(item["title"], Qt.TextElideMode.ElideRight, tw)
            p.drawText(QRectF(tx, r.top() + 7, tw, 18), Qt.AlignLeft | Qt.AlignVCenter, title_elided)

            p.setFont(ps.font(10.5))
            p.setPen(ps.TEXT_MUTED)
            sub_elided = QFontMetricsF(ps.font(10.5)).elidedText(item["sub"], Qt.TextElideMode.ElideRight, tw)
            p.drawText(QRectF(tx, r.top() + 26, tw, 16), Qt.AlignLeft | Qt.AlignVCenter, sub_elided)

            # "Katıl" Düğmesi
            if has_join:
                jr = QRectF(r.right() - 56, r.center().y() - 11, 46, 22)
                item["join_rect"] = jr
                j_hov = (self._hover_join_idx == idx)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(180, 240, 255) if j_hov else ps.ACCENT)
                p.drawRoundedRect(jr, 11, 11)
                p.setFont(ps.font(10.5, QFont.Weight.Bold))
                p.setPen(QColor(15, 23, 42))
                p.drawText(jr, Qt.AlignCenter, "Katıl")
            else:
                item["join_rect"] = QRectF()

            y += rh + 6.0
        return y

    # ------------------------------------------------------------- Etkileşimler
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        self._hover_close = self._rect_close.contains(pos)
        self._hover_toggle_month = self._rect_toggle_month.contains(pos)
        self._hover_refresh = self._rect_refresh.contains(pos)

        hov_wk = -1
        for idx, item in enumerate(self._cached_week_days):
            if item.get("rect") and item["rect"].contains(pos):
                hov_wk = idx
                break
        self._hover_week_idx = hov_wk

        hov_ev = -1
        hov_jn = -1
        for idx, item in enumerate(self._cached_events):
            jr = item.get("join_rect")
            if jr and not jr.isEmpty() and jr.contains(pos):
                hov_jn = idx
                break
            if item.get("rect") and item["rect"].contains(pos):
                hov_ev = idx
                break
        self._hover_event_idx = hov_ev
        self._hover_join_idx = hov_jn

        if self.month_expanded:
            self._hover_prev = self._rect_btn_prev.contains(pos)
            self._hover_today = self._rect_btn_today.contains(pos)
            self._hover_next = self._rect_btn_next.contains(pos)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()

        if self._rect_close.contains(pos):
            self.hide_animated()
            return
        if self._rect_toggle_month.contains(pos):
            self.month_expanded = not self.month_expanded
            new_h = self.compute_height()
            self.resize(self.WIDTH, new_h)
            if self._anchor_global:
                self.show_for(self._anchor_global, self._weather_data, self._month_data, self._claude_data, self._city_name)
            self.update()
            return
        if self._rect_refresh.contains(pos):
            self.refresh_requested.emit()
            return

        # Hafta Şeridi Tıklaması
        for item in self._cached_week_days:
            if item.get("rect") and item["rect"].contains(pos):
                self.selected_date = item["date"]
                self._rebuild_cache()
                self.update()
                return

        # Ay Izgarası Butonları
        if self.month_expanded:
            if self._rect_btn_prev.contains(pos):
                self.view_month -= 1
                if self.view_month < 1:
                    self.view_month = 12
                    self.view_year -= 1
                self._rebuild_cache()
                self.update()
                return
            if self._rect_btn_today.contains(pos):
                self.selected_date = self.today
                self.view_year = self.today.year
                self.view_month = self.today.month
                self._rebuild_cache()
                self.update()
                return
            if self._rect_btn_next.contains(pos):
                self.view_month += 1
                if self.view_month > 12:
                    self.view_month = 1
                    self.view_year += 1
                self._rebuild_cache()
                self.update()
                return
            for cell in self._cached_cells:
                if cell.get("rect") and cell["rect"].contains(pos):
                    self.selected_date = cell["date"]
                    self.view_year = cell["date"].year
                    self.view_month = cell["date"].month
                    self._rebuild_cache()
                    self.update()
                    return

        # "Katıl" veya Etkinlik Linki Tıklaması
        for item in self._cached_events:
            jr = item.get("join_rect")
            if jr and not jr.isEmpty() and jr.contains(pos):
                m_url = item.get("meeting")
                if m_url:
                    self.join_requested.emit(str(m_url))
                return
            if item.get("rect") and item["rect"].contains(pos):
                link = item.get("link")
                if link and str(link).startswith(("http://", "https://")):
                    QDesktopServices.openUrl(QUrl(str(link)))
                return

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            return
        super().keyPressEvent(event)
