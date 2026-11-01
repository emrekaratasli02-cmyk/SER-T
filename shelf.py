"""Şerit dosya rafı (v25): Yoink benzeri geçici dosya rafı.

Parçalar:
  * ShelfStore        — saf Python (Qt yok), kilitli, atomik JSON; raftaki dosya/klasör listesi.
  * DownloadsWatcher  — İndirilenler klasöründe biten yeni dosyaları bulur (işçi iş parçacığından çağrılır).
  * draw_shelf_icon   — bant simgesi (ataç + sayı rozeti), saf QPainter.
  * ShelfPanel        — 352 px açılır panel (panel_style kiti), satır sürükle-bırak, iğne, kaldır.

Canlı etki korumaları: pano yazımı, os.startfile ve gerçek QDrag.exec testlerde çalışmaz
(SERIT_ALLOW_REAL_UI=1 ile açılır). Hiçbir değer uydurulmaz: boyut/yaş gerçek dosya durumundan gelir.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QFileInfo, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QFileIconProvider, QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import logpath  # noqa: E402
import panel_style as ps  # noqa: E402

try:
    import clipboard  # noqa: E402
except ImportError:
    clipboard = None

try:
    import winapi  # noqa: E402
except Exception:  # pragma: no cover
    winapi = None

try:
    from PySide6.QtSvg import QSvgRenderer  # noqa: E402
except Exception:  # pragma: no cover
    QSvgRenderer = None

SHELF_FILE_NAME = "shelf.json"
DOWNLOAD_KEEP_S = 600
MAX_ITEMS = 30
SHELF_ICON_W = 28.0

ROW_H = 48.0
MAX_VISIBLE_ROWS = 6
EMPTY_H = 84.0
OVERLINE_H = 25.0
BTN_SZ = 24.0

_TEMP_EXTS = (".crdownload", ".part", ".partial", ".tmp", ".download")
# kendiliğinden gelen öğeler (indirilen dosya, ekran görüntüsü) iğnelenmezse DOWNLOAD_KEEP_S sonra düşer
AUTO_SOURCES = ("download", "screenshot")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


# ============================================================================ yardımcılar
def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _real_ui_allowed() -> bool:
    """Pano/startfile/QDrag gibi canlı etkiler: testte kapalı, SERIT_ALLOW_REAL_UI=1 ile açık."""
    if os.environ.get("SERIT_ALLOW_REAL_UI") == "1":
        return True
    return not logpath.is_running_under_test()


def fmt_size(n: Any, is_dir: bool = False) -> str:
    """Türkçe boyut: '214 KB', '1,2 MB'. Klasör için 'Klasör'."""
    if is_dir:
        return "Klasör"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v < 0:
        return "—"
    if v < 1024:
        return f"{int(v)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        v /= 1024.0
        if v < 1024.0 or unit == "TB":
            if unit != "KB" and v < 10:
                return f"{v:.1f}".replace(".", ",") + f" {unit}"
            return f"{int(round(v))} {unit}"
    return "—"


def fmt_age(added: float, now: Optional[float] = None) -> str:
    """'az önce', '2 dk önce', '3 sa önce', '2 gün önce'."""
    now = time.time() if now is None else now
    d = max(0.0, now - float(added))
    if d < 60:
        return "az önce"
    if d < 3600:
        return f"{int(d // 60)} dk önce"
    if d < 86400:
        return f"{int(d // 3600)} sa önce"
    return f"{int(d // 86400)} gün önce"


# ============================================================================ ShelfStore
class ShelfStore:
    """Raf içeriği. Saf Python, iş parçacığı güvenli, atomik kayıt (tmp + os.replace)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else logpath.get_cache_file(SHELF_FILE_NAME)
        self._lock = threading.RLock()
        self._items: List[Dict[str, Any]] = []
        self._load()

    # -- kalıcılık
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            lst = raw.get("items", []) if isinstance(raw, dict) else []
            out: List[Dict[str, Any]] = []
            seen = set()
            for it in lst:
                if not isinstance(it, dict) or not isinstance(it.get("path"), str) or not it["path"]:
                    continue
                k = _key(it["path"])
                if k in seen:
                    continue
                seen.add(k)
                out.append({
                    "path": it["path"],
                    "name": str(it.get("name") or os.path.basename(it["path"]) or it["path"]),
                    "size": int(it.get("size") or 0),
                    "added": float(it.get("added") or 0.0),
                    "pinned": bool(it.get("pinned", False)),
                    "source": str(it.get("source") or "drop"),
                })
            self._items = out
        except Exception:
            self._items = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"version": 1, "items": self._items}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            pass

    # -- okuma
    def _prune_locked(self) -> bool:
        keep = [it for it in self._items if os.path.exists(it["path"])]
        if len(keep) != len(self._items):
            self._items = keep
            return True
        return False

    def items(self) -> List[Dict[str, Any]]:
        with self._lock:
            if self._prune_locked():
                self._save()
            return [dict(it) for it in self._items]

    def count(self) -> int:
        return len(self.items())

    # -- yazma
    def add_paths(self, paths: List[str], source: str = "drop") -> int:
        n = 0
        with self._lock:
            for p in reversed(list(paths or [])):
                if not p or not os.path.exists(p):
                    continue
                ap = os.path.normpath(os.path.abspath(p))
                k = _key(ap)
                pinned = False
                for i, it in enumerate(self._items):
                    if _key(it["path"]) == k:
                        pinned = it["pinned"]
                        del self._items[i]
                        break
                isdir = os.path.isdir(ap)
                try:
                    size = 0 if isdir else int(os.path.getsize(ap))
                except OSError:
                    size = 0
                self._items.insert(0, {
                    "path": ap,
                    "name": os.path.basename(ap) or ap,
                    "size": size,
                    "added": time.time(),
                    "pinned": pinned,
                    "source": source,
                })
                n += 1
            while len(self._items) > MAX_ITEMS:
                idx = next((i for i in range(len(self._items) - 1, -1, -1) if not self._items[i]["pinned"]), None)
                del self._items[idx if idx is not None else -1]
            if n:
                self._save()
        return n

    def remove(self, path: str) -> None:
        k = _key(path)
        with self._lock:
            before = len(self._items)
            self._items = [it for it in self._items if _key(it["path"]) != k]
            if len(self._items) != before:
                self._save()

    def toggle_pin(self, path: str) -> bool:
        k = _key(path)
        with self._lock:
            for it in self._items:
                if _key(it["path"]) == k:
                    it["pinned"] = not it["pinned"]
                    self._save()
                    return it["pinned"]
        return False

    def clear(self, keep_pinned: bool = True) -> None:
        with self._lock:
            self._items = [it for it in self._items if keep_pinned and it["pinned"]]
            self._save()

    def expire(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            keep = [it for it in self._items
                    if it["pinned"] or it["source"] not in AUTO_SOURCES or now - it["added"] <= DOWNLOAD_KEEP_S]
            changed = len(keep) != len(self._items)
            if changed:
                self._items = keep
                self._save()
            return changed

    def on_dragged_out(self, path: str) -> None:
        k = _key(path)
        with self._lock:
            for it in self._items:
                if _key(it["path"]) == k:
                    if not it["pinned"]:
                        self.remove(path)
                    return


# ============================================================================ DownloadsWatcher
def _downloads_folder() -> str:
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0 and out.value:
            val = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return val
    except Exception:
        pass
    return str(Path.home() / "Downloads")


def screenshots_folder() -> str:
    """Windows Ekran görüntüleri klasörü (FOLDERID_Screenshots; Win+PrtSc ve Ekran Alıntısı Aracı buraya kaydeder)."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        g = GUID(0xB7BEDE81, 0xDF94, 0x4682, (ctypes.c_ubyte * 8)(0xA7, 0xD8, 0x57, 0xA5, 0x26, 0x20, 0xB8, 0x6F))
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0 and out.value:
            val = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return val
    except Exception:
        pass
    return str(Path.home() / "Pictures" / "Screenshots")


class DownloadsWatcher:
    """İndirilenler klasöründe YENİ ve TAMAMLANMIŞ dosyaları bulur. Qt yok; havuz iş parçacığından çağrılır."""

    def __init__(self, folder: Optional[str] = None, exts: Optional[tuple] = None) -> None:
        self._folder = folder or _downloads_folder()
        self._exts = tuple(e.lower() for e in exts) if exts else None   # ör. yalnız resimler
        self._lock = threading.Lock()
        self._baselined = False
        self._known: Dict[str, tuple] = {}
        self._pending: Dict[str, tuple] = {}

    @property
    def folder(self) -> str:
        return self._folder

    def _scan(self) -> Dict[str, tuple]:
        out: Dict[str, tuple] = {}
        try:
            with os.scandir(self._folder) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            continue
                        if e.name.lower().endswith(_TEMP_EXTS):
                            continue
                        if self._exts is not None and not e.name.lower().endswith(self._exts):
                            continue
                        st = e.stat()
                        if getattr(st, "st_file_attributes", 0) & 0x6:   # hidden | system
                            continue
                        out[e.path] = (st.st_size, st.st_mtime_ns)
                    except OSError:
                        continue
        except OSError:
            pass
        return out

    def poll(self) -> List[str]:
        with self._lock:
            cur = self._scan()
            if not self._baselined:
                self._baselined = True
                self._known = dict(cur)
                return []
            found: List[str] = []
            for path, sig in cur.items():
                if self._known.get(path) == sig:
                    continue
                if self._pending.get(path) == sig:
                    found.append(path)
                    self._known[path] = sig
                    self._pending.pop(path, None)
                else:
                    self._pending[path] = sig
            for path in list(self._known):
                if path not in cur:
                    del self._known[path]
            for path in list(self._pending):
                if path not in cur:
                    del self._pending[path]
            return found


# ============================================================================ bant simgesi
_CLIP_D = ("M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.9-8.9a3.3 3.3 0 0 1 4.7 4.7l-8.9 8.9"
           "a1.7 1.7 0 0 1-2.4-2.4l8.2-8.2")
_PIN_D = "M14 3l7 7-2 1-3-1-4 4 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 4-4-1-3z"
_SVG_CACHE: Dict[tuple, QPixmap] = {}


def _svg_pixmap(kind: str, color: QColor, size: float, dpr: float) -> QPixmap:
    key = (kind, color.rgba(), round(size, 2), round(dpr, 3))
    pm = _SVG_CACHE.get(key)
    if pm is not None:
        return pm
    col = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
    op = f"{color.alphaF():.3f}"
    if kind == "clip":
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
               f'stroke="{col}" stroke-opacity="{op}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{_CLIP_D}"/></svg>')
    else:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
               f'fill="{col}" fill-opacity="{op}"><path d="{_PIN_D}"/></svg>')
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    if QSvgRenderer is not None:
        r = QSvgRenderer(svg.encode("utf-8"))
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r.render(qp, QRectF(0, 0, px, px))
        qp.end()
    pm.setDevicePixelRatio(dpr)
    _SVG_CACHE[key] = pm
    return pm


def _device_dpr(p: QPainter) -> float:
    try:
        return max(1.0, float(p.device().devicePixelRatioF()))
    except Exception:
        return 1.0


def draw_shelf_icon(p: QPainter, rect: QRectF, state: str, count: int, hover: bool = False) -> None:
    """28x28 yuvarlak kutu (rect içinde ortalı) + ataç; sayı > 0 ise sağ üstte mavi rozet."""
    if state not in ("idle", "over", "open"):
        state = "idle"
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    box = QRectF(rect.center().x() - SHELF_ICON_W / 2.0, rect.center().y() - SHELF_ICON_W / 2.0,
                 SHELF_ICON_W, SHELF_ICON_W)
    if state == "over":
        p.setBrush(QColor(110, 168, 254, 46))                     # rgba(110,168,254,.18)
        p.setPen(QPen(ps.ACCENT, 1.5))
        p.drawRoundedRect(box.adjusted(-0.75, -0.75, 0.75, 0.75), 8.75, 8.75)
        glyph = QColor(ps.ACCENT)
    elif state == "open":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))                     # .07
        p.drawRoundedRect(box, 8.0, 8.0)
        glyph = QColor(255, 255, 255)
    else:
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 13))
            p.drawRoundedRect(box, 8.0, 8.0)
        glyph = QColor(255, 255, 255, 217 if hover else 140)      # .55 (hover .85)
    pm = _svg_pixmap("clip", glyph, 18.0, _device_dpr(p))
    p.drawPixmap(QPointF(box.center().x() - 9.0, box.center().y() - 9.0), pm)

    if count and count > 0:
        txt = "99+" if count > 99 else str(int(count))
        f = ps.font(10.0, QFont.Weight.Bold, tabular=True)
        tw = QFontMetricsF(f).horizontalAdvance(txt)
        bw = max(16.0, tw + 8.0)
        br = QRectF(box.left() + 18.0, box.top() - 6.0, bw, 16.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.ACCENT)
        p.drawRoundedRect(br, 8.0, 8.0)
        p.setFont(f)
        p.setPen(QColor(0x0D, 0x0F, 0x13))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, txt)
    p.restore()


# ============================================================================ dosya türü simgesi
_ICON_PROVIDER: Optional[QFileIconProvider] = None
_TYPE_ICON_CACHE: Dict[tuple, QPixmap] = {}


def type_icon(path: str, is_dir: bool, dpr: float) -> QPixmap:
    """QFileIconProvider simgesi, uzantı başına önbellekli (yalnız GUI iş parçacığı)."""
    global _ICON_PROVIDER
    ext = "<dir>" if is_dir else os.path.splitext(path)[1].lower()
    key = (ext, round(dpr, 3))
    pm = _TYPE_ICON_CACHE.get(key)
    if pm is not None:
        return pm
    if _ICON_PROVIDER is None:
        _ICON_PROVIDER = QFileIconProvider()
    px = int(round(28 * dpr))
    pm = QPixmap()
    try:
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
        if not icon.isNull():
            pm = icon.pixmap(QSize(px, px))
            if not pm.isNull() and (pm.width() != px or pm.height() != px):
                # Windows kabuk simgesi istenenden büyük (256 px) dönebiliyor: satıra taşıyordu
                pm = pm.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception:
        pm = QPixmap()
    if pm.isNull():                                   # çevrimdışı/ekransız ortam: düz belge simgesi
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qp.setPen(QPen(QColor(255, 255, 255, 90), dpr))
        qp.setBrush(QColor(255, 255, 255, 20))
        qp.drawRoundedRect(QRectF(px * 0.2, px * 0.08, px * 0.6, px * 0.84), 3 * dpr, 3 * dpr)
        qp.end()
    pm.setDevicePixelRatio(dpr)
    _TYPE_ICON_CACHE[key] = pm
    return pm


# ============================================================================ ShelfPanel
class ShelfPanel(QWidget):
    """Dosya rafı paneli (352 px)."""

    WIDTH = int(ps.PANEL_W)
    changed = Signal()

    def __init__(self, store: ShelfStore, parent: Optional[QWidget] = None, clip_store: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._store = store
        self._clip_store = clip_store or (clipboard.ClipboardStore() if clipboard is not None else None)
        self._clip_monitor: Optional[Any] = None
        self._tab: str = "files"  # "files" veya "clips"
        self._clip_items: List[Dict[str, Any]] = []
        self._clip_row_rects: List[QRectF] = []
        self._clip_rm_rects: List[QRectF] = []
        self._sel_idx: int = 0
        self._items: List[Dict[str, Any]] = []
        self._rects: Dict[str, QRectF] = {}
        self._row_rects: List[QRectF] = []
        self._pin_rects: List[QRectF] = []
        self._rm_rects: List[QRectF] = []
        self._list_rect = QRectF()
        self._scroll = 0.0
        self._hover: Optional[str] = None
        self._press_idx: Optional[int] = None
        self._press_pos = QPointF()
        self._dragging = False
        self._closing = False
        self._anchor_global: Optional[QRectF] = None
        self._last_close_time = 0.0
        self._copy_note: Optional[str] = None
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._on_anchor_timeout)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._clear_note)
        # testler için: koruma yolunun çalıştığını gösteren izler
        self.guard_log: List[str] = []
        self.refresh()

    @staticmethod
    def _draw_header_icon(p: QPainter, r: QRectF) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dpr = _device_dpr(p)
        pm = _svg_pixmap("clip", QColor(255, 255, 255, 230), 16.0, dpr)
        pw = pm.width() / dpr
        ph = pm.height() / dpr
        p.drawPixmap(QPointF(r.center().x() - pw / 2.0, r.center().y() - ph / 2.0), pm)
        p.restore()

    # ------------------------------------------------------------ yerleşim
    def _visible_rows(self) -> int:
        return min(len(self._items), MAX_VISIBLE_ROWS)

    def compute_height(self) -> int:
        if self._tab == "clips":
            rows = min(len(self._clip_items), 5)
            body = EMPTY_H if not self._clip_items else max(1, rows) * 52.0
        else:
            body = EMPTY_H if not self._items else self._visible_rows() * ROW_H
        card_h = 2 * ps.CARD_PAD + OVERLINE_H + body
        return int(round(ps.PAD + ps.HEADER_H + ps.GAP + card_h + ps.GAP + ps.FOOTER_H + ps.PAD))

    def _max_scroll(self) -> float:
        if self._tab == "clips":
            return max(0.0, len(self._clip_items) * 52.0 - min(len(self._clip_items), 5) * 52.0)
        return max(0.0, len(self._items) * ROW_H - self._visible_rows() * ROW_H)

    def _layout(self) -> None:
        w = float(self.width())
        cw = w - 2 * ps.PAD
        self._rects = {}
        self._row_rects, self._pin_rects, self._rm_rects = [], [], []
        self._clip_row_rects, self._clip_rm_rects = [], []
        y = ps.PAD
        hdr_rect = QRectF(ps.PAD, y, cw, ps.HEADER_H)
        self._rects["hdr"] = hdr_rect
        close_sz = ps.CLOSE_SZ
        self._rects["close"] = QRectF(hdr_rect.right() - close_sz, hdr_rect.center().y() - close_sz / 2.0, close_sz, close_sz)

        if self._clip_store is not None:
            tab_bar_w = 190.0
            tab_bar_h = 26.0
            tab_bar_r = QRectF(hdr_rect.left(), hdr_rect.center().y() - tab_bar_h / 2.0, tab_bar_w, tab_bar_h)
            tab_w = tab_bar_w / 2.0
            self._rects["tab_files"] = QRectF(tab_bar_r.left(), tab_bar_r.top(), tab_w, tab_bar_h)
            self._rects["tab_clips"] = QRectF(tab_bar_r.left() + tab_w, tab_bar_r.top(), tab_w, tab_bar_h)

        y += ps.HEADER_H + ps.GAP

        if self._tab == "clips":
            rows = min(len(self._clip_items), 5)
            body_h = EMPTY_H if not self._clip_items else max(1, rows) * 52.0
            card_h = 2 * ps.CARD_PAD + OVERLINE_H + body_h
            card_rect = QRectF(ps.PAD, y, cw, card_h)
            self._rects["card"] = card_rect
            inner = card_rect.adjusted(ps.CARD_PAD, ps.CARD_PAD, -ps.CARD_PAD, -ps.CARD_PAD)

            clear_label = self._copy_note or "Temizle"
            fm_ovr = QFontMetricsF(ps.font(10.5, QFont.Weight.DemiBold))
            clear_w = fm_ovr.horizontalAdvance(clear_label) + 12.0
            self._rects["copy"] = QRectF(inner.right() - clear_w, inner.top(), clear_w, 18.0)

            list_top = inner.top() + OVERLINE_H
            self._list_rect = QRectF(inner.left(), list_top, inner.width(), body_h)
            self._scroll = max(0.0, min(self._max_scroll(), self._scroll))

            for i in range(len(self._clip_items)):
                r = QRectF(inner.left(), list_top + i * 52.0 - self._scroll, inner.width(), 48.0)
                self._clip_row_rects.append(r)
                rm = QRectF(r.right() - 24.0, r.center().y() - 10.0, 20.0, 20.0)
                self._clip_rm_rects.append(rm)
        else:
            body_h = EMPTY_H if not self._items else self._visible_rows() * ROW_H
            card_h = 2 * ps.CARD_PAD + OVERLINE_H + body_h
            card_rect = QRectF(ps.PAD, y, cw, card_h)
            self._rects["card"] = card_rect

            inner = card_rect.adjusted(ps.CARD_PAD, ps.CARD_PAD, -ps.CARD_PAD, -ps.CARD_PAD)
            copy_label = self._copy_note or "Hepsini kopyala ›"
            fm_ovr = QFontMetricsF(ps.font(10.5, QFont.Weight.DemiBold))
            copy_w = fm_ovr.horizontalAdvance(copy_label) + 12.0
            self._rects["copy"] = QRectF(inner.right() - copy_w, inner.top(), copy_w, 18.0)

            list_top = inner.top() + OVERLINE_H
            self._list_rect = QRectF(inner.left(), list_top, inner.width(), body_h)
            self._scroll = max(0.0, min(self._max_scroll(), self._scroll))

            btn_sz = BTN_SZ
            for i in range(len(self._items)):
                r = QRectF(inner.left(), list_top + i * ROW_H - self._scroll, inner.width(), ROW_H)
                self._row_rects.append(r)
                rm = QRectF(r.right() - 6.0 - btn_sz, r.center().y() - btn_sz / 2.0, btn_sz, btn_sz)
                pin = QRectF(rm.left() - 4.0 - btn_sz, r.center().y() - btn_sz / 2.0, btn_sz, btn_sz)
                self._rm_rects.append(rm)
                self._pin_rects.append(pin)

        y += card_h + ps.GAP
        fr = QRectF(ps.PAD, y, cw, ps.FOOTER_H)
        self._rects["footer"] = fr

        f_btn = ps.font(11.5, QFont.Weight.Medium)
        tw = QFontMetricsF(f_btn).horizontalAdvance("Temizle")
        btn_w = min(tw + 20.0, max(28.0, cw * 0.55))
        btn_h = min(24.0, ps.FOOTER_H - 3.0)
        self._rects["clear"] = QRectF(fr.right() - btn_w, fr.top() + 3.0 + (ps.FOOTER_H - 3.0 - btn_h) / 2.0, btn_w, btn_h)

    def refresh(self) -> None:
        self._items = self._store.items()
        if self._clip_store is not None:
            self._clip_items = self._clip_store.items()
        h = self.compute_height()
        if h != self.height() or self.width() != self.WIDTH:
            old_h = self.height()
            self.resize(self.WIDTH, h)
            if self.isVisible() and old_h > 0:
                self.move(self.x(), self.y() - (h - old_h))   # alt kenar sabit
                self._apply_round()
        self._layout()
        self.update()

    def _apply_round(self) -> None:
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                scr = self.screen() or QGuiApplication.primaryScreen()
                dpr = scr.devicePixelRatio() if scr is not None else 1.0
                winapi.set_round_region(int(self.winId()), self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass

    # ------------------------------------------------------------ açılır pencere API
    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def recently_closed(self, threshold_ms: float = 250.0) -> bool:
        if self._last_close_time <= 0.0:
            return False
        return (time.monotonic() - self._last_close_time) * 1000.0 <= threshold_ms

    def show_for(self, anchor_global: Optional[QRectF], *args: Any, switch_from_x: Optional[int] = None, **kw: Any) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        self._closing = False
        self._scroll = 0.0
        self.refresh()
        tx, ty, dpr = 100, 100, 1.0
        if self._anchor_global is not None:
            tx = int(self._anchor_global.center().x() - self.width() / 2.0)
            ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
            scr = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                dpr = scr.devicePixelRatio()
                m = 8
                tx = max(g.left() + m, min(g.right() - self.width() - m, tx))
                if ty < g.top() + m:
                    ty = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
                if ty + self.height() > g.bottom() - m:
                    ty = max(g.top() + m, g.bottom() - self.height() - m)
        winid = int(self.winId())
        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(winid, self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass
        ps.animate_in(self, QPoint(tx, ty), switch_from_x=switch_from_x)
        self.activateWindow()
        self.setFocus()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._last_close_time = time.monotonic()

        def _done() -> None:
            self._closing = False

        ps.animate_out(self, on_done=_done)

    def hide_instant(self) -> None:
        if self.isVisible():
            self._last_close_time = time.monotonic()
        self._closing = False
        ps.animate_out(self, instant=True)

    def panel_x(self) -> int:
        return int(self.x())

    def switch_tab(self, tab: str) -> None:
        if tab not in ("files", "clips") or tab == self._tab:
            return
        self._tab = tab
        self._scroll = 0.0
        self._sel_idx = 0
        h = self.compute_height()
        if h != self.height() or self.width() != self.WIDTH:
            old_h = self.height()
            self.resize(self.WIDTH, h)
            if self.isVisible() and old_h > 0:
                self.move(self.x(), self.y() - (h - old_h))
                self._apply_round()
        self._layout()
        self.update()

    # ------------------------------------------------------------ olaylar
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if self._clip_store is not None:
                self.switch_tab("clips" if self._tab == "files" else "files")
                event.accept()
                return
        if self._tab == "clips":
            if key == Qt.Key.Key_Up:
                if self._clip_items:
                    self._sel_idx = max(0, self._sel_idx - 1)
                    self.update()
                event.accept()
                return
            if key == Qt.Key.Key_Down:
                if self._clip_items:
                    self._sel_idx = min(len(self._clip_items) - 1, self._sel_idx + 1)
                    self.update()
                event.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._clip_items and 0 <= self._sel_idx < len(self._clip_items):
                    self.copy_clip_at(self._sel_idx)
                event.accept()
                return
            if key == Qt.Key.Key_Delete:
                if self._clip_items and 0 <= self._sel_idx < len(self._clip_items):
                    self.remove_clip_at(self._sel_idx)
                event.accept()
                return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange:
            if (not self.isActiveWindow() and self.isVisible() and not self._closing and not self._dragging):
                if self._anchor_global is not None and self._anchor_global.contains(QPointF(QCursor.pos())):
                    self._last_close_time = time.monotonic()
                    self._anchor_timer.start(300)
                else:
                    self.hide_animated()
        super().changeEvent(event)

    def _on_anchor_timeout(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and not self._closing and not self._dragging:
            self.hide_animated()

    def hideEvent(self, event) -> None:
        self._closing = False
        self._last_close_time = time.monotonic()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self._layout()
        super().resizeEvent(event)

    # -- isabet
    def _row_at(self, pos: QPointF) -> Optional[int]:
        if not self._list_rect.contains(pos):
            return None
        for i, r in enumerate(self._row_rects):
            if r.contains(pos):
                return i
        return None

    def _hit(self, pos: QPointF) -> Optional[str]:
        for k in ("close", "clear", "copy", "tab_files", "tab_clips"):
            r = self._rects.get(k)
            if r is not None and r.contains(pos):
                return k
        if self._tab == "clips":
            if self._list_rect.contains(pos):
                for i, rm in enumerate(self._clip_rm_rects):
                    if rm.contains(pos):
                        return f"clip_rm:{i}"
                for i, r in enumerate(self._clip_row_rects):
                    if r.contains(pos):
                        return f"clip:{i}"
            return None
        i = self._row_at(pos)
        if i is not None:
            if self._rm_rects[i].contains(pos):
                return f"rm:{i}"
            if self._pin_rects[i].contains(pos):
                return f"pin:{i}"
            return f"row:{i}"
        return None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._press_idx is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                idx = self._press_idx
                self._press_idx = None
                if 0 <= idx < len(self._items):
                    self._start_drag(self._items[idx]["path"])
                event.accept()
                return
        h = self._hit(pos)
        if h != self._hover:
            self._hover = h
            if h and h.startswith("clip:"):
                try:
                    self._sel_idx = int(h[5:])
                except Exception:
                    pass
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        h = self._hit(pos)
        self._press_idx = None
        if h == "close":
            self.hide_animated()
        elif h == "tab_files":
            self.switch_tab("files")
        elif h == "tab_clips":
            self.switch_tab("clips")
        elif h == "clear":
            self.activate_clear()
        elif h == "copy":
            if self._tab == "clips":
                self.activate_clear()
            else:
                self.copy_all()
        elif h and h.startswith("clip:"):
            self.copy_clip_at(int(h[5:]))
        elif h and h.startswith("clip_rm:"):
            self.remove_clip_at(int(h[8:]))
        elif h and h.startswith("pin:"):
            self.toggle_pin_at(int(h[4:]))
        elif h and h.startswith("rm:"):
            self.remove_at(int(h[3:]))
        elif h and h.startswith("row:"):
            self._press_idx = int(h[4:])
            self._press_pos = QPointF(pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._press_idx = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            h = self._hit(event.position())
            if h and h.startswith("row:"):
                self.open_at(int(h[4:]))
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        if self._max_scroll() > 0 and self._list_rect.contains(event.position()):
            step = 40.0 if event.angleDelta().y() < 0 else -40.0
            ns = max(0.0, min(self._max_scroll(), self._scroll + step))
            if ns != self._scroll:
                self._scroll = ns
                self._layout()
                self.update()
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------ eylemler
    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()

    def activate_clear(self) -> None:
        if self._tab == "clips":
            if self._clip_store is not None:
                self._clip_store.clear()
                self._after_change()
        else:
            self._store.clear(keep_pinned=True)
            self._after_change()

    def copy_clip_at(self, i: int) -> None:
        if self._clip_store is None or not (0 <= i < len(self._clip_items)):
            return
        text = self._clip_store.get_text(i)
        if not text:
            return
        if hasattr(self, "_clip_monitor") and self._clip_monitor is not None:
            self._clip_monitor.copy_to_system(text)
        elif _real_ui_allowed():
            QGuiApplication.clipboard().setText(text)
        self.guard_log.append("copy_clip")
        self._copy_note = "Kopyalandı ✓"
        self._note_timer.start(1200)
        self._layout()
        self.update()

    def remove_clip_at(self, i: int) -> None:
        if self._clip_store is not None and 0 <= i < len(self._clip_items):
            self._clip_store.remove_at(i)
            self._after_change()

    def toggle_pin_at(self, i: int) -> None:
        if 0 <= i < len(self._items):
            self._store.toggle_pin(self._items[i]["path"])
            self._after_change()

    def remove_at(self, i: int) -> None:
        if 0 <= i < len(self._items):
            self._store.remove(self._items[i]["path"])
            self._after_change()

    def open_at(self, i: int) -> None:
        if not (0 <= i < len(self._items)):
            return
        if not _real_ui_allowed():
            self.guard_log.append("open")
            return
        try:
            os.startfile(self._items[i]["path"])  # noqa: S606
            self.hide_animated()
        except Exception:
            pass

    def _urls(self) -> List[QUrl]:
        return [QUrl.fromLocalFile(it["path"]) for it in self._items]

    def copy_all(self) -> int:
        """Rafın dosya listesini CF_HDROP olarak panoya koyar. Testte pano ASLA dokunulmaz."""
        urls = self._urls()
        if not urls:
            return 0
        if not _real_ui_allowed():
            self.guard_log.append("copy")
            return len(urls)
        md = QMimeData()
        md.setUrls(urls)
        QGuiApplication.clipboard().setMimeData(md)
        self._copy_note = "Kopyalandı"
        self._note_timer.start(1500)
        self.update()
        return len(urls)

    def _clear_note(self) -> None:
        self._copy_note = None
        self.update()

    def _start_drag(self, path: str) -> None:
        if not _real_ui_allowed():
            self.guard_log.append("drag")
            return
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(path)])
        drag = QDrag(self)
        drag.setMimeData(md)
        self._dragging = True
        try:
            res = drag.exec(Qt.DropAction.CopyAction)
        finally:
            self._dragging = False
        if res != Qt.DropAction.IgnoreAction:
            self._store.on_dragged_out(path)
            self._after_change()

    # ------------------------------------------------------------ çizim
    def render_to_image(self, dpr: float = 1.25) -> QImage:
        self._layout()
        img = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint(p)
        p.end()
        return img

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        w, h = float(self.width()), float(self.height())
        ps.draw_panel_shell(p, QRectF(0, 0, w, h))

        # 1. Başlık: Segmentli sekme [Dosyalar (N)] [Pano (M)] veya klasik 'Dosya rafı'
        if self._clip_store is not None and "tab_files" in self._rects:
            tf = self._rects["tab_files"]
            tc = self._rects["tab_clips"]
            t_bar = QRectF(tf.left(), tf.top(), tf.width() + tc.width(), tf.height())

            p.save()
            p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
            p.setBrush(QColor(0x1D, 0x1F, 0x24))
            p.drawRoundedRect(t_bar, 6.0, 6.0)

            f_tab = ps.font(10.5, QFont.Weight.Medium)
            p.setFont(f_tab)

            # Aktif sekme arka planı
            act_r = tf if self._tab == "files" else tc
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(act_r.adjusted(1.5, 1.5, -1.5, -1.5), 5.0, 5.0)

            # Sekme metinleri
            p.setPen(ps.TEXT if self._tab == "files" else ps.TEXT_MUTED)
            p.drawText(tf, Qt.AlignmentFlag.AlignCenter, f"Dosyalar ({len(self._items)})")

            p.setPen(ps.TEXT if self._tab == "clips" else ps.TEXT_MUTED)
            p.drawText(tc, Qt.AlignmentFlag.AlignCenter, f"Pano ({len(self._clip_items)})")

            # Kapat (✕)
            cr = self._rects["close"]
            hx = (self._hover == "close")
            p.setPen(QPen(ps.TEXT if hx else ps.TEXT_CLOSE, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            cx, cy = cr.center().x(), cr.center().y()
            p.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
            p.drawLine(QPointF(cx + 3.5, cy - 3.5), QPointF(cx - 3.5, cy + 3.5))
            p.restore()
        else:
            chip_txt = f"{len(self._items)} dosya"
            hdr = ps.draw_header(
                p, self._rects["hdr"], "Dosya rafı",
                icon=self._draw_header_icon,
                chip=chip_txt,
                chip_dot=ps.ACCENT if self._items else None,
                close_hover=(self._hover == "close"),
            )
            if hdr.get("close") is not None:
                self._rects["close"] = QRectF(hdr["close"])

        # 2. PANO SEKME ÇİZİMİ
        if self._tab == "clips":
            clear_label = self._copy_note or "Temizle"
            ps.draw_card(p, self._rects["card"], overline="Son kopyalananlar", overline_right=clear_label)

            lr = self._list_rect
            if not self._clip_items:
                p.save()
                p.setFont(ps.font(11.5, QFont.Weight.Normal))
                p.setPen(ps.TEXT_MUTED)
                p.drawText(lr, Qt.AlignmentFlag.AlignCenter, "Pano geçmişi boş\n(Ctrl+C ile kopyalananlar burada listelenir)")
                p.restore()
            else:
                p.save()
                p.setClipRect(lr)
                f_text = ps.font(11.5, QFont.Weight.Medium)
                f_meta = ps.font(9.5, QFont.Weight.Normal)
                f_tag = ps.font(8.5, QFont.Weight.DemiBold)

                for i, it in enumerate(self._clip_items):
                    if i >= len(self._clip_row_rects):
                        break
                    r = self._clip_row_rects[i]
                    hov = (self._hover == f"clip:{i}" or self._sel_idx == i)

                    if hov:
                        p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
                        p.setBrush(QColor(255, 255, 255, 12))
                        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6.0, 6.0)
                    else:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(255, 255, 255, 4))
                        p.drawRoundedRect(r, 6.0, 6.0)

                    # Tür etiketi
                    kind = it.get("kind", "text").upper()
                    if kind == "URL":
                        kind_lbl = "LİNK"
                    elif kind == "CODE":
                        kind_lbl = "KOD"
                    elif kind == "HEX":
                        kind_lbl = "RENK"
                    else:
                        kind_lbl = "METİN"

                    tag_r = QRectF(r.left() + 8.0, r.top() + 7.0, 38.0, 15.0)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 14))
                    p.drawRoundedRect(tag_r, 3.0, 3.0)
                    p.setFont(f_tag)
                    p.setPen(ps.TEXT_MUTED)
                    p.drawText(tag_r, Qt.AlignmentFlag.AlignCenter, kind_lbl)

                    # Zaman
                    age_str = clipboard.fmt_clip_age(it.get("added", 0)) if clipboard else ""
                    p.setFont(f_meta)
                    p.setPen(ps.TEXT_META)
                    p.drawText(QRectF(tag_r.right() + 6.0, r.top() + 6.0, 120.0, 16.0),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, age_str)

                    # Metin önizlemesi
                    p.setFont(f_text)
                    p.setPen(ps.TEXT if hov else ps.TEXT_BODY)
                    prev = it.get("preview", "")
                    fm = QFontMetricsF(f_text)
                    elided = fm.elidedText(prev, Qt.TextElideMode.ElideRight, r.width() - 55.0)
                    p.drawText(QRectF(r.left() + 8.0, r.top() + 24.0, r.width() - 55.0, 18.0),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

                    # Sağ işlem: hover/seçiliyse '↵' kopyala veya '✕' sil
                    rm_r = self._clip_rm_rects[i]
                    if self._hover == f"clip_rm:{i}":
                        p.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
                        cx, cy = rm_r.center().x(), rm_r.center().y()
                        p.drawLine(QPointF(cx - 3.0, cy - 3.0), QPointF(cx + 3.0, cy + 3.0))
                        p.drawLine(QPointF(cx + 3.0, cy - 3.0), QPointF(cx - 3.0, cy + 3.0))
                    elif hov:
                        p.setFont(ps.font(11.0, QFont.Weight.Medium))
                        p.setPen(ps.ACCENT)
                        p.drawText(rm_r, Qt.AlignmentFlag.AlignCenter, "↵")

                p.restore()

            # Pano Alt Bilgisi
            fr = self._rects["footer"]
            btn_rect = ps.draw_footer(
                p, fr, "Enter veya tıkla kopyala", "Temizle",
                button_hover=(self._hover == "clear")
            )
            if btn_rect is not None:
                self._rects["clear"] = btn_rect
            return

        # 3. DOSYALAR SEKME ÇİZİMİ (Klasik Raf)
        copy_label = self._copy_note or ("Hepsini kopyala ›" if self._items else None)
        ps.draw_card(p, self._rects["card"], overline="Dosyalar", overline_right=copy_label)

        # 3. Liste alanı
        lr = self._list_rect
        if not self._items:
            p.save()
            box = lr.adjusted(4.0, 2.0, -4.0, -2.0)
            pen = QPen(QColor(255, 255, 255, 30), 1.0, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_TILE, ps.R_TILE)
            dpr = _device_dpr(p)
            pm = _svg_pixmap("clip", QColor(255, 255, 255, 90), 20.0, dpr)
            p.drawPixmap(QPointF(box.center().x() - 10.0, box.top() + 16.0), pm)
            p.setFont(ps.font(13.0, QFont.Weight.Medium))
            p.setPen(ps.TEXT_MUTED)
            p.drawText(QRectF(box.left(), box.top() + 40.0, box.width(), 28.0), Qt.AlignmentFlag.AlignCenter,
                       "Dosyayı bar'a sürükle")
            p.restore()
        else:
            p.save()
            p.setClipRect(lr)
            now = time.time()
            dpr = _device_dpr(p)
            f_name = ps.font(13.0, QFont.Weight.Normal)
            f_meta = ps.font(11.0, QFont.Weight.Normal)
            fm_name, fm_meta = QFontMetricsF(f_name), QFontMetricsF(f_meta)
            for i, it in enumerate(self._items):
                r = self._row_rects[i]
                if r.bottom() < lr.top() or r.top() > lr.bottom():
                    continue
                hov_row = self._hover in (f"row:{i}", f"pin:{i}", f"rm:{i}")
                if hov_row:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(ps.TILE_BG)
                    p.drawRoundedRect(r, 8.0, 8.0)
                isdir = os.path.isdir(it["path"])
                ic = type_icon(it["path"], isdir, dpr)
                p.drawPixmap(QPointF(r.left() + 6.0, r.center().y() - 14.0), ic)
                tx = r.left() + 6.0 + 28.0 + 10.0
                tw = max(20.0, self._pin_rects[i].left() - 8.0 - tx)
                p.setFont(f_name)
                p.setPen(QColor(255, 255, 255, 230))
                p.drawText(QRectF(tx, r.center().y() - 16.0, tw, 16.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           fm_name.elidedText(it["name"], Qt.TextElideMode.ElideMiddle, tw))
                p.setFont(f_meta)
                p.setPen(ps.TEXT_META)
                meta = f"{fmt_size(it['size'], isdir)} · {fmt_age(it['added'], now)}"
                p.drawText(QRectF(tx, r.center().y() + 1.0, tw, 15.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           fm_meta.elidedText(meta, Qt.TextElideMode.ElideRight, tw))

                # İğne butonu (>= 24x24 px)
                pr = self._pin_rects[i]
                hp = self._hover == f"pin:{i}"
                if it["pinned"]:
                    p.setPen(QPen(QColor(110, 168, 254, 120), 1.0))
                    p.setBrush(QColor(110, 168, 254, 51))
                    p.drawRoundedRect(pr.adjusted(0.5, 0.5, -0.5, -0.5), 6.0, 6.0)
                    p.drawPixmap(QPointF(pr.center().x() - 7.0, pr.center().y() - 7.0),
                                 _svg_pixmap("pin", ps.ACCENT, 14.0, dpr))
                elif hov_row:
                    if hp:
                        p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
                        p.setBrush(ps.BUTTON_HOVER)
                        p.drawRoundedRect(pr.adjusted(0.5, 0.5, -0.5, -0.5), 6.0, 6.0)
                    else:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPixmap(QPointF(pr.center().x() - 7.0, pr.center().y() - 7.0),
                                 _svg_pixmap("pin", QColor(255, 255, 255, 220 if hp else 110), 14.0, dpr))

                # Kaldır butonu (✕, >= 24x24 px)
                rm = self._rm_rects[i]
                hx = self._hover == f"rm:{i}"
                if hov_row:
                    if hx:
                        p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
                        p.setBrush(ps.BUTTON_HOVER)
                        p.drawRoundedRect(rm.adjusted(0.5, 0.5, -0.5, -0.5), 6.0, 6.0)
                    else:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(ps.TEXT if hx else ps.TEXT_CLOSE, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    c = rm.center()
                    d = 4.0
                    p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
                    p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
            p.restore()

            if self._max_scroll() > 0:
                p.save()
                tr = QRectF(w - ps.PAD - 5.0, lr.top() + 2.0, 3.0, lr.height() - 4.0)
                th = max(18.0, tr.height() * (lr.height() / (len(self._items) * ROW_H)))
                ty = tr.top() + (tr.height() - th) * (self._scroll / self._max_scroll())
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(QRectF(tr.left(), ty, tr.width(), th), 1.5, 1.5)
                p.restore()

        # 4. Alt bilgi: kaynak metni + sağda hayalet 'Temizle' butonu
        fr = self._rects["footer"]
        can_clear = any(not it["pinned"] for it in self._items)
        if can_clear:
            btn_rect = ps.draw_footer(p, fr, "Tutup maile ya da klasöre sürükle", "Temizle",
                                      button_hover=(self._hover == "clear"))
            if btn_rect is not None:
                self._rects["clear"] = btn_rect
        else:
            ps.draw_footer(p, fr, "Tutup maile ya da klasöre sürükle", None)
            btn_rect = self._rects["clear"]
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(QColor(255, 255, 255, 25), 1.0))
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawPath(ps.rounded(btn_rect.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_BUTTON))
            p.setFont(ps.font(11.5, QFont.Weight.Medium))
            # Pasif durumda kontrast >= 3:1 (QColor(255, 255, 255, 120) koyu fonda ~4.7:1 verir)
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "Temizle")
            p.restore()
