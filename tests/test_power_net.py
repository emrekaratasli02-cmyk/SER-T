"""tests/test_power_net.py - Unit and live read-only tests for power_net.py.

Covers:
  1. Pure netsh WLAN parser (English connected, Turkish connected, disconnected,
     radio hardware/software off, no-adapter EN/TR).
  2. Battery capacity maths (48686 / 61538 -> 79) and unknown/None preservation.
  3. Test guards raising RuntimeError for set_wifi, set_bluetooth, and open_settings.
  4. Mocked set_wifi, set_bluetooth, and open_settings behavior when guard is bypassed.
  5. Live read-only checks and timing benchmarks for battery_info, wifi_info,
     bluetooth_info, and radio_toggle_supported.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import power_net


# ==============================================================================
# 1. SAMPLE NETSH OUTPUTS & PURE PARSER TESTS
# ==============================================================================

NETSH_EN_CONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : f2b60bb5-0865-4401-92fa-e17f876d2e1f
    Physical address       : 40:c7:3c:99:b8:a3
    Interface type         : Primary
    State                  : connected
    SSID                   : Karatasli_5G
    AP BSSID               : 6c:e8:73:5d:31:25
    Band                   : 5 GHz
    Channel                : 36
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
    Receive rate (Mbps)    : 526.5
    Transmit rate (Mbps)   : 468
    Signal                 : 61%
    Rssi                   : -68
    Profile                : Karatasli_5G
"""

NETSH_TR_CONNECTED = """
Sistemde 1 arabirim var:

    Ad                     : Wi-Fi
    Açıklama               : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : f2b60bb5-0865-4401-92fa-e17f876d2e1f
    Fiziksel adres         : 40:c7:3c:99:b8:a3
    Durum                  : bağlandı
    SSID                   : EvAgi_Fiber
    BSSID                  : 11:22:33:44:55:66
    Ağ türü                : Altyapı
    Radyo türü             : 802.11ax
    Sinyal                 : 88%
    Profil                 : EvAgi_Fiber
"""

NETSH_EN_DISCONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : f2b60bb5-0865-4401-92fa-e17f876d2e1f
    Physical address       : 40:c7:3c:99:b8:a3
    State                  : disconnected
    Radio status           : Hardware On
                             Software On
"""

NETSH_TR_DISCONNECTED_RADIO_OFF = """
Sistemde 1 arabirim var:

    Ad                     : Wi-Fi
    Açıklama               : Intel(R) Wi-Fi 6 AX201 160MHz
    Durum                  : bağlantı kesildi
    Radyo durumu           : Donanım Açık
                             Yazılım Kapalı
"""

NETSH_TR_DISCONNECTED_UNKNOWN_RADIO = """
Sistemde 1 arabirim var:

    Ad                     : Wi-Fi
    Açıklama               : Intel(R) Wi-Fi 6 AX201 160MHz
    Durum                  : bağlı değil
"""

NETSH_NO_ADAPTER_EN = "There is no wireless interface on the system."
NETSH_NO_ADAPTER_TR = "Sistemde kablosuz arabirim yok."


def test_netsh_parser() -> None:
    print("Testing pure netsh WLAN parser (EN/TR/disconnected/no-adapter)...")

    r_en = power_net.parse_netsh_wlan_interfaces(NETSH_EN_CONNECTED)
    assert r_en == {
        "available": True,
        "on": True,
        "connected": True,
        "ssid": "Karatasli_5G",
        "signal": 61,
    }, f"Unexpected EN connected result: {r_en}"

    r_tr = power_net.parse_netsh_wlan_interfaces(NETSH_TR_CONNECTED)
    assert r_tr == {
        "available": True,
        "on": True,
        "connected": True,
        "ssid": "EvAgi_Fiber",
        "signal": 88,
    }, f"Unexpected TR connected result: {r_tr}"

    r_disc = power_net.parse_netsh_wlan_interfaces(NETSH_EN_DISCONNECTED)
    assert r_disc == {
        "available": True,
        "on": True,
        "connected": False,
        "ssid": None,
        "signal": None,
    }, f"Unexpected EN disconnected result: {r_disc}"

    r_off = power_net.parse_netsh_wlan_interfaces(NETSH_TR_DISCONNECTED_RADIO_OFF)
    assert r_off == {
        "available": True,
        "on": False,
        "connected": False,
        "ssid": None,
        "signal": None,
    }, f"Unexpected TR radio-off result: {r_off}"

    r_unk = power_net.parse_netsh_wlan_interfaces(NETSH_TR_DISCONNECTED_UNKNOWN_RADIO)
    assert r_unk == {
        "available": True,
        "on": None,
        "connected": False,
        "ssid": None,
        "signal": None,
    }, f"Unexpected TR unknown-radio result: {r_unk}"

    for empty_sample in (NETSH_NO_ADAPTER_EN, NETSH_NO_ADAPTER_TR, "", "   "):
        r_none = power_net.parse_netsh_wlan_interfaces(empty_sample)
        assert r_none == {
            "available": False,
            "on": None,
            "connected": False,
            "ssid": None,
            "signal": None,
        }, f"Unexpected no-adapter result for {empty_sample!r}: {r_none}"

    print("  [OK] Pure netsh parser passed.")


# ==============================================================================
# 2. CAPACITY MATHS & UNKNOWN VALUES TESTS
# ==============================================================================

def test_capacity_maths_and_unknowns() -> None:
    print("Testing battery capacity maths and unknown value preservation...")

    # Exact requirement: 48686 / 61538 -> 79
    assert power_net._compute_capacity_pct(48686, 61538) == 79
    assert power_net._compute_capacity_pct(61538, 61538) == 100
    assert power_net._compute_capacity_pct(None, 61538) is None
    assert power_net._compute_capacity_pct(48686, None) is None
    assert power_net._compute_capacity_pct(48686, 0) is None
    assert power_net._compute_capacity_pct(0, 61538) is None
    assert power_net._compute_capacity_pct(-100, 61538) is None

    # Unknown battery values stay None when hardware/WMI returns nothing
    with patch.object(power_net.psutil, "sensors_battery", return_value=None), \
         patch.object(power_net, "_read_wmi_battery_status", return_value=(None, None, None, False)):
        b_none = power_net.battery_info()
        assert b_none == {
            "present": False,
            "percent": None,
            "plugged": None,
            "charging": None,
            "secs_left": None,
            "rate_w": None,
            "full_mwh": None,
            "design_mwh": None,
            "capacity_pct": None,
            "source": "Windows",
        }
        assert "cycle_count" not in b_none

    # Unlimited / unknown secsleft becomes None
    class FakeSBattery:
        percent = 55
        power_plugged = True
        secsleft = power_net.psutil.POWER_TIME_UNLIMITED

    with patch.object(power_net.psutil, "sensors_battery", return_value=FakeSBattery()), \
         patch.object(power_net, "_read_wmi_battery_status", return_value=(True, None, None, True)), \
         patch.object(power_net, "_read_wmi_battery_capacities", return_value=(None, None)):
        b_partial = power_net.battery_info()
        assert b_partial["present"] is True
        assert b_partial["percent"] == 55
        assert b_partial["plugged"] is True
        assert b_partial["charging"] is None
        assert b_partial["secs_left"] is None
        assert b_partial["rate_w"] is None
        assert b_partial["full_mwh"] is None
        assert b_partial["design_mwh"] is None
        assert b_partial["capacity_pct"] is None

    # Bluetooth unknown 'on' and 'connected_count' remain None when WinRT is absent
    with patch.object(power_net, "_bluetooth_info_winrt", return_value=None), \
         patch.object(power_net, "_bluetooth_pnp_available", return_value=True):
        bt = power_net.bluetooth_info()
        assert bt == {"available": True, "on": None, "connected_count": None}

    print("  [OK] Capacity maths and unknown preservation passed.")


# ==============================================================================
# 3. TEST GUARDS & MOCKED CONTROLS
# ==============================================================================

def test_guards_raise_under_test() -> None:
    print("Testing test-mode guards on set_wifi, set_bluetooth, and open_settings...")

    guarded_calls = [
        (power_net.set_wifi, (True,)),
        (power_net.set_wifi, (False,)),
        (power_net.set_bluetooth, (True,)),
        (power_net.set_bluetooth, (False,)),
        (power_net.open_settings, ("wifi",)),
        (power_net.open_settings, ("bluetooth",)),
        (power_net.open_settings, ("battery",)),
        (power_net.open_settings, ("power",)),
    ]
    for fn, args in guarded_calls:
        try:
            fn(*args)
        except RuntimeError:
            continue
        raise AssertionError(f"{fn.__name__}{args} did not raise RuntimeError under test!")

    print("  [OK] All mutating/UI functions raised RuntimeError under test.")


def test_mocked_toggles_and_open_settings() -> None:
    print("Testing mocked set_wifi, set_bluetooth, and open_settings (guard patched)...")

    opened_uris = []

    with patch.object(power_net, "_guard_real_power_net", lambda what: None), \
         patch.object(power_net.os, "startfile", side_effect=opened_uris.append, create=True):
        for page, expected_uri in [
            ("wifi", "ms-settings:network-wifi"),
            ("bluetooth", "ms-settings:bluetooth"),
            ("battery", "ms-settings:batterysaver"),
            ("power", "ms-settings:powersleep"),
        ]:
            assert power_net.open_settings(page) is True
            assert opened_uris[-1] == expected_uri

        assert power_net.open_settings("invalid_page") is False
        assert len(opened_uris) == 4

    with patch.object(power_net, "_guard_real_power_net", lambda what: None), \
         patch.object(power_net, "_set_radio_state_winrt", return_value=False) as mock_toggle:
        assert power_net.set_wifi(True) is False
        mock_toggle.assert_called_with("WI_FI", True)
        assert power_net.set_bluetooth(False) is False
        mock_toggle.assert_called_with("BLUETOOTH", False)

    print("  [OK] Mocked controls and settings launcher passed.")


# ==============================================================================
# 4. LIVE READ-ONLY CALLS & PERFORMANCE TIMINGS
# ==============================================================================

def test_live_read_only_and_timings() -> None:
    print("\n--- LIVE READ-ONLY CALLS & TIMINGS ---")

    # 1. Cold battery_info
    t0 = time.perf_counter()
    bat_cold = power_net.battery_info()
    bat_cold_ms = (time.perf_counter() - t0) * 1000.0
    print(f"battery_info (cold): {bat_cold_ms:.2f} ms -> {bat_cold}")

    expected_bat_keys = {
        "present",
        "percent",
        "plugged",
        "charging",
        "secs_left",
        "rate_w",
        "full_mwh",
        "design_mwh",
        "capacity_pct",
        "source",
    }
    assert set(bat_cold.keys()) == expected_bat_keys, f"Key mismatch: {bat_cold.keys()}"
    assert "cycle_count" not in bat_cold
    assert bat_cold["source"] == "Windows"
    assert isinstance(bat_cold["present"], bool)
    assert bat_cold_ms < 1500.0, f"Cold battery_info took {bat_cold_ms:.2f} ms (> 1500 ms)"

    # 2. Warm battery_info (cached capacities)
    warm_bat_times = []
    for _ in range(3):
        t0 = time.perf_counter()
        bat_warm = power_net.battery_info()
        warm_bat_times.append((time.perf_counter() - t0) * 1000.0)
        assert bat_warm["present"] == bat_cold["present"]
    avg_bat_warm_ms = sum(warm_bat_times) / len(warm_bat_times)
    print(f"battery_info (warm avg): {avg_bat_warm_ms:.2f} ms (runs: {[round(x, 2) for x in warm_bat_times]} ms)")
    assert avg_bat_warm_ms < 300.0, f"Warm battery_info took {avg_bat_warm_ms:.2f} ms (> 300 ms)"

    # 3. wifi_info
    t0 = time.perf_counter()
    wifi_cold = power_net.wifi_info()
    wifi_cold_ms = (time.perf_counter() - t0) * 1000.0
    print(f"wifi_info (cold): {wifi_cold_ms:.2f} ms -> {wifi_cold}")

    expected_wifi_keys = {"available", "on", "connected", "ssid", "signal"}
    assert set(wifi_cold.keys()) == expected_wifi_keys, f"Key mismatch: {wifi_cold.keys()}"
    assert isinstance(wifi_cold["available"], bool)
    assert isinstance(wifi_cold["connected"], bool)
    assert wifi_cold_ms < 1500.0, f"Cold wifi_info took {wifi_cold_ms:.2f} ms (> 1500 ms)"

    t0 = time.perf_counter()
    wifi_warm = power_net.wifi_info()
    wifi_warm_ms = (time.perf_counter() - t0) * 1000.0
    print(f"wifi_info (warm): {wifi_warm_ms:.2f} ms -> {wifi_warm}")
    assert wifi_warm_ms < 1500.0, f"Warm wifi_info took {wifi_warm_ms:.2f} ms (> 1500 ms)"

    # 4. bluetooth_info
    t0 = time.perf_counter()
    bt_info = power_net.bluetooth_info()
    bt_ms = (time.perf_counter() - t0) * 1000.0
    print(f"bluetooth_info: {bt_ms:.2f} ms -> {bt_info}")

    expected_bt_keys = {"available", "on", "connected_count"}
    assert set(bt_info.keys()) == expected_bt_keys, f"Key mismatch: {bt_info.keys()}"
    assert isinstance(bt_info["available"], bool)
    assert bt_ms < 1500.0, f"bluetooth_info took {bt_ms:.2f} ms (> 1500 ms)"

    # 5. radio_toggle_supported
    toggle_sup = power_net.radio_toggle_supported()
    print(f"radio_toggle_supported -> {toggle_sup}")
    assert set(toggle_sup.keys()) == {"wifi", "bluetooth", "reason"}
    assert isinstance(toggle_sup["wifi"], bool)
    assert isinstance(toggle_sup["bluetooth"], bool)
    assert isinstance(toggle_sup["reason"], str) and toggle_sup["reason"]

    print("  [OK] Live read-only checks and timing benchmarks passed.")


def main() -> int:
    print("=" * 60)
    print("  ŞERİT POWER & NETWORK BACKEND TEST SUITE")
    print("=" * 60)

    test_netsh_parser()
    test_capacity_maths_and_unknowns()
    test_guards_raise_under_test()
    test_mocked_toggles_and_open_settings()
    test_live_read_only_and_timings()

    print("\n" + "=" * 60)
    print("  ALL POWER & NETWORK TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
