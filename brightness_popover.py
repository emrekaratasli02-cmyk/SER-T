"""Screen brightness popover for the Şerit dock, built on panel_style v2 (shared panel kit).

Displays one horizontal pill slider per detected monitor (internal panel via WMI,
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
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
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

PRESET_LEVELS = (25, 50, 75, 100)
WHEEL_STEP = 5
ROW_H = 42.0          # slider satırı (etiket + 18 px iz + tutaç)
ROW_GAP = 14.0
ERR_H = 14.0          # okunamayan ekranın hata satırı
CARD_OVER_H = 25.0    # kart üst başlığı (15 px + 10 px boşluk)


def _is_laptop(m: Dict[str, Any]) -> bool:
    name = str(m.get("name", "")).lower()
    return str(m.get("kind", "")) == "wmi" or "dizüstü" in name or "laptop" in name


def _display_name(m: Dict[str, Any]) -> str:
    return "Dizüstü" if _is_laptop(m) else str(m.get("name", "Ekran"))


def _draggable(m: Dict[str, Any]) -> bool:
    return bool(m.get("ok")) and m.get("level") is not None


class BrightnessPopover(QWidget):
    """Parlaklık paneli: yatay hap kaydırıcılar (ekran başına bir tane) + önayarlar + Eşitle."""

    WIDTH: int = int(panel_style.WIDTH["bright"])
    RADIUS: float = panel_style.R_PANEL

    level_requested = Signal(str, int)

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

        self._monitors: List[Dict[str, Any]] = []
        self._anchor_global: Optional[QRectF] = None
        self._dragging_id: Optional[str] = None
        self._active_preset: Optional[int] = None

        # Layout önbelleği (paint sırasında doldurulur)
        self._slider_layout_cache: List[Dict[str, Any]] = []
        self._preset_buttons_cache: List[Dict[str, Any]] = []
        self._btn_close_rect = QRectF()
        self._btn_sync_rect = QRectF()

        self._hover_close: bool = False
        self._hover_sync: bool = False
        self._hover_preset_idx: int = -1
        self._hover_slider_id: Optional[str] = None

        self._coalescer = BrightnessCoalescer(self, interval_ms=60)
        self._coalescer.level_requested.connect(self.level_requested.emit)

        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self.resize(self.WIDTH, self.compute_height())

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def is_open(self) -> bool:
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def _rows_height(self) -> float:
        n = len(self._monitors)
        if n == 0:
            return 30.0
        h = n * ROW_H + (n - 1) * ROW_GAP
        h += sum(ERR_H for m in self._monitors if not m.get("ok"))
        return h

    def compute_height(self) -> int:
        pad = panel_style.CARD_PAD
        card1 = 2 * pad + CARD_OVER_H + self._rows_height()
        card2 = 2 * pad + CARD_OVER_H + panel_style.PRESET_PILL_H
        total = (panel_style.PAD + panel_style.HEADER_H + panel_style.GAP + card1
                 + panel_style.GAP + card2 + panel_style.GAP + panel_style.FOOTER_H + panel_style.PAD * 0.5)
        return int(math.ceil(total))

    def show_for(self, anchor_global: Optional[QRectF], monitors: List[Any],
                 switch_from_x: Optional[int] = None) -> None:
        """Position above anchor and animate in via panel_style.animate_in."""
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None

        raw_list = monitors if isinstance(monitors, list) else []
        self._monitors = [_sanitize_monitor_item(m, i) for i, m in enumerate(raw_list)]
        self._dragging_id = None
        self._active_preset = None

        self.resize(self.WIDTH, self.compute_height())

        dpr = 1.0
        target = self.pos()
        if self._anchor_global is not None:
            anchor_cx = self._anchor_global.center().x()
            target_x = int(anchor_cx - self.width() / 2.0)
            target_y = int(self._anchor_global.top() - self.height() - panel_style.ANCHOR_GAP)

            screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint())
            if screen is None:
                screen = QGuiApplication.primaryScreen()
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
                    target_y = below_y if below_y + self.height() <= geom.bottom() - margin else min_y
                elif target_y > max_y:
                    target_y = max_y
            target = QPoint(target_x, target_y)

        hwnd = int(self.winId())
        if winapi and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(hwnd, self.width(), self.height(), int(panel_style.R_PANEL), dpr)
            except Exception:
                pass

        self._is_closing = False
        panel_style.animate_in(self, target, switch_from_x=switch_from_x)
        self.activateWindow()

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
        new_by_id = {m["id"]: m for m in new_sanitized}
        for existing in self._monitors:
            mid = existing["id"]
            if mid in new_by_id and mid != self._dragging_id:
                upd = new_by_id[mid]
                for k in ("level", "ok", "err", "name", "kind"):
                    existing[k] = upd[k]

        if len(self._monitors) != len(new_sanitized):
            self._monitors = new_sanitized
        old_h = self.height()
        new_h = self.compute_height()
        if new_h != old_h:
            self.resize(self.WIDTH, new_h)
        self.update()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._is_closing:
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()
        panel_style.animate_out(self, on_done=self._on_closed)

    def hide_instant(self) -> None:
        """Close without animation (e.g. switching to another capsule panel)."""
        if not self.isVisible():
            self._is_closing = False
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()
        panel_style.animate_out(self, on_done=self._on_closed, instant=True)

    def _on_closed(self) -> None:
        self._is_closing = False

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        w_phys = max(1, int(self.width() * dpr))
        h_phys = max(1, int(self.height() * dpr))
        img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint_card(p)
        p.end()
        return img

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

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

    def _apply_level(self, m: Dict[str, Any], lvl: int, force: bool) -> None:
        m["level"] = lvl
        self._active_preset = None
        self._coalescer.request(m["id"], lvl, force=force)

    def _apply_all(self, lvl: int) -> None:
        self._active_preset = lvl
        for m in self._monitors:
            if m.get("ok"):
                m["level"] = lvl
                self._coalescer.request(m["id"], lvl, force=True)

    def _slider_at(self, pos, key: str = "hit_rect") -> Optional[Dict[str, Any]]:
        for item in self._slider_layout_cache:
            if item[key].contains(pos):
                return item
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()

            if self._btn_close_rect.contains(pos):
                self.hide_animated()
                event.accept()
                return

            for pb in self._preset_buttons_cache:
                if pb["rect"].contains(pos):
                    self._apply_all(pb["level"])
                    self.update()
                    event.accept()
                    return

            if self._btn_sync_rect.contains(pos):
                ok_lvls = [m.get("level") for m in self._monitors if m.get("ok") and m.get("level") is not None]
                if ok_lvls:
                    self._apply_all(ok_lvls[0])
                    self.update()
                    event.accept()
                    return

            item = self._slider_at(pos)
            if item is not None and _draggable(item["monitor"]):
                m = item["monitor"]
                self._dragging_id = m["id"]
                self._apply_level(m, panel_style.slider_value_at(item["track_rect"], pos.x()), False)
                self.update()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()

        if self._dragging_id:
            for item in self._slider_layout_cache:
                m = item["monitor"]
                if m.get("id") == self._dragging_id:
                    self._apply_level(m, panel_style.slider_value_at(item["track_rect"], pos.x()), False)
                    self.update()
                    event.accept()
                    return

        old = (self._hover_close, self._hover_sync, self._hover_preset_idx, self._hover_slider_id)
        self._hover_close = self._btn_close_rect.contains(pos)
        self._hover_sync = self._btn_sync_rect.contains(pos)
        self._hover_preset_idx = -1
        for idx, pb in enumerate(self._preset_buttons_cache):
            if pb["rect"].contains(pos):
                self._hover_preset_idx = idx
                break
        hs = self._slider_at(pos)
        self._hover_slider_id = hs["monitor"]["id"] if hs is not None and _draggable(hs["monitor"]) else None
        if old != (self._hover_close, self._hover_sync, self._hover_preset_idx, self._hover_slider_id):
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_close = self._hover_sync = False
        self._hover_preset_idx = -1
        self._hover_slider_id = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_id:
            for item in self._slider_layout_cache:
                m = item["monitor"]
                if m.get("id") == self._dragging_id:
                    lvl = m.get("level", 50)
                    self._coalescer.request(self._dragging_id, lvl if lvl is not None else 50, force=True)
                    break
            self._dragging_id = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        item = self._slider_at(event.position(), "row_rect")
        if item is not None and _draggable(item["monitor"]):
            m = item["monitor"]
            delta = WHEEL_STEP if event.angleDelta().y() > 0 else -WHEEL_STEP
            cur = m.get("level") if m.get("level") is not None else 50
            self._apply_level(m, max(0, min(100, cur + delta)), False)
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    # -----------------------------------------------------------------------
    # Painting
    # -----------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        try:
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                self._paint_card(p)
            finally:
                p.end()
        except Exception as e:
            _log_err("BrightnessPopover.paintEvent", e)

    def _active_preset_index(self) -> Optional[int]:
        lvl = self._active_preset
        if lvl is None:
            ok_lvls = [m.get("level") for m in self._monitors if _draggable(m)]
            if ok_lvls and all(v == ok_lvls[0] for v in ok_lvls):
                lvl = ok_lvls[0]
        return PRESET_LEVELS.index(lvl) if lvl in PRESET_LEVELS else None

    def _paint_pills(self, p: QPainter, rect: QRectF) -> None:
        """Önayar hapları; aktif olan v24 mavi vurgusunda (eskiden kehribar; bar iki renge indi)."""
        n = len(PRESET_LEVELS)
        gap = 8.0
        pill_w = (rect.width() - gap * (n - 1)) / n
        pill_h = min(panel_style.PRESET_PILL_H, rect.height())
        y = rect.center().y() - pill_h / 2.0
        active = self._active_preset_index()
        self._preset_buttons_cache = []
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, lvl in enumerate(PRESET_LEVELS):
            pr = QRectF(rect.left() + i * (pill_w + gap), y, pill_w, pill_h)
            self._preset_buttons_cache.append({"level": lvl, "rect": pr})
            hov = i == self._hover_preset_idx
            path = panel_style.rounded(pr.adjusted(0.5, 0.5, -0.5, -0.5), pill_h / 2.0)
            if i == active:
                p.setPen(QPen(panel_style.ACCENT, 1.0))
                p.setBrush(QColor(110, 168, 254, 46))
                txt = panel_style.ACCENT
                p.setFont(panel_style.font(12.0, QFont.Weight.DemiBold))
            else:
                p.setPen(QPen(panel_style.BUTTON_BORDER, 1.0))
                p.setBrush(panel_style.BUTTON_HOVER if hov else panel_style.BUTTON_BG)
                txt = panel_style.TEXT if hov else QColor(255, 255, 255, 204)
                p.setFont(panel_style.font(12.0, QFont.Weight.Medium))
            p.drawPath(path)
            p.setPen(txt)
            p.drawText(pr, Qt.AlignmentFlag.AlignCenter, panel_style.pct(lvl))
        p.restore()

    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        PAD, GAP = panel_style.PAD, panel_style.GAP
        panel_style.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))

        n = len(self._monitors)
        chip = f"{n} ekran" if n else "Ekran yok"
        hdr = panel_style.draw_header(
            p, QRectF(PAD, PAD, w - 2 * PAD, panel_style.HEADER_H), "Parlaklık",
            icon=lambda pp, r: draw_sun_icon(pp, r.adjusted(2, 2, -2, -2), panel_style.BRIGHT),
            chip=chip, close_hover=self._hover_close,
        )
        self._btn_close_rect = QRectF(hdr["close"])

        # Kart 1: EKRANLAR
        y = PAD + panel_style.HEADER_H + GAP
        card_h = 2 * panel_style.CARD_PAD + CARD_OVER_H + self._rows_height()
        inner = panel_style.draw_card(p, QRectF(PAD, y, w - 2 * PAD, card_h), "Ekranlar")
        self._slider_layout_cache = []

        if not self._monitors:
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, "Monitör bulunamadı")
        else:
            ry = inner.top()
            for m in self._monitors:
                ok = bool(m.get("ok"))
                lvl = m.get("level")
                has_val = ok and lvl is not None
                row_h = ROW_H + (0.0 if ok else ERR_H)
                row = QRectF(inner.left(), ry, inner.width(), row_h)
                col = panel_style.TEXT_BODY if has_val else panel_style.TEXT_MUTED
                icon_fn = draw_laptop_icon if _is_laptop(m) else draw_monitor_icon
                hover = (self._hover_slider_id == m["id"]) or (self._dragging_id == m["id"])
                res = panel_style.draw_slider(
                    p, QRectF(row.left(), row.top(), row.width(), ROW_H), _display_name(m),
                    lvl if has_val else None, fill=panel_style.BRIGHT_FILL,
                    icon=lambda pp, r, f=icon_fn, c=col: f(pp, r, c),
                    hover=hover and has_val,
                )
                track = QRectF(res["track"])
                self._slider_layout_cache.append({
                    "monitor": m,
                    "card_rect": row,
                    "row_rect": row,
                    "trough_rect": track,
                    "track_rect": track,
                    "hit_rect": track.adjusted(-4.0, -9.0, 4.0, 9.0),
                })
                if not ok:
                    p.save()
                    p.setFont(panel_style.font(11.0, QFont.Weight.Normal))
                    p.setPen(panel_style.WARN)
                    fm = QFontMetricsF(panel_style.font(11.0, QFont.Weight.Normal))
                    err = fm.elidedText(str(m.get("err") or "Kullanılamıyor"), Qt.TextElideMode.ElideRight, row.width())
                    p.drawText(QRectF(row.left(), row.top() + ROW_H - 2.0, row.width(), ERR_H),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, err)
                    p.restore()
                ry += row_h + ROW_GAP

        # Kart 2: HIZLI ÖNAYARLAR
        y += card_h + GAP
        card2_h = 2 * panel_style.CARD_PAD + CARD_OVER_H + panel_style.PRESET_PILL_H
        inner2 = panel_style.draw_card(p, QRectF(PAD, y, w - 2 * PAD, card2_h), "Hızlı önayarlar")
        self._paint_pills(p, inner2)

        # Alt bilgi
        y += card2_h + GAP
        ok_n = sum(1 for m in self._monitors if _draggable(m))
        btn = panel_style.draw_footer(
            p, QRectF(PAD, y, w - 2 * PAD, panel_style.FOOTER_H),
            "Windows · " + time.strftime("%H:%M"),
            "Eşitle" if ok_n >= 2 else None, self._hover_sync,
        )
        self._btn_sync_rect = QRectF(btn) if btn is not None else QRectF()
