"""tray_actions.py - Process resolution and safe termination for Şerit tray items.

How the dock will use it:
-------------------------
On right-click of a tray icon (band icon or a row of the Bildirim Alanı panel):
1. The dock dispatches `resolve_processes(item)` to its background worker pool.
2. In the UI thread, it opens `ActionMenu` with:
     header = clean_tray_name(item)
     subtitle = res['label'] if res['ok'] else res['reason']
     actions = [
       {'id': 'open', 'text': 'Aç', 'icon': 'open'},
       {'id': 'end',  'text': 'Görevi sonlandır', 'icon': 'stop',
        'danger': True, 'confirm': True, 'enabled': res['ok'], 'hint': res['reason']}
     ]
3. When the user confirms 'end', the dock dispatches `end_task(item)` on the pool.
4. The dock schedules tray list refreshes after 800 ms and 3.0 s.

Pure Python, worker-thread safe, never raises exceptions to callers.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import psutil

# Safe imports for Serit environment
try:
    from sources import log_err
except ImportError:
    def log_err(source: str, exc: Exception) -> None:
        pass

try:
    import tray_panel
except ImportError:
    tray_panel = None

try:
    import trayicons
except ImportError:
    trayicons = None


# Generic host executables that host scripts or managed child runtimes
GENERIC_HOSTS: Set[str] = {
    "python.exe",
    "pythonw.exe",
    "py.exe",
    "autohotkey.exe",
    "autohotkey64.exe",
    "autohotkey32.exe",
    "node.exe",
    "java.exe",
    "javaw.exe",
    "wscript.exe",
    "cscript.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
}

# Known token mappings for common apps running under generic hosts
TOKEN_MAP: Dict[str, List[str]] = {
    "dikte": ["dikte", "bekci", "bekçi"],
    "cmdpal-tab": ["cmdpal-tab", "cmdpal", "tapaj"],
    "tapaj": ["tapaj", "cmdpal-tab", "cmdpal"],
}


def _norm_path(p: Any) -> str:
    """Normalize file paths for robust case-insensitive comparison on Windows."""
    if not p or not isinstance(p, (str, Path)):
        return ""
    try:
        return os.path.normcase(os.path.abspath(str(p)))
    except Exception:
        return str(p).strip().lower()


def _is_windows_system(exe_path: str) -> bool:
    """Return True if executable resides in Windows system root (%SystemRoot%),
    excluding user-mode driver repositories such as DriverStore.
    """
    if not exe_path:
        return False
    norm_exe = _norm_path(exe_path)
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    norm_sys = _norm_path(sys_root)
    sep = os.sep
    if norm_exe.startswith(norm_sys + sep) or norm_exe == norm_sys:
        # User-mode vendor drivers in DriverStore are not protected core Windows components
        ds = _norm_path(os.path.join(sys_root, "System32", "DriverStore"))
        if norm_exe.startswith(ds + sep) or norm_exe == ds:
            return False
        return True
    return False


def _is_current_user(username: Optional[str]) -> bool:
    """Check if the process username belongs to the current interactive user."""
    if not username:
        return False
    u = username.lower().strip()
    curr = getpass.getuser().lower().strip()
    return u == curr or u.endswith("\\" + curr) or u.endswith("/" + curr)


def _is_generic_host(exe_path: str) -> bool:
    """Check if the executable is a generic interpreter/script host."""
    try:
        stem_ext = Path(exe_path).name.lower()
        if stem_ext in GENERIC_HOSTS:
            return True
        if stem_ext.startswith("autohotkey") or stem_ext.startswith("python"):
            return True
    except Exception:
        pass
    return False


def _derive_tokens(item: Dict[str, Any]) -> List[str]:
    """Derive distinctive tokens from item fields (name, tooltip, clean name)."""
    tokens: Set[str] = set()
    raw_name = str(item.get("name") or "").lower()
    raw_tip = str(item.get("tooltip") or "").lower()
    raw_full = str(item.get("full_name") or "").lower()
    clean_name = ""
    try:
        if tray_panel and hasattr(tray_panel, "clean_tray_name"):
            clean_name = tray_panel.clean_tray_name(item).lower()
    except Exception:
        pass

    for k, v in TOKEN_MAP.items():
        if k in raw_name or k in raw_tip or k in raw_full or k in clean_name:
            tokens.update(v)

    for text in (clean_name, raw_name, raw_tip, raw_full):
        if not text:
            continue
        words = re.findall(r"[a-zA-Z0-9_\-\.]{4,}", text)
        for w in words:
            w_clean = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", w).lower()
            if len(w_clean) >= 4:
                tokens.add(w_clean)

    return list(tokens)


def _get_self_pids() -> Set[int]:
    """Return set of current process PID, its ancestors, and direct children."""
    prot: Set[int] = set()
    try:
        cur = psutil.Process()
        prot.add(cur.pid)
        for parent in cur.parents():
            prot.add(parent.pid)
        for child in cur.children(recursive=True):
            try:
                cmd = " ".join(child.cmdline()).lower()
                if "serit_kill_probe_" in cmd:
                    continue
            except Exception:
                pass
            prot.add(child.pid)
    except Exception:
        pass
    return prot


def _is_protected_proc(proc: psutil.Process, self_pids: Set[int]) -> Tuple[bool, str]:
    """Return (True, reason) if a process is protected from termination."""
    try:
        if proc.pid in self_pids:
            return True, "Şerit korumalı işlem"
    except Exception:
        return True, "Korumalı işlem"

    try:
        exe = proc.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
        exe = ""

    try:
        cmdline = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
        cmdline = []

    cmd_str = " ".join(cmdline).lower()
    exe_norm = _norm_path(exe)

    # Protect Şerit dock instances
    if "serit_v5" in cmd_str:
        return True, "Şerit korumalı işlem"

    name_lower = ""
    try:
        name_lower = proc.name().lower()
    except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
        pass

    # Protect Windows Explorer
    if name_lower == "explorer.exe" or exe_norm.endswith("explorer.exe"):
        return True, "Windows bileşeni sonlandırılamaz"

    # Protect Windows System components
    if exe and _is_windows_system(exe):
        return True, "Windows bileşeni sonlandırılamaz"

    # Protect Hermes agent environment
    if "\\hermes\\" in exe_norm or "/hermes/" in exe_norm or "hermes-agent" in exe_norm or "hermes-agent" in cmd_str:
        return True, "Hermes korumalı işlem"

    return False, ""


def resolve_processes(item: Any) -> Dict[str, Any]:
    """Resolve process trees corresponding to a system tray item.

    Returns:
        dict {
            'ok': bool,
            'pids': list[int],
            'roots': list[int],
            'count': int,
            'label': str (Turkish, e.g. 'Zoom · 3 işlem'),
            'reason': str | None (Turkish reason when not ok)
        }
    """
    empty_result = {
        "ok": False,
        "pids": [],
        "roots": [],
        "count": 0,
        "label": "",
        "reason": "İşlem bulunamadı",
    }
    try:
        if not isinstance(item, dict):
            return empty_result

        raw_exe = item.get("exe")
        if not raw_exe or not isinstance(raw_exe, str) or not raw_exe.strip():
            return empty_result

        # Check if item itself is a Windows system component
        if _is_windows_system(raw_exe):
            return {
                "ok": False,
                "pids": [],
                "roots": [],
                "count": 0,
                "label": "",
                "reason": "Windows bileşeni sonlandırılamaz",
            }

        target_exe = _norm_path(raw_exe)
        is_gen = _is_generic_host(raw_exe)
        tokens = _derive_tokens(item) if is_gen else []

        self_pids = _get_self_pids()
        clean_name = ""
        try:
            if tray_panel and hasattr(tray_panel, "clean_tray_name"):
                clean_name = tray_panel.clean_tray_name(item)
        except Exception:
            pass
        if not clean_name:
            clean_name = str(item.get("name") or Path(raw_exe).stem)

        any_exe_match = False
        other_user_or_system = False
        protected_count = 0

        matched_candidates: Dict[int, psutil.Process] = {}

        for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "username"]):
            try:
                p_exe = p.info.get("exe") or ""
                if not p_exe:
                    continue
                if _norm_path(p_exe) != target_exe:
                    continue

                any_exe_match = True

                # Check generic host cmdline match
                if is_gen:
                    p_cmd = p.info.get("cmdline") or []
                    cmd_str = " ".join(p_cmd).lower()
                    matched_token = False
                    for tok in tokens:
                        if tok in cmd_str:
                            matched_token = True
                            break
                    # Special Dikte watchdog rule: include watchdog under D:/Apps/dikte
                    if not matched_token and ("dikte" in tokens or "bekci" in tokens):
                        if "d:/apps/dikte" in cmd_str or "d:\\apps\\dikte" in cmd_str or "bekci" in cmd_str:
                            matched_token = True

                    if not matched_token:
                        continue

                # Check protected status
                is_prot, _ = _is_protected_proc(p, self_pids)
                if is_prot:
                    protected_count += 1
                    continue

                # Check user ownership
                u = p.info.get("username")
                if not _is_current_user(u):
                    other_user_or_system = True
                    continue

                matched_candidates[p.pid] = p

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                other_user_or_system = True
                continue
            except Exception:
                continue

        if not matched_candidates:
            if protected_count > 0:
                return {
                    "ok": False,
                    "pids": [],
                    "roots": [],
                    "count": 0,
                    "label": "",
                    "reason": "Şerit korumalı işlem",
                }
            if other_user_or_system or (any_exe_match and not is_gen):
                return {
                    "ok": False,
                    "pids": [],
                    "roots": [],
                    "count": 0,
                    "label": "",
                    "reason": "Yönetici izni gerekiyor",
                }
            return empty_result

        # Identify roots among matched_candidates
        initial_pids = set(matched_candidates.keys())
        matched_roots: List[psutil.Process] = []
        for pid, proc in matched_candidates.items():
            try:
                ppid = proc.ppid()
                if ppid not in initial_pids:
                    matched_roots.append(proc)
            except Exception:
                matched_roots.append(proc)

        # Include descendants of each matched root
        full_process_map: Dict[int, psutil.Process] = dict(matched_candidates)
        for root in matched_roots:
            try:
                for child in root.children(recursive=True):
                    if child.pid in full_process_map:
                        continue
                    is_prot, _ = _is_protected_proc(child, self_pids)
                    if is_prot:
                        continue
                    try:
                        u = child.username()
                    except Exception:
                        u = None
                    if not _is_current_user(u):
                        continue
                    full_process_map[child.pid] = child
            except Exception:
                pass

        # Final roots calculation in full_process_map
        all_pids = set(full_process_map.keys())
        final_roots: List[int] = []
        for pid, proc in full_process_map.items():
            try:
                ppid = proc.ppid()
                if ppid not in all_pids:
                    final_roots.append(pid)
            except Exception:
                final_roots.append(pid)

        sorted_pids = sorted(all_pids)
        final_roots.sort()
        count = len(sorted_pids)

        label = f"{clean_name} · {count} işlem"

        return {
            "ok": True,
            "pids": sorted_pids,
            "roots": final_roots,
            "count": count,
            "label": label,
            "reason": None,
        }

    except Exception as exc:
        log_err("tray_actions.resolve_processes", exc)
        return empty_result


def end_task(item: Any, timeout: float = 3.0) -> Dict[str, Any]:
    """Safely terminate all processes associated with a tray item.

    Re-resolves processes dynamically (never trusts stale PIDs).
    Terminates children first, waits up to timeout seconds.
    Escalates to kill() on any survivors, waits up to 1.0 second more.
    Never kills anything outside resolve_processes().
    Worker-thread safe, never raises.
    """
    try:
        resolved = resolve_processes(item)
        if not resolved.get("ok"):
            return {
                "ok": False,
                "killed": 0,
                "survivors": 0,
                "reason": resolved.get("reason") or "İşlem bulunamadı",
            }

        pids = resolved.get("pids") or []
        if not pids:
            return {
                "ok": True,
                "killed": 0,
                "survivors": 0,
                "reason": None,
            }

        # Build set of self and protected PIDs to strictly prevent harming system
        self_pids = _get_self_pids()

        procs: Dict[int, psutil.Process] = {}
        for pid in pids:
            if pid in self_pids:
                continue
            try:
                p = psutil.Process(pid)
                is_prot, _ = _is_protected_proc(p, self_pids)
                if not is_prot:
                    procs[pid] = p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not procs:
            return {
                "ok": True,
                "killed": 0,
                "survivors": 0,
                "reason": None,
            }

        # Order procs: children first (non-roots first, roots last)
        roots_set = set(resolved.get("roots") or [])
        ordered_procs = [p for pid, p in procs.items() if pid not in roots_set] + [
            p for pid, p in procs.items() if pid in roots_set
        ]

        # 1. Terminate all (children first)
        for p in ordered_procs:
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass
            except Exception as exc:
                log_err("tray_actions.end_task.terminate", exc)

        gone, alive = psutil.wait_procs(list(procs.values()), timeout=timeout)

        # 2. Escalate to kill() for any survivors
        if alive:
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                except Exception as exc:
                    log_err("tray_actions.end_task.kill", exc)

            gone2, alive2 = psutil.wait_procs(alive, timeout=1.0)
            survivors_count = len(alive2)
        else:
            survivors_count = 0

        total_initial = len(procs)
        killed_count = total_initial - survivors_count

        if survivors_count > 0:
            return {
                "ok": False,
                "killed": killed_count,
                "survivors": survivors_count,
                "reason": f"{survivors_count} işlem sonlandırılamadı",
            }

        return {
            "ok": True,
            "killed": killed_count,
            "survivors": 0,
            "reason": None,
        }

    except Exception as exc:
        log_err("tray_actions.end_task", exc)
        return {
            "ok": False,
            "killed": 0,
            "survivors": 0,
            "reason": str(exc),
        }


def open_item(item: Any) -> bool:
    """Activate tray item (open application / restore window).

    Delegates to trayicons.activate(item, button='left').
    Worker-thread safe, never raises.
    """
    try:
        if trayicons and hasattr(trayicons, "activate"):
            return bool(trayicons.activate(item, button="left"))
    except Exception as exc:
        log_err("tray_actions.open_item", exc)
    return False
