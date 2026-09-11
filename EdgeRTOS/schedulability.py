"""
EdgeRTOS Formal Schedulability Analysis Engine
=============================================
Implements:
- Rate-Monotonic (RM) Liu & Layland bound: U <= n(2^(1/n) - 1)
- Exact Response-Time Analysis (RTA) for Fixed-Priority Preemptive Systems
- Earliest Deadline First (EDF) utilization bound: U <= 1.0
- Online Admission Safety Guard for dynamic adaptation
"""

from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple

from EdgeRTOS.task import Task


class SchedulabilityAnalyzer:
    """
    Formal Real-Time Schedulability Analysis Engine.
    """
    @staticmethod
    def rm_utilization_bound(n: int) -> float:
        """Calculate Liu & Layland RM bound for n periodic tasks."""
        if n <= 0:
            return 1.0
        return n * (math.pow(2.0, 1.0 / n) - 1.0)

    @classmethod
    def calculate_utilization(cls, tasks: List[Task]) -> float:
        """Compute system utilization U = sum(Ci / Ti) for periodic tasks."""
        u = 0.0
        for t in tasks:
            if t.is_periodic and t.period_ms and t.period_ms > 0:
                c = t.wcet_ms or 1.0
                u += (c / t.period_ms)
        return u

    @classmethod
    def is_rm_schedulable_bound(cls, tasks: List[Task]) -> Tuple[bool, float, float]:
        """
        Check RM schedulability using the utilization bound test.
        Returns: (is_schedulable, current_utilization, rm_bound)
        """
        periodic_tasks = [t for t in tasks if t.is_periodic and t.period_ms]
        n = len(periodic_tasks)
        if n == 0:
            return (True, 0.0, 1.0)

        u = cls.calculate_utilization(periodic_tasks)
        bound = cls.rm_utilization_bound(n)
        return (u <= bound, u, bound)

    @classmethod
    def is_edf_schedulable(cls, tasks: List[Task]) -> Tuple[bool, float]:
        """
        Check EDF schedulability (U <= 1.0 for implicit deadlines).
        Returns: (is_schedulable, current_utilization)
        """
        periodic_tasks = [t for t in tasks if t.is_periodic and t.period_ms]
        u = cls.calculate_utilization(periodic_tasks)
        return (u <= 1.0, u)

    @classmethod
    def response_time_analysis(cls, tasks: List[Task]) -> Dict[str, Tuple[bool, float, float]]:
        """
        Exact Response-Time Analysis (RTA) for Fixed-Priority Preemptive Systems.
        R_i^(k+1) = C_i + sum_{j in hp(i)} ceil(R_i^(k) / T_j) * C_j
        
        Returns: Dict[task_name -> (is_schedulable, worst_case_response_time, deadline)]
        """
        periodic = [t for t in tasks if t.is_periodic and t.period_ms]
        sorted_tasks = sorted(periodic, key=lambda t: t.priority, reverse=True)
        results = {}

        for i, task in enumerate(sorted_tasks):
            ci = task.wcet_ms
            di = task.deadline_ms or task.period_ms or float("inf")
            higher_priority_tasks = sorted_tasks[:i]

            r = ci
            converged = False
            schedulable = False

            while True:
                interference = 0.0
                for hp in higher_priority_tasks:
                    hp_period = hp.period_ms or 1.0
                    hp_wcet = hp.wcet_ms or 0.0
                    interference += math.ceil(r / hp_period) * hp_wcet

                r_next = ci + interference

                if r_next > di:
                    schedulable = False
                    converged = True
                    r = r_next
                    break

                if abs(r_next - r) < 1e-4:
                    converged = True
                    schedulable = True
                    r = r_next
                    break

                r = r_next

            results[task.name] = (schedulable, r, di)

        return results

    @classmethod
    def check_dynamic_adaptation_safety(
        cls,
        tasks: List[Task],
        target_task_name: str,
        candidate_period_ms: float,
        candidate_priority: Optional[int] = None,
        max_allowable_utilization: float = 0.85
    ) -> bool:
        """
        Strict Admission Safety Guard.
        Ensures that adapting target_task's period/priority will NEVER starve
        hard real-time safety tasks (e.g. T_capture, T_actuate, T_motor_control).
        """
        hypothetical_tasks: List[Task] = []
        for t in tasks:
            if t.name == target_task_name:
                hypo = Task(
                    name=t.name,
                    func=t.func,
                    priority=candidate_priority if candidate_priority is not None else t.priority,
                    period_ms=candidate_period_ms,
                    deadline_ms=candidate_period_ms,
                    wcet_ms=t.wcet_ms,
                    is_periodic=t.is_periodic,
                    is_hard_realtime=t.is_hard_realtime
                )
                hypothetical_tasks.append(hypo)
            else:
                hypothetical_tasks.append(t)

        u = cls.calculate_utilization(hypothetical_tasks)
        if u > max_allowable_utilization:
            return False

        rta = cls.response_time_analysis(hypothetical_tasks)
        for t in hypothetical_tasks:
            if t.is_hard_realtime:
                schedulable, r, d = rta.get(t.name, (False, 999999.0, 0.0))
                if not schedulable or r > d:
                    return False

        return True
