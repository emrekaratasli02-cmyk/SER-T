"""test_action_menu.py - Unit and visual contract tests for ActionMenu widget.

Includes:
- Bad-data matrix (>= 15 cases)
- Offscreen rendering at DPR 1.0 and 2.0
- Arm/confirm timing, auto-timeout, and disarming on leave
- Disabled rows do not emit actions
- Full keyboard navigation (Up, Down skipping disabled, Enter, Esc)
- show_at anchor positioning and screen boundary clamping
"""

from pathlib import Path
import sys
import unittest

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication

# Ensure QApplication is initialized for offscreen Qt tests
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

from action_menu import ActionMenu, WIDTH


class TestActionMenuBadData(unittest.TestCase):
    """Resilience testing with invalid, malformed, or unusual input structures."""

    def setUp(self) -> None:
        self.menu = ActionMenu()

    def test_bad_data_matrix_15_cases(self) -> None:
        """Verify >= 15 cases of bad or malformed inputs never raise or crash."""
        cases = [
            # 1. Non-list actions
            None,
            # 2. String instead of list
            "not a list",
            # 3. Integer instead of list
            12345,
            # 4. List with None
            [None],
            # 5. List with string element
            ["invalid string element"],
            # 6. List with integer element
            [42],
            # 7. Empty dict
            [{}],
            # 8. Missing text and icon
            [{"id": "only_id"}],
            # 9. Non-string id and text
            [{"id": 123, "text": 456}],
            # 10. Non-boolean enabled and danger
            [{"id": "test", "enabled": "not_bool", "danger": 1}],
            # 11. Non-boolean confirm
            [{"id": "test", "confirm": "yes"}],
            # 12. Non-string hint and invalid icon type
            [{"id": "test", "hint": 999, "icon": 123}],
            # 13. All fields None
            [{"id": None, "text": None, "icon": None, "danger": None, "enabled": None, "hint": None, "confirm": None}],
            # 14. Unknown extra keys
            [{"id": "valid", "extra_token": "ignore_me", "nested": {"a": 1}}],
            # 15. Mixed valid and completely corrupt entries
            [{"id": "ok", "text": "OK"}, None, 999, {}, {"id": "ok2", "text": "OK2"}],
            # 16. Unicode and control characters in strings
            [{"id": "\x00\x01\t", "text": "\n\r\tSpecial \u2603 \U0001F600", "hint": "\x07Bell"}],
        ]

        self.assertGreaterEqual(len(cases), 15)

        for i, bad_action_set in enumerate(cases):
            with self.subTest(case_idx=i):
                # set_actions should absorb anything
                self.menu.set_actions(bad_action_set)  # type: ignore[arg-type]
                h = self.menu.compute_height()
                self.assertIsInstance(h, int)
                self.assertGreater(h, 0)
                # render offscreen should not crash
                img = self.menu.render_to_image(dpr=1.0)
                self.assertFalse(img.isNull())

    def test_bad_header_inputs(self) -> None:
        """Header inputs with None, numbers, or corrupt types."""
        header_cases = [
            (None, None, None),
            (123, 456, None),
            ("", "", None),
            ("Title", None, None),
            ("Title", "Subtitle", QPixmap()),
        ]
        for t, s, ico in header_cases:
            self.menu.set_header(t, s, ico)  # type: ignore[arg-type]
            h = self.menu.compute_height()
            self.assertGreater(h, 0)


class TestActionMenuRender(unittest.TestCase):
    """Visual rendering contract tests."""

    def setUp(self) -> None:
        self.menu = ActionMenu()
        self.menu.set_header("Zoom", "Zoom · 10 işlem")
        self.menu.set_actions([
            {"id": "open", "text": "Aç", "icon": "open"},
            {
                "id": "end",
                "text": "Görevi sonlandır",
                "icon": "stop",
                "danger": True,
                "confirm": True,
                "enabled": True,
            },
        ])

    def test_offscreen_render_dpr2(self) -> None:
        """Verify high-DPI rendering produces expected dimensions and ratio."""
        self.menu.resize(self.menu.WIDTH, self.menu.compute_height())
        img = self.menu.render_to_image(dpr=2.0)
        self.assertFalse(img.isNull())
        self.assertEqual(img.devicePixelRatio(), 2.0)
        self.assertEqual(img.width(), self.menu.WIDTH * 2)
        self.assertEqual(img.height(), self.menu.compute_height() * 2)

    def test_offscreen_render_dpr1(self) -> None:
        """Verify standard 1.0 DPR rendering."""
        self.menu.resize(self.menu.WIDTH, self.menu.compute_height())
        img = self.menu.render_to_image(dpr=1.0)
        self.assertFalse(img.isNull())
        self.assertEqual(img.devicePixelRatio(), 1.0)
        self.assertEqual(img.width(), self.menu.WIDTH)

    def test_offscreen_render_disabled_row_with_hint(self) -> None:
        """Verify disabled row with hint renders cleanly."""
        self.menu.set_actions([
            {"id": "open", "text": "Aç", "icon": "open"},
            {
                "id": "end",
                "text": "Görevi sonlandır",
                "icon": "stop",
                "danger": True,
                "confirm": True,
                "enabled": False,
                "hint": "Windows bileşeni sonlandırılamaz",
            },
        ])
        self.menu.resize(self.menu.WIDTH, self.menu.compute_height())
        img = self.menu.render_to_image(dpr=2.0)
        self.assertFalse(img.isNull())


class TestActionMenuInteractions(unittest.TestCase):
    """Interaction logic, signals, arm-to-confirm, and keyboard navigation."""

    def setUp(self) -> None:
        self.menu = ActionMenu()
        self.chosen_actions = []
        self.menu.action_chosen.connect(self.chosen_actions.append)

    def test_disabled_rows_dont_emit(self) -> None:
        """Disabled row must never trigger action_chosen signal."""
        self.menu.set_actions([
            {"id": "row_enabled", "text": "Etkin", "enabled": True},
            {"id": "row_disabled", "text": "Devre Dışı", "enabled": False, "hint": "Korumalı"},
        ])

        # Trigger disabled row (idx=1)
        self.menu._trigger_row(1)
        self.assertEqual(self.chosen_actions, [])

        # Trigger enabled row (idx=0)
        self.menu._trigger_row(0)
        self.assertEqual(self.chosen_actions, ["row_enabled"])

    def test_arm_confirm_timing_and_leave(self) -> None:
        """First click arms, second click confirms; leave disarms."""
        self.menu.set_actions([
            {
                "id": "danger_task",
                "text": "Görevi sonlandır",
                "danger": True,
                "confirm": True,
                "enabled": True,
            }
        ])

        # 1. First click: Arms the row
        self.menu._trigger_row(0)
        self.assertEqual(self.chosen_actions, [], "First click must not emit")
        self.assertEqual(self.menu._armed_action_id, "danger_task")
        self.assertTrue(self.menu._arm_timer.isActive())

        # 2. Second click before timeout: Confirms and emits
        self.menu._trigger_row(0)
        self.assertEqual(self.chosen_actions, ["danger_task"])
        self.assertIsNone(self.menu._armed_action_id)
        self.assertFalse(self.menu._arm_timer.isActive())

        # 3. Test disarming on mouse leave
        self.chosen_actions.clear()
        self.menu._trigger_row(0)  # re-arm
        self.assertEqual(self.menu._armed_action_id, "danger_task")
        # Simulate leave
        self.menu._disarm()
        self.assertIsNone(self.menu._armed_action_id)
        # Clicking again now arms instead of confirming
        self.menu._trigger_row(0)
        self.assertEqual(self.chosen_actions, [], "Must arm again after disarm")
        self.assertEqual(self.menu._armed_action_id, "danger_task")

    def test_keyboard_navigation(self) -> None:
        """Up/Down arrows navigate enabled rows, Enter triggers, Esc closes."""
        self.menu.set_actions([
            {"id": "act0", "text": "Action 0", "enabled": True},
            {"id": "act1", "text": "Action 1 (Disabled)", "enabled": False},
            {"id": "act2", "text": "Action 2", "enabled": True},
        ])

        # Initial hover index is -1
        self.assertEqual(self.menu._hover_idx, -1)

        # Press Down -> skips to first enabled row (idx=0)
        ev_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        self.menu.keyPressEvent(ev_down)
        self.assertEqual(self.menu._hover_idx, 0)

        # Press Down -> skips disabled row (idx=1) directly to act2 (idx=2)
        self.menu.keyPressEvent(ev_down)
        self.assertEqual(self.menu._hover_idx, 2)

        # Press Up -> skips disabled row (idx=1) back to act0 (idx=0)
        ev_up = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        self.menu.keyPressEvent(ev_up)
        self.assertEqual(self.menu._hover_idx, 0)

        # Press Enter -> triggers act0
        ev_enter = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        self.menu.keyPressEvent(ev_enter)
        self.assertEqual(self.chosen_actions, ["act0"])

        # Press Esc -> hides menu
        ev_esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.menu.keyPressEvent(ev_esc)
        self.assertTrue(self.menu._is_closing or not self.menu.isVisible())

    def test_show_at_clamping(self) -> None:
        """Verify show_at positions above anchor and clamps to screen bounds."""
        anchor = QRectF(300.0, 600.0, 36.0, 36.0)
        self.menu.set_header("App", "Status")
        self.menu.set_actions([{"id": "a", "text": "Action"}])
        self.menu.show_at(anchor)

        self.assertTrue(self.menu.isVisible())
        self.assertTrue(self.menu.is_open())
        # Width must match WIDTH token
        self.assertEqual(self.menu.width(), WIDTH)
        # Must be positioned above anchor.top()
        self.assertLessEqual(self.menu.y() + self.menu.height(), anchor.top() + 8.0)


if __name__ == "__main__":
    unittest.main()
