"""Şerit üzerine gelince önizleme kartı (v23).

Çalışan bir uygulama kütüğünün üzerinde fare durunca, kütüğün üstünde o uygulamanın pencerelerini
küçük canlı görüntüleriyle gösterir (Windows görev çubuğu önizlemesi gibi). Panel odak almaz,
yalnızca çizer ve sinyal yayar; görüntüleri dock sağlar. Gerçek pencere API'si bu modülde çağrılmaz.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402
from window_picker import EMPTY_TITLE, _sanitize_windows, split_title  # noqa: E402

PAD = 12.0
HEAD_H = 22.0
HEAD_GAP = 8.0
THUMB_W = 176.0
THUMB_H = 104.0
TITLE_GAP = 6.0
TITLE_H = 16.0
SUB_H = 14.0          # yalnız küçültülmüş pencere varsa ("küçültülmüş" satırı)
CARD_GAP = 8.0
MAX_CARDS = 4
MORE_W = 56.0
CLOSE_SZ = 20.0
PLACEHOLDER = QColor(0x26, 0x28, 0x2E)


def compute_size(n_windows: int, any_minimized: bool) -> Tuple[int, int]:
    """Panel boyutu (mantıksal px): içerik kadar geniş, kart sayısı en çok 4 (+N kutusu)."""
    n = max(1, int(n_windows))
    shown = min(n, MAX_CARDS)
    w = PAD * 2 + shown * THUMB_W + (shown - 1) * CARD_GAP
    if n > MAX_CARDS:
        w += CARD_GAP + MORE_W
    h = PAD + HEAD_H + HEAD_GAP + THUMB_H + TITLE_GAP + TITLE_H + PAD + (SUB_H if any_minimized else 0.0)
    return int(round(w)), int(round(h))


class HoverPreview(QWidget):
    """Uygulama kütüğünün üstünde açılan, odak almayan önizleme kartı."""

    window_chosen = Signal(int)
    close_requested = Signal(int)
    more_requested = Signal()
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self._app_key: Optional[str] = None
        self._app_name: str = ""
        self._icon: Optional[QPixmap] = None
        self._windows: List[Dict[str, Any]] = []
        self._thumbs: Dict[int, QImage] = {}
        self._anchor: Optional[QRectF] = None
        self._closing: bool = False
        self._hover_hwnd: Optional[int] = None
        self._hover_close: Optional[int] = None
        self._hover_more: bool = False
        self._cards: List[Tuple[int, QRectF, QRectF, QRectF]] = []  # hwnd, kart, görüntü, kapat
        self._more_rect: Optional[QRectF] = None
        self._relayout()

    # ------------------------------------------------------------------ durum
    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def current_app(self) -> Optional[str]:
        return self._app_key if self.is_open() else None

    def _relayout(self) -> None:
        w, h = compute_size(len(self._windows), any(x["minimized"] for x in self._windows[:MAX_CARDS]))
        if self.width() != w or self.height() != h:
            self.setFixedSize(w, h)

    def _target_pos(self) -> QPoint:
        if self._anchor is None:
            return QPoint(100, 100)
        a = self._anchor
        w, h = self.width(), self.height()
        tx = int(round(a.center().x() - w / 2.0))
        ty = int(round(a.top() - h - ps.ANCHOR_GAP))
        screen = QGuiApplication.screenAt(a.center().toPoint()) or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            m = 8
            left, top, right, bottom = g.left() + m, g.top() + m, g.right() - m, g.bottom() - m
            tx = max(left, min(right - w, tx)) if right - w >= left else left
            ty = max(top, min(bottom - h, ty)) if bottom - h >= top else top
        return QPoint(int(tx), int(ty))

    # ------------------------------------------------------------- dış arayüz
    def show_for(
        self,
        anchor_global: QRectF,
        app_key: str,
        app_name: str,
        icon: Optional[QPixmap],
        windows: list,
        thumbs: Optional[dict] = None,
    ) -> None:
        wins = _sanitize_windows(windows)
        if not wins:
            if self.isVisible():
                self.hide_animated()
            return
        same_app = self.is_open() and self._app_key == str(app_key)
        switching = self.is_open() and not same_app
        old_x = int(self.x())
        self._anchor = QRectF(anchor_global) if anchor_global is not None else None
        self._app_key = str(app_key)
        self._app_name = str(app_name or "").strip()
        self._icon = icon if isinstance(icon, QPixmap) and not icon.isNull() else None
        if not same_app:
            self._thumbs = {}
            self._hover_hwnd = self._hover_close = None
            self._hover_more = False
        self._windows = wins
        alive = {x["hwnd"] for x in wins}
        self._thumbs = {h: im for h, im in self._thumbs.items() if h in alive}
        self.set_thumbnails(thumbs or {}, repaint=False)
        self._relayout()
        self._closing = False
        if same_app:
            self.move(self._target_pos())  # aynı uygulama: animasyonu yeniden oynatma
            self.update()
            return
        ps.animate_in(self, self._target_pos(), switch_from_x=old_x if switching else None)
        self.update()

    def set_windows(self, windows: Any) -> None:
        wins = _sanitize_windows(windows)
        if not wins:
            self.hide_animated()
            return
        self._windows = wins
        alive = {x["hwnd"] for x in wins}
        self._thumbs = {h: im for h, im in self._thumbs.items() if h in alive}
        if self._hover_hwnd not in alive:
            self._hover_hwnd = self._hover_close = None
        self._relayout()
        if self.isVisible():
            self.move(self._target_pos())
        self.update()

    def set_thumbnails(self, thumbs: Any, repaint: bool = True) -> None:
        if not isinstance(thumbs, dict):
            return
        alive = {x["hwnd"] for x in self._windows}
        for h, img in thumbs.items():
            if isinstance(h, int) and not isinstance(h, bool) and h in alive and isinstance(img, QImage) \
                    and not img.isNull():
                self._thumbs[h] = img
        if repaint:
            self.update()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._closing:
            return
        self._closing = True

        def _done() -> None:
            self._closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        self._closing = False
        ps.animate_out(self, instant=True)

    # ---------------------------------------------------------------- olaylar
    def _hit(self, pos: QPointF) -> Tuple[str, Optional[int]]:
        for hwnd, card, _thumb, close in self._cards:
            if hwnd == self._hover_hwnd and close.contains(pos):
                return "close", hwnd
            if card.contains(pos):
                return "card", hwnd
        if self._more_rect is not None and self._more_rect.contains(pos):
            return "more", None
        return "", None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        kind, hwnd = self._hit(pos)
        if kind == "close":
            # kapat düğmesi yalnız üzerinde durulan kartta görünür; kart üzerindeyken hover korunur
            new = (hwnd, hwnd, False)
        elif kind == "card":
            new = (hwnd, None, False)
            for h, _card, _thumb, close in self._cards:
                if h == hwnd and close.contains(pos):
                    new = (hwnd, hwnd, False)
        elif kind == "more":
            new = (None, None, True)
        else:
            new = (None, None, False)
        if new != (self._hover_hwnd, self._hover_close, self._hover_more):
            self._hover_hwnd, self._hover_close, self._hover_more = new
            self.setCursor(Qt.CursorShape.PointingHandCursor if any(v for v in new) else Qt.CursorShape.ArrowCursor)
            self.update()

    def enterEvent(self, event) -> None:
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._hover_hwnd is not None or self._hover_more:
            self._hover_hwnd = self._hover_close = None
            self._hover_more = False
            self.update()
        self.hover_left.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        # hover durumu henüz güncellenmemiş olabilir (doğrudan tık): önce güncelle
        self.mouseMoveEvent(event)
        kind, hwnd = self._hit(pos)
        btn = event.button()
        if kind == "close" and btn == Qt.MouseButton.LeftButton and hwnd is not None:
            self.close_requested.emit(int(hwnd))
        elif kind == "card" and hwnd is not None:
            if btn == Qt.MouseButton.MiddleButton:
                self.close_requested.emit(int(hwnd))
            elif btn == Qt.MouseButton.LeftButton:
                self.window_chosen.emit(int(hwnd))
                self.hide_animated()
        elif kind == "more" and btn == Qt.MouseButton.LeftButton:
            self.more_requested.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ çizim
    def render_to_image(self, dpr: float = 2.0) -> QImage:
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            self._paint(p)
        finally:
            p.end()
        return img

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = float(self.width()), float(self.height())
        ps.draw_panel_shell(p, QRectF(0, 0, w, h))
        self._cards = []
        self._more_rect = None

        # başlık: simge + ad, sağda "N pencere"
        head = QRectF(PAD, PAD, w - 2 * PAD, HEAD_H)
        icon_r = QRectF(head.left(), head.center().y() - 8.0, 16.0, 16.0)
        self._draw_icon(p, icon_r, 1.0)
        n = len(self._windows)
        f_meta = ps.font(11.0)
        meta = f"{n} pencere" if n >= 2 else ""
        meta_w = QFontMetricsF(f_meta).horizontalAdvance(meta) if meta else 0.0
        f_name = ps.font(13.0, QFont.Weight.DemiBold)
        name_r = QRectF(icon_r.right() + 8.0, head.top(), head.width() - 24.0 - meta_w - 10.0, head.height())
        p.setFont(f_name)
        p.setPen(ps.TEXT)
        p.drawText(name_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetricsF(f_name).elidedText(self._app_name or "Uygulama", Qt.TextElideMode.ElideRight,
                                                    max(10.0, name_r.width())))
        if meta:
            p.setFont(f_meta)
            p.setPen(ps.TEXT_META)
            p.drawText(head, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, meta)

        # kartlar
        y0 = PAD + HEAD_H + HEAD_GAP
        card_h = THUMB_H + TITLE_GAP + TITLE_H + (SUB_H if any(x["minimized"] for x in self._windows[:MAX_CARDS]) else 0.0)
        f_title = ps.font(12.0)
        f_sub = ps.font(11.0)
        fm_t, fm_s = QFontMetricsF(f_title), QFontMetricsF(f_sub)
        x = PAD
        for item in self._windows[:MAX_CARDS]:
            hwnd = item["hwnd"]
            card = QRectF(x, y0, THUMB_W, card_h)
            thumb = QRectF(x, y0, THUMB_W, THUMB_H)
            close = QRectF(thumb.right() - CLOSE_SZ - 5.0, thumb.top() + 5.0, CLOSE_SZ, CLOSE_SZ)
            hovered = hwnd == self._hover_hwnd
            if hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.BUTTON_HOVER)
                p.drawPath(ps.rounded(card.adjusted(-4.0, -4.0, 4.0, 2.0), 10.0))
            self._draw_thumb(p, thumb, item)
            if item["active"]:
                p.setPen(QPen(ps.ACCENT, 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(ps.rounded(thumb.adjusted(0.8, 0.8, -0.8, -0.8), 7.5))

            # başlık satırı: temiz başlık + " · site"
            main, site = split_title(item["title"], self._app_name)
            tr = QRectF(x + 2.0, thumb.bottom() + TITLE_GAP, THUMB_W - 4.0, TITLE_H)
            p.setFont(f_title)
            p.setPen(ps.TEXT_MUTED if item["minimized"] else ps.TEXT)
            shown = fm_t.elidedText(main or EMPTY_TITLE, Qt.TextElideMode.ElideRight, tr.width())
            p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
            used = fm_t.horizontalAdvance(shown)
            if site and shown == main:
                rest = tr.width() - used
                tail = fm_s.elidedText(" · " + site, Qt.TextElideMode.ElideRight, rest)
                if rest > 30.0 and tail.strip(" ·…"):
                    p.setFont(f_sub)
                    p.setPen(ps.TEXT_META)
                    p.drawText(QRectF(tr.left() + used, tr.top(), rest, tr.height()),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, tail)
            if item["minimized"]:
                p.setFont(f_sub)
                p.setPen(ps.TEXT_META)
                p.drawText(QRectF(tr.left(), tr.bottom(), tr.width(), SUB_H),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "küçültülmüş")

            if hovered:
                hot = self._hover_close == hwnd
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.DANGER if hot else QColor(0, 0, 0, 150))
                p.drawEllipse(close)
                p.setPen(QPen(QColor(255, 255, 255), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                c, d = close.center(), 3.4
                p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
                p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
            self._cards.append((hwnd, QRectF(card), QRectF(thumb), QRectF(close)))
            x += THUMB_W + CARD_GAP

        if n > MAX_CARDS:
            more = QRectF(x, y0, MORE_W, THUMB_H)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ps.BUTTON_HOVER if self._hover_more else ps.BUTTON_BG)
            p.drawPath(ps.rounded(more, 8.0))
            p.setFont(ps.font(15.0, QFont.Weight.DemiBold))
            p.setPen(ps.TEXT if self._hover_more else ps.TEXT_MUTED)
            p.drawText(more, Qt.AlignmentFlag.AlignCenter, f"+{n - MAX_CARDS}")
            self._more_rect = QRectF(more)

    def _draw_icon(self, p: QPainter, r: QRectF, opacity: float) -> None:
        p.save()
        p.setOpacity(opacity)
        if self._icon is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(r.toRect(), self._icon)
        else:  # genel pencere simgesi
            p.setPen(QPen(ps.TEXT_MUTED, 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            box = r.adjusted(1.5, 2.5, -1.5, -2.5)
            p.drawRoundedRect(box, 2.5, 2.5)
            p.drawLine(QPointF(box.left(), box.top() + box.height() * 0.3),
                       QPointF(box.right(), box.top() + box.height() * 0.3))
        p.restore()

    def _draw_thumb(self, p: QPainter, r: QRectF, item: Dict[str, Any]) -> None:
        img = None if item["minimized"] else self._thumbs.get(item["hwnd"])
        p.save()
        p.setClipPath(ps.rounded(r, 8.0), Qt.ClipOperation.IntersectClip)
        if img is not None and img.width() > 0 and img.height() > 0:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            ia, ra = img.width() / img.height(), r.width() / r.height()
            if ia > ra:  # geniş görüntü: ortadan kırp
                sw = img.height() * ra
                src = QRectF((img.width() - sw) / 2.0, 0.0, sw, float(img.height()))
            else:        # uzun görüntü: üstten kırp (sekmeler görünsün)
                src = QRectF(0.0, 0.0, float(img.width()), img.width() / ra)
            p.drawImage(r, img, src)
        else:
            p.fillRect(r, PLACEHOLDER)
            s = 26.0
            self._draw_icon(p, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                            0.5 if item["minimized"] else 0.8)
        p.restore()
        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 31), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ps.rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), 7.5))
        p.restore()
