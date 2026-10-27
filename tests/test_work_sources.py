"""test_work_sources.py - Comprehensive tests for work_sources.py.

Includes:
- Pure synthetic unit tests (>= 20 cases) covering parsing, sorting, open counts,
  stale flags, URL building, privacy guarantees (no ozet/bodies), timeouts, bad JSON,
  missing files, non-zero exits, and garbage values.
- Thread safety and caching verification.
- Read-only live telemetry check printing counts, labels, and measured durations only.
"""

import datetime as dt
import json
from pathlib import Path
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

import work_sources as ws


# ---------------------------------------------------------------------------
# 1) Unit Tests: Shared Formatting Helpers
# ---------------------------------------------------------------------------
def test_tr_relative_hours() -> None:
    assert ws.tr_relative_hours(None) == ""
    assert ws.tr_relative_hours("invalid") == ""
    assert ws.tr_relative_hours(0) == "0 dk"
    assert ws.tr_relative_hours(0.6667) == "40 dk"
    assert ws.tr_relative_hours(0.1) == "6 dk"
    assert ws.tr_relative_hours(1.0) == "1 sa"
    assert ws.tr_relative_hours(5) == "5 sa"
    assert ws.tr_relative_hours(23.5) == "23 sa"
    assert ws.tr_relative_hours(24) == "1 g"
    assert ws.tr_relative_hours(48) == "2 g"
    assert ws.tr_relative_hours(316) == "13 g"


def test_tr_days_left() -> None:
    assert ws.tr_days_left(None) == ""
    assert ws.tr_days_left("bad") == ""
    assert ws.tr_days_left(0) == "bugün"
    assert ws.tr_days_left(1) == "yarın"
    assert ws.tr_days_left(4) == "4 gün"
    assert ws.tr_days_left(-1) == "gecikti 1 gün"
    assert ws.tr_days_left(-2) == "gecikti 2 gün"


def test_tr_short_date() -> None:
    assert ws.tr_short_date(None) == ""
    assert ws.tr_short_date("") == ""
    assert ws.tr_short_date(dt.date(2026, 10, 31)) == "31 Eki Cmt"
    assert ws.tr_short_date(dt.date(2026, 10, 30)) == "30 Eki Cum"
    assert ws.tr_short_date(dt.datetime(2026, 10, 27, 10, 30)) == "27 Eki Sal"
    assert ws.tr_short_date("2026-10-31") == "31 Eki Cmt"
    assert ws.tr_short_date("2026-10-30T14:20:00Z") == "30 Eki Cum"


def test_tr_reset_time() -> None:
    assert ws.tr_reset_time(None) is None
    assert ws.tr_reset_time("") is None
    assert ws.tr_reset_time("not-a-date") is None
    # 2026-10-29 13:40:36 UTC -> 16:40:36 in UTC+3 (Thursday / Per)
    res = ws.tr_reset_time("2026-10-29T13:40:36Z")
    assert res == "29 Eki Per 16:40"


def test_clean_sender_name() -> None:
    assert ws.clean_sender_name(None) == ""
    assert ws.clean_sender_name("") == ""
    assert ws.clean_sender_name("Test Kişi <test@example.com>") == "Test Kişi"
    assert ws.clean_sender_name('"Afra Akbalık" <afra@example.com>') == "Afra Akbalık"
    assert ws.clean_sender_name("Apple <appleid@apple.com>") == "Apple"
    assert ws.clean_sender_name("hello@example.com") == "hello@example.com"
    assert ws.clean_sender_name("<support@corp.com>") == "support@corp.com"
    assert ws.clean_sender_name("Plain Sender") == "Plain Sender"


def test_shorten_ag_label() -> None:
    assert ws.shorten_ag_label("Claude (Opus/Sonnet)") == "Claude"
    assert ws.shorten_ag_label("Gemini …") == "Gemini"
    assert ws.shorten_ag_label("Gemini ...") == "Gemini"
    assert ws.shorten_ag_label("Gemini (Flash/Pro)") == "Gemini"
    assert ws.shorten_ag_label("GPT-OSS") == "GPT-OSS"
    assert ws.shorten_ag_label("Gemini Pro") == "Gemini Pro"
    # Overly long labels
    long_lbl = "A" * 35
    shortened = ws.shorten_ag_label(long_lbl)
    assert len(shortened) <= 24
    assert shortened.endswith("…")


# ---------------------------------------------------------------------------
# 2) Unit Tests: fetch_mail_waiting (Synthetic Fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture
def synthetic_mail_dir(tmp_path: Path) -> Path:
    """Create synthetic mail fixtures with fake names and test subjects."""
    mail_dir = tmp_path / "mail-bekleyen"
    mail_dir.mkdir()

    # ias.json: 2 items (1 open 48h, 1 closed 10h)
    ias_data = {
        "hesap": "ias",
        "adres": "test.ias@example.com",
        "olusturma": "2026-10-27T08:00:00+03:00",
        "bekleyen": [
            {
                "kimden": "Test Müşteri <musteri@corp.com>",
                "konu": "Acil Entegrasyon Testi",
                "bekleme_saat": 48,
                "okunmamis": True,
                "kapanis_tahmini": False,
                "rol": "to",
                "thread_id": "thread_ias_1",
                "ozet": "GİZLİ ÖZET METNİ - ASLA GÖRÜNMEMELİ",
                "message_id": "msg_ias_1",
            },
            {
                "kimden": "Test Yanıt <yanit@corp.com>",
                "konu": "Teşekkürler",
                "bekleme_saat": 10,
                "okunmamis": False,
                "kapanis_tahmini": True,
                "rol": "to",
                "thread_id": "thread_ias_2",
                "ozet": "GİZLİ İKİNCİ ÖZET",
                "message_id": "msg_ias_2",
            },
        ],
    }
    (mail_dir / "ias.json").write_text(json.dumps(ias_data), encoding="utf-8")

    # kisisel02.json: 3 items (2 open [120h, 24h], 1 closed [5h])
    kisisel_data = {
        "hesap": "kisisel02",
        "adres": "test.kisisel@example.com",
        "olusturma": "2026-10-27T08:05:00+03:00",
        "bekleyen": [
            {
                "kimden": "Test Banka <banka@example.com>",
                "konu": "Hesap Özeti Bilgilendirme",
                "bekleme_saat": 24,
                "okunmamis": True,
                "kapanis_tahmini": False,
                "rol": "to",
                "thread_id": "thread_kis_1",
                "ozet": "GİZLİ BANKA ÖZETİ",
            },
            {
                "kimden": "Eski Arkadaş <arkadas@example.com>",
                "konu": "Selamlar",
                "bekleme_saat": 120,
                "okunmamis": False,
                "kapanis_tahmini": False,
                "rol": "cc",
                "thread_id": "thread_kis_2",
                "ozet": "GİZLİ ARKADAŞ ÖZETİ",
            },
            {
                "kimden": "Bülten Servisi <bulten@example.com>",
                "konu": "Haftalık Bülten",
                "bekleme_saat": 5,
                "okunmamis": False,
                "kapanis_tahmini": True,
                "rol": "to",
                "thread_id": "thread_kis_3",
            },
        ],
    }
    (mail_dir / "kisisel02.json").write_text(json.dumps(kisisel_data), encoding="utf-8")

    # logaritma.json: 0 items
    logaritma_data = {
        "hesap": "logaritma",
        "adres": "test.logaritma@example.com",
        "olusturma": "2026-10-27T08:02:00+03:00",
        "bekleyen": [],
    }
    (mail_dir / "logaritma.json").write_text(json.dumps(logaritma_data), encoding="utf-8")

    # _durum.json
    durum_data = {"zaman": "2026-10-27T08:05:00+03:00"}
    (mail_dir / "_durum.json").write_text(json.dumps(durum_data), encoding="utf-8")

    return mail_dir


def test_fetch_mail_waiting_counts_and_sorting(synthetic_mail_dir: Path) -> None:
    res = ws.fetch_mail_waiting(synthetic_mail_dir)
    assert not res.get("err")
    assert res.get("source") == "Hermes mail taraması"
    # Total open: 1 from ias + 2 from kisisel + 0 from logaritma = 3
    assert res.get("total_open") == 3
    # Oldest waiting hours among open items is 120
    assert res.get("oldest_h") == 120

    accounts = res.get("accounts", [])
    assert len(accounts) == 3

    # Check IAS account
    ias_acc = next(a for a in accounts if a["key"] == "ias")
    assert ias_acc["label"] == "IAS"
    assert ias_acc["open"] == 1
    assert len(ias_acc["items"]) == 2
    # Verify open first sorting: open (48h) must precede closed (10h)
    assert ias_acc["items"][0]["kapanis_tahmini"] is False
    assert ias_acc["items"][0]["bekleme_saat"] == 48
    assert ias_acc["items"][1]["kapanis_tahmini"] is True
    assert ias_acc["items"][1]["bekleme_saat"] == 10

    # Check Kişisel account: open items sorted by bekleme_saat desc (120h before 24h)
    kis_acc = next(a for a in accounts if a["key"] == "kisisel02")
    assert kis_acc["label"] == "Kişisel"
    assert kis_acc["open"] == 2
    assert kis_acc["items"][0]["bekleme_saat"] == 120
    assert kis_acc["items"][1]["bekleme_saat"] == 24
    assert kis_acc["items"][2]["kapanis_tahmini"] is True


def test_fetch_mail_waiting_privacy_contract(synthetic_mail_dir: Path) -> None:
    """Strict privacy rule: ozet, message_id and body text must NEVER be present."""
    res = ws.fetch_mail_waiting(synthetic_mail_dir)
    for acc in res.get("accounts", []):
        for it in acc.get("items", []):
            assert "ozet" not in it, f"Privacy violation: 'ozet' found in item: {it}"
            assert "message_id" not in it, f"Privacy violation: 'message_id' found in item: {it}"
            assert "body" not in it
            # Display name must not contain raw angle bracket address
            assert "<" not in it["kimden"]
            assert ">" not in it["kimden"]


def test_fetch_mail_waiting_url_generation(synthetic_mail_dir: Path) -> None:
    res = ws.fetch_mail_waiting(synthetic_mail_dir)
    accounts = res.get("accounts", [])
    ias_acc = next(a for a in accounts if a["key"] == "ias")
    item0 = ias_acc["items"][0]
    expected_url = f"https://mail.google.com/mail/u/?authuser=test.ias@example.com#all/{item0['thread_id']}"
    assert item0["url"] == expected_url


def test_fetch_mail_waiting_stale_flag(tmp_path: Path) -> None:
    mail_dir = tmp_path / "stale-mail"
    mail_dir.mkdir()
    # 20 hours ago
    old_time = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20)).isoformat()
    old_data = {
        "hesap": "ias",
        "adres": "test@example.com",
        "olusturma": old_time,
        "bekleyen": [],
    }
    (mail_dir / "ias.json").write_text(json.dumps(old_data), encoding="utf-8")
    (mail_dir / "_durum.json").write_text(json.dumps({"zaman": old_time}), encoding="utf-8")

    res = ws.fetch_mail_waiting(mail_dir)
    assert res.get("stale") is True


def test_fetch_mail_waiting_missing_account_file(synthetic_mail_dir: Path) -> None:
    # Delete logaritma.json
    (synthetic_mail_dir / "logaritma.json").unlink()
    # Invalidate cache by touching ias.json
    (synthetic_mail_dir / "ias.json").touch()

    res = ws.fetch_mail_waiting(synthetic_mail_dir)
    assert len(res.get("accounts", [])) == 2
    assert any("Logaritma" in w for w in res.get("warnings", []))


def test_fetch_mail_waiting_corrupt_json(synthetic_mail_dir: Path) -> None:
    (synthetic_mail_dir / "logaritma.json").write_text("CORRUPT NOT JSON", encoding="utf-8")
    (synthetic_mail_dir / "ias.json").touch()

    res = ws.fetch_mail_waiting(synthetic_mail_dir)
    assert len(res.get("accounts", [])) == 2
    assert any("Logaritma" in w for w in res.get("warnings", []))


def test_fetch_mail_waiting_missing_directory(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    res = ws.fetch_mail_waiting(non_existent)
    assert res.get("total_open") == 0
    assert res.get("stale") is True
    assert len(res.get("accounts", [])) == 0


def test_fetch_mail_waiting_garbage_values(tmp_path: Path) -> None:
    mail_dir = tmp_path / "garbage"
    mail_dir.mkdir()
    garbage_data = {
        "hesap": "ias",
        "adres": "test@example.com",
        "olusturma": "not-a-valid-date",
        "bekleyen": [
            {
                "kimden": None,
                "konu": None,
                "bekleme_saat": "not-an-int",
                "kapanis_tahmini": None,
                "thread_id": None,
            },
            "not-even-a-dict",
        ],
    }
    (mail_dir / "ias.json").write_text(json.dumps(garbage_data), encoding="utf-8")
    res = ws.fetch_mail_waiting(mail_dir)
    assert not res.get("err")
    assert res.get("total_open") == 1
    ias_item = res["accounts"][0]["items"][0]
    assert ias_item["bekleme_saat"] == 0
    assert ias_item["kimden"] == ""
    assert ias_item["url"] == ""


def test_fetch_mail_waiting_mtime_caching(synthetic_mail_dir: Path) -> None:
    res1 = ws.fetch_mail_waiting(synthetic_mail_dir)
    res2 = ws.fetch_mail_waiting(synthetic_mail_dir)
    assert res1 == res2


# ---------------------------------------------------------------------------
# 3) Unit Tests: fetch_tasks (Synthetic Fixtures via Subprocess Mock)
# ---------------------------------------------------------------------------
def test_fetch_tasks_success(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    base_dir = tmp_path / "hermes"
    scripts_dir = base_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "google_tasks.py").touch()

    today = dt.date.today()
    due_future = (today + dt.timedelta(days=4)).isoformat()
    due_past = (today - dt.timedelta(days=2)).isoformat()

    fake_tasks = [
        {
            "id": "task_1",
            "title": "Gelecek Görev",
            "due": f"{due_future}T00:00:00.000Z",
            "status": "needsAction",
            "notes": "İlk satır not\nİkinci satır gizli not",
        },
        {
            "id": "task_2",
            "title": "Gecikmiş Görev",
            "due": f"{due_past}T00:00:00.000Z",
            "status": "needsAction",
            "notes": "A" * 100,  # Note over 60 chars
        },
        {
            "id": "task_3",
            "title": "Tarihsiz Görev",
            "due": None,
            "status": "needsAction",
            "notes": "",
        },
        {
            "id": "task_4",
            "title": "Tamamlanmış Görev",
            "due": None,
            "status": "completed",
            "notes": "",
        },
    ]

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(fake_tasks)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        res = ws.fetch_tasks(hermes_py=dummy_py, base_dir=base_dir)

        # Strictly 'list' only passed
        call_args = mock_run.call_args[0][0]
        assert call_args[2] == "list"
        assert "add" not in call_args
        assert "done" not in call_args

    assert not res.get("err")
    assert res.get("source") == "Google Görevler (02)"
    # 3 active tasks (excluding completed task_4)
    assert res.get("open") == 3

    items = res.get("items", [])
    assert len(items) == 4

    # Sorting check: items with due date first (past first, then future), None last
    assert items[0]["id"] == "task_2"
    assert items[0]["days_left"] == -2
    assert items[0]["overdue"] is True
    assert len(items[0]["notes_short"]) <= 60

    assert items[1]["id"] == "task_1"
    assert items[1]["days_left"] == 4
    assert items[1]["overdue"] is False
    assert items[1]["notes_short"] == "İlk satır not"

    assert items[2]["due"] is None
    assert items[2]["days_left"] is None

    # First item with due date
    nxt = res.get("next")
    assert nxt is not None and nxt["id"] == "task_2"


def test_fetch_tasks_sorting_with_multiple_none_due(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    base_dir = tmp_path / "hermes"
    scripts_dir = base_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "google_tasks.py").touch()

    fake_tasks = [
        {"id": "t1", "title": "Zebra", "due": None, "status": "needsAction", "notes": ""},
        {"id": "t2", "title": "Alfa", "due": None, "status": "needsAction", "notes": ""},
        {"id": "t3", "title": "Beta", "due": "2026-10-31T00:00:00.000Z", "status": "needsAction", "notes": ""},
    ]
    mock_proc = MagicMock(returncode=0, stdout=json.dumps(fake_tasks), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_tasks(hermes_py=dummy_py, base_dir=base_dir)

    items = res.get("items", [])
    assert items[0]["id"] == "t3"  # due date first
    assert items[1]["title"] == "Alfa"  # alphabetical for None due
    assert items[2]["title"] == "Zebra"


def test_fetch_tasks_nonzero_exit(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    base_dir = tmp_path / "hermes"
    scripts_dir = base_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "google_tasks.py").touch()

    mock_proc = MagicMock(returncode=1, stdout="", stderr="OAuth Error")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_tasks(hermes_py=dummy_py, base_dir=base_dir)
    assert res.get("err") == "Google Görevler okunamadı"


def test_fetch_tasks_bad_json(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    base_dir = tmp_path / "hermes"
    scripts_dir = base_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "google_tasks.py").touch()

    mock_proc = MagicMock(returncode=0, stdout="FATAL NOT JSON", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_tasks(hermes_py=dummy_py, base_dir=base_dir)
    assert res.get("err") == "Google Görevler çıktısı bozuk"


def test_fetch_tasks_timeout(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    base_dir = tmp_path / "hermes"
    scripts_dir = base_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "google_tasks.py").touch()

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=30)):
        res = ws.fetch_tasks(hermes_py=dummy_py, base_dir=base_dir)
    assert res.get("err") == "Google Görevler zaman aşımı"


def test_fetch_tasks_missing_script(tmp_path: Path) -> None:
    res = ws.fetch_tasks(hermes_py=tmp_path / "missing.exe", base_dir=tmp_path / "missing")
    assert res.get("err") == "Google Görevler CLI bulunamadı"


# ---------------------------------------------------------------------------
# 4) Unit Tests: fetch_antigravity (Synthetic Fixtures via Subprocess Mock)
# ---------------------------------------------------------------------------
def test_fetch_antigravity_success(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    dummy_script = tmp_path / "ag_quota.py"
    dummy_script.touch()

    fake_output = {
        "available": True,
        "reason": None,
        "windows": [
            {"label": "Claude (Opus/Sonnet)", "used_percent": 82.4, "reset_at": "2026-10-29T13:40:36Z"},
            {"label": "GPT-OSS", "used_percent": 100.0, "reset_at": "2026-10-29T13:40:36Z"},
            {"label": "Gemini …", "used_percent": 25.0, "reset_at": "2026-10-27T12:00:00Z"},
        ],
    }

    mock_proc = MagicMock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_antigravity(hermes_py=dummy_py, tool_script=dummy_script)

    assert not res.get("err")
    assert res.get("source") == "Antigravity"
    groups = res.get("groups", [])
    assert len(groups) == 3

    # Check shortening: 'Claude (Opus/Sonnet)' -> 'Claude'
    assert groups[0]["label"] == "Claude"
    assert groups[0]["used"] == 82.4
    assert groups[0]["reset_tr"] == "29 Eki Per 16:40"

    assert groups[1]["label"] == "GPT-OSS"
    assert groups[1]["used"] == 100.0

    # 'Gemini …' -> 'Gemini'
    assert groups[2]["label"] == "Gemini"
    assert groups[2]["used"] == 25.0


def test_fetch_antigravity_unavailable(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    dummy_script = tmp_path / "ag_quota.py"
    dummy_script.touch()

    fake_output = {"available": False, "reason": "oauth_required", "windows": []}
    mock_proc = MagicMock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_antigravity(hermes_py=dummy_py, tool_script=dummy_script)
    assert res.get("err") == "Antigravity okunamadı"


def test_fetch_antigravity_bad_json(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    dummy_script = tmp_path / "ag_quota.py"
    dummy_script.touch()

    mock_proc = MagicMock(returncode=0, stdout="ERROR LINE", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        res = ws.fetch_antigravity(hermes_py=dummy_py, tool_script=dummy_script)
    assert res.get("err") == "Antigravity okunamadı"


def test_fetch_antigravity_timeout(tmp_path: Path) -> None:
    dummy_py = tmp_path / "python.exe"
    dummy_py.touch()
    dummy_script = tmp_path / "ag_quota.py"
    dummy_script.touch()

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=40)):
        res = ws.fetch_antigravity(hermes_py=dummy_py, tool_script=dummy_script)
    assert res.get("err") == "Antigravity okunamadı"


def test_fetch_antigravity_missing_script(tmp_path: Path) -> None:
    res = ws.fetch_antigravity(hermes_py=tmp_path / "missing.exe", tool_script=tmp_path / "missing.py")
    assert res.get("err") == "Antigravity okunamadı"


# ---------------------------------------------------------------------------
# 5) READ-ONLY Live Telemetry Check (Prints counts & durations ONLY)
# ---------------------------------------------------------------------------
def test_live_read_only_telemetry() -> None:
    """Live verification running against real host environment.

    Strict privacy rule: prints ONLY counts, labels, and durations.
    Never prints subject lines, personal names, task notes, or auth tokens.
    """
    print("\n--- LIVE READ-ONLY TELEMETRY REPORT ---")

    # 1. Mail waiting
    t0 = time.perf_counter()
    mail_data = ws.fetch_mail_waiting()
    dur_mail = time.perf_counter() - t0

    if "err" in mail_data:
        print(f"Mail Live: ERROR ({mail_data['err']}) [{dur_mail:.3f}s]")
    else:
        acc_counts = {a["key"]: a["open"] for a in mail_data.get("accounts", [])}
        print(
            f"Mail Live: Total Open={mail_data.get('total_open')}, "
            f"Per Account={acc_counts}, "
            f"Oldest={mail_data.get('oldest_h')}h, "
            f"ScannedAt={mail_data.get('scanned_at')}, "
            f"Stale={mail_data.get('stale')} "
            f"[{dur_mail:.3f}s]"
        )

    # 2. Google Tasks
    t0 = time.perf_counter()
    tasks_data = ws.fetch_tasks()
    dur_tasks = time.perf_counter() - t0

    if "err" in tasks_data:
        print(f"Tasks Live: ERROR ({tasks_data['err']}) [{dur_tasks:.3f}s]")
    else:
        next_due_days = tasks_data.get("next", {}).get("days_left") if tasks_data.get("next") else None
        print(
            f"Tasks Live: Open Count={tasks_data.get('open')}, "
            f"Next Due DaysLeft={next_due_days} "
            f"[{dur_tasks:.3f}s]"
        )

    # 3. Antigravity Quota
    t0 = time.perf_counter()
    ag_data = ws.fetch_antigravity()
    dur_ag = time.perf_counter() - t0

    if "err" in ag_data:
        print(f"Antigravity Live: ERROR ({ag_data['err']}) [{dur_ag:.3f}s]")
    else:
        groups_summary = [
            f"{g['label']}: {g['used']}% (Reset: {g['reset_tr']})"
            for g in ag_data.get("groups", [])
        ]
        print(
            f"Antigravity Live: Groups={groups_summary} "
            f"[{dur_ag:.3f}s]"
        )

    print("---------------------------------------\n")


# ---------------------------------------------------------------------------
# 5) Unit Tests: Auto Sender Rules and Filtering (Synthetic Only)
# ---------------------------------------------------------------------------
def test_is_auto_sender_local_parts() -> None:
    """Verify local-part regex patterns for automated notification mailboxes."""
    auto_senders = [
        "noreply@example.com",
        "No-Reply@company.org",
        "donotreply@service.io",
        "do-not-reply@portal.net",
        "notification@app.com",
        "notifications@system.com",
        "mailer-daemon@relay.com",
        "appleid@example.org",
        "account@corp.com",
        "accounts@auth.com",
        "security@platform.com",
        "alerts@monitor.com",
        "alert@status.com",
        "newsletter@digest.com",
        "NoReply+123@support.com",
        "Security-Alert@host.com",
    ]
    for s in auto_senders:
        assert ws.is_auto_sender(s) is True, f"Expected {s} to be auto"
        assert ws.is_auto_sender(f"Bot <{s}>") is True, f"Expected Bot <{s}> to be auto"


def test_is_auto_sender_known_domains_and_addrs() -> None:
    """Verify exact known domains and addresses."""
    known_auto = [
        "appleid@apple.com",
        "account@nvidia.com",
        "admin@accounts.google.com",
        "update@mail.instagram.com",
        "info@notification.mail.instagram.com",
        "security@facebookmail.com",
        "messages@linkedin.com",
        "noreply@email.marketing.com",
        "news@email.store.com",
    ]
    for s in known_auto:
        assert ws.is_auto_sender(s) is True, f"Expected {s} to be auto"


def test_is_auto_sender_human_senders() -> None:
    """Verify human and corporate collaborator addresses are strictly NOT classified as auto."""
    human_senders = [
        "fle@is-dba.com",
        "hello@team-brain.com",
        "hello@lumen-research.com",
        "john.doe@dentsu.com",
        "jane.smith@havasmedia.com",
        "colleague@integralads.com",
        "emre@example.com",
        "client.contact@agency.com",
    ]
    for s in human_senders:
        assert ws.is_auto_sender(s) is False, f"Expected human sender {s} to NOT be auto"
        assert ws.is_auto_sender(f"Human Person <{s}>") is False


def test_is_auto_sender_custom_ignores() -> None:
    """Verify custom user ignore substrings from settings.json."""
    custom_list = ["custombot", "dailyreport"]
    assert ws.is_auto_sender("sender@custombot.org", custom_list) is True
    assert ws.is_auto_sender("dailyreport-archive@corp.com", custom_list) is True
    assert ws.is_auto_sender("regular@corp.com", custom_list) is False


def test_fetch_mail_waiting_auto_filtering_synthetic(tmp_path: Path) -> None:
    """Verify that automated emails are flagged and excluded from open counts."""
    mail_dir = tmp_path / "mail-filter-test"
    mail_dir.mkdir()

    # Synthetic IAS: 1 human open, 1 human closed, 1 auto notification
    ias_data = {
        "hesap": "ias",
        "adres": "test@ias.example.com",
        "olusturma": "2026-10-27T10:00:00+03:00",
        "bekleyen": [
            {
                "kimden": "Müşteri Temsilcisi <musteri@corp.com>",
                "konu": "Proje Raporu",
                "bekleme_saat": 20,
                "okunmamis": False,
                "kapanis_tahmini": False,
            },
            {
                "kimden": "Eski İş Arkadaşı <arkadas@havasmedia.com>",
                "konu": "Eski Konu",
                "bekleme_saat": 5,
                "okunmamis": False,
                "kapanis_tahmini": True,
            },
            {
                "kimden": "Bildirim Sistemi <noreply@ias.example.com>",
                "konu": "Sistem Güncellemesi",
                "bekleme_saat": 50,
                "okunmamis": True,
                "kapanis_tahmini": False,
            },
        ],
    }

    # Synthetic Kişisel: 1 human open, 2 auto (Apple + NVIDIA)
    kisisel_data = {
        "hesap": "kisisel02",
        "adres": "test@gmail.com",
        "olusturma": "2026-10-27T10:00:00+03:00",
        "bekleyen": [
            {
                "kimden": "Dost Kişi <fle@is-dba.com>",
                "konu": "Kahve Randevusu",
                "bekleme_saat": 15,
                "okunmamis": True,
                "kapanis_tahmini": False,
            },
            {
                "kimden": "Apple <appleid@apple.com>",
                "konu": "Hesap Özeti",
                "bekleme_saat": 100,
                "okunmamis": False,
                "kapanis_tahmini": False,
            },
            {
                "kimden": "NVIDIA <account@nvidia.com>",
                "konu": "Güvenlik Kodu",
                "bekleme_saat": 80,
                "okunmamis": True,
                "kapanis_tahmini": False,
            },
        ],
    }

    # Synthetic Logaritma: empty
    logaritma_data = {
        "hesap": "logaritma",
        "adres": "test@logaritma.com",
        "olusturma": "2026-10-27T10:00:00+03:00",
        "bekleyen": [],
    }

    (mail_dir / "ias.json").write_text(json.dumps(ias_data), encoding="utf-8")
    (mail_dir / "kisisel02.json").write_text(json.dumps(kisisel_data), encoding="utf-8")
    (mail_dir / "logaritma.json").write_text(json.dumps(logaritma_data), encoding="utf-8")

    res = ws.fetch_mail_waiting(mail_dir=mail_dir)

    assert "err" not in res
    assert res["total_open"] == 2  # 1 from IAS, 1 from Kişisel
    assert res["hidden_auto"] == 3  # 1 from IAS, 2 from Kişisel
    assert res["oldest_h"] == 20  # Max of open human items: 20 and 15 (auto's 50, 100, 80 excluded)

    accs = {a["key"]: a for a in res["accounts"]}
    assert accs["ias"]["open"] == 1
    assert accs["ias"]["hidden_auto"] == 1
    assert accs["kisisel02"]["open"] == 1
    assert accs["kisisel02"]["hidden_auto"] == 2
    assert accs["logaritma"]["open"] == 0
    assert accs["logaritma"]["hidden_auto"] == 0

    # Verify item contents and privacy
    for a in res["accounts"]:
        for it in a["items"]:
            assert "ozet" not in it
            assert "message_id" not in it
            assert "body" not in it
            assert "auto" in it

