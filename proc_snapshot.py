"""Tek sistem çağrısıyla tüm süreçlerin adı + bellek (working set) anlık görüntüsü.

psutil.process_iter(["memory_info"]) her süreç için ayrı çağrı yapar; erişim
reddedilen süreçlerde her seferinde tüm sistem listesini yeniden sorgular
(~273 süreçte ~440 ms). Bu sürede GIL çekişmesi GUI iş parçacığındaki
EnumWindows geri çağrılarını bekletir ve bar ~0,4 sn donar.

NtQuerySystemInformation(SystemProcessInformation) aynı veriyi tek çağrıda verir
(~2-5 ms). Yalnız okuma yapar; hiçbir süreç açılmaz.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import sys
from typing import Dict, List, Optional, Tuple

_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

# x64 SYSTEM_PROCESS_INFORMATION alan ofsetleri (winternl.h / ntexapi.h)
_OFF_NEXT = 0
_OFF_NAME_LEN = 56
_OFF_NAME_BUF = 64
_OFF_PID = 80
_OFF_WORKING_SET = 144

_ntdll = None
if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
    try:
        _ntdll = ctypes.WinDLL("ntdll")
        _ntdll.NtQuerySystemInformation.argtypes = [w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
        _ntdll.NtQuerySystemInformation.restype = ctypes.c_long
    except Exception:  # pragma: no cover - non-Windows / unusual systems
        _ntdll = None

_buf_size = 512 * 1024


def snapshot() -> Optional[List[Tuple[int, str, int]]]:
    """[(pid, ad, working_set_bayt), ...] ya da desteklenmiyorsa None."""
    global _buf_size
    if _ntdll is None:
        return None
    for _ in range(4):
        buf = ctypes.create_string_buffer(_buf_size)
        needed = w.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(_SYSTEM_PROCESS_INFORMATION, buf, _buf_size, ctypes.byref(needed))
        if (status & 0xFFFFFFFF) == _STATUS_INFO_LENGTH_MISMATCH:
            _buf_size = max(_buf_size * 2, int(needed.value) + 64 * 1024)
            continue
        if status != 0:
            return None
        raw = buf.raw
        out: List[Tuple[int, str, int]] = []
        off = 0
        base = ctypes.addressof(buf)
        while True:
            nxt = int.from_bytes(raw[off + _OFF_NEXT: off + _OFF_NEXT + 4], "little")
            pid = int.from_bytes(raw[off + _OFF_PID: off + _OFF_PID + 8], "little")
            name_len = int.from_bytes(raw[off + _OFF_NAME_LEN: off + _OFF_NAME_LEN + 2], "little")
            name_ptr = int.from_bytes(raw[off + _OFF_NAME_BUF: off + _OFF_NAME_BUF + 8], "little")
            ws = int.from_bytes(raw[off + _OFF_WORKING_SET: off + _OFF_WORKING_SET + 8], "little")
            name = ""
            if name_ptr and name_len:
                rel = name_ptr - base
                if 0 <= rel and rel + name_len <= len(raw):
                    name = raw[rel: rel + name_len].decode("utf-16-le", "replace")
            out.append((pid, name, ws))
            if nxt == 0:
                break
            off += nxt
            if off >= len(raw):
                break
        return out
    return None


def memory_by_name() -> Optional[Dict[str, float]]:
    """{süreç adı: toplam MB} ya da desteklenmiyorsa None."""
    snap = snapshot()
    if snap is None:
        return None
    agg: Dict[str, float] = {}
    for pid, name, ws in snap:
        if pid == 0 or not name:
            continue
        agg[name] = agg.get(name, 0.0) + ws / (1024.0 * 1024.0)
    return agg
