"""Modern obsidian acrylic tray popover panel for the Şerit dock.

Displays live system tray icons in a compact flyout list matching the approved v5
obsidian design system with high-DPI crisp icons, Turkish name cleaning, status
translations, smooth scrolling, keyboard navigation, and fluent animations.
"""

from __future__ import annotations

import math
from pathlib import Path
import re
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
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

# Safe imports from serit package
try:
    import sources
    import winapi
except ImportError:
    serit_dir = str(Path(__file__).resolve().parent)
    if serit_dir not in sys.path:
        sys.path.insert(0, serit_dir)
    try:
        import sources
        import winapi
    except Exception:
        sources = None
        winapi = None


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available."""
    if sources and hasattr(sources, "log_err"):
        try:
            sources.log_err(source, exc)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Visual Styling Tokens (Obsidian Acrylic Glass & Lumabar Matte)
# ---------------------------------------------------------------------------

WIDTH: int = 310
# Note: PopoverV2 uses 14.0; TrayPanel uses 16.0 per approved v5 mockup spec
RADIUS: float = 16.0

COLOR_BG: QColor = QColor(20, 21, 25, 248)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(225, 228, 235, 240)
COLOR_TEXT_MUTED: QColor = QColor(148, 154, 166, 220)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 20)

COLOR_BADGE_BG: QColor = QColor(255, 255, 255, 20)
COLOR_BADGE_TXT: QColor = QColor(148, 154, 166, 220)

COLOR_ROW_HOVER: QColor = QColor(255, 255, 255, 18)
COLOR_ROW_HIGHLIGHT: QColor = QColor(255, 255, 255, 26)

COLOR_REFRESH_BG: QColor = QColor(255, 255, 255, 22)
COLOR_REFRESH_BG_HOVER: QColor = QColor(255, 255, 255, 38)
COLOR_REFRESH_BG_PRESS: QColor = QColor(255, 255, 255, 55)
COLOR_REFRESH_BORDER: QColor = QColor(255, 255, 255, 24)
COLOR_REFRESH_TXT: QColor = QColor(255, 255, 255, 245)

COLOR_SCROLL_INDICATOR: QColor = QColor(255, 255, 255, 70)


def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    tabular: bool = False,
    letter_spacing: Optional[float] = None,
) -> QFont:
    """Create a high-DPI Segoe UI Variable font instance."""
    f = QFont("Segoe UI Variable Text")
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    f.setPixelSize(int(round(size_px)))
    f.setWeight(weight)
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


# ---------------------------------------------------------------------------
# Public Helper Functions
# ---------------------------------------------------------------------------

KNOWN_NAME_MAP: Dict[str, str] = {
    "nvidia settings": "NVIDIA Ayarları",
    "windows security": "Windows Güvenlik",
    "securityhealthsystray": "Windows Güvenlik",
    "whatsapp.root": "WhatsApp",
    "whatsapp": "WhatsApp",
    "dsatray": "Intel Destek Asistanı",
    "powertoys awake": "PowerToys Awake",
    "dikte · türkçe": "Dikte · Türkçe",
    "dikte": "Dikte · Türkçe",
}

STATUS_MAP: List[Tuple[str, str]] = [
    ("not signed in", "Oturum açılmadı"),
    ("no actions needed", "İşlem gerekmiyor"),
    ("up to date", "Güncel"),
]


def clean_tray_name(item: Any) -> str:
    """Return Turkish, short display name from item['name'] / item['tooltip'] / item['exe'].

    Rules:
    - Drop English status suffixes after ' - ', ' – ', ' — '.
    - Drop version numbers (e.g. 'PowerToys v0.98.1' -> 'PowerToys').
    - Map known system / app names to Turkish equivalents.
    - Strip trailing '.exe'.
    - Never return empty string (fallback to exe base name, then 'Uygulama').
    """
    if not isinstance(item, dict):
        return "Uygulama"

    raw_name = item.get("name")
    raw_tip = item.get("tooltip")
    raw_exe = item.get("exe")

    # Pick candidate string
    s = ""
    for candidate in [raw_name, raw_tip]:
        if candidate and isinstance(candidate, str) and candidate.strip():
            s = candidate.strip()
            break

    if not s and raw_exe and isinstance(raw_exe, str):
        try:
            s = Path(raw_exe).stem
        except Exception:
            s = ""

    if not s:
        return "Uygulama"

    # Strip trailing .exe if present
    if s.lower().endswith(".exe"):
        s = s[:-4].strip()

    # Drop duplicate repeated phrase (e.g. "PowerToys Awake PowerToys Awake" -> "PowerToys Awake")
    s = re.sub(r"^(.{3,})\s+\1$", r"\1", s).strip()

    # Drop English status suffixes after ' - ', ' – ', ' — '
    s = re.split(r"\s+[-–—]\s+", s, maxsplit=1)[0].strip()

    # Drop version numbers (e.g. 'PowerToys v0.98.1' -> 'PowerToys', 'App 1.2.3' -> 'App')
    s = re.sub(r"\s+v\d+(\.\d+)*.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+\d+(\.\d+){2,}.*$", "", s).strip()

    # Strip trailing .exe again if leftover
    if s.lower().endswith(".exe"):
        s = s[:-4].strip()

    # Check known names mapping
    low = s.lower()
    if low in KNOWN_NAME_MAP:
        return KNOWN_NAME_MAP[low]

    # Check if exe stem matches known names
    if raw_exe and isinstance(raw_exe, str):
        try:
            exe_stem = Path(raw_exe).stem.lower()
            if exe_stem in KNOWN_NAME_MAP:
                return KNOWN_NAME_MAP[exe_stem]
        except Exception:
            pass

    if not s:
        if raw_exe and isinstance(raw_exe, str):
            try:
                base = Path(raw_exe).stem
                if base:
                    return base
            except Exception:
                pass
        return "Uygulama"

    return s


def tray_status_tr(item: Any) -> str:
    """Return Turkish second line from tooltip status, only for known phrases, else ''."""
    if not isinstance(item, dict):
        return ""

    texts: List[str] = []
    tip = item.get("tooltip")
    if tip and isinstance(tip, str):
        texts.append(tip)
    name = item.get("name")
    if name and isinstance(name, str):
        texts.append(name)

    combined = " ".join(texts).lower()
    for phrase, tr_status in STATUS_MAP:
        if phrase in combined:
            return tr_status
    return ""


def dedupe_tray_items(items: Any) -> List[Dict[str, Any]]:
    """Remove duplicates by cleaned name keeping the first."""
    if not isinstance(items, list):
        return []
    seen = set()
    result: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cleaned = clean_tray_name(it).strip().lower()
        if cleaned not in seen:
            seen.add(cleaned)
            result.append(it)
    return result


# ---------------------------------------------------------------------------
# Vector Icon Primitives
# ---------------------------------------------------------------------------

def draw_generic_app_glyph(p: QPainter, rect: QRectF) -> None:
    """Draw a clean, platform-neutral vector app window glyph (NO letters)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer squircle container
    path = QPainterPath()
    path.addRoundedRect(rect, 4.5, 4.5)
    p.fillPath(path, QColor(255, 255, 255, 22))
    p.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
    p.drawPath(path)

    # Titlebar separator line
    p.setPen(QPen(QColor(255, 255, 255, 80), 1.0))
    p.drawLine(
        QPointF(rect.left() + 3.0, rect.top() + 6.0),
        QPointF(rect.right() - 3.0, rect.top() + 6.0),
    )

    # Content window panes
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawRoundedRect(QRectF(rect.left() + 3.5, rect.top() + 8.5, 5.0, 6.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(rect.right() - 8.5, rect.top() + 8.5, 5.0, 6.0), 1.0, 1.0)

    p.restore()


# ---------------------------------------------------------------------------
# TrayPanel Widget
# ---------------------------------------------------------------------------

class TrayPanel(QWidget):
    """Modern obsidian acrylic flyout panel for Windows system tray icons."""

    WIDTH: int = WIDTH
    RADIUS: float = RADIUS

    ROW_HEIGHT: float = 34.0
    ROW_GAP: float = 2.0
    ROW_STRIDE: float = 36.0  # 34 + 2
    LIST_MAX_HEIGHT: float = 340.0

    PADDING_TOP: float = 16.0
    PADDING_BOTTOM: float = 14.0
    HEADER_HEIGHT: float = 24.0
    HEADER_BOTTOM_GAP: float = 14.0
    FOOTER_TOP_GAP: float = 10.0
    FOOTER_HEIGHT: float = 24.0

    item_activated = Signal(object, str)
    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Frameless translucent flyout setup
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Tray state
        self._items: List[Dict[str, Any]] = []
        self._icons: Dict[str, Any] = {}
        self._scaled_icons: Dict[Tuple[str, float], QPixmap] = {}
        self._generic_glyph_cache: Dict[float, QPixmap] = {}
        self._anchor_global: Optional[QRectF] = None

        # Interactive states
        self._hover_idx: int = -1
        self._highlight_idx: int = -1
        self._close_hovered: bool = False
        self._refresh_hovered: bool = False
        self._refresh_pressed: bool = False

        # Scrolling state
        self._scroll_y: float = 0.0

        # Geometry rects for hit-testing
        self._close_rect: QRectF = QRectF()
        self._refresh_rect: QRectF = QRectF()
        self._list_rect: QRectF = QRectF()

        # Lifecycle & Animation
        self._last_close_time: float = 0.0
        self._is_closing: bool = False

        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Typography
        self.f_title = make_font(13.5, QFont.Weight.DemiBold)
        self.f_badge = make_font(10.0, QFont.Weight.Normal)
        self.f_name = make_font(12.0, QFont.Weight.DemiBold)
        self.f_sub = make_font(10.5, QFont.Weight.Normal)
        self.f_footer = make_font(10.5, QFont.Weight.Normal)
        self.f_btn = make_font(11.0, QFont.Weight.Medium)
        self.f_empty = make_font(12.0, QFont.Weight.Normal)

        self.resize(self.WIDTH, self.compute_height())

    # -----------------------------------------------------------------------
    # Public API
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

    def set_items(self, items: Any, icons: Any = None) -> None:
        """Update displayed tray items and icon cache without throwing."""
        try:
            raw_list = items if isinstance(items, list) else []
            sanitized: List[Dict[str, Any]] = []
            for it in raw_list:
                if isinstance(it, dict):
                    sanitized.append(it)
                else:
                    sanitized.append({"name": str(it) if it is not None else ""})
            self._items = sanitized

            if isinstance(icons, dict):
                self._icons = icons
            else:
                self._icons = {}

            self._scaled_icons.clear()

            # Clamp hover, highlight, and scroll
            if self._highlight_idx >= len(self._items):
                self._highlight_idx = len(self._items) - 1
            if self._hover_idx >= len(self._items):
                self._hover_idx = -1

            max_scroll = max(0.0, self._total_list_height() - self._visible_list_height())
            self._scroll_y = max(0.0, min(max_scroll, self._scroll_y))

            h = self.compute_height()
            self.resize(self.WIDTH, h)
            self.update()
        except Exception as exc:
            _log_err("TrayPanel.set_items", exc)

    def compute_height(self) -> int:
        """Compute card height dynamically based on item count."""
        try:
            list_h = self._visible_list_height()
            total_h = (
                self.PADDING_TOP
                + self.HEADER_HEIGHT
                + self.HEADER_BOTTOM_GAP
                + list_h
                + self.FOOTER_TOP_GAP
                + 1.0  # hairline
                + self.FOOTER_HEIGHT
                + self.PADDING_BOTTOM
            )
            return int(math.ceil(total_h))
        except Exception as exc:
            _log_err("TrayPanel.compute_height", exc)
            return 200

    def show_for(self, anchor_global: Optional[QRectF]) -> None:
        """Position panel above anchor right-aligned and trigger entry transition."""
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
                # Right-aligned to anchor's right edge
                target_x = int(self._anchor_global.right() - self.width())
                target_y = int(self._anchor_global.top() - self.height() - 8)

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
                        below_y = int(self._anchor_global.bottom() + 8)
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
                    _log_err("TrayPanel.winapi", exc)

            # Trigger open transition: fade 0->1, slide 8px in 190ms OutCubic
            self._is_closing = False
            self._anim.stop()
            self._anim.setDuration(190)
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
            _log_err("TrayPanel.show_for", exc)

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
            _log_err("TrayPanel.hide_animated", exc)

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current popover view offscreen to a high-DPI ARGB32 QImage."""
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

            saved_op = self._anim_opacity
            saved_off = self._anim_offset_y
            self._anim_opacity = 1.0
            self._anim_offset_y = 0.0

            self._paint_card(p)

            self._anim_opacity = saved_op
            self._anim_offset_y = saved_off

            p.end()
            return img
        except Exception as exc:
            _log_err("TrayPanel.render_to_image", exc)
            return QImage()

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _total_list_height(self) -> float:
        if not self._items:
            return 40.0
        return max(34.0, len(self._items) * self.ROW_STRIDE - self.ROW_GAP)

    def _visible_list_height(self) -> float:
        if not self._items:
            return 40.0
        return min(self.LIST_MAX_HEIGHT, self._total_list_height())

    def _get_scaled_icon(self, item: Dict[str, Any], dpr: float) -> Optional[QPixmap]:
        """Return crisp pre-scaled QPixmap cached per DPR, or None if missing."""
        name = str(item.get("name") or "")
        cache_key = (name, dpr)
        if cache_key in self._scaled_icons:
            return self._scaled_icons[cache_key]

        pm = None
        if name in self._icons:
            pm = self._icons[name]
        elif item.get("tooltip") and str(item["tooltip"]) in self._icons:
            pm = self._icons[str(item["tooltip"])]
        elif item.get("exe") and str(item["exe"]) in self._icons:
            pm = self._icons[str(item["exe"])]

        if isinstance(pm, QPixmap) and not pm.isNull():
            target_px = int(round(20.0 * dpr))
            scaled = pm.scaled(
                target_px,
                target_px,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._scaled_icons[cache_key] = scaled
            return scaled

        return None

    def _get_generic_glyph(self, dpr: float) -> QPixmap:
        """Return cached generic app glyph QPixmap for missing icons at target DPR."""
        if dpr in self._generic_glyph_cache:
            return self._generic_glyph_cache[dpr]

        size_px = int(round(20.0 * dpr))
        pm = QPixmap(size_px, size_px)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_generic_app_glyph(p, QRectF(0.5, 0.5, 19.0, 19.0))
        p.end()

        self._generic_glyph_cache[dpr] = pm
        return pm

    def _row_at_point(self, pos: QPointF) -> int:
        """Hit test row index from local coordinates."""
        if not self._list_rect.contains(pos):
            return -1
        rel_y = pos.y() - self._list_rect.top() + self._scroll_y
        if rel_y < 0:
            return -1
        idx = int(rel_y // self.ROW_STRIDE)
        if 0 <= idx < len(self._items):
            offset = rel_y % self.ROW_STRIDE
            if offset <= self.ROW_HEIGHT:
                return idx
        return -1

    def _ensure_row_visible(self, idx: int) -> None:
        """Adjust scroll position so that row at idx is within view."""
        if idx < 0 or idx >= len(self._items):
            return
        row_top = idx * self.ROW_STRIDE
        row_bottom = row_top + self.ROW_HEIGHT
        vis_h = self._visible_list_height()
        max_scroll = max(0.0, self._total_list_height() - vis_h)

        if row_top < self._scroll_y:
            self._scroll_y = max(0.0, float(row_top))
        elif row_bottom > self._scroll_y + vis_h:
            self._scroll_y = min(max_scroll, float(row_bottom - vis_h))

    # -----------------------------------------------------------------------
    # Animation Callbacks
    # -----------------------------------------------------------------------

    def _on_anim_value_changed(self, val: float) -> None:
        try:
            f = float(val)
            self._anim_progress = f
            self._anim_opacity = max(0.0, min(1.0, f))
            if self._is_closing:
                self._anim_offset_y = 6.0 * (1.0 - self._anim_opacity)
            else:
                self._anim_offset_y = 8.0 * (1.0 - self._anim_opacity)
            self.update()
        except Exception as exc:
            _log_err("TrayPanel.anim_value", exc)

    def _on_anim_finished(self) -> None:
        try:
            if self._is_closing:
                self.hide()
                self._is_closing = False
                self._anim_opacity = 0.0
                self.update()
        except Exception as exc:
            _log_err("TrayPanel.anim_finished", exc)

    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    # -----------------------------------------------------------------------
    # Painting Implementation
    # -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._paint_card(p)
        except Exception as exc:
            _log_err("TrayPanel.paintEvent", exc)
        finally:
            p.end()

    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        dpr = p.device().devicePixelRatio() if p.device() else 1.0

        p.save()
        p.setOpacity(self._anim_opacity)
        p.translate(0.0, self._anim_offset_y)

        r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = rounded_path(r, self.RADIUS)

        # 1. Base dark acrylic glass fill
        p.fillPath(path, COLOR_BG)

        # 2. Specular top sheen
        p.save()
        p.setClipPath(path)
        hl = QLinearGradient(0.0, 0.0, 0.0, 6.0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 45))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(1.0, 1.0, w - 2.0, 6.0), hl)
        p.restore()

        # 3. Dual boundary strokes (outer dark + inner specular rim)
        p.setPen(QPen(QColor(0, 0, 0, 95), 1.0))
        p.drawPath(path)

        inner_r = r.adjusted(0.75, 0.75, -0.75, -0.75)
        inner_path = rounded_path(inner_r, max(0.0, self.RADIUS - 0.75))
        rim_grad = QLinearGradient(0.0, 0.0, 0.0, h)
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 80))
        rim_grad.setColorAt(0.20, QColor(255, 255, 255, 30))
        rim_grad.setColorAt(0.80, QColor(255, 255, 255, 10))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 22))
        p.setPen(QPen(rim_grad, 1.0))
        p.drawPath(inner_path)

        # 4. Header: Chevron-up line icon + Title + Count Badge + Close ✕
        header_y = self.PADDING_TOP

        # Chevron-up vector icon (15px)
        cx_ch = 18.0 + 7.5
        cy_ch = header_y + 12.0
        p.save()
        pen_ch = QPen(
            QColor(255, 255, 255, 235),
            1.8,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        p.setPen(pen_ch)
        p.drawLine(QPointF(cx_ch - 4.5, cy_ch + 2.0), QPointF(cx_ch, cy_ch - 2.5))
        p.drawLine(QPointF(cx_ch, cy_ch - 2.5), QPointF(cx_ch + 4.5, cy_ch + 2.0))
        p.restore()

        # Title: 'Bildirim Alanı' 13.5px semibold
        title_text = "Bildirim Alanı"
        p.setFont(self.f_title)
        p.setPen(COLOR_TEXT_PRIMARY)
        fm_t = QFontMetricsF(self.f_title)
        title_w = fm_t.horizontalAdvance(title_text)
        title_rect = QRectF(38.0, header_y, title_w + 4.0, self.HEADER_HEIGHT)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_text)

        # Pill Badge: 'N öge'
        badge_text = f"{len(self._items)} öge"
        p.setFont(self.f_badge)
        fm_b = QFontMetricsF(self.f_badge)
        bw = fm_b.horizontalAdvance(badge_text) + 12.0
        badge_x = 38.0 + title_w + 8.0
        badge_rect = QRectF(badge_x, header_y + (self.HEADER_HEIGHT - 17.0) / 2.0, bw, 17.0)
        p.fillPath(rounded_path(badge_rect, 8.5), COLOR_BADGE_BG)
        p.setPen(COLOR_BADGE_TXT)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # Close ✕ button (24x24)
        self._close_rect = QRectF(w - 18.0 - 24.0, header_y, 24.0, 24.0)
        if self._close_hovered:
            p.fillPath(rounded_path(self._close_rect, 6.0), QColor(255, 255, 255, 25))

        cx_cl = self._close_rect.center().x()
        cy_cl = self._close_rect.center().y()
        p.save()
        close_pen_col = QColor(255, 255, 255, 240) if self._close_hovered else COLOR_TEXT_MUTED
        p.setPen(QPen(close_pen_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx_cl - 3.5, cy_cl - 3.5), QPointF(cx_cl + 3.5, cy_cl + 3.5))
        p.drawLine(QPointF(cx_cl + 3.5, cy_cl - 3.5), QPointF(cx_cl - 3.5, cy_cl + 3.5))
        p.restore()

        # 5. List Area (Max 340px)
        list_y = self.PADDING_TOP + self.HEADER_HEIGHT + self.HEADER_BOTTOM_GAP
        vis_h = self._visible_list_height()
        self._list_rect = QRectF(12.0, list_y, w - 24.0, vis_h)

        p.save()
        p.setClipRect(self._list_rect)

        if not self._items:
            p.setFont(self.f_empty)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(self._list_rect, Qt.AlignmentFlag.AlignCenter, "Gizli simge yok")
        else:
            avail_txt_w = w - 28.0 - 52.0 - 8.0

            for i, item in enumerate(self._items):
                row_y = list_y - self._scroll_y + i * self.ROW_STRIDE
                if row_y + self.ROW_HEIGHT < list_y or row_y > list_y + vis_h:
                    continue

                row_rect = QRectF(14.0, row_y, w - 28.0, self.ROW_HEIGHT)

                # Row hover / highlight background
                if i == self._hover_idx:
                    p.fillPath(rounded_path(row_rect, 8.0), COLOR_ROW_HOVER)
                elif i == self._highlight_idx:
                    p.fillPath(rounded_path(row_rect, 8.0), COLOR_ROW_HIGHLIGHT)

                # Icon (20x20 crisp)
                pm = self._get_scaled_icon(item, dpr)
                if pm is not None:
                    p.drawPixmap(QPointF(22.0, row_y + 7.0), pm)
                else:
                    glyph_pm = self._get_generic_glyph(dpr)
                    p.drawPixmap(QPointF(22.0, row_y + 7.0), glyph_pm)

                # Text: Name & Optional Turkish Status
                cleaned_name = clean_tray_name(item)
                status_str = tray_status_tr(item)

                if status_str:
                    p.setFont(self.f_name)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    fm_name = QFontMetricsF(self.f_name)
                    elided_name = fm_name.elidedText(
                        cleaned_name, Qt.TextElideMode.ElideRight, avail_txt_w
                    )
                    p.drawText(
                        QRectF(50.0, row_y + 3.0, avail_txt_w, 16.0),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        elided_name,
                    )

                    p.setFont(self.f_sub)
                    p.setPen(COLOR_TEXT_MUTED)
                    fm_sub = QFontMetricsF(self.f_sub)
                    elided_sub = fm_sub.elidedText(
                        status_str, Qt.TextElideMode.ElideRight, avail_txt_w
                    )
                    p.drawText(
                        QRectF(50.0, row_y + 18.0, avail_txt_w, 13.0),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        elided_sub,
                    )
                else:
                    p.setFont(self.f_name)
                    p.setPen(COLOR_TEXT_PRIMARY)
                    fm_name = QFontMetricsF(self.f_name)
                    elided_name = fm_name.elidedText(
                        cleaned_name, Qt.TextElideMode.ElideRight, avail_txt_w
                    )
                    p.drawText(
                        QRectF(50.0, row_y + 9.0, avail_txt_w, 16.0),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        elided_name,
                    )

        p.restore()

        # Thin 3px scroll indicator (drawn only while scrolled)
        total_h = self._total_list_height()
        if total_h > vis_h and self._scroll_y > 0.5:
            max_scroll = total_h - vis_h
            thumb_h = max(24.0, vis_h * (vis_h / total_h))
            thumb_y = list_y + (self._scroll_y / max_scroll) * (vis_h - thumb_h)
            thumb_rect = QRectF(w - 7.5, thumb_y, 3.0, thumb_h)
            p.fillPath(rounded_path(thumb_rect, 1.5), COLOR_SCROLL_INDICATOR)

        # 6. Footer (Hairline + 'Windows sistem tepsisi' + 'Yenile' button)
        footer_line_y = list_y + vis_h + self.FOOTER_TOP_GAP
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(18.0, footer_line_y), QPointF(w - 18.0, footer_line_y))

        footer_y = footer_line_y + 1.0 + (self.FOOTER_HEIGHT - 22.0) / 2.0

        # Footer Left Note
        p.setFont(self.f_footer)
        p.setPen(QColor(255, 255, 255, 115))
        note_rect = QRectF(18.0, footer_y, w - 36.0 - 66.0, 22.0)
        p.drawText(
            note_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Windows sistem tepsisi",
        )

        # Footer Right 'Yenile' Button (62x22, radius 6)
        self._refresh_rect = QRectF(w - 18.0 - 62.0, footer_y, 62.0, 22.0)
        btn_path = rounded_path(self._refresh_rect, 6.0)

        if self._refresh_pressed:
            btn_bg = COLOR_REFRESH_BG_PRESS
        elif self._refresh_hovered:
            btn_bg = COLOR_REFRESH_BG_HOVER
        else:
            btn_bg = COLOR_REFRESH_BG

        p.fillPath(btn_path, btn_bg)
        p.setPen(QPen(COLOR_REFRESH_BORDER, 1.0))
        p.drawPath(btn_path)

        p.setFont(self.f_btn)
        p.setPen(COLOR_REFRESH_TXT)
        p.drawText(self._refresh_rect, Qt.AlignmentFlag.AlignCenter, "Yenile")

        p.restore()

    # -----------------------------------------------------------------------
    # Event Handling
    # -----------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        try:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide_animated()
                event.accept()
                return

            if key == Qt.Key.Key_Down:
                if self._items:
                    if self._highlight_idx < 0:
                        self._highlight_idx = 0
                    else:
                        self._highlight_idx = min(len(self._items) - 1, self._highlight_idx + 1)
                    self._ensure_row_visible(self._highlight_idx)
                    self.update()
                    event.accept()
                    return

            elif key == Qt.Key.Key_Up:
                if self._items:
                    if self._highlight_idx < 0:
                        self._highlight_idx = len(self._items) - 1
                    else:
                        self._highlight_idx = max(0, self._highlight_idx - 1)
                    self._ensure_row_visible(self._highlight_idx)
                    self.update()
                    event.accept()
                    return

            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if 0 <= self._highlight_idx < len(self._items):
                    item = self._items[self._highlight_idx]
                    self.item_activated.emit(item, "left")
                    self.hide_animated()
                    event.accept()
                    return
        except Exception as exc:
            _log_err("TrayPanel.keyPressEvent", exc)

        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        try:
            if event.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                    cursor_pos = QCursor.pos()
                    if (
                        self._anchor_global is not None
                        and self._anchor_global.contains(QPointF(cursor_pos))
                    ):
                        self._last_close_time = time.monotonic()
                        self._anchor_timer.start(300)
                        super().changeEvent(event)
                        return
                    self.hide_animated()
        except Exception as exc:
            _log_err("TrayPanel.changeEvent", exc)

        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        try:
            pos = event.position()
            button = event.button()

            if button == Qt.MouseButton.LeftButton:
                # Top-right ✕ close button
                if self._close_rect.contains(pos):
                    self.hide_animated()
                    event.accept()
                    return

                # Footer Yenile button press state
                if self._refresh_rect.contains(pos):
                    self._refresh_pressed = True
                    self.update()
                    event.accept()
                    return

                # List row selection (left click closes)
                hit_idx = self._row_at_point(pos)
                if 0 <= hit_idx < len(self._items):
                    item = self._items[hit_idx]
                    self.item_activated.emit(item, "left")
                    self.hide_animated()
                    event.accept()
                    return

            elif button == Qt.MouseButton.RightButton:
                # List row selection (right click keeps open)
                hit_idx = self._row_at_point(pos)
                if 0 <= hit_idx < len(self._items):
                    item = self._items[hit_idx]
                    self.item_activated.emit(item, "right")
                    event.accept()
                    return
        except Exception as exc:
            _log_err("TrayPanel.mousePressEvent", exc)

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
            _log_err("TrayPanel.mouseReleaseEvent", exc)

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        try:
            pos = event.position()
            was_close = self._close_hovered
            was_ref = self._refresh_hovered
            old_hover = self._hover_idx

            self._close_hovered = self._close_rect.contains(pos)
            self._refresh_hovered = self._refresh_rect.contains(pos)
            self._hover_idx = self._row_at_point(pos)

            if (
                was_close != self._close_hovered
                or was_ref != self._refresh_hovered
                or old_hover != self._hover_idx
            ):
                self.update()
        except Exception as exc:
            _log_err("TrayPanel.mouseMoveEvent", exc)

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_idx = -1
        self._close_hovered = False
        self._refresh_hovered = False
        self._refresh_pressed = False
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        try:
            delta = event.angleDelta().y()
            vis_h = self._visible_list_height()
            total_h = self._total_list_height()
            max_scroll = max(0.0, total_h - vis_h)

            if max_scroll > 0.0:
                step = (delta / 120.0) * 40.0
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self._hover_idx = self._row_at_point(event.position())
                self.update()
                event.accept()
                return
        except Exception as exc:
            _log_err("TrayPanel.wheelEvent", exc)

        super().wheelEvent(event)
