"""
Experiment: Run Baseline Fixed-Priority Line Follower
=====================================================
Executes the fixed-period line follower and exports benchmark metrics.
Usage:
    python -m Line_Following_Robot.robot.experiments.run_baseline
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from Line_Following_Robot.robot.line_follower_app import run_baseline_robot

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "../../../benchmarks")
    os.makedirs(out_dir, exist_ok=True)
    csv_file = os.path.join(out_dir, "benchmark_baseline.csv")

    print("[EXPERIMENT 1/2] Establishing Baseline Profile...")
    summary = run_baseline_robot(duration_sec=10.0, log_path=csv_file)
    print(f"\n[DONE] Baseline experiment complete. Results saved to {csv_file}")
