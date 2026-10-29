"""test_v24_layout_a.py - v24 adım 1: A yerleşimi, açık kart zemini, yazı ölçeği, kontrast, panel noktaları.

Zero side effects: preview-mode dock + offscreen QImage; örnek veriler; ayar/log/önbellek dosyasına dokunmaz.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import dock_cards  # noqa: E402
import panel_style as ps  # noqa: E402

DPR = 1.25
BG = QColor(13, 15, 19)


def _module():
    spec = importlib.util.spec_from_file_location("serit_v5_layout_a", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_la_")) / "settings.json"
    m.save_settings = lambda cfg: None
    return m


M = _module()


def _dock(n_apps: int = 3, media: bool = True):
    d = M.SeritDock({"style": "band", "cards": {"cal": False, "mail": False, "ag": True, "sys": True}},
                    preview_mode=True)
    d.store.update("claude", {"session": 100.0, "week": 51.0, "session_reset": "", "week_reset": ""})
    d.store.update("ag", {"groups": [{"label": "Claude", "used": 40.0}, {"label": "Gemini 3", "used": 20.0}]})
    d.store.update("sys", {"cpu": 20.0, "ram": 58.0})
    d.store.update("wx", {"temp": 14.0, "icon": "cloud"})
    d.tiles = [{"exe": f"C:/ornek/{i}.exe", "name": f"Örnek {i}", "running": i == 0, "hwnds": [i + 1] if i == 0 else []}
               for i in range(n_apps)]
    d._now_playing_info = ({"title": "Örnek uzun yayın başlığı · bölüm 3", "artist": "Örnek kanal", "app": "Chrome",
                            "playing": False} if media else None)
    d.compute_layout_and_resize()
    d.resize(1536, int(M.DOCK_HEIGHT))
    return d


def _render(d) -> QImage:
    img = QImage(int(d.width() * DPR), int(M.DOCK_HEIGHT * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(0)
    d.render(img, QPoint(0, 0))
    return img


def _boxes(d) -> dict:
    return {k: QRectF(r) for r, k, _e in d.hit_boxes}


def _dividers(img: QImage) -> list:
    y = int(32 * DPR)
    out = []
    for x in range(int(12 * DPR), img.width() - 2):
        c, l2, r2 = QColor(img.pixel(x, y)), QColor(img.pixel(x - 2, y)), QColor(img.pixel(x + 2, y))
        if 25 < c.red() < 70 and abs(l2.red() - 13) < 5 and abs(r2.red() - 13) < 5:
            run = sum(1 for yy in range(int(20 * DPR), int(44 * DPR)) if abs(QColor(img.pixel(x, yy)).red() - c.red()) < 4)
            if run >= int(22 * DPR):
                out.append(x / DPR)
    return out


def test_layout_a_left_cards_apps_centred_media_right() -> None:
    d = _dock()
    img = _render(d)
    b = _boxes(d)
    assert abs(b["claude"].x() - 14.0) < 0.6, b["claude"].x()  # bilgi kartları sol kenarda
    apps = sorted((r for k, r in b.items() if k.startswith("app_")), key=lambda r: r.x())
    centre = (apps[0].x() + apps[-1].right()) / 2.0
    assert abs(centre - d.width() / 2.0) <= 1.0, (centre, d.width())  # uygulamalar tam ortada
    gap = b["tray"].x() - b["media"].right()
    assert 10.0 <= gap <= 22.0, gap  # medya sağ kümenin yanında
    assert b["media"].x() >= apps[-1].right() + 40.0 - 0.5, (b["media"].x(), apps[-1].right())
    assert b["media"].width() > dock_cards.MEDIA_CARD_WIDTH, b["media"].width()  # boş yerle genişledi
    divs = _dividers(img)
    between = [x for x in divs if b["media"].right() - 12.0 < x < b["tray"].x()]
    assert len(between) == 1, (divs, b["media"].right(), b["tray"].x())  # medya | sağ küme ayracı tek ve aradaki boşlukta
    assert not [x for x in divs if b["sys"].right() < x < apps[0].x()], divs  # sol kanat | uygulamalar ayracı yok
    c = QColor(img.pixel(int((b["claude"].x() + 4) * DPR), int((b["claude"].y() + 4) * DPR)))
    assert (c.red(), c.green(), c.blue()) == (13, 15, 19), c.name()  # panel kapalı: kart kutusuz


def test_layout_a_survives_many_apps() -> None:
    d = _dock(n_apps=8)
    _render(d)  # kutular çizimde dolar
    b = _boxes(d)
    apps = sorted((r for k, r in b.items() if k.startswith("app_")), key=lambda r: r.x())
    assert b["sys"].right() < apps[0].x(), "sol kanat uygulamalara binmemeli"
    assert apps[-1].right() < b["media"].x(), "medya uygulamalara binmemeli"
    assert b["media"].right() < b["tray"].x(), "medya sağ kümeye binmemeli"


def test_open_panel_card_gets_soft_fill() -> None:
    d = _dock()
    d._left_open_sig = lambda: (True, False, False, False)  # Claude paneli açık (örnek)
    img = _render(d)
    r = _boxes(d)["claude"]
    c = QColor(img.pixel(int((r.x() + 4) * DPR), int((r.y() + 26) * DPR)))
    assert c.red() > 20 and abs(c.red() - c.blue()) < 12, c.name()  # nötr hafif zemin
    r_ag = _boxes(d)["ag"]
    c2 = QColor(img.pixel(int((r_ag.x() + 4) * DPR), int((r_ag.y() + 26) * DPR)))
    assert (c2.red(), c2.green(), c2.blue()) == (13, 15, 19), c2.name()  # yalnız açık kart


def test_card_width_fits_full_quota_with_reset_time() -> None:
    assert dock_cards.CLAUDE_CARD_WIDTH == M.CLAUDE_CARD_WIDTH == 204.0
    assert dock_cards.AG_CARD_WIDTH == M.AG_CARD_WIDTH == 204.0
    text_w = dock_cards.CLAUDE_CARD_WIDTH - 59.0 - 10.0
    img = QImage(400, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    p = QPainter(img)
    import theme
    for lbl in ("Oturum", "Hafta", "Claude", "Gemini"):
        for rst in ("23 sa 59 dk", "19 sa 27 dk", "Cmt 09:00"):
            need = 0.0
            for size, weight, txt, tab in ((12.0, theme.QFont.Weight.DemiBold, "%100", True),
                                           (11.0, theme.QFont.Weight.Normal, lbl, False),
                                           (10.0, theme.QFont.Weight.Normal, rst, False)):
                p.setFont(theme.make_font(size, weight, tabular=tab))
                need += p.fontMetrics().horizontalAdvance(txt)
            assert need + 9.0 <= text_w, (lbl, rst, need + 9.0, text_w)
    p.end()


def test_type_scale_and_contrast() -> None:
    import inspect
    src = inspect.getsource(dock_cards)
    for bad in ("make_font(9.5", "make_font(10.5", "make_font(12.5", "make_font(14.5"):
        assert bad not in src, bad
    assert dock_cards.COLOR_TXT_FAINT.alpha() == 133  # .52
    assert ps.TEXT_META.alpha() == 122 and ps.TEXT_LABEL.alpha() == 122  # .48


def test_panel_dots_only_on_problem_and_sys_icon_blue() -> None:
    import popover_v2
    import inspect
    assert '"#64D2FF"' not in inspect.getsource(popover_v2.draw_sys_icon)
    seen = []
    orig = ps.draw_header

    def spy(p, rect, title, *a, **k):
        seen.append((title, k.get("chip_dot")))
        return orig(p, rect, title, *a, **k)

    ps.draw_header = spy
    try:
        import info_panels
        qp = info_panels.QuotaPanel()
        qp.set_data({"groups": [{"label": "Claude", "used": 40.0}]})
        qp.render_to_image(1.0)
        qp.set_data({"err": "örnek hata", "groups": []})
        qp.render_to_image(1.0)
    finally:
        ps.draw_header = orig
    ok_dot = [d for t, d in seen if t == "Antigravity"]
    assert ok_dot[0] is None, "sorun yokken nokta çizilmez"
    assert ok_dot[-1] is not None and QColor(ok_dot[-1]).rgba() == ps.DANGER.rgba(), "hatada kırmızı nokta"


def run_all() -> None:
    for fn in (test_layout_a_left_cards_apps_centred_media_right, test_layout_a_survives_many_apps,
               test_open_panel_card_gets_soft_fill, test_card_width_fits_full_quota_with_reset_time,
               test_type_scale_and_contrast, test_panel_dots_only_on_problem_and_sys_icon_blue):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_LAYOUT_A TESTS PASSED")


if __name__ == "__main__":
    run_all()
