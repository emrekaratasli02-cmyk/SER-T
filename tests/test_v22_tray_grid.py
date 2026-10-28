"""test_v22_tray_grid.py - TrayPanel v22: Windows 11 gizli simge flyout $(PUNCT)ızgarası.

Doğrulanan davranışlar (yalnızca ÖRNEK veri ve üretilmiş renkli simgeler; GERÇEK tepsi ASLA okunmaz/etkinleştirilmez):
- 0, 3, 9 ve 23 (kaydırmalı) öğe dpr 2.0 render + tek parça pafta: _ref/out/v22_tray_sheet.png
- Genişlik: >= 5 öğe -> 260; az öğe -> daralır ama etiket ~140 px kalır; 23 öğe -> 4 satır + etiket yüksekliği
- Hücre tıklama: sol -> item_activated(item, "left") + kapanır; sağ -> "right" + açık kalır
- Klavye: oklar ızgarada gezinir, Enter = sol, Shift+F10 / Menu = sağ, Esc kapatır
- item_anchor_global(item): hücre merkezinin global eşini İÇEREN 44x44 dikdörtgen döner
- Tekerlek kaydırma sınırda kelepçelenir; kaydırma göstergesi korunur
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

import tray_panel as tp  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(["test_v22_tray_grid"])

ANCHOR = QRectF(500.0, 800.0, 120.0, 32.0)

SAMPLE_NAMES = [
    "WhatsApp", "Zoom", "Spotify", "OneDrive", "Bluetooth",
    "Windows Güvenlik", "NVIDIA Ayarları", "PowerToys Awake",
    "Steam", "Discord", "Telegram", "Intel Destek Asistanı",
    "Dikte · Türkçe", "Slack", "Everything", "Unigram",
    "Steam Client Bootstrapper", "Epic Games", "Güvenlik Kamerası",
    "Yedekleme", "Ağ Denetimi", "Sürücü Yardımcısı", "Rapor Aracı",
]

SAMPLE_COLORS = [
    "#BF5AF2", "#0A84FF", "#64D2FF", "#FFB020", "#30D158",
    "#FF453A", "#D97757", "#5E5CE6",
]

_icon_counter = 0


def _stub_icon(color: str) -> QPixmap:
    """Sintetik renkli tepsi simgesi (gerçek simge okunmaz; yalnız yerel QPixmap)."""
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


def _items(n: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(n):
        items.append({"name": SAMPLE_NAMES[i % len(SAMPLE_NAMES)],
                      "tooltip": f"{SAMPLE_NAMES[i % len(SAMPLE_NAMES)]} · örnek {i}",
                      "exe": f"C:\\Program Files\\Ornek{i}\\app.exe"})
    return items


def _icons(count: int) -> Dict[str, QPixmap]:
    icons: Dict[str, QPixmap] = {}
    for i in range(min(count, len(SAMPLE_COLORS) * 3)):
        name = SAMPLE_NAMES[i % len(SAMPLE_NAMES)]
        if name not in icons:
            icons[name] = _stub_icon(SAMPLE_COLORS[i % len(SAMPLE_COLORS)])
    return icons


def _panel(n: int, with_icons: bool = True) -> tp.TrayPanel:
    panel = tp.TrayPanel()
    panel.set_items(_items(n), _icons(len(SAMPLE_NAMES)) if with_icons else None)
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


def _wheel(widget, dy: int) -> QWheelEvent:
    ev = QWheelEvent(
        QPointF(widget.width() / 2.0, widget.height() / 2.0),
        QPointF(widget.width() / 2.0, widget.height() / 2.0),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    widget.wheelEvent(ev)
    return ev


def test_widths_and_heights():
    """>= 5 öğe -> 260; az öğe daralır; etiket ~140 px; 23 öğe -> 4 satır + etiket."""
    p5 = _panel(5)
    assert p5.width() == 260 == p5.WIDTH
    assert p5.height() == 12 + (44) + 4 + 26 + 12   # tek satır

    p23 = _panel(23)
    assert p23.width() == 260
    capped = 12 + (4 * 44 + 3 * 4) + 4 + 26 + 12
    assert p23.height() == capped, f"23 öğe yüksekliği: {p23.height()} != {capped}"

    # Görünür satır sayısı 4 ile sınırlı
    assert p23._visible_rows() == 4 and p23._total_rows() == 5

    p3 = _panel(3)
    assert p3.width() == 164            # 3 sütun: 3*44+2*4+24
    label_avail = p3.width() - 2 * tp.TrayPanel.GRID_PAD
    assert label_avail >= 138.0         # etiket satırı ~140 px alan bulur

    p1 = _panel(1)
    assert p1.width() == 164            # alt sınır: MIN_WIDTH
    assert p1.height() == 12 + 44 + 4 + 26 + 12


def test_grid_geometry_and_empty_state():
    """Hücreler 44x44 5 sütunlu dizilir; boş liste -> 'Gizli simge yok' kompakt panel."""
    p5 = _panel(5)
    r0 = p5._cell_rect(0)
    r4 = p5._cell_rect(4)
    assert r0.isValid() and r0.width() == 44.0 and r0.height() == 44.0
    assert r4.left() - r0.left() == 4 * tp.TrayPanel.ROW_STRIDE
    assert p5.chip_text() == "5 simge"

    pe = _panel(0)
    assert pe.EMPTY_TEXT == "Gizli simge yok"
    assert pe.height() == 50            # kompakt: 12 + 26 + 12
    assert pe.width() == 164
    assert pe._cell_rects == {} and pe._grid_rect.isNull()
    img = pe.render_to_image(2.0)
    assert not img.isNull()
    pe.update()
    pe.wheelEvent(_wheel(pe, -120))     # boş ızgarada tekerlek zararsız
    assert pe._scroll_y == 0.0


def test_left_click_cell_i():
    """Hücre i'ye sol tık -> item_activated(items[i], 'left') ve panel kapanır."""
    p = _panel(9)
    hits: List[Tuple[Any, str]] = []
    p.item_activated.connect(lambda item, btn: hits.append((item, btn)))
    p.show_for(ANCHOR)
    assert p.is_open()

    cell = p._cell_rect(2)
    _mouse(p, cell.center())
    assert len(hits) == 1
    assert hits[0][0]["name"] == SAMPLE_NAMES[2]
    assert hits[0][1] == "left"
    assert not p.is_open()              # sol tık kapatır
    p.hide_instant()
    assert not p.isVisible()


def test_right_click_stays_open():
    """Sağ tık -> item_activated(items[i], 'right'); panel açık kalır."""
    p = _panel(9)
    hits: List[Tuple[Any, str]] = []
    p.item_activated.connect(lambda item, btn: hits.append((item, btn)))
    p.show_for(ANCHOR)
    assert p.is_open()

    cell = p._cell_rect(5)
    _mouse(p, cell.center(), btn=Qt.MouseButton.RightButton)
    assert len(hits) == 1 and hits[0][1] == "right"
    assert hits[0][0]["name"] == SAMPLE_NAMES[5]
    assert p.is_open()                  # sağ tık açık kalır

    # Boş alana sağ tık: sinyal yok
    n_before = len(hits)
    _mouse(p, QPointF(p.width() - 2.0, p.height() - 2.0), btn=Qt.MouseButton.RightButton)
    _mouse(p, QPointF(2.0, 2.0), btn=Qt.MouseButton.RightButton)
    assert len(hits) == n_before
    p.hide_instant()
    assert not p.isVisible()


def test_keyboard_grid_navigation():
    """Oklar ızgarada gezinir (5'er adım Down/Up, 1'er adım Right/Left); Enter sol; Shift+F10/Menu sağ."""
    p = _panel(23)
    hits: List[Tuple[Any, str]] = []
    p.item_activated.connect(lambda item, btn: hits.append((item, btn)))
    p.show_for(ANCHOR)
    assert p.is_open() and p._highlight_idx == -1

    def key(k, mods=Qt.KeyboardModifier.NoModifier):
        ev = QKeyEvent(QEvent.Type.KeyPress, k, mods)
        p.keyPressEvent(ev)

    key(Qt.Key.Key_Down)
    assert p._highlight_idx == 0
    key(Qt.Key.Key_Right)
    assert p._highlight_idx == 1
    key(Qt.Key.Key_Down)
    assert p._highlight_idx == 6                  # bir sonraki satır
    key(Qt.Key.Key_Left)
    assert p._highlight_idx == 5
    key(Qt.Key.Key_Up)
    assert p._highlight_idx == 0
    p._highlight_idx = 22                          # son hücreye zıpla
    key(Qt.Key.Key_Down)
    assert p._highlight_idx == 22                  # sınırlı: ileri gidemez

    key(Qt.Key.Key_Return)
    assert len(hits) == 1 and hits[0][1] == "left"
    assert not p.is_open()                         # Enter kapatır

    p.hide_instant()
    p.show_for(ANCHOR)
    p._highlight_idx = 3
    key(Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert len(hits) == 2 and hits[1][1] == "right"
    assert p.is_open()                             # sağ tık gibi açık kalır
    key(Qt.Key.Key_Menu)
    assert len(hits) == 3 and hits[2][1] == "right"
    assert p.is_open()

    key(Qt.Key.Key_Escape)
    p.hide_instant()
    assert not p.isVisible()


def test_keyboard_scroll_follows_focus():
    """Odağın alt satırlara inmesi görünür alanı kaydırır."""
    p = _panel(23)
    p.show_for(ANCHOR)
    assert p._scroll_y == 0.0
    p._highlight_idx = 21
    p._ensure_cell_visible(21)
    assert p._scroll_y > 0.0
    total = p._total_grid_height()
    max_scroll = total - p._visible_grid_h()
    assert p._scroll_y <= max_scroll
    p.hide_instant()


def test_wheel_scroll_clamped():
    """Tekerlek kaydırır, hem 0 hem max saniyede kelepçelenir; hover güncellenir."""
    p = _panel(23)
    p.show_for(ANCHOR)
    max_scroll = p._total_grid_height() - p._visible_grid_h()

    _wheel(p, -120)
    assert p._scroll_y > 0.0 and p._scroll_y <= max_scroll

    for _ in range(12):                            # uzağa
        _wheel(p, -120)
    assert p._scroll_y == max_scroll

    for _ in range(12):                            # başa
        _wheel(p, 120)
    assert p._scroll_y == 0.0
    p.hide_instant()


def test_item_anchor_global():
    """item_anchor_global(item): hücre merkezinin global eşini içeren 44x44 global dikdörtgen."""
    p = _panel(9)
    p.setGeometry(30, 40, p.compute_width(), p.compute_height())
    p.show()
    QApplication.processEvents()
    p.render_to_image(2.0)

    idx = 3
    cell = p._cell_rect(idx)
    center_local = cell.center().toPoint()
    center_global = p.mapToGlobal(center_local)

    anchor = p.item_anchor_global(_items(9)[idx])
    assert anchor is not None
    assert anchor.width() == 44.0 and anchor.height() == 44.0
    assert anchor.contains(QPointF(center_global)), (
        f"anchor {anchor} merkez {center_global.x()},{center_global.y()} içermiyor")

    # Bilinmeyen öğe -> None
    assert p.item_anchor_global({"name": "yok"}) is None
    assert p.item_anchor_global(None) is None
    p.hide_instant()
    assert not p.isVisible()


def _panel_img(n: int, hover: int = -1, kbd: int = -1, scroll: int = 0,
               with_icons: bool = True) -> QImage:
    p = _panel(n, with_icons=with_icons)
    if hover >= 0:
        p._hover_idx = hover
    if kbd >= 0:
        p._highlight_idx = kbd
    if scroll:
        p._scroll_y = max(0.0, min(p._total_grid_height() - p._visible_grid_h(), float(scroll)))
    p._layout()
    return p.render_to_image(2.0)


def test_render_sheet_dpr2():
    """0/3/9/23 öğe + hover + odak paftası: _ref/out/v22_tray_sheet.png (kendi gözümle bakılır)."""
    tiles = [
        ("0 simge — boş", _panel_img(0, with_icons=False)),
        ("3 simge — hover", _panel_img(3, hover=1)),
        ("9 simge — klavye odağı", _panel_img(9, kbd=5)),
        ("23 simge — kaydırma", _panel_img(23, hover=8, scroll=48 // 2)),
        ("5 simge — sessiz", _panel_img(5)),
        ("23 simge — odak+hover", _panel_img(23, hover=10, kbd=11, scroll=12)),
    ]

    dpr = 2.0
    margin = 24.0
    caption_h = 18.0
    gap = 16.0

    x = margin
    total_w = margin
    max_h = 0.0
    for _cap, img in tiles:
        total_w += img.width() / dpr + gap
        max_h = max(max_h, img.height() / dpr)
    total_w += margin

    canvas_h = margin + caption_h + max_h + 2 * caption_h + margin
    sheet = QImage(int(total_w * dpr), int(canvas_h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    sheet.setDevicePixelRatio(dpr)
    sheet.fill(QColor("#0C0D0F"))

    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    f_cap = QFont()
    f_cap.setPixelSize(12)
    p.setFont(f_cap)
    x = margin
    for cap, img in tiles:
        disp_w = img.width() / dpr
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(x, margin, disp_w, caption_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cap)
        y = margin + caption_h
        p.drawImage(QPointF(x, y), img)
        x += disp_w + gap
    p.end()

    assert x <= total_w + 0.5, "Pafta genişliği taşma"
    out = OUT / "v22_tray_sheet.png"
    assert sheet.save(str(out)) and out.is_file() and out.stat().st_size > 0

    # Ayrıca tek tek null olmayan render kanıtı
    for _cap, img in tiles:
        assert not img.isNull() and img.width() > 0 and img.height() > 0


def run_all() -> None:
    print("=== RUNNING test_v22_tray_grid.py ===")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("=== ALL V22 TRAY GRID TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
