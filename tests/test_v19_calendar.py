"""v19: Takvim paneli ortak panel kiti üzerinde + vergi tutarı kopyalama çipi.

Gerçek pano yazılmaz (logpath.is_running_under_test()), ağ/kullanıcı dosyası okunmaz.
Tüm veriler stub'dır; render'lar _ref/out altına yazılır.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import calendar_panel as cp
import panel_style

OUT = REPO_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv)
LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 10, 27, 20, 35, tzinfo=LOCAL_TZ)
ANCHOR = QRectF(500, 800, 120, 32)

TAX_EVENT = {
    "title": "💸 Vergi: Örnek KDV son gün – 1.234,56 TL",
    "start": dt.date(2026, 10, 28),
    "end": dt.date(2026, 10, 29),
    "all_day": True,
    "link": "",
    "category": "Vergi/ödeme",
}
OTHER_EVENTS = [
    {
        "title": "Müşteri vakası takibi (örnek)",
        "start": dt.date(2026, 10, 30),
        "end": dt.date(2026, 10, 31),
        "all_day": True,
        "link": "",
        "category": "Google Takvim",
    },
    {
        "title": "Les Ateliers fiyat revizyonu",
        "start": dt.date(2026, 10, 31),
        "end": dt.date(2026, 11, 1),
        "all_day": True,
        "link": "",
        "category": "Google Takvim",
    },
]


def mk(events=None, selected: dt.date = dt.date(2026, 10, 27),
       updated: str = "19:58") -> cp.CalendarPanel:
    panel = cp.CalendarPanel()
    panel._now_override = NOW
    panel.selected_date = selected
    panel.view_year = selected.year
    panel.view_month = selected.month
    panel.show_for(ANCHOR, {"events": list(events if events is not None else []),
                            "updated": updated}, {})
    return panel


def click(panel: cp.CalendarPanel, pt) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pt,
        pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev)


def test_amount_parser() -> None:
    assert cp.parse_turkish_amount("Örnek KDV son gün – 1.234,56 TL") == "1.234,56"
    assert cp.parse_turkish_amount("Kira 6.432,80 TL") == "6.432,80"
    assert cp.parse_turkish_amount("1.234,56 TL ödendi") == "1.234,56"
    assert cp.parse_turkish_amount("Tutar yok") is None
    assert cp.parse_turkish_amount("1.234,56") is None            # TL olmadan None
    assert cp.parse_turkish_amount("1.234,56 USD") is None
    assert cp.parse_turkish_amount(None) is None


def test_chip_window_and_tax_only() -> None:
    # 28 Eki (now + ~3 sa): çip var
    panel = mk([TAX_EVENT] + OTHER_EVENTS)
    assert panel._tax_chip is not None
    assert panel._tax_chip["amount"] == "1.234,56"
    assert panel._tax_chip["label"] == "Örnek KDV son gün · 1.234,56 TL"
    panel.hide_instant()
    panel.close()

    # 30 Eki all-day (~51 sa sonra): 48 saat penceresi dışında, çip yok
    far = dict(TAX_EVENT)
    far["start"] = dt.date(2026, 10, 30)
    far["end"] = dt.date(2026, 10, 31)
    panel = mk([far])
    assert panel._tax_chip is None
    panel.hide_instant()
    panel.close()

    # Vergi değil: kategori Google ve başlıkta anahtar kelime yok -> çip yok
    not_tax = {
        "title": "Toplantı – 1.234,56 TL",
        "start": dt.date(2026, 10, 28),
        "end": dt.date(2026, 10, 29),
        "all_day": True,
        "link": "",
        "category": "Google Takvim",
    }
    panel = mk([not_tax])
    assert panel._tax_chip is None
    panel.hide_instant()
    panel.close()

    # Kategori Google ama başlıkta KDV var -> çip var (mevcut kategori VEYA anahtar kelime)
    keyword_tax = dict(not_tax)
    keyword_tax["title"] = "KDV ödemesi – 1.234,56 TL"
    panel = mk([keyword_tax])
    assert panel._tax_chip is not None and panel._tax_chip["amount"] == "1.234,56"
    panel.hide_instant()
    panel.close()

    # Vergi ama tutar yok -> çip yok (tutar uydurulmaz)
    no_amount = {
        "title": "💸 Vergi: Örnek KDV son gün",
        "start": dt.date(2026, 10, 28),
        "end": dt.date(2026, 10, 29),
        "all_day": True,
        "link": "",
        "category": "Vergi/ödeme",
    }
    panel = mk([no_amount])
    assert panel._tax_chip is None
    panel.hide_instant()
    panel.close()


def test_chip_hit_test_and_test_clipboard_guard() -> None:
    panel = mk([TAX_EVENT] + OTHER_EVENTS)
    panel.render_to_image(2.0)
    assert not panel._tax_chip_rect.isNull()

    # Gerçek pano yazılmadığını kanıtla: clipboard() hiç çağrılmamalı.
    assert cp._under_test() is True
    fake_clip = MagicMock()
    orig_clip = cp.QGuiApplication.clipboard
    cp.QGuiApplication.clipboard = staticmethod(lambda: fake_clip)
    try:
        click(panel, panel._tax_chip_rect.center())
        assert fake_clip.setText.call_count == 0, "Test sırasında gerçek panoya yazıldı!"
    finally:
        cp.QGuiApplication.clipboard = orig_clip

    assert panel._tax_copied is True
    assert cp._write_clipboard("1.234,56") is False              # testte gerçek yazma kapalı
    panel.hide_instant()
    panel.close()


def test_width_close_switch_and_hide_instant() -> None:
    panel = mk([TAX_EVENT] + OTHER_EVENTS)
    assert panel.WIDTH == panel_style.WIDTH["cal"] == 440
    assert panel.width() == 440

    click(panel, panel._rect_close.center())
    assert panel._is_closing is True
    panel.hide_instant()
    assert not panel.isVisible()

    panel.show_for(ANCHOR, {"events": [TAX_EVENT] + OTHER_EVENTS, "updated": "19:58"},
                   {}, switch_from_x=300)
    assert panel.is_open()
    panel.hide_instant()
    assert not panel.isVisible() and panel.recently_closed()

    # Esc kapanışı
    panel.show_for(ANCHOR, {"events": [], "updated": "19:58"}, {})
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(ev)
    panel.hide_instant()
    assert not panel.isVisible()
    panel.close()


def test_paint_benchmark() -> None:
    panel = mk([TAX_EVENT] + OTHER_EVENTS)
    panel.render_to_image(2.0)
    img = QImage(panel.width() * 2, panel.height() * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    rounds, per_round = 5, 20
    times = []
    p = QPainter(img)
    for _ in range(rounds):
        t0 = time.perf_counter()
        for _ in range(per_round):
            panel._paint_panel(p)
        times.append(((time.perf_counter() - t0) / per_round) * 1000.0)
    p.end()
    best = min(times)
    print(f"  [BENCHMARK] Best-round paint time: {best:.2f} ms per frame (Contract: < 8.0 ms)")
    assert best < 8.0, f"Paint time exceeded 8.0 ms: {best:.2f} ms"
    panel.hide_instant()
    panel.close()


def test_renders() -> None:
    # 1) Normal: vergi çipi görünür
    panel = mk([TAX_EVENT] + OTHER_EVENTS, selected=dt.date(2026, 10, 27))
    assert panel._tax_chip is not None
    img = panel.render_to_image(2.0)
    assert img.width() == 880 and img.height() == panel.height() * 2
    img.save(str(OUT / "takvim_normal.png"))

    # 2) Kopyalandı ✓ durumu
    panel.copy_tax_amount()
    assert panel._tax_copied is True
    panel.render_to_image(2.0).save(str(OUT / "takvim_kopyalandi.png"))

    panel.hide_instant()
    panel.close()

    # 3) Boş: Kasım 2027 (görünen ızgarada tatil yok) + etkinlik yok
    empty = cp.CalendarPanel()
    empty._now_override = dt.datetime(2027, 11, 1, 10, 0, tzinfo=LOCAL_TZ)
    empty.selected_date = dt.date(2027, 11, 1)
    empty.view_year, empty.view_month = 2027, 11
    empty.show_for(ANCHOR, {"events": [], "updated": "19:58"}, {})
    assert empty._tax_chip is None
    assert empty._cached_month_event_count == 0
    assert not empty._cached_upcoming
    empty.render_to_image(2.0).save(str(OUT / "takvim_bos.png"))
    empty.hide_instant()
    empty.close()

    for name in ("takvim_normal.png", "takvim_kopyalandi.png", "takvim_bos.png"):
        assert (OUT / name).exists(), name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
