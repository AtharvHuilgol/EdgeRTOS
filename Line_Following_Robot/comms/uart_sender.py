"""
RPi UART Sender — Serial Interface to ESP32
=============================================
Wraps pyserial for sending motor commands from the Raspberry Pi
to ESP32 over UART. Handles port detection, connection, and
automatic heartbeat generation.

RPi UART Setup:
    sudo raspi-config  → Interface Options → Serial Port
    - Login shell over serial: NO
    - Serial port hardware: YES
    sudo reboot

    pip install pyserial
"""

import os
import time
import threading
from typing import Optional

from Line_Following_Robot.comms.uart_protocol import (
    BAUD_RATE,
    encode_motor_command,
    encode_heartbeat,
    encode_stop,
)

# ── Platform detection ──────────────────────────────────────────────────────
ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        with open("/sys/firmware/devicetree/base/model", "r") as _f:
            if "raspberry pi" in _f.read().lower():
                ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False

# ── Serial import ───────────────────────────────────────────────────────────
_serial_mod = None
try:
    import serial as _serial_mod  # type: ignore
except ImportError:
    if ON_RASPBERRY_PI:
        print("[UART] pyserial not installed. Run: pip install pyserial")
    _serial_mod = None

# Default serial port on RPi 4/5 (UART0 = /dev/serial0 → /dev/ttyS0 or /dev/ttyAMA0)
DEFAULT_PORT = "/dev/serial0"


class UARTSender:
    """
    Serial UART sender for RPi → ESP32 motor commands.

    On non-RPi platforms, operates in simulation mode (prints to console).

    Args:
        port:      Serial port path (default: /dev/serial0)
        baud_rate: UART baud rate (default: 115200)
        heartbeat_interval_ms: Heartbeat period (default: 500ms)
        simulation: Force simulation mode
    """

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baud_rate: int = BAUD_RATE,
        heartbeat_interval_ms: int = 500,
        simulation: bool = not ON_RASPBERRY_PI,
    ):
        self.port = port
        self.baud_rate = baud_rate
        self.heartbeat_interval_s = heartbeat_interval_ms / 1000.0
        self.simulation = simulation or (_serial_mod is None)

        self._serial: Optional[object] = None
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_running = False
        self._lock = threading.Lock()
        self._last_send_time = 0.0

        if not self.simulation:
            self._open_serial()

    def _open_serial(self) -> None:
        """Open the serial port."""
        try:
            self._serial = _serial_mod.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=0.1,
                write_timeout=0.1,
            )
            print(f"[UART] Opened {self.port} @ {self.baud_rate} baud")
        except Exception as exc:
            print(f"[UART] Failed to open {self.port}: {exc} — falling back to simulation")
            self.simulation = True
            self._serial = None

    def start_heartbeat(self) -> None:
        """Start background heartbeat thread."""
        if self._hb_running:
            return
        self._hb_running = True
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="UART_Heartbeat"
        )
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        """Stop background heartbeat thread."""
        self._hb_running = False
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=2.0)
            self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        """Sends periodic heartbeat when no other data has been sent recently."""
        while self._hb_running:
            elapsed = time.monotonic() - self._last_send_time
            if elapsed >= self.heartbeat_interval_s:
                self._write_raw(encode_heartbeat())
            time.sleep(self.heartbeat_interval_s / 2)

    def send_motor_command(self, left_pwm: float, right_pwm: float,
                           base_speed: float = 60.0) -> None:
        """
        Send a motor command to ESP32.

        Args:
            left_pwm:  Left motor speed (-100 to +100)
            right_pwm: Right motor speed (-100 to +100)
            base_speed: Informational base speed
        """
        data = encode_motor_command(left_pwm, right_pwm, base_speed)
        self._write_raw(data)

    def send_emergency_stop(self) -> None:
        """Send emergency stop to ESP32."""
        self._write_raw(encode_stop())
        print("[UART] Emergency stop sent")

    def _write_raw(self, data: bytes) -> None:
        """Thread-safe raw write to serial port or simulation console."""
        with self._lock:
            self._last_send_time = time.monotonic()
            if self.simulation:
                # Simulation: print to console for debugging
                msg = data.decode("ascii").strip()
                # Suppress heartbeat spam in simulation
                if not msg.startswith("HBT"):
                    print(f"[UART SIM] → {msg}")
                return
            try:
                self._serial.write(data)
                self._serial.flush()
            except Exception as exc:
                print(f"[UART] Write error: {exc}")

    def close(self) -> None:
        """Shutdown: stop heartbeat, send stop, close port."""
        self.stop_heartbeat()
        if not self.simulation and self._serial is not None:
            try:
                self._write_raw(encode_stop())
                self._serial.close()
            except Exception:
                pass
        print("[UART] Connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if serial port is open and connected."""
        if self.simulation:
            return True
        return self._serial is not None and self._serial.is_open
