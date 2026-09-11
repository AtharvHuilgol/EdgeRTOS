"""
EdgeRTOS: Confidence-Aware Real-Time Scheduling Layer for Edge AI Inference
==========================================================================
Developed for: RTOS Mini Project & Conference Research
Authors: Atharv Huilgol, Vibhuti Sahu, Chinmayi Pethkar
Guidance: Prof. Archana Bhamare

A Python-based Real-Time Operating System scheduling package designed for edge devices
(Raspberry Pi 4/5 running Ubuntu 22.04) and cross-platform development (Windows/macOS/Linux).
"""

from EdgeRTOS.task import (
    Task,
    TaskState,
    Priority,
    TaskStats,
    Queue,
    EventGroup,
    Mutex,
    Semaphore,
    delay_ms,
    delay_until,
    get_time_s,
    get_time_ms,
    get_time_ns,
    set_native_thread_priority,
    SCHED_OTHER,
    SCHED_FIFO,
    SCHED_RR
)

from EdgeRTOS.schedulability import SchedulabilityAnalyzer

from EdgeRTOS.metrics import (
    ConfidenceMetric,
    ConfidenceRecord,
    TelemetryLogger,
    TelemetryEntry,
    get_current_cpu_percent
)

from EdgeRTOS.scheduler import (
    RTOSScheduler,
    ConfidenceScheduler
)

from typing import Any, Callable, Optional

# ==============================================================================
# GLOBAL SINGLETON & CONVENIENCE API (FreeRTOS Style)
# ==============================================================================

_global_rtos = RTOSScheduler()

def init(name: str = "EdgeRTOS") -> RTOSScheduler:
    """Initialize or reset the global RTOS instance."""
    global _global_rtos
    if _global_rtos.is_running:
        _global_rtos.stop()
    _global_rtos = RTOSScheduler(name=name)
    return _global_rtos

def get_rtos() -> RTOSScheduler:
    """Get active global RTOS scheduler instance."""
    return _global_rtos

def create_task(
    name: str,
    func: Callable[..., Any],
    priority: int = Priority.MEDIUM,
    period_ms: Optional[float] = None,
    deadline_ms: Optional[float] = None,
    wcet_ms: float = 10.0,
    is_periodic: bool = True,
    args: Optional[tuple] = None,
    kwargs: Optional[dict] = None,
    is_hard_realtime: bool = False
) -> Task:
    """Convenience wrapper for task creation."""
    return _global_rtos.create_task(
        name=name,
        func=func,
        priority=priority,
        period_ms=period_ms,
        deadline_ms=deadline_ms,
        wcet_ms=wcet_ms,
        is_periodic=is_periodic,
        args=args,
        kwargs=kwargs,
        is_hard_realtime=is_hard_realtime
    )

def start() -> None:
    """Start global RTOS scheduler."""
    _global_rtos.start()

def stop() -> None:
    """Stop global RTOS scheduler."""
    _global_rtos.stop()

def queue_create(maxsize: int = 10) -> Queue:
    """Create a thread-safe RTOS queue."""
    return Queue(maxsize=maxsize)

def event_group_create() -> EventGroup:
    """Create an RTOS event group."""
    return EventGroup()

def mutex_create() -> Mutex:
    """Create an RTOS mutex."""
    return Mutex()

def semaphore_create(initial_value: int = 1) -> Semaphore:
    """Create an RTOS semaphore."""
    return Semaphore(initial_value=initial_value)

# FreeRTOS API exact aliases
xTaskCreate = create_task
vTaskStartScheduler = start
vTaskDelay = delay_ms
vTaskDelayUntil = delay_until
xQueueCreate = queue_create
xEventGroupCreate = event_group_create

__all__ = [
    "Task",
    "TaskState",
    "Priority",
    "TaskStats",
    "Queue",
    "EventGroup",
    "Mutex",
    "Semaphore",
    "delay_ms",
    "delay_until",
    "get_time_s",
    "get_time_ms",
    "get_time_ns",
    "set_native_thread_priority",
    "SchedulabilityAnalyzer",
    "ConfidenceMetric",
    "ConfidenceRecord",
    "TelemetryLogger",
    "TelemetryEntry",
    "get_current_cpu_percent",
    "RTOSScheduler",
    "ConfidenceScheduler",
    "init",
    "get_rtos",
    "create_task",
    "start",
    "stop",
    "queue_create",
    "event_group_create",
    "mutex_create",
    "semaphore_create",
    "xTaskCreate",
    "vTaskStartScheduler",
    "vTaskDelay",
    "vTaskDelayUntil",
    "xQueueCreate",
    "xEventGroupCreate",
]
