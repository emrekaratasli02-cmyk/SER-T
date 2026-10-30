"""Idle repaint harness: simulated time, counts update() regions + driver frames."""
from __future__ import annotations
import os, tempfile, random
os.environ.setdefault("SERIT_TEST", "1")
os.environ.setdefault("SERIT_LOG", os.path.join(tempfile.gettempdir(), "serit-agent.log"))
import importlib.util, sys
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

def load_mod():
    spec = importlib.util.spec_from_file_location("serit_v5_idle", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_idle_")) / "settings.json"
    m.save_settings = lambda cfg: None
    return m

def run(playing: bool, seconds: int = 60, cpu_base=8.0, ram_base=76.0, jitter=3, seed=1, big_step_at=None):
    mod = load_mod()
    QApplication.instance() or QApplication([])
    dock = mod.SeritDock({"style": "band", "cards": {"ag": True, "sys": True, "cal": False, "mail": False, "fx": False}}, preview_mode=True)
    dock.resize(1536, int(mod.DOCK_HEIGHT))
    dock.compute_layout_and_resize(initial=True)
    from PySide6.QtCore import QTimer
    dock.media_ring_timer = QTimer(); dock.media_ring_timer.setInterval(500); dock.media_ring_timer.start()
    drv = dock.anim_driver
    drv.stop_all()
    drv._simulated_time_ms = 1000.0
    rnd = random.Random(seed)
    sysd = {"cpu": cpu_base, "ram": ram_base, "source": "t"}
    dock.on_data_ready("sys", sysd); dock.sync_anim_values()
    media = {"vol": {"level": 40.0, "muted": False, "device": "x"},
             "np": ({"title": "T", "artist": "A", "app": "p", "playing": True, "duration_s": 200.0, "position_s": 10.0} if playing else None)}
    dock.on_data_ready("media", media)
    dock._now_playing_info = media["np"]
    stats = {"paints": 0, "frames": 0, "px": 0}
    pending = []
    full = QRect(0, 0, dock.width(), dock.height())
    def stub_update(*a):
        if not a: pending.append(full)
        elif isinstance(a[0], QRect): pending.append(a[0])
        elif hasattr(a[0], "boundingRect"): pending.append(a[0].boundingRect())
        else: pending.append(full)
    dock.update = stub_update
    drv.frame.connect(lambda: stats.__setitem__("frames", stats["frames"] + 1))
    def flush():
        if pending:
            from PySide6.QtGui import QRegion
            r = QRegion()
            for q in pending: r = r.united(q.intersected(full))
            stats["paints"] += 1
            stats["px"] += sum(x.width() * x.height() for x in r)
            pending.clear()
    step = 16
    for ms in range(0, seconds * 1000, step):
        if ms % 2000 == 0 and ms:
            if big_step_at is not None and ms == big_step_at:
                sysd = {"cpu": 70.0, "ram": ram_base, "source": "t"}
            else:
                sysd = {"cpu": max(0, cpu_base + rnd.uniform(-jitter, jitter)), "ram": ram_base + rnd.uniform(-jitter, jitter), "source": "t"}
            dock.on_data_ready("sys", dict(sysd))
        if ms % 10000 == 0 and ms:
            dock._on_clock_tick() if hasattr(dock, "_on_clock_tick") else None
        if ms % 3000 == 0 and ms:
            dock.on_data_ready("media", dict(media))
        if ms % 500 == 0 and ms:
            dock._now_playing_info = media["np"]
            if dock.media_ring_timer.isActive():
                dock._on_media_ring_tick()
        if ms % 1000 == 0 and ms:
            dock._check_fullscreen()
        if drv.is_running():
            drv.step_manual(step)
        else:
            drv._simulated_time_ms += step
        flush()
    mp = stats["px"] / 1e6
    return {"paints": stats["paints"], "frames": stats["frames"], "megapix": round(mp, 3), "seconds": seconds,
            "full_mp": full.width() * full.height() / 1e6}

BASELINE_PAINTS = 660  # main 4c60ece: her 16 ms karede bir boyama (60 sn)


def test_idle_paints_reduced() -> None:
    for playing in (False, True):
        r = run(playing)
        assert r["paints"] <= BASELINE_PAINTS * 0.3, r
        assert r["frames"] <= BASELINE_PAINTS * 0.3, r
        assert r["megapix"] <= BASELINE_PAINTS * r["full_mp"] * 0.3, r


def test_large_cpu_change_still_animates() -> None:
    r = run(False, seconds=10, big_step_at=4000)
    assert r["frames"] >= 15, r  # ~350 ms sweep => >= ~20 frames


def main() -> None:
    test_idle_paints_reduced()
    test_large_cpu_change_still_animates()
    print("test_v25_idle_paint OK", run(False), run(True))


if __name__ == "__main__":
    main()
