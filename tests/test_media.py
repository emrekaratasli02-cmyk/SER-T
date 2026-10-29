"""test_media.py - Verification and visual test suite for Serit media module.

Validates:
  1. Read-only live Core Audio volume and active session queries.
  2. INPUT Win32 structure sizing (40 bytes on 64-bit architecture).
  3. Title parsing unit tests across Spotify, YouTube, YouTube Music, and unrelated windows.
  4. High-DPI DPR 2.0 showcase render of volume chips, media chips, and popover slider panel.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys

# Ensure Serit modules are importable
SERIT_DIR = Path(__file__).resolve().parent.parent
if str(SERIT_DIR) not in sys.path:
    sys.path.insert(0, str(SERIT_DIR))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
)

import media
import theme


def test_live_read_only() -> None:
    """Print live read-only system audio and media state.

    STRICT READ-ONLY: Never modifies volume, mute, or dispatches media keys.
    """
    print("\n--- 1. LIVE CORE AUDIO & MEDIA STATE (READ ONLY) ---")

    vol = media.get_volume()
    print(f"Current Volume : {vol['level']}% | Muted: {vol['muted']} | Device: '{vol['device']}'")

    sessions = media.get_active_audio_sessions()
    print(f"Active Audio Sessions (State==1): {sessions}")

    np = media.now_playing()
    if np:
        print(f"Now Playing    : App: {np['app']} | Title: '{np['title']}' | Artist: '{np['artist']}' | Playing: {np['playing']}")
    else:
        print("Now Playing    : None detected from visible windows")

    devices = media.list_output_devices(active_only=True)
    print(f"Active Output Devices ({len(devices)}):")
    for d in devices:
        def_flag = " [DEFAULT]" if d["default"] else ""
        print(f"  - {d['name']}{def_flag} (id: {d['id']})")


def test_win32_input_struct() -> None:
    """Assert INPUT struct size is exactly 40 bytes on 64-bit Windows."""
    print("\n--- 2. WIN32 INPUT STRUCT ASSERTIONS ---")
    size = ctypes.sizeof(media.INPUT)
    print(f"ctypes.sizeof(media.INPUT) = {size} bytes")
    assert size == 40, f"Expected INPUT struct size 40 on 64-bit Windows, got {size}"

    assert ctypes.sizeof(media.KEYBDINPUT) == 24, f"Expected KEYBDINPUT size 24, got {ctypes.sizeof(media.KEYBDINPUT)}"
    assert "playpause" in media.VK_KEY_MAP
    assert "next" in media.VK_KEY_MAP
    assert "prev" in media.VK_KEY_MAP
    print("INPUT struct size 40 and virtual key mappings verified OK.")


def test_title_parsing_unit_tests() -> None:
    """Unit-test title parsing heuristics against expected cases."""
    print("\n--- 3. TITLE PARSING HEURISTIC UNIT TESTS ---")

    # Case A: Spotify desktop active song
    res_sp = media.parse_media_title("The Weeknd - Blinding Lights", r"C:\Users\Emre\AppData\Local\Microsoft\WindowsApps\Spotify.exe")
    assert res_sp is not None, "Failed to parse Spotify active song"
    assert res_sp["artist"] == "The Weeknd"
    assert res_sp["title"] == "Blinding Lights"
    assert res_sp["app"] == "Spotify"
    print("  [PASS] Spotify playing: 'The Weeknd - Blinding Lights'")

    # Case B: Spotify idle / paused
    assert media.parse_media_title("Spotify", r"C:\Spotify\spotify.exe") is None
    assert media.parse_media_title("Spotify Premium", r"C:\Spotify\spotify.exe") is None
    assert media.parse_media_title("Spotify Free", r"C:\Spotify\spotify.exe") is None
    print("  [PASS] Spotify idle titles return None")

    # Case C: YouTube in Chrome
    yt_chrome_title = "Müge Anlı ile Tatlı Sert | 26 Ekim 2026 Pazartesi - 19. Sezon - YouTube - Google Chrome"
    res_yt = media.parse_media_title(yt_chrome_title, r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert res_yt is not None, "Failed to parse YouTube in Chrome"
    assert res_yt["app"] == "YouTube"
    assert res_yt["title"] == "Müge Anlı ile Tatlı Sert | 26 Ekim 2026 Pazartesi - 19. Sezon"
    print("  [PASS] YouTube in Chrome parsed correctly")

    # Case D: YouTube Music
    ytm_title = "Starboy - The Weeknd - YouTube Music - Google Chrome"
    res_ytm = media.parse_media_title(ytm_title, r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert res_ytm is not None, "Failed to parse YouTube Music"
    assert res_ytm["app"] == "YouTube Music"
    assert res_ytm["title"] == "Starboy"
    assert res_ytm["artist"] == "The Weeknd"
    print("  [PASS] YouTube Music in Chrome parsed correctly")

    # Case E: Unrelated windows
    assert media.parse_media_title("GarantiBBVA_Performans_IAS - Google Docs - Google Chrome", "chrome.exe") is None
    assert media.parse_media_title("Claude", "claude.exe") is None
    assert media.parse_media_title("Hermes", "hermes.exe") is None
    assert media.parse_media_title("", "chrome.exe") is None
    print("  [PASS] Unrelated application windows cleanly return None")


def render_media_showcase(out_path: str) -> None:
    """Render high-DPI (DPR 2.0) visual showcase of chips and popover slider panel."""
    print("\n--- 4. RENDERING HIGH-DPI MEDIA SHOWCASE ---")
    dpr = 2.0
    w_logical = 760.0
    h_logical = 440.0

    img = QImage(
        int(round(w_logical * dpr)),
        int(round(h_logical * dpr)),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(12, 15, 22))

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # 1. Subtle desktop wallpaper background gradient
    bg_grad = QLinearGradient(0, 0, w_logical, h_logical)
    bg_grad.setColorAt(0.0, QColor(14, 18, 28))
    bg_grad.setColorAt(0.5, QColor(20, 26, 40))
    bg_grad.setColorAt(1.0, QColor(10, 13, 20))
    p.fillRect(QRectF(0, 0, w_logical, h_logical), bg_grad)

    # Ambient glow blobs behind popovers
    glow1 = theme.rounded_path(QRectF(40, 160, 290, 140), 24.0)
    p.fillPath(glow1, QColor(96, 181, 255, 12))
    glow2 = theme.rounded_path(QRectF(380, 160, 290, 140), 24.0)
    p.fillPath(glow2, QColor(240, 138, 93, 10))

    # Title header
    f_title = theme.make_font(15.0, QFont.Weight.DemiBold)
    p.setFont(f_title)
    p.setPen(theme.COLOR_TEXT_PRIMARY)
    p.drawText(QRectF(30, 16, 700, 22), Qt.AlignLeft | Qt.AlignVCenter, "Şerit Dock - Medya & Ses Bileşenleri Showcase (DPR 2.0)")

    # --------------------------------------------------------------------------
    # ROW 1: DOCK CAPSULE WITH CHIPS
    # --------------------------------------------------------------------------
    dock_rect = QRectF(30.0, 52.0, 700.0, 56.0)
    theme.draw_glass_capsule(p, dock_rect, radius=28.0)

    # Chip A: Normal Volume Chip (74%)
    r_vol_a = QRectF(42.0, 60.0, 76.0, 40.0)
    media.draw_volume_chip(p, r_vol_a, level=74.0, muted=False, hover_t=0.0)

    # Chip B: Hovered Volume Chip (38%)
    r_vol_b = QRectF(124.0, 60.0, 76.0, 40.0)
    media.draw_volume_chip(p, r_vol_b, level=38.0, muted=False, hover_t=1.0)

    # Chip C: Muted Volume Chip
    r_vol_c = QRectF(206.0, 60.0, 76.0, 40.0)
    media.draw_volume_chip(p, r_vol_c, level=0.0, muted=True, hover_t=0.0)

    # Separator with symmetric 10px flanking gaps
    theme.draw_separator(p, 292.0, y=69.0, height=22.0)

    # Chip D: Spotify Playing Media Chip
    sp_info = {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "app": "Spotify",
        "exe": "spotify.exe",
    }
    r_media_sp = QRectF(302.0, 60.0, 204.0, 40.0)
    media.draw_media_chip(p, r_media_sp, sp_info, playing=True, hover_t=0.0)

    # Chip E: YouTube Media Chip (Paused)
    yt_info = {
        "title": "Müge Anlı | 26 Ekim 2026 Pazartesi - 19. Sezon",
        "artist": "YouTube",
        "app": "YouTube",
        "exe": "chrome.exe",
    }
    r_media_yt = QRectF(516.0, 60.0, 202.0, 40.0)
    media.draw_media_chip(p, r_media_yt, yt_info, playing=False, hover_t=0.5)

    # Labels for Row 1
    f_sub = theme.make_font(10.0, QFont.Weight.Normal)
    p.setFont(f_sub)
    p.setPen(theme.COLOR_TEXT_MUTED)
    p.drawText(QRectF(30, 114, 700, 16), Qt.AlignLeft, "↑ Standart Ses (74%) · Üzerine Gelinen (Hover) · Sessiz (Muted) · Spotify Çalıyor · YouTube Duraklatıldı")

    # --------------------------------------------------------------------------
    # ROW 2: FLYOUT POPOVER PANELS
    # --------------------------------------------------------------------------
    # Popover 1: Active Playback Panel
    pop_rect1 = QRectF(50.0, 150.0, 280.0, 126.0)
    media.draw_volume_slider_panel(
        p,
        pop_rect1,
        level=74.0,
        muted=False,
        device="Speakers (Realtek(R) Audio)",
    )

    # Popover 2: Muted State Panel
    pop_rect2 = QRectF(390.0, 150.0, 280.0, 126.0)
    media.draw_volume_slider_panel(
        p,
        pop_rect2,
        level=0.0,
        muted=True,
        device="MSI MP223 (NVIDIA High Definition Audio)",
    )

    # --------------------------------------------------------------------------
    # ROW 3: SPEC & LIVE STATUS FOOTER
    # --------------------------------------------------------------------------
    f_foot = theme.make_font(10.5, QFont.Weight.Normal)
    p.setFont(f_foot)
    p.setPen(theme.COLOR_TEXT_SECONDARY)

    live_vol = media.get_volume()
    live_txt = f"Canlı Sistem Değeri: %{live_vol['level']} ({live_vol['device']}) · Sessiz: {live_vol['muted']}"
    p.drawText(QRectF(50, 290, 660, 20), Qt.AlignLeft, live_txt)

    f_spec = theme.make_font(9.5, QFont.Weight.Normal)
    p.setFont(f_spec)
    p.setPen(theme.COLOR_TEXT_MUTED)
    p.drawText(
        QRectF(50, 314, 660, 44),
        Qt.AlignLeft | Qt.TextWordWrap,
        "Tasarım Detayları: QPainterPath vektör hoparlör (0-3 dinamik ses dalgası) · Kalibre edilmiş mini halka göstergesi · "
        "Spotify / YouTube renkli dairesel rozetleri · Elided 2-satır tipografi (11px/10px) · Dokunmatik hit-box dikdörtgenleri · "
        "Win32 SendInput (40-byte INPUT struct) · pycaw Core Audio UI thread CoInitialize desteği.",
    )

    p.end()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"Showcase image successfully rendered to:\n  {out_path}")


def main() -> None:
    # Ensure QGuiApplication exists for font metrics and text rendering
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    _ = app

    test_live_read_only()
    test_win32_input_struct()
    test_title_parsing_unit_tests()

    showcase_path = "C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5/media_showcase.png"
    render_media_showcase(showcase_path)
    print("\nALL VERIFICATIONS AND TESTS PASSED!")


if __name__ == "__main__":
    main()
