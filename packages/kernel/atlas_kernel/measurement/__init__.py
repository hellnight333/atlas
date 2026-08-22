"""Measurement — what changed after an intervention, and how sure we are.

The truth layer under every future report. Nothing here presents anything; it
establishes what may honestly be said, so that a roadmap, a portal or an ROI
summary built later cannot claim more than the evidence carries.
"""

from .attribution import Attribution, Claim, at_least, permits, phrasing, refuse
from .models import (
    METRICS,
    AIVisibilityObservation,
    BaselineState,
    Confidence,
    Direction,
    Measurement,
    Metric,
    MetricFamily,
    Observation,
    Window,
    window_around,
)
from .service import OutsideWindow, ProvenanceMissing, read, record, summarise, vet

__all__ = [
    "AIVisibilityObservation", "Attribution", "BaselineState", "Claim", "Confidence",
    "Direction", "METRICS", "Measurement", "Metric", "MetricFamily", "Observation",
    "OutsideWindow", "ProvenanceMissing", "Window", "at_least", "permits", "phrasing",
    "read", "record", "refuse", "summarise", "vet", "window_around",
]
