"""test_appbar_contract.py - Unit test verifying Windows AppBar registration contract."""

from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import importlib.util
spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
# Gerçek settings.json'a ASLA yazma: SeritDock(preview_mode=False) varsayılan pinleri kaydediyordu.
import tempfile
_TMP = Path(tempfile.mkdtemp(prefix='serit_appbar_'))
serit_mod.SETTINGS_FILE = _TMP / 'settings.json'
serit_mod.save_settings = lambda cfg: None

def test_appbar_logic():
    QApplication.instance() or QApplication([])
    # 1. In preview mode, _register_appbar must return False and not invoke shell32
    dock_preview = serit_mod.SeritDock({"reserve_space": True}, preview_mode=True)
    with patch("ctypes.windll.shell32.SHAppBarMessage") as mock_sh:
        assert dock_preview._register_appbar() is False
        mock_sh.assert_not_called()

    # 2. In normal mode with reserve_space=False, must return False
    dock_no_reserve = serit_mod.SeritDock({"reserve_space": False}, preview_mode=False)
    with patch("ctypes.windll.shell32.SHAppBarMessage") as mock_sh:
        assert dock_no_reserve._register_appbar() is False
        mock_sh.assert_not_called()

    # 3. In normal mode with reserve_space=True, must call ABM_NEW (0), ABM_QUERYPOS (2), ABM_SETPOS (3)
    dock = serit_mod.SeritDock({"reserve_space": True}, preview_mode=False)
    # mock winId
    # Gerçek bir pencere tutamacı gerekir (MonitorFromWindow); masaüstü penceresi. SHAppBarMessage yine sahte.
    import ctypes
    dock.winId = MagicMock(return_value=ctypes.windll.user32.GetDesktopWindow())
    with patch("ctypes.windll.shell32.SHAppBarMessage", return_value=1) as mock_sh:
        res = dock._register_appbar()
        assert res is True
        assert dock._appbar_registered is True
        # Verify calls for ABM_NEW (0), ABM_QUERYPOS (2), ABM_SETPOS (3)
        called_msgs = [call[0][0] for call in mock_sh.call_args_list]
        assert 0 in called_msgs, "ABM_NEW (0) must be called"
        assert 2 in called_msgs, "ABM_QUERYPOS (2) must be called"
        assert 3 in called_msgs, "ABM_SETPOS (3) must be called"

        # 4. _unregister_appbar must call ABM_REMOVE (1)
        dock._unregister_appbar()
        assert dock._appbar_registered is False
        assert mock_sh.call_args_list[-1][0][0] == 1, "ABM_REMOVE (1) must be called"

    print("ALL APPBAR CONTRACT TESTS PASSED.")

if __name__ == "__main__":
    test_appbar_logic()
