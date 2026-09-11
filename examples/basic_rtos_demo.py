"""
Basic EdgeRTOS Demonstration
============================
Demonstrates basic real-time task creation, drift-free periodic execution,
and inter-task communication via bounded RTOS Queues.
"""

import os
import sys
import time

# Ensure repository root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import EdgeRTOS as rtos
from EdgeRTOS import Priority, Queue

# Initialize scheduler
scheduler = rtos.RTOSScheduler("Basic_Demo")

# Bounded message queue between Producer and Consumer
msg_queue = Queue(maxsize=5)

def producer_task():
    """Periodic producer running every 50ms (Priority 60)."""
    count = getattr(producer_task, "count", 0) + 1
    producer_task.count = count
    msg = f"Telemetry_Packet_#{count}"
    success = msg_queue.send(msg, timeout_ms=10)
    print(f"[PRODUCER | T=50ms] Sent: {msg} (Success: {success})")

def consumer_task():
    """Periodic consumer running every 100ms (Priority 40)."""
    msg = msg_queue.receive(timeout_ms=20)
    if msg:
        print(f"  [CONSUMER | T=100ms] Processed: {msg}")

if __name__ == "__main__":
    print("=" * 65)
    print("  EdgeRTOS: Basic Multi-Task Demonstration")
    print("=" * 65)

    # Register tasks
    scheduler.create_task("T_producer", producer_task, priority=Priority.HIGH, period_ms=50.0, wcet_ms=2.0)
    scheduler.create_task("T_consumer", consumer_task, priority=Priority.MEDIUM, period_ms=100.0, wcet_ms=4.0)

    # Start RTOS
    scheduler.start()
    time.sleep(1.0)
    scheduler.stop()

    # Print status table
    scheduler.print_task_table()
