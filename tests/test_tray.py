"""Unit tests and visual rendering verification for tray module.

Asserts 64-bit Win32 struct alignments for SendInput, verifies helper builders,
and renders high-DPI DPR 2 preview cards for the chevron button in normal, hover,
and open states.

SAFETY RULE: Keystrokes are NOT dispatched in this test suite.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys

# Add project root to sys.path
PROJECT_ROOT = Path("D:/Apps/serit")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import tray  # noqa: E402


def test_struct_sizes() -> None:
    """Verify exact Win32 struct sizes on 64-bit Windows."""
    size_input = ctypes.sizeof(tray.INPUT)
    size_ki = ctypes.sizeof(tray.KEYBDINPUT)
    size_mi = ctypes.sizeof(tray.MOUSEINPUT)
    size_hi = ctypes.sizeof(tray.HARDWAREINPUT)

    print(f"[TEST] sizeof(INPUT): {size_input} bytes (expected: 40)")
    print(f"[TEST] sizeof(KEYBDINPUT): {size_ki} bytes (expected: 24)")
    print(f"[TEST] sizeof(MOUSEINPUT): {size_mi} bytes (expected: 32)")
    print(f"[TEST] sizeof(HARDWAREINPUT): {size_hi} bytes (expected: 8)")

    assert size_input == 40, f"Expected sizeof(INPUT)==40 on 64-bit, got {size_input}"
    assert size_ki == 24, f"Expected sizeof(KEYBDINPUT)==24, got {size_ki}"
    assert size_mi == 32, f"Expected sizeof(MOUSEINPUT)==32, got {size_mi}"
    assert size_hi == 8, f"Expected sizeof(HARDWAREINPUT)==8, got {size_hi}"


def test_input_construction() -> None:
    """Verify keyboard INPUT construction helpers without sending input."""
    down_win = tray._make_key_input(tray.VK_LWIN, keyup=False)
    up_win = tray._make_key_input(tray.VK_LWIN, keyup=True)

    assert down_win.type == tray.INPUT_KEYBOARD
    assert down_win.ki.wVk == tray.VK_LWIN
    assert down_win.ki.dwFlags == 0

    assert up_win.type == tray.INPUT_KEYBOARD
    assert up_win.ki.wVk == tray.VK_LWIN
    assert up_win.ki.dwFlags == tray.KEYEVENTF_KEYUP

    # Build sequence of 4 chord inputs
    chord = (tray.INPUT * 4)(
        tray._make_key_input(tray.VK_LWIN, keyup=False),
        tray._make_key_input(tray.VK_B, keyup=False),
        tray._make_key_input(tray.VK_B, keyup=True),
        tray._make_key_input(tray.VK_LWIN, keyup=True),
    )
    assert len(chord) == 4
    assert ctypes.sizeof(chord) == 160
    print("[TEST] Successfully constructed INPUT array with length 4 (160 bytes)")


def render_preview_image(output_path: Path) -> None:
    """Render the chevron button in Normal, Hover, and Open states at DPR 2."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logical_w = 420
    logical_h = 160
    dpr = 2.0

    img = QImage(
        int(logical_w * dpr),
        int(logical_h * dpr),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(14, 16, 20, 255))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background subtle panel to contrast glass buttons
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(22, 26, 34, 255))
    p.drawRoundedRect(QRectF(16.0, 16.0, logical_w - 32.0, logical_h - 32.0), 16.0, 16.0)

    # Title
    font_title = QFont("Segoe UI Variable Text", 11)
    font_title.setBold(True)
    p.setFont(font_title)
    p.setPen(QColor(255, 255, 255, 230))
    p.drawText(QPointF(32.0, 42.0), "Şerit Dock - Hidden Tray Icons (^) Button")

    font_sub = QFont("Segoe UI Variable Text", 9)
    p.setFont(font_sub)

    # States: Normal, Hover, Open
    states = [
        ("Normal (hover=0.0)", 0.0, False, 50.0),
        ("Hover (hover=1.0)", 1.0, False, 175.0),
        ("Open / Active", 0.0, True, 300.0),
    ]

    btn_w = 34.0
    btn_h = 36.0
    btn_y = 66.0

    for label, hover_t, open_state, x in states:
        # Draw label centered under button
        lbl_w = 110.0
        lbl_rect = QRectF(x + (btn_w - lbl_w) / 2.0, btn_y + btn_h + 8.0, lbl_w, 20.0)
        p.setPen(QColor(200, 210, 225, 180))
        p.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, label)

        # Draw chevron button
        btn_rect = QRectF(x, btn_y, btn_w, btn_h)
        tray.draw_chevron_button(p, btn_rect, hover_t=hover_t, open_state=open_state)

    p.end()

    saved = img.save(str(output_path), "PNG")
    assert saved, f"Failed to save image to {output_path}"
    print(f"[TEST] Rendered high-DPI chevron button preview to: {output_path}")


def main() -> None:
    print("=== Running test_tray.py ===")
    test_struct_sizes()
    test_input_construction()

    out_png = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5/tray_button.png")
    render_preview_image(out_png)
    print("=== All tests passed successfully ===")


if __name__ == "__main__":
    main()
