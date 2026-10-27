"""Şerit v5 - Modern acrylic glass floating dock for Windows 11.

Integrates theme.py (design tokens & primitives), anim.py (zero-idle driver & tweens),
pinned.py (pinned apps & dark glass tiles), popover_v2.py (sectioned acrylic flyouts),
alerts.py (proactive notification toasts), tray.py (hidden icons overflow),
and media.py (volume slider popover, media keys & now-playing detection).
"""

from __future__ import annotations

import atexit
import ctypes
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
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
    QActionGroup,
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
import dock_cards
import media
import pinned
import popover_v2
import sources
import theme
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
    "reserve_space": True,
    # "band" = tam genişlik koyu şerit (Lumabar "full width"), "pill" = ortada kapsül
    "style": "band",
    "cards": {
        "sys": False,
        "fx": False,
        "cal": True,
    },
}

# Dimension Tokens for v5 / dock v3
DOCK_HEIGHT: float = 64.0
DOCK_RADIUS: float = 20.0
CARD_HEIGHT: float = 52.0
CARD_RADIUS: float = 13.0
CARD_Y: float = 6.0
GAP_MODULE: float = 6.0
CLAUDE_CARD_WIDTH: float = 182.0
MEDIA_CARD_WIDTH: float = 314.0
SYS_CARD_WIDTH: float = 166.0
MARKET_CARD_WIDTH: float = 160.0
CLOCK_BLOCK_WIDTH: float = 70.0
TRAY_COLUMN_WIDTH: float = 32.0

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
    bak_file = SETTINGS_FILE.parent / "settings.json.bak"
    loaded = False
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
                loaded = True
        except Exception as exc:
            sources.log_err("load_settings_corrupt", exc)
    if not loaded and bak_file.exists():
        try:
            data = json.loads(bak_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
                sources.log_err(
                    "load_settings_bak_used",
                    RuntimeError("settings.json corrupt, recovered from settings.json.bak"),
                )
        except Exception as exc:
            sources.log_err("load_settings_bak_corrupt", exc)
    return cfg


def save_settings(cfg: dict) -> None:
    try:
        tmp_file = SETTINGS_FILE.parent / "settings.json.tmp"
        bak_file = SETTINGS_FILE.parent / "settings.json.bak"
        content = json.dumps(cfg, ensure_ascii=False, indent=2)
        tmp_file.write_text(content, encoding="utf-8")
        if SETTINGS_FILE.exists():
            try:
                shutil.copy2(SETTINGS_FILE, bak_file)
            except Exception as exc:
                sources.log_err("save_settings_bak", exc)
        os.replace(tmp_file, SETTINGS_FILE)
    except Exception as exc:
        sources.log_err("save_settings", exc)


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
        self._icon_cache: Dict[str, QPixmap] = {}
        self._hits: list = []
        self._hover = -1
        self._closed_at = 0.0

    def recently_closed(self) -> bool:
        return (time.time() - self._closed_at) < 0.25

    def set_items(self, items: list) -> None:
        self._items = list(items or [])
        if self.isVisible():
            self._sync_icons()
            self.update()

    def _sync_icons(self) -> None:
        uncached = []
        for it in self._items:
            key = f"{it.get('name', '')}::{it.get('exe', '')}"
            if key not in self._icon_cache or self._icon_cache[key].isNull():
                uncached.append(it)
        if uncached:
            try:
                new_icons = trayicons.get_tray_icons(uncached)
                for it in uncached:
                    name = it.get("name", "")
                    key = f"{name}::{it.get('exe', '')}"
                    pm = new_icons.get(name)
                    if pm is not None and not pm.isNull():
                        self._icon_cache[key] = pm
            except Exception as exc:
                sources.log_err("tray_sync_icons", exc)
        self._icons = {
            it.get("name", ""): self._icon_cache.get(f"{it.get('name', '')}::{it.get('exe', '')}", QPixmap())
            for it in self._items
        }

    def show_for(self, anchor_global: QRectF) -> None:
        self._sync_icons()
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


class VolumeCoalescer(QObject):
    """Coalesces volume change requests to avoid flooding worker/COM threads.

    Applies at most once every 40ms, and guarantees final value is applied on force=True.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._target_level: Optional[float] = None
        self._last_apply_time: float = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def request(self, level: float, force: bool = False) -> None:
        self._target_level = float(level)
        now = time.monotonic()
        elapsed = now - self._last_apply_time
        if force or elapsed >= 0.040:
            self._timer.stop()
            self._flush()
        elif not self._timer.isActive():
            rem_ms = max(5, int((0.040 - elapsed) * 1000))
            self._timer.start(rem_ms)

    def _flush(self) -> None:
        if self._target_level is None:
            return
        lvl = self._target_level

        def _apply() -> None:
            media.set_volume(lvl)

        submitted = sources.submit("vol_set", _apply)
        if submitted:
            self._last_apply_time = time.monotonic()
        else:
            self._timer.start(15)


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
        self._coalescer = VolumeCoalescer(self)

        self._level: float = 50.0
        self._muted: bool = False
        self._device: str = ""
        self._is_dragging_slider: bool = False
        self._hit_rects: Dict[str, QRectF] = {}
        self.resize(self.WIDTH, self.HEIGHT)

    def _request_volume(self, level: float, force: bool = False) -> None:
        self._level = float(level)
        if self.on_volume_change:
            self.on_volume_change(self._level, self._muted)
        self.update()
        if self.parent_dock and getattr(self.parent_dock, "preview_mode", False):
            return
        self._coalescer.request(self._level, force=force)

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
                    sources.submit("vol_mute", media.toggle_mute)
                self._muted = not self._muted
                if self.on_volume_change:
                    self.on_volume_change(self._level, self._muted)
                self.update()
                return

            r_slider = self._hit_rects.get("slider")
            if r_slider and r_slider.adjusted(-8.0, -8.0, 8.0, 8.0).contains(pos):
                self._is_dragging_slider = True
                pct = max(0.0, min(100.0, (pos.x() - r_slider.left()) / r_slider.width() * 100.0))
                self._request_volume(pct, force=False)
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
                    self._request_volume(val, force=True)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging_slider:
            r_slider = self._hit_rects.get("slider")
            if r_slider:
                pct = max(0.0, min(100.0, (event.position().x() - r_slider.left()) / r_slider.width() * 100.0))
                self._request_volume(pct, force=False)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._is_dragging_slider:
                self._is_dragging_slider = False
                self._request_volume(self._level, force=True)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        diff = 2.0 if event.angleDelta().y() > 0 else -2.0
        self._level = max(0.0, min(100.0, self._level + diff))
        self._request_volume(self._level, force=False)
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
        self._vol_coalescer = VolumeCoalescer(self)
        self._cleaned_up: bool = False

        # Pre-warm icon cache for pinned items
        for p in self.pins:
            exe = p.get("exe") or p.get("path") or ""
            if exe and exe not in self._icon_cache:
                self._icon_cache[exe] = winapi.app_icon(exe, 64)

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

        # Calendar Panel contract
        self.cal_panel = None
        try:
            import calendar_panel
            self.cal_panel = calendar_panel.CalendarPanel()
            if hasattr(self.cal_panel, "refresh_requested"):
                self.cal_panel.refresh_requested.connect(self._on_cal_refresh_requested)
        except (ImportError, Exception) as exc:
            sources.log_err("cal_panel_init", exc)
            self.cal_panel = None

        # AppBar registered state
        self._appbar_registered: bool = False
        self._appbar_bottom_logical: Optional[int] = None
        # Bant modunda kart grubunun (animasyonlu) genişliği; grup bu genişlikle ortalanır
        self._content_w: float = 0.0

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

    def _on_cal_refresh_requested(self) -> None:
        self.submit_fetch("cal")
        self.submit_fetch("calmonth")

    def _register_appbar(self) -> bool:
        if self.preview_mode or not bool(self.settings.get("reserve_space", True)):
            return False
        hwnd = int(self.winId())
        if not hwnd:
            return False
        try:
            shell32 = ctypes.windll.shell32
            # ABM_NEW = 0, ABE_BOTTOM = 3
            # APPBARDATA: cbSize, hWnd, uCallbackMessage, uEdge, rc (RECT), lParam
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            _APPBARDATA = winapi.APPBARDATA  # winapi argtypes ile aynı tip olmalı
            abd = _APPBARDATA()
            abd.cbSize = ctypes.sizeof(_APPBARDATA)
            abd.hWnd = hwnd
            abd.uCallbackMessage = 0
            abd.uEdge = 3  # ABE_BOTTOM

            if not self._appbar_registered:
                # ABM_NEW = 0
                res = shell32.SHAppBarMessage(0, ctypes.byref(abd))
                if not res:
                    return False
                self._appbar_registered = True

            # Query & set pos. SHAppBarMessage FİZİKSEL piksel ister; Qt mantıksal piksel verir
            # (%125 ölçekte 864 mantıksal = 1080 fiziksel). Monitör dikdörtgenini doğrudan Windows'tan al.
            class _MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                            ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]
            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            hmon = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
            if not hmon or not user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi)):
                return False
            screen = self.screen() or QGuiApplication.primaryScreen()
            dpr = float(screen.devicePixelRatio()) if screen else 1.0
            # Bant: tam 64 (şeridin kendisi). Kapsül: 64 + alt boşluk 12 + 4 = 80 (mantıksal)
            logical_h = DOCK_HEIGHT if self._is_band() else (DOCK_HEIGHT + 12 + 4)
            appbar_h = int(round(logical_h * dpr))

            abd.rc.left = mi.rcMonitor.left
            abd.rc.right = mi.rcMonitor.right
            abd.rc.bottom = mi.rcMonitor.bottom
            abd.rc.top = mi.rcMonitor.bottom - appbar_h

            # ABM_QUERYPOS = 2
            shell32.SHAppBarMessage(2, ctypes.byref(abd))
            abd.rc.top = abd.rc.bottom - appbar_h
            # ABM_SETPOS = 3
            shell32.SHAppBarMessage(3, ctypes.byref(abd))
            # Barın oturacağı alt kenar (mantıksal, ekran koordinatı): place_dock bunu kullanır,
            # yoksa ayrılan alan kullanılabilir alanı küçülttüğü için bar yukarı kayardı.
            if screen is not None:
                sg = screen.geometry()
                self._appbar_bottom_logical = sg.top() + int(round((abd.rc.bottom - mi.rcMonitor.top) / dpr)) - 1
            return True
        except Exception as exc:
            sources.log_err("register_appbar", exc)
            return False

    def _unregister_appbar(self) -> None:
        if not self._appbar_registered or self.preview_mode:
            return
        hwnd = int(self.winId() or 0)
        if not hwnd:
            return
        try:
            shell32 = ctypes.windll.shell32
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            _APPBARDATA = winapi.APPBARDATA  # winapi argtypes ile aynı tip olmalı
            abd = _APPBARDATA()
            abd.cbSize = ctypes.sizeof(_APPBARDATA)
            abd.hWnd = hwnd
            # ABM_REMOVE = 1
            shell32.SHAppBarMessage(1, ctypes.byref(abd))
            self._appbar_registered = False
        except Exception as exc:
            sources.log_err("unregister_appbar", exc)

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

        self._register_appbar()

        wh = self.windowHandle()
        if wh is not None:
            wh.screenChanged.connect(self._on_screen_changed)

        # Görev çubuğu gizlenince ekranın kullanılabilir alanı birkaç yüz ms sonra büyür;
        # bar o anda yerleşirse dipte değil, eski görev çubuğunun üstünde kalıyordu.
        scr = self.screen() or QGuiApplication.primaryScreen()
        if scr is not None:
            scr.availableGeometryChanged.connect(lambda _g: (self.place_dock(), self._register_appbar()))
        for ms in (400, 1200, 3000):
            QTimer.singleShot(ms, self.place_dock)

    def _on_screen_changed(self, screen) -> None:
        dpr = screen.devicePixelRatio() if screen else 1.25
        winapi.set_round_region(int(self.winId()), self.width(), int(DOCK_HEIGHT), int(DOCK_RADIUS), dpr)
        self.place_dock()
        self._register_appbar()
        self.update()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
            self.place_dock()
        super().changeEvent(event)

    def cleanup(self) -> None:
        """K3 Safe taskbar restoration on quit."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self._unregister_appbar()
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

        # Calmonth fetch timer (every 60 s + at start)
        self.calmonth_timer = QTimer(self)
        self.calmonth_timer.setInterval(60000)
        self.calmonth_timer.timeout.connect(lambda: self.submit_fetch("calmonth"))
        self.calmonth_timer.start()
        self.submit_fetch("calmonth")

        # Open windows polling timer (1.5 s)
        self.win_timer = QTimer(self)
        self.win_timer.setInterval(1500)
        self.win_timer.timeout.connect(self.update_windows)
        self.win_timer.start()

        # Media & Volume polling timer (3 s)
        self.media_timer = QTimer(self)
        self.media_timer.setInterval(3000)
        self.media_timer.timeout.connect(lambda: self.submit_fetch("media"))
        self.media_timer.start()
        self.submit_fetch("media")

        # Top processes polling timer (60 s)
        self.top_timer = QTimer(self)
        self.top_timer.setInterval(60000)
        self.top_timer.timeout.connect(lambda: self.submit_fetch("top"))
        self.top_timer.start()
        self.submit_fetch("top")

        # Hidden tray items polling timer (60 s)
        self.tray_timer = QTimer(self)
        self.tray_timer.setInterval(60000)
        self.tray_timer.timeout.connect(lambda: self.submit_fetch("tray"))
        self.tray_timer.start()
        self.submit_fetch("tray")

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
        """Poll media in background worker."""
        self.submit_fetch("media")

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
            "calmonth": getattr(sources, "fetch_month_calendar", None),
            "media": sources.fetch_media,
            "top": lambda: popover_v2.top_processes(3),
            "tray": trayicons.list_tray_items,
        }
        fn = fetchers.get(key)
        if fn:
            sources.submit(key, fn, lambda k, res: self.dispatcher.data_ready.emit(k, res))

    def on_data_ready(self, key: str, res: Any) -> None:
        if isinstance(res, dict) and res.get("err"):
            sources.log_err(key, RuntimeError(str(res.get("err"))))
        self.store.update(key, res)

        if key == "media":
            if not isinstance(res, dict):
                return
            changed = False
            v_data = res.get("vol") or {}
            lvl = float(v_data.get("level", self._vol_level))
            muted = bool(v_data.get("muted", self._vol_muted))
            dev = str(v_data.get("device", self._vol_device))
            if lvl != self._vol_level or muted != self._vol_muted or dev != self._vol_device:
                self._vol_level = lvl
                self._vol_muted = muted
                self._vol_device = dev
                if self.vol_popover.isVisible():
                    self.vol_popover.update_volume(lvl, muted, dev)
                changed = True

            np = res.get("np")
            if np != self._now_playing_info:
                self._now_playing_info = np
                changed = True

            if changed:
                self.compute_layout_and_resize()
                self.update()
            return

        if key == "tray":
            items = res if isinstance(res, list) else (res.get("items") or res.get("data") or [])
            self.tray_popover.set_items(items)
            return

        # Tween retargeting: only when value changed by >= 1 point (Requirement 6)
        if key == "claude" and isinstance(res, dict):
            s = safe_float(res.get("session"), None)
            w = safe_float(res.get("week"), None)
            has_err = ("err" in res) or (s is None and w is None)
            self.anim_claude_op.retarget(0.45 if has_err else 1.0)
            if s is not None and abs(s - self.anim_claude_s.target_val) >= 1.0:
                self.anim_claude_s.retarget(s)
            if w is not None and abs(w - self.anim_claude_w.target_val) >= 1.0:
                self.anim_claude_w.retarget(w)
        elif key == "sys" and isinstance(res, dict):
            cpu = safe_float(res.get("cpu"), None)
            ram = safe_float(res.get("ram"), None)
            has_err = ("err" in res) or (cpu is None and ram is None)
            self.anim_sys_op.retarget(0.45 if has_err else 1.0)
            if cpu is not None and abs(cpu - self.anim_cpu.target_val) >= 1.0:
                self.anim_cpu.retarget(cpu)
            if ram is not None and abs(ram - self.anim_ram.target_val) >= 1.0:
                self.anim_ram.retarget(ram)
        elif key == "wx" and isinstance(res, dict):
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

        for t in tiles:
            exe = t.get("exe") or t.get("path") or ""
            if exe and exe not in self._icon_cache:
                self._icon_cache[exe] = winapi.app_icon(exe, 64)

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
        return self._icon_cache.get(exe, QPixmap())

    def place_dock(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        geom = QRect(screen.availableGeometry()) if screen else QRect(0, 0, 1536, 864)
        # Bar kendine alan ayırdıysa (AppBar) kullanılabilir alan barın ÜSTÜNDE biter;
        # bar o ayrılan şeridin içinde, ekranın dibinde durmalı.
        ab_bottom = getattr(self, "_appbar_bottom_logical", None)
        if getattr(self, "_appbar_registered", False) and ab_bottom is not None:
            geom.setBottom(int(ab_bottom))
        if self._is_band():
            # Tam genişlik şerit: ekranın soluna, sağına ve dibine yapışık
            sg = screen.geometry() if screen else QRect(0, 0, 1536, 864)
            if self.width() != sg.width() or self.height() != int(DOCK_HEIGHT):
                self.resize(sg.width(), int(DOCK_HEIGHT))
            self.move(sg.left(), int(geom.bottom() - DOCK_HEIGHT + 1))
            return

        pos = self.settings.get("pos")

        if pos and len(pos) == 2:
            cx, y = pos
            x = int(round(cx - self.width() / 2.0))
            # Kayıtlı yükseklik, ekranın dibine 60 px'ten yakınsa "dipte" sayılır ve dibe yapışır
            # (görev çubuğu açıkken kaydedilen eski konum barı havada bırakmasın).
            bottom_y = int(geom.bottom() - DOCK_HEIGHT - 12)
            target_y = bottom_y if abs(int(y) - bottom_y) <= 60 or int(y) > bottom_y else int(y)
        else:
            x = int(round(geom.center().x() - self.width() / 2.0))
            target_y = int(geom.bottom() - DOCK_HEIGHT - 12)

        clamped_x = max(geom.left(), min(x, geom.right() - self.width()))
        clamped_y = max(geom.top(), min(target_y, geom.bottom() - int(DOCK_HEIGHT)))
        self.move(clamped_x, clamped_y)

    def _is_band(self) -> bool:
        return str(self.settings.get("style", "band")) != "pill"

    def _on_width_tween_update(self, val: float) -> None:
        if self._is_band():
            self._content_w = float(val)
            self.update()
            return
        curr_w = int(round(val))
        if curr_w != self.width() and self.isVisible():
            cx = self.x() + self.width() / 2.0
            self.resize(curr_w, int(DOCK_HEIGHT))
            new_x = int(round(cx - curr_w / 2.0))
            self.move(new_x, self.y())

    def compute_layout_and_resize(self, initial: bool = False) -> None:
        """Computes pixel-precise layout for dock v3 cards and animates dock width."""
        cards_cfg = dict(self.settings.get("cards") or {})
        show_cal = cards_cfg.get("cal", True)
        show_sys = cards_cfg.get("sys", False)
        show_fx = cards_cfg.get("fx", False)

        # Items list
        items: List[float] = []

        # 1. Claude Card: 182px
        items.append(CLAUDE_CARD_WIDTH)

        # 2. Apps Group: N tiles * 44 + (N-1) * 4
        n_tiles = len(self.tiles)
        w_apps = (n_tiles * pinned.TILE_WIDTH + max(0, n_tiles - 1) * pinned.GAP) if n_tiles > 0 else 0.0
        if w_apps > 0:
            items.append(w_apps)

        # 3. Media Card: 314px (only if now_playing has title)
        has_media = bool(self._now_playing_info and self._now_playing_info.get("title"))
        if has_media:
            items.append(MEDIA_CARD_WIDTH)

        # 4. System Card (optional): 166px
        if show_sys:
            items.append(SYS_CARD_WIDTH)

        # 5. Market Card (optional): 160px
        if show_fx:
            items.append(MARKET_CARD_WIDTH)

        # 6. Calendar Card: dynamic measured width
        if show_cal:
            cal_data = self.store.get("cal") or {}
            w_cal = dock_cards.measure_calendar_card_width(cal_data)
            items.append(w_cal)

        # 7. Clock Block: 70px
        items.append(CLOCK_BLOCK_WIDTH)

        # 8. Tray Column: 32px
        items.append(TRAY_COLUMN_WIDTH)

        # Symmetrical padding: 6px on left and right, 6px between items
        n_items = len(items)
        inner_gaps = max(0, n_items - 1) * GAP_MODULE
        total_w = int(math.ceil(6.0 * 2.0 + sum(items) + inner_gaps))

        if self._is_band():
            scr = self.screen() or QGuiApplication.primaryScreen()
            sw = scr.geometry().width() if scr else 1536
            if self.width() != sw or self.height() != int(DOCK_HEIGHT):
                self.resize(sw, int(DOCK_HEIGHT))
            if initial or self.preview_mode or not self.isVisible() or self._content_w <= 0:
                self._content_w = float(total_w)
                self.dock_width_tween.value = float(total_w)
                self.dock_width_tween.target_val = float(total_w)
            elif total_w != int(round(self.dock_width_tween.target_val)):
                self.dock_width_tween.retarget(total_w)
            return

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

        # 1. Physical Glass Capsule with Specular Rim & Grain (cached QPixmap)
        if self._is_band():
            # Tam genişlik koyu şerit (köşesiz) + üstte ince ayırıcı çizgi
            p.fillRect(QRectF(0, 0, self.width(), DOCK_HEIGHT), QColor(13, 15, 19))
            p.fillRect(QRectF(0, 0, self.width(), 1.0), QColor(255, 255, 255, 18))
            cw = self._content_w if self._content_w > 0 else float(self.width())
            x0 = float(max(0, int(round((self.width() - cw) / 2.0))))
        else:
            r_dock = QRectF(0.5, 0.5, self.width() - 1.0, DOCK_HEIGHT - 1.0)
            theme.draw_glass_capsule(p, r_dock, radius=DOCK_RADIUS)
            x0 = 0.0

        self.hit_boxes.clear()
        x = x0 + 6.0  # inner padding 6px
        card_y = CARD_Y  # 6px from top
        card_h = CARD_HEIGHT  # 52px

        cards_cfg = dict(self.settings.get("cards") or {})
        show_cal = cards_cfg.get("cal", True)
        show_sys = cards_cfg.get("sys", False)
        show_fx = cards_cfg.get("fx", False)

        # 1. Claude Card (182x52)
        r_claude = QRectF(x, card_y, CLAUDE_CARD_WIDTH, card_h)
        self.hit_boxes.append((r_claude, "claude", None))
        c_hover = self._hover_key == "claude"
        c_press = self.press_tween.scale if (self._pressed_key == "claude") else 1.0
        c_entry = self.store.get("claude") or {}
        dock_cards.draw_claude_card(p, r_claude, c_entry, hover=c_hover, press_scale=c_press)
        x += CLAUDE_CARD_WIDTH + GAP_MODULE

        # 2. Apps Group (44x46 cells, 4px gap, vertically centered at 52px slot)
        n_tiles = len(self.tiles)
        hover_idx = self._preview_hover_idx if self._preview_hover_idx is not None else self._hover_app_idx
        scales_lifts = anim.HoverMagnifier.compute_for_index(n_tiles, hover_idx)

        self._tile_centers = []
        self._tile_rects = []
        tile_y = card_y + (card_h - pinned.TILE_HEIGHT) / 2.0  # 6 + (52-46)/2 = 9.0

        for i, t in enumerate(self.tiles):
            tile_x = x + i * (pinned.TILE_WIDTH + pinned.GAP)
            r_slot = QRectF(tile_x, tile_y, pinned.TILE_WIDTH, pinned.TILE_HEIGHT)
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

            pinned.draw_tile(
                p=p,
                rect=r_draw,
                tile=t,
                pixmap=pix,
                hover_t=hover_t,
                press_scale=press_scale * scale,
                dot_count=t.get("count"),
                indicator_y=r_slot.bottom() - 4.0,
            )

        if n_tiles > 0:
            w_apps = n_tiles * pinned.TILE_WIDTH + (n_tiles - 1) * pinned.GAP
            x += w_apps + GAP_MODULE

        # 3. Media Card (314x52, only if now_playing has title)
        has_media = bool(self._now_playing_info and self._now_playing_info.get("title"))
        if has_media:
            r_media = QRectF(x, card_y, MEDIA_CARD_WIDTH, card_h)
            self.hit_boxes.append((r_media, "media", self._now_playing_info))
            m_hover = self._hover_key == "media"
            m_press = self.press_tween.scale if (self._pressed_key == "media") else 1.0
            m_ctrl_hover = getattr(self, "_hover_media_ctrl", None)
            self._media_hit_rects = dock_cards.draw_media_card(
                p, r_media, self._now_playing_info, hover=m_hover, press_scale=m_press, hovered_control=m_ctrl_hover
            )
            x += MEDIA_CARD_WIDTH + GAP_MODULE

        # 4. System Card (optional, 166x52)
        if show_sys:
            r_sys = QRectF(x, card_y, SYS_CARD_WIDTH, card_h)
            self.hit_boxes.append((r_sys, "sys", None))
            s_hover = self._hover_key == "sys"
            s_press = self.press_tween.scale if (self._pressed_key == "sys") else 1.0
            sys_entry = self.store.get("sys") or {}
            dock_cards.draw_sys_card(p, r_sys, sys_entry, hover=s_hover, press_scale=s_press)
            x += SYS_CARD_WIDTH + GAP_MODULE

        # 5. Market Card (optional, 160x52)
        if show_fx:
            r_fx = QRectF(x, card_y, MARKET_CARD_WIDTH, card_h)
            self.hit_boxes.append((r_fx, "fx", None))
            f_hover = self._hover_key == "fx"
            f_press = self.press_tween.scale if (self._pressed_key == "fx") else 1.0
            fx_entry = self.store.get("fx") or {}
            dock_cards.draw_market_card(p, r_fx, fx_entry, hover=f_hover, press_scale=f_press)
            x += MARKET_CARD_WIDTH + GAP_MODULE

        # 6. Calendar Card (dynamic width)
        if show_cal:
            cal_data = self.store.get("cal") or {}
            w_cal = dock_cards.measure_calendar_card_width(cal_data)
            r_cal = QRectF(x, card_y, w_cal, card_h)
            self.hit_boxes.append((r_cal, "cal", None))
            cal_hover = self._hover_key == "cal"
            cal_press = self.press_tween.scale if (self._pressed_key == "cal") else 1.0
            dock_cards.draw_calendar_card(p, r_cal, cal_data, hover=cal_hover, press_scale=cal_press)
            x += w_cal + GAP_MODULE

        # 7. Clock Block (70x52)
        r_clock = QRectF(x, card_y, CLOCK_BLOCK_WIDTH, card_h)
        self._clock_rect = r_clock
        self.hit_boxes.append((r_clock, "clock", None))
        clk_hover = self._hover_key == "clock"
        clk_press = self.press_tween.scale if (self._pressed_key == "clock") else 1.0

        wx_entry = self.store.get("wx") or {}
        temp_val = safe_float(wx_entry.get("temp"), None)
        temp_str = f"{int(round(temp_val))}°" if temp_val is not None else "12°"

        r_temp = dock_cards.draw_clock_block(p, r_clock, temp_str=temp_str, hover=clk_hover, press_scale=clk_press)
        # Add temperature circle hit box with higher priority
        self.hit_boxes.append((r_temp, "wx", None))
        x += CLOCK_BLOCK_WIDTH + GAP_MODULE

        # 8. Tray Column (32px width)
        r_tray_col = QRectF(x, card_y, TRAY_COLUMN_WIDTH, card_h)
        h_btn = None
        if self._hover_key == "vol":
            h_btn = "spk"
        elif self._hover_key == "tray":
            h_btn = "chv"
        r_spk, r_chv = dock_cards.draw_tray_column(p, r_tray_col, vol_muted=self._vol_muted, hovered_btn=h_btn)
        self.hit_boxes.append((r_spk, "vol", None))
        self.hit_boxes.append((r_chv, "tray", None))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._window_start_pos = self.pos()
            self._is_dragging = False

            pos = event.position()
            for r, key, extra in reversed(self.hit_boxes):
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

            # Check dock window dragging (bant ekrana sabit, sürüklenmez)
            if self._drag_start_pos and not self._is_band():
                delta = event.globalPosition().toPoint() - self._drag_start_pos
                if not self._is_dragging and delta.manhattanLength() > 5:
                    self._is_dragging = True
                if self._is_dragging and self._window_start_pos:
                    self.move(self._window_start_pos + delta)
                    return

        new_hover = None
        new_app_idx = None
        new_media_ctrl = None
        tooltip_text = ""
        for r, key, extra in reversed(self.hit_boxes):
            if r.contains(pos):
                new_hover = key
                if key.startswith("app_"):
                    try:
                        new_app_idx = int(key.split("_")[1])
                    except (IndexError, ValueError):
                        new_app_idx = None
                elif key == "media":
                    if self._media_hit_rects:
                        for m_ctrl, m_rect in self._media_hit_rects.items():
                            if m_rect.contains(pos):
                                new_media_ctrl = m_ctrl
                                break
                tooltip_text = self.get_tooltip_text(key, extra)
                break

        self._hover_media_ctrl = new_media_ctrl

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
            if new_hover == "tray":
                self.submit_fetch("tray")

        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.preview_mode:
            self.bubble.hide()
        if self._hover_key is not None or self._hover_app_idx is not None:
            self._hover_key = None
            self._hover_app_idx = None
            self.setToolTip("")
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
                if self.vol_popover.isVisible():
                    self.vol_popover.update_volume(new_val, self._vol_muted, self._vol_device)
                self.update()
                if not self.preview_mode:
                    self._vol_coalescer.request(new_val, force=False)
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
                action = None
                if r_prev and r_prev.contains(pos):
                    action = "prev"
                elif r_play and r_play.contains(pos):
                    action = "playpause"
                elif r_next and r_next.contains(pos):
                    action = "next"
                if action:
                    sources.submit("media_ctl", lambda a=action: media.media_control(a))
                    QTimer.singleShot(350, lambda: self.submit_fetch("media"))
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
        elif key == "clock" or key == "cal":
            # Takvim paneli contract: self.cal_panel.show_for(anchor_global, month_data, claude_data)
            cal_data = dict(self.store.get("cal") or {})
            month_data = dict(self.store.get("calmonth") or cal_data)
            c_data = dict(self.store.get("claude") or {})
            anchor_global = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())

            if self.cal_panel is not None and hasattr(self.cal_panel, "show_for"):
                is_open = getattr(self.cal_panel, "is_open", None)
                recently_closed = getattr(self.cal_panel, "recently_closed", None)
                hide_animated = getattr(self.cal_panel, "hide_animated", None)

                if is_open and is_open():
                    if hide_animated:
                        hide_animated()
                    else:
                        self.cal_panel.hide()
                elif recently_closed and recently_closed():
                    pass
                else:
                    try:
                        self.cal_panel.show_for(anchor_global, month_data, c_data)
                    except Exception as exc:
                        sources.log_err("cal_panel_show", exc)
                        self.popover.show_for("cal", anchor_global, cal_data)
            else:
                if self.popover.is_open("cal"):
                    self.popover.hide_animated()
                elif not self.popover.recently_closed("cal"):
                    self.popover.show_for("cal", anchor_global, cal_data)
        elif key in ("claude", "sys", "wx", "fx"):
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
                    top_entry = self.store.get("top")
                    if isinstance(top_entry, dict):
                        data["top"] = top_entry.get("top") or top_entry.get("data") or []
                    elif isinstance(top_entry, list):
                        data["top"] = top_entry
                    else:
                        data["top"] = []
                    self.submit_fetch("top")
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

        menu.addSeparator()
        style_group = QActionGroup(menu)
        style_group.setExclusive(True)
        for label, style in (("Tam genişlik şerit", "band"), ("Ortada kapsül", "pill")):
            act_style = QAction(label, menu)
            act_style.setCheckable(True)
            act_style.setChecked((style == "band") == self._is_band())
            act_style.triggered.connect(lambda _c=False, st=style: self.set_dock_style(st))
            style_group.addAction(act_style)
            menu.addAction(act_style)
        menu.addSeparator()

        # Optional cards toggles (dock v3: sys, fx, cal)
        cards_cfg = dict(self.settings.get("cards") or {})
        
        act_cal = QAction("Takvim kartı", menu)
        act_cal.setCheckable(True)
        act_cal.setChecked(cards_cfg.get("cal", True))
        def on_toggle_cal(checked: bool):
            cfg = dict(self.settings.get("cards") or {})
            cfg["cal"] = checked
            self.settings["cards"] = cfg
            save_settings(self.settings)
            self.compute_layout_and_resize()
            self.place_dock()
            self.update()
        act_cal.triggered.connect(on_toggle_cal)
        menu.addAction(act_cal)

        act_sys = QAction("Sistem kartı", menu)
        act_sys.setCheckable(True)
        act_sys.setChecked(cards_cfg.get("sys", False))
        def on_toggle_sys(checked: bool):
            cfg = dict(self.settings.get("cards") or {})
            cfg["sys"] = checked
            self.settings["cards"] = cfg
            save_settings(self.settings)
            self.compute_layout_and_resize()
            self.place_dock()
            self.update()
        act_sys.triggered.connect(on_toggle_sys)
        menu.addAction(act_sys)

        act_market = QAction("Piyasa kartı", menu)
        act_market.setCheckable(True)
        act_market.setChecked(cards_cfg.get("fx", False))
        def on_toggle_market(checked: bool):
            cfg = dict(self.settings.get("cards") or {})
            cfg["fx"] = checked
            self.settings["cards"] = cfg
            save_settings(self.settings)
            self.compute_layout_and_resize()
            self.place_dock()
            self.update()
        act_market.triggered.connect(on_toggle_market)
        menu.addAction(act_market)

        menu.addSeparator()

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

    def set_dock_style(self, style: str) -> None:
        style = "pill" if style == "pill" else "band"
        if str(self.settings.get("style", "band")) == style:
            return
        self.settings["style"] = style
        save_settings(self.settings)
        self._content_w = 0.0
        self.compute_layout_and_resize(initial=True)
        self._register_appbar()  # ayrılan alt alan: bant 64, kapsül 80
        self.place_dock()
        self.update()

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

    cal_data = sources.fetch_calendar()
    store.update("cal", cal_data)

    raw_wins = winapi.list_windows()
    groups = winapi.group_by_app(raw_wins)
    pins = list(settings.get("pinned") or pinned.load_default_pins())
    tiles = pinned.merge_tiles(pins, groups)

    # Initialize dock in preview mode (zero side effects)
    dock = SeritDock(settings, preview_mode=True)
    dock.store = store
    dock.pins = pins
    dock.tiles = tiles

    for t in tiles:
        exe = t.get("exe") or t.get("path") or ""
        if exe and exe not in dock._icon_cache:
            dock._icon_cache[exe] = winapi.app_icon(exe, 64)

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

    print(f"PREVIEW_SAVED: {out_p} ({cw1}x{ch1} @2x, dock_w={dock_w}px)")
    print(f"PREVIEW_HOVER_SAVED: {hover_p} ({cw2}x{ch2} @2x)")
    return


def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sources.LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} [UNCAUGHT] {tb_str}\n")
    except Exception:
        pass


sys.excepthook = _handle_exception


def main() -> None:
    sources.rotate_log_if_needed()

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
        pid, hostname, appname = lock.getLockInfo()
        is_live = False
        if pid and psutil.pid_exists(pid):
            try:
                proc = psutil.Process(pid)
                cmdline = " ".join(proc.cmdline())
                if "serit_v5.pyw" in cmdline:
                    is_live = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                is_live = False
        if not is_live:
            lock.removeStaleLockFile()
            if not lock.tryLock(100):
                print("Şerit zaten çalışıyor.")
                return
        else:
            print("Şerit zaten çalışıyor.")
            return

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    settings = load_settings()
    dock = SeritDock(settings, preview_mode=False)
    app.aboutToQuit.connect(dock.cleanup)
    atexit.register(dock.cleanup)
    dock.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
