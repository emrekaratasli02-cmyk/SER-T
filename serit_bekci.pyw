"""Crash watchdog for the Şerit dock application.

Monitors the Şerit dock process (serit_v5.pyw). If the dock process dies
unexpectedly, restores the Windows taskbar (respecting 'taskbar_original')
and releases the dock's AppBar space reservation via SHAppBarMessage ABM_REMOVE.
Then it restarts the dock, with a budget of at most 3 restarts within a sliding
10-minute window. If the dock crashes a 4th time within 10 minutes, the watchdog
stops restarting, restores the Windows taskbar to visible (autohide off), and exits.

Dikte Process Isolation:
Dikte (D:/Apps/dikte/dikte.pyw and bekci.pyw) may also run with a pythonw.exe
interpreter. The watchdog identifies the dock exclusively by checking command-line
arguments ending with 'serit_v5.pyw' and never by executable path.

Clean Exit Detection (marker + pid + age):
The real dock (only when running as D:/Apps/serit/serit_v5.pyw, never from tests, previews
or worktree copies) writes APP_DIR/.clean_exit in DockBar.cleanup() via
logpath.write_clean_exit_marker(): JSON {"pid", "ppid", "t"}. The watchdog accepts a marker
ONLY if it parses, its pid or ppid is the process being watched (child_proc.pid, the external
monitored pid, or a child process recorded while it ran: the venv pythonw is a launcher whose
child runs the code) and its time is not older than that process' start (2 s slack).
Anything else (empty/foreign/old marker) is stale: it is deleted, logged as
'stale marker ignored' and the exit is treated as a crash. The exit code is irrelevant.
No valid marker = crash -> restart (3 per 10 min budget), unless another live dock already
exists (e.g. the single-instance lock made ours exit); then the watchdog attaches to it.
The marker is deleted at watchdog startup and right before every dock launch.
The old 'hide_taskbar' heuristic for external docks was dropped: a user close ('Kapat')
always writes a matching marker, so the marker rule covers it fully.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable, List, Optional, Tuple

import psutil

try:
    from logpath import LOG_PATH
except ImportError:
    LOG_PATH = Path("D:/Apps/serit/serit.log")

import winapi

APP_DIR = Path("D:/Apps/serit")
DOCK_SCRIPT = APP_DIR / "serit_v5.pyw"
SETTINGS_FILE = APP_DIR / "settings.json"
MARKER_FILE = APP_DIR / ".clean_exit"
PYTHONW_PATH = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"  # Şerit kendi ortamı (Dikte'den ayrı)

MUTEX_NAME = "Local\\SeritBekci"
ABM_REMOVE = 1


def _log(msg: str) -> None:
    """Append a timestamped message to LOG_PATH with prefix [bekci]."""
    try:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} [bekci] {msg}\n")
    except OSError:
        pass


def is_dock_process(proc: psutil.Process) -> bool:
    """Return True if the process has a command-line argument ending with serit_v5.pyw.

    Ignores bekci itself and processes that do not explicitly target serit_v5.pyw.
    """
    try:
        if proc.pid == os.getpid():
            return False
        cmdline = proc.cmdline()
        if not cmdline:
            return False
        for arg in cmdline:
            norm_arg = str(arg).strip().replace("\\", "/").lower()
            if norm_arg.endswith("serit_v5.pyw"):
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    except Exception:
        return False
    return False


def find_dock_process() -> Optional[psutil.Process]:
    """Find a running dock process by inspecting cmdline arguments."""
    for proc in psutil.process_iter(["pid"]):
        try:
            if is_dock_process(proc):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def find_dock_hwnd(pid: int) -> int:
    """Find top-level window handle for the given process ID."""
    if not pid:
        return 0
    found_hwnd = 0
    try:
        user32 = getattr(winapi, "user32", None)
        if user32 is None:
            return 0

        def enum_cb(hwnd_raw: int, _: int) -> bool:
            nonlocal found_hwnd
            hwnd = int(hwnd_raw or 0)
            target_pid = w.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
            if target_pid.value == pid:
                found_hwnd = hwnd
                return False
            return True

        cb_type = getattr(winapi, "WNDENUMPROC", None)
        if cb_type is not None:
            user32.EnumWindows(cb_type(enum_cb), 0)
    except Exception as exc:
        _log(f"find_dock_hwnd error: {exc}")
    return found_hwnd


def release_appbar(hwnd: int = 0) -> bool:
    """Release dock AppBar reservation via winapi APPBARDATA and ABM_REMOVE."""
    try:
        shell32 = getattr(winapi, "shell32", None)
        appbar_cls = getattr(winapi, "APPBARDATA", None)
        if shell32 is None or appbar_cls is None:
            return False
        abd = appbar_cls()
        abd.cbSize = ctypes.sizeof(appbar_cls)
        abd.hWnd = int(hwnd or 0)
        shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))
        _log(f"released appbar for hwnd {hwnd}")
        return True
    except Exception as exc:
        _log(f"release_appbar error: {exc}")
        return False


def restore_taskbar(
    settings_path: Path = SETTINGS_FILE,
    force_visible: bool = False,
) -> bool:
    """Restore Windows taskbar autohide state.

    Respects settings.json 'taskbar_original' unless force_visible is True.
    If taskbar_original was False (or missing), autohide is set to False (visible).
    Never writes to settings.json.
    """
    target_autohide = False
    if not force_visible:
        try:
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    orig = data.get("taskbar_original")
                    if orig is not None:
                        target_autohide = bool(orig)
        except Exception as exc:
            _log(f"restore_taskbar settings read error: {exc}")

    try:
        winapi.taskbar_autohide_set(target_autohide)
        _log(f"taskbar restored (autohide={target_autohide}, force_visible={force_visible})")
        return True
    except Exception as exc:
        _log(f"restore_taskbar error: {exc}")
        return False


def read_marker(marker_path: Path) -> Optional[dict]:
    """Parse the marker JSON; None if missing or unparseable."""
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def evaluate_exit(
    marker_path: Path = MARKER_FILE,
    watched_pids: Optional[Iterable[int]] = None,
    started_at: float = 0.0,
) -> Tuple[bool, str]:
    """Decide whether an exit was deliberate. Returns (clean, reason).

    A marker counts only if its pid/ppid is in watched_pids and its time >= started_at - 2 s.
    A marker that exists but does not qualify is deleted (stale).
    """
    if not marker_path.exists():
        return False, "no marker"
    pids = {int(p) for p in (watched_pids or []) if p}
    data = read_marker(marker_path)
    reason = ""
    ok = False
    if data is None:
        reason = "unparseable/empty marker"
    else:
        try:
            m_pid = int(data.get("pid", 0) or 0)
            m_ppid = int(data.get("ppid", 0) or 0)
            m_t = float(data.get("t", 0) or 0)
        except (TypeError, ValueError):
            m_pid = m_ppid = 0
            m_t = 0.0
        if not m_t:
            try:
                m_t = marker_path.stat().st_mtime
            except OSError:
                m_t = 0.0
        hit = m_pid if m_pid in pids else (m_ppid if m_ppid in pids else 0)
        if not hit:
            reason = f"foreign pid (marker pid={m_pid} ppid={m_ppid}, watching {sorted(pids)})"
        elif m_t < started_at - 2.0:
            reason = f"older than process start (marker t={m_t:.0f} < start {started_at:.0f})"
        else:
            ok = True
            reason = f"marker matched pid {hit}"
    if not ok:
        try:
            marker_path.unlink()
        except Exception:
            pass
        _log(f"stale marker ignored ({reason})")
    return ok, reason


def is_clean_exit(
    marker_path: Path = MARKER_FILE,
    watched_pids: Optional[Iterable[int]] = None,
    started_at: float = 0.0,
) -> bool:
    """True only if a valid marker (see evaluate_exit) proves a deliberate close.

    Exit code and the hide_taskbar setting play no role: no valid marker = crash.
    A valid marker is consumed (deleted).
    """
    ok, _ = evaluate_exit(marker_path, watched_pids, started_at)
    if ok:
        try:
            marker_path.unlink()
        except Exception:
            pass
    return ok


def clear_marker(marker_path: Path) -> None:
    try:
        if marker_path.exists():
            marker_path.unlink()
            _log("cleared existing .clean_exit marker")
    except Exception:
        pass


def launch_dock(
    pythonw_path: Path = PYTHONW_PATH,
    dock_script: Path = DOCK_SCRIPT,
    app_dir: Path = APP_DIR,
) -> subprocess.Popen:
    """Launch the dock as a child process."""
    py_exe = pythonw_path if pythonw_path.exists() else Path(sys.executable)
    cmd = [str(py_exe), str(dock_script)]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _log(f"Launching dock: {cmd} (cwd={app_dir})")
    proc = subprocess.Popen(
        cmd,
        cwd=str(app_dir),
        creationflags=creationflags,
    )
    return proc


class SingleInstance:
    """Named mutex to prevent multiple watchdog instances from running concurrently."""

    def __init__(self, name: str = MUTEX_NAME):
        self.name = name
        self.handle = None
        self.already_running = False

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True

        kernel32 = getattr(ctypes, "windll", None)
        if kernel32 is None or not hasattr(kernel32, "kernel32"):
            return True
        k32 = kernel32.kernel32
        create_mutex = getattr(k32, "CreateMutexW", None)
        get_last_error = getattr(k32, "GetLastError", None)
        if create_mutex is None or get_last_error is None:
            return True

        create_mutex.argtypes = [w.LPVOID, w.BOOL, w.LPCWSTR]
        create_mutex.restype = w.HANDLE
        get_last_error.argtypes = []
        get_last_error.restype = w.DWORD

        self.handle = create_mutex(None, False, self.name)
        # ERROR_ALREADY_EXISTS = 183
        if not self.handle or get_last_error() == 183:
            self.already_running = True
            if self.handle:
                try:
                    k32.CloseHandle(self.handle)
                except Exception:
                    pass
                self.handle = None
            return False
        return True

    def release(self) -> None:
        if self.handle:
            try:
                kernel32 = getattr(ctypes, "windll", None)
                if kernel32 and hasattr(kernel32, "kernel32"):
                    kernel32.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None

    def __enter__(self) -> SingleInstance:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class SeritBekci:
    """Watchdog daemon for Şerit dock."""

    def __init__(
        self,
        poll_interval: float = 3.0,
        max_restarts: int = 3,
        window_seconds: float = 600.0,
        settings_path: Path = SETTINGS_FILE,
        marker_path: Path = MARKER_FILE,
        pythonw_path: Path = PYTHONW_PATH,
        dock_script: Path = DOCK_SCRIPT,
        app_dir: Path = APP_DIR,
    ):
        self.poll_interval = poll_interval
        self.max_restarts = max_restarts
        self.window_seconds = window_seconds
        self.settings_path = settings_path
        self.marker_path = marker_path
        self.pythonw_path = pythonw_path
        self.dock_script = dock_script
        self.app_dir = app_dir

        self.crash_timestamps: List[float] = []
        self.child_proc: Optional[subprocess.Popen] = None
        self.monitored_pid: Optional[int] = None
        self.dock_hwnd: Optional[int] = None
        self.running: bool = False
        self.started_at: float = 0.0
        self.watched_pids: set = set()

    def _track_children(self, pid: int) -> None:
        """Remember the pids of the watched process and its children (launcher -> real dock)."""
        try:
            self.watched_pids.add(pid)
            for ch in psutil.Process(pid).children(recursive=True):
                self.watched_pids.add(ch.pid)
        except Exception:
            pass

    def _attach_existing(self, reason: str) -> bool:
        """If another live dock exists, watch it instead of launching a second one."""
        existing = find_dock_process()
        if existing is None:
            return False
        self.monitored_pid = existing.pid
        self.watched_pids = {existing.pid}
        try:
            self.started_at = existing.create_time()
        except Exception:
            self.started_at = time.time()
        self._track_children(existing.pid)
        self.dock_hwnd = find_dock_hwnd(existing.pid)
        _log(f"attached to existing dock PID {existing.pid} ({reason})")
        return True

    def start_dock(self) -> None:
        """Start or restart the dock as a child process."""
        clear_marker(self.marker_path)
        self.started_at = time.time()
        self.watched_pids = set()
        self.child_proc = launch_dock(
            pythonw_path=self.pythonw_path,
            dock_script=self.dock_script,
            app_dir=self.app_dir,
        )
        self.monitored_pid = self.child_proc.pid
        self.watched_pids = {self.child_proc.pid}
        self.dock_hwnd = None
        _log(f"Dock child process started with PID {self.child_proc.pid}")

    def handle_crash(self) -> bool:
        """Handle dock process crash: restore taskbar, release appbar, and restart if allowed.

        Returns True if restarted, False if budget exceeded (stopped).
        """
        now = time.time()
        self.crash_timestamps = [
            t for t in self.crash_timestamps if (now - t) <= self.window_seconds
        ]
        self.crash_timestamps.append(now)
        crash_count = len(self.crash_timestamps)

        budget_exceeded = crash_count > self.max_restarts

        _log(
            f"Dock crash #{crash_count} within {self.window_seconds}s "
            f"(budget_exceeded={budget_exceeded})"
        )

        # Restore taskbar: force visible if budget exceeded
        restore_taskbar(
            settings_path=self.settings_path,
            force_visible=budget_exceeded,
        )

        # Release AppBar
        release_appbar(self.dock_hwnd or 0)
        self.dock_hwnd = None

        if budget_exceeded:
            _log(
                f"Crash limit ({self.max_restarts} in {self.window_seconds}s) exceeded. "
                "Taskbar restored to visible. Stopping watchdog."
            )
            self.running = False
            return False

        _log(f"Restarting dock ({crash_count}/{self.max_restarts})...")
        self.start_dock()
        return True

    def step(self) -> None:
        """Perform one monitoring tick. Suitable for direct testing."""
        # 1. Monitoring child process started by bekci
        if self.child_proc is not None:
            ret = self.child_proc.poll()
            if ret is None:
                # Still running
                self._track_children(self.child_proc.pid)
                if not self.dock_hwnd and self.child_proc.pid:
                    self.dock_hwnd = find_dock_hwnd(self.child_proc.pid)
                return

            # Child process has exited!
            pid = self.child_proc.pid
            self.watched_pids.add(pid)
            clean, reason = evaluate_exit(self.marker_path, self.watched_pids, self.started_at)
            if clean:
                clear_marker(self.marker_path)
            self.child_proc = None
            self.monitored_pid = None

            if clean:
                _log(f"Dock child process {pid} exited cleanly (code {ret}; {reason}). Watchdog stopping.")
                self.running = False
            else:
                _log(f"Dock child process {pid} exited without valid marker (code {ret}; {reason}): crash.")
                if self._attach_existing("another dock is alive"):
                    return
                self.handle_crash()
            return

        # 2. Monitoring external dock process
        if self.monitored_pid is not None:
            is_alive = False
            try:
                p = psutil.Process(self.monitored_pid)
                if p.is_running() and is_dock_process(p):
                    is_alive = True
                    if not self.dock_hwnd:
                        self.dock_hwnd = find_dock_hwnd(self.monitored_pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                is_alive = False
            except Exception:
                is_alive = False

            if is_alive:
                self._track_children(self.monitored_pid)
                return

            # External process is no longer running!
            pid = self.monitored_pid
            self.monitored_pid = None
            self.watched_pids.add(pid)
            clean, reason = evaluate_exit(self.marker_path, self.watched_pids, self.started_at)
            if clean:
                clear_marker(self.marker_path)
                _log(f"External dock process {pid} exited cleanly ({reason}). Watchdog stopping.")
                self.running = False
            else:
                _log(f"External dock process {pid} disappeared without valid marker ({reason}): crash.")
                if self._attach_existing("another dock is alive"):
                    return
                self.handle_crash()
            return

        # 3. Neither child nor external process is currently tracked.
        if self._attach_existing("startup"):
            pass
        else:
            _log("No active dock process found. Starting dock.")
            self.start_dock()

    def run(self) -> None:
        """Main loop: run step() every poll_interval seconds."""
        self.running = True
        _log("Şerit bekçi watchdog started.")
        clear_marker(self.marker_path)
        try:
            while self.running:
                self.step()
                if not self.running:
                    break
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            _log("Watchdog interrupted by user.")
        finally:
            _log("Şerit bekçi watchdog stopped.")


def main() -> int:
    mutex = SingleInstance()
    if not mutex.acquire():
        _log("Another bekci instance is already running (mutex held). Exiting.")
        return 0

    try:
        bekci = SeritBekci()
        bekci.run()
    finally:
        mutex.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
