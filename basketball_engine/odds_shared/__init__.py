"""Shared identity, continuity and HTTP reliability primitives for odds systems."""

from .canonical_entities import (
    EntityRegistry,
    canonical_event_id,
    canonicalize_event,
    canonicalize_team_pair,
    default_registry,
    same_fixture,
)
from .http_retry import RetryPolicy, request_with_retry

__all__ = [
    "EntityRegistry",
    "RetryPolicy",
    "canonical_event_id",
    "canonicalize_event",
    "canonicalize_team_pair",
    "default_registry",
    "request_with_retry",
    "same_fixture",
]
