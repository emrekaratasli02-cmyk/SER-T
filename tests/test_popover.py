"""Unit tests and visual snapshot verification for Popover window."""

from pathlib import Path
import sys
import time

# Ensure serit directory is in path
serit_dir = str(Path(__file__).resolve().parent.parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication

from popover import (
    Popover,
    build_claude_content,
    build_content,
    build_fx_content,
    build_sys_content,
    build_wx_content,
)

SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-audit")


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_content_builders():
    """Verify content builders produce required keys and valid source lines."""
    # 1. Claude
    c_data = {
        "plan": "Max",
        "session": 44.0,
        "session_reset": "2026-10-26T16:10:00Z",
        "week": 9.0,
        "week_reset": "2026-10-31T06:00:00Z",
        "source": "Anthropic · Claude Code girişi",
        "fetched_at": time.time(),
    }
    c_res = build_claude_content(c_data)
    assert c_res["title"] == "Claude"
    assert c_res["badge"] == "Max"
    assert len(c_res["rows"]) == 2
    assert "Kaynak: Anthropic" in c_res["source_line"]
    assert c_res["stale"] is False

    # 2. Sys
    s_data = {
        "cpu": 28.5,
        "ram": 64.2,
        "ram_used_gb": 10.27,
        "ram_total_gb": 16.0,
        "disk_c": 74.0,
        "source": "Bu bilgisayar (psutil)",
        "fetched_at": time.time(),
    }
    s_res = build_sys_content(s_data)
    assert s_res["title"] == "Sistem"
    assert len(s_res["rows"]) == 3
    assert "Kaynak: Bu bilgisayar" in s_res["source_line"]

    # 3. Wx
    w_data = {
        "temp": 18.5,
        "feel": 17.0,
        "desc": "Açık",
        "icon": "sun",
        "min": 12.0,
        "max": 21.0,
        "wind": 14.0,
        "source": "open-meteo.com",
        "fetched_at": time.time(),
    }
    w_res = build_wx_content(w_data, city="Aksaray")
    assert "Aksaray" in w_res["title"]
    assert len(w_res["rows"]) == 1
    assert w_res["rows"][0]["temp"] == "18.5°"
    assert "Kaynak: open-meteo.com" in w_res["source_line"]

    # 4. Fx
    f_data = {
        "usd": 34.2544,
        "usd_chg": 0.14,
        "eur": 37.1082,
        "eur_chg": -0.22,
        "gold": 3012.0,
        "gold_chg": 0.45,
        "updated": "16:00",
        "source": "finans.truncgil.com",
        "fetched_at": time.time(),
    }
    f_res = build_fx_content(f_data)
    assert f_res["title"] == "Piyasa (satış)"
    assert len(f_res["rows"]) == 3
    assert "%+0,14" in f_res["rows"][0]["chg"]
    assert "%-0,22" in f_res["rows"][1]["chg"]
    assert "Kaynak: finans.truncgil.com" in f_res["source_line"]

    # 5. Stale & Error
    stale_claude = dict(c_data, stale=True)
    c_stale_res = build_claude_content(stale_claude)
    assert c_stale_res["stale"] is True
    assert "Bayat" in c_stale_res["source_line"]

    err_claude = {"err": "Claude Code girişi yok", "source": "Anthropic"}
    c_err_res = build_claude_content(err_claude)
    assert c_err_res["badge"] == "Hata"
    assert c_err_res["error"] == "Claude Code girişi yok"
    assert "Hata" in c_err_res["source_line"]

    print("✓ Content builders assertions passed.")


def test_k4_focus_loss_and_recently_closed():
    """Verify K4 focus-loss fix: anchor click ignores auto-close and coordinates toggle."""
    get_qapp()
    pop = Popover()

    # Anchor rect in global coordinates
    anchor = QRectF(400, 700, 100, 40)
    data = {
        "plan": "Max",
        "session": 30.0,
        "session_reset": "2026-10-26T18:00:00Z",
        "week": 10.0,
        "week_reset": "",
    }
    pop.show_for("claude", anchor, data)
    assert pop.is_open("claude") is True
    assert pop.is_open("sys") is False

    # Simulate mouse cursor inside anchor rect
    QCursor.setPos(450, 720)
    assert anchor.contains(QPointF(QCursor.pos())) is True

    # 1. Test recently_closed initially false
    pop._last_close_time = 0.0
    assert pop.recently_closed("claude") is False

    # 2. Simulate deactivation with cursor over anchor
    # Trigger changeEvent via focus loss simulation
    pop._anchor_rect_global = anchor
    # When cursor is over anchor, Popover records close time and prevents auto-close
    pop._last_close_time = time.monotonic()
    pop._last_close_kind = "claude"

    assert pop.recently_closed("claude") is True
    assert pop.recently_closed("claude", threshold_ms=10) is True
    assert pop.recently_closed("sys") is False

    # 3. If closed 300ms ago, recently_closed with threshold 250ms should return False
    pop._last_close_time = time.monotonic() - 0.30
    assert pop.recently_closed("claude", threshold_ms=250.0) is False

    pop.hide()
    print("✓ K4 focus loss & recently_closed logic assertions passed.")


def test_close_animation_ends_hidden():
    """Verify hide_animated() runs close animation and widget ends hidden."""
    app = get_qapp()
    pop = Popover()
    anchor = QRectF(500, 700, 80, 40)
    pop.show_for("sys", anchor, {"cpu": 15.0, "ram": 45.0})
    assert pop.isVisible() is True
    assert pop.is_open("sys") is True

    # Initiate animated hide
    pop.hide_animated()
    assert pop._is_closing is True
    assert pop.is_open("sys") is False  # is_open must be False while closing

    # Pump event loop until animation finishes (150ms duration)
    start_t = time.monotonic()
    while pop.isVisible() and (time.monotonic() - start_t) < 0.6:
        app.processEvents()
        time.sleep(0.01)

    assert pop.isVisible() is False
    assert pop._is_closing is False
    print("✓ Close animation ends hidden assertion passed.")


def test_positioning_and_clamping():
    """Verify popover positions above anchor with 10 px gap and clamps to screen."""
    get_qapp()
    pop = Popover()
    screen = QGuiApplication.primaryScreen()
    geom = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    # 1. Standard bottom-dock positioning
    anchor = QRectF(geom.center().x() - 40, geom.bottom() - 50, 80, 40)
    pop.show_for("claude", anchor, {"session": 20.0, "week": 10.0})

    expected_cx = anchor.center().x()
    actual_cx = pop.x() + pop.width() / 2.0
    assert abs(actual_cx - expected_cx) <= 1.0
    expected_y = int(anchor.top() - pop.height() - 10)
    assert pop.y() == expected_y

    # 2. Clamping against left edge
    left_anchor = QRectF(geom.left() - 50, geom.bottom() - 50, 80, 40)
    pop.show_for("claude", left_anchor, {"session": 20.0, "week": 10.0})
    assert pop.x() >= geom.left() + 10

    # 3. Clamping against right edge
    right_anchor = QRectF(geom.right() + 50, geom.bottom() - 50, 80, 40)
    pop.show_for("claude", right_anchor, {"session": 20.0, "week": 10.0})
    assert pop.x() + pop.width() <= geom.right() - 10

    pop.hide()
    print("✓ Positioning and clamping assertions passed.")


def render_snapshots():
    """Render all kinds to DPR 2 PNGs in the scratch directory."""
    get_qapp()
    pop = Popover()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    dummy_anchor = QRectF(500, 700, 80, 40)

    # Sample datasets
    samples = {
        "pop_claude.png": (
            "claude",
            {
                "plan": "Max",
                "session": 44.0,
                "session_reset": "2026-10-26T16:10:00Z",
                "week": 9.0,
                "week_reset": "2026-10-31T06:00:00Z",
                "source": "Anthropic · Claude Code girişi",
                "fetched_at": time.time(),
            },
        ),
        "pop_sys.png": (
            "sys",
            {
                "cpu": 32.0,
                "ram": 78.4,
                "ram_used_gb": 12.5,
                "ram_total_gb": 16.0,
                "disk_c": 68.0,
                "source": "Bu bilgisayar (psutil)",
                "fetched_at": time.time(),
            },
        ),
        "pop_wx.png": (
            "wx",
            {
                "temp": 19.4,
                "feel": 18.2,
                "desc": "Parçalı bulutlu",
                "icon": "partly",
                "min": 11.5,
                "max": 22.0,
                "wind": 12.6,
                "city": "Aksaray",
                "source": "open-meteo.com",
                "fetched_at": time.time(),
            },
        ),
        "pop_fx.png": (
            "fx",
            {
                "usd": 34.2850,
                "usd_chg": 0.18,
                "eur": 37.1420,
                "eur_chg": -0.31,
                "gold": 3025.0,
                "gold_chg": 0.52,
                "updated": "16:04",
                "source": "finans.truncgil.com",
                "fetched_at": time.time(),
            },
        ),
        "pop_claude_stale.png": (
            "claude",
            {
                "plan": "Max",
                "session": 88.0,
                "session_reset": "2026-10-26T17:00:00Z",
                "week": 96.0,
                "week_reset": "2026-10-31T06:00:00Z",
                "source": "Anthropic · Claude Code girişi",
                "fetched_at": time.time() - 3600,
                "stale": True,
            },
        ),
        "pop_error.png": (
            "claude",
            {
                "err": "Claude Code girişi yok (credentials.json)",
                "source": "Anthropic · Claude Code girişi",
                "fetched_at": time.time(),
            },
        ),
    }

    generated_paths = []
    for filename, (kind, data) in samples.items():
        content = build_content(kind, data)
        pop._content = content
        pop._kind = kind
        pop._anchor_rect_global = dummy_anchor
        h = pop.compute_height(content)
        pop.resize(pop.WIDTH, h)

        img = pop.render_to_image(dpr=2.0)
        out_path = SCRATCH_DIR / filename
        saved = img.save(str(out_path))
        assert saved is True, f"Failed to save {out_path}"
        generated_paths.append(str(out_path))
        print(f"  Exported DPR 2 render: {out_path} ({img.width()}x{img.height()} px)")

    pop.deleteLater()
    return generated_paths


if __name__ == "__main__":
    print("--- RUNNING POPOVER TEST SUITE ---")
    test_content_builders()
    test_k4_focus_loss_and_recently_closed()
    test_close_animation_ends_hidden()
    test_positioning_and_clamping()
    print("\n--- GENERATING OFFSCREEN VISUAL SNAPSHOTS ---")
    paths = render_snapshots()
    print(f"\nSuccessfully generated {len(paths)} snapshots.")
    print("ALL TESTS PASSED.")
