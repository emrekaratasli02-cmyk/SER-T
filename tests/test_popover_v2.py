"""Comprehensive unit tests and high-DPI visual snapshot verification for PopoverV2.

Tests:
1. Content builders (claude, sys, wx, fx, error, stale, top_processes).
2. K4 window coordination and recently_closed debounce logic.
3. Refresh button hit testing, micro-interaction state, and on_refresh callback.
4. Renders DPR 2.0 offscreen snapshots to scratch directory for visual inspection.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

# Ensure serit directory is in Python path
serit_dir = str(Path(__file__).resolve().parent.parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

from PySide6.QtCore import QPointF, QRect
from PySide6.QtWidgets import QApplication

from popover_v2 import (
    PopoverV2,
    build_claude_content,
    build_fx_content,
    build_sys_content,
    build_wx_content,
    top_processes,
)
import panel_style

REF_DIR = Path(__file__).resolve().parent.parent / "_ref"
SCRATCH_DIR = REF_DIR / "tmp"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def get_qapp() -> QApplication:
    """Acquire existing QApplication or create headless instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_top_processes():
    """Verify top_processes helper filters system processes and sorts by MB."""
    procs = top_processes(n=3)
    assert isinstance(procs, list), "top_processes must return a list"
    assert len(procs) <= 3, "top_processes must return at most n items"

    skip = {"system idle process", "system", "svchost.exe", "registry", "memory compression"}
    for p in procs:
        assert "name" in p and "mb" in p
        assert p["name"].lower() not in skip
        assert p["mb"] >= 0.0

    if len(procs) >= 2:
        assert procs[0]["mb"] >= procs[1]["mb"], "top_processes must be sorted descending"

    print("✓ top_processes test passed.")


def test_content_builders():
    """Verify all kind content builders construct conforming sectioned schemas."""
    # 1. Claude Builder
    claude_data = {
        "plan": "Max",
        "session": 72.0,
        "session_reset": "2026-10-26T19:30:00Z",
        "week": 14.0,
        "week_reset": "2026-10-31T06:00:00Z",
        "opus": 8.0,
        "source": "Anthropic · Claude Code girişi",
        "fetched_at": time.time(),
    }
    c_res = build_claude_content(claude_data)
    assert c_res["title"] == "Claude"
    assert c_res["badge"] == "Max"
    assert len(c_res["sections"]) == 1
    assert c_res["sections"][0]["title"] == "KULLANIM"
    assert len(c_res["sections"][0]["rows"]) == 3
    assert "Claude Code girişinden okunur" in c_res["footer_note"]

    # 2. Sys Builder
    sys_data = {
        "cpu": 24.0,
        "ram": 68.5,
        "ram_used_gb": 10.96,
        "ram_total_gb": 16.0,
        "disk_c": 32.0,
        "top": [{"name": "chrome.exe", "mb": 2048.5}, {"name": "claude.exe", "mb": 650.0}],
        "source": "Bu bilgisayar",
        "fetched_at": time.time(),
    }
    s_res = build_sys_content(sys_data)
    assert s_res["title"] == "Sistem"
    assert len(s_res["sections"]) == 2
    assert s_res["sections"][0]["title"] == "SİSTEM"
    assert s_res["sections"][1]["title"] == "EN ÇOK BELLEK"
    assert len(s_res["sections"][1]["rows"]) == 2

    # 3. Wx Builder
    wx_data = {
        "temp": 19.5,
        "feel": 18.0,
        "desc": "Parçalı bulutlu",
        "icon": "partly",
        "min": 11.0,
        "max": 22.0,
        "wind": 12.5,
        "city": "Aksaray",
        "source": "open-meteo.com",
        "fetched_at": time.time(),
    }
    w_res = build_wx_content(wx_data)
    assert "Hava Durumu" in w_res["title"]
    assert "hero" in w_res
    assert w_res["hero"]["desc"] == "Parçalı bulutlu"
    assert len(w_res["sections"][0]["rows"]) == 3

    # 4. Fx Builder
    fx_data = {
        "usd": 34.25,
        "usd_chg": 0.14,
        "eur": 37.10,
        "eur_chg": -0.22,
        "gold": 3012.0,
        "gold_chg": 0.45,
        "updated": "2026-10-26 16:30:00",
        "source": "finans.truncgil.com",
        "fetched_at": time.time(),
    }
    f_res = build_fx_content(fx_data)
    assert f_res["title"] == "Piyasa"
    assert len(f_res["sections"][0]["rows"]) == 3
    assert "%+0,14" in f_res["sections"][0]["rows"][0]["chg"]

    # 5. Stale & Error Builders
    stale_claude = dict(claude_data, stale=True)
    c_stale_res = build_claude_content(stale_claude)
    assert c_stale_res["stale"] is True
    assert "önbellek" in c_stale_res["footer_note"]

    err_claude = {
        "err": "Claude Code girişi yok",
        "session": 72.0,
        "week": 14.0,
        "plan": "Max",
    }
    c_err_res = build_claude_content(err_claude)
    assert c_err_res["badge"] == "Hata"
    assert c_err_res["error"] == "Claude Code girişi yok"
    # Even in error state, preserved rows exist for dimmed display
    assert len(c_err_res["sections"]) == 1

    print("✓ Content builders test passed.")


def test_refresh_button_and_callbacks():
    """Verify refresh button hit testing, visual states, and callback dispatch."""
    _app = get_qapp()

    refreshed_kinds = []

    def on_refresh_handler(kind: str):
        refreshed_kinds.append(kind)

    popover = PopoverV2(on_refresh=on_refresh_handler)
    anchor = QRect(200, 800, 80, 40)

    # Show popover
    popover.show_for("claude", anchor, {"plan": "Max", "session": 50.0, "week": 20.0})
    _app.processEvents()

    btn_rect = popover.refresh_button_rect()
    assert btn_rect.isValid()
    assert btn_rect.width() >= 44.0
    assert btn_rect.height() >= 20.0

    # Hit testing inside button
    center_btn = btn_rect.center()
    assert popover.is_refresh_hit(center_btn) is True

    # Hit testing outside button
    top_left = QPointF(10.0, 10.0)
    assert popover.is_refresh_hit(top_left) is False

    # Trigger refresh
    assert popover._refresh_spinning is False
    popover.trigger_refresh()
    assert len(refreshed_kinds) == 1
    assert refreshed_kinds[0] == "claude"
    assert popover._refresh_spinning is True

    print("✓ Refresh button and callback test passed.")


def test_k4_logic():
    """Verify PopoverV2 is_open and recently_closed debounce mechanics."""
    _app = get_qapp()
    popover = PopoverV2()
    anchor = QRect(200, 800, 80, 40)

    assert popover.is_open() is False
    assert popover.recently_closed() is False

    popover.show_for("sys", anchor, {"cpu": 20.0, "ram": 50.0, "disk_c": 30.0})
    _app.processEvents()

    assert popover.is_open() is True
    assert popover.is_open("sys") is True
    assert popover.is_open("claude") is False

    # Simulate close
    popover.hide_animated()
    assert popover._is_closing is True
    assert popover.recently_closed(kind="sys", threshold_ms=1000.0) is True
    assert popover.recently_closed(kind="claude", threshold_ms=1000.0) is False

    print("✓ K4 logic test passed.")


def render_all_snapshots():
    """Render every kind + stale + error to DPR 2.0 PNGs using static stub data only."""
    _app = get_qapp()
    popover = PopoverV2()
    anchor = QRect(400, 900, 100, 48)

    claude_data = {
        "plan": "Max 5x",
        "session": 77.0,
        "session_reset": "2026-10-26T19:30:00Z",
        "week": 11.0,
        "week_reset": "2026-10-31T06:00:00Z",
        "source": "Anthropic · Claude Code girişi",
        "fetched_at": time.time(),
    }
    sys_data = {
        "cpu": 28.0,
        "ram": 74.0,
        "ram_used_gb": 9.6,
        "ram_total_gb": 15.7,
        "disk_c": 27.0,
        "cpu_name": "Core 5 210H",
        "disk_free_gb": 748.0,
        "top": [
            {"name": "chrome.exe", "mb": 3501.5},
            {"name": "Hermes.exe", "mb": 1509.5},
            {"name": "MemCompression", "mb": 939.5},
        ],
        "fetched_at": time.time(),
    }
    wx_data = {
        "temp": 19.5,
        "feel": 18.0,
        "desc": "Parçalı bulutlu",
        "icon": "partly",
        "min": 11.0,
        "max": 22.0,
        "wind": 12.5,
        "city": "Aksaray",
        "source": "open-meteo.com",
        "fetched_at": time.time(),
    }
    fx_data = {
        "usd": 34.25,
        "usd_chg": 0.14,
        "eur": 37.10,
        "eur_chg": -0.22,
        "gold": 3012.0,
        "gold_chg": 0.45,
        "updated": "2026-10-26 16:30:00",
        "source": "finans.truncgil.com",
        "fetched_at": time.time(),
    }

    snapshots = [
        ("pv2_claude.png", "claude", claude_data),
        ("pv2_claude_stale.png", "claude", dict(claude_data, stale=True)),
        ("pv2_claude_error.png", "claude", dict(claude_data, err="Claude Code girişi yok")),
        ("pv2_sys.png", "sys", sys_data),
        ("pv2_sys_error.png", "sys", dict(sys_data, err="psutil telemetrisi alınamadı")),
        ("pv2_wx.png", "wx", wx_data),
        ("pv2_fx.png", "fx", fx_data),
    ]
    for fname, kind, data in snapshots:
        popover.show_for(kind, anchor, data)
        _app.processEvents()
        img = popover.render_to_image(dpr=2.0)
        path = SCRATCH_DIR / fname
        img.save(str(path))
        print(f"Saved {path} ({img.width()}x{img.height()})")

    # Refresh Button Spinning / Pressed Micro-state
    popover.show_for("claude", anchor, claude_data)
    popover._refresh_spinning = True
    popover._spin_angle = 120.0
    popover._refresh_hovered = True
    popover._refresh_pressed = True
    _app.processEvents()
    img_spinning = popover.render_to_image(dpr=2.0)
    p_spinning = SCRATCH_DIR / "pv2_refresh_spinning.png"
    img_spinning.save(str(p_spinning))
    print(f"Saved {p_spinning}")

    print("✓ All snapshots successfully rendered.")


def test_direction_c_requirements():
    """Verify Direction C specifics: widths, hidden plan badge on empty string, Turkish formatting, missing data."""
    _app = get_qapp()
    popover = PopoverV2()
    anchor = QRect(400, 900, 100, 48)

    # 1. Width verification
    popover.show_for("claude", anchor, {"session": 10.0, "week": 20.0, "plan": "Max 5x"})
    _app.processEvents()
    assert popover.width() == panel_style.WIDTH["claude"], \
        f"Claude width must be {panel_style.WIDTH['claude']}, got {popover.width()}"

    popover.show_for("sys", anchor, {"cpu": 50.0, "ram": 60.0, "disk_c": 30.0})
    _app.processEvents()
    assert popover.width() == panel_style.WIDTH["sys"], \
        f"Sistem width must be {panel_style.WIDTH['sys']}, got {popover.width()}"

    # 2. Plan badge hidden when plan is ''
    c_empty_plan = build_claude_content({"session": 10.0, "week": 20.0, "plan": ""})
    assert c_empty_plan["plan"] == ""
    assert c_empty_plan["badge"] is None

    # 3. Missing data handling
    sys_missing = build_sys_content({"cpu": None, "ram": None, "disk_c": None, "top": []})
    assert sys_missing["cpu"] is None
    assert sys_missing["ram"] is None
    assert sys_missing["disk_c"] is None
    assert sys_missing["top"] == []

    # 4. Turkish number format in processes
    import sources
    assert sources.fmt_tr(3501.5, 1) == "3.501,5"
    assert sources.fmt_tr(1509.5, 1) == "1.509,5"
    assert sources.fmt_tr(939.5, 1) == "939,5"
    assert sources.fmt_tr(None) == "—"

    # 5. Render evidence inside the worktree
    v13_dir = REF_DIR / "tmp"
    v13_dir.mkdir(parents=True, exist_ok=True)

    import datetime as dt
    now = dt.datetime.now(sources.LOCAL_TZ)
    s_reset = (now + dt.timedelta(hours=4, minutes=21)).isoformat()
    days_until_sat = (5 - now.weekday()) % 7
    if days_until_sat == 0:
        days_until_sat = 7
    sat_dt = now.replace(hour=8, minute=59, second=0, microsecond=0) + dt.timedelta(days=days_until_sat)
    w_reset = sat_dt.isoformat()

    claude_evidence = {
        "session": 7.0,
        "session_reset": s_reset,
        "week": 25.0,
        "week_reset": w_reset,
        "plan": "Max 5x",
        "subscribed_at": "2026-05-21T07:23:39.399643Z",
        "extra_usage": False,
        "fetched_at": (now.replace(hour=14, minute=55)).timestamp(),
    }
    popover.show_for("claude", anchor, claude_evidence)
    _app.processEvents()
    img_c = popover.render_to_image(dpr=2.0)
    img_c.save(str(v13_dir / "claude.png"))

    sys_evidence = {
        "cpu": 52.0,
        "ram": 75.0,
        "ram_used_gb": 11.8,
        "ram_total_gb": 15.7,
        "disk_c": 27.0,
        "top": [
            {"name": "chrome.exe", "mb": 3501.5},
            {"name": "Hermes.exe", "mb": 1509.5},
            {"name": "MemCompression", "mb": 939.5},
        ],
        "fetched_at": (now.replace(hour=14, minute=58)).timestamp(),
    }
    popover.show_for("sys", anchor, sys_evidence)
    _app.processEvents()
    img_s = popover.render_to_image(dpr=2.0)
    img_s.save(str(v13_dir / "sistem.png"))

    sys_veriyok_evidence = {
        "cpu": None,
        "ram": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "disk_c": None,
        "top": [],
        "plan": "",
        "fetched_at": (now.replace(hour=14, minute=58)).timestamp(),
    }
    popover.show_for("sys", anchor, sys_veriyok_evidence)
    _app.processEvents()
    img_sv = popover.render_to_image(dpr=2.0)
    img_sv.save(str(v13_dir / "sistem_veriyok.png"))

    print("✓ Direction C requirements test passed.")


if __name__ == "__main__":
    test_top_processes()
    test_content_builders()
    test_refresh_button_and_callbacks()
    test_k4_logic()
    test_direction_c_requirements()
    render_all_snapshots()
