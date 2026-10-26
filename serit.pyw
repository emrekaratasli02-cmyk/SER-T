# Şerit: Emre'nin kişisel bilgi şeridi (v1, 26 Eki 2026).
# Ekranın üstünde ince, her zaman üstte duran bir şerit: Claude limiti, döviz/altın, hava, sistem.
# Claude: Claude Code'un ~/.claude/.credentials.json girişini SADECE okur, asla yenilemez/yazmaz.
import sys, json, time, threading, webbrowser, datetime as dt
from pathlib import Path

import httpx, psutil
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPoint, QLockFile
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QPainterPath, QPen, QGuiApplication, QImage)
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QToolTip

APP_DIR = Path(__file__).resolve().parent
SETTINGS = APP_DIR / "settings.json"
LOG = APP_DIR / "serit.log"
CRED = Path.home() / ".claude" / ".credentials.json"
DEFAULTS = {"city": "Aksaray", "lat": 38.37, "lon": 34.03, "pos": None}

H = 30
PAD_X, SEG_GAP = 14, 12
TXT, MUTED = QColor(232, 236, 241), QColor(140, 150, 166)
MINT, SKY = QColor(110, 231, 200), QColor(124, 196, 255)
AMBER, RED, GREEN = QColor(255, 196, 92), QColor(255, 110, 110), QColor(120, 220, 150)

WMO = {0: "Açık", 1: "Az bulutlu", 2: "Parçalı bulutlu", 3: "Kapalı", 45: "Sis", 48: "Sis",
       51: "Çisenti", 53: "Çisenti", 55: "Çisenti", 56: "Çisenti", 57: "Çisenti",
       61: "Yağmur", 63: "Yağmur", 65: "Kuvvetli yağmur", 66: "Donan yağmur", 67: "Donan yağmur",
       71: "Kar", 73: "Kar", 75: "Yoğun kar", 77: "Kar", 80: "Sağanak", 81: "Sağanak",
       82: "Kuvvetli sağanak", 85: "Kar sağanağı", 86: "Kar sağanağı", 95: "Fırtına",
       96: "Dolu", 99: "Dolu"}


def log(msg):
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def tr_num(s):  # "6.424,49" -> 6424.49
    return float(str(s).replace(".", "").replace(",", ".").replace("%", ""))


def fmt_tr(x, dec):
    t = f"{x:,.{dec}f}"
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def left_text(iso):
    try:
        end = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    sec = max(0, (end - dt.datetime.now(dt.timezone.utc)).total_seconds())
    d, rem = divmod(int(sec), 86400)
    h, m = rem // 3600, (rem % 3600) // 60
    if d:
        return f"{d}g {h}sa"
    if h:
        return f"{h}sa {m}dk"
    return f"{m}dk"


# ---------------- veri kaynakları (arka plan iş parçacıklarında çalışır) ----------------
def fetch_claude():
    try:
        c = json.loads(CRED.read_text(encoding="utf-8"))["claudeAiOauth"]
    except (OSError, ValueError, KeyError):
        return {"err": "Claude Code girişi yok"}
    if c.get("expiresAt", 0) / 1000 < time.time():
        # Yenilemeyi Claude Code'a bırakıyoruz: refresh token'ı biz döndürürsek onun girişi bozulur.
        return {"err": "giriş süresi doldu, Claude Code'u bir kez aç"}
    r = httpx.get("https://api.anthropic.com/api/oauth/usage", timeout=15,
                  headers={"Authorization": "Bearer " + c["accessToken"],
                           "anthropic-beta": "oauth-2025-04-20"})
    if r.status_code != 200:
        return {"err": f"hata {r.status_code}"}
    j = r.json()
    fh, sd = j.get("five_hour") or {}, j.get("seven_day") or {}
    return {"s": fh.get("utilization"), "s_reset": fh.get("resets_at"),
            "w": sd.get("utilization"), "w_reset": sd.get("resets_at"),
            "plan": c.get("subscriptionType", "")}


def fetch_fx():
    j = httpx.get("https://finans.truncgil.com/today.json", timeout=15).json()
    out = {"updated": j.get("Update_Date", "")}
    for key, name in (("USD", "usd"), ("EUR", "eur"), ("gram-altin", "gold")):
        v = j.get(key) or {}
        out[name] = tr_num(v.get("Satış"))
        out[name + "_chg"] = tr_num(v.get("Değişim", "0"))
    return out


def fetch_wx(s):
    u = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
         "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
         "&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=Europe/Istanbul")
    j = httpx.get(u.format(**s), timeout=15).json()
    cur, day = j["current"], j.get("daily", {})
    return {"t": cur["temperature_2m"], "feel": cur.get("apparent_temperature"),
            "code": cur.get("weather_code"), "wind": cur.get("wind_speed_10m"),
            "max": (day.get("temperature_2m_max") or [None])[0],
            "min": (day.get("temperature_2m_min") or [None])[0]}


def fetch_sys():
    vm = psutil.virtual_memory()
    return {"cpu": psutil.cpu_percent(None), "ram": vm.percent,
            "ram_used": vm.used / 2**30, "ram_total": vm.total / 2**30}


class Feeder(QObject):
    got = Signal(str, object)

    def run(self, key, fn):
        def work():
            try:
                val = fn()
            except Exception as e:  # ağ yoksa şerit çökmesin, sadece o bölüm uyarı göstersin
                log(f"{key}: {type(e).__name__}: {e}")
                val = {"err": "bağlantı yok"}
            if isinstance(val, dict):
                val["at"] = time.time()
            self.got.emit(key, val)
        threading.Thread(target=work, daemon=True).start()


# ---------------- şerit ----------------
class Serit(QWidget):
    def __init__(self, settings):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.s = settings
        self.data = {"claude": None, "fx": None, "wx": None, "sys": None}
        self.f_main = QFont("Segoe UI Variable Text", 9)
        self.f_main.setWeight(QFont.DemiBold)
        self.f_small = QFont("Segoe UI Variable Text", 8)
        self.hits, self._press, self._dragging = [], None, False
        self.feeder = Feeder()
        self.feeder.got.connect(self.on_data)
        self.relayout()

    # --- veri ---
    def start_timers(self):
        for key, fn, sec in (("claude", fetch_claude, 120), ("fx", fetch_fx, 300),
                             ("wx", lambda: fetch_wx(self.s), 900)):
            t = QTimer(self, interval=sec * 1000)
            t.timeout.connect(lambda k=key, f=fn: self.feeder.run(k, f))
            t.start()
            self.feeder.run(key, fn)
        psutil.cpu_percent(None)
        t = QTimer(self, interval=2000)
        t.timeout.connect(lambda: self.on_data("sys", fetch_sys()))
        t.start()
        t2 = QTimer(self, interval=30000)  # "kalan süre" yazısı ilerlesin
        t2.timeout.connect(self.relayout)
        t2.start()

    def refresh_all(self):
        self.feeder.run("claude", fetch_claude)
        self.feeder.run("fx", fetch_fx)
        self.feeder.run("wx", lambda: fetch_wx(self.s))

    def on_data(self, key, val):
        old = self.data.get(key)
        if isinstance(val, dict) and val.get("err") and old and not old.get("err"):
            old["stale"] = True  # geçici hata: son iyi değeri göster, soluk
        else:
            self.data[key] = val
        self.relayout()

    # --- içerik: (segment, [öğeler]) ---
    def segments(self):
        segs = []
        c = self.data["claude"]
        it = [("t", "Claude", MUTED, "s"), ("g", 6)]
        if c is None:
            it.append(("t", "…", MUTED, "m"))
        elif c.get("err"):
            it.append(("t", c["err"], AMBER, "s"))
        else:
            it += [("t", f"%{c['s']:.0f}", self.level(c["s"]), "m", "%100"), ("g", 5),
                   ("b", c["s"] / 100), ("g", 6), ("t", left_text(c["s_reset"]), MUTED, "s"),
                   ("g", 12), ("t", "Hafta", MUTED, "s"), ("g", 5),
                   ("t", f"%{c['w']:.0f}", self.level(c["w"]), "m", "%100"), ("g", 5),
                   ("b", c["w"] / 100)]
        segs.append(("claude", it))

        f = self.data["fx"]
        it = []
        if f is None:
            it.append(("t", "Kur …", MUTED, "m"))
        elif f.get("err"):
            it.append(("t", "Kur: " + f["err"], AMBER, "s"))
        else:
            for sym, k, dec in (("$", "usd", 2), ("€", "eur", 2), ("Altın", "gold", 0)):
                it += [("t", sym, MUTED, "s"), ("g", 4), ("t", fmt_tr(f[k], dec), TXT, "m"),
                       ("g", 2), ("t", "▲" if f[k + "_chg"] > 0 else ("▼" if f[k + "_chg"] < 0 else "•"),
                                  GREEN if f[k + "_chg"] > 0 else (RED if f[k + "_chg"] < 0 else MUTED), "s"),
                       ("g", 10)]
            it.pop()
        segs.append(("fx", it))

        w = self.data["wx"]
        if w is None:
            it = [("t", "Hava …", MUTED, "m")]
        elif w.get("err"):
            it = [("t", "Hava: " + w["err"], AMBER, "s")]
        else:
            it = [("t", self.s["city"], MUTED, "s"), ("g", 6), ("t", f"{w['t']:.0f}°", TXT, "m"),
                  ("g", 5), ("t", WMO.get(w["code"], ""), MUTED, "s")]
        segs.append(("wx", it))

        y = self.data["sys"]
        if y:
            segs.append(("sys", [("t", "CPU", MUTED, "s"), ("g", 4),
                                 ("t", f"%{y['cpu']:.0f}", self.level(y["cpu"], 85, 95), "m", "%100"),
                                 ("g", 10), ("t", "RAM", MUTED, "s"), ("g", 4),
                                 ("t", f"%{y['ram']:.0f}", self.level(y["ram"], 85, 95), "m", "%100")]))
        return segs

    @staticmethod
    def level(v, warn=80, crit=95):
        return RED if v >= crit else (AMBER if v >= warn else TXT)

    def item_w(self, it):
        if it[0] == "g":
            return it[1]
        if it[0] == "b":
            return 34
        fm = QFontMetricsF(self.f_main if it[3] == "m" else self.f_small)
        w = fm.horizontalAdvance(it[1])
        if len(it) > 4:  # sabit genişlik: rakam değişince şerit zıplamasın
            w = max(w, fm.horizontalAdvance(it[4]))
        return w

    def relayout(self):
        self._segs = self.segments()
        width = PAD_X * 2 + sum(sum(self.item_w(i) for i in it) for _, it in self._segs)
        width += (len(self._segs) - 1) * (SEG_GAP * 2 + 1)
        width = int(width + 0.5)
        if width != self.width():
            cx = self.geometry().center().x() if self.isVisible() else None
            self.resize(width, H)
            if cx is not None:
                self.move(cx - width // 2, self.y())
        self.update()

    def place(self):
        p = self.s.get("pos")
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if p:
            self.move(p[0] - self.width() // 2, p[1])
        else:
            self.move(scr.center().x() - self.width() // 2, scr.top() + 6)

    # --- çizim ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, H / 2, H / 2)
        p.fillPath(path, QColor(18, 21, 27, 214))
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawPath(path)

        x, self.hits = PAD_X, []
        for n, (key, items) in enumerate(self._segs):
            if n:
                x += SEG_GAP
                p.setPen(QPen(QColor(255, 255, 255, 30), 1))
                p.drawLine(int(x) + 0.5, 8, int(x) + 0.5, H - 8)
                x += 1 + SEG_GAP
            x0 = x
            stale = (self.data.get(key) or {}).get("stale")
            for it in items:
                w = self.item_w(it)
                if it[0] == "t":
                    p.setFont(self.f_main if it[3] == "m" else self.f_small)
                    col = QColor(it[2])
                    if stale:
                        col.setAlpha(120)
                    p.setPen(col)
                    p.drawText(QRectF(x, 0, w + 1, H), Qt.AlignVCenter | Qt.AlignLeft, it[1])
                elif it[0] == "b":
                    self.draw_bar(p, QRectF(x, H / 2 - 2.5, w, 5), it[1])
                x += w
            self.hits.append((QRectF(x0 - SEG_GAP / 2, 0, x - x0 + SEG_GAP, H), key))
        p.end()

    def draw_bar(self, p, r, frac):
        frac = max(0.0, min(1.0, frac or 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 36))
        p.drawRoundedRect(r, 2.5, 2.5)
        if frac <= 0:
            return
        fill = QRectF(r.x(), r.y(), max(r.height(), r.width() * frac), r.height())
        if frac >= 0.8:
            p.setBrush(RED if frac >= 0.95 else AMBER)
        else:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, MINT)
            g.setColorAt(1, SKY)
            p.setBrush(g)
        p.drawRoundedRect(fill, 2.5, 2.5)

    # --- fare ---
    def key_at(self, pos):
        for r, k in self.hits:
            if r.contains(pos):
                return k
        return None

    def tooltip(self, key):
        d = self.data.get(key) or {}
        at = dt.datetime.fromtimestamp(d["at"]).strftime("%H:%M") if d.get("at") else "-"
        if key == "claude" and "s" in d:
            return (f"Claude ({d.get('plan', '')})\nOturum (5 saat): %{d['s']:.0f} · {left_text(d['s_reset'])} sonra sıfırlanır\n"
                    f"Haftalık: %{d['w']:.0f} · {left_text(d['w_reset'])} sonra sıfırlanır\n"
                    f"Kaynak: Anthropic, Claude Code girişi · {at}\nTıkla: claude.ai kullanım sayfası")
        if key == "fx" and "usd" in d:
            return (f"Satış fiyatları (günlük değişim)\nUSD {fmt_tr(d['usd'], 4)}  (%{fmt_tr(d['usd_chg'], 2)})\n"
                    f"EUR {fmt_tr(d['eur'], 4)}  (%{fmt_tr(d['eur_chg'], 2)})\n"
                    f"Gram altın {fmt_tr(d['gold'], 2)}  (%{fmt_tr(d['gold_chg'], 2)})\n"
                    f"Kaynak: finans.truncgil.com · veri saati {d['updated']}")
        if key == "wx" and "t" in d:
            return (f"{self.s['city']}: {d['t']:.0f}° ({WMO.get(d['code'], '')}), hissedilen {d['feel']:.0f}°\n"
                    f"Bugün en düşük {d['min']:.0f}° / en yüksek {d['max']:.0f}°, rüzgâr {d['wind']:.0f} km/sa\n"
                    f"Kaynak: open-meteo.com · {at}")
        if key == "sys" and d:
            return f"CPU %{d['cpu']:.0f}\nRAM {d['ram_used']:.1f} / {d['ram_total']:.1f} GB"
        return d.get("err", "")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.pos())
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press and e.buttons() & Qt.LeftButton:
            d = e.globalPosition().toPoint() - self._press[0]
            if self._dragging or d.manhattanLength() > 4:
                self._dragging = True
                self.move(self._press[1] + d)
            return
        k = self.key_at(e.position())
        QToolTip.showText(e.globalPosition().toPoint(), self.tooltip(k) if k else "", self)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._press:
            return
        if self._dragging:
            self.s["pos"] = [self.geometry().center().x(), self.y()]
            save_settings(self.s)
        elif self.key_at(e.position()) == "claude":
            webbrowser.open("https://claude.ai/settings/usage")
        else:
            self.refresh_all()
        self._press, self._dragging = None, False

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Yenile", self.refresh_all)
        m.addAction("Konumu sıfırla", self.reset_pos)
        m.addSeparator()
        m.addAction("Kapat", QApplication.quit)
        m.exec(e.globalPos())

    def reset_pos(self):
        self.s["pos"] = None
        save_settings(self.s)
        self.place()


def render_preview(out):
    """Başsız önizleme: gerçek veriyi çekip şeridi sahte bir duvar kâğıdı üstünde PNG yapar."""
    s = load_settings()
    w = Serit(s)
    psutil.cpu_percent(None)
    time.sleep(0.5)
    for k, fn in (("claude", fetch_claude), ("fx", fetch_fx), ("wx", lambda: fetch_wx(s)), ("sys", fetch_sys)):
        try:
            v = fn()
        except Exception as e:
            v = {"err": str(e)}
        v["at"] = time.time()
        w.on_data(k, v)
    dpr = 2.0
    bw, bh = w.width() + 120, H + 70
    img = QImage(int(bw * dpr), int(bh * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    p = QPainter(img)
    g = QLinearGradient(0, 0, bw, bh)
    g.setColorAt(0, QColor(58, 84, 120))
    g.setColorAt(0.5, QColor(96, 120, 140))
    g.setColorAt(1, QColor(150, 140, 120))
    p.fillRect(QRectF(0, 0, bw, bh), g)
    p.end()
    w.render(img, QPoint(60, 35))
    img.save(out)
    print(out, w.width(), "x", H)


def main():
    if "--preview" in sys.argv:
        app = QApplication(sys.argv)
        render_preview(sys.argv[sys.argv.index("--preview") + 1])
        return
    app = QApplication(sys.argv)
    lock = QLockFile(str(APP_DIR / "serit.lock"))
    if not lock.tryLock(100):
        return  # zaten açık
    app.setQuitOnLastWindowClosed(False)
    w = Serit(load_settings())
    w.place()
    w.show()
    w.start_timers()
    log("başladı")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
