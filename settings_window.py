"""settings_window.py - Settings window ('Ayarlar') for Şerit dock.

Frameless dark window adhering to Windows 11 Fluent design:
- 560 x 520 px, 12 px outer corner radius, opaque dark background
- High-DPI Segoe UI Variable typography
- Sections:
  1. 'Görünüm': Tam genişlik şerit / Ortada kapsül, Windows görev çubuğunu gizle, Ekran alanını ayır
  2. 'Kartlar': Claude, Mail, Antigravity, Sistem (işlemci/bellek halkaları), Takvim, Müzik
  3. 'Sabitlenen uygulamalar': list from settings['pinned'] with 'Kaldır' button
  4. 'Uyarılar': Uyarıları etkinleştir (alerts_enabled)
  5. 'Hakkında': Şerit dock info, git version, log file path, 'Log klasörünü aç' button
- Windows 11 Fluent styled toggles (custom painted)
- Action buttons: 'Vazgeç' (cancel) and 'Uygula' (apply)
- Esc key closes window without applying
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QWidget,
)

import theme
import winapi
from logpath import get_log_path

# ==============================================================================
# COLOR & DIMENSION CONSTANTS
# ==============================================================================

WINDOW_WIDTH: int = 560
WINDOW_HEIGHT: int = 520
CORNER_RADIUS: float = 12.0
SIDEBAR_WIDTH: float = 172.0
BOTTOM_BAR_HEIGHT: float = 54.0

# Colors (Windows 11 Dark Acrylic / Fluent Palette)
COLOR_BG: QColor = QColor(24, 25, 29)  # Fully opaque dark surface
COLOR_SIDEBAR_BG: QColor = QColor(19, 20, 24)
COLOR_BORDER: QColor = QColor(255, 255, 255, 22)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 14)

COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 245)
COLOR_TEXT_SECONDARY: QColor = QColor(255, 255, 255, 175)
COLOR_TEXT_MUTED: QColor = QColor(255, 255, 255, 110)

# Windows 11 Accent: Calm vibrant cyan-blue
COLOR_ACCENT: QColor = QColor("#0078D4")  # Standard Fluent blue
COLOR_ACCENT_HOVER: QColor = QColor("#1A86D9")
COLOR_ACCENT_PRESS: QColor = QColor("#006CBE")

COLOR_CARD_BG: QColor = QColor(255, 255, 255, 8)
COLOR_CARD_BORDER: QColor = QColor(255, 255, 255, 16)
COLOR_ROW_HOVER: QColor = QColor(255, 255, 255, 14)

# Section IDs
SECTIONS: List[Tuple[str, str]] = [
    ("appearance", "Görünüm"),
    ("cards", "Kartlar"),
    ("pinned", "Sabitlenen uygulamalar"),
    ("alerts", "Uyarılar"),
    ("about", "Hakkında"),
]

# Supported cards mapping: (key, title, subtitle)
CARD_DEFS: List[Tuple[str, str, str]] = [
    ("claude", "Claude", "Kullanım ve kota bilgisi"),
    ("mail", "Mail", "Cevap bekleyen mailler (otomatik bildirimler hariç)"),
    ("ag", "Antigravity", "Model kotaları ve durum"),
    ("sys", "Sistem halkaları", "İşlemci ve bellek kullanımı"),
    ("cal", "Takvim", "Günün etkinlikleri ve saat"),
    ("media", "Müzik", "Şu an çalan medya ve kontroller"),
]


def _get_git_version() -> str:
    """Retrieve git version or fallback."""
    try:
        app_dir = Path(__file__).resolve().parent
        res = subprocess.run(
            ["git", "-C", str(app_dir), "describe", "--always", "--tags"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        ver = res.stdout.strip()
        return ver if ver else "—"
    except Exception:
        return "—"


# ==============================================================================
# FLUENT TOGGLE WIDGET (Windows 11 Style)
# ==============================================================================


class FluentToggle(QWidget):
    """Windows 11 Fluent styled toggle switch.

    Dimensions: 40px width x 20px height capsule.
    Pill thumb: 12px circle moving from left (off) to right (on).
    No iOS glossy thumb; clean flat Fluent pill.
    """

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._checked: bool = bool(checked)
        self._hover: bool = False
        self._pressed: bool = False
        self.setFixedSize(40, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self.toggled.emit(self._checked)
            self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        r = h / 2.0  # 10.0 radius for 20px capsule

        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = theme.rounded_path(rect, r)

        # Track background
        if self._checked:
            if self._pressed:
                track_col = COLOR_ACCENT_PRESS
            elif self._hover:
                track_col = COLOR_ACCENT_HOVER
            else:
                track_col = COLOR_ACCENT
            p.fillPath(path, track_col)
            # Subtle accent border
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
            p.drawPath(path)

            # Thumb (white on accent)
            thumb_size = 12.0
            if self._pressed:
                thumb_w = 14.0  # Slight elongation when pressed
            else:
                thumb_w = 12.0
            thumb_x = w - 4.0 - thumb_w
            thumb_y = (h - thumb_size) / 2.0
            thumb_rect = QRectF(thumb_x, thumb_y, thumb_w, thumb_size)
            p.fillPath(theme.rounded_path(thumb_rect, thumb_size / 2.0), QColor(255, 255, 255))
        else:
            # Off state: dark subtle fill + stroke
            if self._pressed:
                bg_col = QColor(255, 255, 255, 24)
                border_col = QColor(255, 255, 255, 120)
            elif self._hover:
                bg_col = QColor(255, 255, 255, 16)
                border_col = QColor(255, 255, 255, 100)
            else:
                bg_col = QColor(255, 255, 255, 8)
                border_col = QColor(255, 255, 255, 75)

            p.fillPath(path, bg_col)
            p.setPen(QPen(border_col, 1.0))
            p.drawPath(path)

            # Thumb (muted white off)
            thumb_size = 10.0
            thumb_w = 12.0 if self._pressed else 10.0
            thumb_x = 4.0
            thumb_y = (h - thumb_size) / 2.0
            thumb_rect = QRectF(thumb_x, thumb_y, thumb_w, thumb_size)
            thumb_col = QColor(255, 255, 255, 200) if self._hover else QColor(255, 255, 255, 160)
            p.fillPath(theme.rounded_path(thumb_rect, thumb_size / 2.0), thumb_col)

        p.end()


# ==============================================================================
# SETTINGS WINDOW WIDGET
# ==============================================================================


class SettingsWindow(QWidget):
    """Frameless settings window for Şerit dock."""

    def __init__(
        self,
        settings: dict,
        on_apply: Callable[[dict], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._original_settings: dict = settings
        self._on_apply_cb: Callable[[dict], None] = on_apply

        # Working copy of settings
        self.working_settings: dict = copy.deepcopy(settings)
        # Ensure default structures
        if "cards" not in self.working_settings or not isinstance(self.working_settings["cards"], dict):
            self.working_settings["cards"] = {}
        if "pinned" not in self.working_settings or not isinstance(self.working_settings["pinned"], list):
            self.working_settings["pinned"] = []
        else:
            # Deepcopy list of dicts
            self.working_settings["pinned"] = [dict(p) for p in self.working_settings["pinned"] if isinstance(p, dict)]

        self.current_section: str = "appearance"

        # Interactive state
        self._hover_section: Optional[str] = None
        self._hover_btn: Optional[str] = None
        self._hover_item_key: Optional[str] = None

        # Hit testing records for content area
        # (rect, kind, extra)
        self._content_hit_boxes: List[Tuple[QRectF, str, Any]] = []

        # Pinned list scroll offset
        self._scroll_offset_y: float = 0.0

        # Pre-cache git version
        self._git_ver = _get_git_version()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def switch_section(self, section_id: str) -> None:
        """Switch active section in sidebar."""
        valid_ids = [s[0] for s in SECTIONS]
        if section_id in valid_ids and self.current_section != section_id:
            self.current_section = section_id
            self._scroll_offset_y = 0.0
            self.update()

    def apply_and_close(self) -> None:
        """Invoke on_apply callback with deep-copied new settings and close."""
        cfg_out = copy.deepcopy(self.working_settings)
        if callable(self._on_apply_cb):
            self._on_apply_cb(cfg_out)
        self.close()

    def cancel_and_close(self) -> None:
        """Close window without invoking callback."""
        self.close()

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_and_close()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = QPointF(event.position())

        # Check Close button (top right 'X')
        close_rect = QRectF(float(self.width()) - 36.0, 10.0, 26.0, 26.0)
        if close_rect.contains(pos):
            self.cancel_and_close()
            return

        # Check Bottom buttons (Vazgeç / Uygula)
        btn_apply = self._get_apply_button_rect()
        btn_cancel = self._get_cancel_button_rect()
        if btn_apply.contains(pos):
            self.apply_and_close()
            return
        if btn_cancel.contains(pos):
            self.cancel_and_close()
            return

        # Check Sidebar section click
        for s_rect, sid, _ in self._get_sidebar_items():
            if s_rect.contains(pos):
                self.switch_section(sid)
                return

        # Check Content hit boxes
        for r, kind, extra in self._content_hit_boxes:
            if r.contains(pos):
                if kind == "toggle_style":
                    # extra is 'band' or 'pill'
                    self.working_settings["style"] = str(extra)
                    self.update()
                    return
                elif kind == "toggle_setting":
                    # extra is key name (e.g. 'hide_taskbar', 'reserve_space', 'alerts_enabled')
                    cur_val = bool(self.working_settings.get(extra, False))
                    self.working_settings[extra] = not cur_val
                    self.update()
                    return
                elif kind == "toggle_card":
                    # extra is card key
                    cards = self.working_settings.setdefault("cards", {})
                    # default fallback depends on card key
                    cur = bool(cards.get(extra, True)) if extra != "sys" else bool(cards.get("sys", False))
                    cards[extra] = not cur
                    self.update()
                    return
                elif kind == "remove_pin":
                    # extra is index in pinned list
                    pins = self.working_settings.get("pinned", [])
                    if 0 <= extra < len(pins):
                        del pins[extra]
                        self.update()
                    return
                elif kind == "open_logs":
                    self._on_open_logs_clicked()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = QPointF(event.position())

        prev_hover_sec = self._hover_section
        prev_hover_btn = self._hover_btn
        prev_hover_item = self._hover_item_key

        self._hover_section = None
        self._hover_btn = None
        self._hover_item_key = None

        # Check Close button
        close_rect = QRectF(float(self.width()) - 36.0, 10.0, 26.0, 26.0)
        if close_rect.contains(pos):
            self._hover_btn = "close"

        # Sidebar
        for s_rect, sid, _ in self._get_sidebar_items():
            if s_rect.contains(pos):
                self._hover_section = sid
                break

        # Bottom buttons
        if self._get_apply_button_rect().contains(pos):
            self._hover_btn = "apply"
        elif self._get_cancel_button_rect().contains(pos):
            self._hover_btn = "cancel"

        # Content hit boxes
        for r, kind, extra in self._content_hit_boxes:
            if r.contains(pos):
                self._hover_item_key = f"{kind}:{extra}"
                break

        if (
            self._hover_section != prev_hover_sec
            or self._hover_btn != prev_hover_btn
            or self._hover_item_key != prev_hover_item
        ):
            self.update()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_section = None
        self._hover_btn = None
        self._hover_item_key = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Only pinned section has scrolling
        if self.current_section == "pinned":
            delta = event.angleDelta().y()
            self._scroll_offset_y = min(0.0, self._scroll_offset_y + delta * 0.4)
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def _on_open_logs_clicked(self) -> None:
        """Open log folder with explorer. Uses os.startfile ONLY when clicked by user."""
        try:
            log_p = get_log_path()
            folder = log_p.parent
            if folder.exists():
                os.startfile(str(folder))
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Layout & Geometry Helpers
    # -------------------------------------------------------------------------

    def _get_sidebar_items(self) -> List[Tuple[QRectF, str, str]]:
        items = []
        top_y = 60.0
        row_h = 36.0
        gap = 4.0
        for i, (sid, title) in enumerate(SECTIONS):
            y = top_y + i * (row_h + gap)
            rect = QRectF(12.0, y, SIDEBAR_WIDTH - 24.0, row_h)
            items.append((rect, sid, title))
        return items

    def _get_apply_button_rect(self) -> QRectF:
        btn_w = 88.0
        btn_h = 32.0
        x = float(self.width()) - 20.0 - btn_w
        y = float(self.height()) - 16.0 - btn_h
        return QRectF(x, y, btn_w, btn_h)

    def _get_cancel_button_rect(self) -> QRectF:
        btn_w = 88.0
        btn_h = 32.0
        x = float(self.width()) - 20.0 - btn_w - 10.0 - btn_w
        y = float(self.height()) - 16.0 - btn_h
        return QRectF(x, y, btn_w, btn_h)

    # -------------------------------------------------------------------------
    # Offscreen Rendering for Tests / Showcase
    # -------------------------------------------------------------------------

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render entire window offscreen to high-DPI QImage."""
        w_phys = max(1, int(round(float(self.width()) * dpr)))
        h_phys = max(1, int(round(float(self.height()) * dpr)))
        img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self._paint_all(p)
        p.end()
        return img

    # -------------------------------------------------------------------------
    # Painting Implementation
    # -------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._paint_all(p)
        p.end()

    def _paint_all(self, p: QPainter) -> None:
        self._content_hit_boxes.clear()

        w = float(self.width())
        h = float(self.height())
        outer_rect = QRectF(0.0, 0.0, w, h)
        outer_path = theme.rounded_path(outer_rect, CORNER_RADIUS)

        # 1. Base window background (fully opaque dark surface)
        p.fillPath(outer_path, COLOR_BG)

        # 2. Sidebar background
        p.save()
        p.setClipPath(outer_path)
        sidebar_rect = QRectF(0.0, 0.0, SIDEBAR_WIDTH, h)
        p.fillRect(sidebar_rect, COLOR_SIDEBAR_BG)

        # Hairline separator between sidebar and content
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(SIDEBAR_WIDTH, 0.0), QPointF(SIDEBAR_WIDTH, h - BOTTOM_BAR_HEIGHT))

        # Bottom bar hairline
        p.drawLine(QPointF(0.0, h - BOTTOM_BAR_HEIGHT), QPointF(w, h - BOTTOM_BAR_HEIGHT))
        p.restore()

        # 3. Outer border
        p.setPen(QPen(COLOR_BORDER, 1.0))
        p.drawPath(outer_path)

        # 4. Window Title / App brand in top-left sidebar
        p.setFont(theme.make_font(13.0, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(16.0, 18.0, SIDEBAR_WIDTH - 32.0, 24.0), Qt.AlignmentFlag.AlignVCenter, "Ayarlar")

        # Close 'X' button in top-right
        close_rect = QRectF(w - 34.0, 10.0, 24.0, 24.0)
        is_close_hover = (self._hover_btn == "close")
        if is_close_hover:
            p.fillPath(theme.rounded_path(close_rect, 6.0), QColor(255, 255, 255, 20))
        p.setFont(theme.make_font(11.0, QFont.Weight.Normal))
        p.setPen(COLOR_TEXT_PRIMARY if is_close_hover else COLOR_TEXT_MUTED)
        p.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "✕")

        # 5. Sidebar Navigation Items
        self._paint_sidebar(p)

        # 6. Main Content Area
        content_rect = QRectF(
            SIDEBAR_WIDTH + 24.0,
            24.0,
            w - SIDEBAR_WIDTH - 48.0,
            h - BOTTOM_BAR_HEIGHT - 36.0,
        )
        p.save()
        p.setClipRect(content_rect)
        self._paint_content(p, content_rect)
        p.restore()

        # 7. Bottom Bar Buttons (Vazgeç & Uygula)
        self._paint_bottom_bar(p)

    def _paint_sidebar(self, p: QPainter) -> None:
        for rect, sid, title in self._get_sidebar_items():
            is_active = (self.current_section == sid)
            is_hover = (self._hover_section == sid)

            if is_active:
                p.fillPath(theme.rounded_path(rect, 6.0), QColor(255, 255, 255, 18))
                # Active pill accent indicator on left
                ind_rect = QRectF(rect.x() - 6.0, rect.y() + 9.0, 3.0, 18.0)
                p.fillPath(theme.rounded_path(ind_rect, 1.5), COLOR_ACCENT)
            elif is_hover:
                p.fillPath(theme.rounded_path(rect, 6.0), COLOR_ROW_HOVER)

            p.setFont(theme.make_font(11.0, QFont.Weight.Medium if is_active else QFont.Weight.Normal))
            if is_active:
                p.setPen(COLOR_TEXT_PRIMARY)
            elif is_hover:
                p.setPen(COLOR_TEXT_PRIMARY)
            else:
                p.setPen(COLOR_TEXT_SECONDARY)

            text_rect = QRectF(rect.x() + 8.0, rect.y(), rect.width() - 14.0, rect.height())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

    def _paint_bottom_bar(self, p: QPainter) -> None:
        h = float(self.height())

        # Subtle info text on bottom-left
        p.setFont(theme.make_font(10.0, QFont.Weight.Normal))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(
            QRectF(20.0, h - BOTTOM_BAR_HEIGHT, SIDEBAR_WIDTH + 80.0, BOTTOM_BAR_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Şerit",
        )

        # Cancel Button ('Vazgeç')
        r_cancel = self._get_cancel_button_rect()
        is_cancel_hover = (self._hover_btn == "cancel")
        bg_cancel = QColor(255, 255, 255, 22) if is_cancel_hover else QColor(255, 255, 255, 12)
        p.fillPath(theme.rounded_path(r_cancel, 6.0), bg_cancel)
        p.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        p.drawPath(theme.rounded_path(r_cancel, 6.0))

        p.setFont(theme.make_font(11.0, QFont.Weight.Medium))
        p.setPen(COLOR_TEXT_PRIMARY if is_cancel_hover else COLOR_TEXT_SECONDARY)
        p.drawText(r_cancel, Qt.AlignmentFlag.AlignCenter, "Vazgeç")

        # Apply Button ('Uygula')
        r_apply = self._get_apply_button_rect()
        is_apply_hover = (self._hover_btn == "apply")
        bg_apply = COLOR_ACCENT_HOVER if is_apply_hover else COLOR_ACCENT
        p.fillPath(theme.rounded_path(r_apply, 6.0), bg_apply)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
        p.drawPath(theme.rounded_path(r_apply, 6.0))

        p.setFont(theme.make_font(11.0, QFont.Weight.DemiBold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(r_apply, Qt.AlignmentFlag.AlignCenter, "Uygula")

    # -------------------------------------------------------------------------
    # Section Content Painting
    # -------------------------------------------------------------------------

    def _paint_content(self, p: QPainter, area: QRectF) -> None:
        title_rect = QRectF(area.x(), area.y(), area.width(), 28.0)
        p.setFont(theme.make_font(16.0, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_PRIMARY)

        sec_title = dict(SECTIONS).get(self.current_section, "")
        p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sec_title)

        start_y = area.y() + 38.0
        avail_w = area.width()

        if self.current_section == "appearance":
            self._paint_appearance_section(p, area.x(), start_y, avail_w)
        elif self.current_section == "cards":
            self._paint_cards_section(p, area.x(), start_y, avail_w)
        elif self.current_section == "pinned":
            self._paint_pinned_section(p, area.x(), start_y, avail_w, area.height() - 38.0)
        elif self.current_section == "alerts":
            self._paint_alerts_section(p, area.x(), start_y, avail_w)
        elif self.current_section == "about":
            self._paint_about_section(p, area.x(), start_y, avail_w)

    def _paint_fluent_toggle_at(self, p: QPainter, rect: QRectF, checked: bool, hovered: bool) -> None:
        """Custom-paint Windows 11 Fluent style toggle inside content rows."""
        w = rect.width()
        h = rect.height()
        r = h / 2.0
        path = theme.rounded_path(rect, r)

        if checked:
            track_col = COLOR_ACCENT_HOVER if hovered else COLOR_ACCENT
            p.fillPath(path, track_col)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
            p.drawPath(path)

            thumb_size = 12.0
            thumb_x = rect.x() + w - 4.0 - thumb_size
            thumb_y = rect.y() + (h - thumb_size) / 2.0
            thumb_rect = QRectF(thumb_x, thumb_y, thumb_size, thumb_size)
            p.fillPath(theme.rounded_path(thumb_rect, thumb_size / 2.0), QColor(255, 255, 255))
        else:
            bg_col = QColor(255, 255, 255, 14) if hovered else QColor(255, 255, 255, 8)
            border_col = QColor(255, 255, 255, 90) if hovered else QColor(255, 255, 255, 70)
            p.fillPath(path, bg_col)
            p.setPen(QPen(border_col, 1.0))
            p.drawPath(path)

            thumb_size = 10.0
            thumb_x = rect.x() + 4.0
            thumb_y = rect.y() + (h - thumb_size) / 2.0
            thumb_rect = QRectF(thumb_x, thumb_y, thumb_size, thumb_size)
            thumb_col = QColor(255, 255, 255, 210) if hovered else QColor(255, 255, 255, 160)
            p.fillPath(theme.rounded_path(thumb_rect, thumb_size / 2.0), thumb_col)

    def _paint_card_row(
        self,
        p: QPainter,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        subtitle: Optional[str] = None,
        checked: Optional[bool] = None,
        action_text: Optional[str] = None,
        hit_kind: Optional[str] = None,
        hit_extra: Any = None,
        is_radio: bool = False,
    ) -> QRectF:
        card_rect = QRectF(x, y, w, h)
        key_str = f"{hit_kind}:{hit_extra}" if hit_kind else ""
        is_hover = (self._hover_item_key == key_str)

        # Card container background
        bg_col = QColor(255, 255, 255, 12) if is_hover else COLOR_CARD_BG
        p.fillPath(theme.rounded_path(card_rect, 8.0), bg_col)
        p.setPen(QPen(COLOR_CARD_BORDER, 1.0))
        p.drawPath(theme.rounded_path(card_rect, 8.0))

        # Title & Subtitle
        text_x = x + 14.0
        text_w = w - (58.0 if (checked is not None or is_radio) else (78.0 if action_text else 24.0))
        if subtitle:
            p.setFont(theme.make_font(11.5, QFont.Weight.Medium))
            p.setPen(COLOR_TEXT_PRIMARY)
            p.drawText(QRectF(text_x, y + 8.0, text_w, 20.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

            f_sub = theme.make_font(9.5, QFont.Weight.Normal)
            p.setFont(f_sub)
            fm_sub = QFontMetricsF(f_sub)
            elided_sub = fm_sub.elidedText(subtitle, Qt.TextElideMode.ElideRight, text_w)
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(QRectF(text_x, y + 26.0, text_w, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)
        else:
            p.setFont(theme.make_font(11.5, QFont.Weight.Medium))
            p.setPen(COLOR_TEXT_PRIMARY)
            p.drawText(QRectF(text_x, y, text_w, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Right control: Toggle or Radio or Action Button
        if is_radio and checked is not None:
            r_radio = QRectF(x + w - 34.0, y + (h - 18.0) / 2.0, 18.0, 18.0)
            p.setPen(QPen(COLOR_ACCENT if checked else QColor(255, 255, 255, 90), 1.5))
            p.drawEllipse(r_radio)
            if checked:
                p.fillPath(theme.rounded_path(QRectF(r_radio.x() + 4.5, r_radio.y() + 4.5, 9.0, 9.0), 4.5), COLOR_ACCENT)
        elif checked is not None:
            toggle_rect = QRectF(x + w - 52.0, y + (h - 20.0) / 2.0, 40.0, 20.0)
            self._paint_fluent_toggle_at(p, toggle_rect, checked, is_hover)
        elif action_text:
            btn_w = 64.0
            btn_h = 26.0
            btn_rect = QRectF(x + w - btn_w - 12.0, y + (h - btn_h) / 2.0, btn_w, btn_h)
            btn_bg = QColor(230, 80, 80, 36) if is_hover else QColor(255, 255, 255, 10)
            p.fillPath(theme.rounded_path(btn_rect, 5.0), btn_bg)
            p.setPen(QPen(QColor(230, 80, 80, 120) if is_hover else QColor(255, 255, 255, 20), 1.0))
            p.drawPath(theme.rounded_path(btn_rect, 5.0))

            p.setFont(theme.make_font(10.5, QFont.Weight.Medium))
            p.setPen(QColor("#FF7B7B") if is_hover else COLOR_TEXT_SECONDARY)
            p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, action_text)

        if hit_kind:
            self._content_hit_boxes.append((card_rect, hit_kind, hit_extra))

        return card_rect

    # -------------------------------------------------------------------------
    # Section: Görünüm (Appearance)
    # -------------------------------------------------------------------------

    def _paint_appearance_section(self, p: QPainter, x: float, y: float, w: float) -> None:
        cur_style = str(self.working_settings.get("style", "band"))
        is_band = (cur_style != "pill")

        # Section 1: Dock Style (Tam genişlik şerit vs Ortada kapsül)
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x, y, w, 18.0), Qt.AlignmentFlag.AlignLeft, "ŞERİT DÜZENİ")
        y += 24.0

        row_h = 44.0
        gap = 8.0
        self._paint_card_row(
            p, x, y, w, row_h,
            title="Tam genişlik şerit",
            subtitle="Ekranın solundan sağına uzanan koyu taban şeridi",
            checked=is_band,
            hit_kind="toggle_style",
            hit_extra="band",
            is_radio=True,
        )
        y += row_h + gap

        self._paint_card_row(
            p, x, y, w, row_h,
            title="Ortada kapsül",
            subtitle="Yalnızca öğelerin etrafını saran yüzen kapsül",
            checked=(not is_band),
            hit_kind="toggle_style",
            hit_extra="pill",
            is_radio=True,
        )
        y += row_h + 18.0

        # Section 2: Windows Entegrasyonu
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x, y, w, 18.0), Qt.AlignmentFlag.AlignLeft, "WINDOWS ENTEGRASYONU")
        y += 24.0

        hide_tb = bool(self.working_settings.get("hide_taskbar", False))
        self._paint_card_row(
            p, x, y, w, row_h,
            title="Görev çubuğunu gizle",
            subtitle="Windows görev çubuğunu otomatik gizle",
            checked=hide_tb,
            hit_kind="toggle_setting",
            hit_extra="hide_taskbar",
        )
        y += row_h + gap

        reserve_sp = bool(self.working_settings.get("reserve_space", True))
        self._paint_card_row(
            p, x, y, w, row_h,
            title="Ekran alanını ayır",
            subtitle="Pencerelerin şerit altına girmesini engelle (AppBar)",
            checked=reserve_sp,
            hit_kind="toggle_setting",
            hit_extra="reserve_space",
        )

    # -------------------------------------------------------------------------
    # Section: Kartlar (Cards)
    # -------------------------------------------------------------------------

    def _paint_cards_section(self, p: QPainter, x: float, y: float, w: float) -> None:
        cards_cfg = dict(self.working_settings.get("cards") or {})

        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x, y, w, 18.0), Qt.AlignmentFlag.AlignLeft, "GÖSTERİLECEK KARTLAR")
        y += 24.0

        row_h = 44.0
        gap = 6.0

        for key, title, subtitle in CARD_DEFS:
            # Check default behavior: sys defaults to False if omitted, others True
            if key == "sys":
                checked = bool(cards_cfg.get(key, False))
            else:
                checked = bool(cards_cfg.get(key, True))

            self._paint_card_row(
                p, x, y, w, row_h,
                title=title,
                subtitle=subtitle,
                checked=checked,
                hit_kind="toggle_card",
                hit_extra=key,
            )
            y += row_h + gap

    # -------------------------------------------------------------------------
    # Section: Sabitlenen uygulamalar (Pinned apps)
    # -------------------------------------------------------------------------

    def _paint_pinned_section(self, p: QPainter, x: float, y: float, w: float, max_h: float) -> None:
        pinned_list: List[dict] = self.working_settings.get("pinned", [])

        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(
            QRectF(x, y, w, 18.0),
            Qt.AlignmentFlag.AlignLeft,
            f"SABİTLENENLER ({len(pinned_list)})",
        )
        y += 24.0

        if not pinned_list:
            empty_rect = QRectF(x, y, w, 100.0)
            p.setFont(theme.make_font(11.0, QFont.Weight.Normal))
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(empty_rect, Qt.AlignmentFlag.AlignCenter, "Henüz sabitlenmiş bir uygulama yok.")
            return

        row_h = 42.0
        gap = 6.0
        clip_rect = QRectF(x, y, w, max_h - 24.0)
        p.save()
        p.setClipRect(clip_rect)

        cur_y = y + self._scroll_offset_y
        for idx, item in enumerate(pinned_list):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "Uygulama")
            exe = str(item.get("path") or "")

            # Only draw visible rows
            if cur_y + row_h >= clip_rect.top() and cur_y <= clip_rect.bottom():
                r_row = QRectF(x, cur_y, w, row_h)
                key_str = f"remove_pin:{idx}"
                is_hover = (self._hover_item_key == key_str)

                # Row background
                bg_col = QColor(255, 255, 255, 12) if is_hover else COLOR_CARD_BG
                p.fillPath(theme.rounded_path(r_row, 6.0), bg_col)
                p.setPen(QPen(COLOR_CARD_BORDER, 1.0))
                p.drawPath(theme.rounded_path(r_row, 6.0))

                # App Icon
                icon_rect = QRectF(x + 10.0, cur_y + (row_h - 24.0) / 2.0, 24.0, 24.0)
                try:
                    pix = winapi.app_icon(exe, 32) if exe else QPixmap()
                    if pix and not pix.isNull():
                        theme.draw_icon_crisp(p, pix, icon_rect)
                    else:
                        # Fallback initial circle
                        p.fillPath(theme.rounded_path(icon_rect, 4.0), QColor(255, 255, 255, 18))
                        p.setFont(theme.make_font(10.0, QFont.Weight.Bold))
                        p.setPen(COLOR_TEXT_PRIMARY)
                        p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, name[:1].upper())
                except Exception:
                    pass

                # Name and path
                text_rect = QRectF(x + 42.0, cur_y, w - 120.0, row_h)
                p.setFont(theme.make_font(11.0, QFont.Weight.Medium))
                p.setPen(COLOR_TEXT_PRIMARY)
                p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)

                # 'Kaldır' button
                btn_w = 58.0
                btn_h = 24.0
                btn_rect = QRectF(x + w - btn_w - 10.0, cur_y + (row_h - btn_h) / 2.0, btn_w, btn_h)
                btn_bg = QColor(230, 80, 80, 36) if is_hover else QColor(255, 255, 255, 10)
                p.fillPath(theme.rounded_path(btn_rect, 4.0), btn_bg)
                p.setPen(QPen(QColor(230, 80, 80, 110) if is_hover else QColor(255, 255, 255, 20), 1.0))
                p.drawPath(theme.rounded_path(btn_rect, 4.0))

                p.setFont(theme.make_font(10.0, QFont.Weight.Medium))
                p.setPen(QColor("#FF7B7B") if is_hover else COLOR_TEXT_SECONDARY)
                p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "Kaldır")

                # Register hit box
                self._content_hit_boxes.append((btn_rect, "remove_pin", idx))

            cur_y += row_h + gap

        p.restore()

    # -------------------------------------------------------------------------
    # Section: Uyarılar (Alerts)
    # -------------------------------------------------------------------------

    def _paint_alerts_section(self, p: QPainter, x: float, y: float, w: float) -> None:
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x, y, w, 18.0), Qt.AlignmentFlag.AlignLeft, "SİSTEM VE KULLANIM BİLDİRİMLERİ")
        y += 24.0

        alerts_enabled = bool(self.working_settings.get("alerts_enabled", True))
        row_h = 50.0
        self._paint_card_row(
            p, x, y, w, row_h,
            title="Uyarıları etkinleştir",
            subtitle="Yüksek kaynak kullanımı ve kota bildirimlerini ekranda belirt",
            checked=alerts_enabled,
            hit_kind="toggle_setting",
            hit_extra="alerts_enabled",
        )

    # -------------------------------------------------------------------------
    # Section: Hakkında (About)
    # -------------------------------------------------------------------------

    def _paint_about_section(self, p: QPainter, x: float, y: float, w: float) -> None:
        p.setFont(theme.make_font(10.5, QFont.Weight.DemiBold))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x, y, w, 18.0), Qt.AlignmentFlag.AlignLeft, "UYGULAMA BİLGİSİ")
        y += 24.0

        # Info card
        info_rect = QRectF(x, y, w, 140.0)
        p.fillPath(theme.rounded_path(info_rect, 8.0), COLOR_CARD_BG)
        p.setPen(QPen(COLOR_CARD_BORDER, 1.0))
        p.drawPath(theme.rounded_path(info_rect, 8.0))

        # Title
        p.setFont(theme.make_font(14.0, QFont.Weight.Bold))
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(x + 16.0, y + 14.0, w - 32.0, 22.0), Qt.AlignmentFlag.AlignLeft, "Şerit Dock")

        p.setFont(theme.make_font(10.5, QFont.Weight.Normal))
        p.setPen(COLOR_TEXT_SECONDARY)
        p.drawText(
            QRectF(x + 16.0, y + 38.0, w - 32.0, 18.0),
            Qt.AlignmentFlag.AlignLeft,
            "Windows 11 için modern akrilik görev çubuğu ve bilgi şeridi",
        )

        # Hairline divider inside card
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(x + 16.0, y + 64.0), QPointF(x + w - 16.0, y + 64.0))

        # Version & Commit
        p.setFont(theme.make_font(10.5, QFont.Weight.Medium))
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x + 16.0, y + 74.0, 80.0, 20.0), Qt.AlignmentFlag.AlignLeft, "Sürüm:")
        p.setPen(COLOR_TEXT_PRIMARY)
        p.drawText(QRectF(x + 90.0, y + 74.0, w - 106.0, 20.0), Qt.AlignmentFlag.AlignLeft, self._git_ver)

        # Log Path
        log_file = get_log_path()
        p.setPen(COLOR_TEXT_MUTED)
        p.drawText(QRectF(x + 16.0, y + 98.0, 80.0, 20.0), Qt.AlignmentFlag.AlignLeft, "Günlük:")

        log_str = str(log_file)
        f_log = theme.make_font(9.0, QFont.Weight.Normal)
        p.setFont(f_log)
        fm_log = QFontMetricsF(f_log)
        avail_log_w = w - 106.0
        elided_log = fm_log.elidedText(log_str, Qt.TextElideMode.ElideMiddle, avail_log_w)

        p.setPen(COLOR_TEXT_SECONDARY)
        p.drawText(
            QRectF(x + 90.0, y + 98.0, avail_log_w, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_log,
        )

        y += 140.0 + 16.0

        # Button: 'Log klasörünü aç'
        btn_w = 150.0
        btn_h = 32.0
        btn_rect = QRectF(x, y, btn_w, btn_h)
        is_hover = (self._hover_item_key == "open_logs:btn")

        btn_bg = QColor(255, 255, 255, 18) if is_hover else QColor(255, 255, 255, 10)
        p.fillPath(theme.rounded_path(btn_rect, 6.0), btn_bg)
        p.setPen(QPen(QColor(255, 255, 255, 28) if is_hover else QColor(255, 255, 255, 18), 1.0))
        p.drawPath(theme.rounded_path(btn_rect, 6.0))

        p.setFont(theme.make_font(10.5, QFont.Weight.Medium))
        p.setPen(COLOR_TEXT_PRIMARY if is_hover else COLOR_TEXT_SECONDARY)
        p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "Log klasörünü aç")

        self._content_hit_boxes.append((btn_rect, "open_logs", "btn"))


# ==============================================================================
# ENTRY POINT FUNCTION
# ==============================================================================


def open_settings(
    settings: dict,
    on_apply: Callable[[dict], None],
    parent: Optional[QWidget] = None,
) -> SettingsWindow:
    """Instantiate and return the SettingsWindow without writing to disk."""
    win = SettingsWindow(settings=settings, on_apply=on_apply, parent=parent)
    win.show()
    return win
