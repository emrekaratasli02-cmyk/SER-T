"""AI kartlarının yüzünde metinsiz (yalnızca halka + logo) çizim testleri.

Spec (r6-a13):
- draw_claude_card, draw_ag_card, draw_opencode_card kart yüzünde metin çizmez (show_text=False varsayılan).
- Kart yüzünde yalnızca konsantrik halka dekoru + merkez logo/glif yer alır.
- Halka doluluğu ve renk eşikleri (75/90/95) korunur.
- show_text=True ile detaylar (yüzde, oturum, hafta, model adı) çizilebilir.
- draw_concentric_text_rows fonksiyonu korunur ve enabled parametresini destekler.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

import dock_cards


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _count_ink_in_rect(img: QImage, rect: QRectF, alpha_threshold: int = 20) -> int:
    x0 = max(0, int(rect.left()))
    x1 = min(img.width(), int(rect.right()))
    y0 = max(0, int(rect.top()))
    y1 = min(img.height(), int(rect.bottom()))
    count = 0
    for x in range(x0, x1):
        for y in range(y0, y1):
            if img.pixelColor(x, y).alpha() > alpha_threshold:
                count += 1
    return count


def test_claude_card_face_textless_by_default() -> None:
    get_qapp()
    card_rect = QRectF(0.0, 0.0, 184.0, 52.0)
    text_rect = QRectF(57.0, 0.0, 127.0, 52.0)
    slot_rect = QRectF(10.0, 6.0, 40.0, 40.0)

    claude_data = {
        "session": 65.0,
        "week": 35.0,
        "session_reset": "2026-11-05T18:00:00+03:00",
        "week_reset": "2026-11-08T06:00:00+03:00",
    }

    # 1. Default render: show_text=False
    img_default = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_default.fill(0)
    p = QPainter(img_default)
    dock_cards.draw_claude_card(p, card_rect, claude_data)
    p.end()

    # Slot must have ink (rings and logo)
    slot_ink = _count_ink_in_rect(img_default, slot_rect)
    assert slot_ink > 50, f"Claude slot has no ink: {slot_ink}"

    # Text area must have 0 ink by default
    text_ink_default = _count_ink_in_rect(img_default, text_rect)
    assert text_ink_default == 0, f"Expected 0 text ink by default, got: {text_ink_default}"

    # 2. Explicit render with show_text=True
    img_with_text = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_with_text.fill(0)
    p2 = QPainter(img_with_text)
    dock_cards.draw_claude_card(p2, card_rect, claude_data, show_text=True)
    p2.end()

    text_ink_explicit = _count_ink_in_rect(img_with_text, text_rect)
    assert text_ink_explicit > 100, f"Expected text ink with show_text=True, got: {text_ink_explicit}"
    print("[PASS] test_claude_card_face_textless_by_default")


def test_ag_card_face_textless_by_default() -> None:
    get_qapp()
    card_rect = QRectF(0.0, 0.0, 184.0, 52.0)
    text_rect = QRectF(58.0, 0.0, 126.0, 52.0)
    slot_rect = QRectF(10.0, 6.0, 40.0, 40.0)

    ag_data = {
        "groups": [
            {"label": "Claude · Emre", "used": 80.0, "reset_at": "2026-11-06T12:00:00+03:00"},
            {"label": "Gemini 2.5 · Emre", "used": 45.0, "reset_at": "2026-11-06T15:00:00+03:00"},
        ]
    }

    # 1. Default render: show_text=False
    img_default = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_default.fill(0)
    p = QPainter(img_default)
    dock_cards.draw_ag_card(p, card_rect, ag_data)
    p.end()

    slot_ink = _count_ink_in_rect(img_default, slot_rect)
    assert slot_ink > 50, f"AG slot has no ink: {slot_ink}"

    text_ink_default = _count_ink_in_rect(img_default, text_rect)
    assert text_ink_default == 0, f"Expected 0 text ink by default in AG card, got: {text_ink_default}"

    # 2. Explicit render with show_text=True
    img_with_text = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_with_text.fill(0)
    p2 = QPainter(img_with_text)
    dock_cards.draw_ag_card(p2, card_rect, ag_data, show_text=True)
    p2.end()

    text_ink_explicit = _count_ink_in_rect(img_with_text, text_rect)
    assert text_ink_explicit > 100, f"Expected text ink with show_text=True in AG, got: {text_ink_explicit}"
    print("[PASS] test_ag_card_face_textless_by_default")


def test_opencode_card_face_textless_by_default() -> None:
    get_qapp()
    card_rect = QRectF(0.0, 0.0, 184.0, 52.0)
    text_rect = QRectF(57.0, 0.0, 127.0, 52.0)
    slot_rect = QRectF(10.0, 6.0, 40.0, 40.0)

    oc_data = {
        "available": True,
        "today_input": 120_000,
        "today_output": 80_000,
        "today_cost": 0.0,
        "today_sessions": 4,
        "today_by_model": {"deepseek/coder": 200_000},
    }

    # 1. Default render: show_text=False
    img_default = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_default.fill(0)
    p = QPainter(img_default)
    dock_cards.draw_opencode_card(p, card_rect, oc_data)
    p.end()

    slot_ink = _count_ink_in_rect(img_default, slot_rect)
    assert slot_ink > 30, f"OpenCode slot has no ink: {slot_ink}"

    text_ink_default = _count_ink_in_rect(img_default, text_rect)
    assert text_ink_default == 0, f"Expected 0 text ink by default in OpenCode card, got: {text_ink_default}"

    # 2. Explicit render with show_text=True
    img_with_text = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img_with_text.fill(0)
    p2 = QPainter(img_with_text)
    dock_cards.draw_opencode_card(p2, card_rect, oc_data, show_text=True)
    p2.end()

    text_ink_explicit = _count_ink_in_rect(img_with_text, text_rect)
    assert text_ink_explicit > 100, f"Expected text ink with show_text=True in OpenCode, got: {text_ink_explicit}"
    print("[PASS] test_opencode_card_face_textless_by_default")


def test_concentric_text_rows_enabled_flag() -> None:
    get_qapp()
    img = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    rect = QRectF(10.0, 14.0, 135.0, 36.0)

    # When enabled=False, nothing should be drawn
    dock_cards.draw_concentric_text_rows(
        p, rect,
        (100.0, dock_cards.COLOR_CLAUDE_CORAL, "Claude", "19 sa 27 dk"),
        (86.0, dock_cards.COLOR_GEMINI_BLUE, "Gemini", "21 sa 28 dk"),
        enabled=False,
    )
    p.end()
    assert _count_ink_in_rect(img, QRectF(0, 0, 200, 64)) == 0

    # When enabled=True (default), text is drawn
    img2 = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img2.fill(0)
    p2 = QPainter(img2)
    dock_cards.draw_concentric_text_rows(
        p2, rect,
        (100.0, dock_cards.COLOR_CLAUDE_CORAL, "Claude", "19 sa 27 dk"),
        (86.0, dock_cards.COLOR_GEMINI_BLUE, "Gemini", "21 sa 28 dk"),
    )
    p2.end()
    assert _count_ink_in_rect(img2, QRectF(0, 0, 200, 64)) > 100
    print("[PASS] test_concentric_text_rows_enabled_flag")


def test_card_threshold_colors_preserved() -> None:
    blue = QColor(100, 210, 255)
    # Below 75% -> base color
    assert dock_cards.usage_color(50.0, blue) == blue
    assert dock_cards.usage_color(74.9, blue) == blue
    # >= 75% -> COLOR_RING_WARN
    assert dock_cards.usage_color(75.0, blue) == dock_cards.COLOR_RING_WARN
    assert dock_cards.usage_color(89.9, blue) == dock_cards.COLOR_RING_WARN
    # >= 90% (or 95% critical) -> COLOR_RING_CRITICAL
    assert dock_cards.usage_color(95.0, blue) == dock_cards.COLOR_RING_CRITICAL
    print("[PASS] test_card_threshold_colors_preserved")


if __name__ == "__main__":
    test_claude_card_face_textless_by_default()
    test_ag_card_face_textless_by_default()
    test_opencode_card_face_textless_by_default()
    test_concentric_text_rows_enabled_flag()
    test_card_threshold_colors_preserved()
    print("ALL AI CARD TEXTLESS TESTS PASSED!")
