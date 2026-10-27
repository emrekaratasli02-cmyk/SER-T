"""Modern dark-mode card-layered audio mixer popover panel for Şerit dock (Direction C).

Option 2 'Uygulama Mikseri':
- Header: 'Ses' title + device chip ('Hoparlör · Realtek Audio' via media.tr_device_name) + close button.
- Master Tile: big percentage, horizontal slider (drag/wheel/click), round mute button.
- Uygulamalar Tile: per-app session row (icon, name, mini slider, %, mute button; playing apps have blue dot).
  Empty state: 'Ses çalan uygulama yok'.
- Footer: 'Windows ses ayarları' link (opens ms-settings:apps-volume on click).
- Adaptive height based on row count (max 6 visible rows, then scroll).
- Screen clamping with 8px margin and gap above anchor.
- Coalesced updates (~40ms master, ~60ms apps) via background worker threads.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import (
    QEvent,
    QObject,
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
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

# Add serit dir to sys.path if not present
_serit_dir = str(Path(__file__).resolve().parent)
if _serit_dir not in sys.path:
    sys.path.insert(0, _serit_dir)

import panel_style

try:
    import media
except ImportError:
    media = None

try:
    import winapi
except ImportError:
    winapi = None

try:
    import sources
except ImportError:
    sources = None

try:
    import audio_mixer
except ImportError:
    audio_mixer = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Vector Mark Drawings
# ---------------------------------------------------------------------------

def draw_equalizer_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw crisp 3-slider equalizer vector mark."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()
    h = 14.0

    # Vertical track lines
    x1 = cx - 5.0
    x2 = cx
    x3 = cx + 5.0
    y_top = cy - h / 2.0
    y_bot = cy + h / 2.0

    p.drawLine(QPointF(x1, y_top), QPointF(x1, y_bot))
    p.drawLine(QPointF(x2, y_top), QPointF(x2, y_bot))
    p.drawLine(QPointF(x3, y_top), QPointF(x3, y_bot))

    # Knob tick marks
    p.drawLine(QPointF(x1 - 2.0, cy - 2.5), QPointF(x1 + 2.0, cy - 2.5))
    p.drawLine(QPointF(x2 - 2.0, cy + 2.5), QPointF(x2 + 2.0, cy + 2.5))
    p.drawLine(QPointF(x3 - 2.0, cy - 1.0), QPointF(x3 + 2.0, cy - 1.0))
    p.restore()


def draw_speaker_icon(p: QPainter, rect: QRectF, color: QColor, muted: bool = False) -> None:
    """Draw clean vector speaker icon with sound arcs or mute slash."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()

    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)

    # Speaker cone
    path = QPainterPath()
    # Left box
    path.moveTo(cx - 5.5, cy - 2.5)
    path.lineTo(cx - 3.5, cy - 2.5)
    # Expanding cone
    path.lineTo(cx - 0.5, cy - 5.5)
    path.lineTo(cx - 0.5, cy + 5.5)
    path.lineTo(cx - 3.5, cy + 2.5)
    path.lineTo(cx - 5.5, cy + 2.5)
    path.closeSubpath()
    p.drawPath(path)

    if muted:
        # Draw slash / X
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen_slash = QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen_slash)
        p.drawLine(QPointF(cx + 2.0, cy - 3.5), QPointF(cx + 6.5, cy + 3.5))
        p.drawLine(QPointF(cx + 6.5, cy - 3.5), QPointF(cx + 2.0, cy + 3.5))
    else:
        # Draw 2 sound wave arcs
        p.setBrush(Qt.BrushStyle.NoBrush)
        r1 = QRectF(cx - 4.0, cy - 4.5, 9.0, 9.0)
        p.drawArc(r1, -45 * 16, 90 * 16)
        r2 = QRectF(cx - 5.5, cy - 6.5, 13.0, 13.0)
        p.drawArc(r2, -45 * 16, 90 * 16)

    p.restore()


def draw_gear_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw small vector settings gear icon."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()
    r_outer = 4.8
    r_inner = 2.4

    pen = QPen(color, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

    # 6 teeth
    for i in range(6):
        ang = i * (math.pi / 3.0)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        p.drawLine(
            QPointF(cx + (r_inner + 0.6) * cos_a, cy + (r_inner + 0.6) * sin_a),
            QPointF(cx + r_outer * cos_a, cy + r_outer * sin_a),
        )
    p.restore()


def draw_fallback_app_icon(p: QPainter, rect: QRectF, name: str) -> None:
    """Draw fallback letter circle when application icon is unavailable."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    palette = [
        QColor(0x0A, 0x84, 0xFF),  # Sound blue
        QColor(0x30, 0xD1, 0x58),  # Spotify green
        QColor(0xBF, 0x5A, 0xF2),  # Purple
        QColor(0xFF, 0x9F, 0x0A),  # Amber
        QColor(0x64, 0xD2, 0xFF),  # Cyan
        QColor(0xEA, 0x43, 0x35),  # Red
    ]
    color_idx = sum(ord(c) for c in name) % len(palette) if name else 0
    bg_col = palette[color_idx]

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg_col)
    p.drawEllipse(rect)

    letter = (name.strip()[:1].upper()) if name.strip() else "S"
    p.setPen(panel_style.TEXT)
    f = panel_style.font(rect.height() * 0.52, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
    p.restore()


# ---------------------------------------------------------------------------
# Rate-Limiting Coalescers
# ---------------------------------------------------------------------------

class MasterVolumeCoalescer(QObject):
    """Coalesces master volume changes (~40ms) to prevent flooding worker threads."""

    def __init__(self, parent: Optional[QObject] = None, interval_ms: int = 40) -> None:
        super().__init__(parent)
        self._interval_ms: int = interval_ms
        self._target_level: Optional[float] = None
        self._last_apply_time: float = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def request(self, level: float, force: bool = False) -> None:
        self._target_level = float(level)
        now = time.monotonic()
        elapsed = now - self._last_apply_time
        if force or elapsed >= (self._interval_ms / 1000.0):
            self._timer.stop()
            self._flush()
        elif not self._timer.isActive():
            rem_ms = max(5, int((self._interval_ms / 1000.0 - elapsed) * 1000))
            self._timer.start(rem_ms)

    def _flush(self) -> None:
        if self._target_level is None:
            return
        lvl = self._target_level

        def _apply() -> None:
            if media and hasattr(media, "set_volume"):
                media.set_volume(lvl)

        if sources and hasattr(sources, "submit"):
            submitted = sources.submit("vol_set", _apply)
            if submitted:
                self._last_apply_time = time.monotonic()
            else:
                self._timer.start(15)
        else:
            _apply()
            self._last_apply_time = time.monotonic()

    def stop(self) -> None:
        self._timer.stop()


class AppVolumeCoalescer(QObject):
    """Coalesces per-application volume changes (~60ms), keeping pending latest per key."""

    def __init__(self, parent: Optional[QObject] = None, interval_ms: int = 60) -> None:
        super().__init__(parent)
        self._interval_ms: int = interval_ms
        self._pending: Dict[str, float] = {}
        self._last_submit_time: Dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def request(self, key: str, level: float, force: bool = False) -> None:
        level = max(0.0, min(100.0, float(level)))
        self._pending[key] = level
        now = time.monotonic()
        last = self._last_submit_time.get(key, 0.0)
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
        items = list(self._pending.items())
        for key, lvl in items:
            target_int = max(0, min(100, int(round(lvl))))

            def _apply(k=key, v=target_int) -> None:
                if audio_mixer is not None and hasattr(audio_mixer, "set_session_level"):
                    audio_mixer.set_session_level(k, v)

            if sources and hasattr(sources, "submit"):
                sub_key = f"app_vol_{key}"
                submitted = sources.submit(sub_key, _apply)
                if submitted:
                    self._last_submit_time[key] = time.monotonic()
                    self._pending.pop(key, None)
                else:
                    self._timer.start(20)
            else:
                _apply()
                self._last_submit_time[key] = time.monotonic()
                self._pending.pop(key, None)

    def stop(self) -> None:
        self._timer.stop()


# ---------------------------------------------------------------------------
# VolumePopover Class (Direction C Option 2 'Uygulama Mikseri')
# ---------------------------------------------------------------------------

class VolumePopover(QWidget):
    """Sectioned Direction C volume mixer popover panel for Şerit dock."""

    WIDTH: int = int(panel_style.WIDTH.get("vol", 340))
    HEIGHT: int = 282
    MAX_VISIBLE_ROWS: int = 6

    sessions_loaded = Signal(object)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_volume_change: Optional[Callable[[float, bool], None]] = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.parent_dock = parent
        self.on_volume_change = on_volume_change

        # Master Audio State
        self._level: float = 50.0
        self._muted: bool = False
        self._device: str = ""

        # Sessions State
        self._sessions: List[Dict[str, Any]] = []

        # Interactive state
        self._anchor_global: Optional[QRectF] = None
        self._dragging: Optional[str] = None  # "master" or "app:<key>"
        self._scroll_y: float = 0.0
        self._max_scroll_y: float = 0.0

        # Hover states
        self._hover_close: bool = False
        self._hover_footer: bool = False
        self._hover_master_mute: bool = False
        self._hover_session_mute: Optional[str] = None

        # Hit rectangles cache
        self._btn_close_rect = QRectF()
        self._link_footer_rect = QRectF()
        self._hit_master_slider = QRectF()
        self._hit_master_mute = QRectF()
        self._hit_app_rows: List[Dict[str, Any]] = []

        # Rate-limiting coalescers
        self._master_coalescer = MasterVolumeCoalescer(self, interval_ms=40)
        self._app_coalescer = AppVolumeCoalescer(self, interval_ms=60)

        # 2s Periodic Session Refresher
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self.refresh_sessions)

        # Signal connections
        self.sessions_loaded.connect(self._on_sessions_loaded)

        # Focus / bounce tracking
        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)

        # Opacity & animation state
        self._anim_opacity: float = 1.0

        self.resize(self.WIDTH, self.compute_height())

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True if popover is visible and not in close transition."""
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        """Check if popover closed recently to prevent toggle reopen bounce."""
        if self._last_close_time <= 0.0:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def compute_height(self) -> int:
        """Compute window height dynamically based on row count (max 6 visible rows)."""
        # Header (44) + Gap (10) + Master Tile (78) + Gap (10) + Apps Tile + Gap (10) + Footer (40)
        n = len(self._sessions)
        if n == 0:
            # Apps tile padding (12+12) + label (16) + gap (10) + empty (38) = 88
            apps_tile_h = 88
        else:
            visible_n = min(n, self.MAX_VISIBLE_ROWS)
            # Row height 42, gap between rows 8 -> visible rows: 42*v + 8*(v-1) = 50*v - 8
            # Apps tile padding (12+12) + label (16) + gap (10) + rows = 50*v + 42
            apps_tile_h = 50 * visible_n + 42

        return 44 + 10 + 78 + 10 + apps_tile_h + 10 + 40

    def show_for(
        self,
        anchor_global: Optional[QRectF] = None,
        level: float = 50.0,
        muted: bool = False,
        device: str = "",
    ) -> None:
        """Position panel centered above anchor, clamp to screen, and show."""
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._level = float(level)
        self._muted = bool(muted)
        self._device = str(device)
        self._dragging = None
        self._scroll_y = 0.0
        self._is_closing = False

        h = self.compute_height()
        self.resize(self.WIDTH, h)
        self._reposition()

        # Apply rounded region if winapi available
        scr = QGuiApplication.primaryScreen()
        if self._anchor_global is not None:
            center_pt = self._anchor_global.center().toPoint()
            scr = QGuiApplication.screenAt(center_pt) or scr
        dpr = scr.devicePixelRatio() if scr else 1.0

        if winapi and hasattr(winapi, "set_round_region"):
            try:
                hwnd = int(self.winId())
                winapi.set_round_region(hwnd, self.width(), self.height(), int(panel_style.R_PANEL), dpr)
            except Exception as exc:
                _log_err("VolumePopover.winapi_round", exc)

        self.show()
        self.raise_()
        self.activateWindow()

        # Start periodic 2s polling and fetch immediately
        self._poll_timer.start(2000)
        self.refresh_sessions()
        self.update()

    def update_volume(self, level: float, muted: bool, device: Optional[str] = None) -> None:
        """Update master volume level, mute state, and optional device name."""
        self._level = float(level)
        self._muted = bool(muted)
        if device is not None:
            self._device = str(device)
        self.update()

    def update_sessions(self, sessions: List[Dict[str, Any]]) -> None:
        """Update active audio application sessions."""
        self._on_sessions_loaded(sessions)

    def refresh_sessions(self) -> None:
        """Trigger background audio session enumeration via worker thread."""
        def _fetch() -> list:
            if audio_mixer is not None and hasattr(audio_mixer, "list_sessions"):
                try:
                    res = audio_mixer.list_sessions()
                    return list(res) if isinstance(res, (list, tuple)) else []
                except Exception as exc:
                    _log_err("audio_mixer.list_sessions", exc)
                    return []
            return []

        def _on_done(key: str, res: Any) -> None:
            if isinstance(res, list):
                self.sessions_loaded.emit(res)
                if (
                    self.parent_dock
                    and hasattr(self.parent_dock, "dispatcher")
                    and self.parent_dock.dispatcher is not None
                ):
                    try:
                        self.parent_dock.dispatcher.data_ready.emit("audio_sessions", res)
                    except Exception:
                        pass

        if sources and hasattr(sources, "submit"):
            sources.submit("audio_sessions", _fetch, _on_done)
        else:
            res = _fetch()
            _on_done("audio_sessions", res)

    def hide(self) -> None:
        """Hide panel and stop polling timer."""
        self._poll_timer.stop()
        self._master_coalescer.stop()
        self._app_coalescer.stop()
        self._dragging = None
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hide()

    # -----------------------------------------------------------------------
    # Internal Helpers & Thread-Safe Slots
    # -----------------------------------------------------------------------

    def _on_sessions_loaded(self, sessions: List[Dict[str, Any]]) -> None:
        """Handle sessions loaded on GUI thread without disrupting active drag."""
        raw_list = sessions if isinstance(sessions, list) else []
        old_count = len(self._sessions)

        # Merge or replace sessions, preserving current level if dragging
        active_drag_key = (
            self._dragging.split(":", 1)[1]
            if self._dragging and self._dragging.startswith("app:")
            else None
        )

        new_sessions: List[Dict[str, Any]] = []
        for s in raw_list:
            if not isinstance(s, dict):
                continue
            item = dict(s)
            k = str(item.get("key", item.get("name", "")))
            if active_drag_key and k == active_drag_key:
                # Keep currently dragged local level
                for ex in self._sessions:
                    if str(ex.get("key", ex.get("name", ""))) == active_drag_key:
                        item["level"] = ex.get("level", item.get("level", 50.0))
                        break
            new_sessions.append(item)

        self._sessions = new_sessions

        # Recompute height if row count changed
        if len(self._sessions) != old_count:
            h = self.compute_height()
            if h != self.height():
                self.resize(self.WIDTH, h)
                self._reposition()

        self.update()

    def _reposition(self) -> None:
        """Position panel centered above anchor and clamp strictly inside screen bounds."""
        if self._anchor_global is None:
            return

        cx = self._anchor_global.center().x()
        target_x = int(round(cx - self.width() / 2.0))
        target_y = int(round(self._anchor_global.top() - self.height() - panel_style.ANCHOR_GAP))

        center_pt = self._anchor_global.center().toPoint()
        scr = QGuiApplication.screenAt(center_pt) or QGuiApplication.primaryScreen()
        if scr is not None:
            geom = scr.geometry()
            margin = 8
            min_x = geom.left() + margin
            max_x = geom.right() + 1 - self.width() - margin
            if max_x >= min_x:
                target_x = max(min_x, min(max_x, target_x))
            else:
                target_x = min_x

            min_y = geom.top() + margin
            max_y = geom.bottom() + 1 - self.height() - margin
            if target_y < min_y:
                below_y = int(round(self._anchor_global.bottom() + panel_style.ANCHOR_GAP))
                if below_y + self.height() <= geom.bottom() - margin:
                    target_y = below_y
                else:
                    target_y = min_y
            elif target_y > max_y:
                target_y = max_y

        self.move(target_x, target_y)

    def _request_master_volume(self, level: float, force: bool = False) -> None:
        """Apply master volume request via coalescer and invoke dock callback."""
        self._level = max(0.0, min(100.0, float(level)))
        if self.on_volume_change:
            try:
                self.on_volume_change(self._level, self._muted)
            except Exception as exc:
                _log_err("on_volume_change", exc)
        self.update()

        if self.parent_dock and getattr(self.parent_dock, "preview_mode", False):
            return
        self._master_coalescer.request(self._level, force=force)

    def _request_session_level(self, key: str, level: float, force: bool = False) -> None:
        """Apply session level request via coalescer."""
        level = max(0.0, min(100.0, float(level)))
        for s in self._sessions:
            if str(s.get("key", s.get("name", ""))) == key:
                s["level"] = level
                break
        self.update()

        if self.parent_dock and getattr(self.parent_dock, "preview_mode", False):
            return
        self._app_coalescer.request(key, level, force=force)

    def toggle_master_mute(self) -> None:
        """Toggle master mute state."""
        self._muted = not self._muted
        if self.on_volume_change:
            try:
                self.on_volume_change(self._level, self._muted)
            except Exception as exc:
                _log_err("on_volume_change", exc)
        self.update()

        def _apply() -> None:
            if media and hasattr(media, "toggle_mute"):
                media.toggle_mute()

        if self.parent_dock and getattr(self.parent_dock, "preview_mode", False):
            return
        if sources and hasattr(sources, "submit"):
            sources.submit("vol_mute", _apply)
        else:
            _apply()

    def toggle_session_mute(self, key: str) -> None:
        """Toggle mute state for an application session."""
        target_muted = False
        for s in self._sessions:
            if str(s.get("key", s.get("name", ""))) == key:
                target_muted = not bool(s.get("muted", False))
                s["muted"] = target_muted
                break
        self.update()

        def _apply(k=key, m=target_muted) -> None:
            if audio_mixer is not None and hasattr(audio_mixer, "set_session_mute"):
                audio_mixer.set_session_mute(k, m)

        if self.parent_dock and getattr(self.parent_dock, "preview_mode", False):
            return
        if sources and hasattr(sources, "submit"):
            sources.submit(f"app_mute_{key}", _apply)
        else:
            _apply()

    def _open_windows_sound_settings(self) -> None:
        """Open Windows volume mixer settings page."""
        try:
            if hasattr(os, "startfile"):
                os.startfile("ms-settings:apps-volume")
            else:
                import subprocess
                subprocess.Popen(["start", "ms-settings:apps-volume"], shell=True)
        except Exception as exc:
            _log_err("open_audio_settings", exc)

    # -----------------------------------------------------------------------
    # Painting
    # -----------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint_card(p)
        finally:
            p.end()

    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        r_full = QRectF(0.0, 0.0, w, h)

        # 1. Base Shell (Direction C Opaque Dark Graphite)
        panel_style.draw_panel_shell(p, r_full)

        # -------------------------------------------------------------------
        # 2. Header: Equalizer Icon + 'Ses' + Device Chip + Close Button ('✕')
        # -------------------------------------------------------------------
        icon_r = QRectF(14.0, 13.0, 18.0, 18.0)
        draw_equalizer_icon(p, icon_r, panel_style.SOUND)

        title = "Ses"
        f_title = panel_style.f_title()
        p.setFont(f_title)
        p.setPen(panel_style.TEXT)
        fm_t = QFontMetricsF(f_title)
        title_w = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(38.0, 11.0, title_w + 4.0, 22.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Close button ('✕')
        self._btn_close_rect = QRectF(w - 14.0 - 24.0, 10.0, 24.0, 24.0)
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

        # Device Chip: 'Hoparlör · Realtek Audio' via media.tr_device_name
        dev_raw = self._device
        dev_name = media.tr_device_name(dev_raw) if (media and hasattr(media, "tr_device_name")) else dev_raw
        if not dev_name and dev_raw:
            dev_name = dev_raw

        if dev_name:
            f_chip = panel_style.font(10.5, QFont.Weight.Medium)
            p.setFont(f_chip)
            fm_c = QFontMetricsF(f_chip)

            chip_x = 38.0 + title_w + 10.0
            max_chip_w = (self._btn_close_rect.left() - 8.0) - chip_x
            if max_chip_w > 40.0:
                avail_text_w = max_chip_w - 34.0  # simge (12) + boşluklar
                disp_dev_name = fm_c.elidedText(dev_name, Qt.TextElideMode.ElideRight, avail_text_w)
                chip_w = min(max_chip_w, fm_c.horizontalAdvance(disp_dev_name) + 34.0)
                chip_r = QRectF(chip_x, 12.0, chip_w, 20.0)

                p.save()
                p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
                p.setBrush(QColor(255, 255, 255, 14))
                p.drawPath(panel_style.rounded(chip_r, 10.0))

                # Mini speaker icon inside chip
                spk_rect = QRectF(chip_x + 8.0, 16.0, 12.0, 12.0)
                draw_speaker_icon(p, spk_rect, panel_style.TEXT_MUTED, muted=False)

                # Text
                p.setPen(panel_style.TEXT_BODY)
                p.drawText(
                    QRectF(chip_x + 25.0, 12.0, chip_w - 31.0, 20.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    disp_dev_name,
                )
                p.restore()

        # Separator under header
        p.setPen(QPen(panel_style.TILE_BORDER, 1.0))
        p.drawLine(QPointF(0.0, 44.0), QPointF(w, 44.0))

        # -------------------------------------------------------------------
        # 3. Master Tile: 'GENEL SES SEVİYESİ' + Big % + Slider + Mute Round
        # -------------------------------------------------------------------
        y_master = 54.0
        r_master = QRectF(14.0, y_master, w - 28.0, 78.0)
        panel_style.draw_tile(p, r_master)

        # Tile Label: 'GENEL SES SEVİYESİ'
        p.setFont(panel_style.f_label())
        p.setPen(panel_style.TEXT_LABEL)
        p.drawText(
            QRectF(r_master.left() + 12.0, r_master.top() + 11.0, 160.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "GENEL SES SEVİYESİ",
        )

        # Big % Indicator on top-right: e.g. '%25' in SOUND #0A84FF
        f_pct = panel_style.font(16.0, QFont.Weight.ExtraBold, tabular=True)
        p.setFont(f_pct)
        pct_color = panel_style.TEXT_MUTED if self._muted else panel_style.SOUND
        p.setPen(pct_color)
        pct_str = "Sessiz" if self._muted else panel_style.pct(self._level)
        p.drawText(
            QRectF(r_master.right() - 80.0, r_master.top() + 10.0, 68.0, 18.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            pct_str,
        )

        # Horizontal Master Slider & Mute Button Row
        y_controls = r_master.top() + 38.0
        mute_size = 28.0
        r_mute = QRectF(r_master.right() - 12.0 - mute_size, y_controls, mute_size, mute_size)
        self._hit_master_mute = r_mute

        # Draw Mute Round Button
        p.save()
        p.setPen(QPen(panel_style.TILE_BORDER, 1.0))
        p.setBrush(panel_style.BUTTON_HOVER if self._hover_master_mute else panel_style.BUTTON_BG)
        p.drawEllipse(r_mute)
        mute_icon_color = panel_style.DANGER if self._muted else (panel_style.TEXT if self._hover_master_mute else panel_style.TEXT_BODY)
        draw_speaker_icon(p, r_mute, mute_icon_color, muted=self._muted)
        p.restore()

        # Horizontal Master Slider Track
        slider_left = r_master.left() + 12.0
        slider_right = r_mute.left() - 10.0
        slider_w = max(40.0, slider_right - slider_left)
        track_h = 6.0
        track_y = y_controls + (mute_size - track_h) / 2.0
        r_track = QRectF(slider_left, track_y, slider_w, track_h)
        self._hit_master_slider = QRectF(slider_left, y_controls, slider_w, mute_size)

        # Background track
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(panel_style.TRACK)
        p.drawPath(panel_style.rounded(r_track, 3.0))

        # Filled track
        fill_ratio = max(0.0, min(1.0, self._level / 100.0))
        fill_w = slider_w * fill_ratio
        if fill_w > 0.0:
            r_fill = QRectF(slider_left, track_y, fill_w, track_h)
            p.setBrush(panel_style.TEXT_MUTED if self._muted else panel_style.SOUND)
            p.drawPath(panel_style.rounded(r_fill, 3.0))

        # Draggable Thumb
        thumb_cx = slider_left + fill_w
        thumb_cy = track_y + track_h / 2.0
        thumb_r = 7.0
        p.setPen(QPen(QColor(0, 0, 0, 40), 1.0))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_r, thumb_r)
        p.restore()

        # -------------------------------------------------------------------
        # 4. 'UYGULAMALAR' Tile: Per-App Rows (Scrollable if > 6 rows)
        # -------------------------------------------------------------------
        y_apps = r_master.bottom() + 10.0
        n_sessions = len(self._sessions)
        if n_sessions == 0:
            apps_tile_h = 88.0
        else:
            visible_n = min(n_sessions, self.MAX_VISIBLE_ROWS)
            apps_tile_h = 50.0 * visible_n + 42.0

        r_apps = QRectF(14.0, y_apps, w - 28.0, apps_tile_h)
        panel_style.draw_tile(p, r_apps)

        # Section Header: 'UYGULAMALAR' + stream count
        p.setFont(panel_style.f_label())
        p.setPen(panel_style.TEXT_LABEL)
        p.drawText(
            QRectF(r_apps.left() + 12.0, r_apps.top() + 11.0, 120.0, 16.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "UYGULAMALAR",
        )

        count_text = f"{n_sessions} uygulama" if n_sessions > 0 else "0 uygulama"
        p.setFont(panel_style.f_small())
        p.setPen(panel_style.TEXT_MUTED)
        p.drawText(
            QRectF(r_apps.right() - 100.0, r_apps.top() + 11.0, 88.0, 16.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            count_text,
        )

        # Content Area
        content_top = r_apps.top() + 34.0
        content_h = apps_tile_h - 44.0
        content_r = QRectF(r_apps.left() + 12.0, content_top, r_apps.width() - 24.0, content_h)

        self._hit_app_rows = []

        if n_sessions == 0:
            # Empty State
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            p.drawText(content_r, Qt.AlignmentFlag.AlignCenter, "Ses çalan uygulama yok")
        else:
            total_content_h = n_sessions * 50.0 - 8.0
            self._max_scroll_y = max(0.0, total_content_h - content_h)
            self._scroll_y = max(0.0, min(self._max_scroll_y, self._scroll_y))

            p.save()
            p.setClipRect(content_r)

            for i, session in enumerate(self._sessions):
                row_y = content_top + (i * 50.0) - self._scroll_y
                # Skip off-clip rows
                if row_y + 44.0 < content_top or row_y > content_top + content_h:
                    continue

                key = str(session.get("key", session.get("name", f"app_{i}")))
                name = str(session.get("name") or "Uygulama")
                exe = str(session.get("exe") or "")
                level = float(session.get("level", 100.0))
                muted = bool(session.get("muted", False))
                active = bool(session.get("active", False))

                # Upper Line (Icon + Name + Active Dot + %)
                icon_rect = QRectF(content_r.left(), row_y, 20.0, 20.0)
                pix = QPixmap()
                if exe and winapi and hasattr(winapi, "app_icon"):
                    try:
                        pix = winapi.app_icon(exe, 32)
                    except Exception:
                        pix = QPixmap()

                if pix and not pix.isNull():
                    p.drawPixmap(icon_rect.toRect(), pix)
                else:
                    draw_fallback_app_icon(p, icon_rect, name)

                # Active blue dot
                text_left = icon_rect.right() + 8.0
                if active:
                    dot_cx = icon_rect.right() + 6.0
                    dot_cy = row_y + 10.0
                    p.save()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(panel_style.SOUND)
                    p.drawEllipse(QPointF(dot_cx, dot_cy), 2.5, 2.5)
                    p.restore()
                    text_left = dot_cx + 7.0

                # App Percentage
                f_app_pct = panel_style.font(11.0, QFont.Weight.Medium, tabular=True)
                p.setFont(f_app_pct)
                pct_str = "Sessiz" if muted else panel_style.pct(level)
                p.setPen(panel_style.TEXT_MUTED if muted else (panel_style.SOUND if active else panel_style.TEXT_BODY))
                fm_ap = QFontMetricsF(f_app_pct)
                val_w = fm_ap.horizontalAdvance(pct_str) + 4.0
                val_rect = QRectF(content_r.right() - val_w, row_y, val_w, 20.0)
                p.drawText(val_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct_str)

                # App Name (Elided)
                avail_name_w = (val_rect.left() - 6.0) - text_left
                p.setFont(panel_style.f_body())
                p.setPen(panel_style.TEXT)
                fm_name = QFontMetricsF(panel_style.f_body())
                name_disp = fm_name.elidedText(name, Qt.TextElideMode.ElideRight, avail_name_w)
                p.drawText(
                    QRectF(text_left, row_y, avail_name_w, 20.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    name_disp,
                )

                # Lower Line (Mini Slider + Mini Mute Button)
                y_lower = row_y + 22.0
                mini_mute_size = 20.0
                r_mini_mute = QRectF(content_r.right() - mini_mute_size, y_lower, mini_mute_size, mini_mute_size)

                # Mini Mute Button
                hover_this_mute = (self._hover_session_mute == key)
                p.save()
                p.setPen(QPen(panel_style.TILE_BORDER, 1.0))
                p.setBrush(panel_style.BUTTON_HOVER if hover_this_mute else panel_style.BUTTON_BG)
                p.drawPath(panel_style.rounded(r_mini_mute, 6.0))
                icon_mute_col = panel_style.DANGER if muted else (panel_style.TEXT if hover_this_mute else panel_style.TEXT_MUTED)
                draw_speaker_icon(p, r_mini_mute, icon_mute_col, muted=muted)
                p.restore()

                # Mini Slider Track
                m_track_left = content_r.left()
                m_track_right = r_mini_mute.left() - 8.0
                m_track_w = max(30.0, m_track_right - m_track_left)
                m_track_h = 4.0
                m_track_y = y_lower + (mini_mute_size - m_track_h) / 2.0
                r_mini_track = QRectF(m_track_left, m_track_y, m_track_w, m_track_h)

                # Background
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(panel_style.TRACK)
                p.drawPath(panel_style.rounded(r_mini_track, 2.0))

                # Fill
                fill_ratio_app = max(0.0, min(1.0, level / 100.0))
                fill_w_app = m_track_w * fill_ratio_app
                if fill_w_app > 0.0:
                    r_mini_fill = QRectF(m_track_left, m_track_y, fill_w_app, m_track_h)
                    p.setBrush(QColor(10, 132, 255, 70) if muted else panel_style.SOUND)
                    p.drawPath(panel_style.rounded(r_mini_fill, 2.0))

                # Mini Thumb
                thumb_cx_app = m_track_left + fill_w_app
                thumb_cy_app = m_track_y + m_track_h / 2.0
                thumb_r_app = 4.5
                p.setPen(QPen(QColor(0, 0, 0, 40), 1.0))
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPointF(thumb_cx_app, thumb_cy_app), thumb_r_app, thumb_r_app)
                p.restore()

                # Cache hit rects
                self._hit_app_rows.append({
                    "key": key,
                    "row_rect": QRectF(content_r.left(), row_y, content_r.width(), 44.0),
                    "slider_rect": QRectF(m_track_left, y_lower, m_track_w, mini_mute_size),
                    "mute_rect": r_mini_mute,
                    "level": level,
                    "muted": muted,
                })

            p.restore()

            # Scrollbar indicator if sessions > MAX_VISIBLE_ROWS
            if n_sessions > self.MAX_VISIBLE_ROWS and self._max_scroll_y > 0.0:
                sb_w = 3.0
                sb_x = r_apps.right() - 5.0
                sb_track_h = content_h
                sb_thumb_h = max(24.0, (content_h / total_content_h) * sb_track_h)
                sb_thumb_y = content_top + (self._scroll_y / self._max_scroll_y) * (sb_track_h - sb_thumb_h)
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 60))
                p.drawPath(panel_style.rounded(QRectF(sb_x, sb_thumb_y, sb_w, sb_thumb_h), 1.5))
                p.restore()

        # -------------------------------------------------------------------
        # 5. Footer: Pinned 'Windows ses ayarları' Link
        # -------------------------------------------------------------------
        footer_top = h - 40.0
        p.setPen(QPen(panel_style.TILE_BORDER, 1.0))
        p.drawLine(QPointF(14.0, footer_top), QPointF(w - 14.0, footer_top))

        footer_text = "Windows ses ayarları"
        f_foot = panel_style.f_small()
        p.setFont(f_foot)
        fm_foot = QFontMetricsF(f_foot)
        foot_w = fm_foot.horizontalAdvance(footer_text) + 20.0  # icon + gap + text
        foot_h = 24.0
        foot_x = (w - foot_w) / 2.0
        foot_y = footer_top + (40.0 - foot_h) / 2.0
        self._link_footer_rect = QRectF(foot_x, foot_y, foot_w, foot_h)

        # Draw Settings Gear Icon + Link Text
        gear_rect = QRectF(foot_x, foot_y + 4.0, 14.0, 14.0)
        link_color = panel_style.TEXT if self._hover_footer else panel_style.TEXT_MUTED
        draw_gear_icon(p, gear_rect, link_color)

        p.setPen(link_color)
        p.drawText(
            QRectF(foot_x + 18.0, foot_y, foot_w - 18.0, foot_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            footer_text,
        )

        if self._hover_footer:
            # Underline link text on hover
            line_y = foot_y + foot_h - 4.0
            p.setPen(QPen(panel_style.TEXT_BODY, 1.0))
            p.drawLine(QPointF(foot_x + 18.0, line_y), QPointF(foot_x + foot_w, line_y))

    # -----------------------------------------------------------------------
    # Interactive Events
    # -----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()

            # Close button
            if self._btn_close_rect.contains(pos):
                self.hide()
                event.accept()
                return

            # Footer settings link
            if self._link_footer_rect.contains(pos):
                self._open_windows_sound_settings()
                event.accept()
                return

            # Master Mute Button
            if self._hit_master_mute.contains(pos):
                self.toggle_master_mute()
                event.accept()
                return

            # Master Slider Track
            if self._hit_master_slider.adjusted(-4.0, -4.0, 4.0, 4.0).contains(pos):
                self._dragging = "master"
                pct = max(0.0, min(100.0, (pos.x() - self._hit_master_slider.left()) / self._hit_master_slider.width() * 100.0))
                self._request_master_volume(pct, force=False)
                event.accept()
                return

            # App Session Rows
            for row in self._hit_app_rows:
                key = row["key"]
                # Session Mute Button
                if row["mute_rect"].contains(pos):
                    self.toggle_session_mute(key)
                    event.accept()
                    return

                # Session Slider Track
                if row["slider_rect"].adjusted(-4.0, -4.0, 4.0, 4.0).contains(pos):
                    self._dragging = f"app:{key}"
                    pct = max(0.0, min(100.0, (pos.x() - row["slider_rect"].left()) / row["slider_rect"].width() * 100.0))
                    self._request_session_level(key, pct, force=False)
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self._dragging == "master":
            pct = max(0.0, min(100.0, (pos.x() - self._hit_master_slider.left()) / self._hit_master_slider.width() * 100.0))
            self._request_master_volume(pct, force=False)
            event.accept()
            return

        if self._dragging and self._dragging.startswith("app:"):
            key = self._dragging.split(":", 1)[1]
            # Find matching slider rect
            for row in self._hit_app_rows:
                if row["key"] == key:
                    pct = max(0.0, min(100.0, (pos.x() - row["slider_rect"].left()) / row["slider_rect"].width() * 100.0))
                    self._request_session_level(key, pct, force=False)
                    break
            event.accept()
            return

        # Update hover states
        hover_close = self._btn_close_rect.contains(pos)
        hover_footer = self._link_footer_rect.contains(pos)
        hover_master_mute = self._hit_master_mute.contains(pos)

        hover_session_mute = None
        for row in self._hit_app_rows:
            if row["mute_rect"].contains(pos):
                hover_session_mute = row["key"]
                break

        needs_update = (
            hover_close != self._hover_close
            or hover_footer != self._hover_footer
            or hover_master_mute != self._hover_master_mute
            or hover_session_mute != self._hover_session_mute
        )

        self._hover_close = hover_close
        self._hover_footer = hover_footer
        self._hover_master_mute = hover_master_mute
        self._hover_session_mute = hover_session_mute

        # Cursor shaping
        if hover_close or hover_footer or hover_master_mute or hover_session_mute:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

        if needs_update:
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging == "master":
                self._request_master_volume(self._level, force=True)
                self._dragging = None
                event.accept()
                return

            if self._dragging and self._dragging.startswith("app:"):
                key = self._dragging.split(":", 1)[1]
                cur_lvl = 50.0
                for s in self._sessions:
                    if str(s.get("key", s.get("name", ""))) == key:
                        cur_lvl = float(s.get("level", 50.0))
                        break
                self._request_session_level(key, cur_lvl, force=True)
                self._dragging = None
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        pos = event.position()
        delta = event.angleDelta().y()
        diff = 2.0 if delta > 0 else -2.0

        # Master slider wheel
        if self._hit_master_slider.adjusted(-4.0, -10.0, 4.0, 10.0).contains(pos):
            new_lvl = max(0.0, min(100.0, self._level + diff))
            self._request_master_volume(new_lvl, force=False)
            event.accept()
            return

        # App session slider wheel (tight hit rect so wheel scrolls list otherwise)
        if len(self._sessions) <= self.MAX_VISIBLE_ROWS:
            for row in self._hit_app_rows:
                if row["slider_rect"].adjusted(-2.0, -1.0, 2.0, 1.0).contains(pos):
                    key = row["key"]
                    new_lvl = max(0.0, min(100.0, float(row["level"]) + diff))
                    self._request_session_level(key, new_lvl, force=False)
                    event.accept()
                    return

        # Scroll in apps list if > 6 rows
        if len(self._sessions) > self.MAX_VISIBLE_ROWS and self._max_scroll_y > 0.0:
            step = 35.0 if delta < 0 else -35.0
            self._scroll_y = max(0.0, min(self._max_scroll_y, self._scroll_y + step))
            self.update()
            event.accept()
            return

        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
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
                self.hide()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._poll_timer.stop()
        self._master_coalescer.stop()
        self._app_coalescer.stop()
        self._dragging = None
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)


# Alias for backward compatibility / explicit naming
VolumeMixerPopover = VolumePopover
