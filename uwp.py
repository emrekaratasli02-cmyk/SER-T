"""uwp.py - Microsoft Store (MSIX/UWP) uygulama desteği.

Store uygulamaları C:\\Program Files\\WindowsApps\\<Ad>_<Sürüm>_<Mimari>__<YayıncıId>\\ altında
yaşar. Bu modül:
  - is_uwp_path(path): yol bir Store paketinin içinde mi
  - resolve(path):     uygulama güncellenip klasör (sürüm) değiştiyse güncel exe yolunu bulur
  - aumid(path):       'Aile!AppId' kimliği (shell:AppsFolder ile açmak için)
  - launch(path):      Store uygulamasını resmi yoldan başlatır
  - logo_file(path, size): paketteki gerçek logo PNG'sinin yolu

Kurulu paketler kayıt defterinden okunur (~1 ms); PowerShell Get-AppxPackage ~200 ms sürer.
WindowsApps kök klasörü listelenemez (PermissionError), paket klasörlerinin içi okunabilir.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

_WINDOWSAPPS = os.path.normcase(r"\windowsapps" + "\\")
_REPO_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)
# <Ad>_<Sürüm>_<Mimari>_<Kaynak>_<YayıncıId>  (Kaynak çoğu zaman boş: "__")
_FULLNAME_RE = re.compile(r"^(?P<name>[^_]+)_(?P<ver>[\d.]+)_(?P<arch>[^_]*)_(?P<res>[^_]*)_(?P<pub>[^_\\]+)$")


def is_uwp_path(path: str) -> bool:
    return bool(path) and _WINDOWSAPPS in os.path.normcase(path)


def _split(path: str) -> Optional[Tuple[str, str, str]]:
    """(paket kök klasörü, paket tam adı, kökten sonraki göreli yol)"""
    norm = os.path.normpath(path)
    low = os.path.normcase(norm)
    i = low.find(_WINDOWSAPPS)
    if i < 0:
        return None
    start = i + len(_WINDOWSAPPS)
    rest = norm[start:]
    full, _, rel = rest.partition(os.sep)
    if not full:
        return None
    return norm[:start] + full, full, rel


def _parse_fullname(full: str) -> Optional[Dict[str, str]]:
    m = _FULLNAME_RE.match(full)
    return m.groupdict() if m else None


def _ver_key(ver: str) -> Tuple[int, ...]:
    try:
        return tuple(int(x) for x in ver.split("."))
    except ValueError:
        return (0,)


@lru_cache(maxsize=1)
def _installed() -> Tuple[Tuple[str, str], ...]:
    """Kurulu paketler: (tam ad, kök klasör). Kayıt defterinden, süreç başına bir kez."""
    try:
        import winreg
    except ImportError:
        return ()
    out: List[Tuple[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REPO_KEY) as k:
            i = 0
            while True:
                try:
                    full = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, full) as s:
                        root = winreg.QueryValueEx(s, "PackageRootFolder")[0]
                    out.append((full, str(root)))
                except OSError:
                    continue
    except OSError:
        return ()
    return tuple(out)


def refresh() -> None:
    """Kurulu paket ve manifest önbelleklerini temizle (ör. uygulama güncellendikten sonra)."""
    _installed.cache_clear()
    _manifest.cache_clear()


def resolve(path: str) -> str:
    """Yol hâlâ varsa aynen döner; yoksa aynı uygulamanın kurulu en yeni sürümündeki yolu döner."""
    if not is_uwp_path(path) or os.path.exists(path):
        return path
    parts = _split(path)
    if not parts:
        return path
    _root, full, rel = parts
    want = _parse_fullname(full)
    if not want:
        return path
    best: Optional[Tuple[Tuple[int, ...], str]] = None
    for cand_full, cand_root in _installed():
        c = _parse_fullname(cand_full)
        if not c or c["name"] != want["name"] or c["pub"] != want["pub"]:
            continue
        if c["arch"] not in (want["arch"], "neutral"):
            continue
        cand = os.path.join(cand_root, rel)
        if not os.path.exists(cand):
            continue
        key = _ver_key(c["ver"])
        if best is None or key > best[0]:
            best = (key, cand)
    return best[1] if best else path


@lru_cache(maxsize=32)
def _manifest(root: str) -> str:
    try:
        with open(os.path.join(root, "AppxManifest.xml"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _app_element(path: str) -> Optional[str]:
    """Manifestte exe'ye karşılık gelen <Application ...> etiketi (yoksa ilki)."""
    parts = _split(path)
    if not parts:
        return None
    text = _manifest(parts[0])
    apps = re.findall(r"<Application\s[^>]*>", text)
    if not apps:
        return None
    exe = os.path.normcase(parts[2])
    for a in apps:
        m = re.search(r'Executable="([^"]+)"', a)
        if m and os.path.normcase(os.path.normpath(m.group(1))) == exe:
            return a
    return apps[0]


def aumid(path: str) -> Optional[str]:
    """'Ad_YayıncıId!AppId' - shell:AppsFolder\\<aumid> ile açılır."""
    parts = _split(path)
    if not parts:
        return None
    info = _parse_fullname(parts[1])
    app = _app_element(path)
    if not info or not app:
        return None
    m = re.search(r'\sId="([^"]+)"', app)
    if not m:
        return None
    return f"{info['name']}_{info['pub']}!{m.group(1)}"


def launch(path: str) -> bool:
    """Store uygulamasını resmi kimliğiyle başlat. Başarısızsa False."""
    aid = aumid(resolve(path))
    if not aid:
        return False
    try:
        os.startfile("shell:AppsFolder\\" + aid)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def logo_file(path: str, size: int = 64) -> Optional[str]:
    """Manifestteki Square44x44Logo'nun en uygun boyutlu varyantı.

    Tercih: targetsize-N_altform-unplated (şeffaf arka plan, görev çubuğunun kullandığı),
    istenen boyuta eşit/büyük en küçük N; yoksa en büyük N; yoksa scale-* varyantı.
    """
    parts = _split(path)
    if not parts:
        return None
    root = parts[0]
    app = _app_element(path) or ""
    vis = re.search(r"<uap:VisualElements\s[^>]*>|<VisualElements\s[^>]*>", _manifest(root))
    src = re.search(r'Square44x44Logo="([^"]+)"', vis.group(0) if vis else app)
    if not src:
        return None
    rel_dir, base = os.path.split(os.path.normpath(src.group(1)))
    stem, ext = os.path.splitext(base)
    folder = os.path.join(root, rel_dir)
    try:
        files = os.listdir(folder)
    except OSError:
        return None
    prefix = (stem + ".").lower()
    sized: List[Tuple[int, str]] = []
    scaled: List[str] = []
    for fn in files:
        low = fn.lower()
        if not low.startswith(prefix) or not low.endswith(ext.lower()):
            continue
        q = low[len(prefix):-len(ext)]
        if q.startswith("targetsize-") and q.endswith("_altform-unplated"):
            try:
                sized.append((int(q[len("targetsize-"):].split("_")[0]), fn))
            except ValueError:
                pass
        elif q.startswith("scale-") and "_" not in q:
            scaled.append(fn)
    if sized:
        sized.sort()
        pick = next((fn for n, fn in sized if n >= size), sized[-1][1])
        return os.path.join(folder, pick)
    if scaled:
        return os.path.join(folder, sorted(scaled)[-1])
    plain = os.path.join(folder, base)
    return plain if os.path.exists(plain) else None
