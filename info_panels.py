"""info_panels.py - Modern obsidian popover panels for Şerit dock.

Provides:
1) MailPanel: Waiting emails popover ('Yanıt bekleyen mailler') displaying accounts
   (IAS, Kişisel, Logaritma) with unread blue dots, elapsed waiting chips, dimmed
   probable closed states, automated notification concealment counters, and row URL activation.
2) QuotaPanel: Antigravity AI quota popover ('Antigravity kotası') displaying merged
   model quota rows with 5px colored utilization bars and renewal time tags.

Conforms strictly to the Şerit popover family design system (Obsidian acrylic glass,
fluent animations, high-DPI crisp rendering, smooth wheel scrolling, robust bad-data handling).
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

# Safe imports from serit package
try:
    import sources
    import winapi
    import work_sources
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    try:
        import sources
        import winapi
        import work_sources
    except Exception:
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
# Visual Styling Tokens (Obsidian Acrylic Glass & Lumabar Palette)
# ---------------------------------------------------------------------------
RADIUS: float = 16.0

COLOR_BG: QColor = QColor(20, 21, 25, 248)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(225, 228, 235, 240)
COLOR_TEXT_MUTED: QColor = QColor(148, 154, 166, 220)
COLOR_TEXT_DIM: QColor = QColor(156, 163, 175, 235)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 20)

# Mail panel semantic colors
COLOR_UNREAD_DOT: QColor = QColor("#0A84FF")
COLOR_WAIT_CHIP_BG: QColor = QColor(255, 255, 255, 20)
COLOR_WAIT_CHIP_TXT: QColor = QColor(160, 166, 178, 240)
COLOR_ROW_BG: QColor = QColor(255, 255, 255, 8)
COLOR_ROW_BORDER: QColor = QColor(255, 255, 255, 13)
COLOR_ROW_HOVER: QColor = QColor(255, 255, 255, 18)
COLOR_ROW_DIMMED_BG: QColor = QColor(255, 255, 255, 4)
COLOR_ROW_DIMMED_BORDER: QColor = QColor(255, 255, 255, 8)

# Quota panel progress bar colors
COLOR_BAR_GREEN: QColor = QColor("#34C759")
COLOR_BAR_AMBER: QColor = QColor("#FF9F0A")
COLOR_BAR_RED: QColor = QColor("#FF453A")
COLOR_BAR_TRACK: QColor = QColor(255, 255, 255, 33)  # rgba(255,255,255, 0.13)

# Badges and buttons
COLOR_BADGE_BG: QColor = QColor(255, 255, 255, 20)
COLOR_BADGE_TXT: QColor = QColor(160, 166, 178, 230)
COLOR_STALE_BG: QColor = QColor(255, 159, 10, 40)
COLOR_STALE_TXT: QColor = QColor("#FF9F0A")

COLOR_REFRESH_BG: QColor = QColor(255, 255, 255, 22)
COLOR_REFRESH_BG_HOVER: QColor = QColor(255, 255, 255, 38)
COLOR_REFRESH_BG_PRESS: QColor = QColor(255, 255, 255, 55)
COLOR_REFRESH_BORDER: QColor = QColor(255, 255, 255, 24)
COLOR_REFRESH_TXT: QColor = QColor(255, 255, 255, 245)

COLOR_CLOSE_HOVER_BG: QColor = QColor(255, 255, 255, 24)
COLOR_SCROLL_INDICATOR: QColor = QColor(255, 255, 255, 70)


def _ensure_system_fonts() -> None:
    """Ensure essential fonts are loaded even in headless/offscreen environments."""
    try:
        from PySide6.QtGui import QFontDatabase
        if not QFontDatabase.families():
            font_dir = Path("C:/Windows/Fonts")
            for fname in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf"):
                fpath = font_dir / fname
                if fpath.is_file():
                    QFontDatabase.addApplicationFont(str(fpath))
    except Exception:
        pass


def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
    italic: bool = False,
) -> QFont:
    """Create a high-DPI Segoe UI Variable font instance."""
    _ensure_system_fonts()
    f = QFont("Segoe UI")
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial", "sans-serif"])
    f.setPixelSize(int(round(size_px)))
    f.setWeight(weight)
    f.setItalic(italic)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag.fromString("tnum"), 1)
        except Exception:
            pass
    if letter_spacing is not None:
        try:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        except Exception:
            pass
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


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

    # Check if all share a common first-word prefix
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
    """Abstract base popover window providing acrylic glass, positioning, animations."""

    WIDTH: int = 340
    RADIUS: float = RADIUS
    BODY_MAX_HEIGHT: float = 380.0

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

        # Fonts
        self.f_title = make_font(13.0, QFont.Weight.DemiBold)
        self.f_badge = make_font(10.0, QFont.Weight.Medium)
        self.f_sec_title = make_font(10.5, QFont.Weight.Bold, letter_spacing=0.6)
        self.f_row_name = make_font(12.0, QFont.Weight.DemiBold)
        self.f_row_sub = make_font(11.0, QFont.Weight.Normal)
        self.f_tag = make_font(9.5, QFont.Weight.DemiBold)
        self.f_tag_italic = make_font(9.5, QFont.Weight.Normal, italic=True)
        self.f_footer = make_font(10.5, QFont.Weight.Normal)
        self.f_btn = make_font(11.0, QFont.Weight.Medium)
        self.f_empty = make_font(11.0, QFont.Weight.Normal, italic=True)
        self.f_val_tabular = make_font(11.0, QFont.Weight.Bold, tabular=True)

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

    def show_for(self, anchor_global: Optional[QRectF]) -> None:
        """Position panel above anchor centered, clamped to availableGeometry."""
        try:
            if anchor_global is not None:
                try:
                    self._anchor_global = QRectF(anchor_global)
                except Exception:
                    self._anchor_global = None
            else:
                self._anchor_global = None

            h = self.compute_height()
            self.resize(self.WIDTH, h)

            dpr = 1.0
            if self._anchor_global is not None:
                anchor_cx = self._anchor_global.center().x()
                target_x = int(round(anchor_cx - self.width() / 2.0))
                target_y = int(round(self._anchor_global.top() - self.height() - 8))

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
                        below_y = int(round(self._anchor_global.bottom() + 8))
                        if below_y + self.height() <= geom.bottom() - margin:
                            target_y = below_y
                        else:
                            target_y = min_y
                    elif target_y > max_y:
                        target_y = max_y

                self.move(target_x, target_y)

            # Apply Windows acrylic composition & physical rounded region
            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "enable_acrylic"):
                try:
                    winapi.enable_acrylic(hwnd, 0x50181612)
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(self.RADIUS), dpr)
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

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def leaveEvent(self, event) -> None:
        self._close_hovered = False
        self._refresh_hovered = False
        self._refresh_pressed = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
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


# ---------------------------------------------------------------------------
# 1) MailPanel: 'Yanıt bekleyen mailler'
# ---------------------------------------------------------------------------
class MailPanel(_BasePopover):
    """Obsidian popover panel for emails awaiting reply."""

    WIDTH: int = 340
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

        self.resize(self.WIDTH, 260)

    def set_data(self, d: Any) -> None:
        """Update panel with result from fetch_mail_waiting()."""
        try:
            if not isinstance(d, dict):
                d = {}
            self._data = d
            self._total_open = int(d.get("total_open") or 0)
            self._hidden_auto = int(d.get("hidden_auto") or 0)
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
                    acc_by_key[a.get("key", "").lower()] = a

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

    def _visible_items_for_account(self, acc: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return non-auto items to display in rows."""
        raw_items = acc.get("items") if isinstance(acc.get("items"), list) else []
        return [it for it in raw_items if isinstance(it, dict) and not it.get("auto")]

    def _compute_body_total_height(self) -> float:
        """Compute virtual unconstrained height of the mail items body."""
        if not self._accounts:
            return 40.0

        all_visible_count = sum(len(self._visible_items_for_account(a)) for a in self._accounts)
        all_hidden_count = sum(int(a.get("hidden_auto") or 0) for a in self._accounts)
        if all_visible_count == 0 and all_hidden_count == 0:
            return 50.0

        h = 0.0
        for acc in self._accounts:
            h += 20.0  # Section header ('IAS · 2')
            vis_items = self._visible_items_for_account(acc)
            hidden_auto = int(acc.get("hidden_auto") or 0)

            if not vis_items and hidden_auto == 0:
                h += 22.0  # 'Bekleyen yanıt yok'
            else:
                for _ in vis_items:
                    h += 39.0  # Row height: 36px + 3px gap
                if hidden_auto > 0:
                    h += 20.0  # 'N otomatik bildirim gizlendi'
            h += 8.0  # Section bottom margin
        return h

    def compute_height(self) -> int:
        """Compute card height dynamically."""
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        # Header (16 + 24 + 12) + body + footer gap (10) + hairline (1) + footer (24) + padding (14)
        total = 16.0 + 24.0 + 12.0 + body_h + 10.0 + 1.0 + 24.0 + 14.0
        return int(math.ceil(total))

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)

        # 1. Background Obsidian Acrylic
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(COLOR_BG)
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Subtle 1px outer stroke
        p.setPen(QPen(COLOR_ROW_BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)

        # 2. Header
        header_y = 16.0
        icon_rect = QRectF(16.0, header_y + 3.0, 18.0, 18.0)
        if self._svg_renderer and self._svg_renderer.isValid():
            self._svg_renderer.render(p, icon_rect)

        # Title
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        title_rect = QRectF(40.0, header_y, 160.0, 24.0)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Yanıt bekleyen mailler")

        # Top-right ✕ close button
        close_x = w - 16.0 - 20.0
        self._close_rect = QRectF(close_x, header_y + 2.0, 20.0, 20.0)
        if self._close_hovered:
            p.fillPath(rounded_path(self._close_rect, 4.0), COLOR_CLOSE_HOVER_BG)
        p.setPen(QPen(COLOR_TEXT_MUTED, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx = self._close_rect.center().x()
        cy = self._close_rect.center().y()
        d = 4.0
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))

        # Badge 'N bekliyor'
        badge_text = f"{self._total_open} bekliyor"
        p.setFont(self.f_badge)
        fm_badge = QFontMetricsF(self.f_badge)
        badge_w = fm_badge.horizontalAdvance(badge_text) + 12.0
        badge_rect = QRectF(close_x - badge_w - 8.0, header_y + 2.0, badge_w, 20.0)
        p.fillPath(rounded_path(badge_rect, 10.0), COLOR_BADGE_BG)
        p.setPen(COLOR_BADGE_TXT)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 3. Body items list
        body_top = header_y + 24.0 + 12.0
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        body_rect = QRectF(14.0, body_top, w - 28.0, body_h)

        p.save()
        p.setClipRect(body_rect)

        # Reset hit testing rects
        self._row_rects.clear()

        cur_y = body_top - self._scroll_y

        all_vis = sum(len(self._visible_items_for_account(a)) for a in self._accounts)
        all_hidden = sum(int(a.get("hidden_auto") or 0) for a in self._accounts)
        if all_vis == 0 and all_hidden == 0:
            p.setFont(self.f_empty)
            p.setPen(COLOR_TEXT_DIM)
            p.drawText(
                QRectF(16.0, cur_y + 10.0, w - 32.0, 24.0),
                Qt.AlignmentFlag.AlignCenter,
                "Yanıt bekleyen mail yok",
            )
            cur_y += 40.0
        else:
            for acc in self._accounts:
                label = str(acc.get("label") or "").upper()
                open_cnt = int(acc.get("open") or 0)
                sec_head = f"{label} · {open_cnt}"

                # Section Header
                p.setFont(self.f_sec_title)
                p.setPen(COLOR_TEXT_MUTED)
                p.drawText(
                    QRectF(16.0, cur_y, w - 32.0, 18.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    sec_head,
                )
                cur_y += 20.0

                vis_items = self._visible_items_for_account(acc)
                hidden_count = int(acc.get("hidden_auto") or 0)

                if not vis_items and hidden_count == 0:
                    p.setFont(self.f_empty)
                    p.setPen(COLOR_TEXT_DIM)
                    p.drawText(
                        QRectF(18.0, cur_y, w - 36.0, 18.0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        "Bekleyen yanıt yok",
                    )
                    cur_y += 22.0
                else:
                    for it in vis_items:
                        is_closed = bool(it.get("kapanis_tahmini", False))
                        is_unread = bool(it.get("okunmamis", False))
                        url = str(it.get("url") or "")

                        row_rect = QRectF(14.0, cur_y, w - 28.0, 36.0)
                        self._row_rects.append((row_rect, it))

                        # Row background
                        is_hovered = (self._hover_item_url == url and bool(url))
                        if is_hovered:
                            bg_col = COLOR_ROW_HOVER
                        elif is_closed:
                            bg_col = COLOR_ROW_DIMMED_BG
                        else:
                            bg_col = COLOR_ROW_BG
                        border_col = COLOR_ROW_DIMMED_BORDER if is_closed else COLOR_ROW_BORDER

                        p.fillPath(rounded_path(row_rect, 7.0), bg_col)
                        p.setPen(QPen(border_col, 1.0))
                        p.setBrush(Qt.BrushStyle.NoBrush)  # önceki fırça (ör. mavi okunmamış nokta) kenarlık çiziminde dolguya sızmasın
                        p.drawPath(rounded_path(row_rect, 7.0))

                        # Unread blue dot
                        x_offset = 22.0
                        if is_unread and not is_closed:
                            dot_y = cur_y + 9.0
                            p.setPen(Qt.PenStyle.NoPen)
                            p.setBrush(COLOR_UNREAD_DOT)
                            p.drawEllipse(QPointF(x_offset + 2.5, dot_y), 2.5, 2.5)
                            x_offset += 10.0

                        # Sender name
                        sender_name = str(it.get("kimden") or "")
                        p.setFont(self.f_row_name)
                        p.setPen(COLOR_TEXT_DIM if is_closed else COLOR_TEXT_PRIMARY)

                        # Right-aligned tag (waiting duration chip or 'muhtemelen kapandı')
                        if is_closed:
                            p.setFont(self.f_tag_italic)
                            p.setPen(COLOR_TEXT_DIM)
                            tag_text = "muhtemelen kapandı"
                            fm_tag = QFontMetricsF(self.f_tag_italic)
                            tag_w = fm_tag.horizontalAdvance(tag_text)
                            p.drawText(
                                QRectF(w - 22.0 - tag_w, cur_y + 4.0, tag_w, 15.0),
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                tag_text,
                            )
                            sender_max_w = (w - 22.0 - tag_w - 6.0) - x_offset
                        else:
                            wait_h = it.get("bekleme_saat")
                            chip_text = work_sources.tr_relative_hours(wait_h) if work_sources else f"{wait_h} sa"
                            p.setFont(self.f_tag)
                            fm_chip = QFontMetricsF(self.f_tag)
                            chip_tw = fm_chip.horizontalAdvance(chip_text)
                            chip_w = chip_tw + 8.0
                            chip_rect = QRectF(w - 22.0 - chip_w, cur_y + 4.0, chip_w, 14.0)
                            p.fillPath(rounded_path(chip_rect, 4.0), COLOR_WAIT_CHIP_BG)
                            p.setPen(COLOR_WAIT_CHIP_TXT)
                            p.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, chip_text)
                            sender_max_w = (w - 22.0 - chip_w - 6.0) - x_offset

                        # Elide sender
                        fm_sender = QFontMetricsF(self.f_row_name)
                        elided_sender = fm_sender.elidedText(sender_name, Qt.TextElideMode.ElideRight, max(20.0, sender_max_w))
                        p.setFont(self.f_row_name)
                        p.setPen(COLOR_TEXT_DIM if is_closed else COLOR_TEXT_PRIMARY)
                        p.drawText(
                            QRectF(x_offset, cur_y + 4.0, max(20.0, sender_max_w), 15.0),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            elided_sender,
                        )

                        # Subject line
                        subject = str(it.get("konu") or "")
                        p.setFont(self.f_row_sub)
                        p.setPen(COLOR_TEXT_DIM if is_closed else COLOR_TEXT_MUTED)
                        fm_sub = QFontMetricsF(self.f_row_sub)
                        sub_max_w = w - 44.0
                        elided_sub = fm_sub.elidedText(subject, Qt.TextElideMode.ElideRight, sub_max_w)
                        p.drawText(
                            QRectF(22.0, cur_y + 19.0, sub_max_w, 14.0),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            elided_sub,
                        )

                        cur_y += 39.0

                    # Automated notifications concealed line
                    if hidden_count > 0:
                        p.setFont(self.f_empty)
                        p.setPen(COLOR_TEXT_MUTED)
                        p.drawText(
                            QRectF(20.0, cur_y, w - 40.0, 18.0),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            f"{hidden_count} otomatik bildirim gizlendi",
                        )
                        cur_y += 20.0

                cur_y += 8.0

        p.restore()

        # Thin 3px scroll indicator
        total_list_h = self._compute_body_total_height()
        if total_list_h > body_h and self._scroll_y > 0.5:
            max_scroll = total_list_h - body_h
            thumb_h = max(24.0, body_h * (body_h / total_list_h))
            thumb_y = body_top + (self._scroll_y / max_scroll) * (body_h - thumb_h)
            thumb_rect = QRectF(w - 7.0, thumb_y, 3.0, thumb_h)
            p.fillPath(rounded_path(thumb_rect, 1.5), COLOR_SCROLL_INDICATOR)

        # 4. Footer
        footer_line_y = body_top + body_h + 10.0
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(16.0, footer_line_y), QPointF(w - 16.0, footer_line_y))

        footer_y = footer_line_y + 1.0 + 8.0

        # Footer Left: Hermes taraması · 08:31 (with amber 'eski' tag if stale)
        scan_time = self._scanned_at_str or "--:--"
        left_text = f"Hermes taraması · {scan_time}"
        p.setFont(self.f_footer)
        p.setPen(COLOR_TEXT_MUTED)
        fm_footer = QFontMetricsF(self.f_footer)
        txt_w = fm_footer.horizontalAdvance(left_text)
        p.drawText(
            QRectF(16.0, footer_y, txt_w, 22.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            left_text,
        )

        if self._stale:
            stale_rect = QRectF(16.0 + txt_w + 6.0, footer_y + 3.0, 32.0, 16.0)
            p.fillPath(rounded_path(stale_rect, 4.0), COLOR_STALE_BG)
            p.setFont(self.f_tag)
            p.setPen(COLOR_STALE_TXT)
            p.drawText(stale_rect, Qt.AlignmentFlag.AlignCenter, "eski")

        # Footer Right: Yenile button
        btn_w = 64.0
        btn_h = 22.0
        self._refresh_rect = QRectF(w - 16.0 - btn_w, footer_y, btn_w, btn_h)

        if self._refresh_pressed:
            btn_bg = COLOR_REFRESH_BG_PRESS
        elif self._refresh_hovered:
            btn_bg = COLOR_REFRESH_BG_HOVER
        else:
            btn_bg = COLOR_REFRESH_BG

        p.fillPath(rounded_path(self._refresh_rect, 6.0), btn_bg)
        p.setPen(QPen(COLOR_REFRESH_BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)  # önceki fırça (ör. mavi okunmamış nokta) kenarlık çiziminde dolguya sızmasın
        p.drawPath(rounded_path(self._refresh_rect, 6.0))

        p.setFont(self.f_btn)
        p.setPen(COLOR_REFRESH_TXT)
        p.drawText(self._refresh_rect, Qt.AlignmentFlag.AlignCenter, "Yenile")

    # -----------------------------------------------------------------------
    # Mouse & Hit Testing
    # -----------------------------------------------------------------------
    def _row_at_point(self, pos: QPointF) -> Optional[Dict[str, Any]]:
        for r, item in self._row_rects:
            if r.contains(pos):
                return item
        return None

    def mousePressEvent(self, event) -> None:
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

    def mouseReleaseEvent(self, event) -> None:
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

    def mouseMoveEvent(self, event) -> None:
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

    def wheelEvent(self, event) -> None:
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
    """Obsidian popover panel for Antigravity model quota usage."""

    WIDTH: int = 320
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

        self.resize(self.WIDTH, 240)

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

        # Each group card: ~56px + 8px margin
        return len(self._groups) * 64.0

    def compute_height(self) -> int:
        """Compute dynamic window height."""
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        # Header (16 + 24 + 12) + body + footer gap (10) + hairline (1) + footer (24) + padding (14)
        total = 16.0 + 24.0 + 12.0 + body_h + 10.0 + 1.0 + 24.0 + 14.0
        return int(math.ceil(total))

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)

        # 1. Background Obsidian Acrylic
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(COLOR_BG)
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Subtle 1px outer stroke
        p.setPen(QPen(COLOR_ROW_BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)

        # 2. Header
        header_y = 16.0
        icon_rect = QRectF(16.0, header_y + 3.0, 18.0, 18.0)
        if self._png_pixmap and not self._png_pixmap.isNull():
            p.drawPixmap(icon_rect, self._png_pixmap, QRectF(self._png_pixmap.rect()))

        # Title
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        title_rect = QRectF(40.0, header_y, 140.0, 24.0)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Antigravity kotası")

        # Top-right ✕ close button
        close_x = w - 16.0 - 20.0
        self._close_rect = QRectF(close_x, header_y + 2.0, 20.0, 20.0)
        if self._close_hovered:
            p.fillPath(rounded_path(self._close_rect, 4.0), COLOR_CLOSE_HOVER_BG)
        p.setPen(QPen(COLOR_TEXT_MUTED, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx = self._close_rect.center().x()
        cy = self._close_rect.center().y()
        d = 4.0
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))

        # Badge 'Canlı kota'
        badge_text = "Canlı kota"
        p.setFont(self.f_badge)
        fm_badge = QFontMetricsF(self.f_badge)
        badge_w = fm_badge.horizontalAdvance(badge_text) + 12.0
        badge_rect = QRectF(close_x - badge_w - 8.0, header_y + 2.0, badge_w, 20.0)
        p.fillPath(rounded_path(badge_rect, 10.0), COLOR_BADGE_BG)
        p.setPen(COLOR_BADGE_TXT)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 3. Body
        body_top = header_y + 24.0 + 12.0
        body_h = min(self.BODY_MAX_HEIGHT, self._compute_body_total_height())
        body_rect = QRectF(14.0, body_top, w - 28.0, body_h)

        p.save()
        p.setClipRect(body_rect)

        cur_y = body_top - self._scroll_y

        if self._has_error or not self._groups:
            p.setFont(self.f_empty)
            p.setPen(COLOR_TEXT_DIM)
            p.drawText(
                QRectF(16.0, cur_y + 10.0, w - 32.0, 24.0),
                Qt.AlignmentFlag.AlignCenter,
                "Antigravity okunamadı",
            )
        else:
            for g in self._groups:
                row_h = 56.0
                card_rect = QRectF(14.0, cur_y, w - 28.0, row_h)

                # Row Card Background
                p.fillPath(rounded_path(card_rect, 8.0), COLOR_ROW_BG)
                p.setPen(QPen(COLOR_ROW_BORDER, 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)  # önceki fırça (ör. mavi okunmamış nokta) kenarlık çiziminde dolguya sızmasın
                p.drawPath(rounded_path(card_rect, 8.0))

                # Header of card: Model Label Left, Percentage Right
                lbl = str(g.get("label") or "")
                used = float(g.get("used", 0.0))
                pct_str = f"%{int(round(used))} dolu" if used >= 100.0 else f"%{int(round(used))}"

                # Percentage
                p.setFont(self.f_val_tabular)
                p.setPen(COLOR_TEXT_MUTED)
                fm_pct = QFontMetricsF(self.f_val_tabular)
                pct_w = fm_pct.horizontalAdvance(pct_str)
                p.drawText(
                    QRectF(w - 24.0 - pct_w, cur_y + 7.0, pct_w, 16.0),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    pct_str,
                )

                # Model Label
                p.setFont(self.f_row_name)
                p.setPen(COLOR_TEXT_PRIMARY)
                lbl_max_w = (w - 24.0 - pct_w - 8.0) - 24.0
                fm_lbl = QFontMetricsF(self.f_row_name)
                elided_lbl = fm_lbl.elidedText(lbl, Qt.TextElideMode.ElideRight, max(20.0, lbl_max_w))
                p.drawText(
                    QRectF(24.0, cur_y + 7.0, max(20.0, lbl_max_w), 16.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    elided_lbl,
                )

                # 5px Progress Bar
                bar_y = cur_y + 27.0
                bar_w = w - 48.0
                bar_rect = QRectF(24.0, bar_y, bar_w, 5.0)

                # Track
                p.fillPath(rounded_path(bar_rect, 2.5), COLOR_BAR_TRACK)

                # Fill
                fill_w = max(0.0, min(bar_w, bar_w * (used / 100.0)))
                if fill_w > 0.5:
                    if used >= 90.0:
                        fill_col = COLOR_BAR_RED
                    elif used >= 70.0:
                        fill_col = COLOR_BAR_AMBER
                    else:
                        fill_col = COLOR_BAR_GREEN
                    fill_rect = QRectF(24.0, bar_y, fill_w, 5.0)
                    p.fillPath(rounded_path(fill_rect, 2.5), fill_col)

                # Subline: Renewal time
                reset_tr = g.get("reset_tr")
                sub_text = f"Yenilenme: {reset_tr}" if reset_tr else "Yenilenme bilinmiyor"
                p.setFont(self.f_tag)
                p.setPen(COLOR_TEXT_DIM)
                p.drawText(
                    QRectF(24.0, cur_y + 36.0, bar_w, 14.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    sub_text,
                )

                cur_y += row_h + 8.0

        p.restore()

        # Thin 3px scroll indicator
        total_list_h = self._compute_body_total_height()
        if total_list_h > body_h and self._scroll_y > 0.5:
            max_scroll = total_list_h - body_h
            thumb_h = max(24.0, body_h * (body_h / total_list_h))
            thumb_y = body_top + (self._scroll_y / max_scroll) * (body_h - thumb_h)
            thumb_rect = QRectF(w - 7.0, thumb_y, 3.0, thumb_h)
            p.fillPath(rounded_path(thumb_rect, 1.5), COLOR_SCROLL_INDICATOR)

        # 4. Footer
        footer_line_y = body_top + body_h + 10.0
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(16.0, footer_line_y), QPointF(w - 16.0, footer_line_y))

        footer_y = footer_line_y + 1.0 + 8.0

        # Footer Left: Antigravity · 11:30
        left_str = f"Antigravity · {self._fetched_at_str}" if self._fetched_at_str else "Antigravity"
        p.setFont(self.f_footer)
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(
            QRectF(16.0, footer_y, 160.0, 22.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            left_str,
        )

        # Footer Right: Yenile button
        btn_w = 64.0
        btn_h = 22.0
        self._refresh_rect = QRectF(w - 16.0 - btn_w, footer_y, btn_w, btn_h)

        if self._refresh_pressed:
            btn_bg = COLOR_REFRESH_BG_PRESS
        elif self._refresh_hovered:
            btn_bg = COLOR_REFRESH_BG_HOVER
        else:
            btn_bg = COLOR_REFRESH_BG

        p.fillPath(rounded_path(self._refresh_rect, 6.0), btn_bg)
        p.setPen(QPen(COLOR_REFRESH_BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)  # önceki fırça (ör. mavi okunmamış nokta) kenarlık çiziminde dolguya sızmasın
        p.drawPath(rounded_path(self._refresh_rect, 6.0))

        p.setFont(self.f_btn)
        p.setPen(COLOR_REFRESH_TXT)
        p.drawText(self._refresh_rect, Qt.AlignmentFlag.AlignCenter, "Yenile")

    # -----------------------------------------------------------------------
    # Mouse & Hit Testing
    # -----------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
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

    def mouseReleaseEvent(self, event) -> None:
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

    def mouseMoveEvent(self, event) -> None:
        try:
            pos = event.position()
            self._close_hovered = self._close_rect.contains(pos)
            self._refresh_hovered = self._refresh_rect.contains(pos)
        except Exception as exc:
            _log_err("QuotaPanel.mouseMoveEvent", exc)
        super().mouseMoveEvent(event)

    def wheelEvent(self, event) -> None:
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
