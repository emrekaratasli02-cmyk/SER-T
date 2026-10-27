"""Modern acrylic glass screen brightness popover panel for Serit dock.

Displays one slider row per detected monitor (internal panel via WMI, external
monitors via DDC/CI) with fluent animations, mouse wheel / click / drag adjustment,
error indication for unavailable displays, and coalesced level_requested signal emission.
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
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Safe imports from serit package
try:
    import sources
    import winapi
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    try:
        import sources
        import winapi
    except Exception:
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
# Visual Styling Tokens (Lumabar Deep Obsidian Matte & Sun Amber Accent)
# ---------------------------------------------------------------------------

WIDTH: int = 300
CORNER_RADIUS: float = 14.0

COLOR_BG: QColor = QColor(20, 21, 25, 248)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(225, 228, 235, 240)
COLOR_TEXT_MUTED: QColor = QColor(148, 154, 166, 220)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 22)

COLOR_SUN_AMBER: QColor = QColor(255, 196, 92)
COLOR_TRACK_BG: QColor = QColor(255, 255, 255, 26)
COLOR_TRACK_BORDER: QColor = QColor(255, 255, 255, 18)
COLOR_TRACK_DISABLED: QColor = QColor(255, 255, 255, 12)
COLOR_ALERT_WARN: QColor = QColor("#FFC45C")
COLOR_ALERT_ERR: QColor = QColor("#FCA5A5")


def make_font(
    size_px: int,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
) -> QFont:
    """Create a high-DPI Segoe UI Variable font instance."""
    f = QFont("Segoe UI Variable Text")
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    f.setPixelSize(size_px)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag.fromString("tnum"), 1)
        except Exception:
            pass
    if letter_spacing is not None:
        try:
            f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
        except Exception:
            pass
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def draw_sun_icon(p: QPainter, rect: QRectF) -> None:
    """Draw high-DPI vector sun mark in warm amber (no emoji)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    cx = rect.center().x()
    cy = rect.center().y()
    size = min(rect.width(), rect.height())
    r_core = size * 0.22

    # Sun core
    p.setPen(Qt.NoPen)
    p.setBrush(COLOR_SUN_AMBER)
    p.drawEllipse(QPointF(cx, cy), r_core, r_core)

    # Sun rays (8 rays)
    pen = QPen(COLOR_SUN_AMBER, 1.4, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    r_inner = size * 0.34
    r_outer = size * 0.46
    for i in range(8):
        angle = i * (math.pi / 4.0)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        p.drawLine(
            QPointF(cx + r_inner * cos_a, cy + r_inner * sin_a),
            QPointF(cx + r_outer * cos_a, cy + r_outer * sin_a),
        )
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
    name = str(raw.get("name") or ("Dizüstü ekranı" if raw.get("kind") == "wmi" else f"Ekran {idx + 1}"))
    kind = str(raw.get("kind") or "ddc")
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
    """Sectioned acrylic glass flyout panel for monitor brightness control."""

    WIDTH: int = WIDTH
    RADIUS: float = CORNER_RADIUS

    level_requested = Signal(str, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Frameless translucent window configuration
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        # Monitor state
        self._monitors: List[Dict[str, Any]] = []
        self._anchor_global: Optional[QRectF] = None
        self._dragging_id: Optional[str] = None
        self._row_layout_cache: List[Dict[str, Any]] = []

        # Rate-limiting coalescer
        self._coalescer = BrightnessCoalescer(self, interval_ms=60)
        self._coalescer.level_requested.connect(self.level_requested.emit)

        # Focus / bounce tracking
        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Animations
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0
        self._anim_scale: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Typography
        self.f_title = make_font(13, QFont.Weight.DemiBold)
        self.f_label = make_font(12, QFont.Weight.Normal)
        self.f_val = make_font(12, QFont.Weight.DemiBold, tabular=True)
        self.f_sub = make_font(10, QFont.Weight.Normal)

        self.resize(self.WIDTH, 140)

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
        # Top padding (14) + Header (18) + Header bottom gap (12) = 44
        h = 44.0
        if not self._monitors:
            h += 46.0  # Empty state banner
        else:
            for _ in self._monitors:
                h += 52.0  # Row height
            h += 6.0  # Bottom padding
        return max(110, int(math.ceil(h)))

    def show_for(self, anchor_global: Optional[QRectF], monitors: List[Any]) -> None:
        """Position centered above anchor, enable acrylic, and animate in."""
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None

        raw_list = monitors if isinstance(monitors, list) else []
        self._monitors = [_sanitize_monitor_item(m, i) for i, m in enumerate(raw_list)]
        self._dragging_id = None

        h = self.compute_height()
        self.resize(self.WIDTH, h)

        # Position widget above anchor
        dpr = 1.0
        if self._anchor_global is not None:
            anchor_cx = self._anchor_global.center().x()
            target_x = int(anchor_cx - self.width() / 2.0)
            target_y = int(self._anchor_global.top() - self.height() - 10)

            center_pt = self._anchor_global.center().toPoint()
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
                    below_y = int(self._anchor_global.bottom() + 10)
                    if below_y + self.height() <= geom.bottom() - margin:
                        target_y = below_y
                    else:
                        target_y = min_y
                elif target_y > max_y:
                    target_y = max_y

            self.move(target_x, target_y)

        # Apply Windows acrylic composition & physical rounded region
        hwnd = int(self.winId())
        if winapi and hasattr(winapi, "enable_acrylic"):
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
        if event.key() == Qt.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange:
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
        if event.button() == Qt.LeftButton:
            pos = event.position()
            # Top-right close button
            close_r = QRectF(self.width() - 32.0, 12.0, 22.0, 22.0)
            if close_r.contains(pos):
                self.hide_animated()
                event.accept()
                return

            # Sliders
            for item in self._row_layout_cache:
                m = item["monitor"]
                if not m.get("ok"):
                    continue
                hit_r = item["hit_rect"]
                track_r = item["track_rect"]
                if hit_r.contains(pos):
                    mid = m["id"]
                    self._dragging_id = mid
                    pct = max(0, min(100, int(round((pos.x() - track_r.left()) / track_r.width() * 100.0))))
                    m["level"] = pct
                    self._coalescer.request(mid, pct, force=False)
                    self.update()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging_id:
            pos = event.position()
            for item in self._row_layout_cache:
                m = item["monitor"]
                if m.get("id") == self._dragging_id:
                    track_r = item["track_rect"]
                    pct = max(0, min(100, int(round((pos.x() - track_r.left()) / track_r.width() * 100.0))))
                    m["level"] = pct
                    self._coalescer.request(self._dragging_id, pct, force=False)
                    self.update()
                    event.accept()
                    return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging_id:
            for item in self._row_layout_cache:
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
        for item in self._row_layout_cache:
            m = item["monitor"]
            if not m.get("ok"):
                continue
            row_r = item["row_rect"]
            if row_r.contains(pos):
                delta = 5 if event.angleDelta().y() > 0 else -5
                cur_lvl = m.get("level") if m.get("level") is not None else 50
                new_lvl = max(0, min(100, cur_lvl + delta))
                m["level"] = new_lvl
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
                p.setRenderHint(QPainter.Antialiasing)
                p.setRenderHint(QPainter.TextAntialiasing)
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
        r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = rounded_path(r, self.RADIUS)

        # 1. Base dark acrylic glass
        p.fillPath(path, COLOR_BG)

        # 2. Specular top sheen
        p.save()
        p.setClipPath(path)
        hl = QLinearGradient(0, 0, 0, 5)
        hl.setColorAt(0.0, QColor(255, 255, 255, 55))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1, 1, w - 2, 5), hl)
        p.restore()

        # 3. Specular rim & border
        p.setPen(QPen(QColor(0, 0, 0, 95), 1))
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

        # 4. Header: Sun Icon + Title ('Parlaklık') + Close ('✕')
        icon_r = QRectF(16.0, 14.0, 18.0, 18.0)
        draw_sun_icon(p, icon_r)

        title = "Parlaklık"
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_t = QFontMetricsF(self.f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(40.0, 14.0, title_w + 4.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, title)

        # Close mark
        p.save()
        p.setPen(QPen(COLOR_TEXT_MUTED, 1.3, Qt.SolidLine, Qt.RoundCap))
        cx_close = w - 21.0
        cy_close = 23.0
        p.drawLine(QPointF(cx_close - 3.5, cy_close - 3.5), QPointF(cx_close + 3.5, cy_close + 3.5))
        p.drawLine(QPointF(cx_close + 3.5, cy_close - 3.5), QPointF(cx_close - 3.5, cy_close + 3.5))
        p.restore()

        # Hairline separator below header
        p.setPen(QPen(COLOR_HAIRLINE, 1))
        p.drawLine(16, 40, int(w - 16), 40)

        # 5. Monitor Rows
        self._row_layout_cache = []
        y_curr = 48.0

        if not self._monitors:
            p.setFont(self.f_sub)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(QRectF(16.0, y_curr + 8.0, w - 32.0, 20.0), Qt.AlignCenter, "Monitör bulunamadı")
            return

        for m in self._monitors:
            row_h = 52.0
            row_r = QRectF(0.0, y_curr, w, row_h)
            is_ok = bool(m.get("ok"))
            name = str(m.get("name", "Ekran"))
            lvl = m.get("level")

            # Name label
            p.setFont(self.f_label)
            p.setPen(COLOR_TEXT_PRIMARY if is_ok else COLOR_TEXT_MUTED)
            fm_label = QFontMetricsF(self.f_label)
            elided_name = fm_label.elidedText(name, Qt.TextElideMode.ElideRight, w - 90.0)
            p.drawText(QRectF(16.0, y_curr, w - 90.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, elided_name)

            # Tabular percentage / status
            p.setFont(self.f_val)
            val_r = QRectF(w - 16.0 - 54.0, y_curr, 54.0, 18.0)
            if is_ok and lvl is not None:
                val_str = f"%{lvl}"
                p.setPen(COLOR_TEXT_PRIMARY)
                p.drawText(val_r, Qt.AlignRight | Qt.AlignVCenter, val_str)
            else:
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(val_r, Qt.AlignRight | Qt.AlignVCenter, "--")

            # Slider Track & Thumb
            track_r = QRectF(16.0, y_curr + 26.0, w - 32.0, 6.0)
            hit_r = QRectF(16.0, y_curr + 18.0, w - 32.0, 22.0)
            self._row_layout_cache.append({
                "monitor": m,
                "row_rect": row_r,
                "track_rect": track_r,
                "hit_rect": hit_r,
            })

            if is_ok and lvl is not None:
                # Active slider track background
                track_path = rounded_path(track_r, 3.0)
                p.fillPath(track_path, COLOR_TRACK_BG)
                p.setPen(QPen(COLOR_TRACK_BORDER, 1))
                p.drawPath(track_path)

                # Filled progress portion
                fill_w = max(0.0, min(track_r.width(), track_r.width() * (lvl / 100.0)))
                if fill_w > 0:
                    fill_r = QRectF(track_r.left(), track_r.top(), fill_w, track_r.height())
                    fill_path = rounded_path(fill_r, 3.0)
                    fill_grad = QLinearGradient(track_r.left(), 0, track_r.right(), 0)
                    fill_grad.setColorAt(0.0, QColor(255, 180, 60))
                    fill_grad.setColorAt(1.0, QColor(255, 210, 110))
                    p.fillPath(fill_path, fill_grad)

                # Thumb handle
                cx_thumb = track_r.left() + fill_w
                cy_thumb = track_r.center().y()
                r_thumb = 6.5
                thumb_r = QRectF(cx_thumb - r_thumb, cy_thumb - r_thumb, r_thumb * 2.0, r_thumb * 2.0)

                # Thumb drop shadow
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 80))
                p.drawEllipse(thumb_r.adjusted(0, 0.5, 0, 0.5))

                # Thumb core
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(20, 21, 25, 200), 1))
                p.drawEllipse(thumb_r)

                # Thumb center amber pip
                p.setPen(Qt.NoPen)
                p.setBrush(COLOR_SUN_AMBER)
                p.drawEllipse(QRectF(cx_thumb - 2.0, cy_thumb - 2.0, 4.0, 4.0))

            else:
                # Dimmed/disabled track
                track_path = rounded_path(track_r, 3.0)
                p.fillPath(track_path, COLOR_TRACK_DISABLED)
                p.setPen(QPen(QColor(255, 255, 255, 10), 1))
                p.drawPath(track_path)

                # Dimmed reason message
                err_text = m.get("err") or "Kullanılamıyor"
                p.setFont(self.f_sub)
                p.setPen(COLOR_ALERT_WARN)
                fm_sub = QFontMetricsF(self.f_sub)
                elided_sub = fm_sub.elidedText(err_text, Qt.TextElideMode.ElideRight, w - 32.0)
                p.drawText(QRectF(16.0, y_curr + 34.0, w - 32.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)

            y_curr += row_h
