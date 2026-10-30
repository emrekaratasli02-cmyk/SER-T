"""test_v26_updates.py — winget güncelleme denetleyicisi testleri.

Test edilenler:
  * WINGET_ARGS güvenliği (install/--all yok, listeleme kipinde)
  * run_winget_list test koruması (test altında engellenir)
  * parse_winget_table dil bağımsız ayrıştırma (İngilizce, Türkçe, spinner+ikinci tablo, boş çıktı)
  * UpdateChecker periyodik kontrol, önbellekleme ve hata sonrası tekrar deneme
  * band_width ve tooltip biçimlendirmesi
  * UpdatesPanel açılır penceresi, Esc/kapatma/yenileme sinyali etkileşimleri
  * Rozet ve panel ekran dışı (offscreen) PNG çizimleri (DPR 1.25)
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["SERIT_TEST"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontDatabase, QImage, QKeyEvent, QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import updates  # noqa: E402

app = QApplication.instance() or QApplication([])

# Offscreen ortamında Windows Segoe UI yazı tiplerini yükle
fdir = Path("C:/Windows/Fonts")
for _f in ("SegUIVar.ttf", "segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
    _p = fdir / _f
    if _p.exists():
        QFontDatabase.addApplicationFont(str(_p))

SCRATCH_UPD_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v26/upd")


def test_winget_args_safety() -> None:
    """Argüman listesi asla install veya --all içermemeli, salt okunur liste olmalı."""
    args = updates.WINGET_ARGS
    assert isinstance(args, tuple)
    assert "install" not in args, f"WINGET_ARGS install içermemeli: {args}"
    assert "--all" not in args, f"WINGET_ARGS --all içermemeli: {args}"
    assert "-r" not in args, f"WINGET_ARGS -r içermemeli: {args}"
    assert args[0] == "winget"
    assert args[1] == "upgrade"
    assert "--accept-source-agreements" in args
    assert "--disable-interactivity" in args
    assert "--include-unknown" in args


def test_run_winget_list_blocked_under_test() -> None:
    """Test koşullarında harici winget sürecinin çalışması engellenmeli."""
    try:
        updates.run_winget_list()
        assert False, "run_winget_list test ortamında RuntimeError fırlatmalıydı"
    except RuntimeError as exc:
        assert "Test ortamında" in str(exc) or "test" in str(exc).lower()


def test_parse_fixtures() -> None:
    """4 farklı yapay (örnek) fikstür üzerinde ayrıştırma testi."""
    # 1. İngilizce başlıklar
    f_en = """
Name                                                   Id                                Version       Available     Source
----------------------------------------------------------------------------------------------------------------------------
Sample App Alpha                                       Sample.Alpha                      1.0.0         1.1.0         winget
Sample App Beta                                        Sample.Beta                       2.4.1         2.5.0         winget
2 upgrades available.
"""
    items_en = updates.parse_winget_table(f_en)
    assert len(items_en) == 2, f"Beklenen 2, bulunan {len(items_en)}"
    assert items_en[0] == {
        "name": "Sample App Alpha",
        "id": "Sample.Alpha",
        "version": "1.0.0",
        "available": "1.1.0",
        "source": "winget",
    }
    assert items_en[1]["name"] == "Sample App Beta"
    assert items_en[1]["available"] == "2.5.0"

    # 2. Türkçe başlıklar ("Kullanılabilir")
    f_tr = """
Ad                                                     Kimlik                            Sürüm         Kullanılabilir Kaynak
----------------------------------------------------------------------------------------------------------------------------
Örnek Uygulama                                         Ornek.Uygulama                    0.9.1         1.0.0          winget
Not Defteri Pro                                        Not.Defteri                       3.2           3.3            winget
2 yükseltme kullanılabilir.
"""
    items_tr = updates.parse_winget_table(f_tr)
    assert len(items_tr) == 2
    assert items_tr[0]["name"] == "Örnek Uygulama"
    assert items_tr[0]["available"] == "1.0.0"
    assert items_tr[1]["name"] == "Not Defteri Pro"
    assert items_tr[1]["version"] == "3.2"

    # 3. Başta spinner çöpü ve ikinci tablo (bilinmeyen sürümler)
    f_spinner_unknown = """
\\ | / -
Name                                                   Id                                Version       Available     Source
----------------------------------------------------------------------------------------------------------------------------
Kod Editörü                                            Kod.Editor                        1.80.0        1.81.0        winget
1 upgrade available.

The following packages have an upgrade available, but their version cannot be determined:
Name                                                   Id                                Version       Available     Source
----------------------------------------------------------------------------------------------------------------------------
Bilinmeyen Sürüm Paket                                 Bilinmeyen.Paket                  <unknown>     4.0.0         winget
1 upgrade available.
"""
    items_unk = updates.parse_winget_table(f_spinner_unknown)
    assert len(items_unk) == 2
    assert items_unk[0]["name"] == "Kod Editörü"
    assert "unknown" not in items_unk[0]
    assert items_unk[1]["name"] == "Bilinmeyen Sürüm Paket"
    assert items_unk[1].get("unknown") is True
    assert items_unk[1]["available"] == "4.0.0"

    # 4. Boş paket çıktısı
    f_empty = "No installed package found matching input criteria."
    items_empty = updates.parse_winget_table(f_empty)
    assert items_empty == []

    # 5. "available" sütunu boş satırların atlanması
    f_skip = """
Name                                                   Id                                Version       Available     Source
----------------------------------------------------------------------------------------------------------------------------
Valid App                                              Valid.App                         1.0.0         2.0.0         winget
No Update App                                          NoUp.App                          1.0.0                       winget
1 upgrade available.
"""
    items_skip = updates.parse_winget_table(f_skip)
    assert len(items_skip) == 1
    assert items_skip[0]["name"] == "Valid App"


def test_checker_due_and_caching() -> None:
    """UpdateChecker periyodik kontrol, atomik önbellekleme ve zaman aşımı."""
    with tempfile.TemporaryDirectory() as td:
        cache_file = Path(td) / "updates_cache.json"
        sim_now = 1730000000.0

        def fake_now() -> float:
            return sim_now

        raw_output = """
Name                                                   Id                                Version       Available     Source
----------------------------------------------------------------------------------------------------------------------------
Örnek Uygulama                                         Ornek.App                         1.0           1.1           winget
1 upgrade available.
"""

        def fake_runner() -> str:
            return raw_output

        checker = updates.UpdateChecker(cache_path=cache_file, runner=fake_runner, now=fake_now)

        # Önbellek yokken due True olmalı
        assert checker.due() is True
        st0 = checker.state()
        assert st0 == {"count": None, "items": [], "checked_at": None, "err": None}

        # Kontrol çalıştır
        res = checker.check()
        assert res["count"] == 1
        assert len(res["items"]) == 1
        assert res["items"][0]["name"] == "Örnek Uygulama"
        assert res["checked_at"] == sim_now
        assert res["err"] is None

        # Önbellekten okuma
        st1 = checker.state()
        assert st1["count"] == 1
        assert st1["checked_at"] == sim_now

        # 1 saat sonra kontrol zamanı gelmemiş olmalı (< 24 sa)
        sim_now += 3600.0
        assert checker.due() is False

        # 25 saat sonra kontrol zamanı gelmiş olmalı (>= 24 sa)
        sim_now += 24 * 3600.0
        assert checker.due() is True


def test_checker_error_retry() -> None:
    """Hata durumunda 2 saat sonra tekrar deneme."""
    with tempfile.TemporaryDirectory() as td:
        cache_file = Path(td) / "updates_cache.json"
        sim_now = 1730000000.0

        def fake_now() -> float:
            return sim_now

        def failing_runner() -> str:
            raise ConnectionError("Ağ bağlantısı yok")

        checker = updates.UpdateChecker(cache_path=cache_file, runner=failing_runner, now=fake_now)

        res = checker.check()
        assert res["count"] is None
        assert res["items"] == []
        assert "Ağ bağlantısı yok" in str(res["err"])
        assert res["checked_at"] == sim_now

        # 1 saat sonra: hata sonrası 2 saat dolmadığından due False
        sim_now += 3600.0
        assert checker.due() is False

        # 2.5 saat sonra: hata sonrası 2 saat dolduğundan due True
        sim_now += 1.5 * 3600.0
        assert checker.due() is True


def test_band_width_and_tooltip() -> None:
    """band_width ve tooltip kuralları."""
    # Genişlik: count >= 1 -> 38.0; count == 0 veya None veya err -> 0.0
    assert updates.band_width({"count": 3}) == 38.0
    assert updates.band_width({"count": 1}) == 38.0
    assert updates.band_width({"count": 3, "err": "hata"}) == 0.0
    assert updates.band_width({"count": 0}) == 0.0
    assert updates.band_width({"count": None}) == 0.0
    assert updates.band_width(None) == 0.0

    # tooltip
    t_fixed = 1730322600.0  # 2024-10-30 23:10 yerel zaman dilimine benzer
    st_normal = {"count": 3, "checked_at": t_fixed, "err": None}
    tip_normal = updates.tooltip(st_normal)
    assert "3 uygulama güncellenebilir" in tip_normal
    assert "Kaynak: winget (yalnız kontrol)" in tip_normal

    st_zero = {"count": 0, "checked_at": t_fixed, "err": None}
    tip_zero = updates.tooltip(st_zero)
    assert "Tüm uygulamalar güncel" in tip_zero

    st_err = {"count": None, "checked_at": t_fixed, "err": "Bağlantı hatası"}
    tip_err = updates.tooltip(st_err)
    assert "Güncelleme kontrolü başarısız" in tip_err
    assert "Bağlantı hatası" in tip_err

    tip_none = updates.tooltip(None)
    assert "kontrol edilmedi" in tip_none


def test_panel_interactions() -> None:
    """UpdatesPanel esc, kapatma butonu ve 'Şimdi kontrol et' sinyali."""
    panel = updates.UpdatesPanel()
    state = {
        "count": 2,
        "checked_at": time.time(),
        "err": None,
        "items": [
            {"name": "Örnek 1", "id": "O.1", "version": "1.0", "available": "1.1", "source": "winget"},
            {"name": "Örnek 2", "id": "O.2", "version": "2.0", "available": "2.1", "source": "winget"},
        ],
    }
    panel.set_state(state)
    assert panel.compute_height() > 100

    # Esc ile kapanma
    panel.show()
    assert panel.is_open() is True
    press_esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(press_esc)
    panel.hide_instant()
    assert panel.is_open() is False
    assert panel.recently_closed(1000.0) is True

    # 'Şimdi kontrol et' düğmesi tıklama sinyali
    requested = []
    panel.check_requested.connect(lambda: requested.append(True))
    ref_btn = panel._rects.get("refresh")
    assert ref_btn is not None and not ref_btn.isEmpty()
    click_evt = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        ref_btn.center(),
        ref_btn.center(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(click_evt)
    assert len(requested) == 1, "check_requested sinyali tetiklenmeliydi"


def test_render_badge_and_panel_offscreen_and_save_pngs() -> None:
    """Ekran dışı (offscreen) PNG çizimleri (DPR 1.25) ve dosya kayıtları."""
    SCRATCH_UPD_DIR.mkdir(parents=True, exist_ok=True)
    dpr = 1.25

    # 1. Band badge: count 3
    img_b3 = QImage(int(round(38.0 * dpr)), int(round(30.0 * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
    img_b3.setDevicePixelRatio(dpr)
    img_b3.fill(QColor(22, 24, 29))
    p = QPainter(img_b3)
    updates.draw_updates_badge(p, QRectF(0, 0, 38.0, 30.0), {"count": 3}, hover=False)
    p.end()
    p_b3 = SCRATCH_UPD_DIR / "badge_3.png"
    assert img_b3.save(str(p_b3)) is True
    assert p_b3.stat().st_size > 0

    # 2. Band badge: count 14
    img_b14 = QImage(int(round(38.0 * dpr)), int(round(30.0 * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
    img_b14.setDevicePixelRatio(dpr)
    img_b14.fill(QColor(22, 24, 29))
    p = QPainter(img_b14)
    updates.draw_updates_badge(p, QRectF(0, 0, 38.0, 30.0), {"count": 14}, hover=True)
    p.end()
    p_b14 = SCRATCH_UPD_DIR / "badge_14.png"
    assert img_b14.save(str(p_b14)) is True
    assert p_b14.stat().st_size > 0

    def render_panel(panel: updates.UpdatesPanel, filename: str) -> Path:
        w, h = panel.width(), panel.height()
        img = QImage(int(round(w * dpr)), int(round(h * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p_canvas = QPainter(img)
        panel._paint(p_canvas)
        p_canvas.end()
        out_path = SCRATCH_UPD_DIR / filename
        assert img.save(str(out_path)) is True
        assert out_path.stat().st_size > 0
        return out_path

    # 3. Normal 3 öğeli panel (Örnek veriler)
    panel = updates.UpdatesPanel()
    panel.set_state({
        "count": 3,
        "checked_at": time.time(),
        "err": None,
        "items": [
            {"name": "Örnek Uygulama", "id": "Ornek.App", "version": "1.0.4", "available": "1.1.0", "source": "winget"},
            {"name": "Not Defteri Pro", "id": "Not.Defteri", "version": "2.8.0", "available": "3.0.0", "source": "winget"},
            {"name": "Görsel Düzenleyici", "id": "Gorsel.Editor", "version": "0.19.1", "available": "0.20.0", "source": "winget"},
        ],
    })
    p_norm = render_panel(panel, "panel_3_items.png")
    assert p_norm.exists()

    # 4. 14 öğeli panel ("+6 daha" satırı ile)
    items_14 = [
        {"name": f"Örnek Paket {i + 1}", "id": f"Ornek.Paket{i + 1}", "version": f"1.{i}", "available": f"1.{i + 1}", "source": "winget"}
        for i in range(14)
    ]
    panel.set_state({
        "count": 14,
        "checked_at": time.time(),
        "err": None,
        "items": items_14,
    })
    p_14 = render_panel(panel, "panel_14_items.png")
    assert p_14.exists()

    # 5. Boş panel (0 güncelleme)
    panel.set_state({
        "count": 0,
        "checked_at": time.time(),
        "err": None,
        "items": [],
    })
    p_emp = render_panel(panel, "panel_empty.png")
    assert p_emp.exists()

    # 6. Hata durumlu panel
    panel.set_state({
        "count": None,
        "checked_at": time.time(),
        "err": "winget çalıştırılamadı: zaman aşımı (örnek hata)",
        "items": [],
    })
    p_err = render_panel(panel, "panel_error.png")
    assert p_err.exists()


def main() -> int:
    tests = [
        test_winget_args_safety,
        test_run_winget_list_blocked_under_test,
        test_parse_fixtures,
        test_checker_due_and_caching,
        test_checker_error_retry,
        test_band_width_and_tooltip,
        test_panel_interactions,
        test_render_badge_and_panel_offscreen_and_save_pngs,
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
