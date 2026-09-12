"""
EdgeRTOS Real-Time Scheduler & Confidence-Aware Adaptation Engine
================================================================
Defines:
- RTOSScheduler: Preemptive priority & periodic task dispatcher
- ConfidenceScheduler: Dynamic closed-loop priority & period adaptation
- Task lifecycle supervisor & live telemetry hooks
"""

from __future__ import annotations
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from EdgeRTOS.task import (
    Task, TaskState, Priority, delay_until, get_time_ms, set_native_thread_priority, SCHED_FIFO
)
from EdgeRTOS.schedulability import SchedulabilityAnalyzer
from EdgeRTOS.metrics import (
    ConfidenceMetric, ConfidenceRecord, TelemetryLogger, get_current_cpu_percent
)


class ConfidenceScheduler:
    """
    Confidence-Aware Scheduling Policy Engine.
    Evaluates real-time neural network uncertainty, computes adapted period
    and priority, enforces formal RM/EDF schedulability bounds, and updates T_infer.
    """
    def __init__(
        self,
        target_task_name: str = "T_infer",
        secondary_task_name: Optional[str] = "T_sensor_check",
        window_size: int = 5,
        min_period_ms: float = 50.0,
        max_period_ms: float = 300.0,
        nominal_period_ms: float = 100.0,
        min_priority: int = Priority.LOW,
        max_priority: int = Priority.HIGH,
        high_conf_threshold: float = 0.85,
        low_conf_threshold: float = 0.60,
        max_entropy_threshold: float = 0.80
    ):
        self.target_task_name = target_task_name
        self.secondary_task_name = secondary_task_name
        self.window_size = window_size
        self.min_period_ms = min_period_ms
        self.max_period_ms = max_period_ms
        self.nominal_period_ms = nominal_period_ms
        self.min_priority = min_priority
        self.max_priority = max_priority
        self.high_conf_threshold = high_conf_threshold
        self.low_conf_threshold = low_conf_threshold
        self.max_entropy_threshold = max_entropy_threshold

        self._records: List[ConfidenceRecord] = []
        self._lock = threading.Lock()
        self.escalate_sensor_flag = False

    def push_inference_result(
        self,
        probabilities: Union[List[float], Tuple[float, ...]],
        predicted_class: Any
    ) -> ConfidenceRecord:
        """
        Record a fresh inference result from T_infer.
        Returns the computed ConfidenceRecord.
        """
        probs = list(probabilities)
        max_p = max(probs) if probs else 1.0
        entropy = ConfidenceMetric.compute_entropy(probs)
        record = ConfidenceRecord(
            timestamp=get_time_ms(),
            confidence=max_p,
            entropy=entropy,
            predicted_class=predicted_class
        )

        with self._lock:
            self._records.append(record)
            if len(self._records) > self.window_size:
                self._records.pop(0)

        return record

    def evaluate_and_adapt(
        self,
        scheduler: RTOSScheduler
    ) -> Dict[str, Any]:
        """
        Executes Confidence-Aware Adaptation:
        1. Evaluates confidence & stability across recent window.
        2. Computes candidate period and priority.
        3. Enforces formal RM/EDF schedulability bounds.
        4. Applies updated parameters to target task in the scheduler.
        """
        with self._lock:
            records = list(self._records)

        stats = ConfidenceMetric.compute_window_stats(records)
        mean_conf = stats["mean_conf"]
        var_conf = stats["var_conf"]
        flip_rate = stats["flip_rate"]
        mean_entropy = stats["mean_entropy"]

        is_confident_and_stable = (
            mean_conf >= self.high_conf_threshold
            and var_conf < 0.02
            and flip_rate == 0.0
            and mean_entropy < self.max_entropy_threshold
        )

        is_uncertain_or_oscillating = (
            mean_conf < self.low_conf_threshold
            or mean_entropy >= self.max_entropy_threshold
            or flip_rate > 0.25
        )

        target_task = scheduler.get_task(self.target_task_name)
        if not target_task:
            return {"status": "target_task_not_found"}

        current_period = target_task.period_ms or self.nominal_period_ms
        current_priority = target_task.priority

        if is_confident_and_stable:
            candidate_period = min(self.max_period_ms, current_period + 25.0)
            candidate_prio = max(self.min_priority, current_priority - 2)
            self.escalate_sensor_flag = False
            regime = "CONFIDENT_STABLE"
        elif is_uncertain_or_oscillating:
            candidate_period = max(self.min_period_ms, current_period - 30.0)
            candidate_prio = min(self.max_priority, current_priority + 5)
            self.escalate_sensor_flag = True
            regime = "UNCERTAIN_OSCILLATING"
        else:
            if current_period > self.nominal_period_ms:
                candidate_period = max(self.nominal_period_ms, current_period - 10.0)
            else:
                candidate_period = min(self.nominal_period_ms, current_period + 10.0)
            candidate_prio = current_priority
            self.escalate_sensor_flag = False
            regime = "NOMINAL_TRANSITIONAL"

        all_tasks = scheduler.get_all_tasks()
        is_safe = SchedulabilityAnalyzer.check_dynamic_adaptation_safety(
            tasks=all_tasks,
            target_task_name=self.target_task_name,
            candidate_period_ms=candidate_period,
            candidate_priority=candidate_prio
        )

        applied_period = candidate_period
        applied_priority = candidate_prio

        if not is_safe:
            applied_period = max(current_period, candidate_period)
            applied_priority = current_priority
            sched_status = "CLAMPED_BY_SCHEDULABILITY_GUARD"
        else:
            sched_status = "SCHEDULABILITY_APPROVED"

        target_task.set_period(applied_period)
        target_task.set_priority(applied_priority)

        if self.secondary_task_name:
            secondary_task = scheduler.get_task(self.secondary_task_name)
            if secondary_task:
                if self.escalate_sensor_flag:
                    secondary_task.set_priority(Priority.HIGH)
                else:
                    secondary_task.set_priority(secondary_task.base_priority)

        return {
            "regime": regime,
            "mean_confidence": round(mean_conf, 4),
            "variance": round(var_conf, 5),
            "entropy": round(mean_entropy, 4),
            "flip_rate": round(flip_rate, 2),
            "applied_period_ms": applied_period,
            "applied_priority": applied_priority,
            "sched_status": sched_status,
            "sensor_escalated": self.escalate_sensor_flag
        }


class RTOSScheduler:
    """
    Main Preemptive Real-Time Scheduler Engine.
    Dispatches and supervises tasks, enforces periodic release intervals,
    monitors deadlines, and integrates confidence-aware adaptation.
    """
    def __init__(self, name: str = "EdgeRTOS_Scheduler"):
        self.name = name
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        self.is_running = False
        self.telemetry = TelemetryLogger()
        self.confidence_scheduler: Optional[ConfidenceScheduler] = None
        self._start_time = 0.0

    def create_task(
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
    ) -> Task:
        """Create and register a new Real-Time Task (FreeRTOS xTaskCreate)."""
        with self._lock:
            if name in self._tasks:
                raise ValueError(f"Task with name '{name}' already exists.")

            task = Task(
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
            task._scheduler = self
            self._tasks[name] = task
            return task

    def get_task(self, name: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(name)

    def get_all_tasks(self) -> List[Task]:
        with self._lock:
            return list(self._tasks.values())

    def attach_confidence_scheduler(self, conf_sched: ConfidenceScheduler) -> None:
        """Attach a confidence-aware adaptation monitor."""
        self.confidence_scheduler = conf_sched

    def _task_worker_loop(self, task: Task) -> None:
        """Dedicated execution wrapper per RTOS task thread."""
        set_native_thread_priority(task.priority, policy=SCHED_FIFO)

        task._last_wake_time = [get_time_ms()]
        expected_wake_time = task._last_wake_time[0]

        while not task.stop_event.is_set():
            task.resume_event.wait()
            if task.stop_event.is_set():
                break

            release_time = get_time_ms()
            task.stats.last_release_time = release_time
            task.state = TaskState.RUNNING

            if task.is_periodic and task.stats.run_count > 0:
                jitter = abs(release_time - expected_wake_time)
                task.stats.jitter_ms = jitter
            else:
                task.stats.jitter_ms = 0.0

            t0 = get_time_ms()
            try:
                task.func(*task.args, **task.kwargs)
            except Exception as e:
                print(f"[RTOS ERROR] Task '{task.name}' raised an exception: {e}", file=sys.stderr)
            t1 = get_time_ms()

            exec_time = t1 - t0
            task.stats.run_count += 1
            task.stats.last_exec_time_ms = exec_time
            task.stats.total_exec_time_ms += exec_time
            task.stats.min_exec_time_ms = min(task.stats.min_exec_time_ms, exec_time)
            task.stats.max_exec_time_ms = max(task.stats.max_exec_time_ms, exec_time)
            task.stats.last_finish_time = t1

            deadline_met = True
            if task.deadline_ms is not None and task.deadline_ms > 0:
                elapsed_from_release = t1 - release_time
                if elapsed_from_release > task.deadline_ms:
                    task.stats.deadline_misses += 1
                    deadline_met = False
                else:
                    task.stats.deadline_hits += 1
            else:
                task.stats.deadline_hits += 1

            task.state = TaskState.BLOCKED

            curr_cpu = get_current_cpu_percent()
            self.telemetry.log(
                task_name=task.name,
                run_count=task.stats.run_count,
                exec_time_ms=exec_time,
                period_ms=task.period_ms or 0.0,
                priority=task.priority,
                deadline_met=deadline_met,
                jitter_ms=task.stats.jitter_ms,
                cpu_percent=curr_cpu
            )

            if not task.is_periodic:
                break

            current_period = task.period_ms or 100.0
            task.stats.last_period_ms = current_period
            expected_wake_time = task._last_wake_time[0] + current_period
            delay_until(task._last_wake_time, current_period)

        task.state = TaskState.TERMINATED

    def start(self) -> None:
        """Start the RTOS scheduler (FreeRTOS vTaskStartScheduler)."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._start_time = get_time_ms()

            sorted_tasks = sorted(self._tasks.values(), key=lambda t: t.priority, reverse=True)
            for task in sorted_tasks:
                task.stop_event.clear()
                task.resume_event.set()
                task.state = TaskState.READY
                task.thread = threading.Thread(
                    target=self._task_worker_loop,
                    args=(task,),
                    name=f"RTOS_{task.name}",
                    daemon=True
                )
                task.thread.start()

    def stop(self) -> None:
        """Stop the RTOS scheduler and all tasks."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False

            for task in self._tasks.values():
                task.stop()

            for task in self._tasks.values():
                if task.thread and task.thread.is_alive():
                    task.thread.join(timeout=0.5)

    def print_task_table(self) -> None:
        """Print a live formatted ASCII status table of all tasks."""
        print("\n" + "=" * 92)
        print(f"  {self.name.upper()} - ACTIVE REAL-TIME TASK STATUS")
        print("=" * 92)
        header = f"{'Task Name':<16} | {'Prio':<5} | {'Period':<8} | {'State':<10} | {'Runs':<6} | {'Avg (ms)':<9} | {'Max (ms)':<9} | {'Hit Rate':<8}"
        print(header)
        print("-" * 92)
        with self._lock:
            for t in self._tasks.values():
                p_str = f"{t.period_ms:.1f}ms" if t.period_ms else "Event"
                row = (
                    f"{t.name:<16} | {t.priority:<5} | {p_str:<8} | {t.state.value:<10} | "
                    f"{t.stats.run_count:<6} | {t.stats.avg_exec_time_ms:<9.2f} | "
                    f"{t.stats.max_exec_time_ms:<9.2f} | {t.stats.deadline_hit_rate:<7.1f}%"
                )
                print(row)
        print("=" * 92 + "\n")
