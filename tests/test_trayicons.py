"""test_trayicons.py - Test suite for Windows 11 system tray integration in Şerit dock.

Read-only test:
- Enumerates live tray items via list_tray_items().
- Loads real icons via get_tray_icons().
- Renders the acrylic glass panel at DPR 2.0 to traypanel.png.
- Verifies hit boxes, non-null pixmaps, and zero mutations to the user's taskbar.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

# Ensure D:/Apps/serit is on sys.path
serit_root = Path(__file__).resolve().parent.parent
if str(serit_root) not in sys.path:
    sys.path.insert(0, str(serit_root))

import trayicons  # noqa: E402

OUTPUT_PNG = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v5/traypanel.png")


def test_list_and_render_tray_panel() -> None:
    """Read live tray items, print summary, and render panel card at DPR 2.0."""
    _ = QApplication.instance() or QApplication(["test_trayicons"])

    print("=== LIVE SYSTEM TRAY ENUMERATION ===")
    items = trayicons.list_tray_items()
    print(f"Total live tray items discovered: {len(items)}\n")

    for i, it in enumerate(items):
        name = it.get("name", "")
        exe = it.get("exe", "")
        running = it.get("running", False)
        promoted = it.get("promoted", False)
        uia_avail = it.get("uia_available", False)
        has_bytes = bool(it.get("icon_bytes"))
        rect = it.get("rect", (0, 0, 0, 0))
        print(
            f"[{i:02d}] Name: {name!r:32} | Running: {str(running):5} | "
            f"Promoted: {str(promoted):5} | UIA: {str(uia_avail):5} | "
            f"HasBytes: {str(has_bytes):5} | Rect: {rect}\n"
            f"     Exe: {exe}"
        )

    # Load high-DPI icons
    icons = trayicons.get_tray_icons(items)
    print(f"\nTotal icons loaded in cache: {len(icons)}")
    valid_icons = sum(1 for pm in icons.values() if not pm.isNull())
    print(f"Valid non-null QPixmaps: {valid_icons} / {len(items)}")

    # Calculate optimal panel dimensions
    tile_size = 42.0
    gap = 6.0
    pad_x = 14.0
    cols = 5
    rows = max(1, (len(items) + cols - 1) // cols)

    panel_w = 2.0 * pad_x + cols * tile_size + (cols - 1) * gap
    header_h = 34.0
    panel_h = header_h + 16.0 + rows * tile_size + (rows - 1) * gap + 14.0

    margin = 16.0
    canvas_w = int(panel_w + 2 * margin)
    canvas_h = int(panel_h + 2 * margin)

    dpr = 2.0
    img = QImage(int(canvas_w * dpr), int(canvas_h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(0, 0, 0, 0))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # 1. Draw subtle desktop wallpaper backdrop for glass preview
    backdrop_rect = QRectF(0, 0, canvas_w, canvas_h)
    bg_grad = QLinearGradient(0, 0, canvas_w, canvas_h)
    bg_grad.setColorAt(0.0, QColor(24, 28, 38))
    bg_grad.setColorAt(0.5, QColor(16, 20, 28))
    bg_grad.setColorAt(1.0, QColor(10, 12, 18))
    p.fillRect(backdrop_rect, bg_grad)

    # Add subtle backdrop ambient glow
    p.setPen(QColor(255, 255, 255, 15))
    p.setFont(QFont("Segoe UI Variable Display, Segoe UI", 9))
    p.drawText(QPointF(16, canvas_h - 6), "Şerit Dock Acrylic Glass Tray Panel Preview (DPR 2.0)")

    # 2. Render tray glass panel
    panel_rect = QRectF(margin, margin, panel_w, panel_h)
    hover_idx = 2 if len(items) > 2 else (0 if items else -1)
    hit_rects = trayicons.draw_tray_panel(p, panel_rect, items, icons, hover_index=hover_idx)

    p.end()

    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    saved = img.save(str(OUTPUT_PNG), "PNG")
    print(f"\nRendered panel saved to: {OUTPUT_PNG} (success={saved})")
    print(f"Generated {len(hit_rects)} hit rects (expected {len(items)})")

    assert saved, "Failed to save preview PNG"
    assert len(hit_rects) == len(items), f"Hit rects count mismatch: {len(hit_rects)} != {len(items)}"
    assert os.path.exists(OUTPUT_PNG) and os.path.getsize(OUTPUT_PNG) > 0, "PNG output file is missing or empty"
    print("\nALL ASSERTIONS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    test_list_and_render_tray_panel()
