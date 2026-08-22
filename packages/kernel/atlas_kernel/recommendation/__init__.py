"""Recommendation — the bridge from an evidence-backed opportunity to a job.

An opportunity says something could be better. A capability says Qevik can do a
particular thing. Neither can start work: an opportunity has no executor and a
capability has no justification. The recommendation is the join, and it is the
first object in the system a customer is meant to read and answer.
"""

from .models import (
    CustomerTask,
    QevikTask,
    Recommendation,
    RecommendationState,
    Task,
    TaskKind,
    Unsupported,
)
from .offers import CapabilityOffer, OFFERS, offer_for, offers_for_opportunity

__all__ = [
    "CapabilityOffer", "CustomerTask", "OFFERS", "QevikTask", "Recommendation",
    "RecommendationState", "Task", "TaskKind", "Unsupported", "offer_for",
    "offers_for_opportunity",
]
