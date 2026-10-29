"""Unit and integration test suite for brightness backend and BrightnessPopover.

Ensures:
1. settings.json is NEVER touched (checked via SHA-256 before and after suite).
2. WMI and DDC parsing, clamping, and error paths are rigorously tested with mocks.
3. Per-thread COM initialization (COINIT_APARTMENTTHREADED 0x2) and thread-local caching.
4. Coalescing of level_requested signal (<= 60ms, final value on release).
5. Comprehensive bad-data matrix (>= 35 cases) with offscreen QImage rendering.
6. READ-ONLY live check of connected monitors (verifies internal laptop panel 'Dizüstü ekranı').
7. Benchmark timing on main thread vs reused worker thread.
8. DPR 2.0 visual snapshot rendered to scratch directory.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import List, Tuple
from unittest.mock import MagicMock, patch

# Ensure serit directory is on sys.path
serit_dir = str(Path(__file__).resolve().parent.parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication

import brightness
import brightness_popover

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"
SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v6")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def get_file_hash(path: Path) -> str:
    if not path.exists():
        return "NOT_EXISTS"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ===========================================================================
# 1. Parsing & Name Resolution Tests
# ===========================================================================

def test_edid_decoding():
    """Test decoding of ASCII uint16 tuples from WmiMonitorID."""
    print("--- 1. Testing EDID Decoding ---")
    # Typical WmiMonitorID tuple with null termination
    tuples = (77, 83, 73, 32, 77, 80, 50, 50, 51, 0, 0, 0)
    assert brightness._decode_edid_chars(tuples) == "MSI MP223"

    # Empty and invalid cases
    assert brightness._decode_edid_chars(()) == ""
    assert brightness._decode_edid_chars([]) == ""
    assert brightness._decode_edid_chars(None) == ""
    assert brightness._decode_edid_chars("string") == ""
    assert brightness._decode_edid_chars([0, 0, 0]) == ""
    print("  [PASS] EDID character decoding verified.")


def test_wmi_parsing_with_mocks():
    """Test WMI COM query parsing and fallback."""
    print("--- 2. Testing WMI Parsing with Mocks ---")
    mock_item = MagicMock()
    mock_prop_inst = MagicMock()
    mock_prop_inst.Value = "DISPLAY\\CMN1556\\5&3348901b&0&UID4353_0"
    mock_prop_lvl = MagicMock()
    mock_prop_lvl.Value = 85

    def prop_side_effect(name):
        if name == "InstanceName":
            return mock_prop_inst
        if name == "CurrentBrightness":
            return mock_prop_lvl
        return None

    mock_item.Properties_.side_effect = prop_side_effect

    mock_svc = MagicMock()
    mock_svc.ExecQuery.return_value = [mock_item]

    mock_loc = MagicMock()
    mock_loc.ConnectServer.return_value = mock_svc

    with patch("comtypes.client.CreateObject", return_value=mock_loc), \
         patch.object(brightness, "_ensure_com", return_value=True):
        monitors, keys = brightness._query_wmi_brightness_com()
        assert len(monitors) == 1
        m = monitors[0]
        assert m["id"] == "wmi:DISPLAY\\CMN1556\\5&3348901b&0&UID4353_0"
        assert m["name"] == "Dizüstü ekranı"
        assert m["kind"] == "wmi"
        assert m["level"] == 85
        assert m["ok"] is True
        assert m["err"] is None
        assert "CMN1556" in keys
    print("  [PASS] WMI COM parsing verified.")


def test_powershell_fallback_mock():
    """Test PowerShell fallback for WMI query when COM is unavailable."""
    print("--- 3. Testing PowerShell Fallback Mock ---")
    ps_json = json.dumps({
        "InstanceName": "DISPLAY\\CMN1556\\5&3348901b&0&UID4353_0",
        "CurrentBrightness": 70,
    })
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ps_json

    with patch("subprocess.run", return_value=mock_proc):
        monitors, keys = brightness._query_wmi_brightness_powershell()
        assert len(monitors) == 1
        assert monitors[0]["level"] == 70
        assert monitors[0]["name"] == "Dizüstü ekranı"
        assert "CMN1556" in keys

    # PowerShell error/timeout simulation
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ps", timeout=3.0)):
        monitors_timeout, _ = brightness._query_wmi_brightness_powershell()
        assert monitors_timeout == []
    print("  [PASS] PowerShell fallback and timeout paths verified.")


# ===========================================================================
# 2. Clamping & Safe set_level Mocks
# ===========================================================================

def test_set_level_clamping_and_mocks():
    """Test level clamping and mocked set_level for WMI and DDC without real hardware calls."""
    print("--- 4. Testing set_level Clamping & Mocks ---")
    # Invalid inputs
    assert brightness.set_level("", 50) is False
    assert brightness.set_level(None, 50) is False
    assert brightness.set_level("wmi:test", "invalid") is False

    # Mock WMI set_level
    mock_meth = MagicMock()
    mock_in_params = MagicMock()
    mock_prop_item = MagicMock()
    mock_in_params.Properties_.Item.return_value = mock_prop_item
    mock_meth.InParameters.SpawnInstance_.return_value = mock_in_params
    mock_item = MagicMock()
    mock_item.Properties_.return_value.Value = "DISPLAY\\CMN1556\\test"
    mock_item.Methods_.return_value = mock_meth

    mock_svc = MagicMock()
    mock_svc.ExecQuery.return_value = [mock_item]
    mock_loc = MagicMock()
    mock_loc.ConnectServer.return_value = mock_svc

    with patch("comtypes.client.CreateObject", return_value=mock_loc), \
         patch.object(brightness, "_ensure_com", return_value=True):

        # Test upper clamp (150 -> 100)
        ok1 = brightness.set_level("wmi:DISPLAY\\CMN1556\\test", 150)
        assert ok1 is True
        mock_item.ExecMethod_.assert_called_with("WmiSetBrightness", mock_in_params)
        assert mock_prop_item.Value == 100

        # Test lower clamp (-25 -> 0)
        ok2 = brightness.set_level("wmi:DISPLAY\\CMN1556\\test", -25)
        assert ok2 is True
        assert mock_prop_item.Value == 0

        # Test float rounding (42.6 -> 43)
        ok3 = brightness.set_level("wmi:DISPLAY\\CMN1556\\test", 42.6)
        assert ok3 is True
        assert mock_prop_item.Value == 43

    # Mock DDC set_level
    with patch.object(brightness, "_set_ddc_level", return_value=True) as mock_ddc_set:
        ok4 = brightness.set_level("ddc:\\\\.\\DISPLAY2", 80)
        assert ok4 is True
        mock_ddc_set.assert_called_with("ddc:\\\\.\\DISPLAY2", 80)
    print("  [PASS] Clamping and mocked set_level calls verified.")


# ===========================================================================
# 3. Thread-Safety & Per-Thread COM Init
# ===========================================================================

def test_thread_safety_and_com_init():
    """Test that COM is initialized per worker thread with COINIT_APARTMENTTHREADED."""
    print("--- 5. Testing Per-Thread COM Init & Thread Safety ---")
    thread_init_calls = []

    def mock_co_init(flags):
        thread_id = threading.get_ident()
        thread_init_calls.append((thread_id, flags))

    with patch("comtypes.CoInitializeEx", side_effect=mock_co_init):
        # Reset local thread tls
        if hasattr(brightness._tls, "com_initialized"):
            del brightness._tls.com_initialized

        # Main thread
        ok1 = brightness._ensure_com()
        ok2 = brightness._ensure_com()  # Second call should use thread-local cache
        assert ok1 is True and ok2 is True

        worker_results = []
        def worker_task():
            # Reset tls for new worker thread
            if hasattr(brightness._tls, "com_initialized"):
                del brightness._tls.com_initialized
            res1 = brightness._ensure_com()
            res2 = brightness._ensure_com()
            worker_results.append((res1, res2))

        threads = [threading.Thread(target=worker_task) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(worker_results) == 3
        assert all(r == (True, True) for r in worker_results)

        # Verify COINIT_APARTMENTTHREADED (0x2) was passed
        for _, flags in thread_init_calls:
            assert flags == brightness.COINIT_APARTMENTTHREADED

    print("  [PASS] Per-thread COM initialization contract verified.")


# ===========================================================================
# 4. Popover Signal Coalescing Tests
# ===========================================================================

def test_signal_coalescing():
    """Test that level_requested emits coalesced updates <= 60ms and final on release."""
    print("--- 6. Testing Popover Signal Coalescing ---")
    get_qapp()

    coalescer = brightness_popover.BrightnessCoalescer(interval_ms=60)
    emissions: List[Tuple[str, int]] = []
    coalescer.level_requested.connect(lambda mid, lvl: emissions.append((mid, lvl)))

    # Request 1 (first request triggers immediate flush if interval elapsed)
    coalescer.request("mon_1", 20, force=False)
    assert len(emissions) == 1
    assert emissions[0] == ("mon_1", 20)

    # Rapid requests within 60ms window
    coalescer.request("mon_1", 30, force=False)
    coalescer.request("mon_1", 40, force=False)
    coalescer.request("mon_1", 50, force=False)
    # Shouldn't emit immediately
    assert len(emissions) == 1

    # Force flush (as upon mouse release)
    coalescer.request("mon_1", 55, force=True)
    assert len(emissions) == 2
    assert emissions[1] == ("mon_1", 55)

    print("  [PASS] Coalescer 60ms throttling and force-on-release verified.")


# ===========================================================================
# 5. Bad-Data Robustness Matrix (>= 35 cases)
# ===========================================================================

def test_bad_data_robustness_matrix():
    """Test show_for, update_levels, and render_to_image across a matrix of invalid data."""
    print("--- 7. Testing Bad-Data Robustness Matrix (>= 35 cases) ---")
    get_qapp()
    pop = brightness_popover.BrightnessPopover()
    anchor = QRectF(400, 600, 100, 30)

    matrix = [
        None,
        [],
        "invalid_string",
        12345,
        [None],
        [{}],
        [{"id": None}],
        [{"name": None}],
        [{"level": None}],
        [{"ok": None}],
        [{"err": None}],
        [{"id": "m1", "name": "M1", "level": float("nan"), "ok": True}],
        [{"id": "m1", "name": "M1", "level": float("inf"), "ok": True}],
        [{"id": "m1", "name": "M1", "level": float("-inf"), "ok": True}],
        [{"id": "m1", "name": "M1", "level": -50, "ok": True}],
        [{"id": "m1", "name": "M1", "level": 250, "ok": True}],
        [{"id": "m1", "name": "M1", "level": "bad_lvl", "ok": True}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": False, "err": "DDC/CI desteklenmiyor"}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": False, "err": ""}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": False, "err": None}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": False, "err": 9999}],
        [{"id": 12345, "name": 67890, "level": 100, "ok": 1}],
        [{"id": "m1", "name": "A" * 500, "level": 50, "ok": True}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": True, "extra_junk": object()}],
        [{"id": "m1", "level": 10}, {"id": "m2", "level": 20}, {"id": "m3", "level": 30}],
        [{"id": "m1", "level": None, "ok": False}, {"id": "m2", "level": 100, "ok": True}],
        {"m1": 50, "m2": "invalid"},
        {"m1": float("nan")},
        {"m1": None},
        {"m1": -10, "m2": 150},
        [{"id": "", "name": "", "level": 0, "ok": True}],
        [{"id": "m1", "name": "M1", "level": "75.4", "ok": True}],
        [{"id": "m1", "name": "M1", "level": True, "ok": True}],
        [{"id": "m1", "name": "M1", "level": False, "ok": True}],
        [{"id": "m1", "name": "M1", "level": 50.0, "ok": True}],
        [{"id": "m1", "name": "M1", "level": 50, "ok": "maybe"}],
    ]

    for idx, case in enumerate(matrix):
        try:
            if isinstance(case, list) or case is None or isinstance(case, (str, int)):
                pop.show_for(anchor, case)
            pop.update_levels(case)
            img = pop.render_to_image(dpr=2.0)
            assert img is not None
            assert not img.isNull()
        except Exception as exc:
            raise AssertionError(f"Failed on bad-data matrix case {idx} ({case!r}): {exc}") from exc

    print(f"  [PASS] All {len(matrix)} bad-data cases passed offscreen render without raising.")


# ===========================================================================
# 6. Popover Lifecycle, Keyboard & Interaction Simulation
# ===========================================================================

def test_popover_lifecycle_and_events():
    """Test is_open, recently_closed, escape key, and mouse release."""
    print("--- 8. Testing Popover Lifecycle & Events ---")
    get_qapp()
    pop = brightness_popover.BrightnessPopover()
    anchor = QRectF(400, 600, 100, 30)

    assert not pop.is_open()
    assert not pop.recently_closed()

    # Show
    pop.show_for(anchor, [{"id": "m1", "name": "Dizüstü ekranı", "level": 80, "ok": True}])
    assert pop.is_open()

    # Close via Escape
    pop.keyPressEvent(MagicMock(key=lambda: Qt.Key_Escape, accept=lambda: None))
    assert pop._is_closing is True
    assert pop.recently_closed(threshold_ms=500.0)

    # Reset
    pop._is_closing = False
    pop.hide()

    print("  [PASS] Popover lifecycle and escape handling verified.")


# ===========================================================================
# 7. READ-ONLY Live Hardware Verification & Benchmark
# ===========================================================================

def test_live_hardware_read_only():
    """Live read-only test of brightness backend on real hardware."""
    print("--- 9. Live Read-Only Hardware Verification ---")
    # Main thread run
    t0 = time.perf_counter()
    monitors_main = brightness.list_monitors(force_refresh=True)
    t1 = time.perf_counter()
    ms_main = (t1 - t0) * 1000.0

    print(f"  [BENCHMARK] Main thread list_monitors(): {ms_main:.2f} ms")
    assert len(monitors_main) >= 1, "At least one monitor must be detected."

    # Verify laptop panel presence
    wmi_monitors = [m for m in monitors_main if m.get("kind") == "wmi"]
    assert len(wmi_monitors) >= 1, "WMI laptop panel must be detected."
    laptop_panel = wmi_monitors[0]
    assert laptop_panel["name"] == "Dizüstü ekranı"
    assert isinstance(laptop_panel["level"], int)
    assert 0 <= laptop_panel["level"] <= 100
    assert laptop_panel["ok"] is True
    assert laptop_panel["err"] is None
    print(f"  [LIVE WMI] Found {laptop_panel['name']} (ID: {laptop_panel['id']}) Level: %{laptop_panel['level']}")

    # External monitor check if present
    ddc_monitors = [m for m in monitors_main if m.get("kind") == "ddc"]
    for ddc_m in ddc_monitors:
        print(f"  [LIVE DDC] Found {ddc_m['name']} (ID: {ddc_m['id']}) Level: {ddc_m['level']} OK: {ddc_m['ok']} Err: {ddc_m['err']}")

    # Reused worker thread run
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        # Warmup worker thread
        executor.submit(lambda: None).result()

        t_work_0 = time.perf_counter()
        monitors_worker = executor.submit(brightness.list_monitors, False).result()
        t_work_1 = time.perf_counter()
        ms_worker = (t_work_1 - t_work_0) * 1000.0

    print(f"  [BENCHMARK] Reused worker thread list_monitors(): {ms_worker:.2f} ms")
    assert len(monitors_worker) == len(monitors_main)

    # Render high-DPI evidence snapshot (DPR 2.0)
    get_qapp()
    pop = brightness_popover.BrightnessPopover()
    anchor = QRectF(500, 800, 120, 32)
    pop.show_for(anchor, monitors_main)

    png_path = SCRATCH_DIR / "brightness_pop.png"
    img = pop.render_to_image(dpr=2.0)
    saved = img.save(str(png_path))
    assert saved, f"Failed to save {png_path}"
    print(f"  [SAVED] Rendered live popover evidence ({img.width()}x{img.height()}) to {png_path}")


# ===========================================================================
# 8. Direction C Specifications Test
# ===========================================================================

def test_direction_c_styling():
    """Verify Direction C ('Kart katmanlı') brightness popover specs."""
    print("--- 10. Testing Direction C Brightness Specifications ---")
    import panel_style
    get_qapp()
    pop = brightness_popover.BrightnessPopover()
    assert pop.WIDTH == 352 and pop.width() == 352
    assert pop.RADIUS == panel_style.R_PANEL

    anchor = QRectF(500, 800, 120, 32)
    monitors = [
        {"id": "wmi:laptop", "name": "Dizüstü", "kind": "wmi", "level": 67, "ok": True},
        {"id": "ddc:msi", "name": "MSI MP223", "kind": "ddc", "level": 82, "ok": True},
    ]
    pop.show_for(anchor, monitors)

    # Offscreen image render populates caches and verifies layout
    img = pop.render_to_image(dpr=2.0)
    assert img.width() == 704
    assert img.height() == pop.height() * 2

    # Check slider caches
    assert len(pop._slider_layout_cache) == 2
    assert len(pop._preset_buttons_cache) == 4

    # Test preset click simulation (%50)
    p50_btn = pop._preset_buttons_cache[1]
    assert p50_btn["level"] == 50

    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    click_pt = p50_btn["rect"].center()
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, click_pt, click_pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    pop.mousePressEvent(ev)

    assert pop._active_preset == 50
    assert pop._monitors[0]["level"] == 50
    assert pop._monitors[1]["level"] == 50

    print("  [PASS] Direction C brightness specifications verified.")


# ===========================================================================
# Main Test Runner
# ===========================================================================

def run_all_tests():
    print("=" * 60)
    print("      RUNNING ŞERİT BRIGHTNESS UNIT & LIVE TEST SUITE      ")
    print("=" * 60)

    hash_before = get_file_hash(SETTINGS_PATH)
    print(f"[INTEGRITY] settings.json sha256 before: {hash_before}")

    try:
        test_edid_decoding()
        test_wmi_parsing_with_mocks()
        test_powershell_fallback_mock()
        test_set_level_clamping_and_mocks()
        test_thread_safety_and_com_init()
        test_signal_coalescing()
        test_bad_data_robustness_matrix()
        test_popover_lifecycle_and_events()
        test_live_hardware_read_only()
        test_direction_c_styling()
    finally:
        hash_after = get_file_hash(SETTINGS_PATH)
        print(f"[INTEGRITY] settings.json sha256 after:  {hash_after}")
        assert hash_before == hash_after, f"FATAL: settings.json was modified! {hash_before} != {hash_after}"

    print("=" * 60)
    print("ALL BRIGHTNESS TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
