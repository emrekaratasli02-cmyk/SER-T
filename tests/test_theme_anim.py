"""test_theme_anim.py - Verification and visual showcase tests for theme.py and anim.py.

Tests:
  1. Tween reaches target value and fires on_done.
  2. AnimationDriver starts on active tween and stops when idle (0% idle CPU).
  3. Mid-flight retarget continues seamlessly from current value without jumps.
  4. Reduce motion forces instant completion.
  5. PressTween tactile press/release scaling.
  6. HoverMagnifier cosine falloff calculation.
  7. Ring gauge threshold color transitions (7%, 42%, 83%, 97%).
  8. Renders high-DPI showcase PNG (DPR 2) with glass capsule, grain, separators,
     rings, indicators, and crisp Windows explorer icon.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add parent directory to path so serit modules can be imported
SERIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERIT_DIR))

from PySide6.QtCore import QFileInfo, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QFileIconProvider

import anim
import theme

SHOWCASE_PATH = (
    Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-audit")
    / "theme_showcase.png"
)


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        # Avoid "-platform offscreen" so Windows DirectWrite font engine initializes
        app = QApplication(["serit_test"])
    return app


# ==============================================================================
# HEADLESS DRIVER & TWEEN TESTS
# ==============================================================================


def test_tween_reaches_target() -> None:
    """Verifies that a tween smoothly reaches its target value and fires on_done."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = False

    done_called = False

    def on_done() -> None:
        nonlocal done_called
        done_called = True

    tw = anim.Tween(start=10.0, target=90.0, duration=100.0, on_done=on_done)
    driver.start_tween(tw)

    assert driver.is_running()
    assert driver.active_count() == 1

    # Simulate time advancing 120ms
    driver.step_manual(120.0)

    assert tw.is_finished
    assert abs(tw.value - 90.0) < 1e-4
    assert done_called
    print("  [PASS] test_tween_reaches_target")


def test_driver_stops_when_idle() -> None:
    """Verifies zero-idle contract: timer stops when all tweens finish."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = False

    tw1 = anim.Tween(start=0.0, target=50.0, duration=60.0)
    tw2 = anim.Tween(start=100.0, target=0.0, duration=80.0)

    driver.start_tween(tw1)
    driver.start_tween(tw2)
    assert driver.is_running()
    assert driver.active_count() == 2

    # Step past tw1
    driver.step_manual(70.0)
    assert driver.active_count() == 1
    assert driver.is_running()

    # Step past tw2
    driver.step_manual(90.0)
    assert driver.active_count() == 0
    assert not driver.is_running()
    print("  [PASS] test_driver_stops_when_idle")


def test_retarget_mid_flight() -> None:
    """Verifies retargeting mid-flight continues from current value without jumps."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = False

    tw = anim.Tween(start=0.0, target=100.0, duration=200.0, driver=driver)
    tw.start()

    # Advance 100ms (50% progress, for OutCubic 1 - (1-0.5)^3 = 0.875 -> 87.5)
    driver.step_manual(100.0)
    mid_val = tw.value
    assert 80.0 < mid_val < 92.0, f"Expected OutCubic mid value around 87.5, got {mid_val}"

    # Retarget to 200.0
    tw.retarget(200.0, duration=150.0)

    # Start value of the retargeted segment MUST equal current mid-flight value
    assert abs(tw.start_val - mid_val) < 1e-4, "Start value did not match in-flight value"
    assert tw.target_val == 200.0

    # Advance small delta (10ms) - value should move smoothly from mid_val, never jumping to 0 or 200
    driver.step_manual(10.0)
    assert mid_val <= tw.value < 200.0

    # Advance to completion
    driver.step_manual(160.0)
    assert abs(tw.value - 200.0) < 1e-4
    assert not driver.is_running()
    print("  [PASS] test_retarget_mid_flight")


def test_reduce_motion_instant() -> None:
    """Verifies that reduce_motion forces instant completion without timer running."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = True

    done_called = False

    def on_done() -> None:
        nonlocal done_called
        done_called = True

    tw = anim.Tween(start=0.0, target=75.0, duration=500.0, on_done=on_done)
    driver.start_tween(tw)

    assert tw.value == 75.0
    assert tw.is_finished
    assert done_called
    assert not driver.is_running()
    assert driver.active_count() == 0
    print("  [PASS] test_reduce_motion_instant")


def test_press_tween() -> None:
    """Verifies tactile press and release spring feedback."""
    get_qapp()
    driver = anim.AnimationDriver()
    driver.reduce_motion = False

    pt = anim.PressTween(driver=driver)
    assert pt.scale == 1.0

    # Press
    pt.press()
    assert driver.is_running()
    driver.step_manual(80.0)
    assert abs(pt.scale - 0.94) < 1e-4

    # Release
    pt.release()
    driver.step_manual(200.0)
    assert abs(pt.scale - 1.0) < 1e-4
    assert not driver.is_running()
    print("  [PASS] test_press_tween")


def test_hover_magnifier() -> None:
    """Verifies HoverMagnifier cosine falloff across icons and neighbors."""
    # Discrete index mode
    items = anim.HoverMagnifier.compute_for_index(num_items=5, hovered_idx=2)
    assert items[2] == (1.20, -3.5)
    # Immediate neighbors (1 and 3)
    assert abs(items[1][0] - 1.07) < 0.01
    assert abs(items[1][1] - (-1.225)) < 0.01
    assert abs(items[3][0] - 1.07) < 0.01
    assert abs(items[3][1] - (-1.225)) < 0.01
    # Distant items (0 and 4)
    assert items[0] == (1.0, 0.0)
    assert items[4] == (1.0, 0.0)

    # Continuous X mode
    centers = [20.0, 58.0, 96.0, 134.0, 172.0]
    res_x = anim.HoverMagnifier.compute_for_x(centers, mouse_x=96.0, slot_width=38.0)
    assert abs(res_x[2][0] - 1.20) < 1e-4
    assert abs(res_x[2][1] - (-3.5)) < 1e-4
    assert abs(res_x[1][0] - 1.07) < 0.01
    assert abs(res_x[3][0] - 1.07) < 0.01
    print("  [PASS] test_hover_magnifier")


def test_ring_gauge_threshold_colors() -> None:
    """Verifies warning (>=80%) and critical (>=95%) threshold color logic."""
    col_normal = theme.COLOR_CPU
    assert theme.get_ring_threshold_color(7.0, col_normal) == col_normal
    assert theme.get_ring_threshold_color(42.0, col_normal) == col_normal
    assert theme.get_ring_threshold_color(80.0, col_normal) == theme.COLOR_ALERT_WARN
    assert theme.get_ring_threshold_color(83.0, col_normal) == theme.COLOR_ALERT_WARN
    assert theme.get_ring_threshold_color(95.0, col_normal) == theme.COLOR_ALERT_CRIT
    assert theme.get_ring_threshold_color(97.0, col_normal) == theme.COLOR_ALERT_CRIT
    print("  [PASS] test_ring_gauge_threshold_colors")


# ==============================================================================
# VISUAL SHOWCASE RENDER AT DPR 2
# ==============================================================================


def render_showcase_image() -> Path:
    """Renders a comprehensive design showcase to PNG at DPR 2.0.

    Elements included:
      - Physical glass capsule with 3% noise grain and inner specular rim
      - Claude Session ring at 7% (Normal #F08A5D) + label/value stack
      - Claude Week ring at 42% (Normal #F6B38F) + label/value stack
      - Vertical hairlines (Separators 1, 2, 3)
      - App icons with crisp downscaling from C:/Windows/explorer.exe
      - App indicators: active pill (12x3px) and inactive running dots (4px circle)
      - Hover lift and tactile press previews
      - CPU ring at 83% (Threshold Warning #FFC45C)
      - RAM ring at 97% (Threshold Critical #FF6E6E)
      - Weather and Clock chips
    """
    get_qapp()

    dpr = 2.0
    w_logical = 800
    h_logical = 120
    w_phys = int(w_logical * dpr)
    h_phys = int(h_logical * dpr)

    img = QImage(w_phys, h_phys, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    # 1. Desktop background wallpaper simulation (rich dark gradient with subtle glow)
    bg_grad = QLinearGradient(0, 0, w_logical, h_logical)
    bg_grad.setColorAt(0.0, QColor("#131722"))
    bg_grad.setColorAt(0.5, QColor("#1b2232"))
    bg_grad.setColorAt(1.0, QColor("#0f131a"))
    p.fillRect(QRectF(0, 0, w_logical, h_logical), bg_grad)

    # Ambient light catch behind dock to showcase acrylic translucency
    glow = QRadialGradient(w_logical * 0.40, h_logical * 0.7, 220.0)
    glow.setColorAt(0.0, QColor(240, 138, 93, 40))  # Warm amber ambient catch
    glow.setColorAt(0.5, QColor(96, 181, 255, 25))  # Cool cyan ambient catch
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(0, 0, w_logical, h_logical), glow)

    # Measure exact font metrics for dynamic chip widths
    f_lbl = theme.make_font(theme.FONT_SIZE_LBL, QFont.Weight.Normal, letter_spacing=0.2)
    f_val = theme.make_font(theme.FONT_SIZE_VAL, QFont.Weight.DemiBold, tabular=True)
    f_clock = theme.make_font(theme.FONT_SIZE_CLOCK, QFont.Weight.Bold, tabular=True)

    fm_l = QFontMetricsF(f_lbl)
    fm_v = QFontMetricsF(f_val)
    fm_c = QFontMetricsF(f_clock)

    # Calculate content widths
    # 1. Claude Session
    w_s_text = max(fm_l.horizontalAdvance("Oturum"), fm_v.horizontalAdvance("4sa 35dk"))
    w_chip_s = 34.0 + 7.0 + w_s_text

    # 2. Claude Week
    w_w_text = max(fm_l.horizontalAdvance("Hafta"), fm_v.horizontalAdvance("4g 18sa"))
    w_chip_w = 34.0 + 7.0 + w_w_text

    # 3. Separator 1
    w_sep1 = theme.SEP_WIDTH

    # 4. Apps (3 apps: 38px each with 2px gap)
    w_apps = 3 * 38.0 + 2 * theme.ITEM_GAP

    # 5. Separator 2
    w_sep2 = theme.SEP_WIDTH

    # 6. System (CPU 34 + 6 + RAM 34 = 74)
    w_sys = 74.0

    # 7. Separator 3
    w_sep3 = theme.SEP_WIDTH

    # 8. Weather (22px icon + 7px + text)
    w_wx_text = max(fm_l.horizontalAdvance("Aksaray"), fm_v.horizontalAdvance("23° Açık"))
    w_wx = 22.0 + 7.0 + w_wx_text

    # 9. Clock (time 14:34 / date Pzt 26 Eki)
    w_clock_text = max(fm_c.horizontalAdvance("14:34"), fm_l.horizontalAdvance("Pzt 26 Eki"))
    w_clock = w_clock_text

    # Sum total inner width
    total_content_w = (
        w_chip_s + theme.GAP_MODULE +
        w_chip_w + theme.GAP_SEPARATOR +
        w_sep1 + theme.GAP_SEPARATOR +
        w_apps + theme.GAP_SEPARATOR +
        w_sep2 + theme.GAP_SEPARATOR +
        w_sys + theme.GAP_SEPARATOR +
        w_sep3 + theme.GAP_SEPARATOR +
        w_wx + theme.GAP_MODULE +
        w_clock
    )

    dock_w = total_content_w + 2.0 * theme.DOCK_PAD_X
    dock_h = theme.DOCK_HEIGHT
    dock_x = (w_logical - dock_w) / 2.0
    dock_y = (h_logical - dock_h) / 2.0
    dock_rect = QRectF(dock_x, dock_y, dock_w, dock_h)

    # 2. Draw physical glass capsule with grain & specular rim
    theme.draw_glass_capsule(
        p,
        dock_rect,
        radius=theme.DOCK_RADIUS,
        show_grain=True,
        show_specular=True,
        show_outer_stroke=True,
    )

    # Layout cursor
    cur_x = dock_x + theme.DOCK_PAD_X

    # --- ITEM 1: Claude Oturum (7%) ---
    theme.draw_ring_gauge(
        p,
        center=QPointF(cur_x + 17.0, dock_y + dock_h / 2.0),
        size=theme.RING_SIZE,
        stroke=theme.RING_STROKE,
        value_0_100=7.0,
        colour=theme.COLOR_CLAUDE_SESSION,
    )
    theme.draw_chip_text(p, x=cur_x + 39.0, y=dock_y, label="Oturum", value="4sa 35dk")
    cur_x += w_chip_s + theme.GAP_MODULE

    # --- ITEM 2: Claude Hafta (42%) ---
    theme.draw_ring_gauge(
        p,
        center=QPointF(cur_x + 17.0, dock_y + dock_h / 2.0),
        size=theme.RING_SIZE,
        stroke=theme.RING_STROKE,
        value_0_100=42.0,
        colour=theme.COLOR_CLAUDE_WEEK,
    )
    theme.draw_chip_text(p, x=cur_x + 39.0, y=dock_y, label="Hafta", value="4g 18sa")
    cur_x += w_chip_w + theme.GAP_SEPARATOR

    # --- SEPARATOR 1 ---
    theme.draw_separator(p, x=cur_x, y=dock_y + theme.SEP_Y, height=theme.SEP_HEIGHT)
    cur_x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

    # --- APP LAUNCHERS ---
    # Extract real Windows explorer icon
    icon_provider = QFileIconProvider()
    raw_icon = icon_provider.icon(QFileInfo("C:/Windows/explorer.exe"))
    explorer_pm = raw_icon.pixmap(QSize(256, 256))

    # App 1: Explorer (Active with pill indicator)
    app1_cx = cur_x + 19.0
    icon1_rect = QRectF(cur_x + (38.0 - theme.ICON_SIZE) / 2.0, dock_y + 10.0, theme.ICON_SIZE, theme.ICON_SIZE)
    theme.draw_icon_crisp(p, explorer_pm, icon1_rect)
    theme.draw_app_indicator(p, center_x=app1_cx, center_y=dock_y + theme.INDICATOR_Y, is_active=True)
    cur_x += 38.0 + theme.ITEM_GAP

    # App 2: Terminal / Code (Hovered: lifted by 3.5px with running dot)
    app2_cx = cur_x + 19.0
    hover_lift = theme.HOVER_LIFT_Y
    icon2_rect = QRectF(
        cur_x + (38.0 - theme.ICON_SIZE) / 2.0,
        dock_y + 10.0 + hover_lift,
        theme.ICON_SIZE,
        theme.ICON_SIZE,
    )
    # Hover chip highlight
    chip_hover_rect = QRectF(cur_x, dock_y + theme.CHIP_Y, 38.0, theme.CHIP_HEIGHT)
    theme.draw_glass_capsule(p, chip_hover_rect, radius=11.0, is_hovered=True, show_grain=False)
    theme.draw_icon_crisp(p, explorer_pm, icon2_rect)
    theme.draw_app_indicator(p, center_x=app2_cx, center_y=dock_y + theme.INDICATOR_Y, is_active=False)
    cur_x += 38.0 + theme.ITEM_GAP

    # App 3: Browser (Running dot)
    app3_cx = cur_x + 19.0
    icon3_rect = QRectF(cur_x + (38.0 - theme.ICON_SIZE) / 2.0, dock_y + 10.0, theme.ICON_SIZE, theme.ICON_SIZE)
    theme.draw_icon_crisp(p, explorer_pm, icon3_rect)
    theme.draw_app_indicator(p, center_x=app3_cx, center_y=dock_y + theme.INDICATOR_Y, is_active=False)
    cur_x += 38.0 + theme.GAP_SEPARATOR

    # --- SEPARATOR 2 ---
    theme.draw_separator(p, x=cur_x, y=dock_y + theme.SEP_Y, height=theme.SEP_HEIGHT)
    cur_x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

    # --- SYSTEM MONITORS: CPU (83% Warning) & RAM (97% Critical) ---
    sys_cx = cur_x
    # CPU (83% - Amber warning)
    theme.draw_ring_gauge(
        p,
        center=QPointF(sys_cx + 17.0, dock_y + dock_h / 2.0),
        size=theme.RING_SIZE,
        stroke=theme.RING_STROKE,
        value_0_100=83.0,
        colour=theme.COLOR_CPU,
    )
    # RAM (97% - Coral red critical)
    theme.draw_ring_gauge(
        p,
        center=QPointF(sys_cx + 17.0 + 34.0 + 6.0, dock_y + dock_h / 2.0),
        size=theme.RING_SIZE,
        stroke=theme.RING_STROKE,
        value_0_100=97.0,
        colour=theme.COLOR_RAM,
    )
    cur_x += w_sys + theme.GAP_SEPARATOR

    # --- SEPARATOR 3 ---
    theme.draw_separator(p, x=cur_x, y=dock_y + theme.SEP_Y, height=theme.SEP_HEIGHT)
    cur_x += theme.SEP_WIDTH + theme.GAP_SEPARATOR

    # --- WEATHER CHIP ---
    theme.draw_weather_icon(p, QRectF(cur_x, dock_y + (dock_h - 22.0) / 2.0, 22.0, 22.0), icon="partly")
    theme.draw_chip_text(p, x=cur_x + 29.0, y=dock_y, label="Aksaray", value="23° Açık")
    cur_x += w_wx + theme.GAP_MODULE

    # --- CLOCK CHIP ---
    p.setFont(f_clock)
    p.setPen(theme.COLOR_TEXT_PRIMARY)
    p.drawText(QRectF(cur_x, dock_y + 11.0, w_clock + 2.0, 16.0), Qt.AlignLeft | Qt.AlignVCenter, "14:34")
    p.setFont(f_lbl)
    p.setPen(theme.COLOR_TEXT_SECONDARY)
    p.drawText(QRectF(cur_x, dock_y + 26.0, w_clock + 2.0, 14.0), Qt.AlignLeft | Qt.AlignVCenter, "Pzt 26 Eki")

    p.end()

    # Ensure parent output directory exists
    SHOWCASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    success = img.save(str(SHOWCASE_PATH))
    if not success:
        raise RuntimeError(f"Failed to save showcase image to {SHOWCASE_PATH}")

    print(f"  [SAVED] Showcase render exported: {SHOWCASE_PATH}")
    return SHOWCASE_PATH


def run_all_tests() -> None:
    print("=" * 60)
    print("RUNNING ŞERİT THEME & ANIMATION ENGINE TEST SUITE")
    print("=" * 60)

    test_tween_reaches_target()
    test_driver_stops_when_idle()
    test_retarget_mid_flight()
    test_reduce_motion_instant()
    test_press_tween()
    test_hover_magnifier()
    test_ring_gauge_threshold_colors()

    out_png = render_showcase_image()
    assert os.path.exists(out_png) and os.path.getsize(out_png) > 1000

    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
