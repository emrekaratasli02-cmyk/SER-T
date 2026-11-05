"""test_v33_media_output_device.py - MediaPanel ses cikis cihazi degistirici birim testleri."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import media_panel as mp  # noqa: E402


MOCK_DEVICES = [
    {
        "id": "{0.0.0.00000000}.{8067c1b7-8589-4363-aa66-05f3f22f89cf}",
        "name": "Speakers (Realtek(R) Audio)",
        "default": True,
    },
    {
        "id": "{0.0.0.00000000}.{d7267e5b-9c67-4de8-a39f-3f1271660de2}",
        "name": "MSI MP223 (NVIDIA High Definition Audio)",
        "default": False,
    },
    {
        "id": "{0.0.0.00000000}.{cf92534c-3d67-4602-bac6-23a4103aab83}",
        "name": "Headphones (AirPods)",
        "default": False,
    },
]


def test_media_panel_device_set_and_get() -> None:
    """set_devices ve get_active_device davranisini dogrula."""
    pnl = mp.MediaPanel()
    pnl.set_devices(MOCK_DEVICES)

    active = pnl.get_active_device()
    assert active is not None
    assert active["name"] == "Speakers (Realtek(R) Audio)"
    assert active["default"] is True
    assert pnl._vol_device == "Speakers (Realtek(R) Audio)"

    # ID ile belirleme
    target_id = MOCK_DEVICES[1]["id"]
    ok = pnl.set_active_device_by_id(target_id)
    assert ok is True
    assert pnl._active_device_id == target_id
    assert pnl.get_active_device()["name"] == MOCK_DEVICES[1]["name"]

    pnl.close()


def test_media_panel_device_cycling_and_signals() -> None:
    """switch_device(+1/-1) dongusunu ve device_switch_requested sinyalini dogrula."""
    pnl = mp.MediaPanel()
    pnl.set_devices(MOCK_DEVICES)

    emitted_ids = []
    pnl.device_switch_requested.connect(emitted_ids.append)

    # Baslangic: index 0 (Speakers)
    # +1 adim -> index 1 (MSI MP223)
    d1 = pnl.switch_device(1)
    assert d1["name"] == "MSI MP223 (NVIDIA High Definition Audio)"
    assert emitted_ids[-1] == MOCK_DEVICES[1]["id"]

    # +1 adim -> index 2 (Headphones AirPods)
    d2 = pnl.switch_device(1)
    assert d2["name"] == "Headphones (AirPods)"
    assert emitted_ids[-1] == MOCK_DEVICES[2]["id"]

    # +1 adim -> wrap-around basa don (index 0 Speakers)
    d0 = pnl.switch_device(1)
    assert d0["name"] == "Speakers (Realtek(R) Audio)"
    assert emitted_ids[-1] == MOCK_DEVICES[0]["id"]

    # -1 adim -> wrap-around sona don (index 2 Headphones)
    d_back = pnl.switch_device(-1)
    assert d_back["name"] == "Headphones (AirPods)"
    assert emitted_ids[-1] == MOCK_DEVICES[2]["id"]

    pnl.close()


def test_media_panel_device_hit_testing_and_activation() -> None:
    """Hit-test ve activate cagrilari uzerinden mini buton ve cip etkilesimini dogrula."""
    pnl = mp.MediaPanel()
    pnl.set_devices(MOCK_DEVICES)

    for key in ("dev_prev", "dev_chip", "dev_next", "mixer_link"):
        assert key in pnl._rects, f"{key} rects icinde bulunamadi"
        r = pnl._rects[key]
        assert r.width() > 10.0
        assert r.height() > 10.0
        assert pnl._hit(r.center()) == key, f"Hit test {key} icin basarisiz oldu"

    # dev_prev butonuna basinca onceki cihaza gecmeli
    cur = pnl.get_active_device()
    pnl.activate("dev_prev")
    next_dev = pnl.get_active_device()
    assert cur["id"] != next_dev["id"]

    # dev_next butonuna basinca sonraki cihaza gecmeli
    pnl.activate("dev_next")
    assert pnl.get_active_device()["id"] == cur["id"]

    # dev_chip butonuna basinca da click-ofmux gibi sonraki cihaza gecmeli
    pnl.activate("dev_chip")
    assert pnl.get_active_device()["id"] == MOCK_DEVICES[1]["id"]

    # mixer_link basinca open_mixer_requested tetiklenmeli
    mixers = []
    pnl.open_mixer_requested.connect(lambda: mixers.append(True))
    pnl.activate("mixer_link")
    assert mixers == [True]

    pnl.close()


def test_media_panel_render_output_device_ui() -> None:
    """Gorsel QImage ciziminde cihaz secici bilesenlerinin hatasiz cizildigini dogrula."""
    pnl = mp.MediaPanel()
    pnl.set_devices(MOCK_DEVICES)
    pnl.set_volume(72.0, muted=False, device=MOCK_DEVICES[0]["name"])

    img = pnl.render_to_image(dpr=1.5)
    assert not img.isNull()
    assert img.width() == int(pnl.WIDTH * 1.5)
    assert img.height() > 300

    # Hover durumu ile cizim
    pnl._hover = "dev_chip"
    img_hover = pnl.render_to_image(dpr=2.0)
    assert not img_hover.isNull()

    pnl._hover = "dev_prev"
    img_prev = pnl.render_to_image(dpr=1.0)
    assert not img_prev.isNull()

    pnl.close()


def test_core_audio_api_safe_under_test() -> None:
    """Test ortaminda Windows Core Audio cagrilari no-op ve guvenli olmali."""
    devs = mp.list_output_devices(active_only=True)
    assert isinstance(devs, list)
    assert len(devs) >= 1

    # set_default_output_device test modunda gercek sese dokunmadan True donmeli
    res = mp.set_default_output_device("{mock_device_id}")
    assert res is True


def test_serit_v5_wiring() -> None:
    """serit_v5.pyw'de device_switch_requested sinyal baglantisinin varligini dogrula."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("serit_v5_test", str(APP_DIR / "serit_v5.pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    dock = mod.SeritDock({"style": "band"}, preview_mode=True)
    assert hasattr(dock, "_on_media_panel_device_switch")
    assert dock.media_panel is not None
    assert hasattr(dock.media_panel, "device_switch_requested")
    dock.close()


if __name__ == "__main__":
    test_media_panel_device_set_and_get()
    test_media_panel_device_cycling_and_signals()
    test_media_panel_device_hit_testing_and_activation()
    test_media_panel_render_output_device_ui()
    test_core_audio_api_safe_under_test()
    test_serit_v5_wiring()
    print("ALL TEST_V33_MEDIA_OUTPUT_DEVICE TESTS PASSED")
