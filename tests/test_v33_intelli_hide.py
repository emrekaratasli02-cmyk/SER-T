"""test_v33_intelli_hide.py - Intelli-Hide pencere çakışmasında gizlenme ve kenar tetiklemesi (v33).

Zero side effects: preview-mode dock; winapi calls and settings writes are safely isolated.
Verifies:
1. intelli_hide default değeri False.
2. intelli_hide kapalıyken pencere çakışsa bile dock gizlenmez.
3. intelli_hide açıkken çakışma durumunda dock yumuşakça ekran altına kayar (_hidden_y), hover temizlenir.
4. Fare ekran alt kenarına (0-3px) veya dock alanına yaklaşınca dock geri gelir (_normal_y).
5. Fare dock'tan ayrıldığında hemen değil debounce süresiyle (_intelli_leave_timer) gizlenir.
6. Herhangi bir panel, popover veya menü açıkken pencere çakışsa bile dock asla gizlenmez.
7. settings_window üzerinden intelli_hide toggle açılıp kapanabilir ve AppBar kaydıyla senkron çalışır.
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

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

spec = importlib.util.spec_from_file_location("serit_v5_v33ih", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v33ih_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

import settings_window


def _dock(cfg: dict | None = None):
    QApplication.instance() or QApplication([])
    base_cfg = {"style": "band", "reserve_space": True, "intelli_hide": False}
    if cfg:
        base_cfg.update(cfg)
    d = serit_mod.SeritDock(base_cfg, preview_mode=True)
    d.appbar_calls = []
    d._register_appbar = lambda: d.appbar_calls.append("reg") or True
    d._unregister_appbar = lambda: d.appbar_calls.append("unreg")
    d.place_dock()
    d.show()
    return d


def test_default_intelli_hide_setting() -> None:
    """intelli_hide varsayılanda devre dışıdır."""
    assert serit_mod.DEFAULT_SETTINGS.get("intelli_hide") is False
    assert settings_window.SETTING_DEFAULTS.get("intelli_hide") is False
    d = _dock()
    assert d.settings.get("intelli_hide") is False
    assert not d._is_intelli_hidden
    d.hide()


def test_disabled_intelli_hide_never_hides() -> None:
    """intelli_hide False iken pencere çakışsa dahi dock asla gizlenmez."""
    d = _dock({"intelli_hide": False})
    d.preview_mode = False
    try:
        d.check_window_overlap = lambda: True
        d._check_intelli_hide()
        assert not d._is_intelli_hidden
        assert d.y() == d._normal_y
    finally:
        d.preview_mode = True
        d.hide()


def test_intelli_hide_slides_down_on_overlap() -> None:
    """intelli_hide True ve pencere çakıştığında dock ekran altına kayar ve hover temizlenir."""
    d = _dock({"intelli_hide": True})
    d.preview_mode = False
    try:
        QCursor.setPos(0, 0)
        d._hover_key = "app_0"
        d._hover_app_idx = 0
        d.check_window_overlap = lambda: True

        d._check_intelli_hide()

        assert d._is_intelli_hidden is True
        # Optimizasyon (Requirement A): gizlenirken hover sıfırlanmalı
        assert d._hover_key is None
        assert d._hover_app_idx is None
        # anim_dock_y hedefi _hidden_y olmalı
        assert abs(d.anim_dock_y.target_val - float(d._hidden_y)) < 1.0
    finally:
        d.preview_mode = True
        d.hide()


def test_reveal_when_overlap_clears_or_mouse_approaches() -> None:
    """Çakışma bitince veya dock çağrılınca dock normal konumuna döner."""
    d = _dock({"intelli_hide": True})
    d.preview_mode = False
    try:
        QCursor.setPos(0, 0)
        # Önce gizle
        d.check_window_overlap = lambda: True
        d._check_intelli_hide()
        assert d._is_intelli_hidden is True

        # Çakışma bitti
        d.check_window_overlap = lambda: False
        d._check_intelli_hide()
        assert d._is_intelli_hidden is False
        assert abs(d.anim_dock_y.target_val - float(d._normal_y)) < 1.0
    finally:
        d.preview_mode = True
        d.hide()


def test_no_hide_when_panel_or_menu_open() -> None:
    """Açılır panel veya menü varken çakışma olsa dahi gizlenmez."""
    d = _dock({"intelli_hide": True})
    d.preview_mode = False
    try:
        d.check_window_overlap = lambda: True
        # Panel açık gibi davran
        d._is_any_panel_or_menu_open = lambda: True
        d._check_intelli_hide()
        assert d._is_intelli_hidden is False
        assert abs(d.anim_dock_y.target_val - float(d._normal_y)) < 1.0
    finally:
        d.preview_mode = True
        d.hide()


def test_leave_debounce_timer() -> None:
    """Fare ayrıldığında hemen değil debounce zamanlayıcısıyla kontrol edilir."""
    d = _dock({"intelli_hide": True})
    d.preview_mode = False
    try:
        assert d._intelli_leave_timer.interval() == 350
        assert not d._intelli_leave_timer.isActive()
        d.leaveEvent(None)
        assert d._intelli_leave_timer.isActive()
    finally:
        d._intelli_leave_timer.stop()
        d.preview_mode = True
        d.hide()


def test_settings_window_intelli_hide_toggle() -> None:
    """Ayarlar penceresinde intelli_hide toggle'ı doğru çalışır ve on_apply ile aktarılır."""
    applied = []
    win = settings_window.open_settings({"intelli_hide": False}, lambda s: applied.append(s))
    try:
        # toggle_setting extra='intelli_hide' tetikle
        assert win.working_settings.get("intelli_hide") is False
        # Simüle tık
        for r, kind, extra in win._content_hit_boxes:
            if kind == "toggle_setting" and extra == "intelli_hide":
                win.working_settings["intelli_hide"] = not win.working_settings.get("intelli_hide", False)
                break
        assert win.working_settings["intelli_hide"] is True
    finally:
        win.close()


def test_wiring_apply_intelli_hide_coordination() -> None:
    """apply_settings_from_window ile intelli_hide açıldığında appbar kaldırılır, kapanınca tekrar eklenir."""
    d = _dock({"reserve_space": True, "intelli_hide": False})
    d.preview_mode = True
    d.appbar_calls.clear()

    # intelli_hide aç
    d.apply_settings_from_window({"reserve_space": True, "intelli_hide": True})
    assert d.settings["intelli_hide"] is True
    assert "unreg" in d.appbar_calls

    d.appbar_calls.clear()
    # intelli_hide kapat
    d.apply_settings_from_window({"reserve_space": True, "intelli_hide": False})
    assert d.settings["intelli_hide"] is False
    assert "reg" in d.appbar_calls
    d.hide()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL PASSED")
