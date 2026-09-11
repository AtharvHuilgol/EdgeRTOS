"""
EdgeRTOS Confidence Metrics & Telemetry Engine
=============================================
Defines:
- Shannon predictive entropy & statistical confidence trackers
- Sliding window confidence evaluation (mean, variance, flip rate)
- Cycle-by-cycle telemetry logger and CSV export
- System CPU utilization monitor
"""

from __future__ import annotations
import csv
import dataclasses
import math
import os
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from EdgeRTOS.task import get_time_ms

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_current_cpu_percent() -> float:
    """Return system-wide CPU utilization percentage."""
    if HAS_PSUTIL:
        try:
            return psutil.cpu_percent(interval=None)
        except Exception:
            pass
    return 0.0


@dataclasses.dataclass
class ConfidenceRecord:
    timestamp: float
    confidence: float
    entropy: float
    predicted_class: Any


class ConfidenceMetric:
    """
    Computes statistical and information-theoretic confidence metrics
    across a sliding window of inference outputs.
    """
    @staticmethod
    def compute_entropy(probabilities: List[float]) -> float:
        """Shannon predictive entropy H(p) = -sum(p_i * log2(p_i))."""
        entropy = 0.0
        for p in probabilities:
            if p > 1e-7:
                entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def compute_window_stats(records: List[ConfidenceRecord]) -> Dict[str, float]:
        """Compute mean confidence, variance, and class flip frequency."""
        if not records:
            return {"mean_conf": 1.0, "var_conf": 0.0, "flip_rate": 0.0, "mean_entropy": 0.0}

        n = len(records)
        confs = [r.confidence for r in records]
        entropies = [r.entropy for r in records]

        mean_conf = sum(confs) / n
        mean_entropy = sum(entropies) / n
        var_conf = sum((c - mean_conf) ** 2 for c in confs) / n if n > 1 else 0.0

        flips = 0
        for i in range(1, n):
            if records[i].predicted_class != records[i - 1].predicted_class:
                flips += 1
        flip_rate = (flips / (n - 1)) if n > 1 else 0.0

        return {
            "mean_conf": mean_conf,
            "var_conf": var_conf,
            "flip_rate": flip_rate,
            "mean_entropy": mean_entropy
        }


@dataclasses.dataclass
class TelemetryEntry:
    timestamp_ms: float
    task_name: str
    run_count: int
    exec_time_ms: float
    period_ms: float
    priority: int
    deadline_met: bool
    jitter_ms: float
    cpu_percent: float
    confidence: Optional[float] = None
    entropy: Optional[float] = None


class TelemetryLogger:
    """
    Records cycle-by-cycle metrics for comparative evaluation against
    fixed-priority baselines, exactly as required for paper & report figures.
    """
    def __init__(self, max_entries: int = 5000):
        self._entries: List[TelemetryEntry] = []
        self._lock = threading.Lock()
        self.max_entries = max_entries

    def log(
        self,
        task_name: str,
        run_count: int,
        exec_time_ms: float,
        period_ms: float,
        priority: int,
        deadline_met: bool,
        jitter_ms: float,
        cpu_percent: float,
        confidence: Optional[float] = None,
        entropy: Optional[float] = None
    ) -> None:
        entry = TelemetryEntry(
            timestamp_ms=get_time_ms(),
            task_name=task_name,
            run_count=run_count,
            exec_time_ms=exec_time_ms,
            period_ms=period_ms,
            priority=priority,
            deadline_met=deadline_met,
            jitter_ms=jitter_ms,
            cpu_percent=cpu_percent,
            confidence=confidence,
            entropy=entropy
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self.max_entries:
                self._entries.pop(0)

    def export_csv(self, filepath: str) -> None:
        """Export all logged metrics to a standard CSV file."""
        with self._lock:
            entries = list(self._entries)

        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_ms", "task_name", "run_count", "exec_time_ms",
                "period_ms", "priority", "deadline_met", "jitter_ms",
                "cpu_percent", "confidence", "entropy"
            ])
            for e in entries:
                writer.writerow([
                    f"{e.timestamp_ms:.2f}", e.task_name, e.run_count,
                    f"{e.exec_time_ms:.3f}", f"{e.period_ms:.2f}", e.priority,
                    1 if e.deadline_met else 0, f"{e.jitter_ms:.3f}",
                    f"{e.cpu_percent:.1f}",
                    f"{e.confidence:.4f}" if e.confidence is not None else "",
                    f"{e.entropy:.4f}" if e.entropy is not None else ""
                ])

    def get_summary(self) -> Dict[str, Any]:
        """Compute aggregate summary metrics."""
        with self._lock:
            if not self._entries:
                return {}
            total = len(self._entries)
            hits = sum(1 for e in self._entries if e.deadline_met)
            misses = total - hits
            avg_exec = sum(e.exec_time_ms for e in self._entries) / total
            avg_cpu = sum(e.cpu_percent for e in self._entries) / total

        return {
            "total_cycles": total,
            "deadline_hits": hits,
            "deadline_misses": misses,
            "hit_rate_pct": (hits / total * 100.0) if total > 0 else 100.0,
            "avg_exec_time_ms": avg_exec,
            "avg_cpu_percent": avg_cpu
        }
