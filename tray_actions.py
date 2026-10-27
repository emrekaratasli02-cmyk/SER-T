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

import datetime
import getpass
import os
from pathlib import Path
import re
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

import psutil

# Safe imports for Serit environment
try:
    from sources import log_err
except ImportError:
    def log_err(source: str, exc: Exception) -> None:
        pass

try:
    from logpath import LOG_PATH
except ImportError:
    LOG_PATH = Path("D:/Apps/serit/serit.log")


def _log_audit(msg: str) -> None:
    """Audit logger for end_task actions."""
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} {msg}\n")
    except Exception:
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

# Blacklist of generic words that must never be used to identify processes
BLACKLIST_WORDS: Set[str] = {
    "python",
    "pythonw",
    "py",
    "autohotkey",
    "autohotkey64",
    "autohotkey32",
    "node",
    "java",
    "javaw",
    "cmd",
    "powershell",
    "pwsh",
    "wscript",
    "cscript",
    "users",
    "user",
    "appdata",
    "local",
    "programs",
    "program",
    "files",
    "windows",
    "system32",
    "scripts",
    "venv",
    "apps",
    "tools",
    "bin",
    "lib",
    "exe",
    "setting",
    "settings",
}

try:
    _curr_u = getpass.getuser().lower().strip()
    if _curr_u:
        BLACKLIST_WORDS.add(_curr_u)
        for _part in re.split(r"[\s_.-]+", _curr_u):
            if _part:
                BLACKLIST_WORDS.add(_part)
except Exception:
    pass


class ProcessEntry(NamedTuple):
    """Entry holding (pid, create_time). Supports 2-tuple unpacking (pid, create_time),
    attribute access (.pid, .create_time), and dict-like key access."""

    pid: int
    create_time: float = 0.0

    def get(self, key: str, default: Any = None) -> Any:
        if key == "pid":
            return self.pid
        if key == "create_time":
            return self.create_time
        return default

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item == "pid":
                return self.pid
            if item == "create_time":
                return self.create_time
            raise KeyError(item)
        return tuple.__getitem__(self, item)


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
    """Derive distinctive tokens from item fields (name, tooltip, clean name),
    filtering out generic blacklisted words.
    """
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
            for mapped in v:
                m_clean = mapped.lower().strip()
                if m_clean and m_clean not in BLACKLIST_WORDS:
                    tokens.add(m_clean)

    for text in (clean_name, raw_name, raw_tip, raw_full):
        if not text:
            continue
        words = re.findall(r"[a-zA-Z0-9_\-\.]{4,}", text)
        for w in words:
            w_clean = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", w).lower()
            if len(w_clean) >= 4 and w_clean not in BLACKLIST_WORDS:
                tokens.add(w_clean)

    return list(tokens)


def _match_generic_host_arguments(cmdline: List[str], tokens: List[str]) -> bool:
    """Match tokens only against script arguments (cmdline[1:]),
    comparing against each argument's file stem and its parent folder name (lowercase),
    by equality (or token == stem without extension), never substring of the whole line.
    """
    if not cmdline or len(cmdline) < 2 or not tokens:
        return False

    valid_tokens = {tok for tok in tokens if tok and tok not in BLACKLIST_WORDS}
    if not valid_tokens:
        return False

    for arg in cmdline[1:]:
        if not arg or not isinstance(arg, str):
            continue
        clean_arg = arg.strip('\'"')
        if not clean_arg:
            continue
        try:
            p = Path(clean_arg)
            stem = p.stem.lower()
            parent_name = p.parent.name.lower()
        except Exception:
            norm = clean_arg.replace("\\", "/").rstrip("/")
            parts = norm.split("/")
            stem = parts[-1].rsplit(".", 1)[0].lower() if parts else ""
            parent_name = parts[-2].lower() if len(parts) >= 2 else ""

        for tok in valid_tokens:
            if tok == stem:
                return True
            if parent_name and parent_name not in BLACKLIST_WORDS and tok == parent_name:
                return True

    return False


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
        "entries": [],
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
                "entries": [],
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

                # Check generic host script arguments match
                if is_gen:
                    p_cmd = p.info.get("cmdline") or []
                    if not _match_generic_host_arguments(p_cmd, tokens):
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
                    "entries": [],
                    "pids": [],
                    "roots": [],
                    "count": 0,
                    "label": "",
                    "reason": "Şerit korumalı işlem",
                }
            if other_user_or_system or (any_exe_match and not is_gen):
                return {
                    "ok": False,
                    "entries": [],
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

        entries: List[ProcessEntry] = []
        for pid in sorted_pids:
            proc = full_process_map.get(pid)
            ct = 0.0
            if proc:
                try:
                    if hasattr(proc, "create_time") and callable(proc.create_time):
                        ct = proc.create_time()
                except Exception:
                    pass
            entries.append(ProcessEntry(pid, ct))

        label = f"{clean_name} · {count} işlem"

        return {
            "ok": True,
            "entries": entries,
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
    Re-checks create_time and exe right before terminate and kill to prevent PID reuse race.
    Terminates children first, waits up to timeout seconds.
    Escalates to kill() on any survivors, waits up to 1.0 second more.
    Never kills anything outside resolve_processes().
    Logs an audit line on each execution.
    Worker-thread safe, never raises.
    """
    clean_name = ""
    try:
        if tray_panel and hasattr(tray_panel, "clean_tray_name"):
            clean_name = tray_panel.clean_tray_name(item)
    except Exception:
        pass
    if not clean_name:
        raw_exe_val = item.get("exe") if isinstance(item, dict) else ""
        clean_name = str((item.get("name") if isinstance(item, dict) else "") or (Path(raw_exe_val).stem if raw_exe_val else "Bilinmeyen"))

    kapatildi_list: List[str] = []
    hayatta_kalan_list: List[str] = []
    atlanan_list: List[str] = []
    proc_base_exe: Dict[int, str] = {}

    try:
        resolved = resolve_processes(item)
        if not resolved.get("ok"):
            reason_str = resolved.get("reason") or "İşlem bulunamadı"
            _log_audit(f"[tray_actions.end_task] {clean_name}: kapatıldı 0 (), hayatta kalan 0, atlanan 0 ({reason_str})")
            return {
                "ok": False,
                "killed": 0,
                "survivors": 0,
                "reason": reason_str,
            }

        entries = resolved.get("entries") or []
        pids = resolved.get("pids") or []
        expected_meta: Dict[int, float] = {}
        target_pids: List[int] = []

        if entries:
            for entry in entries:
                try:
                    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                        pid_val = int(entry[0])
                        ct_val = float(entry[1])
                        expected_meta[pid_val] = ct_val
                        target_pids.append(pid_val)
                except Exception:
                    pass

        if not target_pids:
            for p in pids:
                if isinstance(p, (tuple, list)):
                    target_pids.append(int(p[0]))
                else:
                    target_pids.append(int(p))

        if not target_pids:
            _log_audit(f"[tray_actions.end_task] {clean_name}: kapatıldı 0 (), hayatta kalan 0, atlanan 0 (hedef işlem yok)")
            return {
                "ok": True,
                "killed": 0,
                "survivors": 0,
                "reason": None,
            }

        raw_exe = item.get("exe") if isinstance(item, dict) else ""
        target_exe = _norm_path(raw_exe) if raw_exe else ""

        # Build set of self and protected PIDs to strictly prevent harming system
        self_pids = _get_self_pids()

        procs: Dict[int, psutil.Process] = {}
        for pid in target_pids:
            if pid in self_pids:
                atlanan_list.append(f"PID {pid}: Şerit korumalı işlem")
                continue
            try:
                p = psutil.Process(pid)
                is_prot, prot_reason = _is_protected_proc(p, self_pids)
                if is_prot:
                    atlanan_list.append(f"PID {pid}: {prot_reason or 'korumalı işlem'}")
                    continue

                exp_ct = expected_meta.get(pid, 0.0)
                if exp_ct > 0:
                    try:
                        if abs(p.create_time() - exp_ct) > 0.05:
                            atlanan_list.append(f"PID {pid}: create_time uyuşmazlığı")
                            continue
                    except Exception:
                        atlanan_list.append(f"PID {pid}: create_time okunamadı")
                        continue

                p_exe = ""
                if target_exe:
                    try:
                        p_exe = p.exe() if callable(getattr(p, "exe", None)) else ""
                        if p_exe and _norm_path(p_exe) != target_exe:
                            atlanan_list.append(f"PID {pid}: exe uyuşmazlığı")
                            continue
                    except Exception:
                        atlanan_list.append(f"PID {pid}: exe okunamadı")
                        continue

                if not p_exe:
                    try:
                        p_exe = p.exe() if callable(getattr(p, "exe", None)) else ""
                    except Exception:
                        pass
                base_name = Path(p_exe).name if p_exe else "exe"
                procs[pid] = p
                proc_base_exe[pid] = base_name

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                atlanan_list.append(f"PID {pid}: erişilemedi/yok")

        if not procs:
            atlanan_str = "; ".join(atlanan_list) if atlanan_list else "yok"
            _log_audit(f"[tray_actions.end_task] {clean_name}: kapatıldı 0 (), hayatta kalan 0, atlanan {len(atlanan_list)} ({atlanan_str})")
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

        def _check_safe_to_act(proc: psutil.Process) -> bool:
            try:
                exp_ct = expected_meta.get(proc.pid, 0.0)
                if exp_ct > 0:
                    if abs(proc.create_time() - exp_ct) > 0.05:
                        return False
                if target_exe:
                    p_e = proc.exe() if callable(getattr(proc, "exe", None)) else ""
                    if p_e and _norm_path(p_e) != target_exe:
                        return False
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                return False

        # 1. Terminate all (children first)
        for p in ordered_procs:
            try:
                if not _check_safe_to_act(p):
                    atlanan_list.append(f"PID {p.pid}: işlem değişti")
                    continue
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
                    if not _check_safe_to_act(p):
                        atlanan_list.append(f"PID {p.pid}: işlem değişti")
                        continue
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                except Exception as exc:
                    log_err("tray_actions.end_task.kill", exc)

            gone2, alive2 = psutil.wait_procs(alive, timeout=1.0)
            survivors_count = len(alive2)
            survivors_set = set(alive2)
        else:
            survivors_count = 0
            survivors_set = set()

        for pid, p in procs.items():
            base = proc_base_exe.get(pid, "exe")
            if p in survivors_set:
                hayatta_kalan_list.append(f"PID {pid} {base}")
            else:
                kapatildi_list.append(f"PID {pid} {base}")

        N = len(kapatildi_list)
        M = len(hayatta_kalan_list)
        K = len(atlanan_list)
        kapatildi_str = ", ".join(kapatildi_list)
        atlanan_str = "; ".join(atlanan_list) if atlanan_list else "yok"

        _log_audit(f"[tray_actions.end_task] {clean_name}: kapatıldı {N} ({kapatildi_str}), hayatta kalan {M}, atlanan {K} ({atlanan_str})")

        if survivors_count > 0:
            return {
                "ok": False,
                "killed": N,
                "survivors": survivors_count,
                "reason": f"{survivors_count} işlem sonlandırılamadı",
            }

        return {
            "ok": True,
            "killed": N,
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
