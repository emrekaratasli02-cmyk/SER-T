"""opencode_panel.py - OpenCode yerel kullanım detay paneli (panel_style v2, 352 px).

Kart tıklanınca açılır; son 24 saat / bugün / toplam kullanımı ve model başına
kırılımı gösterir. Yalnızca ``opencode_usage.read_usage()`` sonuçlarını okur;
ağ veya dosya erişimi yoktur. Odak almaz (bilgi paneli), dışarıya tıklanınca kapanır.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402
import dock_cards  # noqa: E402  (format_token_count)

try:
    import sources
except ImportError:  # pragma: no cover
    sources = None

try:
    import winapi
except ImportError:  # pragma: no cover
    winapi = None


def _log_err(scope: str, exc: Exception) -> None:
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(scope, exc)
        except Exception:
            pass


ROW_H = 18.0          # kart içi bilgi satırı
CARD_OVER_H = 25.0    # draw_card üst başlığı
MAX_MODELS = 5


def _models_sorted(by_model: Any) -> List[tuple]:
    if not isinstance(by_model, dict):
        return []
    items = []
    for k, v in by_model.items():
        try:
            items.append((str(k), int(v)))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda kv: kv[1], reverse=True)
    return items[:MAX_MODELS]


class OpencodePanel(ps.PopoverBase):
    """OpenCode kullanım paneli: son 24 saat + model kırılımı (salt okunur yerel DB)."""

    WIDTH: int = int(ps.PANEL_W)

    refresh_requested = Signal()

    _HINT = (
        "opencode.db içindeki son 24 saatlik mesajlardan toplanır.\n"
        "Giriş = modele giden token (istem + bağlam)\n"
        "Çıkış = üretilen token (cevaplar)\n"
        "Önbellek okuma = aynı bağlamın cache’ten yeniden okunması (ücretsiz)\n"
        "Sınırlı ücretsiz model: maliyet $0.00"
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            activate_on_show=False,
            outside_click_close=True,
            recently_closed_ms=250.0,
        )
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
        self.setToolTip(self._HINT)

        self._data: Dict[str, Any] = {}
        self._hover_close: bool = False
        self._hover_refresh: bool = False

        # Hit kutuları (çizimden bağımsız)
        self._rect_close = QRectF()
        self._rect_refresh = QRectF()

        self.resize(self.WIDTH, self.compute_height())
        self._layout()

    # ------------------------------------------------------------------ veri
    def set_data(self, d: Any) -> None:
        self._data = d if isinstance(d, dict) else {}
        h = self.compute_height()
        if h != self.height():
            self.resize(self.WIDTH, h)
        self._layout()
        self.update()

    # ------------------------------------------------------------------ yerleşim
    def _target_pos(self) -> QPoint:
        """Anchor'ın üzerinde ortalanmış, ekran sınırlarına sıkışmış hedef konum."""
        if self._anchor_global is None:
            return QPoint(100, 100)
        tx = int(self._anchor_global.center().x() - self.width() / 2.0)
        ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            margin = 8
            min_x = geom.left() + margin
            max_x = geom.right() - self.width() - margin
            tx = max(min_x, min(max_x, tx)) if max_x >= min_x else min_x
            min_y = geom.top() + margin
            max_y = geom.bottom() - self.height() - margin
            if ty < min_y:
                below_y = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
                tx_or = below_y if below_y + self.height() <= geom.bottom() - margin else min_y
                ty = tx_or
            elif ty > max_y:
                ty = max_y
        return QPoint(tx, ty)

    def _model_rows(self) -> List[tuple]:
        return _models_sorted(self._data.get("recent_by_model"))

    def _cards_height(self) -> float:
        n_models = max(1, len(self._model_rows()))
        card1 = 2 * ps.CARD_PAD + CARD_OVER_H + 6 * ROW_H
        card2 = 2 * ps.CARD_PAD + CARD_OVER_H + n_models * ROW_H
        return card1 + card2

    def compute_height(self) -> int:
        total = (
            ps.PAD + ps.HEADER_H + ps.GAP
            + self._cards_height()
            + 2 * ps.GAP
            + ps.FOOTER_H + ps.PAD * 0.5
        )
        return int(math.ceil(total))

    def _layout(self) -> None:
        w = float(self.width())
        cw = w - 2.0 * ps.PAD

        # Kapat (başlıkta, sağda)
        header_cy = ps.PAD + ps.HEADER_H / 2.0
        close_sz = min(ps.CLOSE_SZ, ps.HEADER_H)
        self._rect_close = QRectF(
            ps.PAD + cw - close_sz, header_cy - close_sz / 2.0, close_sz, close_sz
        )

        # Yenile düğmesi (alt bilgide, draw_footer dönen rect ile birebir aynı)
        y = ps.PAD + ps.HEADER_H + ps.GAP + self._cards_height() + 2 * ps.GAP
        fr = QRectF(ps.PAD, y, cw, ps.FOOTER_H)
        content_h = fr.height() - 3.0
        cy = fr.top() + 3.0 + content_h / 2.0
        f_ft = ps.font(11.0, QFont.Weight.Medium)
        tw = QFontMetricsF(f_ft).horizontalAdvance("Yenile")
        btn_w = min(tw + 26.0, max(32.0, cw * 0.55))
        btn_h = min(22.0, content_h)
        self._rect_refresh = QRectF(
            fr.right() - btn_w, cy - btn_h / 2.0, btn_w, btn_h
        )

    # ------------------------------------------------------------------ API
    def show_for(
        self,
        anchor_global: Optional[QRectF] = None,
        data: Any = None,
        switch_from_x: Optional[int] = None,
    ) -> None:
        try:
            if data is not None:
                self.set_data(data)
            self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
            h = self.compute_height()
            if h != self.height():
                self.resize(self.WIDTH, h)
            self._layout()

            dpr = 1.0
            if self._anchor_global is not None:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint())
                if screen is None:
                    screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    dpr = screen.devicePixelRatio()

            if winapi is not None and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(
                        int(self.winId()), self.width(), self.height(), int(ps.R_PANEL), dpr
                    )
                except Exception:
                    pass

            self._animate_in(switch_from_x)
        except Exception as exc:
            _log_err("opencode_panel_show_for", exc)

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
            self._paint_panel(p)
        finally:
            p.end()
        return img

    # ------------------------------------------------------------------ olaylar
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        hover_close = self._rect_close.contains(pos)
        hover_refresh = self._rect_refresh.contains(pos)
        if (hover_close, hover_refresh) != (self._hover_close, self._hover_refresh):
            self._hover_close = hover_close
            self._hover_refresh = hover_refresh
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_close or self._hover_refresh:
            self._hover_close = False
            self._hover_refresh = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._rect_close.contains(pos):
                self.hide_animated()
                event.accept()
                return
            if self._rect_refresh.contains(pos):
                self.refresh_requested.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ çizim
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint_panel(p)
        finally:
            p.end()

    def _paint_panel(self, p: QPainter) -> None:
        w = float(self.width())
        cw = w - 2.0 * ps.PAD
        d = self._data
        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, float(self.height())))

        # Başlık
        ps.draw_header(
            p,
            QRectF(ps.PAD, ps.PAD, cw, ps.HEADER_H),
            "OpenCode",
            chip="Son 24 sa",
            close_hover=self._hover_close,
        )

        y = ps.PAD + ps.HEADER_H + ps.GAP

        # Kart 1: SON 24 SAAT
        card1_h = 2 * ps.CARD_PAD + CARD_OVER_H + 6 * ROW_H
        inner1 = ps.draw_card(p, QRectF(ps.PAD, y, cw, card1_h), "Son 24 saat")
        self._paint_metric_rows(p, inner1, [
            ("Giriş", d.get("recent_input")),
            ("Çıkış", d.get("recent_output")),
            ("Önbellek okuma", d.get("recent_cache_read")),
            ("Önbellek yazma", d.get("recent_cache_write")),
            ("Token toplamı", d.get("recent_tokens")),
            ("Maliyet", f"${self._cost_str(d.get('recent_cost'))} · {int(d.get('recent_sessions') or 0)} oturum"),
        ])
        y += card1_h + ps.GAP

        # Kart 2: MODELLER (24 sa)
        models = self._model_rows()
        card2_h = 2 * ps.CARD_PAD + CARD_OVER_H + max(1, len(models)) * ROW_H
        inner2 = ps.draw_card(
            p,
            QRectF(ps.PAD, y, cw, card2_h),
            "Modeller",
            overline_right="24 sa" if models else None,
        )
        if models:
            self._paint_model_rows(p, inner2, models)
        else:
            p.setFont(ps.font(11.0))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(inner2, Qt.AlignmentFlag.AlignCenter, "Model kırılımı yok")
        y += card2_h + ps.GAP

        # Alt bilgi
        upd = str(d.get("updated") or "")
        btn = ps.draw_footer(
            p,
            QRectF(ps.PAD, y, cw, ps.FOOTER_H),
            f"opencode.db · {upd}" if upd else "opencode.db",
            "Yenile",
            self._hover_refresh,
        )
        if btn is not None:
            self._rect_refresh = QRectF(btn)

    def _paint_metric_rows(
        self,
        p: QPainter,
        inner: QRectF,
        rows: List[tuple],
        tail: Optional[str] = None,
    ) -> None:
        """'Etiket değer' satırları; varsa son satır tail metniyle değiştirilir."""
        f_lbl = ps.font(11.0, QFont.Weight.Medium)
        f_val = ps.font(11.5, QFont.Weight.DemiBold, tabular=True)
        fm_v = QFontMetricsF(f_val)
        y = inner.top()
        for i, (label, value) in enumerate(rows):
            is_tail_row = (tail is not None and i == len(rows) - 1)
            p.setFont(f_lbl)
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(inner.left(), y, inner.width() * 0.55, ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            p.setFont(f_val)
            p.setPen(ps.TEXT)
            if is_tail_row and tail is not None:
                text = fm_v.elidedText(tail, Qt.TextElideMode.ElideRight, inner.width())
            elif value is None:
                text = "—"
            elif isinstance(value, str):
                text = value
            else:
                text = dock_cards.format_token_count(value)
            p.drawText(
                QRectF(inner.left() + inner.width() * 0.55, y, inner.width() * 0.45, ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                text,
            )
            y += ROW_H

    def _paint_model_rows(self, p: QPainter, inner: QRectF, models: List[tuple]) -> None:
        f_name = ps.font(11.0)
        f_val = ps.font(11.0, QFont.Weight.DemiBold, tabular=True)
        fm_n = QFontMetricsF(f_name)
        fm_v = QFontMetricsF(f_val)
        name_w = inner.width() * 0.62
        val_w = inner.width() * 0.38 - 6.0
        y = inner.top()
        for name, tokens in models:
            p.setFont(f_name)
            p.setPen(ps.TEXT_BODY)
            p.drawText(
                QRectF(inner.left(), y, name_w, ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_n.elidedText(name, Qt.TextElideMode.ElideRight, max(20.0, name_w - 4.0)),
            )
            p.setFont(f_val)
            p.setPen(ps.TEXT)
            p.drawText(
                QRectF(inner.right() - val_w, y, val_w, ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                fm_v.elidedText(dock_cards.format_token_count(tokens), Qt.TextElideMode.ElideRight, val_w),
            )
            y += ROW_H

    @staticmethod
    def _cost_str(val: Any) -> str:
        try:
            return f"{float(val or 0.0):.2f}"
        except (TypeError, ValueError):
            return "—"
