"""Şerit pencere seçici paneli (panel_style v2).

Bir uygulama kütüğünde birden çok pencere varsa bunları listeler. Panel yalnızca çizer ve
sinyal yayar; pencere numaralandırma, etkinleştirme veya kapatma işini dock yapar.
Gerçek pencere API'leri bu modülde çağrılmaz.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402

ROW_H = 36.0
MAX_VISIBLE = 8
WIDTH = 320
EMPTY_TITLE = "(adsız pencere)"
FOOTER_HINT = "Tıkla: pencereye geç · orta tık: kapat"


def _sanitize_windows(windows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(windows, (list, tuple)):
        return out
    for item in windows:
        if not isinstance(item, dict):
            continue
        hwnd = item.get("hwnd")
        if not isinstance(hwnd, int) or isinstance(hwnd, bool) or hwnd <= 0:
            continue
        raw_title = item.get("title")
        title = " ".join(raw_title.split()) if isinstance(raw_title, str) else ""
        out.append({
            "hwnd": int(hwnd),
            "title": title or EMPTY_TITLE,
            "minimized": bool(item.get("minimized")),
            "active": bool(item.get("active")),
        })
    return out


class WindowPicker(QWidget):
    """Uygulamanın pencerelerini seçtiren 320 px panel."""

    WIDTH = WIDTH

    window_chosen = Signal(int)
    close_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._app_name: str = "Pencereler"
        self._icon: Optional[QPixmap] = None
        self._windows: List[Dict[str, Any]] = []
        self._stamp: str = time.strftime("%H:%M")

        self._anchor_global: Optional[QRectF] = None
        self._last_close_time: float = 0.0
        self._closing: bool = False
        self._scroll_y: float = 0.0
        self._focus: int = 0
        self._focus_visible: bool = False

        self._hover_hwnd: Optional[int] = None
        self._hover_close_hwnd: Optional[int] = None
        self._hover_header_close: bool = False

        self._rects: Dict[str, QRectF] = {}
        self._row_hit_rects: List[Tuple[int, QRectF, Optional[QRectF]]] = []
        self._rows_view: QRectF = QRectF()

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self.resize(WIDTH, self.compute_height())

    # ------------------------------------------------------------------ veri
    def _row_count(self) -> int:
        return max(1, min(len(self._windows), MAX_VISIBLE))

    def _max_scroll(self) -> float:
        return max(0.0, float(len(self._windows) - MAX_VISIBLE) * ROW_H)

    def _card_height(self) -> float:
        return ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + self._row_count() * ROW_H

    def compute_height(self) -> int:
        h = ps.PAD + ps.HEADER_H + ps.GAP + self._card_height()
        h += ps.GAP + ps.FOOTER_H + ps.PAD * 0.5
        return int(round(h))

    def _active_index(self) -> int:
        for i, w in enumerate(self._windows):
            if w.get("active"):
                return i
        return 0

    def _index_of(self, hwnd: Optional[int]) -> int:
        if hwnd is None:
            return -1
        for i, w in enumerate(self._windows):
            if w["hwnd"] == hwnd:
                return i
        return -1

    def set_windows(self, windows: Any) -> None:
        """Pencere listesini güncelle; kaybolan satır düşer, boş liste paneli kapatır."""
        old_focus_hwnd = self._windows[self._focus]["hwnd"] if 0 <= self._focus < len(self._windows) else None
        old_hover = self._hover_hwnd
        self._windows = _sanitize_windows(windows)
        self._stamp = time.strftime("%H:%M")

        if not self._windows:
            self._focus = 0
            self._focus_visible = False
            self._hover_hwnd = None
            self._hover_close_hwnd = None
            self._scroll_y = 0.0
            if self.isVisible():
                self.hide_animated()
            return

        idx = self._index_of(old_focus_hwnd)
        self._focus = idx if idx >= 0 else self._active_index()
        self._hover_hwnd = old_hover if self._index_of(old_hover) >= 0 else None
        self._hover_close_hwnd = None
        self._scroll_y = max(0.0, min(self._max_scroll(), self._scroll_y))

        self._relayout_size()
        if self.isVisible() and not self._closing and self._anchor_global is not None:
            self.move(self._target_pos())

    def _relayout_size(self) -> None:
        h = self.compute_height()
        if h != self.height() or self.width() != WIDTH:
            self.resize(WIDTH, h)

    # ------------------------------------------------------------- genel API
    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def show_for(
        self,
        anchor_global: QRectF,
        app_name: str,
        icon: Optional[QPixmap],
        windows: list,
        switch_from_x: Optional[int] = None,
    ) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._app_name = str(app_name).strip() if app_name else "Pencereler"
        self._icon = icon if isinstance(icon, QPixmap) and not icon.isNull() else None
        self._windows = _sanitize_windows(windows)
        self._stamp = time.strftime("%H:%M")
        self._closing = False
        self._scroll_y = 0.0
        self._hover_hwnd = None
        self._hover_close_hwnd = None
        self._hover_header_close = False
        self._focus = self._active_index()
        self._focus_visible = False
        self._relayout_size()

        if not self._windows:
            if self.isVisible():
                self.hide_animated()
            return

        ps.animate_in(self, self._target_pos(), switch_from_x=switch_from_x)
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

    def _target_pos(self) -> QPoint:
        if self._anchor_global is None:
            return QPoint(100, 100)
        a = self._anchor_global
        w, h = self.width(), self.height()
        tx = int(round(a.center().x() - w / 2.0))
        ty = int(round(a.top() - h - ps.ANCHOR_GAP))
        screen = QGuiApplication.screenAt(a.center().toPoint()) or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            m = 8
            left, top = g.left() + m, g.top() + m
            right, bottom = g.right() - m, g.bottom() - m
            max_x, max_y = right - w, bottom - h
            tx = max(left, min(max_x, tx)) if max_x >= left else left
            if ty < top:
                below = int(round(a.bottom() + ps.ANCHOR_GAP))
                ty = below if below + h <= bottom else top
            ty = max(top, min(max_y, ty)) if max_y >= top else top
        return QPoint(int(tx), int(ty))

    # ---------------------------------------------------------------- olaylar
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self._windows:
                if not (0 <= self._focus < len(self._windows)):
                    self._focus = self._active_index()
                step = -1 if key == Qt.Key.Key_Up else 1
                self._focus = max(0, min(len(self._windows) - 1, self._focus + step))
                self._focus_visible = True
                self._ensure_focus_visible()
                self.update()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if 0 <= self._focus < len(self._windows):
                self._choose(self._windows[self._focus]["hwnd"])
            event.accept()
            return
        if key == Qt.Key.Key_Delete:
            if 0 <= self._focus < len(self._windows):
                self._request_close(self._windows[self._focus]["hwnd"])
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

    def wheelEvent(self, event) -> None:
        max_scroll = self._max_scroll()
        if max_scroll > 0.0:
            delta = event.angleDelta().y()
            if delta:
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - (delta / 120.0) * ROW_H))
                self._hover_hwnd = None
                self._hover_close_hwnd = None
                self.update()
                event.accept()
                return
        super().wheelEvent(event)

    def _row_at(self, pos: QPointF) -> Optional[Tuple[str, int]]:
        if self._rows_view.isNull() or not self._rows_view.contains(pos):
            return None
        for hwnd, row, close in self._row_hit_rects:
            if close is not None and close.contains(pos):
                return ("row_close", hwnd)
            if row.contains(pos):
                return ("row", hwnd)
        return None

    def _hit(self, pos: QPointF) -> Optional[Tuple[str, Optional[int]]]:
        close = self._rects.get("close")
        if close is not None and close.contains(pos):
            return ("close", None)
        row = self._row_at(pos)
        if row is not None:
            return (row[0], row[1])
        return None

    def mouseMoveEvent(self, event) -> None:
        hit = self._hit(event.position())
        header_close = bool(hit is not None and hit[0] == "close")
        row_hwnd = hit[1] if hit is not None and hit[0] in ("row", "row_close") else None
        close_hwnd = hit[1] if hit is not None and hit[0] == "row_close" else None
        if (header_close, row_hwnd, close_hwnd) != (self._hover_header_close, self._hover_hwnd, self._hover_close_hwnd):
            self._hover_header_close = header_close
            self._hover_hwnd = row_hwnd
            self._hover_close_hwnd = close_hwnd
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_header_close or self._hover_hwnd is not None or self._hover_close_hwnd is not None:
            self._hover_header_close = False
            self._hover_hwnd = None
            self._hover_close_hwnd = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit(event.position())
            if hit is not None:
                kind, hwnd = hit
                if kind == "close":
                    self.hide_animated()
                elif kind == "row_close" and hwnd is not None:
                    self._request_close(hwnd)
                elif kind == "row" and hwnd is not None:
                    self._choose(hwnd)
                event.accept()
                return
        elif event.button() == Qt.MouseButton.MiddleButton:
            hit = self._row_at(event.position())
            if hit is not None:
                self._request_close(hit[1])
                event.accept()
                return
        super().mousePressEvent(event)

    def _choose(self, hwnd: int) -> None:
        self.window_chosen.emit(int(hwnd))
        self.hide_animated()

    def _request_close(self, hwnd: int) -> None:
        self.close_requested.emit(int(hwnd))

    def _ensure_focus_visible(self) -> None:
        max_scroll = self._max_scroll()
        if max_scroll <= 0.0:
            return
        rel_top = self._focus * ROW_H
        view_h = MAX_VISIBLE * ROW_H
        if rel_top < self._scroll_y:
            self._scroll_y = rel_top
        elif rel_top + ROW_H > self._scroll_y + view_h:
            self._scroll_y = rel_top + ROW_H - view_h
        self._scroll_y = max(0.0, min(max_scroll, self._scroll_y))

    # ----------------------------------------------------------------- çizim
    def render_to_image(self, dpr: float = 2.0) -> QImage:
        img = QImage(
            max(1, int(self.width() * dpr)),
            max(1, int(self.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        try:
            self._paint(p)
        finally:
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
        self._row_hit_rects = []
        self._rows_view = QRectF()

        x0 = ps.PAD
        cw = w - 2 * ps.PAD
        y = ps.PAD

        icon = self._icon if self._icon is not None else self._draw_app_glyph
        hd = ps.draw_header(
            p,
            QRectF(x0, y, cw, ps.HEADER_H),
            self._app_name,
            icon,
            chip=f"{len(self._windows)} pencere",
            close_hover=self._hover_header_close,
        )
        if hd.get("close") is not None:
            self._rects["close"] = hd["close"]
        y += ps.HEADER_H + ps.GAP

        card_h = self._card_height()
        inner = ps.draw_card(p, QRectF(x0, y, cw, card_h), "Pencereler")
        self._rows_view = QRectF(inner)
        self._paint_rows(p, inner)
        y += card_h + ps.GAP

        fr = QRectF(x0, y, cw, ps.FOOTER_H)
        ps.draw_footer(p, fr, FOOTER_HINT, None)

    def _paint_rows(self, p: QPainter, inner: QRectF) -> None:
        if not inner.isValid() or inner.width() <= 0.0 or inner.height() <= 0.0:
            return

        max_scroll = self._max_scroll()
        scroll = max(0.0, min(max_scroll, self._scroll_y))
        view_h = self._row_count() * ROW_H

        if not self._windows:
            p.save()
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, "Pencere bulunamadı")
            p.restore()
            return

        p.save()
        p.setClipRect(QRectF(inner.left(), inner.top(), inner.width(), view_h))
        f_title = ps.f_body()
        f_mini = ps.font(10.5)
        fm_title = QFontMetricsF(f_title)
        fm_mini = QFontMetricsF(f_mini)
        mini_text = "küçültülmüş"
        mini_w = fm_mini.horizontalAdvance(mini_text)

        for i, item in enumerate(self._windows):
            hwnd = item["hwnd"]
            ry = inner.top() + i * ROW_H - scroll
            row = QRectF(inner.left(), ry, inner.width(), ROW_H)
            if row.bottom() <= inner.top() or row.top() >= inner.top() + view_h:
                continue

            hovered = hwnd == self._hover_hwnd
            focused = i == self._focus and self._focus_visible
            minimized = bool(item.get("minimized"))
            active = bool(item.get("active"))

            if hovered or focused:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.BUTTON_HOVER if hovered else ps.BUTTON_BG)
                p.drawPath(ps.rounded(row.adjusted(0.0, 1.0, 0.0, -1.0), 8.0))

            close_rect: Optional[QRectF] = None
            right = row.right() - 8.0

            if hovered:
                close_rect = QRectF(row.right() - 6.0 - 24.0, row.center().y() - 12.0, 24.0, 24.0)
                right = close_rect.left() - 6.0

            label_rect: Optional[QRectF] = None
            if minimized:
                label_rect = QRectF(right - mini_w, row.top(), mini_w, ROW_H)
                right = label_rect.left() - 8.0

            if active:
                bar = QRectF(row.left() + 3.0, row.center().y() - 9.0, 3.0, 18.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.ACCENT)
                p.drawPath(ps.rounded(bar, 1.5))

            text_left = row.left() + (13.0 if active else 8.0)
            title_w = max(0.0, right - text_left)
            p.setFont(f_title)
            p.setPen(ps.TEXT_MUTED if minimized else ps.TEXT)
            elided = fm_title.elidedText(item["title"], Qt.TextElideMode.ElideMiddle, max(10.0, title_w))
            p.drawText(
                QRectF(text_left, row.top(), title_w, ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                elided,
            )

            if label_rect is not None:
                p.setFont(f_mini)
                p.setPen(ps.TEXT_MUTED)
                p.drawText(
                    label_rect,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    mini_text,
                )

            if close_rect is not None:
                close_hot = hwnd == self._hover_close_hwnd
                if close_hot:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 48))
                    p.drawPath(ps.rounded(close_rect, 6.0))
                p.setPen(QPen(ps.TEXT if close_hot else ps.TEXT_CLOSE, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                c = close_rect.center()
                d = 3.6
                p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
                p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))

            self._row_hit_rects.append((hwnd, QRectF(row), QRectF(close_rect) if close_rect is not None else None))

        p.restore()

        if max_scroll > 0.0 and view_h > 24.0:
            content_h = len(self._windows) * ROW_H
            thumb_h = max(24.0, (view_h / content_h) * view_h)
            thumb_y = inner.top() + (scroll / max_scroll) * (view_h - thumb_h)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 45))
            p.drawRoundedRect(QRectF(inner.right() + 8.0, thumb_y, 3.0, thumb_h), 1.5, 1.5)
            p.restore()

    @staticmethod
    def _draw_app_glyph(p: QPainter, r: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 225), 1.4, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(r.center().x() - 8.0, r.center().y() - 6.5, 16.0, 13.0)
        p.drawRoundedRect(body, 2.0, 2.0)
        p.drawLine(QPointF(body.left() + 2.0, body.top() + 4.0), QPointF(body.right() - 2.0, body.top() + 4.0))
        p.restore()
