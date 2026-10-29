"""test_v24_behaviors.py - v24 adım 2: açılış geri bildirimi, açılamadı balonu, orta tık, takvim tekerleği,
Explorer yeniden başlayınca (TaskbarCreated) yenileme.

Zero side effects: preview-mode dock; pinned.launch / app_new_window / _register_appbar taklit edilir;
gerçek uygulama açılmaz, görev çubuğu ve ayrılan alan değişmez, ayar dosyasına yazılmaz.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import action_menu  # noqa: E402
import calendar_panel  # noqa: E402

DPR = 1.25


def _module():
    spec = importlib.util.spec_from_file_location("serit_v5_behaviors", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_bh_")) / "settings.json"
    m.save_settings = lambda cfg: None
    return m


M = _module()
EXE = sys.executable  # var olan dosya; hiçbir zaman gerçekten başlatılmaz


def _dock():
    d = M.SeritDock({"style": "band"}, preview_mode=True)
    d.update_windows = lambda: None
    return d


def _tile(running=False):
    return {"key": M.pinned._norm_key(EXE), "exe": EXE, "path": EXE, "name": "Örnek", "pinned": True,
            "running": running, "hwnds": [1, 2] if running else [], "count": 2 if running else 0}


def test_launch_feedback_pulse_until_window() -> None:
    d = _dock()
    d.tiles = [_tile()]
    d.compute_layout_and_resize()
    d.resize(1536, int(M.DOCK_HEIGHT))
    old = M.pinned.launch
    calls = []
    M.pinned.launch = lambda p: calls.append(p) or True
    try:
        d.preview_mode = False
        assert d._launch_tile(d.tiles[0], EXE, QRectF(700, 10, 44, 46)) is True
        d.preview_mode = True
    finally:
        M.pinned.launch = old
    assert calls == [EXE]
    ph = d._launch_phase(d.tiles[0])
    assert ph is not None and 0.29 <= ph <= 0.96, ph
    img = QImage(int(1536 * DPR), int(64 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor(13, 15, 19))
    d.render(img, QPoint(0, 0))
    r = {k: rr for rr, k, _e in d.hit_boxes}["app_0"]
    dot = QColor(img.pixel(int(r.center().x() * DPR), int((r.bottom() - 4.0) * DPR)))
    assert dot.red() > 60, dot.name()  # kapalı uygulamada normalde nokta yok; açılırken var
    d.tiles[0]["running"] = True
    d._tick_launching()
    assert not d._launching and not d._launch_timer.isActive()
    d.tiles[0]["running"] = False
    d._launching["eski"] = time.monotonic() - (d.LAUNCH_TIMEOUT_S + 1.0)
    d._tick_launching()
    assert not d._launching, "10 sn sonra nabız durur"


def test_launch_failure_bubble() -> None:
    d = _dock()
    old = M.pinned.launch
    calls = []
    M.pinned.launch = lambda p: calls.append(p) or True
    try:
        assert d._launch_tile({"name": "Eski Kısayol"}, "C:/yok/olmayan.exe", None) is False
        assert calls == [], "olmayan dosya başlatılmaya çalışılmaz"
        assert d._last_fail_text == "Eski Kısayol açılamadı · dosya bulunamadı"
        M.pinned.launch = lambda p: False
        assert d._launch_tile(_tile(), EXE, None) is False
        assert d._last_fail_text == "Örnek açılamadı"
        assert not d._launching
    finally:
        M.pinned.launch = old
    assert not d.fail_bubble.isVisible(), "önizleme kipinde balon gösterilmez"


def test_middle_click_new_window_or_open() -> None:
    d = _dock()
    run, off = _tile(running=True), dict(_tile(), name="Kapalı")
    nw, opened = [], []
    d.app_new_window = lambda p: nw.append(p)
    d._launch_tile = lambda t, p, r=None: opened.append(t["name"]) or True
    d.hit_boxes = [(QRectF(100, 10, 44, 46), "app_0", run), (QRectF(150, 10, 44, 46), "app_1", off)]
    d.preview_mode = False
    try:
        for x in (120.0, 170.0, 400.0):
            ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, 30), QPointF(x, 30),
                             Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            d.mouseReleaseEvent(ev)
    finally:
        d.preview_mode = True
    assert nw == [EXE], nw
    assert opened == ["Kapalı"], opened


def test_menu_shows_middle_click_hint() -> None:
    d = _dock()
    acts = d.build_app_tile_menu_actions(_tile(running=True))
    nw = [a for a in acts if a.get("id") == "new_window"][0]
    assert nw.get("shortcut") == "Orta tık"
    am = action_menu.ActionMenu()
    am.set_actions(acts)
    kept = [a for a in am._actions if a.get("id") == "new_window"][0]
    assert kept.get("shortcut") == "Orta tık", "set_actions kısayolu düşürmemeli"


def test_calendar_wheel_changes_month() -> None:
    cp = calendar_panel.CalendarPanel()
    cp.view_year, cp.view_month = 2026, 10

    def wheel(dy):
        ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        cp.wheelEvent(ev)
        return cp.view_year, cp.view_month

    assert wheel(120) == (2026, 9)
    assert wheel(-120) == (2026, 10)
    assert [wheel(-40) for _ in range(3)] == [(2026, 10), (2026, 10), (2026, 11)]  # dokunmatik birikimli
    cp.view_year, cp.view_month = 2026, 12
    assert wheel(-120) == (2027, 1)


def test_taskbar_created_reregisters_appbar() -> None:
    d = _dock()
    u = ctypes.windll.user32
    u.RegisterWindowMessageW.restype = ctypes.c_uint
    M.SeritDock._WM_TASKBAR_CREATED = int(u.RegisterWindowMessageW("TaskbarCreated"))
    seen = []
    d._on_taskbar_created = lambda: seen.append(1)
    d.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    d.resize(10, 10)
    d.move(-400, -400)
    d.show()
    QTimer.singleShot(100, lambda: u.PostMessageW(ctypes.c_void_p(int(d.winId())), M.SeritDock._WM_TASKBAR_CREATED, 0, 0))
    t_end = time.monotonic() + 2.5
    while time.monotonic() < t_end and not seen:
        app.processEvents()
        time.sleep(0.02)
    d.hide()
    assert seen == [1], "TaskbarCreated alınınca yenileme çağrılmalı"
    # gerçek yenileme: önizleme kipinde hiçbir şeye dokunmaz
    d2 = _dock()
    reg = []
    d2._register_appbar = lambda: reg.append(1) or True
    d2._appbar_registered = True
    M.SeritDock._on_taskbar_created(d2)
    assert reg == [] and d2._appbar_registered is True
    d2.preview_mode = False
    old_set = M.winapi.taskbar_autohide_set
    M.winapi.taskbar_autohide_set = lambda v: reg.append(("autohide", v))
    d2.place_dock = lambda: None
    try:
        M.SeritDock._on_taskbar_created(d2)
    finally:
        M.winapi.taskbar_autohide_set = old_set
        d2.preview_mode = True
    assert d2._appbar_registered is False and 1 in reg, reg  # kayıt bayrağı sıfırlandı, yeniden kaydoldu


def run_all() -> None:
    for fn in (test_launch_feedback_pulse_until_window, test_launch_failure_bubble, test_middle_click_new_window_or_open,
               test_menu_shows_middle_click_hint, test_calendar_wheel_changes_month, test_taskbar_created_reregisters_appbar):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_BEHAVIORS TESTS PASSED")


if __name__ == "__main__":
    run_all()
