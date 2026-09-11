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

# Import EdgeRTOS library (can use either `import edgertos as rtos` or `import rtos`)
import edgertos as rtos
from edgertos import Priority, Task, Queue, EventGroup, ConfidenceScheduler

# ==============================================================================
# HARDWARE CONFIGURATION & SIMULATION FLAGS
# ==============================================================================
# Set to True when running on a physical Raspberry Pi with GPIO & Camera wired
ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False

BUZZER_PIN = 18       # BCM GPIO pin for buzzer/relay
TRIGGER_PIN = 23      # HC-SR04 Trigger pin
ECHO_PIN = 24         # HC-SR04 Echo pin

# ==============================================================================
# RTOS SHARED RESOURCES (QUEUES & EVENT GROUPS)
# ==============================================================================
# Camera frame queue: bounded, overwrite mode so inference always gets freshest frame
frame_queue = rtos.Queue(maxsize=3)

# Inference result queue between T_infer and T_sched_monitor
inference_queue = rtos.Queue(maxsize=5)

# Event group for signaling asynchronous real-time events
system_events = rtos.EventGroup()
FLAG_ACTUATE_TRIGGER = "ACTUATE_TRIGGER"
FLAG_HAZARD_CONFIRMED = "HAZARD_CONFIRMED"


# ==============================================================================
# SCENARIO GENERATOR (Simulating Clear vs Occluded/Ambiguous Inputs)
# ==============================================================================
# In evaluation mode, this simulates distinct phases:
# - Seconds 0-8  : Clear, confident inputs (Person detected with 92-97% confidence)
# - Seconds 8-16 : Ambiguous/occluded inputs (Borderline 45-55% confidence, oscillating)
# - Seconds 16-24: Confident clear inputs again (Recovery)
_scenario_start_time = 0.0

def get_simulated_inference_output(cycle: int):
    elapsed = time.perf_counter() - _scenario_start_time
    phase = int(elapsed // 7) % 3

    if phase == 0 or phase == 2:
        # High confidence & stable (e.g. clearly visible obstacle/target)
        p_target = random.uniform(0.91, 0.98)
        p_other1 = (1.0 - p_target) * 0.7
        p_other2 = (1.0 - p_target) * 0.3
        predicted_class = "person"
        probs = [p_target, p_other1, p_other2]
        is_detection = True
    else:
        # Ambiguous / occluded / borderline inputs (uncertain & oscillating)
        p1 = random.uniform(0.38, 0.48)
        p2 = random.uniform(0.35, 0.45)
        p3 = 1.0 - (p1 + p2)
        classes = ["shadow", "debris", "person"]
        predicted_class = classes[cycle % len(classes)]  # rapid class flipping
        probs = [p1, p2, p3]
        is_detection = False

    return predicted_class, probs, is_detection


# ==============================================================================
# TASK IMPLEMENTATIONS (THE 5-TASK PIPELINE)
# ==============================================================================

def task_capture():
    """
    1. T_capture: Grabs latest camera frame / sensor readings.
    Fixed High Priority (70), Fixed Period (100 ms).
    Hard real-time safety constraint: must never be starved!
    """
    timestamp = rtos.get_time_ms()
    frame_data = {
        "frame_id": int(timestamp),
        "timestamp_ms": timestamp,
        "dummy_pixels": b"RAW_RGB_IMAGE_DATA"
    }
    # Send to inference queue using overwrite mode (freshest frame always kept)
    frame_queue.send_overwrite(frame_data)


def task_infer():
    """
    2. T_infer: Runs AI model inference (TFLite or simulated CNN).
    Outputs predicted class + softmax confidence vector.
    Dynamic Priority & Dynamic Period (adapted by T_sched_monitor).
    """
    frame = frame_queue.receive(timeout_ms=30)
    if frame is None:
        return

    # Simulate inference compute latency (e.g. 15-20 ms on RPi for quantized MobileNet)
    time.sleep(0.018)

    # In production on Pi:
    # interpreter.set_tensor(input_details[0]['index'], frame)
    # interpreter.invoke()
    # output = interpreter.get_tensor(output_details[0]['index'])
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
    # Pass result to scheduling monitor immediately
    inference_queue.send(result, timeout_ms=20)


def task_sched_monitor():
    """
    3 & 4. T_sched_monitor (Our Core Contribution):
    Runs immediately after each inference cycle.
    - Evaluates prediction confidence & predictive entropy across sliding window
    - Determines if model is Confident & Stable vs Uncertain & Oscillating
    - Formally verifies RM / EDF schedulability bounds
    - Adjusts T_infer period (50 - 300 ms) and priority
    - Triggers T_actuate if confirmed detection occurs
    """
    result = inference_queue.receive(timeout_ms=2)
    if not result:
        return

    probs = result["probabilities"]
    pred_class = result["predicted_class"]

    # 1. Feed inference result into confidence tracker
    conf_scheduler.push_inference_result(probs, predicted_class=pred_class)

    # 2. Evaluate metrics, check schedulability, and apply adaptation
    adaptation = conf_scheduler.evaluate_and_adapt(scheduler)

    # 3. If a high-confidence target detection is confirmed, trigger T_actuate
    if result["is_detection"] and max(probs) >= 0.90:
        system_events.set_flag(FLAG_ACTUATE_TRIGGER)

    # Print live real-time console status line
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
    """
    5. T_sensor_check: Reads secondary sensor (ultrasonic / IMU) for sensor fusion.
    Nominal Medium Priority (30), escalates to High Priority when T_infer is uncertain!
    """
    # Simulate secondary ultrasonic distance check (2 ms)
    time.sleep(0.002)


def task_actuate():
    """
    6. T_actuate: Event-driven actuator task.
    Blocks until FLAG_ACTUATE_TRIGGER is asserted by T_sched_monitor.
    Drives physical buzzer / LED / relay for safety response.
    """
    # Wait for detection flag with short poll timeout
    triggered = system_events.wait_flag(FLAG_ACTUATE_TRIGGER, clear_on_exit=True, timeout_ms=2)
    if triggered:
        # On Raspberry Pi:
        # GPIO.output(BUZZER_PIN, GPIO.HIGH); time.sleep(0.05); GPIO.output(BUZZER_PIN, GPIO.LOW)
        pass


# ==============================================================================
# MAIN SETUP & EXECUTION ROUTINE
# ==============================================================================

if __name__ == "__main__":
    print("=" * 95)
    print("  CONFIDENCE-AWARE REAL-TIME SCHEDULING FOR EDGE AI INFERENCE")
    print("  EdgeRTOS Scheduling Layer Demo | Raspberry Pi & Ubuntu 22.04 Compatible")
    print("=" * 95)
    print("Initializing RTOS Tasks, Queues, and Confidence Adaptation Policy...\n")

    scheduler = rtos.RTOSScheduler(name="EdgeRTOS_MiniProject")

    # 1. Register T_capture: Fixed high priority, 100ms period, Hard real-time constraint
    t_capture = scheduler.create_task(
        name="T_capture",
        func=task_capture,
        priority=Priority.HIGH,       # Prio 70
        period_ms=100.0,
        deadline_ms=100.0,
        wcet_ms=5.0,
        is_hard_realtime=True
    )

    # 2. Register T_infer: Variable runtime-adapted priority and period
    t_infer = scheduler.create_task(
        name="T_infer",
        func=task_infer,
        priority=Priority.MEDIUM,     # Nominal Prio 40
        period_ms=100.0,              # Nominal Period 100ms
        deadline_ms=100.0,
        wcet_ms=25.0,
        is_hard_realtime=False
    )

    # 3. Register T_sched_monitor: Runs immediately to evaluate inference output
    t_sched_monitor = scheduler.create_task(
        name="T_sched_monitor",
        func=task_sched_monitor,
        priority=Priority.HIGHEST,    # Prio 90
        period_ms=40.0,               # Fast monitor loop
        deadline_ms=40.0,
        wcet_ms=3.0,
        is_hard_realtime=True
    )

    # 4. Register T_sensor_check: Secondary ultrasonic confirmation task
    t_sensor = scheduler.create_task(
        name="T_sensor_check",
        func=task_sensor_check,
        priority=Priority.LOW,        # Baseline Prio 20 (escalates when uncertain)
        period_ms=150.0,
        deadline_ms=150.0,
        wcet_ms=3.0,
        is_hard_realtime=False
    )

    # 5. Register T_actuate: Event-driven actuator task
    t_actuate = scheduler.create_task(
        name="T_actuate",
        func=task_actuate,
        priority=Priority.HIGH,       # Prio 70
        period_ms=50.0,               # Checks event flags
        deadline_ms=50.0,
        wcet_ms=4.0,
        is_hard_realtime=True
    )

    # Configure the Novel Confidence-Aware Scheduling Engine
    conf_scheduler = ConfidenceScheduler(
        target_task_name="T_infer",
        secondary_task_name="T_sensor_check",
        window_size=5,
        min_period_ms=50.0,           # Fast 50ms sampling when uncertain/oscillating
        max_period_ms=250.0,          # Power-saving 250ms period when confident & stable
        nominal_period_ms=100.0,
        min_priority=Priority.LOW,
        max_priority=Priority.HIGH,
        high_conf_threshold=0.85,
        low_conf_threshold=0.60,
        max_entropy_threshold=0.80
    )
    scheduler.attach_confidence_scheduler(conf_scheduler)

    # Schedulability Verification on Initial Task Set
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

    # Start RTOS Preemptive Scheduler
    print("\nStarting EdgeRTOS Scheduler... Demonstrating dynamic adaptation over 21 seconds:")
    print("  Phase 1 (0-7s) : Confident & Stable -> Period stretches, CPU & power saved")
    print("  Phase 2 (7-14s): Ambiguous/Occluded -> Period shrinks, Priority & sampling boosted")
    print("  Phase 3 (14-21s): Recovery to Confident & Stable\n")

    scheduler.start()

    try:
        time.sleep(15.0)
    except KeyboardInterrupt:
        print("\nStopping demo early on user interrupt...")

    scheduler.stop()
    print("\n\n" + "=" * 95)
    print("Scheduler Stopped. Generating Final Task Statistics Table:")
    scheduler.print_task_table()

    # Export metrics to CSV for paper / project report
    csv_file = "edgertos_metrics_log.csv"
    scheduler.telemetry.export_csv(csv_file)
    print(f"[TELEMETRY EXPORT] Real-time metrics log successfully written to: {csv_file}")
    summary = scheduler.telemetry.get_summary()
    print(f"[EVALUATION SUMMARY]")
    print(f"  - Total Execution Cycles : {summary.get('total_cycles', 0)}")
    print(f"  - Deadline Hit Rate      : {summary.get('hit_rate_pct', 0.0):.2f}%")
    print(f"  - Average CPU Percent    : {summary.get('avg_cpu_percent', 0.0):.1f}%")
    print("=" * 95)
