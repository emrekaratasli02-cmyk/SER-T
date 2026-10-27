"""Modern dark-mode card-layered screen brightness popover panel for Şerit dock (Direction C).

Displays one vertical capsule slider per detected monitor (internal panel via WMI,
external monitors via DDC/CI) with fluent animations, mouse wheel / click / drag adjustment,
error indication for unavailable displays, quick presets, and coalesced level_requested signal emission.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Union

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
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


# ---------------------------------------------------------------------------
# Visual Vector Marks
# ---------------------------------------------------------------------------

def draw_sun_icon(p: QPainter, rect: QRectF, color: Optional[QColor] = None) -> None:
    """Draw high-DPI vector sun mark with central circle and 8 radial rays."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()
    size = min(rect.width(), rect.height())
    c = color if color is not None else panel_style.BRIGHT

    pen = QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    r_core = size * 0.22
    p.drawEllipse(QPointF(cx, cy), r_core, r_core)

    r_in = size * 0.36
    r_out = size * 0.48
    for i in range(8):
        ang = i * (math.pi / 4.0)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        p.drawLine(
            QPointF(cx + r_in * cos_a, cy + r_in * sin_a),
            QPointF(cx + r_out * cos_a, cy + r_out * sin_a),
        )
    p.restore()


def draw_laptop_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw clean laptop device outline."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()
    w = 15.0
    h = 10.0
    # Screen
    screen_r = QRectF(cx - w / 2.0, cy - h / 2.0 - 1.5, w, h)
    p.drawRoundedRect(screen_r, 1.8, 1.8)
    # Base
    base_y = cy + h / 2.0 + 1.5
    p.drawLine(QPointF(cx - w / 2.0 - 2.0, base_y), QPointF(cx + w / 2.0 + 2.0, base_y))
    p.restore()


def draw_monitor_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw clean external monitor outline."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()
    w = 15.0
    h = 10.5
    # Screen
    screen_r = QRectF(cx - w / 2.0, cy - h / 2.0 - 2.5, w, h)
    p.drawRoundedRect(screen_r, 1.8, 1.8)
    # Stand stem
    stem_y1 = screen_r.bottom()
    stem_y2 = stem_y1 + 3.5
    p.drawLine(QPointF(cx, stem_y1), QPointF(cx, stem_y2))
    # Stand foot
    p.drawLine(QPointF(cx - 3.5, stem_y2), QPointF(cx + 3.5, stem_y2))
    p.restore()


def draw_sync_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw circular sync arrows icon."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()
    r = min(rect.width(), rect.height()) * 0.38
    arc_box = QRectF(cx - r, cy - r, 2 * r, 2 * r)

    # Top arc
    p.drawArc(arc_box, int(30 * 16), int(120 * 16))
    # Bottom arc
    p.drawArc(arc_box, int(210 * 16), int(120 * 16))
    p.restore()


def _sanitize_monitor_item(raw: Any, idx: int) -> Dict[str, Any]:
    """Robustly sanitize monitor dictionaries against missing keys, NaN, invalid types."""
    if not isinstance(raw, dict):
        return {
            "id": f"mon_{idx}",
            "name": f"Ekran {idx + 1}",
            "kind": "ddc",
            "level": None,
            "min": 0,
            "max": 100,
            "ok": False,
            "err": "Geçersiz veri",
        }

    mid = str(raw.get("id") or f"mon_{idx}")
    kind = str(raw.get("kind") or "ddc")
    raw_name = raw.get("name")
    if raw_name:
        name = str(raw_name)
    else:
        name = "Dizüstü" if kind == "wmi" else f"Ekran {idx + 1}"

    err = str(raw.get("err")) if raw.get("err") is not None else None

    # Parse and clamp level
    raw_lvl = raw.get("level")
    lvl: Optional[int] = None
    if raw_lvl is not None:
        try:
            f = float(raw_lvl)
            if not (math.isnan(f) or math.isinf(f)):
                lvl = max(0, min(100, int(round(f))))
        except (ValueError, TypeError):
            lvl = None

    ok_val = raw.get("ok")
    if ok_val is None:
        ok = (lvl is not None)
    else:
        ok = bool(ok_val)

    if not ok and err is None:
        err = "Kullanılamıyor"

    return {
        "id": mid,
        "name": name,
        "kind": kind,
        "level": lvl,
        "min": 0,
        "max": 100,
        "ok": ok,
        "err": err,
    }


# ---------------------------------------------------------------------------
# BrightnessCoalescer: Rate-limits worker dispatch to at most every 60ms
# ---------------------------------------------------------------------------

class BrightnessCoalescer(QObject):
    """Coalesces brightness requests to at most once per 60ms, guaranteeing final on force=True."""

    level_requested = Signal(str, int)

    def __init__(self, parent: Optional[QObject] = None, interval_ms: int = 60) -> None:
        super().__init__(parent)
        self._interval_ms: int = interval_ms
        self._pending: Dict[str, int] = {}
        self._last_emit_time: Dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def request(self, monitor_id: str, level: int, force: bool = False) -> None:
        level = max(0, min(100, int(round(level))))
        self._pending[monitor_id] = level
        now = time.monotonic()
        last = self._last_emit_time.get(monitor_id, 0.0)
        elapsed_ms = (now - last) * 1000.0

        if force or elapsed_ms >= self._interval_ms:
            self._timer.stop()
            self._flush()
        elif not self._timer.isActive():
            rem_ms = max(5, int(self._interval_ms - elapsed_ms))
            self._timer.start(rem_ms)

    def _flush(self) -> None:
        if not self._pending:
            return
        now = time.monotonic()
        items = list(self._pending.items())
        self._pending.clear()
        for mid, lvl in items:
            self._last_emit_time[mid] = now
            self.level_requested.emit(mid, lvl)


# ---------------------------------------------------------------------------
# BrightnessPopover Widget
# ---------------------------------------------------------------------------

class BrightnessPopover(QWidget):
    """Sectioned opaque card-layered flyout panel for monitor brightness control (Direction C)."""

    WIDTH: int = 360
    RADIUS: float = panel_style.R_PANEL

    level_requested = Signal(str, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Frameless opaque window configuration
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Monitor state
        self._monitors: List[Dict[str, Any]] = []
        self._anchor_global: Optional[QRectF] = None
        self._dragging_id: Optional[str] = None
        self._active_preset: Optional[int] = 75

        # Layout Cache
        self._slider_layout_cache: List[Dict[str, Any]] = []
        self._preset_buttons_cache: List[Dict[str, Any]] = []
        self._btn_close_rect = QRectF(self.WIDTH - 14.0 - 26.0, 10.0, 26.0, 26.0)
        self._btn_sync_rect = QRectF(self.WIDTH - 14.0 - 78.0, 345.0, 78.0, 26.0)

        # Interactive hover states
        self._hover_close: bool = False
        self._hover_sync: bool = False
        self._hover_preset_idx: int = -1

        # Rate-limiting coalescer
        self._coalescer = BrightnessCoalescer(self, interval_ms=60)
        self._coalescer.level_requested.connect(self.level_requested.emit)

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

        self.resize(self.WIDTH, 380)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True if popover is visible and not in close transition."""
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        """Check if popover closed within threshold_ms to prevent toggle reopen bounce."""
        if self._last_close_time <= 0.0:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def compute_height(self) -> int:
        """Compute card height dynamically based on monitor count."""
        if not self._monitors:
            return 140
        return 380

    def show_for(self, anchor_global: Optional[QRectF], monitors: List[Any]) -> None:
        """Position centered above anchor, apply round region, and animate in."""
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None

        raw_list = monitors if isinstance(monitors, list) else []
        self._monitors = [_sanitize_monitor_item(m, i) for i, m in enumerate(raw_list)]
        self._dragging_id = None

        h = self.compute_height()
        self.resize(self.WIDTH, h)

        # Position widget above anchor with 8px gap
        dpr = 1.0
        if self._anchor_global is not None:
            anchor_cx = self._anchor_global.center().x()
            target_x = int(anchor_cx - self.width() / 2.0)
            target_y = int(self._anchor_global.top() - self.height() - panel_style.ANCHOR_GAP)

            center_pt = self._anchor_global.center().toPoint()
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
                    below_y = int(self._anchor_global.bottom() + panel_style.ANCHOR_GAP)
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

        # Trigger open transition: fade 0->1, slide 8px, scale 0.96->1 in 180ms OutCubic
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

    def update_levels(self, monitors: Union[List[Any], Dict[str, Any]]) -> None:
        """Update monitor levels without repositioning or restarting entry animation."""
        if isinstance(monitors, dict):
            for m in self._monitors:
                mid = m.get("id")
                if mid in monitors and mid != self._dragging_id:
                    val = monitors[mid]
                    try:
                        f = float(val) if val is not None else None
                        if f is not None and not (math.isnan(f) or math.isinf(f)):
                            m["level"] = max(0, min(100, int(round(f))))
                            m["ok"] = True
                            m["err"] = None
                        else:
                            m["level"] = None
                            m["ok"] = False
                    except (ValueError, TypeError):
                        m["level"] = None
                        m["ok"] = False
            self.update()
            return

        raw_list = monitors if isinstance(monitors, list) else []
        new_sanitized = [_sanitize_monitor_item(m, i) for i, m in enumerate(raw_list)]

        # Map by id
        new_by_id = {m["id"]: m for m in new_sanitized}
        for existing in self._monitors:
            mid = existing["id"]
            if mid in new_by_id and mid != self._dragging_id:
                upd = new_by_id[mid]
                existing["level"] = upd["level"]
                existing["ok"] = upd["ok"]
                existing["err"] = upd["err"]
                existing["name"] = upd["name"]
                existing["kind"] = upd["kind"]

        # If monitor list count changed, re-sync and recalculate height
        if len(self._monitors) != len(new_sanitized):
            self._monitors = new_sanitized
            h = self.compute_height()
            self.resize(self.WIDTH, h)

        self.update()

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

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current popover view offscreen to a high-DPI ARGB32 QImage."""
        w_phys = max(1, int(self.width() * dpr))
        h_phys = max(1, int(self.height() * dpr))
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

        self._paint_card(p)

        self._anim_opacity = saved_op
        self._anim_offset_y = saved_off
        self._anim_scale = saved_scale

        p.end()
        return img

    # -----------------------------------------------------------------------
    # Animation Callbacks
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Event Handling
    # -----------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()

            # Top-right close button
            if self._btn_close_rect.contains(pos):
                self.hide_animated()
                event.accept()
                return

            # Presets pills (%25, %50, %75, %100)
            for pb in self._preset_buttons_cache:
                if pb["rect"].contains(pos):
                    target_lvl = pb["level"]
                    self._active_preset = target_lvl
                    for m in self._monitors:
                        if m.get("ok"):
                            m["level"] = target_lvl
                            self._coalescer.request(m["id"], target_lvl, force=True)
                    self.update()
                    event.accept()
                    return

            # Equalize button
            if self._btn_sync_rect.contains(pos):
                # Equalize all monitors to first ok monitor level
                ok_lvls = [m.get("level") for m in self._monitors if m.get("ok") and m.get("level") is not None]
                if ok_lvls:
                    target_lvl = ok_lvls[0]
                    self._active_preset = target_lvl
                    for m in self._monitors:
                        if m.get("ok"):
                            m["level"] = target_lvl
                            self._coalescer.request(m["id"], target_lvl, force=True)
                    self.update()
                    event.accept()
                    return

            # Sliders click & drag
            for item in self._slider_layout_cache:
                m = item["monitor"]
                if not m.get("ok"):
                    continue
                hit_r = item["hit_rect"]
                trough_r = item["trough_rect"]
                if hit_r.contains(pos):
                    mid = m["id"]
                    self._dragging_id = mid
                    pct = max(0, min(100, int(round((trough_r.bottom() - pos.y()) / trough_r.height() * 100.0))))
                    m["level"] = pct
                    self._active_preset = None
                    self._coalescer.request(mid, pct, force=False)
                    self.update()
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        old_close = self._hover_close
        old_sync = self._hover_sync
        old_p_idx = self._hover_preset_idx

        self._hover_close = self._btn_close_rect.contains(pos)
        self._hover_sync = self._btn_sync_rect.contains(pos)

        self._hover_preset_idx = -1
        for idx, pb in enumerate(self._preset_buttons_cache):
            if pb["rect"].contains(pos):
                self._hover_preset_idx = idx
                break

        if self._dragging_id:
            for item in self._slider_layout_cache:
                m = item["monitor"]
                if m.get("id") == self._dragging_id:
                    trough_r = item["trough_rect"]
                    pct = max(0, min(100, int(round((trough_r.bottom() - pos.y()) / trough_r.height() * 100.0))))
                    m["level"] = pct
                    self._active_preset = None
                    self._coalescer.request(self._dragging_id, pct, force=False)
                    self.update()
                    event.accept()
                    return

        if (
            self._hover_close != old_close
            or self._hover_sync != old_sync
            or self._hover_preset_idx != old_p_idx
        ):
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_id:
            for item in self._slider_layout_cache:
                m = item["monitor"]
                if m.get("id") == self._dragging_id:
                    lvl = m.get("level", 50)
                    self._coalescer.request(self._dragging_id, lvl, force=True)
                    break
            self._dragging_id = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        pos = event.position()
        for item in self._slider_layout_cache:
            m = item["monitor"]
            if not m.get("ok"):
                continue
            card_r = item["card_rect"]
            if card_r.contains(pos):
                delta = 5 if event.angleDelta().y() > 0 else -5
                cur_lvl = m.get("level") if m.get("level") is not None else 50
                new_lvl = max(0, min(100, cur_lvl + delta))
                m["level"] = new_lvl
                self._active_preset = None
                self._coalescer.request(m["id"], new_lvl, force=False)
                self.update()
                event.accept()
                return
        super().wheelEvent(event)

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

                self._paint_card(p)
            finally:
                p.end()
        except Exception as e:
            _log_err("BrightnessPopover.paintEvent", e)

    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        r_full = QRectF(0.0, 0.0, w, h)

        # 1. Base Shell (Direction C Opaque Dark Obsidian)
        panel_style.draw_panel_shell(p, r_full)

        # 2. Header: Amber Sun Icon + Title ('Parlaklık') + Badge ('N ekran') + Close Button ('✕')
        sun_r = QRectF(16.0, 14.0, 18.0, 18.0)
        draw_sun_icon(p, sun_r, panel_style.BRIGHT)

        title = "Parlaklık"
        f_title = panel_style.f_title()
        p.setFont(f_title)
        p.setPen(panel_style.TEXT)
        fm_t = QFontMetricsF(f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(40.0, 12.0, title_w + 4.0, 22.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Badge: e.g. "2 ekran"
        badge_text = f"{len(self._monitors)} ekran" if self._monitors else "Ekran yok"
        f_badge = panel_style.font(11.0, QFont.Weight.Medium)
        p.setFont(f_badge)
        fm_b = QFontMetricsF(f_badge)
        badge_w = fm_b.horizontalAdvance(badge_text) + 16.0
        badge_r = QRectF(40.0 + title_w + 10.0, 14.5, badge_w, 18.0)

        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawPath(panel_style.rounded(badge_r, 9.0))
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(badge_r, Qt.AlignmentFlag.AlignCenter, badge_text)
        p.restore()

        # Close button ('✕')
        self._btn_close_rect = QRectF(w - 14.0 - 26.0, 10.0, 26.0, 26.0)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel_style.BUTTON_HOVER if self._hover_close else panel_style.BUTTON_BG)
        p.drawPath(panel_style.rounded(self._btn_close_rect, panel_style.R_BUTTON))
        p.setPen(QPen(panel_style.TEXT if self._hover_close else panel_style.TEXT_MUTED, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx_c = self._btn_close_rect.center().x()
        cy_c = self._btn_close_rect.center().y()
        p.drawLine(QPointF(cx_c - 4.0, cy_c - 4.0), QPointF(cx_c + 4.0, cy_c + 4.0))
        p.drawLine(QPointF(cx_c + 4.0, cy_c - 4.0), QPointF(cx_c - 4.0, cy_c + 4.0))
        p.restore()

        # Separator line under header
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(QPointF(0.0, 46.0), QPointF(w, 46.0))

        # 3. Monitor Tiles (Side-by-Side)
        self._slider_layout_cache = []
        pad_x = 14.0
        y_tiles = 54.0

        if not self._monitors:
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            p.drawText(QRectF(pad_x, y_tiles + 20.0, w - 2 * pad_x, 30.0), Qt.AlignmentFlag.AlignCenter, "Monitör bulunamadı")
            return

        n_mon = len(self._monitors)
        gap = 12.0
        avail_w = w - 2 * pad_x
        if n_mon == 1:
            tile_w = avail_w
        elif n_mon == 2:
            tile_w = (avail_w - gap) / 2.0
        else:
            tile_w = max(110.0, (avail_w - (n_mon - 1) * gap) / float(n_mon))

        tile_h = 196.0

        for i, m in enumerate(self._monitors):
            tile_x = pad_x + i * (tile_w + gap)
            card_r = QRectF(tile_x, y_tiles, tile_w, tile_h)
            is_ok = bool(m.get("ok"))
            lvl = m.get("level")
            name = str(m.get("name", "Ekran"))
            kind = str(m.get("kind", "ddc"))

            # Clean display name
            display_name = "Dizüstü" if (kind == "wmi" or "dizüstü" in name.lower() or "laptop" in name.lower()) else name

            # Draw elevated tile
            panel_style.draw_tile(p, card_r, hover=False)

            # Monitor Header: Device Icon + Name
            cx_card = card_r.center().x()
            icon_r = QRectF(tile_x + 12.0, y_tiles + 12.0, 16.0, 16.0)
            f_name = panel_style.font(11.5, QFont.Weight.DemiBold)
            p.setFont(f_name)
            p.setPen(panel_style.TEXT_BODY if is_ok else panel_style.TEXT_MUTED)

            if kind == "wmi" or "dizüstü" in name.lower():
                draw_laptop_icon(p, icon_r, panel_style.TEXT_BODY if is_ok else panel_style.TEXT_MUTED)
            else:
                draw_monitor_icon(p, icon_r, panel_style.TEXT_BODY if is_ok else panel_style.TEXT_MUTED)

            fm_n = QFontMetricsF(f_name)
            elided_name = fm_n.elidedText(display_name, Qt.TextElideMode.ElideRight, tile_w - 38.0)
            p.drawText(QRectF(tile_x + 32.0, y_tiles + 11.0, tile_w - 40.0, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

            # Hero percentage: large amber %82 or —
            p.setFont(panel_style.font(28.0, QFont.Weight.ExtraBold, tabular=True))
            if is_ok and lvl is not None:
                val_str = f"%{lvl}"
                p.setPen(panel_style.BRIGHT)
            else:
                val_str = "—"
                p.setPen(panel_style.TEXT_MUTED)
            p.drawText(QRectF(tile_x, y_tiles + 33.0, tile_w, 32.0), Qt.AlignmentFlag.AlignCenter, val_str)

            # Vertical Capsule Slider Trough
            trough_w = 48.0
            trough_h = 96.0
            trough_x = cx_card - trough_w / 2.0
            trough_y = y_tiles + 68.0
            trough_r = QRectF(trough_x, trough_y, trough_w, trough_h)
            hit_r = QRectF(trough_x - 6.0, trough_y - 4.0, trough_w + 12.0, trough_h + 8.0)

            self._slider_layout_cache.append({
                "monitor": m,
                "card_rect": card_r,
                "trough_rect": trough_r,
                "hit_rect": hit_r,
            })

            # Trough path (capsule radius 12)
            trough_path = panel_style.rounded(trough_r, 12.0)

            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Trough background & border
            p.fillPath(trough_path, QColor(255, 255, 255, 15) if is_ok else QColor(255, 255, 255, 8))
            p.setPen(QPen(QColor(255, 255, 255, 20) if is_ok else QColor(255, 255, 255, 10), 1))
            p.drawPath(trough_path)

            if is_ok and lvl is not None and lvl > 0:
                # Bottom-up fill
                fill_h = max(0.0, min(trough_h, trough_h * (lvl / 100.0)))
                fill_r = QRectF(trough_x, trough_y + trough_h - fill_h, trough_w, fill_h)

                # Clip fill to capsule
                p.setClipPath(trough_path)

                fill_grad = QLinearGradient(0.0, trough_y, 0.0, trough_y + trough_h)
                fill_grad.setColorAt(0.0, QColor(0xFF, 0xB0, 0x20))
                fill_grad.setColorAt(1.0, QColor(0xFF, 0x95, 0x00))
                p.fillPath(panel_style.rounded(fill_r, 0.0), fill_grad)

            # Embedded sun icon centered in the slider capsule
            sun_inner_r = QRectF(cx_card - 9.0, trough_y + trough_h / 2.0 - 9.0, 18.0, 18.0)
            draw_sun_icon(p, sun_inner_r, panel_style.BRIGHT if is_ok else QColor(255, 255, 255, 40))
            p.restore()

            # Sublabel / caption below slider
            f_caption = panel_style.font(10.5, QFont.Weight.Normal)
            p.setFont(f_caption)
            if not is_ok:
                err_text = m.get("err") or "Kullanılamıyor"
                fm_c = QFontMetricsF(f_caption)
                elided_err = fm_c.elidedText(err_text, Qt.TextElideMode.ElideRight, tile_w - 16.0)
                p.setPen(panel_style.WARN)
                p.drawText(QRectF(tile_x + 8.0, y_tiles + 170.0, tile_w - 16.0, 16.0), Qt.AlignmentFlag.AlignCenter, elided_err)
            else:
                caption = "Dahili ekran" if kind == "wmi" or "dizüstü" in name.lower() else "Harici monitör"
                p.setPen(panel_style.TEXT_MUTED)
                p.drawText(QRectF(tile_x + 8.0, y_tiles + 170.0, tile_w - 16.0, 16.0), Qt.AlignmentFlag.AlignCenter, caption)

        # 4. Quick Presets Card ('HIZLI ÖNAYARLAR')
        y_presets = y_tiles + tile_h + 12.0
        presets_h = 68.0
        presets_r = QRectF(pad_x, y_presets, avail_w, presets_h)
        panel_style.draw_tile(p, presets_r, hover=False)

        # Section Label
        p.setFont(panel_style.f_label())
        p.setPen(panel_style.TEXT_LABEL)
        p.drawText(QRectF(pad_x + 12.0, y_presets + 9.0, avail_w - 24.0, 16.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "HIZLI ÖNAYARLAR")

        # 4 Preset Pills: %25, %50, %75, %100
        pill_lvls = [25, 50, 75, 100]
        self._preset_buttons_cache = []
        pill_gap = 8.0
        pills_pad_x = 12.0
        pill_w = (avail_w - 2 * pills_pad_x - 3 * pill_gap) / 4.0
        pill_h = 28.0
        pill_y = y_presets + 29.0

        for idx, plvl in enumerate(pill_lvls):
            px = pad_x + pills_pad_x + idx * (pill_w + pill_gap)
            pill_r = QRectF(px, pill_y, pill_w, pill_h)
            self._preset_buttons_cache.append({
                "level": plvl,
                "rect": pill_r,
            })

            # Active if matches active_preset or all ok monitors match this level
            is_active = (self._active_preset == plvl)
            if not is_active and self._monitors:
                ok_lvls = [m.get("level") for m in self._monitors if m.get("ok") and m.get("level") is not None]
                if ok_lvls and all(lvl == plvl for lvl in ok_lvls):
                    is_active = True

            is_hover = (self._hover_preset_idx == idx)

            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pill_path = panel_style.rounded(pill_r, panel_style.R_BUTTON)

            if is_active:
                p.fillPath(pill_path, QColor(10, 132, 255, 50))  # rgba(10, 132, 255, 0.20)
                p.setPen(QPen(QColor(10, 132, 255, 130), 1))
                p.drawPath(pill_path)
                p.setPen(panel_style.CPU)  # #64D2FF
            else:
                p.fillPath(pill_path, panel_style.BUTTON_HOVER if is_hover else panel_style.BUTTON_BG)
                p.setPen(QPen(QColor(255, 255, 255, 15), 1))
                p.drawPath(pill_path)
                p.setPen(panel_style.TEXT if is_hover else panel_style.TEXT_BODY)

            p.setFont(panel_style.font(11.5, QFont.Weight.DemiBold))
            p.drawText(pill_r, Qt.AlignmentFlag.AlignCenter, f"%{plvl}")
            p.restore()

        # 5. Footer: Connection Info + Equalize Button
        y_footer = y_presets + presets_h + 10.0
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(QPointF(0.0, y_footer - 2.0), QPointF(w, y_footer - 2.0))

        # Footer Left Label
        p.setFont(panel_style.font(11.0, QFont.Weight.Normal))
        p.setPen(panel_style.TEXT_MUTED)
        p.drawText(QRectF(pad_x + 2.0, y_footer + 4.0, 180.0, 26.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Ekranlara doğrudan uygulanır")

        # Footer Right Button: Eşitle
        self._btn_sync_rect = QRectF(w - pad_x - 76.0, y_footer + 4.0, 76.0, 26.0)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sync_path = panel_style.rounded(self._btn_sync_rect, panel_style.R_BUTTON)
        p.fillPath(sync_path, panel_style.BUTTON_HOVER if self._hover_sync else panel_style.BUTTON_BG)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawPath(sync_path)

        # Sync icon + text
        sync_icon_r = QRectF(self._btn_sync_rect.left() + 7.0, self._btn_sync_rect.top() + 5.0, 15.0, 15.0)
        draw_sync_icon(p, sync_icon_r, panel_style.TEXT if self._hover_sync else panel_style.TEXT_BODY)

        p.setFont(panel_style.font(11.0, QFont.Weight.Medium))
        p.setPen(panel_style.TEXT if self._hover_sync else panel_style.TEXT_BODY)
        p.drawText(QRectF(self._btn_sync_rect.left() + 24.0, self._btn_sync_rect.top(), 48.0, 26.0), Qt.AlignmentFlag.AlignCenter, "Eşitle")
        p.restore()
