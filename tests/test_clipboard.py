"""Unit tests for Şerit clipboard manager (clipboard.py)."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clipboard as cb


def test_detect_kind() -> None:
    assert cb.detect_kind("https://integralads.com") == "url"
    assert cb.detect_kind("http://localhost:8000/dashboard") == "url"
    assert cb.detect_kind("#6EA8FE") == "hex"
    assert cb.detect_kind("#fff") == "hex"
    assert cb.detect_kind("#121417ff") == "hex"
    assert cb.detect_kind("SELECT campaign_id, viewability FROM ias") == "code"
    assert cb.detect_kind("def calculate_ratio(a, b):\n    return a / b") == "code"
    assert cb.detect_kind("Merhaba dünya, nasılsın?") == "text"
    assert cb.detect_kind("") == "text"


def test_fmt_clip_age() -> None:
    now = 1000.0
    assert cb.fmt_clip_age(now - 10, now=now) == "az önce"
    assert cb.fmt_clip_age(now - 130, now=now) == "2 dk önce"
    assert cb.fmt_clip_age(now - 7200, now=now) == "2 sa önce"
    assert cb.fmt_clip_age(now - 86400, now=now) == "Dün"
    assert cb.fmt_clip_age(now - 172800, now=now) == "2 gün önce"


def test_clipboard_store_crud() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_clip.json"
        store = cb.ClipboardStore(p)
        assert len(store.items()) == 0

        # Discard invalid
        assert store.add_text("") is False
        assert store.add_text("   \n\t  ") is False
        assert store.add_text("A" * 60_000) is False
        assert len(store.items()) == 0

        # Add items
        assert store.add_text("İlk metin") is True
        assert len(store.items()) == 1
        assert store.items()[0]["text"] == "İlk metin"
        assert store.items()[0]["kind"] == "text"

        assert store.add_text("https://example.com") is True
        assert len(store.items()) == 2
        assert store.items()[0]["text"] == "https://example.com"
        assert store.items()[0]["kind"] == "url"

        # Deduplication: adding "İlk metin" again should bump it to index 0
        assert store.add_text("İlk metin") is True
        assert len(store.items()) == 2
        assert store.items()[0]["text"] == "İlk metin"

        # Toggle pin
        assert store.toggle_pin(0) is True
        assert store.items()[0]["pinned"] is True

        # Clear (pinned remains)
        assert store.clear() is True
        assert len(store.items()) == 1
        assert store.items()[0]["text"] == "İlk metin"

        # Remove at
        assert store.remove_at(0) is True
        assert len(store.items()) == 0
        assert store.remove_at(99) is False


def test_clipboard_store_max_limit() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_max.json"
        store = cb.ClipboardStore(p)
        for i in range(40):
            store.add_text(f"Klip no {i}")
        items = store.items()
        assert len(items) == cb.MAX_CLIPS
        assert items[0]["text"] == "Klip no 39"


def test_clipboard_monitor_guard() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_mon.json"
        store = cb.ClipboardStore(p)
        mon = cb.ClipboardMonitor(store)
        assert mon.copy_to_system("Deneme") is True
        # In test mode, real clipboard is not monitored/clobbered
        mon.start()
        mon.stop()


def test_shelf_panel_clipboard_tab() -> None:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QKeyEvent
    import shelf

    app = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "test_shelf.json"
        cp = Path(td) / "test_clip.json"

        s = shelf.ShelfStore(sp)
        c = cb.ClipboardStore(cp)
        c.add_text("SELECT 1 FROM test")
        c.add_text("https://example.com/live")

        panel = shelf.ShelfPanel(s, clip_store=c)
        assert panel._tab == "files"
        assert not panel.render_to_image(1.0).isNull()

        # Switch to clips tab
        panel.switch_tab("clips")
        assert panel._tab == "clips"
        assert len(panel._clip_items) == 2
        assert not panel.render_to_image(1.0).isNull()

        # Keyboard tab switch
        ev_tab = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        panel.keyPressEvent(ev_tab)
        assert panel._tab == "files"
        panel.keyPressEvent(ev_tab)
        assert panel._tab == "clips"

        # Keyboard Up/Down navigation
        ev_down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        panel.keyPressEvent(ev_down)
        assert panel._sel_idx == 1
        ev_up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        panel.keyPressEvent(ev_up)
        assert panel._sel_idx == 0

        # Copy selected clip
        panel.copy_clip_at(0)
        assert "copy_clip" in panel.guard_log
        assert panel._copy_note == "Kopyalandı ✓"

        # Remove clip
        panel.remove_clip_at(1)
        assert len(c.items()) == 1

        # Clear clips
        panel.activate_clear()
        assert len(c.items()) == 0


def main() -> int:
    tests = [
        test_detect_kind,
        test_fmt_clip_age,
        test_clipboard_store_crud,
        test_clipboard_store_max_limit,
        test_clipboard_monitor_guard,
        test_shelf_panel_clipboard_tab,
    ]
    for fn in tests:
        fn()
        print(f"OK   {fn.__name__}")
    print(f"All {len(tests)} tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
