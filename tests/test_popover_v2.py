"""Comprehensive unit tests and high-DPI visual snapshot verification for PopoverV2.

Tests:
1. Content builders (claude, sys, wx, fx, error, stale, top_processes).
2. K4 window coordination and recently_closed debounce logic.
3. Refresh button hit testing, micro-interaction state, and on_refresh callback.
4. Renders DPR 2.0 offscreen snapshots to scratch directory for visual inspection.
"""

from __future__ import annotations

import json
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
import sources

SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5")
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
    assert btn_rect.width() >= 60.0
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
    """Render every kind + stale + error to DPR 2.0 PNGs in scratch directory."""
    _app = get_qapp()
    popover = PopoverV2()
    anchor = QRect(400, 900, 100, 48)

    # 1. Claude (Live cache or sample)
    cache_path = Path("D:/Apps/serit/claude_cache.json")
    if cache_path.exists():
        try:
            claude_data = json.loads(cache_path.read_text(encoding="utf-8"))
            print("Loaded live Claude data from claude_cache.json.")
        except Exception:
            claude_data = {
                "plan": "Max (Sample)",
                "session": 77.0,
                "session_reset": "2026-10-26T19:30:00Z",
                "week": 11.0,
                "week_reset": "2026-10-31T06:00:00Z",
                "source": "Sample Claude Data",
                "fetched_at": time.time(),
            }
            print("Used sample Claude data (cache read error).")
    else:
        claude_data = {
            "plan": "Max (Sample)",
            "session": 77.0,
            "session_reset": "2026-10-26T19:30:00Z",
            "week": 11.0,
            "week_reset": "2026-10-31T06:00:00Z",
            "source": "Sample Claude Data",
            "fetched_at": time.time(),
        }
        print("Used sample Claude data (no claude_cache.json).")

    popover.show_for("claude", anchor, claude_data)
    _app.processEvents()
    img_claude = popover.render_to_image(dpr=2.0)
    p_claude = SCRATCH_DIR / "pv2_claude.png"
    img_claude.save(str(p_claude))
    print(f"Saved {p_claude} ({img_claude.width()}x{img_claude.height()})")

    # 2. Claude Stale
    claude_stale = dict(claude_data, stale=True)
    popover.show_for("claude", anchor, claude_stale)
    _app.processEvents()
    img_claude_stale = popover.render_to_image(dpr=2.0)
    p_claude_stale = SCRATCH_DIR / "pv2_claude_stale.png"
    img_claude_stale.save(str(p_claude_stale))
    print(f"Saved {p_claude_stale}")

    # 3. Claude Error (with dimmed cached usage)
    claude_err = dict(claude_data, err="Claude Code girişi yok")
    popover.show_for("claude", anchor, claude_err)
    _app.processEvents()
    img_claude_err = popover.render_to_image(dpr=2.0)
    p_claude_err = SCRATCH_DIR / "pv2_claude_error.png"
    img_claude_err.save(str(p_claude_err))
    print(f"Saved {p_claude_err}")

    # 4. System (Live telemetry with top processes)
    live_sys = sources.fetch_system()
    live_sys["top"] = top_processes(3)
    popover.show_for("sys", anchor, live_sys)
    _app.processEvents()
    img_sys = popover.render_to_image(dpr=2.0)
    p_sys = SCRATCH_DIR / "pv2_sys.png"
    img_sys.save(str(p_sys))
    print(f"Saved {p_sys}")

    # 5. System Error
    sys_err = dict(live_sys, err="psutil telemetrisi alınamadı")
    popover.show_for("sys", anchor, sys_err)
    _app.processEvents()
    img_sys_err = popover.render_to_image(dpr=2.0)
    p_sys_err = SCRATCH_DIR / "pv2_sys_error.png"
    img_sys_err.save(str(p_sys_err))
    print(f"Saved {p_sys_err}")

    # 6. Weather (Live open-meteo)
    live_wx = sources.fetch_weather()
    popover.show_for("wx", anchor, live_wx)
    _app.processEvents()
    img_wx = popover.render_to_image(dpr=2.0)
    p_wx = SCRATCH_DIR / "pv2_wx.png"
    img_wx.save(str(p_wx))
    print(f"Saved {p_wx}")

    # 7. FX (Live finans.truncgil)
    live_fx = sources.fetch_fx()
    popover.show_for("fx", anchor, live_fx)
    _app.processEvents()
    img_fx = popover.render_to_image(dpr=2.0)
    p_fx = SCRATCH_DIR / "pv2_fx.png"
    img_fx.save(str(p_fx))
    print(f"Saved {p_fx}")

    # 8. Refresh Button Spinning / Pressed Micro-state
    popover.show_for("claude", anchor, claude_data)
    popover._refresh_spinning = True
    popover._spin_angle = 120.0  # Angle midway in spin
    popover._refresh_hovered = True
    popover._refresh_pressed = True
    _app.processEvents()
    img_spinning = popover.render_to_image(dpr=2.0)
    p_spinning = SCRATCH_DIR / "pv2_refresh_spinning.png"
    img_spinning.save(str(p_spinning))
    print(f"Saved {p_spinning}")

    print("✓ All snapshots successfully rendered.")


if __name__ == "__main__":
    test_top_processes()
    test_content_builders()
    test_refresh_button_and_callbacks()
    test_k4_logic()
    render_all_snapshots()
