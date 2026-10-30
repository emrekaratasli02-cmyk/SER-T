"""test_v25_pomodoro.py - pomodoro motoru, çubuk bloğu ve panel (sahte saat, gerçek bekleme yok)."""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ["SERIT_TEST"] = "1"
_TMP = tempfile.mkdtemp(prefix="serit_pomo_test_")
os.environ["SERIT_LOG"] = os.path.join(_TMP, "serit.log")
os.environ["SERIT_CACHE_DIR"] = _TMP
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # yalnız bu test işleminde

from PySide6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pomodoro as pm  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def mk(**kw):
    c = Clock()
    return pm.PomodoroTimer(clock=c, **kw), c


def collect(t):
    got = []
    t.phase_finished.connect(lambda a, b: got.append((a, b)))
    return got


def test_start_remaining_progress():
    t, c = mk()
    assert not t.active
    t.start()
    assert t.active and t.running and t.phase == "focus" and t.round_idx == 1
    assert t.remaining_s == 1500 and t.total_s == 1500 and t.progress == 0.0
    c.t += 300
    assert t.remaining_s == 1200 and abs(t.progress - 0.2) < 1e-9
    c.t += 0.5
    assert t.remaining_s == 1200  # ceil: 1199.5 -> 1200


def test_pause_resume():
    t, c = mk()
    t.start()
    c.t += 100
    t.pause()
    assert not t.running and t.remaining_s == 1400
    c.t += 5000
    assert t.remaining_s == 1400
    t.resume()
    assert t.running
    c.t += 40
    assert t.remaining_s == 1360
    t.toggle_pause()
    assert not t.running
    t.toggle_pause()
    assert t.running


def test_full_cycle():
    t, c = mk()
    got = collect(t)
    t.start()
    order = []
    for i in range(4):
        assert t.phase == "focus" and t.round_idx == i + 1, (t.phase, t.round_idx)
        c.t += 1500
        t.tick()
        order.append(got[-1])
        if i < 3:
            assert t.phase == "short" and t.running and t.round_idx == i + 1
            c.t += 300
            t.tick()
            assert t.phase == "focus" and t.round_idx == i + 2
            assert not t.running   # sonraki odak bekler
            t.resume()
    assert t.phase == "long" and t.round_idx == 4 and t.running
    assert order[-1] == ("focus", "long") and order[0] == ("focus", "short")
    c.t += 900
    t.tick()
    assert got[-1] == ("long", "focus") and t.phase == "focus" and t.round_idx == 1 and not t.running


def test_auto_start_flags():
    t, c = mk(auto_start_breaks=False, auto_start_focus=True)
    t.start()
    c.t += 1500
    t.tick()
    assert t.phase == "short" and not t.running
    t.resume()
    c.t += 300
    t.tick()
    assert t.phase == "focus" and t.running


def test_skip_emits_once():
    t, c = mk()
    got = collect(t)
    t.start()
    t.skip()
    assert got == [("focus", "short")]
    assert t.phase == "short" and t.running
    t.skip()
    assert got == [("focus", "short"), ("short", "focus")]
    t.stop()
    t.skip()   # etkin değil: sinyal yok
    assert len(got) == 2


def test_sleep_jump_finishes_once():
    t, c = mk()
    got = collect(t)
    t.start()
    c.t += 99999
    t.tick()
    t.tick()
    t.tick()
    assert got == [("focus", "short")]
    assert t.phase == "short" and t.remaining_s == 300


def test_adjust_clamps():
    t, c = mk()
    t.start()
    t.adjust(5)
    assert t.remaining_s == 1800
    t.adjust(-5)
    assert t.remaining_s == 1500
    t.adjust(200)
    assert t.remaining_s == 5400
    t.adjust(5)
    assert t.remaining_s == 5400
    t.adjust(-200)
    assert t.remaining_s == 60
    t.adjust(-5)
    assert t.remaining_s == 60
    t.pause()
    t.adjust(5)
    assert t.remaining_s == 360
    assert 0.0 <= t.progress <= 1.0


def test_reset_stop():
    t, c = mk()
    t.start()
    c.t += 200
    t.reset()
    assert t.active and not t.running and t.remaining_s == 1500 and t.progress == 0.0
    t.resume()
    c.t += 10
    t.stop()
    assert not t.active and not t.running
    assert pm.band_width(t.state()) == 0.0


def test_internal_qtimer_only_when_running():
    t, c = mk()
    assert not t._qtimer.isActive()
    t.start()
    assert t._qtimer.isActive()
    t.pause()
    assert not t._qtimer.isActive()
    t.resume()
    assert t._qtimer.isActive()
    t.reset()
    assert not t._qtimer.isActive()
    t.resume()
    t.stop()
    assert not t._qtimer.isActive()
    t.start()
    t.skip()   # mola otomatik başlar
    assert t._qtimer.isActive()
    c.t += 300
    t.tick()   # odak bekler
    assert not t._qtimer.isActive()


def test_set_durations_validation():
    t, c = mk()
    t.set_durations(1, 200, 30)
    assert t.durations == (5, 90, 30)
    assert t.total_s == 300 and t.remaining_s == 300   # dokunulmamış evre yeni süreyi alır
    t.set_durations("x", None, 15)
    assert t.durations == (5, 90, 15)
    t.start()
    c.t += 10
    t.set_durations(40, 5, 15)
    assert t.total_s == 300   # akan evre bozulmaz
    t.skip()
    t.skip()
    assert t.total_s == 40 * 60


def test_state_keys():
    t, c = mk()
    keys = {"active", "running", "phase", "round", "rounds", "remaining_s", "total_s", "progress", "task"}
    assert set(t.state()) == keys
    t.set_task("  Rapor  ")
    assert t.state()["task"] == "Rapor"


def _render(state, w=None, h=40.0):
    w = w or max(100.0, pm.band_width(state) + 8)
    img = QImage(int(w * 2), int(h * 2), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(0xFF0D0F13)
    p = QPainter(img)
    pm.draw_pomo_band(p, QRectF(4, 0, pm.band_width(state) or 80, h), state)
    p.end()
    return img


def _st(**kw):
    s = {"active": True, "running": True, "phase": "focus", "round": 2, "rounds": 4, "remaining_s": 1499,
         "total_s": 1500, "progress": 0.4, "task": ""}
    s.update(kw)
    return s


def test_painter_states_and_width():
    long_task = "Çok uzun bir görev adı burada yazıyor ve kesilmeli"
    for st in (_st(task="Rapor kontrolü"), _st(), _st(phase="short", remaining_s=252),
               _st(phase="long"), _st(running=False), _st(task=long_task), _st(task=long_task, running=False)):
        img = _render(st)
        assert not img.isNull()
        w = pm.band_width(st)
        assert 70.0 <= w <= 100.0, (w, st)
    for t in ("24:59", "88:88"):
        w = pm.band_width(_st(remaining_s=int(t[:2]) * 60 + int(t[3:])))
        assert 70.0 <= w <= 100.0, w
    assert pm.band_width(_st(active=False)) == 0.0
    # çizim gerçekten bir şey boyar
    img = _render(_st(task="Rapor"))
    assert any(img.pixel(x, 20) != 0xFF0D0F13 for x in range(img.width()))
    assert 0.0 < pm.band_width(_st(compact=True)) <= 100.0


def test_painter_inactive_noop():
    img = _render(_st(active=False))
    assert img.pixel(5, 5) == 0xFF0D0F13


def _click(panel, key):
    r = panel._rects[key]
    QTest.mouseClick(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center().toPoint())


def test_panel_clicks():
    t, c = mk()
    panel = pm.PomodoroPanel(t)
    panel.show()
    QApplication.processEvents()
    got = collect(t)
    assert "close" in panel._rects and panel._rects["close"].width() >= 24.0
    assert "card_timer" in panel._rects and "card_task" in panel._rects
    assert "skip" in panel._rects and "reset" in panel._rects and "play" in panel._rects and "stop" in panel._rects
    _click(panel, "play")                       # etkin değil -> başlat
    assert t.active and t.running
    _click(panel, "play")
    assert not t.running
    _click(panel, "play")
    assert t.running
    c.t += 100
    _click(panel, "reset")
    assert t.remaining_s == 1500 and not t.running
    _click(panel, "skip")
    assert got == [("focus", "short")] and t.phase == "short"
    _click(panel, "stop")
    assert not t.active
    panel.hide_instant()
    panel.deleteLater()


def test_panel_wheel_chip_and_task():
    t, c = mk()
    panel = pm.PomodoroPanel(t)
    panel.show()
    QApplication.processEvents()
    seen = []
    panel.durations_changed.connect(lambda a, b, d: seen.append((a, b, d)))
    r = panel._rects["chip_0"]
    from PySide6.QtGui import QWheelEvent
    pos = r.center()
    ev = QWheelEvent(pos, panel.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    APP.sendEvent(panel, ev)
    assert seen == [(30, 5, 15)], seen
    assert t.durations == (30, 5, 15)
    # alt sınır
    t.set_durations(5, 5, 15)
    ev2 = QWheelEvent(pos, panel.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, -120),
                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    n = len(seen)
    APP.sendEvent(panel, ev2)
    assert len(seen) == n and t.durations[0] == 5
    # görev yazma
    tasks = []
    panel.task_changed.connect(tasks.append)
    panel._edit.setFocus()
    QTest.keyClicks(panel._edit, "Rapor")
    QTest.keyClick(panel._edit, Qt.Key.Key_Return)
    assert tasks == ["Rapor"] and t.task == "Rapor", (tasks, t.task)
    QTest.keyClick(panel._edit, Qt.Key.Key_Return)
    assert tasks == ["Rapor"]   # değişmedi: yeniden yayılmaz
    panel.hide_instant()
    panel.deleteLater()


def test_panel_render_and_api():
    t, c = mk()
    t.start()
    panel = pm.PomodoroPanel(t)
    assert panel.width() == 352 and not panel.is_open()
    img = panel.render_to_image(1.25)
    assert not img.isNull()
    assert not panel.recently_closed()
    panel.refresh()
    panel.deleteLater()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    order = [
        test_start_remaining_progress, test_pause_resume, test_full_cycle, test_auto_start_flags,
        test_skip_emits_once, test_sleep_jump_finishes_once, test_adjust_clamps, test_reset_stop,
        test_internal_qtimer_only_when_running, test_set_durations_validation, test_state_keys,
        test_painter_states_and_width, test_painter_inactive_noop, test_panel_clicks,
        test_panel_wheel_chip_and_task, test_panel_render_and_api,
    ]
    assert set(order) == set(tests), "listede olmayan test var"
    failed = 0
    for fn in order:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(order) - failed}/{len(order)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
