"""test_v25_presence.py - presence.py: yetenek okuyucu, uyku engelleme, simgeler."""

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="serit-presence-")
os.environ["SERIT_TEST"] = "1"
os.environ["SERIT_LOG"] = os.path.join(_TMP, "serit.log")
os.environ["SERIT_CACHE_DIR"] = _TMP
os.environ.pop("SERIT_ALLOW_REAL_POWER", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import presence  # noqa: E402


# ------------------------------------------------------------ sahte winreg

class _Key:
    def __init__(self, subs=None, vals=None, fail=False):
        self.subs = subs or {}
        self.vals = vals or {}
        self.fail = fail


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree, root_fail=False):
        self.tree = tree  # {"microphone": _Key, "webcam": _Key}
        self.root_fail = root_fail

    def OpenKey(self, parent, name):
        if self.root_fail:
            raise PermissionError("erişim reddedildi")
        if parent == "HKCU":
            cap = name.rsplit("\\", 1)[-1]
            if cap not in self.tree:
                raise FileNotFoundError(name)
            return self.tree[cap]
        if name not in parent.subs:
            raise FileNotFoundError(name)
        k = parent.subs[name]
        if k.fail:
            raise PermissionError(name)
        return k

    def EnumKey(self, key, i):
        names = list(key.subs)
        if i >= len(names):
            raise OSError("bitti")
        return names[i]

    def QueryValueEx(self, key, name):
        if name not in key.vals:
            raise FileNotFoundError(name)
        return (key.vals[name], 11)

    def CloseKey(self, key):
        pass


def _used(start=1, stop=0):
    return _Key(vals={"LastUsedTimeStart": start, "LastUsedTimeStop": stop})


def _with_reg(reg, fn):
    old = presence._winreg
    presence._winreg = reg
    try:
        return fn()
    finally:
        presence._winreg = old


def test_capability_parser():
    tree = {
        "microphone": _Key(subs={
            "Microsoft.WindowsCamera_8wekyb3d8bbwe": _used(5, 0),
            "MSTeams_8wekyb3d8bbwe": _used(5, 99),       # durmuş
            "Vendor.Ses_abc": _Key(vals={"LastUsedTimeStart": 5}),  # Stop yok
            "NonPackaged": _Key(subs={
                "C:#Prog#Zoom#bin#zoom.exe": _used(7, 0),
                "C:#Prog#Eski#eski.exe": _used(7, 3),
            }),
        }),
        "webcam": _Key(subs={
            "MSTeams_8wekyb3d8bbwe": _used(9, 0),
            "Bos_x": _used(0, 0),
            "Bozuk_y": _Key(fail=True),
        }),
    }
    r = _with_reg(FakeWinreg(tree), presence.read_capability_usage)
    assert r["mic"] == ["Kamera", "Zoom"], r
    assert r["cam"] == ["Teams"], r
    assert "err" not in r


def test_capability_error():
    r = _with_reg(FakeWinreg({}, root_fail=True), presence.read_capability_usage)
    assert r["mic"] == [] and r["cam"] == [] and "err" in r, r
    r2 = _with_reg(None, presence.read_capability_usage)
    assert r2["mic"] == [] and "err" in r2
    r3 = _with_reg(FakeWinreg({}), presence.read_capability_usage)  # anahtar yok
    assert r3["mic"] == [] and "err" in r3


def test_friendly_names_and_dedupe():
    f = presence._friendly_package
    assert f("Microsoft.WindowsCamera_8wekyb3d8bbwe") == "Kamera"
    assert f("MSTeams_8wekyb3d8bbwe") == "Teams"
    assert f("Acme.Recorder_123abc") == "Recorder"
    assert presence._friendly_exe("C:#X#zoom.exe") == "Zoom"
    assert presence._friendly_exe("C:#X#foo.exe") == "Foo"
    tree = {"microphone": _Key(subs={"NonPackaged": _Key(subs={
        "C:#A#zoom.exe": _used(1, 0), "D:#B#zoom.exe": _used(1, 0)})}),
        "webcam": _Key()}
    r = _with_reg(FakeWinreg(tree), presence.read_capability_usage)
    assert r["mic"] == ["Zoom"], r


def test_tooltip():
    t = presence.presence_tooltip
    assert t({"mic": ["Zoom"], "cam": ["Teams"]}) == "Mikrofon: Zoom · Kamera: Teams"
    assert t({"mic": ["Zoom", "Edge"], "cam": []}) == "Mikrofon: Zoom, Edge"
    assert t({"mic": [], "cam": ["Kamera"]}) == "Kamera: Kamera"
    assert t({"mic": [], "cam": []}) == ""
    assert t({}) == ""


# ---------------------------------------------------------- sahte kernel32

class FakeK32:
    def __init__(self):
        self.created = 0
        self.closed = 0
        self.sets = []
        self.clears = []
        self.reasons = []
        self._n = 100

    def PowerCreateRequest(self, ref):
        self.created += 1
        self._n += 1
        try:
            self.reasons.append(ref._obj.SimpleReasonString)
        except Exception:
            pass
        return self._n

    def PowerSetRequest(self, h, kind):
        self.sets.append((h, kind))
        return 1

    def PowerClearRequest(self, h, kind):
        self.clears.append((h, kind))
        return 1

    def CloseHandle(self, h):
        self.closed += 1
        return 1

    @property
    def open_handles(self):
        return self.created - self.closed


def _fake():
    presence.release_all()
    fk = FakeK32()
    presence._kernel32 = fk
    return fk


def _unfake():
    presence.release_all()
    presence._kernel32 = None


def test_keep_awake_on_off():
    fk = _fake()
    try:
        assert presence.keep_awake_active() is False
        assert presence.set_keep_awake(True) is True
        assert presence.keep_awake_active() is True
        assert fk.created == 1 and sorted(k for _, k in fk.sets) == [0, 1]
        assert fk.reasons == ["Şerit: uyku engelleme"], fk.reasons
        assert presence.set_keep_awake(False) is False
        assert presence.keep_awake_active() is False
        assert sorted(k for _, k in fk.clears) == [0, 1] and fk.closed == 1
    finally:
        _unfake()


def test_keep_awake_double_on_no_leak():
    fk = _fake()
    try:
        presence.set_keep_awake(True)
        presence.set_keep_awake(True)
        assert fk.created == 1 and fk.open_handles == 1
        presence.set_keep_awake(False)
        presence.set_keep_awake(False)
        assert fk.open_handles == 0 and fk.closed == 1
    finally:
        _unfake()


def test_release_all_idempotent():
    fk = _fake()
    try:
        presence.set_keep_awake(True)
        presence.release_all()
        presence.release_all()
        assert fk.closed == 1 and not presence.keep_awake_active()
    finally:
        _unfake()


def test_guard_blocks_real_path():
    presence.release_all()
    presence._kernel32 = None
    called = []
    orig = presence._load_real_kernel32
    presence._load_real_kernel32 = lambda: called.append(1) or None
    try:
        assert os.environ.get("SERIT_ALLOW_REAL_POWER") != "1"
        assert presence.set_keep_awake(True) is True  # sahte durum
        assert presence.keep_awake_active() is True
        assert presence.set_keep_awake(False) is False
        assert not called, "gerçek kernel32 yüklendi"
        presence.set_keep_awake(True)
        presence.release_all()
        assert not presence.keep_awake_active() and not called
    finally:
        presence._load_real_kernel32 = orig
        presence.release_all()


# ----------------------------------------------------------------- çizim

def _render(fn, w, h, dpr=1.25):
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor("#0d0f13"))
    p = QPainter(img)
    fn(p, QRectF(0, 0, w, h))
    p.end()
    return img


def _nonbg(img):
    bg = QColor("#0d0f13").rgb()
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if img.pixelColor(x, y).rgb() != bg)


def test_draw_all_states():
    for active in (False, True):
        for hover in (False, True):
            img = _render(lambda p, r: presence.draw_keep_awake_icon(p, r, active, hover), 28, 28)
            assert _nonbg(img) > 30
    cases = [{"mic": ["a"], "cam": []}, {"mic": [], "cam": ["b"]}, {"mic": ["a"], "cam": ["b"]}]
    for u in cases:
        for hover in (False, True):
            img = _render(lambda p, r: presence.draw_presence_icon(p, r, u, hover), 24, 28)
            assert _nonbg(img) > 30
    empty = _render(lambda p, r: presence.draw_presence_icon(p, r, {"mic": [], "cam": []}), 24, 28)
    assert _nonbg(empty) == 0
    presence.draw_presence_icon  # noqa: B018


def main():
    tests = [
        test_capability_parser, test_capability_error, test_friendly_names_and_dedupe,
        test_tooltip, test_keep_awake_on_off, test_keep_awake_double_on_no_leak,
        test_release_all_idempotent, test_guard_blocks_real_path, test_draw_all_states,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, exc)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
