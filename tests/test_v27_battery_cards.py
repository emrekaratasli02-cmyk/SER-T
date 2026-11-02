"""test_v27_battery_cards.py - Bluetooth cihazlar & Güç modu kartları (v27).

Offscreen test suite for BatteryPanel's two new cards:
1. Bluetooth cihazlar (Card A)
2. Güç modu (Card B)
Pure rendering and signal verification; no OS calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import battery_panel  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
SCRATCH = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/v27-battery")
SCRATCH.mkdir(parents=True, exist_ok=True)

SAMPLE_BAT = {
    "present": True,
    "percent": 82,
    "plugged": False,
    "charging": False,
    "secs_left": 4200,
    "rate_w": 22.5,
    "full_mwh": 51000,
    "design_mwh": 60000,
    "capacity_pct": 85,
    "source": "Windows",
}
SAMPLE_WIFI = {
    "available": True,
    "on": True,
    "connected": True,
    "ssid": "Test_WiFi_5G",
    "signal": 88,
}
SAMPLE_BT_AVAIL = {"available": True, "on": True, "connected_count": 2}


def _mouse_click(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_compute_height_increases() -> None:
    """Kartlar eklendikçe compute_height() değerinin arttığını doğrula."""
    pnl = battery_panel.BatteryPanel()
    h0 = pnl.compute_height()

    # Bluetooth durumu bilinmiyor ve cihaz yokken kart çizilmez
    assert not pnl._should_draw_bt_devices()
    assert pnl.compute_height() == h0

    # Bluetooth açık ama liste boş -> 'Bağlı cihaz yok' kartı eklenir, yükseklik artar
    pnl.set_bluetooth(SAMPLE_BT_AVAIL)
    pnl.set_bt_devices([])
    assert pnl._should_draw_bt_devices()
    h_bt_empty = pnl.compute_height()
    assert h_bt_empty > h0, f"{h_bt_empty} <= {h0}"

    # 2 cihaz eklenince yükseklik daha da artar
    devs_2 = [
        {"name": "Test Kulaklik", "battery": 75, "connected": True, "kind": "audio"},
        {"name": "Test Fare", "battery": None, "connected": True, "kind": "mouse"},
    ]
    pnl.set_bt_devices(devs_2)
    h_bt_2 = pnl.compute_height()
    assert h_bt_2 > h_bt_empty, f"{h_bt_2} <= {h_bt_empty}"

    # 4 cihaz eklenince
    devs_4 = devs_2 + [
        {"name": "Test Klavye", "battery": 90, "connected": True, "kind": "keyboard"},
        {"name": "Test Telefon", "battery": 45, "connected": True, "kind": "phone"},
    ]
    pnl.set_bt_devices(devs_4)
    h_bt_4 = pnl.compute_height()
    assert h_bt_4 > h_bt_2, f"{h_bt_4} <= {h_bt_2}"

    # 1 güç planı varken Güç modu kartı çizilmez (en az 2 plan gerekli)
    pnl.set_power_plans([{"guid": "g1", "name": "Balanced", "active": True}])
    assert not pnl._should_draw_power_plans()
    assert pnl.compute_height() == h_bt_4

    # 2 güç planı -> Güç modu kartı çizilir, yükseklik artar
    pnl.set_power_plans([
        {"guid": "g1", "name": "Balanced", "active": True},
        {"guid": "g2", "name": "Power saver", "active": False},
    ])
    assert pnl._should_draw_power_plans()
    h_plans_2 = pnl.compute_height()
    assert h_plans_2 > h_bt_4, f"{h_plans_2} <= {h_bt_4}"

    # 3 plan (hala 1 satır)
    pnl.set_power_plans([
        {"guid": "g1", "name": "Balanced", "active": True},
        {"guid": "g2", "name": "Power saver", "active": False},
        {"guid": "g3", "name": "High performance", "active": False},
    ])
    h_plans_3 = pnl.compute_height()
    assert h_plans_3 == h_plans_2  # 3 plan tek satırda kalır, yükseklik aynı

    # 4 plan -> 2 satıra sarılır, yükseklik artar
    pnl.set_power_plans([
        {"guid": "g1", "name": "Balanced", "active": True},
        {"guid": "g2", "name": "Power saver", "active": False},
        {"guid": "g3", "name": "High performance", "active": False},
        {"guid": "g4", "name": "Gaming", "active": False},
    ])
    h_plans_4 = pnl.compute_height()
    assert h_plans_4 > h_plans_3, f"{h_plans_4} <= {h_plans_3}"


def test_pill_click_signals() -> None:
    """Hap tıklamasının guid sinyali yayması, aktif hapın yaymaması testi."""
    pnl = battery_panel.BatteryPanel()
    plans = [
        {"guid": "guid-balanced", "name": "Balanced", "active": True},
        {"guid": "guid-saver", "name": "Power saver", "active": False},
        {"guid": "guid-gaming", "name": "Gaming", "active": False},
    ]
    pnl.set_power_plans(plans)
    pnl.render_to_image(2.0)

    assert "plan_0" in pnl._rects
    assert "plan_1" in pnl._rects
    assert "plan_2" in pnl._rects

    emitted: list[str] = []
    pnl.power_plan_requested.connect(emitted.append)

    # Aktif olan hap (plan_0) tıklandığında hiçbir sinyal yayılmamalı
    r0 = pnl._rects["plan_0"]
    pnl.mousePressEvent(_mouse_click(r0.center()))
    assert emitted == [], f"Aktif hap sinyal yaydı: {emitted}"

    pnl.activate("plan_0")
    assert emitted == [], f"Aktif hap activate ile sinyal yaydı: {emitted}"

    # Aktif olmayan hap (plan_1) tıklandığında tam 1 kez guid yayılmalı
    r1 = pnl._rects["plan_1"]
    pnl.mousePressEvent(_mouse_click(r1.center()))
    assert emitted == ["guid-saver"], f"Beklenen ['guid-saver'], gelen {emitted}"

    # Başka bir aktif olmayan hap (plan_2)
    r2 = pnl._rects["plan_2"]
    pnl.mousePressEvent(_mouse_click(r2.center()))
    assert emitted == ["guid-saver", "guid-gaming"], f"Beklenen 2 sinyal, gelen {emitted}"


def test_bad_data_resilience() -> None:
    """Bozuk ve geçersiz verilerin panelde asla hata fırlatmaması."""
    pnl = battery_panel.BatteryPanel()

    # None ve geçersiz veri tipleri
    pnl.set_bt_devices(None)
    pnl.set_power_plans(None)
    pnl.render_to_image(2.0)

    pnl.set_bt_devices("not_a_list")
    pnl.set_power_plans(12345)
    pnl.render_to_image(2.0)

    # Karışık bozuk elemanlar
    bad_devices = [
        None,
        "string",
        42,
        {},
        {"name": None, "battery": "not_int", "connected": None, "kind": None},
        {"name": float("nan"), "battery": float("nan"), "connected": True},
        {"name": "Cok Uzun Aygit Adi " * 20, "battery": 9999, "connected": True},
        {"name": "", "battery": -500, "connected": False},
    ]
    pnl.set_bt_devices(bad_devices)

    bad_plans = [
        None,
        "abc",
        {},
        {"guid": None, "name": None, "active": "yes"},
        {"guid": "", "name": float("nan"), "active": True},
        {"guid": "valid-guid", "name": "Cok Uzun Plan Adi " * 20, "active": False},
    ]
    pnl.set_power_plans(bad_plans)

    # Çizimde hiçbir hata yükselmemeli
    for dpr in (1.0, 1.5, 2.0):
        img = pnl.render_to_image(dpr)
        assert isinstance(img, QImage)
        assert not img.isNull()


def test_three_render_states() -> None:
    """İstenen 3 durumun render edilip scratch dizinine kaydedilmesi."""
    # Durum 1: 2 cihaz + 3 plan
    pnl1 = battery_panel.BatteryPanel()
    pnl1.set_battery(SAMPLE_BAT)
    pnl1.set_wifi(SAMPLE_WIFI)
    pnl1.set_bluetooth(SAMPLE_BT_AVAIL)
    pnl1.set_volume(65.0, False, "Speakers")
    pnl1.set_brightness([{"id": "wmi:l", "name": "Dizüstü", "level": 70, "ok": True}])
    pnl1.set_bt_devices([
        {"name": "Test Kulaklik", "battery": 80, "connected": True, "kind": "audio"},
        {"name": "Test Fare", "battery": None, "connected": True, "kind": "mouse"},
    ])
    pnl1.set_power_plans([
        {"guid": "g-bal", "name": "Balanced", "active": True},
        {"guid": "g-sav", "name": "Power saver", "active": False},
        {"guid": "g-hi", "name": "High performance", "active": False},
    ])
    img1 = pnl1.render_to_image(2.0)
    p1 = SCRATCH / "state1_2devices_3plans.png"
    ok1 = img1.save(str(p1))
    assert ok1 and p1.exists(), f"State 1 kaydedilemedi: {p1}"

    # Durum 2: Boş cihazlar + 2 plan (BT açık)
    pnl2 = battery_panel.BatteryPanel()
    pnl2.set_battery(SAMPLE_BAT)
    pnl2.set_wifi(SAMPLE_WIFI)
    pnl2.set_bluetooth(SAMPLE_BT_AVAIL)
    pnl2.set_volume(40.0, False, "Speakers")
    pnl2.set_brightness([{"id": "wmi:l", "name": "Dizüstü", "level": 50, "ok": True}])
    pnl2.set_bt_devices([])
    pnl2.set_power_plans([
        {"guid": "g-bal", "name": "Balanced", "active": False},
        {"guid": "g-sav", "name": "Power saver", "active": True},
    ])
    img2 = pnl2.render_to_image(2.0)
    p2 = SCRATCH / "state2_empty_devices_2plans.png"
    ok2 = img2.save(str(p2))
    assert ok2 and p2.exists(), f"State 2 kaydedilemedi: {p2}"

    # Durum 3: Veri yok
    pnl3 = battery_panel.BatteryPanel()
    img3 = pnl3.render_to_image(2.0)
    p3 = SCRATCH / "state3_no_data.png"
    ok3 = img3.save(str(p3))
    assert ok3 and p3.exists(), f"State 3 kaydedilemedi: {p3}"


def run_all() -> None:
    test_compute_height_increases()
    print("  [PASS] test_compute_height_increases")
    test_pill_click_signals()
    print("  [PASS] test_pill_click_signals")
    test_bad_data_resilience()
    print("  [PASS] test_bad_data_resilience")
    test_three_render_states()
    print("  [PASS] test_three_render_states")
    print("ALL TEST_V27_BATTERY_CARDS TESTS PASSED")


if __name__ == "__main__":
    run_all()
