"""Calendar panel tests (panel_style v2 rebuild) — stub data only, no network/user files.

Covers:
1. Date parsing: exclusive all-day end, multi-day spans, datetimes
2. Category classification and Turkish holiday / Claude marker helpers
3. Bad-data matrix for show/paint (no exception escapes)
4. Day selection, month navigation and "Bugün"
5. Event link opening (mocked)
6. Paint benchmark (< 8 ms per frame, best round)
7. Design contract: 440 px, 30 px day cells, colored 3 x 28 px event strips
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import time
from typing import Any, List, Tuple
from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QDesktopServices, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import calendar_panel
import panel_style
import sources

OUT_DIR = REPO_DIR / "_ref" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication(sys.argv)

LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 10, 27, 20, 35, tzinfo=LOCAL_TZ)
ANCHOR = QRectF(500, 800, 120, 40)

STUB_EVENTS = [
    {
        "title": "💸 Vergi: Örnek KDV son gün – 1.234,56 TL",
        "start": dt.date(2026, 10, 28),
        "end": dt.date(2026, 10, 29),
        "all_day": True,
        "link": "",
        "category": "Vergi/ödeme",
    },
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


def make_panel(events=None, selected: dt.date = dt.date(2026, 10, 27),
               claude=None, updated: str = "19:58") -> calendar_panel.CalendarPanel:
    panel = calendar_panel.CalendarPanel()
    panel._now_override = NOW
    panel.selected_date = selected
    panel.view_year = selected.year
    panel.view_month = selected.month
    panel.show_for(ANCHOR, {"events": list(STUB_EVENTS if events is None else events),
                            "updated": updated}, claude or {})
    return panel


def click(panel: calendar_panel.CalendarPanel, pt) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pt,
        pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev)


def test_date_parsing_and_spans() -> None:
    print("--- 1. Date parsing & multi-day spans ---")
    d, is_all_day = sources._parse_month_date_or_dt("2026-10-14")
    assert is_all_day is True and d == dt.date(2026, 10, 14)

    dt_val, is_all_day = sources._parse_month_date_or_dt("2026-10-13T09:30:00+03:00")
    assert is_all_day is False and isinstance(dt_val, dt.datetime)
    assert dt_val.hour == 9 and dt_val.minute == 30

    panel = calendar_panel.CalendarPanel()
    span = {
        "title": "Konferans",
        "start": dt.date(2026, 10, 14),
        "end": dt.date(2026, 10, 17),
        "all_day": True,
        "link": "",
        "category": "Google Takvim",
    }
    events = [span]
    assert len(panel._match_events_for_date(dt.date(2026, 10, 14), events, [])) == 1
    assert len(panel._match_events_for_date(dt.date(2026, 10, 15), events, [])) == 1
    assert len(panel._match_events_for_date(dt.date(2026, 10, 16), events, [])) == 1
    assert len(panel._match_events_for_date(dt.date(2026, 10, 17), events, [])) == 0
    assert len(panel._match_events_for_date(dt.date(2026, 10, 13), events, [])) == 0
    panel.close()
    print("  [PASS] Date parsing, exclusive end, multi-day spans verified.")


def test_category_classification() -> None:
    print("--- 2. Category classification & emoji stripping ---")
    tax_cases = [
        "💸 Vergi: Örnek gelir vergisi son gün – 1.234,56 TL",
        "💸 Vergi: Örnek KDV öde – 456,70 TL (GECİKMEDE)",
        "Örnek KDV son gün – 1.234,56 TL",
        "SGK prim borcu son ödeme",
        "İnternet faturası öde",
        "Kira ödemesi",
        "VERGİ DAİRESİ BİLDİRİMİ",
        "Bağ-Kur prim ödemesi",
    ]
    for title in tax_cases:
        assert sources.classify_calendar_category(title) == "Vergi/ödeme", title
    for title in tax_cases[:4] + tax_cases[6:]:
        assert calendar_panel.is_tax_item(title), title

    gcal_cases = [
        "Müşteri vakası takibi (örnek)",
        "Örnek telefon görüşmesi",
        "Örnek kayıt linki kontrolü",
        "Örnek belge kontrolü",
        "Örnek başvuru son gün",
    ]
    for title in gcal_cases:
        assert sources.classify_calendar_category(title) == "Google Takvim", title
        assert not calendar_panel.is_tax_item(title), title

    assert calendar_panel.clean_title("💸 Vergi: KDV öde") == "Vergi: KDV öde"
    assert calendar_panel.clean_title("✅ Örnek görüşme yapıldı") == "Örnek görüşme yapıldı"
    assert calendar_panel.clean_title("🇫🇷 (yedek) Son gün") == "(yedek) Son gün"
    assert calendar_panel.clean_title("🎓 e-Devlet öğrenci") == "e-Devlet öğrenci"
    assert calendar_panel.clean_title("   Normal Başlık   ") == "Normal Başlık"
    print("  [PASS] Category classification and emoji stripping verified.")


def test_holidays_and_claude_markers() -> None:
    print("--- 3. Holidays & Claude markers ---")
    arife = calendar_panel.get_holiday_events_for_date(dt.date(2026, 10, 28))
    assert len(arife) == 1
    assert arife[0]["title"] == "Cumhuriyet Bayramı Arifesi"
    assert arife[0]["category"] == "Resmi tatil"
    assert arife[0]["sub"] == "Yarım gün"
    assert arife[0]["half_day"] is True

    bayram = calendar_panel.get_holiday_events_for_date(dt.date(2026, 10, 29))
    assert len(bayram) == 1 and bayram[0]["sub"] == "Tüm gün"

    mock_claude = {
        "week_reset": "2026-10-31T06:00:00.069953+00:00",
        "subscribed_at": "2026-05-21T07:23:39.399643Z",
    }
    markers_oct = calendar_panel.get_claude_markers_for_month(mock_claude, 2026, 10)
    assert len(markers_oct) == 6
    assert len([m for m in markers_oct if "haftalık sıfırlama" in m["title"]]) == 5
    assert len([m for m in markers_oct if "Claude yenileme ≈" in m["title"]]) == 1

    markers_feb = calendar_panel.get_claude_markers_for_month(
        {"subscribed_at": "2026-01-31T00:00:00Z"}, 2026, 2)
    feb_ren = [m for m in markers_feb if "Claude yenileme ≈" in m["title"]][0]
    assert feb_ren["start"] == dt.date(2026, 2, 28)
    print("  [PASS] Holidays and Claude markers verified.")


def test_bad_data_matrix() -> None:
    print("--- 4. Bad-data matrix (panel paint) ---")
    panel = calendar_panel.CalendarPanel()
    panel._now_override = NOW
    bad_matrix: List[Tuple[Any, Any]] = [
        (None, None),
        ({}, {}),
        ("string", "string"),
        (12345, 67890),
        ([], []),
        ({"events": "not a list"}, {"week_reset": 123}),
        ({"events": [None, 123, {}]}, {"subscribed_at": 999}),
        ({"events": [{"start": "invalid"}]}, {"week_reset": "bad"}),
        ({"events": []}, {"subscribed_at": "bad-date"}),
        ({"updated": None, "stale": "maybe"}, {}),
        ({"events": [{"title": "x", "start": dt.date(2026, 10, 14), "end": None}]}, {}),
    ]
    for idx, (m_data, c_data) in enumerate(bad_matrix, 1):
        try:
            panel.show_for(ANCHOR, m_data, c_data)
            img = panel.render_to_image(dpr=1.0)
            assert not img.isNull(), f"Render failed on bad case {idx}"
        except Exception as exc:
            assert False, f"Exception escaped on bad case {idx}: {exc}"
        panel.hide_instant()
    panel.close()
    print(f"  [PASS] All {len(bad_matrix)} bad-data cases painted without raising.")


def test_navigation_and_selection() -> None:
    print("--- 5. Day selection & month navigation ---")
    panel = make_panel()
    assert panel.view_year == 2026 and panel.view_month == 10

    panel.next_month()
    assert panel.view_month == 11 and panel.view_year == 2026
    panel.prev_month()
    panel.prev_month()
    assert panel.view_month == 9 and panel.view_year == 2026

    panel.go_today()
    assert panel.view_year == panel.today.year
    assert panel.view_month == panel.today.month
    assert panel.selected_date == panel.today

    target = dt.date(2026, 10, 28)
    panel.select_date(target)
    assert panel.selected_date == target
    assert panel.view_year == 2026 and panel.view_month == 10
    assert "28 Ekim" in panel._cached_selected_header_text
    panel.hide_instant()
    panel.close()
    print("  [PASS] Navigation and date selection verified.")


def test_link_click_mock() -> None:
    print("--- 6. Event link click handler ---")
    mock_event = {
        "title": "Google Etkinliği",
        "start": dt.date(2026, 10, 27),
        "end": dt.date(2026, 10, 28),
        "all_day": True,
        "link": "https://calendar.google.com/event?eid=mock_test_123",
        "category": "Google Takvim",
    }
    panel = make_panel(events=[mock_event], selected=dt.date(2026, 10, 27))

    orig_open_url = QDesktopServices.openUrl
    try:
        mock_handler = MagicMock(return_value=True)
        QDesktopServices.openUrl = mock_handler
        assert panel._cached_selected_cards
        click(panel, panel._cached_selected_cards[0]["rect"].center())
        assert mock_handler.called, "QDesktopServices.openUrl was not called on card click"
        assert "mock_test_123" in mock_handler.call_args[0][0].toString()
    finally:
        QDesktopServices.openUrl = orig_open_url
        panel.hide_instant()
        panel.close()
    print("  [PASS] Event card URL opening verified.")


def test_paint_benchmark_and_snapshot() -> None:
    print("--- 7. Paint benchmark (< 8 ms) ---")
    panel = make_panel(selected=dt.date(2026, 10, 27))
    _ = panel.render_to_image(dpr=2.0)

    w_phys = int(panel.width() * 2.0)
    h_phys = int(panel.height() * 2.0)
    img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)

    rounds, per_round = 5, 20
    round_ms = []
    p = QPainter(img)
    for _ in range(rounds):
        t0 = time.perf_counter()
        for _ in range(per_round):
            panel._paint_panel(p)
        round_ms.append(((time.perf_counter() - t0) / per_round) * 1000.0)
    p.end()

    avg_ms = min(round_ms)
    print(f"  [BENCHMARK] Best-round paint time: {avg_ms:.2f} ms per frame (Contract: < 8.0 ms)")
    assert avg_ms < 8.0, f"Paint time exceeded 8.0 ms: {avg_ms:.2f} ms"

    path = OUT_DIR / "takvim_benchmark.png"
    panel.render_to_image(dpr=2.0).save(str(path))
    print(f"  [SAVED] {path}")
    panel.hide_instant()
    panel.close()


def test_design_contract() -> None:
    print("--- 8. Shared-kit design contract ---")
    panel = make_panel(selected=dt.date(2026, 10, 28))
    assert panel.WIDTH == panel_style.WIDTH["cal"] == 440
    assert panel.RADIUS == panel_style.R_PANEL

    # Month grid: six rows of 30 px cells, 4x4 dot 3 px above the cell bottom.
    assert len(panel._cached_cells) == 42
    assert all(abs(c["rect"].height() - 30.0) < 0.01 for c in panel._cached_cells)
    assert abs(panel._cached_cells[0]["rect"].top() + 30.0
               - panel._cached_cells[7]["rect"].top()) < 0.01

    # Selected-day list contains both holiday and tax rows with identity strip colors.
    cats = [s["category"] for s in panel._cached_selected_events]
    assert "Resmi tatil" in cats and "Vergi/ödeme" in cats
    tax_row = [s for s in panel._cached_selected_events if s["category"] == "Vergi/ödeme"][0]
    assert tax_row["strip_color"] == panel_style.WARN
    assert tax_row["amount"] == "1.234,56 TL"

    # Upcoming rows use the same 3 x 28 px strip colors (no round dot field).
    # v24: the selected day (28 Eki: arife + vergi) is not repeated in "Yaklaşan"; list starts the next day.
    assert len(panel._cached_upcoming) == 3
    assert all(u["target_date"] > dt.date(2026, 10, 28) for u in panel._cached_upcoming)
    assert panel._cached_upcoming[0]["strip_color"] == panel_style.DANGER   # 29 Eki Cumhuriyet Bayramı
    assert panel._cached_upcoming[1]["strip_color"] == panel_style.ACCENT
    assert panel._cached_upcoming[2]["strip_color"] == panel_style.ACCENT
    assert panel._cached_footer_source == "Google Takvim · 19:58"

    img = panel.render_to_image(dpr=2.0)
    assert img.width() == 880 and img.height() == panel.height() * 2
    panel.hide_instant()
    panel.close()
    print("  [PASS] Width, 30 px cells, strips and footer source verified.")


if __name__ == "__main__":
    print("=" * 60)
    print("      RUNNING ŞERİT CALENDAR PANEL UNIT TEST SUITE      ")
    print("=" * 60)
    test_date_parsing_and_spans()
    test_category_classification()
    test_holidays_and_claude_markers()
    test_bad_data_matrix()
    test_navigation_and_selection()
    test_link_click_mock()
    test_paint_benchmark_and_snapshot()
    test_design_contract()
    print("=" * 60)
    print("ALL CALENDAR PANEL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
