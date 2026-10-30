"""Şerit pomodoro (v25): zamanlayıcı motoru, çubuk bloğu (tasarım B) ve açılır panel.

* PomodoroTimer: kalan süre her zaman saatten (clock) hesaplanır, kayma yok. İç QTimer (1000 ms) yalnız
  çalışırken açıktır; duraklatılmış/durmuş sayaç sıfır CPU harcar. Uykudan dönüşte (saat sıfırı geçmiş)
  evre tek kez biter.
* band_width / draw_pomo_band: büyük süre (20 px DemiBold, tabular) + altında görev (10.5 px) + 2 px ilerleme çizgisi.
* PomodoroPanel: 352 px'lik panel_style kiti ile açılır panel (süre, tur noktaları, süre çipleri, görev alanı, düğmeler).
Hiçbir değer uydurulmaz: gösterilen her sayı sayaç durumundan gelir.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, QObject, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QLineEdit, QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402
import theme  # noqa: E402

try:
    import winapi  # noqa: E402
except Exception:  # pragma: no cover
    winapi = None

PHASES = ("focus", "short", "long")
MIN_DUR = 5            # chip / set_durations sınırı (dk)
MAX_DUR = 90
MIN_REMAIN_S = 60.0    # adjust() sonrası kalan süre alt sınırı
MAX_REMAIN_S = 90 * 60.0
WHEEL_MIN = 5          # tekerlek adımı (dk)
TASK_MAX = 80

BAND_MIN_W = 76.0      # mockup .pB genişliği
BAND_MAX_W = 90.0
LINE_H = 2.0


def _valid_min(value: Any, default: int) -> int:
    """5..90 dk aralığına sıkıştırılmış tam sayı; sayı değilse varsayılan."""
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)
    return max(MIN_DUR, min(MAX_DUR, v))


# =============================================================================================
# 1. ZAMANLAYICI MOTORU
# =============================================================================================

class PomodoroTimer(QObject):
    changed = Signal()
    phase_finished = Signal(str, str)

    def __init__(self, focus_min: int = 25, short_min: int = 5, long_min: int = 15, rounds: int = 4,
                 clock: Callable[[], float] = time.monotonic, auto_start_breaks: bool = True,
                 auto_start_focus: bool = False) -> None:
        super().__init__()
        self._clock = clock
        self._dur = {"focus": _valid_min(focus_min, 25), "short": _valid_min(short_min, 5),
                     "long": _valid_min(long_min, 15)}
        self._rounds = max(1, int(rounds))
        self.auto_start_breaks = bool(auto_start_breaks)
        self.auto_start_focus = bool(auto_start_focus)
        self._active = False
        self._running = False
        self._phase = "focus"
        self._round = 1
        self._total = self._dur["focus"] * 60.0
        self._rem = self._total          # çalışmıyorken donmuş kalan süre (sn)
        self._deadline = 0.0             # çalışırken bitiş anı (clock)
        self._task = ""
        self._qtimer = QTimer(self)
        self._qtimer.setInterval(1000)
        self._qtimer.timeout.connect(self.tick)

    # ------------------------------------------------------------ özellikler
    @property
    def active(self) -> bool:
        return self._active

    @property
    def running(self) -> bool:
        return self._running

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def round_idx(self) -> int:
        return self._round

    @property
    def rounds(self) -> int:
        return self._rounds

    def _remaining_float(self) -> float:
        if self._running:
            return max(0.0, self._deadline - self._clock())
        return max(0.0, self._rem)

    @property
    def remaining_s(self) -> int:
        return int(math.ceil(self._remaining_float() - 1e-9))

    @property
    def total_s(self) -> int:
        return int(round(self._total))

    @property
    def progress(self) -> float:
        if self._total <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self._remaining_float() / self._total))

    @property
    def task(self) -> str:
        return self._task

    @property
    def durations(self) -> tuple:
        return (self._dur["focus"], self._dur["short"], self._dur["long"])

    # --------------------------------------------------------------- eylemler
    def _begin(self, phase: str, running: bool) -> None:
        self._phase = phase
        self._total = self._dur[phase] * 60.0
        self._rem = self._total
        self._running = bool(running)
        if running:
            self._deadline = self._clock() + self._total
            self._qtimer.start()
        else:
            self._qtimer.stop()

    def start(self, phase: str = "focus") -> None:
        if phase not in PHASES:
            phase = "focus"
        if not self._active:
            self._round = 1
        self._active = True
        self._begin(phase, True)
        self.changed.emit()

    def pause(self) -> None:
        if not (self._active and self._running):
            return
        self._rem = self._remaining_float()
        self._running = False
        self._qtimer.stop()
        self.changed.emit()

    def resume(self) -> None:
        if not self._active or self._running:
            return
        self._running = True
        self._deadline = self._clock() + self._rem
        self._qtimer.start()
        self.changed.emit()

    def toggle_pause(self) -> None:
        if not self._active:
            return
        if self._running:
            self.pause()
        else:
            self.resume()

    def skip(self) -> None:
        if self._active:
            self._finish()

    def reset(self) -> None:
        if not self._active:
            return
        self._begin(self._phase, False)
        self.changed.emit()

    def stop(self) -> None:
        self._active = False
        self._round = 1
        self._begin("focus", False)
        self.changed.emit()

    def adjust(self, minutes: int) -> None:
        if not self._active:
            return
        try:
            delta = int(minutes) * 60.0
        except (TypeError, ValueError):
            return
        if delta == 0:
            return
        rem = self._remaining_float()
        new_rem = max(MIN_REMAIN_S, min(MAX_REMAIN_S, rem + delta))
        applied = new_rem - rem
        if applied == 0 or (applied > 0) != (delta > 0):
            return  # sınırda: ters yöne kaydırma yok
        self._total = max(new_rem, self._total + applied)
        if self._running:
            self._deadline = self._clock() + new_rem
        else:
            self._rem = new_rem
        self.changed.emit()

    def set_task(self, text: str) -> None:
        t = str(text or "").strip()[:TASK_MAX]
        if t != self._task:
            self._task = t
            self.changed.emit()

    def set_durations(self, focus_min: int, short_min: int, long_min: int) -> None:
        """Süreleri 5..90 dk'ya sıkıştırarak kaydeder. Başlamamış (dokunulmamış) evre yeni süreyi alır."""
        new = {"focus": _valid_min(focus_min, self._dur["focus"]),
               "short": _valid_min(short_min, self._dur["short"]),
               "long": _valid_min(long_min, self._dur["long"])}
        if new == self._dur:
            return
        untouched = (not self._running) and abs(self._rem - self._total) < 1e-6
        self._dur = new
        if untouched:
            self._total = new[self._phase] * 60.0
            self._rem = self._total
        self.changed.emit()

    def state(self) -> Dict[str, Any]:
        return {"active": self._active, "running": self._running, "phase": self._phase,
                "round": self._round, "rounds": self._rounds, "remaining_s": self.remaining_s,
                "total_s": self.total_s, "progress": self.progress, "task": self._task}

    # ------------------------------------------------------------------ saat
    def tick(self) -> None:
        if not self._running:
            self._qtimer.stop()
            return
        if self._deadline - self._clock() <= 0.0:
            self._finish()
        else:
            self.changed.emit()

    def _finish(self) -> None:
        finished = self._phase
        if finished == "focus":
            nxt = "long" if self._round % self._rounds == 0 else "short"
        else:
            nxt = "focus"
            self._round = 1 if finished == "long" else self._round + 1
        auto = self.auto_start_focus if nxt == "focus" else self.auto_start_breaks
        self._begin(nxt, auto)   # uykudan dönüşte artan süre sonraki evreye taşınmaz
        self.phase_finished.emit(finished, nxt)
        self.changed.emit()


# =============================================================================================
# 2. ÇUBUK BLOĞU (tasarım B)
# =============================================================================================

_FM_CACHE: Dict[Any, QFontMetricsF] = {}


def _fm(f: QFont) -> QFontMetricsF:
    key = (f.pixelSize(), int(f.weight()), f.letterSpacing(), f.family())
    fm = _FM_CACHE.get(key)
    if fm is None:
        fm = QFontMetricsF(f)
        _FM_CACHE[key] = fm
    return fm


def _f_time() -> QFont:
    return theme.make_font(20.0, QFont.Weight.DemiBold, tabular=True, letter_spacing=-0.3)


def _f_sub() -> QFont:
    return theme.make_font(10.5, QFont.Weight.Normal)


def fmt_time(seconds: Any) -> str:
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        s = 0
    return f"{s // 60:02d}:{s % 60:02d}"


def sub_text(state: Dict[str, Any]) -> str:
    """Çubuk bloğunun ikinci satırı: Duraklatıldı / görev / Odak · 2/4 / Mola."""
    if not state.get("running", False):
        return "Duraklatıldı"
    phase = state.get("phase", "focus")
    if phase == "focus":
        task = str(state.get("task") or "").strip()
        return task if task else f"Odak · {int(state.get('round', 1))}/{int(state.get('rounds', 4))}"
    return "Uzun mola" if phase == "long" else "Mola"


def band_width(state: Dict[str, Any]) -> float:
    """0.0 etkin değilken; aksi halde tasarım B genişliği (76..90 px). state['compact']=True: yalnız süre."""
    if not state or not state.get("active"):
        return 0.0
    w_time = math.ceil(_fm(_f_time()).horizontalAdvance("88:88"))   # sabit: rakamlar oynasa da genişlik oynamaz
    if state.get("compact"):
        return float(min(100.0, w_time + 2.0))
    w_sub = math.ceil(_fm(_f_sub()).horizontalAdvance(sub_text(state))) + 1.0
    return float(max(BAND_MIN_W, min(BAND_MAX_W, max(w_time, w_sub))))


def _baseline(rect: QRectF) -> tuple:
    """Süre taban çizgisi, saat bloğuyla (dock_cards.draw_clock_v1) aynı formül: cap yükseklikleri ile ortalanır."""
    cap_t = _fm(_f_time()).capHeight()
    cap_d = _fm(theme.make_font(11.0, QFont.Weight.Medium)).capHeight()
    gap_td = 9.5
    time_base = rect.center().y() - (cap_t + gap_td + cap_d) / 2.0 + cap_t
    sub_base = time_base + gap_td + cap_d
    return time_base, sub_base


def draw_pomo_band(p: QPainter, rect: QRectF, state: Dict[str, Any], hover: bool = False) -> None:
    if not state or not state.get("active"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    running = bool(state.get("running"))
    phase = state.get("phase", "focus")
    col = QColor(COLOR_FOCUS) if phase == "focus" else QColor(COLOR_BREAK)
    if hover:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(rect.adjusted(-6.0, 0.0, 6.0, 0.0), 11.0, 11.0)

    time_base, sub_base = _baseline(rect)
    f_t = _f_time()
    p.setFont(f_t)
    p.setPen(QColor(255, 255, 255))
    p.setOpacity(1.0 if running else 0.55)
    p.drawText(QPointF(rect.left(), time_base), fmt_time(state.get("remaining_s", 0)))
    p.setOpacity(1.0)

    compact = bool(state.get("compact"))
    if not compact:
        f_s = _f_sub()
        txt = _fm(f_s).elidedText(sub_text(state), Qt.TextElideMode.ElideRight, max(10.0, rect.width()))
        p.setFont(f_s)
        p.setPen(ps.TEXT_META)
        p.drawText(QPointF(rect.left(), sub_base), txt)
        line_y = sub_base + 7.0
    else:
        line_y = time_base + 7.0
    line_y = min(line_y, rect.bottom() - LINE_H - 1.0)
    track = QRectF(rect.left(), line_y, rect.width(), LINE_H)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ps.TRACK)
    p.drawRoundedRect(track, 1.0, 1.0)
    prog = max(0.0, min(1.0, float(state.get("progress", 0.0))))
    if prog > 0.0:
        fill = QColor(col)
        if not running:
            fill.setAlpha(140)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(track.left(), track.top(), max(LINE_H, track.width() * prog), LINE_H), 1.0, 1.0)
    p.restore()


# =============================================================================================
# 3. PANEL
# =============================================================================================

COLOR_FOCUS = QColor(0xD9, 0x77, 0x57)   # Claude coral #D97757
COLOR_BREAK = ps.ACCENT                  # #6EA8FE

CHIP_H = 24.0
BTN_H = 26.0
ROUND_D = 46.0
FIELD_H = 34.0
DOT_D = 7.0
DOT_GAP = 6.0
PHASE_NAME = {"focus": "Odak", "short": "Mola", "long": "Uzun"}


class _TaskEdit(QLineEdit):
    focus_changed = Signal()

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.focus_changed.emit()

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self.focus_changed.emit()


class PomodoroPanel(QWidget):
    """Pomodoro paneli, 352 px geniş (mockup s4)."""

    WIDTH = int(ps.PANEL_W)

    task_changed = Signal(str)
    durations_changed = Signal(int, int, int)

    def __init__(self, timer: PomodoroTimer, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._timer = timer
        self._anchor_global: Optional[QRectF] = None
        self._last_close_time = 0.0
        self._closing = False
        self._hover: Optional[str] = None
        self._rects: Dict[str, QRectF] = {}
        self._last_task = timer.task
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self._edit = _TaskEdit(self)
        self._edit.setPlaceholderText("Ne üzerinde çalışıyorsun?")
        self._edit.setMaxLength(TASK_MAX)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            "QLineEdit{background:transparent;border:none;color:rgba(255,255,255,217);"
            "font-family:'Segoe UI Variable Text','Segoe UI';font-size:12.5px;"
            "selection-background-color:rgba(110,168,254,110);}")
        self._edit.setText(timer.task)
        self._edit.editingFinished.connect(self._commit_task)
        self._edit.focus_changed.connect(self.update)
        self._edit.setMouseTracking(True)

        self.resize(self.WIDTH, self.compute_height())
        self._layout()
        timer.changed.connect(self._on_timer_changed)

    @staticmethod
    def _draw_header_icon(p: QPainter, r: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = r.center().x(), r.center().y() + 1.0
        pen = QPen(QColor(255, 255, 255, 230), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rad = 6.2
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.drawLine(QPointF(cx, cy - rad), QPointF(cx, cy - rad - 2.5))
        p.drawLine(QPointF(cx - 2.2, cy - rad - 2.5), QPointF(cx + 2.2, cy - rad - 2.5))
        p.drawLine(QPointF(cx, cy), QPointF(cx + 2.8, cy - 2.4))
        p.restore()

    # -------------------------------------------------------------- yerleşim
    def compute_height(self) -> int:
        return int(round(self._geom()["height"]))

    @staticmethod
    def _geom() -> Dict[str, float]:
        g: Dict[str, float] = {}
        y = ps.PAD
        g["header"] = y
        y += ps.HEADER_H + ps.GAP
        g["card_timer"] = y
        g["big"] = y + ps.CARD_PAD + 25.0
        g["dots"] = g["big"] + 40.0 + 6.0
        g["chips"] = g["dots"] + DOT_D + 12.0
        g["btns"] = g["chips"] + CHIP_H + 14.0
        card1_h = ps.CARD_PAD + 25.0 + 40.0 + 6.0 + DOT_D + 12.0 + CHIP_H + 14.0 + ROUND_D + ps.CARD_PAD
        y += card1_h + ps.GAP
        g["card_task"] = y
        g["field"] = y + ps.CARD_PAD + 23.0
        card2_h = ps.CARD_PAD + 23.0 + FIELD_H + ps.CARD_PAD
        y += card2_h + ps.GAP
        g["footer"] = y
        y += ps.FOOTER_H + ps.PAD
        g["height"] = y
        return g

    def _layout(self) -> None:
        """Tüm isabet alanlarını hesaplar (çizimden bağımsız, testler çizim beklemeden tıklayabilir)."""
        g = self._geom()
        x0 = ps.PAD
        cw = self.WIDTH - 2 * ps.PAD
        r: Dict[str, QRectF] = {}
        hdr = QRectF(x0, g["header"], cw, ps.HEADER_H)
        r["close"] = QRectF(hdr.right() - ps.CLOSE_SZ, hdr.center().y() - ps.CLOSE_SZ / 2.0, ps.CLOSE_SZ, ps.CLOSE_SZ)
        r["card_timer"] = QRectF(x0, g["card_timer"], cw, (g["card_task"] - ps.GAP) - g["card_timer"])
        r["big"] = QRectF(x0 + ps.CARD_PAD, g["big"], cw - 2 * ps.CARD_PAD, 40.0)
        # çipler
        f_chip = ps.font(11.5, QFont.Weight.Medium)
        fm = QFontMetricsF(f_chip)
        d = self._timer.durations
        labels = [f"{PHASE_NAME[k]} {d[i]}" for i, k in enumerate(PHASES)]
        widths = [fm.horizontalAdvance(t) + 22.0 for t in labels]
        total = sum(widths) + 8.0 * (len(widths) - 1)
        cx = x0 + (cw - total) / 2.0
        for i, w in enumerate(widths):
            r[f"chip_{i}"] = QRectF(cx, g["chips"], w, CHIP_H)
            cx += w + 8.0
        self._chip_labels = labels
        # görev alanı
        r["card_task"] = QRectF(x0, g["card_task"], cw, (g["footer"] - ps.GAP) - g["card_task"])
        field = QRectF(x0 + ps.CARD_PAD, g["field"], cw - 2 * ps.CARD_PAD, FIELD_H)
        r["field"] = field
        f_lbl = ps.font(11.0)
        lbl_w = QFontMetricsF(f_lbl).horizontalAdvance("Görev")
        edit_left = field.left() + 10.0 + lbl_w + 8.0
        er = QRectF(edit_left, field.top() + 1.0, field.right() - 8.0 - edit_left, field.height() - 2.0)
        r["edit"] = er
        self._edit.setGeometry(int(er.left()), int(er.top()), int(er.width()), int(er.height()))
        # düğmeler
        cy = g["btns"] + ROUND_D / 2.0
        mid = x0 + cw / 2.0
        r["play"] = QRectF(mid - ROUND_D / 2.0, g["btns"], ROUND_D, ROUND_D)
        f_btn = ps.font(11.5, QFont.Weight.Medium)
        fmb = QFontMetricsF(f_btn)
        for key, text, side in (("skip", "Atla", -1), ("reset", "Sıfırla", 1)):
            bw = fmb.horizontalAdvance(text) + 22.0
            left = mid - ROUND_D / 2.0 - 14.0 - bw if side < 0 else mid + ROUND_D / 2.0 + 14.0
            r[key] = QRectF(left, cy - BTN_H / 2.0, bw, BTN_H)
        # alt bilgi düğmesi (draw_footer ile aynı ölçüler)
        fr = QRectF(x0, g["footer"], cw, ps.FOOTER_H)
        content_h = ps.FOOTER_H - 3.0
        f_ft = ps.font(11.5, QFont.Weight.Medium)
        bw = min(QFontMetricsF(f_ft).horizontalAdvance("Bitir") + 20.0, max(28.0, cw * 0.55))
        bh = min(24.0, content_h)
        r["stop"] = QRectF(fr.right() - bw, fr.top() + 3.0 + content_h / 2.0 - bh / 2.0, bw, bh)
        r["footer"] = fr
        self._rects = r

    # ------------------------------------------------------------ genel API
    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def refresh(self) -> None:
        if not self._edit.hasFocus() and self._edit.text() != self._timer.task:
            self._edit.setText(self._timer.task)
            self._last_task = self._timer.task
        self._layout()
        self.update()

    def show_for(self, anchor_global: Optional[QRectF], *args: Any, switch_from_x: Optional[int] = None,
                 **kw: Any) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._closing = False
        self.refresh()
        self.resize(self.WIDTH, self.compute_height())
        tx, ty, dpr = 100, 100, 1.0
        if self._anchor_global is not None:
            tx = int(self._anchor_global.center().x() - self.width() / 2.0)
            ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
            scr = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
            if scr is not None:
                geo = scr.availableGeometry()
                dpr = scr.devicePixelRatio()
                m = 8
                tx = max(geo.left() + m, min(geo.right() - self.width() - m, tx))
                if ty < geo.top() + m:
                    ty = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
                if ty + self.height() > geo.bottom() - m:
                    ty = max(geo.top() + m, geo.bottom() - self.height() - m)
        winid = int(self.winId())
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(winid, self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass
        ps.animate_in(self, QPointF(tx, ty).toPoint(), switch_from_x=switch_from_x)
        self.activateWindow()   # görev alanına yazılabilsin
        self.setFocus()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._closing:
            return
        self._commit_task()
        self._closing = True
        self._last_close_time = time.monotonic()

        def _done() -> None:
            self._closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        if self.isVisible():
            self._commit_task()
            self._last_close_time = time.monotonic()
        self._closing = False
        ps.animate_out(self, instant=True)

    # ---------------------------------------------------------------- olaylar
    def _on_timer_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def _commit_task(self) -> None:
        text = self._edit.text().strip()[:TASK_MAX]
        if text == self._last_task:
            return
        self._last_task = text
        self._timer.set_task(text)
        self.task_changed.emit(text)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._closing:
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(QCursor.pos())):
                    self._last_close_time = time.monotonic()
                    self._anchor_timer.start(300)
                else:
                    self.hide_animated()
        super().changeEvent(event)

    def _on_anchor_timeout(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and not self._closing:
            self.hide_animated()

    def hideEvent(self, event) -> None:
        self._closing = False
        self._last_close_time = time.monotonic()
        self._commit_task()
        super().hideEvent(event)

    def _enabled(self, key: str) -> bool:
        if key in ("skip", "reset", "stop"):
            return self._timer.active
        return True

    def _hit(self, pos: QPointF) -> Optional[str]:
        for key in ("close", "skip", "play", "reset", "stop", "chip_0", "chip_1", "chip_2"):
            r = self._rects.get(key)
            if r is not None and r.contains(pos):
                return key
        return None

    def mouseMoveEvent(self, event) -> None:
        h = self._hit(event.position())
        if h != self._hover:
            self._hover = h
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()   # görev alanı odağı bırakır (editingFinished tetiklenir)
            self.activate(self._hit(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    def activate(self, key: Optional[str]) -> None:
        """Tıklama davranışı (testlerde doğrudan çağrılabilir)."""
        t = self._timer
        if key is None or not self._enabled(key):
            return
        if key == "close":
            self.hide_animated()
        elif key == "play":
            if not t.active:
                t.start("focus")
            else:
                t.toggle_pause()
        elif key == "skip":
            t.skip()
        elif key == "reset":
            t.reset()
        elif key == "stop":
            t.stop()

    def wheelEvent(self, event) -> None:
        pos = event.position()
        for i in range(3):
            r = self._rects.get(f"chip_{i}")
            if r is not None and r.contains(pos):
                step = WHEEL_MIN if event.angleDelta().y() > 0 else -WHEEL_MIN
                d = list(self._timer.durations)
                new = max(MIN_DUR, min(MAX_DUR, d[i] + step))
                if new != d[i]:
                    d[i] = new
                    self._timer.set_durations(d[0], d[1], d[2])
                    self._layout()
                    self.durations_changed.emit(*self._timer.durations)
                    self.update()
                event.accept()
                return
        super().wheelEvent(event)

    # ----------------------------------------------------------------- çizim
    def render_to_image(self, dpr: float = 1.25) -> QImage:
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        self.render(img)
        return img

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        self._layout()
        st = self._timer.state()
        r = self._rects
        ps.draw_panel_shell(p, QRectF(0, 0, self.width(), self.height()))
        g = self._geom()

        # 1. Başlık: 'Pomodoro' + durum rozeti + kapat ×
        if not st["active"]:
            chip_str = "Hazır"
            chip_dot = None
        elif st["phase"] == "focus":
            chip_str = f"Odak · {st['round']}/{st['rounds']}"
            chip_dot = COLOR_FOCUS
        else:
            chip_str = f"Mola · {st['round']}/{st['rounds']}"
            chip_dot = COLOR_BREAK

        hdr = ps.draw_header(
            p, QRectF(ps.PAD, g["header"], self.WIDTH - 2 * ps.PAD, ps.HEADER_H),
            "Pomodoro",
            icon=self._draw_header_icon,
            chip=chip_str,
            chip_dot=chip_dot,
            close_hover=(self._hover == "close"),
        )
        if hdr.get("close") is not None:
            r["close"] = QRectF(hdr["close"])

        # 2. Zamanlayıcı kartı
        ps.draw_card(p, r["card_timer"], overline="Zamanlayıcı")

        # büyük süre (40 px, tabular); duraklatılmış %55
        p.save()
        p.setFont(ps.f_hero(40.0))
        f = p.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.5)
        p.setFont(f)
        p.setOpacity(1.0 if (st["running"] or not st["active"]) else 0.55)
        p.setPen(ps.TEXT)
        p.drawText(r["big"], Qt.AlignmentFlag.AlignCenter, fmt_time(st["remaining_s"]))
        p.restore()

        # tur noktaları
        n = st["rounds"]
        done = (st["round"] - 1) + (0 if st["phase"] == "focus" else 1)
        done = max(0, min(n, done))
        cur = st["round"] - 1 if st["phase"] == "focus" else -1
        total_w = n * DOT_D + (n - 1) * DOT_GAP
        dx = (self.WIDTH - total_w) / 2.0
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            if i < done:
                p.setBrush(COLOR_FOCUS)
            elif i == cur:
                col = QColor(COLOR_FOCUS)
                col.setAlpha(128)
                p.setBrush(col)
            else:
                p.setBrush(QColor(255, 255, 255, 46))
            p.drawEllipse(QRectF(dx + i * (DOT_D + DOT_GAP), g["dots"], DOT_D, DOT_D))
        p.restore()

        # süre çipleri
        cur_phase = st["phase"]
        for i, key in enumerate(PHASES):
            cr = r[f"chip_{i}"]
            on = key == cur_phase
            hov = self._hover == f"chip_{i}"
            p.save()
            if on:
                accent_c = COLOR_FOCUS if key == "focus" else COLOR_BREAK
                border_c = QColor(accent_c)
                border_c.setAlpha(140)
                fill_c = QColor(accent_c)
                fill_c.setAlpha(45)
                p.setPen(QPen(border_c, 1.0))
                p.setBrush(fill_c)
                tc = accent_c
            else:
                p.setPen(QPen(ps.CHIP_BORDER, 1.0))
                p.setBrush(ps.BUTTON_HOVER if hov else ps.CHIP_BG)
                tc = ps.TEXT if hov else ps.TEXT_CHIP
            p.drawPath(ps.rounded(cr.adjusted(0.5, 0.5, -0.5, -0.5), CHIP_H / 2.0))
            p.setFont(ps.font(11.5, QFont.Weight.Medium))
            p.setPen(tc)
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, self._chip_labels[i])
            p.restore()

        # Atla | oynat/duraklat | Sıfırla
        for key, text in (("skip", "Atla"), ("reset", "Sıfırla")):
            br = r[key]
            en = self._enabled(key)
            hov = en and self._hover == key
            p.save()
            if not en:
                p.setOpacity(0.35)
            p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
            p.setBrush(ps.BUTTON_HOVER if hov else ps.BUTTON_BG)
            p.drawPath(ps.rounded(br.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_BUTTON))
            p.setFont(ps.font(11.5, QFont.Weight.Medium))
            p.setPen(ps.TEXT if hov else ps.TEXT_BTN)
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)
            p.restore()
        phase_color = COLOR_BREAK if st.get("phase") in ("short", "long") else COLOR_FOCUS
        self._paint_play(p, r["play"], st["running"], self._hover == "play", phase_color)

        # 3. Görev kartı
        ps.draw_card(p, r["card_task"], overline="Görev")
        fr = r["field"]
        p.save()
        focused = self._edit.hasFocus()
        p.setPen(QPen(QColor(110, 168, 254, 140) if focused else ps.BUTTON_BORDER, 1.0))
        p.setBrush(QColor(255, 255, 255, 13))
        p.drawPath(ps.rounded(fr.adjusted(0.5, 0.5, -0.5, -0.5), 8.0))
        p.restore()

        # 4. Alt bilgi
        if not st["active"]:
            src = "Hazır"
        elif st["phase"] == "focus":
            src = f"Odak turu {st['round']}/{st['rounds']}"
        else:
            src = "Uzun mola" if st["phase"] == "long" else "Kısa mola"
        ps.draw_footer(p, r["footer"], src, "Bitir" if st["active"] else None, button_hover=(self._hover == "stop"))

    @staticmethod
    def _paint_play(p: QPainter, rect: QRectF, running: bool, hover: bool, color: QColor = COLOR_FOCUS) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        hov_col = color.lighter(115)
        p.setBrush(hov_col if hover else color)
        p.drawEllipse(rect)
        p.setBrush(ps.PANEL_BG)
        c = rect.center()
        if running:
            for dx in (-5.0, 2.0):
                p.drawRoundedRect(QRectF(c.x() + dx, c.y() - 6.5, 3.5, 13.0), 1.2, 1.2)
        else:
            path = QPainterPath()
            path.moveTo(c.x() - 4.0, c.y() - 7.0)
            path.lineTo(c.x() + 7.0, c.y())
            path.lineTo(c.x() - 4.0, c.y() + 7.0)
            path.closeSubpath()
            p.drawPath(path)
        p.restore()
