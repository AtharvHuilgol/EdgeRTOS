"""
Camera-Based PID Line Follower — RPi RTOS Application
=======================================================
Real-time line-following pipeline running on Raspberry Pi under EdgeRTOS:

AI Pipeline:
    Camera → YOLO11n TFLite (tape classification: left/right/straight)
           → HSV Yellow Segmentation → Contour → Centroid
           → x_error (pixels) → PID → UART → ESP32 → L298N → Motors

RTOS Tasks:
    T_capture       (30ms, Priority 90, Hard RT)  : Grab camera frames via OpenCV
    T_ai_infer      (60–250ms, Adaptive)          : YOLO + HSV → x_error_pixels
    T_pid_control   (25ms, Priority 85, Hard RT)  : PID → (left_pwm, right_pwm)
    T_uart_send     (25ms, Priority 80, Hard RT)  : Send motor cmds to ESP32 via UART
    T_sched_monitor (40ms, Priority 75, Hard RT)  : Confidence-adaptive scheduling
    T_telemetry     (200ms, Priority 20)          : Log metrics

Calibration:
    14 pixels = 6 cm → 1 pixel ≈ 0.4286 cm

Model: YOLO11n (TFLite, 8-bit dynamic-range quantized, 512×512 input)
Classes: left, right, straight
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import EdgeRTOS as rtos
from EdgeRTOS import Priority, Queue, ConfidenceScheduler
from Line_Following_Robot.comms.uart_sender import UARTSender

# ═══════════════════════════════════════════════════════════════════════════════
# CALIBRATION CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
PIXELS_PER_6CM = 14.0
CM_PER_PIXEL = 6.0 / PIXELS_PER_6CM   # ≈ 0.4286 cm/pixel

# ═══════════════════════════════════════════════════════════════════════════════
# PID CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════
class PIDController:
    """
    Discrete PID controller for line-following steering.

    Input:  error in cm (positive = line is to the right, robot should turn right)
    Output: steering correction (applied as differential to left/right PWM)
    """

    def __init__(self, kp: float = 8.0, ki: float = 0.3, kd: float = 2.5,
                 output_limit: float = 40.0, integral_limit: float = 50.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limit = output_limit
        self.integral_limit = integral_limit

        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = time.monotonic()

    def compute(self, error_cm: float) -> float:
        """
        Compute PID output from the current error.

        Args:
            error_cm: Lateral offset error in centimeters.
                      Positive = line is to the right of center.

        Returns:
            Steering correction value (clamped to ±output_limit).
        """
        now = time.monotonic()
        dt = now - self._prev_time
        if dt <= 0.0:
            dt = 0.001  # prevent division by zero

        # Proportional
        p_term = self.kp * error_cm

        # Integral (with anti-windup clamping)
        self._integral += error_cm * dt
        self._integral = max(-self.integral_limit, min(self.integral_limit, self._integral))
        i_term = self.ki * self._integral

        # Derivative (on error, not on setpoint)
        derivative = (error_cm - self._prev_error) / dt
        d_term = self.kd * derivative

        # Update state
        self._prev_error = error_cm
        self._prev_time = now

        # Total output with saturation
        output = p_term + i_term + d_term
        return max(-self.output_limit, min(self.output_limit, output))

    def reset(self):
        """Reset PID internal state."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = time.monotonic()


# ═══════════════════════════════════════════════════════════════════════════════
# AI LINE DETECTION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════
# Full pipeline: YOLO11n TFLite → HSV Yellow Segmentation → Geometry → x_error
# Auto-detects model file at: Line_Following_Robot/ai/models/best_dynamic_range_quant.tflite
# Falls back to simulation if model/OpenCV not available (e.g., on Windows dev)
# ═══════════════════════════════════════════════════════════════════════════════

from Line_Following_Robot.ai.line_detection_pipeline import LineDetectionPipeline

# Initialize the AI pipeline (auto-detects model path)
ai_pipeline = LineDetectionPipeline()

# Latest AI info dict (shared for telemetry)
latest_ai_info = {
    "direction": "UNKNOWN",
    "yolo_class": "none",
    "yolo_conf": 0.0,
    "angle": None,
}


# ═══════════════════════════════════════════════════════════════════════════════
# CAMERA INTERFACE (OpenCV VideoCapture)
# ═══════════════════════════════════════════════════════════════════════════════
_camera = None
_HAS_CV2 = False
CAMERA_INDEX = 0  # /dev/video0 on RPi

# Try importing cv2. On RPi with sudo, prefer the apt-installed system package.
# Fix: 'sudo python3' uses system Python which may not see pip packages.
# Solution: install via apt → sudo apt install python3-opencv
# OR:       install globally → sudo pip3 install opencv-python-headless
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    print("[CAM] OpenCV not found. Install with ONE of:")
    print("      sudo apt install python3-opencv          ← recommended on RPi")
    print("      sudo pip3 install opencv-python-headless ← if using system python with sudo")
    print("[CAM] Running in simulation mode until OpenCV is available.")


def init_camera():
    """Initialize camera via OpenCV VideoCapture with V4L2 backend (RPi safe)."""
    global _camera
    if not _HAS_CV2:
        print("[CAM] OpenCV not available — running in simulation mode")
        return
    try:
        # Use explicit V4L2 backend on Linux.
        # cv2.VideoCapture(index) alone can segfault on RPi CSI cameras
        # because it tries GStreamer/other backends before V4L2.
        import platform
        if platform.system() == "Linux":
            _camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
        else:
            _camera = cv2.VideoCapture(CAMERA_INDEX)

        if not _camera.isOpened():
            print(f"[CAM] Could not open /dev/video{CAMERA_INDEX}.")
            print(f"      Check: ls /dev/video*")
            print(f"      For CSI PiCamera: sudo apt install python3-libcamera v4l-utils")
            print(f"                        then: sudo modprobe bcm2835-v4l2  (or reboot)")
            _camera = None
            return

        # Set capture resolution
        _camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        _camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        _camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency

        actual_w = int(_camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(_camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[CAM] OpenCV VideoCapture ready ({actual_w}×{actual_h} BGR, V4L2 backend)")

    except Exception as exc:
        print(f"[CAM] Camera init error: {exc} — running in simulation mode")
        _camera = None


def capture_frame():
    """Capture a camera frame (BGR numpy array) or return None for simulation."""
    if _camera is not None:
        ret, frame = _camera.read()
        if ret:
            return frame
    return None  # Simulation: AI pipeline fallback handles None


# ═══════════════════════════════════════════════════════════════════════════════
# RTOS TASK DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Inter-task communication queues
frame_queue = Queue(maxsize=2)
error_queue = Queue(maxsize=3)         # x_error in pixels
pid_output_queue = Queue(maxsize=3)    # (left_pwm, right_pwm)
infer_result_queue = Queue(maxsize=3)  # For confidence scheduler

# Shared state (protected by queue handoff pattern)
latest_error_cm = 0.0
latest_left_pwm = 0.0
latest_right_pwm = 0.0

# Components
pid = PIDController(kp=8.0, ki=0.3, kd=2.5, output_limit=40.0)
uart = UARTSender()  # Auto-detects RPi vs simulation

# Motor parameters
BASE_SPEED = 60.0   # Base forward PWM (0–100)
MIN_SPEED = 15.0    # Minimum PWM to keep motors turning
MAX_SPEED = 95.0    # Maximum PWM


def task_capture():
    """
    T_capture: Grabs camera frames at 30ms intervals.
    Hard real-time — must not miss frames during critical maneuvers.
    """
    frame = capture_frame()
    frame_queue.send_overwrite({
        "frame": frame,
        "timestamp_ms": rtos.get_time_ms(),
    })


def task_ai_infer():
    """
    T_ai_infer: Runs the YOLO + HSV + Geometry pipeline to get x_error.
    Period is adapted by ConfidenceScheduler (60ms–250ms).
    Faster inference on curves, relaxed on straight segments.
    """
    global latest_ai_info

    frame_data = frame_queue.receive(timeout_ms=10)
    if frame_data is None:
        return

    frame = frame_data.get("frame")

    # ── Run full AI pipeline: YOLO → HSV → Geometry → x_error ──
    x_error_pixels, info = ai_pipeline.get_x_error(frame)
    latest_ai_info = info

    # Convert pixels → cm using calibration (14 px = 6 cm)
    x_error_cm = x_error_pixels * CM_PER_PIXEL

    # Publish error for PID task
    error_queue.send_overwrite(x_error_cm)

    # ── Confidence for adaptive scheduling ──
    # Use YOLO confidence when available, else derive from pixel error
    yolo_conf = info.get("yolo_conf", 0.0)
    yolo_detected = info.get("yolo_detected", False)
    abs_error = abs(x_error_pixels)

    if yolo_detected and yolo_conf > 0.7 and abs_error < 5:
        # YOLO confident + centered → high confidence, relax inference
        confidence = 0.95
        pred_class = "CENTERED"
    elif yolo_detected and abs_error < 15:
        # YOLO detected + moderate offset
        confidence = 0.70
        pred_class = "OFFSET"
    elif abs_error >= 15 or not yolo_detected:
        # Large error or no YOLO detection → need frequent inference
        confidence = 0.35
        pred_class = "DEVIATION"
    else:
        confidence = 0.60
        pred_class = info.get("direction", "UNKNOWN")

    probs = [confidence, (1.0 - confidence) * 0.6, (1.0 - confidence) * 0.4]
    infer_result_queue.send({
        "probabilities": probs,
        "predicted_class": pred_class,
        "x_error_pixels": x_error_pixels,
        "x_error_cm": x_error_cm,
    }, timeout_ms=5)


def task_pid_control():
    """
    T_pid_control: Runs PID loop at 25ms (40 Hz).
    Converts lateral cm error into differential motor PWM commands.
    Hard real-time — critical for smooth steering.
    """
    global latest_error_cm, latest_left_pwm, latest_right_pwm

    # Get latest error from AI pipeline (non-blocking)
    new_error = error_queue.receive(timeout_ms=1)
    if new_error is not None:
        latest_error_cm = new_error

    # PID computation
    correction = pid.compute(latest_error_cm)

    # Differential drive: positive correction → turn right (more left, less right)
    left_pwm = BASE_SPEED + correction
    right_pwm = BASE_SPEED - correction

    # Clamp to valid PWM range while maintaining minimum drive
    def clamp_pwm(val):
        if abs(val) < MIN_SPEED:
            return math.copysign(MIN_SPEED, val) if val != 0 else 0.0
        return max(-MAX_SPEED, min(MAX_SPEED, val))

    latest_left_pwm = clamp_pwm(left_pwm)
    latest_right_pwm = clamp_pwm(right_pwm)

    # Publish for UART sender
    pid_output_queue.send_overwrite((latest_left_pwm, latest_right_pwm))


def task_uart_send():
    """
    T_uart_send: Sends motor commands to ESP32 at 25ms (40 Hz).
    Hard real-time — ESP32 expects regular updates.
    """
    cmd = pid_output_queue.receive(timeout_ms=1)
    if cmd is not None:
        left_pwm, right_pwm = cmd
        uart.send_motor_command(left_pwm, right_pwm, BASE_SPEED)


def task_sched_monitor():
    """
    T_sched_monitor: Adapts AI inference rate based on model confidence.
    Guards against conf_scheduler being uninitialised at startup.
    """
    # Guard: conf_scheduler is set inside run_camera_pid_robot().
    # If somehow this task fires before that completes, skip safely.
    if 'conf_scheduler' not in globals() or conf_scheduler is None:
        return

    result = infer_result_queue.receive(timeout_ms=2)
    if not result:
        return

    conf_scheduler.push_inference_result(
        result["probabilities"],
        predicted_class=result["predicted_class"]
    )
    conf_scheduler.evaluate_and_adapt(scheduler)


def task_telemetry():
    """T_telemetry: Logs system state for debugging and analysis."""
    yolo_cls = latest_ai_info.get("yolo_class", "?")
    yolo_conf = latest_ai_info.get("yolo_conf", 0.0)
    direction = latest_ai_info.get("direction", "?")
    print(
        f"[TEL] error={latest_error_cm:+6.2f}cm | "
        f"L={latest_left_pwm:+6.1f} R={latest_right_pwm:+6.1f} | "
        f"YOLO={yolo_cls}({yolo_conf:.2f}) dir={direction} | "
        f"AI={'REAL' if ai_pipeline.is_real else 'SIM'} "
        f"UART={'OK' if uart.is_connected else 'DISCONN'}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run_camera_pid_robot(duration_sec: float = 30.0,
                         log_path: str = "camera_pid_telemetry.csv"):
    """
    Launch the full camera-based PID line follower on RPi.

    Args:
        duration_sec: How long to run (seconds). Set to 0 for infinite.
        log_path:     CSV telemetry output path.
    """
    global scheduler, conf_scheduler

    print("=" * 65)
    print("  EdgeRTOS Camera-PID Line Follower")
    print("  YOLO11n + HSV → PID → UART → ESP32 → L298N → Motors")
    print(f"  Calibration: {PIXELS_PER_6CM:.0f} px = 6 cm "
          f"({CM_PER_PIXEL:.4f} cm/px)")
    print(f"  AI Pipeline: {'REAL (TFLite)' if ai_pipeline.is_real else 'SIMULATION'}")
    print("=" * 65)

    # Initialize hardware
    init_camera()
    uart.start_heartbeat()

    # Create RTOS scheduler
    scheduler = rtos.RTOSScheduler("CameraPID_LineFollower")

    # ── Hard Real-Time Tasks ──
    scheduler.create_task(
        "T_capture", task_capture,
        priority=Priority.REALTIME, period_ms=30.0,
        wcet_ms=5.0, is_hard_realtime=True
    )
    scheduler.create_task(
        "T_pid_control", task_pid_control,
        priority=Priority.HIGHEST, period_ms=25.0,
        wcet_ms=3.0, is_hard_realtime=True
    )
    scheduler.create_task(
        "T_uart_send", task_uart_send,
        priority=80, period_ms=25.0,
        wcet_ms=2.0, is_hard_realtime=True
    )
    scheduler.create_task(
        "T_sched_monitor", task_sched_monitor,
        priority=75, period_ms=40.0,
        wcet_ms=2.0, is_hard_realtime=True
    )

    # ── Adaptive AI Task ──
    scheduler.create_task(
        "T_ai_infer", task_ai_infer,
        priority=Priority.MEDIUM, period_ms=100.0,
        wcet_ms=25.0, is_hard_realtime=False
    )

    # ── Confidence-Adaptive Scheduler ──
    conf_scheduler = ConfidenceScheduler(
        target_task_name="T_ai_infer",
        min_period_ms=60.0,     # Fast: curves/deviations
        max_period_ms=250.0,    # Slow: straight/centered
        nominal_period_ms=100.0,
        min_priority=30,
        max_priority=70,
    )
    scheduler.attach_confidence_scheduler(conf_scheduler)

    # ── Background Tasks ──
    scheduler.create_task(
        "T_telemetry", task_telemetry,
        priority=Priority.LOW, period_ms=200.0,
        wcet_ms=2.0, is_hard_realtime=False
    )

    # ── Run ──
    print(f"\n[RTOS] Starting scheduler "
          f"({'infinite' if duration_sec <= 0 else f'{duration_sec:.0f}s'})...\n")
    scheduler.start()

    try:
        if duration_sec > 0:
            time.sleep(duration_sec)
        else:
            # Run forever until Ctrl+C
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[RTOS] Interrupted by user")
    finally:
        # Graceful shutdown
        uart.send_emergency_stop()
        scheduler.stop()
        uart.close()

        # Cleanup camera
        if _camera is not None:
            try:
                _camera.release()
            except Exception:
                pass

    # ── Report ──
    scheduler.print_task_table()
    if log_path:
        scheduler.telemetry.export_csv(log_path)
        print(f"[RTOS] Telemetry saved to {log_path}")

    return scheduler.telemetry.get_summary()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EdgeRTOS Camera-PID Line Follower (RPi)")
    parser.add_argument("-t", "--time", type=float, default=30.0,
                        help="Run duration in seconds (0 = infinite)")
    parser.add_argument("-o", "--output", type=str, default="camera_pid_telemetry.csv",
                        help="Telemetry CSV output path")
    parser.add_argument("--base-speed", type=float, default=60.0,
                        help="Base motor speed (0–100)")
    parser.add_argument("--kp", type=float, default=8.0, help="PID proportional gain")
    parser.add_argument("--ki", type=float, default=0.3, help="PID integral gain")
    parser.add_argument("--kd", type=float, default=2.5, help="PID derivative gain")
    args = parser.parse_args()

    # Apply CLI overrides
    BASE_SPEED = args.base_speed
    pid = PIDController(kp=args.kp, ki=args.ki, kd=args.kd)

    run_camera_pid_robot(duration_sec=args.time, log_path=args.output)
