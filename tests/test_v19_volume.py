"""v19: Ses paneli panel_style v2 üzerinde (352 px, ortak kit).

Testler GERÇEK sese dokunmaz: media.set_volume/toggle_mute ve audio_mixer.list_sessions
Mock ile değiştirilir; volume_panel.sources None yapılarak birleştirme yolları deterministik
(havuza asla SERIT_ALLOW_REAL_AUDIO verilmez, guard'lar atlanmaz).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import media
import panel_style
import volume_panel as vp

# --- Mock'lar: asla gerçek ses API'sine dokunma --------------------------------
media.set_volume = MagicMock()
media.toggle_mute = MagicMock()
vp.sources = None


def _sessions_stub():
    return [dict(s) for s in [
        {"key": "chrome", "name": "Google Chrome", "exe": "C:\\stub\\chrome.exe",
         "level": 80.0, "muted": False, "active": True, "pids": [1010]},
        {"key": "hermes", "name": "Hermes", "exe": "C:\\stub\\hermes.exe",
         "level": 100.0, "muted": False, "active": False, "pids": [1020]},
        {"key": "dikte", "name": "Dikte", "exe": "C:\\stub\\dikte.exe",
         "level": 100.0, "muted": True, "active": False, "pids": [1030]},
        {"key": "system", "name": "Sistem sesleri", "exe": "",
         "level": 100.0, "muted": False, "active": False, "pids": []},
    ]]


vp.audio_mixer = SimpleNamespace(list_sessions=_sessions_stub)


OUT = Path(__file__).resolve().parent.parent / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)
ANCHOR = QRectF(500, 800, 120, 32)


def _mk(level=72.0, muted=False, sessions=None):
    """Stub veriyle panel kur; render_to_image ile isabet dikdörtgenlerini doldur."""
    pop = vp.VolumePopover()
    pop.update_volume(level, muted, "Speakers (Realtek(R) Audio)")
    pop.update_sessions(sessions if sessions is not None else _sessions_stub())
    pop._stamp = "19:58"
    pop.render_to_image(2.0)
    return pop


def ev(t, pt, btn=Qt.MouseButton.LeftButton):
    return QMouseEvent(t, QPointF(pt), QPointF(pt), btn, btn, Qt.KeyboardModifier.NoModifier)


def test_width():
    pop = _mk()
    assert pop.WIDTH == panel_style.WIDTH["vol"] == 352
    assert pop.width() == 352
    assert pop.height() == pop.compute_height()


def test_header_close_click_closes():
    pop = _mk()
    pop.show_for(ANCHOR, 50.0, False, "Speakers (Realtek(R) Audio)")
    pop.render_to_image(2.0)
    assert not pop._btn_close_rect.isNull()
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, pop._btn_close_rect.center()))
    assert pop._is_closing
    assert pop.recently_closed()
    pop.hide_instant()
    assert not pop.isVisible()
    assert pop.recently_closed()


def test_master_drag_goes_through_coalescer_to_mocked_setter():
    pop = vp.VolumePopover()
    pop.show_for(ANCHOR, 40.0, False, "Speakers (Realtek(R) Audio)")
    assert media.set_volume.call_count == 0            # show_for hiçbir şey yazmadı
    pop.render_to_image(2.0)
    hit = pop._hit_master_slider
    y = hit.center().y()
    x0 = hit.left() + hit.width() * 0.4
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, QPointF(x0, y)))
    assert pop._dragging == "master"
    for f in (0.5, 0.55, 0.58):
        pop.mouseMoveEvent(ev(QEvent.Type.MouseMove, QPointF(hit.left() + hit.width() * f, y)))
    assert pop._level == 58
    pop.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, QPointF(hit.left() + hit.width() * 0.58, y)))
    assert pop._dragging is None
    # Birleştirici yoldan geçti: kanıt için birleşik giden değer listesi ters akışla toplanamaz;
    # kapanışta force=True deveyi (flush) en az bir kez gerçek setter mock'una ulaştırmalı
    assert media.set_volume.call_count >= 1, media.set_volume.mock_calls
    assert media.set_volume.call_args_list[-1][0][0] == 58
    assert pop._level == 58
    from unittest.mock import MagicMock as _M
    assert isinstance(media.set_volume, _M)   # gerçek setter değil, mock
    pop.hide_instant()


def test_per_app_compact_slider_hit_rects():
    pop = _mk(60.0)
    rows = pop._hit_app_rows
    assert len(rows) == 4
    for r in rows:
        tr = r["track_rect"]
        assert tr.width() > 140, tr              # compact iz yeterince geniş
        assert tr.height() <= 12, tr             # 10 px compact iz (18 px ana izden küçük)
        assert r["mute_rect"].width() == vp.APP_MUTE_SZ
    tr0 = rows[0]["track_rect"]
    x0 = tr0.left() + tr0.width() * 0.3
    y0 = tr0.center().y()
    pop.mousePressEvent(ev(QEvent.Type.MouseButtonPress, QPointF(x0, y0)))
    assert pop._dragging == "app:chrome"
    assert pop._sessions[0]["level"] == 30
    pop.mouseMoveEvent(ev(QEvent.Type.MouseMove, QPointF(tr0.left() + tr0.width() * 0.45, y0)))
    pop.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, QPointF(x0, y0)))
    assert pop._dragging is None and pop._sessions[0]["level"] == 45
    pop._app_coalescer.request("chrome", 45, force=True)   # birleştirici yolu da dener
    pop.hide_instant()


def test_wheel_steps():
    pop = _mk(50.0)
    hit = pop._hit_master_slider
    c = hit.center()
    w = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, 120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase, False)
    pop.wheelEvent(w)
    assert pop._level == 52
    row = pop._hit_app_rows[1]["track_rect"].center()
    w2 = QWheelEvent(QPointF(row), QPointF(row), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    pop.wheelEvent(w2)
    assert pop._sessions[1]["level"] == 98


def test_muted_master_shows_sessiz_and_no_fill():
    pop = _mk(72.0, muted=True)
    img = pop.render_to_image(2.0)
    tr = pop._hit_master_slider
    # İz içi pixel; mavi dolgu YOK (sessizde iz boşluğu)
    pt = QPointF(tr.left() + 12.0, tr.center().y())
    c = img.pixelColor(int(pt.x() * 2), int(pt.y() * 2))
    assert not (c.blue() > c.red() + 60), c.getRgb()          # SOUND mavisi değil
    # 'Sessiz' etiketi (DANGER kırmızısı) etiket satırında aranır
    sr = pop._hit_master_slider
    label_y = (tr.top() - 14.0) * 2
    found = False
    for dx in range(int(sr.right() * 2) - 140, int(sr.right() * 2), 2):
        for dy in range(int(label_y) - 4, int(label_y) + 40, 2):
            pc = img.pixelColor(dx, dy)
            if pc.red() > 200 and pc.green() < 130 and pc.blue() < 130:
                found = True
                break
        if found:
            break
    assert found, "sessiz etiketi (kırmızı) metabolik pikselde bulunamadı"
    pop.hide_instant()


def test_empty_state_text():
    pop = _mk(sessions=[])
    assert vp.EMPTY_APPS_TEXT == "Ses çalan uygulama yok"
    assert pop._sessions == [] and pop._hit_app_rows == []
    img = pop.render_to_image(2.0)
    # Uygulamalar kartı merkez civarında soluk metin pikseli (boş durum) aranır
    cx, cy = int(pop.width() / 2 * 2), int((pop.compute_height() - 90) * 2)
    found = any(img.pixelColor(cx + dx, cy + dy).red() > 90
                for dx in range(-120, 120, 4) for dy in range(-20, 20, 2))
    assert found, "boş durum metni piksel olarak bulunamadı"


def test_show_for_switch_and_hide_instant_offscreen():
    pop = vp.VolumePopover()
    pop.show_for(QRectF(40, 40, 120, 32), 30.0, False, "Speakers (Realtek(R) Audio)",
                 switch_from_x=300)
    assert pop.is_open()
    assert pop.isVisible()
    assert pop._sessions, "stub oturumlar show_for ile geldi"
    pop.hide_instant()
    assert not pop.isVisible()
    assert pop.recently_closed()
    pop.show_for(ANCHOR, 66.0, False, "Speakers (Realtek(R) Audio)")
    assert pop.is_open() and pop.width() == panel_style.WIDTH["vol"]
    pop.hide_instant()


def test_renders_dpr2_stub():
    # ses_normal: 4 uygulama, biri çalıyor (chrome), biri sessiz (Dikte)
    pop = _mk(72.0)
    assert len(pop._hit_app_rows) == 4
    assert pop._sessions[0]["active"] and pop._sessions[2]["muted"]
    pop.render_to_image(2.0).save(str(OUT / "ses_normal.png"))
    # ses_sessiz: ana ses sessiz
    mpop = _mk(72.0, muted=True)
    mpop.render_to_image(2.0).save(str(OUT / "ses_sessiz.png"))
    # ses_bos: uygulama yok
    bpop = _mk(50.0, sessions=[])
    bpop.render_to_image(2.0).save(str(OUT / "ses_bos.png"))
    # ses_bilinmiyor: bilinmeyen seviye -> '—'
    stubs = _sessions_stub()
    stubs[0]["level"] = None
    stubs[0]["muted"] = False
    upop = _mk(50.0, sessions=stubs)
    assert upop._sessions[0]["level"] is None
    upop.render_to_image(2.0).save(str(OUT / "ses_bilinmiyor.png"))
    for name in ("ses_normal.png", "ses_sessiz.png", "ses_bos.png", "ses_bilinmiyor.png"):
        f = OUT / name
        assert f.exists() and f.stat().st_size > 5000, (name, f.stat().st_size if f.exists() else -1)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("PASS", n)
