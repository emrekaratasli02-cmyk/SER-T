import datetime as dt
from pathlib import Path
import sys

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

import today_panel
import sources

def test_today_panel_basic():
    p = today_panel.TodayPanel()
    assert p.WIDTH == 360
    assert p.is_open() is False

    anchor = QRectF(500, 800, 100, 36)
    wx = {
        "temp": 19.3,
        "feel": 16.1,
        "desc": "Parçalı Bulutlu",
        "icon": "cloud_sun",
        "max": 19.5,
        "min": 10.1,
        "wind": 16.1,
        "humidity": 43.0,
        "rain": 3.0,
        "hourly": [
            {"time": "16:00", "temp": 18, "icon": "sun"},
            {"time": "17:00", "temp": 17, "icon": "sun"},
        ]
    }
    _tz = getattr(sources, "LOCAL_TZ", dt.timezone(dt.timedelta(hours=3)))
    _now = dt.datetime.now(_tz)
    # Gece yarısına 20 dk kala +20 dk sonraki gün olurdu; o durumda 5 dk öncesini kullan
    # (hem aynı gün kalır hem "yakında/Katıl" penceresinde kalır).
    _start = _now + dt.timedelta(minutes=20)
    if _start.date() != _now.date():
        _start = _now - dt.timedelta(minutes=5)
    events = [
        {
            "title": "Haftalık IAS Operasyon Senkronu",
            "start": _start,
            "meeting": "https://meet.google.com/abc-defg-hij",
            "category": "Google Takvim",
        }
    ]
    p.show_for(anchor, wx, {"events": events}, {}, city="Aksaray")
    assert p.is_open() is True
    assert len(p._cached_hourly) == 3  # Şimdi + 2 saat
    assert len(p._cached_events) == 1
    assert p._cached_events[0]["show_join"] is True

    # Test month expand toggle
    assert p.month_expanded is False
    h_compact = p.height()
    p.month_expanded = True
    h_expanded = p.compute_height()
    assert h_expanded > h_compact

    p.hide_instant()
    assert p.is_open() is False
    p.close()
    print("test_today_panel_basic PASSED")


def test_today_panel_wiring_in_serit() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("serit_v5_v31", str(REPO_DIR / "serit_v5.pyw"))
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    # Gerçek settings.json'a asla yazmasın: ayar dosyasını geçici kopyaya yönlendir
    import tempfile
    from pathlib import Path as _P
    _tmp = _P(tempfile.mkdtemp(prefix="serit-v31-")) / "settings.json"
    m.SETTINGS_FILE = _tmp
    dock = m.SeritDock({"style": "band"}, preview_mode=False)
    assert hasattr(dock, "today_panel")
    assert dock.today_panel is not None
    assert dock.today_panel.WIDTH == 360

    # Test that click on 'wx' or 'clock' routes to today_panel
    anchor = QRectF(100, 10, 80, 40)
    dock.store.update("wx", {"temp": 19.0, "desc": "Güneşli", "icon": "sun"})
    dock.handle_click("wx", None, anchor, QPointF(110, 20))
    assert dock.today_panel.is_open() is True
    dock.today_panel.hide_instant()
    dock.today_panel._last_close_time = 0.0

    dock.handle_click("clock", None, anchor, QPointF(110, 20))
    assert dock.today_panel.is_open() is True
    dock.today_panel.hide_instant()

    dock.close()
    print("test_today_panel_wiring_in_serit PASSED")


if __name__ == "__main__":
    test_today_panel_basic()
    test_today_panel_wiring_in_serit()
