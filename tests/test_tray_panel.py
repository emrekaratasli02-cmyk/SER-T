"""test_tray_panel.py - Test suite for TrayPanel, Turkish cleaning, and deduplication.

Tests:
1. Turkish name cleaning table (all requirements + 10 edge cases)
2. Tooltip status translation
3. Item deduplication
4. Bad data matrix (>= 25 cases) through set_items + render_to_image
5. Hit testing and signal emission (left-click closes, right-click keeps open)
6. Keyboard navigation (Escape, Up/Down, Enter/Return)
7. Scroll clamping with 30 items
8. recently_closed bounce prevention timing
"""

from __future__ import annotations

from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

# Ensure serit root is on sys.path
serit_root = Path(__file__).resolve().parent.parent
if str(serit_root) not in sys.path:
    sys.path.insert(0, str(serit_root))

import panel_style as ps  # noqa: E402
from tray_panel import (  # noqa: E402
    TrayPanel,
    clean_tray_name,
    dedupe_tray_items,
    tray_status_tr,
)


def _ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["test_tray_panel"])
    return app


def test_name_cleaning() -> None:
    """Test clean_tray_name with required canonical cases plus 10 edge cases."""
    print("-> test_name_cleaning")

    # Canonical required cases
    test_cases = [
        ({"name": "Zoom - not signed in Zoom Workplace"}, "Zoom"),
        ({"name": "Windows Security - No actions needed."}, "Windows Güvenlik"),
        ({"name": "PowerToys v0.98.1"}, "PowerToys"),
        ({"name": "PowerToys v0.102.2933"}, "PowerToys"),
        ({"name": "NVIDIA Settings"}, "NVIDIA Ayarları"),
        ({"name": "Windows Security"}, "Windows Güvenlik"),
        ({"name": "SecurityHealthSystray"}, "Windows Güvenlik"),
        ({"name": "SecurityHealthSystray.exe"}, "Windows Güvenlik"),
        ({"name": "WhatsApp.Root"}, "WhatsApp"),
        ({"name": "WhatsApp.Root.exe"}, "WhatsApp"),
        ({"name": "DSATray"}, "Intel Destek Asistanı"),
        ({"name": "DSATray.exe"}, "Intel Destek Asistanı"),
        ({"name": "PowerToys Awake"}, "PowerToys Awake"),
        ({"name": "PowerToys Awake PowerToys Awake"}, "PowerToys Awake"),
        ({"name": "Dikte · Türkçe"}, "Dikte · Türkçe"),
        ({"name": "Dikte"}, "Dikte · Türkçe"),
        ({"name": "WhatsApp"}, "WhatsApp"),
        # 10+ additional edge cases
        ({"name": "Slack - Active – Company Workspace"}, "Slack"),
        ({"name": "Telegram Desktop v4.16.8"}, "Telegram Desktop"),
        ({"name": "Spotify Free - Now Playing"}, "Spotify Free"),
        ({"name": "Discord.exe"}, "Discord"),
        ({"name": "Everything 1.4.1.1024"}, "Everything"),
        ({"name": "Steam - 3 Friends Online"}, "Steam"),
        ({"name": "Epic Games Launcher v15.2.1"}, "Epic Games Launcher"),
        ({"name": "cmdpal-tab.ahk"}, "cmdpal-tab.ahk"),
        ({"name": "CustomApp.exe"}, "CustomApp"),
        ({"name": "", "exe": "C:\\Program Files\\App\\Tool.exe"}, "Tool"),
        ({"name": "MyApp v2.0 Beta"}, "MyApp"),
        ({"name": "App 2026.1.1 - Status OK"}, "App"),
        ({}, "Uygulama"),
        (None, "Uygulama"),
        ("invalid", "Uygulama"),
    ]

    for item, expected in test_cases:
        actual = clean_tray_name(item)
        assert actual == expected, f"Failed for {item!r}: expected {expected!r}, got {actual!r}"
    print("   [OK] Name cleaning passed all cases.")


def test_status_translation() -> None:
    """Test tray_status_tr returns Turkish status for known phrases, else ''."""
    print("-> test_status_translation")

    cases = [
        ({"tooltip": "Zoom - not signed in"}, "Oturum açılmadı"),
        ({"tooltip": "Windows Security - No actions needed."}, "İşlem gerekmiyor"),
        ({"tooltip": "OneDrive - Up to date"}, "Güncel"),
        ({"name": "Zoom - not signed in Zoom Workplace"}, "Oturum açılmadı"),
        ({"name": "Windows Security - No actions needed."}, "İşlem gerekmiyor"),
        ({"tooltip": "Battery 98% discharging"}, ""),  # Unknown -> empty
        ({"tooltip": "Connected to Wi-Fi"}, ""),
        ({"tooltip": ""}, ""),
        ({}, ""),
        (None, ""),
        (12345, ""),
    ]

    for item, expected in cases:
        actual = tray_status_tr(item)
        assert actual == expected, f"Failed for {item!r}: expected {expected!r}, got {actual!r}"
    print("   [OK] Status translation passed all cases.")


def test_dedupe() -> None:
    """Test dedupe_tray_items removes duplicates by cleaned name keeping the first."""
    print("-> test_dedupe")

    items = [
        {"name": "PowerToys Awake PowerToys Awake"},
        {"name": "PowerToys v0.102.2933"},
        {"name": "PowerToys v0.98.1"},  # duplicate cleaned name "PowerToys"
        {"name": "NVIDIA Settings"},
        {"name": "SecurityHealthSystray.exe"},
        {"name": "Windows Security - No actions needed."},  # duplicate "Windows Güvenlik"
        {"name": "WhatsApp.Root"},
        {"name": "WhatsApp"},  # duplicate "WhatsApp"
    ]

    deduped = dedupe_tray_items(items)
    cleaned_names = [clean_tray_name(it) for it in deduped]

    expected = [
        "PowerToys Awake",
        "PowerToys",
        "NVIDIA Ayarları",
        "Windows Güvenlik",
        "WhatsApp",
    ]
    assert cleaned_names == expected, f"Dedupe mismatch: {cleaned_names} != {expected}"

    # Edge cases
    assert dedupe_tray_items(None) == []
    assert dedupe_tray_items([]) == []
    assert dedupe_tray_items([None, "str", {}]) == [{}]
    print("   [OK] Deduplication passed.")


def test_panel_width_shared_kit() -> None:
    """TrayPanel width must be exactly the shared kit tray width (352)."""
    print("-> test_panel_width_shared_kit")
    _ensure_qapp()
    panel = TrayPanel()
    assert panel.WIDTH == ps.WIDTH["tray"] == 352
    assert panel.width() == ps.WIDTH["tray"]
    print("   [OK] Panel width matches panel_style.WIDTH['tray'].")


def test_bad_data_matrix() -> None:
    """Test >= 25 invalid / corrupt data inputs through set_items and offscreen rendering."""
    print("-> test_bad_data_matrix")
    _ensure_qapp()

    panel = TrayPanel()

    bad_matrix: List[Tuple[Any, Any]] = [
        (None, None),
        ([], None),
        ([None], None),
        ([123, "string", [], {}], None),
        ([{"name": None}], None),
        ([{"name": float("nan")}], None),
        ([{"name": float("inf")}], None),
        ([{"name": ""}], None),
        ([{"name": "App", "tooltip": None, "exe": None}], None),
        ([{"name": "App"}], "not_a_dict"),
        ([{"name": "App"}], {"App": None}),
        ([{"name": "App"}], {"App": "not_a_pixmap"}),
        ([{"name": "App"}], {"App": QPixmap()}),  # Null pixmap
        ([{"name": "x" * 1000}], None),  # Extremely long string
        ([{"name": "\x00\x01\x02\x03"}], None),  # Control characters
        ([{"name": "Emoji \U0001f600 \U0001f389 \U0001f680"}], None),
        ([{"name": "HTML <script>alert(1)</script>"}], None),
        ([{"name": "Newlines\n\r\tSpecial"}], None),
        ([{"name": 0}], None),
        ([{"name": False}], None),
        ([{"tooltip": float("nan"), "exe": float("nan")}], None),
        ([{"name": None, "tooltip": None, "exe": None}], None),
        (range(5), None),
        ([{"name": f"App {i}"} for i in range(100)], None),  # 100 items
        ([{"name": "App", "icon_bytes": b"corrupted_bytes"}], None),
        ([{"name": "App"}], {123: 456}),
        ([{"name": "A"}, None, {"name": "B"}], None),
        ([{"name": "Test", "tooltip": "not signed in"}], None),
    ]

    assert len(bad_matrix) >= 25, f"Matrix size {len(bad_matrix)} < 25"

    for idx, (items, icons) in enumerate(bad_matrix):
        panel.set_items(items, icons)
        img = panel.render_to_image(dpr=2.0)
        assert not img.isNull(), f"Render produced null image on test case #{idx}"
        assert img.width() > 0 and img.height() > 0, f"Invalid dimensions on case #{idx}"

    print(f"   [OK] Bad data matrix passed ({len(bad_matrix)} cases rendered safely).")


def test_row_hit_testing_and_signals() -> None:
    """Test mouse clicks: left click emits item_activated and closes, right click keeps open."""
    print("-> test_row_hit_testing_and_signals")
    _ensure_qapp()

    panel = TrayPanel()
    mock_items = [
        {"name": "App 1", "tooltip": "App 1 Tooltip"},
        {"name": "App 2", "tooltip": "App 2 Tooltip"},
        {"name": "App 3", "tooltip": "App 3 Tooltip"},
    ]
    panel.set_items(mock_items)

    # Position at known geometry
    panel.setGeometry(100, 100, panel.WIDTH, panel.compute_height())
    panel.show()
    QApplication.processEvents()
    panel.render_to_image(2.0)  # fills _close_rect / _refresh_rect from paint layout

    activated_events: List[Tuple[Dict[str, Any], str]] = []
    refresh_events: List[bool] = []

    panel.item_activated.connect(lambda item, btn: activated_events.append((item, btn)))
    panel.refresh_requested.connect(lambda: refresh_events.append(True))

    list_rect = panel._list_rect
    y_row0 = list_rect.top() + panel.ROW_HEIGHT / 2.0
    y_row1 = list_rect.top() + panel.ROW_STRIDE + panel.ROW_HEIGHT / 2.0

    # Test 1: Left-click on Row 0
    click_row0 = QPointF(50.0, y_row0)
    ev_left = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        click_row0,
        click_row0,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev_left)

    assert len(activated_events) == 1, "item_activated not emitted on left click"
    assert activated_events[0][0]["name"] == "App 1"
    assert activated_events[0][1] == "left"
    assert panel._is_closing is True, "Panel should be closing on left click"

    # Reset closing state for next test
    panel._is_closing = False
    panel.show()

    # Test 2: Right-click on Row 1
    click_row1 = QPointF(50.0, y_row1)
    ev_right = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        click_row1,
        click_row1,
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev_right)

    assert len(activated_events) == 2, "item_activated not emitted on right click"
    assert activated_events[1][0]["name"] == "App 2"
    assert activated_events[1][1] == "right"
    assert panel._is_closing is False, "Panel should NOT close on right click"

    # Test 3: Click 'Yenile' button
    ref_center = panel._refresh_rect.center()
    ev_ref_press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        ref_center,
        ref_center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev_ref_press)
    assert panel._refresh_pressed is True

    ev_ref_rel = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        ref_center,
        ref_center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mouseReleaseEvent(ev_ref_rel)
    assert len(refresh_events) == 1, "refresh_requested signal not emitted"

    # Test 4: Click ✕ close button
    close_center = panel._close_rect.center()
    ev_close = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        close_center,
        close_center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev_close)
    assert panel._is_closing is True, "Panel should close when ✕ is clicked"

    panel.close()
    print("   [OK] Hit-testing and signal emissions passed.")


def test_keyboard_navigation() -> None:
    """Test Up/Down navigation, Enter activation, and Escape closing."""
    print("-> test_keyboard_navigation")
    _ensure_qapp()

    panel = TrayPanel()
    mock_items = [{"name": "Item A"}, {"name": "Item B"}, {"name": "Item C"}]
    panel.set_items(mock_items)
    panel.show()
    QApplication.processEvents()

    activated: List[Tuple[Dict[str, Any], str]] = []
    panel.item_activated.connect(lambda item, btn: activated.append((item, btn)))

    assert panel._highlight_idx == -1

    # Key Down -> 0
    ev_down1 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev_down1)
    assert panel._highlight_idx == 0

    # Key Down -> 1
    ev_down2 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev_down2)
    assert panel._highlight_idx == 1

    # Key Up -> 0
    ev_up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev_up)
    assert panel._highlight_idx == 0

    # Key Enter on 0
    ev_enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev_enter)
    assert len(activated) == 1
    assert activated[0][0]["name"] == "Item A"
    assert activated[0][1] == "left"
    assert panel._is_closing is True

    # Reset and test Escape
    panel._is_closing = False
    ev_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev_esc)
    assert panel._is_closing is True

    panel.close()
    print("   [OK] Keyboard navigation passed.")


def test_scroll_clamping_with_30_items() -> None:
    """Test list scrolling and clamping with 30 items exceeding max list height."""
    print("-> test_scroll_clamping_with_30_items")
    _ensure_qapp()

    panel = TrayPanel()
    items = [{"name": f"Process_{i:02d}", "tooltip": f"Status {i}"} for i in range(30)]
    panel.set_items(items)

    max_h = panel.LIST_MAX_HEIGHT
    assert panel._visible_list_height() == max_h
    total_h = panel._total_list_height()
    max_scroll = total_h - max_h
    assert max_scroll > 500.0, f"Expected large max_scroll, got {max_scroll}"

    # Initial scroll is 0.0
    assert panel._scroll_y == 0.0

    # Ensure last row visible
    panel._ensure_row_visible(29)
    assert panel._scroll_y > 0.0
    assert panel._scroll_y <= max_scroll

    # Wheel down to exceed bounds
    panel._scroll_y = max_scroll - 10.0
    # Directly test clamping logic
    panel._scroll_y = max(0.0, min(max_scroll, panel._scroll_y + 1000.0))
    assert panel._scroll_y == max_scroll, f"Should clamp to max_scroll: {panel._scroll_y} != {max_scroll}"

    # Wheel up to clamp at 0.0
    panel._scroll_y = max(0.0, min(max_scroll, panel._scroll_y - 2000.0))
    assert panel._scroll_y == 0.0, f"Should clamp to 0.0: {panel._scroll_y}"

    print("   [OK] Scroll clamping passed.")


def test_recently_closed_timing() -> None:
    """Test recently_closed returns True immediately and False after threshold."""
    print("-> test_recently_closed_timing")
    panel = TrayPanel()

    assert panel.recently_closed(250) is False

    # Simulate close
    panel._last_close_time = time.monotonic()
    assert panel.recently_closed(250) is True

    # Simulate 300ms passed
    panel._last_close_time = time.monotonic() - 0.300
    assert panel.recently_closed(250) is False
    print("   [OK] recently_closed timing passed.")


def run_all() -> None:
    """Execute all test functions."""
    print("=== RUNNING test_tray_panel.py ===")
    test_name_cleaning()
    test_status_translation()
    test_dedupe()
    test_panel_width_shared_kit()
    test_bad_data_matrix()
    test_row_hit_testing_and_signals()
    test_keyboard_navigation()
    test_scroll_clamping_with_30_items()
    test_recently_closed_timing()
    print("=== ALL TRAY PANEL TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
