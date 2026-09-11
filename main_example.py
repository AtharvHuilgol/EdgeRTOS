"""
EdgeRTOS Main Demo Runner.
Executes the comprehensive 5-task Edge AI inference pipeline located in examples/edge_ai_pipeline.py.
"""

from examples.edge_ai_pipeline import run_pipeline

if __name__ == "__main__":
    run_pipeline(duration_sec=12.0)
