"""Animasyon kareleri yalnız oynayan kartı boyar; son kare de (tween bitince) tüm şeridi çizmez."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_animreg_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None


def test_anim_frame_region() -> None:
    QApplication.instance() or QApplication([])
    dock = serit_mod.SeritDock({}, preview_mode=True)
    sys_rect = QRectF(100, 6, 96, 52)
    dock.hit_boxes = [(sys_rect, "sys", None)]
    calls: list = []
    dock.update = lambda *a: calls.append(a[0] if a else None)
    drv = dock.anim_driver

    # Oynayan tek tween sistem halkası: yalnız sistem kartı
    drv._tweens = {dock.anim_cpu}
    dock._on_anim_frame()
    assert calls[-1] is not None and calls[-1].contains(sys_rect.toRect()), calls[-1]

    # Son kare: sistem tween'i bitti -> yine yalnız sistem kartı (eskiden tam çizim)
    drv._tweens = set()
    drv.last_finished = (dock.anim_cpu, dock.anim_ram)
    dock._on_anim_frame()
    assert calls[-1] is not None and calls[-1].contains(sys_rect.toRect()), calls[-1]

    # Son karede kart dışı bir tween de bittiyse güvenli taraf: tam çizim
    drv.last_finished = (dock.anim_cpu, dock.anim_pill_x)
    dock._on_anim_frame()
    assert calls[-1] is None

    # Bilinmeyen bitiş (boş liste) -> tam çizim
    drv.last_finished = ()
    dock._on_anim_frame()
    assert calls[-1] is None

    # Karışık tween'ler oynuyorsa tam çizim
    drv._tweens = {dock.anim_cpu, dock.anim_claude_s}
    dock._on_anim_frame()
    assert calls[-1] is None
    drv._tweens = set()


if __name__ == "__main__":
    test_anim_frame_region()
    print("[PASS] test_anim_frame_region")
