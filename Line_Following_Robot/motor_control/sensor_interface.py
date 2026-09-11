"""
Line-Following Robot: Hardware Sensor & Actuator Interface
==========================================================
Provides unified hardware abstraction for:
- 5-channel optical IR sensor array
- Dual-channel DC Motor Driver (L298N / TB6612FNG)
- INA219 current / power sensor (optional)
Includes transparent software simulation fallback when running on PC/laptop.
"""

import math
import os
import random
import time
from typing import Dict, List, Tuple

ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False


class SensorInterface:
    """
    Interface for 5-channel line tracker IR sensors and DC motors.
    """
    def __init__(self, simulation: bool = not ON_RASPBERRY_PI):
        self.simulation = simulation
        self._sim_track_pos = 0.0  # -2.0 (far left) to +2.0 (far right), 0.0 = centered
        self._sim_time = time.perf_counter()

    def read_ir_array(self) -> Tuple[List[int], float]:
        """
        Reads the 5 IR sensors (values: 0 = white/floor, 1 = black/line).
        Returns:
            (raw_sensor_bits, calculated_line_position_offset)
            offset range: -2.0 (sharp left) to +2.0 (sharp right), 0.0 = centered
        """
        if self.simulation:
            # Simulate track meandering: straight, gentle curve, sharp turn
            elapsed = time.perf_counter() - self._sim_time
            # Curvature profile
            curvature = math.sin(elapsed * 0.8) * 1.5
            self._sim_track_pos = curvature + random.uniform(-0.1, 0.1)

            pos = self._sim_track_pos
            # 5-channel sensor response [IR_L2, IR_L1, IR_MID, IR_R1, IR_R2]
            bits = [0, 0, 0, 0, 0]
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

        # Real Raspberry Pi GPIO reads:
        # e.g., [GPIO.input(p) for p in (17, 27, 22, 23, 24)]
        return [0, 0, 1, 0, 0], 0.0

    def set_motor_speeds(self, left_pwm: float, right_pwm: float) -> None:
        """
        Commands motor driver speeds (-100.0 to 100.0).
        """
        left_pwm = max(-100.0, min(100.0, left_pwm))
        right_pwm = max(-100.0, min(100.0, right_pwm))
        if not self.simulation:
            # Real PWM command via RPi.GPIO or pigpio
            pass

    def read_power_metrics(self) -> Dict[str, float]:
        """
        Reads voltage, current, and estimated power (mW).
        """
        if self.simulation:
            base_power_mw = 1800.0  # Pi 4 base idle ~1.8W
            return {
                "voltage_v": 5.05,
                "current_ma": 380.0 + random.uniform(10.0, 50.0),
                "power_mw": base_power_mw + random.uniform(50.0, 250.0)
            }
        return {"voltage_v": 5.0, "current_ma": 400.0, "power_mw": 2000.0}
