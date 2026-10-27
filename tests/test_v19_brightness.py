"""v19: Parlaklık paneli panel_style v2 üzerinde (yatay hap kaydırıcılar). Gerçek parlaklık API'si çağrılmaz."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

import brightness_popover as bp
import panel_style

OUT = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v19")
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication(sys.argv)
ANCHOR = QRectF(500, 800, 120, 32)
TWO = [
    {"id": "wmi:l", "name": "Dizüstü", "kind": "wmi", "level": 67, "ok": True},
    {"id": "ddc:m", "name": "MSI MP223", "kind": "ddc", "level": 82, "ok": True},
]
BAD = [TWO[0], {"id": "ddc:x", "name": "Dell U2720", "kind": "ddc", "level": None, "ok": False, "err": "DDC/CI yanıt vermiyor"}]


def mk(mons):
    pop = bp.BrightnessPopover()
    em = []
    pop.level_requested.connect(lambda m, l: em.append((m, l)))
    pop.show_for(ANCHOR, [dict(m) for m in mons])
    pop.render_to_image(2.0)
    return pop, em


def ev(t, pt, btn=Qt.MouseButton.LeftButton):
    return QMouseEvent(t, QPointF(pt), QPointF(pt), btn, btn, Qt.KeyboardModifier.NoModifier)


def test_layout():
    pop, _ = mk(TWO)
    assert pop.width() == panel_style.WIDTH["bright"] == 352
    assert len(pop._slider_layout_cache) == 2 and len(pop._preset_buttons_cache) == 4
    t0, t1 = (i["track_rect"] for i in pop._slider_layout_cache)
    assert t0.width() > 250 and t1.top() > t0.bottom()          # yatay, alt alta
    assert pop.height() == pop.compute_height()
    pop.render_to_image(2.0).save(str(OUT / "parlaklik_iki_ekran.png"))
    one, _ = mk(TWO[:1])
    assert one.height() < pop.height()
    one.render_to_image(2.0).save(str(OUT / "parlaklik_tek_ekran.png"))
    assert (one._btn_sync_rect.isNull() or one._btn_sync_rect.width() == 0)  # tek ekranda Eşitle yok
    bad, _ = mk(BAD)
    bad.render_to_image(2.0).save(str(OUT / "parlaklik_okunamayan.png"))
    empty, _ = mk([])
    empty.render_to_image(2.0)


def test_drag_click_throttle():
    pop, em = mk(TWO)
    tr = pop._slider_layout_cache[1]["track_rect"]
    y = tr.center().y()
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, QPointF(tr.left() + tr.width() * 0.25, y)))
    assert pop._dragging_id == "ddc:m" and pop._monitors[1]["level"] == 25
    assert pop._monitors[0]["level"] == 67
    for f in (0.30, 0.31, 0.32, 0.33):                      # sıkı döngü: 60 ms kısıtlayıcı yutar
        pop.mouseMoveEvent(ev(QEvent.Type.MouseMove, QPointF(tr.left() + tr.width() * f, y)))
    assert len(em) <= 2, em
    pop.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, QPointF(tr.left() + tr.width() * 0.33, y)))
    assert em[-1] == ("ddc:m", 33) and pop._dragging_id is None
    assert pop._monitors[1]["level"] == 33


def test_presets_and_active_tint():
    pop, em = mk(TWO)
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, pop._preset_buttons_cache[1]["rect"].center()))
    assert [m["level"] for m in pop._monitors] == [50, 50]
    assert sorted(em) == [("ddc:m", 50), ("wmi:l", 50)]
    assert pop._active_preset_index() == 1
    img = pop.render_to_image(2.0)
    r = pop._preset_buttons_cache[1]["rect"]
    c = img.pixelColor(int(r.left() * 2 + 3), int(r.center().y() * 2))
    assert c.red() > c.blue() + 20, c.getRgb()               # kehribar zemin, mavi değil
    pop._hover_preset_idx = 2
    pop.render_to_image(2.0).save(str(OUT / "parlaklik_onayar_hover.png"))
    pop2, em2 = mk(TWO)
    pop2.mousePressEvent(ev(QEvent.Type.MouseButtonPress, pop2._btn_sync_rect.center()))   # Eşitle -> ilk ekranın seviyesi
    assert [m["level"] for m in pop2._monitors] == [67, 67]


def test_wheel():
    pop, em = mk(TWO)
    row = pop._slider_layout_cache[0]["row_rect"].center()
    w = QWheelEvent(QPointF(row), QPointF(row), pop.mapToGlobal(row.toPoint()).__class__(0, 0), pop.mapToGlobal(row.toPoint()).__class__(0, 120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    pop.wheelEvent(w)
    assert pop._monitors[0]["level"] == 72 and pop._monitors[1]["level"] == 82


def test_unreadable_not_draggable():
    pop, em = mk(BAD)
    tr = pop._slider_layout_cache[1]["track_rect"]
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, tr.center()))
    assert pop._dragging_id is None and em == [] and pop._monitors[1]["level"] is None
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, pop._preset_buttons_cache[0]["rect"].center()))
    assert [m for m, _ in em] == ["wmi:l"]                  # okunamayan ekrana yazılmaz


def test_close_and_api():
    pop, _ = mk(TWO)
    assert pop.is_open()
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, pop._btn_close_rect.center()))
    assert pop._is_closing
    pop.hide_instant()
    assert not pop.isVisible() and pop.recently_closed()
    pop.show_for(ANCHOR, TWO, switch_from_x=300)
    assert pop.is_open()
    pop.hide_instant()
    assert not pop.isVisible()
    pop.update_levels({"wmi:l": 10})
    pop.update_levels(TWO)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("PASS", n)
