"""
Experiment: Run Confidence-Aware Adaptive Line Follower
======================================================
Executes the closed-loop confidence-adaptive line follower and exports metrics.
Usage:
    python -m Line_Following_Robot.robot.experiments.run_adaptive
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from Line_Following_Robot.robot.line_follower_adaptive import run_adaptive_robot

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "../../../benchmarks")
    os.makedirs(out_dir, exist_ok=True)
    csv_file = os.path.join(out_dir, "benchmark_adaptive.csv")

    print("[EXPERIMENT 2/2] Executing Confidence-Aware Adaptive Profile...")
    summary = run_adaptive_robot(duration_sec=10.0, log_path=csv_file)
    print(f"\n[DONE] Adaptive experiment complete. Results saved to {csv_file}")
