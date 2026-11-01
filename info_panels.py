"""info_panels.py - Mail ve Antigravity kotaları panelleri (panel_style v2 ortak dili).

MailPanel: 'Yanıt bekleyen mailler' — hesap başına bekleyen iş parçacıkları, sayılar,
boş hesap durumu ve satır tıklamaları. QuotaPanel: Antigravity model kotaları — model
başına ince çubuk, sıfırlanma metni ve yüzde. İki panel de aynı başlık/kart/alt bilgi
iskeletini, aynı açılış-kapanış hareketini ve 352 px genişliği kullanır.

Veri yoksa değer uydurulmaz: eksik değer '—' veya boş iz olarak çizilir.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

# Shared style tokens and helpers
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

import panel_style as ps  # noqa: E402

try:
    import dock_cards
    import sources
    import winapi
    import work_sources
except ImportError:  # pragma: no cover - minimal test environments
    dock_cards = None
    sources = None
    winapi = None
    work_sources = None

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Hesap bölünmüş çubuğu renkleri (IAS / Kişisel / Logaritma)
ACCOUNT_SPLIT_COLORS: Dict[str, QColor] = {
    "ias": QColor("#4285F4"),
    "kisisel02": QColor("#A855F7"),
    "kisisel": QColor("#A855F7"),
    "logaritma": QColor("#30D158"),
}


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available, never raising."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
    italic: bool = False,
) -> QFont:
    """Create a high-DPI font instance with Segoe UI Variable fallback."""
    f = ps.font(size_px, weight, tabular)
    f.setItalic(italic)
    if letter_spacing is not None:
        try:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        except Exception:
            pass
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    return ps.rounded(rect, radius)


def format_merged_labels(labels: List[str]) -> str:
    """Join labels into a unified string, eliding a common prefix when identical."""
    cleaned = [str(l).strip() for l in labels if str(l).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    words = [c.split() for c in cleaned if c.split()]
    if words and len(words) == len(cleaned):
        first_word = words[0][0]
        if all(w[0] == first_word for w in words):
            suffixes = [c[len(first_word):].strip() for c in cleaned]
            if all(suffixes):
                return f"{first_word} " + " · ".join(suffixes)

    return " · ".join(cleaned)


def merge_quota_groups(groups: Any) -> List[Dict[str, Any]]:
    """Merge groups with identical (used, reset_tr) into one row (legacy helper)."""
    if not isinstance(groups, list):
        return []

    batches: Dict[Tuple[float, str], List[Dict[str, Any]]] = {}
    order: List[Tuple[float, str]] = []

    for g in groups:
        if not isinstance(g, dict):
            continue
        raw_label = str(g.get("label") or "").strip()
        try:
            used_val = float(g.get("used", 0.0))
            if math.isnan(used_val) or math.isinf(used_val):
                used_val = 0.0
        except (ValueError, TypeError):
            used_val = 0.0
        used = max(0.0, min(100.0, round(used_val, 1)))

        reset_tr = str(g.get("reset_tr") or "").strip()
        key = (used, reset_tr)

        if key not in batches:
            batches[key] = []
            order.append(key)
        batches[key].append({
            "label": raw_label,
            "used": used,
            "reset_tr": reset_tr if reset_tr else None,
            "reset_at": g.get("reset_at"),
        })

    merged: List[Dict[str, Any]] = []
    for key in order:
        items = batches[key]
        labels = [it["label"] for it in items]
        merged.append({
            "label": format_merged_labels(labels),
            "used": key[0],
            "reset_tr": key[1] if key[1] else None,
            "reset_at": items[0].get("reset_at"),
            "raw_labels": labels,
        })

    return merged


def _stamp(raw: Any) -> str:
    """ISO timestamp -> 'HH:MM'; unknown -> '—'."""
    if not raw:
        return "—"
    try:
        clean = str(raw).replace("Z", "+00:00")
        return dt.datetime.fromisoformat(clean).astimezone().strftime("%H:%M")
    except Exception:
        s = str(raw)
        return s[:5] if len(s) >= 5 else s or "—"


def _norm_used(value: Any) -> Optional[float]:
    """Quota percentage; None/invalid stays None (no invented data)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return max(0.0, min(100.0, round(f, 1)))


def quota_identity_color(label: Any) -> QColor:
    """Claude = CLAUDE, GPT-OSS = neutral grey-white, Gemini = ACCENT."""
    s = str(label or "").lower()
    if "claude" in s:
        return ps.CLAUDE
    if "gpt" in s or "oss" in s:
        return QColor(0xD5, 0xD9, 0xE0)
    if "gemini" in s or "argon" in s:  # v24: Argon = Gemini 4 Argon
        return ps.ACCENT
    return ps.TEXT_BODY


# ---------------------------------------------------------------------------
# Base popover (shared dock flyout architecture)
# ---------------------------------------------------------------------------
class _BasePopover(QWidget):
    """Opaque panel shell with the shared 352 px chrome, hit rects and motion."""

    WIDTH: int = int(ps.WIDTH["mail"])
    RADIUS: float = ps.R_PANEL
    BODY_MAX_HEIGHT: float = 560.0

    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._anchor_global: Optional[QRectF] = None
        self._last_close_time: float = 0.0
        self._is_closing: bool = False
        self._scroll_y: float = 0.0

        self._rects: Dict[str, QRectF] = {}
        self._close_rect: QRectF = QRectF()
        self._refresh_rect: QRectF = QRectF()
        self._close_hovered: bool = False
        self._refresh_hovered: bool = False
        self._refresh_pressed: bool = False

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self.resize(self.WIDTH, 200)

    # ------------------------------------------------------------------ API
    def is_open(self) -> bool:
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def set_data(self, d: Any) -> None:
        raise NotImplementedError

    def _body_total_height(self) -> float:
        raise NotImplementedError

    def _body_view_height(self) -> float:
        top = ps.PAD + ps.HEADER_H + ps.GAP
        bottom = self.height() - ps.PAD * 0.5 - ps.FOOTER_H - ps.GAP
        return max(0.0, bottom - top)

    def compute_height(self) -> int:
        body = min(self.BODY_MAX_HEIGHT, max(1.0, self._body_total_height()))
        total = (ps.PAD + ps.HEADER_H + ps.GAP + body
                 + ps.GAP + ps.FOOTER_H + ps.PAD * 0.5)
        return int(math.ceil(total))

    def show_for(
        self,
        anchor_global: Optional[QRectF] = None,
        data: Any = None,
        switch_from_x: Optional[int] = None,
    ) -> None:
        """Position above the anchor and animate in with the shared motion."""
        try:
            if data is not None:
                self.set_data(data)

            self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
            self.resize(self.WIDTH, self.compute_height())

            target = QPoint(100, 100)
            dpr = 1.0
            if self._anchor_global is not None:
                tx = int(self._anchor_global.center().x() - self.width() / 2.0)
                ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
                screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint())
                if screen is None:
                    screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geom = screen.availableGeometry()
                    dpr = screen.devicePixelRatio()
                    margin = 8
                    min_x = geom.left() + margin
                    max_x = geom.right() - self.width() - margin
                    tx = max(min_x, min(max_x, tx)) if max_x >= min_x else min_x
                    min_y = geom.top() + margin
                    max_y = geom.bottom() - self.height() - margin
                    if ty < min_y:
                        below_y = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
                        ty = below_y if below_y + self.height() <= geom.bottom() - margin else min_y
                    elif ty > max_y:
                        ty = max_y
                target = QPoint(tx, ty)

            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(hwnd, self.width(), self.height(),
                                            int(ps.R_PANEL), dpr)
                except Exception as exc:
                    _log_err("_BasePopover.winapi", exc)

            self._is_closing = False
            ps.animate_in(self, target, switch_from_x=switch_from_x)
            self.activateWindow()
            self.setFocus()
        except Exception as exc:
            _log_err("_BasePopover.show_for", exc)

    def hide_animated(self) -> None:
        if not self.isVisible() or self._is_closing:
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()

        def _done() -> None:
            self._is_closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        """Close without animation (e.g. capsule section switch)."""
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._is_closing = False
        ps.animate_out(self, instant=True)

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_content(p)
        finally:
            p.end()
        return img

    # --------------------------------------------------------------- events
    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(QCursor.pos())):
                    self._last_close_time = time.monotonic()
                    self._anchor_timer.start(300)
                else:
                    self.hide_animated()
        super().changeEvent(event)

    def hideEvent(self, event: Any) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._close_hovered = False
        self._refresh_hovered = False
        self._refresh_pressed = False
        self.update()
        super().leaveEvent(event)

    def _hit(self, pos: QPointF) -> Optional[str]:
        for key in ("close", "refresh"):
            r = self._rects.get(key)
            if r is not None and not r.isNull() and r.contains(pos):
                return key
        return None

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            key = self._hit(event.position())
            if key == "close":
                self.hide_animated()
                event.accept()
                return
            if key == "refresh":
                self._refresh_pressed = True
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._refresh_pressed:
            self._refresh_pressed = False
            pos = event.position()
            if self._refresh_rect.contains(pos):
                self.refresh_requested.emit()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        pos = event.position()
        old = (self._close_hovered, self._refresh_hovered)
        self._close_hovered = self._close_rect.contains(pos)
        self._refresh_hovered = self._refresh_rect.contains(pos)
        if old != (self._close_hovered, self._refresh_hovered):
            self.update()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: Any) -> None:
        total = self._body_total_height()
        view = self._body_view_height()
        max_scroll = max(0.0, total - view)
        if max_scroll > 0.0:
            step = (event.angleDelta().y() / 120.0) * 40.0
            self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
            self.update()
        super().wheelEvent(event)

    # --------------------------------------------------------------- paint
    def paintEvent(self, _event: Any) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_content(p)
        finally:
            p.end()

    def _paint_content(self, p: QPainter) -> None:
        raise NotImplementedError

    def _paint_scroll_indicator(self, p: QPainter, body_top: float, body_h: float) -> None:
        total = self._body_total_height()
        if total <= body_h + 0.5:
            return
        max_scroll = total - body_h
        thumb_h = max(24.0, body_h * (body_h / total))
        thumb_y = body_top + (self._scroll_y / max_scroll) * (body_h - thumb_h)
        thumb = QRectF(self.width() - 7.0, thumb_y, 3.0, thumb_h)
        p.fillPath(rounded_path(thumb, 1.5), QColor(255, 255, 255, 70))

    def _chrome_rects(self) -> Tuple[float, float, float]:
        body_top = ps.PAD + ps.HEADER_H + ps.GAP
        footer_top = self.height() - ps.PAD * 0.5 - ps.FOOTER_H
        body_h = max(0.0, footer_top - ps.GAP - body_top)
        return body_top, body_h, footer_top


# ---------------------------------------------------------------------------
# 1) MailPanel: 'Yanıt bekleyen mailler'
# ---------------------------------------------------------------------------
class MailPanel(_BasePopover):
    """Mail panel: waiting threads per account, counts and empty state."""

    WIDTH: int = int(ps.WIDTH["mail"])
    ASSET_GMAIL: Path = ASSETS_DIR / "gmail.svg"

    HERO_H: float = 115.0
    ROW_H: float = 40.0
    ROW_GAP: float = 6.0
    CLOSED_ROW_H: float = 20.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: Dict[str, Any] = {}
        self._accounts: List[Dict[str, Any]] = []
        self._total_open: int = 0
        self._hidden_auto: int = 0
        self._scanned_at_str: str = ""
        self._stale: bool = False
        self._hover_item_url: Optional[str] = None
        self._row_rects: List[Tuple[QRectF, Dict[str, Any]]] = []

        self._svg_renderer: Optional[QSvgRenderer] = None
        if self.ASSET_GMAIL.is_file():
            try:
                self._svg_renderer = QSvgRenderer(str(self.ASSET_GMAIL))
            except Exception as exc:
                _log_err("MailPanel.svg_load", exc)

        self.resize(self.WIDTH, self.compute_height())

    def set_data(self, d: Any) -> None:
        """Update panel with result from fetch_mail_waiting()."""
        try:
            if not isinstance(d, dict):
                d = {}
            self._data = d
            self._total_open = max(0, int(d.get("total_open") or 0))
            self._hidden_auto = max(0, int(d.get("hidden_auto") or 0))
            self._stale = bool(d.get("stale", False))
            self._scanned_at_str = _stamp(d.get("scanned_at")) if d.get("scanned_at") else ""

            account_order = [("ias", "IAS"), ("kisisel02", "Kişisel"), ("logaritma", "Logaritma")]
            raw_accounts = d.get("accounts") if isinstance(d.get("accounts"), list) else []
            acc_by_key: Dict[str, Dict[str, Any]] = {}
            for a in raw_accounts:
                if isinstance(a, dict):
                    acc_by_key[str(a.get("key") or "").lower()] = a

            self._accounts = []
            for k, default_label in account_order:
                a_data = acc_by_key.get(k)
                if a_data is not None:
                    self._accounts.append(a_data)
                else:
                    self._accounts.append({
                        "key": k,
                        "label": default_label,
                        "open": 0,
                        "hidden_auto": 0,
                        "items": [],
                    })

            self._scroll_y = 0.0
            self.resize(self.WIDTH, self.compute_height())
            self.update()
        except Exception as exc:
            _log_err("MailPanel.set_data", exc)

    def _items_for_account(self, acc: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
        raw_items = acc.get("items") if isinstance(acc.get("items"), list) else []
        active: List[Dict[str, Any]] = []
        closed: List[Dict[str, Any]] = []
        for it in raw_items:
            if not isinstance(it, dict) or it.get("auto"):
                continue
            if it.get("kapanis_tahmini"):
                closed.append(it)
            else:
                active.append(it)
        hidden = max(0, int(acc.get("hidden_auto") or 0))
        return active, closed, hidden

    def _account_card_height(self, acc: Dict[str, Any]) -> float:
        active, closed, hidden = self._items_for_account(acc)
        content = 18.0
        if active:
            content = max(content, len(active) * self.ROW_H + max(0, len(active) - 1) * self.ROW_GAP)
        if closed:
            content += (4.0 if active else 0.0) + len(closed) * self.CLOSED_ROW_H
        if hidden > 0:
            content += (4.0 if (active or closed) else 0.0) + 18.0
        return 2 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + content

    def _body_total_height(self) -> float:
        h = self.HERO_H
        for acc in self._accounts:
            h += ps.GAP + self._account_card_height(acc)
        return h

    # ---------------------------------------------------------------- icons
    def _draw_gmail_icon(self, p: QPainter, rect: QRectF) -> None:
        if self._svg_renderer and self._svg_renderer.isValid():
            self._svg_renderer.render(p, rect)
            return

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sx = rect.width() / 24.0
        sy = rect.height() / 24.0
        p.translate(rect.left(), rect.top())
        p.scale(sx, sy)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4285F4"))
        path_blue = QPainterPath()
        path_blue.moveTo(2, 5)
        path_blue.lineTo(2, 19)
        path_blue.lineTo(6, 19)
        path_blue.lineTo(6, 10.5)
        path_blue.lineTo(12, 15)
        path_blue.lineTo(18, 10.5)
        path_blue.lineTo(18, 19)
        path_blue.lineTo(22, 19)
        path_blue.lineTo(22, 5)
        path_blue.lineTo(12, 12.5)
        path_blue.closeSubpath()
        p.drawPath(path_blue)

        p.setBrush(QColor("#EA4335"))
        p.drawRect(QRectF(20, 5, 2, 14))

        p.setBrush(QColor("#34A853"))
        path_green = QPainterPath()
        path_green.moveTo(2, 19)
        path_green.lineTo(6, 19)
        path_green.lineTo(6, 10.5)
        path_green.lineTo(2, 7.5)
        path_green.closeSubpath()
        p.drawPath(path_green)

        p.setBrush(QColor("#FBBC05"))
        path_amber = QPainterPath()
        path_amber.moveTo(12, 15)
        path_amber.lineTo(18, 10.5)
        path_amber.lineTo(18, 5)
        path_amber.lineTo(15.5, 5)
        path_amber.lineTo(12, 7.6)
        path_amber.lineTo(8.5, 5)
        path_amber.lineTo(6, 5)
        path_amber.lineTo(6, 10.5)
        path_amber.closeSubpath()
        p.drawPath(path_amber)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.restore()

    # ---------------------------------------------------------------- paint
    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))
        self._rects = {}

        chip = f"{self._total_open} bekliyor" if self._total_open > 0 else "Temiz"
        dot = ps.WARN if self._stale else (ps.OK if self._total_open == 0 else ps.ACCENT)
        hdr = ps.draw_header(
            p, QRectF(ps.PAD, ps.PAD, w - 2 * ps.PAD, ps.HEADER_H),
            "Yanıt bekleyen mailler", icon=self._draw_gmail_icon,
            chip=chip, chip_dot=dot, close_hover=self._close_hovered,
        )
        self._close_rect = QRectF(hdr["close"])
        self._rects["close"] = self._close_rect

        body_top, body_h, footer_top = self._chrome_rects()
        body_rect = QRectF(ps.PAD, body_top, w - 2 * ps.PAD, body_h)
        p.save()
        p.setClipRect(body_rect)
        self._row_rects = []

        y = body_top - self._scroll_y
        self._paint_hero(p, QRectF(ps.PAD, y, w - 2 * ps.PAD, self.HERO_H))
        y += self.HERO_H + ps.GAP

        for acc in self._accounts:
            card_h = self._account_card_height(acc)
            self._paint_account(p, QRectF(ps.PAD, y, w - 2 * ps.PAD, card_h), acc)
            y += card_h + ps.GAP

        p.restore()
        self._paint_scroll_indicator(p, body_top, body_h)
        self._paint_footer(p, footer_top)

    def _paint_hero(self, p: QPainter, rect: QRectF) -> None:
        inner = ps.draw_card(p, rect, "Yanıt bekleyen")
        if inner.height() <= 0:
            return

        p.setFont(ps.f_hero(30.0))
        p.setPen(ps.TEXT)
        p.drawText(QRectF(inner.left(), inner.top(), 46.0, 46.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   str(self._total_open))

        rx = inner.left() + 52.0
        rw = max(0.0, inner.right() - rx)

        p.setFont(ps.font(13.0, QFont.Weight.DemiBold))
        p.setPen(ps.TEXT)
        p.drawText(QRectF(rx, inner.top(), rw, 18.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "İlgi bekleyen e-posta")

        active_accs = [a for a in self._accounts if int(a.get("open") or 0) > 0]
        if self._total_open > 0:
            sub_text = (f"{len(active_accs)} farklı hesapta yanıt bekleniyor"
                        if len(active_accs) > 1 else "1 hesapta yanıt bekleniyor")
        else:
            sub_text = "Gelen kutusu temiz"

        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        p.drawText(QRectF(rx, inner.top() + 19.0, rw, 15.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub_text)

        bar_y = inner.top() + 39.0
        bar_rect = QRectF(rx, bar_y, rw, 6.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.TRACK)
        p.drawPath(rounded_path(bar_rect, 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._total_open > 0 and rw > 0:
            p.save()
            p.setClipPath(rounded_path(bar_rect, 3.0))
            seg_x = rx
            for a in self._accounts:
                open_cnt = int(a.get("open") or 0)
                if open_cnt <= 0:
                    continue
                seg_w = rw * (open_cnt / float(self._total_open))
                k = str(a.get("key") or "").lower()
                seg_col = ACCOUNT_SPLIT_COLORS.get(k, ps.ACCENT)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(seg_col)
                p.drawRect(QRectF(seg_x, bar_y, seg_w, 6.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                seg_x += seg_w
            p.restore()

        legend_y = inner.top() + 48.0
        p.setFont(ps.font(10.5, QFont.Weight.Medium))
        fm = QFontMetricsF(p.font())
        leg_x = rx
        if self._total_open > 0:
            for a in self._accounts:
                open_cnt = int(a.get("open") or 0)
                if open_cnt <= 0:
                    continue
                lbl = str(a.get("label") or "")
                k = str(a.get("key") or "").lower()
                dot_col = ACCOUNT_SPLIT_COLORS.get(k, ps.ACCENT)
                leg_str = f"{lbl}: {open_cnt}"
                tw = fm.horizontalAdvance(leg_str)
                if leg_x + tw + 18.0 > inner.right():
                    break
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot_col)
                p.drawEllipse(QRectF(leg_x, legend_y + 4.5, 6.0, 6.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(ps.TEXT_BODY)
                p.drawText(QRectF(leg_x + 9.0, legend_y, tw, 15.0),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, leg_str)
                leg_x += tw + 18.0
        else:
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(rx, legend_y, rw, 15.0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Tüm hesaplar güncel")

    def _paint_account(self, p: QPainter, rect: QRectF, acc: Dict[str, Any]) -> None:
        label = str(acc.get("label") or "").strip() or "—"
        active, closed, hidden = self._items_for_account(acc)
        open_count = len(active)

        inner = ps.draw_card(p, rect, f"{label} ({open_count})")
        if inner.height() <= 0:
            return

        if not active and not closed and hidden == 0:
            p.setFont(make_font(11.0, QFont.Weight.Normal, italic=True))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, "Bekleyen yanıt yok")
            return

        iy = inner.top()
        for idx, it in enumerate(active):
            row_rect = QRectF(inner.left(), iy, inner.width(), self.ROW_H)
            self._paint_active_row(p, row_rect, it)
            iy += self.ROW_H
            if idx < len(active) - 1:
                iy += self.ROW_GAP

        if closed:
            if active:
                iy += 4.0
                p.setPen(QPen(QColor(255, 255, 255, 12), 1.0))
                p.drawLine(QPointF(inner.left(), iy), QPointF(inner.right(), iy))
            for it in closed:
                closed_rect = QRectF(inner.left(), iy, inner.width(), self.CLOSED_ROW_H)
                self._row_rects.append((closed_rect, it))
                sender = str(it.get("kimden") or "")
                p.setFont(ps.f_small())
                p.setPen(QColor(255, 255, 255, 160))
                fm = QFontMetricsF(p.font())
                p.drawText(QRectF(inner.left() + 8.0, iy, inner.width() - 138.0, self.CLOSED_ROW_H),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           fm.elidedText(sender, Qt.TextElideMode.ElideRight,
                                         max(20.0, inner.width() - 138.0)))
                p.setFont(make_font(10.5, QFont.Weight.Normal, italic=True))
                p.setPen(ps.TEXT_MUTED)
                p.drawText(QRectF(inner.right() - 130.0, iy, 130.0, self.CLOSED_ROW_H),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                           "muhtemelen kapandı")
                iy += self.CLOSED_ROW_H

        if hidden > 0:
            iy += 4.0 if (active or closed) else 0.0
            p.setFont(make_font(10.5, QFont.Weight.Normal, italic=True))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(inner.left() + 8.0, iy, inner.width() - 8.0, 18.0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{hidden} otomatik bildirim gizlendi")

    def _paint_active_row(self, p: QPainter, row_rect: QRectF, it: Dict[str, Any]) -> None:
        url = str(it.get("url") or "")
        self._row_rects.append((row_rect, it))
        is_hovered = bool(url) and self._hover_item_url == url
        row_bg = ps.TILE_HOVER if is_hovered else QColor(255, 255, 255, 8)
        row_border = QColor(255, 255, 255, 15) if is_hovered else QColor(255, 255, 255, 10)
        p.setPen(QPen(row_border, 1.0))
        p.setBrush(row_bg)
        p.drawPath(rounded_path(row_rect, 8.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        wait_h = it.get("bekleme_saat")
        is_unread = bool(it.get("okunmamis", False))
        if is_unread:
            dot_col = ps.ACCENT
        elif wait_h is not None:
            try:
                dot_col = ps.WARN if float(wait_h) >= 72.0 else ps.OK
            except (TypeError, ValueError):
                dot_col = ps.OK
        else:
            dot_col = ps.OK

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_col)
        p.drawEllipse(QRectF(row_rect.left() + 8.0, row_rect.top() + 11.0, 6.0, 6.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        chip_text = work_sources.tr_relative_hours(wait_h) if work_sources else ""
        if not chip_text and wait_h is not None:
            chip_text = f"{wait_h} sa"
        p.setFont(ps.font(10.5, QFont.Weight.Medium))
        fm_chip = QFontMetricsF(p.font())
        chip_w = fm_chip.horizontalAdvance(chip_text) + 10.0 if chip_text else 0.0
        chip_rect = QRectF(row_rect.right() - 8.0 - chip_w, row_rect.top() + 4.0, chip_w, 15.0)
        if chip_text:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 15))
            p.drawPath(rounded_path(chip_rect, 4.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(ps.TEXT_MUTED)
            p.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, chip_text)

        sender = str(it.get("kimden") or "")
        p.setFont(ps.font(12.5, QFont.Weight.DemiBold))
        p.setPen(ps.TEXT)
        fm_sender = QFontMetricsF(p.font())
        sender_left = row_rect.left() + 21.0
        sender_max = max(20.0, (chip_rect.left() if chip_text else row_rect.right()) - sender_left - 6.0)
        p.drawText(QRectF(sender_left, row_rect.top() + 2.0, sender_max, 17.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm_sender.elidedText(sender, Qt.TextElideMode.ElideRight, sender_max))

        subject = str(it.get("konu") or "")
        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        fm_sub = QFontMetricsF(p.font())
        sub_max = max(20.0, row_rect.width() - 29.0)
        p.drawText(QRectF(sender_left, row_rect.top() + 19.0, sub_max, 16.0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm_sub.elidedText(subject, Qt.TextElideMode.ElideRight, sub_max))

    def _paint_footer(self, p: QPainter, footer_top: float) -> None:
        stamp = self._scanned_at_str or "—"
        btn = ps.draw_footer(
            p, QRectF(ps.PAD, footer_top, self.width() - 2 * ps.PAD, ps.FOOTER_H),
            f"Hermes taraması · {stamp}", "Yenile", button_hover=self._refresh_hovered,
        )
        self._refresh_rect = QRectF(btn) if btn is not None else QRectF()
        if not self._refresh_rect.isNull():
            self._rects["refresh"] = self._refresh_rect

    # --------------------------------------------------------------- events
    def _row_at_point(self, pos: QPointF) -> Optional[Dict[str, Any]]:
        for r, item in self._row_rects:
            if r.contains(pos):
                return item
        return None

    def mousePressEvent(self, event: Any) -> None:
        try:
            pos = event.position()
            if event.button() == Qt.MouseButton.LeftButton:
                if self._close_rect.contains(pos):
                    self.hide_animated()
                    event.accept()
                    return
                if self._refresh_rect.contains(pos):
                    self._refresh_pressed = True
                    self.update()
                    event.accept()
                    return
                hit_item = self._row_at_point(pos)
                if hit_item is not None:
                    url = hit_item.get("url")
                    if url:
                        try:
                            QDesktopServices.openUrl(QUrl(str(url)))
                        except Exception as exc:
                            _log_err("MailPanel.openUrl", exc)
                    self.hide_animated()
                    event.accept()
                    return
        except Exception as exc:
            _log_err("MailPanel.mousePressEvent", exc)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        super().mouseMoveEvent(event)
        try:
            hit_item = self._row_at_point(event.position())
            old_url = self._hover_item_url
            self._hover_item_url = hit_item.get("url") if hit_item else None
            if old_url != self._hover_item_url:
                self.update()
        except Exception as exc:
            _log_err("MailPanel.mouseMoveEvent", exc)


# ---------------------------------------------------------------------------
# 2) QuotaPanel: Antigravity model quotas
# ---------------------------------------------------------------------------
class QuotaPanel(_BasePopover):
    """Antigravity quota panel: one compact row per model group."""

    WIDTH: int = int(ps.WIDTH["ag"])

    LINE_H: float = 20.0
    BAR_GAP: float = 5.0
    BAR_H: float = 6.0
    ROW_GAP: float = 10.0
    ERROR_TEXT: str = "Antigravity okunamadı"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: Dict[str, Any] = {}
        self._groups: List[Dict[str, Any]] = []
        self._rows: List[Dict[str, Any]] = []
        self._sections: List[Dict[str, Any]] = []
        self._fetched_at_str: str = ""
        self._has_error: bool = False
        self._error_text: str = ""

        self.resize(self.WIDTH, self.compute_height())

    def set_data(self, d: Any) -> None:
        """Update panel with result from fetch_antigravity()."""
        try:
            if not isinstance(d, dict):
                d = {}
            self._data = d
            self._fetched_at_str = _stamp(d.get("fetched_at")) if d.get("fetched_at") else ""

            raw_groups = d.get("groups") if isinstance(d.get("groups"), list) else []
            groups: List[Dict[str, Any]] = []
            for g in raw_groups:
                if not isinstance(g, dict):
                    continue
                label = str(g.get("label") or "").strip() or "—"
                groups.append({
                    "label": label,
                    "used": _norm_used(g.get("used")),
                    "reset_at": g.get("reset_at"),
                    "reset_tr": g.get("reset_tr"),
                })
            self._groups = groups
            self._has_error = bool(d.get("err")) or not groups
            self._error_text = self.ERROR_TEXT if self._has_error else ""
            self._rows = self._build_rows()
            self._sections = self._build_sections()

            self._scroll_y = 0.0
            self.resize(self.WIDTH, self.compute_height())
            self.update()
        except Exception as exc:
            _log_err("QuotaPanel.set_data", exc)

    def _reset_display(self, g: Dict[str, Any]) -> str:
        raw = g.get("reset_at") if g.get("reset_at") else g.get("reset_tr")
        if not raw:
            return "—"
        if dock_cards is not None and hasattr(dock_cards, "format_reset_display"):
            return dock_cards.format_reset_display(raw)
        return str(raw)

    def _build_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for g in self._groups:
            used = g.get("used")
            raw_label = str(g.get("label") or "—")
            identity = quota_identity_color(raw_label)
            # v24 (Emre: tek uyarı): çubuk model renginde kalır, yalnız yüzde %90+ kırmızı; DOLU rozeti yok
            # (bardaki kota kartıyla aynı dil; eskiden rozet + kırmızı yüzde + kırmızı çubuk üç kez söylüyordu).
            warn = used is not None and used >= 90.0

            display_label = raw_label
            account = None
            if "argon" in raw_label.lower():
                account = None
                display_label = "Argon"
            elif " · " in raw_label:
                parts = raw_label.split(" · ", 1)
                account = parts[0].strip()
                display_label = parts[1].strip()

            rows.append({
                "label": raw_label,
                "display_label": display_label,
                "account": account,
                "used": used,
                "reset_text": self._reset_display(g),
                "identity": identity,
                "color": identity,
                "pct_text": ps.pct(used),
                "pct_color": ps.TEXT_LABEL if used is None else (ps.DANGER if warn else identity),
                "badge": None,
                "rect": QRectF(),
                "bar_rect": QRectF(),
            })
        return rows

    def _build_sections(self) -> List[Dict[str, Any]]:
        if self._has_error or not self._rows:
            return [{"overline": "Model kotaları", "rows": []}]

        account_rows: Dict[str, List[Dict[str, Any]]] = {}
        standalone_argon: Optional[Dict[str, Any]] = None
        for r in self._rows:
            acc = r.get("account")
            if acc:
                account_rows.setdefault(acc, []).append(r)
            elif "argon" in str(r.get("label", "")).lower():
                standalone_argon = r

        if not account_rows:
            return [{"overline": "Model kotaları", "rows": self._rows}]

        # Emre ve Büşra kartları: her iki karta da Argon ekle
        for acc, r_list in account_rows.items():
            has_argon = any("argon" in str(x.get("display_label", "")).lower() for x in r_list)
            if not has_argon:
                if "emre" in acc.lower() and standalone_argon:
                    emre_argon = dict(standalone_argon)
                    emre_argon["display_label"] = "Argon"
                    emre_argon["account"] = acc
                    r_list.append(emre_argon)
                else:
                    busra_argon = {
                        "label": f"{acc} · Argon",
                        "display_label": "Argon",
                        "account": acc,
                        "used": 0.0,
                        "reset_text": "—",
                        "identity": ps.ACCENT,
                        "color": ps.ACCENT,
                        "pct_text": "%0",
                        "pct_color": ps.ACCENT,
                        "badge": None,
                        "rect": QRectF(),
                        "bar_rect": QRectF(),
                    }
                    r_list.append(busra_argon)

        sections = []
        for acc, r_list in account_rows.items():
            sections.append({"overline": acc, "rows": r_list})
        return sections

    def _row_step(self) -> float:
        return self.LINE_H + self.BAR_GAP + self.BAR_H + self.ROW_GAP

    def _section_card_height(self, sec: Dict[str, Any]) -> float:
        rows = sec.get("rows") or []
        n = len(rows)
        if n == 0:
            return 2 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + 26.0
        content_h = n * (self.LINE_H + self.BAR_GAP + self.BAR_H) + max(0, n - 1) * self.ROW_GAP
        return 2 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + content_h

    def _content_height(self) -> float:
        if self._has_error or not self._rows:
            return 26.0
        n = len(self._rows)
        return n * (self.LINE_H + self.BAR_GAP + self.BAR_H) + max(0, n - 1) * self.ROW_GAP

    def _card_height(self) -> float:
        return self._body_total_height()

    def _body_total_height(self) -> float:
        if self._has_error or not self._rows:
            return 2 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + 26.0
        secs = getattr(self, "_sections", []) or [{"overline": "Model kotaları", "rows": self._rows}]
        total_h = sum(self._section_card_height(s) for s in secs)
        total_h += max(0, len(secs) - 1) * ps.CARD_GAP
        return total_h

    # ---------------------------------------------------------------- icons
    def _draw_ag_icon(self, p: QPainter, rect: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(110, 168, 254, 38))
        p.drawPath(rounded_path(rect, 6.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.setPen(QPen(ps.ACCENT, 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx = rect.center().x()
        cy = rect.center().y()
        p.drawLine(QPointF(cx - 5.0, cy + 5.0), QPointF(cx, cy - 5.0))
        p.drawLine(QPointF(cx, cy - 5.0), QPointF(cx + 5.0, cy + 5.0))
        p.drawLine(QPointF(cx - 3.0, cy + 1.0), QPointF(cx + 3.0, cy + 1.0))
        p.restore()

    # ---------------------------------------------------------------- paint
    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))
        self._rects = {}

        chip = "Okunamadı" if self._has_error else "Canlı kota"
        dot = ps.DANGER if self._has_error else None
        hdr = ps.draw_header(
            p, QRectF(ps.PAD, ps.PAD, w - 2 * ps.PAD, ps.HEADER_H),
            "Antigravity", icon=self._draw_ag_icon,
            chip=chip, chip_dot=dot, close_hover=self._close_hovered,
        )
        self._close_rect = QRectF(hdr["close"])
        self._rects["close"] = self._close_rect

        body_top, body_h, footer_top = self._chrome_rects()
        body_rect = QRectF(ps.PAD, body_top, w - 2 * ps.PAD, body_h)
        p.save()
        p.setClipRect(body_rect)

        y = body_top - self._scroll_y
        if self._has_error or not self._rows:
            card_h = 2 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + 26.0
            inner = ps.draw_card(p, QRectF(ps.PAD, y, w - 2 * ps.PAD, card_h),
                                 "Model kotaları")
            p.setFont(make_font(12.0, QFont.Weight.Normal, italic=True))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 26.0),
                       Qt.AlignmentFlag.AlignCenter, self.ERROR_TEXT)
        else:
            secs = getattr(self, "_sections", []) or [{"overline": "Model kotaları", "rows": self._rows}]
            for sec in secs:
                card_h = self._section_card_height(sec)
                inner = ps.draw_card(p, QRectF(ps.PAD, y, w - 2 * ps.PAD, card_h),
                                     overline=sec.get("overline"))
                ry = inner.top()
                for row in sec.get("rows") or []:
                    self._paint_row(p, row, QRectF(inner.left(), ry, inner.width(), self.LINE_H))
                    ry += self._row_step()
                y += card_h + ps.CARD_GAP

        p.restore()
        self._paint_scroll_indicator(p, body_top, body_h)
        self._paint_footer(p, footer_top)

    def _paint_row(self, p: QPainter, row: Dict[str, Any], line_rect: QRectF) -> None:
        used = row.get("used")
        color = row.get("color") or ps.TEXT_BODY
        identity = row.get("identity") or ps.TEXT_BODY

        f_pct = ps.font(13.5, QFont.Weight.Bold, tabular=True)
        fm_pct = QFontMetricsF(f_pct)
        pct_text = str(row.get("pct_text") or "—")
        pct_w = max(38.0, fm_pct.horizontalAdvance(pct_text) + 2.0)
        pct_rect = QRectF(line_rect.right() - pct_w, line_rect.top(), pct_w, line_rect.height())

        f_reset = ps.font(11.0)
        fm_reset = QFontMetricsF(f_reset)
        reset_text = str(row.get("reset_text") or "—")
        name_min = 80.0
        reset_max = max(0.0, (pct_rect.left() - 6.0) - (line_rect.left() + name_min))
        reset_disp = fm_reset.elidedText(reset_text, Qt.TextElideMode.ElideRight, reset_max)
        reset_w = fm_reset.horizontalAdvance(reset_disp) if reset_max > 0 else 0.0
        reset_rect = QRectF(pct_rect.left() - 6.0 - reset_w, line_rect.top(), reset_w, line_rect.height())

        badge = row.get("badge")
        badge_slot = 48.0 if badge else 0.0
        name_left = line_rect.left()
        name_max = max(20.0, (reset_rect.left() if reset_w > 0 else pct_rect.left()) - name_left - 8.0 - badge_slot)

        p.setFont(ps.font(13.0, QFont.Weight.DemiBold))
        p.setPen(identity)
        fm_name = QFontMetricsF(p.font())
        lbl_to_draw = str(row.get("display_label") or row.get("label") or "—")
        name_disp = fm_name.elidedText(lbl_to_draw, Qt.TextElideMode.ElideRight, name_max)
        p.drawText(QRectF(name_left, line_rect.top(), name_max, line_rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name_disp)

        if badge:
            bx = name_left + min(fm_name.horizontalAdvance(name_disp), name_max) + 6.0
            ps.draw_badge(p, QRectF(bx, line_rect.top(), 0.0, line_rect.height()), str(badge), "danger")

        p.setFont(f_reset)
        p.setPen(ps.TEXT_MUTED)
        if reset_w > 0:
            p.drawText(reset_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, reset_disp)

        p.setFont(f_pct)
        p.setPen(row.get("pct_color") or ps.TEXT_LABEL)
        p.drawText(pct_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, pct_text)

        bar_rect = QRectF(line_rect.left(), line_rect.bottom() + self.BAR_GAP,
                          line_rect.width(), self.BAR_H)
        ps.draw_thin_bar(p, bar_rect, used, color)
        row["rect"] = QRectF(line_rect)
        row["bar_rect"] = QRectF(bar_rect)

    def _paint_footer(self, p: QPainter, footer_top: float) -> None:
        stamp = self._fetched_at_str or "—"
        btn = ps.draw_footer(
            p, QRectF(ps.PAD, footer_top, self.width() - 2 * ps.PAD, ps.FOOTER_H),
            f"Antigravity · {stamp}", "Yenile", button_hover=self._refresh_hovered,
        )
        self._refresh_rect = QRectF(btn) if btn is not None else QRectF()
        if not self._refresh_rect.isNull():
            self._rects["refresh"] = self._refresh_rect
