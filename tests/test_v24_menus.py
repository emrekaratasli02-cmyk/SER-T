"""test_v24_menus.py - açılır menüler A (v24): tek mavi vurgu, ince ses sürgüsü, sağ tık yeni eylemleri.

Zero side effects: preview-mode dock, temp settings file; winapi.close_window / pinned.launch are stubbed,
so no real window is closed and no app is started.
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
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import panel_style as ps  # noqa: E402


def _dock():
    spec = importlib.util.spec_from_file_location("serit_v5_v24m", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v24m_")) / "settings.json"
    m.save_settings = lambda cfg: None
    return m, m.SeritDock({"style": "band"}, preview_mode=True)


def test_single_accent_palette() -> None:
    blue = QColor("#6EA8FE")
    for name in ("ACCENT", "SOUND", "CPU", "RAM", "DISK"):
        assert getattr(ps, name).name() == blue.name(), name
    assert ps.CLAUDE.name() == "#d97757"
    b = ps.BRIGHT
    assert b.red() == b.green() == b.blue(), "parlaklık simgesi nötr (sarı yok)"
    old = "QColor(10, 132, 255"
    for f in ("panel_style.py", "calendar_panel.py", "info_panels.py", "window_picker.py"):
        assert old not in (APP_DIR / f).read_text(encoding="utf-8"), f


def test_compact_slider_is_thin() -> None:
    img = QImage(400, 80, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(20, 22, 26))
    p = QPainter(img)
    res = ps.draw_slider(p, QRectF(10, 10, 300, 38), "Chrome", 100.0, fill=ps.SOUND, compact=True)
    full = ps.draw_slider(p, QRectF(10, 10, 300, 46), "Ses", 50.0, fill=ps.SOUND)
    p.end()
    assert res["track"].height() == 6.0 and res["knob"].height() == 12.0, (res["track"], res["knob"])
    assert abs(res["knob"].center().y() - res["track"].center().y()) < 0.01
    assert full["track"].height() > res["track"].height()


def test_dock_menu_seven_rows_and_no_card_toggles() -> None:
    _m, d = _dock()
    acts = d.build_dock_menu_actions()
    # v25 satırları (pomodoro / raf / uyku engelleme) test_v25_wiring.py'de
    acts = [a for a in acts if a.get("id") not in {"pomo_toggle", "show_shelf", "keep_awake",
                                                  "toggle_net_speed", "toggle_updates"}]  # v26: test_v26_wiring.py
    rows = [a for a in acts if a.get("type") != "separator"]
    # 7 seçenek + 3 ayırıcı (eskiden 12 seçenek + 4 ayırıcı)
    assert len(rows) == 7 and len(acts) == 10, [a.get("id") for a in acts]
    ids = {a.get("id") for a in rows}
    assert not ids & {"toggle_cal", "toggle_mail", "toggle_ag", "toggle_sys", "reset_pos"}, ids
    assert acts[0]["id"] == "settings" and acts[0].get("icon") == "settings"
    assert acts[-1]["id"] == "quit" and acts[-1]["danger"] and acts[-1]["confirm"]


def test_app_menu_new_window_and_close_all() -> None:
    m, d = _dock()
    exe = sys.executable  # gerçekten var olan bir dosya (yalnız yol kontrolü; başlatılmaz)
    tile = {"exe": exe, "path": exe, "name": "Örnek", "pinned": True, "running": True, "hwnds": [11, 12, 13]}
    acts = d.build_app_tile_menu_actions(tile)
    ids = [a.get("id") for a in acts if a.get("type") != "separator"]
    assert ids == ["new_window", "unpin", "close_all", "end_task"], ids
    close = [a for a in acts if a.get("id") == "close_all"][0]
    assert close["text"] == "Tüm pencereleri kapat (3)" and not close.get("danger")
    one = d.build_app_tile_menu_actions(dict(tile, hwnds=[11]))
    assert [a for a in one if a.get("id") == "close_all"][0]["text"] == "Pencereyi kapat"

    closed, launched = [], []
    old_close, old_launch = m.winapi.close_window, m.pinned.launch
    m.winapi.close_window = lambda h: closed.append(h) or True
    m.pinned.launch = lambda path: launched.append(path) or True
    try:
        close["callback"]()                     # önizleme kipinde hiçbir şey yapmaz
        [a for a in acts if a.get("id") == "new_window"][0]["callback"]()
        assert closed == [] and launched == []
        d.preview_mode = False
        close["callback"]()
        [a for a in acts if a.get("id") == "new_window"][0]["callback"]()
        assert closed == [11, 12, 13], closed
        assert launched == [exe], launched
    finally:
        d.preview_mode = True
        m.winapi.close_window, m.pinned.launch = old_close, old_launch


def test_not_running_app_menu_unchanged() -> None:
    _m, d = _dock()
    acts = d.build_app_tile_menu_actions({"exe": sys.executable, "name": "X", "pinned": False, "running": False})
    assert [a.get("id") for a in acts] == ["pin"]


def run_all() -> None:
    for fn in (test_single_accent_palette, test_compact_slider_is_thin, test_dock_menu_seven_rows_and_no_card_toggles,
               test_app_menu_new_window_and_close_all, test_not_running_app_menu_unchanged):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_MENUS TESTS PASSED")


if __name__ == "__main__":
    run_all()
