"""bt_devices.py - Bluetooth cihazlarını ve pil durumlarını sorgulama modülü.

Windows cfgmgr32 Win32 API'sini ctypes üzerinden doğrudan çağırarak
eşleştirilmiş Bluetooth / BLE cihazlarını, bağlantı durumlarını ve pil
yüzdelerini hızlıca (<200 ms) sorgular. Subprocess veya PowerShell kullanmaz.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import re
from typing import Any, Dict, List, Optional

__all__ = [
    "list_bt_devices",
    "classify_kind",
    "merge_devices",
    "GUID",
    "DEVPROPKEY",
]

# ---------------------------------------------------------------------------
# Ctypes Cfgmgr32 Tanımları (64-bit güvenli)
# ---------------------------------------------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", GUID),
        ("pid", wintypes.ULONG),
    ]


def _make_key(d1: int, d2: int, d3: int, d4_bytes: list[int], pid: int) -> DEVPROPKEY:
    g = GUID(d1, d2, d3, (wintypes.BYTE * 8)(*d4_bytes))
    return DEVPROPKEY(g, pid)


# DEVPKEY_NAME: {b725f130-47ef-101a-a5f1-02608c9eebac}, 10
KEY_NAME = _make_key(
    0xB725F130, 0x47EF, 0x101A,
    [0xA5, 0xF1, 0x02, 0x60, 0x8C, 0x9E, 0xEB, 0xAC], 10
)

# DEVPKEY_Device_BatteryPercentage: {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
KEY_BAT = _make_key(
    0x104EA319, 0x6EE2, 0x4701,
    [0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5], 2
)

# DEVPKEY_Device_IsConnected: {2bd67d8b-8beb-48d5-87e0-6cda3428040a}, 11
KEY_CONN = _make_key(
    0x2BD67D8B, 0x8BEB, 0x48D5,
    [0x87, 0xE0, 0x6C, 0xDA, 0x34, 0x28, 0x04, 0x0A], 11
)

_cfg: Optional[ctypes.WinDLL] = None


def _get_cfgmgr32() -> Optional[ctypes.WinDLL]:
    global _cfg
    if _cfg is not None:
        return _cfg
    try:
        cfg = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        # Argtypes / restype bildirimleri
        cfg.CM_Get_Device_ID_List_SizeW.restype = wintypes.DWORD
        cfg.CM_Get_Device_ID_List_SizeW.argtypes = [
            ctypes.POINTER(wintypes.ULONG),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]

        cfg.CM_Get_Device_ID_ListW.restype = wintypes.DWORD
        cfg.CM_Get_Device_ID_ListW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.ULONG,
            wintypes.ULONG,
        ]

        cfg.CM_Locate_DevNodeW.restype = wintypes.DWORD
        cfg.CM_Locate_DevNodeW.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]

        cfg.CM_Get_DevNode_PropertyW.restype = wintypes.DWORD
        cfg.CM_Get_DevNode_PropertyW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(DEVPROPKEY),
            ctypes.POINTER(wintypes.ULONG),
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.ULONG,
        ]
        _cfg = cfg
        return _cfg
    except Exception as exc:
        try:
            import sources
            sources.log_err("bt_devices_init", exc)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Sınıflandırma ve Birleştirme Mantığı
# ---------------------------------------------------------------------------

_MAC_RE = re.compile(r"dev_([0-9a-fA-F]{12})", re.IGNORECASE)


def classify_kind(name: str) -> str:
    """Cihaz adına göre tür sınıflandırması yapar:

    'phone': iPhone / Android / Galaxy / Pixel
    'watch': WATCH / Band / Watch
    'headset': AirPods / Buds / Headphone / WH- / WF-
    'device': Diğer tüm aygıtlar
    """
    if not name:
        return "device"
    low = name.lower()
    for kw in ("iphone", "android", "galaxy", "pixel"):
        if kw in low:
            return "phone"
    for kw in ("watch", "band"):
        if kw in low:
            return "watch"
    for kw in ("airpods", "buds", "headphone", "wh-", "wf-"):
        if kw in low:
            return "headset"
    return "device"


def merge_devices(raw_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aynı fiziksel cihaza ait farklı kayıtları (BLE ve BTHENUM gibi) birleştirir.

    Aynı MAC sonekine veya aynı isme sahip cihazlar tek kayıtta toplanır:
    - connected: herhangi biri bağlıysa True
    - battery: ilk None olmayan değer (uydurma sayı girilmez)
    - name: aygıt kimliği olmayan en uygun görünen ad
    - kind: classify_kind(name)
    """
    n = len(raw_entries)
    if n == 0:
        return []

    parent = list(range(n))

    def find(i: int) -> int:
        path: list[int] = []
        curr = i
        while parent[curr] != curr:
            path.append(curr)
            curr = parent[curr]
        for node in path:
            parent[node] = curr
        return curr

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for i in range(n):
        for j in range(i + 1, n):
            e1 = raw_entries[i]
            e2 = raw_entries[j]
            same_mac = bool(e1.get("mac") and e1.get("mac") == e2.get("mac"))
            name1 = (e1.get("name") or "").strip().lower()
            name2 = (e2.get("name") or "").strip().lower()
            same_name = bool(name1 and name1 == name2)
            if same_mac or same_name:
                union(i, j)

    groups: dict[int, list[dict[str, Any]]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(raw_entries[i])

    merged: list[dict[str, Any]] = []
    for items in groups.values():
        clean_names = [
            item["name"].strip()
            for item in items
            if item.get("name")
            and not item["name"].strip().upper().startswith(("BTHENUM", "BTHLE", "DEV_"))
        ]
        name = clean_names[0] if clean_names else (items[0].get("name") or "Bilinmeyen Cihaz").strip()

        battery = next((item["battery"] for item in items if item.get("battery") is not None), None)
        connected = any(bool(item.get("connected")) for item in items)
        kind = classify_kind(name)

        merged.append({
            "name": name,
            "battery": battery,
            "connected": connected,
            "kind": kind,
        })

    return merged


# ---------------------------------------------------------------------------
# Ana Sorgulama Fonksiyonu
# ---------------------------------------------------------------------------

def list_bt_devices(only_connected: bool = True) -> list[dict[str, Any]]:
    """Eşleştirilmiş Bluetooth / BLE cihazlarını listeler.

    Döndürülen liste elemanları:
      {"name": str, "battery": int | None, "connected": bool, "kind": str}

    Sıralama: Önce pili olan bağlı cihazlar, ardından diğer bağlı cihazlar.
    Hata durumunda asla istisna fırlatmaz, [] döner ve sources.log_err'e yazar.
    """
    try:
        cfg = _get_cfgmgr32()
        if cfg is None:
            return []

        ul_len = wintypes.ULONG(0)
        ret = cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(ul_len), None, 0)
        if ret != 0 or ul_len.value <= 1:
            return []

        buf = (wintypes.WCHAR * ul_len.value)()
        ret = cfg.CM_Get_Device_ID_ListW(None, buf, ul_len.value, 0)
        if ret != 0:
            return []

        all_devs = [d for d in ctypes.wstring_at(buf, ul_len.value).split("\0") if d]
        # Yalnızca BTHENUM\Dev_ veya BTHLE\Dev_ ile başlayan gerçek cihaz kimlikleri (profil düğümleri hariç)
        bt_devs = [
            d for d in all_devs
            if d.upper().startswith(("BTHENUM\\DEV_", "BTHLE\\DEV_"))
        ]

        raw_entries: list[dict[str, Any]] = []
        for dev_id in bt_devs:
            devinst = wintypes.DWORD(0)
            # 1 = CM_LOCATE_DEVNODE_PHANTOM (çevrimdışı/hayalet cihazlar dahil aranır)
            if cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), dev_id, 1) != 0:
                continue

            ptype = wintypes.ULONG(0)
            psize = wintypes.ULONG(512)
            pbuf = (wintypes.BYTE * 512)()
            name = dev_id
            if cfg.CM_Get_DevNode_PropertyW(
                devinst, ctypes.byref(KEY_NAME), ctypes.byref(ptype),
                ctypes.byref(pbuf), ctypes.byref(psize), 0
            ) == 0:
                name = ctypes.wstring_at(pbuf).strip()

            psize = wintypes.ULONG(16)
            bat: Optional[int] = None
            if cfg.CM_Get_DevNode_PropertyW(
                devinst, ctypes.byref(KEY_BAT), ctypes.byref(ptype),
                ctypes.byref(pbuf), ctypes.byref(psize), 0
            ) == 0:
                val = int(pbuf[0])
                if 0 <= val <= 100:
                    bat = val

            psize = wintypes.ULONG(16)
            conn = False
            if cfg.CM_Get_DevNode_PropertyW(
                devinst, ctypes.byref(KEY_CONN), ctypes.byref(ptype),
                ctypes.byref(pbuf), ctypes.byref(psize), 0
            ) == 0:
                conn = bool(pbuf[0])

            m = _MAC_RE.search(dev_id)
            mac = m.group(1).lower() if m else None

            raw_entries.append({
                "id": dev_id,
                "name": name,
                "battery": bat,
                "connected": conn,
                "mac": mac,
            })

        merged = merge_devices(raw_entries)

        if only_connected:
            filtered = [d for d in merged if d["connected"]]
            return sorted(
                filtered,
                key=lambda d: (0 if d["battery"] is not None else 1, d["name"].lower())
            )

        return sorted(
            merged,
            key=lambda d: (
                0 if (d["connected"] and d["battery"] is not None) else (1 if d["connected"] else 2),
                d["name"].lower()
            )
        )

    except Exception as exc:
        try:
            import sources
            sources.log_err("bt_devices", exc)
        except Exception:
            pass
        return []
