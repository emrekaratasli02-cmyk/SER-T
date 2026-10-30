"""updates.py — Şerit dock winget güncelleme denetleyicisi (yalnız kontrol, asla kurmaz).

Parçalar:
  * WINGET_ARGS         — winget listeleme argümanları (kurulum/yükseltme parametresi içermez)
  * run_winget_list     — winget'i arka planda güvenle çalıştırır (test altında engellenir)
  * parse_winget_table  — dil bağımsız winget tablo ayrıştırıcı (Türkçe/İngilizce/ikinci tablo)
  * UpdateChecker       — atomik önbellekli denetleyici (24 sa periyot, hata durumunda 2 sa)
  * draw_updates_badge  — bant rozet çizici (açık tepsiye inen ok + sayaç rozeti)
  * band_width          — bant genişliği (güncelleme varsa 28 px, yoksa 0 px)
  * tooltip             — bant ipucu metni
  * UpdatesPanel        — panel_style bileşenleriyle açılır popup panel
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import logpath
import panel_style as ps
import theme

try:
    import winapi
except Exception:  # pragma: no cover
    winapi = None

# winget listeleme argümanları — ASLA install, --all veya -r içermez
WINGET_ARGS = (
    "winget",
    "upgrade",
    "--include-unknown",
    "--accept-source-agreements",
    "--disable-interactivity",
)

CHECK_PERIOD_S = 24 * 3600.0  # 24 saat
ERROR_RETRY_S = 2 * 3600.0   # 2 saat
BAND_ICON_W = 38.0

_TR_MONTHS = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _fmt_checked_at(ts: Optional[float]) -> str:
    """Türkçe tarih/saat biçimi: '30 Eki 23:10'."""
    if ts is None:
        return "—"
    try:
        lt = time.localtime(float(ts))
        month = _TR_MONTHS[lt.tm_mon]
        return f"{lt.tm_mday} {month} {lt.tm_hour:02d}:{lt.tm_min:02d}"
    except Exception:
        return "—"


def _fmt_time_short(ts: Optional[float]) -> str:
    """Kısa saat biçimi: '23:10'."""
    if ts is None:
        return "—"
    try:
        lt = time.localtime(float(ts))
        return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
    except Exception:
        return "—"


def run_winget_list(timeout: int = 120) -> str:
    """winget'in yükseltme listeleme komutunu çalıştırır (salt okunur liste, asla kurmaz).

    Test altında (logpath.is_running_under_test()) RuntimeError fırlatarak canlı
    çağrı yapılmasını engeller.
    """
    if logpath.is_running_under_test():
        raise RuntimeError("Test ortamında gerçek winget çalıştırılamaz")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        proc = subprocess.run(
            list(WINGET_ARGS),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
        return proc.stdout or ""
    except FileNotFoundError as exc:
        raise RuntimeError("winget yok") from exc
    except Exception as exc:
        raise RuntimeError(f"winget çalıştırma hatası: {exc}") from exc


def parse_winget_table(text: str) -> List[Dict[str, Any]]:
    """winget çıktı tablosunu dilden bağımsız olarak ayrıştırır.

    Özellikler:
      * Başlık öncesindeki spinner ve ANSI kaçış dizilerini temizler.
      * Çizgili ayırıcı satırın (---) hemen üzerindeki başlık kelimelerinin
        başlangıç konumlarına göre sütunları dil bağımsız dilimler.
      * Her öğe: {"name", "id", "version", "available", "source"}.
      * "available" sütunu boş olan satırları atlar.
      * Özeti görünce (sayı ile başlayan özet satırı) tabloyu sonlandırır.
      * İkinci tablo (bilinmeyen sürümler) varsa aynı mantıkla okuyup "unknown": True ekler.
    """
    if not text:
        return []

    # ANSI temizliği
    clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    raw_lines = clean_text.splitlines()

    items: List[Dict[str, Any]] = []
    table_count = 0
    i = 0
    n = len(raw_lines)

    while i < n:
        line = raw_lines[i]
        s = line.strip()

        # Çizgili ayırıcı satır tespiti
        if len(s) >= 5 and set(s) <= {"-", " "} and s.count("-") >= 5 and i > 0:
            header_line = raw_lines[i - 1]
            matches = list(re.finditer(r"\S+", header_line))

            # Başlık başında tek karakterlik spinner varsa ayıkla
            spinner_chars = {"\\", "/", "-", "|"}
            if matches and matches[0].group() in spinner_chars:
                matches = matches[1:]

            if len(matches) >= 4:
                if len(matches) >= 5:
                    col_starts = [
                        0,
                        matches[1].start(),
                        matches[2].start(),
                        matches[3].start(),
                        matches[4].start(),
                    ]
                else:
                    col_starts = [0, matches[1].start(), matches[2].start(), matches[3].start()]

                # Başlık öncesinde bilinmeyen sürüm açıklaması var mı?
                preceding = "\n".join(raw_lines[max(0, i - 6) : i]).lower()
                is_unknown = (
                    (table_count > 0)
                    or ("unknown" in preceding)
                    or ("belirlene" in preceding)
                    or ("geçerli sürüm" in preceding)
                )
                table_count += 1

                # Satırları tara
                j = i + 1
                while j < n:
                    row = raw_lines[j]
                    row_s = row.strip()
                    if not row_s:
                        j += 1
                        continue

                    # Yeni bir ayırıcı satır geldiyse mevcut tablodan çık
                    if len(row_s) >= 5 and set(row_s) <= {"-", " "} and row_s.count("-") >= 5:
                        break

                    # Özet satırı tespiti: bir sayı ile başlayıp kelimelerle devam eden satır
                    m_sum = re.match(r"^\s*(\d+)\s+([^\d\s].*)", row)
                    if m_sum:
                        is_summary = (
                            len(row) < col_starts[-1]
                            or not row[col_starts[1] : col_starts[2]].strip()
                            or any(
                                kw in row.lower()
                                for kw in (
                                    "upgrade",
                                    "upgrades",
                                    "yükseltme",
                                    "package",
                                    "paket",
                                    "available",
                                    "kullanılabilir",
                                )
                            )
                        )
                        if is_summary:
                            i = j
                            break

                    def _slice(s_text: str, start: int, end: Optional[int] = None) -> str:
                        if start >= len(s_text):
                            return ""
                        if end is None:
                            return s_text[start:].strip()
                        return s_text[start:end].strip()

                    name = _slice(row, col_starts[0], col_starts[1])
                    pkg_id = _slice(row, col_starts[1], col_starts[2])
                    version = _slice(row, col_starts[2], col_starts[3])
                    if len(col_starts) >= 5:
                        available = _slice(row, col_starts[3], col_starts[4])
                        source = _slice(row, col_starts[4], None)
                    else:
                        available = _slice(row, col_starts[3], None)
                        source = ""

                    j += 1

                    # available sütunu boş olanları veya isim/id olmayanları atla
                    if not available or (not name and not pkg_id):
                        continue

                    item: Dict[str, Any] = {
                        "name": name,
                        "id": pkg_id,
                        "version": version,
                        "available": available,
                        "source": source,
                    }
                    if is_unknown:
                        item["unknown"] = True

                    items.append(item)

        i += 1

    return items


class UpdateChecker:
    """winget güncelleme denetleyicisi. Atomik JSON önbellekli ve iş parçacığı güvenli."""

    def __init__(
        self,
        cache_path: Optional[Path | str] = None,
        runner: Optional[Any] = None,
        now: Optional[Any] = None,
    ) -> None:
        self._cache_path = (
            Path(cache_path) if cache_path is not None else logpath.get_cache_file("updates_cache.json")
        )
        self._runner = runner or run_winget_list
        self._now = now or time.time
        self._lock = threading.RLock()

    def _save_cache(self, checked_at: float, items: List[Dict[str, Any]], err: Optional[str]) -> None:
        payload = {
            "checked_at": checked_at,
            "items": items,
            "err": err,
        }
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_name(f"{self._cache_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._cache_path)

    def state(self) -> Dict[str, Any]:
        """Önbellekten son durumu okur (hiçbir harici komut çalıştırmaz)."""
        with self._lock:
            if not self._cache_path.exists():
                return {"count": None, "items": [], "checked_at": None, "err": None}
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                items = data.get("items")
                if not isinstance(items, list):
                    items = []
                err = data.get("err")
                checked_at = data.get("checked_at")
                count = None if err is not None else len(items)
                return {
                    "count": count,
                    "items": items,
                    "checked_at": float(checked_at) if checked_at is not None else None,
                    "err": str(err) if err is not None else None,
                }
            except Exception:
                return {"count": None, "items": [], "checked_at": None, "err": None}

    def due(self) -> bool:
        """Yeni bir kontrol zamanının gelip gelmediğini bildirir (24 saat, hata sonrası 2 saat)."""
        st = self.state()
        checked_at = st.get("checked_at")
        if checked_at is None:
            return True
        age = self._now() - float(checked_at)
        if age < 0:
            return False
        if st.get("err") is not None:
            return age >= ERROR_RETRY_S
        return age >= CHECK_PERIOD_S

    def check(self) -> Dict[str, Any]:
        """İşçi iş parçacığında çalışır: runner'ı çalıştırır, ayrıştırır, önbelleğe yazar."""
        with self._lock:
            t = float(self._now())
            try:
                out = self._runner()
                items = parse_winget_table(out)
                self._save_cache(t, items, None)
            except Exception as exc:
                self._save_cache(t, [], str(exc))
            return self.state()


def band_width(state: Optional[Dict[str, Any]]) -> float:
    """Güncelleme varsa 38 px genişlik, yoksa veya durum bilinmiyorsa 0 px (gizli)."""
    if not state or state.get("err"):
        return 0.0
    count = state.get("count")
    if count is not None and count >= 1:
        return BAND_ICON_W
    return 0.0


def _draw_tray_glyph(p: QPainter, cx: float, cy: float, col: QColor) -> None:
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Tepsi
    path = QPainterPath()
    path.moveTo(cx - 7.0, cy + 2.0)
    path.lineTo(cx - 7.0, cy + 6.0)
    path.lineTo(cx + 7.0, cy + 6.0)
    path.lineTo(cx + 7.0, cy + 2.0)
    p.drawPath(path)

    # İnen ok
    p.drawLine(QPointF(cx, cy - 6.0), QPointF(cx, cy + 2.5))
    path_arrow = QPainterPath()
    path_arrow.moveTo(cx - 3.5, cy - 0.5)
    path_arrow.lineTo(cx, cy + 3.0)
    path_arrow.lineTo(cx + 3.5, cy - 0.5)
    p.drawPath(path_arrow)


def draw_updates_badge(
    p: QPainter,
    rect: QRectF,
    state: Optional[Dict[str, Any]],
    hover: bool = False,
) -> None:
    """Bant rozeti (look B2): Tepsi glifi + sağında mavi (#6EA8FE) sayaç sayısı, çip yok."""
    if not state or state.get("err"):
        return
    count = state.get("count")
    if count is None or count < 1:
        return

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    cy = rect.center().y()
    gx = rect.left() + 9.0
    col = ps.TEXT if hover else ps.TEXT_BODY
    _draw_tray_glyph(p, gx, cy, col)

    tx = gx + 11.0
    f = theme.make_font(10.0, QFont.Weight.DemiBold, tabular=True)
    p.setFont(f)
    p.setPen(ps.ACCENT)
    txt = str(count) if count <= 99 else "99+"
    p.drawText(QPointF(tx, cy + 3.5), txt)

    p.restore()


def tooltip(state: Optional[Dict[str, Any]]) -> str:
    """Bant simgesi ipucu metni."""
    if not state:
        return "Güncellemeler kontrol edilmedi\nKaynak: winget (yalnız kontrol)"
    err = state.get("err")
    checked_at = state.get("checked_at")
    ts_str = _fmt_checked_at(checked_at)
    count = state.get("count")

    if err:
        return f"Güncelleme kontrolü başarısız: {err}\nSon kontrol: {ts_str}\nKaynak: winget (yalnız kontrol)"
    if count is None:
        return "Güncellemeler kontrol edilmedi\nKaynak: winget (yalnız kontrol)"
    if count == 0:
        return f"Tüm uygulamalar güncel\nSon kontrol: {ts_str}\nKaynak: winget (yalnız kontrol)"
    return f"{count} uygulama güncellenebilir\nSon kontrol: {ts_str}\nKaynak: winget (yalnız kontrol)"


class UpdatesPanel(QWidget):
    """Güncellemeler açılır paneli (panel_style kiti ile oluşturulur)."""

    WIDTH = int(ps.PANEL_W)
    check_requested = Signal()

    def __init__(
        self,
        checker: Optional[UpdateChecker] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._checker = checker
        self._state: Dict[str, Any] = (
            checker.state() if checker else {"count": None, "items": [], "checked_at": None, "err": None}
        )

        self._rects: Dict[str, QRectF] = {}
        self._row_rects: List[QRectF] = []
        self._hover_idx: Optional[int] = None
        self._close_hover = False
        self._refresh_hover = False
        self._closing = False
        self._anchor_global: Optional[QRectF] = None
        self._last_close_time = 0.0

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self.refresh()

    def set_state(self, state: Dict[str, Any]) -> None:
        """Paneli verilen durum ile doğrudan günceller."""
        self._state = dict(state)
        self.refresh()

    def compute_height(self) -> int:
        """Mevcut içeriğe göre yükseklik hesabı."""
        h = 13.0 + 32.0 + 10.0  # PAD_V + HDR_H + GAP
        items = self._state.get("items") or []
        err = self._state.get("err")

        if err:
            h += 60.0
        elif not items:
            h += 54.0
        else:
            n = min(len(items), 8)
            h += n * 38.0 + (n - 1) * 6.0
            if len(items) > 8:
                h += 6.0 + 26.0

        h += 10.0 + 32.0 + 13.0  # GAP + FTR_H + PAD_V
        return int(round(h))

    def _layout(self) -> None:
        w = float(self.width())
        self._rects = {}
        self._row_rects = []

        y = 13.0
        self._rects["hdr"] = QRectF(16.0, y, w - 32.0, 32.0)
        y += 32.0 + 10.0

        items = self._state.get("items") or []
        err = self._state.get("err")

        if err:
            self._rects["err_box"] = QRectF(16.0, y, w - 32.0, 60.0)
            y += 60.0
        elif not items:
            self._rects["empty_box"] = QRectF(16.0, y, w - 32.0, 54.0)
            y += 54.0
        else:
            n = min(len(items), 8)
            for i in range(n):
                r = QRectF(16.0, y + i * (38.0 + 6.0), w - 32.0, 38.0)
                self._row_rects.append(r)
            y += n * 38.0 + (n - 1) * 6.0
            if len(items) > 8:
                y += 6.0
                self._rects["more_box"] = QRectF(16.0, y, w - 32.0, 26.0)
                y += 26.0

        y += 10.0
        ftr_r = QRectF(16.0, y, w - 32.0, 32.0)
        self._rects["footer"] = ftr_r

        # Başlık kapat butonu (çizim öncesi de tıklanabilsin)
        close_sz = min(ps.CLOSE_SZ, self._rects["hdr"].height())
        cy_hdr = self._rects["hdr"].center().y()
        self._rects["close"] = QRectF(
            self._rects["hdr"].right() - close_sz,
            cy_hdr - close_sz / 2.0,
            close_sz,
            close_sz,
        )

        # 'Şimdi kontrol et' düğmesi (draw_footer ile birebir aynı ölçü)
        cr = QRectF(ftr_r.left(), ftr_r.top() + 3.0, ftr_r.width(), max(0.0, ftr_r.height() - 3.0))
        f_btn = ps.font(11.5, QFont.Weight.Medium)
        fm_btn = QFontMetricsF(f_btn)
        tw = fm_btn.horizontalAdvance("Şimdi kontrol et")
        bw = min(tw + 20.0, max(28.0, cr.width() * 0.55))
        bh = min(24.0, cr.height())
        self._rects["refresh"] = QRectF(cr.right() - bw, cr.center().y() - bh / 2.0, bw, bh)

    def refresh(self) -> None:
        if self._checker is not None:
            self._state = self._checker.state()
        h = self.compute_height()
        if h != self.height() or self.width() != self.WIDTH:
            old_h = self.height()
            self.resize(self.WIDTH, h)
            if self.isVisible() and old_h > 0:
                self.move(self.x(), self.y() - (h - old_h))
                self._apply_round()
        self._layout()
        self.update()

    def _apply_round(self) -> None:
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                scr = self.screen() or QGuiApplication.primaryScreen()
                dpr = scr.devicePixelRatio() if scr is not None else 1.0
                winapi.set_round_region(int(self.winId()), self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass

    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def show_for(
        self,
        anchor_global: Optional[QRectF],
        *args: Any,
        switch_from_x: Optional[int] = None,
        **kw: Any,
    ) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._closing = False
        self.refresh()
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
                if ty + self.height() > g.bottom() - m:
                    ty = max(g.top() + m, g.bottom() - self.height() - m)

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
        if not self.isVisible() or self._closing:
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
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self._layout()
        super().resizeEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        old_close = self._close_hover
        old_refresh = self._refresh_hover
        old_hrow = self._hover_idx

        close_r = self._rects.get("close")
        self._close_hover = bool(close_r and close_r.contains(pos))

        refresh_r = self._rects.get("refresh")
        self._refresh_hover = bool(refresh_r and refresh_r.contains(pos))

        self._hover_idx = None
        for i, r in enumerate(self._row_rects):
            if r.contains(pos):
                self._hover_idx = i
                break

        if (
            self._close_hover != old_close
            or self._refresh_hover != old_refresh
            or self._hover_idx != old_hrow
        ):
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._close_hover or self._refresh_hover or self._hover_idx is not None:
            self._close_hover = False
            self._refresh_hover = False
            self._hover_idx = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            close_r = self._rects.get("close")
            if close_r and close_r.contains(pos):
                self.hide_animated()
                return

            refresh_r = self._rects.get("refresh")
            if refresh_r and refresh_r.contains(pos):
                self.check_requested.emit()
                return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
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

        # Başlık ve sayaç rozeti
        count = self._state.get("count")
        err = self._state.get("err")
        items = self._state.get("items") or []

        chip_str: Optional[str] = None
        chip_dot: Optional[QColor] = None
        if err:
            chip_str = "Hata"
            chip_dot = ps.WARN
        elif count is not None:
            chip_str = str(count)

        hdr_rect = self._rects.get("hdr", QRectF(16.0, 13.0, w - 32.0, 32.0))
        hdr_res = ps.draw_header(
            p,
            hdr_rect,
            title="Güncellemeler",
            icon=None,
            chip=chip_str,
            chip_dot=chip_dot,
            close_hover=self._close_hover,
        )
        if hdr_res.get("close"):
            self._rects["close"] = hdr_res["close"]

        # Gövde
        if err:
            box = self._rects.get("err_box", QRectF(16.0, 55.0, w - 32.0, 60.0))
            ps.draw_tile(p, box)
            p.save()
            p.setFont(ps.font(12.0, QFont.Weight.DemiBold))
            p.setPen(ps.WARN)
            p.drawText(
                QRectF(box.left() + 10.0, box.top() + 10.0, box.width() - 20.0, 18.0),
                Qt.AlignmentFlag.AlignCenter,
                "Güncelleme kontrolü yapılamadı",
            )
            f_err = ps.font(11.0, QFont.Weight.Normal)
            p.setFont(f_err)
            p.setPen(ps.TEXT_LABEL)
            fm_err = QFontMetricsF(f_err)
            elided_err = fm_err.elidedText(str(err), Qt.TextElideMode.ElideRight, box.width() - 20.0)
            p.drawText(
                QRectF(box.left() + 10.0, box.top() + 32.0, box.width() - 20.0, 18.0),
                Qt.AlignmentFlag.AlignCenter,
                elided_err,
            )
            p.restore()
        elif not items:
            box = self._rects.get("empty_box", QRectF(16.0, 55.0, w - 32.0, 54.0))
            ps.draw_tile(p, box)
            p.save()
            p.setFont(ps.font(12.5, QFont.Weight.Medium))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "Tüm uygulamalar güncel")
            p.restore()
        else:
            f_name = ps.font(12.5, QFont.Weight.Medium)
            f_ver = ps.font(11.0, QFont.Weight.Normal, tabular=True)
            fm_name = QFontMetricsF(f_name)
            fm_ver = QFontMetricsF(f_ver)

            n = min(len(items), 8)
            for i in range(n):
                if i >= len(self._row_rects):
                    break
                row_r = self._row_rects[i]
                it = items[i]
                is_hov = self._hover_idx == i

                ps.draw_tile(p, row_r, hover=is_hov)

                p.save()
                cur_v = it.get("version") or "—"
                avail_v = it.get("available") or "—"
                ver_txt = f"{cur_v} → {avail_v}"
                ver_w = fm_ver.horizontalAdvance(ver_txt)

                # Sağ sürüm geçişi
                p.setFont(f_ver)
                p.setPen(ps.TEXT_MUTED)
                ver_r = QRectF(row_r.right() - 12.0 - ver_w, row_r.top(), ver_w, row_r.height())
                p.drawText(ver_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, ver_txt)

                # Sol uygulama adı
                name_w = max(0.0, ver_r.left() - 10.0 - (row_r.left() + 12.0))
                name_r = QRectF(row_r.left() + 12.0, row_r.top(), name_w, row_r.height())
                elided_name = fm_name.elidedText(it.get("name") or "", Qt.TextElideMode.ElideRight, name_w)
                p.setFont(f_name)
                p.setPen(ps.TEXT)
                p.drawText(name_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_name)
                p.restore()

            if len(items) > 8:
                more_box = self._rects.get("more_box")
                if more_box:
                    p.save()
                    p.setFont(ps.font(11.5, QFont.Weight.Medium))
                    p.setPen(ps.TEXT_LABEL)
                    p.drawText(
                        more_box,
                        Qt.AlignmentFlag.AlignCenter,
                        f"+{len(items) - 8} daha",
                    )
                    p.restore()

        # Alt bilgi
        ftr_rect = self._rects.get("footer", QRectF(16.0, h - 45.0, w - 32.0, 32.0))
        checked_at = self._state.get("checked_at")
        t_str = _fmt_time_short(checked_at)
        src_text = f"winget · son kontrol {t_str}"

        btn_rect = ps.draw_footer(
            p,
            ftr_rect,
            source_text=src_text,
            button_text="Şimdi kontrol et",
            button_hover=self._refresh_hover,
        )
        if btn_rect is not None:
            self._rects["refresh"] = btn_rect
