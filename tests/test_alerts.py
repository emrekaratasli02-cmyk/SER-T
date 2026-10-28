"""Unit tests and visual snapshot verification for alerts module."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

# Ensure serit directory is in sys.path
serit_dir = str(Path(__file__).resolve().parent.parent)
if serit_dir not in sys.path:
    sys.path.insert(0, serit_dir)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from alerts import Alert, AlertEngine, Toast, ToastManager

SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5")


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ==============================================================================
# 1. RULE UNIT TESTS
# ==============================================================================


def test_claude_session_thresholds_and_dedup() -> None:
    """Claude session >= 80% (amber) and >= 95% (red), deduped per session_reset period."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        # 1. Under 80%: no alert
        s1 = {
            "claude": {
                "session": 78.5,
                "session_reset": "2026-10-26T19:00:00Z",
                "week": 20.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res1 = engine.evaluate(s1, now=1000.0)
        assert len(res1) == 0

        # 2. Reaches 82% (>=80%): amber alert
        s2 = {
            "claude": {
                "session": 82.0,
                "session_reset": "2026-10-26T19:00:00Z",
                "week": 20.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res2 = engine.evaluate(s2, now=1005.0)
        assert len(res2) == 1
        a = res2[0]
        assert a.kind == "claude"
        assert a.title == "Claude oturumu %82"
        assert a.accent == "#FFC45C"
        assert "Sıfırlanmaya" in a.body

        # 3. Same period, slight increase to 84%: deduped, no alert
        s3 = {
            "claude": {
                "session": 84.0,
                "session_reset": "2026-10-26T19:00:00Z",
                "week": 20.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res3 = engine.evaluate(s3, now=1130.0)
        assert len(res3) == 0

        # 4. Same period, jumps to 96% (>=95%): red alert
        s4 = {
            "claude": {
                "session": 96.0,
                "session_reset": "2026-10-26T19:00:00Z",
                "week": 20.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        # Space time to respect quiet period
        res4 = engine.evaluate(s4, now=1200.0)
        assert len(res4) == 1
        a95 = res4[0]
        assert a95.title == "Claude oturumu %96"
        assert a95.accent == "#FF6E6E"

        # 5. Subsequent call in same period: deduped
        res5 = engine.evaluate(s4, now=1350.0)
        assert len(res5) == 0

        # 6. New session_reset period: can fire again
        s6 = {
            "claude": {
                "session": 83.0,
                "session_reset": "2026-10-27T00:00:00Z",
                "week": 20.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res6 = engine.evaluate(s6, now=1500.0)
        assert len(res6) == 1
        assert res6[0].title == "Claude oturumu %83"

    finally:
        if state_file.exists():
            state_file.unlink()


def test_claude_weekly_threshold() -> None:
    """Claude weekly >= 80% (period = week_reset)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        s = {
            "claude": {
                "session": 30.0,
                "session_reset": "2026-10-26T19:00:00Z",
                "week": 84.2,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res = engine.evaluate(s, now=1000.0)
        assert len(res) == 1
        assert res[0].title == "Claude haftalık %84"
        assert res[0].accent == "#FFC45C"
        assert "Sıfırlanmaya" in res[0].body

        # Re-evaluating is deduped
        res2 = engine.evaluate(s, now=1200.0)
        assert len(res2) == 0
    finally:
        if state_file.exists():
            state_file.unlink()


def test_fx_thresholds_and_body() -> None:
    """USD / EUR >=1% and Gold >=2% (|change|), period = date + direction, body has value and time."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        # 1. USD up by 1.35% (>= 1.0%)
        s_usd = {
            "fx": {
                "usd": 34.50,
                "usd_chg": 1.35,
                "eur": 37.20,
                "eur_chg": 0.40,
                "gold": 3020.0,
                "gold_chg": 0.50,
                "updated": "16:45",
            }
        }
        res = engine.evaluate(s_usd, now=1000.0)
        assert len(res) == 1
        a = res[0]
        assert a.kind == "fx"
        assert "Dolar" in a.title
        assert "artış" in a.title
        assert a.accent == "#78DC96"  # Up -> green
        assert "34,50" in a.body
        assert "16:45" in a.body

        # 2. Same USD up on same day: deduped
        res_dedup = engine.evaluate(s_usd, now=1150.0)
        assert len(res_dedup) == 0

        # 3. USD drops by 1.20% on same day: direction is 'down', so fires!
        s_usd_down = {
            "fx": {
                "usd": 33.90,
                "usd_chg": -1.20,
                "eur": 37.20,
                "eur_chg": 0.40,
                "gold": 3020.0,
                "gold_chg": 0.50,
                "updated": "17:15",
            }
        }
        res_down = engine.evaluate(s_usd_down, now=1200.0)
        assert len(res_down) == 1
        assert "düşüş" in res_down[0].title
        assert res_down[0].accent == "#FF6E6E"  # Down -> red
        assert "33,90" in res_down[0].body

        # 4. Gold check: 1.8% change -> does not fire (< 2.0%)
        s_gold_sub = {
            "fx": {
                "usd": 33.90,
                "usd_chg": 0.1,
                "eur": 37.20,
                "eur_chg": 0.1,
                "gold": 3080.0,
                "gold_chg": 1.8,
                "updated": "17:30",
            }
        }
        res_gold_sub = engine.evaluate(s_gold_sub, now=1400.0)
        assert len(res_gold_sub) == 0

        # 5. Gold check: 2.2% change -> fires!
        s_gold = {
            "fx": {
                "usd": 33.90,
                "usd_chg": 0.1,
                "eur": 37.20,
                "eur_chg": 0.1,
                "gold": 3100.0,
                "gold_chg": 2.2,
                "updated": "17:35",
            }
        }
        res_gold = engine.evaluate(s_gold, now=1450.0)
        assert len(res_gold) == 1
        assert "Gram Altın" in res_gold[0].title
        assert "3.100,00" in res_gold[0].body
        assert "17:35" in res_gold[0].body

    finally:
        if state_file.exists():
            state_file.unlink()


def test_stale_ignored() -> None:
    """Stale store entries and error entries must be ignored completely."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        # Stale claude with 99% usage
        s1 = {
            "claude": {
                "session": 99.0,
                "session_reset": "2026-10-26T19:00:00Z",
                "stale": True,
            }
        }
        assert len(engine.evaluate(s1, now=1000.0)) == 0

        # Errored fx with 10% change
        s2 = {
            "fx": {
                "usd": 35.0,
                "usd_chg": 10.0,
                "err": "Bağlantı yok",
            }
        }
        assert len(engine.evaluate(s2, now=1200.0)) == 0

        # Stale sys with 99% RAM
        s3 = {
            "sys": {
                "ram": 99.0,
                "stale": True,
            }
        }
        assert len(engine.evaluate(s3, now=1400.0)) == 0
    finally:
        if state_file.exists():
            state_file.unlink()


def test_ram_3_sample_rule_with_fake_times() -> None:
    """RAM >= 92% for 3 consecutive evaluations spaced >= 55s apart (period = hour)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        # Baseline timestamp (e.g. 17:00:00 on 2026-10-26)
        base_t = 1793026800.0

        # Sample 1 at t=0 (RAM 93%) -> Streak length 1, no alert
        s1 = {"sys": {"ram": 93.0, "ram_used_gb": 14.8, "ram_total_gb": 16.0}}
        res1 = engine.evaluate(s1, now=base_t)
        assert len(res1) == 0

        # Sample at t=20s (<55s spaced) -> ignored for streak count, no alert
        res2 = engine.evaluate(s1, now=base_t + 20.0)
        assert len(res2) == 0

        # Sample 2 at t=60s (>=55s spaced) -> Streak length 2, no alert
        res3 = engine.evaluate(s1, now=base_t + 60.0)
        assert len(res3) == 0

        # Interruption: RAM drops to 85% -> streak reset!
        s_low = {"sys": {"ram": 85.0, "ram_used_gb": 13.6, "ram_total_gb": 16.0}}
        res4 = engine.evaluate(s_low, now=base_t + 90.0)
        assert len(res4) == 0

        # Restart streak:
        # Sample 1 at t=120s
        res5 = engine.evaluate(s1, now=base_t + 120.0)
        assert len(res5) == 0

        # Sample 2 at t=180s (60s >= 55s)
        res6 = engine.evaluate(s1, now=base_t + 180.0)
        assert len(res6) == 0

        # Sample 3 at t=240s (60s >= 55s) -> 3 consecutive! Alert fires!
        res7 = engine.evaluate(s1, now=base_t + 240.0)
        assert len(res7) == 1
        a = res7[0]
        assert a.kind == "sys"
        assert a.title == "Bellek kullanımı %93"
        assert a.accent == "#FF6E6E"
        assert "son 3 kontrolde" in a.body

        # Subsequent evaluation in same hour: deduped!
        res8 = engine.evaluate(s1, now=base_t + 300.0)
        assert len(res8) == 0

        # Advance to next hour: can fire again if high
        res9 = engine.evaluate(s1, now=base_t + 3700.0)
        assert len(res9) == 1
        assert res9[0].kind == "sys"

    finally:
        if state_file.exists():
            state_file.unlink()


def test_dedup_and_queue_across_new_engine_instance() -> None:
    """State persistence across distinct AlertEngine instances using scratch temp file."""
    scratch_state = SCRATCH_DIR / "test_state_persistence.json"
    if scratch_state.exists():
        scratch_state.unlink()

    try:
        engine1 = AlertEngine(state_path=scratch_state)

        # Trigger Claude 85% alert
        s = {
            "claude": {
                "session": 85.0,
                "session_reset": "2026-10-26T20:00:00Z",
                "week": 10.0,
                "week_reset": "2026-10-31T06:00:00Z",
            }
        }
        res1 = engine1.evaluate(s, now=1000.0)
        assert len(res1) == 1
        assert res1[0].id == "claude_session_80_2026-10-26T20:00:00Z"

        # Instantiate a brand new AlertEngine pointing to the same state file
        engine2 = AlertEngine(state_path=scratch_state)

        # Verify engine2 remembers the fired alert and does not re-emit
        res2 = engine2.evaluate(s, now=1200.0)
        assert len(res2) == 0

    finally:
        if scratch_state.exists():
            scratch_state.unlink()


def test_quiet_rule_queueing() -> None:
    """Global quiet rule: at most one toast per 120s; remaining are queued and delivered."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file)

        # Both Claude and USD qualify at the exact same evaluation time t=1000
        multi_store = {
            "claude": {
                "session": 85.0,
                "session_reset": "2026-10-26T20:00:00Z",
            },
            "fx": {
                "usd": 34.50,
                "usd_chg": 1.50,
                "updated": "16:00",
            },
        }

        # 1. At t=1000, exactly ONE alert is delivered, the other is queued
        out1 = engine.evaluate(multi_store, now=1000.0)
        assert len(out1) == 1
        assert engine.queue_length == 1

        # 2. At t=1050 (50s < 120s cooldown), no alert is delivered; queue remains 1
        out2 = engine.evaluate(multi_store, now=1050.0)
        assert len(out2) == 0
        assert engine.queue_length == 1

        # 3. At t=1125 (125s >= 120s cooldown), the queued alert is delivered!
        out3 = engine.evaluate(multi_store, now=1125.0)
        assert len(out3) == 1
        assert engine.queue_length == 0
        assert out3[0].kind != out1[0].kind

    finally:
        if state_file.exists():
            state_file.unlink()


def test_enabled_flag() -> None:
    """When enabled is False, evaluate must return [] immediately."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    state_file = Path(tmp.name)
    try:
        engine = AlertEngine(state_path=state_file, enabled=False)
        s = {
            "claude": {
                "session": 96.0,
                "session_reset": "2026-10-26T20:00:00Z",
            }
        }
        assert len(engine.evaluate(s, now=1000.0)) == 0

        engine.enabled = True
        assert len(engine.evaluate(s, now=1000.0)) == 1
    finally:
        if state_file.exists():
            state_file.unlink()


# ==============================================================================
# 2. TOAST WIDGET & MANAGER TESTS (Zero Display Window Leaks)
# ==============================================================================


def test_toast_widget_properties() -> None:
    """Verify Toast widget attributes, fonts, and interaction helpers."""
    get_qapp()

    alert = Alert(
        id="test_alert_1",
        title="Test Bildirimi",
        body="Bu bir test mesajıdır. Detaylar burada yer alır.",
        accent="#FFC45C",
        kind="claude",
    )

    toast = Toast(alert)
    assert toast.width() == Toast.WIDTH == 352  # v21: panel genişliği
    assert toast.height() >= 70
    assert toast.alert.title == "Test Bildirimi"
    assert toast.alert.accent == "#FFC45C"
    toast.deleteLater()


def test_toast_hover_pause_and_click() -> None:
    """Hovering pauses auto-dismiss timer; clicking triggers on_click."""
    get_qapp()

    clicked_alerts = []

    def handle_click(a: Alert) -> None:
        clicked_alerts.append(a)

    alert = Alert(
        id="test_click",
        title="Tıklama Testi",
        body="Tıklandığında çalışmalı.",
        accent="#78DC96",
        kind="fx",
    )

    toast = Toast(alert, on_click=handle_click)
    # Simulate enter event (hover)
    toast.enterEvent(None)
    assert toast._is_hovered is True

    # Simulate leave event
    toast.leaveEvent(None)
    assert toast._is_hovered is False

    # Simulate body click
    class DummyEvent:
        def button(self):
            return Qt.LeftButton

        def position(self):
            return QPointF(50.0, 30.0)

    toast.mousePressEvent(DummyEvent())
    assert len(clicked_alerts) == 1
    assert clicked_alerts[0].id == "test_click"
    toast.deleteLater()


def test_toast_manager_stacking_and_eviction() -> None:
    """ToastManager limits active toasts to 3, evicting the oldest."""
    get_qapp()
    mgr = ToastManager()

    for i in range(4):
        a = Alert(
            id=f"alert_{i}",
            title=f"Başlık {i}",
            body=f"Gövde metni {i}",
            accent="#FFC45C",
            kind="claude",
        )
        mgr.show(a)

    # Active toasts must be capped at 3
    assert len(mgr.active_toasts) == 3
    # Most recently added is alert_3, oldest remaining is alert_1
    assert mgr.active_toasts[-1].alert.id == "alert_3"

    mgr.dismiss_all()
    assert len(mgr.active_toasts) == 0


# ==============================================================================
# 3. OFFSCREEN HIGH-DPI VISUAL SNAPSHOT RENDERING (DPR 2.0)
# ==============================================================================


def render_offscreen_snapshots() -> list[str]:
    """Render 3 distinct toasts (Claude Amber, FX Green, RAM Red) at DPR 2.0."""
    get_qapp()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    samples = [
        (
            "toast_claude.png",
            Alert(
                id="claude_demo",
                title="Claude oturumu %82",
                body="Sıfırlanmaya 1 sa 12 dk (19:09).",
                accent="#FFC45C",
                kind="claude",
            ),
        ),
        (
            "toast_fx.png",
            Alert(
                id="fx_demo",
                title="Dolar %1,45 artış",
                body="1 USD = 34,50 TL · Güncelleme: 16:30",
                accent="#78DC96",
                kind="fx",
            ),
        ),
        (
            "toast_ram.png",
            Alert(
                id="ram_demo",
                title="Bellek kullanımı %94",
                body="RAM son 3 kontrolde %92 üzerinde (15,0\u00A0/\u00A016,0\u00A0GB).",
                accent="#FF6E6E",
                kind="sys",
            ),
        ),
    ]

    saved_paths: list[str] = []
    for filename, alert in samples:
        toast = Toast(alert)
        img: QImage = toast.render_to_image(dpr=2.0)
        out_path = SCRATCH_DIR / filename
        ok = img.save(str(out_path))
        assert ok is True, f"Failed to save {out_path}"
        saved_paths.append(str(out_path))
        print(f"Exported DPR 2.0 render: {out_path} ({img.width()}x{img.height()} px)")
        toast.deleteLater()

    return saved_paths


# ==============================================================================
# MAIN TEST RUNNER
# ==============================================================================

if __name__ == "__main__":
    print("==================================================")
    print("  RUNNING ŞERİT ALERTS & TOASTS UNIT TEST SUITE   ")
    print("==================================================")

    print("\n[1/8] Testing Claude session thresholds & dedup...")
    test_claude_session_thresholds_and_dedup()
    print("      PASSED.")

    print("\n[2/8] Testing Claude weekly threshold...")
    test_claude_weekly_threshold()
    print("      PASSED.")

    print("\n[3/8] Testing FX daily thresholds & body...")
    test_fx_thresholds_and_body()
    print("      PASSED.")

    print("\n[4/8] Testing stale & error entries ignored...")
    test_stale_ignored()
    print("      PASSED.")

    print("\n[5/8] Testing RAM 3-sample rule with fake times...")
    test_ram_3_sample_rule_with_fake_times()
    print("      PASSED.")

    print("\n[6/8] Testing dedup across new AlertEngine instance...")
    test_dedup_and_queue_across_new_engine_instance()
    print("      PASSED.")

    print("\n[7/8] Testing quiet-rule queueing & cooldown...")
    test_quiet_rule_queueing()
    print("      PASSED.")

    print("\n[8/8] Testing engine enabled flag...")
    test_enabled_flag()
    print("      PASSED.")

    print("\n[UI/1] Testing Toast widget properties...")
    test_toast_widget_properties()
    print("       PASSED.")

    print("\n[UI/2] Testing Toast hover pause & click handler...")
    test_toast_hover_pause_and_click()
    print("       PASSED.")

    print("\n[UI/3] Testing ToastManager stacking & max 3 eviction...")
    test_toast_manager_stacking_and_eviction()
    print("       PASSED.")

    print("\n--- GENERATING OFFSCREEN VISUAL SNAPSHOTS (DPR 2.0) ---")
    paths = render_offscreen_snapshots()
    print(f"\nSuccessfully created {len(paths)} visual snapshots.")
    print("ALL TESTS PASSED SUCCESSFULLY.")
