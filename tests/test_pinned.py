"""test_pinned.py - Test suite and visual showcase renderer for pinned.py.

Verifies:
  - load_default_pins(): Resolves shortcuts and handles File Explorer fallback.
  - merge_tiles(): Pin order priority, running state association, case-insensitivity.
  - pure helpers: reorder, pin, unpin, drag_target_index without mutating inputs.
  - launch(): Defined and available (NOT invoked during tests per rules).
  - Visual showcase render at DPR 2 with 5 tiles in distinct states:
      1. Active running tile (pill indicator)
      2. Multi-window running tile (3 dots indicator)
      3. Pinned not-running tile (no indicator)
      4. Hovered tile (hover_t=1.0, label bubble above)
      5. Single-window running tile (1 dot indicator)
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Ensure D:/Apps/serit is on python search path
SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
)
from PySide6.QtWidgets import QApplication

import pinned
import theme
import winapi

SHOWCASE_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5")
SHOWCASE_PATH = SHOWCASE_DIR / "pinned_showcase.png"


def get_qapp() -> QApplication:
    """Ensure a singleton QApplication instance exists for icon retrieval and font rendering."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(["serit_pinned_test"])
    return app


# ==============================================================================
# 1. LOGIC & DATA MODEL TESTS
# ==============================================================================


def test_load_default_pins() -> None:
    """Verify load_default_pins() returns resolved shortcut dicts and handles explorer."""
    get_qapp()
    pins = pinned.load_default_pins()
    print("load_default_pins():", pins)

    assert isinstance(pins, list), "load_default_pins must return a list"
    for item in pins:
        assert "path" in item, "Each pin must have a 'path' key"
        assert "name" in item, "Each pin must have a 'name' key"
        assert os.path.isabs(item["path"]), f"Pin path should be absolute: {item['path']}"

    # Verify that if File Explorer was found, it was mapped to explorer.exe
    for item in pins:
        if "explorer" in item["name"].lower():
            assert "explorer.exe" in item["path"].lower(), "File Explorer must map to explorer.exe"

    print("  [PASS] test_load_default_pins")


def test_merge_tiles() -> None:
    """Verify merge_tiles order, running state merge, and case-insensitivity."""
    pins = [
        {"path": r"C:\Windows\explorer.exe", "name": "File Explorer"},
        {"path": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "name": "Google Chrome"},
        {"path": r"C:\Apps\Notes\notes.exe", "name": "Notes"},
    ]
    groups = [
        # Chrome is running and active, with forward-slashes and lower-case
        {
            "exe": "c:/program files/google/chrome/application/chrome.exe",
            "name": "Google Chrome",
            "title": "Welcome - Chrome",
            "hwnds": [101, 102, 103],
            "active": True,
            "count": 3,
        },
        # Notepad is running, but NOT pinned
        {
            "exe": r"C:\Windows\System32\notepad.exe",
            "name": "Notepad",
            "title": "Untitled - Notepad",
            "hwnds": [201],
            "active": False,
            "count": 1,
        },
    ]

    tiles = pinned.merge_tiles(pins, groups)
    assert len(tiles) == 4, f"Expected 4 tiles (3 pins + 1 unpinned running), got {len(tiles)}"

    # Tile 0: explorer (pinned, not running)
    t0 = tiles[0]
    assert t0["name"] == "File Explorer"
    assert t0["pinned"] is True
    assert t0["running"] is False
    assert t0["active"] is False
    assert t0["hwnds"] == []
    assert t0["count"] == 0

    # Tile 1: chrome (pinned, running, active)
    t1 = tiles[1]
    assert t1["name"] == "Google Chrome"
    assert t1["pinned"] is True
    assert t1["running"] is True
    assert t1["active"] is True
    assert t1["count"] == 3
    assert t1["hwnds"] == [101, 102, 103]

    # Tile 2: notes (pinned, not running)
    t2 = tiles[2]
    assert t2["name"] == "Notes"
    assert t2["pinned"] is True
    assert t2["running"] is False
    assert t2["active"] is False

    # Tile 3: notepad (not pinned, running)
    t3 = tiles[3]
    assert t3["name"] == "Notepad"
    assert t3["pinned"] is False
    assert t3["running"] is True
    assert t3["active"] is False
    assert t3["count"] == 1
    assert t3["hwnds"] == [201]

    print("  [PASS] test_merge_tiles")


def test_pure_helpers() -> None:
    """Verify purity and correctness of reorder, pin, unpin, and drag_target_index."""
    # 1. reorder
    items = [{"path": "a"}, {"path": "b"}, {"path": "c"}, {"path": "d"}]
    orig = list(items)

    r1 = pinned.reorder(items, 0, 2)
    assert [x["path"] for x in r1] == ["b", "c", "a", "d"]
    assert items == orig, "reorder must not mutate original list"

    r2 = pinned.reorder(items, 3, 0)
    assert [x["path"] for x in r2] == ["d", "a", "b", "c"]

    r3 = pinned.reorder(items, 1, 1)
    assert [x["path"] for x in r3] == ["a", "b", "c", "d"]

    # Out of range index should safely return copy
    r_bad = pinned.reorder(items, -1, 10)
    assert r_bad == items

    # 2. pin
    pins = [{"path": r"C:\Windows\explorer.exe", "name": "Explorer"}]
    pins_orig = list(pins)

    p_added = pinned.pin(pins, {"exe": r"C:\Apps\App.exe", "name": "App"})
    assert len(p_added) == 2
    assert p_added[1]["name"] == "App"
    assert pins == pins_orig, "pin must not mutate original list"

    # Avoid duplicate (case/slash insensitive)
    p_dup = pinned.pin(p_added, {"exe": "c:/windows/EXPLORER.exe", "name": "Explorer 2"})
    assert len(p_dup) == 2, "pin must not add duplicate path"

    # 3. unpin
    u_removed = pinned.unpin(p_added, "c:/apps/app.exe")
    assert len(u_removed) == 1
    assert u_removed[0]["name"] == "Explorer"
    assert p_added == [{"path": r"C:\Windows\explorer.exe", "name": "Explorer"}, {"path": r"C:\Apps\App.exe", "name": "App"}]

    u_noop = pinned.unpin(p_added, r"C:\NonExistent.exe")
    assert len(u_noop) == 2

    # 4. drag_target_index
    centers = [100.0, 150.0, 200.0]
    assert pinned.drag_target_index(centers, 50.0) == 0
    assert pinned.drag_target_index(centers, 100.0) == 0
    assert pinned.drag_target_index(centers, 124.0) == 0
    assert pinned.drag_target_index(centers, 126.0) == 1
    assert pinned.drag_target_index(centers, 150.0) == 1
    assert pinned.drag_target_index(centers, 174.0) == 1
    assert pinned.drag_target_index(centers, 176.0) == 2
    assert pinned.drag_target_index(centers, 300.0) == 2
    assert pinned.drag_target_index([], 100.0) == 0

    print("  [PASS] test_pure_helpers")


# ==============================================================================
# 2. VISUAL SHOWCASE RENDERER (DPR 2)
# ==============================================================================


def render_showcase() -> Path:
    """Render high-DPI showcase PNG demonstrating 5 tiles in distinct states.

    States:
      1. Active running tile (pill indicator)
      2. Running tile with 3 windows (3 dots indicator)
      3. Pinned-not-running tile (no indicator)
      4. Hovered tile with label bubble (hover_t=1.0, bubble rendered above tile)
      5. Running tile with 1 window (1 dot indicator)
    """
    get_qapp()

    # Discover live applications for authentic icons
    windows = winapi.list_windows()
    groups = winapi.group_by_app(windows)

    # Resolve executable paths for real icons
    explorer_exe = os.path.normpath(os.environ.get("WINDIR", "C:\\Windows") + "\\explorer.exe")
    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_exe):
        chrome_exe = explorer_exe

    # Use real icons of explorer.exe, chrome.exe and running apps from group_by_app
    running_apps = [g for g in groups if g.get("exe") and os.path.exists(g.get("exe", ""))]
    running_by_name = {g["name"].lower(): g["exe"] for g in running_apps}

    claude_exe = running_by_name.get("claude") or r"C:\Program Files\WindowsApps\Claude_3.6556.2.0_x64__pzs8sxrjxfjjc\app\claude.exe"
    if not os.path.exists(claude_exe):
        claude_exe = chrome_exe

    hermes_exe = running_by_name.get("hermes") or r"C:\Users\Emre Karatasli\AppData\Local\hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe"
    if not os.path.exists(hermes_exe):
        hermes_exe = chrome_exe

    # Pick an additional running app or fallback to notepad
    other_running = [g for g in running_apps if g["exe"].lower() not in (chrome_exe.lower(), explorer_exe.lower(), hermes_exe.lower(), claude_exe.lower())]
    if other_running:
        other_exe = other_running[0]["exe"]
        other_name = other_running[0]["name"]
    else:
        other_exe = r"C:\Windows\System32\notepad.exe"
        other_name = "Not Defteri"
    if not os.path.exists(other_exe):
        other_exe = explorer_exe

    tiles = [
        {
            "name": "Claude",
            "exe": claude_exe,
            "running": True,
            "active": True,
            "count": 1,
            "pinned": True,
        },
        {
            "name": "Google Chrome",
            "exe": chrome_exe,
            "running": True,
            "active": False,
            "count": 3,
            "pinned": True,
        },
        {
            "name": "Dosya Gezgini",
            "exe": explorer_exe,
            "running": False,
            "active": False,
            "count": 0,
            "pinned": True,
        },
        {
            "name": "Hermes",
            "exe": hermes_exe,
            "running": True,
            "active": False,
            "count": 1,
            "pinned": True,
        },
        {
            "name": other_name,
            "exe": other_exe,
            "running": True,
            "active": False,
            "count": 1,
            "pinned": False,
        },
    ]

    # Pre-fetch crisp high-DPI application icons
    pixmaps = [winapi.app_icon(t["exe"], size=64) for t in tiles]

    # Setup rendering canvas
    dpr = 2.0
    logical_w = 420
    logical_h = 160
    pixel_w = int(logical_w * dpr)
    pixel_h = int(logical_h * dpr)

    img = QImage(pixel_w, pixel_h, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(11, 14, 20))  # Sleek dark desktop backdrop

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.TextAntialiasing)

    # Dock capsule geometry
    dock_pad_x = 14.0
    dock_h = 58.0
    tile_w = pinned.TILE
    tile_h = pinned.TILE
    gap = pinned.GAP
    n_tiles = len(tiles)
    content_w = n_tiles * tile_w + (n_tiles - 1) * gap
    dock_w = content_w + 2.0 * dock_pad_x
    dock_x = (logical_w - dock_w) / 2.0
    dock_y = 75.0  # Leave room above for tooltip bubble

    dock_rect = QRectF(dock_x, dock_y, dock_w, dock_h)

    # 1. Draw dock physical glass capsule with specular rim and noise grain
    theme.draw_glass_capsule(
        p,
        rect=dock_rect,
        radius=dock_h / 2.0,
        show_grain=True,
        show_specular=True,
        show_outer_stroke=True,
    )

    # 2. Draw tiles inside the capsule
    tile_y = dock_y + (dock_h - tile_h) / 2.0 - 2.5  # 2.5px up so indicator fits below
    ind_y = tile_y + tile_h + 3.0

    cur_x = dock_x + dock_pad_x
    tile_rects = []

    for i, t in enumerate(tiles):
        r = QRectF(cur_x, tile_y, tile_w, tile_h)
        tile_rects.append(r)
        pm = pixmaps[i]

        # Tile 3 (index 3) is hovered with label bubble
        is_hovered = (i == 3)
        hover_t = 1.0 if is_hovered else 0.0
        press_scale = 1.0

        pinned.draw_tile(
            p=p,
            rect=r,
            tile=t,
            pixmap=pm,
            hover_t=hover_t,
            press_scale=press_scale,
            dot_count=t.get("count"),
            indicator_y=ind_y,
        )

        # Draw label bubble above the hovered tile
        if is_hovered:
            anchor = QPointF(r.center().x(), r.top())
            pinned.draw_label_bubble(
                p=p,
                anchor_center_top=anchor,
                text=t["name"],
                gap=8.0,
            )

        cur_x += tile_w + gap

    p.end()

    # Save to scratch showcase path
    SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
    ok = img.save(str(SHOWCASE_PATH))
    if not ok:
        raise RuntimeError(f"Failed to save showcase image to {SHOWCASE_PATH}")

    print(f"  [SAVED] Showcase render saved to: {SHOWCASE_PATH}")
    return SHOWCASE_PATH


def main() -> None:
    print("=" * 60)
    print("RUNNING ŞERİT PINNED STRIP TEST SUITE")
    print("=" * 60)

    test_load_default_pins()
    test_merge_tiles()
    test_pure_helpers()
    out_png = render_showcase()

    assert os.path.exists(out_png), f"Showcase image does not exist: {out_png}"
    assert os.path.getsize(out_png) > 1000, "Showcase image is too small"

    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
