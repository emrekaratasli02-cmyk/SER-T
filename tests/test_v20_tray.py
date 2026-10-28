"""test_v20_tray.py - TrayPanel temel sözleşmeleri; v22 ızgara ölçüleriyle güncellendi.

Doğrulanan davranışlar (yalnızca yerel sinyalia; GERÇEK tepsi simgesi ASLA etkinleştirilmez):
- Genişlik: >= 5 öğe -> 260 px; az öğe -> daralır (alt sınır 164)
- 44x44 hücreler (5 sütun), hover (radius 8) ve klavye gezinmesi devam ediyor
- Esc kapatır; Sol tık -> item_activated("left") + kapanır; Sağ tık -> item_activated("right") + açık kalır
- Boş durum 'Gizli simge yok'; etiket rozeti 'N simge'
- Başlık/footersız: _refresh_rect yok; refresh_requested sinyali yine declare edilir
- show_for(..., switch_from_x=...) ve hide_instant() (animate_out instant) çevrimdışı çalışır
- DPR 2.0 render kanıtı: _ref/out/tepsi_normal.png, tepsi_uzun.png, tepsi_bos.png
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import tray_panel as tp  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(["test_v20_tray"])

ANCHOR = QRectF(500.0, 800.0, 120.0, 32.0)

STUB_NAMES = [
    "Mesajlaşma",
    "Bulut Depolama",
    "Ekran Kartı",
    "Dikte",
    "Windows Güvenlik",
]

STUB_ITEM_COLORS = ["#BF5AF2", "#0A84FF", "#64D2FF", "#FFB020", "#30D158"]

_icon_counter = 0


def _stub_icon(color: str) -> QPixmap:
    """Sintetik tepsi simgesi (gerçek simge okunmaz, dağıtılmaz; yalnız yerel QPixmap)."""
    global _icon_counter
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 40, 40)
    p.setBrush(QColor(255, 255, 255, 200))
    p.drawEllipse(QPointF(24.0, 24.0), 8.0, 8.0)
    p.end()
    _icon_counter += 1
    return pm


def _stub_items(n: int = 5) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(n):
        items.append({"name": STUB_NAMES[i % len(STUB_NAMES)], "tooltip": f"stub {i}"})
    return items


def _stub_icons() -> Dict[str, QPixmap]:
    return {name: _stub_icon(STUB_ITEM_COLORS[i]) for i, name in enumerate(STUB_NAMES[:3])}


def _panel(n: int = 5, with_icons: bool = True) -> tp.TrayPanel:
    panel = tp.TrayPanel()
    icons = _stub_icons() if with_icons else None
    panel.set_items(_stub_items(n) if n else [], icons)
    panel.render_to_image(2.0)
    return panel


def _mouse(widget, pos: QPointF, btn: Qt.MouseButton = Qt.MouseButton.LeftButton,
           release: bool = False) -> None:
    posf = QPointF(pos)
    etype = QEvent.Type.MouseButtonRelease if release else QEvent.Type.MouseButtonPress
    ev = QMouseEvent(etype, posf, posf, btn, btn, Qt.KeyboardModifier.NoModifier)
    if release:
        widget.mouseReleaseEvent(ev)
    else:
        widget.mousePressEvent(ev)


def test_width_matches_shared_kit():
    """v22 ızgara genişliği sözleşmesi: >= 5 öğe -> 260; az öğe -> daralır."""
    panel = _panel()
    assert panel.WIDTH == 260
    assert panel.width() == 260            # 5*44 + 4*4 + 2*12
    p3 = _panel(3)
    assert p3.width() == 164               # 3 sütun: 3*44 + 2*4 + 2*12
    assert p3.width() - 2 * tp.TrayPanel.GRID_PAD >= 138.0   # etiket ~140 px sığar


def test_esc_close_kept():
    """v22'de ✕ yok; aynı niyet: panel Esc ile kapanır, Yenile tetiklenmez."""
    panel = _panel(3)
    closed: List[bool] = []
    panel.show_for(ANCHOR)
    assert panel.is_open()
    panel.refresh_requested.connect(lambda: closed.append(True))
    ev_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert not hasattr(panel, "_close_rect")     # başlık/✕ kaldırıldı
    panel.keyPressEvent(ev_esc)
    assert not panel.is_open()
    panel.hide_instant()
    assert not panel.isVisible()
    assert closed == []  # kapanış Yenile'yi tetiklemez


def test_row_hit_test_left_right():
    """Hücre vuruşu yerel listeye sinyal yollar (gerçek tepsi etkinleştirilmez)."""
    panel = _panel(3)
    hits: List[Tuple[Any, str]] = []
    panel.item_activated.connect(lambda item, btn: hits.append((item, btn)))
    panel.show_for(ANCHOR)

    cell0 = panel._cell_rect(0)
    _mouse(panel, cell0.center())
    assert len(hits) == 1 and hits[0][1] == "left"
    assert hits[0][0]["name"] == STUB_NAMES[0]
    assert not panel.is_open()                 # sol tık paneli kapatır
    panel.hide_instant()
    assert not panel.isVisible()

    panel.show_for(ANCHOR)
    cell1 = panel._cell_rect(1)
    _mouse(panel, cell1.center(), btn=Qt.MouseButton.RightButton)
    assert len(hits) == 2 and hits[1][1] == "right"
    assert panel.is_open()                     # sağ tık açık kalır

    # Izgara dışı alana tık: sinyal yok
    n_before = len(hits)
    _mouse(panel, QPointF(panel.width() / 2.0, 2.0))
    assert len(hits) == n_before
    panel.hide_instant()
    assert not panel.isVisible()


def test_empty_state_and_chip():
    panel = _panel(0, with_icons=False)
    assert panel.EMPTY_TEXT == "Gizli simge yok"
    assert panel.chip_text() == "0 simge"
    assert panel.height() == int(tp.TrayPanel.GRID_PAD + tp.TrayPanel.LABEL_H + tp.TrayPanel.GRID_PAD)
    img = panel.render_to_image(2.0)
    assert not img.isNull()

    five = _panel(5)
    assert five.chip_text() == "5 simge"
    one = _panel(1, with_icons=False)
    assert one.chip_text() == "1 simge"


def test_refresh_signal_kept():
    """v22'de footer/Yenile yok; aynı niyet: refresh_requested sinyali bağlanabilir kalır."""
    for panel in (_panel(5), _panel(0, with_icons=False)):
        got: List[bool] = []
        panel.refresh_requested.connect(lambda: got.append(True))
        panel.refresh_requested.emit()
        assert got == [True]
        assert not hasattr(panel, "_refresh_rect")   # footer düğmesi kaldırıldı


def test_show_for_switch_and_hide_instant():
    panel = _panel(5)
    panel.show_for(ANCHOR)
    assert panel.is_open() and panel.isVisible()
    panel.hide_instant()
    assert not panel.isVisible() and panel.recently_closed()

    # Kapsül içi bölüm değişimi: switch_from_x ile yatay kaymadan açılır
    panel.show_for(ANCHOR, switch_from_x=120)
    assert panel.is_open()
    assert panel._anchor_global == ANCHOR      # kontrat: konum saklanır
    panel.hide_instant()
    assert not panel.isVisible()

    # Pozisyonel çağrı üzerinde yeni ipucu yok
    panel.show_for(ANCHOR)
    assert panel.is_open()
    panel.hide_instant()
    assert not panel.isVisible()


def test_keyboard_and_scroll_kept():
    """Klavye gezinmesi ve 4 satırla sınırlı ızgara kaydırma davranışı korunur."""
    panel = _panel(23, with_icons=False)
    assert panel._visible_rows() == panel.MAX_ROWS and panel._total_rows() == 5
    assert panel.height() == 12 + (4 * 44 + 3 * 4) + 4 + 26 + 12   # 4 satır + etiket

    dn1 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(dn1)
    assert panel._highlight_idx == 0
    dn2 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(dn2)
    assert panel._highlight_idx == 5
    up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(up)
    assert panel._highlight_idx == 0
    esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(esc)
    panel.hide_instant()

    # Hücre hizalama: sağ tık akışında serit_v5 item_anchor_global kullanır
    panel.show_for(ANCHOR)
    panel.render_to_image(2.0)
    item = panel._items[6]
    anchor = panel.item_anchor_global(item)
    assert anchor is not None
    cell6 = panel._cell_rect(6)
    center_global = panel.mapToGlobal(cell6.center().toPoint())
    assert anchor.contains(QPointF(center_global))
    panel.hide_instant()
    assert not panel.isVisible()


def test_renders_dpr2():
    """DPR 2.0 render kanıtları: normal (hover), uzun (kaydırılmış), boş."""
    normal = _panel(5)
    normal._hover_idx = 1
    img = normal.render_to_image(2.0)
    assert not img.isNull() and img.width() == 2 * 260 and img.height() > 0
    img.save(str(OUT / "tepsi_normal.png"))

    uz = _panel(23, with_icons=False)
    uz._hover_idx = 8                 # görünür aralıkta bir hücre (kaydırma yarım satır)
    uz._scroll_y = (uz._total_grid_height() - uz._visible_grid_h()) / 2.0
    img2 = uz.render_to_image(2.0)
    assert not img2.isNull()
    img2.save(str(OUT / "tepsi_uzun.png"))

    empty = _panel(0, with_icons=False)
    img3 = empty.render_to_image(2.0)
    assert not img3.isNull() and empty.height() < normal.height()
    img3.save(str(OUT / "tepsi_bos.png"))

    for name in ("tepsi_normal.png", "tepsi_uzun.png", "tepsi_bos.png"):
        f = OUT / name
        assert f.is_file() and f.stat().st_size > 0, name


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
    print("ALL TEST_V20_TRAY TESTS PASSED")


if __name__ == "__main__":
    run_all()
