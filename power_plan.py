"""power_plan.py - Windows güç planlarını listeleme ve değiştirme modülü.

Windows `powercfg` komutu üzerinden sistemdeki mevcut güç düzenlerini listeler
ve plan değişimini yönetir.

Kurallar:
- Okuma fonksiyonları (list_plans) asla istisna fırlatmaz.
- Değiştirme fonksiyonu (set_plan) test ortamında çağrıldığında
  `SERIT_ALLOW_REAL_POWER_PLAN=1` ortam değişkeni açıkça verilmedikçe
  RuntimeError fırlatarak gerçek sistem güç planının bozulmasını engeller.
- set_plan çağrılmadan önce GUID regex ve list_plans kontrolü yapılır.
- Tüm subprocess çağrıları CREATE_NO_WINDOW (0x08000000) bayrağıyla penceresiz yürütülür.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from logpath import is_running_under_test

__all__ = [
    "list_plans",
    "set_plan",
    "parse_powercfg_list",
    "CREATE_NO_WINDOW",
    "GUID_RE",
]

CREATE_NO_WINDOW: int = 0x08000000

# GUID doğrulama deseni: 36 karakter (8-4-4-4-12 hex formatı)
GUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

# powercfg /list çıktı satırlarını yakalama deseni (İngilizce ve Türkçe uyumlu)
# Örn:
# Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
# Power Scheme GUID: 5da85d85-eb0c-4710-a805-6da8bbcf1f02  (Office) *
# Güç Düzeni GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Dengeli) *
_LINE_RE = re.compile(
    r"(?:GUID|guid)[:\s]+([0-9a-fA-F-]{36})\s*\((.+)\)\s*(\*?)\s*$",
    re.IGNORECASE,
)


def _guard_real_power_plan(what: str) -> None:
    """Testler sırasında gerçek güç planının değiştirilmesini engeller.

    Yalnızca SERIT_ALLOW_REAL_POWER_PLAN=1 ortam değişkeni tanımlıysa izin verilir.
    """
    try:
        under_test = is_running_under_test()
    except Exception:
        return
    if under_test and os.environ.get("SERIT_ALLOW_REAL_POWER_PLAN") != "1":
        raise RuntimeError(f"Test sırasında gerçek güç planı değiştirilemez: {what}")


def parse_powercfg_list(text: str) -> list[dict[str, Any]]:
    """'powercfg /list' konsol çıktısını çözümler.

    Döndürülen liste:
      [{"guid": str, "name": str, "active": bool}, ...]
    İngilizce ve Türkçe konsol metinleriyle uyumludur.
    """
    plans: list[dict[str, Any]] = []
    if not text:
        return plans

    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = _LINE_RE.search(line)
        if m:
            guid = m.group(1).lower()
            name = m.group(2).strip()
            active = bool(m.group(3) and "*" in m.group(3))
            plans.append({
                "guid": guid,
                "name": name,
                "active": active,
            })
    return plans


def _decode_console_output(raw_bytes: bytes) -> str:
    """Windows konsol çıktısını uygun karakter kodlamasıyla metne dönüştürür.

    powercfg çıktısı OEM kod sayfasıyla (TR Windows'ta cp857) gelir; önce konsol
    kod sayfasını dener, UTF-8'i son çare olarak kullanır (UTF-8-first decode
    cp857 baytlarını 'başarılı ama yanlış' olarak kabul edip plan adlarını bozar).
    """
    if not raw_bytes:
        return ""
    encodings: list[str] = []
    try:
        import ctypes as _ctypes
        cp_out = _ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp_out:
            encodings.append(f"cp{cp_out}")
    except Exception:
        pass
    try:
        import ctypes as _ctypes
        cp_oem = _ctypes.windll.kernel32.GetOEMCP()
        if cp_oem:
            enc = f"cp{cp_oem}"
            if enc not in encodings:
                encodings.append(enc)
    except Exception:
        pass
    for fallback in ("cp857", "cp1254", "utf-8", "cp1252"):
        if fallback not in encodings:
            encodings.append(fallback)
    for enc in encodings:
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def list_plans() -> list[dict[str, Any]]:
    """Sistemdeki kayıtlı tüm güç planlarını listeler.

    Döndürülen liste elemanları:
      {"guid": str, "name": str, "active": bool}

    Hata durumunda asla istisna fırlatmaz, [] döner ve sources.log_err'e yazar.
    """
    try:
        res = subprocess.run(
            ["powercfg", "/list"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=5,
        )
        if res.returncode != 0:
            return []
        text = _decode_console_output(res.stdout)
        return parse_powercfg_list(text)
    except Exception as exc:
        try:
            import sources
            sources.log_err("power_plan", exc)
        except Exception:
            pass
        return []


def set_plan(guid: str) -> bool:
    """Belirtilen GUID'e sahip güç planını etkinleştirir (`powercfg /setactive <guid>`).

    Güvenlik kontrolleri:
      1. Test altında çağrıldığında RuntimeError fırlatır (SERIT_ALLOW_REAL_POWER_PLAN=1 hariç).
      2. GUID değeri regex ^[0-9a-fA-F-]{36}$ ile doğrulanır.
      3. GUID sistemdeki mevcut list_plans() listesinde bulunmalıdır.

    İşlem başarılıysa True, aksi halde False döner.
    """
    _guard_real_power_plan(f"set_plan({guid})")

    if not isinstance(guid, str) or not GUID_RE.match(guid.strip()):
        return False

    normalized_guid = guid.strip().lower()

    try:
        plans = list_plans()
        known_guids = {p.get("guid", "").lower() for p in plans}
        if normalized_guid not in known_guids:
            return False

        res = subprocess.run(
            ["powercfg", "/setactive", normalized_guid],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=5,
        )
        return res.returncode == 0
    except Exception as exc:
        try:
            import sources
            sources.log_err("power_plan", exc)
        except Exception:
            pass
        return False
