"""Şerit Bildirim Alanı (sistem tepsisi) paneli — panel_style v2 ortak kit ÜSTÜNDE (v20).

Açılır panellerin ortak dilini paylaşır: opak #141518 kabuk, 16/12/8 köşe dilimi,
draw_header / draw_card / draw_footer yardımcıları, animate_in / animate_out hareketi.
Panelin kendi işleri: eğri baş sayfa devri yok; DPR uyumlu 24 px gerçek simge + genel glif
yedeği, Türkçe ad temizleme, kaydırma, klavye gezinmesi. Veri yoksa '—' veya 'Simge yok'
boş durumu; hiçbir değer uydurulmaz. Ağır işler GUI iş parçacığı dışındadır.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

_serit_dir = str(Path(__file__).resolve().parent)
if _serit_dir not in sys.path:
    sys.path.insert(0, _serit_dir)

import panel_style as ps  # noqa: E402

try:
    import sources  # noqa: E402
    import winapi  # noqa: E402
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
# Ad temizleme ve Türkçe durum yardımcıları (diğer modüller bunları içe aktarır)
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
# Vektör simge yardımcıları
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
    """Windows sistem tepsisi simge listesi paneli, 352 px, panel_style v2."""

    WIDTH: int = int(ps.WIDTH["tray"])
    RADIUS: float = float(ps.R_PANEL)

    ROW_HEIGHT: float = 40.0
    ROW_STRIDE: float = 40.0
    LIST_MAX_HEIGHT: float = 320.0   # uzun listeler kaydırılır (8 tam satır)
    EMPTY_LIST_H: float = 40.0
    ICON_SZ: float = 24.0
    EMPTY_TEXT: str = "Simge yok"
    ROW_RADIUS: float = 8.0

    item_activated = Signal(object, str)   # (item dict, "left" | "right")
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

        # Tepsi verisi
        self._items: List[Dict[str, Any]] = []
        self._icons: Dict[str, Any] = {}
        self._scaled_icons: Dict[Tuple[str, float], QPixmap] = {}
        self._stamp: str = "—"                        # son set_items saati
        self._anchor_global: Optional[QRectF] = None

        # Etkileşim durumu
        self._hover_idx: int = -1
        self._highlight_idx: int = -1
        self._close_hovered: bool = False
        self._refresh_hovered: bool = False
        self._refresh_pressed: bool = False
        self._scroll_y: float = 0.0

        # Hit-test dikdörtgenleri
        self._rects: Dict[str, QRectF] = {}
        self._close_rect: QRectF = QRectF()
        self._refresh_rect: QRectF = QRectF()
        self._list_rect: QRectF = QRectF(0.0, 0.0, 0.0, 0.0)

        # Yaşam döngüsü
        self._is_closing: bool = False
        self._last_close_time: float = 0.0
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self._f_name = ps.font(12.5, QFont.Weight.DemiBold)
        self._f_sub = ps.f_small()
        self._f_empty = ps.f_body()

        self.resize(self.WIDTH, self.compute_height())
        self._layout()

    # ------------------------------------------------------------- yerleşim
    def _body_list_heights(self) -> Tuple[float, float]:
        """(toplam satır yüksekliği, görünen yükseklik)."""
        if not self._items:
            return self.EMPTY_LIST_H, self.EMPTY_LIST_H
        total = float(len(self._items) * self.ROW_STRIDE)
        return total, min(self.LIST_MAX_HEIGHT, total)

    def _layout(self) -> None:
        """Kart içi liste alanını hesaplar (paint olmaksızın hit-test için)."""
        vh = self._visible_list_height()
        list_top = ps.PAD + ps.HEADER_H + ps.GAP + ps.CARD_GAP + 15.0 + ps.CARD_PAD
        self._list_rect = QRectF(
            ps.PAD + ps.CARD_PAD,
            list_top,
            self.width() - 2.0 * ps.PAD - 2.0 * ps.CARD_PAD,
            vh,
        )

    def compute_height(self) -> int:
        """Öğe sayısına göre panel yüksekliği (kart içeriği dar; uzun liste kaydırılır)."""
        total_h, vis_h = self._body_list_heights()
        h = ps.PAD + ps.HEADER_H + ps.GAP
        h += 2.0 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + vis_h
        h += ps.GAP + ps.FOOTER_H + ps.PAD * 0.5
        return int(round(h))

    # ------------------------------------------------------------------ API
    def is_open(self) -> bool:
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def chip_text(self) -> str:
        """Başlık rozeti: öğe sayısı ('5 öğe')."""
        return f"{len(self._items)} öğe"

    def set_items(self, items: Any, icons: Any = None) -> None:
        """Tepsi simge listesini ve ikon önbelleğini gösterilecek hale getirir."""
        try:
            raw_list = items if isinstance(items, list) else []
            sanitized: List[Dict[str, Any]] = []
            for it in raw_list:
                if isinstance(it, dict):
                    sanitized.append(it)
                else:
                    sanitized.append({"name": str(it) if it is not None else ""})
            self._items = sanitized

            self._icons = icons if isinstance(icons, dict) else {}
            self._scaled_icons.clear()

            self._stamp = time.strftime("%H:%M")

            if self._highlight_idx >= len(self._items):
                self._highlight_idx = len(self._items) - 1
            if self._hover_idx >= len(self._items):
                self._hover_idx = -1

            max_scroll = max(0.0, self._total_list_height() - self._visible_list_height())
            self._scroll_y = max(0.0, min(max_scroll, self._scroll_y))

            self._relayout()
        except Exception as exc:
            _log_err("TrayPanel.set_items", exc)

    def _relayout(self) -> None:
        h = self.compute_height()
        if h != self.height():
            self.resize(self.WIDTH, h)
        self._layout()
        self.update()

    def show_for(self, anchor_global: Optional[QRectF], switch_from_x: Optional[int] = None) -> None:
        """Ancorun sağ kenarına hizalar, yukarı açar; ortak animate_in kullanır."""
        try:
            if anchor_global is not None:
                try:
                    self._anchor_global = QRectF(anchor_global)
                except Exception:
                    self._anchor_global = None
            else:
                self._anchor_global = None

            self._is_closing = False
            self.resize(self.WIDTH, self.compute_height())
            self._layout()

            dpr = 1.0
            target = QPoint(100, 100)
            if self._anchor_global is not None:
                # Eski davranış korunur: tepsinin SAĞ kenarına hizalı
                tx = int(self._anchor_global.right() - self.width())
                ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)

                screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint())
                if screen is None:
                    screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geom = screen.availableGeometry()
                    dpr = screen.devicePixelRatio()
                    m = 8
                    min_x = geom.left() + m
                    max_x = geom.right() - self.width() - m
                    tx = max(min_x, min(max_x, tx)) if max_x >= min_x else min_x
                    min_y = geom.top() + m
                    max_y = geom.bottom() - self.height() - m
                    if ty < min_y:
                        below_y = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
                        ty = below_y if below_y + self.height() <= geom.bottom() - m else min_y
                    elif ty > max_y:
                        ty = max_y
                target = QPoint(tx, ty)

            hwnd = int(self.winId())
            if winapi is not None and hasattr(winapi, "set_round_region"):
                try:
                    winapi.set_round_region(hwnd, self.width(), self.height(), int(ps.R_PANEL), dpr)
                except Exception as exc:
                    _log_err("TrayPanel.winapi", exc)

            ps.animate_in(self, target, switch_from_x=switch_from_x)
            self.activateWindow()
            self.setFocus()
        except Exception as exc:
            _log_err("TrayPanel.show_for", exc)

    def hide_animated(self) -> None:
        if not self.isVisible() or self._is_closing:
            return
        self._is_closing = True
        self._last_close_time = time.monotonic()

        def _done() -> None:
            self._is_closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        """Animasyonsuz kapatma (kapsül bölüm değişimi vb.)."""
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._is_closing = False
        ps.animate_out(self, instant=True)

    def render_to_image(self, dpr: float = 2.0) -> QImage:
        """Paneli çevrimdışı yüksek DPI görüntüye çizer (ARGB32)."""
        img = QImage(
            max(1, int(self.width() * dpr)),
            max(1, int(self.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_card(p)
        finally:
            p.end()
        return img

    # ------------------------------------------------------ satır yardımcıları
    def _total_list_height(self) -> float:
        return self._body_list_heights()[0]

    def _visible_list_height(self) -> float:
        return self._body_list_heights()[1]

    def _get_scaled_icon(self, item: Dict[str, Any], dpr: float) -> Optional[QPixmap]:
        """Öğe için DPR uyumlu 24 px simge; yoksa None."""
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
            target_px = int(round(self.ICON_SZ * dpr))
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

    def _row_at_point(self, pos: QPointF) -> int:
        """Yerel koordinattan görünen satır indeksi; yoksa -1."""
        if self._list_rect is None or self._list_rect.isNull():
            return -1
        if not self._list_rect.contains(pos):
            return -1
        rel_y = pos.y() - self._list_rect.top() + self._scroll_y
        if rel_y < 0:
            return -1
        idx = int(rel_y // self.ROW_STRIDE)
        offset = rel_y - idx * self.ROW_STRIDE
        if offset > self.ROW_HEIGHT:
            return -1
        return idx if 0 <= idx < len(self._items) else -1

    def _ensure_row_visible(self, idx: int) -> None:
        """Klavye gezinmesinde satırı görünür aralığa kaydırır."""
        if idx < 0 or not self._items or idx >= len(self._items):
            return
        row_top = idx * self.ROW_STRIDE
        row_bottom = row_top + self.ROW_HEIGHT
        vis_h = self._visible_list_height()
        max_scroll = max(0.0, self._total_list_height() - vis_h)

        if row_top < self._scroll_y:
            self._scroll_y = float(row_top)
        elif row_bottom > self._scroll_y + vis_h:
            self._scroll_y = min(max_scroll, float(row_bottom - vis_h))

    # ------------------------------------------------------------------ olaylar
    def keyPressEvent(self, event) -> None:
        try:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide_animated()
                event.accept()
                return

            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._items:
                if self._highlight_idx < 0:
                    self._highlight_idx = 0 if key == Qt.Key.Key_Down else len(self._items) - 1
                elif key == Qt.Key.Key_Down:
                    self._highlight_idx = min(len(self._items) - 1, self._highlight_idx + 1)
                else:
                    self._highlight_idx = max(0, self._highlight_idx - 1)
                self._ensure_row_visible(self._highlight_idx)
                self.update()
                event.accept()
                return

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
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
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
                cursor_pos = QCursor.pos()
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(cursor_pos)):
                    # Kapsül kendi tıklamasında kapatacak; düğme bırakılana kadar bekle
                    self._last_close_time = time.monotonic()
                    self._anchor_timer.start(300)
                else:
                    self.hide_animated()
        super().changeEvent(event)

    def _on_anchor_timeout(self) -> None:
        if not self.isActiveWindow() and self.isVisible() and not self._is_closing:
            self.hide_animated()

    def hideEvent(self, event) -> None:
        self._is_closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        try:
            pos = event.position()
            button = event.button()

            if button == Qt.MouseButton.LeftButton:
                if self._close_rect.isValid() and self._close_rect.contains(pos):
                    self.hide_animated()
                    event.accept()
                    return

                if self._refresh_rect.isValid() and self._refresh_rect.contains(pos):
                    self._refresh_pressed = True
                    self.update()
                    event.accept()
                    return

                hit_idx = self._row_at_point(pos)
                if 0 <= hit_idx < len(self._items):
                    item = self._items[hit_idx]
                    self.item_activated.emit(item, "left")
                    self.hide_animated()
                    event.accept()
                    return

            elif button == Qt.MouseButton.RightButton:
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
                if self._refresh_rect.isValid() and self._refresh_rect.contains(event.position()):
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

            self._close_hovered = self._close_rect.isValid() and self._close_rect.contains(pos)
            self._refresh_hovered = self._refresh_rect.isValid() and self._refresh_rect.contains(pos)
            self._hover_idx = self._row_at_point(pos)

            if was_close != self._close_hovered or was_ref != self._refresh_hovered or old_hover != self._hover_idx:
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
            vis_h = self._visible_list_height()
            max_scroll = max(0.0, self._total_list_height() - vis_h)

            if max_scroll > 0.0:
                step = (event.angleDelta().y() / 120.0) * 40.0
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self._hover_idx = self._row_at_point(event.position())
                self.update()
                event.accept()
                return
        except Exception as exc:
            _log_err("TrayPanel.wheelEvent", exc)

        super().wheelEvent(event)

    # ------------------------------------------------------------------ çizim
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_card(p)
        except Exception as exc:
            _log_err("TrayPanel.paintEvent", exc)
        finally:
            p.end()

    @staticmethod
    def _draw_header_icon(p: QPainter, r: QRectF) -> None:
        """Tepsiyi açan bölüme benzer ^ işareti (22 px kutu)."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = r.center().x(), r.center().y()
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.6, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx - 4.5, cy + 2.0), QPointF(cx, cy - 2.5))
        p.drawLine(QPointF(cx, cy - 2.5), QPointF(cx + 4.5, cy + 2.0))
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - 6.5, cy + 6.0), QPointF(cx + 6.5, cy + 6.0))
        p.restore()

    def _paint_row(self, p: QPainter, row: QRectF, idx: int, item: Dict[str, Any], dpr: float) -> None:
        # Satır zemini: hover yumuşak vurgu / klavye imleci
        is_hover = idx == self._hover_idx
        is_kbd = idx == self._highlight_idx
        if is_hover:
            p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
            p.setBrush(ps.TILE_HOVER)
            p.drawPath(ps.rounded(row.adjusted(0.5, 0.5, -0.5, -0.5), self.ROW_RADIUS))
        elif is_kbd:
            p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawPath(ps.rounded(row.adjusted(0.5, 0.5, -0.5, -0.5), self.ROW_RADIUS))

        # Simge: gerçek 24 px icon, yoksa genel uygulama glifi
        icon_x = row.left() + 10.0
        icon_y = row.top() + (self.ROW_HEIGHT - self.ICON_SZ) / 2.0
        pm = self._get_scaled_icon(item, dpr)
        if pm is not None:
            p.drawPixmap(QPointF(icon_x, icon_y), pm)
        else:
            draw_generic_app_glyph(p, QRectF(icon_x + 0.5, icon_y + 0.5,
                                             self.ICON_SZ - 1.0, self.ICON_SZ - 1.0))

        # Ad + varsa Türkçe durum ikinci satırı
        text_x = icon_x + self.ICON_SZ + 10.0
        avail = max(8.0, row.right() - 6.0 - text_x)
        name = clean_tray_name(item)
        status = tray_status_tr(item)

        if status:
            p.setFont(self._f_name)
            fm = QFontMetricsF(self._f_name)
            p.setPen(ps.TEXT)
            p.drawText(
                QRectF(text_x, row.top() + 4.5, avail, 17.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm.elidedText(name, Qt.TextElideMode.ElideRight, avail),
            )
            p.setFont(self._f_sub)
            fm_sub = QFontMetricsF(self._f_sub)
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(text_x, row.top() + 22.0, avail, 13.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_sub.elidedText(status, Qt.TextElideMode.ElideRight, avail),
            )
        else:
            p.setFont(self._f_name)
            fm = QFontMetricsF(self._f_name)
            p.setPen(ps.TEXT)
            p.drawText(
                QRectF(text_x, row.top(), avail, self.ROW_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm.elidedText(name, Qt.TextElideMode.ElideRight, avail),
            )

    def _paint_scroll_indicator(self, p: QPainter) -> None:
        total = self._total_list_height()
        vis_h = self._visible_list_height()
        if total <= vis_h + 0.5 or self._scroll_y <= 0.5:
            return
        max_scroll = total - vis_h
        thumb_h = max(24.0, vis_h * (vis_h / total))
        thumb_y = self._list_rect.top() + (self._scroll_y / max_scroll) * (vis_h - thumb_h)
        thumb = QRectF(self.width() - 7.0, thumb_y, 3.0, thumb_h)
        p.fillPath(ps.rounded(thumb, 1.5), QColor(255, 255, 255, 70))

    def _paint_card(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        dpr = p.device().devicePixelRatio() if p.device() is not None else 1.0

        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))
        self._rects = {}
        self._layout()

        cw = w - 2.0 * ps.PAD
        y = ps.PAD

        # Başlık: 'Bildirim Alanı' + tek rozet ('N öğe') + ×
        hdr = ps.draw_header(
            p,
            QRectF(ps.PAD, y, cw, ps.HEADER_H),
            "Bildirim Alanı",
            self._draw_header_icon,
            chip=self.chip_text(),
            close_hover=self._close_hovered,
        )
        self._close_rect = QRectF(hdr["close"]) if hdr.get("close") is not None else QRectF()
        self._rects["close"] = self._close_rect
        y += ps.HEADER_H + ps.GAP

        # Kart 'UYGULAMALAR': satır başına bir tepsi ögesi
        total_h, vis_h = self._body_list_heights()
        card_h = 2.0 * ps.CARD_PAD + 15.0 + ps.CARD_GAP + vis_h
        ps.draw_card(p, QRectF(ps.PAD, y, cw, card_h), "Uygulamalar")

        p.save()
        p.setClipRect(self._list_rect)

        if not self._items:
            p.setFont(self._f_empty)
            p.setPen(ps.TEXT_MUTED)
            p.drawText(self._list_rect, Qt.AlignmentFlag.AlignCenter, self.EMPTY_TEXT)
        else:
            for i, item in enumerate(self._items):
                row_y = self._list_rect.top() + i * self.ROW_STRIDE - self._scroll_y
                if row_y + self.ROW_HEIGHT < self._list_rect.top() or row_y > self._list_rect.bottom():
                    continue
                row = QRectF(self._list_rect.left(), row_y, self._list_rect.width(), self.ROW_HEIGHT)
                self._paint_row(p, row, i, item, dpr)

        p.restore()

        # Kaydırma göstergesi (yalnız kaydırılırken)
        if total_h > vis_h and self._scroll_y > 0.5:
            self._paint_scroll_indicator(p)

        # Alt bilgi: kaynak + tek hayalet düğme
        footer_top = h - ps.PAD * 0.5 - ps.FOOTER_H
        btn = ps.draw_footer(
            p,
            QRectF(ps.PAD, footer_top, cw, ps.FOOTER_H),
            f"Windows sistem tepsisi · {self._stamp}",
            "Yenile",
            button_hover=self._refresh_hovered,
        )
        self._refresh_rect = QRectF(btn) if btn is not None else QRectF()
        if not self._refresh_rect.isNull():
            self._rects["refresh"] = self._refresh_rect
