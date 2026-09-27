"""
Yellow Tape HSV Segmenter
==========================
Extracts yellow tape/line from a camera frame using HSV thresholding
and morphological operations. Returns the largest valid contour.

Adapted from: segmentation_copy.py (original AI model codebase)
"""

import cv2
import numpy as np
from typing import Optional


class TapeSegmenter:
    """
    Yellow tape segmentation using HSV color space.

    Tunable Parameters:
        lower_yellow / upper_yellow: HSV range for yellow detection
        min_area: Minimum contour area to accept (rejects noise)
    """

    def __init__(self, lower_yellow=(20, 80, 80), upper_yellow=(35, 255, 255),
                 min_area: int = 500):
        self.lower_yellow = np.array(lower_yellow)
        self.upper_yellow = np.array(upper_yellow)
        self.min_area = min_area

    def segment(self, frame: np.ndarray) -> np.ndarray:
        """
        Create a binary mask of yellow pixels.

        Args:
            frame: OpenCV BGR image

        Returns:
            Binary mask (uint8, 0 or 255)
        """
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower_yellow, self.upper_yellow)

        # Morphological cleanup
        kernel_open = np.ones((1, 1), np.uint8)
        kernel_close = np.ones((2, 2), np.uint8)
        kernel_dilate = np.ones((1, 1), np.uint8)

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
        mask = cv2.dilate(mask, kernel_dilate, iterations=1)

        return mask

    def get_contour(self, mask: np.ndarray) -> Optional[np.ndarray]:
        """
        Find the largest valid yellow contour from the mask.

        Returns:
            Largest contour array, or None if no valid contour found.
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < self.min_area:
            return None

        return largest

    def process(self, frame: np.ndarray):
        """Convenience: segment + get_contour in one call."""
        mask = self.segment(frame)
        contour = self.get_contour(mask)
        return mask, contour
