"""test_v21_toast.py - Toast'ların ortak panel kiti (v21) görünümü doğrulaması.

Kapsam: 352 px genişlik (panel_style.PANEL_W), opak panel kabuğu (PANEL_BG +
PANEL_BORDER, R_PANEL, saydam köşeler), 28 px aksan glif kutusu, en fazla 3 satır
gövde (taşarsa '…'), 'Şerit · HH:MM' alt satırı, draw_header görünümlü × kapatma,
bilinmeyen tür / geçersiz aksanda çökmeme ve ToastManager yığınlamasında üst üste
binme yokluğu. DPR 2.0 render kanıtları worktree içi _ref/out/ klasörüne yazılır.

Güvenlik: yalnızca stub veri; ağ çağrısı yok, kaynakları çekilmez, gerçek sistem
ayarlarına (ses, parlaklık, pano ...) dokunulmaz, state dosyası yazılmaz.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
import time

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

import panel_style as ps
from alerts import (
    Alert,
    Toast,
    ToastManager,
    TOAST_BODY_GAP,
    TOAST_FOOTER_GAP,
    TOAST_PAD,
    TOAST_TITLE_ROW_H,
)

OUT_DIR = APP_DIR / "_ref" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

CASES = [
    (
        "claude_warn",
        Alert(
            id="claude_demo_warn",
            title="Claude oturumu %82",
            body="Oturum kotasının %82'si kullanıldı. Sıfırlanma: 1 sa 20 dk",
            accent="#FFC45C",
            kind="claude",
        ),
    ),
    (
        "claude_crit",
        Alert(
            id="claude_demo_crit",
            title="Claude oturumu %95",
            body="Oturum kotasının %95'i kullanıldı. Sıfırlanma: 1 sa 20 dk",
            accent="#FF6E6E",
            kind="claude",
        ),
    ),
    (
        "fx_up",
        Alert(
            id="fx_demo_up",
            title="Dolar %1,45 artış",
            body="1 USD = 41,92 TL · Güncelleme: 16:30",
            accent="#78DC96",
            kind="fx",
        ),
    ),
    (
        "fx_down",
        Alert(
            id="fx_demo_down",
            title="Dolar %1,20 düşüş",
            body="1 USD = 41,42 TL · Güncelleme: 17:05",
            accent="#FF6E6E",
            kind="fx",
        ),
    ),
    (
        "sys_ram",
        Alert(
            id="ram_demo",
            title="Bellek kullanımı %94",
            body="RAM son 3 kontrolde %92 üzerinde (15,0\u00A0/\u00A016,0\u00A0GB).",
            accent="#FF6E6E",
            kind="sys",
        ),
    ),
    (
        "tray_unknown",
        Alert(
            id="tray_demo",
            title="Örnek uygulama kapatılamadı",
            body="Yönetici izni gerekiyor",
            accent="#123",
            kind="tray",
        ),
    ),
]

KNOWN_ACCENTS = {"#FF6E6E", "#FFC45C", "#78DC96"}


def _approx(c1: QColor, c2: QColor, tol: int) -> bool:
    return (
        abs(c1.red() - c2.red()) <= tol
        and abs(c1.green() - c2.green()) <= tol
        and abs(c1.blue() - c2.blue()) <= tol
    )


def test_width_is_shared_panel_width() -> None:
    """Toast tam panel genişliğinde (352) olmalı."""
    for name, alert in CASES:
        t = Toast(alert)
        assert t.width() == 352 == ps.PANEL_W, (name, t.width())
        assert t.height() >= 70
        t.deleteLater()
    print("✓ genişlik == panel_style.PANEL_W (352) testi geçti.")


def test_pixel_checks() -> None:
    """Arka plan ≈ PANEL_BG; (0,0) saydam; eski renkli sol şerit yok."""
    for name, alert in CASES:
        t = Toast(alert)
        img = t.render_to_image(dpr=2.0)
        dpr = img.devicePixelRatio()
        w = img.width() / dpr
        h = img.height() / dpr

        # (0,0) köşesi saydam (opak kabuk yuvarlatılmış, WA_TranslucentBackground)
        corner = img.pixelColor(0, 0)
        assert corner.alpha() == 0, (name, corner)

        # İç noktalar PANEL_BG (sağ alt ve alt orta; metinlerden uzak)
        for lx, ly in ((w - 40.0, h - 8.0), (w / 2.0, h - 8.0)):
            c = img.pixelColor(int(lx * dpr), int(ly * dpr))
            assert _approx(c, ps.PANEL_BG, 8), (name, lx, ly, c)

        # Sol kenar içi (eski 4 px şeridin yeri) artık PANEL_BG — şerit yok
        c_left = img.pixelColor(int(2 * dpr), int(h / 2 * dpr))
        assert _approx(c_left, ps.PANEL_BG, 8), (name, c_left)

        # Bilinen aksanlarda: sol kenarda aksan renginde tek piksel bile yok
        raw = QColor(alert.accent)
        if alert.accent.upper() in KNOWN_ACCENTS:
            for px in range(0, 8):
                c = img.pixelColor(px, int(h / 2 * dpr))
                assert not _approx(c, raw, 30), (name, px, c)
        t.deleteLater()
    print("✓ piksel kontrolleri (PANEL_BG, saydam köşe, şerit yok) geçti.")


def test_body_line_cap_300_chars() -> None:
    """300 karakterlik gövde bildirimi 3 gövde satırının ötesine büyütememeli."""
    long_body = ("Sıfırlanma bilgisi " * 20)[:300]
    assert len(long_body) == 300
    t_long = Toast(
        Alert(
            id="long_body",
            title="Uzun gövde",
            body=long_body,
            accent="#FFC45C",
            kind="claude",
        )
    )
    t_short = Toast(
        Alert(
            id="short_body",
            title="Kısa gövde",
            body="Kısa mesaj.",
            accent="#FFC45C",
            kind="claude",
        )
    )

    fm_body = QFontMetricsF(t_long.f_body)
    lines, truncated = t_long._wrap_body(fm_body, t_long._body_width())
    assert len(lines) == 3 and truncated, (len(lines), truncated)
    assert lines[-1].endswith("…"), lines[-1]

    fm_footer = QFontMetricsF(t_long.f_footer)
    expected = math.ceil(
        TOAST_PAD
        + TOAST_TITLE_ROW_H
        + TOAST_BODY_GAP
        + 3 * fm_body.height()
        + TOAST_FOOTER_GAP
        + fm_footer.height()
        + TOAST_PAD
    )
    assert t_long.height() == expected, (t_long.height(), expected)
    assert t_short.height() < t_long.height()

    # Render da sorunsuz olmalı
    img = t_long.render_to_image(dpr=2.0)
    assert img.width() == 352 * 2
    t_long.deleteLater()
    t_short.deleteLater()
    print("✓ 300 karakterlik gövde 3 satırda kalıyor testi geçti.")


def test_unknown_kind_and_invalid_accent_do_not_raise() -> None:
    """Bilinmeyen tür 'tray' nötr '!' glifi çizmeli; geçersiz aksan çökdürmemeli."""
    name, alert = CASES[-1]  # tray_unknown
    t = Toast(alert)
    assert t._get_glyph() == "!"
    img = t.render_to_image(dpr=2.0)  # raise etmemeli
    assert img.width() == 352 * 2
    # Accent çizimde ACCENT'e düşmeli, Alert içindeki hex değişmemeli
    assert alert.accent == "#123"
    t.deleteLater()
    print("✓ bilinmeyen tür / geçersiz aksan çökmüyor testi geçti.")


def test_accent_mapping() -> None:
    """Çizim aksanı: bilinen hexler kit renklerine; claude+WARN -> CLAUDE."""
    t_warn = Toast(CASES[0][1])
    assert t_warn._paint_accent() == QColor(ps.CLAUDE)  # claude + WARN
    t_crit = Toast(CASES[1][1])
    assert t_crit._paint_accent() == QColor(ps.DANGER)
    t_up = Toast(CASES[2][1])
    assert t_up._paint_accent() == QColor(ps.OK)
    t_tray = Toast(CASES[-1][1])
    # "#123" kısa/bozuk hex sayılır -> ACCENT (görevde 'invalid' olarak işaretli)
    assert t_tray._paint_accent() == QColor(ps.ACCENT)
    t_invalid = Toast(Alert(id="x", title="t", body="b", accent="renk-değil", kind="tray"))
    assert t_invalid._paint_accent() == QColor(ps.ACCENT)
    for tt in (t_warn, t_crit, t_up, t_tray, t_invalid):
        tt.deleteLater()
    print("✓ aksan eşleme testi geçti.")


def test_close_button_and_hover_pause() -> None:
    """× kapatmalı (on_click tetiklemeden); hover zamanlayıcıyı durdurmalı."""
    clicked: list[Alert] = []
    t = Toast(CASES[0][1], on_click=lambda a: clicked.append(a))
    t.render_to_image(dpr=1.0)  # hit rect'leri çizimden doldur
    close = QRectF(t._close_rect)
    assert close.width() == ps.CLOSE_SZ and close.height() == ps.CLOSE_SZ

    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        close.center(),
        close.center(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    t.mousePressEvent(ev)
    assert t._is_dismissing is True
    assert len(clicked) == 0  # × tıklaması on_click çağırmamalı
    t.deleteLater()

    # Hover pause: timer kur, hover'da durmalı, leave'de kalmalı
    t2 = Toast(CASES[2][1])
    t2._timer_deadline = time.time() + 8.0
    t2._dismiss_timer.start(8000)
    t2.enterEvent(None)
    assert t2._is_hovered is True
    assert not t2._dismiss_timer.isActive()
    t2.leaveEvent(None)
    assert t2._is_hovered is False
    assert t2._dismiss_timer.isActive()
    t2.deleteLater()
    print("✓ × kapatma / hover duraklatma testi geçti.")


def test_manager_stacks_without_overlap() -> None:
    """ToastManager 4 uyarıyı da yığınlamalı (en fazla 3 aktif) ve üst üste binmemeli."""
    mgr = ToastManager()
    accents = ("#FFC45C", "#FF6E6E", "#78DC96")
    kinds = ("claude", "sys", "fx")
    for i in range(4):
        mgr.show(
            Alert(
                id=f"stack_{i}",
                title=f"Bildirim {i}",
                body=f"Yığınlama gövdesi {i}.",
                accent=accents[i % 3],
                kind=kinds[i % 3],
            )
        )
    active = mgr.active_toasts
    assert len(active) == 3

    # Yığınlama kayar animasyonla (180 ms) olur: konumların oturması için
    # olay döngüsünü gerçek zamanla birlikte çalıştır.
    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)

    rects = [QRect(t.geometry()) for t in active]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i].intersects(rects[j]), (i, j, rects[i], rects[j])
    mgr.dismiss_all()
    assert len(mgr.active_toasts) == 0
    for _ in range(8):
        app.processEvents()
    time.sleep(0.2)
    for _ in range(4):
        app.processEvents()
    print("✓ ToastManager yığınlama (üst üste binme yok) testi geçti.")


def render_evidence() -> list[Path]:
    """Her durum için DPR 2.0 render + birleştirilmiş pafta (_ref/out)."""
    images: list[tuple[str, QImage]] = []
    for name, alert in CASES:
        t = Toast(alert)
        img = t.render_to_image(dpr=2.0)
        assert img.width() == 352 * 2 and img.height() == t.height() * 2
        path = OUT_DIR / f"v21_toast_{name}.png"
        assert img.save(str(path)) is True
        print(f"  [RENDER] {path} ({img.width()}x{img.height()} px)")
        images.append((name, img))
        t.deleteLater()

    # Hover hali için ek kanıt (claude_warn, tüm gövdeye ince ton)
    t_h = Toast(CASES[0][1])
    hover_img = QImage(
        int(t_h.width() * 2), int(t_h.height() * 2), QImage.Format_ARGB32_Premultiplied
    )
    hover_img.setDevicePixelRatio(2.0)
    hover_img.fill(Qt.GlobalColor.transparent)
    p = QPainter(hover_img)
    t_h._is_hovered = True
    t_h._paint_toast(p, QRectF(0, 0, t_h.width(), t_h.height()))
    t_h._is_hovered = False
    p.end()
    dpr_h = hover_img.devicePixelRatio()
    sample = hover_img.pixelColor(
        int((t_h.width() - 40) * dpr_h), int((t_h.height() - 8) * dpr_h)
    )
    drift = sample.red() - ps.PANEL_BG.red()
    assert 4 <= drift <= 14, (sample, drift)  # ince ton, renk sıçraması yok
    hov_path = OUT_DIR / "v21_toast_claude_warn_hover.png"
    assert hover_img.save(str(hov_path)) is True
    print(f"  [RENDER] {hov_path}")
    t_h.deleteLater()
    images.append(("claude_warn_hover", hover_img))

    # Pafta: dikey dizi
    gap = 12
    total_h = sum(img.height() for _n, img in images) + gap * (len(images) - 1)
    sheet_w = max(img.width() for _n, img in images)
    sheet = QImage(sheet_w, total_h, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor(0x2A, 0x2C, 0x30))
    p = QPainter(sheet)
    y = 0
    for _name, img in images:
        p.drawImage(0, y, img)
        y += img.height() + gap
    p.end()
    sheet_path = OUT_DIR / "v21_toast_sheet.png"
    assert sheet.save(str(sheet_path)) is True
    print(f"  [RENDER] {sheet_path} ({sheet.width()}x{sheet.height()} px)")
    return [OUT_DIR / f"v21_toast_{n}.png" for n, _ in images] + [hov_path, sheet_path]


if __name__ == "__main__":
    test_width_is_shared_panel_width()
    test_pixel_checks()
    test_body_line_cap_300_chars()
    test_unknown_kind_and_invalid_accent_do_not_raise()
    test_accent_mapping()
    test_close_button_and_hover_pause()
    test_manager_stacks_without_overlap()
    render_evidence()
    print("test_v21_toast: ALL PASSED")
