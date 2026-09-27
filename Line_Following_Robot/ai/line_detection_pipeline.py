"""
Line Detection Pipeline — Unified AI Interface
=================================================
Combines the YOLO tape detector, HSV segmenter, and geometry analyzer
into a single callable that returns x_error in pixels from a camera frame.

This is the bridge between the AI model and the RTOS PID controller.

Pipeline:
    Frame → YOLO Detection (classification) → HSV Segmentation → Contour →
    Centroid → x_error (pixels) → returned to PID

Usage:
    from Line_Following_Robot.ai.line_detection_pipeline import LineDetectionPipeline

    pipeline = LineDetectionPipeline()
    x_error, info = pipeline.get_x_error(frame)
    # x_error: float (pixels), info: dict with full analysis details
"""

import os
import math
import time
from typing import Optional, Tuple, Dict

# Try importing OpenCV and numpy (required for real inference)
try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class LineDetectionPipeline:
    """
    Unified line detection pipeline for the camera-based PID follower.

    On RPi with model + OpenCV: runs real YOLO + HSV + geometry pipeline.
    On platforms without dependencies: transparent simulation fallback.

    Args:
        model_path: Path to TFLite model (default: auto-detected in ai/models/)
        confidence: YOLO confidence threshold
        input_size: YOLO input resolution
    """

    def __init__(self, model_path: Optional[str] = None,
                 confidence: float = 0.50, input_size: int = 512):

        self._real_pipeline = False
        self._detector = None
        self._segmenter = None
        self._geometry = None

        # Auto-detect model path
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(__file__), "models",
                "best_dynamic_range_quant.tflite"
            )

        if not _HAS_CV2:
            print("[PIPELINE] OpenCV not available — using simulation fallback")
            return

        # Try loading the full pipeline
        try:
            from Line_Following_Robot.ai.tape_detector import TapeDetector
            from Line_Following_Robot.ai.tape_segmenter import TapeSegmenter
            from Line_Following_Robot.ai.geometry_analyzer import GeometryAnalyzer

            self._detector = TapeDetector(
                model_path=model_path,
                confidence=confidence,
                input_size=input_size
            )
            self._segmenter = TapeSegmenter()
            self._geometry = GeometryAnalyzer(dead_band=25)
            self._real_pipeline = True

            print("[PIPELINE] Full AI pipeline initialized "
                  "(YOLO + HSV + Geometry)")

        except (ImportError, FileNotFoundError, RuntimeError) as exc:
            print(f"[PIPELINE] Could not load AI pipeline: {exc}")
            print("[PIPELINE] Falling back to simulation mode")
            self._real_pipeline = False

    @property
    def is_real(self) -> bool:
        """True if running the real AI model, False if simulating."""
        return self._real_pipeline

    def get_x_error(self, frame) -> Tuple[float, Dict]:
        """
        Process a camera frame and return x_error in pixels.

        Args:
            frame: OpenCV BGR image (numpy array), or None for simulation.

        Returns:
            (x_error_pixels, info_dict)

            x_error_pixels: float
                Positive = tape is RIGHT of frame center
                Negative = tape is LEFT of frame center
                0.0      = centered or no tape (simulation fallback)

            info_dict: dict with full analysis details:
                - error_x:     raw pixel error (int or None)
                - direction:   "LEFT" / "RIGHT" / "STRAIGHT" / "NO TAPE"
                - angle:       tape angle in degrees (float or None)
                - yolo_class:  YOLO classification ("left"/"right"/"straight"/"none")
                - yolo_conf:   YOLO confidence (0.0–1.0)
                - centroid:    (x, y) tuple or None
                - origin:      (frame_cx, frame_cy) tuple
        """
        if self._real_pipeline and frame is not None:
            return self._process_real(frame)
        return self._process_simulation()

    def _process_real(self, frame) -> Tuple[float, Dict]:
        """Run the full YOLO + HSV + Geometry pipeline."""
        # 1. YOLO detection (classification: left/right/straight)
        detection = self._detector.detect(frame)

        # 2. HSV segmentation → contour
        mask = self._segmenter.segment(frame)
        contour = self._segmenter.get_contour(mask)

        # 3. Geometry analysis → x_error
        info = self._geometry.analyze(frame, contour)

        # Extract x_error (use 0.0 if no tape detected)
        x_error = float(info["error_x"]) if info["error_x"] is not None else 0.0

        # Enrich info with YOLO results
        info["yolo_class"] = detection["class_name"]
        info["yolo_conf"] = detection["confidence"]
        info["yolo_detected"] = detection["detected"]

        return x_error, info

    def _process_simulation(self) -> Tuple[float, Dict]:
        """Simulation fallback — sinusoidal track with noise."""
        t = time.perf_counter()
        x_error = 25.0 * math.sin(t * 0.5) + 10.0 * math.sin(t * 1.3)
        noise = (hash(int(t * 1000)) % 100 - 50) * 0.1
        x_error += noise

        return x_error, {
            "error_x": int(x_error),
            "direction": "RIGHT" if x_error > 25 else ("LEFT" if x_error < -25 else "STRAIGHT"),
            "angle": None,
            "centroid": None,
            "origin": (160, 120),
            "yolo_class": "simulated",
            "yolo_conf": 0.0,
            "yolo_detected": False,
        }
