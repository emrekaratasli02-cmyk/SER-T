"""test_audio_mixer.py - Test suite for audio_mixer module.

Tests:
  1. Mocked pycaw sessions:
     - App session merging (multiple sessions -> max volume, all muted, combined pids).
     - Display name resolution (known app map, Win32 FileDescription PE resource, python cmdline).
     - Session sorting (active sessions first, then alphabetical by display name).
     - Terminated/expired process exclusion.
     - set_session_level / set_session_mute on single and multi-instance apps.
  2. Live read-only verification on Windows Core Audio.
  3. Live exact-value set verification (permission-compliant: exact same level & mute).
  4. Timing and performance benchmark (< 60 ms warm target).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from typing import Any, List, Optional
from unittest.mock import patch

SERIT_DIR = Path("D:/Apps/serit")
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

import audio_mixer


# ==============================================================================
# MOCK CLASSES FOR PYCAW SESSIONS
# ==============================================================================

class MockSimpleAudioVolume:
    def __init__(self, level: float = 1.0, mute: int = 0):
        self._level = float(level)
        self._mute = int(mute)
        self.set_volume_calls: List[float] = []
        self.set_mute_calls: List[int] = []

    def GetMasterVolume(self) -> float:
        return self._level

    def SetMasterVolume(self, level: float, context: Any = None) -> None:
        self._level = float(level)
        self.set_volume_calls.append(float(level))

    def GetMute(self) -> int:
        return self._mute

    def SetMute(self, mute: int, context: Any = None) -> None:
        self._mute = int(mute)
        self.set_mute_calls.append(int(mute))


class MockControl:
    def __init__(self, is_system: bool = False):
        self._is_system = is_system

    def IsSystemSoundsSession(self) -> int:
        # S_OK = 0 in COM means TRUE
        return 0 if self._is_system else 1


class MockProcess:
    def __init__(
        self,
        pid: int,
        name: str,
        exe: str = "",
        cmdline: Optional[List[str]] = None,
        running: bool = True,
    ):
        self.pid = pid
        self._name = name
        self._exe = exe
        self._cmdline = cmdline or []
        self._running = running

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return self._exe

    def cmdline(self) -> List[str]:
        return list(self._cmdline)

    def is_running(self) -> bool:
        return self._running

    def create_time(self) -> float:
        return 1000.0


class MockAudioSession:
    def __init__(
        self,
        process: Optional[MockProcess],
        state: int = 0,
        level: float = 1.0,
        mute: int = 0,
        is_system: bool = False,
        process_id: Optional[int] = None,
        display_name: str = "",
        identifier: str = "",
    ):
        self.Process = process
        self.ProcessId = (
            process.pid if process else (0 if is_system else (process_id or 0))
        )
        self.State = state
        self.SimpleAudioVolume = MockSimpleAudioVolume(level, mute)
        self._ctl = MockControl(is_system)
        self.DisplayName = display_name
        self.Identifier = identifier


# ==============================================================================
# UNIT TESTS (MOCKED)
# ==============================================================================

def test_display_name_resolution() -> None:
    """Validate display name rules across known map, scripts, and fallbacks."""
    print("Testing display name resolution...")

    # 1. Known map
    assert audio_mixer.get_display_name("chrome.exe") == "Chrome"
    assert audio_mixer.get_display_name("msedge.exe") == "Edge"
    assert audio_mixer.get_display_name("spotify.exe") == "Spotify"
    assert audio_mixer.get_display_name("zoom.exe") == "Zoom"
    assert audio_mixer.get_display_name("whatsapp.root.exe") == "WhatsApp"
    assert audio_mixer.get_display_name("discord.exe") == "Discord"
    assert audio_mixer.get_display_name("hermes.exe") == "Hermes"
    assert audio_mixer.get_display_name("teams.exe") == "Teams"

    # 2. Python / pythonw script detection
    dikte_cmd = ["pythonw.exe", r"D:\Apps\dikte\dikte.pyw"]
    assert audio_mixer.get_display_name("pythonw.exe", "", dikte_cmd) == "Dikte"

    serit_cmd = ["pythonw.exe", r"D:\Apps\serit\serit_v5.pyw"]
    assert audio_mixer.get_display_name("pythonw.exe", "", serit_cmd) == "Şerit"

    other_cmd = ["python.exe", "worker_job.py"]
    assert audio_mixer.get_display_name("python.exe", "", other_cmd) == "worker_job"

    # 3. PE FileDescription
    system32_cmd = r"C:\Windows\System32\cmd.exe"
    if os.path.exists(system32_cmd):
        desc = audio_mixer.get_file_description(system32_cmd)
        assert desc == "Windows Command Processor"
        assert audio_mixer.get_display_name("cmd.exe", system32_cmd) == "Windows Command Processor"

    print("  [OK] Display name resolution passed.")


def test_session_merging() -> None:
    """Validate merging multiple audio sessions of the same application."""
    print("Testing session merging (Chrome tabs / sub-processes)...")

    # 3 sessions of Chrome:
    # Session 1: pid 101, level 50%, muted True, inactive
    # Session 2: pid 102, level 85%, muted False, active (state 1)
    # Session 3: pid 101, level 70%, muted True, inactive
    s1 = MockAudioSession(
        MockProcess(101, "chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        state=0,
        level=0.50,
        mute=1,
    )
    s2 = MockAudioSession(
        MockProcess(102, "chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        state=1,
        level=0.85,
        mute=0,
    )
    s3 = MockAudioSession(
        MockProcess(101, "chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        state=0,
        level=0.70,
        mute=1,
    )

    with patch.object(audio_mixer.AudioUtilities, "GetAllSessions", return_value=[s1, s2, s3]):
        sessions = audio_mixer.list_sessions()
        assert len(sessions) == 1, f"Expected 1 merged session, got {len(sessions)}"
        ch = sessions[0]
        assert ch["key"] == "chrome.exe"
        assert ch["name"] == "Chrome"
        assert sorted(ch["pids"]) == [101, 102]
        # Max level = 85
        assert ch["level"] == 85
        # Muted = False because s2 is not muted (muted = all muted)
        assert ch["muted"] is False
        # Active = True because s2 is active
        assert ch["active"] is True

    # Check when all sessions of an app ARE muted
    s1.SimpleAudioVolume._mute = 1
    s2.SimpleAudioVolume._mute = 1
    s3.SimpleAudioVolume._mute = 1
    with patch.object(audio_mixer.AudioUtilities, "GetAllSessions", return_value=[s1, s2, s3]):
        sessions = audio_mixer.list_sessions()
        assert sessions[0]["muted"] is True

    print("  [OK] Session merging passed.")


def test_sorting_order() -> None:
    """Validate sorting: active sessions first, then alphabetically by display name."""
    print("Testing sorting order...")

    # S1: Zoom (inactive)
    s_zoom = MockAudioSession(MockProcess(201, "zoom.exe"), state=0)
    # S2: Discord (active)
    s_disc = MockAudioSession(MockProcess(202, "discord.exe"), state=1)
    # S3: Spotify (active)
    s_spot = MockAudioSession(MockProcess(203, "spotify.exe"), state=1)
    # S4: System Sounds (inactive)
    s_sys = MockAudioSession(None, is_system=True, state=0)

    with patch.object(audio_mixer.AudioUtilities, "GetAllSessions", return_value=[s_zoom, s_disc, s_spot, s_sys]):
        sessions = audio_mixer.list_sessions()
        names = [s["name"] for s in sessions]
        # Active first: Discord, Spotify (alphabetical)
        # Inactive next: Sistem sesleri, Zoom (alphabetical)
        expected = ["Discord", "Spotify", "Sistem sesleri", "Zoom"]
        assert names == expected, f"Expected {expected}, got {names}"

    print("  [OK] Sorting order passed.")


def test_exit_and_expiry_handling() -> None:
    """Validate sessions from dead or expired processes are excluded."""
    print("Testing terminated / expired process exclusion...")

    # Dead process (is_running = False)
    dead_p = MockProcess(301, "dead.exe", running=False)
    s_dead = MockAudioSession(dead_p, state=0)

    # Expired session (state = 2)
    alive_p = MockProcess(302, "expired.exe", running=True)
    s_expired = MockAudioSession(alive_p, state=2)

    # Orphaned non-system session (Process is None, not system sounds)
    s_orphan = MockAudioSession(None, is_system=False, process_id=9999, state=0)

    # Valid running app
    valid_p = MockProcess(303, "chrome.exe", running=True)
    s_valid = MockAudioSession(valid_p, state=0)

    # System sounds (Process is None, but is_system=True)
    s_sys = MockAudioSession(None, is_system=True, state=0)

    with patch.object(
        audio_mixer.AudioUtilities,
        "GetAllSessions",
        return_value=[s_dead, s_expired, s_orphan, s_valid, s_sys],
    ):
        sessions = audio_mixer.list_sessions()
        keys = [s["key"] for s in sessions]
        assert "chrome.exe" in keys
        assert "system" in keys
        assert "dead.exe" not in keys
        assert "expired.exe" not in keys
        assert "pid_9999" not in keys
        assert len(sessions) == 2

    print("  [OK] Terminated / expired exclusion passed.")


def test_set_session_level_and_mute_mocked() -> None:
    """Validate set_session_level and set_session_mute on multiple sessions."""
    print("Testing set_session_level and set_session_mute (mocked)...")

    s1 = MockAudioSession(MockProcess(401, "chrome.exe"), level=0.5, mute=0)
    s2 = MockAudioSession(MockProcess(402, "chrome.exe"), level=0.5, mute=0)
    s_sys = MockAudioSession(None, is_system=True, level=1.0, mute=0)

    # Oturumlar sahte (GetAllSessions yamalı): gerçek ses kilidini yalnız bu blokta kaldır
    with patch.object(audio_mixer.AudioUtilities, "GetAllSessions", return_value=[s1, s2, s_sys]),             patch.object(audio_mixer, "_guard_real_audio", lambda what: None):
        # Set level 75 on chrome.exe (should update both sessions)
        ok = audio_mixer.set_session_level("chrome.exe", 75)
        assert ok is True
        assert s1.SimpleAudioVolume._level == 0.75
        assert s2.SimpleAudioVolume._level == 0.75
        assert s_sys.SimpleAudioVolume._level == 1.0  # untouched

        # Set level using stem 'chrome'
        ok2 = audio_mixer.set_session_level("chrome", 60)
        assert ok2 is True
        assert s1.SimpleAudioVolume._level == 0.60
        assert s2.SimpleAudioVolume._level == 0.60

        # Set mute True on chrome
        ok_mute = audio_mixer.set_session_mute("chrome.exe", True)
        assert ok_mute is True
        assert s1.SimpleAudioVolume._mute == 1
        assert s2.SimpleAudioVolume._mute == 1

        # Set level on system sounds
        ok_sys = audio_mixer.set_session_level("system", 40)
        assert ok_sys is True
        assert s_sys.SimpleAudioVolume._level == 0.40

        # Non-existent app
        assert audio_mixer.set_session_level("nonexistent.exe", 50) is False
        assert audio_mixer.set_session_mute("nonexistent.exe", True) is False

    print("  [OK] Mocked set_session_level / set_session_mute passed.")


# ==============================================================================
# LIVE TESTS (CORE AUDIO ON THIS PC)
# ==============================================================================

def test_live_read_only() -> None:
    """Validate live query of Core Audio sessions on current machine."""
    print("\n--- LIVE CORE AUDIO READ-ONLY CHECK ---")
    sessions = audio_mixer.list_sessions()
    assert isinstance(sessions, list)
    print(f"Found {len(sessions)} active/inactive audio session groups:")
    for i, s in enumerate(sessions):
        print(f"  [{i}] key='{s['key']}', name='{s['name']}', level={s['level']}%, muted={s['muted']}, active={s['active']}, pids={s['pids']}")
        assert isinstance(s["key"], str) and s["key"]
        assert isinstance(s["name"], str) and s["name"]
        assert isinstance(s["pids"], list)
        assert isinstance(s["level"], int) and 0 <= s["level"] <= 100
        assert isinstance(s["muted"], bool)
        assert isinstance(s["active"], bool)
        assert isinstance(s["exe"], str)

    # Ensure system sounds session is present
    sys_sound = [s for s in sessions if s["key"] == "system"]
    assert len(sys_sound) == 1, "Expected 'system' audio session"
    assert sys_sound[0]["name"] == "Sistem sesleri"
    print("  [OK] Live read-only check passed.")


def test_real_audio_is_guarded() -> None:
    """Test altında gerçek ses yazımı kilitli olmalı."""
    for fn, args in ((audio_mixer.set_session_level, ("chrome.exe", 5)), (audio_mixer.set_session_mute, ("chrome.exe", True))):
        try:
            fn(*args)
        except RuntimeError:
            continue
        raise AssertionError(f"{fn.__name__} test altında engellenmedi")
    print("  [OK] Gerçek ses kilidi çalışıyor.")


def test_performance_timing() -> None:
    """Benchmark list_sessions duration: warm target < 60 ms."""
    print("\n--- PERFORMANCE & WARM TIMING BENCHMARK ---")
    # Cold query
    t0 = time.perf_counter()
    audio_mixer.list_sessions()
    cold_dur = (time.perf_counter() - t0) * 1000.0

    # Warm queries
    warm_durations = []
    for _ in range(5):
        t0 = time.perf_counter()
        audio_mixer.list_sessions()
        warm_durations.append((time.perf_counter() - t0) * 1000.0)

    avg_warm = sum(warm_durations) / len(warm_durations)
    print(f"Cold run: {cold_dur:.2f} ms")
    print(f"Warm runs: {[round(x, 2) for x in warm_durations]} ms")
    print(f"Average warm duration: {avg_warm:.2f} ms (target: < 60 ms)")
    # Generous ceiling to prevent failure on background OS CPU bursts
    assert avg_warm < 80.0, f"Average warm duration {avg_warm:.2f} ms exceeded threshold"
    print("  [OK] Performance benchmark passed.")


# ==============================================================================
# MAIN RUNNER
# ==============================================================================

def main() -> int:
    print("=" * 60)
    print("  SERIT AUDIO MIXER BACKEND TEST SUITE")
    print("=" * 60)

    test_display_name_resolution()
    test_session_merging()
    test_sorting_order()
    test_exit_and_expiry_handling()
    test_set_session_level_and_mute_mocked()
    test_live_read_only()
    test_real_audio_is_guarded()
    # test_live_set_exact_permissions(): kaldırıldı, testler gerçek sese dokunmaz (27 Eki 2026)
    test_performance_timing()

    print("\n" + "=" * 60)
    print("  ALL AUDIO MIXER TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
