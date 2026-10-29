"""test_v24_argon.py - Gemini 4 Argon kotası (Antigravity yerel dil sunucusu).

Sıfır yan etki: gerçek Antigravity'ye bağlanılmaz (okuyucu/sunucu listesi sahte), önbellek geçici klasörde.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

import ag_local  # noqa: E402
import logpath  # noqa: E402
import work_sources as ws  # noqa: E402

NOW = dt.datetime(2026, 10, 29, 10, 30, tzinfo=dt.timezone.utc)

# GetUserStatus yanıtının sade örneği (29 Eki 2026 canlı yapıya göre; değerler örnek)
SAMPLE = {"userStatus": {"cascadeModelConfigData": {"clientModelConfigs": [
    {"label": "Gemini 3.8 Flash (Medium)", "modelOrAlias": {"model": "MODEL_PLACEHOLDER_M319"},
     "quotaInfo": {"remainingFraction": 0.5, "resetTime": "2026-10-29T16:10:57Z"}},
    {"label": "Claude Opus 5.5 (High)", "modelOrAlias": {"model": "MODEL_PLACEHOLDER_M402"},
     "quotaInfo": {"resetTime": "2026-10-29T13:40:36Z"}},
    {"label": "Gemini 4 Argon (Medium)", "modelOrAlias": {"model": "MODEL_PLACEHOLDER_M418"},
     "quotaInfo": {"remainingFraction": 0.25, "resetTime": "2026-11-02T14:16:53Z"}},
    {"label": "Gemini 4 Argon (High)", "modelOrAlias": {"model": "MODEL_PLACEHOLDER_M417"},
     "quotaInfo": {"remainingFraction": 0.25, "resetTime": "2026-11-02T14:16:53Z"}},
]}}}


def test_parse_argon_only_argon_rows() -> None:
    res = ag_local.parse_argon(SAMPLE)
    assert res == {"used": 75.0, "reset_at": "2026-11-02T14:16:53Z"}, res
    assert ag_local.parse_argon({"x": [{"label": "Gemini 3.8 Flash", "quotaInfo": {"remainingFraction": 1}}]}) is None
    # hakkı biten model: remainingFraction yok, yalnız resetTime -> %100
    full = {"a": [{"label": "Gemini 4 Argon (Low)", "quotaInfo": {"resetTime": "2026-11-02T14:16:53Z"}}]}
    assert ag_local.parse_argon(full)["used"] == 100.0


def test_read_argon_uses_only_localhost_and_keeps_token_in_memory() -> None:
    calls = []

    def fake_post(url, csrf, timeout):
        calls.append((url, csrf))
        if url.startswith("https://127.0.0.1:5001/"):
            return SAMPLE
        raise OSError("bağlantı yok")

    servers = lambda: [{"csrf": "ORNEK-ANAHTAR", "ports": [5000, 5001]}]  # noqa: E731
    with patch.object(ag_local, "_post", side_effect=fake_post):
        res = ag_local.read_argon(servers=servers)
    assert res and res["used"] == 75.0
    assert all(u.startswith(("https://127.0.0.1:", "http://127.0.0.1:")) for u, _ in calls), calls
    assert all(c == "ORNEK-ANAHTAR" for _, c in calls)
    with patch.object(ag_local, "_post", side_effect=OSError("kapalı")):
        assert ag_local.read_argon(servers=servers) is None
    assert ag_local.read_argon(servers=lambda: []) is None


def test_fetch_argon_live_cache_and_reset() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="serit_argon_")) / "ag_argon_cache.json"
    live = ag_local.fetch_argon(now=NOW, reader=lambda: {"used": 98.3, "reset_at": "2026-11-02T14:16:53Z"},
                                cache_path=tmp)
    assert live == {"label": "Argon", "used": 98.3, "reset_at": "2026-11-02T14:16:53Z", "stale": False}
    saved = json.loads(tmp.read_text(encoding="utf-8"))
    assert set(saved) == {"used", "reset_at", "read_at"}, saved   # anahtar/hesap bilgisi yok
    # Antigravity kapalı -> son okuma
    off = ag_local.fetch_argon(now=NOW, reader=lambda: None, cache_path=tmp)
    assert off == {"label": "Argon · son okuma", "used": 98.3, "reset_at": "2026-11-02T14:16:53Z", "stale": True}
    # sıfırlanma saati geçti -> kota yenilendi sayılır
    later = ag_local.fetch_argon(now=dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc), reader=lambda: None,
                                 cache_path=tmp)
    assert later["used"] == 0.0 and later["reset_at"] is None and later["stale"]
    # hiç okuma yoksa satır yok (uydurma veri yok)
    assert ag_local.fetch_argon(now=NOW, reader=lambda: None, cache_path=tmp.with_name("yok.json")) is None


def test_cache_path_never_real_under_test() -> None:
    p = logpath.get_cache_file("ag_argon_cache.json")
    assert p.parent != Path("D:/Apps/serit"), p


def test_fetch_antigravity_appends_argon_group() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="serit_argon_ws_"))
    py, script = tmp / "python.exe", tmp / "ag_quota.py"
    py.touch()
    script.touch()
    out = {"available": True, "reason": None, "windows": [
        {"label": "Claude (Opus/Sonnet)", "used_percent": 100.0, "reset_at": "2026-10-29T13:40:36Z"}]}
    proc = MagicMock(returncode=0, stdout=json.dumps(out), stderr="")
    argon = {"label": "Argon", "used": 98.3, "reset_at": "2026-11-02T14:16:53Z", "stale": False}
    with patch("subprocess.run", return_value=proc), patch.object(ag_local, "fetch_argon", return_value=argon):
        res = ws.fetch_antigravity(hermes_py=py, tool_script=script, local_argon=True)
        assert [g["label"] for g in res["groups"]] == ["Claude", "Argon"]
        g = res["groups"][1]
        assert g["used"] == 98.3 and g["reset_tr"] == "2 Kas Pzt 17:16" and g["stale"] is False
        # testlerde varsayılan kapalı (eski fikstürler değişmez)
        res2 = ws.fetch_antigravity(hermes_py=py, tool_script=script)
        assert [g["label"] for g in res2["groups"]] == ["Claude"]
    with patch("subprocess.run", return_value=proc), patch.object(ag_local, "fetch_argon", return_value=None):
        res3 = ws.fetch_antigravity(hermes_py=py, tool_script=script, local_argon=True)
        assert [g["label"] for g in res3["groups"]] == ["Claude"]


def test_argon_row_in_panel_is_blue() -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import info_panels
    import panel_style as ps
    assert info_panels.quota_identity_color("Argon").name() == ps.ACCENT.name()
    assert info_panels.quota_identity_color("Argon · son okuma").name() == ps.ACCENT.name()
    w = info_panels.QuotaPanel()
    w.set_data({"groups": [{"label": "Claude", "used": 100.0, "reset_at": None},
                           {"label": "Argon", "used": 98.3, "reset_at": None}], "fetched_at": NOW.isoformat()})
    rows = {r["label"]: r for r in w._rows}
    assert rows["Argon"]["color"].name() == ps.ACCENT.name()
    assert rows["Argon"]["pct_color"].name() == ps.DANGER.name() and rows["Argon"]["pct_text"] == "%98"


def run_all() -> None:
    for fn in (test_parse_argon_only_argon_rows, test_read_argon_uses_only_localhost_and_keeps_token_in_memory,
               test_fetch_argon_live_cache_and_reset, test_cache_path_never_real_under_test,
               test_fetch_antigravity_appends_argon_group, test_argon_row_in_panel_is_blue):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_ARGON TESTS PASSED")


if __name__ == "__main__":
    run_all()
