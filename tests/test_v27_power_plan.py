"""test_v27_power_plan.py - Güç planı yönetimi modülü birim testleri.

Test kuralları:
- Tamamen yapay / örnek veriler kullanır (gizlilik ve taşınabilirlik).
- parse_powercfg_list hem İngilizce hem Türkçe konsol çıktılarını doğru çözümler.
- set_plan çağrısının test altında mutlaka RuntimeError fırlattığı doğrulanır.
- set_plan doğrulama mantığı (regex ve mevcut plan kontrolü) yapay verilerle test edilir.
- Testler sırasında gerçek `powercfg /setactive` ASLA çağrılmaz.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

os.environ["SERIT_TEST"] = "1"
_tmp_dir = tempfile.mkdtemp(prefix="serit-test-power-plan-")
os.environ["SERIT_LOG"] = str(Path(_tmp_dir) / "test.log")
os.environ["SERIT_CACHE_DIR"] = _tmp_dir

import power_plan  # noqa: E402


def test_parse_powercfg_list_english() -> None:
    """İngilizce 'powercfg /list' çıktısının doğru çözümlendiğini test eder."""
    sample_en = (
        "Existing Power Schemes (* Active)\n"
        "-----------------------------------\n"
        "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)\n"
        "Power Scheme GUID: 5da85d85-eb0c-4710-a805-6da8bbcf1f02  (Custom Office) *\n"
        "Power Scheme GUID: 653fbb7f-248b-41d0-aa49-03fabbfd5e8e  (High Performance)\n"
    )
    plans = power_plan.parse_powercfg_list(sample_en)
    assert len(plans) == 3

    assert plans[0]["guid"] == "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert plans[0]["name"] == "Balanced"
    assert plans[0]["active"] is False

    assert plans[1]["guid"] == "5da85d85-eb0c-4710-a805-6da8bbcf1f02"
    assert plans[1]["name"] == "Custom Office"
    assert plans[1]["active"] is True

    assert plans[2]["guid"] == "653fbb7f-248b-41d0-aa49-03fabbfd5e8e"
    assert plans[2]["name"] == "High Performance"
    assert plans[2]["active"] is False


def test_parse_powercfg_list_turkish() -> None:
    """Türkçe 'powercfg /list' çıktısının doğru çözümlendiğini test eder."""
    sample_tr = (
        "Mevcut Güç Düzenleri (* Etkin)\n"
        "-----------------------------------\n"
        "Güç Düzeni GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Dengeli)\n"
        "Güç Düzeni GUID: a1b2c3d4-e5f6-7890-abcd-ef0123456789  (Özel Tasarruf) *\n"
        "Güç Düzeni GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Yüksek Performans (önerilen))\n"
    )
    plans = power_plan.parse_powercfg_list(sample_tr)
    assert len(plans) == 3

    assert plans[0]["guid"] == "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert plans[0]["name"] == "Dengeli"
    assert plans[0]["active"] is False

    assert plans[1]["guid"] == "a1b2c3d4-e5f6-7890-abcd-ef0123456789"
    assert plans[1]["name"] == "Özel Tasarruf"
    assert plans[1]["active"] is True

    assert plans[2]["guid"] == "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    assert plans[2]["name"] == "Yüksek Performans (önerilen)"
    assert plans[2]["active"] is False


def test_set_plan_test_guard_raises_runtime_error() -> None:
    """set_plan çağrısının test altında mutlaka RuntimeError fırlattığını doğrular."""
    # SERIT_ALLOW_REAL_POWER_PLAN tanımlı değilken çağrı engellenmelidir
    os.environ.pop("SERIT_ALLOW_REAL_POWER_PLAN", None)
    raised = False
    try:
        power_plan.set_plan("381b4222-f694-41f0-9685-ff5bb260df2e")
    except RuntimeError as exc:
        raised = True
        assert "Test sırasında gerçek güç planı değiştirilemez" in str(exc)

    assert raised, "set_plan test altında RuntimeError fırlatmalıydı"


def test_set_plan_validation_and_safety(monkeypatch=None) -> None:
    """GUID regex doğrulaması ve listede bulunma kontrolünü sahte ortamda test eder.

    Gerçek powercfg /setactive ASLA çağrılmaz (mocked).
    """
    os.environ["SERIT_ALLOW_REAL_POWER_PLAN"] = "1"
    try:
        mock_run = MagicMock()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        # subprocess.run ve list_plans fonsiyonlarını taklit et
        orig_run = subprocess.run
        orig_list_plans = power_plan.list_plans

        fake_known_plans = [
            {"guid": "381b4222-f694-41f0-9685-ff5bb260df2e", "name": "Fake Plan", "active": True}
        ]

        try:
            subprocess.run = mock_run
            power_plan.list_plans = lambda: fake_known_plans

            # 1. Geçersiz regex / komut enjeksiyonu denemeleri
            assert power_plan.set_plan("invalid-guid") is False
            assert power_plan.set_plan("381b4222-f694-41f0-9685-ff5bb260df2e & calc.exe") is False
            assert power_plan.set_plan("381b4222-f694-41f0-9685-ff5bb260df2") is False  # 35 karakter
            assert power_plan.set_plan("381b4222-f694-41f0-9685-ff5bb260df2e1") is False  # 37 karakter
            assert mock_run.call_count == 0, "Geçersiz GUID için subprocess çağrılmamalıydı"

            # 2. Geçerli formatta ancak listede olmayan GUID
            assert power_plan.set_plan("00000000-0000-0000-0000-000000000000") is False
            assert mock_run.call_count == 0, "Listede olmayan GUID için subprocess çağrılmamalıydı"

            # 3. Geçerli format ve listede olan GUID -> mock subprocess çağrılır
            success = power_plan.set_plan("381b4222-f694-41f0-9685-ff5bb260df2e")
            assert success is True
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert call_args == ["powercfg", "/setactive", "381b4222-f694-41f0-9685-ff5bb260df2e"]
            assert mock_run.call_args[1].get("creationflags") == power_plan.CREATE_NO_WINDOW
        finally:
            subprocess.run = orig_run
            power_plan.list_plans = orig_list_plans
    finally:
        os.environ.pop("SERIT_ALLOW_REAL_POWER_PLAN", None)


def test_live_list_plans_query() -> None:
    """Gerçek makinede list_plans sorgusunun istisna fırlatmadığını ve veri döndürdüğünü test eder."""
    plans = power_plan.list_plans()
    assert isinstance(plans, list)
    assert len(plans) > 0, "Windows sisteminde en az bir güç planı bulunmalıdır"

    active_count = 0
    for p in plans:
        assert isinstance(p["guid"], str)
        assert power_plan.GUID_RE.match(p["guid"])
        assert isinstance(p["name"], str)
        assert len(p["name"]) > 0
        assert isinstance(p["active"], bool)
        if p["active"]:
            active_count += 1

    assert active_count >= 1, "En az bir aktif güç planı bulunmalıdır"


def main() -> int:
    tests = [
        test_parse_powercfg_list_english,
        test_parse_powercfg_list_turkish,
        test_set_plan_test_guard_raises_runtime_error,
        test_set_plan_validation_and_safety,
        test_live_list_plans_query,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
