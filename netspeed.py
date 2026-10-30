"""Şerit ağ hızı ölçer ve gösterge çubuğu (v26 Modül A).

Psutil ağ sayaçlarını sorgular, hız türetir ve görev çubuğu üzerinde
iki satırlı kompakt hız göstergesini (↓ indirme, ↑ yükleme) çizer.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import psutil
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402
import theme  # noqa: E402

SHOW_THRESHOLD = 50_000.0  # 50 KB/s
HIDE_THRESHOLD = 30_000.0  # 30 KB/s

EXCLUDED_NIC_SUBSTRINGS = (
    "loopback",
    "vethernet",
    "virtualbox",
    "vmware",
    "hyper-v",
    "bluetooth",
    "teredo",
    "isatap",
    "pseudo",
    "wsl",
)


def is_virtual_or_loopback(nic_name: str) -> bool:
    """Sanal / yerel ağ arayüzlerini filtreler."""
    low = nic_name.lower()
    return any(sub in low for sub in EXCLUDED_NIC_SUBSTRINGS)


def fmt_rate(bps: Optional[float | int]) -> str:
    """Bayt/sn hızını Türkçe standartta formatlar (1 KB = 1000 B).

    - None -> '—'
    - < 1 MB/s -> 'NNN KB/s' (tam sayı, min 0)
    - >= 1 MB/s -> '1,4 MB/s' (tek ondalık, virgül)
    - >= 100 MB/s -> '123 MB/s' (ondalıksız)
    """
    if bps is None:
        return "—"
    try:
        val_f = float(bps)
    except (ValueError, TypeError):
        return "—"

    if val_f < 0:
        return "0 KB/s"
    if val_f < 1_000_000.0:
        val_kb = int(round(val_f / 1000.0))
        if val_kb < 1000:
            return f"{val_kb} KB/s"
        return "1,0 MB/s"

    val_mb = val_f / 1_000_000.0
    if val_mb >= 100.0:
        return f"{int(round(val_mb))} MB/s"
    s = f"{val_mb:.1f}".replace(".", ",")
    return f"{s} MB/s"


_below_count_fallback: int = 0


def should_show(state: Optional[Dict[str, Any]], was_visible: bool) -> bool:
    """Histerezis görünürlük kararı:

    - Görünmezken: max(down, up) >= 50 KB/s olduğunda görünür olur.
    - Görünürken: hız peş peşe 3 örnek boyunca 30 KB/s altında kalırsa gizlenir.

    Peş peşe 30 KB/s altı örnek sayacı state['below_count'] ve _below_count_fallback
    üzerinde tutulur.
    """
    global _below_count_fallback
    if not state:
        _below_count_fallback = 0
        return False

    down = state.get("down")
    up = state.get("up")
    max_rate = max(down or 0.0, up or 0.0)

    count = state.get("below_count")
    if count is None:
        count = _below_count_fallback

    if not was_visible:
        if max_rate >= SHOW_THRESHOLD:
            count = 0
            res = True
        else:
            count = 0
            res = False
    else:
        if max_rate >= HIDE_THRESHOLD:
            count = 0
            res = True
        else:
            count += 1
            if count >= 3:
                res = False
            else:
                res = True

    _below_count_fallback = count
    try:
        state["below_count"] = count
    except Exception:
        pass
    return res


def band_width(state: Optional[Dict[str, Any]]) -> float:
    """En kötü durum dizgilerinden ('↓ 999 KB/s' / '↓ 99,9 MB/s') ölçülmüş SABİT genişlik.

    Görünmüyorken 0.0 döner; görünürken genişlik hız değerine göre zıplamaz.
    """
    if not state or state.get("visible") is False:
        return 0.0
    if state.get("visible") is None and state.get("down") is None and state.get("up") is None:
        return 0.0

    f = theme.make_font(10.0, QFont.Weight.Normal, tabular=True)
    fm = QFontMetricsF(f)
    w1 = fm.horizontalAdvance("↓ 999 KB/s")
    w2 = fm.horizontalAdvance("↓ 99,9 MB/s")
    w3 = fm.horizontalAdvance("↑ 999 KB/s")
    w4 = fm.horizontalAdvance("↑ 99,9 MB/s")
    return float(math.ceil(max(w1, w2, w3, w4)) + 4.0)


def draw_net_band(p: QPainter, rect: QRectF, state: Optional[Dict[str, Any]], hover: bool = False) -> None:
    """Görev çubuğu ağ hızı bandını çizer:

    İki satır (üstte ↓ indirme, altta ↑ yükleme), 10 px yazı, oklar mavi (#6EA8FE),
    değerler beyaz %85 (TEXT_BODY). capHeight kullanılarak rect merkezine dikey ortalanır.
    """
    if not state or state.get("visible") is False:
        return
    if state.get("visible") is None and state.get("down") is None and state.get("up") is None:
        return

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    if hover:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(rect.adjusted(-3.0, 0.0, 3.0, 0.0), 6.0, 6.0)

    f = theme.make_font(10.0, QFont.Weight.Normal, tabular=True)
    fm = QFontMetricsF(f)
    cap = fm.capHeight()
    gap = 2.0
    total_h = cap * 2.0 + gap
    top = rect.center().y() - total_h / 2.0
    base_down = top + cap
    base_up = base_down + gap + cap

    x = rect.left()
    col_arrow = ps.ACCENT
    col_text = ps.TEXT if hover else ps.TEXT_BODY

    p.setFont(f)

    # Üst satır: ↓
    down_rate = state.get("down")
    down_str = fmt_rate(down_rate)
    p.setPen(col_arrow)
    p.drawText(QPointF(x, base_down), "↓")
    arrow_w = max(fm.horizontalAdvance("↓ "), fm.horizontalAdvance("↑ "))
    p.setPen(col_text)
    p.drawText(QPointF(x + arrow_w, base_down), down_str)

    # Alt satır: ↑
    up_rate = state.get("up")
    up_str = fmt_rate(up_rate)
    p.setPen(col_arrow)
    p.drawText(QPointF(x, base_up), "↑")
    p.setPen(col_text)
    p.drawText(QPointF(x + arrow_w, base_up), up_str)

    p.restore()


def tooltip(state: Optional[Dict[str, Any]]) -> str:
    """Ağ hızı ipucu metni."""
    st = state or {}
    down_s = fmt_rate(st.get("down"))
    up_s = fmt_rate(st.get("up"))
    return f"İndirme: {down_s}\nYükleme: {up_s}\nKaynak: Windows ağ sayaçları (psutil), 2 sn"


class NetSpeedMeter:
    """2 saniyede bir psutil ağ sayaçlarını okuyup indirme/yükleme hızlarını hesaplar."""

    def __init__(
        self,
        counters_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        clock: Optional[Callable[[], float]] = None,
        stats_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self._counters_fn = counters_fn or (lambda: psutil.net_io_counters(pernic=True))
        self._clock = clock or time.monotonic
        self._stats_fn = stats_fn or psutil.net_if_stats
        self._last_counters: Optional[Tuple[int, int]] = None
        self._last_t: Optional[float] = None
        self._below_count: int = 0
        self._visible: bool = False

    def sample(self) -> Dict[str, Any]:
        """İş parçacığından çağrılır: {'down': B/s|None, 'up': B/s|None, 't': mono} döner."""
        now = self._clock()
        try:
            counters = self._counters_fn()
        except Exception:
            counters = None

        if not counters:
            return {
                "down": None,
                "up": None,
                "t": now,
                "visible": False,
                "below_count": self._below_count,
            }

        stats = None
        if self._stats_fn:
            try:
                stats = self._stats_fn()
            except Exception:
                stats = None

        total_recv = 0
        total_sent = 0
        for nic_name, c in counters.items():
            if is_virtual_or_loopback(nic_name):
                continue
            if stats and nic_name in stats:
                stat = stats[nic_name]
                isup = getattr(stat, "isup", True)
                if not isup:
                    continue

            if hasattr(c, "bytes_recv") and hasattr(c, "bytes_sent"):
                total_recv += int(c.bytes_recv)
                total_sent += int(c.bytes_sent)
            elif isinstance(c, (list, tuple)) and len(c) >= 2:
                # psutil snetio order: bytes_sent (0), bytes_recv (1)
                total_sent += int(c[0])
                total_recv += int(c[1])
            elif isinstance(c, dict):
                total_recv += int(c.get("bytes_recv", 0))
                total_sent += int(c.get("bytes_sent", 0))

        if self._last_counters is None or self._last_t is None:
            self._last_counters = (total_recv, total_sent)
            self._last_t = now
            return {
                "down": None,
                "up": None,
                "t": now,
                "visible": False,
                "below_count": 0,
            }

        dt = now - self._last_t
        prev_recv, prev_sent = self._last_counters
        self._last_counters = (total_recv, total_sent)
        self._last_t = now

        delta_recv = total_recv - prev_recv
        delta_sent = total_sent - prev_sent

        if dt <= 0 or delta_recv < 0 or delta_sent < 0:
            return {
                "down": None,
                "up": None,
                "t": now,
                "visible": False,
                "below_count": self._below_count,
            }

        down = delta_recv / dt
        up = delta_sent / dt

        max_rate = max(down, up)
        if not self._visible:
            if max_rate >= SHOW_THRESHOLD:
                self._visible = True
                self._below_count = 0
            else:
                self._below_count = 0
        else:
            if max_rate >= HIDE_THRESHOLD:
                self._below_count = 0
            else:
                self._below_count += 1
                if self._below_count >= 3:
                    self._visible = False

        return {
            "down": down,
            "up": up,
            "t": now,
            "visible": self._visible,
            "below_count": self._below_count,
        }
