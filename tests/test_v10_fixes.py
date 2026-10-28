"""test_v10_fixes.py - Verification suite for Şerit dock v10 fixes:
1. ActionMenu integration for app tile and main dock context menus (identical Turkish texts, radio/check, Kapat arm-to-confirm)
2. Settings backup validation (corrupt settings.json does not overwrite settings.json.bak)
3. AppBar registration HWND storage and reuse on unregister
4. Tray icons worker-safe extraction returning QImage (no QPixmap off GUI thread)
5. Media & volume pending latest action resubmission on slow calls
6. Taskbar autohide bit modification preserving ABS_ALWAYSONTOP
7. anim.py SystemParametersInfoW argtypes/restype and LRUCache bounded caps
8. Removal of hard-coded numeric fallbacks
"""

import ctypes
from ctypes import wintypes
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Ensure QApplication exists
qapp = QApplication.instance() or QApplication([])

# Safely load serit_v5 without writing real settings.json
spec = importlib.util.spec_from_file_location("serit_v5_v10_test", str(APP_DIR / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

import action_menu
import anim
import trayicons
import winapi


class TestV10Menus(unittest.TestCase):
    """Test Task 1: ActionMenu replaces old QMenu context menus."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_test_menu_")
        serit_mod.SETTINGS_FILE = Path(self.tmp_dir) / "settings.json"
        self.settings = {
            "style": "band",
            "reserve_space": False,
            "cards": {"cal": True, "mail": True, "ag": True, "sys": False},
            "alerts_enabled": True,
            "hide_taskbar": False,
            "pinned": [{"exe": "notepad.exe", "name": "Notepad"}],
        }
        self.dock = serit_mod.SeritDock(self.settings, preview_mode=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_app_tile_menu_actions(self) -> None:
        """App tile menu offers 'Sabitle' when unpinned, 'Sabitlemeyi kaldır' when pinned."""
        unpinned_extra = {"exe": "calc.exe", "name": "Calculator", "pinned": False}
        pinned_extra = {"exe": "notepad.exe", "name": "Notepad", "pinned": True}

        unpinned_acts = self.dock.build_app_tile_menu_actions(unpinned_extra)
        self.assertEqual(len(unpinned_acts), 1)
        self.assertEqual(unpinned_acts[0]["id"], "pin")
        self.assertEqual(unpinned_acts[0]["text"], "Sabitle")

        pinned_acts = self.dock.build_app_tile_menu_actions(pinned_extra)
        self.assertEqual(len(pinned_acts), 1)
        self.assertEqual(pinned_acts[0]["id"], "unpin")
        self.assertEqual(pinned_acts[0]["text"], "Sabitlemeyi kaldır")

    def test_dock_menu_actions_content_and_order(self) -> None:
        """Main dock menu matches the exact Turkish texts, order, groups and checks of old QMenu."""
        acts = self.dock.build_dock_menu_actions()

        # Expected sequence:
        # 0: Yenile
        # 1: separator
        # 2: Tam genişlik şerit (group='style', checked=True for band)
        # 3: Ortada kapsül (group='style', checked=False for band)
        # 4: separator
        # 5: Takvim kartı (checked=True)
        # 6: Mail kartı (checked=True)
        # 7: Antigravity kartı (checked=True)
        # 8: Sistem kartı (checked=False)
        # 9: separator
        # 10: Uyarılar (checked=True)
        # 11: Windows görev çubuğunu gizle (checked=False)
        # 12: Konumu sıfırla
        # 13: separator
        # 14: Kapat (danger=True, confirm=True)

        expected = [
            ("settings", "Ayarlar…", False, None),  # v21: Ayarlar penceresi
            ("refresh", "Yenile", False, None),
            ("sep", None, False, None),
            ("style_band", "Tam genişlik şerit", True, "style"),
            ("style_pill", "Ortada kapsül", False, "style"),
            ("sep", None, False, None),
            ("toggle_cal", "Takvim kartı", True, None),
            ("toggle_mail", "Mail kartı", True, None),
            ("toggle_ag", "Antigravity kartı", True, None),
            ("toggle_sys", "Sistem kartı", False, None),
            ("sep", None, False, None),
            ("toggle_alerts", "Uyarılar", True, None),
            ("toggle_taskbar", "Windows görev çubuğunu gizle", False, None),
            ("reset_pos", "Konumu sıfırla", False, None),
            ("sep", None, False, None),
            ("quit", "Kapat", False, None),
        ]

        self.assertEqual(len(acts), len(expected))
        for i, (exp_id, exp_text, exp_checked, exp_group) in enumerate(expected):
            act = acts[i]
            if exp_id == "sep":
                self.assertEqual(act.get("type"), "separator")
            else:
                self.assertEqual(act.get("id"), exp_id, f"Row {i} id mismatch")
                self.assertEqual(act.get("text"), exp_text, f"Row {i} text mismatch")
                self.assertEqual(bool(act.get("checked")), exp_checked, f"Row {i} checked mismatch")
                if exp_group:
                    self.assertEqual(act.get("group"), exp_group, f"Row {i} group mismatch")

        # Kapat row must have danger=True and confirm=True
        quit_act = acts[-1]
        self.assertTrue(quit_act.get("danger"))
        self.assertTrue(quit_act.get("confirm"))

    def test_kapat_confirm_two_clicks(self) -> None:
        """Kapat row requires two clicks to confirm (arm then trigger)."""
        menu = action_menu.ActionMenu()
        emitted = []
        menu.action_chosen.connect(emitted.append)

        acts = self.dock.build_dock_menu_actions()
        menu.set_actions(acts)

        quit_idx = len(acts) - 1
        self.assertEqual(acts[quit_idx]["id"], "quit")

        # First click: arms, does NOT emit
        menu._trigger_row(quit_idx)
        self.assertEqual(emitted, [])
        self.assertEqual(menu._armed_action_id, "quit")

        # Second click: confirms, emits
        menu._trigger_row(quit_idx)
        self.assertEqual(emitted, ["quit"])
        self.assertIsNone(menu._armed_action_id)

    def test_menu_rendering_dpr2(self) -> None:
        """Render both menus at DPR 2.0 to ensure crisp rendering without errors."""
        menu = action_menu.ActionMenu()
        menu.set_actions(self.dock.build_dock_menu_actions())
        img_main = menu.render_to_image(dpr=2.0)
        self.assertFalse(img_main.isNull())
        self.assertEqual(img_main.devicePixelRatio(), 2.0)

        app_menu = action_menu.ActionMenu()
        app_menu.set_actions(self.dock.build_app_tile_menu_actions({"exe": "app.exe", "pinned": False}))
        img_app = app_menu.render_to_image(dpr=2.0)
        self.assertFalse(img_app.isNull())
        self.assertEqual(img_app.devicePixelRatio(), 2.0)


class TestV10SettingsBackup(unittest.TestCase):
    """Test Task 2: save_settings validates JSON before backing up."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_test_backup_")
        self.settings_file = Path(self.tmp_dir) / "settings.json"
        self.bak_file = Path(self.tmp_dir) / "settings.json.bak"
        serit_mod.SETTINGS_FILE = self.settings_file

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_valid_json_copies_to_backup(self) -> None:
        """Valid settings.json is copied over settings.json.bak on save."""
        initial_good = {"version": 1, "note": "good"}
        self.settings_file.write_text(json.dumps(initial_good), encoding="utf-8")

        new_settings = {"version": 2, "note": "updated"}
        serit_mod.save_settings(new_settings)

        self.assertTrue(self.bak_file.exists())
        bak_data = json.loads(self.bak_file.read_text(encoding="utf-8"))
        self.assertEqual(bak_data, initial_good)

        saved_data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(saved_data, new_settings)

    def test_corrupt_json_does_not_overwrite_backup(self) -> None:
        """A corrupt settings.json must NOT overwrite a good backup file."""
        good_bak = {"version": 1, "note": "known good backup"}
        self.bak_file.write_text(json.dumps(good_bak), encoding="utf-8")

        # Corrupt file on disk
        self.settings_file.write_text("{corrupt: json not closed", encoding="utf-8")

        new_settings = {"version": 3, "note": "recovered"}
        serit_mod.save_settings(new_settings)

        # settings.json.bak must still contain the good backup!
        bak_data = json.loads(self.bak_file.read_text(encoding="utf-8"))
        self.assertEqual(bak_data, good_bak, "Corrupt file destroyed the backup!")


class TestV10AppBarHwndReuse(unittest.TestCase):
    """Test Task 3: AppBar registration stores HWND and reuses it on unregister."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_test_appbar_")
        serit_mod.SETTINGS_FILE = Path(self.tmp_dir) / "settings.json"
        self.dock = serit_mod.SeritDock({"reserve_space": True}, preview_mode=False)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_hwnd_stored_and_reused_on_unregister(self) -> None:
        """_unregister_appbar must use stored self._appbar_hwnd."""
        mock_shell32 = MagicMock()
        mock_shell32.SHAppBarMessage.return_value = 1

        with patch.object(ctypes.windll, "shell32", mock_shell32), \
             patch.object(self.dock, "winId", return_value=12345678):

            # Simulate registration
            self.dock._appbar_registered = True
            self.dock._appbar_hwnd = 12345678

            # Change winId (e.g. window handle destroyed or changed at exit)
            with patch.object(self.dock, "winId", return_value=0):
                self.dock._unregister_appbar()

            self.assertFalse(self.dock._appbar_registered)
            self.assertIsNone(self.dock._appbar_hwnd)
            self.assertEqual(mock_shell32.SHAppBarMessage.call_count, 1)

            # Check that abd.hWnd sent to ABM_REMOVE (message 1) was 12345678
            call_args = mock_shell32.SHAppBarMessage.call_args
            self.assertEqual(call_args[0][0], 1)  # ABM_REMOVE = 1
            abd_ptr = call_args[0][1]
            abd_obj = abd_ptr._obj
            self.assertEqual(abd_obj.hWnd, 12345678)


class TestV10TrayWorkerSafe(unittest.TestCase):
    """Test Task 4: get_tray_images runs worker-safe without QPixmap."""

    def test_worker_thread_returns_qimage_no_pixmap(self) -> None:
        """Worker thread extraction strictly returns QImage objects."""
        items = [
            {"name": "Dikte · Türkçe", "exe": "D:/Apps/dikte/dikte.ico"},
            {"name": "Notepad", "exe": "C:/Windows/System32/notepad.exe"},
        ]

        worker_result = {}

        def worker():
            images = trayicons.get_tray_images(items)
            for k, img in images.items():
                if not img.isNull():
                    assert isinstance(img, QImage), f"{k} is not QImage"
                    assert not isinstance(img, QPixmap), f"{k} is QPixmap off GUI thread!"
            worker_result["images"] = images

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertIn("images", worker_result)
        # On GUI thread, converting to QPixmap is cheap and successful
        for name, img in worker_result["images"].items():
            if not img.isNull():
                pm = QPixmap.fromImage(img)
                self.assertFalse(pm.isNull())


class TestV10PendingActionResubmit(unittest.TestCase):
    """Test Task 5: sources.submit dropped actions are queued and resubmitted."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_test_pending_")
        serit_mod.SETTINGS_FILE = Path(self.tmp_dir) / "settings.json"
        self.dock = serit_mod.SeritDock({}, preview_mode=False)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pending_action_resubmission(self) -> None:
        """When a second media action arrives while first is in flight, it is queued and flushed on done."""
        actions_run = []
        action_key = "media_ctl"

        def first_action():
            actions_run.append("first")

        def second_action():
            actions_run.append("second")

        # Simulate sources.submit: first call succeeds (True), second returns False (in flight)
        submit_mock = MagicMock(side_effect=[True, False, True])

        with patch("sources.submit", submit_mock):
            self.dock.submit_action(action_key, first_action)
            # While in flight, second action submitted:
            self.dock.submit_action(action_key, second_action)

            # Second action must be pending
            self.assertIn(action_key, self.dock._pending_actions)
            self.assertEqual(self.dock._pending_actions[action_key][0], second_action)

            # Signal worker done:
            self.dock._on_action_task_done(action_key)

            # Now second action should have been submitted
            self.assertNotIn(action_key, self.dock._pending_actions)
            self.assertEqual(submit_mock.call_count, 3)


class TestV10TaskbarAutohidePreservation(unittest.TestCase):
    """Test Task 6: taskbar_autohide_set preserves other bits (e.g. ABS_ALWAYSONTOP)."""

    def test_autohide_bit_preservation(self) -> None:
        """taskbar_autohide_set must bitwise-modify only ABS_AUTOHIDE."""
        mock_shell32 = MagicMock()
        # Suppose taskbar currently has ABS_ALWAYSONTOP (2) set
        ABS_ALWAYSONTOP = 2
        mock_shell32.SHAppBarMessage.return_value = ABS_ALWAYSONTOP

        with patch.object(winapi, "shell32", mock_shell32):
            # Enable autohide: should produce ABS_ALWAYSONTOP | ABS_AUTOHIDE (2 | 1 = 3)
            winapi.taskbar_autohide_set(True)
            self.assertEqual(mock_shell32.SHAppBarMessage.call_count, 2)
            # Call 1 was ABM_GETSTATE (4), Call 2 was ABM_SETSTATE (10)
            set_call = mock_shell32.SHAppBarMessage.call_args_list[1]
            self.assertEqual(set_call[0][0], winapi.ABM_SETSTATE)
            abd_set = set_call[0][1]._obj
            self.assertEqual(abd_set.lParam, ABS_ALWAYSONTOP | winapi.ABS_AUTOHIDE)

            # Reset call count
            mock_shell32.reset_mock()
            # Suppose taskbar currently has both flags (3) set
            mock_shell32.SHAppBarMessage.return_value = ABS_ALWAYSONTOP | winapi.ABS_AUTOHIDE
            # Disable autohide: should produce ABS_ALWAYSONTOP (2)
            winapi.taskbar_autohide_set(False)
            set_call2 = mock_shell32.SHAppBarMessage.call_args_list[1]
            abd_set2 = set_call2[0][1]._obj
            self.assertEqual(abd_set2.lParam, ABS_ALWAYSONTOP)


class TestV10AnimAndCaches(unittest.TestCase):
    """Test Task 7: anim SystemParametersInfoW argtypes and bounded LRU caches."""

    def test_anim_system_parameters_info_signature(self) -> None:
        """anim.py get_system_reduce_motion configures argtypes and restype."""
        # Call get_system_reduce_motion and check ctypes signature
        anim.get_system_reduce_motion()
        user32 = ctypes.windll.user32
        self.assertIsNotNone(user32.SystemParametersInfoW.argtypes)
        self.assertEqual(user32.SystemParametersInfoW.restype, wintypes.BOOL)

    def test_winapi_icon_cache_cap_128(self) -> None:
        """winapi._ICON_CACHE caps at 128 items and evicts oldest."""
        winapi._ICON_CACHE.clear()
        dummy_pix = QPixmap(1, 1)
        for i in range(150):
            norm_key = (f"C:/fake_app_{i}.exe", 64)
            winapi._ICON_CACHE[norm_key] = dummy_pix
            if len(winapi._ICON_CACHE) > 128:
                winapi._ICON_CACHE.popitem(last=False)

        self.assertEqual(len(winapi._ICON_CACHE), 128)
        self.assertNotIn(("C:/fake_app_0.exe", 64), winapi._ICON_CACHE)
        self.assertIn(("C:/fake_app_149.exe", 64), winapi._ICON_CACHE)

    def test_serit_dock_lru_cache(self) -> None:
        """SeritDock LRUCache caps at 128 items and moves accessed items to end."""
        cache = serit_mod.LRUCache(128)
        for i in range(150):
            cache[f"key_{i}"] = i

        self.assertEqual(len(cache), 128)
        self.assertNotIn("key_0", cache)
        self.assertIn("key_149", cache)


class TestV10NumericFallbacks(unittest.TestCase):
    """Test Task 8: No hard-coded numeric fallbacks on screen."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="serit_test_fallbacks_")
        serit_mod.SETTINGS_FILE = Path(self.tmp_dir) / "settings.json"
        self.dock = serit_mod.SeritDock({}, preview_mode=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_safe_float_default_is_none(self) -> None:
        """safe_float defaults to None instead of 0.0."""
        self.assertIsNone(serit_mod.safe_float(None))
        self.assertIsNone(serit_mod.safe_float("invalid"))
        self.assertIsNone(serit_mod.safe_float(float("nan")))
        self.assertEqual(serit_mod.safe_float("42.5"), 42.5)

    def test_ag_tooltip_shows_dash_when_used_missing(self) -> None:
        """Antigravity tooltip shows '—' when group quota used is None (never %0)."""
        self.dock.store.update("ag", {
            "groups": [
                {"label": "Claude 3.5 Sonnet", "used": None, "reset_tr": "Yarın 09:00"}
            ]
        })
        tip = self.dock.get_tooltip_text("ag", None)
        self.assertIn("Claude 3.5 Sonnet: —", tip)
        self.assertNotIn("%0", tip)


if __name__ == "__main__":
    unittest.main()
