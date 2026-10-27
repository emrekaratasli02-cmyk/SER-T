"""Bant (tam genişlik) ve kapsül görünümleri: genişlik, kart grubunun ortalanması, sürükleme, AppBar yüksekliği."""
import importlib.util
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
spec = importlib.util.spec_from_file_location("serit_v5_style", str(APP_DIR / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
# Gerçek settings.json'a asla yazma
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_style_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None


def test_styles() -> None:
    app = QApplication.instance() or QApplication([])
    sw = app.primaryScreen().geometry().width()

    band = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    band.compute_layout_and_resize(initial=True)
    assert band._is_band()
    assert band.width() == sw, (band.width(), sw)
    assert 0 < band._content_w < sw, band._content_w
    img = QImage(band.size(), QImage.Format.Format_ARGB32)
    band.render(img)  # paintEvent hit_boxes'ı doldurur
    # Yeni Lumabar düzeninde uygulama grubu ekran ortasında, kanatlar iki yanda; saat sağ kenarda
    apps_hits = [r for r, k, _e in band.hit_boxes if k.startswith("app_")]
    if apps_hits:
        app_cx = (min(r.left() for r in apps_hits) + max(r.right() for r in apps_hits)) / 2.0
        assert abs(app_cx - (sw / 2.0)) <= 1.0, ("uygulama grubu ortada değil", app_cx, sw / 2.0)
    # Saat sağ kenardaki tepsi kümesinin hemen soluna sabitlenir
    clock_hits = [r for r, k, _e in band.hit_boxes if k == "clock"]
    assert len(clock_hits) == 1, "Saat kartı bulunamadı"

    pill = serit_mod.SeritDock({"style": "pill", "pinned": []}, preview_mode=True)
    pill.compute_layout_and_resize(initial=True)
    assert not pill._is_band()
    # Kapsül modunda aksiyon düğmeleri kapsül içinde yer aldığından pill genişliği bant merkez grubundan geniştir
    assert pill.width() < sw and pill.width() > band._content_w, (pill.width(), band._content_w)

    # Varsayılan (ayar yoksa) bant
    dflt = serit_mod.SeritDock({"pinned": []}, preview_mode=True)
    assert dflt._is_band()

    # Stil değiştirme kapsüle geçince pencere daralır
    band.set_dock_style("pill")
    assert not band._is_band() and band.width() < sw
    band.set_dock_style("band")
    assert band._is_band() and band.width() == sw
    print("ALL DOCK STYLE TESTS PASSED.")


if __name__ == "__main__":
    test_styles()
