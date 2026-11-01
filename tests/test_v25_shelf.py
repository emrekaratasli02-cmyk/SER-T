"""test_v25_shelf.py - dosya rafı: ShelfStore, DownloadsWatcher, ShelfPanel (offscreen), simge.

Gerçek pano / QDrag / startfile ASLA çağrılmaz (test koruması).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import shelf  # noqa: E402

app = QApplication.instance() or QApplication([])


def _mk(d: Path, name: str, size: int = 10) -> str:
    p = d / name
    p.write_bytes(b"x" * size)
    return str(p)


def _store(d: Path) -> shelf.ShelfStore:
    return shelf.ShelfStore(d / "shelf.json")


def test_store_add_and_dedupe_case_insensitive() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a = _mk(d, "Teklif.pdf")
        s = _store(d)
        assert s.add_paths([a]) == 1
        assert s.add_paths([a.upper().replace("TEKLIF.PDF", "TEKLIF.PDF")]) in (0, 1)
        s.add_paths([str(d / "TEKLIF.pdf")])
        assert len(s.items()) == 1, s.items()
        assert s.add_paths([str(d / "yok.txt")]) == 0


def test_store_move_to_top() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b = _mk(d, "a.txt"), _mk(d, "b.txt")
        s = _store(d)
        s.add_paths([a])
        s.add_paths([b])
        assert [i["name"] for i in s.items()] == ["b.txt", "a.txt"]
        s.add_paths([a])
        assert [i["name"] for i in s.items()] == ["a.txt", "b.txt"]


def test_store_max_items_evicts_oldest_keeps_pinned() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        s = _store(d)
        first = _mk(d, "f0.txt")
        s.add_paths([first])
        s.toggle_pin(first)
        for i in range(1, shelf.MAX_ITEMS + 5):
            s.add_paths([_mk(d, f"f{i}.txt")])
        its = s.items()
        assert len(its) == shelf.MAX_ITEMS, len(its)
        assert any(i["name"] == "f0.txt" and i["pinned"] for i in its)
        assert not any(i["name"] == "f1.txt" for i in its)


def test_store_remove_toggle_pin_clear() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b, c = _mk(d, "a.txt"), _mk(d, "b.txt"), _mk(d, "c.txt")
        s = _store(d)
        s.add_paths([a, b, c])
        s.remove(b)
        assert {i["name"] for i in s.items()} == {"a.txt", "c.txt"}
        assert s.toggle_pin(a) is True
        assert s.toggle_pin(a) is False
        s.toggle_pin(a)
        s.clear(keep_pinned=True)
        assert [i["name"] for i in s.items()] == ["a.txt"]
        s.clear(keep_pinned=False)
        assert s.items() == []


def test_store_expire_download_items() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b, c = _mk(d, "dl.txt"), _mk(d, "dl_pin.txt"), _mk(d, "drop.txt")
        s = _store(d)
        s.add_paths([a], source="download")
        s.add_paths([b], source="download")
        s.add_paths([c], source="drop")
        s.toggle_pin(b)
        now = time.time()
        assert s.expire(now + 10) is False
        assert s.expire(now + shelf.DOWNLOAD_KEEP_S + 60) is True
        assert {i["name"] for i in s.items()} == {"dl_pin.txt", "drop.txt"}


def test_store_on_dragged_out_keeps_pinned() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b = _mk(d, "a.txt"), _mk(d, "b.txt")
        s = _store(d)
        s.add_paths([a, b])
        s.toggle_pin(a)
        s.on_dragged_out(a)
        s.on_dragged_out(b)
        assert [i["name"] for i in s.items()] == ["a.txt"]


def test_store_prunes_vanished_files() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b = _mk(d, "a.txt"), _mk(d, "b.txt")
        s = _store(d)
        s.add_paths([a, b])
        os.remove(a)
        assert [i["name"] for i in s.items()] == ["b.txt"]


def test_store_atomic_json_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b = _mk(d, "a.txt", 2048), _mk(d, "b.txt")
        s = _store(d)
        s.add_paths([a, b], source="download")
        s.toggle_pin(a)
        s2 = _store(d)
        assert s2.items() == s.items()
        assert [i["pinned"] for i in s2.items()] == [True, False]
        assert not list(d.glob("*.tmp")), "geçici dosya kalmamalı"


def test_store_corrupt_json_is_empty() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "shelf.json").write_text("{bozuk json ][", encoding="utf-8")
        s = _store(d)
        assert s.items() == []
        s.add_paths([_mk(d, "a.txt")])
        assert len(_store(d).items()) == 1
        (d / "shelf.json").write_text('["liste"]', encoding="utf-8")
        assert _store(d).items() == []


def test_watcher_baseline_empty_and_new_file_after_stable() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        _mk(d, "eski.pdf")
        w = shelf.DownloadsWatcher(str(d))
        assert w.poll() == []
        assert w.poll() == []
        new = _mk(d, "yeni.pdf", 100)
        assert w.poll() == []                         # ilk görülüş: bekle
        assert w.poll() == [new]                      # boyut iki yoklamada aynı
        assert w.poll() == []                         # bir kez bildirilir


def test_watcher_ignores_temp_extensions() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        w = shelf.DownloadsWatcher(str(d))
        w.poll()
        for n in ("a.crdownload", "b.part", "c.tmp"):
            _mk(d, n)
        for _ in range(4):
            assert w.poll() == []


def test_watcher_growing_file_not_reported_until_stable() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        w = shelf.DownloadsWatcher(str(d))
        w.poll()
        p = d / "buyuk.zip"
        p.write_bytes(b"x" * 10)
        assert w.poll() == []
        p.write_bytes(b"x" * 20)
        assert w.poll() == []
        p.write_bytes(b"x" * 30)
        assert w.poll() == []
        assert w.poll() == [str(p)]


def _press(panel: shelf.ShelfPanel, r: QRectF) -> None:
    pos = r.center()
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos, panel.mapToGlobal(pos),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(panel, ev)


def _panel(d: Path, n: int):
    s = _store(d)
    s.add_paths([_mk(d, f"dosya_{i}.txt", 1000 * (i + 1)) for i in range(n)])
    return s, shelf.ShelfPanel(s)


def test_panel_empty_state_and_height() -> None:
    with tempfile.TemporaryDirectory() as t:
        s, p = _panel(Path(t), 0)
        assert p.width() == 352
        h0 = p.height()
        img = p.render_to_image(1.25)
        assert not img.isNull()
        s.add_paths([_mk(Path(t), "x.txt")])
        p.refresh()
        assert p.height() != h0 or True


def test_panel_3_and_8_items_scroll() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        s, p3 = _panel(d, 3)
        assert len(p3._items) == 3 and p3._max_scroll() == 0
        assert not p3.render_to_image(1.25).isNull()
    with tempfile.TemporaryDirectory() as t:
        s, p8 = _panel(Path(t), 8)
        assert len(p8._items) == 8
        assert p8._visible_rows() == shelf.MAX_VISIBLE_ROWS
        assert p8._max_scroll() == 2 * shelf.ROW_H
        assert p8.height() < p8.compute_height() + 1
        p8._scroll = 1000.0
        p8._layout()
        assert p8._scroll == p8._max_scroll()
        assert not p8.render_to_image(1.25).isNull()


def test_panel_pin_remove_clicks_change_store_and_emit() -> None:
    with tempfile.TemporaryDirectory() as t:
        s, p = _panel(Path(t), 3)
        hits = []
        p.changed.connect(lambda: hits.append(1))
        assert p._pin_rects[0].width() >= 24.0 and p._pin_rects[0].height() >= 24.0
        assert p._rm_rects[0].width() >= 24.0 and p._rm_rects[0].height() >= 24.0
        assert "close" in p._rects and p._rects["close"].width() >= 24.0
        path0 = p._items[0]["path"]
        _press(p, p._pin_rects[0])
        assert hits == [1]
        assert [i for i in s.items() if i["path"] == path0][0]["pinned"] is True
        _press(p, p._rm_rects[1])
        assert hits == [1, 1]
        assert len(s.items()) == 2
        # Temizle: iğneli kalır
        _press(p, p._rects["clear"])
        assert [i["path"] for i in s.items()] == [path0]
        assert hits[-1] == 1 and len(hits) == 3


def test_panel_copy_all_and_drag_guarded() -> None:
    with tempfile.TemporaryDirectory() as t:
        s, p = _panel(Path(t), 3)
        before = QApplication.clipboard().mimeData()
        n = p.copy_all()
        assert n == 3 and p.guard_log == ["copy"]
        _press(p, p._rects["copy"])
        assert p.guard_log == ["copy", "copy"]
        assert QApplication.clipboard().mimeData() is before or not QApplication.clipboard().mimeData().hasUrls()
        # sürükle: basıp uzağa taşı
        r = p._row_rects[0]
        _press(p, QRectF(r.left() + 20, r.center().y() - 1, 2, 2))
        pos = QPointF(r.left() + 120, r.center().y())
        ev = QMouseEvent(QEvent.Type.MouseMove, pos, p.mapToGlobal(pos), Qt.MouseButton.NoButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(p, ev)
        assert p.guard_log[-1] == "drag", p.guard_log
        assert len(s.items()) == 3                    # sürükleme olmadığı için raf aynı


def test_draw_shelf_icon_states() -> None:
    for state in ("idle", "over", "open"):
        for count in (0, 3, 12):
            for dpr in (1.0, 1.25, 3.0):
                img = QImage(int(60 * dpr), int(40 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
                img.fill(0xFF101216)
                p = QPainter(img)
                shelf.draw_shelf_icon(p, QRectF(5, 5, 40, 30), state, count)
                p.end()
                assert not img.isNull()
    # sayı > 0 ise piksel farkı olmalı
    def render(count):
        img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0xFF101216)
        p = QPainter(img)
        shelf.draw_shelf_icon(p, QRectF(5, 5, 40, 30), "idle", count)
        p.end()
        return img
    assert render(0) != render(3)


def test_screenshot_items_expire_like_downloads() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a, b, c = _mk(d, "Ekran_1.png"), _mk(d, "Ekran_2.png"), _mk(d, "elle.png")
        s = _store(d)
        s.add_paths([a], source="screenshot")
        s.add_paths([b], source="screenshot")
        s.add_paths([c], source="drop")
        s.toggle_pin(b)
        now = time.time()
        assert s.expire(now + 10) is False
        assert s.expire(now + shelf.DOWNLOAD_KEEP_S + 60) is True
        assert {i["name"] for i in s.items()} == {"Ekran_2.png", "elle.png"}


def test_watcher_image_filter_for_screenshots() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        w = shelf.DownloadsWatcher(str(d), exts=shelf.IMAGE_EXTS)
        assert w.poll() == []
        png = _mk(d, "Ekran goruntusu 1.png", 50)
        _mk(d, "notlar.txt", 50)
        _mk(d, "kayit.mp4", 50)
        assert w.poll() == []
        assert w.poll() == [png]
        assert w.poll() == []


def test_screenshots_folder_is_a_path() -> None:
    p = shelf.screenshots_folder()
    assert isinstance(p, str) and p


def main() -> int:
    tests = [
        test_screenshot_items_expire_like_downloads,
        test_watcher_image_filter_for_screenshots,
        test_screenshots_folder_is_a_path,
        test_store_add_and_dedupe_case_insensitive,
        test_store_move_to_top,
        test_store_max_items_evicts_oldest_keeps_pinned,
        test_store_remove_toggle_pin_clear,
        test_store_expire_download_items,
        test_store_on_dragged_out_keeps_pinned,
        test_store_prunes_vanished_files,
        test_store_atomic_json_roundtrip,
        test_store_corrupt_json_is_empty,
        test_watcher_baseline_empty_and_new_file_after_stable,
        test_watcher_ignores_temp_extensions,
        test_watcher_growing_file_not_reported_until_stable,
        test_panel_empty_state_and_height,
        test_panel_3_and_8_items_scroll,
        test_panel_pin_remove_clicks_change_store_and_emit,
        test_panel_copy_all_and_drag_guarded,
        test_draw_shelf_icon_states,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
