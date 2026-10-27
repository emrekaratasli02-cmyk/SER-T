"""Worker-thread-safe screen brightness backend for Serit dock.

Handles internal laptop screens via WMI (root/wmi: WmiMonitorBrightness /
WmiMonitorBrightnessMethods) and external monitors via DDC/CI (dxva2.dll:
GetMonitorBrightness / SetMonitorBrightness). Safe for concurrent worker threads,
COM-initialized per thread, non-raising, with 30-second topology caching and
PowerShell fallback bounded by a 3-second timeout.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Win32 error codes & COM constants
COINIT_APARTMENTTHREADED: int = 0x2
RPC_E_CHANGED_MODE: int = -2147417850  # 0x80010106
S_FALSE: int = 1
CREATE_NO_WINDOW: int = 0x08000000

# Cache configuration
CACHE_TTL_SEC: float = 30.0

# Thread-local storage for per-thread COM initialization
_tls = threading.local()

# Mutex protecting cache state
_cache_lock = threading.Lock()
_cached_monitors: List[Dict[str, Any]] = []
_last_enum_time: float = 0.0


# ---------------------------------------------------------------------------
# Rate-limiting state for PowerShell fallback
# ---------------------------------------------------------------------------
_last_ps_query_time: float = 0.0
_last_ps_set_time: float = 0.0
_PS_RETRY_INTERVAL_SEC: float = 300.0  # 5 minutes


def _log_err(source: str, exc: Exception) -> None:
    """Log an exception through sources.log_err if available, never raising."""
    try:
        import sources
        sources.log_err(source, exc)
    except Exception:
        pass


def _ensure_com() -> bool:
    """Ensure COM is initialized on the current thread with COINIT_APARTMENTTHREADED."""
    if getattr(_tls, "com_initialized", False):
        return True
    try:
        import comtypes
        comtypes.CoInitializeEx(COINIT_APARTMENTTHREADED)
        _tls.com_initialized = True
        return True
    except Exception as exc:
        winerr = getattr(exc, "winerror", None)
        if winerr in (S_FALSE, 0x80010106, RPC_E_CHANGED_MODE):
            _tls.com_initialized = True
            return True
        _log_err("brightness_com_init", exc)
        return False


# ---------------------------------------------------------------------------
# Ctypes Structs and Function Signatures (64-bit safe handles)
# ---------------------------------------------------------------------------

class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)

# Initialize Win32 DLLs safely
user32 = ctypes.windll.user32
dxva2 = ctypes.windll.dxva2

user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    MONITORENUMPROC,
    wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [
    wintypes.HMONITOR,
    ctypes.POINTER(MONITORINFOEXW),
]
user32.GetMonitorInfoW.restype = wintypes.BOOL

user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW),
    wintypes.DWORD,
]
user32.EnumDisplayDevicesW.restype = wintypes.BOOL

dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR,
    ctypes.POINTER(wintypes.DWORD),
]
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR,
    wintypes.DWORD,
    ctypes.POINTER(PHYSICAL_MONITOR),
]
dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

dxva2.GetMonitorBrightness.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
dxva2.GetMonitorBrightness.restype = wintypes.BOOL

dxva2.SetMonitorBrightness.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
]
dxva2.SetMonitorBrightness.restype = wintypes.BOOL

dxva2.DestroyPhysicalMonitors.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(PHYSICAL_MONITOR),
]
dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# Internal Helpers: WMI & DDC Operations
# ---------------------------------------------------------------------------

def _decode_edid_chars(codes: Any) -> str:
    """Decode ASCII uint16 tuple/list from WmiMonitorID properties."""
    if not codes or not isinstance(codes, (tuple, list)):
        return ""
    try:
        return "".join(chr(c) for c in codes if c != 0).strip()
    except Exception:
        return ""


def _query_wmi_monitor_ids_com() -> Dict[str, str]:
    """Query WmiMonitorID to map instance and model codes to friendly EDID names."""
    edid_names: Dict[str, str] = {}
    if not _ensure_com():
        return edid_names
    try:
        import comtypes.client
        loc = comtypes.client.CreateObject("WbemScripting.SWbemLocator")
        svc = loc.ConnectServer(".", "root\\wmi")
        for item in svc.ExecQuery("SELECT * FROM WmiMonitorID"):
            try:
                inst = item.Properties_("InstanceName").Value
                ufn = item.Properties_("UserFriendlyName").Value
                name = _decode_edid_chars(ufn)
                if name and inst:
                    edid_names[inst.upper()] = name
                    parts = inst.split("\\")
                    if len(parts) >= 2:
                        edid_names[parts[1].upper()] = name
            except Exception:
                continue
    except Exception as exc:
        _log_err("brightness_wmi_ids_com", exc)
    return edid_names


def _query_wmi_brightness_com() -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Read internal monitor brightness via WMI COM interface."""
    monitors: List[Dict[str, Any]] = []
    wmi_keys: Set[str] = set()
    if not _ensure_com():
        return monitors, wmi_keys
    try:
        import comtypes.client
        loc = comtypes.client.CreateObject("WbemScripting.SWbemLocator")
        svc = loc.ConnectServer(".", "root\\wmi")
        for item in svc.ExecQuery("SELECT * FROM WmiMonitorBrightness"):
            try:
                inst = item.Properties_("InstanceName").Value
                lvl = item.Properties_("CurrentBrightness").Value
                if inst:
                    wmi_keys.add(inst.upper())
                    parts = inst.split("\\")
                    if len(parts) >= 2:
                        wmi_keys.add(parts[1].upper())
                val = int(lvl) if lvl is not None else None
                monitors.append({
                    "id": f"wmi:{inst}",
                    "name": "Dizüstü ekranı",
                    "kind": "wmi",
                    "level": val,
                    "min": 0,
                    "max": 100,
                    "ok": val is not None,
                    "err": None if val is not None else "WMI parlaklık okunamadı",
                })
            except Exception as item_exc:
                _log_err("brightness_wmi_item_com", item_exc)
    except Exception as exc:
        _log_err("brightness_wmi_com", exc)
    return monitors, wmi_keys


def _query_wmi_brightness_powershell() -> Tuple[List[Dict[str, Any]], Set[str]]:
    """PowerShell fallback for reading WmiMonitorBrightness with a 6-second timeout."""
    monitors: List[Dict[str, Any]] = []
    wmi_keys: Set[str] = set()
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness | "
        "Select-Object -Property InstanceName, CurrentBrightness | ConvertTo-Json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=6.0,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw = json.loads(proc.stdout.strip())
            items = raw if isinstance(raw, list) else [raw]
            for it in items:
                inst = it.get("InstanceName", "")
                lvl = it.get("CurrentBrightness")
                if inst:
                    wmi_keys.add(inst.upper())
                    parts = inst.split("\\")
                    if len(parts) >= 2:
                        wmi_keys.add(parts[1].upper())
                val = int(lvl) if lvl is not None else None
                monitors.append({
                    "id": f"wmi:{inst}",
                    "name": "Dizüstü ekranı",
                    "kind": "wmi",
                    "level": val,
                    "min": 0,
                    "max": 100,
                    "ok": val is not None,
                    "err": None if val is not None else "WMI parlaklık okunamadı",
                })
    except Exception as exc:
        _log_err("brightness_wmi_powershell", exc)
    return monitors, wmi_keys


def _query_wmi_monitors() -> Tuple[List[Dict[str, Any]], Set[str], Dict[str, str]]:
    """Query internal WMI monitor info, falling back to PowerShell only if COM fails."""
    global _last_ps_query_time
    edid_names = _query_wmi_monitor_ids_com()
    monitors, wmi_keys = _query_wmi_brightness_com()
    if not monitors:
        now = time.monotonic()
        if now - _last_ps_query_time >= _PS_RETRY_INTERVAL_SEC:
            _last_ps_query_time = now
            monitors, wmi_keys = _query_wmi_brightness_powershell()
    return monitors, wmi_keys, edid_names


def _query_ddc_monitors(wmi_keys: Set[str], edid_names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Enumerate external displays via EnumDisplayMonitors and dxva2 DDC/CI."""
    ddc_list: List[Dict[str, Any]] = []

    def enum_callback(h_mon: wintypes.HMONITOR, _hdc: wintypes.HDC, _lprc: Any, _lparam: Any) -> bool:
        try:
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if not user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
                return True

            dev_name = mi.szDevice
            dd = DISPLAY_DEVICEW()
            dd.cbSize = ctypes.sizeof(DISPLAY_DEVICEW)
            user32.EnumDisplayDevicesW(dev_name, 0, ctypes.byref(dd), 0)

            dev_id = dd.DeviceID
            parts = dev_id.split("\\")
            dev_code = parts[1].upper() if len(parts) >= 2 else ""

            # Skip if this display matches the internal WMI laptop screen
            if dev_code and (dev_code in wmi_keys or any(k in dev_id.upper() for k in wmi_keys)):
                return True

            count = wintypes.DWORD()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(h_mon, ctypes.byref(count)) or count.value == 0:
                return True

            arr = (PHYSICAL_MONITOR * count.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(h_mon, count.value, arr):
                return True

            try:
                for i in range(count.value):
                    pm = arr[i]
                    cur_b = wintypes.DWORD()
                    min_b = wintypes.DWORD()
                    max_b = wintypes.DWORD()
                    b_ok = dxva2.GetMonitorBrightness(
                        pm.hPhysicalMonitor,
                        ctypes.byref(min_b),
                        ctypes.byref(cur_b),
                        ctypes.byref(max_b),
                    )

                    # Determine friendly name
                    name = edid_names.get(dev_code)
                    if not name and dev_id.upper() in edid_names:
                        name = edid_names[dev_id.upper()]
                    if not name:
                        desc = str(pm.szPhysicalMonitorDescription).strip()
                        name = desc if desc and desc != "Generic PnP Monitor" else (dd.DeviceString or "Harici ekran")

                    mid = f"ddc:{dev_name}"
                    if b_ok:
                        ddc_list.append({
                            "id": mid,
                            "name": name,
                            "kind": "ddc",
                            "level": int(cur_b.value),
                            "min": int(min_b.value),
                            "max": int(max_b.value),
                            "ok": True,
                            "err": None,
                        })
                    else:
                        ddc_list.append({
                            "id": mid,
                            "name": name,
                            "kind": "ddc",
                            "level": None,
                            "min": 0,
                            "max": 100,
                            "ok": False,
                            "err": "DDC/CI yanıt vermedi",
                        })
            finally:
                dxva2.DestroyPhysicalMonitors(count.value, arr)

        except Exception as cb_exc:
            _log_err("brightness_ddc_enum_cb", cb_exc)
        return True

    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(enum_callback), 0)
    except Exception as exc:
        _log_err("brightness_ddc_enum", exc)

    return ddc_list


def _fast_refresh_levels_locked() -> None:
    """Fast re-read of brightness levels for cached monitors without full re-enumeration."""
    wmi_levels: Dict[str, Optional[int]] = {}
    if _ensure_com():
        try:
            import comtypes.client
            loc = comtypes.client.CreateObject("WbemScripting.SWbemLocator")
            svc = loc.ConnectServer(".", "root\\wmi")
            for item in svc.ExecQuery("SELECT * FROM WmiMonitorBrightness"):
                inst = item.Properties_("InstanceName").Value
                lvl = item.Properties_("CurrentBrightness").Value
                wmi_levels[inst.upper()] = int(lvl) if lvl is not None else None
        except Exception as exc:
            _log_err("brightness_fast_refresh_wmi", exc)

    for m in _cached_monitors:
        kind = m.get("kind")
        mid = m.get("id", "")
        if kind == "wmi":
            target = mid[4:].upper() if mid.startswith("wmi:") else mid.upper()
            val = None
            for inst_k, l in wmi_levels.items():
                if target in inst_k or inst_k in target:
                    val = l
                    break
            if val is not None:
                m["level"] = val
                m["ok"] = True
                m["err"] = None
        elif kind == "ddc":
            target_device = mid[4:] if mid.startswith("ddc:") else mid
            _read_ddc_level_single(m, target_device)


def _read_ddc_level_single(m_dict: Dict[str, Any], target_device: str) -> None:
    """Read DDC brightness for a specific device and update the dict."""
    h_matched: Optional[wintypes.HMONITOR] = None

    def enum_cb(h_mon: wintypes.HMONITOR, _hdc: wintypes.HDC, _lprc: Any, _lparam: Any) -> bool:
        nonlocal h_matched
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            if mi.szDevice == target_device or target_device in mi.szDevice:
                h_matched = h_mon
                return False
        return True

    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(enum_cb), 0)
        if not h_matched:
            return

        count = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(h_matched, ctypes.byref(count)) or count.value == 0:
            return

        arr = (PHYSICAL_MONITOR * count.value)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(h_matched, count.value, arr):
            return

        try:
            for i in range(count.value):
                cur_b = wintypes.DWORD()
                min_b = wintypes.DWORD()
                max_b = wintypes.DWORD()
                if dxva2.GetMonitorBrightness(arr[i].hPhysicalMonitor, ctypes.byref(min_b), ctypes.byref(cur_b), ctypes.byref(max_b)):
                    m_dict["level"] = int(cur_b.value)
                    m_dict["min"] = int(min_b.value)
                    m_dict["max"] = int(max_b.value)
                    m_dict["ok"] = True
                    m_dict["err"] = None
                    break
        finally:
            dxva2.DestroyPhysicalMonitors(count.value, arr)
    except Exception as exc:
        _log_err("brightness_read_ddc_single", exc)


def _update_cached_level(monitor_id: str, level: int) -> None:
    """Update cached level for a monitor upon successful set_level."""
    with _cache_lock:
        for m in _cached_monitors:
            if m.get("id") == monitor_id or monitor_id in m.get("id", ""):
                m["level"] = level
                m["ok"] = True
                m["err"] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_monitors(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Enumerate connected monitors with current brightness levels.

    Results are cached for 30 seconds unless force_refresh is True.
    Returns a list of dicts:
      {
        'id': str,
        'name': str ('Dizüstü ekranı' for internal panel, else EDID name),
        'kind': 'wmi' | 'ddc',
        'level': int (0-100) or None,
        'min': int,
        'max': int,
        'ok': bool,
        'err': str | None
      }
    """
    global _cached_monitors, _last_enum_time

    with _cache_lock:
        now = time.monotonic()
        if not force_refresh and _cached_monitors and (now - _last_enum_time < CACHE_TTL_SEC):
            _fast_refresh_levels_locked()
            return [dict(m) for m in _cached_monitors]

        # Full enumeration
        wmi_monitors, wmi_keys, edid_names = _query_wmi_monitors()
        ddc_monitors = _query_ddc_monitors(wmi_keys, edid_names)

        _cached_monitors = wmi_monitors + ddc_monitors
        _last_enum_time = now
        return [dict(m) for m in _cached_monitors]


def get_levels() -> Dict[str, Optional[int]]:
    """Fast re-read of brightness levels for all known monitors."""
    monitors = list_monitors(force_refresh=False)
    return {str(m.get("id")): m.get("level") for m in monitors}


def set_level(monitor_id: str, level: int) -> bool:
    """Set brightness level (clamped 0-100) for the specified monitor ID.

    Internal laptop panels are updated via WMI; external monitors are updated via DDC/CI.
    Safe to call from worker threads. Never raises, returns True on success, False on failure.
    """
    try:
        level = max(0, min(100, int(round(level))))
    except Exception:
        return False

    if not monitor_id or not isinstance(monitor_id, str):
        return False

    # Check if target is WMI
    is_wmi = monitor_id.startswith("wmi:")
    if not is_wmi:
        with _cache_lock:
            for m in _cached_monitors:
                if m.get("id") == monitor_id and m.get("kind") == "wmi":
                    is_wmi = True
                    break

    if is_wmi:
        return _set_wmi_level(monitor_id, level)

    # Otherwise treat as DDC/CI
    return _set_ddc_level(monitor_id, level)


def _set_wmi_level(monitor_id: str, level: int) -> bool:
    """Set brightness on internal WMI display."""
    global _last_ps_set_time
    target_inst = monitor_id[4:] if monitor_id.startswith("wmi:") else monitor_id

    # 1. Try COM interface
    if _ensure_com():
        try:
            import comtypes.client
            loc = comtypes.client.CreateObject("WbemScripting.SWbemLocator")
            svc = loc.ConnectServer(".", r"root\wmi")
            for item in svc.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods"):
                inst = item.Properties_("InstanceName").Value
                if not target_inst or target_inst.upper() in inst.upper() or inst.upper() in target_inst.upper():
                    meth = item.Methods_("WmiSetBrightness")
                    in_params = meth.InParameters.SpawnInstance_()
                    in_params.Properties_.Item("Timeout").Value = 1
                    in_params.Properties_.Item("Brightness").Value = level
                    item.ExecMethod_("WmiSetBrightness", in_params)
                    _update_cached_level(monitor_id, level)
                    return True
        except Exception as exc:
            _log_err("brightness_set_wmi_com", exc)

    # 2. Fallback to PowerShell CIM with 6-second timeout (rate-limited to max once per 5 min)
    now = time.monotonic()
    if now - _last_ps_set_time >= _PS_RETRY_INTERVAL_SEC:
        _last_ps_set_time = now
        try:
            clean_inst = target_inst.replace("'", "''").replace("\\", "\\\\")
            ps_script = (
                f"$m = Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods | "
                f"Where-Object {{ $_.InstanceName -like '*{clean_inst}*' }} | Select-Object -First 1; "
                f"if ($m) {{ Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Brightness = [byte]{level}; Timeout = [uint32]1}} }} "
                f"else {{ (Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1).WmiSetBrightness(1, {level}) }}"
            )
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                timeout=6.0,
                creationflags=CREATE_NO_WINDOW,
            )
            if proc.returncode == 0:
                _update_cached_level(monitor_id, level)
                return True
        except Exception as exc:
            _log_err("brightness_set_wmi_ps", exc)

    return False


def _set_ddc_level(monitor_id: str, level: int) -> bool:
    """Set brightness on external DDC/CI display."""
    target_device = monitor_id[4:] if monitor_id.startswith("ddc:") else monitor_id
    h_matched: Optional[wintypes.HMONITOR] = None

    def enum_cb(h_mon: wintypes.HMONITOR, _hdc: wintypes.HDC, _lprc: Any, _lparam: Any) -> bool:
        nonlocal h_matched
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            if mi.szDevice == target_device or target_device in mi.szDevice:
                h_matched = h_mon
                return False
        return True

    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(enum_cb), 0)
        if not h_matched:
            return False

        count = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(h_matched, ctypes.byref(count)) or count.value == 0:
            return False

        arr = (PHYSICAL_MONITOR * count.value)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(h_matched, count.value, arr):
            return False

        success = False
        try:
            for i in range(count.value):
                pm = arr[i]
                if dxva2.SetMonitorBrightness(pm.hPhysicalMonitor, wintypes.DWORD(level)):
                    success = True
        finally:
            dxva2.DestroyPhysicalMonitors(count.value, arr)

        if success:
            _update_cached_level(monitor_id, level)
        return success
    except Exception as exc:
        _log_err("brightness_set_ddc", exc)
        return False
