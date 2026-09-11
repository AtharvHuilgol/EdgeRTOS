"""
Auxiliary Object Detection Task
===============================
Runs periodic vision-based or ultrasonic-based obstacle checking.
Asserts emergency stop or avoidance flag if an obstacle is confirmed.
"""

import time
import EdgeRTOS as rtos
from EdgeRTOS import Priority, EventGroup

system_events = rtos.EventGroup()
FLAG_OBSTACLE_DETECTED = "OBSTACLE_DETECTED"

def check_obstacle():
    """Runs periodic obstacle check every 80ms."""
    # Simulated check
    time.sleep(0.003)

if __name__ == "__main__":
    scheduler = rtos.RTOSScheduler("ObjectDetection")
    scheduler.create_task("T_object_detect", check_obstacle, priority=Priority.HIGH, period_ms=80.0, wcet_ms=5.0)
    scheduler.start()
    time.sleep(1.0)
    scheduler.stop()
    scheduler.print_task_table()
