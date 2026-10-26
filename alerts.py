"""alerts.py - Proactive acrylic glass notification toasts and rule engine for Şerit.

Evaluates live telemetry from Claude usage, FX markets, and system memory to surface
timely, glanceable glass toasts before the user actively opens the dock.
Zero focus stealing, hardware-accelerated acrylic styling, and persistent state dedup.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Union

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Ensure serit directory is importable
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

import sources
import theme
import winapi

DEFAULT_STATE_PATH = Path("D:/Apps/serit/alerts_state.json")

# Visual & Geometry Tokens
TOAST_WIDTH: int = 320
TOAST_RADIUS: float = 16.0
TOAST_MARGIN_SCREEN: int = 16
TOAST_STACK_GAP: int = 8
MAX_ACTIVE_TOASTS: int = 3

COLOR_ALERT_WARN = QColor("#FFC45C")  # Amber (Claude / FX warn)
COLOR_ALERT_CRIT = QColor("#FF6E6E")  # Coral Red (Critical / RAM / FX drop)
COLOR_ALERT_GROWTH = QColor("#78DC96")  # Mint Green (FX up)


# ==============================================================================
# 1. ALERT DATA MODEL
# ==============================================================================


class Alert(dict):
    """Notification alert payload supporting both dict access and attribute properties."""

    def __init__(
        self,
        id: str,
        title: str,
        body: str,
        accent: str,
        kind: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            id=id,
            title=title,
            body=body,
            accent=accent,
            kind=kind,
            **kwargs,
        )

    @property
    def id(self) -> str:
        return str(self.get("id", ""))

    @property
    def title(self) -> str:
        return str(self.get("title", ""))

    @property
    def body(self) -> str:
        return str(self.get("body", ""))

    @property
    def accent(self) -> str:
        return str(self.get("accent", "#FFC45C"))

    @property
    def kind(self) -> str:
        return str(self.get("kind", "general"))


# ==============================================================================
# 2. ALERT ENGINE
# ==============================================================================


class AlertEngine:
    """Evaluates telemetry data against rules, dedupes per period, and enforces quiet limits."""

    def __init__(
        self,
        state_path: Union[str, Path] = DEFAULT_STATE_PATH,
        enabled: bool = True,
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled: bool = bool(enabled)

        self._fired_ids: Dict[str, float] = {}
        self._last_toast_time: Optional[float] = None
        self._queue: List[Alert] = []
        self._ram_high_timestamps: List[float] = []

        self._load_state()

    @property
    def queue(self) -> List[Alert]:
        """Current pending alerts waiting for quiet period cooldown."""
        return list(self._queue)

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    def reset_state(self) -> None:
        """Clear all historical deduplication IDs, queues, and RAM sample streaks."""
        self._fired_ids.clear()
        self._last_toast_time = None
        self._queue.clear()
        self._ram_high_timestamps.clear()
        self._save_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
            if isinstance(data, dict):
                self._fired_ids = {
                    str(k): float(v) for k, v in data.get("fired_ids", {}).items()
                }
                last_t = data.get("last_toast_time")
                self._last_toast_time = float(last_t) if last_t is not None else None
                self._queue = [
                    Alert(**item)
                    for item in data.get("queue", [])
                    if isinstance(item, dict)
                ]
                self._ram_high_timestamps = [
                    float(t) for t in data.get("ram_high_timestamps", [])
                ]
        except Exception:
            # Fallback gracefully to empty state if file corrupt
            pass

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "fired_ids": self._fired_ids,
                "last_toast_time": self._last_toast_time,
                "queue": [dict(a) for a in self._queue],
                "ram_high_timestamps": self._ram_high_timestamps,
            }
            tmp_path = self.state_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(self.state_path)
        except Exception:
            pass

    def _extract_valid_entry(
        self,
        store: Any,
        key: str,
    ) -> Optional[Dict[str, Any]]:
        """Safely extract entry, returning None if missing, stale, or marked with error."""
        entry: Any = None
        if hasattr(store, "get"):
            entry = store.get(key)
        elif isinstance(store, dict):
            entry = store.get(key)

        if not isinstance(entry, dict):
            return None

        # Ignore stale entries or entries carrying fetch errors
        if entry.get("stale") is True or bool(entry.get("err")):
            return None

        return entry

    def evaluate(
        self,
        store: Any,
        now: Optional[float] = None,
    ) -> List[Alert]:
        """Evaluate store telemetry and return eligible alerts respecting quiet cooldown."""
        if not self.enabled:
            return []

        eval_time = time.time() if now is None else float(now)
        new_alerts: List[Alert] = []

        # ----------------------------------------------------------------------
        # Rule 1 & 2: Claude Session & Weekly Rules
        # ----------------------------------------------------------------------
        claude = self._extract_valid_entry(store, "claude")
        if claude is not None:
            session_raw = claude.get("session", 0.0)
            session = float(session_raw if session_raw is not None else 0.0)
            session_reset = str(claude.get("session_reset", "") or "").strip()
            period_sess = session_reset if session_reset else "active"

            # Threshold >= 95%
            if session >= 95.0:
                aid_95 = f"claude_session_95_{period_sess}"
                aid_80 = f"claude_session_80_{period_sess}"
                if aid_95 not in self._fired_ids:
                    left = sources.left_text(session_reset) if session_reset else ""
                    clock = sources.reset_clock(session_reset) if session_reset else ""
                    if left and clock:
                        body = f"Sıfırlanmaya {left} ({clock})."
                    else:
                        body = "Kullanım kritik seviyede (%95+)."
                    title = f"Claude oturumu %{int(round(session))}"
                    new_alerts.append(
                        Alert(
                            id=aid_95,
                            title=title,
                            body=body,
                            accent="#FF6E6E",
                            kind="claude",
                        )
                    )
                    self._fired_ids[aid_95] = eval_time
                    self._fired_ids[aid_80] = eval_time
            # Threshold >= 80% (and < 95%)
            elif session >= 80.0:
                aid_80 = f"claude_session_80_{period_sess}"
                if aid_80 not in self._fired_ids:
                    left = sources.left_text(session_reset) if session_reset else ""
                    clock = sources.reset_clock(session_reset) if session_reset else ""
                    if left and clock:
                        body = f"Sıfırlanmaya {left} ({clock})."
                    else:
                        body = "Kullanım yüksek seviyede (%80+)."
                    title = f"Claude oturumu %{int(round(session))}"
                    new_alerts.append(
                        Alert(
                            id=aid_80,
                            title=title,
                            body=body,
                            accent="#FFC45C",
                            kind="claude",
                        )
                    )
                    self._fired_ids[aid_80] = eval_time

            # Claude weekly >= 80% (period = week_reset)
            week_raw = claude.get("week", 0.0)
            week = float(week_raw if week_raw is not None else 0.0)
            week_reset = str(claude.get("week_reset", "") or "").strip()
            period_week = week_reset if week_reset else "active"
            if week >= 80.0:
                aid_week = f"claude_week_80_{period_week}"
                if aid_week not in self._fired_ids:
                    left = sources.left_text(week_reset) if week_reset else ""
                    clock = sources.reset_clock(week_reset) if week_reset else ""
                    if left and clock:
                        body = f"Sıfırlanmaya {left} ({clock})."
                    else:
                        body = "Haftalık kullanım yüksek (%80+)."
                    title = f"Claude haftalık %{int(round(week))}"
                    new_alerts.append(
                        Alert(
                            id=aid_week,
                            title=title,
                            body=body,
                            accent="#FFC45C",
                            kind="claude",
                        )
                    )
                    self._fired_ids[aid_week] = eval_time

        # ----------------------------------------------------------------------
        # Rule 3: FX Market Daily Changes (|change| thresholds)
        # ----------------------------------------------------------------------
        fx = self._extract_valid_entry(store, "fx")
        if fx is not None:
            dt_now = dt.datetime.fromtimestamp(eval_time, sources.LOCAL_TZ)
            today_str = dt_now.strftime("%Y-%m-%d")
            updated_raw = str(fx.get("updated", "") or "").strip()
            source_time = updated_raw if updated_raw else dt_now.strftime("%H:%M")

            # USD: |daily change| >= 1.0%
            usd_val = float(fx.get("usd", 0.0) or 0.0)
            usd_chg = float(fx.get("usd_chg", 0.0) or 0.0)
            if abs(usd_chg) >= 1.0 and usd_val > 0.0:
                direction = "up" if usd_chg > 0 else "down"
                aid_usd = f"fx_usd_{today_str}_{direction}"
                if aid_usd not in self._fired_ids:
                    dir_tr = "artış" if usd_chg > 0 else "düşüş"
                    title = f"Dolar %{sources.fmt_tr(abs(usd_chg), 2)} {dir_tr}"
                    body = f"1 USD = {sources.fmt_tr(usd_val, 2)} TL · Güncelleme: {source_time}"
                    accent = "#78DC96" if usd_chg > 0 else "#FF6E6E"
                    new_alerts.append(
                        Alert(
                            id=aid_usd,
                            title=title,
                            body=body,
                            accent=accent,
                            kind="fx",
                        )
                    )
                    self._fired_ids[aid_usd] = eval_time

            # EUR: |daily change| >= 1.0%
            eur_val = float(fx.get("eur", 0.0) or 0.0)
            eur_chg = float(fx.get("eur_chg", 0.0) or 0.0)
            if abs(eur_chg) >= 1.0 and eur_val > 0.0:
                direction = "up" if eur_chg > 0 else "down"
                aid_eur = f"fx_eur_{today_str}_{direction}"
                if aid_eur not in self._fired_ids:
                    dir_tr = "artış" if eur_chg > 0 else "düşüş"
                    title = f"Euro %{sources.fmt_tr(abs(eur_chg), 2)} {dir_tr}"
                    body = f"1 EUR = {sources.fmt_tr(eur_val, 2)} TL · Güncelleme: {source_time}"
                    accent = "#78DC96" if eur_chg > 0 else "#FF6E6E"
                    new_alerts.append(
                        Alert(
                            id=aid_eur,
                            title=title,
                            body=body,
                            accent=accent,
                            kind="fx",
                        )
                    )
                    self._fired_ids[aid_eur] = eval_time

            # Gram Altın: |daily change| >= 2.0%
            gold_val = float(fx.get("gold", 0.0) or 0.0)
            gold_chg = float(fx.get("gold_chg", 0.0) or 0.0)
            if abs(gold_chg) >= 2.0 and gold_val > 0.0:
                direction = "up" if gold_chg > 0 else "down"
                aid_gold = f"fx_gold_{today_str}_{direction}"
                if aid_gold not in self._fired_ids:
                    dir_tr = "artış" if gold_chg > 0 else "düşüş"
                    title = f"Gram Altın %{sources.fmt_tr(abs(gold_chg), 2)} {dir_tr}"
                    body = f"1 g = {sources.fmt_tr(gold_val, 2)} TL · Güncelleme: {source_time}"
                    accent = "#78DC96" if gold_chg > 0 else "#FF6E6E"
                    new_alerts.append(
                        Alert(
                            id=aid_gold,
                            title=title,
                            body=body,
                            accent=accent,
                            kind="fx",
                        )
                    )
                    self._fired_ids[aid_gold] = eval_time

        # ----------------------------------------------------------------------
        # Rule 4: System RAM Rule (>=92% for 3 samples spaced >=55s, period = hour)
        # ----------------------------------------------------------------------
        sys_entry = self._extract_valid_entry(store, "sys")
        if sys_entry is not None:
            ram = float(sys_entry.get("ram", 0.0) or 0.0)
            ram_used = float(sys_entry.get("ram_used_gb", 0.0) or 0.0)
            ram_total = float(sys_entry.get("ram_total_gb", 0.0) or 0.0)

            if ram >= 92.0:
                if not self._ram_high_timestamps:
                    self._ram_high_timestamps.append(eval_time)
                else:
                    last_t = self._ram_high_timestamps[-1]
                    if (eval_time - last_t) >= 55.0:
                        self._ram_high_timestamps.append(eval_time)

                if len(self._ram_high_timestamps) >= 3:
                    dt_now = dt.datetime.fromtimestamp(eval_time, sources.LOCAL_TZ)
                    hour_str = dt_now.strftime("%Y-%m-%d-%H")
                    aid_ram = f"sys_ram_92_{hour_str}"
                    if aid_ram not in self._fired_ids:
                        title = f"Bellek kullanımı %{int(round(ram))}"
                        if ram_used > 0 and ram_total > 0:
                            body = f"RAM son 3 kontrolde %92 üzerinde ({sources.fmt_tr(ram_used, 1)}\u00A0/\u00A0{sources.fmt_tr(ram_total, 1)}\u00A0GB)."
                        else:
                            body = "RAM son 3 kontrolde %92 üzerinde seyrediyor."
                        new_alerts.append(
                            Alert(
                                id=aid_ram,
                                title=title,
                                body=body,
                                accent="#FF6E6E",
                                kind="sys",
                            )
                        )
                        self._fired_ids[aid_ram] = eval_time
            else:
                # Streak broken when RAM drops below threshold
                self._ram_high_timestamps.clear()

        # Enqueue newly generated alerts
        for alert in new_alerts:
            self._queue.append(alert)

        # ----------------------------------------------------------------------
        # Global Quiet Rule: At most 1 toast per 120s, queue the rest
        # ----------------------------------------------------------------------
        delivered: List[Alert] = []
        if self._queue:
            if (
                self._last_toast_time is None
                or (eval_time - self._last_toast_time) >= 120.0
            ):
                toast_alert = self._queue.pop(0)
                self._last_toast_time = eval_time
                delivered.append(toast_alert)

        self._save_state()
        return delivered


# ==============================================================================
# 3. TOAST WINDOW (Acrylic Glass Notification Card)
# ==============================================================================


class Toast(QWidget):
    """Frameless acrylic glass notification toast card.

    Features zero-focus stealing (ShowWithoutActivating, WindowDoesNotAcceptFocus),
    interactive hover pause, slide-up entrance easing, and offscreen high-DPI rendering.
    """

    WIDTH: int = TOAST_WIDTH
    RADIUS: float = TOAST_RADIUS

    def __init__(
        self,
        alert: Union[Alert, Dict[str, Any]],
        on_click: Optional[Callable[[Alert], None]] = None,
        on_dismiss: Optional[Callable[[Toast], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        if isinstance(alert, dict) and not isinstance(alert, Alert):
            self.alert = Alert(**alert)
        else:
            self.alert = alert

        self._on_click = on_click
        self._on_dismiss = on_dismiss

        # Interaction & Animation states
        self._is_hovered: bool = False
        self._close_hovered: bool = False
        self._close_rect = QRectF(self.WIDTH - 28.0, 10.0, 18.0, 18.0)
        self._is_dismissing: bool = False

        self._target_x: int = 0
        self._target_y: int = 0
        self._anim_opacity: float = 1.0
        self._slide_offset_y: float = 0.0

        # Animations
        self._enter_anim = QVariantAnimation(self)
        self._enter_anim.setDuration(220)
        self._enter_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._enter_anim.setStartValue(0.0)
        self._enter_anim.setEndValue(1.0)
        self._enter_anim.valueChanged.connect(self._on_enter_anim_step)
        self._enter_anim.finished.connect(self._on_enter_anim_done)

        self._exit_anim = QVariantAnimation(self)
        self._exit_anim.setDuration(180)
        self._exit_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._exit_anim.setStartValue(1.0)
        self._exit_anim.setEndValue(0.0)
        self._exit_anim.valueChanged.connect(self._on_exit_anim_step)
        self._exit_anim.finished.connect(self._on_exit_anim_done)

        self._slide_anim = QVariantAnimation(self)
        self._slide_anim.setDuration(180)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.valueChanged.connect(self._on_slide_anim_step)

        # 8-second auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)
        self._timer_deadline: float = 0.0
        self._remaining_dismiss_ms: int = 8000

        # High-DPI Fonts
        self.f_title = theme.make_font(13.0, QFont.Weight.DemiBold)
        self.f_body = theme.make_font(11.5, QFont.Weight.Normal)
        self.f_footer = theme.make_font(10.0, QFont.Weight.Normal)
        self.f_glyph = theme.make_font(12.0, QFont.Weight.Bold)

        # Dynamic height calculation
        h = self.compute_height()
        self.resize(self.WIDTH, h)

    def compute_height(self) -> int:
        """Calculate optimal card height based on text wrapping."""
        fm = QFontMetricsF(self.f_body)
        avail_w = self.WIDTH - 54.0 - 18.0
        bounds = fm.boundingRect(
            QRectF(0, 0, avail_w, 300.0),
            Qt.TextWordWrap,
            self.alert.body,
        )
        body_h = max(18.0, bounds.height())
        total_h = 14.0 + 18.0 + 4.0 + body_h + 4.0 + 14.0 + 14.0
        return int(math.ceil(total_h))

    def _get_glyph(self) -> str:
        """Return category glyph symbol for visual badge."""
        k = str(self.alert.kind).lower()
        if "claude" in k:
            return "✦"
        if "fx" in k:
            t = self.alert.title.lower()
            if "altın" in t or "gold" in self.alert.id:
                return "●"
            if "euro" in t or "eur" in self.alert.id:
                return "€"
            return "$"
        if "sys" in k or "ram" in k:
            return "⚡"
        return "●"

    def show_toast(self, x: int, y: int) -> None:
        """Position and show toast with 10px slide-up enter transition."""
        self._target_x = x
        self._target_y = y
        self._slide_offset_y = 10.0
        self._anim_opacity = 0.0
        self.setWindowOpacity(0.0)
        self.move(x, y + 10)
        self.show()

        hwnd = int(self.winId())
        try:
            winapi.enable_acrylic(hwnd, 0x50181612)
            dpr = self.devicePixelRatioF()
            winapi.set_round_region(
                hwnd, self.width(), self.height(), int(self.RADIUS), dpr
            )
        except Exception:
            pass

        self._enter_anim.stop()
        self._enter_anim.start()

    def reposition(self, x: int, y: int) -> None:
        """Smoothly restack toast to new screen position."""
        if not self.isVisible():
            self.show_toast(x, y)
            return

        self._target_x = x
        start_y = self.y()
        self._target_y = y

        if start_y == y and self.x() == x:
            return

        self._slide_anim.stop()
        self._slide_anim.setStartValue(float(start_y))
        self._slide_anim.setEndValue(float(y))
        self._slide_anim.start()

    def _on_slide_anim_step(self, val: float) -> None:
        self.move(self._target_x, int(round(val)))

    def _on_enter_anim_step(self, val: float) -> None:
        self._anim_opacity = val
        self._slide_offset_y = (1.0 - val) * 10.0
        self.setWindowOpacity(val)
        self.move(self._target_x, int(round(self._target_y + self._slide_offset_y)))
        self.update()

    def _on_enter_anim_done(self) -> None:
        self.move(self._target_x, self._target_y)
        self.setWindowOpacity(1.0)
        self._timer_deadline = time.time() + 8.0
        self._dismiss_timer.start(8000)

    def dismiss(self) -> None:
        """Fade out and close toast."""
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._dismiss_timer.stop()
        self._enter_anim.stop()
        self._slide_anim.stop()
        self._exit_anim.stop()
        self._exit_anim.setStartValue(self.windowOpacity())
        self._exit_anim.setEndValue(0.0)
        self._exit_anim.start()

    def _on_exit_anim_step(self, val: float) -> None:
        self._anim_opacity = val
        self.setWindowOpacity(val)
        self.update()

    def _on_exit_anim_done(self) -> None:
        self.close()
        if callable(self._on_dismiss):
            try:
                self._on_dismiss(self)
            except Exception:
                pass
        self.deleteLater()

    # --------------------------------------------------------------------------
    # Event Handlers
    # --------------------------------------------------------------------------

    def enterEvent(self, event: Any) -> None:
        self._is_hovered = True
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
            rem_sec = max(0.5, self._timer_deadline - time.time())
            self._remaining_dismiss_ms = int(rem_sec * 1000)
        self.update()
        try:
            super().enterEvent(event)
        except Exception:
            pass

    def leaveEvent(self, event: Any) -> None:
        self._is_hovered = False
        self._close_hovered = False
        if not self._is_dismissing:
            rem = max(1500, self._remaining_dismiss_ms)
            self._timer_deadline = time.time() + (rem / 1000.0)
            self._dismiss_timer.start(rem)
        self.update()
        try:
            super().leaveEvent(event)
        except Exception:
            pass

    def mouseMoveEvent(self, event: Any) -> None:
        pos = event.position()
        was_close = self._close_hovered
        self._close_hovered = self._close_rect.contains(pos)
        if was_close != self._close_hovered:
            self.update()
        try:
            super().mouseMoveEvent(event)
        except Exception:
            pass

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._close_rect.contains(pos):
                self.dismiss()
            else:
                if callable(self._on_click):
                    try:
                        self._on_click(self.alert)
                    except Exception:
                        pass
                self.dismiss()
        try:
            super().mousePressEvent(event)
        except Exception:
            pass

    def paintEvent(self, event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_toast(p, QRectF(0, 0, self.width(), self.height()))
        p.end()

    # --------------------------------------------------------------------------
    # Drawing & Offscreen Render
    # --------------------------------------------------------------------------

    def _paint_toast(self, p: QPainter, rect: QRectF) -> None:
        # 1. Physical acrylic glass capsule background
        bg_tint = QColor(18, 22, 30, 230)
        theme.draw_glass_capsule(
            p,
            rect,
            radius=self.RADIUS,
            is_hovered=self._is_hovered,
            bg_tint=bg_tint,
            show_grain=False,
            show_specular=True,
            show_outer_stroke=True,
        )

        accent_col = QColor(self.alert.accent)

        # 2. Left vertical accent indicator bar (docked flush against card curved edge)
        p.save()
        p.setClipPath(theme.rounded_path(rect, self.RADIUS))
        p.fillRect(QRectF(0.0, 0.0, 4.0, rect.height()), accent_col)
        p.restore()

        # 3. Left category icon badge (frosted glass container vertically centered)
        badge_w = 28.0
        badge_h = 28.0
        badge_y = (rect.height() - badge_h) / 2.0
        badge_rect = QRectF(16.0, badge_y, badge_w, badge_h)
        badge_bg = QColor(255, 255, 255, 20)
        p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 75), 1.0))
        p.setBrush(badge_bg)
        p.drawRoundedRect(badge_rect, 8.0, 8.0)

        # Inner glyph symbol
        p.setFont(self.f_glyph)
        p.setPen(accent_col)
        glyph = self._get_glyph()
        p.drawText(badge_rect, Qt.AlignCenter, glyph)

        # 4. Title text (13px semibold)
        p.setFont(self.f_title)
        p.setPen(theme.COLOR_TEXT_PRIMARY)
        title_rect = QRectF(54.0, 14.0, rect.width() - 54.0 - 32.0, 18.0)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.alert.title)

        # 5. Body text (11.5px regular, secondary)
        p.setFont(self.f_body)
        p.setPen(theme.COLOR_TEXT_SECONDARY)
        body_rect = QRectF(
            54.0, 34.0, rect.width() - 54.0 - 18.0, rect.height() - 34.0 - 22.0
        )
        p.drawText(body_rect, Qt.AlignLeft | Qt.TextWordWrap, self.alert.body)

        # 6. Small 'Şerit · HH:MM' line (high contrast legible footer)
        p.setFont(self.f_footer)
        p.setPen(QColor(255, 255, 255, 155))
        now_clock = dt.datetime.now(sources.LOCAL_TZ).strftime("%H:%M")
        footer_text = f"Şerit · {now_clock}"
        footer_rect = QRectF(
            54.0, rect.height() - 22.0, rect.width() - 54.0 - 18.0, 14.0
        )
        p.drawText(footer_rect, Qt.AlignLeft | Qt.AlignVCenter, footer_text)

        # 7. Small '×' close button (vertically aligned with title center)
        close_cy = title_rect.center().y()
        self._close_rect = QRectF(rect.width() - 28.0, close_cy - 9.0, 18.0, 18.0)
        if self._close_hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 32))
            p.drawRoundedRect(self._close_rect, 9.0, 9.0)
            p.setPen(QPen(QColor(255, 255, 255, 240), 1.4, Qt.SolidLine, Qt.RoundCap))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 140), 1.3, Qt.SolidLine, Qt.RoundCap))

        cx = self._close_rect.center().x()
        cy = self._close_rect.center().y()
        d = 3.5
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current toast offscreen to a high-DPI ARGB32 QImage."""
        w = self.width()
        h = self.height()
        img = QImage(
            int(round(w * dpr)),
            int(round(h * dpr)),
            QImage.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        saved_hover = self._is_hovered
        saved_close = self._close_hovered
        self._is_hovered = False
        self._close_hovered = False

        self._paint_toast(p, QRectF(0, 0, w, h))

        self._is_hovered = saved_hover
        self._close_hovered = saved_close

        p.end()
        return img


# ==============================================================================
# 4. TOAST MANAGER
# ==============================================================================


class ToastManager(QObject):
    """Coordinates and stacks active Toast notification cards."""

    def __init__(self, on_click: Optional[Callable[[Alert], None]] = None) -> None:
        super().__init__()
        self._active_toasts: List[Toast] = []
        self._on_click = on_click
        self._max_toasts: int = MAX_ACTIVE_TOASTS
        self._margin: int = TOAST_MARGIN_SCREEN
        self._gap: int = TOAST_STACK_GAP

    @property
    def active_toasts(self) -> List[Toast]:
        return list(self._active_toasts)

    def show(self, alert: Union[Alert, Dict[str, Any]]) -> Toast:
        """Show new notification toast, stacking up to 3 cards upward."""
        if isinstance(alert, dict) and not isinstance(alert, Alert):
            alert = Alert(**alert)

        # Evict oldest toast if capacity reached
        while len(self._active_toasts) >= self._max_toasts:
            oldest = self._active_toasts.pop(0)
            oldest.dismiss()

        toast = Toast(
            alert,
            on_click=self._on_click,
            on_dismiss=self._on_toast_dismissed,
        )
        self._active_toasts.append(toast)
        self._restack()
        return toast

    def _on_toast_dismissed(self, toast: Toast) -> None:
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)
            self._restack()

    def _restack(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
        else:
            avail = QRect(0, 0, 1536, 864)

        base_y = avail.bottom() - self._margin
        current_y = base_y

        # Stack upward: newest toast at bottom, previous ones above
        for toast in reversed(self._active_toasts):
            h = toast.height()
            target_x = avail.right() - self._margin - toast.width()
            target_y = current_y - h
            toast.reposition(target_x, target_y)
            current_y = target_y - self._gap

    def dismiss_all(self) -> None:
        """Dismiss all active toasts immediately."""
        for t in list(self._active_toasts):
            t.dismiss()
        self._active_toasts.clear()
