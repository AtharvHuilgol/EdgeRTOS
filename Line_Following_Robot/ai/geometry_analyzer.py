"""
Geometry Analyzer — Line Position & Orientation
=================================================
Calculates tape centroid, x-axis error (pixels), direction,
and tape angle from a detected contour.

Adapted from: geometry_copy.py (original AI model codebase)

Sign Convention:
    error_x = centroid_x - frame_center_x
    Positive → tape is to the RIGHT of frame center
    Negative → tape is to the LEFT of frame center
"""

import cv2
import numpy as np
from typing import Dict, Optional, Tuple


class GeometryAnalyzer:
    """
    Analyzes tape geometry from a contour to produce x-error and angle.

    Args:
        dead_band: Pixel threshold for STRAIGHT classification (default 25)
    """

    def __init__(self, dead_band: int = 25):
        self.dead_band = dead_band

    def calculate_origin(self, frame: np.ndarray) -> Tuple[int, int]:
        """Calculate frame center point."""
        h, w = frame.shape[:2]
        return w // 2, h // 2

    def calculate_centroid(self, contour) -> Optional[Tuple[int, int]]:
        """Calculate contour centroid using image moments."""
        if contour is None:
            return None
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            return None
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        return cx, cy

    def calculate_x_error(self, centroid: Optional[Tuple[int, int]],
                          origin: Tuple[int, int]) -> Optional[int]:
        """
        Calculate x-axis error in pixels.

        Returns:
            Positive = tape is RIGHT of center
            Negative = tape is LEFT of center
            None     = no tape detected
        """
        if centroid is None:
            return None
        return centroid[0] - origin[0]

    def calculate_direction(self, error_x: Optional[int]) -> str:
        """Classify direction based on error with deadband."""
        if error_x is None:
            return "NO TAPE"
        if error_x > self.dead_band:
            return "RIGHT"
        elif error_x < -self.dead_band:
            return "LEFT"
        return "STRAIGHT"

    def calculate_angle(self, contour) -> Optional[float]:
        """Calculate tape orientation angle in degrees using cv2.fitLine."""
        if contour is None:
            return None
        [vx, vy, x0, y0] = cv2.fitLine(contour, cv2.DIST_L2, 0, 0.01, 0.01)
        angle = float(np.degrees(np.arctan2(float(vy), float(vx))))
        return angle

    def analyze(self, frame: np.ndarray, contour) -> Dict:
        """
        Complete geometry analysis.

        Returns:
            dict with keys: origin, centroid, error_x, direction, angle
        """
        origin = self.calculate_origin(frame)
        centroid = self.calculate_centroid(contour)
        error_x = self.calculate_x_error(centroid, origin)
        direction = self.calculate_direction(error_x)
        angle = self.calculate_angle(contour)

        return {
            "origin": origin,
            "centroid": centroid,
            "error_x": error_x,
            "direction": direction,
            "angle": angle,
        }
