"""test_v32_shelf_poll.py - DownloadsWatcher.busy: inen/oturmamış dosya varken True, boştayken False."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shelf  # noqa: E402


def test_busy_states() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        w = shelf.DownloadsWatcher(str(d))
        w.poll()  # taban çizgisi
        assert w.busy is False

        # inen dosya (.crdownload) -> meşgul
        part = d / "film.mp4.crdownload"
        part.write_bytes(b"x")
        w.poll()
        assert w.busy is True

        # indirme bitti: geçici dosya gitti, gerçek dosya geldi -> boyut oturana kadar meşgul
        part.unlink()
        (d / "film.mp4").write_bytes(b"xx")
        w.poll()
        assert w.busy is True  # ilk görülüş: _pending'de

        found = w.poll()       # ikinci görülüş, aynı imza -> teslim
        assert any(p.endswith("film.mp4") for p in found), found
        assert w.busy is False
    print("test_busy_states PASSED")


if __name__ == "__main__":
    test_busy_states()
    print("ALL test_v32_shelf_poll checks passed.")
