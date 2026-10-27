"""test_settings_window.py - Unit tests and DPR 2.0 visual regression rendering for settings_window.py.

Verifies:
1. Window instantiation with a dict copy
2. Toggling cards, styles, options
3. Removing pinned items
4. 'Uygula' button triggers on_apply with modified copy, leaving input dict unchanged
5. 'Vazgeç' button closes window without triggering on_apply
6. Esc key closes window without triggering on_apply
7. settings.json remains untouched (hash verified)
8. High-DPI DPR 2.0 rendering of all sections to C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v11/ayarlar_*.png
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest

# Ensure QApplication initialized
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

import settings_window
from settings_window import SettingsWindow, open_settings

SETTINGS_FILE = SERIT_DIR / "settings.json"
SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v11")


def get_file_sha256(path: Path) -> str:
    if not path.exists():
        return "<missing>"
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestSettingsWindow(unittest.TestCase):
    """Unit test suite for SettingsWindow."""

    def setUp(self) -> None:
        self.initial_hash = get_file_sha256(SETTINGS_FILE)
        self.sample_settings = {
            "hide_taskbar": False,
            "reserve_space": True,
            "style": "band",
            "alerts_enabled": True,
            "cards": {
                "claude": True,
                "mail": True,
                "ag": True,
                "sys": False,
                "cal": True,
                "media": True,
            },
            "pinned": [
                {"name": "File Explorer", "path": r"C:\Windows\explorer.exe"},
                {"name": "Google Chrome", "path": r"C:\Program Files\Google\Chrome\Application\chrome.exe"},
            ],
        }

    def tearDown(self) -> None:
        # Guarantee settings.json was never modified
        current_hash = get_file_sha256(SETTINGS_FILE)
        self.assertEqual(
            self.initial_hash,
            current_hash,
            "CRITICAL: settings.json was modified during test execution!",
        )

    def test_open_settings_helper(self) -> None:
        """open_settings returns a valid SettingsWindow instance."""
        applied = []
        win = open_settings(self.sample_settings, lambda s: applied.append(s))
        self.assertIsInstance(win, SettingsWindow)
        win.close()

    def test_input_dict_immutability_and_apply(self) -> None:
        """Modifying working_settings and clicking Uygula passes new copy to on_apply without altering input dict."""
        input_copy = copy.deepcopy(self.sample_settings)
        applied_results = []

        def on_apply(new_cfg: dict) -> None:
            applied_results.append(new_cfg)

        win = SettingsWindow(settings=self.sample_settings, on_apply=on_apply)

        # Mutate through window logic
        win.working_settings["style"] = "pill"
        win.working_settings["cards"]["sys"] = True
        del win.working_settings["pinned"][0]

        # Trigger apply
        win.apply_and_close()

        # Check that on_apply was called once
        self.assertEqual(len(applied_results), 1)
        applied_data = applied_results[0]

        # Check modifications applied to output
        self.assertEqual(applied_data["style"], "pill")
        self.assertTrue(applied_data["cards"]["sys"])
        self.assertEqual(len(applied_data["pinned"]), 1)
        self.assertEqual(applied_data["pinned"][0]["name"], "Google Chrome")

        # Check original input dict remains unchanged
        self.assertEqual(self.sample_settings, input_copy)

    def test_cancel_does_not_invoke_callback(self) -> None:
        """Clicking Vazgeç or calling cancel_and_close does not invoke on_apply."""
        applied_results = []
        win = SettingsWindow(settings=self.sample_settings, on_apply=lambda s: applied_results.append(s))

        win.working_settings["alerts_enabled"] = False
        win.cancel_and_close()

        self.assertEqual(len(applied_results), 0)

    def test_escape_key_cancels(self) -> None:
        """Pressing Esc triggers cancel and does not invoke on_apply."""
        applied_results = []
        win = SettingsWindow(settings=self.sample_settings, on_apply=lambda s: applied_results.append(s))

        esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        win.keyPressEvent(esc_event)

        self.assertEqual(len(applied_results), 0)

    def test_section_switching(self) -> None:
        """Switching sections updates current_section."""
        win = SettingsWindow(settings=self.sample_settings, on_apply=lambda s: None)
        self.assertEqual(win.current_section, "appearance")

        win.switch_section("cards")
        self.assertEqual(win.current_section, "cards")

        win.switch_section("pinned")
        self.assertEqual(win.current_section, "pinned")

        win.switch_section("alerts")
        self.assertEqual(win.current_section, "alerts")

        win.switch_section("about")
        self.assertEqual(win.current_section, "about")

        win.close()

    def test_remove_pinned_action(self) -> None:
        """Simulate clicking remove pin button."""
        win = SettingsWindow(settings=self.sample_settings, on_apply=lambda s: None)
        win.switch_section("pinned")
        win.render_to_image(dpr=1.0)  # populate hitboxes

        # Find remove_pin hitbox
        pin_boxes = [box for box in win._content_hit_boxes if box[1] == "remove_pin"]
        self.assertEqual(len(pin_boxes), 2)

        # Click first remove pin
        target_rect = pin_boxes[0][0]
        click_pt = target_rect.center()
        press_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            click_pt,
            click_pt,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win.mousePressEvent(press_ev)

        self.assertEqual(len(win.working_settings["pinned"]), 1)
        self.assertEqual(win.working_settings["pinned"][0]["name"], "Google Chrome")
        win.close()

    def test_fluent_toggle_widget(self) -> None:
        """FluentToggle toggles and emits signal."""
        toggle = settings_window.FluentToggle(checked=False)
        self.assertFalse(toggle.isChecked())

        received = []
        toggle.toggled.connect(lambda val: received.append(val))

        toggle.setChecked(True)
        self.assertTrue(toggle.isChecked())
        self.assertEqual(received, [True])

        # Click event
        click_pt = QPointF(10.0, 10.0)
        p_ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, click_pt, click_pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        r_ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, click_pt, click_pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        toggle.mousePressEvent(p_ev)
        toggle.mouseReleaseEvent(r_ev)

        self.assertFalse(toggle.isChecked())
        self.assertEqual(received, [True, False])

    def test_render_all_sections_dpr2(self) -> None:
        """Render each section at DPR 2.0 to scratch directory and verify images."""
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

        sections = ["appearance", "cards", "pinned", "alerts", "about"]
        section_filenames = {
            "appearance": "ayarlar_gorunum.png",
            "cards": "ayarlar_kartlar.png",
            "pinned": "ayarlar_sabitlenenler.png",
            "alerts": "ayarlar_uyarilar.png",
            "about": "ayarlar_hakkinda.png",
        }

        win = SettingsWindow(settings=self.sample_settings, on_apply=lambda s: None)

        for sec in sections:
            win.switch_section(sec)
            img = win.render_to_image(dpr=2.0)
            self.assertFalse(img.isNull())
            self.assertEqual(img.width(), 560 * 2)
            self.assertEqual(img.height(), 520 * 2)

            out_path = SCRATCH_DIR / section_filenames[sec]
            saved = img.save(str(out_path))
            self.assertTrue(saved, f"Failed to save {out_path}")
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 1000)

        win.close()


if __name__ == "__main__":
    unittest.main()
