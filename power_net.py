"""power_net.py - Background data and control layer for Şerit dock battery & connectivity panel.

Provides:
  - battery_info: battery percent, charging state, remaining time, power rate (W), and capacity health.
  - wifi_info: Wi-Fi adapter availability, radio state, connection status, SSID, and signal %.
  - parse_netsh_wlan_interfaces: pure parser for `netsh wlan show interfaces` output (EN/TR).
  - bluetooth_info: Bluetooth adapter availability, radio state, and connected device count.
  - radio_toggle_supported: reports whether WinRT Windows.Devices.Radios projection is available.
  - set_wifi / set_bluetooth: guarded radio state toggles via WinRT Radios API.
  - open_settings: guarded launcher for Windows Settings pages ('wifi', 'bluetooth', 'battery', 'power').

Rules:
  - All functions are designed to be called from BACKGROUND worker threads (never the GUI thread).
  - CoInitializeEx(0x2) is ensured per worker thread before any COM/WMI call.
  - Read functions never raise unhandled exceptions and complete within ~1 second.
  - Mutating/UI-opening functions (set_wifi, set_bluetooth, open_settings) raise RuntimeError
    under tests unless explicitly allowed via SERIT_ALLOW_REAL_POWER_NET=1.
"""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import datetime
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, Optional, Tuple

import comtypes
import comtypes.client
import psutil

from logpath import LOG_PATH, is_running_under_test

__all__ = [
    "battery_info",
    "wifi_info",
    "parse_netsh_wlan_interfaces",
    "bluetooth_info",
    "radio_toggle_supported",
    "set_wifi",
    "set_bluetooth",
    "open_settings",
]

# ==============================================================================
# 0. CONSTANTS, LOGGING, TEST GUARD & COM INITIALIZATION
# ==============================================================================

CREATE_NO_WINDOW: int = 0x08000000
COINIT_APARTMENTTHREADED: int = 0x2
CAPACITY_CACHE_TTL_SEC: float = 600.0  # 10 minutes
BLUETOOTH_CLASS_GUID: str = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
CM_GETIDLIST_FILTER_SERVICE: int = 0x00000002
CM_GETIDLIST_FILTER_CLASS: int = 0x00000200
CM_GETIDLIST_FILTER_PRESENT: int = 0x00000100
DN_STARTED: int = 0x00000008

SETTINGS_URIS: Dict[str, str] = {
    "wifi": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth",
    "battery": "ms-settings:batterysaver",
    "power": "ms-settings:powersleep",
}

_last_log_msg: str = ""
_last_log_time: float = 0.0
_log_lock = threading.Lock()


def _log(msg: str) -> None:
    """Append a timestamped message to LOG_PATH with 60s duplicate throttle."""
    global _last_log_msg, _last_log_time
    now = time.monotonic()
    with _log_lock:
        if msg == _last_log_msg and (now - _last_log_time) < 60.0:
            return
        _last_log_msg = msg
        _last_log_time = now
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now_str} [power_net] {msg}\n")
    except OSError:
        pass


def _guard_real_power_net(what: str) -> None:
    """Testler gerçek radyolara veya Windows Ayarları pencerelerine ASLA dokunamaz.

    Test altında (pytest veya tests/ klasöründen çalışan betik) gerçek radyo/ayar işlemi engellenir;
    yalnızca SERIT_ALLOW_REAL_POWER_NET=1 açıkça verilirse izin var.
    """
    try:
        under_test = is_running_under_test()
    except Exception:
        return
    if under_test and os.environ.get("SERIT_ALLOW_REAL_POWER_NET") != "1":
        raise RuntimeError(f"Test sırasında gerçek radyo/ayar işlemi yapılamaz: {what}")


_tls = threading.local()


def _ensure_com_initialized() -> bool:
    """Initialize COM on the calling worker thread once (safe for thread pool reuse)."""
    if getattr(_tls, "com_initialized", False):
        return True
    try:
        hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        if hr in (0, 1) or (hr & 0xFFFFFFFF) == 0x80010106:
            _tls.com_initialized = True
            return True
    except Exception:
        pass
    try:
        comtypes.CoInitialize()
        _tls.com_initialized = True
        return True
    except Exception as exc:
        _log(f"COM başlatılamadı: {exc}")
        return False


def _get_wmi_service(namespace: str = r"root\wmi"):
    """Get or create a thread-local WMI connection for the given namespace."""
    if not _ensure_com_initialized():
        return None
    conns: Optional[Dict[str, Any]] = getattr(_tls, "wmi_conns", None)
    if conns is None:
        conns = {}
        _tls.wmi_conns = conns
    key = namespace.lower()
    if key in conns:
        return conns[key]
    try:
        loc = comtypes.client.CreateObject("WbemScripting.SWbemLocator")
        svc = loc.ConnectServer(".", namespace)
        conns[key] = svc
        return svc
    except Exception as exc:
        _log(f"WMI bağlantısı kurulamadı ({namespace}): {exc}")
        return None


# ==============================================================================
# 1. OPTIONAL WINRT RADIOS PROJECTION DETECTION
# ==============================================================================

try:
    from winrt.windows.devices.radios import (  # type: ignore
        Radio as _WinrtRadio,
        RadioAccessStatus as _WinrtRadioAccessStatus,
        RadioKind as _WinrtRadioKind,
        RadioState as _WinrtRadioState,
    )
    _HAS_WINRT_RADIOS = True
except ImportError:
    _WinrtRadio = None
    _WinrtRadioAccessStatus = None
    _WinrtRadioKind = None
    _WinrtRadioState = None
    _HAS_WINRT_RADIOS = False


def radio_toggle_supported() -> Dict[str, Any]:
    """Return whether Wi-Fi and Bluetooth radio toggling is supported via WinRT.

    Returns:
      {'wifi': bool, 'bluetooth': bool, 'reason': str} (Turkish user-facing reason).
    """
    if _HAS_WINRT_RADIOS and _WinrtRadio is not None:
        return {
            "wifi": True,
            "bluetooth": True,
            "reason": "WinRT Windows.Devices.Radios kullanımda",
        }
    return {
        "wifi": False,
        "bluetooth": False,
        "reason": "winrt-Windows.Devices.Radios paketi yüklü değil",
    }


def _run_winrt_coro(coro: Any, timeout: float = 0.9) -> Tuple[bool, Any]:
    """Run an async WinRT coroutine in a bounded daemon thread."""
    box: Dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["res"] = asyncio.run(coro)
        except Exception as exc:
            box["err"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        _log("WinRT radyo işlemi zaman aşımına uğradı")
        return False, None
    if "err" in box:
        _log(f"WinRT radyo hatası: {box['err']}")
        return False, None
    return True, box.get("res")


# ==============================================================================
# 2. BATTERY INFO
# ==============================================================================

_cap_lock = threading.Lock()
_cached_design_mwh: Optional[int] = None
_cached_full_mwh: Optional[int] = None
_cached_cap_time: float = 0.0


def _compute_capacity_pct(full_mwh: Optional[int], design_mwh: Optional[int]) -> Optional[int]:
    """Compute battery health percentage (full / design * 100) safely."""
    if (
        full_mwh is None
        or design_mwh is None
        or not isinstance(full_mwh, (int, float))
        or not isinstance(design_mwh, (int, float))
        or design_mwh <= 0
        or full_mwh <= 0
    ):
        return None
    pct = int(round((float(full_mwh) / float(design_mwh)) * 100.0))
    return max(0, min(200, pct))


def _read_wmi_battery_capacities() -> Tuple[Optional[int], Optional[int]]:
    """Read (full_mwh, design_mwh) from WMI root\\wmi with a 10-minute cache."""
    global _cached_design_mwh, _cached_full_mwh, _cached_cap_time
    now = time.monotonic()
    with _cap_lock:
        if (
            _cached_cap_time > 0.0
            and (now - _cached_cap_time) < CAPACITY_CACHE_TTL_SEC
            and (_cached_design_mwh is not None or _cached_full_mwh is not None)
        ):
            return _cached_full_mwh, _cached_design_mwh

    svc = _get_wmi_service(r"root\wmi")
    if svc is None:
        with _cap_lock:
            return _cached_full_mwh, _cached_design_mwh

    design_total = 0
    design_found = False
    full_total = 0
    full_found = False

    try:
        for item in svc.ExecQuery("SELECT DesignedCapacity FROM BatteryStaticData"):
            try:
                val = item.Properties_("DesignedCapacity").Value
                if val is not None and int(val) > 0:
                    design_total += int(val)
                    design_found = True
            except Exception:
                continue
    except Exception as exc:
        _log(f"BatteryStaticData okunamadı: {exc}")
        if getattr(_tls, "wmi_conns", None):
            _tls.wmi_conns.pop(r"root\wmi", None)

    try:
        for item in svc.ExecQuery("SELECT FullChargedCapacity FROM BatteryFullChargedCapacity"):
            try:
                val = item.Properties_("FullChargedCapacity").Value
                if val is not None and int(val) > 0:
                    full_total += int(val)
                    full_found = True
            except Exception:
                continue
    except Exception as exc:
        _log(f"BatteryFullChargedCapacity okunamadı: {exc}")

    design_val = design_total if design_found else None
    full_val = full_total if full_found else None

    with _cap_lock:
        if design_val is not None or full_val is not None:
            _cached_design_mwh = design_val
            _cached_full_mwh = full_val
            _cached_cap_time = now
        return _cached_full_mwh, _cached_design_mwh


def _read_wmi_battery_status() -> Tuple[Optional[bool], Optional[bool], Optional[float], bool]:
    """Read (power_online, charging, rate_w, found_any) from WMI root\\wmi BatteryStatus."""
    svc = _get_wmi_service(r"root\wmi")
    if svc is None:
        return None, None, None, False

    power_online: Optional[bool] = None
    charging: Optional[bool] = None
    total_rate_mw: int = 0
    rate_found: bool = False
    found_any: bool = False

    try:
        query = "SELECT PowerOnline, Discharging, Charging, DischargeRate, ChargeRate FROM BatteryStatus"
        for item in svc.ExecQuery(query):
            found_any = True
            try:
                po = item.Properties_("PowerOnline").Value
                if po is not None:
                    power_online = bool(po)
            except Exception:
                pass
            try:
                ch = item.Properties_("Charging").Value
                if ch is not None:
                    charging = bool(ch)
            except Exception:
                pass
            try:
                dr = item.Properties_("DischargeRate").Value
                cr = item.Properties_("ChargeRate").Value
                dr_int = int(dr) if dr is not None else 0
                cr_int = int(cr) if cr is not None else 0
                # Filter out invalid/overflow WMI uint32 sentinel values (e.g. 0x80000000 / > 500W)
                if 0 < dr_int < 500_000:
                    total_rate_mw += dr_int
                    rate_found = True
                elif 0 < cr_int < 500_000:
                    total_rate_mw += cr_int
                    rate_found = True
                elif dr_int == 0 and cr_int == 0:
                    rate_found = True
            except Exception:
                pass
    except Exception as exc:
        _log(f"BatteryStatus okunamadı: {exc}")
        if getattr(_tls, "wmi_conns", None):
            _tls.wmi_conns.pop(r"root\wmi", None)

    rate_w: Optional[float] = round(total_rate_mw / 1000.0, 2) if rate_found else None
    return power_online, charging, rate_w, found_any


def battery_info() -> Dict[str, Any]:
    """Return battery status, discharge/charge power in watts, and capacity metrics.

    Returns:
      {
        'present': bool,
        'percent': int | None,
        'plugged': bool | None,
        'charging': bool | None,
        'secs_left': int | None,
        'rate_w': float | None,
        'full_mwh': int | None,
        'design_mwh': int | None,
        'capacity_pct': int | None,
        'source': 'Windows',
      }
    """
    result: Dict[str, Any] = {
        "present": False,
        "percent": None,
        "plugged": None,
        "charging": None,
        "secs_left": None,
        "rate_w": None,
        "full_mwh": None,
        "design_mwh": None,
        "capacity_pct": None,
        "source": "Windows",
    }
    try:
        sb = psutil.sensors_battery()
    except Exception as exc:
        _log(f"psutil.sensors_battery hatası: {exc}")
        sb = None

    wmi_plugged, wmi_charging, rate_w, wmi_found = _read_wmi_battery_status()

    if sb is None and not wmi_found:
        return result

    result["present"] = True

    if sb is not None:
        try:
            if sb.percent is not None:
                result["percent"] = max(0, min(100, int(round(float(sb.percent)))))
        except Exception:
            pass
        if isinstance(sb.power_plugged, bool):
            result["plugged"] = sb.power_plugged
        try:
            secs = sb.secsleft
            if (
                isinstance(secs, int)
                and secs > 0
                and secs not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED)
                and secs < 86400 * 7
            ):
                result["secs_left"] = int(secs)
        except Exception:
            pass

    if result["plugged"] is None and wmi_plugged is not None:
        result["plugged"] = wmi_plugged

    if wmi_charging is not None:
        result["charging"] = wmi_charging
    elif result["plugged"] is False:
        result["charging"] = False

    result["rate_w"] = rate_w

    full_mwh, design_mwh = _read_wmi_battery_capacities()
    result["full_mwh"] = full_mwh
    result["design_mwh"] = design_mwh
    result["capacity_pct"] = _compute_capacity_pct(full_mwh, design_mwh)

    return result


# ==============================================================================
# 3. WI-FI INFO & NETSH PARSER
# ==============================================================================

_NO_INTERFACE_PATTERNS = (
    "there is no wireless interface on the system",
    "sistemde kablosuz arabirim yok",
    "kablosuz yerel ağ hizmeti çalışmıyor",
    "the wireless autoconfig service (wlansvc) is not running",
)

_FIELD_STATE_KEYS = {
    "state",
    "durum",
}
_FIELD_SSID_KEYS = {
    "ssid",
}
_FIELD_SIGNAL_KEYS = {
    "signal",
    "sinyal",
}
_FIELD_RADIO_STATUS_KEYS = {
    "radio status",
    "radyo durumu",
    "software",
    "yazılım",
    "hardware",
    "donanım",
}
_FIELD_NAME_KEYS = {
    "name",
    "ad",
    "isim",
    "description",
    "açıklama",
    "aciklama",
    "guid",
}


def parse_netsh_wlan_interfaces(text: str) -> Dict[str, Any]:
    """Pure parser for `netsh wlan show interfaces` output (English and Turkish).

    Returns:
      {'available': bool, 'on': bool | None, 'connected': bool, 'ssid': str | None, 'signal': int | None}
    """
    res: Dict[str, Any] = {
        "available": False,
        "on": None,
        "connected": False,
        "ssid": None,
        "signal": None,
    }
    if not text or not isinstance(text, str):
        return res

    lowered_all = text.lower()
    for pat in _NO_INTERFACE_PATTERNS:
        if pat in lowered_all:
            return res

    has_interface = False
    state_val: Optional[str] = None
    ssid_val: Optional[str] = None
    signal_val: Optional[int] = None
    radio_off_seen = False
    radio_on_seen = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            low_line = line.lower()
            if any(
                off_w in low_line
                for off_w in ("hardware off", "software off", "donanım kapalı", "donanim kapali", "yazılım kapalı", "yazilim kapali")
            ):
                radio_off_seen = True
            elif any(
                on_w in low_line
                for on_w in ("hardware on", "software on", "donanım açık", "donanim acik", "yazılım açık", "yazilim acik")
            ):
                radio_on_seen = True
            continue
        key_raw, val_raw = line.split(":", 1)
        key = key_raw.strip().lower()
        val = val_raw.strip()
        val_low = val.lower()

        if key in _FIELD_NAME_KEYS and val:
            has_interface = True

        elif key in _FIELD_STATE_KEYS:
            has_interface = True
            state_val = val_low

        elif key in _FIELD_SSID_KEYS or re.fullmatch(r"ssid", key):
            # Ignore BSSID / AP BSSID lines because key == 'ssid' only matches exact SSID
            if val:
                ssid_val = val

        elif key in _FIELD_SIGNAL_KEYS:
            m = re.search(r"(\d+)\s*%", val)
            if m:
                pct = int(m.group(1))
                signal_val = max(0, min(100, pct))

        elif key in _FIELD_RADIO_STATUS_KEYS or "radio" in key or "radyo" in key:
            if any(off_w in val_low for off_w in ("hardware off", "software off", "kapalı", "kapali", "devre dışı", "devre disi", "off")):
                radio_off_seen = True
            elif any(on_w in val_low for on_w in ("hardware on", "software on", "açık", "acik", "etkin", "on")):
                radio_on_seen = True

    if not has_interface:
        return res

    res["available"] = True

    if state_val is not None:
        # Check disconnected BEFORE connected because 'disconnected' contains 'connected'
        is_disconnected = any(
            w in state_val
            for w in (
                "disconnected",
                "bağlantı kesildi",
                "baglanti kesildi",
                "bağlı değil",
                "bagli degil",
                "kesildi",
                "associating",
                "authenticating",
                "disconnecting",
            )
        )
        is_connected = (not is_disconnected) and any(
            w in state_val
            for w in (
                "connected",
                "bağlandı",
                "baglandi",
                "bağlı",
                "bagli",
            )
        )
        if is_connected:
            res["connected"] = True
            res["on"] = True
            res["ssid"] = ssid_val
            res["signal"] = signal_val
        else:
            res["connected"] = False
            res["ssid"] = None
            res["signal"] = None
            if radio_off_seen:
                res["on"] = False
            elif radio_on_seen:
                res["on"] = True
            else:
                res["on"] = None
    else:
        if radio_off_seen:
            res["on"] = False
        elif radio_on_seen:
            res["on"] = True

    return res


def _decode_oem_bytes(raw: bytes) -> str:
    """Safely decode subprocess bytes using console/OEM code page with UTF-8 fallback."""
    if not raw:
        return ""
    encodings = []
    try:
        cp_out = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp_out:
            encodings.append(f"cp{cp_out}")
    except Exception:
        pass
    try:
        cp_oem = ctypes.windll.kernel32.GetOEMCP()
        if cp_oem:
            enc = f"cp{cp_oem}"
            if enc not in encodings:
                encodings.append(enc)
    except Exception:
        pass
    for fallback in ("utf-8", "cp857", "cp1254", "cp437"):
        if fallback not in encodings:
            encodings.append(fallback)

    for enc in encodings:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def wifi_info() -> Dict[str, Any]:
    """Read current Wi-Fi status without admin privileges via `netsh wlan show interfaces`.

    Returns:
      {'available': bool, 'on': bool | None, 'connected': bool, 'ssid': str | None, 'signal': int | None}
    """
    default: Dict[str, Any] = {
        "available": False,
        "on": None,
        "connected": False,
        "ssid": None,
        "signal": None,
    }
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=2.0,
            creationflags=CREATE_NO_WINDOW,
        )
        text = _decode_oem_bytes(proc.stdout or b"")
        if not text.strip() and proc.stderr:
            text = _decode_oem_bytes(proc.stderr)
        return parse_netsh_wlan_interfaces(text)
    except subprocess.TimeoutExpired:
        _log("wifi_info: netsh wlan show interfaces zaman aşımı (2 sn)")
        return default
    except Exception as exc:
        _log(f"wifi_info hatası: {exc}")
        return default


# ==============================================================================
# 4. BLUETOOTH INFO
# ==============================================================================

_cfgmgr32 = None


def _get_cfgmgr32():
    """Lazy-bind cfgmgr32.dll functions for fast, sub-millisecond PnP queries."""
    global _cfgmgr32
    if _cfgmgr32 is None:
        dll = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        dll.CM_Get_Device_ID_List_SizeW.argtypes = [
            ctypes.POINTER(wintypes.ULONG),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]
        dll.CM_Get_Device_ID_List_SizeW.restype = wintypes.DWORD
        dll.CM_Get_Device_ID_ListW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.ULONG,
            wintypes.ULONG,
        ]
        dll.CM_Get_Device_ID_ListW.restype = wintypes.DWORD
        dll.CM_Locate_DevNodeW.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]
        dll.CM_Locate_DevNodeW.restype = wintypes.DWORD
        dll.CM_Get_DevNode_Status.argtypes = [
            ctypes.POINTER(wintypes.ULONG),
            ctypes.POINTER(wintypes.ULONG),
            wintypes.DWORD,
            wintypes.ULONG,
        ]
        dll.CM_Get_DevNode_Status.restype = wintypes.DWORD
        _cfgmgr32 = dll
    return _cfgmgr32


def _bluetooth_info_winrt() -> Optional[Dict[str, Any]]:
    """Query Bluetooth state via WinRT Windows.Devices.Radios if available."""
    if not _HAS_WINRT_RADIOS or _WinrtRadio is None or _WinrtRadioKind is None or _WinrtRadioState is None:
        return None

    async def _query() -> Dict[str, Any]:
        radios = await _WinrtRadio.get_radios_async()
        bt_radios = [r for r in radios if r.kind == _WinrtRadioKind.BLUETOOTH]
        if not bt_radios:
            return {"available": False, "on": None, "connected_count": None}
        is_on = any(r.state == _WinrtRadioState.ON for r in bt_radios)
        return {"available": True, "on": is_on, "connected_count": None}

    ok, data = _run_winrt_coro(_query(), timeout=0.9)
    if ok and isinstance(data, dict):
        return data
    return None


def _bluetooth_pnp_available() -> bool:
    """Fast PnP check via cfgmgr32 (with WMI fallback) for present Bluetooth radio hardware."""
    try:
        cfg = _get_cfgmgr32()
        flags = CM_GETIDLIST_FILTER_CLASS | CM_GETIDLIST_FILTER_PRESENT
        ul_len = wintypes.ULONG(0)
        cr = cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(ul_len), BLUETOOTH_CLASS_GUID, flags)
        if cr == 0 and ul_len.value > 1:
            buf = (wintypes.WCHAR * ul_len.value)()
            if cfg.CM_Get_Device_ID_ListW(BLUETOOTH_CLASS_GUID, buf, ul_len.value, flags) == 0:
                raw = ctypes.wstring_at(buf, ul_len.value)
                devs = [d for d in raw.split("\0") if d]
                for d in devs:
                    devinst = wintypes.DWORD(0)
                    if cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), d, 0) == 0:
                        status = wintypes.ULONG(0)
                        problem = wintypes.ULONG(0)
                        if cfg.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), devinst, 0) == 0:
                            if (status.value & DN_STARTED) and problem.value == 0:
                                return True
                if devs:
                    return True
    except Exception as exc:
        _log(f"cfgmgr32 Bluetooth sorgusu hatası: {exc}")

    # Fallback to WMI root\cimv2 if cfgmgr32 found nothing
    try:
        svc = _get_wmi_service(r"root\cimv2")
        if svc is not None:
            for _ in svc.ExecQuery("SELECT DeviceID FROM Win32_PnPEntity WHERE PNPClass = 'Bluetooth'"):
                return True
    except Exception as exc:
        _log(f"WMI Bluetooth sorgusu hatası: {exc}")

    return False


def bluetooth_info() -> Dict[str, Any]:
    """Return Bluetooth availability, radio state ('on' is None when unknown), and connected count.

    Prefers WinRT Windows.Devices.Radios when installed; otherwise falls back to a fast
    read-only PnP/WMI check and leaves 'on' and 'connected_count' as None (never guesses).
    """
    winrt_res = _bluetooth_info_winrt()
    if winrt_res is not None:
        return winrt_res

    avail = _bluetooth_pnp_available()
    return {
        "available": avail,
        "on": None,
        "connected_count": None,
    }


# ==============================================================================
# 5. GUARDED RADIO TOGGLES & SETTINGS LAUNCHER
# ==============================================================================

def _set_radio_state_winrt(kind_attr: str, on: bool) -> bool:
    """Toggle a radio kind ('WI_FI' or 'BLUETOOTH') via WinRT Windows.Devices.Radios."""
    if (
        not _HAS_WINRT_RADIOS
        or _WinrtRadio is None
        or _WinrtRadioKind is None
        or _WinrtRadioState is None
        or _WinrtRadioAccessStatus is None
    ):
        return False

    target_kind = getattr(_WinrtRadioKind, kind_attr, None)
    if target_kind is None:
        return False

    target_state = _WinrtRadioState.ON if on else _WinrtRadioState.OFF

    async def _toggle() -> bool:
        access = await _WinrtRadio.request_access_async()
        if access != _WinrtRadioAccessStatus.ALLOWED:
            return False
        radios = await _WinrtRadio.get_radios_async()
        matched = [r for r in radios if r.kind == target_kind]
        if not matched:
            return False
        success = False
        for r in matched:
            res = await r.set_state_async(target_state)
            if res == _WinrtRadioAccessStatus.ALLOWED:
                success = True
        return success

    ok, res = _run_winrt_coro(_toggle(), timeout=0.95)
    return bool(ok and res)


def set_wifi(on: bool) -> bool:
    """Turn Wi-Fi radio on or off via WinRT Radios API when supported; else return False.

    Raises RuntimeError when running under tests.
    """
    _guard_real_power_net(f"set_wifi({on})")
    try:
        return _set_radio_state_winrt("WI_FI", bool(on))
    except Exception as exc:
        _log(f"set_wifi hatası: {exc}")
        return False


def set_bluetooth(on: bool) -> bool:
    """Turn Bluetooth radio on or off via WinRT Radios API when supported; else return False.

    Raises RuntimeError when running under tests.
    """
    _guard_real_power_net(f"set_bluetooth({on})")
    try:
        return _set_radio_state_winrt("BLUETOOTH", bool(on))
    except Exception as exc:
        _log(f"set_bluetooth hatası: {exc}")
        return False


def open_settings(page: str) -> bool:
    """Open a Windows Settings page ('wifi', 'bluetooth', 'battery', 'power') via os.startfile.

    Raises RuntimeError when running under tests.
    """
    _guard_real_power_net(f"open_settings({page!r})")
    if not isinstance(page, str):
        return False
    uri = SETTINGS_URIS.get(page.strip().lower())
    if not uri:
        _log(f"open_settings: bilinmeyen sayfa '{page}'")
        return False
    try:
        os.startfile(uri)
        return True
    except Exception as exc:
        _log(f"open_settings({page!r}) hatası: {exc}")
        return False
