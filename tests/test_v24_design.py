"""test_v24_design.py - B tasarımı (kutusuz kartlar + ince ayraç, iki renk, kota satırları, hizalama) (v24).

Zero side effects: offscreen QImage renders with sample data; preview-mode dock; no real window,
volume, brightness or settings file is touched.
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

BG = QColor(13, 15, 19)
DPR = 1.25


def _canvas(w: float = 220.0, h: float = 64.0) -> QImage:
    img = QImage(int(w * DPR), int(h * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(BG)
    return img


def _ink_cols(img: QImage, y0: int = 0, y1: int = -1, thr: int = 12) -> list:
    y1 = img.height() if y1 < 0 else y1
    cols = []
    for x in range(img.width()):
        for y in range(y0, y1):
            c = QColor(img.pixel(x, y))
            if max(abs(c.red() - 13), abs(c.green() - 15), abs(c.blue() - 19)) > thr:
                cols.append(x)
                break
    return cols


def test_card_base_is_boxless_until_hover() -> None:
    img = _canvas()
    p = QPainter(img)
    dock_cards.draw_card_base(p, QRectF(10, 6, 180, 52), hover=False)
    p.end()
    assert _ink_cols(img, thr=1) == [], "B tasarımı: üzerine gelinmeden kart zemini/çerçevesi çizilmez"
    img = _canvas()
    p = QPainter(img)
    dock_cards.draw_card_base(p, QRectF(10, 6, 180, 52), hover=True)
    p.end()
    c = QColor(img.pixel(int(100 * DPR), int(32 * DPR)))
    d = (c.red() - 13, c.green() - 15, c.blue() - 19)
    assert 0 < d[0] < 30 and max(d) - min(d) <= 2, d  # hafif, renksiz zemin


def test_divider_is_one_device_pixel_and_centred() -> None:
    img = _canvas()
    p = QPainter(img)
    dock_cards.draw_card_divider(p, 100.3, 32.0)
    p.end()
    cols = _ink_cols(img, thr=4)
    assert len(cols) == 1, cols  # 1,25 ölçekte tek, keskin cihaz pikseli
    rows = [y for y in range(img.height()) if QColor(img.pixel(cols[0], y)).red() > 20]
    top, bottom = rows[0] / DPR, (rows[-1] + 1) / DPR
    assert abs((top + bottom) / 2.0 - 32.0) <= 0.5, (top, bottom)
    assert abs((bottom - top) - dock_cards.CARD_DIVIDER_H) <= 1.0


def test_two_accent_colours() -> None:
    blue = dock_cards.COLOR_ACCENT_BLUE
    for name in ("COLOR_CLAUDE_SKY", "COLOR_GEMINI_BLUE", "COLOR_CPU_BAR", "COLOR_RAM_BAR", "COLOR_MEDIA_PLAY_BG"):
        assert getattr(dock_cards, name) == blue, name
    assert dock_cards.COLOR_CLAUDE_CORAL == QColor("#D97757")
    for c in (dock_cards.COLOR_MEDIA_GRAD_START, dock_cards.COLOR_MEDIA_GRAD_END):
        assert c.red() == c.green() == c.blue(), "medya karosu nötr (pembe-mor yok)"
    # aynı renkte de işlemci/bellek eşikleri ayrı kalır
    f = dock_cards.get_sys_ring_color
    assert f(77.0, blue, is_ram=False) == dock_cards.COLOR_BAR_AMBER
    assert f(77.0, blue, is_ram=True) == blue
    assert f(85.0, blue, is_ram=True) == dock_cards.COLOR_BAR_AMBER
    assert f(93.0, blue, is_ram=True) == dock_cards.COLOR_BAR_RED


def test_quota_rows_keep_reset_time_and_share_baseline() -> None:
    """%100 + 'Claude' + '19 sa 27 dk' 123 px'e sığar (büyük yüzdeyle saat kaybolmasın)."""
    img = _canvas(200.0, 64.0)
    p = QPainter(img)
    rect = QRectF(10.0, 14.0, 123.0, 36.0)
    dock_cards.draw_concentric_text_rows(
        p, rect, (100.0, dock_cards.COLOR_CLAUDE_CORAL, "Claude", "19 sa 27 dk"),
        (86.0, dock_cards.COLOR_GEMINI_BLUE, "Gemini", "21 sa 28 dk"))
    p.end()
    cols = _ink_cols(img)
    assert cols and cols[-1] / DPR > 128.0, "sıfırlanma saati sağ kenara kadar çizilmeli"

    def ink_rows(x0: float, x1: float, y0: float, y1: float) -> tuple:
        ys = [y for y in range(int(y0 * DPR), int(y1 * DPR))
              if any(max(abs(QColor(img.pixel(x, y)).red() - 13), abs(QColor(img.pixel(x, y)).blue() - 19)) > 40
                     for x in range(int(x0 * DPR), int(x1 * DPR)))]
        return ys[0], ys[-1]

    # üst satır: yüzde rakamları ile sıfırlanma rakamları aynı taban çizgisinde (alt kenar ±1 cihaz px)
    _t1, b_pct = ink_rows(11.0, 34.0, 14.0, 32.0)
    _t2, b_rst = ink_rows(118.0, 133.0, 14.0, 32.0)
    assert abs(b_pct - b_rst) <= 1, (b_pct, b_rst)
    # iki satırlık blok kartın ortasında (32): üst satır büyük harf üstü .. alt satır tabanı
    top, _ = ink_rows(11.0, 34.0, 14.0, 32.0)
    _, bot = ink_rows(11.0, 34.0, 32.0, 50.0)
    assert abs((top + bot + 1) / 2.0 / DPR - 32.0) <= 0.8, (top / DPR, bot / DPR)


def test_media_title_uses_free_width() -> None:
    img = _canvas(340.0, 64.0)
    p = QPainter(img)
    rects = dock_cards.draw_media_card(p, QRectF(10.0, 6.0, 314.0, 52.0),
                                       {"title": "Örnek dizi · 3. Sezon 4. Bölüm", "app": "Chrome",
                                        "artist": "Web Yayını", "playing": True})
    p.end()
    assert abs(rects["prev"].left() - (10.0 + 314.0 - 106.0)) < 0.01  # kontroller sağa yaslı
    title_cols = [x / DPR for x in _ink_cols(img, int(14 * DPR), int(30 * DPR), thr=60) if x / DPR < rects["prev"].left()]
    assert title_cols[-1] > 66.0 + 128.0, "başlık eski 128 px sınırını aşmalı"
    assert title_cols[-1] < rects["prev"].left() - 4.0, "başlık önceki düğmesine değmemeli"


def test_band_dock_draws_dividers_between_groups() -> None:
    spec = importlib.util.spec_from_file_location("serit_v5_v24", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v24_")) / "settings.json"
    m.save_settings = lambda cfg: None
    d = m.SeritDock({"style": "band", "cards": {"cal": False, "mail": False, "ag": True, "sys": True}},
                    preview_mode=True)
    d.store.update("claude", {"session": 28.0, "week": 51.0, "session_reset": "", "week_reset": ""})
    d.store.update("ag", {"groups": [{"label": "Claude", "used": 40.0}, {"label": "Gemini 3", "used": 20.0}]})
    d.store.update("sys", {"cpu": 20.0, "ram": 58.0})
    d.store.update("wx", {"temp": 14.0, "icon": "cloud"})  # hava | saat ayracı için
    d.tiles = [{"exe": "C:/ornek/a.exe", "name": "Örnek A", "running": True, "hwnds": [1], "count": 1},
               {"exe": "C:/ornek/b.exe", "name": "Örnek B", "running": False, "hwnds": []}]
    d._now_playing_info = {"title": "Örnek şarkı", "artist": "Örnek", "app": "Spotify", "playing": False}
    d.compute_layout_and_resize()
    d.resize(1536, int(m.DOCK_HEIGHT))
    img = QImage(int(d.width() * DPR), int(m.DOCK_HEIGHT * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(0)
    d.render(img, QPoint(0, 0))
    y = int(32 * DPR)
    divs = []
    for x in range(int(12 * DPR), img.width() - 2):
        c, l2, r2 = QColor(img.pixel(x, y)), QColor(img.pixel(x - 2, y)), QColor(img.pixel(x + 2, y))
        if 25 < c.red() < 70 and abs(l2.red() - 13) < 5 and abs(r2.red() - 13) < 5:
            run = sum(1 for yy in range(int(20 * DPR), int(44 * DPR)) if abs(QColor(img.pixel(x, yy)).red() - c.red()) < 4)
            if run >= int(22 * DPR):
                divs.append(x / DPR)
    # Claude|AG, AG|Sistem, Sistem|uygulamalar, uygulamalar|medya, hava|saat
    assert len(divs) >= 5, divs
    # kartlar arasında kutu zemini yok: Claude kartının içi bant renginde
    r_claude = next(r for r, k, _e in d.hit_boxes if k == "claude")
    c = QColor(img.pixel(int((r_claude.x() + 4) * DPR), int((r_claude.y() + 4) * DPR)))
    assert (c.red(), c.green(), c.blue()) == (13, 15, 19), c.name()


def run_all() -> None:
    for fn in (test_card_base_is_boxless_until_hover, test_divider_is_one_device_pixel_and_centred,
               test_two_accent_colours, test_quota_rows_keep_reset_time_and_share_baseline,
               test_media_title_uses_free_width, test_band_dock_draws_dividers_between_groups):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_DESIGN TESTS PASSED")


if __name__ == "__main__":
    run_all()
