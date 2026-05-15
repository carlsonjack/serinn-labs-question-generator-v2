"""Recursively convert values to JSON-serializable forms (Flask jsonify, API)."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


def json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if not isinstance(obj, (dict, list, tuple, set)):
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
    if isinstance(obj, int) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, pd.Timedelta):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if not isinstance(obj, (str, bytes)) and hasattr(obj, "item"):
        try:
            return json_safe(obj.item())
        except (ValueError, AttributeError, TypeError):
            pass
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if isinstance(obj, set):
        return [json_safe(x) for x in obj]
    return str(obj)
