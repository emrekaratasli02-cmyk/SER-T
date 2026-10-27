"""Ses mikseri paneli — panel_style v2 ortak panel kiti üzerinde (27 Eki 2026, A tasarımı).

- Başlık: 'Ses' + etkileşimli cihaz rozeti ('Hoparlör · Realtek Audio ›') + kapat ×.
- GENEL SES kartı: ana kaydırıcı (SOUND dolgu, gerçek seviye; sessizde 'Sessiz') + sağıda sessiz düğmesi.
- UYGULAMALAR kartı: oturum başına satır — 24 px uygulama ikonu, ad, compact kaydırıcı
  (10 px iz + 14 px tutaç), yüzde, küçük sessiz düğmesi; oynatan uygulamada mavi nokta.
  Boş durum: 'Ses çalan uygulama yok'. 6 satırdan fazlası kaydırılır.
- Alt bilgi: 'Windows ses · HH:MM' + 'Ses ayarları' hayalet düğmesi (ms-settings:apps-volume).
- Ana/AP düzey τ birleştirme: ~40 ms ana, ~60 ms uygulama (ağır iş GUI dışı işçi iş parçacığında).
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


def draw_bell_icon(p: QPainter, rect: QRectF, color: QColor) -> None:
    """Draw small vector bell icon (system sounds row fallback)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    cy = rect.center().y()

    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Dome (top half circle)
    dome = QRectF(cx - 5.0, cy - 6.0, 10.0, 10.0)
    p.drawArc(dome, 0 * 16, 180 * 16)
    # Sides flaring slightly outwards
    p.drawLine(QPointF(cx - 5.0, cy - 1.0), QPointF(cx - 6.5, cy + 4.0))
    p.drawLine(QPointF(cx + 5.0, cy - 1.0), QPointF(cx + 6.5, cy + 4.0))
    # Base rim
    p.drawLine(QPointF(cx - 6.5, cy + 4.0), QPointF(cx + 6.5, cy + 4.0))
    # Clapper
    p.drawLine(QPointF(cx - 1.6, cy + 6.5), QPointF(cx + 1.6, cy + 6.5))
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
# VolumePopover Class (panel_style v2 'Ses' paneli)
# ---------------------------------------------------------------------------

CARD_OVER_H = 25.0    # draw_card üst başlığı: 15 px etiket + 10 px boşluk
MAIN_ROW_H = 46.0     # ana ses kaydırıcı satırı
ROW_H = 38.0          # uygulama satırı (etiket + 10 px iz + 14 px tutaç)
ROW_GAP = 10.0
EMPTY_H = 30.0        # 'Ses çalan uygulama yok'
MAX_VISIBLE_ROWS = 6
WHEEL_STEP = 2.0      # tekerleğin seviye adımı (eski davranış)
MASTER_MUTE_SZ = 28.0
APP_MUTE_SZ = 24.0
EMPTY_APPS_TEXT = "Ses çalan uygulama yok"


def _device_display(device: str) -> str:
    """'Speakers (Realtek(R) Audio)' -> 'Hoparlör · Realtek Audio' (media'dan)."""
    raw = str(device or "").strip()
    if not raw:
        return ""
    if media is not None and hasattr(media, "tr_device_name"):
        try:
            out = str(media.tr_device_name(raw) or "")
            return out or raw
        except Exception:
            return raw
    return raw


def _device_kind(display: str) -> str:
    """'Hoparlör · Realtek Audio' -> 'Hoparlör' (ana kaydırıcı etiketi)."""
    return display.split(" · ", 1)[0].strip() if display else ""


def _sanitize_session(raw: Any, idx: int) -> Dict[str, Any]:
    """Robustly sanitize an audio session dict; unknown level stays None ('—')."""
    if not isinstance(raw, dict):
        return {"key": f"app_{idx}", "name": "Uygulama", "exe": "", "level": None, "muted": False, "active": False}
    key = str(raw.get("key", raw.get("name", "")) or f"app_{idx}")
    nm_raw = raw.get("name")
    name = str(nm_raw).strip() if nm_raw is not None else ""
    level: Optional[float] = None
    if raw.get("level") is not None:
        try:
            f = float(raw["level"])
            if not (math.isnan(f) or math.isinf(f)):
                level = max(0.0, min(100.0, f))
        except (ValueError, TypeError):
            level = None
    return {
        "key": key,
        "name": name or "Uygulama",
        "exe": str(raw.get("exe") or ""),
        "level": level,
        "muted": bool(raw.get("muted", False)),
        "active": bool(raw.get("active", False)),
    }


class VolumePopover(QWidget):
    """'Ses' mikser paneli — panel_style v2 ortak kit (352 px)."""

    WIDTH: int = int(panel_style.WIDTH["vol"])

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
        self._level: Optional[float] = 50.0
        self._muted: bool = False
        self._device: str = ""
        self._stamp: str = "—"

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
        self._hover_master_slider: bool = False
        self._hover_session_mute: Optional[str] = None
        self._hover_session_slider: Optional[str] = None

        # Hit rectangles cache
        self._btn_close_rect = QRectF()
        self._chip_rect = QRectF()
        self._footer_btn_rect = QRectF()
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
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

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

    def _apps_rows_height(self) -> float:
        n = len(self._sessions)
        if n == 0:
            return EMPTY_H
        v = min(n, MAX_VISIBLE_ROWS)
        return v * ROW_H + (v - 1) * ROW_GAP

    def compute_height(self) -> int:
        """Panel yüksekliği kart ölçülerinden hesaplanır."""
        PAD, GAP = panel_style.PAD, panel_style.GAP
        master_card = 2 * panel_style.CARD_PAD + CARD_OVER_H + MAIN_ROW_H
        apps_card = 2 * panel_style.CARD_PAD + CARD_OVER_H + self._apps_rows_height()
        total = PAD + panel_style.HEADER_H + GAP + master_card + GAP + apps_card
        total += GAP + panel_style.FOOTER_H + PAD * 0.5
        return int(math.ceil(total))

    def show_for(
        self,
        anchor_global: Optional[QRectF] = None,
        level: Optional[float] = 50.0,
        muted: bool = False,
        device: str = "",
        *,
        switch_from_x: Optional[int] = None,
    ) -> None:
        """Position above anchor, clamp to screen, and animate in (ortak hareket)."""
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._level = None if level is None else max(0.0, min(100.0, float(level)))
        self._muted = bool(muted)
        self._device = str(device)
        self._stamp = time.strftime("%H:%M")
        self._dragging = None
        self._scroll_y = 0.0
        self._is_closing = False

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
                max_x = geom.right() + 1 - self.width() - margin
                target_x = max(min_x, min(max_x, target_x)) if max_x >= min_x else min_x
                min_y = geom.top() + margin
                max_y = geom.bottom() + 1 - self.height() - margin
                if target_y < min_y:
                    below_y = int(round(self._anchor_global.bottom() + panel_style.ANCHOR_GAP))
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

        panel_style.animate_in(self, target, switch_from_x=switch_from_x)
        self.activateWindow()

        # Start periodic 2s polling and fetch immediately
        self._poll_timer.start(2000)
        self.refresh_sessions()
        self.update()

    def update_volume(self, level: Optional[float], muted: bool, device: Optional[str] = None) -> None:
        """Update master volume level, mute state, and optional device name."""
        self._level = None if level is None else max(0.0, min(100.0, float(level)))
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
        """Hide panel (hard close) and stop timers."""
        self._poll_timer.stop()
        self._master_coalescer.stop()
        self._app_coalescer.stop()
        self._dragging = None
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hide()

    def hide_animated(self) -> None:
        """Close with the shared animate_out motion."""
        if not self.isVisible() or self._is_closing:
            self._is_closing = False
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()
        self._poll_timer.stop()
        self._dragging = None
        panel_style.animate_out(self, on_done=self._on_closed)

    def hide_instant(self) -> None:
        """Close without animation (e.g. switching to another capsule panel)."""
        self._poll_timer.stop()
        self._dragging = None
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._is_closing = False
        panel_style.animate_out(self, on_done=self._on_closed, instant=True)

    def _on_closed(self) -> None:
        self._is_closing = False

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
        for i, s in enumerate(raw_list):
            item = _sanitize_session(s, i)
            if active_drag_key and item["key"] == active_drag_key:
                # Keep currently dragged local level
                for ex in self._sessions:
                    if str(ex.get("key", "")) == active_drag_key:
                        item["level"] = ex.get("level", item.get("level"))
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
            if str(s.get("key", "")) == key:
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
            if str(s.get("key", "")) == key:
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
    # Rendering (offscreen ölçekleme için ortak yol)
    # -----------------------------------------------------------------------

    def render_to_image(self, dpr: float = 2.0) -> Any:
        from PySide6.QtGui import QImage
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
        PAD, GAP = panel_style.PAD, panel_style.GAP
        cw = w - 2.0 * PAD
        panel_style.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))

        # ------------------------------------------------------------------
        # 1. Başlık: 'Ses' + cihaz rozeti ('… ›') + kapat ×
        # ------------------------------------------------------------------
        dev_disp = _device_display(self._device)
        chip = f"{dev_disp} ›" if dev_disp else None
        hdr = panel_style.draw_header(
            p,
            QRectF(PAD, PAD, cw, panel_style.HEADER_H),
            "Ses",
            icon=lambda pp, r: draw_equalizer_icon(pp, r, panel_style.SOUND),
            chip=chip,
            close_hover=self._hover_close,
        )
        self._btn_close_rect = QRectF(hdr["close"]) if hdr.get("close") is not None else QRectF()
        self._chip_rect = QRectF(hdr["chip"]) if hdr.get("chip") is not None else QRectF()

        y = PAD + panel_style.HEADER_H + GAP

        # ------------------------------------------------------------------
        # 2. GENEL SES kartı: ana kaydırıcı + sessiz düğmesi
        # ------------------------------------------------------------------
        master_h = 2 * panel_style.CARD_PAD + CARD_OVER_H + MAIN_ROW_H
        inner = panel_style.draw_card(p, QRectF(PAD, y, cw, master_h), "Genel ses")
        self._paint_master(p, inner)
        y += master_h + GAP

        # ------------------------------------------------------------------
        # 3. UYGULAMALAR kartı: oturum satırları / boş durum / kaydırma
        # ------------------------------------------------------------------
        apps_h = 2 * panel_style.CARD_PAD + CARD_OVER_H + self._apps_rows_height()
        n_sessions = len(self._sessions)
        over_right = (
            panel_style.turkish_upper(f"{n_sessions} uygulama") if n_sessions else None
        )
        inner2 = panel_style.draw_card(
            p, QRectF(PAD, y, cw, apps_h), "Uygulamalar", overline_right=over_right
        )
        self._paint_apps(p, inner2)
        y += apps_h + GAP

        # ------------------------------------------------------------------
        # 4. Alt bilgi: 'Windows ses · HH:MM' + 'Ses ayarları' düğmesi
        # ------------------------------------------------------------------
        btn = panel_style.draw_footer(
            p,
            QRectF(PAD, y, cw, panel_style.FOOTER_H),
            f"Windows ses · {self._stamp}",
            "Ses ayarları",
            button_hover=self._hover_footer,
        )
        self._footer_btn_rect = QRectF(btn) if btn is not None else QRectF()
        assert h >= y + panel_style.FOOTER_H  # yükseklik formülü tutarlı kalmalı

    def _paint_master(self, p: QPainter, inner: QRectF) -> None:
        """GENEL SES satırı: hoparlör ikonu + etiket + % / 'Sessiz', hap iz, sessiz düğmesi."""
        lvl = self._level
        dev_disp = _device_display(self._device)
        main_label = _device_kind(dev_disp) or "—"

        mute_r = QRectF(inner.right() - MASTER_MUTE_SZ, inner.center().y() - MASTER_MUTE_SZ / 2.0,
                        MASTER_MUTE_SZ, MASTER_MUTE_SZ)
        self._hit_master_mute = QRectF(mute_r)

        slider_r = QRectF(inner.left(), inner.top(),
                          max(40.0, mute_r.left() - 10.0 - inner.left()), inner.height())
        hover = self._hover_master_slider or self._dragging == "master"
        res = panel_style.draw_slider(
            p,
            slider_r,
            main_label,
            lvl,
            fill=panel_style.SOUND,
            icon=lambda pp, r: draw_speaker_icon(
                pp, r, panel_style.DANGER if self._muted else panel_style.TEXT_BODY,
                muted=self._muted),
            hover=hover,
            muted=self._muted,
        )
        track = QRectF(res["track"])
        self._hit_master_slider = track.adjusted(-4.0, -10.0, 4.0, 10.0)

        # Sessiz düğmesi (yuvarlak hap)
        p.save()
        p.setPen(QPen(panel_style.BUTTON_BORDER, 1.0))
        p.setBrush(panel_style.BUTTON_HOVER if self._hover_master_mute else panel_style.BUTTON_BG)
        p.drawPath(panel_style.rounded(mute_r.adjusted(0.5, 0.5, -0.5, -0.5), panel_style.R_BUTTON))
        mute_icon_col = panel_style.DANGER if self._muted else (
            panel_style.TEXT if self._hover_master_mute else panel_style.TEXT_BODY)
        draw_speaker_icon(p, mute_r, mute_icon_col, muted=self._muted)
        p.restore()

    def _paint_apps(self, p: QPainter, inner: QRectF) -> None:
        """UYGULAMALAR satırları; boş durum metni; 6 satırdan fazlası kaydırılır."""
        n = len(self._sessions)
        self._hit_app_rows = []
        content_r = QRectF(inner)

        if n == 0:
            p.setFont(panel_style.f_body())
            p.setPen(panel_style.TEXT_MUTED)
            p.drawText(content_r, Qt.AlignmentFlag.AlignCenter, EMPTY_APPS_TEXT)
            return

        total_content_h = n * ROW_H + (n - 1) * ROW_GAP
        self._max_scroll_y = max(0.0, total_content_h - content_r.height())
        self._scroll_y = max(0.0, min(self._max_scroll_y, self._scroll_y))

        p.save()
        p.setClipRect(content_r)

        for i, session in enumerate(self._sessions):
            row_y = content_r.top() + i * (ROW_H + ROW_GAP) - self._scroll_y
            if row_y + ROW_H < content_r.top() or row_y > content_r.bottom():
                continue

            key = str(session["key"])
            name = str(session["name"])
            exe = str(session["exe"])
            level = session["level"]
            muted = bool(session["muted"])
            active = bool(session["active"])

            # 24 px uygulama ikonu (gerçek ikon; yoksa harf dolgusu / zil)
            icon_r = QRectF(content_r.left(), row_y + (ROW_H - 24.0) / 2.0, 24.0, 24.0)
            pix = QPixmap()
            if exe and winapi and hasattr(winapi, "app_icon"):
                try:
                    pix = winapi.app_icon(exe, 32)
                except Exception:
                    pix = QPixmap()
            if pix is not None and not pix.isNull():
                p.drawPixmap(icon_r.toRect(), pix)
            else:
                if key == "system" or name == "Sistem sesleri":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(panel_style.BUTTON_BG)
                    p.drawEllipse(icon_r)
                    draw_bell_icon(p, icon_r, panel_style.TEXT_BODY)
                else:
                    draw_fallback_app_icon(p, icon_r, name)

            # 'Özel çalıyor' mavi nokta (ikonun sağ üst köşesinde)
            if active:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                glow = QColor(panel_style.SOUND)
                glow.setAlpha(90)
                p.setBrush(glow)
                p.drawEllipse(QPointF(icon_r.right() - 2.0, icon_r.top() + 2.0), 5.0, 5.0)
                p.setBrush(panel_style.SOUND)
                p.drawEllipse(QPointF(icon_r.right() - 2.0, icon_r.top() + 2.0), 3.0, 3.0)
                p.restore()

            # Küçük sessiz düğmesi (sağda)
            mute_r = QRectF(content_r.right() - APP_MUTE_SZ,
                            row_y + (ROW_H - APP_MUTE_SZ) / 2.0, APP_MUTE_SZ, APP_MUTE_SZ)
            hover_mute = (self._hover_session_mute == key)
            p.save()
            p.setPen(QPen(panel_style.BUTTON_BORDER, 1.0))
            p.setBrush(panel_style.BUTTON_HOVER if hover_mute else panel_style.BUTTON_BG)
            p.drawPath(panel_style.rounded(mute_r.adjusted(0.5, 0.5, -0.5, -0.5), panel_style.R_BUTTON))
            icon_mute_col = panel_style.DANGER if muted else (
                panel_style.TEXT if hover_mute else panel_style.TEXT_MUTED)
            draw_speaker_icon(p, mute_r, icon_mute_col, muted=muted)
            p.restore()

            # Compact kaydırıcı (10 px iz + 14 px tutaç); yüzde etiket satırının sağında
            slider_left = icon_r.right() + 10.0
            slider_r = QRectF(slider_left, row_y,
                              max(30.0, mute_r.left() - 10.0 - slider_left), ROW_H)
            hover_row = (self._hover_session_slider == key) or (self._dragging == f"app:{key}")
            res = panel_style.draw_slider(
                p, slider_r, name, level, fill=panel_style.SOUND, muted=muted, hover=hover_row,
                compact=True,
            )
            track = QRectF(res["track"])
            self._hit_app_rows.append({
                "key": key,
                "row_rect": QRectF(content_r.left(), row_y, content_r.width(), ROW_H),
                "track_rect": track,
                "track": track,
                "slider_rect": track.adjusted(-4.0, -4.0, 4.0, 4.0),
                "hit_rect": track.adjusted(-4.0, -4.0, 4.0, 4.0),
                "mute_rect": QRectF(mute_r),
                "level": level,
                "muted": muted,
            })

        p.restore()

        # Kaydırma göstergesi
        if n > MAX_VISIBLE_ROWS and self._max_scroll_y > 0.0:
            sb_w = 3.0
            sb_x = content_r.right() + 4.0
            sb_track_h = content_r.height()
            sb_thumb_h = max(24.0, (content_r.height() / total_content_h) * sb_track_h)
            sb_thumb_y = content_r.top() + (self._scroll_y / self._max_scroll_y) * (sb_track_h - sb_thumb_h)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawPath(panel_style.rounded(QRectF(sb_x, sb_thumb_y, sb_w, sb_thumb_h), 1.5))
            p.restore()

    # -----------------------------------------------------------------------
    # Interactive Events
    # -----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()

            # Kapat ×
            if self._btn_close_rect.contains(pos):
                self.hide_animated()
                event.accept()
                return

            # Cihaz rozeti ('›'): bugünkü ayar eylemi — Windows ses ayarları
            if self._chip_rect.contains(pos):
                self._open_windows_sound_settings()
                event.accept()
                return

            # Alt bilgi düğmesi: 'Ses ayarları'
            if self._footer_btn_rect.contains(pos):
                self._open_windows_sound_settings()
                event.accept()
                return

            # Ana sessiz düğmesi
            if self._hit_master_mute.contains(pos):
                self.toggle_master_mute()
                event.accept()
                return

            # Ana kaydırıcı
            if self._hit_master_slider.contains(pos):
                self._dragging = "master"
                value = panel_style.slider_value_at(self._hit_master_slider, pos.x())
                self._request_master_volume(value, force=False)
                event.accept()
                return

            # Uygulama satırları
            for row in self._hit_app_rows:
                key = row["key"]
                if row["mute_rect"].contains(pos):
                    self.toggle_session_mute(key)
                    event.accept()
                    return
                if row["slider_rect"].contains(pos):
                    self._dragging = f"app:{key}"
                    value = panel_style.slider_value_at(row["track_rect"], pos.x())
                    self._request_session_level(key, value, force=False)
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self._dragging == "master":
            value = panel_style.slider_value_at(self._hit_master_slider, pos.x())
            self._request_master_volume(value, force=False)
            event.accept()
            return

        if self._dragging and self._dragging.startswith("app:"):
            key = self._dragging.split(":", 1)[1]
            for row in self._hit_app_rows:
                if row["key"] == key:
                    value = panel_style.slider_value_at(row["track_rect"], pos.x())
                    self._request_session_level(key, value, force=False)
                    break
            event.accept()
            return

        # Hover durumları
        hover_close = self._btn_close_rect.contains(pos)
        hover_footer = self._footer_btn_rect.contains(pos)
        hover_master_mute = self._hit_master_mute.contains(pos)
        hover_master_slider = self._hit_master_slider.contains(pos)

        hover_session_mute: Optional[str] = None
        hover_session_slider: Optional[str] = None
        for row in self._hit_app_rows:
            if row["mute_rect"].contains(pos):
                hover_session_mute = row["key"]
            if row["slider_rect"].contains(pos):
                hover_session_slider = row["key"]

        needs_update = (
            hover_close != self._hover_close
            or hover_footer != self._hover_footer
            or hover_master_mute != self._hover_master_mute
            or hover_master_slider != self._hover_master_slider
            or hover_session_mute != self._hover_session_mute
            or hover_session_slider != self._hover_session_slider
        )

        self._hover_close = hover_close
        self._hover_footer = hover_footer
        self._hover_master_mute = hover_master_mute
        self._hover_master_slider = hover_master_slider
        self._hover_session_mute = hover_session_mute
        self._hover_session_slider = hover_session_slider

        # Cursor shaping
        if any((hover_close, hover_footer, hover_master_mute, hover_master_slider,
                hover_session_mute is not None, hover_session_slider is not None)):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

        if needs_update:
            self.update()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_close = False
        self._hover_footer = False
        self._hover_master_mute = False
        self._hover_master_slider = False
        self._hover_session_mute = None
        self._hover_session_slider = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging == "master":
                self._request_master_volume(self._level if self._level is not None else 0.0, force=True)
                self._dragging = None
                event.accept()
                return

            if self._dragging and self._dragging.startswith("app:"):
                key = self._dragging.split(":", 1)[1]
                cur_lvl = 50.0
                for s in self._sessions:
                    if str(s.get("key", "")) == key:
                        cur_lvl = float(s.get("level") if s.get("level") is not None else 50.0)
                        break
                self._request_session_level(key, cur_lvl, force=True)
                self._dragging = None
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        pos = event.position()
        delta = event.angleDelta().y()
        diff = WHEEL_STEP if delta > 0 else -WHEEL_STEP

        # Ana kaydırıcı tekerleği
        if self._hit_master_slider.contains(pos):
            if self._level is not None:
                new_lvl = max(0.0, min(100.0, self._level + diff))
                self._request_master_volume(new_lvl, force=False)
            event.accept()
            return

        # Uygulama kaydırıcı tekerleği (sıkı isabet; boşluktan liste kaydırılır)
        for row in self._hit_app_rows:
            if row["slider_rect"].contains(pos):
                key = row["key"]
                base = row["level"] if row["level"] is not None else None
                if base is not None:
                    new_lvl = max(0.0, min(100.0, float(base) + diff))
                    self._request_session_level(key, new_lvl, force=False)
                event.accept()
                return

        # 6 satırdan fazla ise liste kaydır
        if len(self._sessions) > MAX_VISIBLE_ROWS and self._max_scroll_y > 0.0:
            step = 35.0 if delta < 0 else -35.0
            self._scroll_y = max(0.0, min(self._max_scroll_y, self._scroll_y + step))
            self.update()
            event.accept()
            return

        super().wheelEvent(event)

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
        self._poll_timer.stop()
        self._master_coalescer.stop()
        self._app_coalescer.stop()
        self._dragging = None
        self._last_close_time = time.monotonic()
        self._is_closing = False
        super().hideEvent(event)


# Alias for backward compatibility / explicit naming
VolumeMixerPopover = VolumePopover
