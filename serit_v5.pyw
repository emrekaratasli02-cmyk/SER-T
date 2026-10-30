"""Şerit v5 - Modern acrylic glass floating dock for Windows 11.

Integrates theme.py (design tokens & primitives), anim.py (zero-idle driver & tweens),
pinned.py (pinned apps & dark glass tiles), popover_v2.py (sectioned acrylic flyouts),
alerts.py (proactive notification toasts), trayicons.py + tray_panel.py (hidden icons overflow),
and media.py (volume slider popover, media keys & now-playing detection).
"""

from __future__ import annotations

import atexit
import collections
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
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

import action_menu
import alerts
import anim
import brightness
import battery_panel
import brightness_popover
import dock_cards
import media
import pinned
import popover_v2
import power_net
import sources
import theme
import trayicons
import winapi

try:
    import work_sources
except ImportError:
    work_sources = None


class LRUCache(collections.OrderedDict):
    """Bounded LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 128, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        val = super().__getitem__(key)
        self.move_to_end(key)
        return val

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
            return super().__getitem__(key)
        return default

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        if len(self) > self.maxsize:
            self.popitem(last=False)

try:
    import tray_panel
except ImportError:
    tray_panel = None


def clean_tray_name(item: Any) -> str:
    """Helper to get cleaned tray name according to tray_panel contract."""
    if tray_panel is not None and hasattr(tray_panel, "clean_tray_name"):
        try:
            return tray_panel.clean_tray_name(item)
        except Exception:
            pass
    if isinstance(item, dict):
        return str(item.get("name") or item.get("tooltip") or "")
    return str(item)

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
        "cal": True,
        "mail": True,
        "ag": True,
        "sys": True,
    },
}

# Dimension Tokens for v5 / dock v3
DOCK_HEIGHT: float = 64.0
DOCK_RADIUS: float = 20.0
CARD_HEIGHT: float = 52.0
CARD_RADIUS: float = 13.0
CARD_Y: float = 6.0
GAP_MODULE: float = 6.0
CLAUDE_CARD_WIDTH: float = 204.0  # v24: %100 + Oturum + '23 sa 59 dk' sığsın (metin alanı 135)
MEDIA_CARD_WIDTH: float = 314.0
MEDIA_CARD_WIDTH_COMPACT: float = 240.0
AG_CARD_WIDTH: float = 204.0
MAIL_CARD_MIN_WIDTH: float = 112.0
MAIL_CARD_MAX_WIDTH: float = 150.0
SYS_CARD_WIDTH: float = 96.0
MARKET_CARD_WIDTH: float = 160.0
CLOCK_BLOCK_WIDTH: float = 70.0
TRAY_COLUMN_WIDTH: float = 32.0
ACTION_BUTTONS_WIDTH: float = 110.0
ACTION_BTN_SIZE: float = 30.0
ACTION_BTN_GAP: float = 6.0
ACTION_PILL_WIDTH: float = 74.0
ACTION_PILL_WIDTH_BAT: float = 136.0   # gunes | hoparlor | pil
ACTION_PILL_HEIGHT: float = 32.0
DESKTOP_STRIP_W: float = 8.0   # sol alt köşedeki "masaüstünü göster" şeridi
HOVER_OPEN_MS: int = 450       # kütük üzerinde bu kadar durunca önizleme açılır
HOVER_HIDE_MS: int = 250       # kütükten / önizlemeden çıkınca bu kadar sonra kapanır
TRAY_ICON_SIZE: float = 26.0
TRAY_ICON_GAP: float = 2.0

TR_DAYS = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}
_LAST_PAINT_ERROR_LOG: float = 0.0


def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
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
    if isinstance(cfg.get("cards"), dict):
        merged_cards = {"cal": True, "mail": True, "ag": True, "sys": True}
        merged_cards.update(cfg["cards"])
        cfg["cards"] = merged_cards
    return cfg


def save_settings(cfg: dict) -> None:
    try:
        tmp_file = SETTINGS_FILE.parent / "settings.json.tmp"
        bak_file = SETTINGS_FILE.parent / "settings.json.bak"
        content = json.dumps(cfg, ensure_ascii=False, indent=2)
        with open(tmp_file, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        if SETTINGS_FILE.exists():
            try:
                curr_content = SETTINGS_FILE.read_text(encoding="utf-8")
                parsed = json.loads(curr_content)
                if isinstance(parsed, dict):
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
        self._icon_cache = LRUCache(128)
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
                new_images = trayicons.get_tray_images(uncached)
                for it in uncached:
                    name = it.get("name", "")
                    key = f"{name}::{it.get('exe', '')}"
                    img = new_images.get(name)
                    if img is not None and not img.isNull():
                        self._icon_cache[key] = QPixmap.fromImage(img)
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


import volume_panel
VolumePopover = volume_panel.VolumePopover


class DataDispatcher(QObject):
    """Thread-safe UI dispatcher bridging background fetcher thread pool to Qt signals."""

    data_ready = Signal(str, object)
    brightness_done = Signal(str, int)
    tray_resolved = Signal(object, object, object)
    action_done = Signal(str)
    end_task_done = Signal(object, object)  # (tray item, end_task result)
    thumbs_ready = Signal(object, object)  # (exe, {hwnd: QImage}) pencere seçicisi önizlemeleri


def _is_same_data(old: Any, new: Any) -> bool:
    if old is new:
        return True
    if not isinstance(old, dict) or not isinstance(new, dict):
        return old == new
    for k, v in new.items():
        if k == "fetched_at":
            continue
        if old.get(k) != v:
            return False
    return True


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
        self._hover_tray_item: Optional[Dict[str, Any]] = None
        self._preview_hover_idx: Optional[int] = None
        self._pressed_key: Optional[str] = None
        self._icon_cache = LRUCache(128)
        self._clock_rect: Optional[QRectF] = None
        self._media_rect: Optional[QRectF] = None
        self._tray_items: List[Dict[str, Any]] = []
        self._tray_icons: Dict[str, QPixmap] = {}

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
        self.anim_driver.frame.connect(self._on_anim_frame)

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
        self.brightness_popover = brightness_popover.BrightnessPopover()
        self._bat_info: Dict[str, Any] = {}
        self._bat_known_absent: bool = False
        self.battery_panel = battery_panel.BatteryPanel()
        self.battery_panel.toggle_requested.connect(self._on_bat_toggle_requested)
        self.battery_panel.settings_requested.connect(self._on_bat_settings_requested)
        # v22: ses ve parlaklık sürgüleri pil panelinde (kapsülde yalnız pil kaldı)
        for sig_name, slot in (
            ("volume_requested", self._on_bat_volume_requested),
            ("mute_requested", self._on_bat_mute_requested),
            ("brightness_requested", self._on_brightness_requested),
            ("open_volume_mixer", self._on_bat_open_volume_mixer),
            ("open_brightness", self._on_bat_open_brightness),
        ):
            sig = getattr(self.battery_panel, sig_name, None)
            if sig is not None:
                sig.connect(slot)
        self.brightness_popover.level_requested.connect(self._on_brightness_requested)
        self._pending_brightness: Dict[str, int] = {}
        self.bubble = BubbleWidget(self)
        # v24 adım 2: açılış geri bildirimi (nabız noktası + 'açılamadı' balonu)
        self.fail_bubble = BubbleWidget(self)
        self._last_fail_text: str = ""
        self._fail_bubble_timer = QTimer(self)
        self._fail_bubble_timer.setSingleShot(True)
        self._fail_bubble_timer.timeout.connect(self.fail_bubble.hide)
        self._launching: Dict[str, float] = {}
        self._launch_static = False
        self._launch_timer = QTimer(self)
        self._launch_timer.setInterval(60)
        self._launch_timer.timeout.connect(self._tick_launching)

        # Tray Panel contract
        self.tray_panel = None
        try:
            import tray_panel
            self.tray_panel = tray_panel.TrayPanel()
            if hasattr(self.tray_panel, "item_activated"):
                self.tray_panel.item_activated.connect(self._on_tray_panel_item_activated)
        except (ImportError, Exception) as exc:
            sources.log_err("tray_panel_init", exc)
            self.tray_panel = None

        # Info Panels contract (MailPanel & QuotaPanel)
        self.mail_panel = None
        self.quota_panel = None
        try:
            import info_panels
            if hasattr(info_panels, "MailPanel"):
                self.mail_panel = info_panels.MailPanel()
                if hasattr(self.mail_panel, "refresh_requested"):
                    self.mail_panel.refresh_requested.connect(lambda: self.submit_fetch("mail"))
            if hasattr(info_panels, "QuotaPanel"):
                self.quota_panel = info_panels.QuotaPanel()
                if hasattr(self.quota_panel, "refresh_requested"):
                    self.quota_panel.refresh_requested.connect(lambda: self.submit_fetch("ag"))
        except (ImportError, Exception) as exc:
            sources.log_err("info_panels_init", exc)

        # Action Menu & Tray Actions contract
        self.action_menu = None
        self._action_in_flight: bool = False
        self._action_menu_item: Optional[dict] = None
        self._dock_action_menu: Optional[action_menu.ActionMenu] = None
        self._app_action_menu: Optional[action_menu.ActionMenu] = None
        self.window_picker = None  # çok pencereli uygulama döşemesine tıklayınca (ilk kullanımda kurulur)
        self._fs_hidden: bool = False  # tam ekran uygulama yüzünden gizli mi
        # Üzerine gelince önizleme (hover_preview.py, ilk kullanımda kurulur)
        self.hover_preview = None
        self._hover_tile_idx: Optional[int] = None
        self._hover_tile_exe: Optional[str] = None
        self._thumb_cache: Dict[str, Tuple[float, Dict[int, Any]]] = {}
        self._hover_open_timer = QTimer(self)
        self._hover_open_timer.setSingleShot(True)
        self._hover_open_timer.timeout.connect(self._open_hover_preview)
        self._hover_hide_timer = QTimer(self)
        self._hover_hide_timer.setSingleShot(True)
        self._hover_hide_timer.timeout.connect(self._hide_hover_preview)
        self._hover_refresh_timer = QTimer(self)
        self._hover_refresh_timer.setInterval(1500)
        self._hover_refresh_timer.timeout.connect(self._refresh_hover_preview)
        self._picker_exe: Optional[str] = None
        self._raw_windows: List[Dict[str, Any]] = []
        self._pending_actions: Dict[str, Tuple[Callable[[], Any], Optional[Callable[[], None]]]] = {}
        try:
            if hasattr(action_menu, "ActionMenu"):
                self.action_menu = action_menu.ActionMenu()
                if hasattr(self.action_menu, "action_chosen"):
                    self.action_menu.action_chosen.connect(self._on_action_chosen)
        except (ImportError, Exception) as exc:
            sources.log_err("action_menu_init", exc)

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
        self._appbar_hwnd: Optional[int] = None
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

        # Data thread dispatcher & timers
        self.dispatcher = DataDispatcher(self)
        self.dispatcher.data_ready.connect(self.on_data_ready)
        self.dispatcher.brightness_done.connect(self._on_brightness_task_done)
        self.dispatcher.tray_resolved.connect(self._on_tray_resolved)
        self.dispatcher.action_done.connect(self._on_action_task_done)
        self.dispatcher.end_task_done.connect(self._on_end_task_done)
        self.dispatcher.thumbs_ready.connect(self._on_picker_thumbs)
        if not self.preview_mode:
            self.setup_timers()
            self._setup_battery_timers()

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

    # Bu farktan küçük değişimlerde halka/sayı animasyonu oynatılmaz, doğrudan hedefe oturur:
    # boşta 2 sn'de bir gelen 1-3 puanlık dalgalanma için 60 fps'lik süpürme göze görünmez
    # ama her seferinde ~20 tam kare çizdiriyordu. Büyük değişimlerde onaylı süpürme sürer.
    RING_SNAP_DELTA = 5.0

    def _ring_move(self, tw, target: float) -> None:
        if abs(float(target) - tw.value) >= self.RING_SNAP_DELTA:
            tw.retarget(target)
            return
        tw.stop()
        tw.value = float(target)
        tw.start_val = float(target)
        tw.target_val = float(target)

    def _on_anim_frame(self) -> None:
        tweens = getattr(self.anim_driver, "_tweens", None)
        if not tweens:
            # Son kare: biten tween'ler sürücüden düşmüş olarak gelir. Eskiden bu karede her
            # seferinde tüm şerit çiziliyordu (sistem halkaları her 2 sn'de bir oynar). Artık
            # biten tween'lere bakılır: hepsi tek karta aitse yalnız o kart, değilse tam çizim.
            region = self._anim_region(getattr(self.anim_driver, "last_finished", ()))
            self.update(region) if region is not None else self.update()
            return
        region = self._anim_region(tweens)
        self.update(region) if region is not None else self.update()

    def _anim_region(self, tweens) -> Optional[QRect]:
        """Yalnız tek bir kartın tween'leri oynuyorsa o kartın dikdörtgeni, yoksa None (tam çizim)."""
        if not tweens:
            return None
        if all(t in (self.anim_cpu, self.anim_ram, self.anim_sys_op) for t in tweens):
            r = self._get_card_rect("sys")
            return r.toRect().adjusted(-2, -2, 2, 2) if r is not None else None
        if all(t in (self.anim_claude_s, self.anim_claude_w, self.anim_claude_op) for t in tweens):
            r = self._get_card_rect("claude")
            return r.toRect().adjusted(-2, -2, 2, 2) if r is not None else None
        if all(t in (self.anim_pill_x, self.anim_pill_opacity) for t in tweens):
            if self._tile_rects:
                return self._tile_rects[0].united(self._tile_rects[-1]).adjusted(-4, -4, 4, 8).toRect()
        return None

    def _get_card_rect(self, key: Optional[str]) -> Optional[QRectF]:
        if not key:
            return None
        for r, k, _ in self.hit_boxes:
            if k == key:
                return r
        return None

    # ------------------------------------------------------------------ pil
    def _has_battery(self) -> bool:
        b = self._bat_info
        return bool(b.get("present")) and b.get("percent") is not None

    def _pill_width(self) -> float:
        return dock_cards.BATTERY_PILL_W if self._has_battery() else ACTION_PILL_WIDTH

    def _draw_quick_pill(
        self,
        p: QPainter,
        r_pill: QRectF,
        bright_open: bool,
        vol_open: bool,
        register_hitboxes: bool = True,
    ) -> None:
        """Pil varsa yalnız pil kapsülü (ses/parlaklık pil panelinde); yoksa eski güneş | hoparlör kapsülü."""
        bat_open = bool(self.battery_panel.is_open())
        if self._has_battery():
            r_bat = dock_cards.draw_battery_pill(
                p,
                r_pill,
                float(self._bat_info.get("percent")),
                # fişteyken de yeşil: Windows %99-100'de 'şarj olmuyor' der ama makine prizde
                bool(self._bat_info.get("charging")) or bool(self._bat_info.get("plugged")),
                hovered=(self._hover_key == "bat"),
                active=bat_open,
                on_ac_full=battery_panel.on_ac_full(self._bat_info),  # v24: fiş + "Prizde"
            )
            if register_hitboxes:
                self.hit_boxes.append((r_bat, "bat", None))
            return
        hov_part = self._hover_key if self._hover_key in ("bright", "vol", "bat") else None
        act_part = "bright" if bright_open else ("vol" if vol_open else ("bat" if bat_open else None))
        pill_res = dock_cards.draw_quick_settings_pill(
            p,
            r_pill,
            hovered_part=hov_part,
            active_part=act_part,
            vol_level=self._vol_level,
            vol_muted=self._vol_muted,
            bat_percent=self._bat_info.get("percent"),
            bat_charging=bool(self._bat_info.get("charging")),
            bat_present=False,
        )
        if register_hitboxes:
            self.hit_boxes.append((pill_res[0], "bright", None))
            self.hit_boxes.append((pill_res[1], "vol", None))

    def _register_quick_pill_hitboxes(self, r_pill: QRectF, bright_open: bool, vol_open: bool) -> None:
        if self._has_battery():
            self.hit_boxes.append((r_pill, "bat", None))
        else:
            hw = r_pill.width() / 2.0
            r_sun = QRectF(r_pill.x(), r_pill.y(), hw, r_pill.height())
            r_spk = QRectF(r_pill.x() + hw, r_pill.y(), hw, r_pill.height())
            self.hit_boxes.append((r_sun, "bright", None))
            self.hit_boxes.append((r_spk, "vol", None))

    def _actions_width(self) -> float:
        return ACTION_BTN_SIZE + ACTION_BTN_GAP + self._pill_width()

    def _setup_battery_timers(self) -> None:
        """Pil 30 sn'de bir; Wi-Fi/Bluetooth ve en yuksek yuk yalniz panel acikken 5 sn'de bir."""
        self.bat_timer = QTimer(self)
        self.bat_timer.setInterval(30000)
        self.bat_timer.timeout.connect(self._poll_battery)
        self.bat_timer.start()
        self.batnet_timer = QTimer(self)
        self.batnet_timer.setInterval(5000)
        self.batnet_timer.timeout.connect(self._poll_battery_panel)
        self.batnet_timer.start()
        self._poll_battery()

    def _poll_battery(self) -> None:
        if self._bat_known_absent and not self.battery_panel.is_open():
            return
        self.submit_fetch("bat")

    def _poll_battery_panel(self) -> None:
        if self.battery_panel.is_open():
            self.submit_fetch("batnet")
            if self._bat_wants_top():
                self.submit_fetch("battop")

    def _bat_wants_top(self) -> bool:
        b = self._bat_info
        try:
            return (
                bool(b.get("present"))
                and not b.get("plugged")
                and not b.get("charging")
                and float(b.get("rate_w") or 0) >= battery_panel.TOP_LOAD_MIN_W
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _read_batnet() -> Dict[str, Any]:
        sup = power_net.radio_toggle_supported()
        return {"wifi": power_net.wifi_info(), "bt": power_net.bluetooth_info(), "supported": sup}

    @staticmethod
    def _read_top_load() -> List[Dict[str, Any]]:
        """Kisa aralikla CPU olcer (arka plan isci); Idle ve dock'un kendisi haric."""
        me = os.getpid()
        procs = []
        for pr in psutil.process_iter(["pid", "name"]):
            try:
                nm = str(pr.info.get("name") or "").lower()
                if pr.info["pid"] in (0, me) or nm in ("system idle process", "system", "idle"):
                    continue
                pr.cpu_percent(None)
                procs.append(pr)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.5)
        ncpu = float(psutil.cpu_count() or 1)
        agg: Dict[str, float] = {}
        for pr in procs:
            try:
                name = str(pr.info.get("name") or "")
                agg[name] = agg.get(name, 0.0) + pr.cpu_percent(None) / ncpu
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        friendly = {
            "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "zen.exe": "Zen",
            "hermes.exe": "Hermes", "python.exe": "Python", "pythonw.exe": "Python", "code.exe": "VS Code",
            "claude.exe": "Claude", "explorer.exe": "Gezgin", "discord.exe": "Discord", "spotify.exe": "Spotify",
        }
        out = [
            {"name": friendly.get(k.lower(), k[:-4] if k.lower().endswith(".exe") else k), "cpu": round(v, 1)}
            for k, v in agg.items() if v > 0.0
        ]
        out.sort(key=lambda x: x["cpu"], reverse=True)
        return out[:2]

    def _on_battery_data(self, key: str, res: Any) -> None:
        panel = self.battery_panel
        if key == "bat":
            if isinstance(res, dict) and not res.get("err"):
                had = self._has_battery()
                if _is_same_data(self._bat_info, res):
                    return
                self._bat_info = dict(res)
                self._bat_known_absent = not bool(res.get("present"))
                panel.set_battery(self._bat_info)
                if had != self._has_battery():
                    self.compute_layout_and_resize()
                    self.update()
                else:
                    r_bat = self._get_card_rect("bat")
                    if r_bat is not None:
                        self.update(r_bat.toRect().adjusted(-2, -2, 2, 2))
                    else:
                        self.update()
            return
        if key == "battop":
            panel.set_top_load(res if isinstance(res, list) else [])
            return
        if isinstance(res, dict) and not res.get("err"):
            settled = bool(res.get("settled"))
            sup = res.get("supported")
            if isinstance(sup, dict):
                panel.set_supported(bool(sup.get("wifi", True)), bool(sup.get("bluetooth", True)))
            if isinstance(res.get("wifi"), dict) and (settled or not panel.is_busy("wifi")):
                panel.set_wifi(res["wifi"])
            if isinstance(res.get("bt"), dict) and (settled or not panel.is_busy("bluetooth")):
                panel.set_bluetooth(res["bt"])

    def _on_bat_toggle_requested(self, kind: str, target_on: bool) -> None:
        """Wi-Fi/Bluetooth anahtari: ayar ve yeniden okuma arka plan iscisinde."""
        def _worker() -> Dict[str, Any]:
            try:
                if kind == "wifi":
                    power_net.set_wifi(bool(target_on))
                else:
                    power_net.set_bluetooth(bool(target_on))
            except Exception as exc:
                sources.log_err(f"bat_set_{kind}", exc)
            out: Dict[str, Any] = {"settled": True}
            if kind == "wifi":
                out["wifi"] = power_net.wifi_info()
            else:
                out["bt"] = power_net.bluetooth_info()
            return out

        if not sources.submit(f"bat_set_{kind}", _worker, lambda k, r: self.dispatcher.data_ready.emit("batnet", r)):
            self.battery_panel.set_busy(kind, None)

    def _on_bat_settings_requested(self, page: str) -> None:
        def _worker() -> bool:
            return bool(power_net.open_settings(page))
        sources.submit("bat_settings", _worker)

    # ---------------------------------------------------- kapsul paneli gecisi
    def _pill_panel(self, key: str):
        return {"bright": self.brightness_popover, "vol": self.vol_popover, "bat": self.battery_panel}[key]

    def _pill_panel_visible(self, key: str) -> bool:
        try:
            return bool(self._pill_panel(key).isVisible())
        except Exception:
            return False

    def _pill_panel_open(self, key: str) -> bool:
        pnl = self._pill_panel(key)
        if hasattr(pnl, "is_open"):
            return bool(pnl.is_open())
        return bool(pnl.isVisible())

    def _handle_pill_click(self, key: str, rect: QRectF) -> None:
        panel = self._pill_panel(key)
        if self._pill_panel_open(key):
            (getattr(panel, "hide_animated", None) or panel.hide)()
            return
        if hasattr(panel, "recently_closed") and panel.recently_closed():
            return
        switch_from: Optional[int] = None
        for other in ("bright", "vol", "bat"):
            if other != key and self._pill_panel_visible(other):
                op = self._pill_panel(other)
                switch_from = int(op.x())
                (getattr(op, "hide_instant", None) or getattr(op, "hide_animated", None) or op.hide)()
        anchor_global = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())
        if key == "bright":
            self.submit_fetch("bright")
            args: tuple = (self._get_store_monitors(),)
        elif key == "vol":
            args = (self._vol_level, self._vol_muted, self._vol_device)
        else:
            args = ()
            self.submit_fetch("bat")
            self.submit_fetch("batnet")
            self.submit_fetch("bright")
            self._push_bat_panel_controls()
        if switch_from is not None:
            try:
                panel.show_for(anchor_global, *args, switch_from_x=switch_from)
                return
            except TypeError:
                pass
        panel.show_for(anchor_global, *args)

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
                self._appbar_hwnd = hwnd

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
        hwnd = getattr(self, "_appbar_hwnd", None) or int(self.winId() or 0)
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
            self._appbar_hwnd = None
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

        try:
            ctypes.windll.user32.RegisterWindowMessageW.restype = ctypes.c_uint
            SeritDock._WM_TASKBAR_CREATED = int(ctypes.windll.user32.RegisterWindowMessageW("TaskbarCreated"))
        except Exception as exc:
            sources.log_err("taskbar_created", exc)
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

    _WM_TASKBAR_CREATED: int = 0

    def nativeEvent(self, event_type, message):
        """Explorer yeniden başlayınca Windows 'TaskbarCreated' yayınlar: alanı ve gizlemeyi yenile."""
        try:
            if event_type == b"windows_generic_MSG" and SeritDock._WM_TASKBAR_CREATED:
                import ctypes.wintypes as _wt
                msg = _wt.MSG.from_address(int(message))
                if msg.message == SeritDock._WM_TASKBAR_CREATED:
                    QTimer.singleShot(1500, self._on_taskbar_created)
        except Exception as exc:
            sources.log_err("nativeEvent", exc)
        return super().nativeEvent(event_type, message)

    def _on_taskbar_created(self) -> None:
        """Explorer yeni görev çubuğunu kurdu: eski appbar kaydı geçersiz, yeniden kaydol."""
        if self.preview_mode:
            return
        sources.log_err("explorer", RuntimeError("Explorer yeniden başladı; ayrılan alan yenileniyor"))
        self._appbar_registered = False
        self._appbar_hwnd = None
        if self.settings.get("hide_taskbar", False):
            winapi.taskbar_autohide_set(True)
        self._register_appbar()
        self.place_dock()
        self.update()

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
        # Bekçiye "isteyerek kapandı" işareti (serit_bekci.pyw bu dosyayı görünce barı yeniden başlatmaz)
        try:
            (APP_DIR / ".clean_exit").touch()
        except Exception:
            pass
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

        # Tam ekran (video, oyun, sunum) öndeyken bar gizlenir; 1 s yoklama, tek çağrı ~0.1 ms
        self.fs_timer = QTimer(self)
        self.fs_timer.setInterval(1000)
        self.fs_timer.timeout.connect(self._check_fullscreen)
        self.fs_timer.start()

        # Media & Volume polling timer (3 s)
        self.media_timer = QTimer(self)
        self.media_timer.setInterval(3000)
        self.media_timer.timeout.connect(lambda: self.submit_fetch("media"))
        self.media_timer.start()
        self.submit_fetch("media")

        # Media progress ring smooth update timer (2 Hz / 500 ms)
        # Repaints only the play button rect while playing with known duration, near-zero CPU.
        self.media_ring_timer = QTimer(self)
        self.media_ring_timer.setInterval(500)
        self.media_ring_timer.timeout.connect(self._on_media_ring_tick)
        self.media_ring_timer.start()

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

        # Brightness polling timer (60 s)
        self.bright_timer = QTimer(self)
        self.bright_timer.setInterval(60000)
        self.bright_timer.timeout.connect(lambda: self.submit_fetch("bright"))
        self.bright_timer.start()
        self.submit_fetch("bright")

        # Clock refresh timer (10 s) - repaints only the clock rect (Requirement 6)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(10000)
        self.clock_timer.timeout.connect(self._on_clock_tick)
        self.clock_timer.start()

        # Mail polling timer (every 5 min = 300 s + at start)
        self.mail_timer = QTimer(self)
        self.mail_timer.setInterval(300000)
        self.mail_timer.timeout.connect(lambda: self.submit_fetch("mail"))
        self.mail_timer.start()
        self.submit_fetch("mail")

        # Antigravity quota polling timer (every 10 min = 600 s + at start)
        self.ag_timer = QTimer(self)
        self.ag_timer.setInterval(600000)
        self.ag_timer.timeout.connect(lambda: self.submit_fetch("ag"))
        self.ag_timer.start()
        self.submit_fetch("ag")

    def _sync_tray_icons(self) -> None:
        """Cache tray icon pixmaps on GUI thread without blocking."""
        uncached = []
        for it in self._tray_items:
            name = it.get("name", "")
            if name not in self._tray_icons or self._tray_icons[name].isNull():
                uncached.append(it)
        if uncached:
            try:
                new_images = trayicons.get_tray_images(uncached)
                for name, img in new_images.items():
                    if img is not None and not img.isNull():
                        self._tray_icons[name] = QPixmap.fromImage(img)
            except Exception as exc:
                sources.log_err("dock_sync_tray_icons", exc)

    def _get_store_monitors(self) -> List[Dict[str, Any]]:
        raw = self.store.get("bright")
        if isinstance(raw, dict) and "data" in raw:
            return list(raw["data"] or [])
        if isinstance(raw, list):
            return list(raw)
        return []

    def _update_store_brightness_level(self, mon_id: str, level: int) -> None:
        """Update monitor level in local store optimistically."""
        monitors = self._get_store_monitors()
        found = False
        for m in monitors:
            if isinstance(m, dict) and str(m.get("id")) == str(mon_id):
                m["level"] = level
                found = True
                break
        if not found:
            monitors.append({"id": mon_id, "name": mon_id, "level": level, "ok": True})
        self.store.update("bright", monitors)

    def _on_brightness_requested(self, mon_id: str, level: int) -> None:
        """Handle coalesced brightness slider change, queuing latest value."""
        level = max(0, min(100, int(round(level))))
        self._update_store_brightness_level(mon_id, level)
        if not self.preview_mode:
            self._pending_brightness[mon_id] = level
            self._flush_brightness(mon_id)

    def _flush_brightness(self, mon_id: str) -> None:
        """Apply pending brightness level on worker thread pool."""
        if mon_id not in self._pending_brightness:
            return
        lvl = self._pending_brightness[mon_id]
        submit_key = f"bright_set_{mon_id}"

        def _worker():
            return brightness.set_level(mon_id, lvl)

        def _callback(*_args):
            if hasattr(self, "dispatcher") and self.dispatcher is not None:
                self.dispatcher.brightness_done.emit(mon_id, lvl)

        submitted = sources.submit(submit_key, _worker, _callback)
        if submitted:
            if self._pending_brightness.get(mon_id) == lvl:
                del self._pending_brightness[mon_id]
        else:
            QTimer.singleShot(25, lambda: self._flush_brightness(mon_id))

    def _on_brightness_task_done(self, mon_id: str, _finished_lvl: int) -> None:
        """Invoked on GUI thread when worker completes: re-flush if newer value pending."""
        if mon_id in self._pending_brightness:
            self._flush_brightness(mon_id)

    def submit_action(
        self,
        key: str,
        action_fn: Callable[[], Any],
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        """Submit an action to the thread pool with pending latest action per key."""
        self._pending_actions[key] = (action_fn, on_done)
        self._flush_action(key)

    def _flush_action(self, key: str) -> None:
        if key not in self._pending_actions:
            return
        fn, on_done = self._pending_actions[key]

        def _worker():
            return fn()

        def _callback(*_args):
            if hasattr(self, "dispatcher") and self.dispatcher is not None:
                self.dispatcher.action_done.emit(key)

        submitted = sources.submit(key, _worker, _callback)
        if submitted:
            if self._pending_actions.get(key) == (fn, on_done):
                del self._pending_actions[key]
            if on_done:
                try:
                    on_done()
                except Exception as exc:
                    sources.log_err(f"{key}_done", exc)
        else:
            QTimer.singleShot(40, lambda: self._flush_action(key))

    def _on_action_task_done(self, key: str) -> None:
        """Invoked on GUI thread when worker completes: re-flush if newer action pending."""
        if key in self._pending_actions:
            self._flush_action(key)

    def _on_clock_tick(self) -> None:
        """Repaint only the clock rect for near-zero idle CPU.

        Claude / kota kartlarındaki geri sayım ("47 dk") boyama anında hesaplanır; veri değişmese de
        güncel kalsın diye bu iki kart da aynı tikte (10 sn) yeniden çizilir.
        """
        if self._clock_rect is not None:
            self.update(self._clock_rect.toRect().adjusted(-2, -2, 2, 2))
        else:
            self.update()
            return
        for key in ("claude", "ag"):
            r = self._get_card_rect(key)
            if r is not None:
                self.update(r.toRect().adjusted(-2, -2, 2, 2))

    def _on_media_ring_tick(self) -> None:
        """Repaint only the media play button rect for smooth ring progression (~2 fps, near-zero CPU)."""
        if not self._now_playing_info or not self._now_playing_info.get("playing"):
            t = getattr(self, "media_ring_timer", None)
            if t is not None:
                t.stop()  # çalma başlayınca medya verisi yeniden başlatır
            return
        dur = self._now_playing_info.get("duration_s")
        if dur is None or float(dur) <= 0.0:
            return
        if self._media_hit_rects and "playpause" in self._media_hit_rects:
            r_play = self._media_hit_rects["playpause"]
            self.update(r_play.toRect().adjusted(-3, -3, 3, 3))
        elif self._media_rect is not None:
            self.update(self._media_rect.toRect())

    def _poll_media_and_volume(self) -> None:
        """Poll media in background worker."""
        self.submit_fetch("media")

    def _on_volume_changed(self, lvl: float, muted: bool) -> None:
        self._vol_level = float(lvl)
        self._vol_muted = bool(muted)
        self._push_bat_panel_controls()
        self.update()

    # ---------------------------------------------- pil panelindeki ses / parlaklık
    def _push_bat_panel_controls(self) -> None:
        """Pil paneli açıksa ses ve parlaklık değerlerini ona da gönderir."""
        panel = getattr(self, "battery_panel", None)
        if panel is None or not hasattr(panel, "set_volume"):
            return
        try:
            panel.set_volume(self._vol_level, self._vol_muted, self._vol_device or None)
            panel.set_brightness(self._get_store_monitors())
        except Exception as exc:
            sources.log_err("bat_panel_controls", exc)

    def _on_bat_volume_requested(self, level: float) -> None:
        level = max(0.0, min(100.0, float(level)))
        self._vol_level = level
        if level > 0 and self._vol_muted:
            self._on_bat_mute_requested(False)
        if not self.preview_mode:
            self._vol_coalescer.request(level, force=False)
        if self.vol_popover.isVisible():
            self.vol_popover.update_volume(level, self._vol_muted, self._vol_device)
        self.update()

    def _on_bat_mute_requested(self, muted: bool) -> None:
        if bool(muted) == bool(self._vol_muted):
            return
        self._vol_muted = bool(muted)
        if not self.preview_mode:
            sources.submit("vol_mute", media.toggle_mute)
        self._push_bat_panel_controls()
        self.update()

    def _on_bat_open_volume_mixer(self) -> None:
        self._open_panel_from_battery("vol")

    def _on_bat_open_brightness(self) -> None:
        self._open_panel_from_battery("bright")

    def _open_panel_from_battery(self, key: str) -> None:
        """Pil panelindeki '›': ses mikserini / çok ekranlı parlaklığı aynı yerde açar."""
        rect = next((r for r, k, _ in self.hit_boxes if k == "bat"), None)
        if rect is None:
            rect = QRectF(self.width() - 220.0, 16.0, 80.0, 32.0)
        anchor_global = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())
        bp = self.battery_panel
        switch_from = int(bp.x()) if bp.isVisible() else None
        (getattr(bp, "hide_instant", None) or bp.hide)()
        if key == "bright":
            self.submit_fetch("bright")
            panel, args = self.brightness_popover, (self._get_store_monitors(),)
        else:
            panel, args = self.vol_popover, (self._vol_level, self._vol_muted, self._vol_device)
        try:
            if switch_from is not None:
                try:
                    panel.show_for(anchor_global, *args, switch_from_x=switch_from)
                    return
                except TypeError:
                    pass
            panel.show_for(anchor_global, *args)
        except Exception as exc:
            sources.log_err("bat_open_panel", exc)

    @staticmethod
    def _fetch_tray_worker() -> dict:
        items = trayicons.list_tray_items()
        images = trayicons.get_tray_images(items)
        return {"items": items, "images": images}

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
            "tray": self._fetch_tray_worker,
            "bright": brightness.list_monitors,
            "bat": power_net.battery_info,
            "batnet": self._read_batnet,
            "battop": self._read_top_load,
            "mail": getattr(work_sources, "fetch_mail_waiting", None),
            "ag": getattr(work_sources, "fetch_antigravity", None),
        }
        fn = fetchers.get(key)
        if fn:
            sources.submit(key, fn, lambda k, res: self.dispatcher.data_ready.emit(k, res))

    def on_data_ready(self, key: str, res: Any) -> None:
        if isinstance(res, dict) and res.get("err"):
            sources.log_err(key, RuntimeError(str(res.get("err"))))
        old_val = self.store.get(key)
        self.store.update(key, res)

        if key == "mail":
            if _is_same_data(old_val, res):
                return
            if self.mail_panel is not None and hasattr(self.mail_panel, "set_data"):
                try:
                    self.mail_panel.set_data(res if isinstance(res, dict) else {})
                except Exception as exc:
                    sources.log_err("mail_panel_set_data", exc)
            old_w = dock_cards.measure_mail_card_width(old_val if isinstance(old_val, dict) else {})
            new_w = dock_cards.measure_mail_card_width(res if isinstance(res, dict) else {})
            if old_w != new_w:
                self.compute_layout_and_resize()
                self.update()
            else:
                r_mail = self._get_card_rect("mail")
                if r_mail is not None:
                    self.update(r_mail.toRect().adjusted(-2, -2, 2, 2))
                else:
                    self.update()
            return

        if key == "ag":
            if _is_same_data(old_val, res):
                return
            if self.quota_panel is not None and hasattr(self.quota_panel, "set_data"):
                try:
                    self.quota_panel.set_data(res if isinstance(res, dict) else {})
                except Exception as exc:
                    sources.log_err("quota_panel_set_data", exc)
            r_ag = self._get_card_rect("ag")
            if r_ag is not None:
                self.update(r_ag.toRect().adjusted(-2, -2, 2, 2))
            else:
                self.update()
            return

        if key == "audio_sessions":
            if self.vol_popover and self.vol_popover.isVisible():
                self.vol_popover.update_sessions(res if isinstance(res, list) else [])
            return

        if key in ("bat", "batnet", "battop"):
            self._on_battery_data(key, res)
            return

        if key == "bright":
            if self.brightness_popover.is_open():
                self.brightness_popover.update_levels(res)
            if self.battery_panel.is_open():
                self._push_bat_panel_controls()
            if _is_same_data(old_val, res):
                return
            r_bright = self._get_card_rect("bright")
            if r_bright is not None:
                self.update(r_bright.toRect().adjusted(-2, -2, 2, 2))
            return

        if key == "media":
            if not isinstance(res, dict):
                return
            changed_visual = False
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
                if self.battery_panel.is_open():
                    self._push_bat_panel_controls()
                changed_visual = True

            np = res.get("np")
            old_np = self._now_playing_info

            def _track_sig(info):
                if not isinstance(info, dict):
                    return None
                return (
                    info.get("title"),
                    info.get("artist"),
                    info.get("app"),
                    bool(info.get("playing")),
                    info.get("duration_s"),
                )

            track_changed = (_track_sig(np) != _track_sig(old_np))
            self._now_playing_info = np
            t = getattr(self, "media_ring_timer", None)
            if t is not None and isinstance(np, dict) and np.get("playing") and not t.isActive():
                t.start()

            if track_changed:
                self.compute_layout_and_resize()
                self.update()
            elif changed_visual:
                r_vol = self._get_card_rect("vol")
                if r_vol is not None:
                    self.update(r_vol.toRect().adjusted(-2, -2, 2, 2))
                else:
                    self.update()
            return

        if key == "tray":
            if isinstance(res, dict) and "images" in res:
                items = res.get("items") or []
                images = res.get("images") or {}
                items_changed = (self._tray_items != list(items))
                self._tray_items = list(items)
                for name, img in images.items():
                    if img is not None and not img.isNull():
                        self._tray_icons[name] = QPixmap.fromImage(img)
            else:
                items = res if isinstance(res, list) else (res.get("items") or res.get("data") or [])
                items_changed = (self._tray_items != list(items))
                self._tray_items = list(items)
                self._sync_tray_icons()
            if self.tray_panel is not None and hasattr(self.tray_panel, "set_items"):
                try:
                    self.tray_panel.set_items(self._tray_items, self._tray_icons)
                except Exception as exc:
                    sources.log_err("tray_panel_set_items", exc)
            self.tray_popover.set_items(self._tray_items)
            if items_changed:
                self.update()
            return

        # Tween retargeting: only when value changed by >= 1 point (Requirement 6)
        card_changed = False
        card_to_update = None

        if key == "claude" and isinstance(res, dict):
            s = safe_float(res.get("session"), None)
            w = safe_float(res.get("week"), None)
            has_err = ("err" in res) or (s is None and w is None)
            self.anim_claude_op.retarget(0.45 if has_err else 1.0)
            if s is not None and abs(s - self.anim_claude_s.target_val) >= 1.0:
                self.anim_claude_s.retarget(s)
                card_changed = True
            if w is not None and abs(w - self.anim_claude_w.target_val) >= 1.0:
                self.anim_claude_w.retarget(w)
                card_changed = True
            card_to_update = "claude"
        elif key == "sys" and isinstance(res, dict):
            cpu = safe_float(res.get("cpu"), None)
            ram = safe_float(res.get("ram"), None)
            has_err = ("err" in res) or (cpu is None and ram is None)
            self.anim_sys_op.retarget(0.45 if has_err else 1.0)
            if cpu is not None and abs(cpu - self.anim_cpu.target_val) >= 1.0:
                self._ring_move(self.anim_cpu, cpu)
                card_changed = True
            if ram is not None and abs(ram - self.anim_ram.target_val) >= 1.0:
                self._ring_move(self.anim_ram, ram)
                card_changed = True
            card_to_update = "sys"
        elif key == "wx" and isinstance(res, dict):
            has_err = ("err" in res) or (res.get("temp") is None)
            self.anim_wx_op.retarget(0.45 if has_err else 1.0)
            if not _is_same_data(old_val, res):
                card_changed = True
                card_to_update = "clock"
        elif not _is_same_data(old_val, res):
            card_changed = True

        # Proactive alerts engine evaluation in normal mode (Requirement 5)
        if not self.preview_mode and self.alert_engine is not None and self.toast_mgr is not None:
            try:
                new_alerts = self.alert_engine.evaluate(self.store)
                for a in new_alerts:
                    self.toast_mgr.show(a)
            except Exception as exc:
                sources.log_err("alerts", exc)

        if not card_changed and _is_same_data(old_val, res):
            return

        if key in ("claude", "sys"):
            old_err = bool(isinstance(old_val, dict) and old_val.get("err"))
            curr_err = bool(isinstance(res, dict) and res.get("err"))
            if old_err == curr_err:
                if key == "sys" and not card_changed:
                    return  # halka değerleri değişmedi (<1 puan): ekranda görünen bir şey yok
                if not self.anim_driver.is_running():
                    r = self._get_card_rect(card_to_update)
                    if r is not None:
                        self.update(r.toRect().adjusted(-2, -2, 2, 2))
                    else:
                        self.update()
                return

        self.compute_layout_and_resize()
        self.update()

    def update_windows(self) -> None:
        """Y6 Protected window update: skips layout and repaint if list is unchanged."""
        raw_wins = winapi.list_windows()
        self._raw_windows = raw_wins  # pencere seçicisi başlık / küçültülmüş bilgisini buradan alır
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
        show_claude = cards_cfg.get("claude", True)
        show_mail = cards_cfg.get("mail", True)
        show_ag = cards_cfg.get("ag", True)
        show_sys = cards_cfg.get("sys", True)
        show_cal = cards_cfg.get("cal", True)

        has_media = bool(self._now_playing_info and self._now_playing_info.get("title"))

        mail_data = self.store.get("mail") or {}
        cal_data = self.store.get("cal") or {}

        w_mail = dock_cards.measure_mail_card_width(mail_data) if show_mail else 0.0
        w_ag = AG_CARD_WIDTH if show_ag else 0.0
        w_claude = CLAUDE_CARD_WIDTH if show_claude else 0.0
        w_cal = dock_cards.measure_calendar_card_width(cal_data) if show_cal else 0.0

        n_tiles = len(self.tiles)
        w_apps = (n_tiles * pinned.TILE_WIDTH + max(0, n_tiles - 1) * pinned.GAP) if n_tiles > 0 else 0.0

        now_dt = dt.datetime.now(sources.LOCAL_TZ)
        wx_entry = self.store.get("wx") or {}
        temp_val = safe_float(wx_entry.get("temp"), None)
        has_wx = (temp_val is not None)
        temp_str = f"{int(round(temp_val))}°" if has_wx else None
        w_clock = dock_cards.measure_clock_v1_width(now_dt, temp_str=temp_str, has_weather=has_wx)

        if self._is_band():
            scr = self.screen() or QGuiApplication.primaryScreen()
            sw = scr.geometry().width() if scr else 1536
            if self.width() != sw or self.height() != int(DOCK_HEIGHT):
                self.resize(sw, int(DOCK_HEIGHT))

            lw_items: List[float] = []
            if show_claude:
                lw_items.append(w_claude)
            if show_mail:
                lw_items.append(w_mail)
            if show_ag:
                lw_items.append(w_ag)
            if show_sys:
                lw_items.append(SYS_CARD_WIDTH)
            lw_w = (sum(lw_items) + max(0, len(lw_items) - 1) * GAP_MODULE) if lw_items else 0.0

            rw_items: List[float] = []
            if has_media:
                rw_items.append(MEDIA_CARD_WIDTH)
            if show_cal:
                rw_items.append(w_cal)
            rw_w = (sum(rw_items) + max(0, len(rw_items) - 1) * GAP_MODULE) if rw_items else 0.0

            gap_l = GAP_MODULE if (lw_w > 0 and w_apps > 0) else 0.0
            gap_r = GAP_MODULE if (rw_w > 0 and w_apps > 0) else 0.0
            total_center_w = int(math.ceil(lw_w + gap_l + w_apps + gap_r + rw_w))

            if initial or self.preview_mode or not self.isVisible() or self._content_w <= 0:
                self._content_w = float(total_center_w)
                self.dock_width_tween.value = float(total_center_w)
                self.dock_width_tween.target_val = float(total_center_w)
            elif total_center_w != int(round(self.dock_width_tween.target_val)):
                self.dock_width_tween.retarget(total_center_w)
            return

        # Pill style: One centered capsule in order Claude, Mail, Antigravity, Sistem (if enabled), apps, media, calendar, clock, chevron/sun/speaker
        items: List[float] = []
        if show_claude:
            items.append(w_claude)
        if show_mail:
            items.append(w_mail)
        if show_ag:
            items.append(w_ag)
        if show_sys:
            items.append(SYS_CARD_WIDTH)
        if w_apps > 0:
            items.append(w_apps)
        if has_media:
            items.append(MEDIA_CARD_WIDTH)
        if show_cal:
            items.append(w_cal)
        items.append(w_clock)
        items.append(self._actions_width())

        n_items = len(items)
        inner_gaps = max(0, n_items - 1) * GAP_MODULE
        total_w = int(math.ceil(6.0 * 2.0 + sum(items) + inner_gaps))

        if initial or self.preview_mode or not self.isVisible():
            self.resize(total_w, int(DOCK_HEIGHT))
            self.dock_width_tween.value = float(total_w)
            self.dock_width_tween.target_val = float(total_w)
        else:
            if total_w != int(round(self.dock_width_tween.target_val)):
                self.dock_width_tween.retarget(total_w)

    def paintEvent(self, event) -> None:
        """K1 Defensive painter: isolates paint errors and prevents process crashes."""
        global _LAST_PAINT_ERROR_LOG
        p = QPainter(self)
        try:
            exp_rect = event.rect() if event is not None else None
            self._paint_content(p, exp_rect)
        except Exception as exc:
            now = time.time()
            if now - _LAST_PAINT_ERROR_LOG > 60.0:
                _LAST_PAINT_ERROR_LOG = now
                sources.log_err("paintEvent", exc)
        finally:
            p.end()

    # Kart içeriğinin kart kenarına uzaklığı (sol, sağ): ayraç iki yandaki içeriğin tam ortasına konur.
    _CONTENT_INSET: Dict[str, Tuple[float, float]] = {
        "claude": (11.8, 10.0), "ag": (11.8, 10.0), "mail": (10.0, 10.0), "sys": (9.0, 9.0),
        "apps": (6.0, 6.0), "media": (6.0, 10.0), "cal": (12.0, 12.0),
    }

    @classmethod
    def _divider_x(cls, left_key: str, left_r: QRectF, right_key: str, right_r: QRectF) -> float:
        lin = cls._CONTENT_INSET.get(left_key, (10.0, 10.0))[1]
        rin = cls._CONTENT_INSET.get(right_key, (10.0, 10.0))[0]
        return ((left_r.right() - lin) + (right_r.left() + rin)) / 2.0

    @staticmethod
    def _draw_divider(p: QPainter, x: float, cy: float, intersects: Callable[[QRectF], bool]) -> None:
        """Bantta kartlar / gruplar arası ince ayraç (yalnız boyanan bölgeye düşüyorsa)."""
        if intersects(QRectF(x - 1.0, cy - dock_cards.CARD_DIVIDER_H / 2.0 - 1.0, 2.0,
                             dock_cards.CARD_DIVIDER_H + 2.0)):
            dock_cards.draw_card_divider(p, x, cy)

    def _left_open_sig(self) -> Tuple[bool, bool, bool, bool]:
        """Sol kanat kartlarının paneli açık mı: (Claude, Mail, Antigravity, Sistem)."""
        try:
            return (bool(self.popover.is_open("claude")),
                    bool(self.mail_panel is not None and self.mail_panel.is_open()),
                    bool(self.quota_panel is not None and self.quota_panel.is_open()),
                    bool(self.popover.is_open("sys")))
        except Exception:
            return (False, False, False, False)

    def _paint_content(self, p: QPainter, exposed_rect: Optional[Any] = None) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        card_y = CARD_Y  # 6.0
        card_h = CARD_HEIGHT  # 52.0

        exp_f: Optional[QRectF] = QRectF(exposed_rect) if exposed_rect is not None else None
        is_full = exp_f is None or (exp_f.x() <= 1.0 and exp_f.width() >= self.width() - 2.0)
        if is_full:
            self.hit_boxes.clear()

        def intersects(r: QRectF) -> bool:
            return True if exp_f is None else r.intersects(exp_f)

        cards_cfg = dict(self.settings.get("cards") or {})
        show_claude = cards_cfg.get("claude", True)
        show_mail = cards_cfg.get("mail", True)
        show_ag = cards_cfg.get("ag", True)
        show_sys = cards_cfg.get("sys", True)
        show_cal = cards_cfg.get("cal", True)

        has_media = bool(self._now_playing_info and self._now_playing_info.get("title"))

        mail_data = self.store.get("mail") or {}
        ag_data = self.store.get("ag") or {}
        cal_data = self.store.get("cal") or {}
        claude_entry = self.store.get("claude") or {}

        w_mail = dock_cards.measure_mail_card_width(mail_data) if show_mail else 0.0
        w_ag = AG_CARD_WIDTH if show_ag else 0.0
        w_claude = CLAUDE_CARD_WIDTH if show_claude else 0.0
        natural_cal_w = dock_cards.measure_calendar_card_width(cal_data) if show_cal else 0.0

        now_dt = dt.datetime.now(sources.LOCAL_TZ)
        wx_entry = self.store.get("wx") or {}
        temp_val = safe_float(wx_entry.get("temp"), None)
        has_wx = (temp_val is not None)
        temp_str = f"{int(round(temp_val))}°" if has_wx else None
        wx_icon = str(wx_entry.get("icon") or "cloud")
        w_clock = dock_cards.measure_clock_v1_width(now_dt, temp_str=temp_str, has_weather=has_wx)

        n_tiles = len(self.tiles)
        w_apps = (n_tiles * pinned.TILE_WIDTH + max(0, n_tiles - 1) * pinned.GAP) if n_tiles > 0 else 0.0

        if self._is_band():
            # Tam genişlik koyu şerit (köşesiz) + üstte ince ayırıcı çizgi
            if exp_f is None or exp_f.y() < DOCK_HEIGHT:
                p.fillRect(QRectF(0, 0, self.width(), DOCK_HEIGHT), QColor(13, 15, 19))
                p.fillRect(QRectF(0, 0, self.width(), 1.0), QColor(255, 255, 255, 18))

            # Sol alt köşe: masaüstünü göster / geri getir (ekran kenarında, fareyi köşeye atınca bulunur)
            r_desk = QRectF(0.0, 1.0, DESKTOP_STRIP_W, DOCK_HEIGHT - 1.0)
            if is_full:
                self.hit_boxes.append((r_desk, "desktop", None))
            if intersects(r_desk):
                if self._hover_key == "desktop":
                    alpha = 34 if self._pressed_key == "desktop" else 22
                    p.fillRect(r_desk, QColor(255, 255, 255, alpha))
                p.fillRect(QRectF(DESKTOP_STRIP_W, 14.0, 1.0, DOCK_HEIGHT - 28.0), QColor(255, 255, 255, 20))

            sw = float(self.width())
            apps_x = round(sw / 2.0 - w_apps / 2.0) if w_apps > 0 else round(sw / 2.0)

            # Left wing: Claude, Mail, Antigravity, Sistem
            # Sığmazsa önce Mail, sonra Claude + Antigravity birlikte (çift olarak) daralır.
            eff_mail_w = w_mail
            eff_claude_w = w_claude
            eff_ag_w = w_ag
            n_lw = int(show_claude) + int(show_mail) + int(show_ag) + int(show_sys)
            needed_space = (
                (w_claude if show_claude else 0.0)
                + (eff_mail_w if show_mail else 0.0)
                + (w_ag if show_ag else 0.0)
                + (SYS_CARD_WIDTH if show_sys else 0.0)
                + max(0, n_lw - 1) * GAP_MODULE
            )
            max_allowed_lw = apps_x - (GAP_MODULE if (w_apps > 0) else 0.0) - 10.0
            overflow = needed_space - max_allowed_lw
            if overflow > 0 and show_mail:
                can_shrink = max(0.0, eff_mail_w - dock_cards.MAIL_CARD_MIN_WIDTH)
                cut = min(overflow, can_shrink)
                eff_mail_w -= cut
                overflow -= cut
            n_pair = int(show_claude) + int(show_ag)
            if overflow > 0 and n_pair:
                per = min(overflow / n_pair, max(0.0, CLAUDE_CARD_WIDTH - dock_cards.CONC_CARD_MIN_WIDTH))
                if show_claude:
                    eff_claude_w -= per
                if show_ag:
                    eff_ag_w -= per

            lw_cards: List[Tuple[str, float]] = []
            if show_claude:
                lw_cards.append(("claude", eff_claude_w))
            if show_mail:
                lw_cards.append(("mail", eff_mail_w))
            if show_ag:
                lw_cards.append(("ag", eff_ag_w))
            if show_sys:
                lw_cards.append(("sys", SYS_CARD_WIDTH))

            lw_w = (sum(w for _, w in lw_cards) + max(0, len(lw_cards) - 1) * GAP_MODULE) if lw_cards else 0.0
            lw_end = apps_x - (GAP_MODULE if (lw_w > 0 and w_apps > 0) else 0.0)
            lw_start = lw_end - lw_w

            # Right end layout & clearance:
            # Order at right edge: [Right Wing: Media, Cal] ... [Actions: ^, Sun, Spk] [Gap] [Weather + Clock]
            # Clock right edge is pinned at sw - 14.0.
            # Actions left edge is: (sw - 14.0) - w_clock - GAP_MODULE - ACTION_BUTTONS_WIDTH
            media_w = MEDIA_CARD_WIDTH if has_media else 0.0
            cal_w = natural_cal_w
            center_shift = 0.0

            actions_left_x = (sw - 14.0) - w_clock - GAP_MODULE - self._actions_width()

            def calc_clearance(m_w: float, c_w: float, shift: float) -> float:
                rw_items = []
                if has_media:
                    rw_items.append(m_w)
                if show_cal:
                    rw_items.append(c_w)
                rw_w_calc = (sum(rw_items) + max(0, len(rw_items) - 1) * GAP_MODULE) if rw_items else 0.0
                rw_end_calc = (apps_x - shift) + w_apps + (GAP_MODULE if (rw_w_calc > 0 and w_apps > 0) else 0.0) + rw_w_calc
                return actions_left_x - rw_end_calc

            # Fitting algorithm:
            # (a) compact media card: 314 -> 240 px
            if has_media and calc_clearance(media_w, cal_w, center_shift) < 12.0:
                media_w = MEDIA_CARD_WIDTH_COMPACT

            # (b) calendar card max width shrinks with eliding down to 96 px
            if show_cal and calc_clearance(media_w, cal_w, center_shift) < 12.0:
                needed = 12.0 - calc_clearance(media_w, cal_w, center_shift)
                can_shrink = max(0.0, cal_w - 96.0)
                shrink_by = min(needed, can_shrink)
                cal_w -= shrink_by

            # (c) shift centre block left (min 10 px clearance from left screen edge)
            curr_clearance = calc_clearance(media_w, cal_w, center_shift)
            if curr_clearance < 12.0:
                needed = 12.0 - curr_clearance
                max_shift = max(0.0, lw_start - 10.0)
                center_shift = min(needed, max_shift)

            # v24 A yerleşimi: bilgi kartları sola (x=14.0), uygulamalar tam ortaya (apps_x),
            # medya kartı sağ kümenin soluna yaslanır ve sığdığı kadar genişler (maks 380 px).
            # Sığmazsa A iptal olur ve eski (ortalanmış küme) mantığa düşer.
            _use_A = True
            _left_x = 14.0
            _media_right = actions_left_x - 16.0 - ((cal_w + GAP_MODULE) if show_cal else 0.0)
            _avail_media = _media_right - (apps_x + w_apps + 40.0)
            if _left_x + lw_w > apps_x - 40.0 or (has_media and _avail_media < MEDIA_CARD_WIDTH_COMPACT):
                _use_A = False

            if _use_A:
                final_apps_x = apps_x
                cur_lw_x = _left_x
                if has_media:
                    media_w = max(MEDIA_CARD_WIDTH_COMPACT, min(380.0, _avail_media))
            else:
                final_apps_x = apps_x - center_shift
                cur_lw_x = final_apps_x - (GAP_MODULE if (lw_w > 0 and w_apps > 0) else 0.0) - lw_w

            # Left Wing panellerinin açık/kapalı durumu (açık kart altına zemin A)
            open_claude, open_mail, open_ag, open_sys = self._left_open_sig()

            div_cy = card_y + card_h / 2.0
            prev_card: Optional[Tuple[str, QRectF]] = None
            for card_key, card_w in lw_cards:
                r_card = QRectF(cur_lw_x, card_y, card_w, card_h)
                if prev_card is not None:  # v24 kutusuz kartlar: aralarında ince ayraç
                    self._draw_divider(p, self._divider_x(prev_card[0], prev_card[1], card_key, r_card),
                                       div_cy, intersects)
                prev_card = (card_key, r_card)
                if is_full:
                    self.hit_boxes.append((r_card, card_key, None))
                if intersects(r_card):
                    is_hover = (self._hover_key == card_key)
                    press_scale = self.press_tween.scale if (self._pressed_key == card_key) else 1.0
                    card_open = (open_claude if card_key == "claude" else
                                 (open_mail if card_key == "mail" else
                                  (open_ag if card_key == "ag" else open_sys)))

                    if card_open and not is_hover:  # açık panel kartı: kalıcı hafif zemin (A)
                        p.save()
                        p.setRenderHint(QPainter.Antialiasing)
                        p.fillPath(theme.rounded_path(r_card, CARD_RADIUS), QColor(255, 255, 255, 30))
                        p.restore()

                    if card_key == "claude":
                        dock_cards.draw_claude_card(p, r_card, claude_entry, hover=is_hover, press_scale=press_scale)
                    elif card_key == "mail":
                        dock_cards.draw_mail_card(p, r_card, mail_data, hover=is_hover, press_scale=press_scale)
                    elif card_key == "ag":
                        dock_cards.draw_ag_card(p, r_card, ag_data, hover=is_hover, press_scale=press_scale)
                    elif card_key == "sys":
                        sys_entry = self.store.get("sys") or {}
                        c_disp = None if self.preview_mode else self.anim_cpu.value
                        r_disp = None if self.preview_mode else self.anim_ram.value
                        dock_cards.draw_sys_card(
                            p,
                            r_card,
                            sys_entry,
                            hover=is_hover,
                            press_scale=press_scale,
                            cpu_disp=c_disp,
                            ram_disp=r_disp,
                            opacity=self.anim_sys_op.value,
                        )

                cur_lw_x += card_w + GAP_MODULE

            r_apps = QRectF(final_apps_x, card_y, w_apps, card_h)
            if prev_card is not None and w_apps > 0 and not _use_A:  # sol kanat | uygulamalar (eski düzen)
                self._draw_divider(p, self._divider_x(prev_card[0], prev_card[1], "apps", r_apps),
                                   div_cy, intersects)

            # Draw Apps Group
            hover_idx = self._preview_hover_idx if self._preview_hover_idx is not None else self._hover_app_idx
            scales_lifts = anim.HoverMagnifier.compute_for_index(n_tiles, hover_idx)
            self._tile_centers = []
            self._tile_rects = []
            tile_y = card_y + (card_h - pinned.TILE_HEIGHT) / 2.0

            for i, t in enumerate(self.tiles):
                tile_x = final_apps_x + i * (pinned.TILE_WIDTH + pinned.GAP)
                r_slot = QRectF(tile_x, tile_y, pinned.TILE_WIDTH, pinned.TILE_HEIGHT)
                self._tile_rects.append(r_slot)
                self._tile_centers.append(r_slot.center().x())

                app_key = f"app_{i}"
                if is_full:
                    self.hit_boxes.append((r_slot, app_key, t))

                if intersects(r_slot):
                    scale, lift = scales_lifts[i]
                    p_y = tile_y - lift
                    r_draw = QRectF(tile_x, p_y, pinned.TILE_WIDTH, pinned.TILE_HEIGHT)
                    pix = self._icon_cache.get(t.get("exe") or t.get("path") or "")
                    hover_t = 1.0 if (self._hover_app_idx == i) else 0.0
                    press_scale = self.press_tween.scale if (self._pressed_key == app_key) else 1.0

                    pinned.draw_tile(
                        p,
                        r_draw,
                        t,
                        pixmap=pix,
                        hover_t=hover_t,
                        press_scale=press_scale * scale,
                        dot_count=t.get("count"),
                        indicator_y=r_slot.bottom() - 4.0,
                        launch_phase=self._launch_phase(t),
                    )

            # Draw Right Wing: Media, Calendar
            cur_rw_x = final_apps_x + w_apps + (GAP_MODULE if (w_apps > 0) else 0.0)
            if _use_A and has_media:
                cur_rw_x = _media_right - media_w
            elif _use_A and show_cal:
                cur_rw_x = actions_left_x - 16.0 - cal_w
            if has_media:
                r_media = QRectF(cur_rw_x, card_y, media_w, card_h)
                self._media_rect = r_media
                if w_apps > 0:  # uygulamalar | medya
                    self._draw_divider(p, self._divider_x("apps", r_apps, "media", r_media), div_cy, intersects)
                if is_full:
                    self.hit_boxes.append((r_media, "media", self._now_playing_info))
                if intersects(r_media):
                    m_hover = (self._hover_key == "media")
                    m_press = self.press_tween.scale if (self._pressed_key == "media") else 1.0
                    m_ctrl_hover = getattr(self, "_hover_media_ctrl", None)
                    self._media_hit_rects = dock_cards.draw_media_card(
                        p, r_media, self._now_playing_info, hover=m_hover, press_scale=m_press, hovered_control=m_ctrl_hover
                    )
                cur_rw_x += media_w + GAP_MODULE

            if show_cal:
                r_cal = QRectF(cur_rw_x, card_y, cal_w, card_h)
                if has_media or w_apps > 0:
                    lk, lr = ("media", self._media_rect) if (has_media and self._media_rect is not None) \
                        else ("apps", r_apps)
                    self._draw_divider(p, self._divider_x(lk, lr, "cal", r_cal), div_cy, intersects)
                if is_full:
                    self.hit_boxes.append((r_cal, "cal", None))
                if intersects(r_cal):
                    cal_hover = (self._hover_key == "cal")
                    cal_press = self.press_tween.scale if (self._pressed_key == "cal") else 1.0
                    dock_cards.draw_calendar_card(p, r_cal, cal_data, hover=cal_hover, press_scale=cal_press)
                cur_rw_x += cal_w + GAP_MODULE

            if _use_A and (has_media or show_cal):  # A: sağ kanat | sağ küme ayracı
                _last_r = r_cal if show_cal else r_media
                _inset = self._CONTENT_INSET["cal" if show_cal else "media"][1]
                self._draw_divider(p, ((_last_r.right() - _inset) + (actions_left_x + 9.0)) / 2.0,
                                   div_cy, intersects)

            # Right end: Clock V1 at the far right edge, Action buttons to its left
            # Right edge padding: 14.0px (matching action buttons padding previously and left edge balance)
            r_clock_x = (sw - 14.0) - w_clock
            r_clock = QRectF(r_clock_x, card_y, w_clock, card_h)
            self._clock_rect = r_clock
            clk_hover = (self._hover_key == "clock")
            clk_press = self.press_tween.scale if (self._pressed_key == "clock") else 1.0

            if intersects(r_clock):
                r_clk, r_wx = dock_cards.draw_clock_v1(
                    p,
                    r_clock,
                    temp_str=temp_str,
                    hover=clk_hover,
                    press_scale=clk_press,
                    wx_icon=wx_icon,
                    has_weather=has_wx,
                    now=now_dt,
                )
            else:
                r_clk = r_clock
                r_wx = None

            if is_full:
                self.hit_boxes.append((r_clk, "clock", None))
                if r_wx is not None:
                    self.hit_boxes.append((r_wx, "wx", None))

            # Action buttons cluster: ^ chevron (30x30), and A4 Quick Settings Pill (74x32)
            actions_w = self._actions_width()
            actions_x = r_clock_x - GAP_MODULE - actions_w
            btn_y = card_y + (card_h - ACTION_BTN_SIZE) / 2.0
            pill_y = card_y + (card_h - ACTION_PILL_HEIGHT) / 2.0
            tray_open = bool(self.tray_panel.is_open()) if self.tray_panel else bool(self.tray_popover.isVisible())
            bright_open = bool(self.brightness_popover.is_open())
            vol_open = bool(self.vol_popover.isVisible())

            r_chv = QRectF(actions_x, btn_y, ACTION_BTN_SIZE, ACTION_BTN_SIZE)
            r_pill = QRectF(actions_x + ACTION_BTN_SIZE + ACTION_BTN_GAP, pill_y, self._pill_width(), ACTION_PILL_HEIGHT)

            if is_full:
                self.hit_boxes.append((r_chv, "tray", None))
            if intersects(r_chv):
                dock_cards.draw_action_button(p, r_chv, "tray", hover=(self._hover_key == "tray"), active=tray_open)

            if intersects(r_pill):
                self._draw_quick_pill(p, r_pill, bright_open, vol_open, register_hitboxes=is_full)
            elif is_full:
                self._register_quick_pill_hitboxes(r_pill, bright_open, vol_open)
        else:
            # Pill Style: One centered capsule in order Claude, Mail, Antigravity, apps, media, calendar, clock, chevron/sun/speaker
            r_dock = QRectF(0.5, 0.5, self.width() - 1.0, DOCK_HEIGHT - 1.0)
            if intersects(r_dock):
                theme.draw_glass_capsule(p, r_dock, radius=DOCK_RADIUS)

            x = 6.0  # inner padding 6px
            if show_claude:
                r_claude = QRectF(x, card_y, CLAUDE_CARD_WIDTH, card_h)
                if is_full:
                    self.hit_boxes.append((r_claude, "claude", None))
                if intersects(r_claude):
                    c_hover = (self._hover_key == "claude")
                    c_press = self.press_tween.scale if (self._pressed_key == "claude") else 1.0
                    dock_cards.draw_claude_card(p, r_claude, claude_entry, hover=c_hover, press_scale=c_press)
                x += CLAUDE_CARD_WIDTH + GAP_MODULE

            if show_mail:
                r_mail = QRectF(x, card_y, w_mail, card_h)
                if is_full:
                    self.hit_boxes.append((r_mail, "mail", None))
                if intersects(r_mail):
                    m_hover = (self._hover_key == "mail")
                    m_press = self.press_tween.scale if (self._pressed_key == "mail") else 1.0
                    dock_cards.draw_mail_card(p, r_mail, mail_data, hover=m_hover, press_scale=m_press)
                x += w_mail + GAP_MODULE

            if show_ag:
                r_ag = QRectF(x, card_y, w_ag, card_h)
                if is_full:
                    self.hit_boxes.append((r_ag, "ag", None))
                if intersects(r_ag):
                    ag_hover = (self._hover_key == "ag")
                    ag_press = self.press_tween.scale if (self._pressed_key == "ag") else 1.0
                    dock_cards.draw_ag_card(p, r_ag, ag_data, hover=ag_hover, press_scale=ag_press)
                x += w_ag + GAP_MODULE

            if show_sys:
                r_sys = QRectF(x, card_y, SYS_CARD_WIDTH, card_h)
                if is_full:
                    self.hit_boxes.append((r_sys, "sys", None))
                if intersects(r_sys):
                    s_hover = (self._hover_key == "sys")
                    s_press = self.press_tween.scale if (self._pressed_key == "sys") else 1.0
                    sys_entry = self.store.get("sys") or {}
                    c_disp = None if self.preview_mode else self.anim_cpu.value
                    r_disp = None if self.preview_mode else self.anim_ram.value
                    dock_cards.draw_sys_card(
                        p,
                        r_sys,
                        sys_entry,
                        hover=s_hover,
                        press_scale=s_press,
                        cpu_disp=c_disp,
                        ram_disp=r_disp,
                        opacity=self.anim_sys_op.value,
                    )
                x += SYS_CARD_WIDTH + GAP_MODULE

            # Apps Group
            hover_idx = self._preview_hover_idx if self._preview_hover_idx is not None else self._hover_app_idx
            scales_lifts = anim.HoverMagnifier.compute_for_index(n_tiles, hover_idx)
            self._tile_centers = []
            self._tile_rects = []
            tile_y = card_y + (card_h - pinned.TILE_HEIGHT) / 2.0

            for i, t in enumerate(self.tiles):
                tile_x = x + i * (pinned.TILE_WIDTH + pinned.GAP)
                r_slot = QRectF(tile_x, tile_y, pinned.TILE_WIDTH, pinned.TILE_HEIGHT)
                self._tile_rects.append(r_slot)
                self._tile_centers.append(r_slot.center().x())

                app_key = f"app_{i}"
                if is_full:
                    self.hit_boxes.append((r_slot, app_key, t))

                scale, lift_y = scales_lifts[i] if i < len(scales_lifts) else (1.0, 0.0)
                r_draw = QRectF(r_slot.x(), r_slot.y() + lift_y, r_slot.width(), r_slot.height())
                if intersects(r_slot) or intersects(r_draw):
                    is_h = (hover_idx == i)
                    hover_t = 1.0 if is_h else 0.0
                    press_scale = self.press_tween.scale if (self._pressed_key == app_key) else 1.0

                    pix = self.get_app_icon(t.get("exe", ""))
                    pinned.draw_tile(
                        p=p,
                        rect=r_draw,
                        tile=t,
                        pixmap=pix,
                        hover_t=hover_t,
                        press_scale=press_scale * scale,
                        dot_count=t.get("count"),
                        indicator_y=r_slot.bottom() - 4.0,
                        launch_phase=self._launch_phase(t),
                    )

            if n_tiles > 0:
                x += w_apps + GAP_MODULE

            if has_media:
                r_media = QRectF(x, card_y, MEDIA_CARD_WIDTH, card_h)
                if is_full:
                    self.hit_boxes.append((r_media, "media", self._now_playing_info))
                if intersects(r_media):
                    m_hover = (self._hover_key == "media")
                    m_press = self.press_tween.scale if (self._pressed_key == "media") else 1.0
                    m_ctrl_hover = getattr(self, "_hover_media_ctrl", None)
                    self._media_hit_rects = dock_cards.draw_media_card(
                        p, r_media, self._now_playing_info, hover=m_hover, press_scale=m_press, hovered_control=m_ctrl_hover
                    )
                x += MEDIA_CARD_WIDTH + GAP_MODULE

            if show_cal:
                r_cal = QRectF(x, card_y, natural_cal_w, card_h)
                if is_full:
                    self.hit_boxes.append((r_cal, "cal", None))
                if intersects(r_cal):
                    cal_hover = (self._hover_key == "cal")
                    cal_press = self.press_tween.scale if (self._pressed_key == "cal") else 1.0
                    dock_cards.draw_calendar_card(p, r_cal, cal_data, hover=cal_hover, press_scale=cal_press)
                x += natural_cal_w + GAP_MODULE

            # Clock Block
            r_clock = QRectF(x, card_y, w_clock, card_h)
            self._clock_rect = r_clock
            clk_hover = (self._hover_key == "clock")
            clk_press = self.press_tween.scale if (self._pressed_key == "clock") else 1.0

            if intersects(r_clock):
                r_clk, r_wx = dock_cards.draw_clock_v1(
                    p,
                    r_clock,
                    temp_str=temp_str,
                    hover=clk_hover,
                    press_scale=clk_press,
                    wx_icon=wx_icon,
                    has_weather=has_wx,
                    now=now_dt,
                )
            else:
                r_clk = r_clock
                r_wx = None

            if is_full:
                self.hit_boxes.append((r_clk, "clock", None))
                if r_wx is not None:
                    self.hit_boxes.append((r_wx, "wx", None))
            x += w_clock + GAP_MODULE

            # Action buttons cluster: ^ chevron (30x30), and A4 Quick Settings Pill (74x32)
            btn_y = card_y + (card_h - ACTION_BTN_SIZE) / 2.0
            pill_y = card_y + (card_h - ACTION_PILL_HEIGHT) / 2.0
            tray_open = bool(self.tray_panel.is_open()) if self.tray_panel else bool(self.tray_popover.isVisible())
            bright_open = bool(self.brightness_popover.is_open())
            vol_open = bool(self.vol_popover.isVisible())

            r_chv = QRectF(x, btn_y, ACTION_BTN_SIZE, ACTION_BTN_SIZE)
            r_pill = QRectF(x + ACTION_BTN_SIZE + ACTION_BTN_GAP, pill_y, self._pill_width(), ACTION_PILL_HEIGHT)

            if is_full:
                self.hit_boxes.append((r_chv, "tray", None))
            if intersects(r_chv):
                dock_cards.draw_action_button(p, r_chv, "tray", hover=(self._hover_key == "tray"), active=tray_open)

            if intersects(r_pill):
                self._draw_quick_pill(p, r_pill, bright_open, vol_open, register_hitboxes=is_full)
            elif is_full:
                self._register_quick_pill_hitboxes(r_pill, bright_open, vol_open)

    def mousePressEvent(self, event) -> None:
        self._hide_hover_preview(force=True)
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
        new_tray_item = None
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
                elif key == "tray_icon":
                    new_tray_item = extra
                tooltip_text = self.get_tooltip_text(key, extra)
                break

        self._hover_media_ctrl = new_media_ctrl

        hover_changed = (
            new_hover != self._hover_key
            or new_app_idx != self._hover_app_idx
            or new_tray_item != self._hover_tray_item
        )
        if hover_changed:
            self._hover_key = new_hover
            self._hover_app_idx = new_app_idx
            self._hover_tray_item = new_tray_item
            self.update()
            self._on_tile_hover(new_app_idx)
            hp_open = self.hover_preview is not None and self.hover_preview.is_open()

            # Show floating label bubble above hovered tile in normal mode
            if new_app_idx is not None and new_app_idx < len(self.tiles) and not self.preview_mode and not hp_open:
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
            elif new_hover == "bright":
                self.submit_fetch("bright")

        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.preview_mode:
            self.bubble.hide()
        self._on_tile_hover(None)
        if (
            self._hover_key is not None
            or self._hover_app_idx is not None
            or self._hover_tray_item is not None
        ):
            self._hover_key = None
            self._hover_app_idx = None
            self._hover_tray_item = None
            self.setToolTip("")
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton:
            pos = event.position()
            for r, key, extra in reversed(self.hit_boxes):
                if r.contains(pos):
                    if key.startswith("app_") and isinstance(extra, dict):
                        self.handle_tile_middle_click(extra, r)
                    break
            event.accept()
            return
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
                for r, key, extra in reversed(self.hit_boxes):
                    if r.contains(pos):
                        self.handle_click(key, extra, r, pos)
                        break
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        pos = event.position()
        for r, key, _extra in reversed(self.hit_boxes):
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
            elif key == "bright" and r.contains(pos):
                diff = 5 if event.angleDelta().y() > 0 else -5
                monitors = self._get_store_monitors()
                updated = False
                for m in monitors:
                    if isinstance(m, dict) and m.get("ok", True):
                        cur_lvl = m.get("level")
                        if cur_lvl is not None:
                            new_lvl = max(0, min(100, int(cur_lvl) + diff))
                            m["level"] = new_lvl
                            updated = True
                            if not self.preview_mode:
                                self._on_brightness_requested(str(m.get("id")), new_lvl)
                if updated:
                    self.store.update("bright", monitors)
                    if self.brightness_popover.is_open():
                        self.brightness_popover.update_levels(monitors)
                    self.update()
                break
        super().wheelEvent(event)

    def handle_click(self, key: str, extra: Any, rect: QRectF, pos: Optional[QPointF] = None) -> None:
        if key == "desktop":
            if not self.preview_mode:
                winapi.toggle_desktop()
            return
        if key == "tray_icon" and extra:
            if not self.preview_mode:
                trayicons.activate(extra, button="left")
        elif key.startswith("app_") and extra:
            self.handle_tile_click(extra, rect)
        elif key in ("bright", "vol", "bat"):
            self._handle_pill_click(key, rect)
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
                    self.submit_action(
                        "media_ctl",
                        lambda a=action: media.media_control(a),
                        on_done=lambda: QTimer.singleShot(350, lambda: self.submit_fetch("media")),
                    )
        elif key == "tray":
            if self.preview_mode:
                pass
            elif self.tray_panel is not None and hasattr(self.tray_panel, "show_for"):
                is_open = getattr(self.tray_panel, "is_open", None)
                recently_closed = getattr(self.tray_panel, "recently_closed", None)
                hide_animated = getattr(self.tray_panel, "hide_animated", None)
                if is_open and is_open():
                    if hide_animated:
                        hide_animated()
                    else:
                        self.tray_panel.hide()
                elif recently_closed and recently_closed():
                    pass
                else:
                    anchor_global = QRectF(
                        self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                        rect.size(),
                    )
                    self.tray_panel.show_for(anchor_global)
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
        elif key == "mail":
            if self.mail_panel is not None and hasattr(self.mail_panel, "show_for"):
                is_open = getattr(self.mail_panel, "is_open", None)
                recently_closed = getattr(self.mail_panel, "recently_closed", None)
                hide_animated = getattr(self.mail_panel, "hide_animated", None)
                if is_open and is_open():
                    if hide_animated:
                        hide_animated()
                    else:
                        self.mail_panel.hide()
                elif recently_closed and recently_closed():
                    pass
                else:
                    anchor_global = QRectF(
                        self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                        rect.size(),
                    )
                    mail_data = dict(self.store.get("mail") or {})
                    try:
                        self.mail_panel.show_for(anchor_global)
                    except TypeError:
                        self.mail_panel.show_for(anchor_global, mail_data)
                    except Exception as exc:
                        sources.log_err("mail_panel_show", exc)
        elif key == "ag":
            if self.quota_panel is not None and hasattr(self.quota_panel, "show_for"):
                is_open = getattr(self.quota_panel, "is_open", None)
                recently_closed = getattr(self.quota_panel, "recently_closed", None)
                hide_animated = getattr(self.quota_panel, "hide_animated", None)
                if is_open and is_open():
                    if hide_animated:
                        hide_animated()
                    else:
                        self.quota_panel.hide()
                elif recently_closed and recently_closed():
                    pass
                else:
                    anchor_global = QRectF(
                        self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))),
                        rect.size(),
                    )
                    ag_data = dict(self.store.get("ag") or {})
                    try:
                        self.quota_panel.show_for(anchor_global)
                    except TypeError:
                        self.quota_panel.show_for(anchor_global, ag_data)
                    except Exception as exc:
                        sources.log_err("quota_panel_show", exc)

    def _on_tray_panel_item_activated(self, item: dict, btn: str) -> None:
        if btn == "right":
            anchor_global = None
            if self.tray_panel is not None and hasattr(self.tray_panel, "item_anchor_global"):
                try:
                    anchor_global = self.tray_panel.item_anchor_global(item)  # v22 ızgara hücresi
                except Exception as exc:
                    sources.log_err("tray_item_anchor", exc)
                    anchor_global = None
            if anchor_global is None:
                anchor_global = QRectF(self.geometry())
            self._start_tray_end_task_flow(item, anchor_global)
        else:
            if not self.preview_mode:
                trayicons.activate(item, button="left")

    def _start_tray_end_task_flow(self, item: dict, anchor_global: QRectF) -> None:
        try:
            import tray_actions
            import action_menu
            _ = action_menu
        except ImportError:
            if not self.preview_mode:
                trayicons.activate(item, button="right")
            return

        if self.action_menu is None:
            if not self.preview_mode:
                trayicons.activate(item, button="right")
            return

        if self._action_in_flight:
            return

        self._action_in_flight = True
        self._action_menu_item = item

        def _resolve_worker() -> None:
            res: dict = {}
            try:
                res = tray_actions.resolve_processes(item)
            except Exception as exc:
                sources.log_err("tray_resolve_processes", exc)
                res = {"ok": False, "reason": str(exc)}
            self.dispatcher.tray_resolved.emit(item, res, anchor_global)

        if not sources.submit("tray_resolve", _resolve_worker):
            # worker could not be queued: do not leave the menu flag stuck forever
            self._action_in_flight = False
            self._action_menu_item = None

    def _on_tray_resolved(self, item: dict, res: dict, anchor_global: QRectF) -> None:
        self._action_in_flight = False
        if self.action_menu is None:
            return

        name = ""
        try:
            import tray_panel
            name = tray_panel.clean_tray_name(item)
        except Exception:
            name = clean_tray_name(item)

        sub = res.get("label") or res.get("reason") or ""
        pm = self._tray_icons.get(item.get("name", ""))

        actions = [
            {"id": "open", "text": "Aç", "icon": "open"},
            {
                "id": "end",
                "text": "Görevi sonlandır",
                "icon": "stop",
                "danger": True,
                "confirm": True,
                "enabled": bool(res.get("ok")),
                "hint": res.get("reason") or "",
            },
        ]

        try:
            self.action_menu.set_header(name, sub, pm)
            self.action_menu.set_actions(actions)
            self.action_menu.show_at(anchor_global)
        except Exception as exc:
            sources.log_err("action_menu_show", exc)

    def _on_action_chosen(self, action_id: str) -> None:
        item = getattr(self, "_action_menu_item", None)
        if not item:
            return

        if action_id == "open":
            try:
                import tray_actions
                if hasattr(tray_actions, "open_item"):
                    tray_actions.open_item(item)
                else:
                    if not self.preview_mode:
                        trayicons.activate(item, "left")
            except Exception:
                if not self.preview_mode:
                    trayicons.activate(item, "left")
        elif action_id == "end":
            try:
                import tray_actions
                if hasattr(tray_actions, "end_task"):
                    def _end_worker() -> None:
                        res = tray_actions.end_task(item)
                        self.dispatcher.end_task_done.emit(item, res)

                    sources.submit("tray_end_task", _end_worker)
            except Exception as exc:
                sources.log_err("tray_end_task", exc)
            QTimer.singleShot(800, lambda: self.submit_fetch("tray"))
            QTimer.singleShot(3000, lambda: self.submit_fetch("tray"))

    def _on_end_task_done(self, item: dict, res: dict) -> None:
        """GUI thread: tell the user when 'Görevi sonlandır' did not work (it used to fail silently)."""
        if not isinstance(res, dict) or res.get("ok", True):
            return
        mgr = getattr(self, "toast_mgr", None)
        if mgr is None:
            return
        try:
            import tray_panel
            name = tray_panel.clean_tray_name(item)
        except Exception:
            name = clean_tray_name(item)
        reason = str(res.get("reason") or "Görev sonlandırılamadı")
        try:
            mgr.show(
                alerts.Alert(
                    id=f"tray_end:{name}:{int(time.time())}",
                    title=f"{name or 'Uygulama'} kapatılamadı",
                    body=reason,
                    accent="#FF6E6E",
                    kind="tray",
                )
            )
        except Exception as exc:
            sources.log_err("tray_end_toast", exc)

    # ------------------------------------------------------- pencere seçicisi
    def _picker_windows(self, hwnds: List[int]) -> List[Dict[str, Any]]:
        by_hwnd = {int(w.get("hwnd") or 0): w for w in (getattr(self, "_raw_windows", None) or [])}
        out: List[Dict[str, Any]] = []
        for h in hwnds:
            w = by_hwnd.get(int(h or 0))
            if w is None:
                continue
            out.append({
                "hwnd": int(h),
                "title": str(w.get("title") or ""),
                "minimized": bool(w.get("minimized")),
                "active": bool(w.get("active")),
            })
        return out

    def _ensure_window_picker(self):
        if getattr(self, "window_picker", None) is None:
            try:
                import window_picker
                self.window_picker = window_picker.WindowPicker()
                self.window_picker.window_chosen.connect(self._on_picker_chosen)
                self.window_picker.close_requested.connect(self._on_picker_close_requested)
            except Exception as exc:
                sources.log_err("window_picker_init", exc)
                self.window_picker = None
        return self.window_picker

    def _open_window_picker(self, tile: dict, rect: QRectF) -> bool:
        picker = self._ensure_window_picker()
        if picker is None:
            return False
        exe = str(tile.get("exe") or "")
        if picker.is_open() and getattr(self, "_picker_exe", None) == exe:
            picker.hide_animated()
            return True
        if picker.recently_closed() and getattr(self, "_picker_exe", None) == exe:
            return True  # aynı tık pencereyi kapattı; hemen yeniden açma
        wins = self._picker_windows(list(tile.get("hwnds") or []))
        if len(wins) < 2:
            return False
        self._picker_exe = exe
        anchor_global = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())
        cached = self._cached_thumbs(exe, [w["hwnd"] for w in wins])
        try:
            if cached:
                picker.show_for(anchor_global, str(tile.get("name") or ""), self._icon_cache.get(exe), wins,
                                thumbs=cached)
            else:
                picker.show_for(anchor_global, str(tile.get("name") or ""), self._icon_cache.get(exe), wins)
        except Exception as exc:
            sources.log_err("window_picker_show", exc)
            return False
        self._request_picker_thumbs(exe, [w["hwnd"] for w in wins if not w.get("minimized")])
        return True

    # ------------------------------------------------------- tam ekranda gizlen
    def _check_fullscreen(self) -> None:
        """Öndeki pencere barın ekranını tamamen kaplıyorsa barı gizler, çıkınca geri getirir."""
        open_sig = self._left_open_sig()  # panel kapanınca açık-kart zemini kalmasın (saniyede bir, ucuz)
        if open_sig != getattr(self, "_last_open_sig", None):
            self._last_open_sig = open_sig
            self.update()
        if self.preview_mode or not bool(self.settings.get("hide_on_fullscreen", True)):
            fs = False
        else:
            fs = bool(winapi.foreground_fullscreen(os.getpid(), int(self.winId() or 0)))
        if fs == self._fs_hidden:
            return
        self._fs_hidden = fs
        if fs:
            self.bubble.hide()
            self._hide_hover_preview(force=True)
            self.hide()
        else:
            self.show()
            self.update()

    def _request_picker_thumbs(self, exe: str, hwnds: List[int]) -> None:
        """Önizlemeleri arka planda alır (GUI donmaz); liste açılınca yerlerine oturur. Diske yazılmaz."""
        if self.preview_mode or not hwnds:
            return

        def _worker() -> None:
            out = {}
            for h in hwnds[:12]:
                img = winapi.window_thumbnail(int(h))
                if img is not None:
                    out[int(h)] = img
            self.dispatcher.thumbs_ready.emit(exe, out)

        sources.submit(f"picker_thumbs:{exe.lower()}", _worker)

    def _on_picker_thumbs(self, exe: Any, thumbs: Any) -> None:
        if isinstance(exe, str) and isinstance(thumbs, dict) and thumbs:
            now = time.monotonic()
            self._thumb_cache = {k: v for k, v in self._thumb_cache.items() if now - v[0] < 10.0}
            merged = dict(self._thumb_cache.get(exe, (now, {}))[1])
            merged.update(thumbs)
            self._thumb_cache[exe] = (now, merged)
        picker = getattr(self, "window_picker", None)
        if picker is not None and picker.is_open() and exe == getattr(self, "_picker_exe", None):
            try:
                picker.set_thumbnails(thumbs)
            except Exception as exc:
                sources.log_err("window_picker_thumbs", exc)
        hp = getattr(self, "hover_preview", None)
        if hp is not None and hp.current_app() == exe:
            try:
                hp.set_thumbnails(thumbs)
            except Exception as exc:
                sources.log_err("hover_preview_thumbs", exc)

    def _cached_thumbs(self, exe: str, hwnds: List[int]) -> Dict[int, Any]:
        """Son 5 sn içinde alınmış önizlemeler (önizlemeden seçiciye geçerken boş kutu görünmesin)."""
        entry = self._thumb_cache.get(exe)
        if not entry or time.monotonic() - entry[0] > 5.0:
            return {}
        want = {int(h) for h in hwnds}
        return {h: img for h, img in entry[1].items() if h in want}

    # ------------------------------------------------ üzerine gelince önizleme
    def _ensure_hover_preview(self):
        if self.hover_preview is None:
            try:
                import hover_preview
                hp = hover_preview.HoverPreview()
                hp.window_chosen.connect(self._on_picker_chosen)
                hp.close_requested.connect(self._on_preview_close_requested)
                hp.more_requested.connect(self._on_preview_more)
                hp.hover_entered.connect(self._hover_hide_timer.stop)
                hp.hover_left.connect(self._schedule_preview_hide)
                self.hover_preview = hp
            except Exception as exc:
                sources.log_err("hover_preview_init", exc)
                self.hover_preview = None
        return self.hover_preview

    def _on_tile_hover(self, idx: Optional[int]) -> None:
        """Fare bir kütüğe geldi / ayrıldı. Çalışan kütükte bekleyince önizleme açılır."""
        tile = self.tiles[idx] if idx is not None and 0 <= idx < len(self.tiles) else None
        ok = (
            tile is not None
            and bool(tile.get("running"))
            and bool(tile.get("hwnds"))
            and bool(self.settings.get("hover_preview", True))
            and not getattr(self, "_drag_tile_active", False)
        )
        hp = self.hover_preview
        if not ok:
            self._hover_open_timer.stop()
            self._hover_tile_idx = None
            if hp is not None and hp.is_open():
                self._schedule_preview_hide()
            return
        self._hover_hide_timer.stop()
        self._hover_tile_idx = idx
        if hp is not None and hp.is_open():
            self._open_hover_preview()  # açıkken başka kütüğe geçiş: bekletmeden
        else:
            self._hover_open_timer.start(HOVER_OPEN_MS)

    def _open_hover_preview(self) -> None:
        idx = self._hover_tile_idx
        if idx is None or idx >= len(self.tiles) or idx >= len(self._tile_rects):
            return
        if self._hover_app_idx != idx:  # fare çoktan ayrıldı
            return
        picker = getattr(self, "window_picker", None)
        if picker is not None and picker.is_open():
            return
        tile = self.tiles[idx]
        exe = str(tile.get("exe") or "")
        wins = self._picker_windows(list(tile.get("hwnds") or []))
        if not wins:
            return
        hp = self._ensure_hover_preview()
        if hp is None:
            return
        rect = self._tile_rects[idx]
        anchor = QRectF(self.mapToGlobal(QPoint(int(rect.x()), int(rect.y()))), rect.size())
        if not self.preview_mode:
            self.bubble.hide()
        try:
            hp.show_for(anchor, exe, str(tile.get("name") or ""), self._icon_cache.get(exe), wins,
                        self._cached_thumbs(exe, [w["hwnd"] for w in wins]))
        except Exception as exc:
            sources.log_err("hover_preview_show", exc)
            return
        self._hover_tile_exe = exe
        self._request_picker_thumbs(exe, [w["hwnd"] for w in wins[:4] if not w.get("minimized")])
        self._hover_refresh_timer.start()

    def _schedule_preview_hide(self) -> None:
        self._hover_open_timer.stop()
        hp = self.hover_preview
        if hp is not None and hp.is_open():
            self._hover_hide_timer.start(HOVER_HIDE_MS)

    def _hide_hover_preview(self, force: bool = False) -> None:
        self._hover_open_timer.stop()
        self._hover_hide_timer.stop()
        hp = self.hover_preview
        if hp is None or not hp.isVisible():
            self._hover_refresh_timer.stop()
            return
        if not force:
            if hp.underMouse():
                return  # fare önizlemenin üstünde
            if self._hover_tile_idx is not None and self._hover_app_idx == self._hover_tile_idx:
                return  # fare hâlâ çalışan bir kütükte
        if force:
            hp.hide_instant()
        else:
            hp.hide_animated()
        self._hover_refresh_timer.stop()
        self._hover_tile_exe = None

    def _refresh_hover_preview(self) -> None:
        """Önizleme açıkken pencere listesi ve görüntüler 1,5 sn'de bir tazelenir."""
        hp = self.hover_preview
        if hp is None or not hp.is_open():
            self._hover_refresh_timer.stop()
            return
        exe = self._hover_tile_exe
        tile = next((t for t in self.tiles if str(t.get("exe") or "") == exe), None)
        wins = self._picker_windows(list((tile or {}).get("hwnds") or []))
        if not wins:
            self._hide_hover_preview(force=False if hp.underMouse() else True)
            if hp.isVisible():
                hp.hide_animated()
            return
        hp.set_windows(wins)
        self._request_picker_thumbs(str(exe), [w["hwnd"] for w in wins[:4] if not w.get("minimized")])

    def _on_preview_close_requested(self, hwnd: int) -> None:
        if not self.preview_mode:
            winapi.close_window(int(hwnd))

        def _after() -> None:
            self.update_windows()
            self._refresh_hover_preview()

        QTimer.singleShot(600, _after)

    def _on_preview_more(self) -> None:
        """Önizlemede '+N': tam pencere listesini (seçici) açar."""
        exe = self._hover_tile_exe
        idx = next((i for i, t in enumerate(self.tiles) if str(t.get("exe") or "") == exe), None)
        self._hide_hover_preview(force=True)
        if idx is not None and idx < len(self._tile_rects):
            self._open_window_picker(self.tiles[idx], self._tile_rects[idx])

    def _on_picker_chosen(self, hwnd: int) -> None:
        if not self.preview_mode:
            winapi.activate_window(int(hwnd))
        QTimer.singleShot(250, self.update_windows)

    def _on_picker_close_requested(self, hwnd: int) -> None:
        if not self.preview_mode:
            winapi.close_window(int(hwnd))

        def _refresh() -> None:
            self.update_windows()
            picker = getattr(self, "window_picker", None)
            if picker is None or not picker.is_open():
                return
            tile = next((t for t in self.tiles if str(t.get("exe") or "") == getattr(self, "_picker_exe", None)), None)
            picker.set_windows(self._picker_windows(list((tile or {}).get("hwnds") or [])))

        QTimer.singleShot(600, _refresh)

    def handle_tile_click(self, tile: dict, rect: Optional[QRectF] = None) -> None:
        self._hide_hover_preview(force=True)
        if tile.get("running"):
            hwnds = tile.get("hwnds", [])
            if not hwnds:
                return
            exe = tile.get("exe", "")
            if len(hwnds) == 1:
                if not self.preview_mode:
                    winapi.activate_or_minimize(hwnds[0])
            elif rect is not None and self._open_window_picker(tile, rect):
                return
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
                self._launch_tile(tile, path, rect)

    def handle_tile_middle_click(self, tile: dict, rect: Optional[QRectF] = None) -> None:
        """Orta tık: açık uygulamada yeni pencere, kapalıysa normal tık gibi açar."""
        self._hide_hover_preview(force=True)
        if not tile.get("running"):
            self.handle_tile_click(tile, rect)
            return
        path = str(tile.get("path") or tile.get("exe") or "")
        if not path or self.preview_mode:
            return
        if not Path(path).is_file():
            self._show_fail_bubble(rect, f"{tile.get('name') or 'Uygulama'}: yeni pencere açılamadı")
            return
        self.app_new_window(path)

    LAUNCH_TIMEOUT_S: float = 10.0

    def _launch_tile(self, tile: dict, path: str, rect: Optional[QRectF] = None) -> bool:
        """Uygulamayı açar; açılırken ikon soluk + nabız noktası, açılamazsa ikonun üstünde 4 sn balon."""
        name = str(tile.get("name") or Path(path).stem or "Uygulama")
        if not Path(path).exists():
            self._show_fail_bubble(rect, f"{name} açılamadı · dosya bulunamadı")
            sources.log_err("launch", FileNotFoundError(Path(path).name))
            return False
        try:
            ok = bool(pinned.launch(path))
        except Exception as exc:
            sources.log_err("launch", exc)
            ok = False
        if not ok:
            self._show_fail_bubble(rect, f"{name} açılamadı")
            sources.log_err("launch", RuntimeError(f"{Path(path).name} başlatılamadı"))
            return False
        key = str(tile.get("key") or pinned._norm_key(path))
        self._launching[key] = time.monotonic()
        try:
            self._launch_static = bool(anim.get_system_reduce_motion())
        except Exception:
            self._launch_static = False
        if not self._launch_timer.isActive():
            self._launch_timer.start()
        self.update()
        QTimer.singleShot(500, self.update_windows)
        return True

    def _launch_phase(self, tile: dict) -> Optional[float]:
        """Açılmakta olan (henüz penceresi gelmemiş) döşeme için nokta parlaklığı 0.30-0.95, yoksa None."""
        if not self._launching or tile.get("running"):
            return None
        t0 = self._launching.get(str(tile.get("key") or ""))
        if t0 is None:
            return None
        if self._launch_static:
            return 0.85
        return 0.30 + 0.65 * (0.5 + 0.5 * math.cos((time.monotonic() - t0) * 2.0 * math.pi / 1.1))

    def _tick_launching(self) -> None:
        now = time.monotonic()
        running = {str(t.get("key")) for t in self.tiles if t.get("running")}
        for k, t0 in list(self._launching.items()):
            if k in running or now - t0 > self.LAUNCH_TIMEOUT_S:
                del self._launching[k]
        if not self._launching:
            self._launch_timer.stop()
        self.update()

    def _show_fail_bubble(self, rect: Optional[QRectF], text: str) -> None:
        self._last_fail_text = text
        if self.preview_mode:
            return
        try:
            if rect is not None:
                pt = self.mapToGlobal(QPoint(int(round(rect.center().x())), int(round(rect.top()))))
            else:
                pt = self.mapToGlobal(QPoint(self.width() // 2, 0))
            self.bubble.hide()
            self.fail_bubble.show_bubble(QPointF(float(pt.x()), float(pt.y())), text)
            self._fail_bubble_timer.start(4000)
        except Exception as exc:
            sources.log_err("fail_bubble", exc)

    def get_tooltip_text(self, key: str, extra: Any) -> str:
        now_dt = dt.datetime.now(sources.LOCAL_TZ)
        if key == "desktop":
            return "Masaüstünü göster · tekrar tıkla: pencereler geri gelir"
        if key == "bat":
            return battery_panel.pill_tooltip(self._bat_info) or ""
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
        elif key == "mail":
            m = self.store.get("mail") or {}
            scanned_at = m.get("scanned_at")
            t_str = ""
            if scanned_at:
                try:
                    clean_ts = str(scanned_at).replace("Z", "+00:00")
                    s_dt = dt.datetime.fromisoformat(clean_ts)
                    t_str = s_dt.astimezone(sources.LOCAL_TZ).strftime("%H:%M")
                except Exception:
                    t_str = str(scanned_at)
            if not t_str:
                t_str = now_dt.strftime("%H:%M")
            return f"Yanıt bekleyen mailler · Hermes taraması {t_str}"
        elif key == "ag":
            ag = self.store.get("ag") or {}
            if ag.get("err"):
                return "Antigravity okunamadı"
            groups = ag.get("groups") or []
            if not groups:
                return "Antigravity okunamadı"
            lines = []
            for g in groups:
                lbl = g.get("label", "")
                used_val = safe_float(g.get("used"), None)
                used_str = f"%{int(round(used_val))}" if used_val is not None else "—"
                rst = g.get("reset_tr") or "—"
                lines.append(f"{lbl}: {used_str} · yenilenme {rst}")
            return "\n".join(lines)
        elif key == "sys":
            s = self.store.get("sys") or {}
            c_val = safe_float(s.get("cpu"), None)
            r_val = safe_float(s.get("ram"), None)
            r_used = safe_float(s.get("ram_used_gb"), None)
            r_tot = safe_float(s.get("ram_total_gb"), None)
            if c_val is None and r_val is None:
                return "Sistem: Veri yok · psutil"
            c_str = f"%{int(round(c_val))}" if c_val is not None else "–"
            r_str = f"%{int(round(r_val))}" if r_val is not None else "–"
            tip = f"İşlemci {c_str} · Bellek {r_str}"
            if r_used is not None and r_tot is not None and r_tot > 0:
                u_str = f"{r_used:.1f}".replace(".", ",")
                t_str = f"{r_tot:.1f}".replace(".", ",")
                tip += f" · {u_str} / {t_str} GB"
            tip += " · psutil"
            return tip
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
        elif key == "tray_icon" and extra:
            return clean_tray_name(extra)
        elif key == "bright":
            monitors = self._get_store_monitors()
            parts = ["Parlaklık"]
            for m in monitors:
                if isinstance(m, dict) and m.get("ok", True):
                    name = m.get("name") or "Ekran"
                    lvl = m.get("level")
                    lvl_str = f"%{lvl}" if lvl is not None else "—"
                    parts.append(f"{name} {lvl_str}")
            if len(parts) == 1:
                return "Parlaklık"
            return " · ".join(parts)
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

    def build_app_tile_menu_actions(self, extra: dict) -> List[Dict[str, Any]]:
        is_pinned = bool(extra.get("pinned"))
        if is_pinned:
            def do_unpin():
                self.pins = pinned.unpin(self.pins, extra.get("exe") or extra.get("key"))
                if not self.preview_mode:
                    self.settings["pinned"] = self.pins
                    save_settings(self.settings)
                self.update_windows()
            actions: List[Dict[str, Any]] = [{"id": "unpin", "text": "Sabitlemeyi kaldır", "callback": do_unpin}]
        else:
            def do_pin():
                self.pins = pinned.pin(self.pins, extra)
                if not self.preview_mode:
                    self.settings["pinned"] = self.pins
                    save_settings(self.settings)
                self.update_windows()
            actions = [{"id": "pin", "text": "Sabitle", "callback": do_pin}]

        exe = str(extra.get("exe") or "")
        if extra.get("running") and exe:
            def do_end_task():
                self.end_app_task(extra)

            # v24 (Emre): Windows görev çubuğundaki gibi yeni pencere + pencereleri kapat
            hwnds = [int(h) for h in (extra.get("hwnds") or []) if h]
            launch_path = str(extra.get("path") or exe)
            if launch_path and Path(launch_path).is_file():
                actions.insert(0, {"id": "new_window", "text": "Yeni pencere", "icon": "open", "shortcut": "Orta tık",
                                   "callback": lambda: self.app_new_window(launch_path)})
            if hwnds:
                close_txt = f"Tüm pencereleri kapat ({len(hwnds)})" if len(hwnds) > 1 else "Pencereyi kapat"
                actions.append({"type": "separator"})
                actions.append({"id": "close_all", "text": close_txt,
                                "callback": lambda: self.app_close_windows(hwnds)})
            else:
                actions.append({"type": "separator"})
            actions.append({
                "id": "end_task",
                "text": "Görevi sonlandır",
                "icon": "stop",
                "danger": True,
                "confirm": True,
                "callback": do_end_task,
            })
        return actions

    def app_new_window(self, path: str) -> None:
        """Uygulama döşemesi > Yeni pencere: exe'yi yeniden başlatır (Chrome vb. yeni pencere açar)."""
        if not path or self.preview_mode:
            return
        try:
            if not pinned.launch(path):
                sources.log_err("app_new_window", RuntimeError("başlatılamadı"))
        except Exception as exc:
            sources.log_err("app_new_window", exc)
        QTimer.singleShot(900, self.update_windows)

    def app_close_windows(self, hwnds: List[int]) -> None:
        """Uygulama döşemesi > Tüm pencereleri kapat: her pencereye kibar WM_CLOSE (kaydet sorusunu uygulama sorar)."""
        if self.preview_mode:
            return
        for h in hwnds:
            try:
                winapi.close_window(int(h))
            except Exception as exc:
                sources.log_err("app_close_windows", exc)
        QTimer.singleShot(700, self.update_windows)
        QTimer.singleShot(2500, self.update_windows)

    def end_app_task(self, tile: dict) -> None:
        """Uygulama döşemesi > Görevi sonlandır: tepsideki ile aynı güvenli yol (korumalı işlemler atlanır)."""
        exe = str(tile.get("exe") or "")
        if not exe or self.preview_mode:
            return
        item = {"name": str(tile.get("name") or Path(exe).stem), "exe": exe}
        try:
            import tray_actions

            def _worker() -> None:
                res = tray_actions.end_task(item)
                self.dispatcher.end_task_done.emit(item, res)

            sources.submit(f"app_end_task:{exe.lower()}", _worker)
        except Exception as exc:
            sources.log_err("app_end_task", exc)
        QTimer.singleShot(900, self.update_windows)
        QTimer.singleShot(3000, self.update_windows)

    def build_dock_menu_actions(self) -> List[Dict[str, Any]]:
        # v24 (Emre): 12 seçenek -> 7. Kart aç/kapat satırları Ayarlar > Kartlar'da; "Konumu sıfırla" kalktı
        # (tam genişlik şeritte işe yaramıyordu; action_reset_pos yöntemi duruyor).
        def on_toggle_alerts():
            checked = not bool(self.settings.get("alerts_enabled", True))
            self.settings["alerts_enabled"] = checked
            if self.alert_engine is not None:
                self.alert_engine.enabled = checked
            save_settings(self.settings)

        return [
            {"id": "settings", "text": "Ayarlar…", "icon": "settings", "callback": self.action_open_settings},
            {"id": "refresh", "text": "Yenile", "callback": self.action_refresh},
            {"type": "separator"},
            {
                "id": "style_band",
                "text": "Tam genişlik şerit",
                "group": "style",
                "checked": self._is_band(),
                "callback": lambda: self.set_dock_style("band"),
            },
            {
                "id": "style_pill",
                "text": "Ortada kapsül",
                "group": "style",
                "checked": not self._is_band(),
                "callback": lambda: self.set_dock_style("pill"),
            },
            {"type": "separator"},
            {
                "id": "toggle_alerts",
                "text": "Uyarılar",
                "checked": bool(self.settings.get("alerts_enabled", True)),
                "callback": on_toggle_alerts,
            },
            {
                "id": "toggle_taskbar",
                "text": "Windows görev çubuğunu gizle",
                "checked": bool(self.settings.get("hide_taskbar", False)),
                "callback": self.action_toggle_taskbar,
            },
            {"type": "separator"},
            {
                "id": "quit",
                "text": "Kapat",
                "danger": True,
                "confirm": True,
                "callback": QApplication.instance().quit,
            },
        ]

    def contextMenuEvent(self, event) -> None:
        # QContextMenuEvent'te position() yok (yalnız pos()/globalPos()); eskiden her sağ tık hata veriyordu
        cpos = QPointF(event.pos())
        anchor_global = QRectF(float(event.globalPos().x()), float(event.globalPos().y()), 1.0, 1.0)
        for r, key, extra in reversed(self.hit_boxes):
            if key == "tray_icon" and extra and r.contains(cpos):
                tray_anchor = QRectF(
                    self.mapToGlobal(QPoint(int(r.x()), int(r.y()))),
                    r.size(),
                )
                self._start_tray_end_task_flow(extra, tray_anchor)
                return
            if key.startswith("app_") and extra and r.contains(cpos):
                if self._app_action_menu is None:
                    self._app_action_menu = action_menu.ActionMenu()
                actions = self.build_app_tile_menu_actions(extra)
                try:
                    n_win = len(extra.get("hwnds") or [])
                    sub = f"{n_win} pencere" if n_win else ("Sabitlenmiş" if extra.get("pinned") else "")
                    icon = self._icon_cache.get(str(extra.get("exe") or extra.get("path") or ""))
                    self._app_action_menu.set_header(str(extra.get("name") or ""), sub, icon)
                except Exception as exc:
                    sources.log_err("app_menu_header", exc)
                self._app_action_menu.set_actions(actions)
                self._app_action_menu.show_at(anchor_global)
                return

        # Main dock context menu
        if self._dock_action_menu is None:
            self._dock_action_menu = action_menu.ActionMenu()
        dock_actions = self.build_dock_menu_actions()
        self._dock_action_menu.set_actions(dock_actions)
        self._dock_action_menu.show_at(anchor_global)

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

    def action_open_settings(self) -> None:
        """Sağ tık > Ayarlar…: tek pencere; açıksa öne getirir."""
        win = getattr(self, "_settings_win", None)
        if win is not None:
            try:
                if win.isVisible():
                    win.raise_()
                    win.activateWindow()
                    return
            except RuntimeError:
                pass  # C++ nesnesi silinmiş
        try:
            import settings_window
            monitor = getattr(self, "stall_monitor", None)
            provider = monitor.stats if monitor is not None else None
            self._settings_win = settings_window.open_settings(
                self.settings, self.apply_settings_from_window, stats_provider=provider
            )
        except Exception as exc:
            sources.log_err("settings_window", exc)

    def apply_settings_from_window(self, new_cfg: dict) -> None:
        """Ayarlar penceresinde 'Uygula': yalnız değişen ayarları bara uygular ve bir kez kaydeder."""
        if not isinstance(new_cfg, dict):
            return
        old = self.settings
        if bool(new_cfg.get("hide_taskbar", False)) != bool(old.get("hide_taskbar", False)):
            self.action_toggle_taskbar(bool(new_cfg.get("hide_taskbar", False)))
        if bool(new_cfg.get("alerts_enabled", True)) != bool(old.get("alerts_enabled", True)):
            old["alerts_enabled"] = bool(new_cfg.get("alerts_enabled", True))
            if self.alert_engine is not None:
                self.alert_engine.enabled = old["alerts_enabled"]
        if isinstance(new_cfg.get("cards"), dict):
            old["cards"] = dict(new_cfg["cards"])
        if isinstance(new_cfg.get("pinned"), list):
            self.pins = [dict(p) for p in new_cfg["pinned"] if isinstance(p, dict)]
            old["pinned"] = self.pins
        reserve_changed = bool(new_cfg.get("reserve_space", True)) != bool(old.get("reserve_space", True))
        if reserve_changed:
            old["reserve_space"] = bool(new_cfg.get("reserve_space", True))
        new_style = "pill" if new_cfg.get("style") == "pill" else "band"
        if new_style != str(old.get("style", "band")):
            self.set_dock_style(new_style)  # kaydeder, yerleşimi ve AppBar'ı yeniler
        if reserve_changed:
            if old["reserve_space"]:
                self._register_appbar()
            else:
                self._unregister_appbar()
        if not self.preview_mode:
            save_settings(old)
        self.update_windows()
        self.compute_layout_and_resize()
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

    if work_sources is not None:
        try:
            mail_data = work_sources.fetch_mail_waiting()
            store.update("mail", mail_data)
        except Exception as exc:
            sources.log_err("preview_mail", exc)
        try:
            ag_data = work_sources.fetch_antigravity()
            store.update("ag", ag_data)
        except Exception as exc:
            sources.log_err("preview_ag", exc)

    raw_wins = winapi.list_windows()
    groups = winapi.group_by_app(raw_wins)
    pins = list(settings.get("pinned") or pinned.load_default_pins())
    tiles = pinned.merge_tiles(pins, groups)

    # Initialize dock in preview mode (zero side effects)
    dock = SeritDock(settings, preview_mode=True)
    dock.store = store
    dock.pins = pins
    dock.tiles = tiles

    try:
        dock._tray_items = trayicons.list_tray_items()
        images = trayicons.get_tray_images(dock._tray_items)
        for name, img in images.items():
            if img is not None and not img.isNull():
                dock._tray_icons[name] = QPixmap.fromImage(img)
    except Exception as exc:
        sources.log_err("preview_tray", exc)

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

    try:
        import stall_monitor

        _stall_monitor = stall_monitor.StallMonitor(dock)
        _stall_monitor.start()
        dock.stall_monitor = _stall_monitor  # Ayarlar > Performans sayfası buradan okur
        app.aboutToQuit.connect(_stall_monitor.stop)
    except Exception as exc:
        sources.log_err("ui_stall_start", exc)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
