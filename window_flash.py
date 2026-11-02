"""window_flash.py - Taskbar attention flash (orange flash) detection via Win32 Shell Hook.

Monitors top-level application windows requesting attention (calls to FlashWindowEx)
without injecting hooks into foreign processes. Uses RegisterShellHookWindow on a
hidden message window in its own daemon thread with its own message loop.
"""

from __future__ import annotations

import collections
import ctypes
from ctypes import wintypes as w
import os
import threading
from typing import Callable, Optional

# --- Win32 Libraries ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# --- 64-bit Safe Win32 Types ---
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, WPARAM, LPARAM)

# --- ShellHook Constants ---
HSHELL_WINDOWCREATED = 1
HSHELL_WINDOWDESTROYED = 2
HSHELL_ACTIVATESHELLWINDOW = 3
HSHELL_WINDOWACTIVATED = 4
HSHELL_GETMINRECT = 5
HSHELL_REDRAW = 6
HSHELL_TASKMAN = 7
HSHELL_LANGUAGE = 8
HSHELL_SYSMENU = 9
HSHELL_ENDTASK = 10
HSHELL_ACCESSIBILITYSTATE = 11
HSHELL_APPCOMMAND = 12
HSHELL_WINDOWREPLACED = 13
HSHELL_WINDOWREPLACING = 14
HSHELL_HIGHBIT = 0x8000
HSHELL_RUDEAPPACTIVATED = 0x8004
HSHELL_FLASH = 0x8006

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010

# --- Ctypes Signatures ---
user32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
user32.RegisterWindowMessageW.restype = w.UINT

user32.RegisterShellHookWindow.argtypes = [w.HWND]
user32.RegisterShellHookWindow.restype = w.BOOL

user32.DeregisterShellHookWindow.argtypes = [w.HWND]
user32.DeregisterShellHookWindow.restype = w.BOOL

user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.DestroyWindow.argtypes = [w.HWND]
user32.DestroyWindow.restype = w.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.GetMessageW.restype = w.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.TranslateMessage.restype = w.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostMessageW.argtypes = [w.HWND, w.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = w.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.GetWindowThreadProcessId.argtypes = [w.HWND, w.LPDWORD]
user32.GetWindowThreadProcessId.restype = w.DWORD

kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HMODULE

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.UINT),
        ("style", w.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON),
        ("hCursor", w.HANDLE),
        ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
        ("hIconSm", w.HICON),
    ]

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = w.ATOM

user32.CreateWindowExW.argtypes = [
    w.DWORD,
    w.LPCWSTR,
    w.LPCWSTR,
    w.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    w.HWND,
    w.HMENU,
    w.HINSTANCE,
    w.LPVOID,
]
user32.CreateWindowExW.restype = w.HWND

try:
    _SHELL_HOOK_MSG = int(user32.RegisterWindowMessageW("SHELLHOOK") or 0)
except Exception:
    _SHELL_HOOK_MSG = 0

_REGISTRY_LOCK = threading.Lock()
_WATCHER_REGISTRY: dict[int, FlashWatcher] = {}


def _global_wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    try:
        if _SHELL_HOOK_MSG != 0 and msg == _SHELL_HOOK_MSG:
            with _REGISTRY_LOCK:
                watcher = _WATCHER_REGISTRY.get(hwnd)
            if watcher is not None:
                watcher._on_shell_event(int(wparam), int(lparam))
            return 0
        elif msg == WM_CLOSE:
            hwnd_w = w.HWND(hwnd)
            try:
                user32.DeregisterShellHookWindow(hwnd_w)
            except Exception:
                pass
            user32.DestroyWindow(hwnd_w)
            return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
    except Exception as exc:
        try:
            import sources
            sources.log_err("window_flash_wndproc", exc)
        except Exception:
            pass
    return int(user32.DefWindowProcW(w.HWND(hwnd), msg, wparam, lparam))


# Keep a persistent module-level reference to the callback so Python does not GC it
_GLOBAL_WNDPROC_REF = WNDPROC(_global_wnd_proc)

_CLASS_NAME = f"SeritFlashWatcherWindowClass_{os.getpid()}"
_CLASS_ATOM: Optional[int] = None
_CLASS_LOCK = threading.Lock()


def _ensure_class_registered() -> bool:
    global _CLASS_ATOM
    with _CLASS_LOCK:
        if _CLASS_ATOM is not None:
            return True
        try:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = _GLOBAL_WNDPROC_REF
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.hIcon = None
            wc.hCursor = None
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = _CLASS_NAME
            wc.hIconSm = None

            atom = user32.RegisterClassExW(ctypes.byref(wc))
            if atom == 0:
                err = ctypes.GetLastError()
                if err == 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    _CLASS_ATOM = 1
                    return True
                return False
            _CLASS_ATOM = int(atom)
            return True
        except Exception as exc:
            try:
                import sources
                sources.log_err("window_flash_regclass", exc)
            except Exception:
                pass
            return False


class FlashWatcher:
    """Monitors Windows Shell attention flash notifications (HSHELL_FLASH)."""

    def __init__(self) -> None:
        self._flashing_hwnds: set[int] = set()
        self._lock = threading.Lock()
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._hwnd: int = 0
        self._ready_event = threading.Event()

    def start(self) -> None:
        """Start listening for shell flash events in a dedicated background thread."""
        if self._running or (self._thread and self._thread.is_alive()):
            return

        try:
            import logpath
            under_test = bool(logpath.is_running_under_test())
        except Exception:
            under_test = False

        # In automated tests, do not touch real Windows hooks unless explicitly opted in
        if under_test and os.environ.get("SERIT_ALLOW_REAL_FLASH") != "1":
            self._running = True
            return

        try:
            self._running = True
            self._ready_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="SeritFlashWatcherThread",
                daemon=True,
            )
            self._thread.start()
            if not self._ready_event.wait(timeout=2.0) or not self._hwnd:
                self.stop()
        except Exception as exc:
            try:
                import sources
                sources.log_err("window_flash_start", exc)
            except Exception:
                pass
            self._running = False
            self._thread = None

    def _worker_loop(self) -> None:
        try:
            if not _ensure_class_registered():
                self._ready_event.set()
                return

            HWND_MESSAGE = w.HWND(-3)
            # Create hidden message-only window
            hwnd = user32.CreateWindowExW(
                0,
                _CLASS_NAME,
                "SeritFlashWatcherMsgWindow",
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                0,
                kernel32.GetModuleHandleW(None),
                0,
            )
            # Fallback to hidden unparented window if HWND_MESSAGE fails
            if not hwnd:
                hwnd = user32.CreateWindowExW(
                    0,
                    _CLASS_NAME,
                    "SeritFlashWatcherHiddenWindow",
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    kernel32.GetModuleHandleW(None),
                    0,
                )

            if not hwnd:
                self._ready_event.set()
                return

            self._hwnd = int(hwnd)
            with _REGISTRY_LOCK:
                _WATCHER_REGISTRY[self._hwnd] = self

            reg_ok = user32.RegisterShellHookWindow(hwnd)
            if not reg_ok:
                with _REGISTRY_LOCK:
                    _WATCHER_REGISTRY.pop(self._hwnd, None)
                user32.DestroyWindow(hwnd)
                self._hwnd = 0
                self._ready_event.set()
                return

            self._ready_event.set()

            msg = w.MSG()
            while self._running:
                res = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if res <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        except Exception as exc:
            try:
                import sources
                sources.log_err("window_flash_worker", exc)
            except Exception:
                pass
        finally:
            hwnd_to_clean = self._hwnd
            if hwnd_to_clean:
                with _REGISTRY_LOCK:
                    _WATCHER_REGISTRY.pop(hwnd_to_clean, None)
                try:
                    user32.DeregisterShellHookWindow(w.HWND(hwnd_to_clean))
                except Exception:
                    pass
                try:
                    user32.DestroyWindow(w.HWND(hwnd_to_clean))
                except Exception:
                    pass
                self._hwnd = 0
            self._ready_event.set()

    def stop(self) -> None:
        """Stop listening, deregister hooks, destroy helper window, and join worker thread."""
        if not self._running and self._thread is None:
            return

        self._running = False
        hwnd = self._hwnd
        if hwnd:
            try:
                user32.DeregisterShellHookWindow(w.HWND(hwnd))
            except Exception as exc:
                try:
                    import sources
                    sources.log_err("window_flash_deregister", exc)
                except Exception:
                    pass
            try:
                user32.PostMessageW(w.HWND(hwnd), WM_CLOSE, 0, 0)
            except Exception:
                pass

        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=2.0)

        if self._hwnd:
            try:
                user32.DestroyWindow(w.HWND(self._hwnd))
            except Exception:
                pass
            with _REGISTRY_LOCK:
                _WATCHER_REGISTRY.pop(self._hwnd, None)
            self._hwnd = 0

        with self._lock:
            self._flashing_hwnds.clear()
        self._thread = None

    def is_flashing(self, hwnd: int) -> bool:
        """Return True if the given window handle is currently flashing for attention."""
        with self._lock:
            return int(hwnd) in self._flashing_hwnds

    def flashing_hwnds(self) -> set[int]:
        """Return a copy of all window handles currently flashing for attention."""
        with self._lock:
            return set(self._flashing_hwnds)

    def snapshot_by_exe(
        self, resolve: Optional[Callable[[int], str]] = None
    ) -> dict[str, int]:
        """Return a mapping of lowercase executable path to number of flashing windows."""
        if resolve is None:
            resolve = self._default_resolve_exe

        with self._lock:
            hwnds = list(self._flashing_hwnds)

        counts: dict[str, int] = collections.defaultdict(int)
        for hwnd in hwnds:
            try:
                exe = resolve(hwnd)
                if exe:
                    counts[str(exe).lower()] += 1
            except Exception as exc:
                try:
                    import sources
                    sources.log_err("window_flash_snapshot", exc)
                except Exception:
                    pass
        return dict(counts)

    def _on_shell_event(self, wparam: int, lparam: int) -> None:
        """Internal callback invoked when a shell hook event message is received."""
        hwnd = int(lparam or 0)
        event = int(wparam or 0)
        if not hwnd:
            return

        if event == HSHELL_FLASH:
            with self._lock:
                self._flashing_hwnds.add(hwnd)
        elif event in (
            HSHELL_WINDOWACTIVATED,
            HSHELL_RUDEAPPACTIVATED,
            HSHELL_WINDOWDESTROYED,
        ):
            with self._lock:
                self._flashing_hwnds.discard(hwnd)

    @staticmethod
    def _default_resolve_exe(hwnd: int) -> str:
        """Resolve HWND to full executable path using winapi's existing logic."""
        try:
            pid = w.DWORD(0)
            user32.GetWindowThreadProcessId(w.HWND(hwnd), ctypes.byref(pid))
            pid_val = int(pid.value)
            if pid_val > 0:
                try:
                    import winapi
                    exe = winapi._exe_for(pid_val, hwnd)
                    if exe:
                        return exe
                except Exception:
                    pass
                import psutil
                return psutil.Process(pid_val).exe()
        except Exception as exc:
            try:
                import sources
                sources.log_err("window_flash_default_resolve", exc)
            except Exception:
                pass
        return ""
