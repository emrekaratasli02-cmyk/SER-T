"""test_v26_netspeed.py - Ağ hızı ölçer ve gösterge çubuğu birim testleri.

Testler tamamen yapay / örnek veriler kullanır. Gerçek donanım durumuna dokunmaz.
"""
from __future__ import annotations

import collections
import os
from pathlib import Path
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SERIT_TEST"] = "1"
_tmp_dir = tempfile.mkdtemp(prefix="serit-test-netspeed-")
os.environ["SERIT_LOG"] = str(Path(_tmp_dir) / "test.log")
os.environ["SERIT_CACHE_DIR"] = _tmp_dir

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import netspeed  # noqa: E402

app = QApplication.instance() or QApplication([])

_NicStat = collections.namedtuple("_NicStat", ["isup"])
_NicIO = collections.namedtuple("_NicIO", ["bytes_sent", "bytes_recv"])


def test_fmt_rate() -> None:
    assert netspeed.fmt_rate(None) == "—"
    assert netspeed.fmt_rate(0) == "0 KB/s"
    assert netspeed.fmt_rate(-50) == "0 KB/s"
    assert netspeed.fmt_rate(450) == "0 KB/s"
    assert netspeed.fmt_rate(50_000) == "50 KB/s"
    assert netspeed.fmt_rate(999_000) == "999 KB/s"
    assert netspeed.fmt_rate(999_499) == "999 KB/s"
    assert netspeed.fmt_rate(1_000_000) == "1,0 MB/s"
    assert netspeed.fmt_rate(1_400_000) == "1,4 MB/s"
    assert netspeed.fmt_rate(12_400_000) == "12,4 MB/s"
    assert netspeed.fmt_rate(99_900_000) == "99,9 MB/s"
    assert netspeed.fmt_rate(100_000_000) == "100 MB/s"
    assert netspeed.fmt_rate(123_000_000) == "123 MB/s"


def test_meter_first_sample_none() -> None:
    t = 100.0
    counters = {"Ethernet": _NicIO(bytes_sent=10_000, bytes_recv=20_000)}

    meter = netspeed.NetSpeedMeter(
        counters_fn=lambda: counters,
        clock=lambda: t,
        stats_fn=lambda: {"Ethernet": _NicStat(isup=True)},
    )
    res = meter.sample()
    assert res["down"] is None
    assert res["up"] is None
    assert res["t"] == 100.0
    assert res["visible"] is False


def test_meter_normal_rates() -> None:
    t = 100.0
    counters = {"Ethernet": _NicIO(bytes_sent=10_000, bytes_recv=20_000)}

    meter = netspeed.NetSpeedMeter(
        counters_fn=lambda: counters,
        clock=lambda: t,
        stats_fn=lambda: {"Ethernet": _NicStat(isup=True)},
    )
    meter.sample()

    # 2 sn sonra: indirme +160.000 B (80 KB/s), yukleme +24.000 B (12 KB/s)
    t = 102.0
    counters = {"Ethernet": _NicIO(bytes_sent=34_000, bytes_recv=180_000)}
    res = meter.sample()
    assert res["down"] == 80_000.0
    assert res["up"] == 12_000.0
    assert res["t"] == 102.0
    assert res["visible"] is True  # 80 KB/s >= 50 KB/s


def test_meter_wrap_resets_to_none() -> None:
    t = 100.0
    counters = {"Ethernet": _NicIO(bytes_sent=50_000, bytes_recv=100_000)}

    meter = netspeed.NetSpeedMeter(
        counters_fn=lambda: counters,
        clock=lambda: t,
        stats_fn=lambda: {"Ethernet": _NicStat(isup=True)},
    )
    meter.sample()

    # Sayaç sıfırlandı / küçüldü (wrap)
    t = 102.0
    counters = {"Ethernet": _NicIO(bytes_sent=1_000, bytes_recv=2_000)}
    res = meter.sample()
    assert res["down"] is None
    assert res["up"] is None

    # Sonraki örnek normal devam eder
    t = 104.0
    counters = {"Ethernet": _NicIO(bytes_sent=11_000, bytes_recv=12_000)}
    res2 = meter.sample()
    assert res2["down"] == 5_000.0
    assert res2["up"] == 5_000.0


def test_meter_virtual_nics_excluded() -> None:
    t = 100.0
    counters = {
        "Ethernet": _NicIO(bytes_sent=1_000, bytes_recv=2_000),
        "vEthernet (WSL)": _NicIO(bytes_sent=999_999, bytes_recv=999_999),
        "VirtualBox Host-Only": _NicIO(bytes_sent=888_888, bytes_recv=888_888),
        "Loopback Pseudo-Interface 1": _NicIO(bytes_sent=777_777, bytes_recv=777_777),
        "Bluetooth Device": _NicIO(bytes_sent=666_666, bytes_recv=666_666),
    }

    meter = netspeed.NetSpeedMeter(
        counters_fn=lambda: counters,
        clock=lambda: t,
        stats_fn=lambda: {k: _NicStat(isup=True) for k in counters},
    )
    meter.sample()

    t = 102.0
    # Yalnızca Ethernet 10.000 B arttı; sanallar çok artsa bile yok sayılmalı
    counters = {
        "Ethernet": _NicIO(bytes_sent=11_000, bytes_recv=22_000),
        "vEthernet (WSL)": _NicIO(bytes_sent=2_000_000, bytes_recv=2_000_000),
        "VirtualBox Host-Only": _NicIO(bytes_sent=2_000_000, bytes_recv=2_000_000),
        "Loopback Pseudo-Interface 1": _NicIO(bytes_sent=2_000_000, bytes_recv=2_000_000),
        "Bluetooth Device": _NicIO(bytes_sent=2_000_000, bytes_recv=2_000_000),
    }
    res = meter.sample()
    assert res["down"] == 10_000.0
    assert res["up"] == 5_000.0


def test_meter_down_nic_excluded() -> None:
    t = 100.0
    counters = {
        "Wi-Fi": _NicIO(bytes_sent=1_000, bytes_recv=2_000),
        "Ethernet": _NicIO(bytes_sent=10_000, bytes_recv=20_000),
    }
    stats = {
        "Wi-Fi": _NicStat(isup=True),
        "Ethernet": _NicStat(isup=False),  # Kablo takılı değil
    }

    meter = netspeed.NetSpeedMeter(
        counters_fn=lambda: counters,
        clock=lambda: t,
        stats_fn=lambda: stats,
    )
    meter.sample()

    t = 101.0
    counters = {
        "Wi-Fi": _NicIO(bytes_sent=2_000, bytes_recv=4_000),
        "Ethernet": _NicIO(bytes_sent=50_000, bytes_recv=80_000),
    }
    res = meter.sample()
    # Yalnızca Wi-Fi dahil edilmeli: down=2000 B/s, up=1000 B/s
    assert res["down"] == 2_000.0
    assert res["up"] == 1_000.0


def test_hysteresis_on_off() -> None:
    # 1. Başlangıçta görünmezken 50 KB/s altına tepki vermez
    s = {"down": 20_000, "up": 10_000}
    assert netspeed.should_show(s, was_visible=False) is False

    s = {"down": 49_000, "up": 10_000}
    assert netspeed.should_show(s, was_visible=False) is False

    # 2. 50 KB/s ve üzeri görünür yapar
    s = {"down": 50_000, "up": 1_000}
    assert netspeed.should_show(s, was_visible=False) is True

    # 3. Görünürken 30-50 KB/s arasında kalırsa açık kalır
    s = {"down": 35_000, "up": 5_000}
    assert netspeed.should_show(s, was_visible=True) is True

    # 4. 30 KB/s altına indiğinde ilk 2 örnekte açık kalır, 3. örnekte kapanır
    s1 = {"down": 25_000, "up": 5_000}
    assert netspeed.should_show(s1, was_visible=True) is True  # 1. alt örnek

    s2 = {"down": 20_000, "up": 4_000}
    assert netspeed.should_show(s2, was_visible=True) is True  # 2. alt örnek

    s3 = {"down": 10_000, "up": 2_000}
    assert netspeed.should_show(s3, was_visible=True) is False  # 3. alt örnek -> kapandı

    # 5. Kapandıktan sonra 30 KB/s altında kalmaya devam ederse kapalı kalır
    s4 = {"down": 15_000, "up": 1_000}
    assert netspeed.should_show(s4, was_visible=False) is False

    # 6. Tekrar açılmak için 50 KB/s gerekir
    s5 = {"down": 45_000, "up": 0}
    assert netspeed.should_show(s5, was_visible=False) is False

    s6 = {"down": 55_000, "up": 0}
    assert netspeed.should_show(s6, was_visible=False) is True


def test_band_width_constant_across_values() -> None:
    w1 = netspeed.band_width({"down": 1_000, "up": 1_000, "visible": True})
    w2 = netspeed.band_width({"down": 999_000, "up": 100_000, "visible": True})
    w3 = netspeed.band_width({"down": 12_400_000, "up": 1_100_000, "visible": True})
    w4 = netspeed.band_width({"down": 123_000_000, "up": 80_000_000, "visible": True})
    assert w1 == w2 == w3 == w4 > 0.0

    # Görünmüyorken 0.0
    assert netspeed.band_width({"visible": False}) == 0.0
    assert netspeed.band_width(None) == 0.0
    assert netspeed.band_width({}) == 0.0
    assert netspeed.band_width({"down": None, "up": None}) == 0.0


def test_draw_offscreen_without_exceptions() -> None:
    img = QImage(120, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    rect = QRectF(0.0, 0.0, 120.0, 40.0)

    # None değerleri
    netspeed.draw_net_band(p, rect, {"down": None, "up": None, "visible": True})

    # Normal değerler
    netspeed.draw_net_band(p, rect, {"down": 80_000, "up": 12_000, "visible": True}, hover=False)
    netspeed.draw_net_band(p, rect, {"down": 12_400_000, "up": 1_100_000, "visible": True}, hover=True)

    # Görünmez ve boş durumlar
    netspeed.draw_net_band(p, rect, {"visible": False})
    netspeed.draw_net_band(p, rect, None)
    netspeed.draw_net_band(p, rect, {})

    p.end()


def test_tooltip() -> None:
    state = {"down": 1_400_000, "up": 120_000}
    tip = netspeed.tooltip(state)
    assert "İndirme: 1,4 MB/s" in tip
    assert "Yükleme: 120 KB/s" in tip
    assert "Kaynak: Windows ağ sayaçları (psutil), 2 sn" in tip

    # None değerleriyle kontrol
    tip_none = netspeed.tooltip(None)
    assert "İndirme: —" in tip_none
    assert "Yükleme: —" in tip_none


def main() -> int:
    tests = [
        test_fmt_rate,
        test_meter_first_sample_none,
        test_meter_normal_rates,
        test_meter_wrap_resets_to_none,
        test_meter_virtual_nics_excluded,
        test_meter_down_nic_excluded,
        test_hysteresis_on_off,
        test_band_width_constant_across_values,
        test_draw_offscreen_without_exceptions,
        test_tooltip,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
