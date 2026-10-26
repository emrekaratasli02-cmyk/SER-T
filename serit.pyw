# Şerit (v3): Lumabar benzeri yüzen cam dock.
# Mockup Taslak A tasarımı: Tek parça yüzen cam dock, halkalar, çalışan uygulamalar, hava durumu, saat.
#
# winapi.py ve sources.py modülleri üzerine inşa edilmiştir.

import sys
import json
import math
import threading
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil
from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QRect, QRectF, QPoint, QPointF,
    QLockFile, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetricsF, QLinearGradient, QRadialGradient,
    QPainterPath, QPen, QGuiApplication, QImage, QPixmap, QAction
)
from PySide6.QtWidgets import QApplication, QWidget, QMenu

import winapi
import sources

# Sabitler
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
LOCK_FILE_PATH = APP_DIR / "serit.lock"

DOCK_HEIGHT = 56
CORNER_RADIUS = 20
PADDING_X = 10
ITEM_GAP = 2
BOTTOM_OFFSET = 12

COLOR_CLAUDE_S = QColor("#f08a5d")
COLOR_CLAUDE_W = QColor("#f6b38f")
COLOR_CPU = QColor("#7cc4ff")
COLOR_RAM = QColor("#b49cff")

COLOR_ALERT_WARN = QColor("#ffc45c")  # >= 80
COLOR_ALERT_CRIT = QColor("#ff6e6e")  # >= 95

DEFAULT_SETTINGS = {
    "hide_taskbar": False,
    "taskbar_original": None,
    "pos": None,
    "lat": 38.37,
    "lon": 34.03,
    "city": "Aksaray",
}

TR_DAYS = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            cfg.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_settings(cfg: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def make_font(size_px: int, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
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


def get_ring_color(val: float, default_col: QColor) -> QColor:
    if val >= 95:
        return COLOR_ALERT_CRIT
    if val >= 80:
        return COLOR_ALERT_WARN
    return default_col


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(rect, radius, radius)
    return p


def draw_weather_icon(p: QPainter, r: QRectF, icon: str) -> None:
    cx, cy = r.center().x(), r.center().y()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)

    def draw_cloud(base_x: float, base_y: float, w: float = 16, h: float = 10, col: QColor = QColor(230, 235, 245)):
        path = QPainterPath()
        path.addRoundedRect(QRectF(base_x - w / 2, base_y, w, h * 0.7), 3, 3)
        path.addEllipse(QRectF(base_x - w / 2 + 2, base_y - h * 0.4, h * 0.9, h * 0.9))
        path.addEllipse(QRectF(base_x - w / 2 + 6, base_y - h * 0.6, h, h))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPath(path)

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
                QPointF(cx + 9.5 * math.cos(ang), cy + 9.5 * math.sin(ang))
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
        # Default cloud
        draw_cloud(cx, cy - 3, 17, 11)

    p.restore()


class PopoverWindow(QWidget):
    """Frameless acrylic popover window positioned above the dock."""

    def __init__(self, parent_dock: Optional[QWidget] = None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.parent_dock = parent_dock
        self.pop_type = ""
        self.title = ""
        self.badge: Optional[str] = None
        self.rows: List[dict] = []
        self.source_line = ""

        self.f_title = make_font(13, QFont.Weight.Bold)
        self.f_badge = make_font(10, QFont.Weight.DemiBold)
        self.f_row = make_font(12, QFont.Weight.Normal)
        self.f_bold = make_font(12, QFont.Weight.Bold, tabular=True)
        self.f_sub = make_font(10, QFont.Weight.Normal)

    def set_content(self, pop_type: str, title: str, badge: Optional[str], rows: List[dict], source_line: str) -> None:
        self.pop_type = pop_type
        self.title = title
        self.badge = badge
        self.rows = rows
        self.source_line = source_line

        # Dinamik yükseklik hesaplama
        h = 12 + 18 + 10  # üst boşluk + başlık satırı + alt boşluk
        for r in self.rows:
            h += 20
            if r.get("sub"):
                h += 16
            h += 4
        h += 8 + 1 + 7 + 16 + 10  # çizgi + kaynak satırı + alt boşluk
        self.resize(260, int(h))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange:
            if not self.isActiveWindow() and self.isVisible():
                self.hide()
        super().changeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Cam arka plan
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = rounded_path(r, 14)
        p.fillPath(path, QColor(18, 22, 30, 235))

        # Üst parlama
        p.save()
        p.setClipPath(path)
        hl = QLinearGradient(0, 1, 0, 3)
        hl.setColorAt(0, QColor(255, 255, 255, 50))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, self.width() - 2, 2), hl)
        p.restore()

        # Kenarlık
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawPath(path)

        # Başlık ve rozet
        y = 26
        p.setFont(self.f_title)
        p.setPen(Qt.white)
        p.drawText(14, y, self.title)

        if self.badge:
            fm = QFontMetricsF(self.f_title)
            tw = fm.horizontalAdvance(self.title)
            fm_b = QFontMetricsF(self.f_badge)
            bw = fm_b.horizontalAdvance(self.badge) + 12
            b_rect = QRectF(14 + tw + 8, y - 13, bw, 17)
            bpath = rounded_path(b_rect, 5)
            p.fillPath(bpath, QColor(240, 138, 93, 60))
            p.setFont(self.f_badge)
            p.setPen(QColor("#ffcaad"))
            p.drawText(b_rect, Qt.AlignCenter, self.badge)

        y += 18
        # Satırlar
        for r in self.rows:
            label_text = r.get("label", "")
            val_text = r.get("val", "")
            has_pct = "pct" in r

            p.setFont(self.f_row)
            p.setPen(QColor(255, 255, 255, 160))
            label_w = 70 if has_pct else 90
            p.drawText(QRectF(14, y, label_w, 16), Qt.AlignLeft | Qt.AlignVCenter, label_text)

            p.setFont(self.f_bold)
            p.setPen(r.get("val_col", Qt.white))
            val_w = 46 if has_pct else 130
            p.drawText(QRectF(self.width() - val_w - 14, y, val_w, 16), Qt.AlignRight | Qt.AlignVCenter, val_text)

            if has_pct:
                bar_x = 86
                bar_w = self.width() - bar_x - 64
                bar_rect = QRectF(bar_x, y + 5, bar_w, 5)
                p.fillPath(rounded_path(bar_rect, 2.5), QColor(255, 255, 255, 30))
                pct = max(0.0, min(100.0, float(r["pct"])))
                if pct > 0:
                    fill_w = max(4.0, bar_rect.width() * pct / 100.0)
                    fill_rect = QRectF(bar_rect.x(), bar_rect.y(), fill_w, 5)
                    bar_col = r.get("col", QColor("#7cc4ff"))
                    p.fillPath(rounded_path(fill_rect, 2.5), bar_col)

            y += 20
            if r.get("sub"):
                p.setFont(self.f_sub)
                p.setPen(QColor(255, 255, 255, 140))
                sub_x = 86 if has_pct else 14
                p.drawText(QRectF(sub_x, y, self.width() - sub_x - 14, 14), Qt.AlignLeft | Qt.AlignVCenter, r["sub"])
                y += 16
            y += 4

        # Alt çizgi ve kaynak
        y = self.height() - 24
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawLine(14, y - 6, self.width() - 14, y - 6)

        p.setFont(self.f_sub)
        p.setPen(QColor(255, 255, 255, 140))
        p.drawText(QRectF(14, y, self.width() - 28, 16), Qt.AlignLeft | Qt.AlignVCenter, self.source_line)
        p.end()


class FetchWorker(QObject):
    data_ready = Signal(str, dict)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings

    def run(self, key: str) -> None:
        def worker():
            try:
                if key == "claude":
                    res = sources.fetch_claude()
                elif key == "fx":
                    res = sources.fetch_fx()
                elif key == "wx":
                    res = sources.fetch_weather(
                        lat=self.settings.get("lat", 38.37),
                        lon=self.settings.get("lon", 34.03)
                    )
                elif key == "sys":
                    res = sources.fetch_system()
                else:
                    return
            except Exception as exc:
                sources.log_err(key, exc)
                res = {"err": "Bağlantı hatası"}
            self.data_ready.emit(key, res)

        threading.Thread(target=worker, daemon=True).start()


class SeritDock(QWidget):
    """Variant A: Floating acrylic glass dock."""

    def __init__(self, settings: dict, preview_mode: bool = False):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.settings = settings
        self.preview_mode = preview_mode

        self.store = sources.Store()
        self.app_groups: List[dict] = []
        self._app_cycle_indices: Dict[str, int] = {}
        self.hit_boxes: List[Tuple[QRectF, str, Any]] = []
        self._hover_key: Optional[str] = None
        self._icon_cache: Dict[str, QPixmap] = {}

        # Sürükleme değişkenleri
        self._drag_start_pos: Optional[QPoint] = None
        self._window_start_pos: Optional[QPoint] = None
        self._is_dragging = False

        # Yazı tipleri
        self.f_lbl = make_font(11, QFont.Weight.Medium)
        self.f_val = make_font(13, QFont.Weight.DemiBold, tabular=True)
        self.f_ring_num = make_font(11, QFont.Weight.Bold, tabular=True)
        self.f_clock_time = make_font(14, QFont.Weight.Bold, tabular=True)
        self.f_clock_date = make_font(11, QFont.Weight.Medium)

        # Popover penceresi
        self.popover = PopoverWindow(self)

        # Worker ve Timer'lar (preview modunda timer çalışmaz)
        if not self.preview_mode:
            self.worker = FetchWorker(self.settings)
            self.worker.data_ready.connect(self.on_data_ready)
            self.setup_timers()

    def start(self) -> None:
        """Normal mod başlatma: görev çubuğu ve pencere konumu ayarlanır."""
        if self.settings.get("hide_taskbar", False):
            self.settings["taskbar_original"] = winapi.taskbar_autohide_get()
            save_settings(self.settings)
            winapi.taskbar_autohide_set(True)

        self.update_windows()
        self.compute_layout_and_resize()
        self.place_dock()
        self.show()

        # Acrylic ve yuvarlatılmış bölge uygula
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.25
        winapi.enable_acrylic(int(self.winId()), 0x50181612)
        winapi.set_round_region(int(self.winId()), self.width(), DOCK_HEIGHT, CORNER_RADIUS, dpr)

    def cleanup(self) -> None:
        """Kapanış temizliği: görev çubuğunu eski haline getir."""
        if self.settings.get("hide_taskbar", False):
            orig = self.settings.get("taskbar_original")
            if orig is not None:
                winapi.taskbar_autohide_set(orig)

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()

    def setup_timers(self) -> None:
        # psutil cpu_percent'i başlat
        psutil.cpu_percent(None)

        # Veri kaynakları timer'ları
        for key, sec in sources.REFRESH.items():
            timer = QTimer(self)
            timer.setInterval(sec * 1000)
            timer.timeout.connect(lambda k=key: self.worker.run(k))
            timer.start()
            self.worker.run(key)

        # Pencere listesi güncelleme (1.5 s)
        self.win_timer = QTimer(self)
        self.win_timer.setInterval(1500)
        self.win_timer.timeout.connect(self.update_windows)
        self.win_timer.start()

        # Saat yenileme (10 s)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(10000)
        self.clock_timer.timeout.connect(self.update)
        self.clock_timer.start()

    def on_data_ready(self, key: str, res: dict) -> None:
        self.store.update(key, res)
        self.compute_layout_and_resize()
        self.update()

    def update_windows(self) -> None:
        raw_wins = winapi.list_windows()
        groups = winapi.group_by_app(raw_wins)
        self.app_groups = groups[:10]  # Max ~10 apps
        self.compute_layout_and_resize()
        self.update()

    def get_app_icon(self, exe: str) -> QPixmap:
        if exe in self._icon_cache:
            return self._icon_cache[exe]
        pm = winapi.app_icon(exe, 64)
        self._icon_cache[exe] = pm
        return pm

    def place_dock(self) -> None:
        pos = self.settings.get("pos")
        screen = QGuiApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else QRect(0, 0, 1536, 864)

        if pos and len(pos) == 2:
            cx, y = pos
            x = int(cx - self.width() / 2)
            self.move(x, int(y))
        else:
            x = int(geom.center().x() - self.width() / 2)
            y = int(geom.bottom() - DOCK_HEIGHT - BOTTOM_OFFSET)
            self.move(x, y)

    def compute_layout_and_resize(self) -> None:
        """Dinamik genişlik hesaplama ve pencereyi yeniden boyutlandırma."""
        fm_lbl = QFontMetricsF(self.f_lbl)
        fm_val = QFontMetricsF(self.f_val)
        fm_clock = QFontMetricsF(self.f_clock_time)

        # 1. Claude Oturum
        c_entry = self.store.get("claude") or {}
        s_reset = c_entry.get("session_reset", "")
        s_left = sources.left_text(s_reset) if s_reset else "--"
        w_s_text = max(fm_lbl.horizontalAdvance("Oturum"), fm_val.horizontalAdvance(s_left))
        w_chip_s = 16 + 34 + 7 + w_s_text

        # 2. Claude Hafta
        w_reset = c_entry.get("week_reset", "")
        w_left = sources.left_text(w_reset) if w_reset else "--"
        w_w_text = max(fm_lbl.horizontalAdvance("Hafta"), fm_val.horizontalAdvance(w_left))
        w_chip_w = 16 + 34 + 7 + w_w_text

        # 3. Ayraç 1: 9px (1px çizgi + 4px marjin iki taraf)
        w_sep1 = 9

        # 4. Uygulamalar: her biri 38px, aralarında 2px boşluk
        n_apps = len(self.app_groups)
        w_apps = (n_apps * 38 + max(0, n_apps - 1) * ITEM_GAP) if n_apps > 0 else 0

        # 5. Ayraç 2: 9px
        w_sep2 = 9

        # 6. Sistem: 16 (pad) + 34 (cpu) + 6 (gap) + 34 (ram) = 90
        w_sys = 90

        # 7. Hava durumu
        wx_entry = self.store.get("wx") or {}
        desc = wx_entry.get("desc", "Yükleniyor")
        temp = wx_entry.get("temp")
        temp_str = f"{int(round(temp))}°" if temp is not None else "--°"
        w_wx_text = max(fm_lbl.horizontalAdvance(desc), fm_val.horizontalAdvance(temp_str))
        w_wx = 16 + 22 + 7 + w_wx_text

        # 8. Saat
        now = dt.datetime.now(sources.LOCAL_TZ)
        time_str = now.strftime("%H:%M")
        date_str = f"{TR_DAYS.get(now.weekday(), '')} {now.day} {sources.TR_MONTHS.get(now.month, '')}"
        w_clock_text = max(fm_clock.horizontalAdvance(time_str), fm_lbl.horizontalAdvance(date_str))
        w_clock = 20 + w_clock_text

        # Toplam genişlik
        items = [w_chip_s, w_chip_w, w_sep1]
        if w_apps > 0:
            items.append(w_apps)
        items.extend([w_sep2, w_sys, w_wx, w_clock])

        total_w = PADDING_X * 2 + sum(items) + (len(items) - 1) * ITEM_GAP
        total_w = int(math.ceil(total_w))

        if total_w != self.width():
            old_center = self.x() + self.width() / 2 if self.isVisible() else None
            self.resize(total_w, DOCK_HEIGHT)
            if not self.preview_mode and self.isVisible():
                if old_center is not None and self.settings.get("pos"):
                    self.move(int(old_center - total_w / 2), self.y())
                else:
                    self.place_dock()
                dpr = self.screen().devicePixelRatio() if self.screen() else 1.25
                winapi.set_round_region(int(self.winId()), total_w, DOCK_HEIGHT, CORNER_RADIUS, dpr)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. Cam zemin
        r_dock = QRectF(0.5, 0.5, self.width() - 1, DOCK_HEIGHT - 1)
        path_dock = rounded_path(r_dock, CORNER_RADIUS)
        p.fillPath(path_dock, QColor(18, 22, 30, int(255 * 0.40)))

        # Üst parlama çizgisi (inset 0 1px 0 rgba(255,255,255,.20))
        p.save()
        p.setClipPath(path_dock)
        top_hl = QLinearGradient(0, 1, 0, 3)
        top_hl.setColorAt(0, QColor(255, 255, 255, 50))
        top_hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, self.width() - 2, 2), top_hl)
        p.restore()

        # 1px kenarlık rgba(255,255,255,0.16)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.16)), 1))
        p.drawPath(path_dock)

        # Öğeleri çiz
        self.hit_boxes.clear()
        x = PADDING_X
        fm_lbl = QFontMetricsF(self.f_lbl)
        fm_val = QFontMetricsF(self.f_val)
        fm_clock = QFontMetricsF(self.f_clock_time)

        # Veriler
        c_entry = self.store.get("claude") or {}
        c_stale = c_entry.get("stale", False)
        s_pct = float(c_entry.get("session", 0.0))
        s_reset = c_entry.get("session_reset", "")
        s_left = sources.left_text(s_reset) if s_reset else "--"

        w_pct = float(c_entry.get("week", 0.0))
        w_reset = c_entry.get("week_reset", "")
        w_left = sources.left_text(w_reset) if w_reset else "--"

        sys_entry = self.store.get("sys") or {}
        sys_stale = sys_entry.get("stale", False)
        cpu_pct = float(sys_entry.get("cpu", 0.0))
        ram_pct = float(sys_entry.get("ram", 0.0))

        wx_entry = self.store.get("wx") or {}
        wx_stale = wx_entry.get("stale", False)
        desc = wx_entry.get("desc", "Yükleniyor")
        temp = wx_entry.get("temp")
        temp_str = f"{int(round(temp))}°" if temp is not None else "--°"
        wx_icon = wx_entry.get("icon", "cloud")

        now = dt.datetime.now(sources.LOCAL_TZ)
        time_str = now.strftime("%H:%M")
        date_str = f"{TR_DAYS.get(now.weekday(), '')} {now.day} {sources.TR_MONTHS.get(now.month, '')}"

        # --- A) Claude Oturum Çipi ---
        w_s_text = max(fm_lbl.horizontalAdvance("Oturum"), fm_val.horizontalAdvance(s_left))
        chip_s_w = 16 + 34 + 7 + w_s_text
        r_chip_s = QRectF(x, (DOCK_HEIGHT - 38) / 2, chip_s_w, 38)
        self.hit_boxes.append((r_chip_s, "claude", None))

        p.save()
        if c_stale:
            p.setOpacity(0.5)
        if self._hover_key == "claude_s" or self._hover_key == "claude":
            p.fillPath(rounded_path(r_chip_s, 12), QColor(255, 255, 255, 26))

        # Halka (Oturum)
        rx = x + 8 + 17
        ry = DOCK_HEIGHT / 2
        self.draw_ring(p, rx, ry, s_pct, COLOR_CLAUDE_S)

        # Metinler
        tx = x + 8 + 34 + 7
        p.setFont(self.f_lbl)
        p.setPen(QColor(255, 255, 255, int(255 * 0.62)))
        p.drawText(QRectF(tx, 12, w_s_text + 4, 14), Qt.AlignLeft | Qt.AlignVCenter, "Oturum")

        p.setFont(self.f_val)
        p.setPen(Qt.white)
        p.drawText(QRectF(tx, 28, w_s_text + 4, 16), Qt.AlignLeft | Qt.AlignVCenter, s_left)
        p.restore()

        x += chip_s_w + ITEM_GAP

        # --- B) Claude Hafta Çipi ---
        w_w_text = max(fm_lbl.horizontalAdvance("Hafta"), fm_val.horizontalAdvance(w_left))
        chip_w_w = 16 + 34 + 7 + w_w_text
        r_chip_w = QRectF(x, (DOCK_HEIGHT - 38) / 2, chip_w_w, 38)
        self.hit_boxes.append((r_chip_w, "claude", None))

        p.save()
        if c_stale:
            p.setOpacity(0.5)
        rx = x + 8 + 17
        self.draw_ring(p, rx, ry, w_pct, COLOR_CLAUDE_W)

        tx = x + 8 + 34 + 7
        p.setFont(self.f_lbl)
        p.setPen(QColor(255, 255, 255, int(255 * 0.62)))
        p.drawText(QRectF(tx, 12, w_w_text + 4, 14), Qt.AlignLeft | Qt.AlignVCenter, "Hafta")

        p.setFont(self.f_val)
        p.setPen(Qt.white)
        p.drawText(QRectF(tx, 28, w_w_text + 4, 16), Qt.AlignLeft | Qt.AlignVCenter, w_left)
        p.restore()

        x += chip_w_w + ITEM_GAP

        # --- C) Ayraç 1 ---
        p.fillRect(QRectF(x + 4, (DOCK_HEIGHT - 26) / 2, 1, 26), QColor(255, 255, 255, 36))
        x += 9 + ITEM_GAP

        # --- D) Çalışan Uygulamalar ---
        for i, g in enumerate(self.app_groups):
            r_app = QRectF(x, (DOCK_HEIGHT - 38) / 2, 38, 38)
            app_key = f"app_{i}"
            self.hit_boxes.append((r_app, app_key, g))

            is_hovered = (self._hover_key == app_key)
            is_active = g.get("active", False)

            p.save()
            if is_hovered:
                p.fillPath(rounded_path(r_app, 11), QColor(255, 255, 255, 31))

            # İkon (24x24 logical px)
            icon_y = (DOCK_HEIGHT - 24) / 2 - 2
            if is_hovered:
                icon_y -= 2  # lift 2px

            pix = self.get_app_icon(g.get("exe", ""))
            icon_rect = QRectF(x + (38 - 24) / 2, icon_y, 24, 24)
            if not pix.isNull():
                p.drawPixmap(icon_rect.toRect(), pix)
            else:
                # İkon bulunamazsa şık harf karesi
                fallback_path = rounded_path(icon_rect, 6)
                p.fillPath(fallback_path, QColor(45, 52, 68))
                p.setFont(make_font(12, QFont.Weight.Bold))
                p.setPen(Qt.white)
                letter = g.get("name", "A")[:1].upper()
                p.drawText(icon_rect, Qt.AlignCenter, letter)

            # İndikatör
            if is_active:
                pill_rect = QRectF(r_app.center().x() - 7, r_app.bottom() - 4, 14, 3)
                p.fillPath(rounded_path(pill_rect, 1.5), Qt.white)
            else:
                dot_rect = QRectF(r_app.center().x() - 2, r_app.bottom() - 5, 4, 4)
                p.fillPath(rounded_path(dot_rect, 2), QColor(255, 255, 255, 153))

            p.restore()
            x += 38 + ITEM_GAP

        # --- E) Ayraç 2 ---
        p.fillRect(QRectF(x + 4, (DOCK_HEIGHT - 26) / 2, 1, 26), QColor(255, 255, 255, 36))
        x += 9 + ITEM_GAP

        # --- F) Sistem Çipi (CPU ve RAM) ---
        r_chip_sys = QRectF(x, (DOCK_HEIGHT - 38) / 2, 90, 38)
        self.hit_boxes.append((r_chip_sys, "sys", None))

        p.save()
        if sys_stale:
            p.setOpacity(0.5)
        if self._hover_key == "sys":
            p.fillPath(rounded_path(r_chip_sys, 12), QColor(255, 255, 255, 26))

        # CPU Halka
        cpu_x = x + 8 + 17
        self.draw_ring(p, cpu_x, ry, cpu_pct, COLOR_CPU)

        # RAM Halka
        ram_x = cpu_x + 17 + 6 + 17
        self.draw_ring(p, ram_x, ry, ram_pct, COLOR_RAM)
        p.restore()

        x += 90 + ITEM_GAP

        # --- G) Hava Durumu Çipi ---
        w_wx_text = max(fm_lbl.horizontalAdvance(desc), fm_val.horizontalAdvance(temp_str))
        chip_wx_w = 16 + 22 + 7 + w_wx_text
        r_chip_wx = QRectF(x, (DOCK_HEIGHT - 38) / 2, chip_wx_w, 38)
        self.hit_boxes.append((r_chip_wx, "wx", None))

        p.save()
        if wx_stale:
            p.setOpacity(0.5)
        if self._hover_key == "wx":
            p.fillPath(rounded_path(r_chip_wx, 12), QColor(255, 255, 255, 26))

        # Hava ikonu
        draw_weather_icon(p, QRectF(x + 8, (DOCK_HEIGHT - 22) / 2, 22, 22), wx_icon)

        # Hava metinleri
        tx = x + 8 + 22 + 7
        p.setFont(self.f_lbl)
        p.setPen(QColor(255, 255, 255, int(255 * 0.62)))
        p.drawText(QRectF(tx, 12, w_wx_text + 4, 14), Qt.AlignLeft | Qt.AlignVCenter, desc)

        p.setFont(self.f_val)
        p.setPen(Qt.white)
        p.drawText(QRectF(tx, 28, w_wx_text + 4, 16), Qt.AlignLeft | Qt.AlignVCenter, temp_str)
        p.restore()

        x += chip_wx_w + ITEM_GAP

        # --- H) Saat Çipi ---
        w_clock_text = max(fm_clock.horizontalAdvance(time_str), fm_lbl.horizontalAdvance(date_str))
        chip_clock_w = 20 + w_clock_text
        r_chip_clock = QRectF(x, (DOCK_HEIGHT - 38) / 2, chip_clock_w, 38)
        self.hit_boxes.append((r_chip_clock, "clock", None))

        p.save()
        if self._hover_key == "clock":
            p.fillPath(rounded_path(r_chip_clock, 12), QColor(255, 255, 255, 26))

        cx_text = x + 10
        p.setFont(self.f_clock_time)
        p.setPen(Qt.white)
        p.drawText(QRectF(cx_text, 11, w_clock_text, 17), Qt.AlignRight | Qt.AlignVCenter, time_str)

        p.setFont(self.f_clock_date)
        p.setPen(QColor(255, 255, 255, int(255 * 0.62)))
        p.drawText(QRectF(cx_text, 29, w_clock_text, 14), Qt.AlignRight | Qt.AlignVCenter, date_str)
        p.restore()

        p.end()

    def draw_ring(self, p: QPainter, cx: float, cy: float, pct: float, base_col: QColor) -> None:
        """34px çapında, 4px kalınlığında ortası rakamlı halka."""
        r_arc = QRectF(cx - 15, cy - 15, 30, 30)

        # Arka plan halkası (stroke 4, white 16%)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.16)), 4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r_arc)

        # Ön plan halkası
        val = max(0.0, min(100.0, pct))
        if val > 0:
            fg_col = get_ring_color(val, base_col)
            pen_fg = QPen(fg_col, 4, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen_fg)
            span_angle = -int((val / 100.0) * 360 * 16)
            p.drawArc(r_arc, 90 * 16, span_angle)

        # İçteki yüzde sayısı
        p.setFont(self.f_ring_num)
        p.setPen(Qt.white)
        p.drawText(r_arc, Qt.AlignCenter, f"{int(round(val))}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._window_start_pos = self.pos()
            self._is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if event.buttons() & Qt.LeftButton and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            if not self._is_dragging and delta.manhattanLength() > 5:
                self._is_dragging = True
            if self._is_dragging and self._window_start_pos:
                self.move(self._window_start_pos + delta)
            return

        # Hover tespiti ve tooltip
        new_hover = None
        tooltip_text = ""
        for r, key, extra in self.hit_boxes:
            if r.contains(pos):
                new_hover = key
                tooltip_text = self.get_tooltip_text(key, extra)
                break

        if new_hover != self._hover_key:
            self._hover_key = new_hover
            self.update()

        self.setToolTip(tooltip_text)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_key is not None:
            self._hover_key = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._is_dragging:
                self._is_dragging = False
                center_x = self.x() + self.width() / 2
                self.settings["pos"] = [center_x, self.y()]
                save_settings(self.settings)
            else:
                # Tıklama kontrolü
                pos = event.position()
                for r, key, extra in self.hit_boxes:
                    if r.contains(pos):
                        self.handle_click(key, extra, r)
                        break
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def handle_click(self, key: str, extra: Any, rect: QRectF) -> None:
        if key.startswith("app_") and extra:
            self.handle_app_click(extra)
        elif key == "claude":
            self.toggle_popover("claude", rect)
        elif key == "sys":
            self.toggle_popover("sys", rect)
        elif key == "wx":
            self.toggle_popover("wx", rect)

    def handle_app_click(self, group: dict) -> None:
        hwnds = group.get("hwnds", [])
        if not hwnds:
            return
        exe = group.get("exe", "")
        if len(hwnds) == 1:
            winapi.activate_or_minimize(hwnds[0])
        else:
            last_idx = self._app_cycle_indices.get(exe, -1)
            next_idx = (last_idx + 1) % len(hwnds)
            self._app_cycle_indices[exe] = next_idx
            winapi.activate_or_minimize(hwnds[next_idx])
        self.update_windows()

    def get_tooltip_text(self, key: str, extra: Any) -> str:
        now_dt = dt.datetime.now(sources.LOCAL_TZ)
        if key == "claude":
            c = self.store.get("claude") or {}
            src = c.get("source", "Anthropic · Claude Code girişi")
            fa = c.get("fetched_at")
            t_str = dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M") if fa else now_dt.strftime("%H:%M")
            return f"Claude: {src} · {t_str}"
        elif key == "sys":
            s = self.store.get("sys") or {}
            src = s.get("source", "Bu bilgisayar (psutil)")
            return f"Sistem: {src} · Canlı"
        elif key == "wx":
            w = self.store.get("wx") or {}
            src = w.get("source", "open-meteo.com")
            fa = w.get("fetched_at")
            t_str = dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M") if fa else now_dt.strftime("%H:%M")
            return f"Hava: {src} · {t_str}"
        elif key == "clock":
            return now_dt.strftime("%d.%m.%Y %H:%M:%S")
        elif key.startswith("app_") and extra:
            title = extra.get("title", "")
            name = extra.get("name", "")
            cnt = extra.get("count", 1)
            return f"{title or name}" + (f" ({cnt} pencere)" if cnt > 1 else "")
        return ""

    def toggle_popover(self, pop_type: str, chip_rect: Optional[QRectF] = None) -> None:
        if self.popover.isVisible() and self.popover.pop_type == pop_type:
            self.popover.hide()
            return

        self.prepare_popover_content(pop_type)
        if chip_rect:
            screen = QGuiApplication.primaryScreen()
            geom = screen.availableGeometry() if screen else QRect(0, 0, 1536, 864)
            dpr = screen.devicePixelRatio() if screen else 1.25

            px = int(self.x() + chip_rect.x() + chip_rect.width() / 2 - self.popover.width() / 2)
            px = max(geom.left() + 10, min(geom.right() - self.popover.width() - 10, px))
            py = int(self.y() - self.popover.height() - 10)
            self.popover.move(px, py)
            self.popover.show()
            self.popover.activateWindow()

            winapi.enable_acrylic(int(self.popover.winId()), 0x50181612)
            winapi.set_round_region(int(self.popover.winId()), self.popover.width(), self.popover.height(), 14, dpr)
        else:
            self.popover.show()

    def prepare_popover_content(self, pop_type: str) -> None:
        now_dt = dt.datetime.now(sources.LOCAL_TZ)

        if pop_type == "claude":
            c = self.store.get("claude") or {}
            plan = (c.get("plan") or "Max").capitalize()
            s_val = float(c.get("session", 0.0))
            w_val = float(c.get("week", 0.0))
            s_reset = c.get("session_reset", "")
            w_reset = c.get("week_reset", "")

            s_clock = sources.reset_clock(s_reset)
            w_clock = sources.reset_clock(w_reset)
            s_left = sources.left_text(s_reset)
            w_left = sources.left_text(w_reset)

            s_sub = f"{s_left} sonra sıfırlanır ({s_clock})" if s_reset else ""
            w_sub = f"{w_left} sonra ({w_clock})" if w_reset else ""

            rows = [
                {
                    "label": "Oturum",
                    "val": f"%{s_val:.0f}",
                    "pct": s_val,
                    "col": get_ring_color(s_val, COLOR_CLAUDE_S),
                    "sub": s_sub,
                },
                {
                    "label": "Haftalık",
                    "val": f"%{w_val:.0f}",
                    "pct": w_val,
                    "col": get_ring_color(w_val, COLOR_CLAUDE_W),
                    "sub": w_sub,
                }
            ]
            fa = c.get("fetched_at")
            t_str = dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M") if fa else now_dt.strftime("%H:%M")
            src_line = f"Kaynak: {c.get('source', 'Anthropic · Claude Code girişi')} · {t_str}"
            self.popover.set_content("claude", "Claude", f"{plan}", rows, src_line)

        elif pop_type == "sys":
            s = self.store.get("sys") or {}
            cpu_val = float(s.get("cpu", 0.0))
            ram_val = float(s.get("ram", 0.0))
            ram_used = float(s.get("ram_used_gb", 0.0))
            ram_total = float(s.get("ram_total_gb", 0.0))

            rows = [
                {
                    "label": "İşlemci",
                    "val": f"%{cpu_val:.0f}",
                    "pct": cpu_val,
                    "col": get_ring_color(cpu_val, COLOR_CPU),
                },
                {
                    "label": "RAM",
                    "val": f"%{ram_val:.0f}",
                    "pct": ram_val,
                    "col": get_ring_color(ram_val, COLOR_RAM),
                    "sub": f"{ram_used:.1f} GB / {ram_total:.1f} GB kullanılan" if ram_total > 0 else None,
                }
            ]
            if "disk_c" in s:
                disk_val = float(s["disk_c"])
                rows.append({
                    "label": "Disk (C:)",
                    "val": f"%{disk_val:.0f}",
                    "pct": disk_val,
                    "col": get_ring_color(disk_val, QColor("#86efac")),
                })

            src_line = f"Kaynak: {s.get('source', 'Bu bilgisayar (psutil)')} · Canlı"
            self.popover.set_content("sys", "Sistem", None, rows, src_line)

        elif pop_type == "wx":
            w = self.store.get("wx") or {}
            city = self.settings.get("city", "Aksaray")
            temp = w.get("temp")
            temp_str = f"{temp:.1f}°" if temp is not None else "--°"
            feel = w.get("feel")
            feel_str = f"{feel:.1f}°" if feel is not None else "--°"
            desc = w.get("desc", "Bilinmiyor")
            min_t = w.get("min")
            max_t = w.get("max")
            wind = w.get("wind")

            sub1 = f"Hissedilen {feel_str}"
            if min_t is not None and max_t is not None:
                sub1 += f" · En düşük {min_t:.1f}° / En yüksek {max_t:.1f}°"
            sub2 = f"Rüzgar: {wind:.1f} km/s" if wind is not None else None

            rows = [
                {
                    "label": "Şimdi",
                    "val": f"{desc} {temp_str}",
                    "sub": sub1,
                }
            ]
            if sub2:
                rows.append({"label": "", "val": "", "sub": sub2})

            fa = w.get("fetched_at")
            t_str = dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M") if fa else now_dt.strftime("%H:%M")
            src_line = f"Kaynak: {w.get('source', 'open-meteo.com')} · {t_str}"
            self.popover.set_content("wx", f"Hava Durumu · {city}", None, rows, src_line)

        elif pop_type == "fx":
            f = self.store.get("fx") or {}
            usd = float(f.get("usd", 0.0))
            usd_chg = float(f.get("usd_chg", 0.0))
            eur = float(f.get("eur", 0.0))
            eur_chg = float(f.get("eur_chg", 0.0))
            gold = float(f.get("gold", 0.0))
            gold_chg = float(f.get("gold_chg", 0.0))

            def chg_col(val: float) -> QColor:
                if val > 0:
                    return QColor("#78dc96")
                if val < 0:
                    return QColor("#ff6e6e")
                return QColor(255, 255, 255, 160)

            rows = [
                {
                    "label": "Dolar",
                    "val": f"{sources.fmt_tr(usd, 2)} ₺ (%{sources.fmt_tr(usd_chg, 2)})",
                    "val_col": chg_col(usd_chg),
                },
                {
                    "label": "Euro",
                    "val": f"{sources.fmt_tr(eur, 2)} ₺ (%{sources.fmt_tr(eur_chg, 2)})",
                    "val_col": chg_col(eur_chg),
                },
                {
                    "label": "Gram altın",
                    "val": f"{sources.fmt_tr(gold, 0)} ₺ (%{sources.fmt_tr(gold_chg, 2)})",
                    "val_col": chg_col(gold_chg),
                }
            ]
            fa = f.get("fetched_at")
            t_str = f.get("updated") or (dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M") if fa else now_dt.strftime("%H:%M"))
            src_line = f"Kaynak: {f.get('source', 'finans.truncgil.com')} · veri {t_str}"
            self.popover.set_content("fx", "Piyasa (satış)", None, rows, src_line)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(22, 26, 36, 245);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
                padding: 4px;
                color: #e8ecf1;
                font-family: 'Segoe UI Variable Text';
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 25);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 25);
                margin: 4px 8px;
            }
        """)

        act_refresh = menu.addAction("Yenile")
        act_refresh.triggered.connect(self.action_refresh)

        act_fx = menu.addAction("Piyasa")
        act_fx.triggered.connect(lambda: self.toggle_popover("fx", QRectF(self.width() / 2 - 50, 0, 100, 38)))

        act_hide_tb = QAction("Windows görev çubuğunu gizle", menu)
        act_hide_tb.setCheckable(True)
        act_hide_tb.setChecked(self.settings.get("hide_taskbar", False))
        act_hide_tb.triggered.connect(self.action_toggle_taskbar)
        menu.addAction(act_hide_tb)

        act_reset_pos = menu.addAction("Konumu sıfırla")
        act_reset_pos.triggered.connect(self.action_reset_pos)

        menu.addSeparator()

        act_quit = menu.addAction("Kapat")
        act_quit.triggered.connect(QApplication.instance().quit)

        menu.exec(event.globalPos())

    def action_refresh(self) -> None:
        self.update_windows()
        for key in sources.REFRESH.keys():
            self.worker.run(key)

    def action_toggle_taskbar(self, checked: bool) -> None:
        self.settings["hide_taskbar"] = checked
        if checked:
            orig = winapi.taskbar_autohide_get()
            self.settings["taskbar_original"] = orig
            save_settings(self.settings)
            winapi.taskbar_autohide_set(True)
        else:
            orig = self.settings.get("taskbar_original")
            if orig is not None:
                winapi.taskbar_autohide_set(orig)
            save_settings(self.settings)

    def action_reset_pos(self) -> None:
        self.settings["pos"] = None
        save_settings(self.settings)
        self.place_dock()


def draw_wallpaper_gradient(p: QPainter, w: float, h: float) -> None:
    # 1. Taban doğrusal gradyan
    lg = QLinearGradient(0, 0, w * 0.9, h)
    lg.setColorAt(0, QColor("#1b2333"))
    lg.setColorAt(1, QColor("#0b0f16"))
    p.fillRect(QRectF(0, 0, w, h), lg)

    # 2. Radyal renk lekeleri (Mockup .dark .scene gradientleri)
    rads = [
        (0.18 * w, 0.72 * h, 0.26 * w, QColor("#ff8a3d"), 0.09 / 0.26),
        (0.52 * w, 0.88 * h, 0.30 * w, QColor("#3d7bff"), 0.11 / 0.30),
        (0.83 * w, 0.80 * h, 0.24 * w, QColor("#2fd3a5"), 0.08 / 0.24),
        (0.70 * w, 0.20 * h, 0.32 * w, QColor("#8a5cff"), 0.10 / 0.32),
    ]
    for cx, cy, rad, col, stop in rads:
        rg = QRadialGradient(QPointF(cx, cy), rad)
        c_start = QColor(col)
        c_start.setAlpha(170)
        c_mid = QColor(col)
        c_mid.setAlpha(90)
        c_end = QColor(col)
        c_end.setAlpha(0)
        rg.setColorAt(0, c_start)
        rg.setColorAt(min(1.0, stop), c_mid)
        rg.setColorAt(1.0, c_end)
        p.fillRect(QRectF(0, 0, w, h), rg)


def render_preview(output_path_str: str) -> None:
    """Preview mode with ZERO side effects: no taskbar calls, no window activation, no settings writes, no lock file."""
    # Canlı verileri doğrudan sources üzerinden çek
    settings = load_settings()
    store = sources.Store()

    claude_data = sources.fetch_claude()
    store.update("claude", claude_data)

    fx_data = sources.fetch_fx()
    store.update("fx", fx_data)

    wx_data = sources.fetch_weather(lat=settings.get("lat", 38.37), lon=settings.get("lon", 34.03))
    store.update("wx", wx_data)

    sys_data = sources.fetch_system()
    store.update("sys", sys_data)

    # Gerçek pencereler (salt-okunur)
    raw_wins = winapi.list_windows()
    groups = winapi.group_by_app(raw_wins)

    # Dock nesnesi (preview_mode=True: timer ve taskbar kapalı)
    dock = SeritDock(settings, preview_mode=True)
    dock.store = store
    dock.app_groups = groups[:10]
    dock.compute_layout_and_resize()

    dock_w = dock.width()
    dock_h = DOCK_HEIGHT

    # --- 1) Serit Dock Görüntüsü (<output_path>) ---
    cw1 = dock_w + 80
    ch1 = dock_h + 60
    img1 = QImage(int(cw1 * 2), int(ch1 * 2), QImage.Format_ARGB32_Premultiplied)
    img1.setDevicePixelRatio(2.0)
    img1.fill(0)

    p1 = QPainter(img1)
    p1.setRenderHint(QPainter.Antialiasing)
    p1.setRenderHint(QPainter.SmoothPixmapTransform)
    draw_wallpaper_gradient(p1, cw1, ch1)

    dock_x1 = 40
    dock_y1 = 30
    dock.render(p1, QPoint(dock_x1, dock_y1))
    p1.end()

    out_p = Path(output_path_str)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    img1.save(str(out_p))

    # --- 2) Popover Açık Görüntü (<output_path>_pop.png) ---
    dock.prepare_popover_content("claude")
    pop_h = dock.popover.height()

    cw2 = max(dock_w + 80, 560)
    ch2 = pop_h + 16 + dock_h + 50
    img2 = QImage(int(cw2 * 2), int(ch2 * 2), QImage.Format_ARGB32_Premultiplied)
    img2.setDevicePixelRatio(2.0)
    img2.fill(0)

    p2 = QPainter(img2)
    p2.setRenderHint(QPainter.Antialiasing)
    p2.setRenderHint(QPainter.SmoothPixmapTransform)
    draw_wallpaper_gradient(p2, cw2, ch2)

    dock_x2 = int((cw2 - dock_w) / 2)
    dock_y2 = int(ch2 - dock_h - 20)
    dock.render(p2, QPoint(dock_x2, dock_y2))

    pop_x2 = dock_x2 + 10
    pop_y2 = dock_y2 - pop_h - 12
    dock.popover.render(p2, QPoint(pop_x2, pop_y2))
    p2.end()

    if out_p.suffix:
        pop_out_path = out_p.parent / f"{out_p.stem}_pop{out_p.suffix}"
    else:
        pop_out_path = Path(f"{str(out_p)}_pop.png")

    img2.save(str(pop_out_path))

    # Bilgi çıktısı
    print(f"PREVIEW_SAVED: {out_p} ({cw1}x{ch1} @2x)")
    print(f"PREVIEW_POP_SAVED: {pop_out_path} ({cw2}x{ch2} @2x)")
    print(f"LIVE_CLAUDE: session={claude_data.get('session')}%, week={claude_data.get('week')}%, plan={claude_data.get('plan')}")
    print(f"LIVE_SYS: cpu={sys_data.get('cpu')}%, ram={sys_data.get('ram')}%")
    print(f"LIVE_WX: temp={wx_data.get('temp')}°, desc={wx_data.get('desc')}")
    print(f"LIVE_APPS_COUNT: {len(groups)}")


def main() -> None:
    # 1. Preview modu kontrolü
    if "--preview" in sys.argv:
        idx = sys.argv.index("--preview")
        if idx + 1 < len(sys.argv):
            out_file = sys.argv[idx + 1]
        else:
            out_file = str(APP_DIR / "serit_preview.png")
        app = QApplication(sys.argv)
        render_preview(out_file)
        return

    # 2. Normal mod: tekil çalışma kilidi
    lock = QLockFile(str(LOCK_FILE_PATH))
    if not lock.tryLock(100):
        print("Şerit zaten çalışıyor.")
        return

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    settings = load_settings()
    dock = SeritDock(settings, preview_mode=False)
    app.aboutToQuit.connect(dock.cleanup)
    dock.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
