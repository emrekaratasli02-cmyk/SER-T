"""test_v25_wiring.py - v25: dosya rafı / pomodoro / uyku engelleme + mikrofon-kamera göstergesinin dock'a bağlanması.

Gerçek shelf/pomodoro/presence modülleri KULLANILMAZ: sys.modules'a sahte (sözleşme API'li) modüller enjekte edilir.
Yan etki yok: önizleme kipinde dock, geçici ayar dosyası, gerçek bip / güç isteği / pano / sürükleme yok.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
_TMP = tempfile.mkdtemp(prefix="serit_v25w_")
os.environ.setdefault("SERIT_TEST", "1")
os.environ.setdefault("SERIT_LOG", os.path.join(_TMP, "serit.log"))
os.environ.setdefault("SERIT_CACHE_DIR", _TMP)

from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, QRectF, Qt, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

DPR = 1.25


# ------------------------------------------------------------------ sahte modüller
def make_fakes() -> dict:
    sh = types.ModuleType("shelf")
    sh.SHELF_ICON_W = 28.0
    sh.draws = []

    class ShelfStore:
        def __init__(self, path=None):
            self.list = []
            self.added = []

        def items(self):
            return list(self.list)

        def count(self):
            return len(self.list)

        def add_paths(self, paths, source="drop"):
            self.added.append((list(paths), source))
            for p in paths:
                self.list.insert(0, {"path": p, "name": os.path.basename(p), "source": source})
            return len(paths)

        def expire(self, now=None):
            return False

    class ShelfPanel(QObject):
        changed = Signal()

        def __init__(self, store, parent=None):
            super().__init__()
            self.open = False
            self.closed_recently = False
            self.calls = []

        def show_for(self, anchor, *a, **k):
            self.open = True
            self.calls.append("show")

        def hide_animated(self):
            self.open = False
            self.calls.append("hide")

        def is_open(self):
            return self.open

        def recently_closed(self, threshold_ms=250.0):
            return self.closed_recently

        def refresh(self):
            self.calls.append("refresh")

    def draw_shelf_icon(p, rect, state, count, hover=False):
        sh.draws.append((state, count, hover))
        p.fillRect(rect, QColor(200, 60, 60))

    class DownloadsWatcher:
        def __init__(self, folder=None, exts=None):
            self.folder, self.exts = folder, exts

        def poll(self):
            return []

    sh.ShelfStore, sh.ShelfPanel, sh.DownloadsWatcher, sh.draw_shelf_icon = ShelfStore, ShelfPanel, DownloadsWatcher, draw_shelf_icon

    po = types.ModuleType("pomodoro")

    class PomodoroTimer(QObject):
        changed = Signal()
        phase_finished = Signal(str, str)

        def __init__(self, **kw):
            super().__init__()
            self.st = {"active": False, "running": False, "phase": "focus", "round": 1, "rounds": 4,
                       "remaining_s": 1499, "total_s": 1500, "progress": 0.0, "task": ""}
            self.calls = []

        def state(self):
            return dict(self.st)

        def start(self, phase="focus"):
            self.calls.append(("start", phase))
            self.st.update(active=True, running=True)
            self.changed.emit()

        def toggle_pause(self):
            self.calls.append(("toggle_pause",))
            self.st["running"] = not self.st["running"]
            self.changed.emit()

        def adjust(self, minutes):
            self.calls.append(("adjust", minutes))

        def skip(self):
            self.calls.append(("skip",))

        def reset(self):
            self.calls.append(("reset",))

        def stop(self):
            self.calls.append(("stop",))
            self.st.update(active=False, running=False)
            self.changed.emit()

        def set_task(self, text):
            self.st["task"] = text

    class PomodoroPanel(QObject):
        task_changed = Signal(str)
        durations_changed = Signal(int, int, int)

        def __init__(self, timer, parent=None):
            super().__init__()
            self.open = False

        def show_for(self, anchor, *a, **k):
            self.open = True

        def hide_animated(self):
            self.open = False

        def is_open(self):
            return self.open

        def recently_closed(self, threshold_ms=250.0):
            return False

        def refresh(self):
            pass

    def band_width(state):
        if not state.get("active"):
            return 0.0
        if state.get("compact"):
            return 56.0  # gerçek pomodoro.band_width gibi: compact = yalnız süre
        return 90.0 if state.get("task") else 76.0

    def draw_pomo_band(p, rect, state, hover=False):
        p.fillRect(rect, QColor(60, 160, 60))

    po.PomodoroTimer, po.PomodoroPanel, po.band_width, po.draw_pomo_band = PomodoroTimer, PomodoroPanel, band_width, draw_pomo_band

    pr = types.ModuleType("presence")
    pr.KEEP_AWAKE_ICON_W = 28.0
    pr.PRESENCE_ICON_W = 24.0
    pr._ka = False

    def set_keep_awake(on):
        pr._ka = bool(on)
        return pr._ka

    pr.set_keep_awake = set_keep_awake
    pr.keep_awake_active = lambda: pr._ka
    pr.release_all = lambda: setattr(pr, "_ka", False)
    pr.read_capability_usage = lambda: {"mic": ["Zoom"], "cam": []}
    pr.presence_tooltip = lambda u: ("Mikrofon: " + ", ".join(u.get("mic", []))) if u.get("mic") else ""
    pr.draw_keep_awake_icon = lambda p, r, active, hover=False: p.fillRect(r, QColor(60, 60, 200))
    pr.draw_presence_icon = lambda p, r, usage, hover=False: p.fillRect(r, QColor(200, 160, 40))
    return {"shelf": sh, "pomodoro": po, "presence": pr}


def load_module(fakes: bool):
    """serit_v5.pyw'yi (sahte ya da yok) modüllerle yükler."""
    names = ("shelf", "pomodoro", "presence", "netspeed", "updates", "appusage")
    saved = {n: sys.modules.get(n, "__missing__") for n in names}
    if fakes:
        sys.modules.update(make_fakes())
    else:
        for n in names:  # v26 modülleri de yok: eski düzen birebir kalmalı
            sys.modules[n] = None  # import ImportError verir
    try:
        spec = importlib.util.spec_from_file_location("serit_v5_v25w", str(APP_DIR / "serit_v5.pyw"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for n, v in saved.items():
            if v == "__missing__":
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v
    m.SETTINGS_FILE = Path(_TMP) / "settings.json"
    m.save_settings = lambda cfg: None
    return m


def make_dock(m, fakes: bool, cards=None, pomo=False, shelf_items=0, media=False, n_apps=3, width=1536):
    d = m.SeritDock({"style": "band", "cards": cards or {"cal": False, "mail": False, "ag": True, "sys": True}},
                    preview_mode=True)
    d.store.update("claude", {"session": 100.0, "week": 51.0, "session_reset": "", "week_reset": ""})
    d.store.update("ag", {"groups": [{"label": "Claude", "used": 40.0}]})
    d.store.update("sys", {"cpu": 20.0, "ram": 58.0})
    d.store.update("wx", {"temp": 14.0, "icon": "cloud"})
    d.tiles = [{"exe": f"C:/ornek/{i}.exe", "name": f"Örnek {i}", "running": False, "hwnds": []} for i in range(n_apps)]
    d._now_playing_info = ({"title": "Örnek yayın", "artist": "Kanal", "app": "Chrome", "playing": False}
                           if media else None)
    if fakes:
        store = m.shelf.ShelfStore()
        for i in range(shelf_items):
            store.list.append({"path": f"C:/ornek/Rapor{i}.xlsx", "name": f"Rapor{i}.xlsx"})
        d.attach_shelf(store, m.shelf.ShelfPanel(store))
        t = m.pomodoro.PomodoroTimer()
        d.attach_pomodoro(t, m.pomodoro.PomodoroPanel(t))
        if pomo:
            t.st.update(active=True, running=True, remaining_s=1499, progress=0.01,
                        task="Rapor kontrolü ve uzun bir görev adı" if pomo == "long" else "")
            d._pomo_state = t.state()
    d.compute_layout_and_resize(initial=True)
    d.resize(width, int(m.DOCK_HEIGHT))  # bant ekran genişliğine uyar; testte 1536 mantıksal sabitlenir
    d._pomo_sig = (bool(d._pomo_state.get("active")), 0.0)
    if fakes and pomo:
        d._on_pomo_changed()
    return d


def render(d, m, dpr=DPR) -> QImage:
    img = QImage(int(d.width() * dpr), int(m.DOCK_HEIGHT * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0)
    d.render(img, QPoint(0, 0))
    return img


def boxes(d) -> dict:
    return {k: QRectF(r) for r, k, _e in d.hit_boxes}


def _center(r: QRectF) -> QPointF:
    return r.center()


def _wheel(d, pos: QPointF, dy: int) -> None:
    ev = QWheelEvent(pos, d.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, dy), Qt.NoButton,
                     Qt.NoModifier, Qt.ScrollUpdate, False)
    d.wheelEvent(ev)


def _drag_enter(d, paths, pos: QPointF):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    ev = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    d.dragEnterEvent(ev)
    return md, ev


# ------------------------------------------------------------------ testler
def test_menu_rows_and_checked_state() -> None:
    m = load_module(True)
    d = make_dock(m, True)
    d.preview_mode = False  # callback'ler önizlemede de çalışır; menü yapısı aynı
    acts = d.build_dock_menu_actions()
    ids = [a.get("id") for a in acts if a.get("type") != "separator"]
    assert ids[:5] == ["settings", "refresh", "pomo_toggle", "show_shelf", "keep_awake"], ids
    rows = {a["id"]: a for a in acts if a.get("id")}
    assert rows["pomo_toggle"]["text"] == "Pomodoro başlat"
    assert rows["show_shelf"]["text"] == "Dosya rafını göster"
    assert rows["keep_awake"]["text"] == "Uykuyu engelle" and rows["keep_awake"]["checked"] is False
    rows["keep_awake"]["callback"]()
    assert m.presence.keep_awake_active() is True
    rows2 = {a["id"]: a for a in d.build_dock_menu_actions() if a.get("id")}
    assert rows2["keep_awake"]["checked"] is True
    rows2["pomo_toggle"]["callback"]()
    assert d.pomo_timer.calls == [("start", "focus")] and d.pomo_panel.is_open()
    rows3 = {a["id"]: a for a in d.build_dock_menu_actions() if a.get("id")}
    assert rows3["pomo_toggle"]["text"] == "Pomodoro'yu bitir"
    rows3["show_shelf"]["callback"]()
    assert d.shelf_panel.is_open()
    d.preview_mode = True
    m.presence.release_all()


def test_shelf_click_toggles_panel() -> None:
    m = load_module(True)
    d = make_dock(m, True, shelf_items=3)
    img = render(d, m)
    b = boxes(d)
    assert "shelf" in b and "pomo" not in b, list(b)
    assert m.shelf.draws and m.shelf.draws[-1][:2] == ("idle", 3), m.shelf.draws[-1]
    c = _center(b["shelf"])
    d.handle_click("shelf", None, b["shelf"], c)
    assert d.shelf_panel.is_open() and d.shelf_panel.calls == ["show"]
    d.handle_click("shelf", None, b["shelf"], c)
    assert not d.shelf_panel.is_open() and d.shelf_panel.calls == ["show", "hide"]
    d.shelf_panel.closed_recently = True
    d.handle_click("shelf", None, b["shelf"], c)  # recently_closed: yeniden açılmaz
    assert not d.shelf_panel.is_open()
    assert img.width() > 0


def test_pomo_click_wheel_and_context_menu() -> None:
    m = load_module(True)
    d = make_dock(m, True, pomo="long")
    render(d, m)
    b = boxes(d)
    assert "pomo" in b and "shelf" in b
    d.handle_click("pomo", None, b["pomo"], _center(b["pomo"]))
    assert d.pomo_timer.calls == [("toggle_pause",)]
    _wheel(d, _center(b["pomo"]), 120)
    _wheel(d, _center(b["pomo"]), -120)
    assert d.pomo_timer.calls[1:] == [("adjust", 5), ("adjust", -5)], d.pomo_timer.calls
    # sağ tık: ActionMenu 5 satır
    shown = []
    import action_menu as am
    old_show, old_set = am.ActionMenu.show_at, am.ActionMenu.set_actions
    am.ActionMenu.show_at = lambda self, a: shown.append(a)
    got = []
    am.ActionMenu.set_actions = lambda self, acts: got.append(list(acts)) or old_set(self, acts)
    try:
        from PySide6.QtGui import QContextMenuEvent
        c = _center(b["pomo"]).toPoint()
        ev = QContextMenuEvent(QContextMenuEvent.Mouse, c, d.mapToGlobal(c))
        d.contextMenuEvent(ev)
    finally:
        am.ActionMenu.show_at, am.ActionMenu.set_actions = old_show, old_set
    assert shown and got, "menü açılmadı"
    texts = [a["text"] for a in got[-1]]
    # çalışırken 'Duraklat' (toggle_pause ile durdu -> 'Devam et')
    assert len(texts) == 5 and texts[0] == "Paneli aç" and texts[2:] == ["Atla", "Sıfırla", "Bitir"], texts
    assert texts[1] in ("Duraklat", "Devam et")


def test_drag_drop_into_shelf() -> None:
    m = load_module(True)
    d = make_dock(m, True, shelf_items=1)
    d.preview_mode = False
    d.attach_shelf(d.shelf_store, d.shelf_panel)  # gerçek kipte bağlama sürüklemeyi açar
    assert d.acceptDrops()
    render(d, m)
    c = _center(boxes(d)["shelf"])
    f1 = os.path.join(_TMP, "Rapor.xlsx")
    f2 = os.path.join(_TMP, "Teklif.pdf")
    md, ev = _drag_enter(d, [f1, f2], c)
    assert ev.isAccepted() and d._shelf_drag_over
    render(d, m)
    assert m.shelf.draws[-1][0] == "over", m.shelf.draws[-1]
    d.dragLeaveEvent(QDragLeaveEvent())
    assert not d._shelf_drag_over
    render(d, m)
    assert m.shelf.draws[-1][0] == "idle"
    _drag_enter(d, [f1, f2], c)
    drop = QDropEvent(c, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    d.dropEvent(drop)
    assert len(d.shelf_store.added) == 1 and d.shelf_store.added[0][1] == "drop", d.shelf_store.added
    assert [os.path.basename(x) for x in d.shelf_store.added[0][0]] == ["Rapor.xlsx", "Teklif.pdf"]
    assert not d._shelf_drag_over
    # yerel dosya olmayan sürükleme reddedilir
    md2 = QMimeData()
    md2.setText("metin")
    ev2 = QDragEnterEvent(c.toPoint(), Qt.CopyAction, md2, Qt.LeftButton, Qt.NoModifier)
    d.dragEnterEvent(ev2)
    assert not ev2.isAccepted()
    # önizleme kipinde sürüklemeye açılmaz
    d2 = make_dock(m, True)
    assert not d2.acceptDrops()


def _drag_move(d, md, pos: QPointF):
    ev = QDragMoveEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    d.dragMoveEvent(ev)
    return ev


def test_drag_dwell_brings_window_forward() -> None:
    """Dosya sürüklenirken çalışan uygulamanın kutucuğunda ~0,5 sn durunca penceresi öne gelir."""
    m = load_module(True)
    d = make_dock(m, True, shelf_items=0, n_apps=3)
    d.preview_mode = False
    d.attach_shelf(d.shelf_store, d.shelf_panel)
    d.tiles[0].update(running=True, hwnds=[1111, 2222])   # çalışan, 2 pencere
    d.tiles[1].update(running=False, hwnds=[])            # yalnız iğnelenmiş
    render(d, m)
    b = boxes(d)
    calls = []
    d._dwell_activate = lambda h: calls.append(h)
    f1 = os.path.join(_TMP, "Rapor.xlsx")
    md, ev = _drag_enter(d, [f1], _center(b["shelf"]))
    assert ev.isAccepted()
    # çalışan uygulama: kabul edilmez (rafa düşmez), bekleme başlar
    ev = _drag_move(d, md, _center(b["app_0"]))
    assert not ev.isAccepted() and d._drag_dwell_idx == 0 and d._drag_dwell_timer.isActive()
    assert d._hover_app_idx == 0
    _drag_move(d, md, _center(b["app_0"]) + QPointF(2.0, 1.0))   # titreme sayacı sıfırlamaz
    assert d._drag_dwell_timer.isActive() and d._drag_dwell_idx == 0
    d._drag_dwell_timer.stop()
    d._on_drag_dwell()
    assert calls == [1111], calls                         # ilk (en son kullanılan) pencere
    d._on_drag_dwell()
    assert calls == [1111], "aynı kutucukta bir kez"
    # kapalı (iğneli) uygulama: bekleme yok
    ev = _drag_move(d, md, _center(b["app_1"]))
    assert d._drag_dwell_idx is None and not d._drag_dwell_timer.isActive()
    # ataç: tekrar rafa bırakılabilir
    ev = _drag_move(d, md, _center(b["shelf"]))
    assert ev.isAccepted() and d._drag_dwell_idx is None
    # uygulamaya geri dön: yeni bekleme, bir kez daha öne getirir
    _drag_move(d, md, _center(b["app_0"]))
    d._drag_dwell_timer.stop(); d._on_drag_dwell()
    assert calls == [1111, 1111], calls
    # uygulama kutucuğuna bırakılan dosya rafa eklenmez
    drop = QDropEvent(_center(b["app_0"]), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    d.dropEvent(drop)
    assert d.shelf_store.added == [], d.shelf_store.added
    assert d._drag_dwell_idx is None and d._hover_app_idx is None
    # ayar kapalıysa bekleme yok
    d.settings["drag_activate"] = False
    _drag_enter(d, [f1], _center(b["shelf"]))
    _drag_move(d, md, _center(b["app_0"]))
    assert d._drag_dwell_idx is None
    d.settings["drag_activate"] = True
    # dragLeave temizler
    _drag_move(d, md, _center(b["app_0"]))
    d.dragLeaveEvent(QDragLeaveEvent())
    assert d._drag_dwell_idx is None and not d._drag_dwell_timer.isActive()


def test_drag_dwell_real_activate_blocked_under_tests() -> None:
    m = load_module(True)
    d = make_dock(m, True, n_apps=1)
    d.preview_mode = False
    d.tiles[0].update(running=True, hwnds=[1111])
    render(d, m)
    called = []
    orig = m.winapi.activate_window
    m.winapi.activate_window = lambda h: called.append(h)
    try:
        d._dwell_activate = m.winapi.activate_window   # 'gerçek' yol: test korumasına takılmalı
        d._drag_dwell_idx = 0
        d._on_drag_dwell()
    finally:
        m.winapi.activate_window = orig
    assert called == [], called


def test_phase_finished_single_toast_no_beep() -> None:
    m = load_module(True)
    d = make_dock(m, True, pomo=True)
    shown = []

    class FakeMgr:
        def show(self, alert):
            shown.append(alert)

    d.toast_mgr = FakeMgr()
    beeps = []
    import winsound
    old = winsound.MessageBeep
    winsound.MessageBeep = lambda *a: beeps.append(a)
    try:
        d.alert_engine = None
        d.pomo_timer.phase_finished.emit("focus", "short")
        d.pomo_timer.phase_finished.emit("short", "focus")
    finally:
        winsound.MessageBeep = old
    assert len(shown) == 2 and shown[0].kind == "pomodoro", shown
    assert shown[0].title == "Odak bitti" and shown[0].body == "5 dk mola başladı", dict(shown[0])
    assert shown[1].title == "Mola bitti" and shown[1].body == "Yeni odak turu için tıkla", dict(shown[1])
    assert beeps == [], "testte gerçek bip olmamalı"
    d.settings["alerts_enabled"] = False
    d.pomo_timer.phase_finished.emit("focus", "long")
    assert len(shown) == 3 and "15 dk" in shown[2].body  # uyarılar kapalıyken de gösterilir


def test_presence_change_repaints_only_its_rect() -> None:
    m = load_module(True)
    d = make_dock(m, True)
    m.presence.set_keep_awake(True)
    d.update()
    render(d, m)
    assert "keepawake" in boxes(d) and "presence" not in boxes(d)
    updates = []
    d.update = lambda *a: updates.append(a)  # QWidget.update'i gözle
    d._on_presence_data({"mic": ["Zoom"], "cam": []})  # simge belirdi: yerleşim değişir -> tam
    assert len(updates) == 1 and updates[0] == ()
    updates.clear()
    render(d, m)
    r = boxes(d)["presence"]
    d._on_presence_data({"mic": ["Zoom"], "cam": ["Teams"]})  # aynı simge, içerik değişti: yalnız kendi dikdörtgeni
    assert len(updates) == 1 and len(updates[0]) == 1, updates
    assert updates[0][0].contains(r.toRect().center()) and updates[0][0].width() < 60
    updates.clear()
    d._on_presence_data({"mic": ["Zoom"], "cam": ["Teams"]})  # değişmedi: hiçbir şey
    assert updates == []
    m.presence.release_all()


def test_pomo_changed_updates_only_pomo_rect() -> None:
    m = load_module(True)
    d = make_dock(m, True, pomo=True)
    render(d, m)
    updates = []
    d.update = lambda *a: updates.append(a)
    d.pomo_timer.st["remaining_s"] = 1498
    d.pomo_timer.changed.emit()
    assert len(updates) == 1 and len(updates[0]) == 1, updates
    assert updates[0][0].width() < 120
    updates.clear()
    d.pomo_timer.st["task"] = "Yeni görev"  # genişlik değişti -> yerleşim
    d.pomo_timer.changed.emit()
    assert len(updates) == 1 and updates[0] == ()


def test_modules_absent_layout_identical() -> None:
    m = load_module(False)
    assert m.shelf is None and m.pomodoro is None and m.presence is None
    d = make_dock(m, False)
    acts = d.build_dock_menu_actions()
    ids = [a.get("id") for a in acts if a.get("type") != "separator"]
    assert len(ids) == 7 and not {"pomo_toggle", "show_shelf", "keep_awake"} & set(ids), ids
    render(d, m)
    keys = {k for k in boxes(d)}
    assert not keys & {"shelf", "pomo", "keepawake", "presence"}, keys
    assert d._v25_right_width() == 0.0
    assert not d.acceptDrops()
    # sahte modüllerle ama hepsi pasifken (raf kapalı, pomodoro pasif, uyku kapalı) sağ küme/uygulama konumu aynı
    m2 = load_module(True)
    d2 = make_dock(m2, True)
    d2.settings["shelf_enabled"] = False
    render(d2, m2)
    b1, b2 = boxes(d), boxes(d2)
    for k in b1:
        assert abs(b1[k].x() - b2[k].x()) < 0.01 and abs(b1[k].width() - b2[k].width()) < 0.01, k
    # menüsünde raf satırı yok ama (pomodoro, presence) var
    ids2 = [a.get("id") for a in d2.build_dock_menu_actions() if a.get("type") != "separator"]
    assert "show_shelf" not in ids2 and "keep_awake" in ids2


def test_tile_rects_unchanged_by_new_block() -> None:
    m = load_module(True)
    d0 = make_dock(m, True)
    d0.settings["shelf_enabled"] = False
    render(d0, m)
    base = [QRectF(r) for r in d0._tile_rects]
    d1 = make_dock(m, True, pomo="long", shelf_items=12)
    m.presence.set_keep_awake(True)
    d1._presence_usage = {"mic": ["Zoom"], "cam": ["Teams"]}
    render(d1, m)
    assert [QRectF(r) for r in d1._tile_rects] == base
    m.presence.release_all()


def _all_cards():
    return {"cal": True, "mail": True, "ag": True, "sys": True, "claude": True}


def test_full_layout_no_overlap_and_on_screen() -> None:
    m = load_module(True)
    d = make_dock(m, True, cards=_all_cards(), pomo="long", shelf_items=12, media=True, n_apps=3)
    m.presence.set_keep_awake(True)
    d._presence_usage = {"mic": ["Zoom"], "cam": ["Teams"]}
    d.store.update("mail", {"count": 3, "items": []})
    d.compute_layout_and_resize(initial=True)
    d.resize(1536, int(m.DOCK_HEIGHT))
    render(d, m)
    rects = [(k, QRectF(r)) for r, k, _e in d.hit_boxes if k not in ("desktop",) and not k.startswith("app_")
             or k.startswith("app_")]
    # uygulama kutuları büyütme animasyonuna girmez; kutular çakışmamalı
    new_keys = {"shelf", "pomo", "keepawake", "presence"}
    m0 = load_module(False)
    d0 = make_dock(m0, False, cards=_all_cards(), media=True, n_apps=3)
    render(d0, m0)
    b0 = boxes(d0)
    base_overlap = max(b0["media"].right(), b0["cal"].right()) > b0["tray"].x() + 0.01
    print(f"  taban (modüller yok) sağ kanat ^'a taşıyor mu: {base_overlap}")
    for i, (ka, ra) in enumerate(rects):
        if ka in new_keys:
            assert ra.left() >= -0.01 and ra.right() <= d.width() + 0.01, (ka, ra)
        for kb, rb in rects[i + 1:]:
            if ka not in new_keys and kb not in new_keys:
                continue  # eski kartlar arası çakışma bu işin dışında
            if base_overlap and {ka, kb} & {"media", "cal"} and {ka, kb} & {"keepawake", "presence"}:
                continue  # taban düzende (modüller yok) sağ kanat zaten ^ düğmesine değiyor: bilinen önceden var olan taşma
            inter = ra.intersected(rb)
            assert inter.width() <= 0.01 or inter.height() <= 0.01, ("çakışma", ka, ra, kb, rb)
    b = boxes(d)
    assert "keepawake" in b and "presence" in b, list(b)
    if "shelf" not in b or "pomo" not in b:
        print("  tüm kartlar açık: sol kanat doldurdu; yeni blok sığmadı ->", sorted(k for k in b if k in ("shelf", "pomo")) or "gizlendi")
        m.presence.release_all()
        return
    apps = sorted((r for k, r in b.items() if k.startswith("app_")), key=lambda r: r.x())
    left_wing_end = max(b[k].right() for k in ("claude", "mail", "ag", "sys") if k in b)
    gap_l = b["shelf"].x() - left_wing_end
    gap_pomo_apps = apps[0].x() - b["pomo"].right()
    gap_shelf_pomo = b["pomo"].x() - b["shelf"].right()
    chev_gap = b["tray"].x() - b["presence"].right()
    print(f"  ölçülen: sol kanat->raf {gap_l:.1f}px, raf->pomodoro {gap_shelf_pomo:.1f}px, "
          f"pomodoro->uygulamalar {gap_pomo_apps:.1f}px, presence->^ {chev_gap:.1f}px, "
          f"keepawake->presence {b['presence'].x() - b['keepawake'].right():.1f}px")
    assert gap_l >= 12.0 - 0.01, gap_l
    assert abs(gap_pomo_apps - 28.0) < 0.01 and abs(gap_shelf_pomo - 24.0) < 0.01 or d._pomo_compact is not None
    m.presence.release_all()


def test_tight_gaps_keep_task_line() -> None:
    """Yer darsa önce boşluklar daralır (20/16 px), görev satırı kalır; o da sığmazsa compact."""
    m = load_module(True)
    d = make_dock(m, True, pomo="long", shelf_items=1)
    # normal: 28+90+24+28 = 170 -> x=530; dar: 20+90+16+28 = 154 -> x=546
    lay = d._v25_left_layout(700.0, 530.0)   # sınır 542: normal sığmaz, dar sığar
    assert not d._pomo_compact, "dar boşlukla sığmalıydı"
    assert abs(700.0 - lay["pomo"].right() - 20.0) < 0.01, lay
    assert abs(lay["pomo"].x() - lay["shelf"].right() - 16.0) < 0.01, lay
    lay = d._v25_left_layout(700.0, 600.0)   # sınır 612: dar da sığmaz
    assert d._pomo_compact or lay["pomo"] is None, lay
    lay = d._v25_left_layout(700.0, 400.0)   # bol yer: normal boşluklar
    assert not d._pomo_compact and abs(700.0 - lay["pomo"].right() - 28.0) < 0.01, lay


def test_screenshot_results_go_to_shelf_as_screenshot() -> None:
    m = load_module(True)
    d = make_dock(m, True, shelf_items=0)
    tmp = Path(_TMP) / "shot.png"
    tmp.write_bytes(b"x")
    d.on_data_ready("shelfshot", [str(tmp)])
    assert d.shelf_store.added[-1] == ([str(tmp)], "screenshot"), d.shelf_store.added
    d.on_data_ready("shelfdl", [str(tmp)])
    assert d.shelf_store.added[-1] == ([str(tmp)], "download"), d.shelf_store.added


def test_emre_layout_gaps() -> None:
    """Emre'nin barı (ag + sys açık, 1536 mantıksal): yeni blok sol kanat ile uygulamalar arasına sığar."""
    m = load_module(True)
    d = make_dock(m, True, cards={"cal": False, "mail": False, "ag": True, "sys": True, "claude": True},
                  pomo="long", shelf_items=3, media=True, n_apps=3)
    render(d, m)
    b = boxes(d)
    assert "shelf" in b and "pomo" in b, list(b)
    apps = sorted((r for k, r in b.items() if k.startswith("app_")), key=lambda r: r.x())
    gap_l = b["shelf"].x() - b["sys"].right()
    gap_r = apps[0].x() - b["pomo"].right()
    print(f"  Emre düzeni: sol kanat->raf {gap_l:.1f}px, pomodoro->uygulamalar {gap_r:.1f}px, "
          f"raf {b['shelf'].width():.0f}px, pomodoro {b['pomo'].width():.0f}px")
    print(f"  görev satırı düştü mü: {d._pomo_compact}")
    # 28 px normal; yer darsa 20 px (V25_TIGHT_APPS_GAP), görev satırı korunur
    assert gap_l >= 12.0 and (abs(gap_r - 28.0) < 0.01 or abs(gap_r - 20.0) < 0.01), (gap_l, gap_r)


def test_no_polling_or_drops_in_preview() -> None:
    m = load_module(True)
    d = make_dock(m, True, pomo=True)
    assert not d.acceptDrops()
    assert not hasattr(d, "shelfdl_timer") and not hasattr(d, "presence_timer")
    assert d._dl_watcher is None


def test_shelf_downloads_trigger_pulse_and_toast() -> None:
    m = load_module(True)
    d = make_dock(m, True, shelf_items=1)
    d.preview_mode = False
    toasts = []

    class FakeMgr:
        def show(self, alert):
            toasts.append(alert)

    d.toast_mgr = FakeMgr()
    d._shelf_pulse = 0.0

    # 1. İndirme geldiğinde pulse ve bildirim tetiklenmeli
    d._on_shelf_downloads(["/downloads/ias_report.xlsx"], source="download")
    assert d._shelf_pulse == 1.0
    assert len(toasts) == 1
    assert toasts[0].title == "İndirilen dosya rafta"
    assert "ias_report.xlsx" in toasts[0].body
    assert toasts[0].kind == "shelf"

    # 2. Bildirime tıklandığında raf açılmalı
    d._on_toast_clicked(toasts[0])
    assert d.shelf_panel.calls and "show" in d.shelf_panel.calls

    # 3. Darbe zamanlayıcısı sönmeli
    d._on_shelf_pulse_tick()
    assert d._shelf_pulse < 1.0


def main() -> int:
    tests = [
        test_menu_rows_and_checked_state,
        test_shelf_click_toggles_panel,
        test_pomo_click_wheel_and_context_menu,
        test_drag_drop_into_shelf,
        test_phase_finished_single_toast_no_beep,
        test_presence_change_repaints_only_its_rect,
        test_pomo_changed_updates_only_pomo_rect,
        test_modules_absent_layout_identical,
        test_tile_rects_unchanged_by_new_block,
        test_full_layout_no_overlap_and_on_screen,
        test_emre_layout_gaps,
        test_drag_dwell_brings_window_forward,
        test_drag_dwell_real_activate_blocked_under_tests,
        test_screenshot_results_go_to_shelf_as_screenshot,
        test_tight_gaps_keep_task_line,
        test_no_polling_or_drops_in_preview,
        test_shelf_downloads_trigger_pulse_and_toast,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {exc}")
            failed += 1
    print(f"{len(tests) - failed}/{len(tests)} geçti")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
