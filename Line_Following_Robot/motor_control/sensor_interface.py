"""
Line-Following Robot: Hardware Sensor & Actuator Interface
==========================================================
Provides unified hardware abstraction for:
- 5-channel optical IR sensor array
- Dual-channel DC Motor Driver (L298N / TB6612FNG) via PWM
- INA219 current / power sensor (I2C, optional)

On Raspberry Pi 4/5 (Ubuntu 22.04+): uses RPi.GPIO for real hardware control.
On any other platform (Windows, macOS, x86 Linux): transparent simulation fallback.

RPi Ubuntu setup:
    sudo apt-get install -y lgpio libgpiod2
    pip install RPi.GPIO smbus2 pi-ina219
"""

import math
import os
import random
import time
from typing import Dict, List, Optional, Tuple

# ── Platform detection ──────────────────────────────────────────────────────
ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        with open("/sys/firmware/devicetree/base/model", "r") as _f:
            _model = _f.read().lower()
        if "raspberry pi" in _model:
            ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False

# ── GPIO import (RPi only) ───────────────────────────────────────────────────
_GPIO = None
if ON_RASPBERRY_PI:
    try:
        import RPi.GPIO as _GPIO  # type: ignore
    except ImportError:
        print("[WARN] RPi.GPIO not installed — falling back to simulation. "
              "Run: pip install RPi.GPIO  (also needs: sudo apt install lgpio)")
        _GPIO = None

# ── INA219 import (optional, RPi only) ──────────────────────────────────────
_INA219 = None
_ina219_instance: Optional[object] = None
if ON_RASPBERRY_PI:
    try:
        from ina219 import INA219 as _INA219  # type: ignore
    except ImportError:
        _INA219 = None

# ── Pin assignments ──────────────────────────────────────────────────────────
# 5-channel IR array (BCM numbering)
IR_PINS: Tuple[int, ...] = (17, 27, 22, 23, 24)  # L2, L1, MID, R1, R2

# L298N motor driver (BCM)
LEFT_EN   = 12   # PWM-capable (PWM0)
LEFT_IN1  = 5
LEFT_IN2  = 6
RIGHT_EN  = 13   # PWM-capable (PWM1)
RIGHT_IN1 = 20
RIGHT_IN2 = 21

# INA219 I2C address
INA219_ADDRESS   = 0x40
INA219_MAX_A     = 0.4   # shunt resistor rated current (A)
INA219_R_SHUNT   = 0.1   # shunt resistance (Ω)

_PWM_FREQ = 1000  # Hz


class SensorInterface:
    """
    Interface for 5-channel line tracker IR sensors, DC motors, and
    optional INA219 power monitoring.

    Args:
        simulation: If True, use software simulation. Defaults to
                    True on non-RPi platforms, False on Raspberry Pi.
    """

    def __init__(self, simulation: bool = not ON_RASPBERRY_PI):
        self.simulation = simulation or (_GPIO is None)
        self._sim_track_pos = 0.0   # -2.0 (far left) .. +2.0 (far right)
        self._sim_time = time.perf_counter()

        self._left_pwm: Optional[object]  = None
        self._right_pwm: Optional[object] = None

        if not self.simulation and _GPIO is not None:
            self._gpio_setup()

        # INA219
        if not self.simulation and _INA219 is not None:
            try:
                _ina = _INA219(INA219_R_SHUNT, INA219_MAX_A, address=INA219_ADDRESS)
                _ina.configure()
                self._ina = _ina
            except Exception as exc:
                print(f"[WARN] INA219 init failed: {exc} — power metrics will be simulated.")
                self._ina = None
        else:
            self._ina = None

    # ── GPIO Initialisation ───────────────────────────────────────────────────

    def _gpio_setup(self) -> None:
        """Configure all GPIO pins (BCM mode)."""
        _GPIO.setmode(_GPIO.BCM)
        _GPIO.setwarnings(False)

        # IR sensor inputs (with pull-down resistors)
        for pin in IR_PINS:
            _GPIO.setup(pin, _GPIO.IN, pull_up_down=_GPIO.PUD_DOWN)

        # Motor driver outputs
        for pin in (LEFT_IN1, LEFT_IN2, RIGHT_IN1, RIGHT_IN2):
            _GPIO.setup(pin, _GPIO.OUT)
            _GPIO.output(pin, _GPIO.LOW)

        # Enable (PWM) pins
        _GPIO.setup(LEFT_EN,  _GPIO.OUT)
        _GPIO.setup(RIGHT_EN, _GPIO.OUT)
        self._left_pwm  = _GPIO.PWM(LEFT_EN,  _PWM_FREQ)
        self._right_pwm = _GPIO.PWM(RIGHT_EN, _PWM_FREQ)
        self._left_pwm.start(0)
        self._right_pwm.start(0)

    def cleanup(self) -> None:
        """Release all GPIO resources. Call on shutdown."""
        if not self.simulation and _GPIO is not None:
            if self._left_pwm is not None:
                self._left_pwm.stop()
            if self._right_pwm is not None:
                self._right_pwm.stop()
            _GPIO.cleanup()

    # ── IR Sensor Array ───────────────────────────────────────────────────────

    def read_ir_array(self) -> Tuple[List[int], float]:
        """
        Reads the 5 IR sensors (0 = white/floor, 1 = black/line).

        Returns:
            (raw_sensor_bits, line_position_offset)
            offset range: -2.0 (sharp left) .. +2.0 (sharp right), 0.0 = centred
        """
        if self.simulation:
            return self._sim_read_ir()

        # ── Real GPIO reads ──────────────────────────────────────────────────
        bits = [int(_GPIO.input(pin)) for pin in IR_PINS]
        offset = self._compute_offset(bits)
        return bits, offset

    @staticmethod
    def _compute_offset(bits: List[int]) -> float:
        """
        Weighted centroid line position from 5-channel IR array.
        Sensor weights: [-2, -1, 0, +1, +2]
        """
        weights = [-2.0, -1.0, 0.0, 1.0, 2.0]
        total_weight = sum(b * w for b, w in zip(bits, weights))
        total_active = sum(bits)
        if total_active == 0:
            return 0.0   # no line detected — stay last heading
        return total_weight / total_active

    def _sim_read_ir(self) -> Tuple[List[int], float]:
        """Simulate track meandering: straight → gentle curve → sharp turn."""
        elapsed = time.perf_counter() - self._sim_time
        curvature = math.sin(elapsed * 0.8) * 1.5
        self._sim_track_pos = curvature + random.uniform(-0.1, 0.1)
        pos = self._sim_track_pos

        if pos < -1.2:
            bits = [1, 1, 0, 0, 0]
        elif -1.2 <= pos < -0.4:
            bits = [0, 1, 1, 0, 0]
        elif -0.4 <= pos <= 0.4:
            bits = [0, 0, 1, 0, 0]
        elif 0.4 < pos <= 1.2:
            bits = [0, 0, 1, 1, 0]
        else:
            bits = [0, 0, 0, 1, 1]

        return bits, pos

    # ── Motor Control ─────────────────────────────────────────────────────────

    def set_motor_speeds(self, left_pwm: float, right_pwm: float) -> None:
        """
        Commands differential drive motor speeds.

        Args:
            left_pwm:  Left motor speed  (-100.0 reverse .. +100.0 forward)
            right_pwm: Right motor speed (-100.0 reverse .. +100.0 forward)
        """
        left_pwm  = max(-100.0, min(100.0, left_pwm))
        right_pwm = max(-100.0, min(100.0, right_pwm))

        if self.simulation or _GPIO is None:
            return   # No hardware — silently skip

        # ── Left motor ────────────────────────────────────────────────────────
        if left_pwm >= 0:
            _GPIO.output(LEFT_IN1, _GPIO.HIGH)
            _GPIO.output(LEFT_IN2, _GPIO.LOW)
        else:
            _GPIO.output(LEFT_IN1, _GPIO.LOW)
            _GPIO.output(LEFT_IN2, _GPIO.HIGH)
        self._left_pwm.ChangeDutyCycle(abs(left_pwm))

        # ── Right motor ───────────────────────────────────────────────────────
        if right_pwm >= 0:
            _GPIO.output(RIGHT_IN1, _GPIO.HIGH)
            _GPIO.output(RIGHT_IN2, _GPIO.LOW)
        else:
            _GPIO.output(RIGHT_IN1, _GPIO.LOW)
            _GPIO.output(RIGHT_IN2, _GPIO.HIGH)
        self._right_pwm.ChangeDutyCycle(abs(right_pwm))

    def stop_motors(self) -> None:
        """Emergency stop — cuts all motor drive immediately."""
        if not self.simulation and _GPIO is not None:
            for pin in (LEFT_IN1, LEFT_IN2, RIGHT_IN1, RIGHT_IN2):
                _GPIO.output(pin, _GPIO.LOW)
            if self._left_pwm is not None:
                self._left_pwm.ChangeDutyCycle(0)
            if self._right_pwm is not None:
                self._right_pwm.ChangeDutyCycle(0)

    # ── Power Monitoring ──────────────────────────────────────────────────────

    def read_power_metrics(self) -> Dict[str, float]:
        """
        Reads voltage (V), current (mA), and estimated power (mW).
        Uses INA219 over I2C when available; falls back to simulation otherwise.
        """
        if self._ina is not None:
            try:
                return {
                    "voltage_v":  self._ina.voltage(),
                    "current_ma": self._ina.current(),
                    "power_mw":   self._ina.power(),
                }
            except Exception:
                pass   # fall through to simulation on transient I2C error

        # ── Simulation fallback ───────────────────────────────────────────────
        return {
            "voltage_v":  5.05,
            "current_ma": 380.0 + random.uniform(10.0, 50.0),
            "power_mw":   1800.0 + random.uniform(50.0, 250.0),
        }
