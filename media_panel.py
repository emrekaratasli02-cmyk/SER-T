"""Şerit Medya Mini-Popover Paneli (v30) — panel_style v2 ortak kiti üzerinde (352 px).

Özellikler:
  1. Başlık: 'Şimdi Çalıyor' + etkileşimli uygulama rozeti ('Spotify ›' / 'Chrome ›') + kapat ×.
  2. Şarkı / Video Kartı:
     - Solda 64×64 yüksek çözünürlüklü yuvarlatılmış albüm/video kapağı (yoksa 5-bar ekolayzır yuvası).
     - Sağda 2 satıra kadar tam başlık, sanatçı/kanal adı ve durum rozeti (ÇALIYOR / DURAKLATILDI).
     - Altta etkileşimli sarma çubuğu (seekbar — tıklama ve sürükleme destekli) + sol/sağ süre ('02:22' / '04:05').
     - Ortada 5 kontrol düğmesi: 10 sn geri ('-10s'), Önceki ('⏮'), Oynat/Duraklat (ambient renkli 44px daire), Sonraki ('⏭'), 10 sn ileri ('+10s').
  3. Ses & Çıkış Kartı:
     - Üstte 'SES VE ÇIKIŞ' başlığı ve sağda ses çıkış cihazı ('Hoparlör ›' -> tıklayınca Ses Mikseri açılır).
     - Altta sessiz düğmesi + etkileşimli ses sürgüsü (tekerlek ve sürükleme destekli).
  4. Alt bilgi: Kaynak ('Windows medya oturumu') + 'Uygulamayı aç' düğmesi.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import panel_style as ps  # noqa: E402
import dock_cards  # noqa: E402

try:
    import winapi  # noqa: E402
except Exception:  # pragma: no cover
    winapi = None

try:
    from volume_panel import draw_speaker_icon as _draw_speaker_icon  # noqa: E402
except Exception:  # pragma: no cover
    _draw_speaker_icon = None

try:
    import media  # noqa: E402
except Exception:  # pragma: no cover
    media = None


def list_output_devices(active_only: bool = True) -> list[Dict[str, Any]]:
    """Ses cikis cihazlarini ve aktif varsayilani dondurur."""
    import os
    if os.environ.get("SERIT_TEST") == "1":
        return [
            {"id": "{0.0.0.00000000}.{realtek_mock}", "name": "Speakers (Realtek(R) Audio)", "default": True},
            {"id": "{0.0.0.00000000}.{airpods_mock}", "name": "Headphones (AirPods)", "default": False},
        ]
    if media is not None and hasattr(media, "list_output_devices"):
        try:
            devs = media.list_output_devices(active_only=active_only)
            if devs:
                return [dict(d) for d in devs]
        except Exception:
            pass
    return []


def set_default_output_device(device_id: str) -> bool:
    """Windows Core Audio IPolicyConfig COM arayuzu ile varsayilan ses cikis uc noktasini ayarlar."""
    import os
    if os.environ.get("SERIT_TEST") == "1" or os.environ.get("SERIT_ALLOW_REAL_AUDIO") != "1":
        return True
    if not device_id:
        return False
    try:
        import ctypes
        import comtypes
        from comtypes import GUID, COMMETHOD, HRESULT, IUnknown
        from ctypes import POINTER, c_int, c_longlong, c_void_p, c_wchar_p
        import comtypes.client as cc

        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        except Exception:
            pass

        CLSID_PolicyConfigClient = GUID('{870af99c-171d-4f9e-af0d-e63df40c2bc9}')

        class IPolicyConfig(IUnknown):
            _iid_ = GUID('{f8679f50-850a-41cf-9c72-430f290290c8}')
            _methods_ = [
                COMMETHOD([], HRESULT, 'GetMixFormat', (['in'], c_wchar_p, 'wszDeviceId'), (['out', 'retval'], POINTER(c_void_p), 'ppwfxFormat')),
                COMMETHOD([], HRESULT, 'GetDeviceFormat', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_int, 'dwFlags'), (['out', 'retval'], POINTER(c_void_p), 'ppwfxFormat')),
                COMMETHOD([], HRESULT, 'ResetDeviceFormat', (['in'], c_wchar_p, 'wszDeviceId')),
                COMMETHOD([], HRESULT, 'SetDeviceFormat', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_void_p, 'pwfxFormat'), (['in'], c_void_p, 'pwfxFormatReq')),
                COMMETHOD([], HRESULT, 'GetProcessingPeriod', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_int, 'dwFlags'), (['out', 'retval'], POINTER(c_longlong), 'phnsDefaultPeriod'), (['out', 'retval'], POINTER(c_longlong), 'phnsMinimumPeriod')),
                COMMETHOD([], HRESULT, 'SetProcessingPeriod', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_longlong, 'hnsPeriod')),
                COMMETHOD([], HRESULT, 'GetShareMode', (['in'], c_wchar_p, 'wszDeviceId'), (['out', 'retval'], POINTER(c_void_p), 'pShareMode')),
                COMMETHOD([], HRESULT, 'SetShareMode', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_void_p, 'pShareMode')),
                COMMETHOD([], HRESULT, 'GetPropertyValue', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_void_p, 'key'), (['out', 'retval'], POINTER(c_void_p), 'pv')),
                COMMETHOD([], HRESULT, 'SetPropertyValue', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_void_p, 'key'), (['in'], c_void_p, 'pv')),
                COMMETHOD([], HRESULT, 'SetDefaultEndpoint', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_int, 'eRole')),
                COMMETHOD([], HRESULT, 'SetEndpointVisibility', (['in'], c_wchar_p, 'wszDeviceId'), (['in'], c_int, 'bVisible')),
            ]

        client = cc.CreateObject(CLSID_PolicyConfigClient, interface=IPolicyConfig)
        hr0 = client.SetDefaultEndpoint(str(device_id), 0)
        hr1 = client.SetDefaultEndpoint(str(device_id), 1)
        return (hr0 == 0 and hr1 == 0)
    except Exception:
        return False


def fmt_mmss(seconds: Any) -> str:
    """Saniyeyi '02:24' veya '1:05:12' biçimine çevirir; geçersizse '—'."""
    if seconds is None:
        return "—"
    try:
        s = int(round(max(0.0, float(seconds))))
    except (TypeError, ValueError):
        return "—"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


class MediaPanel(ps.PopoverBase):
    """Medya kartına tıklandığında açılan zengin kontrol ve ses paneli (352 px)."""

    WIDTH: int = int(ps.PANEL_W)

    control_requested = Signal(str)          # 'prev' | 'playpause' | 'next'
    seek_requested = Signal(float)           # 0.0 .. 1.0
    volume_requested = Signal(float)         # 0.0 .. 100.0
    mute_requested = Signal(bool)            # True | False
    open_mixer_requested = Signal()          # Ses mikseri panelini aç
    open_app_requested = Signal(str)         # Kaynak uygulamayı öne getir (exe/aumid)
    device_switch_requested = Signal(str)    # Ses çıkış cihazını değiştir (device_id)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            activate_on_show=True,
            outside_click_close=False,
            recently_closed_ms=250.0,
        )
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setMouseTracking(True)

        self._media: Dict[str, Any] = {}
        self._vol_level: float = 50.0
        self._vol_muted: bool = False
        self._vol_device: str = ""
        self._devices: list[Dict[str, Any]] = []
        self._active_device_id: str = ""

        self._hover: Optional[str] = None
        self._dragging: Optional[str] = None      # 'seek' | 'vol'
        self._drag_seek_frac: Optional[float] = None

        # Volume wheel coalescer: send pending level after ~150ms idle
        self._vol_pending_level: Optional[float] = None
        self._vol_coalescer_timer = QTimer(self)
        self._vol_coalescer_timer.setSingleShot(True)
        self._vol_coalescer_timer.timeout.connect(self._flush_vol_coalescer)

        self._rects: Dict[str, QRectF] = {}

        # Panel açıkken ilerleme çubuğunu saniyede 2 kez akıcı güncelle
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(500)
        self._live_timer.timeout.connect(self.update)

        self.resize(self.WIDTH, self.compute_height())
        self._layout()

    def _target_pos(self) -> QPoint:
        """Anchor'ın üzerinde ortalanmış, ekran sınırlarına sıkışmış hedef konum."""
        if self._anchor_global is None:
            return QPoint(100, 100)
        tx = int(self._anchor_global.center().x() - self.width() / 2.0)
        ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
        scr = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            dpr = scr.devicePixelRatio()
            m = 8
            tx = max(geo.left() + m, min(geo.right() - self.width() - m, tx))
            if ty < geo.top() + m:
                ty = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
            if ty + self.height() > geo.bottom() - m:
                ty = max(geo.top() + m, geo.bottom() - self.height() - m)
        return QPoint(tx, ty)

    # ------------------------------------------------------------ görünürlük API
    def set_media(self, info: Optional[Dict[str, Any]]) -> None:
        self._media = dict(info) if isinstance(info, dict) else {}
        if self._dragging != "seek":
            self._drag_seek_frac = None
        self._layout()
        self.update()

    def set_volume(
        self,
        level: Optional[float],
        muted: bool = False,
        device: Optional[str] = None,
        devices: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        if level is not None:
            try:
                self._vol_level = max(0.0, min(100.0, float(level)))
            except (TypeError, ValueError):
                pass
        self._vol_muted = bool(muted)
        if device is not None:
            self._vol_device = str(device)
            for d in self._devices:
                if d.get("name") == self._vol_device:
                    self._active_device_id = str(d.get("id", ""))
                    break
        if devices is not None:
            self.set_devices(devices, self._active_device_id or None)
        self._layout()
        self.update()

    def set_devices(self, devices: list[Dict[str, Any]], active_id: Optional[str] = None) -> None:
        """Ses cikis cihazlari listesini kaydeder ve secili olani belirler."""
        self._devices = [dict(d) for d in devices if isinstance(d, dict)]
        if active_id is not None:
            self._active_device_id = str(active_id)
            for d in self._devices:
                if d.get("id") == self._active_device_id:
                    self._vol_device = str(d.get("name") or "")
                    break
        else:
            found = False
            for d in self._devices:
                if d.get("default"):
                    self._active_device_id = str(d.get("id", ""))
                    self._vol_device = str(d.get("name") or "")
                    found = True
                    break
            if not found and self._devices:
                self._active_device_id = str(self._devices[0].get("id", ""))
                self._vol_device = str(self._devices[0].get("name") or "")
        self._layout()
        self.update()

    def refresh_devices(self) -> None:
        """Sistemdeki ses cikis cihazlarini gunceller."""
        try:
            devs = list_output_devices(active_only=True)
            if devs:
                self.set_devices(devs, self._active_device_id or None)
        except Exception:
            pass

    def get_active_device(self) -> Optional[Dict[str, Any]]:
        """Mevcut secili ses cikis cihazini doner."""
        for d in self._devices:
            if d.get("id") == self._active_device_id:
                return d
        if self._devices:
            return self._devices[0]
        return None

    def switch_device(self, delta: int = 1) -> Optional[Dict[str, Any]]:
        """Ses cikis cihazini delta adim kadar degistirir (+1 sonraki, -1 onceki)."""
        if not self._devices:
            self.refresh_devices()
        if not self._devices:
            return None
        if len(self._devices) <= 1:
            return self._devices[0]

        cur_idx = -1
        if self._active_device_id:
            for i, d in enumerate(self._devices):
                if d.get("id") == self._active_device_id:
                    cur_idx = i
                    break
        if cur_idx == -1 and self._vol_device:
            for i, d in enumerate(self._devices):
                if d.get("name") == self._vol_device:
                    cur_idx = i
                    break
        if cur_idx == -1:
            cur_idx = 0

        next_idx = (cur_idx + delta) % len(self._devices)
        target = self._devices[next_idx]
        self._active_device_id = str(target.get("id", ""))
        self._vol_device = str(target.get("name") or "")
        self.device_switch_requested.emit(self._active_device_id)
        set_default_output_device(self._active_device_id)
        self._layout()
        self.update()
        return target

    def set_active_device_by_id(self, dev_id: str) -> bool:
        """Belirtilen ID'ye sahip cihazi varsayilan yapar."""
        for d in self._devices:
            if d.get("id") == dev_id:
                self._active_device_id = str(dev_id)
                self._vol_device = str(d.get("name") or "")
                self.device_switch_requested.emit(self._active_device_id)
                set_default_output_device(self._active_device_id)
                self._layout()
                self.update()
                return True
        return False

    def _live_times(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """(pos_s, dur_s, frac) döner; canlı oynatmada geçen süreyi ekler."""
        m = self._media
        dur = m.get("duration_s")
        pos = m.get("position_s")
        if dur is None:
            return None, None, None
        try:
            dur_f = float(dur)
        except (TypeError, ValueError):
            return None, None, None
        if dur_f <= 0.0:
            return None, None, None
        if self._drag_seek_frac is not None:
            f = max(0.0, min(1.0, float(self._drag_seek_frac)))
            return f * dur_f, dur_f, f
        if pos is None:
            return 0.0, dur_f, 0.0
        try:
            pos_f = float(pos)
        except (TypeError, ValueError):
            pos_f = 0.0
        if m.get("playing") and isinstance(m.get("updated_at"), (int, float)):
            pos_f += max(0.0, time.monotonic() - float(m["updated_at"]))
        pos_f = max(0.0, min(dur_f, pos_f))
        return pos_f, dur_f, pos_f / dur_f

    # ------------------------------------------------------------ yerleşim
    def compute_height(self) -> int:
        # PAD + HEADER(32) + GAP + CARD_TRACK(180) + GAP + CARD_VOL(80) + GAP + FOOTER(32) + PAD
        h = ps.PAD + ps.HEADER_H + ps.GAP + 180.0 + ps.GAP + 80.0 + ps.GAP + ps.FOOTER_H + ps.PAD
        return int(round(h))

    def _layout(self) -> None:
        x0 = ps.PAD
        cw = self.WIDTH - 2 * ps.PAD
        y = ps.PAD
        r: Dict[str, QRectF] = {}

        hdr = QRectF(x0, y, cw, ps.HEADER_H)
        r["hdr"] = hdr
        r["close"] = QRectF(hdr.right() - ps.CLOSE_SZ, hdr.center().y() - ps.CLOSE_SZ / 2.0, ps.CLOSE_SZ, ps.CLOSE_SZ)
        r["app_chip"] = QRectF(hdr.right() - ps.CLOSE_SZ - 8.0 - 96.0, hdr.center().y() - 11.0, 96.0, 22.0)
        y += ps.HEADER_H + ps.GAP

        # 1. Parça / Video kartı (180 px)
        card1_h = 180.0
        c1 = QRectF(x0, y, cw, card1_h)
        r["card_track"] = c1
        in1 = c1.adjusted(ps.CARD_PAD, ps.CARD_PAD, -ps.CARD_PAD, -ps.CARD_PAD)

        # Kapak 64x64
        r["art"] = QRectF(in1.left(), in1.top(), 64.0, 64.0)
        r["meta"] = QRectF(in1.left() + 76.0, in1.top(), in1.width() - 76.0, 64.0)

        # Seekbar (y = in1.top() + 75)
        seek_y = in1.top() + 75.0
        r["seek_hit"] = QRectF(in1.left(), seek_y - 6.0, in1.width(), 18.0)
        r["seek_track"] = QRectF(in1.left(), seek_y, in1.width(), 5.0)
        r["seek_times"] = QRectF(in1.left(), seek_y + 10.0, in1.width(), 16.0)

        # Kontrol düğmeleri (y = in1.bottom() - 24)
        ctrl_cy = in1.bottom() - 24.0
        mid_x = in1.center().x()
        play_d = 44.0
        side_d = 32.0
        step_w = 40.0
        step_h = 26.0
        r["playpause"] = QRectF(mid_x - play_d / 2.0, ctrl_cy - play_d / 2.0, play_d, play_d)
        r["prev"] = QRectF(mid_x - play_d / 2.0 - 14.0 - side_d, ctrl_cy - side_d / 2.0, side_d, side_d)
        r["next"] = QRectF(mid_x + play_d / 2.0 + 14.0, ctrl_cy - side_d / 2.0, side_d, side_d)
        r["back10"] = QRectF(r["prev"].left() - 12.0 - step_w, ctrl_cy - step_h / 2.0, step_w, step_h)
        r["fwd10"] = QRectF(r["next"].right() + 12.0, ctrl_cy - step_h / 2.0, step_w, step_h)

        y += card1_h + ps.GAP

        # 2. Ses ve Çıkış kartı (80 px)
        card2_h = 80.0
        c2 = QRectF(x0, y, cw, card2_h)
        r["card_vol"] = c2
        in2 = c2.adjusted(ps.CARD_PAD, ps.CARD_PAD, -ps.CARD_PAD, -ps.CARD_PAD)

        # Üst satır: SES VE ÇIKIŞ | [‹] [Hoparlör · Realtek] [›] | Mikser ›
        y_top = in2.top() - 2.0
        h_btn = 19.0
        r_right = in2.right()

        w_mix = 44.0
        r["mixer_link"] = QRectF(r_right - w_mix, y_top, w_mix, h_btn)

        w_step = 17.0
        r["dev_next"] = QRectF(r["mixer_link"].left() - 4.0 - w_step, y_top, w_step, h_btn)

        w_chip = 108.0
        r["dev_chip"] = QRectF(r["dev_next"].left() - 4.0 - w_chip, y_top, w_chip, h_btn)

        r["dev_prev"] = QRectF(r["dev_chip"].left() - 4.0 - w_step, y_top, w_step, h_btn)

        vol_row_y = in2.top() + 24.0
        r["mute_btn"] = QRectF(in2.left(), vol_row_y, 28.0, 28.0)
        r["vol_hit"] = QRectF(in2.left() + 36.0, vol_row_y, in2.width() - 36.0 - 42.0, 28.0)
        r["vol_track"] = QRectF(r["vol_hit"].left(), vol_row_y + 11.0, r["vol_hit"].width(), 6.0)
        r["vol_pct"] = QRectF(in2.right() - 38.0, vol_row_y, 38.0, 28.0)

        y += card2_h + ps.GAP

        # 3. Alt bilgi
        fr = QRectF(x0, y, cw, ps.FOOTER_H)
        r["footer"] = fr
        r["open_app"] = QRectF(fr.right() - 110.0, fr.top() + 5.0, 110.0, 22.0)

        self._rects = r

    # ------------------------------------------------------------ görünürlük API
    def _target_pos(self) -> QPoint:
        """Anchor'ın üzerinde ortalanmış, ekran sınırlarına sıkışmış hedef konum."""
        if self._anchor_global is None:
            return QPoint(100, 100)
        tx = int(self._anchor_global.center().x() - self.width() / 2.0)
        ty = int(self._anchor_global.top() - self.height() - ps.ANCHOR_GAP)
        scr = QGuiApplication.screenAt(self._anchor_global.center().toPoint()) or QGuiApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            m = 8
            tx = max(geo.left() + m, min(geo.right() - self.width() - m, tx))
            if ty < geo.top() + m:
                ty = int(self._anchor_global.bottom() + ps.ANCHOR_GAP)
            if ty + self.height() > geo.bottom() - m:
                ty = max(geo.top() + m, geo.bottom() - self.height() - m)
        return QPoint(tx, ty)

    def show_for(
        self,
        anchor_global: Optional[QRectF],
        media_info: Optional[Dict[str, Any]] = None,
        vol_level: Optional[float] = None,
        vol_muted: bool = False,
        vol_device: Optional[str] = None,
        *,
        devices: Optional[list[Dict[str, Any]]] = None,
        switch_from_x: Optional[int] = None,
    ) -> None:
        self._anchor_global = QRectF(anchor_global) if anchor_global is not None else None
        if media_info is not None:
            self._media = dict(media_info)
        if devices is not None:
            self.set_devices(devices)
        elif not self._devices:
            self.refresh_devices()
        if vol_level is not None:
            self.set_volume(vol_level, vol_muted, vol_device)
        self.resize(self.WIDTH, self.compute_height())
        self._layout()

        dpr = 1.0
        if self._anchor_global is not None:
            screen = QGuiApplication.screenAt(self._anchor_global.center().toPoint())
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is not None:
                dpr = screen.devicePixelRatio()

        if winapi is not None and hasattr(winapi, "set_round_region"):
            try:
                winapi.set_round_region(int(self.winId()), self.width(), self.height(), int(ps.R_PANEL), dpr)
            except Exception:
                pass

        self._live_timer.start()
        self._animate_in(switch_from_x)


    def hide_animated(self, on_done: Optional[Callable[[], None]] = None) -> None:
        if not self.isVisible() or self._is_closing:
            return
        self._live_timer.stop()
        self._vol_coalescer_timer.stop()
        self._vol_pending_level = None
        super().hide_animated(on_done=on_done)

    def hide_instant(self) -> None:
        self._live_timer.stop()
        self._vol_coalescer_timer.stop()
        self._vol_pending_level = None
        super().hide_instant()

    # ------------------------------------------------------------ etkileşim
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self.control_requested.emit("playpause")
            event.accept()
            return
        super().keyPressEvent(event)

    def _hit(self, pos: QPointF) -> Optional[str]:
        for key in (
            "close", "app_chip", "playpause", "prev", "next", "back10", "fwd10",
            "seek_hit", "dev_prev", "dev_chip", "dev_next", "mixer_link",
            "mute_btn", "vol_hit", "open_app",
        ):
            r = self._rects.get(key)
            if r is not None and r.contains(pos):
                return key
        return None

    def _seek_frac_at(self, x: float) -> float:
        tr = self._rects.get("seek_track")
        if tr is None or tr.width() <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - tr.left()) / tr.width()))

    def _vol_at(self, x: float) -> float:
        tr = self._rects.get("vol_track")
        if tr is None or tr.width() <= 0:
            return 0.0
        return round(max(0.0, min(1.0, (x - tr.left()) / tr.width())) * 100.0)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            h = self._hit(pos)
            if h == "seek_hit":
                _, dur, _ = self._live_times()
                if dur and dur > 0:
                    self._dragging = "seek"
                    self._drag_seek_frac = self._seek_frac_at(pos.x())
                    self.update()
                event.accept()
                return
            if h == "vol_hit":
                self._dragging = "vol"
                val = self._vol_at(pos.x())
                self._vol_level = val
                self.volume_requested.emit(val)
                self.update()
                event.accept()
                return
            self.activate(h)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._dragging == "seek":
            self._drag_seek_frac = self._seek_frac_at(pos.x())
            self.update()
            event.accept()
            return
        if self._dragging == "vol":
            val = self._vol_at(pos.x())
            if val != self._vol_level:
                self._vol_level = val
                self.volume_requested.emit(val)
                self.update()
            event.accept()
            return
        h = self._hit(pos)
        if h != self._hover:
            self._hover = h
            self.update()
        if h in (
            "close", "app_chip", "playpause", "prev", "next", "back10", "fwd10",
            "dev_prev", "dev_chip", "dev_next", "mixer_link", "mute_btn", "open_app",
        ):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            mode = self._dragging
            self._dragging = None
            if mode == "seek" and self._drag_seek_frac is not None:
                frac = float(self._drag_seek_frac)
                _, dur, _ = self._live_times()
                if dur and dur > 0:
                    self._media["position_s"] = frac * dur
                    self._media["updated_at"] = time.monotonic()
                self._drag_seek_frac = None
                self.seek_requested.emit(frac)
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        diff = 2.0 if event.angleDelta().y() > 0 else -2.0
        val = max(0.0, min(100.0, self._vol_level + diff))
        self._vol_level = val
        self._vol_pending_level = val
        self.update()
        # Send pending level after 150ms idle to avoid flood on fast wheel
        self._vol_coalescer_timer.start(150)
        event.accept()

    def _flush_vol_coalescer(self) -> None:
        """Emit the pending volume level once."""
        if self._vol_pending_level is not None:
            self.volume_requested.emit(self._vol_pending_level)
            self._vol_pending_level = None

    def activate(self, key: Optional[str]) -> None:
        if not key:
            return
        if key == "close":
            self.hide_animated()
        elif key in ("prev", "playpause", "next"):
            if key == "playpause" and self._media:
                self._media["playing"] = not bool(self._media.get("playing", True))
                self._media["updated_at"] = time.monotonic()
                self.update()
            self.control_requested.emit(key)
        elif key in ("back10", "fwd10"):
            pos_s, dur_s, _ = self._live_times()
            if dur_s and dur_s > 0.0 and pos_s is not None:
                delta = -10.0 if key == "back10" else 10.0
                new_pos = max(0.0, min(dur_s, pos_s + delta))
                frac = new_pos / dur_s
                self._media["position_s"] = new_pos
                self._media["updated_at"] = time.monotonic()
                self.seek_requested.emit(frac)
                self.update()
        elif key == "dev_prev":
            self.switch_device(-1)
        elif key in ("dev_next", "dev_chip"):
            self.switch_device(1)
        elif key == "mute_btn":
            self._vol_muted = not self._vol_muted
            self.mute_requested.emit(self._vol_muted)
            self.update()
        elif key == "mixer_link":
            self.open_mixer_requested.emit()
        elif key in ("app_chip", "open_app"):
            exe = str(self._media.get("exe") or self._media.get("app") or "")
            self.open_app_requested.emit(exe)

    # ------------------------------------------------------------ çizim
    def render_to_image(self, dpr: float = 1.5) -> QImage:
        img = QImage(
            max(1, int(round(self.width() * dpr))),
            max(1, int(round(self.height() * dpr))),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            self._paint(p)
        finally:
            p.end()
        return img

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        self._layout()
        ps.draw_panel_shell(p, QRectF(0, 0, self.width(), self.height()))

        m = self._media or {}
        playing = bool(m.get("playing", False))
        app_name = str(m.get("app") or "Medya")
        title = str(m.get("title") or "Medya oynatılmıyor")
        artist = str(m.get("artist") or "—")

        art_img, art_accent = dock_cards._decode_media_art(m.get("art_bytes"))
        accent = art_accent if art_accent is not None else ps.ACCENT

        # 1. Başlık
        hdr_out = ps.draw_header(
            p,
            self._rects["hdr"],
            "Şimdi Çalıyor",
            chip=f"{app_name} ›",
            chip_dot=ps.OK if playing else ps.TEXT_MUTED,
            close_hover=(self._hover == "close"),
        )
        if hdr_out.get("close") is not None:
            self._rects["close"] = hdr_out["close"]
        if hdr_out.get("chip") is not None:
            self._rects["app_chip"] = hdr_out["chip"]

        # 2. Parça / Video Kartı
        c1 = self._rects["card_track"]
        ps.draw_tile(p, c1, hover=False)

        # Ambient üst parlama (kapak rengi varsa)
        if art_accent is not None:
            p.save()
            p.setClipPath(ps.rounded(c1.adjusted(0.5, 0.5, -0.5, -0.5), ps.R_CARD))
            amb_grad = QLinearGradient(c1.left(), c1.top(), c1.right(), c1.top() + 72.0)
            c_top = QColor(accent)
            c_top.setAlpha(36)
            c_zero = QColor(accent)
            c_zero.setAlpha(0)
            amb_grad.setColorAt(0.0, c_top)
            amb_grad.setColorAt(1.0, c_zero)
            p.fillRect(c1, amb_grad)
            p.restore()

        # 64x64 Albüm Kapağı / Ekolayzır Karosu
        art_r = self._rects["art"]
        dock_cards.draw_equalizer_tile(
            p, art_r, playing=playing, art_img=art_img, accent_color=accent
        )

        # Başlık, sanatçı ve durum rozeti
        meta_r = self._rects["meta"]
        f_title = ps.font(13.5, QFont.Weight.DemiBold)
        fm_t = QFontMetricsF(f_title)
        p.setFont(f_title)
        p.setPen(ps.TEXT)
        elided_title = fm_t.elidedText(title, Qt.TextElideMode.ElideRight, meta_r.width())
        p.drawText(
            QRectF(meta_r.left(), meta_r.top() + 2.0, meta_r.width(), 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        f_art = ps.font(11.5, QFont.Weight.Normal)
        fm_a = QFontMetricsF(f_art)
        p.setFont(f_art)
        p.setPen(ps.TEXT_MUTED)
        elided_artist = fm_a.elidedText(artist, Qt.TextElideMode.ElideRight, meta_r.width())
        p.drawText(
            QRectF(meta_r.left(), meta_r.top() + 23.0, meta_r.width(), 17.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_artist,
        )

        # Durum göstergesi (canlı ve zarif durum çipi)
        status_y = meta_r.top() + 44.0
        badge_rect = QRectF(meta_r.left(), status_y, 74.0, 18.0)
        p.setPen(QColor(255, 255, 255, 20))
        p.setBrush(QColor(16, 185, 129, 32) if playing else QColor(255, 255, 255, 14))
        p.drawRoundedRect(badge_rect, 9.0, 9.0)
        # Dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ps.OK if playing else ps.TEXT_MUTED))
        p.drawEllipse(QPointF(badge_rect.left() + 7.5, badge_rect.center().y()), 2.5, 2.5)
        # Text
        p.setFont(ps.font(9.5, QFont.Weight.DemiBold))
        p.setPen(QColor(16, 185, 129) if playing else ps.TEXT_MUTED)
        p.drawText(
            QRectF(badge_rect.left() + 14.0, badge_rect.top(), badge_rect.width() - 16.0, badge_rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Çalıyor" if playing else "Duraklatıldı",
        )

        # Seekbar (Sarma Çubuğu) ve Süreler
        pos_s, dur_s, frac = self._live_times()
        st_r = self._rects["seek_track"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.SLIDER_TRACK)
        p.drawRoundedRect(st_r, 2.5, 2.5)

        if frac is not None and frac > 0.0:
            fill_w = max(5.0, st_r.width() * frac)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(st_r.left(), st_r.top(), fill_w, st_r.height()), 2.5, 2.5)
            # Tutaç (thumb)
            kx = st_r.left() + st_r.width() * frac
            ky = st_r.center().y()
            kr = 6.0 if (self._hover == "seek_hit" or self._dragging == "seek") else 4.5
            p.setBrush(QColor(255, 255, 255))
            p.setPen(QPen(QColor(0, 0, 0, 70), 1.0))
            p.drawEllipse(QPointF(kx, ky), kr, kr)

        tm_r = self._rects["seek_times"]
        f_tm = ps.font(10.0, QFont.Weight.Medium, tabular=True)
        p.setFont(f_tm)
        p.setPen(ps.TEXT_META)
        p.drawText(QRectF(tm_r.left(), tm_r.top(), 52.0, tm_r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fmt_mmss(pos_s))
        p.drawText(QRectF(tm_r.right() - 52.0, tm_r.top(), 52.0, tm_r.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, fmt_mmss(dur_s))

        # Kontrol Düğmeleri (-10s, Prev, Play/Pause, Next, +10s)
        has_seek = dur_s is not None and dur_s > 0.0
        f_step = ps.font(10.5, QFont.Weight.DemiBold, tabular=True)
        for k_step, lbl in (("back10", "-10s"), ("fwd10", "+10s")):
            rs = self._rects[k_step]
            hov = (self._hover == k_step) and has_seek
            p.setPen(QPen(QColor(255, 255, 255, 36) if hov else ps.BUTTON_BORDER, 1.0))
            p.setBrush(ps.BUTTON_HOVER if hov else ps.BUTTON_BG)
            p.drawRoundedRect(rs, 13.0, 13.0)  # Modern hap kapsül
            p.setFont(f_step)
            p.setPen(ps.TEXT if hov else (ps.TEXT_BTN if has_seek else ps.TEXT_CLOSE))
            p.drawText(rs, Qt.AlignmentFlag.AlignCenter, lbl)

        # Prev & Next
        for k_pn, is_next in (("prev", False), ("next", True)):
            rn = self._rects[k_pn]
            hov = (self._hover == k_pn)
            p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
            p.setBrush(ps.BUTTON_HOVER if hov else ps.BUTTON_BG)
            p.drawEllipse(rn)
            self._draw_skip_glyph(p, rn.center(), is_next=is_next, color=ps.TEXT if hov else ps.TEXT_BODY)

        # Merkez Play/Pause (42x42 ambient vurgu dairesi)
        rp = self._rects["playpause"]
        hov_p = (self._hover == "playpause")
        play_bg = QColor(accent).lighter(112) if hov_p else QColor(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(play_bg)
        p.drawEllipse(rp)
        # Koyu veya beyaz ikon (kontrasta göre)
        fg_p = QColor(0x11, 0x13, 0x17) if play_bg.lightness() > 145 else QColor(255, 255, 255)
        self._draw_play_pause_glyph(p, rp.center(), playing=playing, color=fg_p)

        # 3. Ses ve Çıkış Kartı
        c2 = self._rects["card_vol"]
        ps.draw_card(p, c2, overline="Ses ve çıkış", overline_right=None)

        # Cihaz değiştirici: [‹] [Hoparlör · Realtek] [›] ve Mikser ›
        dev_text = self._vol_device or "Hoparlör"
        disp_raw = ""
        try:
            import media as _m_mod
            disp_raw = _m_mod.tr_device_name(dev_text)
        except Exception:
            disp_raw = dev_text
        if not disp_raw:
            disp_raw = "Hoparlör"

        has_multi = len(self._devices) > 1
        r_prev = self._rects["dev_prev"]
        r_chip = self._rects["dev_chip"]
        r_next = self._rects["dev_next"]
        r_mix = self._rects["mixer_link"]

        # Önceki cihaz düğmesi [‹]
        hov_prev = (self._hover == "dev_prev") and has_multi
        p.setPen(QColor(255, 255, 255, 38) if hov_prev else QColor(255, 255, 255, 20))
        p.setBrush(QColor(255, 255, 255, 24) if hov_prev else QColor(255, 255, 255, 10))
        p.drawRoundedRect(r_prev, 4.0, 4.0)
        p.setFont(ps.font(11.0, QFont.Weight.Bold))
        p.setPen(accent if hov_prev else (ps.TEXT if has_multi else QColor(255, 255, 255, 45)))
        p.drawText(r_prev, Qt.AlignmentFlag.AlignCenter, "‹")

        # Cihaz Çipi / Seçici [Hoparlör · Realtek]
        hov_chip = (self._hover == "dev_chip")
        p.setPen(QColor(accent) if hov_chip else QColor(255, 255, 255, 26))
        p.setBrush(QColor(255, 255, 255, 26) if hov_chip else QColor(255, 255, 255, 14))
        p.drawRoundedRect(r_chip, 5.0, 5.0)

        # Aktif cihaz yeşil / açık nokta göstergesi
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent if not self._vol_muted else ps.TEXT_MUTED))
        p.drawEllipse(QPointF(r_chip.left() + 7.5, r_chip.center().y()), 2.5, 2.5)

        # Cihaz adı metni
        f_chip = ps.font(10.0, QFont.Weight.Medium)
        fm_chip = QFontMetricsF(f_chip)
        p.setFont(f_chip)
        p.setPen(accent if hov_chip else ps.TEXT)
        elided_dev = fm_chip.elidedText(disp_raw, Qt.TextElideMode.ElideRight, r_chip.width() - 17.0)
        p.drawText(
            QRectF(r_chip.left() + 14.0, r_chip.top(), r_chip.width() - 16.0, r_chip.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_dev,
        )

        # Sonraki cihaz düğmesi [›]
        hov_next = (self._hover == "dev_next") and has_multi
        p.setPen(QColor(255, 255, 255, 38) if hov_next else QColor(255, 255, 255, 20))
        p.setBrush(QColor(255, 255, 255, 24) if hov_next else QColor(255, 255, 255, 10))
        p.drawRoundedRect(r_next, 4.0, 4.0)
        p.setFont(ps.font(11.0, QFont.Weight.Bold))
        p.setPen(accent if hov_next else (ps.TEXT if has_multi else QColor(255, 255, 255, 45)))
        p.drawText(r_next, Qt.AlignmentFlag.AlignCenter, "›")

        # Sağdaki mikser bağlantısı (Mikser ›)
        hov_mix = (self._hover == "mixer_link")
        p.setFont(ps.font(10.0, QFont.Weight.Normal))
        p.setPen(accent if hov_mix else ps.TEXT_MUTED)
        p.drawText(
            r_mix,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "Mikser ›",
        )

        # Sessiz düğmesi
        rm = self._rects["mute_btn"]
        hov_m = (self._hover == "mute_btn")
        p.setPen(QPen(ps.BUTTON_BORDER, 1.0))
        p.setBrush(QColor(255, 69, 58, 45) if self._vol_muted else (ps.BUTTON_HOVER if hov_m else ps.BUTTON_BG))
        p.drawRoundedRect(rm, 7.0, 7.0)
        ic_col = ps.DANGER if self._vol_muted else (ps.TEXT if hov_m else ps.TEXT_BODY)
        if _draw_speaker_icon is not None:
            _draw_speaker_icon(p, rm, ic_col, muted=self._vol_muted)
        else:
            p.setFont(ps.font(11.0, QFont.Weight.Bold))
            p.setPen(ic_col)
            p.drawText(rm, Qt.AlignmentFlag.AlignCenter, "×" if self._vol_muted else "♪")

        # Ses sürgüsü
        vt = self._rects["vol_track"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ps.SLIDER_TRACK)
        p.drawRoundedRect(vt, 3.0, 3.0)
        v_frac = 0.0 if self._vol_muted else max(0.0, min(1.0, self._vol_level / 100.0))
        if v_frac > 0.0:
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(vt.left(), vt.top(), max(6.0, vt.width() * v_frac), vt.height()), 3.0, 3.0)
        vkx = vt.left() + vt.width() * v_frac
        vky = vt.center().y()
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(0, 0, 0, 70), 1.0))
        p.drawEllipse(QPointF(vkx, vky), 5.5, 5.5)

        # Sağ ses yüzdesi
        vp = self._rects["vol_pct"]
        p.setFont(ps.font(11.5, QFont.Weight.DemiBold, tabular=True))
        p.setPen(ps.DANGER if self._vol_muted else ps.TEXT_BODY)
        p.drawText(
            vp,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "Sessiz" if self._vol_muted else f"%{int(round(self._vol_level))}",
        )

        # 4. Alt bilgi
        src_txt = str(m.get("source") or "Windows medya oturumu")
        btn_r = ps.draw_footer(
            p,
            self._rects["footer"],
            src_txt,
            button_text="Uygulamayı aç",
            button_hover=(self._hover == "open_app"),
        )
        if btn_r is not None:
            self._rects["open_app"] = btn_r

    @staticmethod
    def _draw_skip_glyph(p: QPainter, center: QPointF, is_next: bool, color: QColor) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cx, cy = center.x(), center.y()
        tri = QPainterPath()
        if is_next:
            tri.moveTo(cx - 3.6, cy - 4.2)
            tri.lineTo(cx + 2.0, cy)
            tri.lineTo(cx - 3.6, cy + 4.2)
            tri.closeSubpath()
            p.drawPath(tri)
            p.drawRoundedRect(QRectF(cx + 2.4, cy - 4.2, 1.6, 8.4), 0.7, 0.7)
        else:
            tri.moveTo(cx + 3.6, cy - 4.2)
            tri.lineTo(cx - 2.0, cy)
            tri.lineTo(cx + 3.6, cy + 4.2)
            tri.closeSubpath()
            p.drawPath(tri)
            p.drawRoundedRect(QRectF(cx - 4.0, cy - 4.2, 1.6, 8.4), 0.7, 0.7)
        p.restore()

    @staticmethod
    def _draw_play_pause_glyph(p: QPainter, center: QPointF, playing: bool, color: QColor) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cx, cy = center.x(), center.y()
        if playing:
            p.drawRoundedRect(QRectF(cx - 4.6, cy - 5.8, 3.2, 11.6), 1.2, 1.2)
            p.drawRoundedRect(QRectF(cx + 1.4, cy - 5.8, 3.2, 11.6), 1.2, 1.2)
        else:
            tri = QPainterPath()
            tri.moveTo(cx - 3.5, cy - 6.0)
            tri.lineTo(cx + 6.0, cy)
            tri.lineTo(cx - 3.5, cy + 6.0)
            tri.closeSubpath()
            p.drawPath(tri)
        p.restore()
