# Şerit (v2): Lumabar benzeri, masaüstünün altına yerleşen cam dock.
# Özellikler:
# 1. Görev Çubuğu Modu: Çalışan pencereleri simge olarak gösterir, tıklandığında ön plana getirir.
# 2. Windows Görev Çubuğu Yönetimi: Başladığında görev çubuğunu otomatik-gizlemeye alır, kapanırken eski haline döndürür.
# 3. Lumabar Tarzı Cam Görünüm: Yarı saydam siyah cam zemin, buzlu kartlar, dolum çubukları.
# 4. Detaylı Açılır Paneller (Pencere tıklama, Claude detay, Kur detay).
# 5. Güvenlik: Claude Code girişini SADECE okur (~/.claude/.credentials.json).

import sys, json, time, threading, ctypes, ctypes.wintypes as w
import datetime as dt
from pathlib import Path

import httpx, psutil
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPoint, QLockFile
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QPainterPath, QPen, QGuiApplication, QImage)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QDialog,
                               QVBoxLayout, QLabel, QPushButton, QFrame)

# --- Win32 API ---
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
dwmapi = ctypes.windll.dwmapi

class APPBARDATA(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('hWnd', w.HWND), ('uCallbackMessage', w.UINT),
                ('uEdge', w.UINT), ('rc', w.RECT), ('lParam', w.LPARAM)]

ABM_GETSTATE = 0x00000004
ABM_SETSTATE = 0x0000000A
ABS_AUTOHIDE = 0x00000001
DWMWA_CLOAKED = 14
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_RESTORE = 9
SW_SHOW = 5

def set_taskbar_autohide(enable=True):
    try:
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        abd.lParam = ABS_AUTOHIDE if enable else 0
        shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))
    except Exception as e:
        log(f"taskbar autohide error: {e}")

def get_running_windows():
    wins = []
    def enum_cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title or title in ("Program Manager", "Settings", "Şerit", "Windows Input Experience"):
            return True
        cloaked = w.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value != 0:
            return True
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
            return True
        wins.append({"hwnd": hwnd, "title": title, "active": user32.GetForegroundWindow() == hwnd})
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return wins

def activate_window(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetForegroundWindow(hwnd)

# --- Uygulama Sabitleri ---
APP_DIR = Path(__file__).resolve().parent
SETTINGS = APP_DIR / "settings.json"
LOG = APP_DIR / "serit.log"
CRED = Path.home() / ".claude" / ".credentials.json"
DEFAULTS = {"city": "Aksaray", "lat": 38.37, "lon": 34.03, "pos": None, "autohide_taskbar": True}

H = 46  # Lumabar tarzı ferah dock
PAD_X, SEG_GAP = 12, 10
BG_GLASS = QColor(14, 16, 22, 230)
CARD_BG = QColor(255, 255, 255, 14)
CARD_BORDER = QColor(255, 255, 255, 28)
TXT, MUTED = QColor(240, 244, 250), QColor(150, 160, 178)
ACCENT_PURPLE = QColor(168, 85, 247)
AMBER, RED, GREEN = QColor(255, 196, 92), QColor(255, 110, 110), QColor(120, 220, 150)

WMO = {0: "Açık", 1: "Az bulutlu", 2: "Parçalı bulutlu", 3: "Kapalı", 45: "Sis", 48: "Sis",
       51: "Çisenti", 61: "Yağmur", 71: "Kar", 80: "Sağanak", 95: "Fırtına"}

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

def tr_num(s):
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

# --- Veri Kaynakları ---
def fetch_claude():
    try:
        c = json.loads(CRED.read_text(encoding="utf-8"))["claudeAiOauth"]
    except (OSError, ValueError, KeyError):
        return {"err": "Claude Code girişi yok"}
    if c.get("expiresAt", 0) / 1000 < time.time():
        return {"err": "Giriş süresi doldu"}
    r = httpx.get("https://api.anthropic.com/api/oauth/usage", timeout=15,
                  headers={"Authorization": "Bearer " + c["accessToken"],
                           "anthropic-beta": "oauth-2025-04-20"})
    if r.status_code != 200:
        return {"err": f"Hata {r.status_code}"}
    j = r.json()
    fh, sd = j.get("five_hour") or {}, j.get("seven_day") or {}
    return {"s": fh.get("utilization"), "s_reset": fh.get("resets_at"),
            "w": sd.get("utilization"), "w_reset": sd.get("resets_at"),
            "plan": c.get("subscriptionType", "Max")}

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
            except Exception as e:
                log(f"{key}: {type(e).__name__}: {e}")
                val = {"err": "bağlantı yok"}
            if isinstance(val, dict):
                val["at"] = time.time()
            self.got.emit(key, val)
        threading.Thread(target=work, daemon=True).start()

# --- Popover ---
class Popover(QDialog):
    def __init__(self, parent, title, body_text):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: rgba(22, 26, 36, 245);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 12px;
            }
            QLabel { color: #e8ecf1; font-family: 'Segoe UI Variable Text'; }
        """)
        blayout = QVBoxLayout(box)
        lbl_title = QLabel(f"<b>{title}</b>")
        lbl_title.setStyleSheet("font-size: 13px; color: #a855f7;")
        blayout.addWidget(lbl_title)
        lbl_body = QLabel(body_text)
        lbl_body.setStyleSheet("font-size: 11px; line-height: 1.4;")
        blayout.addWidget(lbl_body)
        btn_close = QPushButton("Kapat")
        btn_close.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,20); border: none; border-radius: 6px; color: white; padding: 4px 10px; }
            QPushButton:hover { background: rgba(255,255,255,35); }
        """)
        btn_close.clicked.connect(self.close)
        blayout.addWidget(btn_close, 0, Qt.AlignRight)
        layout.addWidget(box)

# --- Şerit Dock ---
class SeritDock(QWidget):
    def __init__(self, settings):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.s = settings
        self.data = {"claude": None, "fx": None, "wx": None, "sys": None}
        self.windows = []
        
        self.f_title = QFont("Segoe UI Variable Text", 8)
        self.f_main = QFont("Segoe UI Variable Text", 10, QFont.Bold)
        self.f_small = QFont("Segoe UI Variable Text", 8)
        
        self.hits = []
        self._press, self._dragging = None, False
        self.feeder = Feeder()
        self.feeder.got.connect(self.on_data)
        
        if self.s.get("autohide_taskbar", True):
            set_taskbar_autohide(True)
            
        self.start_timers()
        self.relayout()

    def closeEvent(self, event):
        if self.s.get("autohide_taskbar", True):
            set_taskbar_autohide(False)
        event.accept()

    def start_timers(self):
        for key, fn, sec in (("claude", fetch_claude, 120), ("fx", fetch_fx, 300),
                             ("wx", lambda: fetch_wx(self.s), 900)):
            t = QTimer(self, interval=sec * 1000)
            t.timeout.connect(lambda k=key, f=fn: self.feeder.run(k, f))
            t.start()
            self.feeder.run(key, fn)
            
        psutil.cpu_percent(None)
        t_sys = QTimer(self, interval=2000)
        t_sys.timeout.connect(lambda: self.on_data("sys", fetch_sys()))
        t_sys.start()
        
        t_win = QTimer(self, interval=1500)
        t_win.timeout.connect(self.update_windows)
        t_win.start()
        self.update_windows()

    def update_windows(self):
        self.windows = get_running_windows()
        self.relayout()

    def on_data(self, key, val):
        self.data[key] = val
        self.relayout()

    def relayout(self):
        w_claude = 135
        w_fx = 185
        w_wins = max(40, len(self.windows) * 36 + 10)
        w_wx_sys = 140
        w_clock = 75
        
        total_w = PAD_X * 2 + w_claude + w_fx + w_wins + w_wx_sys + w_clock + 4 * SEG_GAP
        if total_w != self.width():
            cx = self.geometry().center().x() if self.isVisible() else None
            self.resize(total_w, H)
            if cx is not None:
                self.move(cx - total_w // 2, self.y())
            else:
                self.place()
        self.update()

    def place(self):
        p = self.s.get("pos")
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if p:
            self.move(p[0] - self.width() // 2, p[1])
        else:
            self.move(scr.center().x() - self.width() // 2, scr.bottom() - H - 8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        r_dock = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path_dock = QPainterPath()
        path_dock.addRoundedRect(r_dock, 16, 16)
        p.fillPath(path_dock, BG_GLASS)
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        p.drawPath(path_dock)

        x = PAD_X
        self.hits = []

        x = self.draw_card_claude(p, x) + SEG_GAP
        x = self.draw_card_fx(p, x) + SEG_GAP
        x = self.draw_wins_dock(p, x) + SEG_GAP
        x = self.draw_card_wx_sys(p, x) + SEG_GAP
        self.draw_card_clock(p, x)
        p.end()

    def draw_card(self, p, x, w):
        r = QRectF(x, (H - 34) / 2, w, 34)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, CARD_BG)
        p.setPen(QPen(CARD_BORDER, 1))
        p.drawPath(path)
        return r

    def draw_card_claude(self, p, x):
        w = 135
        r = self.draw_card(p, x, w)
        self.hits.append((r, "claude"))
        
        r_icon = QRectF(x + 5, r.y() + 5, 24, 24)
        p.fillPath(self.round_rect_path(r_icon, 5), QColor(217, 119, 6, 200))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.setPen(Qt.white)
        p.drawText(r_icon, Qt.AlignCenter, "C")

        c = self.data["claude"]
        if c is None or c.get("err"):
            p.setFont(self.f_small)
            p.setPen(AMBER if c else MUTED)
            p.drawText(QRectF(x + 34, r.y(), w - 38, 34), Qt.AlignVCenter, c["err"] if c else "Yükleniyor...")
            return x + w

        p.setFont(self.f_title)
        p.setPen(MUTED)
        p.drawText(int(x) + 34, int(r.y()) + 12, "Oturum")
        
        p.setFont(self.f_main)
        p.setPen(self.level(c["s"]))
        p.drawText(int(x) + 34, int(r.y()) + 27, f"%{c['s']:.0f}")

        left_str = left_text(c["s_reset"])
        p.setFont(self.f_small)
        p.setPen(MUTED)
        p.drawText(QRectF(x + 75, r.y() + 2, 52, 14), Qt.AlignRight, left_str)

        r_bar = QRectF(x + 75, r.y() + 18, 52, 4)
        self.draw_mini_bar(p, r_bar, c["s"] / 100)
        return x + w

    def draw_card_fx(self, p, x):
        w = 185
        r = self.draw_card(p, x, w)
        self.hits.append((r, "fx"))

        f = self.data["fx"]
        if not f or f.get("err"):
            p.setFont(self.f_small)
            p.setPen(AMBER if f else MUTED)
            p.drawText(QRectF(x + 8, r.y(), w - 16, 34), Qt.AlignVCenter, f["err"] if f else "Kurlar...")
            return x + w

        items = [("$", f["usd"], f["usd_chg"], 2), ("€", f["eur"], f["eur_chg"], 2), ("G.Altın", f["gold"], f["gold_chg"], 0)]
        curr_x = x + 8
        for sym, val, chg, dec in items:
            p.setFont(self.f_title)
            p.setPen(MUTED)
            p.drawText(int(curr_x), int(r.y()) + 12, sym)

            p.setFont(self.f_small)
            p.setPen(TXT)
            val_str = fmt_tr(val, dec)
            p.drawText(int(curr_x), int(r.y()) + 26, val_str)

            p.setPen(GREEN if chg > 0 else (RED if chg < 0 else MUTED))
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "•")
            p.drawText(int(curr_x + QFontMetricsF(self.f_small).horizontalAdvance(val_str) + 2), int(r.y()) + 26, arrow)

            curr_x += 58
        return x + w

    def draw_wins_dock(self, p, x):
        w = max(40, len(self.windows) * 36 + 10)
        r = QRectF(x, (H - 34) / 2, w, 34)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, QColor(0, 0, 0, 40))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawPath(path)

        curr_x = x + 6
        for win in self.windows:
            r_icon = QRectF(curr_x, r.y() + 3, 28, 28)
            self.hits.append((r_icon, f"win_{win['hwnd']}"))

            if win["active"]:
                p.fillPath(self.round_rect_path(r_icon, 6), QColor(255, 255, 255, 30))

            char = win["title"][0].upper() if win["title"] else "W"
            p.fillPath(self.round_rect_path(QRectF(curr_x + 3, r.y() + 6, 22, 22), 5), ACCENT_PURPLE if win["active"] else QColor(60, 65, 80))
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.setPen(Qt.white)
            p.drawText(QRectF(curr_x + 3, r.y() + 6, 22, 22), Qt.AlignCenter, char)

            if win["active"]:
                p.setBrush(ACCENT_PURPLE)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPoint(int(curr_x) + 14, int(r.y()) + 31), 2, 2)

            curr_x += 36
        return x + w

    def draw_card_wx_sys(self, p, x):
        w = 140
        r = self.draw_card(p, x, w)
        self.hits.append((r, "wx_sys"))

        wx, sys_d = self.data["wx"], self.data["sys"]
        
        p.setFont(self.f_main)
        p.setPen(TXT)
        if wx and "t" in wx:
            p.drawText(int(x) + 8, int(r.y()) + 22, f"{wx['t']:.0f}°")
            p.setFont(self.f_title)
            p.setPen(MUTED)
            p.drawText(int(x) + 30, int(r.y()) + 20, self.s["city"])

        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.drawLine(int(x) + 72, int(r.y()) + 6, int(x) + 72, int(r.y()) + 28)

        if sys_d:
            p.setFont(self.f_title)
            p.setPen(MUTED)
            p.drawText(int(x) + 78, int(r.y()) + 12, "CPU")
            p.setFont(self.f_small)
            p.setPen(self.level(sys_d["cpu"], 85, 95))
            p.drawText(int(x) + 102, int(r.y()) + 12, f"%{sys_d['cpu']:.0f}")

            p.setFont(self.f_title)
            p.setPen(MUTED)
            p.drawText(int(x) + 78, int(r.y()) + 26, "RAM")
            p.setFont(self.f_small)
            p.setPen(self.level(sys_d["ram"], 85, 95))
            p.drawText(int(x) + 102, int(r.y()) + 26, f"%{sys_d['ram']:.0f}")

        return x + w

    def draw_card_clock(self, p, x):
        w = 75
        r = self.draw_card(p, x, w)
        self.hits.append((r, "clock"))

        now = dt.datetime.now()
        p.setFont(QFont("Segoe UI Variable Text", 10, QFont.Bold))
        p.setPen(TXT)
        p.drawText(QRectF(x, r.y() + 2, w, 16), Qt.AlignCenter, now.strftime("%H:%M"))

        p.setFont(self.f_title)
        p.setPen(MUTED)
        p.drawText(QRectF(x, r.y() + 18, w, 12), Qt.AlignCenter, now.strftime("%d %b %a"))
        return x + w

    def draw_mini_bar(self, p, r, frac):
        frac = max(0.0, min(1.0, frac or 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 25))
        p.drawRoundedRect(r, 2, 2)
        if frac > 0:
            fill = QRectF(r.x(), r.y(), max(2, r.width() * frac), r.height())
            p.setBrush(GREEN if frac < 0.8 else (AMBER if frac < 0.95 else RED))
            p.drawRoundedRect(fill, 2, 2)

    def round_rect_path(self, r, radius):
        p = QPainterPath()
        p.addRoundedRect(r, radius, radius)
        return p

    def level(self, v, warn=80, crit=95):
        return RED if v >= crit else (AMBER if v >= warn else TXT)

    def key_at(self, pos):
        for r, k in self.hits:
            if r.contains(pos):
                return k
        return None

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

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._press:
            return
        if self._dragging:
            self.s["pos"] = [self.geometry().center().x(), self.y()]
            save_settings(self.s)
        else:
            k = self.key_at(e.position())
            if k:
                self.handle_click(k)
        self._press, self._dragging = None, False

    def handle_click(self, key):
        if key.startswith("win_"):
            hwnd = int(key.split("_")[1])
            activate_window(hwnd)
            self.update_windows()
        elif key == "claude":
            c = self.data["claude"] or {}
            msg = f"<b>Plan:</b> {c.get('plan', 'Max')}<br><br>" \
                  f"<b>Oturum (5sa):</b> %{c.get('s',0):.0f} ({left_text(c.get('s_reset'))} kaldı)<br>" \
                  f"<b>Haftalık:</b> %{c.get('w',0):.0f} ({left_text(c.get('w_reset'))} kaldı)<br><br>" \
                  f"<i>Kaynak: Anthropic API (Claude Code girişi)</i>"
            pop = Popover(self, "Claude Kullanım Detayı", msg)
            pop.move(self.x() + 10, self.y() - 120)
            pop.exec()
        elif key == "fx":
            f = self.data["fx"] or {}
            msg = f"<b>USD:</b> {fmt_tr(f.get('usd',0),4)} TL (%{fmt_tr(f.get('usd_chg',0),2)})<br>" \
                  f"<b>EUR:</b> {fmt_tr(f.get('eur',0),4)} TL (%{fmt_tr(f.get('eur_chg',0),2)})<br>" \
                  f"<b>Gram Altın:</b> {fmt_tr(f.get('gold',0),2)} TL (%{fmt_tr(f.get('gold_chg',0),2)})<br><br>" \
                  f"<i>Veri saati: {f.get('updated','-')}</i>"
            pop = Popover(self, "Piyasa Detayı", msg)
            pop.move(self.x() + 120, self.y() - 130)
            pop.exec()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Yenile", lambda: self.update_windows())
        act_th = m.addAction("Windows Görev Çubuğunu Gizle", lambda: self.toggle_autohide())
        act_th.setCheckable(True)
        act_th.setChecked(self.s.get("autohide_taskbar", True))
        m.addAction("Konumu Sıfırla", self.reset_pos)
        m.addSeparator()
        m.addAction("Kapat", QApplication.quit)
        m.exec(e.globalPos())

    def toggle_autohide(self):
        cur = not self.s.get("autohide_taskbar", True)
        self.s["autohide_taskbar"] = cur
        save_settings(self.s)
        set_taskbar_autohide(cur)

    def reset_pos(self):
        self.s["pos"] = None
        save_settings(self.s)
        self.place()

def render_preview(out):
    QApplication(sys.argv)
    s = load_settings()
    w = SeritDock(s)
    w.data["claude"] = {"s": 34, "w": 12, "s_reset": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2, minutes=15)).isoformat(), "plan": "Max"}
    w.data["fx"] = {"usd": 49.75, "usd_chg": 0.14, "eur": 55.77, "eur_chg": 0.10, "gold": 6424.0, "gold_chg": 0.62}
    w.data["wx"] = {"t": 23.0, "code": 1}
    w.data["sys"] = {"cpu": 18.0, "ram": 42.0}
    w.windows = [
        {"hwnd": 1, "title": "GarantiBBVA_Performans_IAS", "active": True},
        {"hwnd": 2, "title": "Chrome - Lumabar", "active": False},
        {"hwnd": 3, "title": "The Mentalist S02E13", "active": False},
        {"hwnd": 4, "title": "Hermes Desktop", "active": False}
    ]
    w.relayout()
    
    bw, bh = w.width() + 80, H + 60
    img = QImage(int(bw * 2), int(bh * 2), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    p = QPainter(img)
    g = QLinearGradient(0, 0, bw, bh)
    g.setColorAt(0, QColor(30, 35, 45))
    g.setColorAt(1, QColor(15, 18, 24))
    p.fillRect(QRectF(0, 0, bw, bh), g)
    p.end()
    
    w.render(img, QPoint(40, 30))
    img.save(out)
    print(out, w.width(), "x", H)

def main():
    if "--preview" in sys.argv:
        render_preview(sys.argv[sys.argv.index("--preview") + 1])
        return
    app = QApplication(sys.argv)
    lock = QLockFile(str(APP_DIR / "serit.lock"))
    if not lock.tryLock(100):
        return
    app.setQuitOnLastWindowClosed(False)
    w = SeritDock(load_settings())
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

