"""winapi pencere->exe önbelleği: aynı pencere için psutil bir kez sorulur, kapanan pencere düşer."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import winapi  # noqa: E402


def test_exe_cache_hits_and_prunes() -> None:
    winapi._EXE_CACHE.clear()
    calls: list[int] = []

    def fake_process(pid: int):
        calls.append(pid)
        proc = mock.Mock()
        if pid == 666:
            proc.exe.side_effect = PermissionError("AccessDenied")  # yetkili süreç
        else:
            proc.exe.return_value = f"C:\\app{pid}.exe"
        return proc

    with mock.patch.object(winapi.psutil, "Process", side_effect=fake_process):
        # İlk tur: her pencere bir kez sorulur
        assert winapi._exe_for(10, 1001) == "C:\\app10.exe"
        assert winapi._exe_for(666, 1002) == ""
        assert calls == [10, 666]

        # Sonraki turlar: hiç sorulmaz (erişim reddi de önbelleğe girer)
        for _ in range(5):
            assert winapi._exe_for(10, 1001) == "C:\\app10.exe"
            assert winapi._exe_for(666, 1002) == ""
        assert calls == [10, 666]

        # 1002 kapandı: budamadan sonra önbellekte yalnız 1001 kalır
        winapi._prune_exe_cache({(10, 1001)})
        assert set(winapi._EXE_CACHE) == {(10, 1001)}

        # Aynı PID başka bir pencereyle (veya PID yeniden kullanılınca yeni hwnd) yeniden sorulur
        assert winapi._exe_for(10, 2001) == "C:\\app10.exe"
        assert calls == [10, 666, 10]
    winapi._EXE_CACHE.clear()


if __name__ == "__main__":
    test_exe_cache_hits_and_prunes()
    print("[PASS] test_winapi_exe_cache")
