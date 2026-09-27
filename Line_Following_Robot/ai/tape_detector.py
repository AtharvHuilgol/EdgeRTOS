"""
TFLite YOLO Tape Detector
==========================
Runs YOLO11n (TFLite, 8-bit dynamic-range quantized) for tape/line
classification into: left, right, straight.

Adapted from: detector_copy.py (original AI model codebase)
Input:  512×512 RGB float32 image
Output: best detection dict with class, confidence, bounding box
"""

import os
import numpy as np
import cv2

# ── TFLite interpreter import (RPi → tflite-runtime, dev → tensorflow) ──
_Interpreter = None
try:
    from ai_edge_litert.interpreter import Interpreter as _Interpreter  # type: ignore
except ImportError:
    try:
        from tflite_runtime.interpreter import Interpreter as _Interpreter  # type: ignore
    except ImportError:
        try:
            from tensorflow.lite.python.interpreter import Interpreter as _Interpreter  # type: ignore
        except ImportError:
            _Interpreter = None


class TapeDetector:
    """
    YOLO11n TFLite tape detector.

    Classes: ["left", "right", "straight"]

    Args:
        model_path:  Path to .tflite model file
        confidence:  Minimum detection confidence threshold
        input_size:  Model input resolution (512×512)
    """

    CLASS_NAMES = ["left", "right", "straight"]

    def __init__(self, model_path: str, confidence: float = 0.50,
                 input_size: int = 512):
        self.model_path = model_path
        self.confidence_threshold = confidence
        self.input_size = input_size

        if _Interpreter is None:
            raise ImportError(
                "No TFLite runtime found. Install one of:\n"
                "  pip install ai-edge-litert    (RPi recommended)\n"
                "  pip install tflite-runtime\n"
                "  pip install tensorflow"
            )

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"TFLite model not found: {model_path}")

        self.interpreter = _Interpreter(model_path=self.model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        print(f"[YOLO] TFLite model loaded: {os.path.basename(model_path)}")
        print(f"[YOLO] Input: {self.input_details[0]['shape']} "
              f"{self.input_details[0]['dtype']}")
        print(f"[YOLO] Output: {self.output_details[0]['shape']} "
              f"{self.output_details[0]['dtype']}")

    def detect(self, frame: np.ndarray) -> dict:
        """
        Run YOLO detection on a BGR frame.

        Args:
            frame: OpenCV BGR image (any size)

        Returns:
            dict with keys: detected, confidence, class_id, class_name, box
        """
        original_h, original_w = frame.shape[:2]

        # Resize to model input
        image = cv2.resize(frame, (self.input_size, self.input_size))
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = image.astype(np.float32) / 255.0
        image = np.expand_dims(image, axis=0)

        # Run inference
        self.interpreter.set_tensor(self.input_details[0]["index"], image)
        self.interpreter.invoke()

        # Parse output
        output = self.interpreter.get_tensor(self.output_details[0]["index"])
        output = np.squeeze(output)

        if output.ndim != 2:
            return self._no_detection()

        # Transpose if needed: (7, N) → (N, 7)
        if output.shape[0] == 7:
            output = output.T
        elif output.shape[1] != 7:
            return self._no_detection()

        # Separate boxes [cx, cy, w, h] and class scores [left, right, straight]
        boxes = output[:, :4]
        class_scores = output[:, 4:7]

        class_ids = np.argmax(class_scores, axis=1)
        confidences = np.max(class_scores, axis=1)

        # Filter by confidence
        valid = np.where(confidences >= self.confidence_threshold)[0]
        if len(valid) == 0:
            return self._no_detection()

        # Best detection
        best_idx = valid[np.argmax(confidences[valid])]
        conf = float(confidences[best_idx])
        cls_id = int(class_ids[best_idx])

        # Scale bounding box to original frame size
        cx, cy, w, h = boxes[best_idx]
        sx = original_w / self.input_size
        sy = original_h / self.input_size

        x1 = int(max(0, (cx - w / 2) * sx))
        y1 = int(max(0, (cy - h / 2) * sy))
        x2 = int(min(original_w - 1, (cx + w / 2) * sx))
        y2 = int(min(original_h - 1, (cy + h / 2) * sy))

        return {
            "detected": True,
            "confidence": conf,
            "class_id": cls_id,
            "class_name": self.CLASS_NAMES[cls_id],
            "box": (x1, y1, x2, y2),
        }

    @staticmethod
    def _no_detection() -> dict:
        return {
            "detected": False,
            "confidence": 0.0,
            "class_id": -1,
            "class_name": "none",
            "box": None,
        }

    def tape_detected(self, result: dict) -> bool:
        return result["detected"]

    def confidence(self, result: dict) -> float:
        return result["confidence"]

    def class_name(self, result: dict) -> str:
        return result["class_name"]
