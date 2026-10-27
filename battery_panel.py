"""Şerit pil paneli (panel_style v2): 'Pil ve bağlantılar'.

Pil durumu kartı + Wi-Fi / Bluetooth anahtarları. Panel yalnızca veri gösterir ve sinyal yayar;
gerçek radyo/ayar işlemleri ve ağır okumalar (power_net, psutil) panelin dışında, dock'un arka plan
işçisinde yapılır. Veri yoksa '—' gösterilir, hiçbir değer uydurulmaz.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402

try:
    import winapi  # noqa: E402
except Exception:  # pragma: no cover
    winapi = None

TOP_LOAD_MIN_W = 35.0
LOW_PCT = 20
WARN_PCT = 35


def level_color(percent: Optional[float], charging: bool) -> QColor:
    """Pil renk kuralı: şarjda ACCENT, <=20 DANGER, 21-35 WARN, aksi halde beyaz/OK."""
    if charging:
        return ps.ACCENT
    if percent is None:
        return ps.TEXT_MUTED
    if percent <= LOW_PCT:
        return ps.DANGER
    if percent <= WARN_PCT:
        return ps.WARN
    return ps.OK


def fmt_remaining(secs: Optional[float]) -> Optional[str]:
    """'~22 dk kaldı' / '~1 sa 5 dk kaldı'; bilinmiyorsa None."""
    if secs is None:
        return None
    try:
        m = int(round(float(secs) / 60.0))
    except (TypeError, ValueError):
        return None
    if m < 0:
        return None
    m = max(1, m)
    if m >= 60:
        h, mm = divmod(m, 60)
        return f"~{h} sa {mm} dk kaldı" if mm else f"~{h} sa kaldı"
    return f"~{m} dk kaldı"


def fmt_mwh(v: Any) -> str:
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def fmt_watt(w: Any) -> Optional[str]:
    try:
        return f"~{int(round(abs(float(w))))} W"
    except (TypeError, ValueError):
        return None


def battery_state(b: Dict[str, Any]) -> str:
    """'charging' | 'full' | 'battery' | 'unknown'."""
    if not b or not b.get("present"):
        return "unknown"
    if b.get("charging"):
        return "charging"
    pct = b.get("percent")
    if b.get("plugged"):
        return "full" if (pct is not None and pct >= 95) else "plugged"
    return "battery"


def state_label(b: Dict[str, Any]) -> str:
    st = battery_state(b)
    return {
        "charging": "Şarj oluyor",
        "full": "Prizde, dolu",
        "plugged": "Prizde",
        "battery": "Pilde",
    }.get(st, "—")


def chip_text(b: Dict[str, Any]) -> Optional[str]:
    st = battery_state(b)
    pct = b.get("percent") if b else None
    if st == "charging":
        return "Şarj oluyor"
    if st == "battery":
        if pct is not None and pct <= LOW_PCT:
            return "Düşük pil"
        w = fmt_watt(b.get("rate_w"))
        return f"Pilde · {w}" if w else "Pilde"
    if st in ("full", "plugged"):
        return "Prizde"
    return None


def pill_tooltip(b: Dict[str, Any]) -> Optional[str]:
    """Kapsül ipucu; yalnızca gerçek değerler."""
    if not b or not b.get("present") or b.get("percent") is None:
        return None
    pct = f"%{int(round(b['percent']))}"
    st = battery_state(b)
    if st == "charging":
        return f"{pct} · Şarj oluyor"
    if st in ("full", "plugged"):
        return f"{pct} · Prizde"
    rem = fmt_remaining(b.get("secs_left"))
    return f"{pct} · Pilde · {rem}" if rem else f"{pct} · Pilde"


def _icon_wifi(p: QPainter, r: QRectF) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, by = r.center().x(), r.center().y() + 5.0
    for rad in (3.5, 7.0, 10.5):
        arc = QRectF(cx - rad, by - rad, rad * 2, rad * 2)
        p.drawArc(arc, 45 * 16, 90 * 16)
    p.setBrush(QColor(255, 255, 255, 220))
    p.drawEllipse(QPointF(cx, by), 1.2, 1.2)
    p.restore()


def _icon_bt(p: QPainter, r: QRectF) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    path = QPainterPath()
    path.moveTo(cx - 4.0, cy - 3.5)
    path.lineTo(cx + 4.0, cy + 3.5)
    path.lineTo(cx, cy + 7.0)
    path.lineTo(cx, cy - 7.0)
    path.lineTo(cx + 4.0, cy - 3.5)
    path.lineTo(cx - 4.0, cy + 3.5)
    p.drawPath(path)
    p.restore()


class BatteryPanel(QWidget):
    """Pil ve bağlantılar paneli, 352 px geniş."""

    WIDTH = int(ps.WIDTH["bat"])

    toggle_requested = Signal(str, bool)   # 'wifi' | 'bluetooth', istenen durum
    settings_requested = Signal(str)       # 'wifi' | 'bluetooth' | 'power'

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._bat: Dict[str, Any] = {}
        self._wifi: Dict[str, Any] = {}
        self._bt: Dict[str, Any] = {}
        self._top: List[Dict[str, Any]] = []
        self._busy: Dict[str, Optional[str]] = {"wifi": None, "bluetooth": None}  # None | 'on' | 'off' (istenen)
        self._supported: Dict[str, bool] = {"wifi": True, "bluetooth": True}
        self._stamp: str = "—"

        self._anchor_global: Optional[QRectF] = None
        self._last_close_time: float = 0.0
        self._hover: Optional[str] = None
        self._rects: Dict[str, QRectF] = {}
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)
        self.resize(self.WIDTH, self.compute_height())

    # ------------------------------------------------------------------ veri
    def set_battery(self, info: Optional[Dict[str, Any]]) -> None:
        self._bat = dict(info) if isinstance(info, dict) else {}
        self._stamp = time.strftime("%H:%M")
        self._relayout()

    def set_wifi(self, info: Optional[Dict[str, Any]]) -> None:
        self._wifi = dict(info) if isinstance(info, dict) else {}
        self._busy["wifi"] = None
        self.update()

    def set_bluetooth(self, info: Optional[Dict[str, Any]]) -> None:
        self._bt = dict(info) if isinstance(info, dict) else {}
        self._busy["bluetooth"] = None
        self.update()

    def set_top_load(self, procs: Optional[List[Dict[str, Any]]]) -> None:
        self._top = [dict(x) for x in (procs or []) if isinstance(x, dict)][:2]
        self._relayout()

    def set_supported(self, wifi: bool, bluetooth: bool) -> None:
        self._supported = {"wifi": bool(wifi), "bluetooth": bool(bluetooth)}
        self.update()

    def set_busy(self, kind: str, target_on: Optional[bool]) -> None:
        if kind in self._busy:
            self._busy[kind] = None if target_on is None else ("on" if target_on else "off")
            self.update()

    def is_busy(self, kind: str) -> bool:
        return self._busy.get(kind) is not None

    def _relayout(self) -> None:
        h = self.compute_height()
        if h != self.height():
            self.resize(self.WIDTH, h)
        self.update()

    # ------------------------------------------------------------ türetilmiş
    def show_top_load(self) -> bool:
        b = self._bat
        try:
            rate = float(b.get("rate_w")) if b.get("rate_w") is not None else None
        except (TypeError, ValueError):
            rate = None
        return bool(b.get("present") and battery_state(b) == "battery" and rate is not None
                    and abs(rate) >= TOP_LOAD_MIN_W and self._top)

    def _toggle_state(self, kind: str) -> str:
        if self._busy.get(kind):
            return "busy"
        info = self._wifi if kind == "wifi" else self._bt
        if not self._supported.get(kind, True) or not info or not info.get("available", False):
            return "unavailable"
        return "on" if info.get("on") else "off"

    def _toggle_texts(self, kind: str) -> tuple[str, str]:
        st = self._toggle_state(kind)
        if kind == "wifi":
            title = "Wi-Fi"
            if st == "busy":
                return title, "Açılıyor…" if self._busy["wifi"] == "on" else "Kapatılıyor…"
            if st == "unavailable":
                return title, "Kullanılamıyor"
            if st == "off":
                return title, "Kapalı"
            if self._wifi.get("connected"):
                sig = self._wifi.get("signal")
                ssid = self._wifi.get("ssid") or title
                return str(ssid), (f"Sinyal %{int(round(sig))}" if sig is not None else "Bağlı")
            return title, "Bağlı değil"
        title = "Bluetooth"
        if st == "busy":
            return title, "Açılıyor…" if self._busy["bluetooth"] == "on" else "Kapatılıyor…"
        if st == "unavailable":
            return title, "Kullanılamıyor"
        return title, "Açık" if st == "on" else "Kapalı"

    # -------------------------------------------------------------- yerleşim
    def _bat_card_height(self) -> float:
        h = ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP   # üst başlık
        h += 44.0                                    # hero satırı
        h += 8.0 + 12.0                              # çubuk
        lines = 0
        if self._bat.get("full_mwh") is not None and self._bat.get("design_mwh") is not None:
            lines += 1
        if fmt_watt(self._bat.get("rate_w")) and battery_state(self._bat) in ("battery", "charging"):
            lines += 1
        h += 8.0 + lines * 18.0 if lines else 0.0
        if self.show_top_load():
            h += 10.0 + 1.0 + 8.0 + 18.0 * len(self._top[:2])
        return h

    def _wireless_card_height(self) -> float:
        return ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + 52.0

    def compute_height(self) -> int:
        h = ps.PAD + ps.HEADER_H + ps.GAP + self._bat_card_height() + ps.GAP + self._wireless_card_height()
        h += ps.GAP + ps.FOOTER_H + ps.PAD * 0.5
        return int(round(h))

    # ------------------------------------------------------------- genel API
    def is_open(self) -> bool:
        return self.isVisible() and not getattr(self, "_closing", False)

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def show_for(self, anchor_global: Optional[QRectF], *args: Any, switch_from_x: Optional[int] = None, **kw: Any) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._closing = False
        self.resize(self.WIDTH, self.compute_height())
        tx, ty, dpr = 100, 100, 1.0
        if self._anchor_global is not None:
            tx = int(self._anchor_global.center().x() - self.width() / 2.0)
            ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
            scr = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                dpr = scr.devicePixelRatio()
                m = 8
                tx = max(g.left() + m, min(g.right() - self.width() - m, tx))
                if ty < g.top() + m:
                    ty = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
        winid = int(self.winId())
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(winid, self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass
        ps.animate_in(self, QPoint(tx, ty), switch_from_x=switch_from_x)
        self.activateWindow()
        self.setFocus()

    def hide_animated(self) -> None:
        if not self.isVisible() or getattr(self, "_closing", False):
            return
        self._closing = True
        self._last_close_time = time.monotonic()

        def _done() -> None:
            self._closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._closing = False
        ps.animate_out(self, instant=True)

    def panel_x(self) -> int:
        return int(self.x())

    # ---------------------------------------------------------------- olaylar
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not getattr(self, "_closing", False):
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(QCursor.pos())):
                    # Kapsül kendi tıklamasında kapatacak; sekmeyi yeniden açmasın
                    self._last_close_time = time.monotonic()
                    self._anchor_timer.start(300)
                else:
                    self.hide_animated()
        super().changeEvent(event)

    def _on_anchor_timeout(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and not getattr(self, "_closing", False):
            self.hide_animated()

    def hideEvent(self, event) -> None:
        self._closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def _hit(self, pos: QPointF) -> Optional[str]:
        for key in ("close", "wifi_main", "wifi_chev", "bt_main", "bt_chev", "footer_btn"):
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
            self.activate(self._hit(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    def activate(self, key: Optional[str]) -> None:
        """Tıklama davranışı (testlerde doğrudan çağrılabilir)."""
        if key == "close":
            self.hide_animated()
        elif key in ("wifi_main", "bt_main"):
            kind = "wifi" if key == "wifi_main" else "bluetooth"
            st = self._toggle_state(kind)
            if st in ("busy", "unavailable"):
                return
            target = st != "on"
            self.set_busy(kind, target)
            self.toggle_requested.emit(kind, target)
        elif key in ("wifi_chev", "bt_chev"):
            kind = "wifi" if key == "wifi_chev" else "bluetooth"
            self.hide_animated()
            self.settings_requested.emit(kind)
        elif key == "footer_btn":
            self.hide_animated()
            self.settings_requested.emit("power")

    # ----------------------------------------------------------------- çizim
    def render_to_image(self, dpr: float = 2.0) -> QImage:
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint(p)
        p.end()
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
        w, h = float(self.width()), float(self.height())
        ps.draw_panel_shell(p, QRectF(0, 0, w, h))
        self._rects = {}
        x0 = ps.PAD
        cw = w - 2 * ps.PAD
        y = ps.PAD

        # başlık
        b = self._bat
        chip = chip_text(b)
        dot = None
        if chip:
            dot = level_color(b.get("percent"), bool(b.get("charging"))) if b.get("percent") is not None else None
        hd = ps.draw_header(p, QRectF(x0, y, cw, ps.HEADER_H), "Pil ve bağlantılar", self._draw_header_icon,
                            chip=chip, chip_dot=dot, close_hover=(self._hover == "close"))
        if hd.get("close") is not None:
            self._rects["close"] = hd["close"]
        y += ps.HEADER_H + ps.GAP

        # pil durumu kartı
        card_h = self._bat_card_height()
        cap = b.get("capacity_pct")
        right = f"Kapasite {ps.pct(cap)}" if cap is not None else None
        inner = ps.draw_card(p, QRectF(x0, y, cw, card_h), "Pil durumu", right)
        self._paint_battery(p, inner)
        y += card_h + ps.GAP

        # kablosuz kartı
        wh = self._wireless_card_height()
        inner = ps.draw_card(p, QRectF(x0, y, cw, wh), "Kablosuz bağlantılar")
        bw = (inner.width() - 8.0) / 2.0
        for i, kind in enumerate(("wifi", "bluetooth")):
            r = QRectF(inner.left() + i * (bw + 8.0), inner.top(), bw, 52.0)
            title, sub = self._toggle_texts(kind)
            st = self._toggle_state(kind)
            hp = None
            pre = "wifi" if kind == "wifi" else "bt"
            if self._hover == f"{pre}_main":
                hp = "main"
            elif self._hover == f"{pre}_chev":
                hp = "chevron"
            res = ps.draw_toggle_button(p, r, title, sub, _icon_wifi if kind == "wifi" else _icon_bt,
                                        state=st, hover_part=hp, has_chevron=True)
            if res.get("main") is not None:
                self._rects[f"{pre}_main"] = res["main"]
            if res.get("chevron") is not None:
                self._rects[f"{pre}_chev"] = res["chevron"]
        y += wh + ps.GAP

        # alt bilgi
        fr = QRectF(x0, y, cw, ps.FOOTER_H)
        btn = ps.draw_footer(p, fr, f"Windows · {self._stamp}", "Güç ayarları", button_hover=(self._hover == "footer_btn"))
        if btn is not None:
            self._rects["footer_btn"] = btn

    @staticmethod
    def _draw_header_icon(p: QPainter, r: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(r.center().x() - 7.0, r.center().y() - 3.8, 12.5, 7.6)
        p.drawRoundedRect(body, 1.8, 1.8)
        p.drawLine(QPointF(body.right() + 1.6, r.center().y() - 1.8), QPointF(body.right() + 1.6, r.center().y() + 1.8))
        p.restore()

    def _paint_battery(self, p: QPainter, r: QRectF) -> None:
        b = self._bat
        has = bool(b.get("present")) and b.get("percent") is not None
        pct = float(b["percent"]) if has else None
        charging = bool(b.get("charging"))
        col = level_color(pct, charging)
        p.save()
        # hero satırı
        hero_rect = QRectF(r.left(), r.top(), 110.0, 40.0)
        p.setFont(ps.f_hero())
        p.setPen(ps.TEXT)
        p.drawText(hero_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, ps.pct(pct) if has else "—")
        hero_w = QFontMetricsF(ps.f_hero()).horizontalAdvance(ps.pct(pct) if has else "—")
        p.setFont(ps.f_body())
        p.setPen(ps.TEXT_BODY)
        p.drawText(QRectF(r.left() + hero_w + 10.0, r.top(), 120.0, 40.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, state_label(b))
        rem = fmt_remaining(b.get("secs_left")) if battery_state(b) == "battery" else None
        if rem:
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(r.right() - 110.0, r.top(), 110.0, 40.0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, rem)
        y = r.top() + 44.0 + 8.0
        # 12 px çubuk
        bar = QRectF(r.left(), y, r.width(), 12.0)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.TRACK)
        p.drawRoundedRect(bar, 6.0, 6.0)
        if has and pct > 0:
            fw = max(12.0, bar.width() * min(100.0, pct) / 100.0)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), fw, bar.height()), 6.0, 6.0)
        y += 12.0 + 8.0
        # telemetri
        p.setFont(ps.f_small())
        lines = []
        if b.get("full_mwh") is not None and b.get("design_mwh") is not None:
            lines.append(f"Tam dolum: {fmt_mwh(b['full_mwh'])} / {fmt_mwh(b['design_mwh'])} mWh")
        w = fmt_watt(b.get("rate_w"))
        if w and battery_state(b) == "battery":
            lines.append(f"Deşarj: {w}")
        elif w and battery_state(b) == "charging":
            lines.append(f"Şarj: {w}")
        for ln in lines:
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(r.left(), y, r.width(), 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, ln)
            y += 18.0
        # en yüksek yük
        if self.show_top_load():
            y += 10.0
            p.setPen(QPen(ps.FOOTER_LINE, 1.0))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            y += 8.0
            for pr in self._top[:2]:
                name = str(pr.get("name") or "—")
                cpu = pr.get("cpu")
                p.setFont(ps.f_small())
                p.setPen(ps.TEXT_BODY)
                p.drawText(QRectF(r.left(), y, r.width() - 70.0, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           ("En yüksek yük: " if pr is self._top[0] else "") + name)
                p.setPen(ps.TEXT_MUTED)
                p.drawText(QRectF(r.right() - 64.0, y, 64.0, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                           f"%{int(round(cpu))}" if cpu is not None else "—")
                y += 18.0
        p.restore()
