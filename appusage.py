"""Şerit uygulama kaynak kullanımı örnekleyicisi (v26 Modül B).

Tek NtQuerySystemInformation(SystemProcessInformation) çağrısıyla sistemdeki tüm
süreçlerin CPU ve bellek (WorkingSetPrivateSize) kullanımını toplar.
Ctrl tuşuyla simge üzerine gelindiğinde baloncuğa aktarılır.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

# x64 SYSTEM_PROCESS_INFORMATION ofsetleri (winternl.h / ntexapi.h)
_OFF_NEXT = 0
_OFF_WORKING_SET_PRIVATE = 8   # ULONGLONG (Görev Yöneticisi 'Bellek' sütunu)
_OFF_CREATE_TIME = 32          # LARGE_INTEGER (100-ns)
_OFF_USER_TIME = 40            # LARGE_INTEGER (100-ns)
_OFF_KERNEL_TIME = 48          # LARGE_INTEGER (100-ns)
_OFF_NAME_LEN = 56             # USHORT
_OFF_NAME_BUF = 64             # PWSTR
_OFF_PID = 80                  # HANDLE / ULONG_PTR

_ntdll = None
if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
    try:
        _ntdll = ctypes.WinDLL("ntdll")
        _ntdll.NtQuerySystemInformation.argtypes = [
            w.ULONG,
            ctypes.c_void_p,
            w.ULONG,
            ctypes.POINTER(w.ULONG),
        ]
        _ntdll.NtQuerySystemInformation.restype = ctypes.c_long
    except Exception:
        _ntdll = None

_buf_size = 512 * 1024


def query_system_processes() -> Optional[List[Tuple[int, str, int, int, int, int]]]:
    """Tüm süreçleri tek ntdll çağrısıyla okur.

    Dönüş: [(pid, ad, ws_private_bayt, create_time, user_time, kernel_time), ...]
    veya desteklenmiyorsa None.
    """
    global _buf_size
    if _ntdll is None:
        return None

    for _ in range(4):
        buf = ctypes.create_string_buffer(_buf_size)
        needed = w.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(
            _SYSTEM_PROCESS_INFORMATION, buf, _buf_size, ctypes.byref(needed)
        )
        if (status & 0xFFFFFFFF) == _STATUS_INFO_LENGTH_MISMATCH:
            _buf_size = max(_buf_size * 2, int(needed.value) + 64 * 1024)
            continue
        if status != 0:
            return None

        raw = buf.raw
        base = ctypes.addressof(buf)
        out: List[Tuple[int, str, int, int, int, int]] = []
        off = 0
        while True:
            nxt = int.from_bytes(raw[off + _OFF_NEXT : off + _OFF_NEXT + 4], "little")
            pid = int.from_bytes(raw[off + _OFF_PID : off + _OFF_PID + 8], "little")
            name_len = int.from_bytes(raw[off + _OFF_NAME_LEN : off + _OFF_NAME_LEN + 2], "little")
            name_ptr = int.from_bytes(raw[off + _OFF_NAME_BUF : off + _OFF_NAME_BUF + 8], "little")
            ws_priv = int.from_bytes(raw[off + _OFF_WORKING_SET_PRIVATE : off + _OFF_WORKING_SET_PRIVATE + 8], "little")
            create_t = int.from_bytes(raw[off + _OFF_CREATE_TIME : off + _OFF_CREATE_TIME + 8], "little")
            user_t = int.from_bytes(raw[off + _OFF_USER_TIME : off + _OFF_USER_TIME + 8], "little")
            kern_t = int.from_bytes(raw[off + _OFF_KERNEL_TIME : off + _OFF_KERNEL_TIME + 8], "little")

            name = ""
            if name_ptr and name_len:
                rel = name_ptr - base
                if 0 <= rel and rel + name_len <= len(raw):
                    name = raw[rel : rel + name_len].decode("utf-16-le", "replace")

            out.append((pid, name, ws_priv, create_t, user_t, kern_t))
            if nxt == 0:
                break
            off += nxt
            if off >= len(raw):
                break
        return out
    return None


def _unpack_row(row: Any) -> Tuple[int, str, int, int, int, int]:
    """Farklı biçimlerdeki (tuple, namedtuple, dict) süreç satırını ayrıştırır."""
    if isinstance(row, dict):
        return (
            int(row.get("pid", 0)),
            str(row.get("name", "")),
            int(row.get("ws_private", 0)),
            int(row.get("create_time", 0)),
            int(row.get("user_time", 0)),
            int(row.get("kernel_time", 0)),
        )
    if isinstance(row, (tuple, list)):
        return (
            int(row[0]),
            str(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
            int(row[5]),
        )
    return (
        int(getattr(row, "pid", 0)),
        str(getattr(row, "name", "")),
        int(getattr(row, "ws_private", 0)),
        int(getattr(row, "create_time", 0)),
        int(getattr(row, "user_time", 0)),
        int(getattr(row, "kernel_time", 0)),
    )


class AppUsageSampler:
    """Tüm uygulamaların CPU ve bellek kullanımını periyodik olarak sorgular."""

    def __init__(
        self,
        query_fn: Optional[Callable[[], Optional[List[Any]]]] = None,
        clock: Optional[Callable[[], float]] = None,
        cpu_count: Optional[int] = None,
    ) -> None:
        self._query_fn = query_fn or query_system_processes
        self._clock = clock or time.monotonic
        self._cpu_count = max(1, int(cpu_count or os.cpu_count() or 1))
        # (pid, create_time) -> (user_time + kernel_time)
        self._prev_procs: Optional[Dict[Tuple[int, int], int]] = None
        self._prev_t: Optional[float] = None

    def sample(self) -> Dict[str, Dict[str, Any]]:
        """İş parçacığından çağrılır: {exe_adı_küçük: {'cpu': float|None, 'mem_mb': float, 'procs': int}} döner."""
        now = self._clock()
        rows = self._query_fn()
        if rows is None:
            return {}

        is_first = (self._prev_t is None or self._prev_procs is None)
        dt = (now - self._prev_t) if not is_first and self._prev_t is not None else 0.0

        current_procs: Dict[Tuple[int, int], int] = {}
        exe_mem_bytes: Dict[str, int] = {}
        exe_proc_count: Dict[str, int] = {}
        exe_cpu_delta: Dict[str, int] = {}
        exe_has_tracked_procs: Dict[str, bool] = {}

        for row in rows:
            pid, name, ws_priv, create_t, user_t, kern_t = _unpack_row(row)
            if pid == 0 or not name:
                continue

            exe = name.lower()
            key = (pid, create_t)
            cpu_time = user_t + kern_t

            current_procs[key] = cpu_time
            exe_mem_bytes[exe] = exe_mem_bytes.get(exe, 0) + ws_priv
            exe_proc_count[exe] = exe_proc_count.get(exe, 0) + 1

            if not is_first and dt > 0 and self._prev_procs is not None:
                if key in self._prev_procs:
                    prev_cpu = self._prev_procs[key]
                    delta = cpu_time - prev_cpu
                    if delta > 0:
                        exe_cpu_delta[exe] = exe_cpu_delta.get(exe, 0) + delta
                    else:
                        exe_cpu_delta.setdefault(exe, 0)
                    exe_has_tracked_procs[exe] = True

        self._prev_procs = current_procs
        self._prev_t = now

        out: Dict[str, Dict[str, Any]] = {}
        for exe, count in exe_proc_count.items():
            mem_mb = exe_mem_bytes.get(exe, 0) / (1024.0 * 1024.0)
            if is_first or dt <= 0:
                cpu_val = None
            else:
                if exe_has_tracked_procs.get(exe, False):
                    delta = exe_cpu_delta.get(exe, 0)
                    # 100-ns biriminden saniyeye: / 10_000_000.0
                    share = (delta / (dt * 10_000_000.0 * self._cpu_count)) * 100.0
                    cpu_val = max(0.0, min(100.0, share))
                else:
                    cpu_val = None

            out[exe] = {
                "cpu": cpu_val,
                "mem_mb": mem_mb,
                "procs": count,
            }
        return out


def usage_for_tile(data: Optional[Dict[str, Any]], tile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Döşeme (tile) için exe temel adını küçük harfle bulup kullanım bilgisini döner."""
    if not data or not tile or not isinstance(tile, dict):
        return None
    exe_path = tile.get("exe")
    if not exe_path or not isinstance(exe_path, str):
        return None
    base = Path(exe_path).name.lower()
    return data.get(base)


def fmt_usage(u: Optional[Dict[str, Any]]) -> str:
    """Kullanım sözlüğünü Türkçe balon metnine dönüştürür.

    Örnek: 'CPU %12 · Bellek 1,4 GB' veya 'CPU — · Bellek 640 MB'.
    """
    if not u or not isinstance(u, dict):
        return "CPU — · Bellek —"

    cpu = u.get("cpu")
    mem = u.get("mem_mb")

    if cpu is None:
        c_str = "CPU —"
    elif cpu < 1.0:
        val = max(0.0, float(cpu))
        c_str = f"CPU %{val:.1f}".replace(".", ",")
        if c_str == "CPU %1,0":
            c_str = "CPU %1"
    else:
        c_str = f"CPU %{int(round(float(cpu)))}"

    if mem is None:
        m_str = "Bellek —"
    elif mem < 1000.0:
        m_str = f"Bellek {int(round(max(0.0, float(mem))))} MB"
    else:
        gb = float(mem) / 1024.0
        m_str = f"Bellek {gb:.1f}".replace(".", ",") + " GB"

    return f"{c_str} · {m_str}"
