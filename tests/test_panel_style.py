"""Tests for panel_style v2 (Approved Sheet A & B shared drawing kit) and panel_kit.png self-check."""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path("D:/Apps/serit")
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

import panel_style as ps


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _rect_inside(outer: QRectF, inner: QRectF, tol: float = 2.0) -> bool:
    return (
        inner.left() >= outer.left() - tol
        and inner.top() >= outer.top() - tol
        and inner.right() <= outer.right() + tol
        and inner.bottom() <= outer.bottom() + tol
    )


def _count_color_pixels(img: QImage, rect: QRectF, dpr: float, target: QColor, tol: int = 30) -> int:
    x0 = max(0, int(rect.left() * dpr))
    y0 = max(0, int(rect.top() * dpr))
    x1 = min(img.width(), int(rect.right() * dpr))
    y1 = min(img.height(), int(rect.bottom() * dpr))
    tr, tg, tb = target.red(), target.green(), target.blue()
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            if abs(c.red() - tr) <= tol and abs(c.green() - tg) <= tol and abs(c.blue() - tb) <= tol:
                count += 1
    return count


def test_constants_and_legacy_compat() -> None:
    assert ps.HEADER_H == 32.0
    assert ps.FOOTER_H == 32.0
    assert ps.PAD == 16.0
    assert ps.GAP == 12.0
    assert ps.CARD_PAD == 13.0
    assert ps.TILE_PAD == 13.0
    assert ps.R_PANEL == 16.0
    assert ps.R_TILE == 12.0
    assert ps.R_BUTTON == 8.0
    assert isinstance(ps.WIDTH, dict) and ps.WIDTH["sys"] == ps.PANEL_W == 352  # 27 Eki: tüm tek sütun paneller 352
    assert ps.pct(25.4) == "%25"
    assert ps.pct(None) == "—"

    _ensure_app()
    assert ps.f_hero().pixelSize() > 0
    assert ps.f_title().pixelSize() == 15
    assert ps.f_label().pixelSize() > 0
    assert ps.f_body().pixelSize() > 0
    assert ps.f_small().pixelSize() == 11


def test_turkish_upper() -> None:
    assert ps.turkish_upper("işlemci") == "İŞLEMCİ"
    assert ps.turkish_upper("ekran parlaklığı") == "EKRAN PARLAKLIĞI"
    assert ps.turkish_upper("hızlı önayarlar") == "HIZLI ÖNAYARLAR"
    assert ps.turkish_upper("kullanım göstergeleri") == "KULLANIM GÖSTERGELERİ"
    assert ps.turkish_upper("") == ""


def test_slider_value_at() -> None:
    track = QRectF(20.0, 50.0, 200.0, 18.0)
    assert ps.slider_value_at(track, 20.0) == 0
    assert ps.slider_value_at(track, 220.0) == 100
    assert ps.slider_value_at(track, 120.0) == 50
    assert ps.slider_value_at(track, -50.0) == 0
    assert ps.slider_value_at(track, 500.0) == 100
    assert ps.slider_value_at(QRectF(10.0, 10.0, 0.0, 18.0), 15.0) == 0


def test_helpers_dpr_and_hit_rects() -> None:
    _ensure_app()
    for dpr in (1.0, 2.0):
        w, h = 400, 620
        img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        panel_rect = QRectF(10.0, 10.0, 360.0, 580.0)
        ps.draw_panel_shell(p, panel_rect)

        # 1. draw_header (with icon callable, chip, chip_dot)
        hdr_rect = QRectF(26.0, 26.0, 328.0, ps.HEADER_H)
        hdr_hits = ps.draw_header(
            p,
            hdr_rect,
            "Sistem",
            icon=lambda qp, r: qp.fillRect(r, ps.CPU),
            chip="Canlı",
            chip_dot=ps.OK,
            close_hover=True,
        )
        assert isinstance(hdr_hits, dict)
        assert hdr_hits["close"] is not None and _rect_inside(hdr_rect, hdr_hits["close"])
        assert hdr_hits["chip"] is not None and _rect_inside(hdr_rect, hdr_hits["chip"])

        # draw_header without chip, with QPixmap icon
        pm = QPixmap(16, 16)
        pm.fill(ps.ACCENT)
        hdr2_hits = ps.draw_header(p, hdr_rect, "Başlık", icon=pm, chip=None, close_hover=False)
        assert hdr2_hits["close"] is not None and _rect_inside(hdr_rect, hdr2_hits["close"])
        assert hdr2_hits["chip"] is None

        # 2. draw_card
        card_rect = QRectF(26.0, 70.0, 328.0, 130.0)
        content_rect = ps.draw_card(
            p,
            card_rect,
            overline="ekran parlaklığı",
            overline_right="Uygulamalar ›",
            hover=False,
        )
        assert _rect_inside(card_rect, content_rect)
        assert content_rect.top() > card_rect.top() + ps.CARD_PAD

        # draw_card without overline
        plain_inner = ps.draw_card(p, card_rect, overline=None, hover=True)
        assert _rect_inside(card_rect, plain_inner)

        # 3. draw_slider (active value)
        sl_rect = QRectF(content_rect.left(), content_rect.top(), content_rect.width(), 44.0)
        sl_hits = ps.draw_slider(
            p,
            sl_rect,
            "Dizüstü",
            67,
            fill=ps.BRIGHT_FILL,
            icon=lambda qp, r: qp.fillRect(r, ps.TEXT),
            hover=True,
            muted=False,
        )
        assert _rect_inside(sl_rect, sl_hits["track"])
        assert _rect_inside(sl_rect, sl_hits["knob"], tol=3.0)

        # 4. draw_ring_with_text & draw_ring
        ps.draw_ring_with_text(p, 90.0, 250.0, 28, ps.CPU, sub="İşlemci", meta="Core 5 210H")
        ps.draw_ring_with_text(p, 200.0, 250.0, None, ps.RAM, sub="Bellek", meta="—")

        # 5. draw_thin_bar
        tb_rect = QRectF(26.0, 310.0, 328.0, 10.0)
        ps.draw_thin_bar(p, tb_rect, 82, ps.ACCENT)

        # 6. draw_preset_pills
        pr_rect = QRectF(26.0, 330.0, 328.0, 32.0)
        pill_rects = ps.draw_preset_pills(p, pr_rect, ["%25", "%50", "%75", "%100"], active_index=2, hover_index=0)
        assert len(pill_rects) == 4
        for pr in pill_rects:
            assert _rect_inside(pr_rect, pr)

        # 7. draw_toggle_button
        tg1_rect = QRectF(26.0, 375.0, 160.0, ps.TOGGLE_H)
        tg1 = ps.draw_toggle_button(
            p,
            tg1_rect,
            "Wi-Fi",
            "Karatasli_5G",
            icon=lambda qp, r: qp.fillRect(r, ps.ACCENT),
            state="on",
            hover_part="main",
            has_chevron=True,
        )
        assert _rect_inside(tg1_rect, tg1["main"])
        assert tg1["chevron"] is not None and _rect_inside(tg1_rect, tg1["chevron"])

        tg2_rect = QRectF(194.0, 375.0, 160.0, ps.TOGGLE_H)
        tg2 = ps.draw_toggle_button(
            p,
            tg2_rect,
            "Uçak modu",
            None,
            state="off",
            hover_part=None,
            has_chevron=False,
        )
        assert _rect_inside(tg2_rect, tg2["main"])
        assert tg2["chevron"] is None

        for st in ("unavailable", "busy"):
            ps.draw_toggle_button(p, tg2_rect, "Test", "Alt", state=st, hover_part="chevron", has_chevron=True)

        # 8. draw_badge
        for i, kind in enumerate(("danger", "ok", "info", "muted")):
            b_rect = QRectF(26.0 + i * 75.0, 425.0, 70.0, 22.0)
            out_b = ps.draw_badge(p, b_rect, kind.upper(), kind=kind)
            assert _rect_inside(b_rect, out_b)
        ps.draw_badge(p, QPointF(26.0, 452.0), "NOKTA", kind="info")
        ps.draw_badge(p, (120.0, 452.0), "DEMET", kind="ok")

        # 9. draw_footer
        ft_rect = QRectF(26.0, 540.0, 328.0, ps.FOOTER_H)
        btn_rect = ps.draw_footer(p, ft_rect, "Bu bilgisayar · 20:40", button_text="Yenile", button_hover=True)
        assert btn_rect is not None and _rect_inside(ft_rect, btn_rect)
        assert ps.draw_footer(p, ft_rect, "Kaynak", button_text=None) is None

        p.end()


def test_none_values_draw_no_fill() -> None:
    _ensure_app()
    for dpr in (1.0, 2.0):
        img = QImage(int(300 * dpr), int(260 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(ps.TILE_BG)

        p = QPainter(img)
        fill_color = QColor("#FF0055")  # unmistakable bright magenta

        # Slider with value=None
        sl_rect = QRectF(20.0, 20.0, 260.0, 44.0)
        sl_hits = ps.draw_slider(p, sl_rect, "Yok", None, fill=fill_color)
        assert sl_hits["knob"].width() == 0.0

        # Thin bar with value=None
        tb_rect = QRectF(20.0, 80.0, 260.0, 10.0)
        ps.draw_thin_bar(p, tb_rect, None, fill_color)

        # Ring with value=None
        ring_rect = QRectF(118.0, 110.0, 64.0, 64.0)
        ps.draw_ring_with_text(p, 150.0, 142.0, None, fill_color, sub="Yok")

        p.end()

        assert _count_color_pixels(img, sl_rect, dpr, fill_color) == 0
        assert _count_color_pixels(img, tb_rect, dpr, fill_color) == 0
        assert _count_color_pixels(img, ring_rect, dpr, fill_color) == 0


# --- Icon painters for visual self-check sheet -----------------------------------------------

def _draw_sys_header_icon(p: QPainter, r: QRectF) -> None:
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    bg = QColor(ps.CPU)
    bg.setAlpha(38)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawPath(ps.rounded(r, ps.R_ICON_BOX))

    pen = QPen(ps.CPU, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    p.drawRoundedRect(QRectF(cx - 6.0, cy - 5.5, 12.0, 8.5), 1.5, 1.5)
    p.drawLine(QPointF(cx - 3.0, cy + 5.5), QPointF(cx + 3.0, cy + 5.5))
    p.drawLine(QPointF(cx, cy + 3.0), QPointF(cx, cy + 5.5))


def _draw_laptop_icon(p: QPainter, r: QRectF) -> None:
    pen = QPen(ps.TEXT_SLIDER, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    p.drawRoundedRect(QRectF(cx - 5.5, cy - 4.5, 11.0, 7.5), 1.2, 1.2)
    p.drawLine(QPointF(cx - 6.5, cy + 4.5), QPointF(cx + 6.5, cy + 4.5))


def _draw_monitor_icon(p: QPainter, r: QRectF) -> None:
    pen = QPen(ps.TEXT_SLIDER, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    p.drawRoundedRect(QRectF(cx - 5.5, cy - 5.0, 11.0, 7.5), 1.2, 1.2)
    p.drawLine(QPointF(cx - 2.5, cy + 5.0), QPointF(cx + 2.5, cy + 5.0))
    p.drawLine(QPointF(cx, cy + 2.5), QPointF(cx, cy + 5.0))


def _draw_wifi_icon(p: QPainter, r: QRectF) -> None:
    pen = QPen(ps.ACCENT, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y() + 4.0
    for rad in (3.2, 6.2, 9.2):
        arc_r = QRectF(cx - rad, cy - rad, rad * 2.0, rad * 2.0)
        p.drawArc(arc_r, 45 * 16, 90 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ps.ACCENT)
    p.drawEllipse(QPointF(cx, cy), 1.3, 1.3)


def _draw_bt_icon(p: QPainter, r: QRectF) -> None:
    pen = QPen(QColor(255, 255, 255, 140), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    pts = [
        QPointF(cx - 3.2, cy - 3.2),
        QPointF(cx + 3.2, cy + 3.2),
        QPointF(cx, cy + 6.2),
        QPointF(cx, cy - 6.2),
        QPointF(cx + 3.2, cy - 3.2),
        QPointF(cx - 3.2, cy + 3.2),
    ]
    for i in range(len(pts) - 1):
        p.drawLine(pts[i], pts[i + 1])


def generate_self_check_sheet() -> Path:
    _ensure_app()
    out_dir = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v19")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "panel_kit.png"

    dpr = 2.0
    margin = 24.0
    panel_w = 360.0

    # Calculate exact panel height from components + gaps
    sliders_card_h = 142.0
    rings_card_h = 152.0
    toggles_card_h = 90.0
    presets_card_h = 80.0
    panel_h = (
        ps.PAD
        + ps.HEADER_H
        + ps.GAP
        + sliders_card_h
        + ps.GAP
        + rings_card_h
        + ps.GAP
        + toggles_card_h
        + ps.GAP
        + presets_card_h
        + ps.GAP
        + ps.FOOTER_H
        + ps.PAD
    )
    canvas_w = int(panel_w + margin * 2)
    canvas_h = int(panel_h + margin * 2)

    img = QImage(int(canvas_w * dpr), int(canvas_h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor("#0C0D0F"))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    panel_rect = QRectF(margin, margin, panel_w, panel_h)
    ps.draw_panel_shell(p, panel_rect)

    x0 = panel_rect.left() + ps.PAD
    cw = panel_w - 2 * ps.PAD
    y = panel_rect.top() + ps.PAD

    # 1. Header with chip + close
    hdr_rect = QRectF(x0, y, cw, ps.HEADER_H)
    ps.draw_header(
        p,
        hdr_rect,
        "Sistem & Kontroller",
        icon=_draw_sys_header_icon,
        chip="Canlı",
        chip_dot=ps.OK,
        close_hover=False,
    )
    y += ps.HEADER_H + ps.GAP

    # 2. Card with overline and two sliders 'Dizüstü %67' / 'MSI MP223 %82'
    sliders_card_rect = QRectF(x0, y, cw, sliders_card_h)
    sl_inner = ps.draw_card(p, sliders_card_rect, overline="Ekran Parlaklığı")
    s1_rect = QRectF(sl_inner.left(), sl_inner.top(), sl_inner.width(), 42.0)
    ps.draw_slider(p, s1_rect, "Dizüstü", 67, fill=ps.BRIGHT_FILL, icon=_draw_laptop_icon)
    s2_rect = QRectF(sl_inner.left(), s1_rect.bottom() + 10.0, sl_inner.width(), 42.0)
    ps.draw_slider(p, s2_rect, "MSI MP223", 82, fill=ps.BRIGHT_FILL, icon=_draw_monitor_icon)
    y += sliders_card_h + ps.GAP

    # 3. Ring row CPU 28 / RAM 74
    rings_card_rect = QRectF(x0, y, cw, rings_card_h)
    rg_inner = ps.draw_card(p, rings_card_rect, overline="Donanım Kaynakları")
    ring_cy = rg_inner.top() + 34.0
    cx_cpu = rg_inner.left() + rg_inner.width() * 0.28
    cx_ram = rg_inner.left() + rg_inner.width() * 0.72
    ps.draw_ring_with_text(p, cx_cpu, ring_cy, 28, ps.CPU, sub="İşlemci", meta="Core 5 210H")
    ps.draw_ring_with_text(p, cx_ram, ring_cy, 74, ps.RAM, sub="Bellek", meta="11,6 / 15,7 GB")
    y += rings_card_h + ps.GAP

    # 4. Two toggle buttons Wi-Fi 'Karatasli_5G' on and Bluetooth 'Kapalı' off
    toggles_card_rect = QRectF(x0, y, cw, toggles_card_h)
    tg_inner = ps.draw_card(p, toggles_card_rect, overline="Hızlı Anahtarlar")
    tg_gap = 8.0
    tg_w = (tg_inner.width() - tg_gap) / 2.0
    w_rect = QRectF(tg_inner.left(), tg_inner.top(), tg_w, ps.TOGGLE_H)
    b_rect = QRectF(w_rect.right() + tg_gap, tg_inner.top(), tg_w, ps.TOGGLE_H)
    ps.draw_toggle_button(
        p,
        w_rect,
        "Wi-Fi",
        "Karatasli_5G",
        icon=_draw_wifi_icon,
        state="on",
        has_chevron=True,
    )
    ps.draw_toggle_button(
        p,
        b_rect,
        "Bluetooth",
        "Kapalı",
        icon=_draw_bt_icon,
        state="off",
        has_chevron=True,
    )
    y += toggles_card_h + ps.GAP

    # 5. Preset pills card
    presets_card_rect = QRectF(x0, y, cw, presets_card_h)
    pr_inner = ps.draw_card(p, presets_card_rect, overline="Hızlı Önayarlar")
    ps.draw_preset_pills(
        p,
        QRectF(pr_inner.left(), pr_inner.top(), pr_inner.width(), ps.PRESET_PILL_H),
        ["%25", "%50", "%75", "%100"],
        active_index=2,
    )
    y += presets_card_h + ps.GAP

    # 6. Footer 'Bu bilgisayar · 20:40' + 'Yenile'
    footer_rect = QRectF(x0, y, cw, ps.FOOTER_H)
    ps.draw_footer(p, footer_rect, "Bu bilgisayar · 20:40", button_text="Yenile")

    p.end()
    assert img.save(str(out_path))
    assert out_path.exists() and out_path.stat().st_size > 5000
    return out_path


def main() -> int:
    test_constants_and_legacy_compat()
    test_turkish_upper()
    test_slider_value_at()
    test_helpers_dpr_and_hit_rects()
    test_none_values_draw_no_fill()
    test_animate_in_out()
    out = generate_self_check_sheet()
    print(f"ALL test_panel_style checks passed. Self-check sheet: {out}")
    return 0



def test_animate_in_out() -> None:
    """Ortak açılış/kapanış hareketi: sonunda hedef konumda, saydamlık 1; kapanınca gizli ve konum geri."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    w = QWidget()
    w.resize(120, 80)
    target = QPoint(200, 300)

    def finish() -> None:
        """Animasyonu zamana bağlı beklemeden sonuna getir (test makine yükünden etkilenmesin)."""
        g = getattr(w, "_ps_anim", None)
        if g is not None:
            g.setCurrentTime(g.totalDuration())
        app.processEvents()

    ps.animate_in(w, target)
    finish()
    assert w.isVisible() and w.pos() == target, w.pos()
    assert abs(w.windowOpacity() - 1.0) < 0.01
    done = []
    ps.animate_out(w, on_done=lambda: done.append(1))
    finish()
    assert not w.isVisible() and done == [1] and abs(w.windowOpacity() - 1.0) < 0.01
    ps.animate_in(w, target, switch_from_x=50)
    finish()
    assert w.pos() == target
    ps.animate_out(w, instant=True)
    assert not w.isVisible()
    print("[PASS] animate_in / animate_out")



if __name__ == "__main__":
    raise SystemExit(main())

