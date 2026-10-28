"""Şerit Bildirim Alanı (sistem tepsisi) paneli — v22 kompakt simge ızgarası.

Windows 11 gizli simge flyout'u hissi: başlıksız, kartsız, footersız opak
#141518 kabuk; 44 px hücreler halinde 5 sütunlu simge ızgarası, altta tek
26 px etiket satırı (hover/odaklı öğenin temiz adı; hiçbiri değilse 'N simge';
liste boşsa kompakt 'Gizli simge yok'). DPR uyumlu 24 px gerçek simge + genel
glif yedeği korunur. Türkçe ad temizleme, kaydırma ve klavye gezinmesi korunur;
veri yoksa uydurma yapılmaz. Ağır işler GUI iş parçacığı dışındadır.
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
# TrayPanel Widget — v22 kompakt simge ızgarası
# ---------------------------------------------------------------------------

class TrayPanel(QWidget):
    """Windows sistem tepsisi simge ızgarası paneli (Windows 11 gizli simge flyout'u)."""

    WIDTH: int = 260            # tam ızgara genişliği (>= 5 öğe); daha az öğede daralır
    RADIUS: float = float(ps.R_PANEL)

    CELL_SZ: float = 44.0       # hücre 44x44
    CELL_GAP: float = 4.0       # hücreler arası boşluk
    CELLS_PER_ROW: int = 5      # 5 sütun
    GRID_PAD: float = 12.0      # ızgara çevre boşluğu
    ICON_SZ: float = 24.0       # hücre içi ortalı simge
    LABEL_H: float = 26.0       # ızgara altı etiket satırı
    LABEL_GAP: float = 4.0      # ızgara - etiket arası
    MAX_ROWS: int = 4           # 4 satırdan fazlası tekerlekle kaydırılır
    CELL_RADIUS: float = 8.0    # hover/odak hücre köşesi
    MIN_WIDTH: float = 164.0    # etiket satırına ~140 px kalan alt genişlik
    EMPTY_TEXT: str = "Gizli simge yok"
    EMPTY_H: float = GRID_PAD + LABEL_H + GRID_PAD

    # v20/v21 uyumluluk: dock getattr yolunda satır bantı olarak aynı hücre geometrisi
    ROW_HEIGHT: float = 44.0
    ROW_STRIDE: float = 48.0    # CELL_SZ + CELL_GAP

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
        self._anchor_global: Optional[QRectF] = None

        # Etkileşim durumu
        self._hover_idx: int = -1
        self._highlight_idx: int = -1
        self._pressed_idx: int = -1
        self._scroll_y: float = 0.0

        # Hit-test dikdörtgenleri
        self._grid_rect: QRectF = QRectF()
        self._label_rect: QRectF = QRectF()
        self._cell_rects: Dict[int, QRectF] = {}

        # Yaşam döngüsü
        self._is_closing: bool = False
        self._last_close_time: float = 0.0
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)

        self._f_label = ps.f_small()
        self._f_empty = ps.f_body()

        self.resize(self.compute_width(), self.compute_height())
        self._layout()

    # ------------------------------------------------------------- yerleşim
    def _cols_needed(self) -> int:
        """Öğe sayısı için gereken sütun sayısı (en çok 5)."""
        if not self._items:
            return 0
        return min(len(self._items), self.CELLS_PER_ROW)

    def _total_rows(self) -> int:
        """Sanal ızgaradaki toplam satır sayısı."""
        if not self._items:
            return 0
        return (len(self._items) + self.CELLS_PER_ROW - 1) // self.CELLS_PER_ROW

    def _visible_rows(self) -> int:
        """Görünen satır sayısı: 4 satırdan fazlası kaydırılır."""
        return min(self._total_rows(), self.MAX_ROWS)

    def _grid_content_size(self) -> Tuple[float, float]:
        """(ızgara içeriği genişlik, dikey olarak kaydırılabilir SANAL ızgara yüksekliği)."""
        cols = self._cols_needed()
        if cols == 0:
            return 0.0, 0.0
        w = cols * self.CELL_SZ + (cols - 1) * self.CELL_GAP
        h = self._total_rows() * self.CELL_SZ + (self._total_rows() - 1) * self.CELL_GAP
        return w, h

    def _visible_grid_h(self) -> float:
        """Görünen ızgara yüksekliği (<= 4 satır)."""
        rows = self._visible_rows()
        if rows == 0:
            return 0.0
        return rows * self.CELL_SZ + (rows - 1) * self.CELL_GAP

    def compute_width(self) -> int:
        """Genişlik: 5x44 + 4x4 + 24 = 260; daha az öğe → daralır; etiket ~140 px alt sınır."""
        cols = self._cols_needed()
        if cols == 0:
            return int(round(self.MIN_WIDTH))
        w = cols * self.CELL_SZ + (cols - 1) * self.CELL_GAP + 2.0 * self.GRID_PAD
        return int(round(max(self.MIN_WIDTH, w)))

    def compute_height(self) -> int:
        """Yükseklik: 12 + ızgara (max 4 satır) + 4 + 26 etiket + 12; boş liste kompakt."""
        if not self._items:
            return int(round(self.EMPTY_H))
        h = self.GRID_PAD + self._visible_grid_h() + self.LABEL_GAP + self.LABEL_H + self.GRID_PAD
        return int(round(h))

    def _layout(self) -> None:
        """Izgara alanını ve hücre dikdörtgenlerini hesaplar (hit-test için)."""
        w = float(self.width())
        if not self._items:
            self._grid_rect = QRectF()
            self._label_rect = QRectF(self.GRID_PAD, self.GRID_PAD,
                                      max(0.0, w - 2.0 * self.GRID_PAD), self.LABEL_H)
            self._cell_rects = {}
            return

        content_w, _total_h = self._grid_content_size()
        gx = (w - content_w) / 2.0 if content_w < w else self.GRID_PAD
        self._grid_rect = QRectF(gx, self.GRID_PAD, content_w, self._visible_grid_h())
        self._label_rect = QRectF(
            self.GRID_PAD,
            self._grid_rect.bottom() + self.LABEL_GAP,
            max(0.0, w - 2.0 * self.GRID_PAD),
            self.LABEL_H,
        )

        self._cell_rects = {}
        for idx in range(len(self._items)):
            self._cell_rects[idx] = self._cell_rect(idx)

    # ------------------------------------------------------------------ API
    def is_open(self) -> bool:
        return self.isVisible() and not self._is_closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def chip_text(self) -> str:
        """Etiket rozeti: simge sayısı ('N simge')."""
        return f"{len(self._items)} simge"

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

            if self._highlight_idx >= len(self._items):
                self._highlight_idx = len(self._items) - 1
            if self._hover_idx >= len(self._items):
                self._hover_idx = -1
            if self._pressed_idx >= len(self._items):
                self._pressed_idx = -1

            max_scroll = max(0.0, self._total_grid_height() - self._visible_grid_h())
            self._scroll_y = max(0.0, min(max_scroll, self._scroll_y))

            self._relayout()
        except Exception as exc:
            _log_err("TrayPanel.set_items", exc)

    def _relayout(self) -> None:
        w = self.compute_width()
        h = self.compute_height()
        if w != self.width() or h != self.height():
            self.resize(w, h)
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
            self.resize(self.compute_width(), self.compute_height())
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
            self._paint_content(p)
        finally:
            p.end()
        return img

    # -------------------------------------------------- ızgara yardımcıları
    def _total_grid_height(self) -> float:
        """SANAL ızgara yüksekliği (tüm satırlar)."""
        return self._grid_content_size()[1]

    def _cell_rect(self, idx: int) -> QRectF:
        """Öğenin görünen hücre dikdörtgeni (yerel koordinat, kaydırma dahil)."""
        if self._grid_rect.isNull() or idx < 0 or idx >= len(self._items):
            return QRectF()
        col = idx % self.CELLS_PER_ROW
        row = idx // self.CELLS_PER_ROW
        x = self._grid_rect.left() + col * self.ROW_STRIDE
        y = self._grid_rect.top() + row * self.ROW_STRIDE - self._scroll_y
        return QRectF(x, y, self.CELL_SZ, self.CELL_SZ)

    def _cell_at_point(self, pos: QPointF) -> int:
        """Yerel koordinattan hücre indeksi; yoksa -1."""
        for idx in sorted(self._cell_rects.keys()):
            r = self._cell_rects[idx]
            if r.isValid() and r.contains(pos):
                return idx
        return -1

    def item_anchor_global(self, item: Any) -> Optional[QRectF]:
        """Öğenin hücresinin GLOBAL dikdörtgeni (sağ tık menüsü bunun üzerine çapa lanır)."""
        try:
            if not self._items or item not in self._items:
                return None
            idx = self._items.index(item)
            r = self._cell_rect(idx)
            if r.isNull():
                return None
            c = r.center()
            gc = self.mapToGlobal(QPoint(int(c.x()), int(c.y())))
            return QRectF(float(gc.x() - self.CELL_SZ / 2.0),
                          float(gc.y() - self.CELL_SZ / 2.0),
                          self.CELL_SZ, self.CELL_SZ)
        except Exception as exc:
            _log_err("TrayPanel.item_anchor_global", exc)
            return None

    def _ensure_cell_visible(self, idx: int) -> None:
        """Klavye gezinmesinde hücrenin satırını görünür aralığa kaydırır."""
        if idx < 0 or not self._items or idx >= len(self._items):
            return
        row = idx // self.CELLS_PER_ROW
        row_top = row * self.ROW_STRIDE
        row_bottom = row_top + self.CELL_SZ
        vis_h = self._visible_grid_h()
        max_scroll = max(0.0, self._total_grid_height() - vis_h)

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

            n = len(self._items)
            moved = False
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_Right) and n:
                if self._highlight_idx < 0:
                    self._highlight_idx = 0 if key in (
                        Qt.Key.Key_Down, Qt.Key.Key_Right) else n - 1
                    moved = True
                elif key == Qt.Key.Key_Down:
                    self._highlight_idx = min(n - 1, self._highlight_idx + self.CELLS_PER_ROW)
                    moved = True
                elif key == Qt.Key.Key_Up:
                    self._highlight_idx = max(0, self._highlight_idx - self.CELLS_PER_ROW)
                    moved = True
                elif key == Qt.Key.Key_Right:
                    self._highlight_idx = min(n - 1, self._highlight_idx + 1)
                    moved = True
                else:
                    self._highlight_idx = max(0, self._highlight_idx - 1)
                    moved = True
                if moved:
                    self._ensure_cell_visible(self._highlight_idx)
                    self.update()
                    event.accept()
                    return

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if 0 <= self._highlight_idx < n:
                    item = self._items[self._highlight_idx]
                    self.item_activated.emit(item, "left")
                    self.hide_animated()
                    event.accept()
                    return

            is_menu_key = key == Qt.Key.Key_Menu or (
                key == Qt.Key.Key_F10 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            if is_menu_key:
                if 0 <= self._highlight_idx < n:
                    item = self._items[self._highlight_idx]
                    self.item_activated.emit(item, "right")
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

            hit_idx = self._cell_at_point(pos)
            if button == Qt.MouseButton.LeftButton:
                if 0 <= hit_idx < len(self._items):
                    self._pressed_idx = hit_idx
                    item = self._items[hit_idx]
                    self.update()
                    self.item_activated.emit(item, "left")
                    self.hide_animated()
                    event.accept()
                    return

            elif button == Qt.MouseButton.RightButton:
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
            if self._pressed_idx >= 0:
                self._pressed_idx = -1
                self.update()
                event.accept()
                return
        except Exception as exc:
            _log_err("TrayPanel.mouseReleaseEvent", exc)

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        try:
            pos = event.position()
            old_hover = self._hover_idx
            self._hover_idx = self._cell_at_point(pos)
            if old_hover != self._hover_idx:
                self.update()
        except Exception as exc:
            _log_err("TrayPanel.mouseMoveEvent", exc)

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_idx = -1
        self._pressed_idx = -1
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        try:
            vis_h = self._visible_grid_h()
            max_scroll = max(0.0, self._total_grid_height() - vis_h)

            if max_scroll > 0.0:
                step = (event.angleDelta().y() / 120.0) * self.ROW_STRIDE
                self._scroll_y = max(0.0, min(max_scroll, self._scroll_y - step))
                self._layout()
                self._hover_idx = self._cell_at_point(event.position())
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
            self._paint_content(p)
        except Exception as exc:
            _log_err("TrayPanel.paintEvent", exc)
        finally:
            p.end()

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

    def _paint_cell(self, p: QPainter, cell: QRectF, idx: int, item: Dict[str, Any], dpr: float) -> None:
        is_hover = idx == self._hover_idx
        is_pressed = idx == self._pressed_idx
        is_kbd = idx == self._highlight_idx

        # Hücre zemini: hover BUTTON_HOVER / basılı daha koyu
        if is_pressed:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 55))
            p.drawPath(ps.rounded(cell, self.CELL_RADIUS))
        elif is_hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ps.BUTTON_HOVER)
            p.drawPath(ps.rounded(cell, self.CELL_RADIUS))

        # Klavye odağı: 1 px ACCENT halkası
        if is_kbd:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ps.ACCENT, 1.0))
            p.drawPath(ps.rounded(cell.adjusted(0.5, 0.5, -0.5, -0.5), self.CELL_RADIUS))

        # Simge: gerçek 24 px icon ortalı, yoksa genel uygulama glifi
        pm = self._get_scaled_icon(item, dpr)
        if pm is not None:
            pm_w = pm.width() / max(1.0, pm.devicePixelRatio())
            pm_h = pm.height() / max(1.0, pm.devicePixelRatio())
            ix = cell.center().x() - pm_w / 2.0
            iy = cell.center().y() - pm_h / 2.0
            p.drawPixmap(QPointF(ix, iy), pm)
        else:
            gr = QRectF(cell.center().x() - self.ICON_SZ / 2.0 + 0.5,
                        cell.center().y() - self.ICON_SZ / 2.0 + 0.5,
                        self.ICON_SZ - 1.0, self.ICON_SZ - 1.0)
            draw_generic_app_glyph(p, gr)

    def _paint_label(self, p: QPainter) -> None:
        """Izgara altı tek etiket satırı: temiz ad (hover/odak), 'N simge', 'Gizli simge yok'."""
        r = self._label_rect
        if r.isNull():
            return
        n = len(self._items)
        idx = self._hover_idx if 0 <= self._hover_idx < n else (
            self._highlight_idx if 0 <= self._highlight_idx < n else -1)

        p.setFont(self._f_label)
        if idx >= 0:
            fm = QFontMetricsF(self._f_label)
            text = fm.elidedText(clean_tray_name(self._items[idx]),
                                 Qt.TextElideMode.ElideRight, max(8.0, r.width()))
            p.setPen(ps.TEXT_BODY)
        else:
            text = self.EMPTY_TEXT if not self._items else self.chip_text()
            p.setPen(ps.TEXT_MUTED)

        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def _paint_scroll_indicator(self, p: QPainter) -> None:
        total = self._total_grid_height()
        vis_h = self._visible_grid_h()
        if total <= vis_h + 0.5 or self._scroll_y <= 0.5 or self._grid_rect.isNull():
            return
        max_scroll = total - vis_h
        thumb_h = max(24.0, vis_h * (vis_h / total))
        thumb_y = self._grid_rect.top() + (self._scroll_y / max_scroll) * (vis_h - thumb_h)
        thumb = QRectF(self.width() - 7.0, thumb_y, 3.0, thumb_h)
        p.fillPath(ps.rounded(thumb, 1.5), QColor(255, 255, 255, 70))

    def _paint_content(self, p: QPainter) -> None:
        w = float(self.width())
        h = float(self.height())
        dpr = p.device().devicePixelRatio() if p.device() is not None else 1.0

        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))
        self._cell_rects = {}
        self._layout()

        if not self._items:
            # Kompakt boş durum: ortada soluk 'Gizli simge yok'
            p.setFont(self._f_empty)
            p.setPen(ps.TEXT_MUTED)
            empty_rect = QRectF(self.GRID_PAD, self.GRID_PAD,
                                max(0.0, w - 2.0 * self.GRID_PAD), self.LABEL_H)
            p.drawText(empty_rect, Qt.AlignmentFlag.AlignCenter, self.EMPTY_TEXT)
            return

        # Izgara: görünür hücreler klibi
        p.save()
        p.setClipRect(self._grid_rect.adjusted(-1.0, -1.0, 1.0, 1.0))
        for idx in sorted(self._cell_rects.keys()):
            item = self._items[idx]
            if isinstance(item, dict):
                self._paint_cell(p, self._cell_rects[idx], idx, item, dpr)
        p.restore()

        self._paint_label(p)

        # Kaydırma göstergesi (yalnız kaydırılırken)
        self._paint_scroll_indicator(p)
