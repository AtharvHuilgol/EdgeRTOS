"""
Experiment Data Collection Utility
==================================
Helper functions to aggregate, format, and serialize benchmark telemetry.
"""

import csv
import os
from typing import Any, Dict, List

def load_metrics_csv(filepath: str) -> List[Dict[str, Any]]:
    """Loads a CSV telemetry file into a list of row dictionaries."""
    if not os.path.exists(filepath):
        return []
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records
