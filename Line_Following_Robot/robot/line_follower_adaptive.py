"""
Confidence-Aware Adaptive Real-Time Line Follower
=================================================
Implements the closed-loop confidence-adaptive RTOS architecture:
- T_ir_read        (25 ms, Priority 90, Hard Real-Time) : Hardware safety backup
- T_motor_control  (25 ms, Priority 85, Hard Real-Time) : High-rate steering fusion
- T_capture        (60 ms, Priority 70, Hard Real-Time) : Camera frame grabber
- T_sched_monitor  (40 ms, Priority 80, Hard Real-Time) : Uncertainty analyzer & adaptation
- T_infer          (60-250 ms, Adaptive Prio 30-70)     : CNN lane classification
- T_logger         (100 ms, Priority 20)                : Power & deadline metrics
"""

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import EdgeRTOS as rtos
from EdgeRTOS import Priority, Queue, EventGroup, ConfidenceScheduler
from Line_Following_Robot.motor_control.sensor_interface import SensorInterface

sensors = SensorInterface()

# Inter-task communications
frame_queue = Queue(maxsize=3)
infer_result_queue = Queue(maxsize=3)
steering_queue = Queue(maxsize=5)

latest_ir_offset = 0.0
latest_ai_steering = 0.0
use_ir_fallback = False


def task_ir_read():
    """T_ir_read: Reads 5-channel IR array at fixed high priority (25ms)."""
    global latest_ir_offset
    bits, offset = sensors.read_ir_array()
    latest_ir_offset = offset


def task_motor_control():
    """T_motor_control: Fuses steering directives and drives motors (25ms)."""
    global use_ir_fallback, latest_ai_steering, latest_ir_offset

    ai_cmd = steering_queue.receive(timeout_ms=1)
    if ai_cmd is not None:
        latest_ai_steering = ai_cmd
        use_ir_fallback = False
    else:
        # Fallback to IR sensor array if AI inference is delayed or ambiguous
        use_ir_fallback = True

    steering = latest_ir_offset if use_ir_fallback else latest_ai_steering

    # Differential drive PWM
    base_speed = 60.0
    kp = 25.0
    correction = kp * steering
    left_pwm = base_speed + correction
    right_pwm = base_speed - correction
    sensors.set_motor_speeds(left_pwm, right_pwm)


def task_capture():
    """T_capture: Grabs camera frames at fixed period (60ms)."""
    frame_queue.send_overwrite({
        "timestamp_ms": rtos.get_time_ms(),
        "dummy_frame": True
    })


def task_infer():
    """T_infer: Runs neural network model. Adapted between 60ms and 250ms."""
    frame = frame_queue.receive(timeout_ms=5)
    if not frame:
        return

    # Simulate inference latency (16ms)
    time.sleep(0.016)

    # Track curvature simulation:
    t = time.perf_counter()
    track_difficulty = abs(math.sin(t * 0.7))  # 0.0 = straight, 1.0 = sharp turn/intersection

    if track_difficulty < 0.4:
        # Straight easy path: high confidence (95%), centered
        p_straight = random.uniform(0.92, 0.98)
        probs = [p_straight, (1.0 - p_straight) * 0.6, (1.0 - p_straight) * 0.4]
        steering_dir = 0.05
        pred_class = "STRAIGHT"
    else:
        # Ambiguous curve: lower confidence (45-55%), oscillating classes
        p1 = random.uniform(0.40, 0.52)
        p2 = random.uniform(0.35, 0.48)
        p3 = 1.0 - (p1 + p2)
        probs = [p1, p2, p3]
        steering_dir = math.copysign(1.2, math.sin(t * 1.5))
        pred_class = "SHARP_LEFT" if steering_dir < 0 else "SHARP_RIGHT"

    infer_result_queue.send({
        "probabilities": probs,
        "predicted_class": pred_class,
        "steering": steering_dir
    }, timeout_ms=5)

    steering_queue.send(steering_dir, timeout_ms=5)


def task_sched_monitor():
    """T_sched_monitor: Adapts T_infer priority/period based on model confidence."""
    result = infer_result_queue.receive(timeout_ms=2)
    if not result:
        return

    conf_scheduler.push_inference_result(
        result["probabilities"],
        predicted_class=result["predicted_class"]
    )
    conf_scheduler.evaluate_and_adapt(scheduler)


def run_adaptive_robot(duration_sec: float = 12.0, log_path: str = "benchmark_adaptive.csv"):
    global scheduler, conf_scheduler

    scheduler = rtos.RTOSScheduler("LineFollower_Adaptive")

    scheduler.create_task("T_ir_read", task_ir_read, priority=Priority.REALTIME, period_ms=25.0, wcet_ms=2.0, is_hard_realtime=True)
    scheduler.create_task("T_motor_control", task_motor_control, priority=Priority.HIGHEST, period_ms=25.0, wcet_ms=3.0, is_hard_realtime=True)
    scheduler.create_task("T_capture", task_capture, priority=Priority.HIGH, period_ms=60.0, wcet_ms=4.0, is_hard_realtime=True)
    scheduler.create_task("T_sched_monitor", task_sched_monitor, priority=80, period_ms=40.0, wcet_ms=2.0, is_hard_realtime=True)
    scheduler.create_task("T_infer", task_infer, priority=Priority.MEDIUM, period_ms=100.0, wcet_ms=20.0, is_hard_realtime=False)

    conf_scheduler = ConfidenceScheduler(
        target_task_name="T_infer",
        min_period_ms=60.0,
        max_period_ms=250.0,
        nominal_period_ms=100.0,
        min_priority=30,
        max_priority=70
    )
    scheduler.attach_confidence_scheduler(conf_scheduler)

    print(f"[ADAPTIVE] Running Confidence-Aware RTOS Line Follower for {duration_sec:.1f}s...")
    scheduler.start()
    time.sleep(duration_sec)
    scheduler.stop()

    scheduler.print_task_table()
    if log_path:
        scheduler.telemetry.export_csv(log_path)
        print(f"[ADAPTIVE] Telemetry logged to {log_path}")

    return scheduler.telemetry.get_summary()


if __name__ == "__main__":
    run_adaptive_robot(duration_sec=10.0)
