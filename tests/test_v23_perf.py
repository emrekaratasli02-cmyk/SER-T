"""tests/test_v23_perf.py - v23 performance & repaint optimization regression suite.

Verifies:
1. theme.rounded_path and theme._get_cloud_path return cached QPainterPath objects.
2. theme.make_font returns cached QFont instances.
3. dock_cards font metrics and text width caches return consistent, accurate values.
4. on_data_ready with identical data does not trigger unnecessary updates/repaints.
5. Partial repaints preserve hit_boxes and render without error.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SERIT_TEST", "1")
os.environ.setdefault("SERIT_LOG", os.path.join(tempfile.gettempdir(), "serit-agent.log"))

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QPoint, QRect, QRectF
from PySide6.QtGui import QFont, QImage, QPainterPath, QRegion
from PySide6.QtWidgets import QApplication

spec = importlib.util.spec_from_file_location("serit_v5_v23perf", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v23perf_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

import dock_cards
import theme


def _get_app():
    return QApplication.instance() or QApplication([])


def test_rounded_path_caching() -> None:
    _get_app()
    r = QRectF(10.0, 10.0, 100.0, 50.0)
    p1 = theme.rounded_path(r, 8.0)
    p2 = theme.rounded_path(r, 8.0)
    assert p1 is p2, "theme.rounded_path must return cached QPainterPath instance for identical rect & radius"

    # Different geometry creates distinct cached path
    r2 = QRectF(20.0, 10.0, 100.0, 50.0)
    p3 = theme.rounded_path(r2, 8.0)
    assert p3 is not p1, "Different rect must return distinct QPainterPath"


def test_make_font_caching() -> None:
    _get_app()
    f1 = theme.make_font(12.0, QFont.Weight.DemiBold)
    f2 = theme.make_font(12.0, QFont.Weight.DemiBold)
    assert f1 is f2, "theme.make_font must return cached QFont instance for identical size & weight"
    assert f1.pixelSize() == 12
    assert f1.weight() == QFont.Weight.DemiBold


def test_cloud_path_caching() -> None:
    _get_app()
    c1 = theme._get_cloud_path(16.0, 10.0)
    c2 = theme._get_cloud_path(16.0, 10.0)
    assert c1 is c2, "theme._get_cloud_path must return cached QPainterPath"
    assert isinstance(c1, QPainterPath)
    assert not c1.isEmpty()


def test_dock_cards_caches() -> None:
    _get_app()
    f = theme.make_font(11.0, QFont.Weight.Normal)
    fm1 = dock_cards._get_fm(f)
    fm2 = dock_cards._get_fm(f)
    assert fm1 is fm2, "dock_cards._get_fm must return cached QFontMetricsF"

    w1 = dock_cards._text_width(fm1, "Test Text 123")
    w2 = dock_cards._text_width(fm1, "Test Text 123")
    assert w1 == w2
    assert w1 > 0.0

    el1 = dock_cards._elided_text(fm1, "Very Long Text That Will Be Elided Soon", 40.0)
    el2 = dock_cards._elided_text(fm1, "Very Long Text That Will Be Elided Soon", 40.0)
    assert el1 == el2
    assert "…" in el1


def test_unchanged_data_skips_repaint() -> None:
    _get_app()
    dock = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    dock.resize(1920, int(serit_mod.DOCK_HEIGHT))
    dock.compute_layout_and_resize(initial=True)

    # Initial data
    initial_sys = {"cpu": 25.0, "ram": 60.0, "source": "test"}
    dock.on_data_ready("sys", initial_sys)
    dock.sync_anim_values()

    # Track calls to update()
    update_calls = []
    orig_update = dock.update

    def stub_update(*args):
        update_calls.append(args)
        return orig_update(*args)

    dock.update = stub_update

    # 1. Update sys with identical data
    dock.on_data_ready("sys", {"cpu": 25.0, "ram": 60.0, "source": "test"})
    assert len(update_calls) == 0, f"Unchanged sys data must not call update(); called {len(update_calls)} times"

    # 2. Update mail with identical data
    dock.store.update("mail", {"waiting": 2})
    dock.on_data_ready("mail", {"waiting": 2})
    assert len(update_calls) == 0, f"Unchanged mail data must not call update(); called {len(update_calls)} times"

    # 3. Update ag with identical data
    dock.store.update("ag", {"groups": []})
    dock.on_data_ready("ag", {"groups": []})
    assert len(update_calls) == 0, f"Unchanged ag data must not call update(); called {len(update_calls)} times"


def test_partial_repaint_preserves_hitboxes() -> None:
    _get_app()
    dock = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    dock.resize(1920, int(serit_mod.DOCK_HEIGHT))
    dock.compute_layout_and_resize(initial=True)

    img = QImage(1920, int(serit_mod.DOCK_HEIGHT), QImage.Format.Format_ARGB32)
    dock.render(img, QPoint(0, 0))

    initial_hitboxes = list(dock.hit_boxes)
    assert len(initial_hitboxes) > 0, "Initial full render must populate hit_boxes"

    # Render a small 40x40 region
    dock.render(img, QPoint(0, 0), QRegion(QRect(600, 12, 40, 40)))

    # Verify hitboxes were NOT wiped out by the partial paint
    after_keys = [k for _, k, _ in dock.hit_boxes]
    initial_keys = [k for _, k, _ in initial_hitboxes]
    assert after_keys == initial_keys, "Partial repaint must preserve hit_boxes for entire dock"


def run_all() -> None:
    test_rounded_path_caching()
    print("PASS test_rounded_path_caching")
    test_make_font_caching()
    print("PASS test_make_font_caching")
    test_cloud_path_caching()
    print("PASS test_cloud_path_caching")
    test_dock_cards_caches()
    print("PASS test_dock_cards_caches")
    test_unchanged_data_skips_repaint()
    print("PASS test_unchanged_data_skips_repaint")
    test_partial_repaint_preserves_hitboxes()
    print("PASS test_partial_repaint_preserves_hitboxes")
    print("ALL PASSED")


if __name__ == "__main__":
    run_all()
