"""test_dock_v15.py - Verification for Şerit dock v15 layout changes:
1. Individual tray icons removed from band, chevron retained.
2. Clock (with attached weather) moved to far right edge (14px padding).
3. Antigravity logo visual height and width match Claude logo (29x29 in 40x40 slot).
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import dock_cards

spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

# Zero side-effects: isolate settings
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v15_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def get_visible_bbox(qimg: QImage):
    min_x, max_x, min_y, max_y = 9999, -1, 9999, -1
    for y in range(qimg.height()):
        for x in range(qimg.width()):
            alpha = (qimg.pixel(x, y) >> 24) & 0xFF
            if alpha > 10:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x == -1:
        return None
    return (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def test_logo_dimensions_match() -> None:
    """Requirement (3): Antigravity logo visible bounding box matches Claude logo visible size (29x29)."""
    get_qapp()

    # Claude in 40x40 slot
    c_img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    c_img.fill(0)
    p_c = QPainter(c_img)
    slot_c = QRectF(0.0, 0.0, 40.0, 40.0)
    c_pm = dock_cards.get_claude_symbol_pixmap(29.0, 1.0)
    assert c_pm is not None and not c_pm.isNull()
    sym_c_x = slot_c.x() + (slot_c.width() - 29.0) / 2.0
    sym_c_y = slot_c.y() + (slot_c.height() - 29.0) / 2.0
    p_c.drawPixmap(QPointF(sym_c_x, sym_c_y), c_pm)
    p_c.end()
    c_bbox = get_visible_bbox(c_img)
    assert c_bbox is not None
    # Claude visible box: width 29, height 29, centered at (6, 6)
    assert c_bbox == (6, 6, 29, 29), f"Expected Claude bbox (6, 6, 29, 29), got {c_bbox}"

    # Antigravity in 40x40 slot
    ag_img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    ag_img.fill(0)
    p_ag = QPainter(ag_img)
    slot_ag = QRectF(0.0, 0.0, 40.0, 40.0)
    ag_pm = dock_cards.get_antigravity_pixmap(35.0, 1.0)
    assert ag_pm is not None and not ag_pm.isNull()
    sym_ag_x = slot_ag.x() + (slot_ag.width() - 35.0) / 2.0
    sym_ag_y = slot_ag.y() + (slot_ag.height() - 35.0) / 2.0
    p_ag.drawPixmap(QPointF(sym_ag_x, sym_ag_y), ag_pm)
    p_ag.end()
    ag_bbox = get_visible_bbox(ag_img)
    assert ag_bbox is not None
    assert ag_bbox == (6, 6, 29, 29), f"Expected AG bbox (6, 6, 29, 29), got {ag_bbox}"

    # Visual heights and widths match exactly
    assert ag_bbox[2] == c_bbox[2], f"Width mismatch: AG {ag_bbox[2]} vs Claude {c_bbox[2]}"
    assert ag_bbox[3] == c_bbox[3], f"Height mismatch: AG {ag_bbox[3]} vs Claude {c_bbox[3]}"
    print(f"[PASS] Both logos visible bounding boxes in 40x40 slot match exactly: {c_bbox}")


def test_band_layout_order_and_edge_padding() -> None:
    """Requirements (1) & (2): No tray icons on band, right side order: media, cal, ^, sun, spk, [weather + clock] at far right edge (14px padding)."""
    get_qapp()
    sw = 1536.0

    dock = serit_mod.SeritDock({"style": "band", "pinned": [{"exe": "app1.exe", "name": "App 1"}]}, preview_mode=True)
    dock.pins = [{"exe": "app1.exe", "name": "App 1"}]
    dock.tiles = [{"exe": "app1.exe", "name": "App 1"}]
    dock._tray_items = [{"name": f"tray_{i}"} for i in range(8)]
    dock._now_playing_info = {"title": "Test Title", "app": "Spotify"}
    dock.store.update("wx", {"temp": 19.0, "icon": "cloud"})

    dock.resize(int(sw), 64)
    dock.compute_layout_and_resize(initial=True)
    img = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
    dock.render(img)

    # 1. No tray icons
    tray_icons = [e for r, k, e in dock.hit_boxes if k == "tray_icon"]
    assert len(tray_icons) == 0, f"Expected 0 tray icons on band, found {len(tray_icons)}"

    # 2. Key rects
    r_claude = next(r for r, k, _e in dock.hit_boxes if k == "claude")
    r_ag = next(r for r, k, _e in dock.hit_boxes if k == "ag")
    r_app = next(r for r, k, _e in dock.hit_boxes if k == "app_0")
    r_media = next(r for r, k, _e in dock.hit_boxes if k == "media")
    r_cal = next(r for r, k, _e in dock.hit_boxes if k == "cal")
    r_chv = next(r for r, k, _e in dock.hit_boxes if k == "tray")
    r_sun = next(r for r, k, _e in dock.hit_boxes if k == "bright")
    r_spk = next(r for r, k, _e in dock.hit_boxes if k == "vol")
    r_clock = next(r for r, k, _e in dock.hit_boxes if k == "clock")
    r_wx = next((r for r, k, _e in dock.hit_boxes if k == "wx"), None)

    # Order verification (strictly left-to-right)
    assert r_claude.right() < r_ag.left()
    assert r_ag.right() < r_app.left()
    assert r_app.right() < r_media.left()
    assert r_media.right() < r_cal.left()
    assert r_cal.right() < r_chv.left()
    assert r_chv.right() < r_sun.left()
    assert r_sun.right() < r_spk.left()
    assert r_spk.right() < r_clock.left()

    # Weather is attached to the left of clock text within the clock block
    if r_wx is not None:
        assert r_wx.left() >= r_clock.left()
        assert r_wx.right() <= r_clock.right()

    # Far right edge padding: 14.0px
    right_pad = sw - r_clock.right()
    assert abs(right_pad - 14.0) <= 0.5, f"Clock right padding should be 14.0px, got {right_pad}"

    # Center apps remained centered
    assert abs(r_app.center().x() - (sw / 2.0)) <= 1.0, f"App center {r_app.center().x()} not at screen center 768"

    print("[PASS] Band layout order and far right clock positioning verified.")


def main() -> None:
    test_logo_dimensions_match()
    test_band_layout_order_and_edge_padding()
    print("ALL TEST_DOCK_V15 TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
