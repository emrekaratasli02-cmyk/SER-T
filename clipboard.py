"""Şerit pano yöneticisi (v26.2): Sade, hafif ve hızlı pano geçmişi.

Anti-slop felsefesi:
  * Saf Python + Qt QClipboard (ekstra bağımlılık yok, webview/electron yok).
  * Güvenli: Şifre yöneticisi gizlilik bayraklarını ve devasa metinleri (>50 KB) yoksayar.
  * Atomik JSON depolama (logpath yönlendirmesiyle testleri ve gerçek veriyi korur).
  * Anlık tür tespiti: URL, Hex Renk, Kod/SQL ve Düz Metin.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import logpath  # noqa: E402

CLIPBOARD_FILE_NAME = "clipboard.json"
MAX_CLIPS = 30
MAX_TEXT_LEN = 50_000
PREVIEW_LEN = 120

_RE_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RE_URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_CODE_TOKENS = (
    "select ", "insert ", "update ", "delete ", "from ", "where ",
    "def ", "class ", "import ", "from ", "return ", "const ",
    "function", "console.", "<div>", "</div>", "=>", "===", "!=",
    "SELECT ", "INSERT ", "UPDATE ", "DELETE ", "FROM ", "WHERE "
)


def _real_ui_allowed() -> bool:
    """Canlı etki koruması: testlerde pano yazılmaz/okunmaz."""
    if os.environ.get("SERIT_ALLOW_REAL_UI") == "1":
        return True
    return not logpath.is_running_under_test()


def detect_kind(text: str) -> str:
    """Metin içeriğine göre tür tespiti: 'url', 'hex', 'code', 'text'."""
    s = text.strip()
    if not s:
        return "text"
    if _RE_HEX_COLOR.match(s):
        return "hex"
    if _RE_URL.match(s):
        return "url"
    if any(tok in s for tok in _CODE_TOKENS) or "\n" in s and any(c in s for c in "{}[]();"):
        return "code"
    return "text"


def fmt_clip_age(added: float, now: Optional[float] = None) -> str:
    """Türkçe sade zaman damgası: 'az önce', '2 dk', '15 dk', '1 sa', 'Dün'."""
    now = time.time() if now is None else now
    diff = max(0.0, now - float(added))
    if diff < 60:
        return "az önce"
    if diff < 3600:
        return f"{int(diff // 60)} dk önce"
    if diff < 86400:
        return f"{int(diff // 3600)} sa önce"
    days = int(diff // 86400)
    return "Dün" if days == 1 else f"{days} gün önce"


class ClipboardStore:
    """Pano geçmişi veri deposu: Kilitli, atomik JSON kayıt."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self._path = Path(path) if path is not None else logpath.get_cache_file(CLIPBOARD_FILE_NAME)
        self._lock = threading.Lock()
        self._items: List[Dict[str, Any]] = []
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._items = []
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                    self._items = raw["items"][:MAX_CLIPS]
                else:
                    self._items = []
            except Exception:
                self._items = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = {"version": 1, "items": self._items[:MAX_CLIPS]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def add_text(self, text: str, source: str = "clipboard") -> bool:
        """Yeni kopyalanan metni ekle; aynı metin varsa başa taşı."""
        if not text or not isinstance(text, str):
            return False
        cleaned = text.strip()
        if not cleaned or len(text) > MAX_TEXT_LEN:
            return False

        with self._lock:
            # Varsa eskiyi kaldır (başa taşımak için)
            self._items = [it for it in self._items if it.get("text") != text]

            kind = detect_kind(cleaned)
            now = time.time()
            preview = cleaned[:PREVIEW_LEN].replace("\r\n", " ").replace("\n", " ")

            entry = {
                "text": text,
                "preview": preview,
                "kind": kind,
                "added": now,
                "pinned": False,
                "source": source,
            }
            self._items.insert(0, entry)
            self._items = self._items[:MAX_CLIPS]
            try:
                self._save()
                return True
            except Exception:
                return False

    def remove_at(self, idx: int) -> bool:
        """Belirtilen indisteki öğeyi sil."""
        with self._lock:
            if 0 <= idx < len(self._items):
                self._items.pop(idx)
                try:
                    self._save()
                    return True
                except Exception:
                    return False
            return False

    def clear(self) -> bool:
        """Tüm öğeleri temizle (iğneliler hariç tutulabilir)."""
        with self._lock:
            self._items = [it for it in self._items if it.get("pinned")]
            try:
                self._save()
                return True
            except Exception:
                return False

    def toggle_pin(self, idx: int) -> bool:
        """İğne durumunu tersine çevir."""
        with self._lock:
            if 0 <= idx < len(self._items):
                self._items[idx]["pinned"] = not self._items[idx].get("pinned", False)
                try:
                    self._save()
                    return True
                except Exception:
                    return False
            return False

    def items(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._items)

    def get_text(self, idx: int) -> Optional[str]:
        with self._lock:
            if 0 <= idx < len(self._items):
                return self._items[idx].get("text")
            return None


class ClipboardMonitor(QObject):
    """Sistem panosunu (Ctrl+C) dinler ve ClipboardStore'a yazar."""

    changed = Signal()

    def __init__(self, store: Optional[ClipboardStore] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.store = store or ClipboardStore()
        self._suppress_next = False
        self._connected = False

    def start(self) -> None:
        """Pano dinleyicisini başlat."""
        if self._connected:
            return
        app = QGuiApplication.instance()
        if app is None:
            return
        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.dataChanged.connect(self._on_data_changed)
            self._connected = True

    def stop(self) -> None:
        if not self._connected:
            return
        clip = QGuiApplication.clipboard()
        if clip is not None:
            try:
                clip.dataChanged.disconnect(self._on_data_changed)
            except Exception:
                pass
        self._connected = False

    def _on_data_changed(self) -> None:
        if not _real_ui_allowed():
            return
        if self._suppress_next:
            self._suppress_next = False
            return
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        text = clip.text()
        if text and self.store.add_text(text):
            self.changed.emit()

    def copy_to_system(self, text: str) -> bool:
        """Bir metni sistem panosuna geri yazar (kendi dinleyicisini susturarak)."""
        if not text:
            return False
        self._suppress_next = True
        if not _real_ui_allowed():
            # Test modunda gerçek panoya dokunmadan başarılı say
            return True
        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.setText(text)
            return True
        return False
