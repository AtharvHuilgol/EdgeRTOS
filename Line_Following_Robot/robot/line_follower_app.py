"""
Fixed-Rate Baseline Real-Time Line Follower
===========================================
Runs traditional fixed-priority, fixed-period real-time task loop without adaptation.
Used as control baseline to measure CPU and power savings of EdgeRTOS.
"""

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import EdgeRTOS as rtos
from EdgeRTOS import Priority, Queue
from Line_Following_Robot.motor_control.sensor_interface import SensorInterface

sensors = SensorInterface()
frame_queue = Queue(maxsize=3)
steering_queue = Queue(maxsize=5)

latest_ir_offset = 0.0
latest_ai_steering = 0.0


def task_ir_read():
    global latest_ir_offset
    bits, offset = sensors.read_ir_array()
    latest_ir_offset = offset


def task_motor_control():
    global latest_ai_steering, latest_ir_offset
    ai_cmd = steering_queue.receive(timeout_ms=1)
    if ai_cmd is not None:
        latest_ai_steering = ai_cmd

    steering = latest_ai_steering
    base_speed = 60.0
    kp = 25.0
    correction = kp * steering
    sensors.set_motor_speeds(base_speed + correction, base_speed - correction)


def task_capture():
    frame_queue.send_overwrite({"timestamp_ms": rtos.get_time_ms()})


def task_infer_fixed():
    """Fixed-rate inference: runs strictly at 100ms regardless of track difficulty."""
    frame = frame_queue.receive(timeout_ms=5)
    if not frame:
        return
    time.sleep(0.016)
    steering_queue.send(random.uniform(-0.5, 0.5), timeout_ms=5)


def run_baseline_robot(duration_sec: float = 12.0, log_path: str = "benchmark_baseline.csv"):
    scheduler = rtos.RTOSScheduler("LineFollower_Baseline")

    scheduler.create_task("T_ir_read", task_ir_read, priority=Priority.REALTIME, period_ms=25.0, wcet_ms=2.0, is_hard_realtime=True)
    scheduler.create_task("T_motor_control", task_motor_control, priority=Priority.HIGHEST, period_ms=25.0, wcet_ms=3.0, is_hard_realtime=True)
    scheduler.create_task("T_capture", task_capture, priority=Priority.HIGH, period_ms=60.0, wcet_ms=4.0, is_hard_realtime=True)
    # Fixed priority and fixed period (100ms)
    scheduler.create_task("T_infer", task_infer_fixed, priority=Priority.MEDIUM, period_ms=100.0, wcet_ms=20.0, is_hard_realtime=False)

    print(f"[BASELINE] Running Fixed-Priority Baseline Line Follower for {duration_sec:.1f}s...")
    scheduler.start()
    time.sleep(duration_sec)
    scheduler.stop()

    scheduler.print_task_table()
    if log_path:
        scheduler.telemetry.export_csv(log_path)
        print(f"[BASELINE] Telemetry logged to {log_path}")

    return scheduler.telemetry.get_summary()


if __name__ == "__main__":
    run_baseline_robot(duration_sec=10.0)
