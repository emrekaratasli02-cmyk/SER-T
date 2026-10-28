"""test_v22_window_picker.py - pencere seçici paneli. Gerçek pencere API'si ASLA çağrılmaz."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication

import window_picker as wp  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv)


def W(hwnd: int, title: str, minimized: bool = False, active: bool = False) -> dict:
    return {"hwnd": hwnd, "title": title, "minimized": minimized, "active": active}


TWO = [
    W(40101, "Gelen kutusu - Örnek"),
    W(40102, "Proje dokümanı"),
]
THREE = [
    W(40201, "YouTube"),
    W(40202, "Proje dokümanı", active=True),
    W(40203, "Gelen kutusu - Örnek", minimized=True),
]
TWELVE = [W(40300 + i, f"Pencere {i + 1} - Sekme başlığı", active=(i == 2)) for i in range(12)]
LONG = [
    W(40401, "Çok uzun bir pencere başlığı: 2026 bütçe planlaması ve tedarikçi sözleşmeleri - Son sürüm"),
    W(40402, "Gelen kutusu - Örnek - Haftalık özet ve ekli dosyalar", minimized=True),
    W(40403, "YouTube"),
]
GARBAGE = [
    W(40501, ""),
    W(40502, "Gelen kutusu - Örnek"),
    "çöp",
    {},
    {"hwnd": 0, "title": "Sıfır"},
    {"hwnd": None, "title": "Yok"},
    {"hwnd": -7, "title": "Eksi"},
    {"hwnd": True, "title": "Bool"},
    {"hwnd": 40503, "title": None},
]


def _anchor(frac_x: float = 0.5) -> QRectF:
    g = QGuiApplication.primaryScreen().availableGeometry()
    return QRectF(g.left() + g.width() * frac_x - 48.0, g.top() + g.height() * 0.6, 96.0, 40.0)


def _stub_icon() -> QPixmap:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#D97757"))
        p.drawRoundedRect(QRectF(2.0, 2.0, 28.0, 28.0), 7.0, 7.0)
        p.setBrush(QColor("#141518"))
        p.drawRoundedRect(QRectF(8.0, 11.0, 16.0, 11.0), 3.0, 3.0)
    finally:
        p.end()
    return pm


def _pick(windows: list, app_name: str = "Chrome", icon=None, anchor: QRectF | None = None) -> wp.WindowPicker:
    pnl = wp.WindowPicker()
    raw = [dict(w) if isinstance(w, dict) else w for w in windows]
    pnl.show_for(anchor if anchor is not None else _anchor(), app_name, icon, raw)
    return pnl


def _press(pt: QPointF, button=Qt.MouseButton.LeftButton) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress, pt, pt, button, button, Qt.KeyboardModifier.NoModifier
    )


def _move(pt: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseMove, pt, pt, Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )


def _key(key: Qt.Key) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def _wheel(delta: int, pt: QPointF = QPointF(10, 10)) -> QWheelEvent:
    return QWheelEvent(
        pt, pt, QPoint(0, 0), QPoint(0, delta),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_width_header_rows():
    pnl = _pick(THREE)
    assert wp.WindowPicker.WIDTH == wp.WIDTH == 320 == pnl.width()
    assert pnl.height() == pnl.compute_height()
    pnl.render_to_image(2.0)
    assert len(pnl._row_hit_rects) == 3
    assert [h for h, _r, _c in pnl._row_hit_rects] == [40201, 40202, 40203]
    assert pnl._focus == 1
    rows = [r for _h, r, _c in pnl._row_hit_rects]
    assert all(abs(r.height() - wp.ROW_H) < 0.01 for r in rows)
    assert all(abs(rows[i + 1].top() - rows[i].bottom()) < 0.01 for i in range(len(rows) - 1))
    assert "close" in pnl._rects
    pnl.show_for(_anchor(0.3), "Chrome", None, TWO, switch_from_x=int(pnl.x()))
    assert pnl.is_open() and len(pnl._windows) == 2
    pnl.hide_instant()


def test_click_row_emits_chosen():
    for i in range(3):
        pnl = _pick(THREE)
        got: list[int] = []
        pnl.window_chosen.connect(got.append)
        pnl.render_to_image(2.0)
        pnl.mousePressEvent(_press(pnl._row_hit_rects[i][1].center()))
        assert got == [THREE[i]["hwnd"]], (i, got)
        assert not pnl.is_open()
        pnl.hide_instant()


def test_row_x_and_middle_emit_close():
    pnl = _pick(THREE)
    got: list[int] = []
    chosen: list[int] = []
    pnl.close_requested.connect(got.append)
    pnl.window_chosen.connect(chosen.append)
    pnl.render_to_image(2.0)
    row = pnl._row_hit_rects[0][1]
    pnl.mouseMoveEvent(_move(row.center()))
    pnl.render_to_image(2.0)
    close_rect = pnl._row_hit_rects[0][2]
    assert close_rect is not None
    pnl.mousePressEvent(_press(close_rect.center()))
    assert got == [40201] and chosen == []
    assert pnl.is_open()

    pnl.mousePressEvent(_press(pnl._row_hit_rects[2][1].center(), Qt.MouseButton.MiddleButton))
    assert got == [40201, 40203]
    assert pnl.is_open()
    pnl.hide_instant()


def test_keyboard_down_enter():
    pnl = _pick(THREE)
    got: list[int] = []
    pnl.window_chosen.connect(got.append)
    assert pnl._focus == 1
    pnl.keyPressEvent(_key(Qt.Key.Key_Down))
    assert pnl._focus == 2
    pnl.keyPressEvent(_key(Qt.Key.Key_Return))
    assert got == [40203]
    assert not pnl.is_open()
    pnl.hide_instant()


def test_keyboard_delete_emits_close():
    pnl = _pick(THREE)
    got: list[int] = []
    pnl.close_requested.connect(got.append)
    pnl.keyPressEvent(_key(Qt.Key.Key_Up))
    assert pnl._focus == 0
    pnl.keyPressEvent(_key(Qt.Key.Key_Delete))
    assert got == [40201]
    assert pnl.is_open()
    pnl.hide_instant()


def test_escape_and_header_close():
    pnl = _pick(TWO)
    pnl.render_to_image(2.0)
    pnl.keyPressEvent(_key(Qt.Key.Key_Escape))
    assert not pnl.is_open()
    pnl.hide_instant()

    pnl = _pick(TWO)
    pnl.render_to_image(2.0)
    pnl.mousePressEvent(_press(pnl._rects["close"].center()))
    assert not pnl.is_open()
    pnl.hide_instant()


def test_set_windows_empty_closes_and_update_keeps_focus():
    pnl = _pick(THREE)
    assert pnl.is_open()
    pnl.render_to_image(2.0)
    pnl.set_windows([THREE[0], W(40202, "Proje dokümanı", active=True)])
    assert len(pnl._windows) == 2 and pnl.is_open()
    assert pnl._focus == 1
    pnl.set_windows([])
    assert not pnl.is_open()
    assert pnl._windows == []
    pnl.hide_instant()


def test_anchoring_left_center_right():
    g = QGuiApplication.primaryScreen().availableGeometry()
    y = g.top() + int(g.height() * 0.55)
    anchors = {
        "sol": QRectF(g.left() + 4.0, y, 96.0, 40.0),
        "orta": QRectF(g.center().x() - 48.0, y, 96.0, 40.0),
        "sağ": QRectF(g.right() - 100.0, y, 96.0, 40.0),
    }
    for name, anchor in anchors.items():
        pnl = _pick(THREE, anchor=anchor)
        r = QRectF(pnl.x(), pnl.y(), pnl.width(), pnl.height())
        assert r.bottom() < anchor.top(), (name, r, anchor)
        assert g.contains(r.toRect()), (name, r, g)
        if name == "orta":
            assert abs(r.center().x() - anchor.center().x()) <= 1.0, (name, r, anchor)
        pnl.hide_instant()


def test_wheel_scrolls_and_clamps():
    pnl = _pick(TWELVE)
    pnl.render_to_image(2.0)
    assert pnl._max_scroll() == (12 - wp.MAX_VISIBLE) * wp.ROW_H
    pnl.wheelEvent(_wheel(-120))
    assert abs(pnl._scroll_y - wp.ROW_H) < 0.01
    for _ in range(20):
        pnl.wheelEvent(_wheel(-120))
    assert abs(pnl._scroll_y - pnl._max_scroll()) < 0.01
    pnl.wheelEvent(_wheel(120))
    assert abs(pnl._scroll_y - (pnl._max_scroll() - wp.ROW_H)) < 0.01
    pnl.keyPressEvent(_key(Qt.Key.Key_Up))
    pnl.keyPressEvent(_key(Qt.Key.Key_Up))
    assert pnl._scroll_y <= pnl._focus * wp.ROW_H + 0.01
    pnl.hide_instant()


def test_garbage_skipped_and_empty_title():
    pnl = _pick(GARBAGE)
    assert [w["hwnd"] for w in pnl._windows] == [40501, 40502, 40503]
    assert pnl._windows[0]["title"] == "(adsız pencere)"
    assert pnl._windows[2]["title"] == "(adsız pencere)"
    pnl.render_to_image(2.0)
    assert len(pnl._row_hit_rects) == 3
    pnl.hide_instant()


def test_recently_closed():
    pnl = wp.WindowPicker()
    assert not pnl.recently_closed()
    pnl.show_for(_anchor(), "Chrome", None, TWO)
    assert pnl.is_open()
    pnl.hide_instant()
    assert not pnl.is_open()
    assert pnl.recently_closed()
    assert pnl.recently_closed(10000.0)


def _render(name: str, windows: list, app_name: str = "Chrome", hover_index: int | None = None,
            hover_close: bool = False, scroll_frac: float = 0.0, icon=None) -> QImage:
    pnl = _pick(windows, app_name=app_name, icon=icon)
    if hover_index is not None and 0 <= hover_index < len(pnl._windows):
        hwnd = pnl._windows[hover_index]["hwnd"]
        pnl._hover_hwnd = hwnd
        pnl._hover_close_hwnd = hwnd if hover_close else None
    if scroll_frac:
        pnl._scroll_y = pnl._max_scroll() * scroll_frac
    img = pnl.render_to_image(2.0)
    assert img.save(str(OUT / f"v22_picker_{name}.png"))
    pnl.hide_instant()
    return img


def test_render_sheet():
    images = [
        ("iki_pencere", _render("iki_pencere", TWO, icon=_stub_icon())),
        ("uc_pencere_hover", _render("uc_pencere_hover", THREE, hover_index=1, hover_close=True)),
        ("on_iki_kaydirma", _render("on_iki_kaydirma", TWELVE, scroll_frac=0.5)),
        ("uzun_basliklar", _render("uzun_basliklar", LONG, hover_index=1)),
        ("bos_ve_cop", _render("bos_ve_cop", GARBAGE)),
    ]
    gap = 20
    cols = 3
    rows = max(1, math.ceil(len(images) / cols))
    cell_w = max(img.width() for _n, img in images) // 2
    cell_h = max(img.height() for _n, img in images) // 2
    sheet = QImage(
        cols * cell_w + (cols + 1) * gap,
        rows * cell_h + (rows + 1) * gap,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    sheet.fill(QColor("#0C0D0F"))
    p = QPainter(sheet)
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for idx, (_name, img) in enumerate(images):
            col = idx % cols
            row = idx // cols
            x = gap + col * (cell_w + gap)
            y = gap + row * (cell_h + gap)
            p.drawImage(QRectF(x, y, cell_w, cell_h), img)
    finally:
        p.end()
    out = OUT / "v22_picker_sheet.png"
    assert sheet.save(str(out)), out
    assert out.exists() and out.stat().st_size > 5000
    print(f"  [RENDER] {out}")


def run_all() -> None:
    tests = [
        test_width_header_rows,
        test_click_row_emits_chosen,
        test_row_x_and_middle_emit_close,
        test_keyboard_down_enter,
        test_keyboard_delete_emits_close,
        test_escape_and_header_close,
        test_set_windows_empty_closes_and_update_keeps_focus,
        test_anchoring_left_center_right,
        test_wheel_scrolls_and_clamps,
        test_garbage_skipped_and_empty_title,
        test_recently_closed,
        test_render_sheet,
    ]
    for fn in tests:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V22_WINDOW_PICKER TESTS PASSED")


if __name__ == "__main__":
    run_all()
