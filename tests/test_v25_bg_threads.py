"""v25: tek HTTP istemcisi, FX kesik gövde yeniden denemesi, medya için tek olay döngüsü.
Ağa ve gerçek WinRT'ye çıkılmaz."""
import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

import media
import sources

FX_OK = ('{"USD":{"Satış":"49,9","Değişim":"0,08"},"EUR":{"Satış":"55,7","Değişim":"0,1"},'
         '"gram-altin":{"Satış":"6.397,04","Değişim":"1,2"},"Update_Date":"x"}')


def _reset_client():
    sources._http_reset()


def test_client_reused_and_recreated():
    _reset_client()
    calls = {"n": 0, "fail": 0}

    def handler(req):
        calls["n"] += 1
        if calls["fail"]:
            calls["fail"] -= 1
            raise httpx.ConnectError("boom", request=req)
        return httpx.Response(200, json={"ok": 1})

    orig = httpx.Client
    made = []

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        c = orig(*a, **k)
        made.append(c)
        return c

    sources.httpx.Client = factory
    try:
        for _ in range(5):
            assert sources._http_get("https://x.test/a").status_code == 200
        assert len(made) == 1, len(made)
        calls["fail"] = 1
        assert sources._http_get("https://x.test/a").status_code == 200
        assert len(made) == 2, "ağ hatasından sonra istemci yeniden kurulmalı"
        assert made[0].is_closed
        for _ in range(3):
            sources._http_get("https://x.test/a")
        assert len(made) == 2
    finally:
        sources.httpx.Client = orig
        _reset_client()
    print("✓ paylaşılan istemci testi geçti.")


class _R:
    status_code = 200

    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def json(self):
        if self.exc:
            raise self.exc
        import json
        return json.loads(self.text)


def _fx_with(responses):
    orig_get, orig_delay = sources._http_get, sources._FX_RETRY_DELAY_S
    it = iter(responses)
    n = {"c": 0}

    def fake(url, **kw):
        n["c"] += 1
        return next(it)

    sources._http_get, sources._FX_RETRY_DELAY_S = fake, 0.0
    sources._FX_LOG_LAST.clear()
    try:
        return sources.fetch_fx(), n["c"]
    finally:
        sources._http_get, sources._FX_RETRY_DELAY_S = orig_get, orig_delay


def test_fx_truncated_then_ok():
    r, n = _fx_with([_R(FX_OK[:40]), _R(FX_OK)])
    assert "err" not in r and r["usd"] == 49.9 and n == 2, (r, n)
    r, n = _fx_with([_R(exc=UnicodeDecodeError("utf-8", b"\xc5", 0, 1, "unexpected end of data")), _R(FX_OK)])
    assert "err" not in r and n == 2
    print("✓ FX kesik gövde -> tek yeniden deneme -> başarı.")


def test_fx_truncated_twice():
    r, n = _fx_with([_R(FX_OK[:40]), _R(FX_OK[:50])])
    assert r == {"err": "Bağlantı yok"} and n == 2, (r, n)
    print("✓ FX iki kez kesik -> hata sonucu.")


def test_media_loop_threads_and_hang():
    media._LOOP_LAST_START = -1e9
    created = []
    orig_start = threading.Thread.start

    def counting(self, *a, **k):
        created.append(self.name)
        return orig_start(self, *a, **k)

    threading.Thread.start = counting
    try:
        async def quick():
            return 7
        for _ in range(50):
            ok, v = media._run_on_loop(quick)
            assert ok and v == 7
        assert len(created) <= 2, created
        assert created[0] == "serit-media-loop"

        async def hang():
            await asyncio.sleep(60)
        t0 = time.monotonic()
        ok, v = media._run_on_loop(hang, 0.3)
        assert not ok and time.monotonic() - t0 < 2.0
        ok, v = media._run_on_loop(quick)  # iptal edilen iş döngüyü bloklamaz
        assert ok and v == 7
        assert len(created) <= 2, created
    finally:
        threading.Thread.start = orig_start
    print("✓ medya tek döngü + zaman aşımı testi geçti.")


def test_media_loop_replaced_when_blocked():
    media._LOOP_LAST_START = -1e9
    async def quick():
        return 1
    assert media._run_on_loop(quick)[0]
    old = media._LOOP_THREAD
    async def block():
        time.sleep(1.2)  # döngü iş parçacığını gerçekten bloklar
    ok, _ = media._run_on_loop(block, 0.2)
    assert not ok
    media._LOOP_DEAD_AFTER_S = 0.0
    media._LOOP_RESTART_GAP_S = 0.0
    try:
        ok, v = media._run_on_loop(quick, 1.5)
        assert ok and v == 1 and media._LOOP_THREAD is not old
    finally:
        media._LOOP_DEAD_AFTER_S = 4.0
        media._LOOP_RESTART_GAP_S = 30.0
    time.sleep(1.2)
    print("✓ takılı döngü yenisiyle değiştirildi.")


def test_media_control_blocked_under_test():
    assert media.media_control("playpause") is False
    print("✓ test altında medya komutu gönderilmez.")


if __name__ == "__main__":
    test_client_reused_and_recreated()
    test_fx_truncated_then_ok()
    test_fx_truncated_twice()
    test_media_loop_threads_and_hang()
    test_media_loop_replaced_when_blocked()
    test_media_control_blocked_under_test()
