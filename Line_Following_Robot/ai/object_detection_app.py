"""
Auxiliary Object Detection Task
================================
Runs periodic vision-based obstacle checking using a TFLite model when
available on Raspberry Pi, with a transparent simulation fallback everywhere.

On Raspberry Pi 4/5 (Ubuntu 22.04+):
    pip install ai-edge-litert
    # Place your model at: Line_Following_Robot/ai/models/object_detector.tflite

On any other platform:
    Runs in software simulation — no hardware or model required.
"""

import os
import time
import random
from typing import List, Optional, Tuple

import EdgeRTOS as rtos
from EdgeRTOS import Priority, EventGroup

# ── Platform detection ───────────────────────────────────────────────────────
ON_RASPBERRY_PI = False
try:
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        with open("/sys/firmware/devicetree/base/model", "r") as _f:
            if "raspberry pi" in _f.read().lower():
                ON_RASPBERRY_PI = True
except Exception:
    ON_RASPBERRY_PI = False

# ── TFLite import (ai-edge-litert, replaces deprecated tflite-runtime) ───────
_tflite_interpreter = None
HAS_TFLITE = False

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "object_detector.tflite"
)

def _try_load_tflite_model() -> bool:
    """
    Attempt to load the TFLite object detection model.
    Returns True on success, False if library or model is unavailable.
    """
    global _tflite_interpreter, HAS_TFLITE

    # Try ai-edge-litert (modern Google package)
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore
        _Interpreter = Interpreter
    except ImportError:
        # Fallback: old tflite-runtime package name
        try:
            import tflite_runtime.interpreter as tflite  # type: ignore
            _Interpreter = tflite.Interpreter
        except ImportError:
            print("[AI] TFLite runtime not found. Running in simulation mode.")
            print("     To install on RPi4 Ubuntu: pip install ai-edge-litert")
            return False

    if not os.path.exists(MODEL_PATH):
        print(f"[AI] Model not found at: {MODEL_PATH}")
        print("     Place your object_detector.tflite model there to enable real inference.")
        return False

    try:
        _tflite_interpreter = _Interpreter(model_path=MODEL_PATH)
        _tflite_interpreter.allocate_tensors()
        HAS_TFLITE = True
        print(f"[AI] TFLite model loaded: {MODEL_PATH}")
        return True
    except Exception as exc:
        print(f"[AI] Failed to initialise TFLite interpreter: {exc}")
        return False


def run_tflite_inference(frame_data: Optional[bytes] = None) -> Tuple[str, List[float], bool]:
    """
    Run object detection inference.

    Returns:
        (predicted_class, softmax_probabilities, is_obstacle_detected)
    """
    if HAS_TFLITE and _tflite_interpreter is not None:
        try:
            input_details  = _tflite_interpreter.get_input_details()
            output_details = _tflite_interpreter.get_output_details()

            import numpy as np  # type: ignore
            # Build a dummy input tensor (replace with real frame preprocessing)
            input_shape = input_details[0]["shape"]
            input_data  = np.zeros(input_shape, dtype=input_details[0]["dtype"])
            _tflite_interpreter.set_tensor(input_details[0]["index"], input_data)
            _tflite_interpreter.invoke()

            output = _tflite_interpreter.get_tensor(output_details[0]["index"])
            probs  = output[0].tolist()
            max_idx    = probs.index(max(probs))
            pred_class = f"class_{max_idx}"
            detected   = max(probs) >= 0.75
            return pred_class, probs, detected

        except Exception as exc:
            print(f"[AI] Inference error: {exc} — falling back to simulation")

    # ── Simulation fallback ───────────────────────────────────────────────────
    t = time.perf_counter()
    if (int(t) % 6) < 3:
        # Obstacle-present phase
        p_obs = random.uniform(0.82, 0.96)
        probs = [p_obs, (1.0 - p_obs) * 0.6, (1.0 - p_obs) * 0.4]
        return "obstacle", probs, True
    else:
        # Clear path phase
        p_clear = random.uniform(0.03, 0.15)
        probs = [p_clear, random.uniform(0.05, 0.12), 1.0 - p_clear - probs[1]]
        return "clear", probs, False


# ── RTOS Task & Event Group ───────────────────────────────────────────────────
system_events = rtos.EventGroup()
FLAG_OBSTACLE_DETECTED = "OBSTACLE_DETECTED"


def check_obstacle() -> None:
    """T_object_detect: Periodic obstacle detection task (80 ms period)."""
    _, probs, is_detected = run_tflite_inference()

    if is_detected:
        system_events.set_flag(FLAG_OBSTACLE_DETECTED)


# ── Standalone entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    _try_load_tflite_model()

    scheduler = rtos.RTOSScheduler("ObjectDetection")
    scheduler.create_task(
        "T_object_detect",
        check_obstacle,
        priority=Priority.HIGH,
        period_ms=80.0,
        wcet_ms=5.0,
    )
    scheduler.start()
    time.sleep(2.0)
    scheduler.stop()
    scheduler.print_task_table()
