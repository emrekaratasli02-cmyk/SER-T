"""anim.py - 60 FPS animation engine and zero-idle CPU driver for Şerit dock.

Coordinates property interpolations, tactile spring/press feedback, and icon
magnification using a centralized 16ms QTimer driver that stops completely
when all tweens are idle. Fully compliant with Windows Reduce Motion.
"""

from __future__ import annotations

import math
import time
from typing import Callable, List, Optional, Set, Tuple

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, QTimer, Signal


def get_system_reduce_motion() -> bool:
    """Reads Windows accessibility animation setting (SPI_GETCLIENTAREAANIMATION = 0x1042).

    Returns True if animations should be reduced (i.e. system animation is disabled).
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        user32.SystemParametersInfoW.restype = wintypes.BOOL
        val = wintypes.BOOL()
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        res = user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(val), 0)
        if res:
            return not bool(val.value)
    except Exception:
        pass
    return False


# ==============================================================================
# 1. BASE TWEEN & FLOAT TWEEN
# ==============================================================================


class BaseTween:
    """Abstract base class for property tweens."""

    def __init__(
        self,
        duration: float = 200.0,
        easing: QEasingCurve.Type | QEasingCurve = QEasingCurve.Type.OutCubic,
        on_done: Optional[Callable[[], None]] = None,
        driver: Optional[AnimationDriver] = None,
    ) -> None:
        self.duration_ms: float = float(duration)
        if isinstance(easing, QEasingCurve):
            self.easing_curve: QEasingCurve = easing
        else:
            self.easing_curve = QEasingCurve(easing)

        self.on_done: Optional[Callable[[], None]] = on_done
        self._driver: Optional[AnimationDriver] = driver
        self.start_time_ms: float = 0.0
        self.is_finished: bool = True

    def set_driver(self, driver: AnimationDriver) -> None:
        self._driver = driver

    def update(self, now_ms: float) -> bool:
        """Advances the tween to now_ms. Returns True if completed."""
        raise NotImplementedError

    def finish(self) -> None:
        """Snaps value to target and triggers completion callback."""
        raise NotImplementedError

    def finish_instant(self) -> None:
        """Instantly terminates at target value without animation."""
        raise NotImplementedError

    def stop(self) -> None:
        """Halts tween at its current value."""
        self.is_finished = True
        if self._driver is not None:
            self._driver.remove_tween(self)


class Tween(BaseTween):
    """Animates a single floating-point property.

    Supports mid-flight retargeting without visual jumps, seamlessly picking
    up from the current in-flight value.
    """

    def __init__(
        self,
        start: float = 0.0,
        target: float = 0.0,
        duration: float = 200.0,
        easing: QEasingCurve.Type | QEasingCurve = QEasingCurve.Type.OutCubic,
        on_update: Optional[Callable[[float], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        driver: Optional[AnimationDriver] = None,
    ) -> None:
        super().__init__(duration=duration, easing=easing, on_done=on_done, driver=driver)
        self.value: float = float(start)
        self.start_val: float = float(start)
        self.target_val: float = float(target)
        self.on_update: Optional[Callable[[float], None]] = on_update

    def start(self, driver: Optional[AnimationDriver] = None) -> Tween:
        """Registers and starts the tween with the given or default driver."""
        drv = driver or self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)
        return self

    def retarget(self, new_target: float, duration: Optional[float] = None) -> None:
        """Redirects tween to a new target starting smoothly from its current value."""
        # Zaten hedefte ve hareketsizse hiçbir şey yapma: aksi halde her veri gelişinde
        # (2 sn) sürücü 60 fps tam çizim başlatıp boşta işlemci harcıyordu.
        if abs(float(new_target) - self.target_val) < 1e-6 and abs(self.value - self.target_val) < 1e-6:
            return
        self.start_val = self.value
        self.target_val = float(new_target)
        if duration is not None:
            self.duration_ms = float(duration)

        drv = self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)

    def update(self, now_ms: float) -> bool:
        if self.duration_ms <= 0.0:
            self.value = self.target_val
            if self.on_update is not None:
                self.on_update(self.value)
            self.is_finished = True
            return True

        elapsed = now_ms - self.start_time_ms
        progress = max(0.0, min(1.0, elapsed / self.duration_ms))
        eased = self.easing_curve.valueForProgress(progress)

        self.value = self.start_val + (self.target_val - self.start_val) * eased

        if self.on_update is not None:
            self.on_update(self.value)

        if progress >= 1.0:
            self.value = self.target_val
            self.is_finished = True
            return True

        return False

    def finish(self) -> None:
        self.value = self.target_val
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()

    def finish_instant(self) -> None:
        self.value = self.target_val
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()


# Alias for explicit typing
FloatTween = Tween


# ==============================================================================
# 2. POINT & RECT TWEENS
# ==============================================================================


class PointTween(BaseTween):
    """Animates a 2D coordinate (QPointF) with smooth retargeting."""

    def __init__(
        self,
        start: QPointF,
        target: QPointF,
        duration: float = 200.0,
        easing: QEasingCurve.Type | QEasingCurve = QEasingCurve.Type.OutCubic,
        on_update: Optional[Callable[[QPointF], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        driver: Optional[AnimationDriver] = None,
    ) -> None:
        super().__init__(duration=duration, easing=easing, on_done=on_done, driver=driver)
        self.value: QPointF = QPointF(start)
        self.start_pt: QPointF = QPointF(start)
        self.target_pt: QPointF = QPointF(target)
        self.on_update: Optional[Callable[[QPointF], None]] = on_update

    def start(self, driver: Optional[AnimationDriver] = None) -> PointTween:
        drv = driver or self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)
        return self

    def retarget(self, new_target: QPointF, duration: Optional[float] = None) -> None:
        self.start_pt = QPointF(self.value)
        self.target_pt = QPointF(new_target)
        if duration is not None:
            self.duration_ms = float(duration)
        drv = self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)

    def update(self, now_ms: float) -> bool:
        if self.duration_ms <= 0.0:
            self.value = QPointF(self.target_pt)
            if self.on_update is not None:
                self.on_update(self.value)
            self.is_finished = True
            return True

        elapsed = now_ms - self.start_time_ms
        progress = max(0.0, min(1.0, elapsed / self.duration_ms))
        eased = self.easing_curve.valueForProgress(progress)

        nx = self.start_pt.x() + (self.target_pt.x() - self.start_pt.x()) * eased
        ny = self.start_pt.y() + (self.target_pt.y() - self.start_pt.y()) * eased
        self.value = QPointF(nx, ny)

        if self.on_update is not None:
            self.on_update(self.value)

        if progress >= 1.0:
            self.value = QPointF(self.target_pt)
            self.is_finished = True
            return True

        return False

    def finish(self) -> None:
        self.value = QPointF(self.target_pt)
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()

    def finish_instant(self) -> None:
        self.value = QPointF(self.target_pt)
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()


class RectTween(BaseTween):
    """Animates a bounding rectangle (QRectF) with smooth retargeting."""

    def __init__(
        self,
        start: QRectF,
        target: QRectF,
        duration: float = 200.0,
        easing: QEasingCurve.Type | QEasingCurve = QEasingCurve.Type.OutCubic,
        on_update: Optional[Callable[[QRectF], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        driver: Optional[AnimationDriver] = None,
    ) -> None:
        super().__init__(duration=duration, easing=easing, on_done=on_done, driver=driver)
        self.value: QRectF = QRectF(start)
        self.start_rect: QRectF = QRectF(start)
        self.target_rect: QRectF = QRectF(target)
        self.on_update: Optional[Callable[[QRectF], None]] = on_update

    def start(self, driver: Optional[AnimationDriver] = None) -> RectTween:
        drv = driver or self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)
        return self

    def retarget(self, new_target: QRectF, duration: Optional[float] = None) -> None:
        self.start_rect = QRectF(self.value)
        self.target_rect = QRectF(new_target)
        if duration is not None:
            self.duration_ms = float(duration)
        drv = self._driver or get_default_driver()
        self.set_driver(drv)
        now_ms = drv._simulated_time_ms if drv._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        self.start_time_ms = now_ms
        self.is_finished = False
        drv.start_tween(self)

    def update(self, now_ms: float) -> bool:
        if self.duration_ms <= 0.0:
            self.value = QRectF(self.target_rect)
            if self.on_update is not None:
                self.on_update(self.value)
            self.is_finished = True
            return True

        elapsed = now_ms - self.start_time_ms
        progress = max(0.0, min(1.0, elapsed / self.duration_ms))
        eased = self.easing_curve.valueForProgress(progress)

        nx = self.start_rect.x() + (self.target_rect.x() - self.start_rect.x()) * eased
        ny = self.start_rect.y() + (self.target_rect.y() - self.start_rect.y()) * eased
        nw = self.start_rect.width() + (self.target_rect.width() - self.start_rect.width()) * eased
        nh = self.start_rect.height() + (self.target_rect.height() - self.start_rect.height()) * eased
        self.value = QRectF(nx, ny, nw, nh)

        if self.on_update is not None:
            self.on_update(self.value)

        if progress >= 1.0:
            self.value = QRectF(self.target_rect)
            self.is_finished = True
            return True

        return False

    def finish(self) -> None:
        self.value = QRectF(self.target_rect)
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()

    def finish_instant(self) -> None:
        self.value = QRectF(self.target_rect)
        self.is_finished = True
        if self.on_update is not None:
            self.on_update(self.value)
        if self.on_done is not None:
            self.on_done()


# ==============================================================================
# 3. TACTILE PRESS & SPRING FEEDBACK
# ==============================================================================


class PressTween:
    """Tactile press feedback helper with OutQuad compression and OutBack spring release."""

    def __init__(
        self,
        normal_scale: float = 1.0,
        pressed_scale: float = 0.94,
        press_duration: float = 70.0,
        release_duration: float = 180.0,
        on_update: Optional[Callable[[float], None]] = None,
        driver: Optional[AnimationDriver] = None,
    ) -> None:
        self.normal_scale: float = normal_scale
        self.pressed_scale: float = pressed_scale
        self.press_duration: float = press_duration
        self.release_duration: float = release_duration
        self.on_update: Optional[Callable[[float], None]] = on_update

        self._tween = Tween(
            start=normal_scale,
            target=normal_scale,
            duration=press_duration,
            easing=QEasingCurve.Type.OutQuad,
            on_update=self._handle_update,
            driver=driver,
        )

    def _handle_update(self, val: float) -> None:
        if self.on_update is not None:
            self.on_update(val)

    @property
    def scale(self) -> float:
        return self._tween.value

    def press(self) -> None:
        """Triggers the fast press squish (OutQuad)."""
        self._tween.easing_curve = QEasingCurve(QEasingCurve.Type.OutQuad)
        self._tween.retarget(self.pressed_scale, duration=self.press_duration)

    def release(self) -> None:
        """Triggers the bouncy spring release (OutBack)."""
        self._tween.easing_curve = QEasingCurve(QEasingCurve.Type.OutBack)
        self._tween.retarget(self.normal_scale, duration=self.release_duration)

    def reset(self) -> None:
        """Snaps scale back to normal immediately."""
        self._tween.stop()
        self._tween.value = self.normal_scale
        self._handle_update(self.normal_scale)


# ==============================================================================
# 4. HOVER MAGNIFIER & COSINE FALLOFF
# ==============================================================================


class HoverMagnifier:
    """Calculates per-icon scale and lift using smooth cosine falloff.

    Target peak: 1.20 scale, -3.5px lift.
    Neighbors: ~1.08 scale, -1.22px lift (using 0.35 neighbor factor).
    """

    MAX_SCALE: float = 1.20
    MAX_LIFT: float = -3.5
    NEIGHBOR_FACTOR: float = 0.35

    @classmethod
    def compute_for_index(
        cls,
        num_items: int,
        hovered_idx: Optional[int],
    ) -> List[Tuple[float, float]]:
        """Computes (scale, lift_y) for each item given the discrete hovered index."""
        results: List[Tuple[float, float]] = []
        if hovered_idx is None or hovered_idx < 0 or hovered_idx >= num_items:
            return [(1.0, 0.0)] * num_items

        for i in range(num_items):
            diff = abs(i - hovered_idx)
            if diff == 0:
                results.append((cls.MAX_SCALE, cls.MAX_LIFT))
            elif diff == 1:
                s = 1.0 + (cls.MAX_SCALE - 1.0) * cls.NEIGHBOR_FACTOR
                lift = cls.MAX_LIFT * cls.NEIGHBOR_FACTOR
                results.append((s, lift))
            else:
                results.append((1.0, 0.0))

        return results

    @classmethod
    def compute_for_x(
        cls,
        item_centers: List[float],
        mouse_x: Optional[float],
        slot_width: float = 38.0,
    ) -> List[Tuple[float, float]]:
        """Computes (scale, lift_y) for each item from continuous cursor X position."""
        n = len(item_centers)
        if mouse_x is None or n == 0:
            return [(1.0, 0.0)] * n

        results: List[Tuple[float, float]] = []
        for cx in item_centers:
            d = abs(mouse_x - cx)
            norm_d = d / slot_width if slot_width > 0.0 else 999.0

            if norm_d <= 1.0:
                # Cosine transition from 1.0 down to NEIGHBOR_FACTOR
                factor = 1.0 - (1.0 - cls.NEIGHBOR_FACTOR) * 0.5 * (1.0 - math.cos(math.pi * norm_d))
            elif norm_d <= 2.0:
                # Cosine transition from NEIGHBOR_FACTOR down to 0.0
                factor = cls.NEIGHBOR_FACTOR * 0.5 * (1.0 + math.cos(math.pi * (norm_d - 1.0)))
            else:
                factor = 0.0

            s = 1.0 + (cls.MAX_SCALE - 1.0) * factor
            lift = cls.MAX_LIFT * factor
            results.append((s, lift))

        return results


# ==============================================================================
# 5. CENTRAL ANIMATION DRIVER (ZERO IDLE CPU)
# ==============================================================================


class AnimationDriver(QObject):
    """Central 60 FPS animation coordinator with strict 0% idle CPU consumption.

    Maintains a single 16ms QTimer that runs ONLY while at least one tween is
    active, completely stopping when the queue empties.
    """

    frame: Signal = Signal()
    frame_tick: Signal = Signal()  # Convenient alias for frame

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._on_tick)

        self._tweens: Set[BaseTween] = set()
        self.reduce_motion: bool = get_system_reduce_motion()
        self._simulated_time_ms: Optional[float] = None

    def is_running(self) -> bool:
        """Returns True if the driver timer is actively ticking."""
        return self._timer.isActive() and len(self._tweens) > 0

    def active_count(self) -> int:
        """Returns the number of currently active tweens."""
        return len(self._tweens)

    def start_tween(self, tween: BaseTween) -> None:
        """Enqueues an active tween and starts the 16ms timer if currently stopped."""
        if self.reduce_motion:
            tween.finish_instant()
            self._tweens.discard(tween)
            return

        tween.set_driver(self)
        current_time = self._simulated_time_ms if self._simulated_time_ms is not None else (time.perf_counter() * 1000.0)
        if tween.is_finished or tween.start_time_ms == 0.0:
            tween.start_time_ms = current_time
            tween.is_finished = False

        self._tweens.add(tween)
        if not self._timer.isActive():
            self._timer.start(16)

    def remove_tween(self, tween: BaseTween) -> None:
        """Removes a tween and stops the timer if no other tweens remain."""
        self._tweens.discard(tween)
        if len(self._tweens) == 0 and self._timer.isActive():
            self._timer.stop()

    def stop_all(self) -> None:
        """Halts all active tweens and stops the driver timer."""
        self._tweens.clear()
        if self._timer.isActive():
            self._timer.stop()

    def _advance_to(self, now_ms: float) -> None:
        finished: List[BaseTween] = []

        for tw in list(self._tweens):
            done = tw.update(now_ms)
            if done:
                finished.append(tw)

        for tw in finished:
            self._tweens.discard(tw)
            tw.finish()

        if len(self._tweens) == 0 and self._timer.isActive():
            self._timer.stop()

        self.frame.emit()
        self.frame_tick.emit()

    def _on_tick(self) -> None:
        """16ms tick handler: advances all active tweens in a single batch pass."""
        self._advance_to(time.perf_counter() * 1000.0)

    def step_manual(self, delta_ms: float) -> None:
        """Advances active tweens manually for deterministic headless unit tests."""
        if self._simulated_time_ms is None:
            self._simulated_time_ms = time.perf_counter() * 1000.0
        self._simulated_time_ms += delta_ms
        self._advance_to(self._simulated_time_ms)


# Global default driver instance
_DEFAULT_DRIVER: Optional[AnimationDriver] = None


def get_default_driver() -> AnimationDriver:
    """Returns the shared application AnimationDriver singleton."""
    global _DEFAULT_DRIVER
    if _DEFAULT_DRIVER is None:
        _DEFAULT_DRIVER = AnimationDriver()
    return _DEFAULT_DRIVER


def set_default_driver(driver: Optional[AnimationDriver]) -> None:
    """Sets or resets the default shared animation driver."""
    global _DEFAULT_DRIVER
    _DEFAULT_DRIVER = driver
