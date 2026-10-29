"""ag_local.py - Antigravity'nin kendi (yerel) dil sunucusundan Gemini 4 Argon kotası.

Argon, Google'ın hesap model listesinde (cloudcode fetchAvailableModels) yok; yalnız Antigravity
uygulamasının model menüsünde var (29 Eki 2026). Menü kotayı bilgisayardaki dil sunucusundan
(language_server.exe, 127.0.0.1, GetUserStatus) alır. Bu modül yalnız OKUR:
- CSRF anahtarı sürecin komut satırından alınır, yalnız bellekte kalır; log'a, diske, ekrana yazılmaz.
- Yalnız 127.0.0.1'e bağlanır (sunucu sertifikası kendinden imzalı; doğrulama yalnız bu yerel
  bağlantıda kapalı, vekil sunucu kullanılmaz).
- Antigravity kapalıyken son okuma önbellekten döner ve "son okuma" diye işaretlenir; sıfırlanma
  saati geçtiyse kullanım 0 sayılır (kota o saatte yenilenir).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

import logpath

CACHE_NAME = "ag_argon_cache.json"
LABEL_LIVE = "Argon"
LABEL_CACHED = "Argon · son okuma"
_SVC = "exa.language_server_pb.LanguageServerService"
_BODY = json.dumps({"metadata": {"ideName": "antigravity", "extensionName": "antigravity",
                                 "locale": "en"}}).encode()
_CSRF_RE = re.compile(r"^--csrf_token(?:=(.*))?$")


def _log_err(source: str, exc: Exception) -> None:
    try:
        import sources
        sources.log_err(source, exc)
    except Exception:
        pass


def _parse_iso(val: Any) -> Optional[dt.datetime]:
    if not val:
        return None
    try:
        d = dt.datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _find_servers() -> List[Dict[str, Any]]:
    """Antigravity'nin dil sunucusu süreçleri: [{csrf, ports}] (anahtar yalnız bellekte)."""
    out: List[Dict[str, Any]] = []
    if psutil is None:
        return out
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if not name.startswith("language_server"):
                continue
            cl = list(proc.info.get("cmdline") or [])
            where = str(proc.info.get("exe") or (cl[0] if cl else "")).lower()
            if "antigravity" not in where:
                continue  # başka bir editörün dil sunucusu
            csrf = None
            for i, arg in enumerate(cl):
                m = _CSRF_RE.match(arg)
                if m:
                    csrf = m.group(1) if m.group(1) is not None else (cl[i + 1] if i + 1 < len(cl) else None)
                    break
            ports = sorted({c.laddr.port for c in proc.net_connections(kind="tcp")
                            if c.status == psutil.CONN_LISTEN and c.laddr})
            if ports:
                out.append({"csrf": csrf, "ports": ports})
        except Exception:
            continue
    return out


def _post(url: str, csrf: Optional[str], timeout: float) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json", "Connect-Protocol-Version": "1"}
    if csrf:
        headers["X-Codeium-Csrf-Token"] = csrf
    handlers: List[Any] = [urllib.request.ProxyHandler({})]
    if url.startswith("https"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # yalnız 127.0.0.1: Antigravity'nin kendinden imzalı sertifikası
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=_BODY, headers=headers, method="POST")
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _walk(obj: Any, found: List[Dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        if "quotaInfo" in obj and "label" in obj:
            found.append(obj)
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def parse_argon(data: Any) -> Optional[Dict[str, Any]]:
    """GetUserStatus yanıtından Argon satırları -> {used, reset_at}. Argon yoksa None.

    Argon (Low/Medium/High) tek kotayı paylaşır; yine de en dolu olanı ve en yakın sıfırlanmayı alır.
    Hakkı biten modelde remainingFraction hiç gelmez (yalnız resetTime): %100 kullanılmış sayılır.
    """
    rows: List[Dict[str, Any]] = []
    _walk(data, rows)
    fracs: List[float] = []
    resets: List[dt.datetime] = []
    for row in rows:
        if "argon" not in str(row.get("label") or "").lower():
            continue
        quota = row.get("quotaInfo") or {}
        frac = quota.get("remainingFraction")
        reset = _parse_iso(quota.get("resetTime"))
        if isinstance(frac, bool) or not isinstance(frac, (int, float)):
            if reset is None:
                continue
            frac = 0.0
        fracs.append(max(0.0, min(1.0, float(frac))))
        if reset is not None:
            resets.append(reset)
    if not fracs:
        return None
    used = round(100.0 * (1.0 - min(fracs)), 1)
    reset_at = min(resets).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if resets else None
    return {"used": max(0.0, min(100.0, used)), "reset_at": reset_at}


def read_argon(timeout: float = 4.0,
               servers: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> Optional[Dict[str, Any]]:
    """Çalışan Antigravity'den canlı Argon kotası; Antigravity kapalıysa ya da Argon yoksa None."""
    for srv in (servers or _find_servers)():
        for port in srv.get("ports") or []:
            for scheme in ("https", "http"):
                try:
                    data = _post(f"{scheme}://127.0.0.1:{int(port)}/{_SVC}/GetUserStatus", srv.get("csrf"), timeout)
                except Exception:
                    continue  # yanlış port/şema: sessizce sıradakine geç
                res = parse_argon(data)
                if res is not None:
                    return res
                break  # bu port cevap verdi ama Argon yok: diğer şemayı deneme
    return None


def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("used"), (int, float)) else None
    except Exception:
        return None


def _save(path: Path, data: Dict[str, Any]) -> None:
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        _log_err("ag_local_cache", exc)


def fetch_argon(now: Optional[dt.datetime] = None,
                reader: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                cache_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Kota paneli için Argon grubu: {label, used, reset_at(UTC ISO), stale}. Hiç okuma yoksa None."""
    now = now or dt.datetime.now(dt.timezone.utc)
    path = Path(cache_path) if cache_path else logpath.get_cache_file(CACHE_NAME)
    live = None
    try:
        live = (reader or read_argon)()
    except Exception as exc:
        _log_err("ag_local", exc)
    if live:
        _save(path, {"used": live["used"], "reset_at": live.get("reset_at"), "read_at": now.isoformat()})
        return {"label": LABEL_LIVE, "used": live["used"], "reset_at": live.get("reset_at"), "stale": False}
    cached = _load(path)
    if not cached:
        return None
    used: Optional[float] = float(cached["used"])
    reset_at = cached.get("reset_at")
    reset_dt = _parse_iso(reset_at)
    if reset_dt is not None and reset_dt <= now:
        used, reset_at = 0.0, None  # sıfırlanma saati geçti: kota yenilendi, yeni saat bilinmiyor
    return {"label": LABEL_CACHED, "used": used, "reset_at": reset_at, "stale": True}
