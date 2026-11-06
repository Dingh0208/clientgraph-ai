# -*- coding: utf-8 -*-
"""ClientGraph AI conflict detection."""
from .detector import DIMENSIONS, detect, normalize_value, observations_from_evidence

__all__ = ["detect", "normalize_value", "observations_from_evidence", "DIMENSIONS"]
