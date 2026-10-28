"""test_v22_dock_actions.py - sol alt masaüstü köşesi, döşemede 'Görevi sonlandır', pencere seçicisi bağlantısı.

Zero side effects: preview-mode dock; winapi state changers, save_settings and
tray_actions.end_task are replaced with recorders. No real window, process or key is touched.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location("serit_v5_v22", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v22_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

CALLS: list = []
serit_mod.winapi.toggle_desktop = lambda: CALLS.append(("desktop",))
serit_mod.winapi.activate_window = lambda h: CALLS.append(("activate", h))
serit_mod.winapi.close_window = lambda h: CALLS.append(("close", h)) or True
serit_mod.winapi.activate_or_minimize = lambda h: CALLS.append(("toggle", h))


def _dock():
    QApplication.instance() or QApplication([])
    d = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    return d


def test_desktop_corner_hit_box_and_click() -> None:
    d = _dock()
    img = d.render_to_image(1.0) if hasattr(d, "render_to_image") else None
    if img is None:
        d.resize(1536, int(serit_mod.DOCK_HEIGHT))
        d.grab()
    boxes = [(r, k) for r, k, _ in d.hit_boxes if k == "desktop"]
    assert boxes, "sol alt köşe alanı çizilmeli"
    r = boxes[0][0]
    assert r.x() == 0.0 and r.width() == serit_mod.DESKTOP_STRIP_W
    CALLS.clear()
    d.preview_mode = False
    d.handle_click("desktop", None, r)
    d.preview_mode = True
    assert CALLS == [("desktop",)]
    assert "Masaüstünü göster" in d.get_tooltip_text("desktop", None)


def test_app_menu_end_task_only_for_running() -> None:
    d = _dock()
    running = {"exe": r"C:\Apps\Chrome\chrome.exe", "name": "Chrome", "pinned": True, "running": True, "hwnds": [1, 2]}
    acts = d.build_app_tile_menu_actions(running)
    ids = [a.get("id") for a in acts if a.get("type") != "separator"]
    assert ids == ["unpin", "end_task"], ids
    end = [a for a in acts if a.get("id") == "end_task"][0]
    assert end["text"] == "Görevi sonlandır" and end["danger"] and end["confirm"]
    not_running = {"exe": r"C:\Apps\x.exe", "name": "X", "pinned": True, "running": False}
    assert [a["id"] for a in d.build_app_tile_menu_actions(not_running)] == ["unpin"]


def test_end_app_task_uses_safe_path_and_reports() -> None:
    import tray_actions

    d = _dock()
    seen: list = []
    done: list = []
    old = tray_actions.end_task
    old_submit = serit_mod.sources.submit
    tray_actions.end_task = lambda item: seen.append(item) or {"ok": False, "reason": "Yönetici izni gerekiyor"}
    serit_mod.sources.submit = lambda key, fn, cb=None: (fn(), True)[1]
    d.dispatcher.end_task_done.connect(lambda item, res: done.append((item, res)))
    try:
        d.preview_mode = False
        d.end_app_task({"exe": r"C:\Apps\Chrome\chrome.exe", "name": "Chrome"})
    finally:
        d.preview_mode = True
        tray_actions.end_task = old
        serit_mod.sources.submit = old_submit
    assert seen == [{"name": "Chrome", "exe": r"C:\Apps\Chrome\chrome.exe"}]
    assert done and done[0][1]["reason"] == "Yönetici izni gerekiyor"


def test_multi_window_click_opens_picker_not_cycle() -> None:
    d = _dock()
    d._raw_windows = [
        {"hwnd": 11, "title": "Gelen kutusu - Örnek", "minimized": False, "active": True},
        {"hwnd": 12, "title": "YouTube", "minimized": True, "active": False},
    ]

    class FakePicker:
        def __init__(self):
            self.shown = None
            self.open = False

        def is_open(self):
            return self.open

        def recently_closed(self, threshold_ms=250.0):
            return False

        def show_for(self, anchor, name, icon, wins):
            self.shown = (name, wins)
            self.open = True

        def hide_animated(self):
            self.open = False

    d.window_picker = FakePicker()
    CALLS.clear()
    tile = {"exe": r"C:\Apps\Chrome\chrome.exe", "name": "Chrome", "running": True, "hwnds": [11, 12]}
    d.preview_mode = False
    try:
        d.handle_tile_click(tile, QRectF(100, 10, 44, 44))
    finally:
        d.preview_mode = True
    assert d.window_picker.shown is not None, "çok pencerede seçici açılmalı"
    name, wins = d.window_picker.shown
    assert name == "Chrome" and [w["hwnd"] for w in wins] == [11, 12]
    assert wins[1]["minimized"] is True and wins[0]["active"] is True
    assert not any(c[0] == "toggle" for c in CALLS), "sırayla geçiş yapılmamalı"
    d.preview_mode = False
    try:
        d.handle_tile_click(tile, QRectF(100, 10, 44, 44))  # ikinci tık kapatır
    finally:
        d.preview_mode = True
    assert d.window_picker.open is False


def test_single_window_and_missing_picker_fallback() -> None:
    d = _dock()
    CALLS.clear()
    d.preview_mode = False
    try:
        d.handle_tile_click({"exe": "a.exe", "running": True, "hwnds": [5]}, QRectF(0, 0, 10, 10))
        d._raw_windows = []  # başlık bilgisi yok -> seçici açılamaz, eski sırayla geçiş
        d.window_picker = None
        d._ensure_window_picker = lambda: None
        d.handle_tile_click({"exe": "b.exe", "running": True, "hwnds": [6, 7]}, QRectF(0, 0, 10, 10))
    finally:
        d.preview_mode = True
    assert ("toggle", 5) in CALLS
    assert any(c[0] == "toggle" and c[1] in (6, 7) for c in CALLS)


def test_picker_signals_call_winapi() -> None:
    d = _dock()
    CALLS.clear()
    d.preview_mode = False
    try:
        d._on_picker_chosen(42)
        d._on_picker_close_requested(43)
    finally:
        d.preview_mode = True
    assert ("activate", 42) in CALLS and ("close", 43) in CALLS


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL PASSED")
