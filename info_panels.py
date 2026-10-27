"""info_panels.py - Modern popover panels for Şerit dock (Direction C: 'Kart katmanlı').

Provides:
1) MailPanel: Waiting emails popover ('Yanıt bekleyen mailler') displaying:
   - Hero tile with big waiting count, 'İlgi bekleyen e-posta', account split bar (IAS, Kişisel, Logaritma), and legend.
   - Per-account card with waiting rows (sender bold, subject muted, duration chip e.g. '13 g', status dots).
   - Inactive probable closed items ('muhtemelen kapandı') listed at the bottom of the account tile in muted italic.
   - Concealed automated notifications counter ('N otomatik bildirim gizlendi').
   - Empty account state ('Bekleyen yanıt yok').
   - Pinned footer ('Hermes taraması · HH:MM' with 'eski' tag when stale) and interactive 'Yenile' button.
2) QuotaPanel: Antigravity AI quota popover ('Antigravity kotası') displaying:
   - One big elevated tile per model group with large tabular percentage (red #FF453A when >= 90 'DOLU', cyan #38BDF8 when 0 'KULLANILABİLİR').
   - Colored left accent strip (4px).
   - Reset time label ('Sıfırlanma süresi: …').
   - Thin 6px status bar (empty when 0, colored when active).
   - Pinned footer ('Antigravity Gateway · HH:MM') and interactive 'Yenile' button.

Fully opaque (acrylic disabled, set_round_region radius panel_style.R_PANEL),
clamped to screen with 8px margin, high-DPI crisp rendering, smooth wheel scrolling.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
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
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


def _ensure_system_fonts() -> None:
    """Ensure essential fonts are loaded even in headless/offscreen environments."""
    if QGuiApplication.instance() is None:
        return
    try:
        from PySide6.QtGui import QFontDatabase
        if not QFontDatabase.families():
            font_dir = Path("C:/Windows/Fonts")
            for fname in ("SegUIVar.ttf", "segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "arial.ttf"):
                fpath = font_dir / fname
                if fpath.is_file():
                    QFontDatabase.addApplicationFont(str(fpath))
    except Exception:
        pass

# Shared style tokens and helpers
serit_dir = str(Path(__file__).resolve().parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

import panel_style

try:
    import sources
    import winapi
    import work_sources
except ImportError:
    sources = None
    winapi = None
    work_sources = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available, never raising."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Visual Tokens (Referencing panel_style.py for Direction C)
# ---------------------------------------------------------------------------
RADIUS: float = panel_style.R_PANEL
R_TILE: float = panel_style.R_TILE
R_BUTTON: float = panel_style.R_BUTTON

COLOR_BG: QColor = panel_style.PANEL_BG
COLOR_BORDER: QColor = panel_style.PANEL_BORDER
COLOR_TILE_BG: QColor = panel_style.TILE_BG
COLOR_TILE_BORDER: QColor = panel_style.TILE_BORDER
COLOR_TILE_HOVER: QColor = panel_style.TILE_HOVER

COLOR_BUTTON_BG: QColor = panel_style.BUTTON_BG
COLOR_BUTTON_HOVER: QColor = panel_style.BUTTON_HOVER
COLOR_BUTTON_PRESS: QColor = QColor(255, 255, 255, 45)

COLOR_TEXT_PRIMARY: QColor = panel_style.TEXT
COLOR_TEXT_SECONDARY: QColor = panel_style.TEXT_BODY
COLOR_TEXT_MUTED: QColor = panel_style.TEXT_MUTED
COLOR_TEXT_LABEL: QColor = panel_style.TEXT_LABEL

COLOR_DANGER: QColor = panel_style.DANGER
COLOR_WARN: QColor = panel_style.WARN
COLOR_OK: QColor = panel_style.OK
COLOR_CYAN: QColor = QColor("#38BDF8")
COLOR_ACCENT: QColor = panel_style.ACCENT
COLOR_TRACK: QColor = panel_style.TRACK

COLOR_STALE_BG: QColor = QColor(255, 159, 10, 40)
COLOR_STALE_TXT: QColor = panel_style.WARN
COLOR_SCROLL_INDICATOR: QColor = QColor(255, 255, 255, 70)

# Semantic colors for email accounts
ACCOUNT_SPLIT_COLORS: Dict[str, QColor] = {
    "ias": QColor("#4285F4"),
    "kisisel02": QColor("#A855F7"),
    "kisisel": QColor("#A855F7"),
    "logaritma": QColor("#30D158"),
}

ACCOUNT_LABEL_COLORS: Dict[str, QColor] = {
    "ias": QColor("#64D2FF"),
    "kisisel02": QColor("#BF5AF2"),
    "kisisel": QColor("#BF5AF2"),
    "logaritma": QColor("#30D158"),
}


# ---------------------------------------------------------------------------
# Font & Drawing Compatibility Helpers
# ---------------------------------------------------------------------------
def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
    italic: bool = False,
) -> QFont:
    """Create a high-DPI font instance with Segoe UI Variable fallback."""
    f = panel_style.font(size_px, weight, tabular)
    f.setItalic(italic)
    if letter_spacing is not None:
        try:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        except Exception:
            pass
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    return panel_style.rounded(rect, radius)


def format_merged_labels(labels: List[str]) -> str:
    """Join labels into a unified string, eliding common prefix if identical.

    Example:
        ['Gemini Pro', 'Gemini Flash', 'Gemini Görsel'] -> 'Gemini Pro · Flash · Görsel'
        ['Claude', 'GPT-OSS'] -> 'Claude · GPT-OSS'
    """
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
    """Merge groups with identical (used, reset_tr) into one row with joined labels.

    Preserves order of appearance.
    """
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


# ---------------------------------------------------------------------------
# Base Popover Class (Shared Dock Flyout Architecture)
# ---------------------------------------------------------------------------
class _BasePopover(QWidget):
    """Abstract base popover window providing Direction C opaque canvas, positioning, animations."""

    WIDTH: int = 380
    RADIUS: float = panel_style.R_PANEL
    BODY_MAX_HEIGHT: float = 700.0

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

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        # Animation states
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Scrolling state
        self._scroll_y: float = 0.0

        # Interactive hit rects
        self._close_rect: QRectF = QRectF()
        self._refresh_rect: QRectF = QRectF()
        self._close_hovered: bool = False
        self._refresh_hovered: bool = False
        self._refresh_pressed: bool = False

        # Prebuilt typography
        self.f_title = panel_style.f_title()
        self.f_label = panel_style.f_label()
        self.f_body = panel_style.f_body()
        self.f_small = panel_style.f_small()

    # -----------------------------------------------------------------------
    # Public Common API
    # -----------------------------------------------------------------------
    def is_open(self) -> bool:
        """Return True if panel is visible and not in close transition."""
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        """Check if panel closed within threshold_ms to prevent toggle reopen bounce."""
        if self._last_close_time <= 0.0:
            return False
        elapsed_ms = (time.monotonic() - self._last_close_time) * 1000.0
        return elapsed_ms <= threshold_ms

    def set_data(self, d: Any) -> None:
        """Update panel data model."""
        raise NotImplementedError

    def compute_height(self) -> int:
        """Compute window height based on current data."""
        raise NotImplementedError

    def show_for(self, anchor_global: Optional[QRectF] = None, data: Any = None) -> None:
        """Position panel above anchor centered, clamped to availableGeometry."""
        try:
            if data is not None:
                self.set_data(data)

            if anchor_global is not None:
                try:
                    self._anchor_global = QRectF(anchor_global)
                except Exception:
                    self._anchor_global = None
            else:
                self._anchor_global = None

            h = self.compute_height()
            center_pt = self._anchor_global.center().toPoint() if self._anchor_global is not None else QCursor.pos()
            screen = QGuiApplication.screenAt(center_pt) or QGuiApplication.primaryScreen()
            if screen is not None:
                max_h = int(screen.availableGeometry().height() - 2 * panel_style.ANCHOR_GAP)
                h = min(h, max_h)
            self.resize(self.WIDTH, h)

            dpr = 1.0
            if self._anchor_global is not None:
                anchor_cx = self._anchor_global.center().x()
                target_x = int(round(anchor_cx - self.width() / 2.0))
                target_y = int(round(self._anchor_global.top() - self.height() - panel_style.ANCHOR_GAP))

                center_pt = self._anchor_global.center().toPoint()
                screen = QGuiApplication.screenAt(center_pt) or QGuiApplication.primaryScreen()

                if screen is not None:
                    geom = screen.availableGeometry()
                    dpr = screen.devicePixelRatio()
                    margin = 8
                    min_x = geom.left() + margin
                    max_x = geom.right() - self.width() - margin
                    if max_x >= min_x:
                        target_x = max(min_x, min(max_x, target_x))
                    else:
                        target_x = min_x

                    min_y = geom.top() + margin
                    max_y = geom.bottom() - self.height() - margin
                    if target_y < min_y:
                        below_y = int(round(self._anchor_global.bottom() + panel_style.ANCHOR_GAP))
                        if below_y + self.height() <= geom.bottom() - margin:
                            target_y = below_y
                        else:
                            target_y = min_y
                    elif target_y > max_y:
                        target_y = max_y

                self.move(target_x, target_y)

            # Apply physical rounded region; acrylic is explicitly disabled for opaque Direction C
            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(panel_style.R_PANEL), dpr)
                except Exception as exc:
                    _log_err("_BasePopover.winapi", exc)

            # Trigger open transition: fade 0->1, slide 8px in 180ms OutCubic
            self._is_closing = False
            self._anim.stop()
            self._anim.setDuration(180)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)

            self._anim_progress = 0.0
            self._anim_opacity = 0.0
            self._anim_offset_y = 8.0

            self.show()
            self.activateWindow()
            self._anim.start()
        except Exception as exc:
            _log_err("_BasePopover.show_for", exc)

    def hide_animated(self) -> None:
        """Trigger close transition: fade 1->0, slide 6px in 150ms InQuad, then hide."""
        try:
            if not self.isVisible() or self._is_closing:
                return

            self._is_closing = True
            self._last_close_time = time.monotonic()

            self._anim.stop()
            start_val = self._anim_progress
            duration = max(30, int(150 * start_val))

            self._anim.setDuration(duration)
            self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self._anim.setStartValue(start_val)
            self._anim.setEndValue(0.0)
            self._anim.start()
        except Exception as exc:
            _log_err("_BasePopover.hide_animated", exc)

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current popover offscreen to a high-DPI ARGB32 QImage."""
        try:
            w_phys = max(1, int(self.width() * dpr))
            h_phys = max(1, int(self.height() * dpr))
            img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(Qt.GlobalColor.transparent)

            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            self._paint_content(p)
            p.end()
            return img
        except Exception as exc:
            _log_err("_BasePopover.render_to_image", exc)
            return QImage()

    # -----------------------------------------------------------------------
    # Animation & Event Handlers
    # -----------------------------------------------------------------------
    def _on_anim_value_changed(self, value: Any) -> None:
        try:
            v = float(value)
            self._anim_progress = v
            self._anim_opacity = max(0.0, min(1.0, v))
            self._anim_offset_y = (1.0 - v) * 8.0
            self.update()
        except Exception:
            pass

    def _on_anim_finished(self) -> None:
        if self._is_closing:
            self.hide()
            self._is_closing = False
            self.update()

    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    def changeEvent(self, event: QEvent) -> None:
        try:
            if event.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                    cursor_pos = QCursor.pos()
                    if self._anchor_global is not None and self._anchor_global.contains(QPointF(cursor_pos)):
                        self._last_close_time = time.monotonic()
                        self._anchor_timer.start(300)
                        super().changeEvent(event)
                        return
                    self.hide_animated()
        except Exception as exc:
            _log_err("_BasePopover.changeEvent", exc)
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

    def paintEvent(self, event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._anim_opacity < 1.0 or abs(self._anim_offset_y) > 0.01:
            p.setOpacity(self._anim_opacity)
            p.translate(0.0, self._anim_offset_y)

        self._paint_content(p)

    def _paint_content(self, p: QPainter) -> None:
        """Subclasses implement full drawing logic."""
        raise NotImplementedError

    def _draw_refresh_button(self, p: QPainter, rect: QRectF) -> None:
        """Draw interactive 'Yenile' button with circular arrow icon."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._refresh_pressed:
            btn_bg = COLOR_BUTTON_PRESS
        elif self._refresh_hovered:
            btn_bg = COLOR_BUTTON_HOVER
        else:
            btn_bg = COLOR_BUTTON_BG

        # Background & border
        p.setPen(QPen(COLOR_TILE_BORDER, 1.0))
        p.setBrush(btn_bg)
        p.drawPath(rounded_path(rect, R_BUTTON))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Refresh Icon (circular arrow)
        icon_cx = rect.left() + 15.0
        icon_cy = rect.center().y()
        r = 4.5
        arc_rect = QRectF(icon_cx - r, icon_cy - r, r * 2.0, r * 2.0)
        pen_icon = QPen(COLOR_TEXT_PRIMARY, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen_icon)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, 45 * 16, 270 * 16)
        # Arrowhead
        arrow_tip_x = icon_cx + r * 0.707
        arrow_tip_y = icon_cy - r * 0.707
        p.drawLine(QPointF(arrow_tip_x, arrow_tip_y), QPointF(arrow_tip_x + 2.5, arrow_tip_y - 0.5))
        p.drawLine(QPointF(arrow_tip_x, arrow_tip_y), QPointF(arrow_tip_x + 0.5, arrow_tip_y + 2.5))

        # Text 'Yenile'
        p.setFont(panel_style.font(11.0, QFont.Weight.Medium))
        p.setPen(COLOR_TEXT_PRIMARY)
        text_rect = QRectF(rect.left() + 24.0, rect.top(), rect.width() - 26.0, rect.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Yenile")
        p.restore()

    def _draw_close_button(self, p: QPainter, rect: QRectF) -> None:
        """Draw top-right ✕ close button."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._close_hovered:
            p.fillPath(rounded_path(rect, 4.0), COLOR_BUTTON_HOVER)
        pen = QPen(COLOR_TEXT_MUTED, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        cy = rect.center().y()
        d = 4.0
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
        p.restore()


# ---------------------------------------------------------------------------
# 1) MailPanel: 'Yanıt bekleyen mailler'
# ---------------------------------------------------------------------------
class MailPanel(_BasePopover):
    """Direction C popover panel for emails awaiting reply ('Yanıt bekleyen mailler')."""

    WIDTH: int = 380
    ASSET_GMAIL: Path = Path(r"D:/Apps/serit/assets/gmail.svg")

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

        # SVG Renderer cache
        self._svg_renderer: Optional[QSvgRenderer] = None
        if self.ASSET_GMAIL.is_file():
            try:
                self._svg_renderer = QSvgRenderer(str(self.ASSET_GMAIL))
            except Exception as exc:
                _log_err("MailPanel.svg_load", exc)

        self.resize(self.WIDTH, 340)

    def set_data(self, d: Any) -> None:
        """Update panel with result from fetch_mail_waiting()."""
        try:
            if not isinstance(d, dict):
                d = {}
            self._data = d
            self._total_open = max(0, int(d.get("total_open") or 0))
            self._hidden_auto = max(0, int(d.get("hidden_auto") or 0))
            self._stale = bool(d.get("stale", False))

            # Format scanned_at timestamp
            raw_scan = d.get("scanned_at")
            if raw_scan:
                try:
                    s_clean = str(raw_scan).replace("Z", "+00:00")
                    dt_val = dt.datetime.fromisoformat(s_clean).astimezone()
                    self._scanned_at_str = dt_val.strftime("%H:%M")
                except Exception:
                    self._scanned_at_str = str(raw_scan)[:5]
            else:
                self._scanned_at_str = ""

            # Ensure sections in exact order: IAS, Kişisel, Logaritma
            account_order = [("ias", "IAS"), ("kisisel02", "Kişisel"), ("logaritma", "Logaritma")]
            raw_accounts = d.get("accounts") if isinstance(d.get("accounts"), list) else []
            acc_by_key = {}
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
        """Separate non-auto account items into (active_items, closed_items, hidden_auto_count)."""
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

    def _compute_body_total_height(self) -> float:
        """Compute virtual unconstrained height of hero card + account cards."""
        # 1. Hero tile height: 86px
        h = 86.0 + 10.0  # hero + gap

        # 2. Account cards
        for acc in self._accounts:
            active, closed, hidden = self._items_for_account(acc)
            if not active and not closed and hidden == 0:
                h += 36.0 + 10.0  # slim empty tile + gap
            else:
                card_h = 12.0 + 18.0 + 8.0  # top pad + header + gap
                if active:
                    card_h += len(active) * 38.0 + max(0, len(active) - 1) * 6.0
                if closed:
                    card_h += 6.0 + len(closed) * 20.0
                if hidden > 0:
                    card_h += 6.0 + 18.0
                card_h += 12.0  # bottom pad
                h += card_h + 10.0

        return max(40.0, h)

    def compute_height(self) -> int:
        """Compute dynamic window height with header, scrollable body, and footer."""
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        # Header (16 + 24 + 10) + body + footer (40)
        total = 50.0 + body_h + 40.0
        return int(math.ceil(total))

    def _draw_gmail_icon(self, p: QPainter, rect: QRectF) -> None:
        """Draw Gmail multi-color icon."""
        if self._svg_renderer and self._svg_renderer.isValid():
            self._svg_renderer.render(p, rect)
            return

        # Fallback vector Gmail path
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sx = rect.width() / 24.0
        sy = rect.height() / 24.0
        p.translate(rect.left(), rect.top())
        p.scale(sx, sy)

        p.setPen(Qt.PenStyle.NoPen)
        # Blue main body
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

        # Red strip
        p.setBrush(QColor("#EA4335"))
        p.drawRect(QRectF(20, 5, 2, 14))

        # Green strip
        p.setBrush(QColor("#34A853"))
        path_green = QPainterPath()
        path_green.moveTo(2, 19)
        path_green.lineTo(6, 19)
        path_green.lineTo(6, 10.5)
        path_green.lineTo(2, 7.5)
        path_green.closeSubpath()
        p.drawPath(path_green)

        # Amber chevron
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

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)

        # 1. Base Panel Shell (Fully opaque Direction C canvas)
        panel_style.draw_panel_shell(p, rect)

        # 2. Header
        header_y = 16.0
        icon_rect = QRectF(16.0, header_y + 2.0, 20.0, 20.0)
        self._draw_gmail_icon(p, icon_rect)

        # Title
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        title_rect = QRectF(44.0, header_y, 180.0, 24.0)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Yanıt bekleyen mailler")

        # Top-right ✕ close button
        close_x = w - 16.0 - 20.0
        self._close_rect = QRectF(close_x, header_y + 2.0, 20.0, 20.0)
        self._draw_close_button(p, self._close_rect)

        # Badge 'N bekliyor'
        badge_text = f"{self._total_open} bekliyor"
        p.setFont(self.f_small)
        fm_badge = QFontMetricsF(self.f_small)
        badge_w = fm_badge.horizontalAdvance(badge_text) + 14.0
        badge_rect = QRectF(close_x - badge_w - 8.0, header_y + 2.0, badge_w, 20.0)
        p.setPen(QPen(COLOR_TILE_BORDER, 1.0))
        p.setBrush(COLOR_BUTTON_BG)
        p.drawPath(rounded_path(badge_rect, 10.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(COLOR_TEXT_SECONDARY)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 3. Body
        body_top = header_y + 24.0 + 10.0
        body_h = h - body_top - 40.0
        body_rect = QRectF(16.0, body_top, w - 32.0, body_h)

        p.save()
        p.setClipRect(body_rect)
        self._row_rects.clear()

        cur_y = body_top - self._scroll_y
        card_w = w - 32.0

        # --- A. Hero Tile ('İlgi bekleyen e-posta') ---
        hero_h = 86.0
        hero_rect = QRectF(16.0, cur_y, card_w, hero_h)
        panel_style.draw_tile(p, hero_rect)

        # Hero Big Number Box (Left)
        num_box_rect = QRectF(16.0 + 13.0, cur_y + 15.0, 56.0, 56.0)
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawPath(rounded_path(num_box_rect, 10.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.setFont(panel_style.f_hero(32.0))
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(num_box_rect, Qt.AlignmentFlag.AlignCenter, str(self._total_open))

        # Hero Information & Split Bar (Right)
        right_x = 16.0 + 13.0 + 56.0 + 14.0
        right_w = card_w - (13.0 + 56.0 + 14.0 + 14.0)

        # Title
        p.setFont(panel_style.font(13.0, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(right_x, cur_y + 12.0, right_w, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "İlgi bekleyen e-posta")

        # Subtitle
        active_accs = [a for a in self._accounts if int(a.get("open") or 0) > 0]
        if self._total_open > 0:
            acc_cnt = len(active_accs)
            sub_text = f"{acc_cnt} farklı hesapta yanıt bekleniyor" if acc_cnt > 1 else "1 hesapta yanıt bekleniyor"
        else:
            sub_text = "Gelen kutusu temiz"

        p.setFont(self.f_small)
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(right_x, cur_y + 30.0, right_w, 15.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub_text)

        # Split Bar
        bar_y = cur_y + 49.0
        bar_rect = QRectF(right_x, bar_y, right_w, 8.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(COLOR_TRACK)
        p.drawPath(rounded_path(bar_rect, 4.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._total_open > 0:
            p.save()
            p.setClipPath(rounded_path(bar_rect, 4.0))
            seg_x = right_x
            for a in self._accounts:
                open_cnt = int(a.get("open") or 0)
                if open_cnt <= 0:
                    continue
                seg_w = right_w * (open_cnt / float(self._total_open))
                k = str(a.get("key") or "").lower()
                seg_col = ACCOUNT_SPLIT_COLORS.get(k, COLOR_ACCENT)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(seg_col)
                p.drawRect(QRectF(seg_x, bar_y, seg_w, 8.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                seg_x += seg_w
            p.restore()

        # Legend
        legend_y = cur_y + 62.0
        p.setFont(panel_style.font(10.5, QFont.Weight.Medium))
        leg_x = right_x
        if self._total_open > 0:
            for a in self._accounts:
                open_cnt = int(a.get("open") or 0)
                if open_cnt <= 0:
                    continue
                lbl = str(a.get("label") or "")
                k = str(a.get("key") or "").lower()
                dot_col = ACCOUNT_SPLIT_COLORS.get(k, COLOR_ACCENT)

                # Dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot_col)
                p.drawEllipse(QRectF(leg_x, legend_y + 4.5, 6.0, 6.0))
                p.setBrush(Qt.BrushStyle.NoBrush)

                # Text
                leg_str = f"{lbl}: {open_cnt}"
                fm_leg = QFontMetricsF(p.font())
                tw = fm_leg.horizontalAdvance(leg_str)
                p.setPen(COLOR_TEXT_SECONDARY)
                p.drawText(QRectF(leg_x + 9.0, legend_y, tw, 15.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, leg_str)
                leg_x += tw + 18.0
        else:
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(QRectF(right_x, legend_y, right_w, 15.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Tüm hesaplar güncel")

        cur_y += hero_h + 10.0

        # --- B. Per-Account Tiles ---
        for acc in self._accounts:
            k = str(acc.get("key") or "").lower()
            label = str(acc.get("label") or "").strip()
            active_items, closed_items, hidden_auto = self._items_for_account(acc)

            # Case 1: Empty Account
            if not active_items and not closed_items and hidden_auto == 0:
                empty_rect = QRectF(16.0, cur_y, card_w, 36.0)
                panel_style.draw_tile(p, empty_rect)

                # Left: Account • 0
                p.setFont(panel_style.font(11.0, QFont.Weight.DemiBold))
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(QRectF(16.0 + 14.0, cur_y, 140.0, 36.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{label} • 0")

                # Right: Bekleyen yanıt yok
                p.setFont(make_font(11.0, QFont.Weight.Normal, italic=True))
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(QRectF(w - 16.0 - 150.0, cur_y, 136.0, 36.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Bekleyen yanıt yok")

                cur_y += 36.0 + 10.0
                continue

            # Case 2: Populated Account Tile
            card_h = 12.0 + 18.0 + 8.0
            if active_items:
                card_h += len(active_items) * 38.0 + max(0, len(active_items) - 1) * 6.0
            if closed_items:
                card_h += 6.0 + len(closed_items) * 20.0
            if hidden_auto > 0:
                card_h += 6.0 + 18.0
            card_h += 12.0

            card_rect = QRectF(16.0, cur_y, card_w, card_h)
            panel_style.draw_tile(p, card_rect)

            # Section Header (e.g. IAS (3))
            header_col = ACCOUNT_LABEL_COLORS.get(k, COLOR_CYAN)
            p.setFont(self.f_label)
            p.setPen(header_col)
            open_count = len(active_items)
            p.drawText(QRectF(16.0 + 13.0, cur_y + 12.0, card_w - 26.0, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{label} ({open_count})")

            item_y = cur_y + 12.0 + 18.0 + 8.0
            inner_w = card_w - 26.0

            # Active Rows
            for it in active_items:
                url = str(it.get("url") or "")
                row_rect = QRectF(16.0 + 13.0, item_y, inner_w, 38.0)
                self._row_rects.append((row_rect, it))

                is_hovered = (self._hover_item_url == url and bool(url))
                row_bg = COLOR_TILE_HOVER if is_hovered else QColor(255, 255, 255, 8)
                row_border = QColor(255, 255, 255, 15) if is_hovered else QColor(255, 255, 255, 10)

                p.setPen(QPen(row_border, 1.0))
                p.setBrush(row_bg)
                p.drawPath(rounded_path(row_rect, 8.0))
                p.setBrush(Qt.BrushStyle.NoBrush)

                # Line 1: Dot + Sender + Duration Chip
                wait_h = it.get("bekleme_saat")
                is_unread = bool(it.get("okunmamis", False))

                # Status dot
                dot_y = item_y + 10.0
                if is_unread:
                    dot_col = COLOR_ACCENT
                elif wait_h is not None and float(wait_h) >= 72.0:
                    dot_col = COLOR_WARN
                else:
                    dot_col = COLOR_OK

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot_col)
                p.drawEllipse(QRectF(16.0 + 21.0, dot_y, 6.0, 6.0))
                p.setBrush(Qt.BrushStyle.NoBrush)

                # Duration chip on the right
                chip_text = work_sources.tr_relative_hours(wait_h) if work_sources else f"{wait_h} sa"
                p.setFont(panel_style.font(10.5, QFont.Weight.Medium))
                fm_chip = QFontMetricsF(p.font())
                chip_tw = fm_chip.horizontalAdvance(chip_text)
                chip_w = chip_tw + 10.0
                chip_rect = QRectF(16.0 + 13.0 + inner_w - chip_w - 8.0, item_y + 4.0, chip_w, 15.0)

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 15))
                p.drawPath(rounded_path(chip_rect, 4.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, chip_text)

                # Sender name
                sender_name = str(it.get("kimden") or "")
                p.setFont(panel_style.font(12.0, QFont.Weight.DemiBold))
                p.setPen(COLOR_TEXT_PRIMARY)
                fm_sender = QFontMetricsF(p.font())
                max_sender_w = (chip_rect.left() - (16.0 + 33.0)) - 6.0
                elided_sender = fm_sender.elidedText(sender_name, Qt.TextElideMode.ElideRight, max(20.0, max_sender_w))
                p.drawText(QRectF(16.0 + 33.0, item_y + 3.0, max(20.0, max_sender_w), 16.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_sender)

                # Line 2: Subject line
                subject = str(it.get("konu") or "")
                p.setFont(self.f_small)
                p.setPen(COLOR_TEXT_MUTED)
                fm_sub = QFontMetricsF(self.f_small)
                sub_max_w = inner_w - 24.0
                elided_sub = fm_sub.elidedText(subject, Qt.TextElideMode.ElideRight, sub_max_w)
                p.drawText(QRectF(16.0 + 33.0, item_y + 19.0, sub_max_w, 15.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_sub)

                item_y += 38.0 + 6.0

            # Inactive probable closed items ('muhtemelen kapandı')
            if closed_items:
                item_y += 3.0
                p.setPen(QPen(QColor(255, 255, 255, 12), 1.0))
                p.drawLine(QPointF(16.0 + 13.0, item_y), QPointF(16.0 + 13.0 + inner_w, item_y))
                item_y += 5.0
                for it in closed_items:
                    url = str(it.get("url") or "")
                    closed_rect = QRectF(16.0 + 13.0, item_y, inner_w, 20.0)
                    self._row_rects.append((closed_rect, it))

                    sender_name = str(it.get("kimden") or "")
                    p.setFont(self.f_small)
                    p.setPen(QColor(255, 255, 255, 160))
                    p.drawText(QRectF(16.0 + 21.0, item_y, inner_w - 140.0, 20.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sender_name)

                    p.setFont(make_font(10.5, QFont.Weight.Normal, italic=True))
                    p.setPen(COLOR_TEXT_MUTED)
                    p.drawText(QRectF(16.0 + 13.0 + inner_w - 130.0, item_y, 122.0, 20.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "muhtemelen kapandı")

                    item_y += 20.0

            # Concealed automated notifications note
            if hidden_auto > 0:
                item_y += 2.0
                p.setFont(make_font(10.5, QFont.Weight.Normal, italic=True))
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(QRectF(16.0 + 21.0, item_y, inner_w - 16.0, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{hidden_auto} otomatik bildirim gizlendi")
                item_y += 18.0

            cur_y += card_h + 10.0

        p.restore()

        # Thin scroll indicator if content overflows
        total_list_h = self._compute_body_total_height()
        if total_list_h > body_h and self._scroll_y > 0.5:
            max_scroll = total_list_h - body_h
            thumb_h = max(24.0, body_h * (body_h / total_list_h))
            thumb_y = body_top + (self._scroll_y / max_scroll) * (body_h - thumb_h)
            thumb_rect = QRectF(w - 7.0, thumb_y, 3.0, thumb_h)
            p.fillPath(rounded_path(thumb_rect, 1.5), COLOR_SCROLL_INDICATOR)

        # 4. Pinned Footer
        footer_top = h - 40.0
        p.setPen(QPen(COLOR_BORDER, 1.0))
        p.drawLine(QPointF(16.0, footer_top), QPointF(w - 16.0, footer_top))

        footer_y = footer_top + 9.0
        scan_time = self._scanned_at_str or "—"
        left_text = f"Hermes taraması · {scan_time}"
        p.setFont(self.f_small)
        p.setPen(COLOR_TEXT_MUTED)
        fm_footer = QFontMetricsF(self.f_small)
        txt_w = fm_footer.horizontalAdvance(left_text)
        p.drawText(QRectF(16.0, footer_y, txt_w, 22.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, left_text)

        if self._stale:
            stale_rect = QRectF(16.0 + txt_w + 6.0, footer_y + 3.0, 32.0, 16.0)
            p.fillPath(rounded_path(stale_rect, 4.0), COLOR_STALE_BG)
            p.setFont(panel_style.font(9.5, QFont.Weight.DemiBold))
            p.setPen(COLOR_STALE_TXT)
            p.drawText(stale_rect, Qt.AlignmentFlag.AlignCenter, "eski")

        btn_w = 68.0
        btn_h = 24.0
        self._refresh_rect = QRectF(w - 16.0 - btn_w, footer_y - 1.0, btn_w, btn_h)
        self._draw_refresh_button(p, self._refresh_rect)

    # -----------------------------------------------------------------------
    # Mouse & Hit Testing
    # -----------------------------------------------------------------------
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
                            QDesktopServices.openUrl(QUrl(url))
                        except Exception as u_exc:
                            _log_err("MailPanel.openUrl", u_exc)
                    self.hide_animated()
                    event.accept()
                    return
        except Exception as exc:
            _log_err("MailPanel.mousePressEvent", exc)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        try:
            if event.button() == Qt.MouseButton.LeftButton and self._refresh_pressed:
                self._refresh_pressed = False
                if self._refresh_rect.contains(event.position()):
                    self.refresh_requested.emit()
                self.update()
                event.accept()
                return
        except Exception as exc:
            _log_err("MailPanel.mouseReleaseEvent", exc)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        try:
            pos = event.position()
            self._close_hovered = self._close_rect.contains(pos)
            self._refresh_hovered = self._refresh_rect.contains(pos)

            hit_item = self._row_at_point(pos)
            old_url = self._hover_item_url
            self._hover_item_url = hit_item.get("url") if hit_item else None
            if old_url != self._hover_item_url:
                self.update()
        except Exception as exc:
            _log_err("MailPanel.mouseMoveEvent", exc)
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: Any) -> None:
        try:
            delta = event.angleDelta().y()
            body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
            total_h = self._compute_body_total_height()
            max_scroll = max(0.0, total_h - body_h)

            if max_scroll > 0.0:
                step = (delta / 120.0) * 40.0
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self.update()
        except Exception as exc:
            _log_err("MailPanel.wheelEvent", exc)
        super().wheelEvent(event)


# ---------------------------------------------------------------------------
# 2) QuotaPanel: 'Antigravity kotası'
# ---------------------------------------------------------------------------
class QuotaPanel(_BasePopover):
    """Direction C popover panel for Antigravity model quota usage."""

    WIDTH: int = 380
    ASSET_ANTIGRAVITY: Path = Path(r"D:/Apps/serit/assets/antigravity.png")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: Dict[str, Any] = {}
        self._groups: List[Dict[str, Any]] = []
        self._fetched_at_str: str = ""
        self._has_error: bool = False

        self._png_pixmap: Optional[QPixmap] = None
        if self.ASSET_ANTIGRAVITY.is_file():
            try:
                self._png_pixmap = QPixmap(str(self.ASSET_ANTIGRAVITY))
            except Exception as exc:
                _log_err("QuotaPanel.png_load", exc)

        self.resize(self.WIDTH, 260)

    def set_data(self, d: Any) -> None:
        """Update panel with result from fetch_antigravity()."""
        try:
            if not isinstance(d, dict):
                d = {}
            self._data = d
            self._has_error = bool(d.get("err")) or not bool(d.get("groups"))

            # Format fetched_at
            raw_fetched = d.get("fetched_at")
            if raw_fetched:
                try:
                    f_clean = str(raw_fetched).replace("Z", "+00:00")
                    dt_val = dt.datetime.fromisoformat(f_clean).astimezone()
                    self._fetched_at_str = dt_val.strftime("%H:%M")
                except Exception:
                    self._fetched_at_str = str(raw_fetched)[:5]
            else:
                self._fetched_at_str = ""

            raw_groups = d.get("groups") if isinstance(d.get("groups"), list) else []
            self._groups = merge_quota_groups(raw_groups)
            if not self._groups and not self._has_error:
                self._has_error = True

            self._scroll_y = 0.0
            self.resize(self.WIDTH, self.compute_height())
            self.update()
        except Exception as exc:
            _log_err("QuotaPanel.set_data", exc)

    def _compute_body_total_height(self) -> float:
        """Compute unconstrained height of quota rows."""
        if self._has_error or not self._groups:
            return 44.0

        # Each big model group tile is 78px + 10px gap
        return len(self._groups) * 88.0

    def compute_height(self) -> int:
        """Compute dynamic window height."""
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        total = 50.0 + body_h + 40.0
        return int(math.ceil(total))

    def _draw_ag_icon(self, p: QPainter, rect: QRectF) -> None:
        """Draw official Antigravity geometric logo."""
        if self._png_pixmap and not self._png_pixmap.isNull():
            p.drawPixmap(rect, self._png_pixmap, QRectF(self._png_pixmap.rect()))
            return

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1E2026"))
        p.drawPath(rounded_path(rect, 5.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        pen = QPen(COLOR_CYAN, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        # Draw chevron / A path
        cx = rect.center().x()
        cy = rect.center().y()
        p.drawLine(QPointF(cx - 5.0, cy + 5.0), QPointF(cx, cy - 5.0))
        p.drawLine(QPointF(cx, cy - 5.0), QPointF(cx + 5.0, cy + 5.0))
        p.drawLine(QPointF(cx - 3.0, cy + 1.0), QPointF(cx + 3.0, cy + 1.0))
        p.restore()

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)

        # 1. Base Panel Shell (Fully opaque Direction C canvas)
        panel_style.draw_panel_shell(p, rect)

        # 2. Header
        header_y = 16.0
        icon_rect = QRectF(16.0, header_y + 2.0, 20.0, 20.0)
        self._draw_ag_icon(p, icon_rect)

        # Title
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        title_rect = QRectF(44.0, header_y, 160.0, 24.0)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Antigravity kotası")

        # Top-right ✕ close button
        close_x = w - 16.0 - 20.0
        self._close_rect = QRectF(close_x, header_y + 2.0, 20.0, 20.0)
        self._draw_close_button(p, self._close_rect)

        # Badge 'Canlı kota' with live green dot
        badge_text = "Canlı kota"
        p.setFont(panel_style.font(10.5, QFont.Weight.Medium))
        fm_badge = QFontMetricsF(p.font())
        badge_text_w = fm_badge.horizontalAdvance(badge_text)
        badge_w = badge_text_w + 24.0
        badge_rect = QRectF(close_x - badge_w - 8.0, header_y + 2.0, badge_w, 20.0)
        p.setPen(QPen(COLOR_TILE_BORDER, 1.0))
        p.setBrush(COLOR_BUTTON_BG)
        p.drawPath(rounded_path(badge_rect, 10.0))
        p.setBrush(Qt.BrushStyle.NoBrush)

        dot_cx = badge_rect.left() + 9.0
        dot_cy = badge_rect.center().y()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(COLOR_OK)
        p.drawEllipse(QPointF(dot_cx, dot_cy), 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.setPen(COLOR_TEXT_SECONDARY)
        p.drawText(QRectF(badge_rect.left() + 15.0, badge_rect.top(), badge_text_w + 4.0, 20.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, badge_text)

        # 3. Body
        body_top = header_y + 24.0 + 10.0
        body_h = h - body_top - 40.0
        body_rect = QRectF(16.0, body_top, w - 32.0, body_h)

        p.save()
        p.setClipRect(body_rect)

        cur_y = body_top - self._scroll_y
        card_w = w - 32.0

        if self._has_error or not self._groups:
            p.setFont(make_font(12.0, QFont.Weight.Normal, italic=True))
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(QRectF(16.0, cur_y + 10.0, card_w, 24.0), Qt.AlignmentFlag.AlignCenter, "Antigravity okunamadı")
        else:
            for g in self._groups:
                card_h = 78.0
                card_rect = QRectF(16.0, cur_y, card_w, card_h)

                # Card Background & Border
                panel_style.draw_tile(p, card_rect)

                used = float(g.get("used", 0.0))
                lbl = str(g.get("label") or "")
                reset_tr = g.get("reset_tr")

                # Left Colored Accent Strip (4px wide, clipped to rounded left corners)
                if used >= 90.0:
                    accent_col = COLOR_DANGER
                elif used <= 0.0:
                    accent_col = COLOR_CYAN
                else:
                    accent_col = COLOR_WARN

                p.save()
                p.setClipPath(rounded_path(card_rect, R_TILE))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent_col)
                p.drawRect(QRectF(card_rect.left(), card_rect.top(), 4.0, card_rect.height()))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.restore()

                # Content layout inside card
                inner_left = card_rect.left() + 16.0
                inner_right = card_rect.right() - 14.0

                # Top Right: Big Percentage & Status Badge
                pct_str = f"%{int(round(used))}"
                p.setFont(panel_style.f_hero(26.0))
                fm_pct = QFontMetricsF(p.font())
                pct_w = fm_pct.horizontalAdvance(pct_str)
                pct_rect = QRectF(inner_right - pct_w, cur_y + 10.0, pct_w, 26.0)

                p.setPen(accent_col)
                p.drawText(pct_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct_str)

                # Status Badge below percentage
                if used >= 90.0:
                    tag_text = "DOLU"
                    tag_col = COLOR_DANGER
                    tag_bg = QColor(255, 69, 58, 30)
                    f_tag = panel_style.font(10.0, QFont.Weight.Bold)
                    pad_h = 10.0
                elif used <= 0.0:
                    tag_text = "KULLANILABİLİR"
                    tag_col = COLOR_CYAN
                    tag_bg = QColor(56, 189, 248, 30)
                    f_tag = panel_style.font(9.0, QFont.Weight.Bold)
                    pad_h = 8.0
                else:
                    tag_text = "AKTİF"
                    tag_col = COLOR_WARN
                    tag_bg = QColor(255, 159, 10, 30)
                    f_tag = panel_style.font(10.0, QFont.Weight.Bold)
                    pad_h = 10.0

                p.setFont(f_tag)
                fm_tag = QFontMetricsF(f_tag)
                tag_tw = fm_tag.horizontalAdvance(tag_text)
                tag_w = tag_tw + pad_h
                tag_rect = QRectF(inner_right - tag_w, cur_y + 38.0, tag_w, 16.0)

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(tag_bg)
                p.drawPath(rounded_path(tag_rect, 4.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(tag_col)
                p.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)

                # Top Left: Model Label & Reset Time
                avail_title_w = (min(pct_rect.left(), tag_rect.left()) - inner_left) - 10.0

                p.setFont(panel_style.font(13.5, QFont.Weight.DemiBold))
                p.setPen(COLOR_TEXT_PRIMARY)
                fm_lbl = QFontMetricsF(p.font())
                elided_lbl = fm_lbl.elidedText(lbl, Qt.TextElideMode.ElideRight, max(20.0, avail_title_w))
                p.drawText(QRectF(inner_left, cur_y + 12.0, max(20.0, avail_title_w), 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_lbl)

                # Reset subline
                sub_text = f"Sıfırlanma süresi: {reset_tr}" if reset_tr else "Sıfırlanma süresi: —"
                p.setFont(self.f_small)
                p.setPen(COLOR_TEXT_MUTED)
                fm_sub = QFontMetricsF(self.f_small)
                elided_sub = fm_sub.elidedText(sub_text, Qt.TextElideMode.ElideRight, max(20.0, avail_title_w))
                p.drawText(QRectF(inner_left, cur_y + 32.0, max(20.0, avail_title_w), 16.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_sub)

                # Bottom Row: Thin 6px Progress Bar
                bar_y = cur_y + 60.0
                bar_w = card_w - 30.0
                bar_rect = QRectF(inner_left, bar_y, bar_w, 6.0)

                p.setPen(QPen(QColor(255, 255, 255, 10), 1.0))
                p.setBrush(COLOR_TRACK)
                p.drawPath(rounded_path(bar_rect, 3.0))
                p.setBrush(Qt.BrushStyle.NoBrush)

                if used > 0.0:
                    p.save()
                    p.setClipPath(rounded_path(bar_rect, 3.0))
                    fill_w = max(0.0, min(bar_w, bar_w * (used / 100.0)))
                    p.setPen(Qt.PenStyle.NoPen)
                    if used >= 90.0:
                        from PySide6.QtGui import QLinearGradient
                        grad = QLinearGradient(inner_left, bar_y, inner_left + fill_w, bar_y)
                        grad.setColorAt(0.0, QColor("#F59E0B"))
                        grad.setColorAt(1.0, COLOR_DANGER)
                        p.setBrush(grad)
                    else:
                        p.setBrush(accent_col)
                    p.drawRect(QRectF(inner_left, bar_y, fill_w, 6.0))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.restore()

                cur_y += card_h + 10.0

        p.restore()

        # Thin scroll indicator
        total_list_h = self._compute_body_total_height()
        if total_list_h > body_h and self._scroll_y > 0.5:
            max_scroll = total_list_h - body_h
            thumb_h = max(24.0, body_h * (body_h / total_list_h))
            thumb_y = body_top + (self._scroll_y / max_scroll) * (body_h - thumb_h)
            thumb_rect = QRectF(w - 7.0, thumb_y, 3.0, thumb_h)
            p.fillPath(rounded_path(thumb_rect, 1.5), COLOR_SCROLL_INDICATOR)

        # 4. Pinned Footer
        footer_top = h - 40.0
        p.setPen(QPen(COLOR_BORDER, 1.0))
        p.drawLine(QPointF(16.0, footer_top), QPointF(w - 16.0, footer_top))

        footer_y = footer_top + 9.0
        fetch_time = self._fetched_at_str or "—"
        left_text = f"Antigravity Gateway · {fetch_time}"
        p.setFont(self.f_small)
        p.setPen(COLOR_TEXT_MUTED)
        fm_footer = QFontMetricsF(self.f_small)
        txt_w = fm_footer.horizontalAdvance(left_text)
        p.drawText(QRectF(16.0, footer_y, txt_w, 22.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, left_text)

        btn_w = 68.0
        btn_h = 24.0
        self._refresh_rect = QRectF(w - 16.0 - btn_w, footer_y - 1.0, btn_w, btn_h)
        self._draw_refresh_button(p, self._refresh_rect)

    # -----------------------------------------------------------------------
    # Mouse & Hit Testing
    # -----------------------------------------------------------------------
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
        except Exception as exc:
            _log_err("QuotaPanel.mousePressEvent", exc)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        try:
            if event.button() == Qt.MouseButton.LeftButton and self._refresh_pressed:
                self._refresh_pressed = False
                if self._refresh_rect.contains(event.position()):
                    self.refresh_requested.emit()
                self.update()
                event.accept()
                return
        except Exception as exc:
            _log_err("QuotaPanel.mouseReleaseEvent", exc)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        try:
            pos = event.position()
            self._close_hovered = self._close_rect.contains(pos)
            self._refresh_hovered = self._refresh_rect.contains(pos)
            self.update()
        except Exception as exc:
            _log_err("QuotaPanel.mouseMoveEvent", exc)
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: Any) -> None:
        try:
            delta = event.angleDelta().y()
            body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
            total_h = self._compute_body_total_height()
            max_scroll = max(0.0, total_h - body_h)

            if max_scroll > 0.0:
                step = (delta / 120.0) * 40.0
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self.update()
        except Exception as exc:
            _log_err("QuotaPanel.wheelEvent", exc)
        super().wheelEvent(event)
