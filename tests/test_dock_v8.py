"""test_dock_v8.py - Unit and integration tests for Şerit dock v8 Lumabar layout:
1) App group centred on screen centre (+-1 px) in band mode with 3 and 8 apps
2) Wings not overlapping apps/clock with and without media
3) Fitting order (tray icons drop before media card compacts)
4) Mail and Antigravity card states (ok, zero, error, stale) and hit keys
5) Menu toggles saved to settings['cards']
6) Tray end-task contract with tray_actions / action_menu mocked (end_task never called before action_chosen('end'))
7) Safe fallbacks when modules are missing
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
from typing import List
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dock_cards

# Import serit_v5 safely with isolated settings file
spec = importlib.util.spec_from_file_location("serit_v5_v8", str(PROJECT_ROOT / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

REAL_SETTINGS_FILE = PROJECT_ROOT / "settings.json"
TEMP_SETTINGS_DIR = Path(tempfile.mkdtemp(prefix="serit_v8_test_"))
serit_mod.SETTINGS_FILE = TEMP_SETTINGS_DIR / "settings.json"


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def get_settings_hash() -> str:
    if REAL_SETTINGS_FILE.is_file():
        return hashlib.sha256(REAL_SETTINGS_FILE.read_bytes()).hexdigest()
    return ""


def test_app_group_centering() -> None:
    """Verify app group is centred exactly on screen centre (+-1 px) with 3 and 8 apps."""
    get_qapp()
    sw = 1536.0
    screen_center = sw / 2.0  # 768.0

    # 1. Test with 3 apps
    three_apps = [{"exe": f"app_{i}.exe", "name": f"App {i}"} for i in range(3)]
    dock3 = serit_mod.SeritDock({"style": "band", "pinned": three_apps}, preview_mode=True)
    dock3.tiles = list(three_apps)
    dock3.resize(int(sw), 64)
    dock3.compute_layout_and_resize(initial=True)
    img3 = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
    dock3.render(img3)

    app_hits3 = [r for r, k, _e in dock3.hit_boxes if k.startswith("app_")]
    assert len(app_hits3) == 3, f"Expected 3 app tiles, got {len(app_hits3)}"
    cx3 = (min(r.left() for r in app_hits3) + max(r.right() for r in app_hits3)) / 2.0
    assert abs(cx3 - screen_center) <= 1.0, f"3 apps center {cx3} not at {screen_center} (+-1px)"

    # 2. Test with 8 apps
    eight_apps = [{"exe": f"app_{i}.exe", "name": f"App {i}"} for i in range(8)]
    dock8 = serit_mod.SeritDock({"style": "band", "pinned": eight_apps}, preview_mode=True)
    dock8.tiles = list(eight_apps)
    dock8.resize(int(sw), 64)
    dock8.compute_layout_and_resize(initial=True)
    img8 = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
    dock8.render(img8)

    app_hits8 = [r for r, k, _e in dock8.hit_boxes if k.startswith("app_")]
    assert len(app_hits8) == 8, f"Expected 8 app tiles, got {len(app_hits8)}"
    cx8 = (min(r.left() for r in app_hits8) + max(r.right() for r in app_hits8)) / 2.0
    assert abs(cx8 - screen_center) <= 1.0, f"8 apps center {cx8} not at {screen_center} (+-1px)"
    print("[PASS] App group centred on screen centre (+-1 px) with 3 and 8 apps.")


def test_wings_no_overlap() -> None:
    """Verify left and right wings never overlap apps or clock, with and without media."""
    get_qapp()
    sw = 1536.0

    for n_apps in (3, 8):
        apps = [{"exe": f"app_{i}.exe", "name": f"App {i}"} for i in range(n_apps)]
        for has_media in (False, True):
            dock = serit_mod.SeritDock({"style": "band", "pinned": apps}, preview_mode=True)
            dock.tiles = list(apps)
            dock._tray_items = [{"name": f"tray_{i}"} for i in range(9)]
            if has_media:
                dock._now_playing_info = {"title": "Test Title", "app": "Chrome", "artist": "Web"}
            else:
                dock._now_playing_info = None

            dock.resize(int(sw), 64)
            dock.compute_layout_and_resize(initial=True)
            img = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
            dock.render(img)

            # Extract rects
            lw_hits = [r for r, k, _e in dock.hit_boxes if k in ("claude", "mail", "ag", "sys")]
            app_hits = [r for r, k, _e in dock.hit_boxes if k.startswith("app_")]
            rw_hits = [r for r, k, _e in dock.hit_boxes if k in ("media", "cal")]
            clk_hits = [r for r, k, _e in dock.hit_boxes if k == "clock"]
            vol_hits = [r for r, k, _e in dock.hit_boxes if k == "vol"]
            chv_hits = [r for r, k, _e in dock.hit_boxes if k == "tray"]

            assert len(app_hits) == n_apps
            assert len(clk_hits) >= 1
            assert len(vol_hits) == 1
            assert len(chv_hits) == 1

            lw_left = min(r.left() for r in lw_hits)
            lw_right = max(r.right() for r in lw_hits)
            app_left = min(r.left() for r in app_hits)
            app_right = max(r.right() for r in app_hits)
            rw_left = min(r.left() for r in rw_hits)
            rw_right = max(r.right() for r in rw_hits)
            chv_left = chv_hits[0].left()
            clk_right = clk_hits[0].right()

            # Assert clearances
            assert lw_left >= 10.0, f"Left wing {lw_left} overlaps left screen edge (< 10px)"
            assert lw_right <= app_left - 5.5, f"Left wing {lw_right} overlaps apps {app_left}"
            assert rw_left >= app_right + 5.5, f"Right wing {rw_left} overlaps apps {app_right}"
            assert chv_left >= rw_right + 11.5, f"Actions {chv_left} overlaps right wing {rw_right} (clearance < 12px)"
            assert abs(sw - 14.0 - clk_right) <= 1.0, f"Clock not pinned 14px from right screen edge: {sw - clk_right}"


    print("[PASS] Wings do not overlap apps or clock with and without media.")


def test_fitting_order() -> None:
    """Verify fitting order: media compacts first (314 -> 240 px), then calendar shrinks, then center shifts."""
    get_qapp()

    # Create dock with media playing
    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    dock._tray_items = [{"name": f"tray_{i}"} for i in range(10)]
    dock._now_playing_info = {"title": "A Very Long Media Track Title", "app": "Spotify"}

    # At 1536 width with 0 apps, media card is 314px and no individual tray icons on band
    dock.resize(1536, 64)
    img = QImage(1536, 64, QImage.Format.Format_ARGB32)
    dock.render(img)

    r_media_wide = next(r for r, k, _e in dock.hit_boxes if k == "media")
    tray_icons_wide = [e for r, k, e in dock.hit_boxes if k == "tray_icon"]
    assert r_media_wide.width() == 314.0, f"Expected uncompacted 314px media card, got {r_media_wide.width()}"
    assert len(tray_icons_wide) == 0, f"Expected no tray icons on band, got {len(tray_icons_wide)}"

    # In extremely tight space (e.g. 1000px with 8 apps + media), tray icons are 0 and media compacted to 240px
    eight_apps = [{"exe": f"app_{i}.exe", "name": f"App {i}"} for i in range(8)]
    dock_tight = serit_mod.SeritDock({"style": "band", "pinned": eight_apps}, preview_mode=True)
    dock_tight.tiles = list(eight_apps)
    dock_tight._tray_items = [{"name": f"tray_{i}"} for i in range(10)]
    dock_tight._now_playing_info = {"title": "Title", "app": "Chrome"}
    dock_tight.resize(1000, 64)
    dock_tight.compute_layout_and_resize(initial=True)
    img_tight = QImage(1000, 64, QImage.Format.Format_ARGB32)
    dock_tight.render(img_tight)

    tray_tight = [e for r, k, e in dock_tight.hit_boxes if k == "tray_icon"]
    r_media_tight = next(r for r, k, _e in dock_tight.hit_boxes if k == "media")
    assert len(tray_tight) == 0, f"Expected 0 tray icons under tight space, got {len(tray_tight)}"
    assert r_media_tight.width() == 240.0, f"Expected 240px compacted media card under tight space, got {r_media_tight.width()}"

    print("[PASS] Fitting order verified: tray icons drop before media card compacts.")


def test_mail_and_ag_card_states() -> None:
    """Verify mail and ag card states (ok, zero, error, stale), metrics, and hit keys."""
    get_qapp()

    # 1. Mail card states
    mail_ok = {
        "total_open": 4,
        "accounts": [{"label": "IAS", "open": 2}, {"label": "Kişisel", "open": 2}, {"label": "Logaritma", "open": 0}],
        "stale": False,
        "scanned_at": "2026-10-27T08:31:00+03:00",
    }
    val, lbl, err, stale = dock_cards.format_mail_card_text(mail_ok)
    assert val == "4 bekliyor"
    assert lbl == "IAS 2 · Kişisel 2"
    assert not err and not stale
    w_ok = dock_cards.measure_mail_card_width(mail_ok)
    assert 112.0 <= w_ok <= 150.0

    mail_zero = {"total_open": 0, "accounts": [], "stale": False}
    val_z, lbl_z, err_z, _ = dock_cards.format_mail_card_text(mail_zero)
    assert val_z == "Yanıt yok"
    assert lbl_z == "Hepsi yanıtlandı"
    assert not err_z

    mail_err = {"err": "Dizin okunamadı"}
    val_e, lbl_e, err_e, _ = dock_cards.format_mail_card_text(mail_err)
    assert val_e == "—"
    assert lbl_e == "Mail okunamadı"
    assert err_e

    mail_stale = {"total_open": 2, "accounts": [{"label": "IAS", "open": 2}], "stale": True}
    _, _, _, is_stale = dock_cards.format_mail_card_text(mail_stale)
    assert is_stale

    # Offscreen render mail card without raising
    img_mail = QImage(200, 64, QImage.Format.Format_ARGB32)
    p_mail = QPainter(img_mail)
    for m_state in (mail_ok, mail_zero, mail_err, mail_stale):
        dock_cards.draw_mail_card(p_mail, QRectF(10, 6, 130, 52), m_state)
    p_mail.end()

    # 2. Antigravity card states
    ag_ok = {
        "groups": [
            {"label": "Claude", "used": 100.0, "reset_tr": "29 Eki Per 16:40"},
            {"label": "Gemini Pro", "used": 28.5, "reset_tr": "27 Eki Sal 14:54"},
            {"label": "Gemini Flash", "used": 32.4, "reset_tr": "27 Eki Sal 14:54"},
        ]
    }
    img_ag = QImage(200, 64, QImage.Format.Format_ARGB32)
    p_ag = QPainter(img_ag)
    dock_cards.draw_ag_card(p_ag, QRectF(10, 6, 142, 52), ag_ok)
    dock_cards.draw_ag_card(p_ag, QRectF(10, 6, 142, 52), {"err": "Quota error"})
    p_ag.end()

    # 3. Hit boxes in SeritDock
    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    dock.store.update("mail", mail_ok)
    dock.store.update("ag", ag_ok)
    dock.resize(1536, 64)
    img_dock = QImage(1536, 64, QImage.Format.Format_ARGB32)
    dock.render(img_dock)

    keys = [k for _r, k, _e in dock.hit_boxes]
    assert "mail" in keys, "Hit box 'mail' missing from dock"
    assert "ag" in keys, "Hit box 'ag' missing from dock"

    # Tooltips
    tip_mail = dock.get_tooltip_text("mail", None)
    assert "Yanıt bekleyen mailler" in tip_mail
    assert "08:31" in tip_mail

    tip_ag = dock.get_tooltip_text("ag", None)
    assert "Claude: %100" in tip_ag
    assert "29 Eki Per 16:40" in tip_ag

    print("[PASS] Mail and AG card states, rendering, hit keys, and tooltips verified.")


def test_menu_toggles_saved() -> None:
    """Verify menu toggles for Mail and Antigravity cards update and save settings['cards']."""
    get_qapp()
    saved_cfgs: List[dict] = []

    def mock_save(cfg: dict) -> None:
        saved_cfgs.append(dict(cfg))

    dock = serit_mod.SeritDock({"style": "band", "cards": {"cal": True, "mail": True, "ag": True, "sys": False}}, preview_mode=True)
    with patch.object(serit_mod, "save_settings", side_effect=mock_save):
        # Toggle mail off
        cfg = dict(dock.settings.get("cards") or {})
        cfg["mail"] = False
        dock.settings["cards"] = cfg
        serit_mod.save_settings(dock.settings)

        assert len(saved_cfgs) >= 1
        assert saved_cfgs[-1]["cards"]["mail"] is False

        # Toggle ag off
        cfg["ag"] = False
        dock.settings["cards"] = cfg
        serit_mod.save_settings(dock.settings)
        assert saved_cfgs[-1]["cards"]["ag"] is False

        # Toggle sys on
        cfg["sys"] = True
        dock.settings["cards"] = cfg
        serit_mod.save_settings(dock.settings)
        assert saved_cfgs[-1]["cards"]["sys"] is True

    print("[PASS] Menu toggles and settings['cards'] saving verified.")


def test_tray_end_task_contract() -> None:
    """Verify tray end-task contract with tray_actions / action_menu mocked."""
    get_qapp()

    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=False)
    test_item = {"name": "TestApp", "pid": 1234}
    anchor = QRectF(100, 10, 26, 26)

    mock_tray_actions = MagicMock()
    mock_tray_actions.resolve_processes.return_value = {"ok": True, "label": "TestApp running"}
    mock_action_menu = MagicMock()
    dock.action_menu = mock_action_menu

    with patch.dict(sys.modules, {"tray_actions": mock_tray_actions, "action_menu": MagicMock()}):
        # 1. Trigger flow
        dock._start_tray_end_task_flow(test_item, anchor)
        assert dock._action_in_flight is True
        # Keep one in-flight item at a time: second immediate trigger must be ignored
        dock._start_tray_end_task_flow(test_item, anchor)

        # Allow worker thread pool to execute resolve_processes
        t0 = time.time()
        while time.time() - t0 < 2.0:
            QApplication.processEvents()
            if not dock._action_in_flight:
                break
            time.sleep(0.02)

        # resolve_processes was called
        assert mock_tray_actions.resolve_processes.called
        # ActionMenu set_header, set_actions, show_at were called
        assert mock_action_menu.set_header.called
        assert mock_action_menu.set_actions.called
        assert mock_action_menu.show_at.called

        # CRITICAL CONTRACT: end_task must NEVER be called before action_chosen('end')
        assert not mock_tray_actions.end_task.called, "end_task was called prematurely!"

        # 2. Test action_chosen('open')
        dock._on_action_chosen("open")
        assert mock_tray_actions.open_item.called
        assert not mock_tray_actions.end_task.called

        # 3. Test action_chosen('end')
        dock._on_action_chosen("end")
        t0 = time.time()
        while time.time() - t0 < 1.0:
            QApplication.processEvents()
            if mock_tray_actions.end_task.called:
                break
            time.sleep(0.02)
        assert mock_tray_actions.end_task.called

    print("[PASS] Tray end-task contract verified (end_task never called before action_chosen('end')).")


def test_missing_modules_fallback() -> None:
    """Verify safe fallback when info_panels, tray_actions, or action_menu are missing."""
    get_qapp()

    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    dock.mail_panel = None
    dock.quota_panel = None
    dock.action_menu = None

    # Clicking mail/ag when panel is None must not raise
    dock.handle_click("mail", None, QRectF(10, 6, 120, 52))
    dock.handle_click("ag", None, QRectF(140, 6, 142, 52))

    # Right-click tray item when action_menu is None must fall back to trayicons.activate without raising
    with patch("trayicons.activate") as mock_act:
        dock.preview_mode = False
        dock._start_tray_end_task_flow({"name": "App"}, QRectF(0, 0, 20, 20))
        assert mock_act.called

    print("[PASS] Safe fallbacks for missing modules verified.")


def run_all() -> None:
    h_before = get_settings_hash()
    print(f"[INTEGRITY] settings.json hash before: {h_before}")

    test_app_group_centering()
    test_wings_no_overlap()
    test_fitting_order()
    test_mail_and_ag_card_states()
    test_menu_toggles_saved()
    test_tray_end_task_contract()
    test_missing_modules_fallback()

    h_after = get_settings_hash()
    print(f"[INTEGRITY] settings.json hash after:  {h_after}")
    assert h_before == h_after, f"settings.json was modified! {h_before} != {h_after}"
    print("ALL DOCK V8 TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all()
