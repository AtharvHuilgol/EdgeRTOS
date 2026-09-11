"""
EdgeRTOS Task Management & Real-Time Synchronization Primitives
==============================================================
Defines:
- Task Control Block (Task, TaskState, Priority, TaskStats)
- Drift-free periodic execution clocks (delay_until / vTaskDelayUntil)
- RTOS IPC: Queue (xQueue), EventGroup (xEventGroup), Mutex, Semaphore
- POSIX real-time priority interface for Linux / Raspberry Pi
"""

from __future__ import annotations
import ctypes
import dataclasses
import enum
import os
import platform
import queue
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

SCHED_OTHER = 0
SCHED_FIFO = 1
SCHED_RR = 2

_libc = None
if IS_LINUX:
    try:
        _libc = ctypes.CDLL("libc.so.6", use_errno=True)
    except Exception:
        try:
            _libc = ctypes.CDLL("libpthread.so.0", use_errno=True)
        except Exception:
            _libc = None

class _SchedParam(ctypes.Structure):
    _fields_ = [("sched_priority", ctypes.c_int)]


def set_native_thread_priority(priority: int, policy: int = SCHED_FIFO) -> bool:
    """
    Attempt to configure POSIX real-time priority on Linux/Raspberry Pi.
    Gracefully falls back on Windows or if running without CAP_SYS_NICE/root.
    """
    if not IS_LINUX or _libc is None:
        return False

    try:
        rt_prio = max(1, min(99, priority))
        param = _SchedParam(rt_prio)
        pthread_self = _libc.pthread_self
        pthread_self.restype = ctypes.c_ulong
        tid = pthread_self()
        res = _libc.pthread_setschedparam(tid, ctypes.c_int(policy), ctypes.byref(param))
        return res == 0
    except Exception:
        return False


def get_time_s() -> float:
    """High-resolution monotonic time in seconds."""
    return time.perf_counter()

def get_time_ms() -> float:
    """High-resolution monotonic time in milliseconds."""
    return time.perf_counter() * 1000.0

def get_time_ns() -> int:
    """High-resolution monotonic time in nanoseconds."""
    return time.perf_counter_ns()

def delay_ms(duration_ms: float) -> None:
    """
    Relative delay in milliseconds, yielding CPU to scheduler.
    High-precision hybrid sleep (time.sleep + spin-wait for remaining microseconds).
    """
    if duration_ms <= 0:
        return
    
    target = get_time_ms() + duration_ms
    rem = duration_ms
    if rem > 2.0:
        time.sleep((rem - 1.5) / 1000.0)
    
    while get_time_ms() < target:
        pass


def delay_until(last_wake_time: List[float], period_ms: float) -> None:
    """
    FreeRTOS-style vTaskDelayUntil implementation.
    Prevents timing drift across periodic execution cycles.
    
    Args:
        last_wake_time: Single-element list [timestamp_ms] acting as mutable pointer
        period_ms: Period in milliseconds
    """
    target = last_wake_time[0] + period_ms
    now = get_time_ms()
    
    if target <= now:
        last_wake_time[0] = now
        return

    rem = target - now
    if rem > 2.0:
        time.sleep((rem - 1.5) / 1000.0)
    
    while get_time_ms() < target:
        pass
    
    last_wake_time[0] = target


class TaskState(enum.Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Priority:
    """
    Task priority constants.
    FreeRTOS & POSIX style: Higher numeric value = Higher execution priority.
    Range: 0 (Idle) to 99 (Max Real-Time).
    """
    IDLE = 0
    LOWEST = 5
    LOW = 20
    MEDIUM = 40
    HIGH = 70
    HIGHEST = 90
    REALTIME = 99

    @staticmethod
    def clamp(val: int) -> int:
        return max(0, min(99, int(val)))


@dataclasses.dataclass
class TaskStats:
    """Runtime statistics tracked per task."""
    run_count: int = 0
    deadline_hits: int = 0
    deadline_misses: int = 0
    total_exec_time_ms: float = 0.0
    last_exec_time_ms: float = 0.0
    min_exec_time_ms: float = float("inf")
    max_exec_time_ms: float = 0.0
    last_period_ms: float = 0.0
    jitter_ms: float = 0.0
    last_release_time: float = 0.0
    last_finish_time: float = 0.0

    @property
    def avg_exec_time_ms(self) -> float:
        return (self.total_exec_time_ms / self.run_count) if self.run_count > 0 else 0.0

    @property
    def deadline_hit_rate(self) -> float:
        total = self.deadline_hits + self.deadline_misses
        return (self.deadline_hits / total * 100.0) if total > 0 else 100.0


class Task:
    """
    Task Control Block (TCB) representing a Real-Time Task.
    """
    def __init__(
        self,
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
    ):
        self.name = name
        self.func = func
        self._priority = Priority.clamp(priority)
        self.base_priority = self._priority
        self.period_ms = period_ms
        self.deadline_ms = deadline_ms if deadline_ms is not None else period_ms
        self.wcet_ms = wcet_ms
        self.is_periodic = is_periodic
        self.is_hard_realtime = is_hard_realtime
        self.args = args or ()
        self.kwargs = kwargs or {}

        self.state = TaskState.READY
        self.stats = TaskStats()
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.resume_event.set()
        
        self.thread: Optional[threading.Thread] = None
        self._last_wake_time = [0.0]
        self._lock = threading.RLock()
        self._scheduler = None

    @property
    def priority(self) -> int:
        with self._lock:
            return self._priority

    def set_priority(self, new_prio: int) -> None:
        """Dynamically update task priority (like FreeRTOS vTaskPrioritySet)."""
        with self._lock:
            self._priority = Priority.clamp(new_prio)
            if self.thread and self.thread.is_alive():
                set_native_thread_priority(self._priority)

    def set_period(self, new_period_ms: float) -> None:
        """Dynamically adapt task period."""
        with self._lock:
            self.period_ms = max(1.0, float(new_period_ms))
            if self.deadline_ms is None or self.deadline_ms > self.period_ms:
                self.deadline_ms = self.period_ms

    def suspend(self) -> None:
        """Suspend task execution."""
        with self._lock:
            self.state = TaskState.SUSPENDED
            self.resume_event.clear()

    def resume(self) -> None:
        """Resume a suspended task."""
        with self._lock:
            self.state = TaskState.READY
            self.resume_event.set()

    def stop(self) -> None:
        """Request task termination."""
        self.stop_event.set()
        self.resume_event.set()


class Queue:
    """
    Thread-safe Bounded RTOS Message Queue.
    Equivalent to FreeRTOS xQueue.
    """
    def __init__(self, maxsize: int = 10):
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self.maxsize = maxsize
        self.overflow_count = 0
        self._lock = threading.Lock()

    def send(self, item: Any, timeout_ms: Optional[float] = None) -> bool:
        """
        Send item to queue.
        Returns True if successful, False on timeout/overflow.
        """
        timeout_s = (timeout_ms / 1000.0) if timeout_ms is not None else None
        try:
            self._queue.put(item, block=True, timeout=timeout_s)
            return True
        except queue.Full:
            with self._lock:
                self.overflow_count += 1
            return False

    def send_overwrite(self, item: Any) -> None:
        """
        Send item to queue, dropping oldest if full.
        Useful for camera frame buffers where latest data is paramount.
        """
        with self._lock:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.overflow_count += 1

    def receive(self, timeout_ms: Optional[float] = None) -> Optional[Any]:
        """
        Receive item from queue. Blocks until item available or timeout expires.
        Returns None on timeout.
        """
        timeout_s = (timeout_ms / 1000.0) if timeout_ms is not None else None
        try:
            return self._queue.get(block=True, timeout=timeout_s)
        except queue.Empty:
            return None

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def size(self) -> int:
        return self._queue.qsize()


class EventGroup:
    """
    RTOS Event Flag Group.
    Equivalent to FreeRTOS xEventGroup.
    Allows tasks to wait for combinations of synchronization event bits/flags.
    """
    def __init__(self):
        self._flags: Dict[str, bool] = {}
        self._cond = threading.Condition()

    def set_flag(self, flag: str) -> None:
        with self._cond:
            self._flags[flag] = True
            self._cond.notify_all()

    def clear_flag(self, flag: str) -> None:
        with self._cond:
            self._flags[flag] = False

    def is_set(self, flag: str) -> bool:
        with self._cond:
            return self._flags.get(flag, False)

    def wait_flag(self, flag: str, clear_on_exit: bool = True, timeout_ms: Optional[float] = None) -> bool:
        """
        Wait until a specific flag is set.
        Returns True if triggered, False on timeout.
        """
        timeout_s = (timeout_ms / 1000.0) if timeout_ms is not None else None
        deadline = (get_time_s() + timeout_s) if timeout_s is not None else None

        with self._cond:
            while not self._flags.get(flag, False):
                if deadline is not None:
                    remaining = deadline - get_time_s()
                    if remaining <= 0:
                        return False
                    self._cond.wait(timeout=remaining)
                else:
                    self._cond.wait()

            if clear_on_exit:
                self._flags[flag] = False
            return True


class Mutex:
    """RTOS Mutex with timeout support."""
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, timeout_ms: Optional[float] = None) -> bool:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms is not None else -1
        return self._lock.acquire(timeout=timeout_s)

    def release(self) -> None:
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class Semaphore:
    """Counting RTOS Semaphore."""
    def __init__(self, initial_value: int = 1):
        self._sem = threading.Semaphore(value=initial_value)

    def take(self, timeout_ms: Optional[float] = None) -> bool:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms is not None else None
        return self._sem.acquire(timeout=timeout_s)

    def give(self) -> None:
        self._sem.release()
