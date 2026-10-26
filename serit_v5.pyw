"""Şerit v5 - Modern acrylic glass floating dock for Windows 11.

Integrates theme.py (design tokens & primitives), anim.py (zero-idle driver & tweens),
pinned.py (pinned apps & dark glass tiles), popover_v2.py (sectioned acrylic flyouts),
alerts.py (proactive notification toasts), tray.py (hidden icons overflow),
and media.py (volume slider popover, media keys & now-playing detection).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil
from PySide6.QtCore import (
    QEvent,
    QLockFile,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMenu, QToolTip, QWidget

import alerts
import anim
import media
import pinned
import popover_v2
import sources
import theme
import tray
import trayicons
import winapi

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
LOCK_FILE_PATH = APP_DIR / "serit.lock"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "hide_taskbar": False,
    "taskbar_original": None,
    "pos": None,
    "lat": 38.37,
    "lon": 34.03,
    "city": "Aksaray",
    "pinned": None,
    "alerts_enabled": True,
}

# Dimension Tokens for v5
DOCK_HEIGHT: float = 64.0
DOCK_RADIUS: float = 32.0
CHIP_HEIGHT: float = 40.0
CHIP_Y: float = 12.0
SEP_HEIGHT: float = 24.0
SEP_Y: float = 20.0
RY: float = 32.0
TILE_Y: float = 7.0
IND_Y: float = 56.5
VOL_CHIP_WIDTH: float = 76.0
MEDIA_CHIP_WIDTH: float = 204.0
TRAY_BTN_WIDTH: float = 30.0
TRAY_BTN_HEIGHT: float = 36.0

TR_DAYS = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}
_LAST_PAINT_ERROR_LOG: float = 0.0


def safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """Safely coerce any value to float, filtering None/NaN/Inf/TypeError."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


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


def draw_wallpaper_gradient(p: QPainter, w: float, h: float) -> None:
    """Renders dark radial glow wallpaper for preview offscreen snapshots."""
    lg = QLinearGradient(0, 0, w * 0.9, h)
    lg.setColorAt(0, QColor("#1b2333"))
    lg.setColorAt(1, QColor("#0b0f16"))
    p.fillRect(QRectF(0, 0, w, h), lg)

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


class BubbleWidget(QWidget):
    """Floating label bubble tooltip displayed above hovered tile."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._text: str = ""

    def show_bubble(self, global_anchor: QPointF, text: str) -> None:
        if not text:
            self.hide()
            return
        self._text = text
        f = theme.make_font(pinned.BUBBLE_FONT_SIZE, QFont.Weight.Medium)
        fm = QFontMetricsF(f)
        bw = fm.horizontalAdvance(text) + 2.0 * pinned.BUBBLE_PAD_H
        bh = fm.height() + 2.0 * pinned.BUBBLE_PAD_V
        self.resize(int(math.ceil(bw + 4)), int(math.ceil(bh + 4)))
        self.move(
            int(round(global_anchor.x() - bw / 2.0)),
            int(round(global_anchor.y() - pinned.BUBBLE_GAP - bh)),
        )
        self.show()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        pinned.draw_label_bubble(
            p,
            QPointF(self.width() / 2.0, float(self.height())),
            self._text,
            gap=0.0,
        )
        p.end()


class TrayPopover(QWidget):
    """^ düğmesinin açtığı kendi cam panelimiz: Windows'un gizli simgeleri (trayicons.py)."""

    COLS = 6
    TILE = 44.0
    PAD = 14.0
    HEAD = 30.0

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._items: list = []
        self._icons: dict = {}
        self._hits: list = []
        self._hover = -1
        self._closed_at = 0.0

    def recently_closed(self) -> bool:
        return (time.time() - self._closed_at) < 0.25

    def show_for(self, anchor_global: QRectF) -> None:
        self._items = trayicons.list_tray_items()
        self._icons = trayicons.get_tray_icons(self._items)
        rows = max(1, (len(self._items) + self.COLS - 1) // self.COLS)
        cols = max(1, min(self.COLS, len(self._items)))
        w = int(self.PAD * 2 + cols * self.TILE + (cols - 1) * 6)
        h = int(self.HEAD + self.PAD + rows * self.TILE + (rows - 1) * 6 + 6)
        self.resize(max(w, 200), h)
        scr = QGuiApplication.screenAt(anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = int(min(max(anchor_global.center().x() - self.width() / 2, g.left() + 8), g.right() - self.width() - 8))
        y = int(anchor_global.top() - self.height() - 10)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.25
        winapi.enable_acrylic(int(self.winId()), 0x50181612)
        winapi.set_round_region(int(self.winId()), self.width(), self.height(), 18, dpr)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow() and self.isVisible():
            self._closed_at = time.time()
            self.hide()
        super().changeEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self._closed_at = time.time()
            self.hide()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        try:
            self._hits = trayicons.draw_tray_panel(p, QRectF(self.rect()), self._items, self._icons, self._hover)
            if not self._items:
                p.setPen(theme.COLOR_TEXT_SECONDARY)
                p.drawText(QRectF(self.rect()), Qt.AlignCenter, "Gizli simge yok")
        except Exception as exc:
            sources.log_err("tray_paint", exc)
        p.end()

    def _index_at(self, pos) -> int:
        for i, r in enumerate(self._hits):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()
            if 0 <= i < len(self._items):
                QToolTip.showText(e.globalPosition().toPoint(), self._items[i].get("name", ""), self)

    def mouseReleaseEvent(self, e) -> None:
        i = self._index_at(e.position())
        if 0 <= i < len(self._items):
            btn = "right" if e.button() == Qt.RightButton else "left"
            self._closed_at = time.time()
            self.hide()
            trayicons.activate(self._items[i], button=btn)


class VolumePopover(QWidget):
    """Sectioned acrylic glass flyout panel for master audio volume control."""

    WIDTH: int = 280
    HEIGHT: int = 126

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_volume_change: Optional[Callable[[float, bool], None]] = None,
    ) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.parent_dock = parent
        self.on_volume_change = on_volume_change

        self._level: float = 50.0
        self._muted: bool = False
        self._device: str = ""
        self._is_dragging_slider: bool = False
        self._hit_rects: Dict[str, QRectF] = {}
        self.resize(self.WIDTH, self.HEIGHT)

    def show_for(
        self,
        anchor_global: QRectF,
        level: float,
        muted: bool,
        device: str = "",
    ) -> None:
        self._level = float(level)
        self._muted = bool(muted)
        self._device = device
        self.resize(self.WIDTH, self.HEIGHT)
        cx = anchor_global.center().x()
        x = int(round(cx - self.width() / 2.0))
        y = int(round(anchor_global.top() - self.height() - 10.0))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def update_volume(self, level: float, muted: bool, device: Optional[str] = None) -> None:
        self._level = float(level)
        self._muted = bool(muted)
        if device is not None:
            self._device = device
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r_card = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        self._hit_rects = media.draw_volume_slider_panel(
            p,
            r_card,
            level=self._level,
            muted=self._muted,
            device=self._device,
        )
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            r_mute = self._hit_rects.get("mute_btn")
            if r_mute and r_mute.contains(pos):
                if self.parent_dock and not getattr(self.parent_dock, "preview_mode", False):
                    media.toggle_mute()
                self._muted = not self._muted
                if self.on_volume_change:
                    self.on_volume_change(self._level, self._muted)
                self.update()
                return

            r_slider = self._hit_rects.get("slider")
            if r_slider and r_slider.adjusted(-8.0, -8.0, 8.0, 8.0).contains(pos):
                self._is_dragging_slider = True
                pct = max(0.0, min(100.0, (pos.x() - r_slider.left()) / r_slider.width() * 100.0))
                self._level = pct
                if self.parent_dock and not getattr(self.parent_dock, "preview_mode", False):
                    media.set_volume(pct)
                if self.on_volume_change:
                    self.on_volume_change(self._level, self._muted)
                self.update()
                return

            # Presets (25%, 50%, 75%, 100%)
            presets = [("25%", 25.0), ("50%", 50.0), ("75%", 75.0), ("100%", 100.0)]
            pad_x = 16.0
            preset_w = 34.0
            preset_h = 24.0
            preset_gap = 5.0
            presets_total = len(presets) * preset_w + (len(presets) - 1) * preset_gap
            start_px = float(self.width()) - pad_x - presets_total
            footer_y = r_slider.bottom() + 10.0 if r_slider else 78.0
            for idx, (_, val) in enumerate(presets):
                rp = QRectF(start_px + idx * (preset_w + preset_gap), footer_y, preset_w, preset_h)
                if rp.contains(pos):
                    self._level = val
                    if self.parent_dock and not getattr(self.parent_dock, "preview_mode", False):
                        media.set_volume(val)
                    if self.on_volume_change:
                        self.on_volume_change(self._level, self._muted)
                    self.update()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging_slider:
            r_slider = self._hit_rects.get("slider")
            if r_slider:
                pct = max(0.0, min(100.0, (event.position().x() - r_slider.left()) / r_slider.width() * 100.0))
                self._level = pct
                if self.parent_dock and not getattr(self.parent_dock, "preview_mode", False):
                    media.set_volume(pct)
                if self.on_volume_change:
                    self.on_volume_change(self._level, self._muted)
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._is_dragging_slider = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        diff = 2.0 if event.angleDelta().y() > 0 else -2.0
        self._level = max(0.0, min(100.0, self._level + diff))
        if self.parent_dock and not getattr(self.parent_dock, "preview_mode", False):
            media.set_volume(self._level)
        if self.on_volume_change:
            self.on_volume_change(self._level, self._muted)
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)


class DataDispatcher(QObject):
    """Thread-safe UI dispatcher bridging background fetcher thread pool to Qt signals."""

    data_ready = Signal(str, dict)


class SeritDock(QWidget):
    """Variant A: Floating Acrylic glass dock capsule with physical animations."""

    def __init__(self, settings: dict, preview_mode: bool = False):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.settings = settings
        self.preview_mode = preview_mode

        # Pinned apps and tiles state
        pins_raw = self.settings.get("pinned")
        if pins_raw is None:
            pins_raw = pinned.load_default_pins()
            if not self.preview_mode:
                self.settings["pinned"] = pins_raw
                save_settings(self.settings)
        self.pins: List[Dict[str, str]] = list(pins_raw or [])
        self.tiles: List[Dict[str, Any]] = []
        self._last_tiles_sig: Optional[tuple] = None
        self._tile_centers: List[float] = []
        self._tile_rects: List[QRectF] = []

        # Tile dragging state (horizontal reordering)
        self._drag_tile_idx: Optional[int] = None
        self._drag_tile_start_x: Optional[float] = None
        self._drag_tile_active: bool = False
        self._drag_tile_cur_x: Optional[float] = None

        # Data & window state
        self.store = sources.Store()
        self.app_groups: List[dict] = []
        self._last_groups_sig: Optional[tuple] = None
        self._app_cycle_indices: Dict[str, int] = {}
        self.hit_boxes: List[Tuple[QRectF, str, Any]] = []
        self._hover_key: Optional[str] = None
        self._hover_app_idx: Optional[int] = None
        self._preview_hover_idx: Optional[int] = None
        self._pressed_key: Optional[str] = None
        self._icon_cache: Dict[str, QPixmap] = {}
        self._clock_rect: Optional[QRectF] = None

        # Audio & Media state
        self._vol_level: float = 50.0
        self._vol_muted: bool = False
        self._vol_device: str = ""
        self._now_playing_info: Optional[Dict[str, Any]] = None
        self._media_hit_rects: Dict[str, QRectF] = {}

        v_init = media.get_volume()
        self._vol_level = float(v_init.get("level", 50.0))
        self._vol_muted = bool(v_init.get("muted", False))
        self._vol_device = str(v_init.get("device", ""))
        self._now_playing_info = media.now_playing()

        # Drag tracking (dock position)
        self._drag_start_pos: Optional[QPoint] = None
        self._window_start_pos: Optional[QPoint] = None
        self._is_dragging: bool = False

        # Central animation engine
        self.anim_driver = anim.get_default_driver()
        self.anim_driver.frame.connect(self.update)

        # Dynamic tweens
        self.anim_claude_s = anim.Tween(0.0, 0.0, theme.DUR_RING_SWEEP_SLOW, driver=self.anim_driver)
        self.anim_claude_w = anim.Tween(0.0, 0.0, theme.DUR_RING_SWEEP_SLOW, driver=self.anim_driver)
        self.anim_cpu = anim.Tween(0.0, 0.0, theme.DUR_RING_SWEEP_FAST, driver=self.anim_driver)
        self.anim_ram = anim.Tween(0.0, 0.0, theme.DUR_RING_SWEEP_FAST, driver=self.anim_driver)

        # Stale opacity tweens (fade to 45% when stale or error)
        self.anim_claude_op = anim.Tween(1.0, 1.0, theme.DUR_STALE_FADE, driver=self.anim_driver)
        self.anim_sys_op = anim.Tween(1.0, 1.0, theme.DUR_STALE_FADE, driver=self.anim_driver)
        self.anim_wx_op = anim.Tween(1.0, 1.0, theme.DUR_STALE_FADE, driver=self.anim_driver)

        # Active indicator gliding pill
        self.anim_pill_x = anim.Tween(0.0, 0.0, theme.DUR_PILL_GLIDE, driver=self.anim_driver)
        self.anim_pill_opacity = anim.Tween(0.0, 0.0, 160.0, driver=self.anim_driver)

        # Dock dynamic width tween
        self.dock_width_tween = anim.Tween(
            DOCK_HEIGHT, DOCK_HEIGHT, theme.DUR_DOCK_RESIZE, driver=self.anim_driver
        )
        self.dock_width_tween.on_update = self._on_width_tween_update

        # Tactile press spring
        self.press_tween = anim.PressTween(
            normal_scale=1.0,
            pressed_scale=theme.PRESS_SCALE,
            press_duration=theme.DUR_PRESS,
            release_duration=theme.DUR_RELEASE,
            driver=self.anim_driver,
        )

        # Typography cache
        self.f_lbl = theme.make_font(theme.FONT_SIZE_LBL, QFont.Weight.Normal, letter_spacing=0.2)
        self.f_val = theme.make_font(theme.FONT_SIZE_VAL, QFont.Weight.DemiBold, tabular=True)
        self.f_clock_time = theme.make_font(theme.FONT_SIZE_CLOCK, QFont.Weight.Bold, tabular=True)

        # Layout cached widths
        self._w_chip_s: float = 80.0
        self._w_chip_w: float = 80.0

        # Rich acrylic popover flyouts
        self.popover = popover_v2.PopoverV2(self, on_refresh=self.submit_fetch)
        self.vol_popover = VolumePopover(self, on_volume_change=self._on_volume_changed)
        self.tray_popover = TrayPopover()
        self.bubble = BubbleWidget(self)

        # Proactive alerts engine & toast manager (normal mode only)
        alerts_enabled = bool(self.settings.get("alerts_enabled", True))
        if not self.preview_mode:
            self.alert_engine: Optional[alerts.AlertEngine] = alerts.AlertEngine(
                state_path="D:/Apps/serit/alerts_state.json",
                enabled=alerts_enabled,
            )
            self.toast_mgr: Optional[alerts.ToastManager] = alerts.ToastManager()
        else:
            self.alert_engine = None
            self.toast_mgr = None

        # Data thread dispatcher & timers (normal mode only)
        if not self.preview_mode:
            self.dispatcher = DataDispatcher(self)
            self.dispatcher.data_ready.connect(self.on_data_ready)
            self.setup_timers()

    def sync_anim_values(self) -> None:
        """Instant snapshot synchronization for headless renders."""
        c = self.store.get("claude") or {}
        s = safe_float(c.get("session"), None)
        w = safe_float(c.get("week"), None)
        if s is not None:
            self.anim_claude_s.value = s
            self.anim_claude_s.target_val = s
        if w is not None:
            self.anim_claude_w.value = w
            self.anim_claude_w.target_val = w

        sys_d = self.store.get("sys") or {}
        cpu = safe_float(sys_d.get("cpu"), None)
        ram = safe_float(sys_d.get("ram"), None)
        if cpu is not None:
            self.anim_cpu.value = cpu
            self.anim_cpu.target_val = cpu
        if ram is not None:
            self.anim_ram.value = ram
            self.anim_ram.target_val = ram

    def start(self) -> None:
        """Start dock in normal mode with K3 taskbar safety check."""
        if self.settings.get("hide_taskbar", False):
            if self.settings.get("taskbar_original") is None:
                self.settings["taskbar_original"] = winapi.taskbar_autohide_get()
                save_settings(self.settings)
            winapi.taskbar_autohide_set(True)

        self.update_windows()
        self.compute_layout_and_resize(initial=True)
        self.place_dock()
        self.show()

        dpr = self.screen().devicePixelRatio() if self.screen() else 1.25
        winapi.enable_acrylic(int(self.winId()), 0x50181612)
        winapi.set_round_region(int(self.winId()), self.width(), int(DOCK_HEIGHT), int(DOCK_RADIUS), dpr)

        wh = self.windowHandle()
        if wh is not None:
            wh.screenChanged.connect(self._on_screen_changed)

    def _on_screen_changed(self, screen) -> None:
        dpr = screen.devicePixelRatio() if screen else 1.25
        winapi.set_round_region(int(self.winId()), self.width(), int(DOCK_HEIGHT), int(DOCK_RADIUS), dpr)
        self.update()

    def cleanup(self) -> None:
        """K3 Safe taskbar restoration on quit."""
        if self.settings.get("hide_taskbar", False):
            orig = self.settings.get("taskbar_original")
            if orig is not None:
                try:
                    winapi.taskbar_autohide_set(bool(orig))
                except Exception:
                    pass
                self.settings["taskbar_original"] = None
                save_settings(self.settings)

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()

    def setup_timers(self) -> None:
        psutil.cpu_percent(None)

        # Background thread pool fetch timers
        for key, sec in sources.REFRESH.items():
            timer = QTimer(self)
            timer.setInterval(sec * 1000)
            timer.timeout.connect(lambda k=key: self.submit_fetch(k))
            timer.start()
            self.submit_fetch(key)

        # Open windows polling timer (1.5 s)
        self.win_timer = QTimer(self)
        self.win_timer.setInterval(1500)
        self.win_timer.timeout.connect(self.update_windows)
        self.win_timer.start()

        # Media & Volume polling timer (3 s)
        self.media_timer = QTimer(self)
        self.media_timer.setInterval(3000)
        self.media_timer.timeout.connect(self._poll_media_and_volume)
        self.media_timer.start()

        # Clock refresh timer (10 s) - repaints only the clock rect (Requirement 6)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(10000)
        self.clock_timer.timeout.connect(self._on_clock_tick)
        self.clock_timer.start()

    def _on_clock_tick(self) -> None:
        """Repaint only the clock rect for near-zero idle CPU."""
        if self._clock_rect is not None:
            self.update(self._clock_rect.toRect().adjusted(-2, -2, 2, 2))
        else:
            self.update()

    def _poll_media_and_volume(self) -> None:
        """Poll volume and now-playing heuristics on UI thread; only repaint on change."""
        changed = False
        v_data = media.get_volume()
        lvl = float(v_data.get("level", 50.0))
        muted = bool(v_data.get("muted", False))
        dev = str(v_data.get("device", ""))
        if lvl != self._vol_level or muted != self._vol_muted or dev != self._vol_device:
            self._vol_level = lvl
            self._vol_muted = muted
            self._vol_device = dev
            if self.vol_popover.isVisible():
                self.vol_popover.update_volume(lvl, muted, dev)
            changed = True

        np = media.now_playing()
        if np != self._now_playing_info:
            self._now_playing_info = np
            changed = True

        if changed:
            self.compute_layout_and_resize()
            self.update()

    def _on_volume_changed(self, lvl: float, muted: bool) -> None:
        self._vol_level = float(lvl)
        self._vol_muted = bool(muted)
        self.update()

    def submit_fetch(self, key: str) -> None:
        fetchers = {
            "claude": sources.fetch_claude,
            "fx": sources.fetch_fx,
            "wx": lambda: sources.fetch_weather(
                lat=self.settings.get("lat", 38.37), lon=self.settings.get("lon", 34.03)
            ),
            "sys": sources.fetch_system,
            "cal": sources.fetch_calendar,
        }
        fn = fetchers.get(key)
        if fn:
            sources.submit(key, fn, lambda k, res: self.dispatcher.data_ready.emit(k, res))

    def on_data_ready(self, key: str, res: dict) -> None:
        if isinstance(res, dict) and "err" in res:
            sources.log_err(key, RuntimeError(str(res.get("err"))))
        self.store.update(key, res)

        # Tween retargeting: only when value changed by >= 1 point (Requirement 6)
        if key == "claude":
            s = safe_float(res.get("session"), None)
            w = safe_float(res.get("week"), None)
            has_err = ("err" in res) or (s is None and w is None)
            self.anim_claude_op.retarget(0.45 if has_err else 1.0)
            if s is not None and abs(s - self.anim_claude_s.target_val) >= 1.0:
                self.anim_claude_s.retarget(s)
            if w is not None and abs(w - self.anim_claude_w.target_val) >= 1.0:
                self.anim_claude_w.retarget(w)
        elif key == "sys":
            cpu = safe_float(res.get("cpu"), None)
            ram = safe_float(res.get("ram"), None)
            has_err = ("err" in res) or (cpu is None and ram is None)
            self.anim_sys_op.retarget(0.45 if has_err else 1.0)
            if cpu is not None and abs(cpu - self.anim_cpu.target_val) >= 1.0:
                self.anim_cpu.retarget(cpu)
            if ram is not None and abs(ram - self.anim_ram.target_val) >= 1.0:
                self.anim_ram.retarget(ram)
        elif key == "wx":
            has_err = ("err" in res) or (res.get("temp") is None)
            self.anim_wx_op.retarget(0.45 if has_err else 1.0)

        # Proactive alerts engine evaluation in normal mode (Requirement 5)
        if not self.preview_mode and self.alert_engine is not None and self.toast_mgr is not None:
            try:
                new_alerts = self.alert_engine.evaluate(self.store)
                for a in new_alerts:
                    self.toast_mgr.show(a)
            except Exception as exc:
                sources.log_err("alerts", exc)

        self.compute_layout_and_resize()
        self.update()

    def update_windows(self) -> None:
        """Y6 Protected window update: skips layout and repaint if list is unchanged."""
        raw_wins = winapi.list_windows()
        groups = winapi.group_by_app(raw_wins)
        tiles = pinned.merge_tiles(self.pins, groups)

        sig = tuple(
            (
                t.get("key"),
                t.get("name"),
                t.get("pinned"),
                t.get("running"),
                t.get("active"),
                t.get("count"),
                tuple(t.get("hwnds", [])),
            )
            for t in tiles
        )
        if sig != self._last_tiles_sig:
            self._last_tiles_sig = sig
            self.tiles = tiles
            self.compute_layout_and_resize()
            self._update_pill_glide()
            self.update()

    def _update_pill_glide(self) -> None:
        """Calculates and glides active application indicator pill."""
        active_idx = next((i for i, t in enumerate(self.tiles) if t.get("active")), None)
        if active_idx is not None and self._tile_centers and active_idx < len(self._tile_centers):
            target_cx = self._tile_centers[active_idx]
            if self.anim_pill_opacity.value < 0.05:
                self.anim_pill_x.value = target_cx
                self.anim_pill_x.target_val = target_cx
                self.anim_pill_opacity.retarget(1.0)
            else:
                self.anim_pill_x.retarget(target_cx)
                self.anim_pill_opacity.retarget(1.0)
        else:
            self.anim_pill_opacity.retarget(0.0)

    def get_app_icon(self, exe: str) -> QPixmap:
        if not exe:
            return QPixmap()
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
            x = int(round(cx - self.width() / 2.0))
            self.move(x, int(y))
        else:
            x = int(round(geom.center().x() - self.width() / 2.0))
            y = int(geom.bottom() - DOCK_HEIGHT - 12)
            self.move(x, y)

    def _on_width_tween_update(self, val: float) -> None:
        curr_w = int(round(val))
        if curr_w != self.width() and self.isVisible():
            cx = self.x() + self.width() / 2.0
            self.resize(curr_w, int(DOCK_HEIGHT))
            new_x = int(round(cx - curr_w / 2.0))
            self.move(new_x, self.y())
            dpr = self.screen().devicePixelRatio() if self.screen() else 1.25
            winapi.set_round_region(int(self.winId()), curr_w, int(DOCK_HEIGHT), int(DOCK_RADIUS), dpr)

    def compute_layout_and_resize(self, initial: bool = False) -> None:
        """Computes pixel-precise layout with symmetrical padding and animates dock width."""
        fm_lbl = QFontMetricsF(self.f_lbl)
        fm_val = QFontMetricsF(self.f_val)
        fm_clock = QFontMetricsF(self.f_clock_time)

        # 1. Claude Oturum
        c_entry = self.store.get("claude") or {}
        s_reset = c_entry.get("session_reset", "")
        s_left = sources.left_text(s_reset) if (s_reset and isinstance(s_reset, str)) else "--"
        if "err" in c_entry and not s_reset:
            s_left = "–"
        w_s_text = max(fm_lbl.horizontalAdvance("Oturum"), fm_val.horizontalAdvance(s_left))
        self._w_chip_s = theme.CHIP_PAD_X * 2 + theme.RING_SIZE + 7.0 + w_s_text

        # 2. Claude Hafta
        w_reset = c_entry.get("week_reset", "")
        w_left = sources.left_text(w_reset) if (w_reset and isinstance(w_reset, str)) else "--"
        if "err" in c_entry and not w_reset:
            w_left = "–"
        w_w_text = max(fm_lbl.horizontalAdvance("Hafta"), fm_val.horizontalAdvance(w_left))
        self._w_chip_w = theme.CHIP_PAD_X * 2 + theme.RING_SIZE + 7.0 + w_w_text

        # 3. Separator 1
        w_sep1 = theme.GAP_SEPARATOR * 2 + theme.SEP_WIDTH

        # 4. Apps (pinned + running merged tiles via pinned.TILE = 46px)
        n_tiles = len(self.tiles)
        w_tiles = (n_tiles * pinned.TILE + max(0, n_tiles - 1) * pinned.GAP) if n_tiles > 0 else 0.0

        # 5. Separator 2 (only if tiles > 0)
        w_sep2 = (theme.GAP_SEPARATOR * 2 + theme.SEP_WIDTH) if n_tiles > 0 else 0.0

        # 6. Telemetry chip
        w_sys = 90.0

        # 7. Volume chip
        w_vol = VOL_CHIP_WIDTH

        # 8. Media chip (only if now_playing returns something)
        has_media = bool(self._now_playing_info)

        # 9. Separator 3
        w_sep3 = theme.GAP_SEPARATOR * 2 + theme.SEP_WIDTH

        # 10. Weather
        wx_entry = self.store.get("wx") or {}
        desc = str(wx_entry.get("desc") or "Yükleniyor")
        temp = safe_float(wx_entry.get("temp"), None)
        temp_str = f"{int(round(temp))}°" if temp is not None else "–°"
        w_wx_text = max(fm_lbl.horizontalAdvance(desc), fm_val.horizontalAdvance(temp_str))
        w_wx = theme.CHIP_PAD_X * 2 + 22.0 + 7.0 + w_wx_text

        # 11. Clock
        now = dt.datetime.now(sources.LOCAL_TZ)
        time_str = now.strftime("%H:%M")
        date_str = f"{TR_DAYS.get(now.weekday(), '')} {now.day} {sources.TR_MONTHS.get(now.month, '')}"
        w_clock_text = max(fm_clock.horizontalAdvance(time_str), fm_lbl.horizontalAdvance(date_str))
        w_clock = theme.CHIP_PAD_X * 2 + w_clock_text

        # 12. Tray Chevron Button
        w_tray = TRAY_BTN_WIDTH

        # Total dock capsule width
        items = [self._w_chip_s, theme.GAP_MODULE, self._w_chip_w, w_sep1]
        if n_tiles > 0:
            items.extend([w_tiles, w_sep2])
        items.extend([w_sys, theme.GAP_MODULE, w_vol])
        if has_media:
            items.extend([theme.GAP_MODULE, MEDIA_CHIP_WIDTH])
        items.extend([w_sep3, w_wx, theme.GAP_MODULE, w_clock, theme.GAP_MODULE, w_tray])

        total_w = int(math.ceil(theme.DOCK_PAD_X * 2 + sum(items)))

        if initial or self.preview_mode or not self.isVisible():
            self.resize(total_w, int(DOCK_HEIGHT))
            self.dock_width_tween.value = float(total_w)
            self.dock_width_tween.target_val = float(total_w)
        else:
            if total_w != int(round(self.dock_width_tween.target_val)):
                self.dock_width_tween.retarget(total_w)

    def paintEvent(self, _event) -> None:
        """K1 Defensive painter: isolates paint errors and prevents process crashes."""
        global _LAST_PAINT_ERROR_LOG
        p = QPainter(self)
        try:
            self._paint_content(p)
        except Exception as exc:
            now = time.time()
            if now - _LAST_PAINT_ERROR_LOG > 60.0:
                _LAST_PAINT_ERROR_LOG = now
                sources.log_err("paintEvent", exc)
        finally:
            p.end()

    def _paint_content(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. Physical Glass Capsule with Specular Rim & Grain
        r_dock = QRectF(0.5, 0.5, self.width() - 1.0, DOCK_HEIGHT - 1.0)
        theme.draw_glass_capsule(p, r_dock, radius=DOCK_RADIUS)

        self.hit_boxes.clear()
        x = theme.DOCK_PAD_X
        ry = RY

        # Data & opacities
        c_entry = self.store.get("claude") or {}
        c_err = ("err" in c_entry) or (
            c_entry.get("session") is None and c_entry.get("week") is None and "session_reset" not in c_entry
        )
        s_pct = safe_float(c_entry.get("session"), None)
        s_reset = c_entry.get("session_reset", "")
        s_left = sources.left_text(s_reset) if (s_reset and isinstance(s_reset, str)) else ("–" if c_err else "--")

        fm_lbl = QFontMetricsF(self.f_lbl)
        fm_val = QFontMetricsF(self.f_val)
        fm_clock = QFontMetricsF(self.f_clock_time)

        # A) Claude Oturum Chip
        w_s_text = max(fm_lbl.horizontalAdvance("Oturum"), fm_val.horizontalAdvance(s_left))
        chip_s_w = theme.CHIP_PAD_X * 2 + theme.RING_SIZE + 7.0 + w_s_text
        r_chip_s = QRectF(x, CHIP_Y, chip_s_w, CHIP_HEIGHT)
        self.hit_boxes.append((r_chip_s, "claude", None))

        claude_op = self.anim_claude_op.value
        p.save()
        if self._hover_key in ("claude_s", "claude"):
            p.fillPath(theme.rounded_path(r_chip_s, theme.CHIP_RADIUS), theme.COLOR_CHIP_HOVER)

        if self._pressed_key in ("claude_s", "claude") and self.press_tween.scale != 1.0:
            ps = self.press_tween.scale
            pc = r_chip_s.center()
            p.translate(pc)
            p.scale(ps, ps)
            p.translate(-pc)

        rx = x + theme.CHIP_PAD_X + theme.RING_SIZE / 2.0
        if c_err or s_pct is None:
            theme.draw_ring_gauge(
                p,
                QPointF(rx, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=0.0,
                text="–",
                colour=theme.COLOR_CLAUDE_SESSION,
                opacity=claude_op,
            )
            p.setFont(self.f_lbl)
            p.setPen(theme.COLOR_ALERT_WARN)
            p.drawText(
                QRectF(rx + theme.RING_SIZE / 2.0 + 7.0, CHIP_Y + 3.0, w_s_text + 4.0, 12.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                "Oturum",
            )
            p.setFont(self.f_val)
            p.setPen(theme.COLOR_TEXT_MUTED)
            p.drawText(
                QRectF(rx + theme.RING_SIZE / 2.0 + 7.0, CHIP_Y + 16.0, w_s_text + 4.0, 16.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                s_left,
            )
        else:
            val_disp = self.anim_claude_s.value if not self.preview_mode else s_pct
            theme.draw_ring_gauge(
                p,
                QPointF(rx, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=val_disp,
                colour=theme.COLOR_CLAUDE_SESSION,
                opacity=claude_op,
            )
            theme.draw_chip_text(
                p,
                rx + theme.RING_SIZE / 2.0 + 7.0,
                y=CHIP_Y - 8.0,
                label="Oturum",
                value=s_left,
                label_w=w_s_text,
                value_w=w_s_text,
                opacity=claude_op,
            )
        p.restore()

        x += chip_s_w + theme.GAP_MODULE

        # B) Claude Hafta Chip
        w_pct = safe_float(c_entry.get("week"), None)
        w_reset = c_entry.get("week_reset", "")
        w_left = sources.left_text(w_reset) if (w_reset and isinstance(w_reset, str)) else ("–" if c_err else "--")

        w_w_text = max(fm_lbl.horizontalAdvance("Hafta"), fm_val.horizontalAdvance(w_left))
        chip_w_w = theme.CHIP_PAD_X * 2 + theme.RING_SIZE + 7.0 + w_w_text
        r_chip_w = QRectF(x, CHIP_Y, chip_w_w, CHIP_HEIGHT)
        self.hit_boxes.append((r_chip_w, "claude", None))

        p.save()
        if self._hover_key in ("claude_w", "claude"):
            p.fillPath(theme.rounded_path(r_chip_w, theme.CHIP_RADIUS), theme.COLOR_CHIP_HOVER)

        if self._pressed_key in ("claude_w", "claude") and self.press_tween.scale != 1.0:
            ps = self.press_tween.scale
            pc = r_chip_w.center()
            p.translate(pc)
            p.scale(ps, ps)
            p.translate(-pc)

        rx = x + theme.CHIP_PAD_X + theme.RING_SIZE / 2.0
        if c_err or w_pct is None:
            theme.draw_ring_gauge(
                p,
                QPointF(rx, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=0.0,
                text="–",
                colour=theme.COLOR_CLAUDE_WEEK,
                opacity=claude_op,
            )
            p.setFont(self.f_lbl)
            p.setPen(theme.COLOR_ALERT_WARN)
            p.drawText(
                QRectF(rx + theme.RING_SIZE / 2.0 + 7.0, CHIP_Y + 3.0, w_w_text + 4.0, 12.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                "Hafta",
            )
            p.setFont(self.f_val)
            p.setPen(theme.COLOR_TEXT_MUTED)
            p.drawText(
                QRectF(rx + theme.RING_SIZE / 2.0 + 7.0, CHIP_Y + 16.0, w_w_text + 4.0, 16.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                w_left,
            )
        else:
            val_disp = self.anim_claude_w.value if not self.preview_mode else w_pct
            theme.draw_ring_gauge(
                p,
                QPointF(rx, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=val_disp,
                colour=theme.COLOR_CLAUDE_WEEK,
                opacity=claude_op,
            )
            theme.draw_chip_text(
                p,
                rx + theme.RING_SIZE / 2.0 + 7.0,
                y=CHIP_Y - 8.0,
                label="Hafta",
                value=w_left,
                label_w=w_w_text,
                value_w=w_w_text,
                opacity=claude_op,
            )
        p.restore()

        x += chip_w_w + theme.GAP_SEPARATOR

        # C) Separator 1
        theme.draw_separator(p, x, y=SEP_Y, height=SEP_HEIGHT)
        x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

        # D) Apps Strip (Pinned + Running Tiles via pinned.draw_tile, 46px)
        n_tiles = len(self.tiles)
        hover_idx = self._preview_hover_idx if self._preview_hover_idx is not None else self._hover_app_idx
        scales_lifts = anim.HoverMagnifier.compute_for_index(n_tiles, hover_idx)

        self._tile_centers = []
        self._tile_rects = []
        active_idx = next((i for i, t in enumerate(self.tiles) if t.get("active")), None)

        for i, t in enumerate(self.tiles):
            tile_x = x + i * (pinned.TILE + pinned.GAP)
            r_slot = QRectF(tile_x, TILE_Y, pinned.TILE, pinned.TILE)
            self._tile_rects.append(r_slot)
            self._tile_centers.append(r_slot.center().x())

            app_key = f"app_{i}"
            self.hit_boxes.append((r_slot, app_key, t))

            is_h = hover_idx == i
            hover_t = 1.0 if is_h else 0.0
            scale, lift_y = scales_lifts[i] if i < len(scales_lifts) else (1.0, 0.0)

            press_scale = 1.0
            if self._pressed_key == app_key and self.press_tween.scale != 1.0:
                press_scale = self.press_tween.scale

            pix = self.get_app_icon(t.get("exe", ""))

            r_draw = QRectF(r_slot.x(), r_slot.y() + lift_y, r_slot.width(), r_slot.height())

            t_draw = dict(t)
            is_active = bool(t.get("active", False))
            if is_active:
                t_draw["active"] = False

            pinned.draw_tile(
                p=p,
                rect=r_draw,
                tile=t_draw,
                pixmap=pix,
                hover_t=hover_t,
                press_scale=press_scale * scale,
                dot_count=t.get("count"),
                indicator_y=IND_Y,
            )

        # Draw gliding active indicator pill
        if active_idx is not None and self._tile_centers and active_idx < len(self._tile_centers):
            pill_cx = (
                self.anim_pill_x.value
                if (not self.preview_mode and self.anim_pill_opacity.value > 0.01)
                else self._tile_centers[active_idx]
            )
            op = self.anim_pill_opacity.value if not self.preview_mode else 1.0
            if op > 0.01:
                p.save()
                p.setOpacity(op)
                theme.draw_app_indicator(
                    p,
                    center_x=pill_cx,
                    center_y=IND_Y,
                    width=theme.INDICATOR_ACTIVE_W,
                    height=theme.INDICATOR_ACTIVE_H,
                    radius=theme.INDICATOR_ACTIVE_R,
                    is_active=True,
                )
                p.restore()

        if n_tiles > 0:
            x += n_tiles * pinned.TILE + (n_tiles - 1) * pinned.GAP
            x += theme.GAP_SEPARATOR
            theme.draw_separator(p, x, y=SEP_Y, height=SEP_HEIGHT)
            x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

        # E) Hardware Telemetry Chip (CPU & RAM)
        sys_entry = self.store.get("sys") or {}
        sys_err = ("err" in sys_entry) or (sys_entry.get("cpu") is None and sys_entry.get("ram") is None)
        cpu_val = safe_float(sys_entry.get("cpu"), None)
        ram_val = safe_float(sys_entry.get("ram"), None)

        chip_sys_w = 90.0
        r_chip_sys = QRectF(x, CHIP_Y, chip_sys_w, CHIP_HEIGHT)
        self.hit_boxes.append((r_chip_sys, "sys", None))

        sys_op = self.anim_sys_op.value
        p.save()
        if self._hover_key == "sys":
            p.fillPath(theme.rounded_path(r_chip_sys, theme.CHIP_RADIUS), theme.COLOR_CHIP_HOVER)

        if self._pressed_key == "sys" and self.press_tween.scale != 1.0:
            ps = self.press_tween.scale
            pc = r_chip_sys.center()
            p.translate(pc)
            p.scale(ps, ps)
            p.translate(-pc)

        rx_cpu = x + theme.CHIP_PAD_X + theme.RING_SIZE / 2.0
        rx_ram = rx_cpu + theme.RING_SIZE + 6.0

        if sys_err or cpu_val is None:
            theme.draw_ring_gauge(
                p,
                QPointF(rx_cpu, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=0.0,
                text="–",
                colour=theme.COLOR_CPU,
                opacity=sys_op,
            )
        else:
            cpu_disp = self.anim_cpu.value if not self.preview_mode else cpu_val
            theme.draw_ring_gauge(
                p,
                QPointF(rx_cpu, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=cpu_disp,
                colour=theme.COLOR_CPU,
                opacity=sys_op,
            )

        if sys_err or ram_val is None:
            theme.draw_ring_gauge(
                p,
                QPointF(rx_ram, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=0.0,
                text="–",
                colour=theme.COLOR_RAM,
                opacity=sys_op,
            )
        else:
            ram_disp = self.anim_ram.value if not self.preview_mode else ram_val
            theme.draw_ring_gauge(
                p,
                QPointF(rx_ram, ry),
                size=theme.RING_SIZE,
                stroke=theme.RING_STROKE,
                value_0_100=ram_disp,
                colour=theme.COLOR_RAM,
                opacity=sys_op,
            )
        p.restore()

        x += chip_sys_w + theme.GAP_MODULE

        # F) Volume Chip
        r_chip_vol = QRectF(x, CHIP_Y, VOL_CHIP_WIDTH, CHIP_HEIGHT)
        self.hit_boxes.append((r_chip_vol, "vol", None))
        vol_h_t = 1.0 if (self._hover_key == "vol") else 0.0
        media.draw_volume_chip(
            p,
            r_chip_vol,
            level=self._vol_level,
            muted=self._vol_muted,
            hover_t=vol_h_t,
        )
        x += VOL_CHIP_WIDTH

        # G) Media Chip (only when now_playing returns something)
        if self._now_playing_info:
            x += theme.GAP_MODULE
            r_chip_media = QRectF(x, CHIP_Y, MEDIA_CHIP_WIDTH, CHIP_HEIGHT)
            self.hit_boxes.append((r_chip_media, "media", self._now_playing_info))
            med_h_t = 1.0 if (self._hover_key == "media") else 0.0
            self._media_hit_rects = media.draw_media_chip(
                p,
                r_chip_media,
                self._now_playing_info,
                playing=bool(self._now_playing_info.get("playing", True)),
                hover_t=med_h_t,
            )
            x += MEDIA_CHIP_WIDTH

        # Separator 3
        x += theme.GAP_SEPARATOR
        theme.draw_separator(p, x, y=SEP_Y, height=SEP_HEIGHT)
        x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

        # H) Weather Chip
        wx_entry = self.store.get("wx") or {}
        wx_err = ("err" in wx_entry) or (wx_entry.get("temp") is None)
        desc = str(wx_entry.get("desc") or ("Bağlantı yok" if wx_err else "Yükleniyor"))
        temp = safe_float(wx_entry.get("temp"), None)
        temp_str = f"{int(round(temp))}°" if temp is not None else "–°"
        wx_icon = str(wx_entry.get("icon") or "cloud")

        w_wx_text = max(fm_lbl.horizontalAdvance(desc), fm_val.horizontalAdvance(temp_str))
        chip_wx_w = theme.CHIP_PAD_X * 2 + 22.0 + 7.0 + w_wx_text
        r_chip_wx = QRectF(x, CHIP_Y, chip_wx_w, CHIP_HEIGHT)
        self.hit_boxes.append((r_chip_wx, "wx", None))

        wx_op = self.anim_wx_op.value
        p.save()
        if self._hover_key == "wx":
            p.fillPath(theme.rounded_path(r_chip_wx, theme.CHIP_RADIUS), theme.COLOR_CHIP_HOVER)

        if self._pressed_key == "wx" and self.press_tween.scale != 1.0:
            ps = self.press_tween.scale
            pc = r_chip_wx.center()
            p.translate(pc)
            p.scale(ps, ps)
            p.translate(-pc)

        wx_rect = QRectF(x + theme.CHIP_PAD_X, (DOCK_HEIGHT - 22.0) / 2.0, 22.0, 22.0)
        theme.draw_weather_icon(p, wx_rect, icon=wx_icon)

        wx_tx = x + theme.CHIP_PAD_X + 22.0 + 7.0
        if wx_err:
            p.setFont(self.f_lbl)
            p.setPen(theme.COLOR_ALERT_WARN)
            p.drawText(QRectF(wx_tx, CHIP_Y + 3.0, w_wx_text + 4.0, 12.0), Qt.AlignLeft | Qt.AlignVCenter, desc)
            p.setFont(self.f_val)
            p.setPen(theme.COLOR_TEXT_MUTED)
            p.drawText(QRectF(wx_tx, CHIP_Y + 16.0, w_wx_text + 4.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, temp_str)
        else:
            theme.draw_chip_text(
                p, wx_tx, y=CHIP_Y - 8.0, label=desc, value=temp_str, label_w=w_wx_text, value_w=w_wx_text, opacity=wx_op
            )
        p.restore()

        x += chip_wx_w + theme.GAP_MODULE

        # I) Clock & Date Chip
        now = dt.datetime.now(sources.LOCAL_TZ)
        time_str = now.strftime("%H:%M")
        date_str = f"{TR_DAYS.get(now.weekday(), '')} {now.day} {sources.TR_MONTHS.get(now.month, '')}"
        w_clock_text = max(fm_clock.horizontalAdvance(time_str), fm_lbl.horizontalAdvance(date_str))
        chip_clock_w = theme.CHIP_PAD_X * 2 + w_clock_text
        r_chip_clock = QRectF(x, CHIP_Y, chip_clock_w, CHIP_HEIGHT)
        self._clock_rect = r_chip_clock
        self.hit_boxes.append((r_chip_clock, "clock", None))

        p.save()
        if self._hover_key == "clock":
            p.fillPath(theme.rounded_path(r_chip_clock, theme.CHIP_RADIUS), theme.COLOR_CHIP_HOVER)

        if self._pressed_key == "clock" and self.press_tween.scale != 1.0:
            ps = self.press_tween.scale
            pc = r_chip_clock.center()
            p.translate(pc)
            p.scale(ps, ps)
            p.translate(-pc)

        cx_text = x + theme.CHIP_PAD_X
        p.setFont(self.f_clock_time)
        p.setPen(theme.COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(cx_text, CHIP_Y + 3.0, w_clock_text + 4.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, time_str)

        p.setFont(self.f_lbl)
        p.setPen(theme.COLOR_TEXT_SECONDARY)
        p.drawText(QRectF(cx_text, CHIP_Y + 19.0, w_clock_text + 4.0, 14.0), Qt.AlignLeft | Qt.AlignVCenter, date_str)

        # Bugün (ya da 3 saat içinde) takvimde bir şey varsa sağ üstte küçük kırmızı nokta.
        try:
            cal = self.store.get("cal") or {}
            soon = False
            for ev in cal.get("events") or []:
                st = ev.get("start")
                if st is not None and (st.date() <= now.date() or (st - now).total_seconds() < 3 * 3600):
                    soon = True
                    break
            if soon:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.COLOR_ALERT_CRIT)
                p.drawEllipse(QPointF(r_chip_clock.right() - 5.0, CHIP_Y + 6.0), 3.0, 3.0)
        except Exception as exc:
            sources.log_err("cal_dot", exc)
        p.restore()

        x += chip_clock_w + theme.GAP_MODULE

        # J) Hidden Icons Chevron Button (tray.draw_chevron_button)
        r_btn_tray = QRectF(x, (DOCK_HEIGHT - TRAY_BTN_HEIGHT) / 2.0, TRAY_BTN_WIDTH, TRAY_BTN_HEIGHT)
        self.hit_boxes.append((r_btn_tray, "tray", None))
        tray_h_t = 1.0 if (self._hover_key == "tray") else 0.0
        tray.draw_chevron_button(p, r_btn_tray, hover_t=tray_h_t, open_state=False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._window_start_pos = self.pos()
            self._is_dragging = False

            pos = event.position()
            for r, key, extra in self.hit_boxes:
                if r.contains(pos):
                    self._pressed_key = key
                    self.press_tween.press()
                    if key.startswith("app_"):
                        try:
                            self._drag_tile_idx = int(key.split("_")[1])
                            self._drag_tile_start_x = pos.x()
                            self._drag_tile_cur_x = pos.x()
                            self._drag_tile_active = False
                        except (IndexError, ValueError):
                            self._drag_tile_idx = None
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if event.buttons() & Qt.LeftButton:
            # Check tile horizontal drag (> 6 px)
            if self._drag_tile_idx is not None and self._drag_tile_start_x is not None:
                dx = abs(pos.x() - self._drag_tile_start_x)
                if not self._drag_tile_active and dx > 6.0:
                    self._drag_tile_active = True
                if self._drag_tile_active:
                    self._drag_tile_cur_x = pos.x()
                    return

            # Check dock window dragging
            if self._drag_start_pos:
                delta = event.globalPosition().toPoint() - self._drag_start_pos
                if not self._is_dragging and delta.manhattanLength() > 5:
                    self._is_dragging = True
                if self._is_dragging and self._window_start_pos:
                    self.move(self._window_start_pos + delta)
                    return

        new_hover = None
        new_app_idx = None
        tooltip_text = ""
        for r, key, extra in self.hit_boxes:
            if r.contains(pos):
                new_hover = key
                if key.startswith("app_"):
                    try:
                        new_app_idx = int(key.split("_")[1])
                    except (IndexError, ValueError):
                        new_app_idx = None
                tooltip_text = self.get_tooltip_text(key, extra)
                break

        if new_hover != self._hover_key or new_app_idx != self._hover_app_idx:
            self._hover_key = new_hover
            self._hover_app_idx = new_app_idx
            self.update()

            # Show floating label bubble above hovered tile in normal mode
            if new_app_idx is not None and new_app_idx < len(self.tiles) and not self.preview_mode:
                t_hov = self.tiles[new_app_idx]
                r_tile = self._tile_rects[new_app_idx] if new_app_idx < len(self._tile_rects) else None
                if r_tile:
                    pt_top = self.mapToGlobal(QPoint(int(round(r_tile.center().x())), int(round(r_tile.top()))))
                    self.bubble.show_bubble(QPointF(float(pt_top.x()), float(pt_top.y())), t_hov.get("name", ""))
            else:
                if not self.preview_mode:
                    self.bubble.hide()

        self.setToolTip(tooltip_text)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.preview_mode:
            self.bubble.hide()
        if self._hover_key is not None or self._hover_app_idx is not None:
            self._hover_key = None
            self._hover_app_idx = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.press_tween.release()
            self._pressed_key = None

            # Handle finished tile drag reorder
            if self._drag_tile_active and self._drag_tile_idx is not None and self._drag_tile_cur_x is not None:
                n_pinned = sum(1 for t in self.tiles if t.get("pinned"))
                if n_pinned > 1 and self._drag_tile_idx < n_pinned and self._tile_centers:
                    pinned_centers = self._tile_centers[:n_pinned]
                    tgt_idx = pinned.drag_target_index(pinned_centers, self._drag_tile_cur_x)
                    tgt_idx = max(0, min(n_pinned - 1, tgt_idx))
                    if tgt_idx != self._drag_tile_idx:
                        self.pins = pinned.reorder(self.pins, self._drag_tile_idx, tgt_idx)
                        if not self.preview_mode:
                            self.settings["pinned"] = self.pins
                            save_settings(self.settings)
                        self.update_windows()
                self._drag_tile_active = False
                self._drag_tile_idx = None
                self._drag_tile_start_x = None
                self._drag_tile_cur_x = None
                self._drag_start_pos = None
                super().mouseReleaseEvent(event)
                return

            self._drag_tile_active = False
            self._drag_tile_idx = None
            self._drag_tile_start_x = None
            self._drag_tile_cur_x = None

            if self._is_dragging:
                self._is_dragging = False
                center_x = self.x() + self.width() / 2.0
                self.settings["pos"] = [center_x, self.y()]
                save_settings(self.settings)
            else:
                pos = event.position()
                for r, key, extra in self.hit_boxes:
                    if r.contains(pos):
                        self.handle_click(key, extra, r, pos)
                        break
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        pos = event.position()
        for r, key, _extra in self.hit_boxes:
            if key == "vol" and r.contains(pos):
                diff = 2.0 if event.angleDelta().y() > 0 else -2.0
                new_val = max(0.0, min(100.0, self._vol_level + diff))
                self._vol_level = new_val
                if not self.preview_mode:
                    media.set_volume(new_val)
                if self.vol_popover.isVisible():
                    self.vol_popover.update_volume(new_val, self._vol_muted, self._vol_device)
                self.update()
                break
        super().wheelEvent(event)

    def handle_click(self, key: str, extra: Any, rect: QRectF, pos: Optional[QPointF] = None) -> None:
        if key.startswith("app_") and extra:
            self.handle_tile_click(extra)
        elif key == "vol":
            if self.vol_popover.isVisible():
                self.vol_popover.hide()
            else:
                anchor_global = QRectF(
                    self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                    rect.size(),
                )
                self.vol_popover.show_for(anchor_global, self._vol_level, self._vol_muted, self._vol_device)
        elif key == "media":
            if self._media_hit_rects and not self.preview_mode and pos is not None:
                r_prev = self._media_hit_rects.get("prev")
                r_play = self._media_hit_rects.get("playpause")
                r_next = self._media_hit_rects.get("next")
                if r_prev and r_prev.contains(pos):
                    media.media_control("prev")
                elif r_play and r_play.contains(pos):
                    media.media_control("playpause")
                elif r_next and r_next.contains(pos):
                    media.media_control("next")
        elif key == "tray":
            # Kendi cam panelimiz; Windows'un köşedeki paneli yalnızca sağ tık menüsünden.
            if self.preview_mode:
                pass
            elif self.tray_popover.isVisible():
                self.tray_popover.hide()
            elif not self.tray_popover.recently_closed():
                anchor_global = QRectF(
                    self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                    rect.size(),
                )
                self.tray_popover.show_for(anchor_global)
        elif key == "clock":
            # Saat = takvim (kişisel 02). Aynı açılır panel altyapısı, tür "cal".
            if self.popover.is_open("cal"):
                self.popover.hide_animated()
            elif not self.popover.recently_closed("cal"):
                anchor_global = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())
                self.popover.show_for("cal", anchor_global, dict(self.store.get("cal") or {}))
        elif key in ("claude", "sys", "wx"):
            if self.popover.is_open(key):
                self.popover.hide_animated()
            elif self.popover.recently_closed(key):
                pass
            else:
                anchor_global = QRectF(
                    self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                    rect.size(),
                )
                data = dict(self.store.get(key) or {})
                if key == "sys":
                    data["top"] = popover_v2.top_processes(3)
                kwargs = {}
                if key == "wx":
                    kwargs["city"] = self.settings.get("city", "Aksaray")
                self.popover.show_for(key, anchor_global, data, **kwargs)

    def handle_tile_click(self, tile: dict) -> None:
        if tile.get("running"):
            hwnds = tile.get("hwnds", [])
            if not hwnds:
                return
            exe = tile.get("exe", "")
            if len(hwnds) == 1:
                if not self.preview_mode:
                    winapi.activate_or_minimize(hwnds[0])
            else:
                last_idx = self._app_cycle_indices.get(exe, -1)
                next_idx = (last_idx + 1) % len(hwnds)
                self._app_cycle_indices[exe] = next_idx
                if not self.preview_mode:
                    winapi.activate_or_minimize(hwnds[next_idx])
            self.update_windows()
        else:
            path = tile.get("exe") or tile.get("path") or ""
            if path and not self.preview_mode:
                pinned.launch(path)

    def get_tooltip_text(self, key: str, extra: Any) -> str:
        now_dt = dt.datetime.now(sources.LOCAL_TZ)
        if key == "claude":
            c = self.store.get("claude") or {}
            src = c.get("source", "Anthropic · Claude Code girişi")
            fa = c.get("fetched_at")
            t_str = (
                dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M")
                if fa
                else now_dt.strftime("%H:%M")
            )
            return f"Claude: {src} · {t_str}"
        elif key == "sys":
            s = self.store.get("sys") or {}
            src = s.get("source", "Bu bilgisayar (psutil)")
            return f"Sistem: {src} · Canlı"
        elif key == "vol":
            st = "Sessiz" if self._vol_muted else f"%{int(round(self._vol_level))}"
            return f"Ses Düzeyi: {st}"
        elif key == "media" and extra:
            t = extra.get("title", "")
            a = extra.get("artist", "")
            app = extra.get("app", "")
            return f"{app}: {t} - {a}" if (t or a) else "Medya"
        elif key == "tray":
            return "Gizli simgeleri göster"
        elif key == "wx":
            w = self.store.get("wx") or {}
            src = w.get("source", "open-meteo.com")
            fa = w.get("fetched_at")
            t_str = (
                dt.datetime.fromtimestamp(fa, tz=sources.LOCAL_TZ).strftime("%H:%M")
                if fa
                else now_dt.strftime("%H:%M")
            )
            return f"Hava: {src} · {t_str}"
        elif key == "clock":
            cal = self.store.get("cal") or {}
            nxt = cal.get("next")
            base = now_dt.strftime("%d.%m.%Y %H:%M")
            if cal.get("err"):
                return f"{base}\nTakvim: {cal['err']}"
            if nxt:
                return f"{base}\nSıradaki: {nxt['title']} · {sources.event_when(nxt)}\nTıkla: takvim"
            return f"{base}\nYakında etkinlik yok · Tıkla: takvim"
        elif key.startswith("app_") and extra:
            name = extra.get("name") or extra.get("title") or "Uygulama"
            cnt = extra.get("count", 1)
            is_p = extra.get("pinned", False)
            p_tag = " (Sabitlendi)" if is_p else ""
            return f"{name} ({cnt} pencere){p_tag}" if cnt > 1 else f"{name}{p_tag}"
        return ""

    def contextMenuEvent(self, event) -> None:
        for r, key, extra in self.hit_boxes:
            if key.startswith("app_") and extra and r.contains(event.position()):
                # App tile context menu: Sabitle / Sabitlemeyi kaldır
                tile_menu = QMenu(self)
                tile_menu.setStyleSheet("""
                    QMenu {
                        background-color: rgba(22, 26, 36, 245);
                        border: 1px solid rgba(255, 255, 255, 40);
                        border-radius: 8px;
                        padding: 4px;
                        color: #e8ecf1;
                        font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
                        font-size: 12px;
                    }
                    QMenu::item {
                        padding: 6px 18px;
                        border-radius: 4px;
                    }
                    QMenu::item:selected {
                        background-color: rgba(255, 255, 255, 25);
                    }
                """)
                is_pinned = bool(extra.get("pinned"))
                if is_pinned:
                    act_unpin = tile_menu.addAction("Sabitlemeyi kaldır")
                    def do_unpin():
                        self.pins = pinned.unpin(self.pins, extra.get("exe") or extra.get("key"))
                        if not self.preview_mode:
                            self.settings["pinned"] = self.pins
                            save_settings(self.settings)
                        self.update_windows()
                    act_unpin.triggered.connect(do_unpin)
                else:
                    act_pin = tile_menu.addAction("Sabitle")
                    def do_pin():
                        self.pins = pinned.pin(self.pins, extra)
                        if not self.preview_mode:
                            self.settings["pinned"] = self.pins
                            save_settings(self.settings)
                        self.update_windows()
                    act_pin.triggered.connect(do_pin)
                tile_menu.exec(event.globalPos())
                return

        # Main dock context menu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(22, 26, 36, 245);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
                padding: 4px;
                color: #e8ecf1;
                font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
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
        act_fx.triggered.connect(self.action_show_fx)

        # Alerts toggle (Requirement 5)
        act_alerts = QAction("Uyarılar", menu)
        act_alerts.setCheckable(True)
        act_alerts.setChecked(self.settings.get("alerts_enabled", True))
        def on_toggle_alerts(checked: bool):
            self.settings["alerts_enabled"] = checked
            if self.alert_engine is not None:
                self.alert_engine.enabled = checked
            save_settings(self.settings)
        act_alerts.triggered.connect(on_toggle_alerts)
        menu.addAction(act_alerts)

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
            self.submit_fetch(key)

    def action_show_fx(self) -> None:
        if self.popover.is_open("fx"):
            self.popover.hide_animated()
        elif self.popover.recently_closed("fx"):
            pass
        else:
            anchor_global = QRectF(self.x() + self.width() / 2.0 - 50.0, self.y(), 100.0, theme.CHIP_HEIGHT)
            data = self.store.get("fx") or {}
            self.popover.show_for("fx", anchor_global, data)

    def action_toggle_taskbar(self, checked: bool) -> None:
        self.settings["hide_taskbar"] = checked
        if checked:
            if self.settings.get("taskbar_original") is None:
                self.settings["taskbar_original"] = winapi.taskbar_autohide_get()
            save_settings(self.settings)
            winapi.taskbar_autohide_set(True)
        else:
            orig = self.settings.get("taskbar_original")
            if orig is not None:
                winapi.taskbar_autohide_set(bool(orig))
                self.settings["taskbar_original"] = None
            save_settings(self.settings)

    def action_reset_pos(self) -> None:
        self.settings["pos"] = None
        save_settings(self.settings)
        self.place_dock()


def render_preview(output_path_str: str) -> None:
    """Preview mode with zero side effects: no taskbar calls, no activation, no settings write, no lock file."""
    settings = load_settings()
    store = sources.Store()

    # Live data: prefer D:/Apps/serit/claude_cache.json if present to avoid rate limits
    claude_cache_file = APP_DIR / "claude_cache.json"
    claude_data = None
    if claude_cache_file.exists():
        try:
            raw_cache = claude_cache_file.read_text(encoding="utf-8")
            if raw_cache.strip():
                claude_data = json.loads(raw_cache)
        except Exception:
            claude_data = None
    if not claude_data:
        claude_data = sources.fetch_claude()
    store.update("claude", claude_data)

    fx_data = sources.fetch_fx()
    store.update("fx", fx_data)

    wx_data = sources.fetch_weather(lat=settings.get("lat", 38.37), lon=settings.get("lon", 34.03))
    store.update("wx", wx_data)

    sys_data = sources.fetch_system()
    store.update("sys", sys_data)

    raw_wins = winapi.list_windows()
    groups = winapi.group_by_app(raw_wins)
    pins = list(settings.get("pinned") or pinned.load_default_pins())
    tiles = pinned.merge_tiles(pins, groups)

    # Initialize dock in preview mode (zero side effects)
    dock = SeritDock(settings, preview_mode=True)
    dock.store = store
    dock.pins = pins
    dock.tiles = tiles

    # Read-only live volume and now-playing
    vol_data = media.get_volume()
    dock._vol_level = float(vol_data.get("level", 50.0))
    dock._vol_muted = bool(vol_data.get("muted", False))
    dock._vol_device = str(vol_data.get("device", ""))
    dock._now_playing_info = media.now_playing()

    dock.sync_anim_values()
    dock.compute_layout_and_resize(initial=True)

    dock_w = dock.width()
    dock_h = int(DOCK_HEIGHT)

    out_p = Path(output_path_str)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_p.suffix if out_p.suffix else ".png"

    # --- 1) Standard Dock Render (<png>) ---
    cw1 = dock_w + 80
    ch1 = dock_h + 60
    img1 = QImage(int(cw1 * 2), int(ch1 * 2), QImage.Format.Format_ARGB32_Premultiplied)
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
    img1.save(str(out_p))

    # --- 2) Hover Dock Render (<png>_hover.png) ---
    hover_p = out_p.parent / f"{out_p.stem}_hover{suffix}"
    dock._preview_hover_idx = 1 if len(dock.tiles) >= 2 else (0 if len(dock.tiles) == 1 else None)
    dock._hover_key = f"app_{dock._preview_hover_idx}" if dock._preview_hover_idx is not None else None

    cw2 = dock_w + 80
    ch2 = dock_h + 80
    dock_x2 = 40
    dock_y2 = 45

    img2 = QImage(int(cw2 * 2), int(ch2 * 2), QImage.Format.Format_ARGB32_Premultiplied)
    img2.setDevicePixelRatio(2.0)
    img2.fill(0)

    p2 = QPainter(img2)
    p2.setRenderHint(QPainter.Antialiasing)
    p2.setRenderHint(QPainter.SmoothPixmapTransform)
    draw_wallpaper_gradient(p2, cw2, ch2)
    dock.render(p2, QPoint(dock_x2, dock_y2))

    # Draw label bubble above the hovered 2nd tile
    if dock._preview_hover_idx is not None and dock._preview_hover_idx < len(dock.tiles):
        t_hov = dock.tiles[dock._preview_hover_idx]
        t_rect = dock._tile_rects[dock._preview_hover_idx] if dock._preview_hover_idx < len(dock._tile_rects) else None
        if t_rect:
            anchor_preview = QPointF(dock_x2 + t_rect.center().x(), dock_y2 + t_rect.top() - 3.0)
            pinned.draw_label_bubble(p2, anchor_preview, t_hov.get("name", ""))

    p2.end()
    img2.save(str(hover_p))

    dock._preview_hover_idx = None
    dock._hover_key = None

    # --- 3) Popover Dock Render (<png>_pop.png) ---
    pop_p = out_p.parent / f"{out_p.stem}_pop{suffix}"
    dock.popover._kind = "claude"
    dock.popover._content = popover_v2.build_content("claude", claude_data)
    pop_h = dock.popover.compute_height(dock.popover._content)
    dock.popover.resize(dock.popover.WIDTH, pop_h)
    pop_img = dock.popover.render_to_image(dpr=2.0)

    cw3 = max(dock_w + 80, 560)
    ch3 = pop_h + 16 + dock_h + 50
    img3 = QImage(int(cw3 * 2), int(ch3 * 2), QImage.Format.Format_ARGB32_Premultiplied)
    img3.setDevicePixelRatio(2.0)
    img3.fill(0)

    p3 = QPainter(img3)
    p3.setRenderHint(QPainter.Antialiasing)
    p3.setRenderHint(QPainter.SmoothPixmapTransform)
    draw_wallpaper_gradient(p3, cw3, ch3)

    dock_x3 = int((cw3 - dock_w) / 2.0)
    dock_y3 = int(ch3 - dock_h - 20)
    dock.render(p3, QPoint(dock_x3, dock_y3))

    pop_x3 = dock_x3 + int(theme.DOCK_PAD_X)
    pop_y3 = dock_y3 - pop_h - 10
    p3.drawImage(QPoint(pop_x3, pop_y3), pop_img)
    p3.end()
    img3.save(str(pop_p))

    # --- 4) Volume Panel Render (<png>_vol.png) ---
    vol_p = out_p.parent / f"{out_p.stem}_vol{suffix}"
    vol_card_w = 280.0
    vol_card_h = 126.0

    cw4 = max(dock_w + 80, 560)
    ch4 = int(vol_card_h) + 16 + dock_h + 50
    img4 = QImage(int(cw4 * 2), int(ch4 * 2), QImage.Format.Format_ARGB32_Premultiplied)
    img4.setDevicePixelRatio(2.0)
    img4.fill(0)

    p4 = QPainter(img4)
    p4.setRenderHint(QPainter.Antialiasing)
    p4.setRenderHint(QPainter.SmoothPixmapTransform)
    draw_wallpaper_gradient(p4, cw4, ch4)

    dock_x4 = int((cw4 - dock_w) / 2.0)
    dock_y4 = int(ch4 - dock_h - 20)
    dock.render(p4, QPoint(dock_x4, dock_y4))

    vol_box = next((r for r, k, _ in dock.hit_boxes if k == "vol"), None)
    if vol_box:
        vol_cx = dock_x4 + vol_box.center().x()
    else:
        vol_cx = dock_x4 + dock_w / 2.0
    vol_x4 = int(round(vol_cx - vol_card_w / 2.0))
    vol_y4 = int(round(dock_y4 - vol_card_h - 10.0))

    media.draw_volume_slider_panel(
        p4,
        QRectF(vol_x4, vol_y4, vol_card_w, vol_card_h),
        level=dock._vol_level,
        muted=dock._vol_muted,
        device=dock._vol_device,
    )
    p4.end()
    img4.save(str(vol_p))

    s_val_str = f"%{int(round(claude_data.get('session')))}" if claude_data.get('session') is not None else "--"
    w_val_str = f"%{int(round(claude_data.get('week')))}" if claude_data.get('week') is not None else "--"
    cpu_val_str = f"%{int(round(sys_data.get('cpu')))}" if sys_data.get('cpu') is not None else "--"
    ram_val_str = f"%{int(round(sys_data.get('ram')))}" if sys_data.get('ram') is not None else "--"
    disk_val_str = f"%{int(round(sys_data.get('disk_c')))}" if sys_data.get('disk_c') is not None else "--"
    vol_val_str = f"%{int(round(dock._vol_level))}"

    print(f"PREVIEW_SAVED: {out_p} ({cw1}x{ch1} @2x)")
    print(f"PREVIEW_HOVER_SAVED: {hover_p} ({cw2}x{ch2} @2x)")
    print(f"PREVIEW_POP_SAVED: {pop_p} ({cw3}x{ch3} @2x)")
    print(f"PREVIEW_VOL_SAVED: {vol_p} ({cw4}x{ch4} @2x)")
    print(
        f"LIVE_CLAUDE: session={s_val_str}, week={w_val_str}, plan={claude_data.get('plan')}"
    )
    print(
        f"LIVE_SYS: cpu={cpu_val_str}, ram={ram_val_str}, disk_c={disk_val_str}"
    )
    print(f"LIVE_WX: temp={wx_data.get('temp')}°, desc={wx_data.get('desc')}")
    print(f"LIVE_VOLUME: level={vol_val_str}, muted={dock._vol_muted}, device={dock._vol_device}")
    np_title = dock._now_playing_info.get('title', '') if dock._now_playing_info else 'Yok'
    np_app = dock._now_playing_info.get('app', '') if dock._now_playing_info else ''
    print(f"LIVE_MEDIA: active={bool(dock._now_playing_info)}, app={np_app}, title={np_title}")
    n_pins = sum(1 for t in dock.tiles if t.get('pinned'))
    n_run = sum(1 for t in dock.tiles if t.get('running'))
    print(f"LIVE_TILES_COUNT: {len(dock.tiles)} (pinned={n_pins}, running={n_run})")


def main() -> None:
    if "--restore-taskbar" in sys.argv:
        settings = load_settings()
        orig = settings.get("taskbar_original")
        target = bool(orig) if orig is not None else False
        try:
            winapi.taskbar_autohide_set(target)
            print(f"TASKBAR_RESTORED: {target}")
        except Exception as exc:
            print(f"TASKBAR_RESTORE_FAIL: {exc}")
        settings["taskbar_original"] = None
        settings["hide_taskbar"] = False
        save_settings(settings)
        return

    if "--preview" in sys.argv:
        idx = sys.argv.index("--preview")
        out_file = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else str(APP_DIR / "serit_preview.png")
        app = QApplication(sys.argv)
        render_preview(out_file)
        return

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
