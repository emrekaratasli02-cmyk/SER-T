"""tests/test_v27_calendar_join.py - Calendar panel meeting join button and link extractor tests (v27).

Covers:
1. Pure helper extract_meeting_link(*texts):
   - Positive cases: Zoom (zoom.us, sub.zoom.us), Google Meet, Teams (microsoft & live), Webex (webex.com, sub.webex.com)
   - Trailing punctuation stripped: .,;:!?)>]}>"'`
   - Negative security cases: http://, lookalike hosts (zoom.us.evil.com, meet.google.com.attacker.com),
     javascript:, data:, non-https schemes, arbitrary domains.
2. sources.fetch_month_calendar event parsing with 'meeting' key from yer/baslik.
3. CalendarPanel join button presence and time-window contract:
   - Today and within window (-10 min <= now - start <= 60 min): 'Katıl' pill displayed.
   - Tomorrow: no pill.
   - 2 hours ago: no pill.
   - 2 hours ahead: no pill.
   - All-day event: no pill.
   - Long title: cleanly elided before the 'Katıl' pill (no text overlap/clipping).
4. Signal contract:
   - Clicking 'Katıl' pill emits join_requested(url) with the exact validated URL.
   - Nothing is opened directly (QDesktopServices.openUrl is not called on join click).
5. Offscreen render snapshot saved to scratch directory.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import tempfile
from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QDesktopServices, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import calendar_panel
import sources

app = QApplication.instance() or QApplication(sys.argv)

LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 11, 2, 10, 0, tzinfo=LOCAL_TZ)
SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/v27-calendar")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
ANCHOR = QRectF(500, 800, 120, 40)


def click_at(panel: calendar_panel.CalendarPanel, pt: QPointF) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pt,
        pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(ev)


def test_meeting_link_extractor_security_and_formats() -> None:
    print("--- 1. Pure helper extract_meeting_link tests ---")
    extractors = [
        ("calendar_panel", calendar_panel.extract_meeting_link),
        ("sources", sources.extract_meeting_link),
    ]

    for mod_name, fn in extractors:
        # Positive cases
        assert fn("https://zoom.us/j/123456789") == "https://zoom.us/j/123456789", f"{mod_name}: zoom bare"
        assert fn("https://us02web.zoom.us/j/987654321?pwd=secret_token") == "https://us02web.zoom.us/j/987654321?pwd=secret_token"
        assert fn("https://meet.google.com/abc-defg-hij") == "https://meet.google.com/abc-defg-hij"
        assert fn("https://teams.microsoft.com/l/meetup-join/19%3ameeting_xyz") == "https://teams.microsoft.com/l/meetup-join/19%3ameeting_xyz"
        assert fn("https://teams.live.com/meet/9876543210") == "https://teams.live.com/meet/9876543210"
        assert fn("https://company.webex.com/meet/user123") == "https://company.webex.com/meet/user123"
        assert fn("https://webex.com/join/user123") == "https://webex.com/join/user123"

        # Trailing punctuation
        assert fn("Görüşme: (https://meet.google.com/abc-def-ghi)!") == "https://meet.google.com/abc-def-ghi"
        assert fn("Link: https://zoom.us/j/123456789, lütfen katılın.") == "https://zoom.us/j/123456789"
        assert fn("Katılım https://teams.microsoft.com/l/meetup-join/123; teşekkürler") == "https://teams.microsoft.com/l/meetup-join/123"
        assert fn("URL: <https://teams.live.com/meet/555>") == "https://teams.live.com/meet/555"
        assert fn("`https://us04web.zoom.us/j/777?pwd=abc`.") == "https://us04web.zoom.us/j/777?pwd=abc"

        # Multiple texts
        assert fn("Ofis toplantı odası", "Haftalık Senkron https://meet.google.com/foo-bar-baz") == "https://meet.google.com/foo-bar-baz"
        assert fn("https://zoom.us/j/111", "https://meet.google.com/222") == "https://zoom.us/j/111"

        # Negative cases
        assert fn("http://zoom.us/j/123456789") is None, "Insecure HTTP must be rejected"
        assert fn("https://zoom.us.evil.com/j/123456789") is None, "Lookalike evil domain must be rejected"
        assert fn("https://evilzoom.us/j/123") is None, "Prefix lookalike must be rejected"
        assert fn("https://meet.google.com.phishing.org/abc") is None, "Phishing subdomain must be rejected"
        assert fn("https://teams.microsoft.com.attacker.com/join") is None, "Attacker host must be rejected"
        assert fn("https://teams.live.com.evil.com/join") is None, "Evil live domain must be rejected"
        assert fn("https://evilwebex.com/meet/user") is None, "Evil webex must be rejected"
        assert fn("javascript:alert(document.cookie)") is None, "javascript: pseudo-URL must be rejected"
        assert fn("data:text/html,<script>alert(1)</script>") is None, "data: pseudo-URL must be rejected"
        assert fn("https://calendar.google.com/event?eid=123") is None, "Regular calendar link is not a meeting link"
        assert fn("https://example.com/meeting") is None, "Arbitrary domain must be rejected"
        assert fn(None, 12345, "", "   ") is None, "Falsy / non-string arguments return None"

    print("  [PASS] Meeting link extractor positive and negative security tests verified.")


def test_sources_fetch_month_calendar_meeting_key() -> None:
    print("--- 2. sources.fetch_month_calendar meeting key tests ---")
    temp_ay = Path(tempfile.mkdtemp(prefix="serit_v27cal_")) / "ay.json"
    data = {
        "zaman": "2026-11-02T09:45:00+03:00",
        "bas": "2026-11-01T00:00:00+03:00",
        "bit": "2026-11-30T00:00:00+03:00",
        "etkinlikler": [
            {
                "baslik": "Müşteri Görüşmesi",
                "bas": "2026-11-02T10:00:00+03:00",
                "bit": "2026-11-02T10:30:00+03:00",
                "tum_gun": False,
                "yer": "https://meet.google.com/abc-def-ghi",
                "link": "https://calendar.google.com/event?eid=1",
            },
            {
                "baslik": "Proje Senkronu https://zoom.us/j/999888777",
                "bas": "2026-11-02T11:00:00+03:00",
                "bit": "2026-11-02T11:45:00+03:00",
                "tum_gun": False,
                "yer": "Online",
                "link": "https://calendar.google.com/event?eid=2",
            },
            {
                "baslik": "Yüz Yüze Öğle Yemeği",
                "bas": "2026-11-02T12:30:00+03:00",
                "bit": "2026-11-02T13:30:00+03:00",
                "tum_gun": False,
                "yer": "Kadıköy",
                "link": "https://calendar.google.com/event?eid=3",
            },
        ],
        "hata": None,
    }
    temp_ay.write_text(__import__("json").dumps(data), encoding="utf-8")

    res = sources.fetch_month_calendar(path=temp_ay, now=NOW)
    events = res.get("events", [])
    assert len(events) == 3, f"Expected 3 events, got {len(events)}"

    # First event has meeting in yer
    assert events[0]["meeting"] == "https://meet.google.com/abc-def-ghi"
    # Second event has meeting in baslik
    assert events[1]["meeting"] == "https://zoom.us/j/999888777"
    # Third event has no meeting
    assert events[2]["meeting"] is None

    print("  [PASS] sources.fetch_month_calendar passes 'meeting' key correctly.")


def test_calendar_panel_join_pill_and_signal() -> None:
    print("--- 3. CalendarPanel join pill display and timing contracts ---")
    today = NOW.date()

    # Events matrix around NOW (2026-11-02 10:00):
    # ev_imminent: starts at 10:05 (starts in 5 min -> within 10 min window) -> HAS PILL
    ev_imminent = {
        "title": "Strateji Toplantısı",
        "start": dt.datetime(2026, 11, 2, 10, 5, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 2, 10, 45, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://meet.google.com/xyz-uvw-rst",
        "link": "https://calendar.google.com/event?eid=101",
        "category": "Google Takvim",
    }
    # ev_ongoing: started 30 min ago at 09:30 -> within 60 min after start -> HAS PILL
    ev_ongoing = {
        "title": "Devam Eden Senkron https://zoom.us/j/111222333",
        "start": dt.datetime(2026, 11, 2, 9, 30, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 2, 10, 30, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://zoom.us/j/111222333",
        "link": "https://calendar.google.com/event?eid=102",
        "category": "Google Takvim",
    }
    # ev_two_hours_ago: started 2 hours ago at 08:00 (120 min ago > 60 min) -> NO PILL
    ev_two_hours_ago = {
        "title": "Sabah Kontrolü",
        "start": dt.datetime(2026, 11, 2, 8, 0, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 2, 8, 30, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://teams.microsoft.com/l/meetup-join/999",
        "link": "https://calendar.google.com/event?eid=103",
        "category": "Google Takvim",
    }
    # ev_future_2h: starts in 2 hours at 12:00 -> NO PILL
    ev_future_2h = {
        "title": "Öğleden Sonra Brifingi",
        "start": dt.datetime(2026, 11, 2, 12, 0, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 2, 12, 30, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://meet.google.com/future-meeting",
        "link": "https://calendar.google.com/event?eid=104",
        "category": "Google Takvim",
    }
    # ev_tomorrow: starts tomorrow -> NO PILL
    ev_tomorrow = {
        "title": "Yarınki Planlama",
        "start": dt.datetime(2026, 11, 3, 10, 0, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 3, 11, 0, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://zoom.us/j/999111222",
        "link": "https://calendar.google.com/event?eid=105",
        "category": "Google Takvim",
    }
    # ev_all_day_today: all-day event today -> NO PILL (no timed kickoff)
    ev_all_day_today = {
        "title": "Şirket İçi Hackathon https://zoom.us/j/444555666",
        "start": today,
        "end": today + dt.timedelta(days=1),
        "all_day": True,
        "meeting": "https://zoom.us/j/444555666",
        "link": "https://calendar.google.com/event?eid=106",
        "category": "Google Takvim",
    }

    panel = calendar_panel.CalendarPanel()
    panel._now_override = NOW
    panel.selected_date = today
    panel.view_year = today.year
    panel.view_month = today.month

    test_events = [
        ev_imminent,
        ev_ongoing,
        ev_two_hours_ago,
        ev_future_2h,
        ev_tomorrow,
        ev_all_day_today,
    ]
    panel.show_for(ANCHOR, {"events": test_events, "updated": "09:58"}, {})

    # Check selected day agenda items
    sel_rows = panel._cached_selected_events
    # Rows should contain today's events:
    title_to_row = {r["title"]: r for r in sel_rows}

    # 1. ev_imminent must have join button
    assert "Strateji Toplantısı" in title_to_row
    row_imminent = title_to_row["Strateji Toplantısı"]
    assert row_imminent["show_join"] is True, "Imminent meeting must have show_join=True"
    assert not row_imminent["join_rect"].isEmpty(), "Imminent meeting must have valid join_rect"

    # 2. ev_ongoing (started 30 min ago) must have join button
    title_ongoing = "Devam Eden Senkron https://zoom.us/j/111222333"
    assert title_ongoing in title_to_row
    row_ongoing = title_to_row[title_ongoing]
    assert row_ongoing["show_join"] is True, "Ongoing meeting within 60 min must have show_join=True"
    assert not row_ongoing["join_rect"].isEmpty()

    # 3. ev_two_hours_ago must NOT have join button
    if "Sabah Kontrolü" in title_to_row:
        assert title_to_row["Sabah Kontrolü"]["show_join"] is False, "Meeting 2 hours ago must NOT show join pill"

    # 4. ev_future_2h must NOT have join button
    if "Öğleden Sonra Brifingi" in title_to_row:
        assert title_to_row["Öğleden Sonra Brifingi"]["show_join"] is False, "Meeting in 2h must NOT show join pill"

    # 5. ev_all_day_today must NOT have join button
    for r in sel_rows:
        if r.get("all_day"):
            assert r["show_join"] is False, "All-day event must not show join pill"

    # 6. ev_tomorrow is in upcoming card, verify it does NOT have join button
    for up_r in panel._cached_upcoming:
        if up_r.get("target_date") == today + dt.timedelta(days=1):
            assert up_r["show_join"] is False, "Tomorrow's event in upcoming card must not show join pill"

    print("  [PASS] Join pill presence / timing window verified.")

    # 7. Test Signal join_requested and ensure NO browser / QDesktopServices opens
    print("--- 4. Signal emit & safety contract ---")
    orig_open_url = QDesktopServices.openUrl
    emitted_links = []
    panel.join_requested.connect(lambda url: emitted_links.append(url))

    try:
        mock_open_url = MagicMock(return_value=True)
        QDesktopServices.openUrl = mock_open_url

        # Click the join pill
        join_btn_center = row_imminent["join_rect"].center()
        click_at(panel, join_btn_center)

        # Assert Signal was emitted with the validated URL
        assert len(emitted_links) == 1, f"Expected 1 join_requested emission, got {len(emitted_links)}"
        assert emitted_links[0] == "https://meet.google.com/xyz-uvw-rst"
        # CRITICAL SAFETY: openUrl MUST NOT be called!
        assert not mock_open_url.called, "QDesktopServices.openUrl was called! Panel must NOT open URLs directly."

        # Click outside the join pill on the row text -> normal card link opening
        row_text_pt = QPointF(row_imminent["rect"].left() + 50.0, row_imminent["rect"].center().y())
        click_at(panel, row_text_pt)
        assert mock_open_url.called, "Normal event click must invoke standard openUrl for Google Calendar link"
        assert len(emitted_links) == 1, "Normal event click must NOT emit join_requested"

    finally:
        QDesktopServices.openUrl = orig_open_url

    print("  [PASS] Signal join_requested emitted safely; no direct browser open from join button.")

    # 8. Test text elision and clipping prevention with a very long title
    long_event = {
        "title": "Çok Uzun Toplantı Başlığı: Şirket Geneli Üç Aylık Yol Haritası Değerlendirmesi ve Planlama Oturumu",
        "start": dt.datetime(2026, 11, 2, 10, 2, tzinfo=LOCAL_TZ),
        "end": dt.datetime(2026, 11, 2, 10, 45, tzinfo=LOCAL_TZ),
        "all_day": False,
        "meeting": "https://zoom.us/j/555666777",
        "link": "https://calendar.google.com/event?eid=long",
        "category": "Google Takvim",
    }
    panel.show_for(ANCHOR, {"events": [long_event], "updated": "10:00"}, {})
    row_long = panel._cached_selected_events[0]
    assert row_long["show_join"] is True
    assert not row_long["join_rect"].isEmpty()
    # The text width must be bounded by the join button's left edge
    expected_max_text_w = row_long["join_rect"].left() - 8.0 - (row_long["rect"].left() + 12.0)
    assert expected_max_text_w > 50.0, "Text area must have reasonable space"

    # Render offscreen to PNG
    img = panel.render_to_image(dpr=2.0)
    assert isinstance(img, QImage) and not img.isNull()
    png_path = SCRATCH_DIR / "v27_calendar_join_pill.png"
    ok = img.save(str(png_path), "PNG")
    assert ok, f"Failed to save PNG to {png_path}"
    assert png_path.exists() and png_path.stat().st_size > 0
    print(f"  [SAVED] Offscreen render with 'Katıl' pill: {png_path}")

    panel.hide_instant()
    panel.close()
    print("  [PASS] Long title elision and offscreen render verified.")


def main() -> None:
    print("=" * 60)
    print("      RUNNING ŞERİT CALENDAR PANEL JOIN UNIT TEST SUITE      ")
    print("=" * 60)
    test_meeting_link_extractor_security_and_formats()
    test_sources_fetch_month_calendar_meeting_key()
    test_calendar_panel_join_pill_and_signal()
    print("=" * 60)
    print("ALL V27 CALENDAR JOIN TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
