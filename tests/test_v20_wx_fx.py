"""test_v20_wx_fx.py - Hava Durumu ve Döviz panellerinin ortak panel kiti (v20) doğrulaması.

Kapsam: 352 px genişlik, × kapatma, eksik değerlerde '—' (asla '--°'), hata rozeti,
Türkçe sayı biçimleri, switch_from_x / hide_instant ve DPR 2.0 render kanıtları.

Güvenlik: yalnızca statik sahte (stub) veri kullanılır; sources.fetch_weather/fetch_fx
çağrılmaz, ağa çıkılmaz, gerçek sistem değerleri değiştirilmez.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

import panel_style as ps
from popover_v2 import (
    PopoverV2,
    build_fx_content,
    build_wx_content,
)

OUT_DIR = APP_DIR / "_ref" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

ANCHOR = QRect(400, 900, 100, 48)
STAMP = 1_790_000_000.0  # sabit zaman: saat biçimi deterministik kalsın

WX_NORMAL = {
    "temp": 12.0,
    "feel": 10.5,
    "desc": "Parçalı bulutlu",
    "icon": "partly",
    "min": 7.0,
    "max": 15.5,
    "wind": 12.5,
    "city": "Aksaray",
    "source": "open-meteo.com",
    "fetched_at": STAMP,
}
WX_EKSIK = {
    "temp": 9.4,
    "desc": "Açık",
    "icon": "sun",
    "city": "Aksaray",
    "source": "open-meteo.com",
    "fetched_at": STAMP,
}
WX_HATA = {
    "err": "Bağlantı yok",
    "city": "Aksaray",
    "source": "open-meteo.com",
    "fetched_at": STAMP,
}
FX_NORMAL = {
    "usd": 41.92,
    "usd_chg": 0.42,
    "eur": 45.10,
    "eur_chg": -0.18,
    "gold": 5512.40,
    "gold_chg": 0.75,
    "updated": "2026-10-27 20:35:00",
    "source": "finans.truncgil.com",
    "fetched_at": STAMP,
}
FX_EKSIK = {
    "usd": 41.92,
    "usd_chg": None,
    "eur": None,
    "eur_chg": None,
    "gold": None,
    "gold_chg": None,
    "updated": "2026-10-27 20:35:00",
    "source": "finans.truncgil.com",
    "fetched_at": STAMP,
}


def _new_popover() -> PopoverV2:
    return PopoverV2()


def _click_close(pop: PopoverV2) -> None:
    pop.render_to_image(dpr=1.0)  # hit-rect'leri çizimden doldur
    assert pop._close_rect.isValid()
    center = pop._close_rect.center()
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(center), QPointF(center),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    pop.mousePressEvent(ev)


def _all_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for value in obj.values():
            out.extend(_all_strings(value))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for value in obj:
            out.extend(_all_strings(value))
        return out
    return []


def test_widths_and_close():
    """Her iki panel 352 px olmalı ve başlıktaki × kapatmalı."""
    pop = _new_popover()
    pop.show_for("wx", ANCHOR, WX_NORMAL)
    app.processEvents()
    assert pop.width() == ps.WIDTH["wx"] == 352
    _click_close(pop)
    assert pop._is_closing is True
    pop.hide_instant()
    app.processEvents()

    pop.show_for("fx", ANCHOR, FX_NORMAL)
    app.processEvents()
    assert pop.width() == ps.WIDTH["fx"] == 352
    _click_close(pop)
    assert pop._is_closing is True
    pop.hide_instant()
    print("✓ width / × closes test passed.")


def test_wx_missing_and_error():
    """Eksik değerler '—' olmalı; hiçbir yerde '--°' bulunmamalı. Hata rozeti 'Hata'."""
    content = build_wx_content(WX_EKSIK)
    assert content["badge"] == "Aksaray"
    assert content["now"]["temp"] == "9,4°"
    assert content["now"]["desc"] == "Açık"
    rows = content["sections"][0]["rows"]
    assert rows[0]["val"] == "—"      # Hissedilen
    assert rows[1]["val"] == "—"      # En düşük / En yüksek
    assert rows[2]["val"] == "—"      # Rüzgâr
    assert all("--°" not in s for s in _all_strings(content))

    err_content = build_wx_content(WX_HATA)
    assert err_content["badge"] == "Hata"
    assert err_content["error"] == "Bağlantı yok"
    assert err_content["now"]["desc"] == "Hava durumu alınamadı"
    assert err_content["now"]["temp"] == "—"
    assert all(row["val"] == "—" for row in err_content["sections"][0]["rows"])
    assert all("--°" not in s for s in _all_strings(err_content))
    print("✓ weather missing / error test passed.")


def test_fx_missing_and_formats():
    """Döviz eksik değerleri '—'; değerler Türkçe biçimde ve TL ile yazılmalı."""
    missing = build_fx_content(FX_EKSIK)
    assert missing["title"] == "Döviz"
    assert missing["badge"] == "Canlı"
    rows = missing["sections"][0]["rows"]
    assert rows[0]["val"] == "41,92 TL"
    assert rows[0]["chg"] == "—"
    assert rows[1]["val"] == "—" and rows[1]["chg"] == "—"
    assert rows[2]["val"] == "—" and rows[2]["chg"] == "—"
    assert [r["label"] for r in rows] == ["Dolar (USD)", "Euro (EUR)", "Gram altın"]

    normal = build_fx_content(FX_NORMAL)
    rows = normal["sections"][0]["rows"]
    assert rows[0]["chg"].startswith("%0,42")
    assert rows[1]["chg"].startswith("-%0,18")
    assert rows[2]["val"] == "5.512,40 TL"
    assert normal["badge"] == "Canlı"

    err = build_fx_content(dict(FX_NORMAL, err="Bağlantı yok"))
    assert err["badge"] == "Hata"
    assert err["error"] == "Bağlantı yok"
    assert all(r["val"] == "—" for r in err["sections"][0]["rows"])
    print("✓ currency missing / error / format test passed.")


def test_footers():
    """Alt bilgide kaynak + HH:MM; hava durumunda bayat veri 'önbellek' notu."""
    wx = build_wx_content(WX_NORMAL)
    assert wx["footer_note"].startswith("open-meteo.com · ")
    assert re.search(r"·\s*\d{2}:\d{2}$", wx["footer_note"])

    wx_stale = build_wx_content(dict(WX_NORMAL, stale=True))
    assert wx_stale["footer_note"].endswith(" · önbellek")

    fx = build_fx_content(FX_NORMAL)
    assert fx["footer_note"] == "finans.truncgil.com · 20:35"
    print("✓ footer texts test passed.")


def test_switch_from_x_and_hide_instant():
    """switch_from_x animasyonu ve hide_instant() her iki panelde çalışmalı."""
    pop = _new_popover()
    pop.show_for("wx", ANCHOR, WX_NORMAL, switch_from_x=80)
    app.processEvents()
    assert pop.isVisible() is True
    assert pop.is_open("wx") is True
    pop.hide_instant()
    app.processEvents()
    assert pop.isVisible() is False
    assert pop.recently_closed("wx", threshold_ms=1000.0) is True

    pop.show_for("fx", ANCHOR, FX_NORMAL, switch_from_x=220)
    app.processEvents()
    assert pop.isVisible() is True
    assert pop.is_open("fx") is True
    pop.hide_instant()
    app.processEvents()
    assert pop.isVisible() is False
    assert pop.recently_closed("fx", threshold_ms=1000.0) is True
    print("✓ switch_from_x / hide_instant test passed.")


def render_evidence():
    """DPR 2.0 render kanıtları (yalnız bu worktree içindeki _ref/out)."""
    pop = _new_popover()
    cases = [
        ("hava_normal", "wx", WX_NORMAL),
        ("hava_eksik", "wx", WX_EKSIK),
        ("hava_hata", "wx", WX_HATA),
        ("doviz_normal", "fx", FX_NORMAL),
        ("doviz_eksik", "fx", FX_EKSIK),
    ]
    for name, kind, data in cases:
        pop.show_for(kind, ANCHOR, data)
        app.processEvents()
        img = pop.render_to_image(dpr=2.0)
        path = OUT_DIR / f"{name}.png"
        img.save(str(path))
        assert isinstance(img, QImage)
        assert img.width() == pop.width() * 2
        assert img.height() == pop.height() * 2
        print(f"  [RENDER] {path}")
    pop.hide_instant()


if __name__ == "__main__":
    test_widths_and_close()
    test_wx_missing_and_error()
    test_fx_missing_and_formats()
    test_footers()
    test_switch_from_x_and_hide_instant()
    render_evidence()
    print("test_v20_wx_fx: ALL PASSED")
