"""test_v27_bt_devices.py - Bluetooth cihaz sorgulama modülü birim testleri.

Testler tamamen yapay / sahte veriler kullanır (gerçek cihaz adı veya MAC içermez).
Gerçek makinede çalıştırma testi yalnızca çalışma süresini (<500 ms) ve
veri şemasını doğrular; belirli bir cihazın varlığını zorunlu tutmaz.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

os.environ["SERIT_TEST"] = "1"
_tmp_dir = tempfile.mkdtemp(prefix="serit-test-bt-")
os.environ["SERIT_LOG"] = str(Path(_tmp_dir) / "test.log")
os.environ["SERIT_CACHE_DIR"] = _tmp_dir

import bt_devices  # noqa: E402


def test_classify_kind() -> None:
    """classify_kind fonksiyonunun cihaz türlerini doğru sınıflandırdığını test eder."""
    # Telefon anahtar kelimeleri: iPhone, Android, Galaxy, Pixel
    assert bt_devices.classify_kind("Mock iPhone Device") == "phone"
    assert bt_devices.classify_kind("Sample Android Unit") == "phone"
    assert bt_devices.classify_kind("Test Galaxy Terminal") == "phone"
    assert bt_devices.classify_kind("Pixel Mock Handset") == "phone"

    # Saat anahtar kelimeleri: WATCH, Band, Watch
    assert bt_devices.classify_kind("Sample WATCH Model X") == "watch"
    assert bt_devices.classify_kind("Fitness Band Ultra") == "watch"
    assert bt_devices.classify_kind("Classic Smart Watch") == "watch"

    # Kulaklık anahtar kelimeleri: AirPods, Buds, Headphone, WH-, WF-
    assert bt_devices.classify_kind("AirPods Fake Pro") == "headset"
    assert bt_devices.classify_kind("Wireless Audio Buds") == "headset"
    assert bt_devices.classify_kind("Studio Headphone 3000") == "headset"
    assert bt_devices.classify_kind("Stereo WH-999X") == "headset"
    assert bt_devices.classify_kind("In-Ear WF-888Y") == "headset"

    # Varsayılan tür: device
    assert bt_devices.classify_kind("Generic Wireless Mouse") == "device"
    assert bt_devices.classify_kind("Office Keyboard") == "device"
    assert bt_devices.classify_kind("") == "device"


def test_merge_devices_by_mac() -> None:
    """Aynı MAC adresine sahip farklı kayıtların (BLE ve Standart BT) doğru birleştirildiğini test eder."""
    raw = [
        {
            "id": r"BTHLE\Dev_001122334455\1&234",
            "name": "Mock Smart Watch",
            "battery": 75,
            "connected": True,
            "mac": "001122334455",
        },
        {
            "id": r"BTHENUM\Dev_001122334455\5&678",
            "name": "Mock Smart Watch",
            "battery": None,
            "connected": False,
            "mac": "001122334455",
        },
    ]
    merged = bt_devices.merge_devices(raw)
    assert len(merged) == 1
    dev = merged[0]
    assert dev["name"] == "Mock Smart Watch"
    assert dev["battery"] == 75
    assert dev["connected"] is True
    assert dev["kind"] == "watch"


def test_merge_devices_by_name() -> None:
    """Farklı MAC sonekine sahip ancak aynı ada sahip kayıtların birleştirilmesini test eder."""
    raw = [
        {
            "id": r"BTHLE\Dev_aabbcc001122\1&2",
            "name": "Mock Handset",
            "battery": 82,
            "connected": False,
            "mac": "aabbcc001122",
        },
        {
            "id": r"BTHENUM\Dev_ddeeff334455\3&4",
            "name": "Mock Handset",
            "battery": None,
            "connected": True,
            "mac": "ddeeff334455",
        },
    ]
    merged = bt_devices.merge_devices(raw)
    assert len(merged) == 1
    dev = merged[0]
    assert dev["name"] == "Mock Handset"
    assert dev["battery"] == 82
    assert dev["connected"] is True


def test_merge_devices_battery_none_handling() -> None:
    """Pili olmayan cihazlarda battery değerinin None olarak kalmasını test eder."""
    raw = [
        {
            "id": r"BTHENUM\Dev_112233445566\1&2",
            "name": "Mock Earphones",
            "battery": None,
            "connected": True,
            "mac": "112233445566",
        },
    ]
    merged = bt_devices.merge_devices(raw)
    assert len(merged) == 1
    assert merged[0]["battery"] is None
    assert merged[0]["connected"] is True


def test_merge_devices_transitive() -> None:
    """Aynı cihazı zincirleme (A=B MAC ile, B=C isim ile) bağlayan kayıtların birleştiğini test eder."""
    raw = [
        {
            "id": r"BTHLE\Dev_aaaa11112222\1",
            "name": "Alpha Model",
            "battery": None,
            "connected": False,
            "mac": "aaaa11112222",
        },
        {
            "id": r"BTHENUM\Dev_aaaa11112222\2",
            "name": "Alpha Friendly",
            "battery": 55,
            "connected": False,
            "mac": "aaaa11112222",
        },
        {
            "id": r"BTHENUM\Dev_bbbb33334444\3",
            "name": "Alpha Friendly",
            "battery": None,
            "connected": True,
            "mac": "bbbb33334444",
        },
    ]
    merged = bt_devices.merge_devices(raw)
    assert len(merged) == 1
    assert merged[0]["battery"] == 55
    assert merged[0]["connected"] is True


def test_live_list_bt_devices_performance_and_schema() -> None:
    """Gerçek makinede list_bt_devices çağrısının istisna fırlatmadığını ve <500 ms döndüğünü test eder."""
    t0 = time.perf_counter()
    devices = bt_devices.list_bt_devices(only_connected=True)
    dur_ms = (time.perf_counter() - t0) * 1000.0

    print(f"list_bt_devices execution time: {dur_ms:.2f} ms (device count: {len(devices)})")
    assert dur_ms < 500.0, f"list_bt_devices çok yavaş: {dur_ms:.2f} ms >= 500 ms"

    # Şema ve veri doğrulaması (cihaz ismi kontrol edilmez - gizlilik ve taşınabilirlik)
    has_battery_section = True
    for d in devices:
        assert isinstance(d["name"], str)
        assert len(d["name"]) > 0
        assert d["connected"] is True
        assert d["kind"] in {"phone", "watch", "headset", "device"}
        if d["battery"] is not None:
            assert isinstance(d["battery"], int)
            assert 0 <= d["battery"] <= 100
            assert has_battery_section, "Pili olan cihazlar pilsiz olanlardan önce gelmeli"
        else:
            has_battery_section = False


def main() -> int:
    tests = [
        test_classify_kind,
        test_merge_devices_by_mac,
        test_merge_devices_by_name,
        test_merge_devices_battery_none_handling,
        test_merge_devices_transitive,
        test_live_list_bt_devices_performance_and_schema,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
