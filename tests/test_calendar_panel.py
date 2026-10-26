"""Unit and integration tests for calendar_panel.py and sources.fetch_month_calendar().

Covers:
1. Date parsing: all-day exclusive end, multi-day spans, datetime parsing
2. Category classification: Google Takvim, Vergi/ödeme, Resmi tatil, Claude
3. Turkish public holidays and computed Claude usage markers
4. Bad-data matrix (>= 30 test cases) for fetch_month_calendar and panel show/paint
5. Day selection and month navigation
6. Mocked link opening via QDesktopServices
7. Paint performance benchmarking (< 5ms per frame)
8. High-DPI DPR 2.0 offscreen renders:
   - cal_oct.png
   - cal_oct_28.png
   - cal_nov.png
   - cal_empty.png
   - cal_error.png
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
import time
from typing import Any, List, Tuple
from unittest.mock import MagicMock

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QDesktopServices, QImage, QPainter
from PySide6.QtWidgets import QApplication

# Ensure repository root in sys.path
REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import calendar_panel
import sources

SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v6")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

# Headless / GUI App instance
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


def test_date_parsing_and_spans() -> None:
    """Test date parsing, exclusive all-day end, and multi-day spans."""
    print("--- 1. Testing Date Parsing & Multi-day Spans ---")

    # 1. 10-char string is parsed as all-day date
    d, is_all_day = sources._parse_month_date_or_dt("2026-10-14")
    assert is_all_day is True, "Expected all_day=True for 10-char date"
    assert d == dt.date(2026, 10, 14)

    # 2. ISO datetime is parsed as timed datetime
    dt_val, is_all_day = sources._parse_month_date_or_dt("2026-10-13T09:30:00+03:00")
    assert is_all_day is False, "Expected all_day=False for ISO datetime"
    assert isinstance(dt_val, dt.datetime)
    assert dt_val.hour == 9 and dt_val.minute == 30

    # 3. Exclusive all-day end behavior
    panel = calendar_panel.CalendarPanel()
    span_event = {
        "title": "Konferans",
        "start": dt.date(2026, 10, 14),
        "end": dt.date(2026, 10, 17),  # Spans 14, 15, 16 (17 is exclusive)
        "all_day": True,
        "link": "",
        "category": "Google Takvim",
    }
    events_list = [span_event]

    m14 = panel._match_events_for_date(dt.date(2026, 10, 14), events_list, [])
    assert len(m14) == 1, "Should cover start day 2026-10-14"

    m15 = panel._match_events_for_date(dt.date(2026, 10, 15), events_list, [])
    assert len(m15) == 1, "Should cover middle day 2026-10-15"

    m16 = panel._match_events_for_date(dt.date(2026, 10, 16), events_list, [])
    assert len(m16) == 1, "Should cover last inclusive day 2026-10-16"

    m17 = panel._match_events_for_date(dt.date(2026, 10, 17), events_list, [])
    assert len(m17) == 0, "Exclusive end 2026-10-17 must NOT be covered"

    m13 = panel._match_events_for_date(dt.date(2026, 10, 13), events_list, [])
    assert len(m13) == 0, "Day before start must NOT be covered"

    print("  [PASS] Date parsing, exclusive end, and multi-day spans verified.")


def test_category_classification() -> None:
    """Test category classification by keywords, symbols, and emojis."""
    print("--- 2. Testing Category Classification ---")

    tax_cases = [
        "💸 Vergi: Gelir vergisi son gün – 1.739,70 TL",
        "💸 Vergi: Ağustos KDV öde – 811,50 TL (GECİKMEDE)",
        "Eylül KDV son gün – 791,00 TL",
        "SGK prim borcu son ödeme",
        "İnternet faturası öde",
        "Kira ödemesi",
        "VERGİ DAİRESİ BİLDİRİMİ",
    ]
    for title in tax_cases:
        cat = sources.classify_calendar_category(title)
        assert cat == "Vergi/ödeme", f"Failed for '{title}' -> got '{cat}'"

    gcal_cases = [
        "IAS Case 00802139 takip (kariyer.net Ad Clutter)",
        "Alo 199 arandı — harçsız öğrenci pasaportu",
        "IS-DBA kayıt linki geldi mi?",
        "e-Devlet öğrenci belgesi çıktı mı?",
        "Codex aboneliği bitiyor: yeni işçi planını konuş",
        "Nantes başvuru son gün",
    ]
    for title in gcal_cases:
        cat = sources.classify_calendar_category(title)
        assert cat == "Google Takvim", f"Failed for '{title}' -> got '{cat}'"

    # Emoji stripping
    assert calendar_panel.clean_title("💸 Vergi: KDV öde") == "Vergi: KDV öde"
    assert calendar_panel.clean_title("✅ Alo 199 arandı") == "Alo 199 arandı"
    assert calendar_panel.clean_title("🇫🇷 (yedek) Son gün") == "(yedek) Son gün"
    assert calendar_panel.clean_title("🎓 e-Devlet öğrenci") == "e-Devlet öğrenci"
    assert calendar_panel.clean_title("🤖 Codex aboneliği") == "Codex aboneliği"
    assert calendar_panel.clean_title("   Normal Başlık   ") == "Normal Başlık"

    print("  [PASS] Category classification and emoji stripping verified.")


def test_holidays_and_claude_markers() -> None:
    """Test Turkish public holidays and computed Claude usage markers."""
    print("--- 3. Testing Holidays & Claude Markers ---")

    # 1. Republic Day Eve (Arife, Half-day)
    arife = calendar_panel.get_holiday_events_for_date(dt.date(2026, 10, 28))
    assert len(arife) == 1
    assert arife[0]["title"] == "Cumhuriyet Bayramı Arifesi"
    assert arife[0]["category"] == "Resmi tatil"
    assert arife[0]["sub"] == "Yarım gün"
    assert arife[0]["half_day"] is True

    # 2. Republic Day (Full holiday)
    bayram = calendar_panel.get_holiday_events_for_date(dt.date(2026, 10, 29))
    assert len(bayram) == 1
    assert bayram[0]["title"] == "Cumhuriyet Bayramı"
    assert bayram[0]["category"] == "Resmi tatil"
    assert bayram[0]["sub"] == "Tüm gün"
    assert bayram[0]["half_day"] is False

    # 3. Claude Markers
    mock_claude = {
        "week_reset": "2026-10-31T06:00:00.069953+00:00",  # Saturday 09:00 UTC+3
        "subscribed_at": "2026-05-21T07:23:39.399643Z",     # 21st of month
    }
    markers_oct = calendar_panel.get_claude_markers_for_month(mock_claude, 2026, 10)

    # 5 Saturdays in Oct 2026 (Oct 3, 10, 17, 24, 31) + 1 subscription renewal (Oct 21) = 6 markers
    assert len(markers_oct) == 6, f"Expected 6 markers in Oct 2026, got {len(markers_oct)}"

    sat_markers = [m for m in markers_oct if "haftalık sıfırlama" in m["title"]]
    assert len(sat_markers) == 5
    for sm in sat_markers:
        assert sm["category"] == "Claude"
        assert "09:00" in sm["title"]

    ren_markers = [m for m in markers_oct if "Claude yenileme ≈" in m["title"]]
    assert len(ren_markers) == 1
    assert ren_markers[0]["start"] == dt.date(2026, 10, 21)
    assert ren_markers[0]["category"] == "Claude"

    # February clamping test (day 31 -> clamped to 28)
    mock_claude_31 = {"subscribed_at": "2026-01-31T00:00:00Z"}
    markers_feb = calendar_panel.get_claude_markers_for_month(mock_claude_31, 2026, 2)
    feb_ren = [m for m in markers_feb if "Claude yenileme ≈" in m["title"]][0]
    assert feb_ren["start"] == dt.date(2026, 2, 28)

    print("  [PASS] Holidays and Claude markers verified.")


def test_bad_data_matrix() -> None:
    """Test robustness against bad data matrix (>= 30 cases) for file and panel."""
    print("--- 4. Testing Bad-Data Robustness Matrix (>= 30 cases) ---")
    tmp_path = SCRATCH_DIR / "test_probe.json"

    bad_matrix_file: List[Any] = [
        # (raw_content_or_none, expected_error_substring)
        (None, "Takvim dosyası yok"),             # Case 1: File does not exist
        ("", "Takvim okunamadı"),                 # Case 2: Empty file
        ("{", "Takvim okunamadı"),                # Case 3: Truncated JSON
        ("null", "Geçersiz veri"),                # Case 4: Literal null
        ("12345", "Geçersiz veri"),               # Case 5: Literal int
        ("\"hello\"", "Geçersiz veri"),           # Case 6: Literal string
        ("[]", "Geçersiz veri"),                  # Case 7: Literal list
        ("true", "Geçersiz veri"),                # Case 8: Literal bool
        (json.dumps({"hata": "API 500"}), "Takvim güncellenemedi"),  # Case 9: Error flag set
        (json.dumps({}), None),                   # Case 10: Empty dict
        (json.dumps({"etkinlikler": None}), None),# Case 11: None etkinlikler
        (json.dumps({"etkinlikler": 123}), None), # Case 12: Invalid etkinlikler type
        (json.dumps({"etkinlikler": "str"}), None),# Case 13: String etkinlikler
        (json.dumps({"etkinlikler": [None, 42, "foo", []]}), None), # Case 14: Non-dict items
        (json.dumps({"etkinlikler": [{}]}), None),# Case 15: Empty event
        (json.dumps({"etkinlikler": [{"bas": None}]}), None), # Case 16: None start
        (json.dumps({"etkinlikler": [{"bas": "bad-date"}]}), None), # Case 17: Bad date string
        (json.dumps({"etkinlikler": [{"bas": "2026-10-15", "bit": "bad"}]}), None), # Case 18: Bad end
        (json.dumps({"etkinlikler": [{"bas": "2026-10-15", "baslik": None}]}), None), # Case 19: None title
        (json.dumps({"etkinlikler": [{"bas": "2026-10-15", "link": None}]}), None), # Case 20: None link
        (json.dumps({"zaman": "not-iso", "etkinlikler": []}), None), # Case 21: Invalid zaman
        (json.dumps({"zaman": None, "etkinlikler": []}), None), # Case 22: None zaman
        (json.dumps({"bas": "bad", "bit": "bad", "etkinlikler": []}), None), # Case 23: Bad range
        (json.dumps({"etkinlikler": [{"bas": "2026-10-14T10:00:00", "bit": None}]}), None), # Case 24: Datetime without tz
        (json.dumps({"etkinlikler": [{"bas": "2026-10-14", "tum_gun": False}]}), None), # Case 25: 10-char with tum_gun False
    ]

    for idx, (content, exp_err) in enumerate(bad_matrix_file, 1):
        if content is None:
            if tmp_path.exists():
                tmp_path.unlink()
        else:
            tmp_path.write_text(content, encoding="utf-8")

        res = sources.fetch_month_calendar(tmp_path)
        assert isinstance(res, dict)
        assert "events" in res
        assert "updated" in res
        assert "stale" in res
        assert "range" in res
        assert "err" in res
        if exp_err:
            assert res["err"] is not None and exp_err in res["err"], f"Case {idx} failed: {res['err']}"
        else:
            assert res["err"] is None

    if tmp_path.exists():
        tmp_path.unlink()

    # Panel UI Garbage Data Matrix
    panel = calendar_panel.CalendarPanel()
    bad_panel_matrix: List[Tuple[Any, Any]] = [
        (None, None),                                # Case 26
        ({}, {}),                                    # Case 27
        ("string", "string"),                        # Case 28
        (12345, 67890),                              # Case 29
        ([], []),                                    # Case 30
        ({"events": "not a list"}, {"week_reset": 123}), # Case 31
        ({"events": [None, 123, {}]}, {"subscribed_at": 999}), # Case 32
        ({"events": [{"bas": "invalid"}]}, {"week_reset": "bad"}), # Case 33
        ({"events": []}, {"subscribed_at": "bad-date"}), # Case 34
        ({"updated": None, "stale": "maybe"}, {}),   # Case 35
    ]

    for idx, (m_data, c_data) in enumerate(bad_panel_matrix, 26):
        try:
            panel.show_for(QRectF(100, 500, 80, 40), m_data, c_data)
            img = panel.render_to_image(dpr=1.0)
            assert not img.isNull(), f"Render failed on bad case {idx}"
        except Exception as exc:
            assert False, f"Exception escaped on bad case {idx}: {exc}"

    print(f"  [PASS] All {len(bad_matrix_file) + len(bad_panel_matrix)} bad-data matrix cases passed without raising.")


def test_navigation_and_selection() -> None:
    """Test day selection, month navigation, and 'Bugün' action."""
    print("--- 5. Testing Day Selection & Month Navigation ---")
    panel = calendar_panel.CalendarPanel()
    panel.show_for(QRectF(200, 600, 100, 40), {}, {})

    initial_year = panel.view_year
    initial_month = panel.view_month

    # Navigate to next month
    panel.next_month()
    if initial_month == 12:
        assert panel.view_month == 1 and panel.view_year == initial_year + 1
    else:
        assert panel.view_month == initial_month + 1 and panel.view_year == initial_year

    # Navigate to previous month twice
    panel.prev_month()
    panel.prev_month()
    if initial_month == 1:
        assert panel.view_month == 11 and panel.view_year == initial_year - 1
    else:
        assert panel.view_month == initial_month - 1

    # 'Bugün' action
    panel.go_today()
    assert panel.view_year == panel.today.year
    assert panel.view_month == panel.today.month
    assert panel.selected_date == panel.today

    # Select specific date
    target = dt.date(2026, 10, 28)
    panel.select_date(target)
    assert panel.selected_date == target
    assert panel.view_year == 2026
    assert panel.view_month == 10
    assert "28 Ekim" in panel._cached_selected_header_text

    print("  [PASS] Navigation and date selection verified.")


def test_link_click_mock() -> None:
    """Test clicking an event card with link opens URL via QDesktopServices."""
    print("--- 6. Testing Event Link Click Handler ---")
    panel = calendar_panel.CalendarPanel()

    mock_event = {
        "title": "Google Etkinliği",
        "start": dt.date(2026, 10, 26),
        "end": dt.date(2026, 10, 27),
        "all_day": True,
        "link": "https://calendar.google.com/event?eid=mock_test_123",
        "category": "Google Takvim",
    }
    panel.show_for(QRectF(100, 600, 100, 40), {"events": [mock_event]}, {})

    # Mock QDesktopServices.openUrl
    orig_open_url = QDesktopServices.openUrl
    try:
        mock_handler = MagicMock(return_value=True)
        QDesktopServices.openUrl = mock_handler

        # Trigger click on first card
        assert len(panel._cached_selected_cards) > 0
        card_rect = panel._cached_selected_cards[0]["rect"]
        click_pt = card_rect.center()

        # Simulate mouse press at click_pt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        press_ev = QMouseEvent(
            QEvent.MouseButtonPress,
            click_pt,
            click_pt,
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        panel.mousePressEvent(press_ev)

        assert mock_handler.called, "QDesktopServices.openUrl was not called on card click"
        call_arg = mock_handler.call_args[0][0].toString()
        assert "mock_test_123" in call_arg, f"Unexpected URL opened: {call_arg}"
    finally:
        QDesktopServices.openUrl = orig_open_url

    print("  [PASS] Event card URL opening verified.")


def test_paint_benchmark_and_snapshots() -> None:
    """Benchmark paint performance (< 5ms) and render evidence screenshots."""
    print("--- 7. Testing Paint Benchmark (< 5ms) & Offscreen Evidence ---")
    panel = calendar_panel.CalendarPanel()

    # Load real ay.json data
    real_month = sources.fetch_month_calendar()
    real_claude = sources.fetch_claude()

    # Benchmark paint performance
    panel.show_for(QRectF(500, 800, 120, 40), real_month, real_claude)
    panel.select_date(dt.date(2026, 10, 26))

    # Warmup
    _ = panel.render_to_image(dpr=2.0)

    # 100 benchmark iterations
    iterations = 100
    t0 = time.perf_counter()
    w_phys = int(panel.width() * 2.0)
    h_phys = int(panel.height() * 2.0)
    img = QImage(w_phys, h_phys, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)

    p = QPainter(img)
    for _ in range(iterations):
        panel._paint_panel(p)
    p.end()
    t1 = time.perf_counter()

    avg_ms = ((t1 - t0) / iterations) * 1000.0
    print(f"  [BENCHMARK] Average paint time: {avg_ms:.2f} ms per frame (Contract: < 5.0 ms)")
    assert avg_ms < 5.0, f"Paint time exceeded 5.0 ms: {avg_ms:.2f} ms"

    # Render Evidence Snapshots (DPR 2.0)
    # 1. cal_oct.png (real ay.json, today 26 Oct selected)
    panel.show_for(QRectF(500, 800, 120, 40), real_month, real_claude)
    panel.select_date(dt.date(2026, 10, 26))
    img_oct = panel.render_to_image(dpr=2.0)
    path_oct = SCRATCH_DIR / "cal_oct.png"
    img_oct.save(str(path_oct))
    print(f"  [SAVED] {path_oct} ({img_oct.width()}x{img_oct.height()})")

    # 2. cal_oct_28.png (28 Oct selected: KDV + arife)
    panel.select_date(dt.date(2026, 10, 28))
    img_oct_28 = panel.render_to_image(dpr=2.0)
    path_oct_28 = SCRATCH_DIR / "cal_oct_28.png"
    img_oct_28.save(str(path_oct_28))
    print(f"  [SAVED] {path_oct_28} ({img_oct_28.width()}x{img_oct_28.height()})")

    # 3. cal_nov.png (November 2026 view)
    panel.next_month()
    panel.select_date(dt.date(2026, 11, 1))
    img_nov = panel.render_to_image(dpr=2.0)
    path_nov = SCRATCH_DIR / "cal_nov.png"
    img_nov.save(str(path_nov))
    print(f"  [SAVED] {path_nov} ({img_nov.width()}x{img_nov.height()})")

    # 4. cal_empty.png (no data)
    panel.show_for(QRectF(500, 800, 120, 40), {"events": []}, {})
    panel.select_date(dt.date(2026, 10, 26))
    img_empty = panel.render_to_image(dpr=2.0)
    path_empty = SCRATCH_DIR / "cal_empty.png"
    img_empty.save(str(path_empty))
    print(f"  [SAVED] {path_empty} ({img_empty.width()}x{img_empty.height()})")

    # 5. cal_error.png (corrupt file state)
    corrupt_month = sources.fetch_month_calendar(Path("non_existent_file.json"))
    panel.show_for(QRectF(500, 800, 120, 40), corrupt_month, {})
    img_error = panel.render_to_image(dpr=2.0)
    path_error = SCRATCH_DIR / "cal_error.png"
    img_error.save(str(path_error))
    print(f"  [SAVED] {path_error} ({img_error.width()}x{img_error.height()})")

    print("  [PASS] All 5 high-DPI evidence snapshots successfully generated.")


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
    test_paint_benchmark_and_snapshots()
    print("=" * 60)
    print("ALL CALENDAR PANEL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
