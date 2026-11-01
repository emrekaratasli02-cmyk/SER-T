"""settings_window.py - Şerit dock ayarlar penceresi (panel_style v2 ortak dili).

560 x 520 px, yuvarlatılmış 16 px köşe, gerçekten saydam dış köşeler. Sol tarafta 172 px
gezinti çubuğu, sağda kartlardan oluşan içerik ve altta Vazgeç / Uygula çubuğu.
Bölümler: Görünüm, Kartlar, Sabitlenen uygulamalar, Uyarılar, Performans, Hakkında.
"""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

import panel_style as ps
import theme
import winapi
from logpath import get_log_path

WINDOW_WIDTH: int = 560
WINDOW_HEIGHT: int = 520
CORNER_RADIUS: float = ps.R_PANEL
SIDEBAR_WIDTH: float = 172.0
BOTTOM_BAR_HEIGHT: float = 54.0

SECTIONS: List[Tuple[str, str]] = [
    ("appearance", "Görünüm"),
    ("cards", "Kartlar"),
    ("pinned", "Sabitlenen uygulamalar"),
    ("alerts", "Uyarılar"),
    ("performance", "Performans"),
    ("about", "Hakkında"),
]

CARD_DEFS: List[Tuple[str, str, str]] = [
    ("claude", "Claude", "Kullanım ve kota bilgisi"),
    ("mail", "Mail", "Cevap bekleyen mailler"),
    ("ag", "Antigravity", "Model kotaları ve durum"),
    ("sys", "Sistem halkaları", "İşlemci ve bellek kullanımı"),
    ("cal", "Takvim", "Günün etkinlikleri ve saat"),
    ("media", "Müzik", "Şu an çalan medya ve kontroller"),
]

TOOL_DEFS: List[Tuple[str, str, str]] = [
    ("shelf_enabled", "Dosya rafı ve Pano", "İndirilenler, ekran görüntüleri ve kopyalananlar"),
    ("net_speed_enabled", "Canlı ağ hızı", "50 KB/sn üstü trafikte ↓/↑ hız göstergesi"),
    ("updates_enabled", "Güncelleme rozeti", "Winget güncellemelerini sağ kümede bildir"),
    ("drag_activate", "Sürükle-öne-getir", "Dosya sürüklerken uygulama penceresini aç"),
    ("app_usage_ctrl", "Ctrl ile kullanım süresi", "İkon üzerinde Ctrl basılıyken süreyi göster"),
]

SETTING_DEFAULTS: Dict[str, bool] = {
    "hide_taskbar": False,
    "reserve_space": True,
    "alerts_enabled": True,
    "shelf_enabled": True,
    "shelf_screenshots": True,
    "drag_activate": True,
    "net_speed_enabled": True,
    "updates_enabled": True,
    "app_usage_ctrl": True,
    "presence_enabled": True,
    "hide_on_fullscreen": True,
    "hover_preview": True,
}

STALL_NOTE = "300 ms ve üstü takılmalar sayılır · uyku süresi sayılmaz"
STALL_UNAVAILABLE = "Donma ölçer çalışmıyor"
STALL_NONE = "Bu oturumda donma yok"
STALL_ROW_H = 21.0


_GIT_VER_CACHE: Optional[str] = None


def _get_git_version() -> str:
    """Kısa commit kimliği, doğrudan .git dosyalarından okunur.

    Eskiden `git describe` alt süreci GUI iş parçacığında çalışıyordu ve pencere her
    açılışta ~2 sn donuyordu (28 Eki, ui_stall_stack). Artık alt süreç yok ve sonuç önbellekte.
    """
    global _GIT_VER_CACHE
    if _GIT_VER_CACHE is not None:
        return _GIT_VER_CACHE
    ver = "—"
    try:
        git_dir = Path(__file__).resolve().parent / ".git"
        if git_dir.is_file():  # worktree: "gitdir: <yol>"
            txt = git_dir.read_text(encoding="utf-8").strip()
            if txt.startswith("gitdir:"):
                git_dir = Path(txt.split(":", 1)[1].strip())
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        sha = head
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            common = git_dir
            common_file = git_dir / "commondir"
            if common_file.is_file():
                common = (git_dir / common_file.read_text(encoding="utf-8").strip()).resolve()
            sha = ""
            for base in (git_dir, common):
                ref_file = base / ref
                if ref_file.is_file():
                    sha = ref_file.read_text(encoding="utf-8").strip()
                    break
            if not sha:
                packed = common / "packed-refs"
                if packed.is_file():
                    for line in packed.read_text(encoding="utf-8").splitlines():
                        if line.endswith(" " + ref):
                            sha = line.split(" ", 1)[0]
                            break
        if len(sha) >= 7 and all(c in "0123456789abcdef" for c in sha[:7].lower()):
            ver = sha[:7]
    except Exception:
        ver = "—"
    _GIT_VER_CACHE = ver
    return ver


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def normalize_stall_stats(raw: Any) -> Optional[Dict[str, Any]]:
    """StallMonitor.stats() çıktısını doğrular; bozuksa None döner, sayı uydurmaz."""
    if not isinstance(raw, dict):
        return None
    count = _as_int(raw.get("count"))
    worst = _as_int(raw.get("worst_ms"))
    if count is None or worst is None or count < 0 or worst < 0:
        return None
    last = raw.get("last", [])
    if last is None:
        last = []
    if not isinstance(last, list):
        return None
    items: List[Dict[str, Any]] = []
    for entry in last:
        if not isinstance(entry, dict):
            return None
        ms = _as_int(entry.get("ms"))
        stamp = _as_float(entry.get("time"))
        if ms is None or stamp is None or ms < 0:
            return None
        top = entry.get("top")
        items.append({"ms": ms, "time": stamp, "top": str(top) if top is not None else "—"})
    return {"count": count, "worst_ms": worst, "last": items[-20:]}


def format_ms(ms: int) -> str:
    """Türkçe binlik ayırıcı: 1250 -> '1.250 ms'."""
    try:
        return f"{int(ms):,}".replace(",", ".") + " ms"
    except (TypeError, ValueError):
        return "—"


def stall_color(ms: int) -> QColor:
    if ms >= 1000:
        return ps.DANGER
    if ms >= 300:
        return ps.WARN
    return ps.TEXT_BODY


class FluentToggle(QWidget):
    """40 x 20 px pill anahtar; panel_style renkleriyle çizilir."""

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
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(0.5, 0.5, float(self.width()) - 1.0, float(self.height()) - 1.0)
            _paint_toggle_shape(p, rect, self._checked, self._hover, self._pressed)
        finally:
            p.end()


def _paint_toggle_shape(p: QPainter, rect: QRectF, checked: bool, hover: bool, pressed: bool) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = rect.height() / 2.0
    path = ps.rounded(rect, radius)
    w = rect.width()
    h = rect.height()

    if checked:
        track = ps.ACCENT.lighter(112) if (hover or pressed) else ps.ACCENT
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawPath(path)
        thumb_sz = 12.0
        thumb_w = 14.0 if pressed else thumb_sz
        thumb = QRectF(rect.x() + w - 4.0 - thumb_w, rect.y() + (h - thumb_sz) / 2.0, thumb_w, thumb_sz)
        p.setBrush(ps.TEXT)
        p.drawPath(ps.rounded(thumb, thumb_sz / 2.0))
    else:
        p.setPen(QPen(ps.TEXT_MUTED if hover else ps.TRACK, 1.0))
        p.setBrush(ps.TRACK)
        p.drawPath(path)
        thumb_sz = 10.0
        thumb_w = 12.0 if pressed else thumb_sz
        thumb = QRectF(rect.x() + 4.0, rect.y() + (h - thumb_sz) / 2.0, thumb_w, thumb_sz)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.TEXT_MUTED)
        p.drawPath(ps.rounded(thumb, thumb_sz / 2.0))
    p.restore()


class SettingsWindow(QWidget):
    """Şerit dock ayarları; çalışma kopyası üzerinde değişir, Uygula ile geri verir."""

    def __init__(
        self,
        settings: dict,
        on_apply: Callable[[dict], None],
        parent: Optional[QWidget] = None,
        *,
        stats_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._original_settings: dict = settings
        self._on_apply_cb: Callable[[dict], None] = on_apply
        self._stats_provider = stats_provider

        self.working_settings: dict = copy.deepcopy(settings)
        if "cards" not in self.working_settings or not isinstance(self.working_settings["cards"], dict):
            self.working_settings["cards"] = {}
        if "pinned" not in self.working_settings or not isinstance(self.working_settings["pinned"], list):
            self.working_settings["pinned"] = []
        else:
            self.working_settings["pinned"] = [
                dict(item) for item in self.working_settings["pinned"] if isinstance(item, dict)
            ]

        self.current_section: str = "appearance"

        self._hover_section: Optional[str] = None
        self._hover_btn: Optional[str] = None
        self._hover_item_key: Optional[str] = None

        self._content_hit_boxes: List[Tuple[QRectF, str, Any]] = []
        self._toggle_rects: Dict[str, QRectF] = {}
        self._toggle_checked: Dict[str, bool] = {}
        self._close_rect: QRectF = QRectF()

        self._scroll_offset_y: float = 0.0
        self._pinned_inner_h: float = 0.0
        self._pinned_content_h: float = 0.0
        self._cards_view_h: float = 0.0
        self._cards_total_h: float = 0.0

        self._git_ver = _get_git_version()

        self._stats: Optional[Dict[str, Any]] = None
        self._stats_ok: bool = False
        self._last_close_time: float = 0.0

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._on_stats_tick)

    # ------------------------------------------------------------------ API
    def switch_section(self, section_id: str) -> None:
        valid_ids = [s[0] for s in SECTIONS]
        if section_id not in valid_ids or self.current_section == section_id:
            return
        self.current_section = section_id
        self._scroll_offset_y = 0.0
        if section_id == "performance":
            self._load_stats()
        self._sync_stats_timer()
        self.update()

    def apply_and_close(self) -> None:
        cfg_out = copy.deepcopy(self.working_settings)
        if callable(self._on_apply_cb):
            self._on_apply_cb(cfg_out)
        self._hide_animated()

    def cancel_and_close(self) -> None:
        self._hide_animated()

    def show_for(self, anchor_global: Optional[QRectF] = None, *, switch_from_x: Optional[int] = None) -> None:
        target = self._target_position(anchor_global)
        dpr = 1.0
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            dpr = screen.devicePixelRatio()
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(int(self.winId()), self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass
        self._last_close_time = 0.0
        if self.current_section == "performance":
            self._load_stats()
        ps.animate_in(self, target, switch_from_x=switch_from_x)
        self.activateWindow()
        self.setFocus()

    def hide_instant(self) -> None:
        if self.isVisible():
            self._last_close_time = time.monotonic()
        ps.animate_out(self, instant=True)

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    # --------------------------------------------------------------- konum
    def _target_position(self, anchor_global: Optional[QRectF]) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if anchor_global is not None:
            screen = QGuiApplication.screenAt(anchor_global.center().toPoint()) or screen
        if screen is None:
            return QPoint(100, 100)
        geom = screen.availableGeometry()
        margin = 8
        if anchor_global is None:
            tx = int(geom.center().x() - self.width() / 2.0)
            ty = int(geom.center().y() - self.height() / 2.0)
        else:
            tx = int(anchor_global.center().x() - self.width() / 2.0)
            ty = int(anchor_global.top() - self.height() - ps.ANCHOR_GAP)
            if ty < geom.top() + margin:
                ty = int(anchor_global.bottom() + ps.ANCHOR_GAP)
        max_x = geom.right() - self.width() - margin
        tx = max(geom.left() + margin, min(max_x, tx)) if max_x >= geom.left() + margin else geom.left() + margin
        max_y = geom.bottom() - self.height() - margin
        ty = max(geom.top() + margin, min(max_y, ty)) if max_y >= geom.top() + margin else geom.top() + margin
        return QPoint(tx, ty)

    # -------------------------------------------------------------- istatistik
    def _load_stats(self) -> None:
        self._stats = None
        self._stats_ok = False
        provider = self._stats_provider
        if not callable(provider):
            return
        try:
            raw = provider()
        except Exception:
            return
        normalized = normalize_stall_stats(raw)
        if normalized is None:
            return
        self._stats = normalized
        self._stats_ok = True

    def _on_stats_tick(self) -> None:
        if self.current_section != "performance" or not self.isVisible():
            self._stats_timer.stop()
            return
        self._load_stats()
        self.update()

    def _sync_stats_timer(self) -> None:
        should_run = self.isVisible() and self.current_section == "performance"
        if should_run and not self._stats_timer.isActive():
            self._stats_timer.start()
        elif not should_run and self._stats_timer.isActive():
            self._stats_timer.stop()

    def performance_strings(self) -> Dict[str, str]:
        """Performans kartında çizilen metinler (testler de bunu okur)."""
        if not self._stats_ok or self._stats is None:
            return {"count": "—", "worst": "—", "status": STALL_UNAVAILABLE}
        count = int(self._stats["count"])
        worst = int(self._stats["worst_ms"])
        if count == 0:
            return {"count": "0", "worst": "—", "status": STALL_NONE}
        return {"count": str(count), "worst": format_ms(worst), "status": ""}

    def performance_rows(self) -> List[Dict[str, Any]]:
        """En yeni önce, en çok 8 satır; renk eşikleriyle."""
        if not self._stats_ok or self._stats is None:
            return []
        rows: List[Dict[str, Any]] = []
        for entry in reversed(self._stats["last"][-8:]):
            try:
                stamp = time.strftime("%H:%M:%S", time.localtime(entry["time"]))
            except (ValueError, OSError, OverflowError):
                stamp = "—"
            ms = int(entry["ms"])
            rows.append(
                {
                    "time": stamp,
                    "ms": ms,
                    "ms_text": format_ms(ms),
                    "top": str(entry.get("top") or "—"),
                    "color": stall_color(ms),
                }
            )
        return rows

    def _card_checked(self, key: str) -> bool:
        cards = self.working_settings.get("cards")
        if not isinstance(cards, dict):
            return True
        return bool(cards.get(key, True))

    # ---------------------------------------------------------------- olaylar
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_and_close()
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        if self.current_section == "performance":
            self._load_stats()
        self._sync_stats_timer()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._stats_timer.stop()
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._stats_timer.stop()
        super().closeEvent(event)

    def _hide_animated(self) -> None:
        if self.isVisible():
            self._last_close_time = time.monotonic()
            ps.animate_out(self)
        else:
            self.hide()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = QPointF(event.position())

        if self._close_rect.isNull():
            self._close_rect = QRectF(
                float(self.width()) - 40.0, 24.0, ps.CLOSE_SZ, ps.CLOSE_SZ
            )
        if self._close_rect.contains(pos):
            self.cancel_and_close()
            return

        if self._get_apply_button_rect().contains(pos):
            self.apply_and_close()
            return
        if self._get_cancel_button_rect().contains(pos):
            self.cancel_and_close()
            return

        for s_rect, sid, _ in self._get_sidebar_items():
            if s_rect.contains(pos):
                self.switch_section(sid)
                return

        for r, kind, extra in self._content_hit_boxes:
            if not r.contains(pos):
                continue
            if kind == "toggle_style":
                self.working_settings["style"] = str(extra)
                self.update()
                return
            if kind == "toggle_setting":
                default_val = SETTING_DEFAULTS.get(str(extra), False)
                cur_val = bool(self.working_settings.get(extra, default_val))
                self.working_settings[extra] = not cur_val
                self.update()
                return
            if kind == "toggle_card":
                cards = self.working_settings.setdefault("cards", {})
                cur_val = bool(cards.get(extra, True))
                cards[extra] = not cur_val
                self.update()
                return
            if kind == "remove_pin":
                pins = self.working_settings.get("pinned", [])
                if 0 <= extra < len(pins):
                    del pins[extra]
                    self.update()
                return
            if kind == "open_logs":
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

        if self._close_rect.contains(pos):
            self._hover_btn = "close"

        for s_rect, sid, _ in self._get_sidebar_items():
            if s_rect.contains(pos):
                self._hover_section = sid
                break

        if self._get_apply_button_rect().contains(pos):
            self._hover_btn = "apply"
        elif self._get_cancel_button_rect().contains(pos):
            self._hover_btn = "cancel"

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
        if self.current_section == "pinned":
            delta = event.angleDelta().y()
            self._scroll_offset_y = min(0.0, self._scroll_offset_y + delta * 0.4)
            min_offset = min(0.0, self._pinned_inner_h - self._pinned_content_h)
            self._scroll_offset_y = max(min_offset, self._scroll_offset_y)
            self.update()
            event.accept()
            return
        if self.current_section == "cards":
            delta = event.angleDelta().y()
            self._scroll_offset_y = min(0.0, self._scroll_offset_y + delta * 0.4)
            min_offset = min(0.0, self._cards_view_h - self._cards_total_h)
            self._scroll_offset_y = max(min_offset, self._scroll_offset_y)
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def _on_open_logs_clicked(self) -> None:
        try:
            log_p = get_log_path()
            folder = log_p.parent
            if folder.exists():
                os.startfile(str(folder))
        except Exception:
            pass

    # -------------------------------------------------------------- yerleşim
    def _get_sidebar_items(self) -> List[Tuple[QRectF, str, str]]:
        items: List[Tuple[QRectF, str, str]] = []
        top_y = 60.0
        row_h = 36.0
        gap = 4.0
        for i, (sid, title) in enumerate(SECTIONS):
            y = top_y + i * (row_h + gap)
            items.append((QRectF(12.0, y, SIDEBAR_WIDTH - 24.0, row_h), sid, title))
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

    def _content_rect(self) -> QRectF:
        return QRectF(
            SIDEBAR_WIDTH + 24.0,
            24.0,
            float(self.width()) - SIDEBAR_WIDTH - 48.0,
            float(self.height()) - BOTTOM_BAR_HEIGHT - 36.0,
        )

    # ------------------------------------------------------------ görüntü
    def render_to_image(self, dpr: float = 2.0) -> QImage:
        w_phys = max(1, int(round(float(self.width()) * dpr)))
        h_phys = max(1, int(round(float(self.height()) * dpr)))
        img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_all(p)
        finally:
            p.end()
        return img

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._paint_all(p)
        finally:
            p.end()

    def _paint_all(self, p: QPainter) -> None:
        self._content_hit_boxes.clear()
        self._toggle_rects.clear()
        self._toggle_checked.clear()

        w = float(self.width())
        h = float(self.height())
        ps.draw_panel_shell(p, QRectF(0.0, 0.0, w, h))
        shell = ps.rounded(QRectF(0.0, 0.0, w, h), ps.R_PANEL)

        p.save()
        p.setClipPath(shell)
        p.fillRect(QRectF(0.0, 0.0, SIDEBAR_WIDTH, h), QColor(ps.TILE_BG.red(), ps.TILE_BG.green(), ps.TILE_BG.blue(), 120))
        p.setPen(QPen(ps.FOOTER_LINE, 1.0))
        p.drawLine(QPointF(0.0, h - BOTTOM_BAR_HEIGHT + 0.5), QPointF(w, h - BOTTOM_BAR_HEIGHT + 0.5))
        p.restore()

        p.setFont(ps.f_title())
        p.setPen(ps.TEXT)
        p.drawText(
            QRectF(16.0, 16.0, SIDEBAR_WIDTH - 32.0, 28.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Ayarlar",
        )

        self._paint_sidebar(p)

        content = self._content_rect()
        p.save()
        p.setClipRect(content)
        hdr = ps.draw_header(
            p,
            QRectF(content.x(), content.y(), content.width(), ps.HEADER_H),
            dict(SECTIONS).get(self.current_section, ""),
            chip=None,
            close_hover=(self._hover_btn == "close"),
        )
        close = hdr.get("close")
        self._close_rect = QRectF(close) if isinstance(close, QRectF) else QRectF()
        self._paint_section(p, content)
        p.restore()

        self._paint_bottom_bar(p)

    def _paint_sidebar(self, p: QPainter) -> None:
        for rect, sid, title in self._get_sidebar_items():
            is_active = self.current_section == sid
            is_hover = self._hover_section == sid

            if is_active:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.BUTTON_HOVER)
                p.drawPath(ps.rounded(rect, ps.R_BUTTON))
                p.setBrush(ps.ACCENT)
                p.drawPath(ps.rounded(QRectF(rect.left() - 6.0, rect.top() + 9.0, 3.0, 18.0), 1.5))
            elif is_hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ps.BUTTON_BG)
                p.drawPath(ps.rounded(rect, ps.R_BUTTON))

            p.setFont(ps.font(11.0, QFont.Weight.Medium if is_active else QFont.Weight.Normal))
            p.setPen(ps.TEXT if is_active else ps.TEXT_BODY)
            fm = QFontMetricsF(p.font())
            text = fm.elidedText(title, Qt.TextElideMode.ElideRight, max(10.0, rect.width() - 20.0))
            p.drawText(
                QRectF(rect.left() + 10.0, rect.top(), rect.width() - 16.0, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )

    def _paint_bottom_bar(self, p: QPainter) -> None:
        h = float(self.height())
        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        p.drawText(
            QRectF(20.0, h - BOTTOM_BAR_HEIGHT, SIDEBAR_WIDTH - 24.0, BOTTOM_BAR_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Şerit",
        )

        r_cancel = self._get_cancel_button_rect()
        hover_cancel = self._hover_btn == "cancel"
        p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
        p.setBrush(ps.BUTTON_HOVER if hover_cancel else ps.BUTTON_BG)
        p.drawPath(ps.rounded(r_cancel.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_BUTTON))
        p.setFont(ps.font(11.5, QFont.Weight.Medium))
        p.setPen(ps.TEXT if hover_cancel else ps.TEXT_BTN)
        p.drawText(r_cancel, Qt.AlignmentFlag.AlignCenter, "Vazgeç")

        r_apply = self._get_apply_button_rect()
        hover_apply = self._hover_btn == "apply"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.ACCENT.lighter(112) if hover_apply else ps.ACCENT)
        p.drawPath(ps.rounded(r_apply.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_BUTTON))
        p.setFont(ps.font(11.5, QFont.Weight.DemiBold))
        p.setPen(ps.TEXT)
        p.drawText(r_apply, Qt.AlignmentFlag.AlignCenter, "Uygula")

    # ------------------------------------------------------------- bölümler
    def _paint_section(self, p: QPainter, area: QRectF) -> None:
        x = area.x()
        w = area.width()
        y = area.y() + ps.HEADER_H + ps.GAP
        bottom = area.bottom()

        if self.current_section == "appearance":
            self._paint_appearance(p, x, y, w)
        elif self.current_section == "cards":
            self._paint_cards(p, x, y, w, max(0.0, bottom - y))
        elif self.current_section == "pinned":
            self._paint_pinned(p, x, y, w, max(0.0, bottom - y))
        elif self.current_section == "alerts":
            self._paint_alerts(p, x, y, w)
        elif self.current_section == "performance":
            self._paint_performance(p, x, y, w)
        elif self.current_section == "about":
            self._paint_about(p, x, y, w)

    @staticmethod
    def _card_height(row_heights: List[float]) -> float:
        seps = max(0, len(row_heights) - 1)
        return ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + sum(row_heights) + seps

    @staticmethod
    def _paint_separator(p: QPainter, x: float, y: float, w: float) -> None:
        p.setPen(QPen(ps.FOOTER_LINE, 1.0))
        p.drawLine(QPointF(x, y + 0.5), QPointF(x + w, y + 0.5))

    def _draw_row(
        self,
        p: QPainter,
        rect: QRectF,
        title: str,
        subtitle: Optional[str] = None,
        checked: Optional[bool] = None,
        radio: bool = False,
        kind: Optional[str] = None,
        extra: Any = None,
    ) -> None:
        key = f"{kind}:{extra}" if kind else ""
        hovered = bool(key) and self._hover_item_key == key

        if hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ps.BUTTON_BG)
            p.drawPath(ps.rounded(rect.adjusted(0.0, 1.0, 0.0, -1.0), ps.R_BUTTON))

        control_w = 0.0
        if checked is not None:
            control_w = 34.0 if radio else 56.0
        text_left = rect.left() + 10.0
        text_w = max(0.0, rect.width() - 20.0 - control_w)

        if subtitle:
            block_h = min(rect.height(), 38.0)
            ty = rect.top() + (rect.height() - block_h) / 2.0
            p.setFont(ps.f_body())
            p.setPen(ps.TEXT)
            fm_t = QFontMetricsF(p.font())
            p.drawText(
                QRectF(text_left, ty, text_w, 20.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_t.elidedText(title, Qt.TextElideMode.ElideRight, max(10.0, text_w)),
            )
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            fm_s = QFontMetricsF(p.font())
            p.drawText(
                QRectF(text_left, ty + 20.0, text_w, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_s.elidedText(subtitle, Qt.TextElideMode.ElideRight, max(10.0, text_w)),
            )
        else:
            p.setFont(ps.f_body())
            p.setPen(ps.TEXT)
            fm_t = QFontMetricsF(p.font())
            p.drawText(
                QRectF(text_left, rect.top(), text_w, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_t.elidedText(title, Qt.TextElideMode.ElideRight, max(10.0, text_w)),
            )

        if checked is not None:
            if radio:
                r_radio = QRectF(rect.right() - 32.0, rect.center().y() - 9.0, 18.0, 18.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(ps.ACCENT if checked else ps.TEXT_MUTED, 1.5))
                p.drawEllipse(r_radio)
                if checked:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(ps.ACCENT)
                    p.drawPath(ps.rounded(QRectF(r_radio.x() + 4.5, r_radio.y() + 4.5, 9.0, 9.0), 4.5))
                if key:
                    self._toggle_rects[key] = r_radio
            else:
                r_toggle = QRectF(rect.right() - 52.0, rect.center().y() - 10.0, 40.0, 20.0)
                _paint_toggle_shape(p, r_toggle, bool(checked), hovered, False)
                if key:
                    self._toggle_rects[key] = r_toggle
            if key:
                self._toggle_checked[key] = bool(checked)

        if kind:
            self._content_hit_boxes.append((QRectF(rect), kind, extra))

    # ------------------------------------------------------------- Görünüm
    def _paint_appearance(self, p: QPainter, x: float, y: float, w: float) -> None:
        cur_style = str(self.working_settings.get("style", "band"))
        is_band = cur_style != "pill"

        rows = [46.0, 46.0]
        card_h = self._card_height(rows)
        inner = ps.draw_card(p, QRectF(x, y, w, card_h), "Şerit düzeni")
        r1 = QRectF(inner.left(), inner.top(), inner.width(), rows[0])
        self._draw_row(
            p, r1, "Tam genişlik şerit", "Ekranın solundan sağına uzanan koyu taban şeridi",
            checked=is_band, radio=True, kind="toggle_style", extra="band",
        )
        self._paint_separator(p, inner.left(), r1.bottom(), inner.width())
        r2 = QRectF(inner.left(), r1.bottom() + 1.0, inner.width(), rows[1])
        self._draw_row(
            p, r2, "Ortada kapsül", "Yalnızca öğelerin etrafını saran yüzen kapsül",
            checked=not is_band, radio=True, kind="toggle_style", extra="pill",
        )

        y += card_h + ps.GAP
        rows2 = [52.0, 52.0]
        card2_h = self._card_height(rows2)
        inner2 = ps.draw_card(p, QRectF(x, y, w, card2_h), "Görev çubuğu")
        hide_tb = bool(self.working_settings.get("hide_taskbar", False))
        r3 = QRectF(inner2.left(), inner2.top(), inner2.width(), rows2[0])
        self._draw_row(
            p, r3, "Görev çubuğunu gizle", "Windows görev çubuğunu otomatik gizle",
            checked=hide_tb, kind="toggle_setting", extra="hide_taskbar",
        )
        self._paint_separator(p, inner2.left(), r3.bottom(), inner2.width())
        reserve_sp = bool(self.working_settings.get("reserve_space", True))
        r4 = QRectF(inner2.left(), r3.bottom() + 1.0, inner2.width(), rows2[1])
        self._draw_row(
            p, r4, "Ekran alanını ayır", "Pencereler şeridin altına girmesin",
            checked=reserve_sp, kind="toggle_setting", extra="reserve_space",
        )

    # -------------------------------------------------------------- Kartlar
    def _paint_cards(self, p: QPainter, x: float, y: float, w: float, max_h: float = 360.0) -> None:
        row_h = 44.0
        rows1 = [row_h] * len(CARD_DEFS)
        card1_h = self._card_height(rows1)
        rows2 = [row_h] * len(TOOL_DEFS)
        card2_h = self._card_height(rows2)
        total_h = card1_h + ps.GAP + card2_h
        self._cards_view_h = max_h
        self._cards_total_h = total_h

        min_offset = min(0.0, max_h - total_h)
        self._scroll_offset_y = max(min_offset, min(0.0, self._scroll_offset_y))

        p.save()
        p.setClipRect(QRectF(x, y, w, max_h))
        cy = y + self._scroll_offset_y

        inner = ps.draw_card(p, QRectF(x, cy, w, card1_h), "Gösterilecek kartlar")
        ry = inner.top()
        for idx, (key, title, subtitle) in enumerate(CARD_DEFS):
            rect = QRectF(inner.left(), ry, inner.width(), row_h)
            self._draw_row(
                p, rect, title, subtitle,
                checked=self._card_checked(key), kind="toggle_card", extra=key,
            )
            if idx < len(CARD_DEFS) - 1:
                self._paint_separator(p, inner.left(), rect.bottom(), inner.width())
            ry += row_h + 1.0

        cy += card1_h + ps.GAP
        inner2 = ps.draw_card(p, QRectF(x, cy, w, card2_h), "Akıllı araçlar")
        ry2 = inner2.top()
        for idx, (key, title, subtitle) in enumerate(TOOL_DEFS):
            rect = QRectF(inner2.left(), ry2, inner2.width(), row_h)
            def_val = SETTING_DEFAULTS.get(key, True)
            val = bool(self.working_settings.get(key, def_val))
            self._draw_row(
                p, rect, title, subtitle,
                checked=val, kind="toggle_setting", extra=key,
            )
            if idx < len(TOOL_DEFS) - 1:
                self._paint_separator(p, inner2.left(), rect.bottom(), inner2.width())
            ry2 += row_h + 1.0

        if total_h > max_h + 1.0:
            max_scr = total_h - max_h
            thumb_h = max(24.0, max_h * (max_h / total_h))
            thumb_y = y + (-self._scroll_offset_y / max_scr) * (max_h - thumb_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 65))
            p.drawPath(ps.rounded(QRectF(x + w - 4.0, thumb_y, 3.0, thumb_h), 1.5))

        p.restore()

    # --------------------------------------------------- Sabitlenen uygulamalar
    def _paint_pinned(self, p: QPainter, x: float, y: float, w: float, max_h: float) -> None:
        pins = self.working_settings.get("pinned", [])
        row_h = 44.0
        gap = 1.0
        content_h = len(pins) * (row_h + gap) - gap if pins else 0.0
        needed = ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + max(44.0, content_h)
        card_h = min(max_h, max(120.0, needed))
        inner = ps.draw_card(
            p, QRectF(x, y, w, card_h), f"Sabitlenen uygulamalar ({len(pins)})"
        )
        self._pinned_inner_h = inner.height()
        self._pinned_content_h = content_h

        if not pins:
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(inner.left(), inner.top(), inner.width(), inner.height()),
                Qt.AlignmentFlag.AlignCenter,
                "Henüz sabitlenmiş bir uygulama yok.",
            )
            return

        min_offset = min(0.0, inner.height() - content_h)
        self._scroll_offset_y = max(min_offset, min(0.0, self._scroll_offset_y))

        p.save()
        p.setClipRect(inner)
        cur_y = inner.top() + self._scroll_offset_y
        for idx, item in enumerate(pins):
            if not isinstance(item, dict):
                cur_y += row_h + gap
                continue
            if cur_y + row_h >= inner.top() and cur_y <= inner.bottom():
                r_row = QRectF(inner.left(), cur_y, inner.width(), row_h)
                key = f"remove_pin:{idx}"
                hovered = self._hover_item_key == key
                if hovered:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(ps.BUTTON_BG)
                    p.drawPath(ps.rounded(r_row.adjusted(0.0, 1.0, 0.0, -1.0), ps.R_BUTTON))

                name = str(item.get("name") or "Uygulama")
                exe = str(item.get("path") or "")

                icon_rect = QRectF(inner.left() + 9.0, cur_y + (row_h - 24.0) / 2.0, 24.0, 24.0)
                drawn = False
                if exe:
                    try:
                        pix = winapi.app_icon(exe, 32)
                        if isinstance(pix, QPixmap) and not pix.isNull():
                            theme.draw_icon_crisp(p, pix, icon_rect)
                            drawn = True
                    except Exception:
                        drawn = False
                if not drawn:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 18))
                    p.drawPath(ps.rounded(icon_rect, 4.0))
                    p.setFont(ps.font(10.0, QFont.Weight.Bold))
                    p.setPen(ps.TEXT)
                    p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, name[:1].upper())

                btn_w = 58.0
                btn_h = 24.0
                btn_rect = QRectF(inner.right() - btn_w - 8.0, cur_y + (row_h - btn_h) / 2.0, btn_w, btn_h)

                text_left = icon_rect.right() + 9.0
                text_w = max(10.0, btn_rect.left() - 8.0 - text_left)
                p.setFont(ps.f_body())
                p.setPen(ps.TEXT)
                fm_name = QFontMetricsF(p.font())
                p.drawText(
                    QRectF(text_left, cur_y + 5.0, text_w, 18.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    fm_name.elidedText(name, Qt.TextElideMode.ElideRight, text_w),
                )
                p.setFont(ps.f_small())
                p.setPen(ps.TEXT_MUTED)
                fm_path = QFontMetricsF(p.font())
                p.drawText(
                    QRectF(text_left, cur_y + 23.0, text_w, 16.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    fm_path.elidedText(exe or "—", Qt.TextElideMode.ElideMiddle, text_w),
                )

                p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
                p.setBrush(ps.BUTTON_HOVER if hovered else ps.BUTTON_BG)
                p.drawPath(ps.rounded(btn_rect, ps.R_BUTTON))
                p.setFont(ps.font(11.0, QFont.Weight.Medium))
                p.setPen(ps.TEXT if hovered else ps.TEXT_BTN)
                p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "Kaldır")

                self._content_hit_boxes.append((btn_rect, "remove_pin", idx))

            if idx < len(pins) - 1:
                self._paint_separator(p, inner.left(), cur_y + row_h, inner.width())
            cur_y += row_h + gap

        p.restore()

    # ------------------------------------------------------------- Uyarılar
    def _paint_alerts(self, p: QPainter, x: float, y: float, w: float) -> None:
        card_h = self._card_height([52.0])
        inner = ps.draw_card(p, QRectF(x, y, w, card_h), "Sistem ve kullanım bildirimleri")
        alerts_enabled = bool(self.working_settings.get("alerts_enabled", True))
        rect = QRectF(inner.left(), inner.top(), inner.width(), 52.0)
        self._draw_row(
            p, rect, "Uyarıları etkinleştir",
            "Kota, döviz ve bellek uyarıları",
            checked=alerts_enabled, kind="toggle_setting", extra="alerts_enabled",
        )

    # ----------------------------------------------------------- Performans
    def _paint_performance(self, p: QPainter, x: float, y: float, w: float) -> None:
        texts = self.performance_strings()

        card1_h = ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + 72.0
        inner = ps.draw_card(p, QRectF(x, y, w, card1_h), "Arayüz donmaları")
        col_w = inner.width() / 2.0

        f_label = ps.f_small()
        f_num = ps.font(26.0, QFont.Weight.Bold, tabular=True)

        p.setFont(f_label)
        p.setPen(ps.TEXT_MUTED)
        p.drawText(
            QRectF(inner.left(), inner.top(), col_w - 8.0, 14.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Bu oturumda",
        )
        p.drawText(
            QRectF(inner.left() + col_w, inner.top(), col_w, 14.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "En uzun",
        )

        count = texts["count"]
        worst = texts["worst"]
        p.setFont(f_num)
        p.setPen(ps.TEXT)
        p.drawText(
            QRectF(inner.left(), inner.top() + 16.0, col_w - 8.0, 36.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            count,
        )
        if self._stats_ok and self._stats is not None and int(self._stats["count"]) > 0:
            worst_col = stall_color(int(self._stats["worst_ms"]))
        else:
            worst_col = ps.TEXT_LABEL
        p.setPen(worst_col)
        p.drawText(
            QRectF(inner.left() + col_w, inner.top() + 16.0, col_w, 36.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            worst,
        )

        status = texts["status"]
        if status:
            p.setFont(f_label)
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(inner.left(), inner.top() + 54.0, inner.width(), 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                status,
            )

        y += card1_h + ps.GAP

        rows = self.performance_rows()
        if rows:
            rows_h = len(rows) * STALL_ROW_H + (len(rows) - 1)
        else:
            rows_h = 18.0
        card2_h = ps.CARD_PAD * 2 + 15.0 + ps.CARD_GAP + rows_h
        right = f"son {len(rows)}" if rows else None
        inner2 = ps.draw_card(p, QRectF(x, y, w, card2_h), "Son donmalar", right)

        if not self._stats_ok:
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(inner2.left(), inner2.top(), inner2.width(), 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "—",
            )
        elif not rows:
            p.setFont(ps.f_small())
            p.setPen(ps.TEXT_MUTED)
            p.drawText(
                QRectF(inner2.left(), inner2.top(), inner2.width(), 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "Kayıt yok",
            )
        else:
            ry = inner2.top()
            for idx, row in enumerate(rows):
                r_row = QRectF(inner2.left(), ry, inner2.width(), STALL_ROW_H)
                time_w = 58.0
                ms_w = 66.0

                p.setFont(ps.f_small())
                p.setPen(ps.TEXT_MUTED)
                p.drawText(
                    QRectF(r_row.left(), r_row.top(), time_w, r_row.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    row["time"],
                )

                p.setFont(ps.font(11.5, QFont.Weight.Medium, tabular=True))
                p.setPen(row["color"])
                p.drawText(
                    QRectF(r_row.left() + time_w + 2.0, r_row.top(), ms_w, r_row.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    row["ms_text"],
                )

                top_left = r_row.left() + time_w + 2.0 + ms_w + 6.0
                top_w = max(10.0, r_row.right() - top_left)
                p.setFont(ps.f_small())
                p.setPen(ps.TEXT_MUTED)
                fm_top = QFontMetricsF(p.font())
                p.drawText(
                    QRectF(top_left, r_row.top(), top_w, r_row.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    fm_top.elidedText(str(row["top"]), Qt.TextElideMode.ElideMiddle, top_w),
                )

                if idx < len(rows) - 1:
                    self._paint_separator(p, inner2.left(), r_row.bottom() - 0.5, inner2.width())
                ry += STALL_ROW_H + 1.0

        y += card2_h + 8.0
        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        fm_note = QFontMetricsF(p.font())
        p.drawText(
            QRectF(x, y, w, 16.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_note.elidedText(STALL_NOTE, Qt.TextElideMode.ElideRight, w),
        )

    # ------------------------------------------------------------- Hakkında
    def _paint_about(self, p: QPainter, x: float, y: float, w: float) -> None:
        card_h = 140.0
        inner = ps.draw_card(p, QRectF(x, y, w, card_h), "Uygulama bilgisi")

        p.setFont(ps.f_body())
        p.setPen(ps.TEXT)
        p.drawText(
            QRectF(inner.left(), inner.top(), inner.width(), 20.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Şerit Dock",
        )

        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        p.drawText(
            QRectF(inner.left(), inner.top() + 20.0, inner.width(), 16.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Windows 11 için görev çubuğu ve bilgi şeridi",
        )

        p.setPen(QPen(ps.FOOTER_LINE, 1.0))
        p.drawLine(
            QPointF(inner.left(), inner.top() + 44.0),
            QPointF(inner.right(), inner.top() + 44.0),
        )

        label_w = 62.0
        row1_y = inner.top() + 52.0
        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        p.drawText(
            QRectF(inner.left(), row1_y, label_w, 18.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Sürüm",
        )
        p.setPen(ps.TEXT_BODY)
        p.drawText(
            QRectF(inner.left() + label_w, row1_y, inner.width() - label_w, 18.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._git_ver,
        )

        row2_y = row1_y + 22.0
        p.setFont(ps.f_small())
        p.setPen(ps.TEXT_MUTED)
        p.drawText(
            QRectF(inner.left(), row2_y, label_w, 18.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Günlük",
        )
        log_str = str(get_log_path())
        avail = max(10.0, inner.width() - label_w)
        fm_log = QFontMetricsF(ps.f_small())
        p.setPen(ps.TEXT_BODY)
        p.drawText(
            QRectF(inner.left() + label_w, row2_y, avail, 18.0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_log.elidedText(log_str, Qt.TextElideMode.ElideMiddle, avail),
        )

        y += card_h + 14.0
        btn_rect = QRectF(x, y, 150.0, 32.0)
        hovered = self._hover_item_key == "open_logs:btn"
        p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
        p.setBrush(ps.BUTTON_HOVER if hovered else ps.BUTTON_BG)
        p.drawPath(ps.rounded(btn_rect.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_BUTTON))
        p.setFont(ps.font(11.5, QFont.Weight.Medium))
        p.setPen(ps.TEXT if hovered else ps.TEXT_BTN)
        p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "Log klasörünü aç")
        self._content_hit_boxes.append((btn_rect, "open_logs", "btn"))


def open_settings(
    settings: dict,
    on_apply: Callable[[dict], None],
    parent: Optional[QWidget] = None,
    *,
    stats_provider: Optional[Callable[[], dict]] = None,
) -> SettingsWindow:
    """Pencereyi oluşturur ve ortak panel hareketiyle gösterir; diske yazmaz."""
    win = SettingsWindow(
        settings=settings,
        on_apply=on_apply,
        parent=parent,
        stats_provider=stats_provider,
    )
    win.show_for()
    return win
