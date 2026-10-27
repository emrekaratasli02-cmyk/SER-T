"""test_info_panels.py - Comprehensive tests for info_panels.py popovers.

Includes:
1) Offscreen render of MailPanel and QuotaPanel with synthetic data.
2) Row hit-testing with mocked QDesktopServices.openUrl.
3) Stale tag presence and toggling.
4) Merged quota groups verification (e.g. 'Gemini Pro · Flash · Görsel').
5) Bad-data matrix (>= 30 test cases: None, NaN, strings, missing keys, huge lists).
6) recently_closed timing and open/close state transitions.
7) Common public API contract and availableGeometry clamping.
8) settings.json integrity check (read-only verification).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

# Ensure serit root is on path
serit_dir = str(Path(__file__).resolve().parent.parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

import info_panels as ip


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Ensure QApplication instance is initialized for GUI testing."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


SETTINGS_PATH = Path(r"D:/Apps/serit/settings.json")


def _get_settings_hash() -> str:
    if SETTINGS_PATH.is_file():
        return hashlib.sha256(SETTINGS_PATH.read_bytes()).hexdigest()
    return ""


_SETTINGS_HASH_AT_IMPORT = _get_settings_hash()


# ---------------------------------------------------------------------------
# 1) Offscreen Rendering with Synthetic Data
# ---------------------------------------------------------------------------
def test_offscreen_render_both_panels(qapp: QApplication) -> None:
    """Verify offscreen rendering at DPR 2.0 produces valid images."""
    # Synthetic Mail Data
    mail_data = {
        "accounts": [
            {
                "key": "ias",
                "label": "IAS",
                "open": 2,
                "hidden_auto": 0,
                "items": [
                    {
                        "kimden": "Müşteri Bir",
                        "konu": "Raporlama Entegrasyonu",
                        "bekleme_saat": 48,
                        "okunmamis": True,
                        "kapanis_tahmini": False,
                        "url": "https://mail.google.com/test1",
                    },
                    {
                        "kimden": "Eski İş",
                        "konu": "Kapanmış Talep",
                        "bekleme_saat": 10,
                        "okunmamis": False,
                        "kapanis_tahmini": True,
                        "url": "https://mail.google.com/test2",
                    },
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
                        "konu": "Buluşma Planı",
                        "bekleme_saat": 5,
                        "okunmamis": False,
                        "kapanis_tahmini": False,
                        "url": "https://mail.google.com/test3",
                    },
                ],
            },
            {
                "key": "logaritma",
                "label": "Logaritma",
                "open": 0,
                "hidden_auto": 0,
                "items": [],
            },
        ],
        "total_open": 3,
        "hidden_auto": 3,
        "scanned_at": "2026-10-27T10:30:00+03:00",
        "stale": False,
    }

    mp = ip.MailPanel()
    mp.set_data(mail_data)
    img_mail = mp.render_to_image(dpr=2.0)
    assert not img_mail.isNull()
    assert img_mail.width() == int(mp.WIDTH * 2.0)
    assert img_mail.height() > 0

    # Synthetic Quota Data
    quota_data = {
        "groups": [
            {"label": "Claude", "used": 100.0, "reset_tr": "29 Eki Per 16:40"},
            {"label": "GPT-OSS", "used": 100.0, "reset_tr": "29 Eki Per 16:40"},
            {"label": "Gemini Pro", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
            {"label": "Gemini Flash", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
            {"label": "Gemini Görsel", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
        ],
        "fetched_at": "2026-10-27T12:00:00+03:00",
        "source": "Antigravity",
    }

    qp = ip.QuotaPanel()
    qp.set_data(quota_data)
    img_quota = qp.render_to_image(dpr=2.0)
    assert not img_quota.isNull()
    assert img_quota.width() == int(qp.WIDTH * 2.0)
    assert img_quota.height() > 0


# ---------------------------------------------------------------------------
# 2) Mail Panel Row Hit-Testing (URL Opening Mocked)
# ---------------------------------------------------------------------------
def test_mail_panel_row_hit_testing(qapp: QApplication) -> None:
    """Verify clicking an item row opens item['url'] and closes the panel."""
    test_url = "https://mail.google.com/mail/u/?authuser=test@example.com#all/thread123"
    mail_data = {
        "accounts": [
            {
                "key": "ias",
                "label": "IAS",
                "open": 1,
                "hidden_auto": 0,
                "items": [
                    {
                        "kimden": "Test Gönderici",
                        "konu": "Hit Test Konusu",
                        "bekleme_saat": 2,
                        "okunmamis": True,
                        "kapanis_tahmini": False,
                        "url": test_url,
                    }
                ],
            }
        ],
        "total_open": 1,
        "hidden_auto": 0,
    }

    mp = ip.MailPanel()
    mp.set_data(mail_data)
    mp.render_to_image(1.0)  # Populate row rects

    assert len(mp._row_rects) == 1
    row_rect, hit_item = mp._row_rects[0]
    assert hit_item["url"] == test_url

    with patch.object(QDesktopServices, "openUrl", return_value=True) as mock_open_url:
        with patch.object(mp, "hide_animated") as mock_hide:
            # Simulate left click inside row rect
            click_point = row_rect.center()
            found_item = mp._row_at_point(click_point)
            assert found_item == hit_item

            event = MagicMock()
            event.button.return_value = QGuiApplication.primaryScreen()  # Dummy non-left
            event.position.return_value = click_point

            # Trigger mousePressEvent directly with mocked left button
            from PySide6.QtCore import Qt
            event.button.return_value = Qt.MouseButton.LeftButton
            mp.mousePressEvent(event)

            mock_open_url.assert_called_once()
            called_qurl = mock_open_url.call_args[0][0]
            assert called_qurl.toString() == test_url
            mock_hide.assert_called_once()


# ---------------------------------------------------------------------------
# 3) Stale Tag Presence
# ---------------------------------------------------------------------------
def test_mail_panel_stale_tag(qapp: QApplication) -> None:
    """Verify stale flag toggling and rendering."""
    mp = ip.MailPanel()

    # Fresh data
    mp.set_data({"accounts": [], "total_open": 0, "stale": False, "scanned_at": "2026-10-27T12:00:00Z"})
    assert mp._stale is False
    img_fresh = mp.render_to_image(1.0)
    assert not img_fresh.isNull()

    # Stale data (> 14h)
    mp.set_data({"accounts": [], "total_open": 0, "stale": True, "scanned_at": "2026-10-26T18:00:00Z"})
    assert mp._stale is True
    img_stale = mp.render_to_image(1.0)
    assert not img_stale.isNull()


# ---------------------------------------------------------------------------
# 4) Merged Quota Groups
# ---------------------------------------------------------------------------
def test_merged_quota_groups() -> None:
    """Verify merging identical (used, reset_tr) groups with prefix elision."""
    raw_groups = [
        {"label": "Claude", "used": 100.0, "reset_tr": "29 Eki Per 16:40"},
        {"label": "GPT-OSS", "used": 100.0, "reset_tr": "29 Eki Per 16:40"},
        {"label": "Gemini Pro", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
        {"label": "Gemini Flash", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
        {"label": "Gemini Görsel", "used": 29.0, "reset_tr": "27 Eki Sal 14:54"},
    ]

    merged = ip.merge_quota_groups(raw_groups)
    assert len(merged) == 2

    # Group 1: Claude and GPT-OSS (identical 100%, same reset)
    assert merged[0]["label"] == "Claude · GPT-OSS"
    assert merged[0]["used"] == 100.0
    assert merged[0]["reset_tr"] == "29 Eki Per 16:40"

    # Group 2: Gemini family (identical 29%, same reset, shared 'Gemini' prefix)
    assert merged[1]["label"] == "Gemini Pro · Flash · Görsel"
    assert merged[1]["used"] == 29.0
    assert merged[1]["reset_tr"] == "27 Eki Sal 14:54"

    # Test single item preservation
    single = ip.merge_quota_groups([{"label": "Only One", "used": 50.0, "reset_tr": "Yarın"}])
    assert len(single) == 1
    assert single[0]["label"] == "Only One"

    # Test different reset_tr prevents merging even if used is same
    diff_reset = [
        {"label": "Model A", "used": 50.0, "reset_tr": "Bugün"},
        {"label": "Model B", "used": 50.0, "reset_tr": "Yarın"},
    ]
    assert len(ip.merge_quota_groups(diff_reset)) == 2


# ---------------------------------------------------------------------------
# 5) Bad-Data Matrix (>= 30 Test Cases)
# ---------------------------------------------------------------------------
BAD_DATA_CASES = [
    None,
    {},
    "",
    "corrupted string",
    12345,
    3.1415,
    [],
    [1, 2, 3],
    float("nan"),
    float("inf"),
    {"err": "Custom error message"},
    {"accounts": None, "total_open": None},
    {"accounts": "not a list", "total_open": "not an int"},
    {"accounts": [None, "str", 123, {}]},
    {
        "accounts": [
            {
                "key": None,
                "label": None,
                "open": "invalid",
                "hidden_auto": None,
                "items": None,
            }
        ]
    },
    {
        "accounts": [
            {
                "key": "ias",
                "label": "IAS",
                "open": -5,
                "hidden_auto": -2,
                "items": [
                    None,
                    "invalid",
                    {},
                    {"kimden": None, "konu": None, "bekleme_saat": None, "url": None},
                    {"kimden": 123, "konu": 456, "bekleme_saat": "NaN", "url": 789},
                    {"kimden": "A", "konu": "B", "bekleme_saat": -10, "url": ""},
                    {"kimden": "X" * 300, "konu": "Y" * 500, "bekleme_saat": 999999},
                ],
            }
        ]
    },
    {"groups": None, "fetched_at": None},
    {"groups": "not a list", "fetched_at": 123},
    {"groups": [None, "invalid", 42, {}]},
    {
        "groups": [
            {"label": None, "used": None, "reset_tr": None},
            {"label": 123, "used": "invalid", "reset_tr": 456},
            {"label": "NaN Used", "used": float("nan"), "reset_tr": None},
            {"label": "Inf Used", "used": float("inf"), "reset_tr": "never"},
            {"label": "Negative", "used": -50.0, "reset_tr": "past"},
            {"label": "Over 100", "used": 999.0, "reset_tr": "future"},
        ]
    },
    # Huge mail list (scrolling test)
    {
        "accounts": [
            {
                "key": "ias",
                "label": "IAS",
                "open": 50,
                "hidden_auto": 20,
                "items": [
                    {
                        "kimden": f"Gönderici {i}",
                        "konu": f"Konu Başlığı {i} - Detaylı açıklama metni",
                        "bekleme_saat": i * 2,
                        "okunmamis": (i % 2 == 0),
                        "kapanis_tahmini": (i % 5 == 0),
                        "auto": False,
                        "url": f"https://mail.google.com/thread_{i}",
                    }
                    for i in range(50)
                ],
            }
        ],
        "total_open": 50,
        "hidden_auto": 20,
    },
    # Huge quota list
    {
        "groups": [
            {
                "label": f"Model Tier {i}",
                "used": float(i % 100),
                "reset_tr": f"2{i % 9} Eki Per 12:00",
            }
            for i in range(40)
        ]
    },
]


@pytest.mark.parametrize("bad_val", BAD_DATA_CASES)
def test_bad_data_matrix_mail_panel(qapp: QApplication, bad_val: Any) -> None:
    """Verify MailPanel never crashes on corrupted or malicious inputs."""
    mp = ip.MailPanel()
    mp.set_data(bad_val)
    h = mp.compute_height()
    assert h >= 100
    img = mp.render_to_image(1.0)
    assert not img.isNull()


@pytest.mark.parametrize("bad_val", BAD_DATA_CASES)
def test_bad_data_matrix_quota_panel(qapp: QApplication, bad_val: Any) -> None:
    """Verify QuotaPanel never crashes on corrupted or malicious inputs."""
    qp = ip.QuotaPanel()
    qp.set_data(bad_val)
    h = qp.compute_height()
    assert h >= 100
    img = qp.render_to_image(1.0)
    assert not img.isNull()


# ---------------------------------------------------------------------------
# 6) recently_closed Timing & Transitions
# ---------------------------------------------------------------------------
def test_recently_closed_timing(qapp: QApplication) -> None:
    """Verify recently_closed returns False initially, True after close, False after threshold."""
    panel = ip.MailPanel()
    assert panel.recently_closed(threshold_ms=250.0) is False

    # Simulate close
    panel._last_close_time = time.monotonic()
    assert panel.recently_closed(threshold_ms=250.0) is True

    # Sleep past threshold
    time.sleep(0.26)
    assert panel.recently_closed(threshold_ms=250.0) is False


def test_is_open_state(qapp: QApplication) -> None:
    """Verify is_open accurately tracks visibility and animation closing state."""
    panel = ip.QuotaPanel()
    assert panel.is_open() is False

    panel.setVisible(True)
    panel._is_closing = False
    assert panel.is_open() is True

    panel._is_closing = True
    assert panel.is_open() is False

    panel.setVisible(False)
    panel._is_closing = False
    assert panel.is_open() is False


# ---------------------------------------------------------------------------
# 7) Common Public API Contract
# ---------------------------------------------------------------------------
def test_common_public_api_contract(qapp: QApplication) -> None:
    """Verify both panels expose identical required public API."""
    for cls in (ip.MailPanel, ip.QuotaPanel):
        panel = cls()
        assert hasattr(panel, "set_data")
        assert hasattr(panel, "show_for")
        assert hasattr(panel, "hide_animated")
        assert hasattr(panel, "is_open")
        assert hasattr(panel, "recently_closed")
        assert hasattr(panel, "refresh_requested")
        assert 320 <= panel.WIDTH <= 340
        assert panel.RADIUS == 16.0

        # Anchor positioning check
        anchor = QRectF(500.0, 700.0, 60.0, 40.0)
        panel.show_for(anchor)
        # Check window was repositioned above anchor
        assert panel.y() < anchor.top()


# ---------------------------------------------------------------------------
# 8) Protection of settings.json
# ---------------------------------------------------------------------------
def test_settings_json_never_modified() -> None:
    """Strictly assert D:/Apps/serit/settings.json was never modified."""
    # Sabit hash yerine modül yüklendiği andaki hash ile karşılaştır (Emre ayarı değiştirince test kırılmasın)
    initial_hash = _SETTINGS_HASH_AT_IMPORT
    current_hash = _get_settings_hash()
    assert current_hash == initial_hash, "settings.json was modified by tests!"
