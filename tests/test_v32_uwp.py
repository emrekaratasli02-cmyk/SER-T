"""test_v32_uwp.py - Store (MSIX/UWP) uygulama desteği: yol çözme, AUMID, logo seçimi.

Sahte bir WindowsApps ağacı geçici klasörde kurulur; gerçek sisteme dokunulmaz.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uwp  # noqa: E402

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10">
  <Identity Name="5319275A.WhatsAppDesktop" Version="{ver}" ProcessorArchitecture="x64" />
  <Applications>
    <Application Id="App" Executable="WhatsApp.Root.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="WhatsApp" Square44x44Logo="Assets\\AppList.png" Square150x150Logo="Assets\\MedTile.png" />
    </Application>
  </Applications>
</Package>
"""

PUB = "cv1g1gvanyjgm"


def make_pkg(base: Path, ver: str, sizes=(16, 32, 48, 64, 256)) -> Path:
    full = f"5319275A.WhatsAppDesktop_{ver}_x64__{PUB}"
    root = base / "WindowsApps" / full
    (root / "Assets").mkdir(parents=True)
    (root / "AppxManifest.xml").write_text(MANIFEST.format(ver=ver), encoding="utf-8")
    (root / "WhatsApp.Root.exe").write_bytes(b"MZ")
    for n in sizes:
        (root / "Assets" / f"AppList.targetsize-{n}_altform-unplated.png").write_bytes(b"x")
        (root / "Assets" / f"AppList.targetsize-{n}.png").write_bytes(b"x")  # plakalı, seçilmemeli
    (root / "Assets" / "AppList.scale-200.png").write_bytes(b"x")
    return root


def test_detection_and_split() -> None:
    assert uwp.is_uwp_path(r"C:\Program Files\WindowsApps\X_1.0_x64__abc\a.exe")
    assert not uwp.is_uwp_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert not uwp.is_uwp_path("")
    print("test_detection_and_split PASSED")


def test_aumid_and_logo() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_pkg(Path(td), "2.2641.101.0")
        exe = str(root / "WhatsApp.Root.exe")
        uwp.refresh()
        assert uwp.aumid(exe) == f"5319275A.WhatsAppDesktop_{PUB}!App", uwp.aumid(exe)
        # boyut seçimi: eşit/büyük en küçük, unplated tercih
        assert os.path.basename(uwp.logo_file(exe, 64)) == "AppList.targetsize-64_altform-unplated.png"
        assert os.path.basename(uwp.logo_file(exe, 50)) == "AppList.targetsize-64_altform-unplated.png"
        assert os.path.basename(uwp.logo_file(exe, 512)) == "AppList.targetsize-256_altform-unplated.png"
    print("test_aumid_and_logo PASSED")


def test_logo_fallback_scale() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_pkg(Path(td), "1.0.0.0", sizes=())
        uwp.refresh()
        assert os.path.basename(uwp.logo_file(str(root / "WhatsApp.Root.exe"), 64)) == "AppList.scale-200.png"
    print("test_logo_fallback_scale PASSED")


def test_resolve_after_update() -> None:
    """Uygulama güncellendi: eski sürüm klasörü yok, yeni sürüm kurulu -> yeni yol."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        old_exe = str(base / "WindowsApps" / f"5319275A.WhatsAppDesktop_2.2641.101.0_x64__{PUB}" / "WhatsApp.Root.exe")
        new_root = make_pkg(base, "2.2650.5.0")
        older_root = make_pkg(base, "2.2600.1.0")
        other = make_pkg_other(base)
        fake = (
            (new_root.name, str(new_root)),
            (older_root.name, str(older_root)),
            (other.name, str(other)),
        )
        orig = uwp._installed
        uwp._installed = lambda: fake  # type: ignore[assignment]
        try:
            got = uwp.resolve(old_exe)
            assert got == str(new_root / "WhatsApp.Root.exe"), got
            # var olan yol olduğu gibi döner
            assert uwp.resolve(str(older_root / "WhatsApp.Root.exe")) == str(older_root / "WhatsApp.Root.exe")
            # Store dışı yol dokunulmaz
            assert uwp.resolve(r"C:\x\y.exe") == r"C:\x\y.exe"
        finally:
            uwp._installed = orig  # type: ignore[assignment]
    # paket hiç yoksa yol aynen döner (çökmez)
    gone = r"C:\Program Files\WindowsApps\Nope.App_1.0.0.0_x64__zzz\a.exe"
    assert uwp.resolve(gone) == gone
    print("test_resolve_after_update PASSED")


def make_pkg_other(base: Path) -> Path:
    # aynı ad, farklı yayıncı -> eşleşmemeli
    root = base / "WindowsApps" / "5319275A.WhatsAppDesktop_9.9.9.9_x64__otherpub"
    root.mkdir(parents=True)
    (root / "WhatsApp.Root.exe").write_bytes(b"MZ")
    return root


def test_real_machine_whatsapp() -> None:
    """Bu makinede WhatsApp kuruluysa: kayıt defterinden bulunur, logo gerçek dosya."""
    uwp.refresh()
    pk = [(f, r) for f, r in uwp._installed() if f.startswith("5319275A.WhatsAppDesktop_")]
    if not pk:
        print("test_real_machine_whatsapp SKIPPED (kurulu değil)")
        return
    exe = os.path.join(pk[0][1], "WhatsApp.Root.exe")
    assert os.path.exists(exe)
    assert uwp.aumid(exe) == "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", uwp.aumid(exe)
    logo = uwp.logo_file(exe, 64)
    assert logo and os.path.exists(logo), logo
    print("test_real_machine_whatsapp PASSED")


if __name__ == "__main__":
    test_detection_and_split()
    test_aumid_and_logo()
    test_logo_fallback_scale()
    test_resolve_after_update()
    test_real_machine_whatsapp()
    print("ALL test_v32_uwp checks passed.")
