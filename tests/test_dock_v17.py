"""v17: Claude + Antigravity kartları D4 (iç içe iki halka) — 27 Eki 2026."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter

app = QGuiApplication.instance() or QGuiApplication([])

import dock_cards  # noqa: E402


def _render(fn, data, w=192.0):
    img = QImage(int(w) + 20, 64, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    fn(p, QRectF(10, 6, w, 52), data)
    p.end()
    return img


def test_cards_same_width_pair() -> None:
    assert dock_cards.CLAUDE_CARD_WIDTH == dock_cards.AG_CARD_WIDTH
    assert dock_cards.CONC_CARD_MIN_WIDTH < dock_cards.CLAUDE_CARD_WIDTH
    print("[PASS] Claude ve Antigravity kartları aynı genişlikte")


def test_states_render_without_error() -> None:
    claude_ok = {"session": 63, "week": 29, "session_reset": "2026-10-27T18:59:00+00:00",
                 "week_reset": "2026-10-31T06:00:00+00:00"}
    claude_high = {"session": 92, "week": 41, "session_reset": "2026-10-27T18:59:00+00:00",
                   "week_reset": "2026-10-31T06:00:00+00:00"}
    claude_missing = {"session": None, "week": None, "session_reset": ""}
    ag_ok = {"groups": [{"label": "Claude", "used": 100.0, "reset_at": "2026-10-29T16:40:00+03:00"},
                        {"label": "Gemini Pro", "used": 65.8, "reset_at": "2026-10-27T19:54:00+03:00"}]}
    for fn, data in ((dock_cards.draw_claude_card, claude_ok), (dock_cards.draw_claude_card, claude_high),
                     (dock_cards.draw_claude_card, claude_missing), (dock_cards.draw_claude_card, {"err": "x"}),
                     (dock_cards.draw_ag_card, ag_ok), (dock_cards.draw_ag_card, {"err": "x"}),
                     (dock_cards.draw_ag_card, {"groups": []})):
        for w in (dock_cards.CLAUDE_CARD_WIDTH, dock_cards.CONC_CARD_MIN_WIDTH):
            _render(fn, data, w)
    print("[PASS] normal, yüksek, eksik veri ve hata durumları iki genişlikte çiziliyor")


if __name__ == "__main__":
    test_cards_same_width_pair()
    test_states_render_without_error()


def test_reset_rounds_to_minute() -> None:
    import datetime as dt
    now = dt.datetime(2026, 10, 27, 16, 50, tzinfo=dt.timezone.utc)
    assert dock_cards.format_reset_display("2026-10-31T05:59:59.791398+00:00", now) == "Cmt 09:00"
    assert dock_cards.format_reset_display("2026-10-27T21:29:59+00:00", now) == "4 sa 39 dk"
    assert dock_cards.format_reset_display("2026-10-29T16:40:41+03:00", now) == "Per 16:40"
    assert dock_cards.format_reset_display("", now) == "—"
    print("[PASS] sıfırlanma zamanı dakikaya yuvarlanıyor")


if __name__ == "__main__":
    test_reset_rounds_to_minute()
