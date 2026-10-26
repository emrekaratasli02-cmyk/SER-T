"""Self-test for winapi.py module."""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to sys.path so winapi can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
import winapi  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)

    # 1. list_windows()
    windows = winapi.list_windows()
    print(f"list_windows() count: {len(windows)}")
    for idx, w in enumerate(windows[:5], 1):
        print(f"  [{idx}] title: {w['title']!r} | exe: {w['exe']!r}")

    # 2. group_by_app()
    groups = winapi.group_by_app(windows)
    print(f"group_by_app() count: {len(groups)}")
    for idx, g in enumerate(groups[:5], 1):
        print(
            f"  [{idx}] exe: {g['exe']!r} | count: {g['count']} "
            f"| active: {g['active']} | title: {g['title']!r}"
        )

    # 3. app_icon() for first 3 exes
    print("app_icon() results:")
    exes: list[str] = []
    for g in groups:
        exe_path = g.get("exe") or ""
        if exe_path and exe_path not in exes:
            exes.append(exe_path)
            if len(exes) == 3:
                break

    for exe_path in exes:
        pix = winapi.app_icon(exe_path, 64)
        print(
            f"  exe: {exe_path} -> size: {pix.width()}x{pix.height()}, isNull: {pix.isNull()}"
        )

    # 4. Acrylic & round region test widget
    w_logical = 320
    h_logical = 90
    radius_logical = 18

    screen = QApplication.primaryScreen()
    dpr = float(screen.devicePixelRatio())
    geo = screen.geometry()
    x = int((geo.width() - w_logical) / 2)
    y = int(geo.height() - h_logical - 60)

    test_widget = QWidget()
    test_widget.setWindowFlags(
        Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    )
    test_widget.setAttribute(Qt.WA_TranslucentBackground, True)
    test_widget.setGeometry(x, y, w_logical, h_logical)
    test_widget.show()
    app.processEvents()

    hwnd = int(test_widget.winId())
    acrylic_applied = winapi.enable_acrylic(hwnd, 0x50201812)
    winapi.set_round_region(hwnd, w_logical, h_logical, radius_logical, dpr)
    print(
        f"Acrylic test widget: hwnd={hwnd}, enable_acrylic={acrylic_applied}, "
        f"pos=({x}, {y}), size=({w_logical}x{h_logical})"
    )

    # Keep visible for 1.5 s
    start = time.time()
    while time.time() - start < 1.5:
        app.processEvents()
        time.sleep(0.05)

    # Grab screenshot of widget region
    scratch_png = Path(
        r"C:\Users\Emre Karatasli\AppData\Local\hermes\cache\scratch\winapi_acrylic.png"
    )
    scratch_png.parent.mkdir(parents=True, exist_ok=True)
    pixmap = screen.grabWindow(0, x, y, w_logical, h_logical)
    saved = pixmap.save(str(scratch_png), "PNG")
    print(
        f"Screenshot saved: {saved} -> {scratch_png} "
        f"(size: {pixmap.width()}x{pixmap.height()})"
    )

    test_widget.close()
    app.processEvents()

    # 5. taskbar_autohide_get() ONLY (Safety rule: do not call taskbar_autohide_set or activate_or_minimize on real windows)
    autohide = winapi.taskbar_autohide_get()
    print(f"taskbar_autohide_get(): {autohide}")


if __name__ == "__main__":
    main()
