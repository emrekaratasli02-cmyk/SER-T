"""v21: Ayarlar penceresi panel_style ortak dili + Performans (donma istatistikleri) sayfası.

Gerçek ses/parlaklık/ağ ayarı çağrılmaz; sağlayıcı verisi stub'dır. Görseller _ref/out altına yazılır.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

import panel_style as ps
import settings_window as sw

APP = QApplication.instance() or QApplication(sys.argv)
OUT = Path(__file__).resolve().parent.parent / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = ["appearance", "cards", "pinned", "alerts", "performance", "about"]
RENDERS: list[Path] = []


def sample_settings() -> dict:
    return {
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


STUB_STATS = {
    "count": 3,
    "worst_ms": 1250,
    "last": [
        {"ms": 1250, "time": 1700000000.0, "top": "popover_v2.py:233 _paint"},
        {"ms": 412, "time": 1700000100.0, "top": "dock_cards.py:810 paint"},
        {"ms": 90, "time": 1700000200.0, "top": "settings_window.py:900 _paint_all"},
    ],
}


def stub_provider() -> dict:
    return {
        "count": STUB_STATS["count"],
        "worst_ms": STUB_STATS["worst_ms"],
        "last": [dict(item) for item in STUB_STATS["last"]],
    }


def _save(img: QImage, name: str) -> Path:
    path = OUT / name
    assert img.save(str(path)), f"kaydedilemedi: {path}"
    assert path.exists() and path.stat().st_size > 1000, path
    RENDERS.append(path)
    return path


def _click(win: sw.SettingsWindow, pt: QPointF) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pt,
        pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(ev)


def test_render_all_sections() -> None:
    win = sw.SettingsWindow(sample_settings(), lambda s: None, stats_provider=stub_provider)
    assert win.width() == 560 and win.height() == 520
    ids = [sid for sid, _title in sw.SECTIONS]
    assert ids.index("performance") == ids.index("alerts") + 1
    assert ids.index("about") == ids.index("performance") + 1
    for sec in SECTIONS:
        win.switch_section(sec)
        img = win.render_to_image(dpr=2.0)
        assert not img.isNull()
        assert img.width() == 1120 and img.height() == 1040
        _save(img, f"v21_settings_{sec}.png")
    win.close()


def test_performance_stub_numbers() -> None:
    win = sw.SettingsWindow(sample_settings(), lambda s: None, stats_provider=stub_provider)
    win.switch_section("performance")
    texts = win.performance_strings()
    assert texts["count"] == "3", texts
    assert texts["worst"] == "1.250 ms", texts
    assert texts["status"] == "", texts

    rows = win.performance_rows()
    assert len(rows) == 3
    assert [r["ms"] for r in rows] == [90, 412, 1250]
    assert rows[0]["top"] == "settings_window.py:900 _paint_all"
    assert rows[-1]["top"] == "popover_v2.py:233 _paint"
    assert rows[0]["color"] == ps.TEXT_BODY
    assert rows[1]["color"] == ps.WARN
    assert rows[2]["color"] == ps.DANGER
    assert len(rows[0]["time"].split(":")) == 3
    _save(win.render_to_image(2.0), "v21_settings_performance.png")
    win.close()


def test_performance_unavailable() -> None:
    for provider in (None, lambda: (_ for _ in ()).throw(RuntimeError("stub")), lambda: {"count": "üç"}):
        win = sw.SettingsWindow(sample_settings(), lambda s: None, stats_provider=provider)
        win.switch_section("performance")
        texts = win.performance_strings()
        assert texts == {"count": "—", "worst": "—", "status": sw.STALL_UNAVAILABLE}, texts
        assert win.performance_rows() == []
        img = win.render_to_image(2.0)
        assert not img.isNull()
        if provider is None:
            _save(img, "v21_settings_performance_none.png")
        win.close()


def test_performance_zero() -> None:
    win = sw.SettingsWindow(
        sample_settings(), lambda s: None,
        stats_provider=lambda: {"count": 0, "worst_ms": 0, "last": []},
    )
    win.switch_section("performance")
    texts = win.performance_strings()
    assert texts == {"count": "0", "worst": "—", "status": sw.STALL_NONE}, texts
    assert win.performance_rows() == []
    _save(win.render_to_image(2.0), "v21_settings_performance_zero.png")
    win.close()


def test_stats_timer_follows_page_and_visibility() -> None:
    calls = []

    def provider() -> dict:
        calls.append(1)
        return stub_provider()

    win = sw.SettingsWindow(sample_settings(), lambda s: None, stats_provider=provider)
    assert not win._stats_timer.isActive()
    assert win._stats_timer.interval() == 1000

    win.switch_section("performance")
    assert not win._stats_timer.isActive(), "pencere görünmezken zamanlayıcı çalışmamalı"
    assert calls, "sayfaya gelince bir kez okunmalı"

    win.show()
    APP.processEvents()
    assert win._stats_timer.isActive(), "performans sayfası görünürken çalışmalı"

    win.switch_section("cards")
    assert not win._stats_timer.isActive(), "sayfadan çıkınca durmalı"

    win.switch_section("performance")
    assert win._stats_timer.isActive()

    win.close()
    APP.processEvents()
    assert not win._stats_timer.isActive(), "kapanınca durmalı"


def test_panel_tokens_in_pixels() -> None:
    win = sw.SettingsWindow(sample_settings(), lambda s: None)
    win.switch_section("cards")
    img = win.render_to_image(2.0)

    bg = img.pixelColor(int(548 * 2), int(300 * 2))
    assert abs(bg.red() - ps.PANEL_BG.red()) <= 4
    assert abs(bg.green() - ps.PANEL_BG.green()) <= 4
    assert abs(bg.blue() - ps.PANEL_BG.blue()) <= 4
    assert bg.alpha() == 255

    toggle = win._toggle_rects["toggle_card:claude"]
    on_px = img.pixelColor(int((toggle.left() + 6.0) * 2), int(toggle.center().y() * 2))
    assert abs(on_px.red() - ps.ACCENT.red()) <= 6
    assert abs(on_px.green() - ps.ACCENT.green()) <= 6
    assert abs(on_px.blue() - ps.ACCENT.blue()) <= 6

    for y in range(0, img.height(), 17):
        for x in range(0, img.width(), 19):
            c = img.pixelColor(x, y)
            assert c.name() != "#0078d4", (x, y)
    win.close()


def test_missing_card_key_is_on() -> None:
    settings = sample_settings()
    settings["cards"] = {"claude": False}
    win = sw.SettingsWindow(settings, lambda s: None)
    win.switch_section("cards")
    win.render_to_image(2.0)

    assert win._card_checked("media") is True
    assert win._toggle_checked["toggle_card:media"] is True
    assert win._toggle_checked["toggle_card:claude"] is False

    target = None
    for rect, kind, extra in win._content_hit_boxes:
        if kind == "toggle_card" and extra == "media":
            target = rect
            break
    assert target is not None
    _click(win, target.center())
    assert win.working_settings["cards"]["media"] is False
    win.close()


def test_stitch_sheet() -> None:
    paths = [p for p in RENDERS if p.exists()]
    assert paths, "önce render üretilmeli"
    imgs = [QImage(str(p)) for p in paths]
    gap = 20
    cols = 3
    rows = max(1, math.ceil(len(imgs) / cols))
    cell_w = max(i.width() for i in imgs) // 2
    cell_h = max(i.height() for i in imgs) // 2
    sheet = QImage(
        cols * cell_w + (cols + 1) * gap,
        rows * cell_h + (rows + 1) * gap,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    sheet.fill(QColor("#0C0D0F"))
    p = QPainter(sheet)
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for idx, img in enumerate(imgs):
            col = idx % cols
            row = idx // cols
            x = gap + col * (cell_w + gap)
            y = gap + row * (cell_h + gap)
            p.drawImage(QRectF(x, y, cell_w, cell_h), img)
    finally:
        p.end()
    out = OUT / "v21_settings_sheet.png"
    assert sheet.save(str(out)), out
    assert out.exists() and out.stat().st_size > 5000


def main() -> int:
    test_render_all_sections()
    test_performance_stub_numbers()
    test_performance_unavailable()
    test_performance_zero()
    test_stats_timer_follows_page_and_visibility()
    test_panel_tokens_in_pixels()
    test_missing_card_key_is_on()
    test_stitch_sheet()
    print("ALL test_v21_settings checks passed.")
    print("sheet:", OUT / "v21_settings_sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
