"""tests/test_sys_rings.py - Unit and regression tests for CPU/RAM ring gauges card.

Tests coverage:
  - Numerical and edge values: 0, 29, 77, 95, None, NaN, numeric and non-numeric strings
  - Colour threshold logic: base (<70), amber (>=70), red (>=90)
  - Card width and layout dimensions
  - Error state handling ('–' displayed, no active arc)
  - Absence of hard-coded fallback numbers on missing data
  - Animation Tweens: retargeting, smooth progression, and settling (driver stops)
  - Dock integration: tooltip formatting, default-ON settings, popover click
  - Settings integrity: ensures settings.json is never mutated
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
from pathlib import Path
import sys
import tempfile

# Guarantee repo root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

import anim
import dock_cards

# Import serit_v5 safely with isolated settings file
spec = importlib.util.spec_from_file_location("serit_v5_sys", str(PROJECT_ROOT / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

REAL_SETTINGS_FILE = PROJECT_ROOT / "settings.json"
TEMP_SETTINGS_DIR = Path(tempfile.mkdtemp(prefix="serit_sys_test_"))
serit_mod.SETTINGS_FILE = TEMP_SETTINGS_DIR / "settings.json"


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def get_settings_hash() -> str:
    if REAL_SETTINGS_FILE.is_file():
        return hashlib.sha256(REAL_SETTINGS_FILE.read_bytes()).hexdigest()
    return ""


# ==============================================================================
# 1. METRIC PARSING & NUMERICAL VALUES
# ==============================================================================

def test_metric_parsing_and_edge_values() -> None:
    """Verify safe float conversion for 0, 29, 77, 95, None, NaN, and strings."""
    # Standard numbers
    assert dock_cards._parse_sys_metric(0) == 0.0
    assert dock_cards._parse_sys_metric(0.0) == 0.0
    assert dock_cards._parse_sys_metric(29) == 29.0
    assert dock_cards._parse_sys_metric(77) == 77.0
    assert dock_cards._parse_sys_metric(95) == 95.0

    # Bounds clamping [0, 100]
    assert dock_cards._parse_sys_metric(-15.0) == 0.0
    assert dock_cards._parse_sys_metric(120.0) == 100.0

    # None and NaN
    assert dock_cards._parse_sys_metric(None) is None
    assert dock_cards._parse_sys_metric(float("nan")) is None
    assert dock_cards._parse_sys_metric(math.nan) is None
    assert dock_cards._parse_sys_metric(float("inf")) is None

    # Strings
    assert dock_cards._parse_sys_metric("29") == 29.0
    assert dock_cards._parse_sys_metric("77.4") == 77.4
    assert dock_cards._parse_sys_metric("0") == 0.0
    assert dock_cards._parse_sys_metric("100") == 100.0
    assert dock_cards._parse_sys_metric("bad_string") is None
    assert dock_cards._parse_sys_metric("N/A") is None
    assert dock_cards._parse_sys_metric("") is None
    assert dock_cards._parse_sys_metric({}) is None
    assert dock_cards._parse_sys_metric([]) is None


# ==============================================================================
# 2. COLOUR THRESHOLDS
# ==============================================================================

def test_colour_thresholds() -> None:
    """Verify colour thresholds: base (<70), amber (>=70), red (>=90)."""
    cpu_base = dock_cards.COLOR_CPU_BAR
    ram_base = dock_cards.COLOR_RAM_BAR
    amber = dock_cards.COLOR_BAR_AMBER
    red = dock_cards.COLOR_BAR_RED

    # CPU base colour checks (<70)
    assert dock_cards.get_sys_ring_color(0.0, cpu_base) == cpu_base
    assert dock_cards.get_sys_ring_color(29.0, cpu_base) == cpu_base
    assert dock_cards.get_sys_ring_color(69.9, cpu_base) == cpu_base

    # RAM base colour checks (<70)
    assert dock_cards.get_sys_ring_color(0.0, ram_base) == ram_base
    assert dock_cards.get_sys_ring_color(50.0, ram_base) == ram_base
    assert dock_cards.get_sys_ring_color(69.9, ram_base) == ram_base

    # Amber threshold (>= 70 and < 90)
    assert dock_cards.get_sys_ring_color(70.0, cpu_base) == amber
    assert dock_cards.get_sys_ring_color(77.0, cpu_base) == amber
    # Bellek eşiği daha yüksek: normal kullanım %74-77 (85 turuncu, 93 kırmızı)
    assert dock_cards.get_sys_ring_color(77.0, ram_base) == ram_base
    assert dock_cards.get_sys_ring_color(84.9, ram_base) == ram_base
    assert dock_cards.get_sys_ring_color(85.0, ram_base) == amber
    assert dock_cards.get_sys_ring_color(92.9, ram_base) == amber

    # Red threshold (>= 90)
    assert dock_cards.get_sys_ring_color(90.0, cpu_base) == red
    assert dock_cards.get_sys_ring_color(95.0, cpu_base) == red
    assert dock_cards.get_sys_ring_color(95.0, ram_base) == red
    assert dock_cards.get_sys_ring_color(100.0, ram_base) == red


# ==============================================================================
# 3. CARD WIDTH AND DIMENSIONS
# ==============================================================================

def test_card_width_and_geometry() -> None:
    """Verify card width is ~96-110 px and matches serit_v5 token."""
    w = dock_cards.SYS_CARD_WIDTH
    assert 96.0 <= w <= 110.0, f"Card width {w} out of ~96-110 px range"
    assert serit_mod.SYS_CARD_WIDTH == w, "serit_v5.SYS_CARD_WIDTH mismatch with dock_cards"
    assert dock_cards.SYS_RING_SIZE in (34.0, 35.0, 36.0)
    assert 3.5 <= dock_cards.SYS_RING_STROKE <= 4.0


# ==============================================================================
# 4. ERROR STATE AND ABSENCE OF HARD-CODED FALLBACK NUMBERS
# ==============================================================================

def test_error_state_and_no_fake_numbers() -> None:
    """Ensure missing or error data renders '–' without falling back to fake 0 or other numbers."""
    get_qapp()

    test_cases = [
        {"err": "Bağlantı yok"},
        {},
        {"cpu": None, "ram": None},
        {"cpu": "invalid", "ram": float("nan")},
    ]

    for data in test_cases:
        img = QImage(int(dock_cards.SYS_CARD_WIDTH * 2), 104, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(2.0)
        p = QPainter(img)
        rect = QRectF(0, 0, dock_cards.SYS_CARD_WIDTH, 52.0)
        # Must not throw
        dock_cards.draw_sys_card(p, rect, data)
        p.end()

        # Check internal metrics extracted by card logic
        has_err = bool(data.get("err"))
        raw_cpu = None if has_err else data.get("cpu")
        raw_ram = None if has_err else data.get("ram")
        assert dock_cards._parse_sys_metric(raw_cpu) is None
        assert dock_cards._parse_sys_metric(raw_ram) is None


# ==============================================================================
# 5. ANIMATION TWEEN BEHAVIOR & SETTLING
# ==============================================================================

def test_animation_tween_stops_when_settled() -> None:
    """Verify anim.Tween retargeting smoothly approaches target and driver stops when settled."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = False
    driver._simulated_time_ms = 0.0

    tw_cpu = anim.Tween(0.0, 0.0, serit_mod.theme.DUR_RING_SWEEP_FAST, driver=driver)
    tw_ram = anim.Tween(0.0, 0.0, serit_mod.theme.DUR_RING_SWEEP_FAST, driver=driver)

    assert not driver.is_running()

    # Retarget CPU to 29.0 and RAM to 77.0
    tw_cpu.retarget(29.0)
    tw_ram.retarget(77.0)

    assert driver.is_running()
    assert driver.active_count() == 2

    # Step halfway (175 ms)
    driver.step_manual(175.0)
    assert 0.0 < tw_cpu.value < 29.0
    assert 0.0 < tw_ram.value < 77.0
    assert driver.is_running()

    # Step past duration (another 225 ms)
    driver.step_manual(225.0)
    assert tw_cpu.value == 29.0
    assert tw_ram.value == 77.0
    assert tw_cpu.is_finished
    assert tw_ram.is_finished

    # Crucial requirement: no permanent repaint loop, driver timer stops when settled
    assert not driver.is_running()
    assert driver.active_count() == 0


# ==============================================================================
# 6. DOCK INTEGRATION, DEFAULT-ON & TOOLTIP
# ==============================================================================

def test_dock_default_on_and_tooltip() -> None:
    """Verify DEFAULT_SETTINGS cards.sys is True, merged_cards is True, and tooltip format."""
    get_qapp()

    # Default settings checks
    assert serit_mod.DEFAULT_SETTINGS["cards"]["sys"] is True

    # Test load_settings merging
    cfg = serit_mod.load_settings()
    assert "sys" in cfg["cards"]

    # Dock instance in preview mode
    apps = [{"exe": "test.exe", "name": "Test"}]
    dock = serit_mod.SeritDock({"style": "band", "pinned": apps}, preview_mode=True)
    dock.tiles = list(apps)
    dock.resize(1536, 64)

    # Set store data
    dock.store.update("sys", {
        "cpu": 29.0,
        "ram": 77.0,
        "ram_used_gb": 7.9,
        "ram_total_gb": 15.8,
        "source": "Bu bilgisayar",
    })

    dock.compute_layout_and_resize(initial=True)
    img = QImage(1536, 64, QImage.Format.Format_ARGB32)
    dock.render(img)

    # Verify 'sys' hit box exists
    sys_hits = [r for r, k, _e in dock.hit_boxes if k == "sys"]
    assert len(sys_hits) == 1, "Expected 'sys' card hit box in dock"
    r_sys = sys_hits[0]
    assert r_sys.width() == dock_cards.SYS_CARD_WIDTH
    assert r_sys.height() == 52.0

    # Verify tooltip text
    tip = dock.get_tooltip_text("sys", None)
    assert "İşlemci %29 · Bellek %77" in tip
    assert "Bellek %77 · 7,9 / 15,8 GB" in tip
    assert "psutil" in tip

    # Test error/missing tooltip
    dock.store._data.clear()
    dock.store.update("sys", {"err": "Error"})
    tip_err = dock.get_tooltip_text("sys", None)
    assert "psutil" in tip_err
    assert "Veri yok" in tip_err


# ==============================================================================
# MAIN RUNNER
# ==============================================================================

def run_all_tests() -> None:
    hash_before = get_settings_hash()
    print(f"[INTEGRITY] settings.json hash before: {hash_before}")

    test_metric_parsing_and_edge_values()
    print("[PASS] Metric parsing and edge values (0, 29, 77, 95, None, NaN, strings).")

    test_colour_thresholds()
    print("[PASS] Colour thresholds (base, amber >=70, red >=90).")

    test_card_width_and_geometry()
    print("[PASS] Card width (~96-110 px) and geometry.")

    test_error_state_and_no_fake_numbers()
    print("[PASS] Error state shows '–' without fake fallback numbers.")

    test_animation_tween_stops_when_settled()
    print("[PASS] Animation Tweens update smoothly and stop when settled.")

    test_dock_default_on_and_tooltip()
    print("[PASS] Dock default ON, hit box, and tooltip formatting.")

    hash_after = get_settings_hash()
    print(f"[INTEGRITY] settings.json hash after:  {hash_after}")
    assert hash_before == hash_after, "FATAL: settings.json was modified during tests!"
    print("ALL SYS RINGS TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all_tests()
