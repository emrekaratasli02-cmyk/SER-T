"""test_v26_wiring.py - v26 bağlantıları: ağ hızı (A1), güncelleme rozeti (B2), Ctrl kaynak balonu (C1).

Gerçek winget, gerçek Ctrl tuşu ve gerçek süreç örneklemesi ASLA çağrılmaz; sahteler enjekte edilir.
Yükleyici/yardımcılar test_v25_wiring.py'den gelir (shelf/pomodoro/presence sahte, v26 modülleri gerçek).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_v25_wiring as tw  # noqa: E402  (QApplication + SERIT_TEST ortamını kurar)
from PySide6.QtCore import QPointF  # noqa: E402

import netspeed  # noqa: E402


def _dock(cards=None, n_apps=3):
    m = tw.load_module(True)
    assert m.netspeed is not None and m.updates is not None and m.appusage is not None
    d = tw.make_dock(m, True, cards=cards, n_apps=n_apps)
    return m, d


def _net(down, up, visible=True):
    return {"down": down, "up": up, "t": 1.0, "visible": visible, "below_count": 0}


def _upd(count, err=None):
    items = [{"name": f"Örnek {i}", "id": f"Ornek.{i}", "version": "1.0", "available": "1.1", "source": "winget"}
             for i in range(count or 0)]
    return {"count": count, "items": items, "checked_at": 1_700_000_000.0, "err": err}


def test_net_item_appears_only_when_visible() -> None:
    m, d = _dock()
    assert "net" not in dict(d._v25_right_items())
    d._on_net_data(_net(None, None, visible=False))
    assert "net" not in dict(d._v25_right_items())
    d._on_net_data(_net(80_000.0, 12_000.0))
    items = dict(d._v25_right_items())
    assert abs(items["net"] - netspeed.band_width(d._net_state)) < 0.01, items
    tw.render(d, m)
    assert "net" in tw.boxes(d)
    # yalnız sayılar değişince: tam yeniden çizim yok, yalnız ağ dikdörtgeni
    calls = []
    d._v25_update_key = lambda k: calls.append(k)
    sig = d._net_sig
    d._on_net_data(_net(12_400_000.0, 1_100_000.0))
    assert d._net_sig == sig and calls == ["net"], (d._net_sig, calls)
    # genişlik değerle değişmez
    assert abs(dict(d._v25_right_items())["net"] - items["net"]) < 0.01
    d._on_net_data(_net(1_000.0, 0.0, visible=False))
    assert "net" not in dict(d._v25_right_items())


def test_net_setting_off_hides_item() -> None:
    m, d = _dock()
    d._on_net_data(_net(80_000.0, 12_000.0))
    d.settings["net_speed_enabled"] = False
    assert "net" not in dict(d._v25_right_items())


def test_updates_badge_width_click_and_error() -> None:
    m, d = _dock()
    assert "updates" not in dict(d._v25_right_items())
    d._on_updates_data(_upd(3))
    assert abs(dict(d._v25_right_items())["updates"] - 38.0) < 0.01
    tw.render(d, m)
    b = tw.boxes(d)
    assert "updates" in b

    class FakePanel:
        def __init__(self):
            self.open, self.shown = False, []

        def is_open(self):
            return self.open

        def recently_closed(self):
            return False

        def show_for(self, anchor, *a, **k):
            self.open = True
            self.shown.append(anchor)

        def hide_animated(self):
            self.open = False

    fp = FakePanel()
    d._updates_panel = fp
    d.handle_click("updates", None, b["updates"])
    assert fp.open and len(fp.shown) == 1
    d.handle_click("updates", None, b["updates"])
    assert not fp.open
    d._on_updates_data(_upd(None, err="winget yok"))
    assert "updates" not in dict(d._v25_right_items())
    d._on_updates_data(_upd(0))
    assert "updates" not in dict(d._v25_right_items())


def test_updates_due_check_submits_pool_job_only() -> None:
    m, d = _dock()
    sub = []
    d.submit_fetch = lambda k: sub.append(k)

    class FakeChecker:
        def __init__(self, due):
            self._due = due

        def due(self):
            return self._due

    d._update_checker = FakeChecker(True)
    d._check_updates_if_due()
    assert sub == ["updates_check"], sub
    d._update_checker = FakeChecker(False)
    d._check_updates_if_due()
    assert sub == ["updates_check"], sub
    d.settings["updates_enabled"] = False
    d._update_checker = FakeChecker(True)
    d._check_updates_if_due()
    assert sub == ["updates_check"], sub


class _FakeBubble:
    def __init__(self):
        self.calls = []

    def show_bubble(self, anchor, text, sub_text=None):
        self.calls.append((text, sub_text))

    def hide(self):
        self.calls.append(("hide", None))


def test_ctrl_bubble_two_lines_and_timers() -> None:
    m, d = _dock()
    tw.render(d, m)
    d.preview_mode = False
    d.bubble = _FakeBubble()
    sub = []
    d.submit_fetch = lambda k: sub.append(k)
    d.tiles[0].update(running=True, hwnds=[1111], name="Örnek 0")
    d.tiles[1].update(running=False, hwnds=[])
    d._app_usage_data = {"0.exe": {"cpu": 12.0, "mem_mb": 640.0, "procs": 1}}
    ctrl = {"down": False}
    d._ctrl_down_fn = lambda: ctrl["down"]
    d._hover_app_idx = 0
    d._on_tile_hover(0)
    assert d._ctrl_poll_timer.isActive() and not d._app_usage_timer.isActive()
    d._on_ctrl_poll()                     # Ctrl basılı değil: hiçbir şey olmaz
    assert d.bubble.calls == [] and sub == []
    ctrl["down"] = True
    d._on_ctrl_poll()
    assert d._app_usage_timer.isActive() and sub == ["appusage"], sub
    assert d.bubble.calls[-1] == ("Örnek 0", "CPU %12 · Bellek 640 MB"), d.bubble.calls
    n = len(d.bubble.calls)
    d._on_ctrl_poll()                     # basılı kalırken 100 ms'de bir balon yeniden açılmaz
    assert len(d.bubble.calls) == n
    d._on_app_usage_data({"0.exe": {"cpu": 38.0, "mem_mb": 2150.0, "procs": 3}})
    assert d.bubble.calls[-1] == ("Örnek 0", "CPU %38 · Bellek 2,1 GB"), d.bubble.calls[-1]
    ctrl["down"] = False
    d._on_ctrl_poll()
    assert not d._app_usage_timer.isActive()
    assert d.bubble.calls[-1] == ("Örnek 0", None), d.bubble.calls[-1]
    # fare ayrılınca iki zamanlayıcı da durur
    ctrl["down"] = True
    d._on_ctrl_poll()
    d._hover_app_idx = None
    d._on_tile_hover(None)
    assert not d._ctrl_poll_timer.isActive() and not d._app_usage_timer.isActive()
    # kapalı (iğneli) uygulamada yoklama başlamaz
    d._hover_app_idx = 1
    d._on_tile_hover(1)
    assert not d._ctrl_poll_timer.isActive()
    # ayar kapalıysa başlamaz
    d.settings["app_usage_ctrl"] = False
    d._hover_app_idx = 0
    d._on_tile_hover(0)
    assert not d._ctrl_poll_timer.isActive()


def test_menu_rows_toggle_settings() -> None:
    m, d = _dock()
    acts = [a for a in d.build_dock_menu_actions() if a.get("type") != "separator"]
    ids = [a.get("id") for a in acts]
    assert ids[:5] == ["settings", "refresh", "pomo_toggle", "show_shelf", "keep_awake"], ids
    assert ids[5:7] == ["toggle_net_speed", "toggle_updates"], ids
    row = {a["id"]: a for a in acts}
    assert row["toggle_net_speed"]["checked"] is True and row["toggle_updates"]["checked"] is True
    row["toggle_net_speed"]["callback"]()
    row["toggle_updates"]["callback"]()
    assert d.settings["net_speed_enabled"] is False and d.settings["updates_enabled"] is False
    row2 = {a["id"]: a for a in d.build_dock_menu_actions() if a.get("id")}
    assert row2["toggle_net_speed"]["checked"] is False and row2["toggle_updates"]["checked"] is False


def test_all_right_items_fit_with_all_cards() -> None:
    m, d = _dock(cards=tw._all_cards() if hasattr(tw, "_all_cards") else
                 {"cal": True, "mail": True, "ag": True, "sys": True, "claude": True}, n_apps=5)
    d._on_net_data(_net(12_400_000.0, 1_100_000.0))
    d._on_updates_data(_upd(14))
    m.presence._ka = True
    d._presence_usage = {"mic": ["Örnek"], "cam": []}
    d.compute_layout_and_resize()
    tw.render(d, m)
    b = tw.boxes(d)
    new = [k for k in ("net", "updates", "keepawake", "presence") if k in b]
    assert {"net", "updates"} <= set(new), list(b)
    order = sorted(new, key=lambda k: b[k].x())
    assert order == [k for k in ("net", "updates", "keepawake", "presence") if k in new], order
    for k in new:
        r = b[k]
        assert r.right() <= d.width() + 0.01 and r.x() >= 0.0, (k, r)
        for k2, r2 in b.items():
            if k2 == k:
                continue
            inter = r.intersected(r2)
            assert inter.width() <= 0.5 or inter.height() <= 0.5, (k, k2, r, r2)


def test_bubble_one_line_unchanged() -> None:
    m, d = _dock()
    bw = m.BubbleWidget()
    bw.show_bubble(QPointF(-5000.0, -5000.0), "Örnek")
    one = (bw.width(), bw.height(), bw._sub_text)
    bw.hide()
    bw.show_bubble(QPointF(-5000.0, -5000.0), "Örnek", sub_text="CPU %12 · Bellek 640 MB")
    two = (bw.width(), bw.height())
    bw.hide()
    assert one[2] is None and two[1] > one[1], (one, two)


def main() -> int:
    tests = [
        test_net_item_appears_only_when_visible,
        test_net_setting_off_hides_item,
        test_updates_badge_width_click_and_error,
        test_updates_due_check_submits_pool_job_only,
        test_ctrl_bubble_two_lines_and_timers,
        test_menu_rows_toggle_settings,
        test_all_right_items_fit_with_all_cards,
        test_bubble_one_line_unchanged,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("SERIT_TEST", "1")
    raise SystemExit(main())
