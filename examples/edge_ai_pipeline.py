"""
Confidence-Aware Real-Time Scheduling for Edge AI Inference
===========================================================
RTOS Mini Project & Paper Implementation
Team: Atharv Huilgol, Vibhuti Sahu, Chinmayi Pethkar
Guide: Prof. Archana Bhamare

Main execution script demonstrating the 5-task EdgeRTOS pipeline:
1. T_capture      : Grabs frames at fixed high-priority period (100 ms)
2. T_infer        : AI inference producing softmax confidence (adaptable 50-300 ms)
3. T_sensor_check : Secondary ultrasonic/IMU sensor check (escalated on uncertainty)
4. T_sched_monitor: Evaluates confidence/entropy, enforces RM/EDF bounds, adapts T_infer
5. T_actuate      : Event-driven buzzer/LED actuator triggered on confirmed detection

Designed for Raspberry Pi 4/5 (Ubuntu 22.04) with cross-platform simulation on Windows.
"""

import math
import os
import random
import sys
import time

# Ensure repository root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import EdgeRTOS as rtos
from EdgeRTOS import Priority, Task, Queue, EventGroup, ConfidenceScheduler

ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False

BUZZER_PIN = 18
TRIGGER_PIN = 23
ECHO_PIN = 24

frame_queue = rtos.Queue(maxsize=3)
inference_queue = rtos.Queue(maxsize=5)
system_events = rtos.EventGroup()
FLAG_ACTUATE_TRIGGER = "ACTUATE_TRIGGER"
FLAG_HAZARD_CONFIRMED = "HAZARD_CONFIRMED"

_scenario_start_time = 0.0

def get_simulated_inference_output(cycle: int):
    elapsed = time.perf_counter() - _scenario_start_time
    phase = int(elapsed // 5) % 3

    if phase == 0 or phase == 2:
        p_target = random.uniform(0.91, 0.98)
        p_other1 = (1.0 - p_target) * 0.7
        p_other2 = (1.0 - p_target) * 0.3
        predicted_class = "person"
        probs = [p_target, p_other1, p_other2]
        is_detection = True
    else:
        p1 = random.uniform(0.38, 0.48)
        p2 = random.uniform(0.35, 0.45)
        p3 = 1.0 - (p1 + p2)
        classes = ["shadow", "debris", "person"]
        predicted_class = classes[cycle % len(classes)]
        probs = [p1, p2, p3]
        is_detection = False

    return predicted_class, probs, is_detection


def task_capture():
    timestamp = rtos.get_time_ms()
    frame_data = {
        "frame_id": int(timestamp),
        "timestamp_ms": timestamp,
        "dummy_pixels": b"RAW_RGB_IMAGE_DATA"
    }
    frame_queue.send_overwrite(frame_data)


def task_infer():
    frame = frame_queue.receive(timeout_ms=5)
    if frame is None:
        return

    time.sleep(0.018)

    infer_count = getattr(task_infer, "count", 0) + 1
    task_infer.count = infer_count

    predicted_class, probs, is_detection = get_simulated_inference_output(infer_count)

    result = {
        "cycle": infer_count,
        "predicted_class": predicted_class,
        "probabilities": probs,
        "is_detection": is_detection,
        "inference_time_ms": 18.0
    }
    inference_queue.send(result, timeout_ms=5)


def task_sched_monitor():
    result = inference_queue.receive(timeout_ms=2)
    if not result:
        return

    probs = result["probabilities"]
    pred_class = result["predicted_class"]

    conf_scheduler.push_inference_result(probs, predicted_class=pred_class)
    adaptation = conf_scheduler.evaluate_and_adapt(scheduler)

    if result["is_detection"] and max(probs) >= 0.90:
        system_events.set_flag(FLAG_ACTUATE_TRIGGER)

    regime = adaptation.get("regime", "UNKNOWN")
    period = adaptation.get("applied_period_ms", 0.0)
    prio = adaptation.get("applied_priority", 0)
    conf = adaptation.get("mean_confidence", 0.0)
    ent = adaptation.get("entropy", 0.0)
    guard = adaptation.get("sched_status", "")

    regime_color = "\033[92m" if regime == "CONFIDENT_STABLE" else "\033[91m"
    reset_color = "\033[0m"

    sys.stdout.write(
        f"\r[MONITOR] {regime_color}{regime:<21}{reset_color} | "
        f"Conf: {conf*100:5.1f}% | Entropy: {ent:.3f} | "
        f"T_infer Period: {period:5.1f}ms | Prio: {prio:2d} | Guard: {guard}"
    )
    sys.stdout.flush()


def task_sensor_check():
    time.sleep(0.002)


def task_actuate():
    triggered = system_events.wait_flag(FLAG_ACTUATE_TRIGGER, clear_on_exit=True, timeout_ms=2)
    if triggered:
        pass


def run_pipeline(duration_sec: float = 15.0, csv_output: str = "edgertos_metrics_log.csv"):
    global scheduler, conf_scheduler, _scenario_start_time

    print("=" * 95)
    print("  CONFIDENCE-AWARE REAL-TIME SCHEDULING FOR EDGE AI INFERENCE")
    print("  EdgeRTOS Scheduling Layer Demo | Raspberry Pi & Ubuntu 22.04 Compatible")
    print("=" * 95)
    print("Initializing RTOS Tasks, Queues, and Confidence Adaptation Policy...\n")

    scheduler = rtos.RTOSScheduler(name="EdgeRTOS_Pipeline")

    t_capture = scheduler.create_task(
        name="T_capture",
        func=task_capture,
        priority=Priority.HIGH,
        period_ms=100.0,
        deadline_ms=100.0,
        wcet_ms=5.0,
        is_hard_realtime=True
    )

    t_infer = scheduler.create_task(
        name="T_infer",
        func=task_infer,
        priority=Priority.MEDIUM,
        period_ms=100.0,
        deadline_ms=100.0,
        wcet_ms=25.0,
        is_hard_realtime=False
    )

    t_sched_monitor = scheduler.create_task(
        name="T_sched_monitor",
        func=task_sched_monitor,
        priority=Priority.HIGHEST,
        period_ms=40.0,
        deadline_ms=40.0,
        wcet_ms=3.0,
        is_hard_realtime=True
    )

    t_sensor = scheduler.create_task(
        name="T_sensor_check",
        func=task_sensor_check,
        priority=Priority.LOW,
        period_ms=150.0,
        deadline_ms=150.0,
        wcet_ms=3.0,
        is_hard_realtime=False
    )

    t_actuate = scheduler.create_task(
        name="T_actuate",
        func=task_actuate,
        priority=Priority.HIGH,
        period_ms=50.0,
        deadline_ms=50.0,
        wcet_ms=4.0,
        is_hard_realtime=True
    )

    conf_scheduler = ConfidenceScheduler(
        target_task_name="T_infer",
        secondary_task_name="T_sensor_check",
        window_size=5,
        min_period_ms=50.0,
        max_period_ms=250.0,
        nominal_period_ms=100.0,
        min_priority=Priority.LOW,
        max_priority=Priority.HIGH,
        high_conf_threshold=0.85,
        low_conf_threshold=0.60,
        max_entropy_threshold=0.80
    )
    scheduler.attach_confidence_scheduler(conf_scheduler)

    tasks = scheduler.get_all_tasks()
    is_rm, u, rm_bound = rtos.SchedulabilityAnalyzer.is_rm_schedulable_bound(tasks)
    is_edf, edf_u = rtos.SchedulabilityAnalyzer.is_edf_schedulable(tasks)
    rta_results = rtos.SchedulabilityAnalyzer.response_time_analysis(tasks)

    print(f"[FORMAL SCHEDULABILITY CHECK]")
    print(f"  - System Utilization (U)  : {u:.3f}")
    print(f"  - Liu & Layland RM Bound  : {rm_bound:.3f} -> {'PASS (Guaranteed Schedulable)' if is_rm else 'CHECK RTA'}")
    print(f"  - EDF Feasibility (U<=1.0): {edf_u:.3f} -> {'PASS' if is_edf else 'FAIL'}")
    print(f"  - Exact Response Time Analysis (RTA):")
    for tname, (schedulable, r, d) in rta_results.items():
        print(f"    * {tname:<16}: Worst-Case R={r:.1f}ms, Deadline D={d:.1f}ms -> {'OK' if schedulable else 'MISSED'}")
    print("-" * 95)

    _scenario_start_time = time.perf_counter()

    print(f"\nStarting EdgeRTOS Scheduler... Demonstrating dynamic adaptation over {duration_sec:.1f}s:")
    print("  Phase 1: Confident & Stable  -> Period stretches, CPU & power saved")
    print("  Phase 2: Ambiguous/Occluded  -> Period shrinks, Priority & sampling boosted")
    print("  Phase 3: Recovery to Baseline\n")

    scheduler.start()

    try:
        time.sleep(duration_sec)
    except KeyboardInterrupt:
        print("\nStopping demo early on user interrupt...")

    scheduler.stop()
    print("\n\n" + "=" * 95)
    print("Scheduler Stopped. Generating Final Task Statistics Table:")
    scheduler.print_task_table()

    if csv_output:
        scheduler.telemetry.export_csv(csv_output)
        print(f"[TELEMETRY EXPORT] Metrics log written to: {csv_output}")

    summary = scheduler.telemetry.get_summary()
    print(f"[EVALUATION SUMMARY]")
    print(f"  - Total Execution Cycles : {summary.get('total_cycles', 0)}")
    print(f"  - Deadline Hit Rate      : {summary.get('hit_rate_pct', 0.0):.2f}%")
    print(f"  - Average CPU Percent    : {summary.get('avg_cpu_percent', 0.0):.1f}%")
    print("=" * 95)


if __name__ == "__main__":
    run_pipeline(duration_sec=12.0)
