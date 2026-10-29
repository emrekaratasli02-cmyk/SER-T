"""action_menu.py - Modern obsidian acrylic action menu widget for Şerit dock.

How the dock will use it:
-------------------------
On right-click of a tray icon (band icon or a row of the Bildirim Alanı panel):
    menu = ActionMenu()
    menu.set_header(
        title=clean_tray_name(item),
        subtitle=res['label'] if res['ok'] else res['reason'],
        icon=extracted_pixmap,
    )
    menu.set_actions([
        {'id': 'open', 'text': 'Aç', 'icon': 'open'},
        {
            'id': 'end',
            'text': 'Görevi sonlandır',
            'icon': 'stop',
            'danger': True,
            'confirm': True,
            'enabled': res['ok'],
            'hint': res['reason'] or '',
        },
    ])
    menu.action_chosen.connect(lambda act_id: on_action(item, act_id))
    menu.show_at(anchor_rect)

Features:
- Frameless, translucent obsidian acrylic glass (COLOR_BG) with specular sheen.
- 160-180 ms OutCubic slide-fade animation.
- Arm-to-confirm mechanism with 3-second auto-timeout and mouse-leave reset.
- Crisp vector line glyphs ('open', 'stop', 'settings') with no emoji or low-res art.
- Full keyboard navigation (Up, Down, Enter/Space, Esc).
- High-DPI support with offscreen rendering at arbitrary DPR.
"""

from __future__ import annotations

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
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

# Safe imports for Serit environment
try:
    from sources import log_err
except ImportError:
    def log_err(source: str, exc: Exception) -> None:
        pass

try:
    import winapi
except ImportError:
    winapi = None


# ---------------------------------------------------------------------------
# Visual Tokens
# ---------------------------------------------------------------------------

WIDTH: int = 240
CORNER_RADIUS: float = 13.0

COLOR_BG: QColor = QColor(20, 21, 25, 248)
COLOR_BORDER: QColor = QColor(255, 255, 255, 20)
COLOR_HAIRLINE: QColor = QColor(255, 255, 255, 22)
COLOR_TEXT_PRIMARY: QColor = QColor(255, 255, 255, 255)
COLOR_TEXT_SECONDARY: QColor = QColor(225, 228, 235, 240)
COLOR_TEXT_MUTED: QColor = QColor(148, 154, 166, 220)
COLOR_TEXT_DISABLED: QColor = QColor(255, 255, 255, 75)

COLOR_ROW_HOVER: QColor = QColor(255, 255, 255, 18)  # ~rgba(255, 255, 255, 0.07)
COLOR_DANGER: QColor = QColor("#FF453A")
COLOR_DANGER_ARMED_BG: QColor = QColor(255, 69, 58, 42)


def make_font(
    size_px: float,
    weight: QFont.Weight = QFont.Weight.Normal,
) -> QFont:
    """Create a high-DPI Segoe UI Variable font instance."""
    f = QFont("Segoe UI Variable Text")
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    f.setPixelSize(int(round(size_px)))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Construct a rounded rectangle QPainterPath."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def draw_line_glyph(
    p: QPainter,
    glyph: str,
    rect: QRectF,
    color: QColor,
    pen_width: float = 1.35,
) -> None:
    """Draw a minimalist crisp vector glyph."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx = rect.center().x()
    cy = rect.center().y()

    if glyph == "open":
        # Box with top-right open + outgoing arrow
        bx = cx - 5.5
        by = cy - 2.5
        bw = 8.0
        bh = 8.0
        box_path = QPainterPath()
        box_path.moveTo(bx + 4.0, by)
        box_path.lineTo(bx, by)
        box_path.lineTo(bx, by + bh)
        box_path.lineTo(bx + bw, by + bh)
        box_path.lineTo(bx + bw, by + 4.0)
        p.drawPath(box_path)

        # Arrow shaft and head
        ax1 = cx - 1.0
        ay1 = cy + 1.0
        ax2 = cx + 5.5
        ay2 = cy - 5.5
        p.drawLine(QPointF(ax1, ay1), QPointF(ax2, ay2))
        p.drawLine(QPointF(ax2 - 3.5, ay2), QPointF(ax2, ay2))
        p.drawLine(QPointF(ax2, ay2 + 3.5), QPointF(ax2, ay2))

    elif glyph == "stop":
        # Octagonal or rounded square stop symbol
        size = 11.0
        sq_rect = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)
        sq_path = QPainterPath()
        sq_path.addRoundedRect(sq_rect, 2.5, 2.5)
        p.drawPath(sq_path)
        # Inner 'x' or cross
        offset = 2.4
        p.drawLine(QPointF(cx - offset, cy - offset), QPointF(cx + offset, cy + offset))
        p.drawLine(QPointF(cx - offset, cy + offset), QPointF(cx + offset, cy - offset))

    elif glyph == "settings":
        # Two clean horizontal slider lines with adjustment pips
        y1 = cy - 3.0
        y2 = cy + 3.0
        p.drawLine(QPointF(cx - 6.0, y1), QPointF(cx + 6.0, y1))
        p.drawLine(QPointF(cx - 6.0, y2), QPointF(cx + 6.0, y2))
        # Pip 1
        p.drawLine(QPointF(cx - 2.0, y1 - 2.0), QPointF(cx - 2.0, y1 + 2.0))
        # Pip 2
        p.drawLine(QPointF(cx + 2.0, y2 - 2.0), QPointF(cx + 2.0, y2 + 2.0))

    p.restore()


# ---------------------------------------------------------------------------
# ActionMenu Widget
# ---------------------------------------------------------------------------

class ActionMenu(QWidget):
    """Modern obsidian flyout action menu for Şerit dock."""

    WIDTH: int = WIDTH
    RADIUS: float = CORNER_RADIUS

    ROW_HEIGHT: float = 32.0
    ROW_GAP: float = 2.0
    ROW_RADIUS: float = 8.0
    PADDING_HORIZ: float = 8.0
    PADDING_VERT: float = 8.0
    HEADER_HEIGHT: float = 40.0
    DIVIDER_HEIGHT: float = 9.0  # 4px gap + 1px hairline + 4px gap
    SEPARATOR_HEIGHT: float = 9.0
    TITLE_HEIGHT: float = 22.0

    action_chosen = Signal(str)

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

        # Header state
        self._title: str = ""
        self._subtitle: str = ""
        self._header_icon: Optional[QPixmap] = None

        # Actions list
        self._actions: List[Dict[str, Any]] = []

        # Interactive states & scrolling
        self._hover_idx: int = -1
        self._scroll_y: float = 0.0
        self._armed_action_id: Optional[str] = None
        self._anchor_global: Optional[QRectF] = None

        # Arm timer (3-second auto-timeout)
        self._arm_timer = QTimer(self)
        self._arm_timer.setSingleShot(True)
        self._arm_timer.timeout.connect(self._on_arm_timeout)

        # Lifecycle & Animation
        self._is_closing: bool = False
        self._anim_progress: float = 1.0
        self._anim_opacity: float = 1.0
        self._anim_offset_y: float = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # Typography
        self.f_title = make_font(12.5, QFont.Weight.DemiBold)
        self.f_sub = make_font(10.5, QFont.Weight.Normal)
        self.f_row = make_font(12.0, QFont.Weight.Medium)
        self.f_hint = make_font(10.5, QFont.Weight.Normal)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def set_header(
        self,
        title: str,
        subtitle: str = "",
        icon: Optional[QPixmap] = None,
    ) -> None:
        """Configure menu header."""
        self._title = str(title or "").strip()
        self._subtitle = str(subtitle or "").strip()
        self._header_icon = icon
        self.updateGeometry()
        self.update()

    def set_actions(self, actions: List[Dict[str, Any]]) -> None:
        """Configure list of action items, separators, and section titles.

        Each item dict can be:
            1. An action row:
                id: str
                text: str
                icon: 'open' | 'stop' | 'settings' | None
                danger: bool (default False)
                enabled: bool (default True)
                hint: str (default '')
                shortcut: str (sağda soluk kısayol ipucu, örn. 'Orta tık')
                confirm: bool (default False)
                checked: bool (draws a check mark on the right, default False)
                group: str (radio style; draw a filled dot for selected one)
                callback: callable (invoked on action trigger)
            2. A separator row:
                type: 'separator'
            3. A section title:
                type: 'title'
                text: str
        """
        clean_actions: List[Dict[str, Any]] = []
        if isinstance(actions, list):
            for a in actions:
                if not isinstance(a, dict):
                    continue
                row_type = a.get("type")
                if row_type == "separator":
                    clean_actions.append({"type": "separator"})
                elif row_type == "title":
                    clean_actions.append({
                        "type": "title",
                        "text": str(a.get("text") or "").strip(),
                    })
                else:
                    item_dict: Dict[str, Any] = {
                        "type": "action",
                        "id": str(a.get("id") or ""),
                        "text": str(a.get("text") or ""),
                        "icon": a.get("icon"),
                        "danger": bool(a.get("danger", False)),
                        "enabled": bool(a.get("enabled", True)),
                        "hint": str(a.get("hint") or ""),
                        "confirm": bool(a.get("confirm", False)),
                        "checked": bool(a.get("checked", False)),
                        "shortcut": str(a.get("shortcut") or ""),
                    }
                    if "group" in a and a["group"] is not None:
                        item_dict["group"] = str(a["group"])
                    if "callback" in a and callable(a["callback"]):
                        item_dict["callback"] = a["callback"]
                    clean_actions.append(item_dict)
        self._actions = clean_actions
        self._hover_idx = -1
        self._scroll_y = 0.0
        self._disarm()
        self.updateGeometry()
        self.update()

    def _row_height(self, action: Dict[str, Any]) -> float:
        t = action.get("type", "action")
        if t == "separator":
            return self.SEPARATOR_HEIGHT
        if t == "title":
            return self.TITLE_HEIGHT
        return self.ROW_HEIGHT

    def _row_y_offsets(self) -> List[Tuple[float, float]]:
        has_header = bool(self._title or self._subtitle or self._header_icon)
        curr_y = self.PADDING_VERT
        if has_header:
            curr_y += self.HEADER_HEIGHT + self.DIVIDER_HEIGHT

        offsets: List[Tuple[float, float]] = []
        for act in self._actions:
            rh = self._row_height(act)
            offsets.append((curr_y, curr_y + rh))
            curr_y += rh + self.ROW_GAP
        return offsets

    def compute_height(self) -> int:
        """Compute total menu height based on content."""
        has_header = bool(self._title or self._subtitle or self._header_icon)
        h = self.PADDING_VERT * 2
        if has_header:
            h += self.HEADER_HEIGHT + self.DIVIDER_HEIGHT
        n_rows = len(self._actions)
        if n_rows > 0:
            for act in self._actions:
                h += self._row_height(act)
            h += (n_rows - 1) * self.ROW_GAP
        return int(round(h))

    def show_at(self, anchor_global: QRectF) -> None:
        """Position menu relative to anchor, clamped inside availableGeometry with scrolling if needed."""
        try:
            if anchor_global is not None:
                try:
                    self._anchor_global = QRectF(anchor_global)
                except Exception:
                    self._anchor_global = None
            else:
                self._anchor_global = None

            content_h = self.compute_height()
            h = content_h
            dpr = 1.0

            screen = None
            if self._anchor_global is not None:
                center_pt = self._anchor_global.center().toPoint()
                screen = QGuiApplication.screenAt(center_pt)
            if screen is None:
                screen = QGuiApplication.primaryScreen()

            if screen is not None:
                geom = screen.availableGeometry()
                dpr = screen.devicePixelRatio()
                margin = 8
                max_allowed_h = geom.height() - margin * 2
                if h > max_allowed_h:
                    h = max_allowed_h

            self.resize(self.WIDTH, h)
            self._scroll_y = 0.0

            if self._anchor_global is not None and screen is not None:
                geom = screen.availableGeometry()
                margin = 8
                center_x = self._anchor_global.center().x()
                target_x = int(round(center_x - self.width() / 2.0))
                target_y = int(round(self._anchor_global.top() - self.height() - 8))

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

            # Acrylic blur & rounded region
            hwnd = int(self.winId())
            if winapi and hasattr(winapi, "enable_acrylic"):
                try:
                    winapi.enable_acrylic(hwnd, 0x50181612)
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(self.RADIUS), dpr)
                except Exception as exc:
                    log_err("ActionMenu.winapi", exc)

            # Entry transition: fade 0->1, slide 8px in 170ms OutCubic
            self._is_closing = False
            self._anim.stop()
            self._anim.setDuration(170)
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
            log_err("ActionMenu.show_at", exc)

    def hide_animated(self) -> None:
        """Trigger close transition: fade 1->0, slide 6px in 140ms InQuad, then hide."""
        try:
            if not self.isVisible() or self._is_closing:
                return

            self._disarm()
            self._is_closing = True

            self._anim.stop()
            start_val = self._anim_progress
            duration = max(30, int(140 * start_val))

            self._anim.setDuration(duration)
            self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self._anim.setStartValue(start_val)
            self._anim.setEndValue(0.0)
            self._anim.start()
        except Exception as exc:
            log_err("ActionMenu.hide_animated", exc)

    def is_open(self) -> bool:
        """Return True if menu is currently visible and not in closing animation."""
        return self.isVisible() and not self._is_closing

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Render current action menu view offscreen to a high-DPI ARGB32 QImage."""
        try:
            if not self.isVisible():
                self.resize(self.WIDTH, self.compute_height())
            w_phys = max(1, int(round(self.width() * dpr)))
            h_phys = max(1, int(round(self.height() * dpr)))
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

            try:
                self._paint_content(p)
            finally:
                self._anim_opacity = saved_op
                self._anim_offset_y = saved_off
                p.end()
            return img
        except Exception as exc:
            log_err("ActionMenu.render_to_image", exc)
            return QImage()

    # -----------------------------------------------------------------------
    # Animation Callbacks
    # -----------------------------------------------------------------------

    def _on_anim_value_changed(self, val: Any) -> None:
        v = float(val)
        self._anim_progress = v
        self._anim_opacity = v
        if self._is_closing:
            self._anim_offset_y = (1.0 - v) * 6.0
        else:
            self._anim_offset_y = (1.0 - v) * 8.0
        self.update()

    def _on_anim_finished(self) -> None:
        if self._is_closing:
            self._is_closing = False
            self.hide()

    def _on_arm_timeout(self) -> None:
        self._disarm()
        self.update()

    def _disarm(self) -> None:
        self._armed_action_id = None
        if self._arm_timer.isActive():
            self._arm_timer.stop()

    # -----------------------------------------------------------------------
    # Event Handlers
    # -----------------------------------------------------------------------

    def changeEvent(self, event: QEvent) -> None:
        try:
            if event.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                    self.hide_animated()
        except Exception as exc:
            log_err("ActionMenu.changeEvent", exc)
        super().changeEvent(event)

    def wheelEvent(self, event) -> None:
        try:
            content_h = self.compute_height()
            max_scroll = max(0.0, float(content_h - self.height()))
            if max_scroll > 0.0:
                delta = event.angleDelta().y()
                step = (delta / 120.0) * 40.0
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self._hover_idx = self._row_at(event.position().y())
                self.update()
                event.accept()
                return
        except Exception as exc:
            log_err("ActionMenu.wheelEvent", exc)
        super().wheelEvent(event)

    def _ensure_row_visible(self, idx: int) -> None:
        content_h = self.compute_height()
        max_scroll = max(0.0, float(content_h - self.height()))
        if max_scroll <= 0.0 or not (0 <= idx < len(self._actions)):
            return
        offsets = self._row_y_offsets()
        if idx >= len(offsets):
            return
        top, bottom = offsets[idx]
        has_header = bool(self._title or self._subtitle or self._header_icon)
        rows_start_y = self.PADDING_VERT
        if has_header:
            rows_start_y += self.HEADER_HEIGHT + self.DIVIDER_HEIGHT
        vis_h = self.height() - rows_start_y - self.PADDING_VERT

        rel_top = top - rows_start_y
        rel_bottom = bottom - rows_start_y

        if rel_top < self._scroll_y:
            self._scroll_y = max(0.0, float(rel_top))
        elif rel_bottom > self._scroll_y + vis_h:
            self._scroll_y = min(max_scroll, float(rel_bottom - vis_h))

    def leaveEvent(self, event: QEvent) -> None:
        self._hover_idx = -1
        self._disarm()
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            n = len(self._actions)
            if n > 0:
                step = -1 if key == Qt.Key.Key_Up else 1
                curr = self._hover_idx if self._hover_idx >= 0 else (-1 if step > 0 else n)
                # Find next enabled action row (skip separators, titles, and disabled rows)
                for i in range(1, n + 1):
                    cand = (curr + step * i) % n
                    act = self._actions[cand]
                    if act.get("type", "action") == "action" and act.get("enabled", True):
                        self._hover_idx = cand
                        self._ensure_row_visible(cand)
                        self.update()
                        break
            event.accept()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if 0 <= self._hover_idx < len(self._actions):
                self._trigger_row(self._hover_idx)
            event.accept()
            return

        super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        idx = self._row_at(pos.y())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._row_at(event.position().y())
            if idx >= 0:
                self._trigger_row(idx)
        super().mousePressEvent(event)

    def _row_at(self, y: float) -> int:
        eff_y = y + self._scroll_y
        offsets = self._row_y_offsets()
        for i, (top, bottom) in enumerate(offsets):
            if top <= eff_y <= bottom:
                act = self._actions[i]
                if act.get("type", "action") == "action":
                    return i
                return -1
        return -1

    def _trigger_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._actions)):
            return
        action = self._actions[idx]
        if action.get("type", "action") != "action":
            return
        if not action.get("enabled", True):
            return

        act_id = action.get("id", "")
        needs_confirm = action.get("confirm", False)
        cb = action.get("callback")

        if needs_confirm:
            if self._armed_action_id == act_id:
                # Confirmed! Emit and close
                self._disarm()
                self.action_chosen.emit(act_id)
                if callable(cb):
                    try:
                        cb()
                    except Exception as exc:
                        log_err("ActionMenu.callback", exc)
                self.hide_animated()
            else:
                # First click: Arm
                self._armed_action_id = act_id
                self._arm_timer.start(3000)
                self.update()
        else:
            self._disarm()
            self.action_chosen.emit(act_id)
            if callable(cb):
                try:
                    cb()
                except Exception as exc:
                    log_err("ActionMenu.callback", exc)
            self.hide_animated()

    # -----------------------------------------------------------------------
    # Painting
    # -----------------------------------------------------------------------

    def paintEvent(self, event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._paint_content(p)

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return

        p.save()
        p.setOpacity(self._anim_opacity)
        p.translate(0.0, self._anim_offset_y)

        # 1. Base dark acrylic glass fill
        full_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        panel_path = rounded_path(full_rect, self.RADIUS)
        p.fillPath(panel_path, COLOR_BG)

        # 2. Specular top sheen
        p.save()
        p.setClipPath(panel_path)
        hl = QLinearGradient(0.0, 0.0, 0.0, 5.0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 35))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0.0, 0.0, w, 5.0), hl)
        p.restore()

        # 3. Outer subtle stroke
        p.setPen(QPen(COLOR_BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(panel_path)

        curr_y = self.PADDING_VERT

        # 4. Header (if present)
        has_header = bool(self._title or self._subtitle or self._header_icon)
        if has_header:
            header_rect = QRectF(self.PADDING_HORIZ + 4.0, curr_y, w - (self.PADDING_HORIZ + 4.0) * 2, self.HEADER_HEIGHT)
            self._draw_header(p, header_rect)
            curr_y += self.HEADER_HEIGHT

            # Hairline divider
            curr_y += 4.0
            p.setPen(QPen(COLOR_HAIRLINE, 1.0))
            p.drawLine(QPointF(self.PADDING_HORIZ + 4.0, curr_y), QPointF(w - (self.PADDING_HORIZ + 4.0), curr_y))
            curr_y += 5.0

        # Scrollable rows area
        content_h = self.compute_height()
        max_scroll = max(0.0, float(content_h - h))
        rows_start_y = curr_y
        rows_clip_h = max(0.0, h - rows_start_y - self.PADDING_VERT)

        p.save()
        if max_scroll > 0.0:
            p.setClipRect(QRectF(0.0, rows_start_y, w, rows_clip_h))
            p.translate(0.0, -self._scroll_y)

        # 5. Action rows, separators, titles
        offsets = self._row_y_offsets()
        for i, action in enumerate(self._actions):
            if i >= len(offsets):
                break
            top, bottom = offsets[i]
            row_rect = QRectF(self.PADDING_HORIZ, top, w - self.PADDING_HORIZ * 2, bottom - top)
            row_type = action.get("type", "action")
            if row_type == "separator":
                self._draw_separator(p, row_rect)
            elif row_type == "title":
                self._draw_title(p, row_rect, action.get("text", ""))
            else:
                self._draw_row(p, row_rect, action, is_hover=(i == self._hover_idx))

        p.restore()

        # 6. Scrollbar thumb if content is taller than menu height
        if max_scroll > 0.0 and rows_clip_h > 24.0:
            thumb_h = max(24.0, (h / content_h) * rows_clip_h)
            thumb_y = rows_start_y + (self._scroll_y / max_scroll) * (rows_clip_h - thumb_h)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 45))
            p.drawRoundedRect(QRectF(w - 5.0, thumb_y, 3.0, thumb_h), 1.5, 1.5)
            p.restore()

        p.restore()

    def _draw_separator(self, p: QPainter, rect: QRectF) -> None:
        p.save()
        cy = rect.center().y()
        p.setPen(QPen(COLOR_HAIRLINE, 1.0))
        p.drawLine(QPointF(self.PADDING_HORIZ + 4.0, cy), QPointF(self.width() - (self.PADDING_HORIZ + 4.0), cy))
        p.restore()

    def _draw_title(self, p: QPainter, rect: QRectF, title_text: str) -> None:
        p.save()
        p.setFont(self.f_sub)
        p.setPen(COLOR_TEXT_MUTED)
        fm = QFontMetricsF(self.f_sub)
        avail_w = rect.width() - 16.0
        elided = fm.elidedText(title_text, Qt.TextElideMode.ElideRight, max(0.0, avail_w))
        t_rect = QRectF(rect.left() + 8.0, rect.top(), max(0.0, avail_w), rect.height())
        p.drawText(t_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
        p.restore()

    def _draw_header(self, p: QPainter, rect: QRectF) -> None:
        p.save()
        left = rect.left()
        cy = rect.center().y()

        # App Icon (20x20)
        icon_size = 20.0
        if self._header_icon and not self._header_icon.isNull():
            target_r = QRectF(left, cy - icon_size / 2.0, icon_size, icon_size)
            p.drawPixmap(target_r.toRect(), self._header_icon)
            left += icon_size + 8.0
        else:
            # Subtle circle placeholder if no icon provided
            target_r = QRectF(left, cy - icon_size / 2.0, icon_size, icon_size)
            p.setPen(QPen(COLOR_HAIRLINE, 1.0))
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawEllipse(target_r)
            left += icon_size + 8.0

        # Title & Subtitle text
        text_w = rect.right() - left
        if self._subtitle:
            # 2 lines: Title 12.5px, Subtitle 10.5px
            p.setFont(self.f_title)
            p.setPen(COLOR_TEXT_PRIMARY)
            fm_t = QFontMetricsF(self.f_title)
            t_elided = fm_t.elidedText(self._title, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(QRectF(left, rect.top() + 1.0, text_w, 18.0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), t_elided)

            p.setFont(self.f_sub)
            p.setPen(COLOR_TEXT_MUTED)
            fm_s = QFontMetricsF(self.f_sub)
            s_elided = fm_s.elidedText(self._subtitle, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(QRectF(left, rect.top() + 19.0, text_w, 16.0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), s_elided)
        else:
            # Single centered line
            p.setFont(self.f_title)
            p.setPen(COLOR_TEXT_PRIMARY)
            fm_t = QFontMetricsF(self.f_title)
            t_elided = fm_t.elidedText(self._title, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(QRectF(left, rect.top(), text_w, rect.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), t_elided)

        p.restore()

    def _draw_row(self, p: QPainter, rect: QRectF, action: Dict[str, Any], is_hover: bool) -> None:
        p.save()

        act_id = action.get("id", "")
        enabled = action.get("enabled", True)
        danger = action.get("danger", False)
        is_armed = (self._armed_action_id == act_id)

        # Background tinting
        if is_armed:
            path = rounded_path(rect, self.ROW_RADIUS)
            p.fillPath(path, COLOR_DANGER_ARMED_BG)
            p.setPen(QPen(COLOR_DANGER, 1.0))
            p.drawPath(path)
        elif is_hover and enabled:
            path = rounded_path(rect, self.ROW_RADIUS)
            p.fillPath(path, COLOR_ROW_HOVER)

        # Content geometry
        inset_x = rect.left() + 8.0
        cy = rect.center().y()
        glyph = action.get("icon")

        # Color resolution
        if not enabled:
            fg_color = COLOR_TEXT_DISABLED
        elif is_armed or danger:
            fg_color = COLOR_DANGER
        else:
            fg_color = COLOR_TEXT_PRIMARY

        # Glyph drawing
        if glyph:
            glyph_rect = QRectF(inset_x, cy - 8.0, 16.0, 16.0)
            draw_line_glyph(p, str(glyph), glyph_rect, fg_color)
            inset_x += 24.0

        # Text resolution
        p.setFont(self.f_row)
        p.setPen(fg_color)

        if is_armed:
            row_text = "Emin misin? Tekrar tıkla"
        else:
            row_text = action.get("text", "")

        fm = QFontMetricsF(self.f_row)
        hint_text = (action.get("hint", "") if not enabled else "") or str(action.get("shortcut") or "")
        # Sebep zaten başlığın alt satırında yazıyorsa tekrar etme (eylem metni kesilmesin)
        if hint_text and hint_text.strip() == str(self._subtitle or "").strip():
            hint_text = ""
        # Indicator resolution: radio dot or checkmark
        is_radio = bool(action.get("group"))
        is_checked = bool(action.get("checked"))
        indicator_w = 20.0 if (is_radio or is_checked) else 0.0

        if is_radio:
            if is_checked:
                p.save()
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fg_color)
                p.drawEllipse(QPointF(rect.right() - 14.0, cy), 3.5, 3.5)
                p.restore()
        elif is_checked:
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(fg_color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx = rect.right() - 14.0
            p.drawLine(QPointF(cx - 4.5, cy), QPointF(cx - 1.5, cy + 3.0))
            p.drawLine(QPointF(cx - 1.5, cy + 3.0), QPointF(cx + 4.5, cy - 3.5))
            p.restore()

        avail_w = rect.right() - 8.0 - indicator_w - inset_x

        if hint_text:
            p.setFont(self.f_hint)
            fm_h = QFontMetricsF(self.f_hint)
            hint_w = fm_h.horizontalAdvance(hint_text)
            hint_rect = QRectF(rect.right() - 8.0 - indicator_w - hint_w, rect.top(), hint_w, rect.height())
            p.setPen(COLOR_TEXT_MUTED)
            p.drawText(hint_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), hint_text)
            avail_w -= (hint_w + 8.0)
            p.setFont(self.f_row)
            p.setPen(fg_color)

        elided = fm.elidedText(row_text, Qt.TextElideMode.ElideRight, max(0.0, avail_w))
        text_rect = QRectF(inset_x, rect.top(), max(0.0, avail_w), rect.height())
        p.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)

        p.restore()
