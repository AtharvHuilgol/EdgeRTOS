"""
Comparative Performance Analysis
================================
Parses benchmark telemetry from baseline and adaptive experiment runs.
Computes:
- CPU utilization savings (%)
- Deadline hit/miss rate comparisons
- Latency and period adaptation responsiveness
- Formatted comparative diagnostic summary table

Usage:
    python -m Line_Following_Robot.experiments.analysis
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from Line_Following_Robot.experiments.data_collection import load_metrics_csv

def analyze_benchmarks(base_csv: str, adapt_csv: str) -> None:
    print("\n" + "=" * 80)
    print("  EDGERTOS PERFORMANCE BENCHMARK ANALYSIS")
    print("  Confidence-Aware Adaptive RTOS vs. Fixed-Rate Baseline")
    print("=" * 80)

    base_rows = load_metrics_csv(base_csv)
    adapt_rows = load_metrics_csv(adapt_csv)

    if not base_rows:
        print(f"[!] Baseline metrics file not found or empty: {base_csv}")
        print("    Run: python -m Line_Following_Robot.experiments.run_baseline")
        return
    if not adapt_rows:
        print(f"[!] Adaptive metrics file not found or empty: {adapt_csv}")
        print("    Run: python -m Line_Following_Robot.experiments.run_adaptive")
        return

    # 1. CPU Utilization Comparison
    base_cpus = [float(r["cpu_percent"]) for r in base_rows if r["cpu_percent"]]
    adapt_cpus = [float(r["cpu_percent"]) for r in adapt_rows if r["cpu_percent"]]

    avg_base_cpu = sum(base_cpus) / len(base_cpus) if base_cpus else 0.0
    avg_adapt_cpu = sum(adapt_cpus) / len(adapt_cpus) if adapt_cpus else 0.0
    cpu_savings = max(0.0, (avg_base_cpu - avg_adapt_cpu) / avg_base_cpu * 100.0) if avg_base_cpu > 0 else 0.0

    # 2. Deadline Hit Rates
    base_hits = sum(1 for r in base_rows if r.get("deadline_met") == "1")
    adapt_hits = sum(1 for r in adapt_rows if r.get("deadline_met") == "1")
    base_hit_rate = (base_hits / len(base_rows) * 100.0) if base_rows else 100.0
    adapt_hit_rate = (adapt_hits / len(adapt_rows) * 100.0) if adapt_rows else 100.0

    # 3. T_infer Execution Counts and Periods
    base_infer = [r for r in base_rows if r.get("task_name") == "T_infer"]
    adapt_infer = [r for r in adapt_rows if r.get("task_name") == "T_infer"]

    adapt_periods = [float(r["period_ms"]) for r in adapt_infer if r.get("period_ms")]
    min_adapt_p = min(adapt_periods) if adapt_periods else 100.0
    max_adapt_p = max(adapt_periods) if adapt_periods else 100.0
    avg_adapt_p = (sum(adapt_periods) / len(adapt_periods)) if adapt_periods else 100.0

    print(f"\n{'Metric Description':<38} | {'Fixed Baseline':<16} | {'Adaptive EdgeRTOS':<18}")
    print("-" * 80)
    print(f"{'Total Recorded Cycles':<38} | {len(base_rows):<16} | {len(adapt_rows):<18}")
    print(f"{'Average System CPU %':<38} | {avg_base_cpu:<15.1f}% | {avg_adapt_cpu:<17.1f}%")
    print(f"{'Overall Deadline Hit Rate':<38} | {base_hit_rate:<15.2f}% | {adapt_hit_rate:<17.2f}%")
    print(f"{'T_infer Invocations':<38} | {len(base_infer):<16} | {len(adapt_infer):<18}")
    print(f"{'T_infer Sampling Period Range':<38} | {'100.0 ms (Fixed)':<16} | {f'{min_adapt_p:.0f}-{max_adapt_p:.0f} ms':<18}")
    print(f"{'Average Inference Period':<38} | {'100.0 ms':<16} | {f'{avg_adapt_p:.1f} ms':<18}")
    print("-" * 80)
    print(f"\n>>> SUMMARY OF RESULTS:")
    print(f"  [+] Dynamic Adaptation: Period stretched up to {max_adapt_p:.0f}ms on straight segments.")
    print(f"  [+] Responsiveness: Compressed down to {min_adapt_p:.0f}ms during ambiguous maneuvers.")
    print(f"  [+] Hard Schedulability: Safety-critical tasks maintained {adapt_hit_rate:.1f}% deadline compliance.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    benchmarks_dir = os.path.join(os.path.dirname(__file__), "../../benchmarks")
    base_file = os.path.join(benchmarks_dir, "benchmark_baseline.csv")
    adapt_file = os.path.join(benchmarks_dir, "benchmark_adaptive.csv")

    # If benchmarks haven't been run yet, run them automatically
    if not os.path.exists(base_file):
        print("Running initial baseline benchmark...")
        from Line_Following_Robot.applications.line_follower_app import run_baseline_robot
        run_baseline_robot(duration_sec=6.0, log_path=base_file)

    if not os.path.exists(adapt_file):
        print("Running initial adaptive benchmark...")
        from Line_Following_Robot.applications.line_follower_adaptive import run_adaptive_robot
        run_adaptive_robot(duration_sec=6.0, log_path=adapt_file)

    analyze_benchmarks(base_file, adapt_file)
