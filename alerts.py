"""alerts.py - Proactive acrylic glass notification toasts and rule engine for Şerit.

Evaluates live telemetry from Claude usage, FX markets, and system memory to surface
timely, glanceable glass toasts before the user actively opens the dock.
Zero focus stealing, hardware-accelerated acrylic styling, and persistent state dedup.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Union

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
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
)
from PySide6.QtWidgets import QWidget

# Ensure serit directory is importable
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

import panel_style
import sources
import winapi

DEFAULT_STATE_PATH = Path("D:/Apps/serit/alerts_state.json")

# Visual & Geometry Tokens (v21: ortak panel dili — panel_style kitine göre)
TOAST_WIDTH: int = int(panel_style.PANEL_W)          # 352 — tek sütun ortak panel genişliği
TOAST_RADIUS: float = float(panel_style.R_PANEL)     # 16 — dış köşe yarıçapı
TOAST_MARGIN_SCREEN: int = 16
TOAST_STACK_GAP: int = 8
MAX_ACTIVE_TOASTS: int = 3

# Toast çizim sabitleri (yalnızca boyama; panel kitindeki ölçüler)
TOAST_PAD: float = float(panel_style.PAD)                  # 16 iç boşluk
TOAST_ICON_BOX: float = 28.0                               # sol aksan ikon kutusu
TOAST_ICON_RADIUS: float = float(panel_style.R_ICON_BOX)   # 6
TOAST_ICON_TEXT_GAP: float = 10.0                          # kutu ile metin arası
TOAST_TEXT_X: float = TOAST_PAD + TOAST_ICON_BOX + TOAST_ICON_TEXT_GAP   # 54
TOAST_TITLE_ROW_H: float = TOAST_ICON_BOX                  # başlık satırı kutuyla aynı yükseklikte
TOAST_BODY_GAP: float = 2.0                                # başlık satırı -> gövde
TOAST_FOOTER_GAP: float = 6.0                              # gövde -> 'Şerit · HH:MM'
TOAST_MAX_BODY_LINES: int = 3                              # gövde en fazla 3 satır, sonrası '…'
TOAST_ICON_ALPHA: int = 46                                 # ~%18 aksan dolgusu
TOAST_HOVER_TINT: QColor = QColor(255, 255, 255, 8)        # tüm gövdeye ince hover tonu

COLOR_ALERT_WARN = QColor("#FFC45C")  # Amber (Claude / FX warn)
COLOR_ALERT_CRIT = QColor("#FF6E6E")  # Coral Red (Critical / RAM / FX drop)
COLOR_ALERT_GROWTH = QColor("#78DC96")  # Mint Green (FX up)

# Yalnızca boyama için aksan eşlemesi (Alert içindeki hex değeri değişmez)
_ACCENT_TO_KIT: Dict[str, QColor] = {
    "#FF6E6E": panel_style.DANGER,
    "#FFC45C": panel_style.WARN,
    "#78DC96": panel_style.OK,
}


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
        """Atomically persist alert state to disk using a unique temporary file and os.replace."""
        tmp_path = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "fired_ids": self._fired_ids,
                "last_toast_time": self._last_toast_time,
                "queue": [dict(a) for a in self._queue],
                "ram_high_timestamps": self._ram_high_timestamps,
            }
            tmp_path = self.state_path.with_name(f"{self.state_path.name}.tmp.{os.getpid()}")
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(self.state_path))
        except Exception:
            pass
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
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
        dirty: bool = False

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
                    dirty = True
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
                    dirty = True

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
                    dirty = True

        # ----------------------------------------------------------------------
        # Rule 3: FX Market Daily Changes (|change| thresholds)
        # ----------------------------------------------------------------------
        fx = self._extract_valid_entry(store, "fx")
        if fx is not None:
            dt_now = dt.datetime.fromtimestamp(eval_time, sources.LOCAL_TZ)
            today_str = dt_now.strftime("%Y-%m-%d")
            updated_raw = str(fx.get("updated", "") or "").strip()
            source_time = updated_raw

            # USD: |daily change| >= 1.0%
            usd_val = float(fx.get("usd", 0.0) or 0.0)
            usd_chg = float(fx.get("usd_chg", 0.0) or 0.0)
            if abs(usd_chg) >= 1.0 and usd_val > 0.0:
                direction = "up" if usd_chg > 0 else "down"
                aid_usd = f"fx_usd_{today_str}_{direction}"
                if aid_usd not in self._fired_ids:
                    dir_tr = "artış" if usd_chg > 0 else "düşüş"
                    title = f"Dolar %{sources.fmt_tr(abs(usd_chg), 2)} {dir_tr}"
                    upd_suffix = f" · Güncelleme: {source_time}" if source_time else ""
                    body = f"1 USD = {sources.fmt_tr(usd_val, 2)} TL{upd_suffix}"
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
                    dirty = True

            # EUR: |daily change| >= 1.0%
            eur_val = float(fx.get("eur", 0.0) or 0.0)
            eur_chg = float(fx.get("eur_chg", 0.0) or 0.0)
            if abs(eur_chg) >= 1.0 and eur_val > 0.0:
                direction = "up" if eur_chg > 0 else "down"
                aid_eur = f"fx_eur_{today_str}_{direction}"
                if aid_eur not in self._fired_ids:
                    dir_tr = "artış" if eur_chg > 0 else "düşüş"
                    title = f"Euro %{sources.fmt_tr(abs(eur_chg), 2)} {dir_tr}"
                    upd_suffix = f" · Güncelleme: {source_time}" if source_time else ""
                    body = f"1 EUR = {sources.fmt_tr(eur_val, 2)} TL{upd_suffix}"
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
                    dirty = True

            # Gram Altın: |daily change| >= 2.0%
            gold_val = float(fx.get("gold", 0.0) or 0.0)
            gold_chg = float(fx.get("gold_chg", 0.0) or 0.0)
            if abs(gold_chg) >= 2.0 and gold_val > 0.0:
                direction = "up" if gold_chg > 0 else "down"
                aid_gold = f"fx_gold_{today_str}_{direction}"
                if aid_gold not in self._fired_ids:
                    dir_tr = "artış" if gold_chg > 0 else "düşüş"
                    title = f"Gram Altın %{sources.fmt_tr(abs(gold_chg), 2)} {dir_tr}"
                    upd_suffix = f" · Güncelleme: {source_time}" if source_time else ""
                    body = f"1 g = {sources.fmt_tr(gold_val, 2)} TL{upd_suffix}"
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
                    dirty = True

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
                    dirty = True
                else:
                    last_t = self._ram_high_timestamps[-1]
                    if (eval_time - last_t) >= 55.0:
                        self._ram_high_timestamps.append(eval_time)
                        dirty = True

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
                        dirty = True
            elif self._ram_high_timestamps:
                # Streak broken when RAM drops below threshold
                self._ram_high_timestamps.clear()
                dirty = True

        # Enqueue newly generated alerts
        if new_alerts:
            for alert in new_alerts:
                self._queue.append(alert)
            dirty = True

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
                dirty = True

        if dirty:
            self._save_state()
        return delivered


# ==============================================================================
# 3. TOAST WINDOW (Acrylic Glass Notification Card)
# ==============================================================================


class Toast(QWidget):
    """Frameless opaque notification toast card in the shared panel look (panel_style).

    Features zero focus stealing (ShowWithoutActivating, WindowDoesNotAcceptFocus),
    interactive hover pause, shared fade+slide entrance easing, and offscreen
    high-DPI rendering.
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
        self._close_rect = QRectF(
            self.WIDTH - TOAST_PAD - panel_style.CLOSE_SZ,
            TOAST_PAD + (TOAST_TITLE_ROW_H - panel_style.CLOSE_SZ) / 2.0,
            panel_style.CLOSE_SZ,
            panel_style.CLOSE_SZ,
        )
        self._is_dismissing: bool = False

        self._target_x: int = 0
        self._target_y: int = 0
        self._anim_opacity: float = 1.0
        self._slide_offset_y: float = 0.0
        self._exit_from_opacity: float = 1.0
        self._exit_from_y: float = 0.0

        # Animations (ortak panel hareketi: 160 ms açılış / 115 ms kapanış)
        self._enter_anim = QVariantAnimation(self)
        self._enter_anim.setDuration(panel_style.anim_ms(panel_style.ANIM_OPEN_MS))
        self._enter_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._enter_anim.setStartValue(0.0)
        self._enter_anim.setEndValue(1.0)
        self._enter_anim.valueChanged.connect(self._on_enter_anim_step)
        self._enter_anim.finished.connect(self._on_enter_anim_done)

        self._exit_anim = QVariantAnimation(self)
        self._exit_anim.setDuration(panel_style.anim_ms(panel_style.ANIM_CLOSE_MS))
        self._exit_anim.setEasingCurve(QEasingCurve.Type.InCubic)
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

        # Shared panel typography
        self.f_title = panel_style.f_title()
        self.f_body = panel_style.f_body()
        self.f_footer = panel_style.f_small()
        self.f_glyph = panel_style.font(13.0, QFont.Weight.Bold)

        # Dynamic height calculation
        h = self.compute_height()
        self.resize(self.WIDTH, h)

    def _body_width(self) -> float:
        return self.WIDTH - TOAST_TEXT_X - TOAST_PAD

    def _wrap_body(
        self,
        fm: QFontMetricsF,
        width: float,
        max_lines: int = TOAST_MAX_BODY_LINES,
    ) -> tuple[list[str], bool]:
        """Greedy word-wrap; en fazla max_lines satır, taşan içerik son satırda '…' ile kısaltılır."""
        text = " ".join(str(self.alert.body or "").split())
        if not text:
            return [], False
        lines: list[str] = []
        cur = ""
        for word in text.split(" "):
            trial = word if not cur else f"{cur} {word}"
            if not cur or fm.horizontalAdvance(trial) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return lines, False
        tail = " ".join(lines[max_lines - 1:])
        shown = lines[: max_lines - 1]
        shown.append(fm.elidedText(tail, Qt.TextElideMode.ElideRight, max(10.0, width)))
        return shown, True

    def compute_height(self) -> int:
        """Calculate optimal card height: title row + up to 3 wrapped body lines + footer."""
        fm_body = QFontMetricsF(self.f_body)
        fm_footer = QFontMetricsF(self.f_footer)
        lines, _truncated = self._wrap_body(fm_body, self._body_width())
        body_h = max(1, len(lines)) * fm_body.height()
        total_h = (
            TOAST_PAD
            + TOAST_TITLE_ROW_H
            + TOAST_BODY_GAP
            + body_h
            + TOAST_FOOTER_GAP
            + fm_footer.height()
            + TOAST_PAD
        )
        return int(math.ceil(total_h))

    def _paint_accent(self) -> QColor:
        """Alert aksanını yalnızca çizim için ortak kit rengine eşler.

        Bilinen hexler kit renklerine bağlanır; 'claude' uyarısı WARN aksanıyla
        geldiğinde glif kutusu CLAUDE rengini kullanır. Diğer hexler ayrıştırılır,
        geçersizse ACCENT kullanılır. Alert içindeki hex değeri hiç değişmez.
        """
        raw = str(self.alert.accent or "").strip()
        kit = _ACCENT_TO_KIT.get(raw.upper())
        if kit is not None:
            if "claude" in str(self.alert.kind).lower() and kit == panel_style.WARN:
                return QColor(panel_style.CLAUDE)
            return QColor(kit)
        # Yalnız tam biçimli hex (#RRGGBB / #AARRGGBB) ayrıştırılır; kısa/bozuk
        # değerler (#123 gibi) geçersiz sayılır ve ACCENT kullanılır.
        hex_ok = raw.startswith("#") and len(raw) in (7, 9) and all(
            c in "0123456789abcdefABCDEF" for c in raw[1:]
        )
        parsed = QColor(raw) if hex_ok else QColor()
        if not parsed.isValid():
            return QColor(panel_style.ACCENT)
        return parsed

    def _get_glyph(self) -> str:
        """Return category glyph symbol for visual badge (bilinmeyen tür: nötr '!')."""
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
        if "shelf" in k or "download" in k:
            return "↓"
        if "pomodoro" in k:
            return "⏱"
        return "!"

    def show_toast(self, x: int, y: int) -> None:
        """Position and show toast with the shared panel entrance (fade + 6 px slide)."""
        self._target_x = x
        self._target_y = y
        open_ms = panel_style.anim_ms(panel_style.ANIM_OPEN_MS)
        if open_ms <= 0:
            self._slide_offset_y = 0.0
            self._anim_opacity = 1.0
            self.setWindowOpacity(1.0)
            self.move(x, y)
            self.show()
            self._on_enter_anim_done()
            return
        self._slide_offset_y = panel_style.ANIM_OPEN_SLIDE
        self._anim_opacity = 0.0
        self.setWindowOpacity(0.0)
        self.move(x, y + int(panel_style.ANIM_OPEN_SLIDE))
        self.show()

        hwnd = int(self.winId())
        try:
            dpr = self.devicePixelRatioF()
            winapi.set_round_region(
                hwnd, self.width(), self.height(), int(self.RADIUS), dpr
            )
        except Exception:
            pass

        self._enter_anim.stop()
        self._enter_anim.setDuration(open_ms)
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
        self._slide_offset_y = (1.0 - val) * panel_style.ANIM_OPEN_SLIDE
        self.setWindowOpacity(val)
        self.move(self._target_x, int(round(self._target_y + self._slide_offset_y)))
        self.update()

    def _on_enter_anim_done(self) -> None:
        self.move(self._target_x, self._target_y)
        self.setWindowOpacity(1.0)
        self._timer_deadline = time.time() + 8.0
        self._dismiss_timer.start(8000)

    def dismiss(self) -> None:
        """Fade out (panel_style timing: 115 ms InCubic + 4 px aşağı) and close toast."""
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._dismiss_timer.stop()
        self._enter_anim.stop()
        self._slide_anim.stop()
        close_ms = panel_style.anim_ms(panel_style.ANIM_CLOSE_MS)
        if close_ms <= 0 or not self.isVisible():
            self._on_exit_anim_done()
            return
        self._exit_from_opacity = float(self.windowOpacity())
        self._exit_from_y = float(self.y())
        self._exit_anim.stop()
        self._exit_anim.setDuration(close_ms)
        self._exit_anim.start()

    def _on_exit_anim_step(self, val: float) -> None:
        val_f = float(val)
        self._anim_opacity = self._exit_from_opacity * val_f
        self.setWindowOpacity(self._anim_opacity)
        self.move(
            self._target_x,
            int(round(self._exit_from_y + (1.0 - val_f) * panel_style.ANIM_CLOSE_SLIDE)),
        )
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
        # 1. Opak ortak panel kabuğu (akrilik/cam kapsül yok, renkli sol şerit yok)
        panel_style.draw_panel_shell(p, rect)
        if self._is_hovered:
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(TOAST_HOVER_TINT)
            p.drawPath(panel_style.rounded(rect, panel_style.R_PANEL))
            p.restore()

        accent_col = self._paint_accent()

        # 2. Sol 28 px yuvarlak aksan ikon kutusu (~%18 dolgu, aksan renginde glif)
        icon_box = QRectF(TOAST_PAD, TOAST_PAD, TOAST_ICON_BOX, TOAST_ICON_BOX)
        p.setPen(Qt.NoPen)
        p.setBrush(
            QColor(accent_col.red(), accent_col.green(), accent_col.blue(), TOAST_ICON_ALPHA)
        )
        p.drawPath(panel_style.rounded(icon_box, TOAST_ICON_RADIUS))

        p.setFont(self.f_glyph)
        p.setPen(accent_col)
        p.drawText(icon_box, Qt.AlignCenter, self._get_glyph())

        # 3. Başlık satırı + sağ üst × (draw_header görünümü: TEXT_CLOSE, BUTTON_HOVER, R_CLOSE)
        title_row = QRectF(
            TOAST_TEXT_X,
            TOAST_PAD,
            rect.width() - TOAST_TEXT_X - TOAST_PAD,
            TOAST_TITLE_ROW_H,
        )
        hdr = panel_style.draw_header(
            p, title_row, self.alert.title, close_hover=self._close_hovered
        )
        close = hdr.get("close")
        if close is not None:
            self._close_rect = QRectF(close)

        # 4. Gövde (f_body, TEXT_BODY; en fazla 3 satır, taşarsa son satır '…' ile kısaltılır)
        fm_body = QFontMetricsF(self.f_body)
        lines, _truncated = self._wrap_body(fm_body, self._body_width())
        p.setFont(self.f_body)
        p.setPen(panel_style.TEXT_BODY)
        line_box = QRectF(
            TOAST_TEXT_X,
            TOAST_PAD + TOAST_TITLE_ROW_H + TOAST_BODY_GAP,
            self._body_width(),
            fm_body.height(),
        )
        for line in lines:
            p.drawText(
                line_box, Qt.AlignLeft | Qt.AlignVCenter, line
            )
            line_box = line_box.translated(0.0, fm_body.height())

        # 5. 'Şerit · HH:MM' alt satırı (f_small, TEXT_META)
        fm_footer = QFontMetricsF(self.f_footer)
        now_clock = dt.datetime.now(sources.LOCAL_TZ).strftime("%H:%M")
        p.setFont(self.f_footer)
        p.setPen(panel_style.TEXT_META)
        footer_rect = QRectF(
            TOAST_TEXT_X,
            rect.height() - TOAST_PAD - fm_footer.height(),
            self._body_width(),
            fm_footer.height(),
        )
        p.drawText(
            footer_rect, Qt.AlignLeft | Qt.AlignVCenter, f"Şerit · {now_clock}"
        )

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
