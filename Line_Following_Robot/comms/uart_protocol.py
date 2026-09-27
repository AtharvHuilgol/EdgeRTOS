"""
UART Protocol: RPi ↔ ESP32 Communication
==========================================
Defines the line-based ASCII protocol used to send motor commands
from Raspberry Pi to ESP32 over UART (TX0/RX0 on ESP32).

Protocol Format (RPi → ESP32):
    CMD:<left_pwm>,<right_pwm>,<base_speed>\n

    left_pwm   : -100.0 to +100.0 (signed, negative = reverse)
    right_pwm  : -100.0 to +100.0
    base_speed : 0.0 to 100.0 (for informational/safety scaling)

    Examples:
        CMD:75.0,45.0,60.0\n    → left at 75%, right at 45%
        CMD:-30.0,30.0,60.0\n   → spin left
        CMD:0.0,0.0,0.0\n       → full stop

Heartbeat (RPi → ESP32):
    HBT\n
    Sent every 500ms. If ESP32 doesn't receive any message for
    WATCHDOG_TIMEOUT_MS, it triggers emergency motor stop.

Emergency Stop:
    STP\n
    Immediate motor cut on ESP32.

Acknowledgement (ESP32 → RPi, optional):
    ACK:<status>\n
    status: OK | ERR | ESTOP

Wiring:
    RPi GPIO14 (TXD0) → ESP32 RX0 (GPIO3)
    RPi GPIO15 (RXD0) → ESP32 TX0 (GPIO1)
    Common GND
    Logic levels: RPi 3.3V ↔ ESP32 3.3V (direct connection OK)

Baud Rate: 115200
"""

import struct
from typing import Optional, Tuple

# Protocol constants
BAUD_RATE = 115200
WATCHDOG_TIMEOUT_MS = 1500  # ESP32 stops motors if no message received

# Message prefixes
PREFIX_CMD = "CMD:"
PREFIX_HBT = "HBT"
PREFIX_STP = "STP"
PREFIX_ACK = "ACK:"

# Line terminator
TERMINATOR = "\n"


def encode_motor_command(left_pwm: float, right_pwm: float,
                         base_speed: float = 60.0) -> bytes:
    """
    Encode a motor command into the UART wire format.

    Args:
        left_pwm:   Left motor PWM (-100 to +100)
        right_pwm:  Right motor PWM (-100 to +100)
        base_speed: Reference base speed (informational)

    Returns:
        Encoded bytes ready for serial.write()
    """
    left_pwm = max(-100.0, min(100.0, left_pwm))
    right_pwm = max(-100.0, min(100.0, right_pwm))
    msg = f"{PREFIX_CMD}{left_pwm:.1f},{right_pwm:.1f},{base_speed:.1f}{TERMINATOR}"
    return msg.encode("ascii")


def encode_heartbeat() -> bytes:
    """Encode a heartbeat message."""
    return f"{PREFIX_HBT}{TERMINATOR}".encode("ascii")


def encode_stop() -> bytes:
    """Encode an emergency stop command."""
    return f"{PREFIX_STP}{TERMINATOR}".encode("ascii")


def decode_motor_command(line: str) -> Optional[Tuple[float, float, float]]:
    """
    Parse a received motor command line.

    Args:
        line: Raw line string (with or without newline)

    Returns:
        (left_pwm, right_pwm, base_speed) or None if parse fails
    """
    line = line.strip()
    if not line.startswith(PREFIX_CMD):
        return None
    try:
        payload = line[len(PREFIX_CMD):]
        parts = payload.split(",")
        if len(parts) != 3:
            return None
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (ValueError, IndexError):
        return None


def is_heartbeat(line: str) -> bool:
    """Check if a received line is a heartbeat."""
    return line.strip() == PREFIX_HBT


def is_stop(line: str) -> bool:
    """Check if a received line is an emergency stop."""
    return line.strip() == PREFIX_STP
