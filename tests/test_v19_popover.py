"""test_v19_popover.py - Claude ve Sistem panellerinin ortak panel kiti (v19) doğrulaması.

Kapsam: genişlikler, × kapatma, halka renk eşiği (%89 kimlik / %90 DANGER), eksik veride
'—' + boş halka, switch_from_x ve hide_instant, DPR 2.0 render kanıtları.

Güvenlik: yalnızca statik sahte (stub) veri kullanılır; sources.fetch_claude/fetch_system
çağrılmaz, ağa çıkılmaz, gerçek ses/parlaklık/radyo/clipboard değiştirilmez.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
import sys

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

import panel_style as ps
import sources
from popover_v2 import PopoverV2, build_claude_content, build_sys_content, ring_color

OUT_DIR = APP_DIR / "_ref" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

NOW = dt.datetime.now(sources.LOCAL_TZ)
SESSION_RESET = (NOW + dt.timedelta(hours=4, minutes=34)).isoformat()
_DAYS_TO_SAT = (5 - NOW.weekday()) % 7 or 7
WEEK_RESET = (NOW + dt.timedelta(days=_DAYS_TO_SAT)).replace(
    hour=9, minute=0, second=0, microsecond=0).isoformat()
STAMP = NOW.replace(hour=19, minute=58, second=0, microsecond=0).timestamp()

CLAUDE_NORMAL = {
    "plan": "Max 5x",
    "session": 3.0,
    "session_reset": SESSION_RESET,
    "week": 30.0,
    "week_reset": WEEK_RESET,
    "subscribed_at": "2026-05-21T07:23:39Z",
    "extra_usage": False,
    "fetched_at": STAMP,
}
CLAUDE_MISSING = {
    "plan": "Max 5x",
    "session": None,
    "week": None,
    "session_reset": None,
    "week_reset": None,
    "fetched_at": STAMP,
}
SYS_NORMAL = {
    "cpu": 28.0,
    "ram": 74.0,
    "ram_used_gb": 9.6,
    "ram_total_gb": 15.7,
    "disk_c": 27.0,
    "cpu_name": "Core 5 210H",
    "disk_free_gb": 748.0,
    "top": [
        {"name": "chrome.exe", "mb": 3501.5},
        {"name": "Hermes.exe", "mb": 1509.5},
        {"name": "MemCompression", "mb": 939.5},
    ],
    "fetched_at": STAMP,
}
SYS_HIGH = dict(SYS_NORMAL, cpu=95.0)

ANCHOR = QRect(400, 900, 100, 48)


def _new_popover() -> PopoverV2:
    return PopoverV2()


def test_widths():
    """Claude ve Sistem tam olarak panel_style.WIDTH değerinde olmalı."""
    pop = _new_popover()
    pop.show_for("claude", ANCHOR, CLAUDE_NORMAL)
    app.processEvents()
    assert pop.width() == ps.WIDTH["claude"] == 352

    pop.show_for("sys", ANCHOR, SYS_NORMAL)
    app.processEvents()
    assert pop.width() == ps.WIDTH["sys"] == 352
    pop.hide_instant()
    print("✓ width test passed.")


def test_close_button_closes():
    """Başlıktaki × tıklaması paneli kapatmalı."""
    pop = _new_popover()
    pop.show_for("claude", ANCHOR, CLAUDE_NORMAL)
    app.processEvents()
    pop.render_to_image(dpr=1.0)  # hit-rect'leri çizimden doldur
    assert pop._close_rect.isValid()

    center = pop._close_rect.center()
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(center), QPointF(center),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    pop.mousePressEvent(ev)
    assert pop._is_closing is True
    pop.hide_instant()
    print("✓ × closes test passed.")


def test_ring_colour_rule():
    """Kullanım/kota halkası: %89 kimlik rengi, %90 DANGER."""
    assert ring_color(89.0, ps.CLAUDE) == ps.CLAUDE
    assert ring_color(90.0, ps.CLAUDE) == ps.DANGER
    assert ring_color(89.9, ps.CPU) == ps.CPU
    assert ring_color(90.0, ps.CPU) == ps.DANGER
    assert ring_color(95.0, ps.RAM) == ps.DANGER
    assert ring_color(27.0, ps.DISK) == ps.DISK
    assert ring_color(None, ps.DISK) == ps.DISK

    content = build_claude_content(dict(CLAUDE_NORMAL, session=90.0))
    assert content["session"] == 90.0

    pop = _new_popover()
    captured = []
    original = ps.draw_ring_with_text

    def spy(painter, cx, cy, value, color, **kw):
        captured.append((value, color.name()))
        return original(painter, cx, cy, value, color, **kw)

    ps.draw_ring_with_text = spy
    try:
        pop.show_for("claude", ANCHOR, dict(CLAUDE_NORMAL, session=89.0, week=89.9))
        pop.render_to_image(dpr=1.0)
        assert captured[:2] == [(89.0, ps.CLAUDE.name()), (89.9, ps.CLAUDE.name())]
        captured.clear()
        pop.show_for("claude", ANCHOR, dict(CLAUDE_NORMAL, session=90.0, week=95.0))
        pop.render_to_image(dpr=1.0)
        assert captured[:2] == [(90.0, ps.DANGER.name()), (95.0, ps.DANGER.name())]
    finally:
        ps.draw_ring_with_text = original
    pop.hide_instant()
    print("✓ ring colour rule test passed.")


def test_missing_values_show_dash_and_empty_ring():
    """Eksik değerler '—' yazar; halka yalnızca iz olarak çizilir (uydurma yok)."""
    content = build_claude_content(CLAUDE_MISSING)
    assert content["session"] is None and content["week"] is None
    assert ps.pct(content["session"]) == "—"
    assert content["session_meta"] == "Sıfırlanır: —"
    # Ek kullanım bilinmiyorsa uydurma "Kapalı" değil None ("—") olmalı
    assert content["extra_usage"] is None
    assert build_claude_content(dict(CLAUDE_MISSING, extra_usage=False))["extra_usage"] is False
    assert build_claude_content(dict(CLAUDE_MISSING, extra_usage=True))["extra_usage"] is True

    sys_content = build_sys_content({"cpu": None, "ram": None, "disk_c": None})
    assert sys_content["cpu_meta"] == "—"
    assert sys_content["ram_meta"] == "—"
    assert sys_content["disk_meta"] == "—"

    pop = _new_popover()
    pop.show_for("claude", ANCHOR, CLAUDE_MISSING)
    app.processEvents()

    captured = []
    original = ps.draw_ring

    def spy(painter, cx, cy, diameter, stroke, value, color):
        captured.append(value)
        return original(painter, cx, cy, diameter, stroke, value, color)

    ps.draw_ring = spy
    try:
        img = pop.render_to_image(dpr=1.0)
    finally:
        ps.draw_ring = original

    assert isinstance(img, QImage)
    assert len(captured) == 2
    assert all(v is None for v in captured)
    pop.hide_instant()
    print("✓ missing data / empty ring test passed.")


def test_switch_from_x_and_hide_instant():
    """switch_from_x animasyonu ve hide_instant() çevrimdışı çalışmalı."""
    pop = _new_popover()
    pop.show_for("claude", ANCHOR, CLAUDE_NORMAL, switch_from_x=80)
    app.processEvents()
    assert pop.isVisible() is True
    assert pop.is_open("claude") is True

    pop.hide_instant()
    app.processEvents()
    assert pop.isVisible() is False
    assert pop.recently_closed("claude", threshold_ms=1000.0) is True

    pop.show_for("sys", ANCHOR, SYS_NORMAL)
    app.processEvents()
    assert pop.width() == ps.WIDTH["sys"]
    pop.hide_instant()
    print("✓ switch_from_x / hide_instant test passed.")


def test_footer_texts():
    """Alt bilgi kaynak metni + saat içermeli."""
    c = build_claude_content(CLAUDE_NORMAL)
    s = build_sys_content(SYS_NORMAL)
    assert "Claude Code girişinden okunur" in c["footer_note"]
    assert re.search(r"·\s*\d{2}:\d{2}$", c["footer_note"])
    assert s["footer_note"].startswith("Bu bilgisayar · ")
    assert re.search(r"·\s*\d{2}:\d{2}$", s["footer_note"])
    print("✓ footer texts test passed.")


def render_evidence():
    """DPR 2.0 render kanıtları (yalnız bu worktree içindeki _ref/out)."""
    pop = _new_popover()
    cases = [
        ("claude_normal", "claude", CLAUDE_NORMAL),
        ("claude_yok", "claude", CLAUDE_MISSING),
        ("sistem_normal", "sys", SYS_NORMAL),
        ("sistem_yuksek", "sys", SYS_HIGH),
    ]
    for name, kind, data in cases:
        pop.show_for(kind, ANCHOR, data)
        app.processEvents()
        img = pop.render_to_image(dpr=2.0)
        path = OUT_DIR / f"{name}.png"
        img.save(str(path))
        assert img.width() == pop.width() * 2
        assert img.height() == pop.height() * 2
        print(f"  [RENDER] {path}")
    pop.hide_instant()
    print("✓ evidence renders written.")


if __name__ == "__main__":
    test_widths()
    test_close_button_closes()
    test_ring_colour_rule()
    test_missing_values_show_dash_and_empty_ring()
    test_switch_from_x_and_hide_instant()
    test_footer_texts()
    render_evidence()
    print("test_v19_popover: ALL PASSED")
