"""test_v19_info_panels.py - Mail ve Antigravity panelleri ortak panel kitine geçti.

352 px genişlik, kota satırları (DOLU/%100 kırmızı, %82 mavi, eksik '—'), hata durumu,
× kapatma, switch_from_x / hide_instant ve alt bilgi Yenile sinyali doğrulanır.
Yalnızca sahte (stub) veri kullanılır; ağ okuyucuları ASLA çağrılmaz.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import info_panels as ip  # noqa: E402
import panel_style as ps  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

ANCHOR = QRectF(500.0, 800.0, 120.0, 32.0)


def _iso(days: int, hours: int = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days, hours=hours)).isoformat()


AG_NORMAL = {
    "groups": [
        {"label": "Claude", "used": 100.0, "reset_at": _iso(2)},
        {"label": "GPT-OSS", "used": 61.0, "reset_at": _iso(0, 3)},
        {"label": "Gemini", "used": 82.0, "reset_at": _iso(3)},
        {"label": "Gemini Görsel", "used": None, "reset_at": None},
    ],
    "fetched_at": _iso(0),
}
AG_ERROR = {"err": "Antigravity okunamadı"}

MAIL_NORMAL = {
    "accounts": [
        {
            "key": "ias",
            "label": "IAS",
            "open": 1,
            "hidden_auto": 0,
            "items": [
                {
                    "kimden": "Müşteri Bir",
                    "konu": "Raporlama entegrasyonu hakkında çok uzun bir konu başlığı",
                    "bekleme_saat": 48,
                    "okunmamis": True,
                    "kapanis_tahmini": False,
                    "url": "https://mail.google.com/test1",
                }
            ],
        },
        {
            "key": "kisisel02",
            "label": "Kişisel",
            "open": 1,
            "hidden_auto": 3,
            "items": [
                {
                    "kimden": "Arkadaş İki",
                    "konu": "Buluşma planı",
                    "bekleme_saat": 5,
                    "okunmamis": False,
                    "kapanis_tahmini": False,
                    "url": "https://mail.google.com/test3",
                }
            ],
        },
        {"key": "logaritma", "label": "Logaritma", "open": 0, "hidden_auto": 0, "items": []},
    ],
    "total_open": 2,
    "hidden_auto": 3,
    "scanned_at": _iso(0),
    "stale": False,
}

MAIL_EMPTY = {
    "accounts": [
        {"key": "ias", "label": "IAS", "open": 0, "hidden_auto": 0, "items": []},
        {"key": "kisisel02", "label": "Kişisel", "open": 0, "hidden_auto": 0, "items": []},
        {"key": "logaritma", "label": "Logaritma", "open": 0, "hidden_auto": 0, "items": []},
    ],
    "total_open": 0,
    "hidden_auto": 0,
    "scanned_at": None,
    "stale": False,
}


def _mouse(widget, pos, release: bool = False):
    posf = QPointF(pos)
    etype = QEvent.Type.MouseButtonRelease if release else QEvent.Type.MouseButtonPress
    event = QMouseEvent(
        etype, posf, posf, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    if release:
        widget.mouseReleaseEvent(event)
    else:
        widget.mousePressEvent(event)


def _quota(data=AG_NORMAL):
    panel = ip.QuotaPanel()
    panel.set_data(data)
    panel.render_to_image(2.0)
    return panel


def _mail(data=MAIL_NORMAL):
    panel = ip.MailPanel()
    panel.set_data(data)
    panel.render_to_image(2.0)
    return panel


def test_widths_match_shared_kit():
    assert ps.WIDTH["mail"] == ps.WIDTH["ag"] == 352
    assert ip.MailPanel.WIDTH == ip.QuotaPanel.WIDTH == 352
    assert ip.MailPanel().width() == 352
    assert ip.QuotaPanel().width() == 352


def test_quota_rows_and_colors():
    panel = _quota()
    rows = {str(r["label"]): r for r in panel._rows}
    assert len(panel._rows) == 4  # her grup tek satır; birleştirme yok

    claude = rows["Claude"]
    assert claude["used"] == 100.0
    # v24 (tek uyarı): DOLU rozeti yok, çubuk model renginde, yalnız yüzde kırmızı
    assert claude["badge"] is None
    assert claude["pct_text"] == "%100"
    assert claude["color"].name() == ps.CLAUDE.name()
    assert claude["pct_color"].name() == ps.DANGER.name()

    gemini = rows["Gemini"]
    assert gemini["used"] == 82.0
    assert gemini["badge"] is None
    assert gemini["pct_text"] == "%82"
    assert gemini["color"].name() == ps.ACCENT.name()

    gpt = rows["GPT-OSS"]
    assert gpt["badge"] is None
    assert gpt["identity"].name() == "#d5d9e0"

    missing = rows["Gemini Görsel"]
    assert missing["used"] is None
    assert missing["pct_text"] == "—"
    assert missing["badge"] is None

    for row in panel._rows:
        assert not row["rect"].isNull() and not row["bar_rect"].isNull()
        assert row["reset_text"]


def test_quota_error_state():
    panel = _quota(AG_ERROR)
    assert panel._has_error is True
    assert panel._error_text == "Antigravity okunamadı"
    assert panel._rows == []
    assert panel.height() < _quota().height()

    empty = ip.QuotaPanel()
    empty.set_data(None)
    empty.render_to_image(2.0)
    assert empty._has_error and empty._error_text == "Antigravity okunamadı"


def test_close_hit_rect_closes_both_panels():
    for cls, data in ((ip.MailPanel, MAIL_NORMAL), (ip.QuotaPanel, AG_NORMAL)):
        panel = cls()
        panel.show_for(ANCHOR, data, switch_from_x=120)
        panel.render_to_image(2.0)
        assert panel._close_rect.width() > 0
        _mouse(panel, panel._close_rect.center())
        assert panel._is_closing is True
        panel.hide_instant()
        assert not panel.isVisible()


def test_switch_from_x_and_hide_instant():
    for cls, data in ((ip.MailPanel, MAIL_NORMAL), (ip.QuotaPanel, AG_NORMAL)):
        panel = cls()
        panel.set_data(data)
        panel.show_for(ANCHOR, data, switch_from_x=120)
        assert panel.is_open()
        assert panel.isVisible()
        panel.hide_instant()
        assert not panel.isVisible()
        assert panel.recently_closed()


def test_footer_refresh_button_emits_signal():
    for panel in (_mail(), _quota()):
        got = []
        panel.refresh_requested.connect(lambda: got.append(True))
        assert not panel._refresh_rect.isNull()
        center = panel._refresh_rect.center()
        _mouse(panel, center)
        assert panel._refresh_pressed is True
        _mouse(panel, center, release=True)
        assert got == [True]
        assert panel._refresh_pressed is False


def test_renders_dpr2():
    normal_q = _quota()
    error_q = _quota(AG_ERROR)
    normal_m = _mail()
    empty_m = _mail(MAIL_EMPTY)

    cases = {
        "ag_normal.png": normal_q,
        "ag_hata.png": error_q,
        "mail_normal.png": normal_m,
        "mail_bos.png": empty_m,
    }
    for name, panel in cases.items():
        img = panel.render_to_image(2.0)
        assert not img.isNull()
        assert img.width() == 704
        assert img.height() > 0
        img.save(str(OUT / name))
        assert (OUT / name).is_file()


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  [PASS] {name}")
    print("ALL TEST_V19_INFO_PANELS TESTS PASSED")


if __name__ == "__main__":
    run_all()
