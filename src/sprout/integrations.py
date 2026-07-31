"""Privacy-preserving contracts for first-party product integrations.

Household context is deliberately a selector, never a horticultural fact
source.  The only accepted fields are coarse species/light/task signals; names,
notes, photos, member identifiers, addresses, and coordinates have no place in
this contract and Pydantic rejects them as unknown fields.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HouseholdPlantContext(_Strict):
    species: str = Field(min_length=1, max_length=120)
    light_profile: Literal["low", "medium", "bright_indirect", "direct", "unknown"] = "unknown"

    @field_validator("species")
    @classmethod
    def safe_species(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("species contains control characters")
        cleaned = " ".join(value.split())
        return cleaned


class HouseholdTaskContext(_Strict):
    plant_species: str = Field(min_length=1, max_length=120)
    task_type: Literal["water", "fertilize", "prune", "repot", "custom"]
    due_in_days: int = Field(ge=-365, le=365)
    last_completed_days_ago: int | None = Field(default=None, ge=0, le=3650)

    @field_validator("plant_species")
    @classmethod
    def safe_species(cls, value: str) -> str:
        return HouseholdPlantContext.safe_species(value)


class FamilyGreenhouseRequest(_Strict):
    question: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "es"] = "en"
    plants: tuple[HouseholdPlantContext, ...] = Field(default_factory=tuple, max_length=100)
    tasks: tuple[HouseholdTaskContext, ...] = Field(default_factory=tuple, max_length=100)

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be empty")
        return cleaned


def canonical_payload(payload: Mapping[str, object]) -> bytes:
    """Return the stable UTF-8 representation signed by both services."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}\n{digest}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    now: int | None = None,
    max_skew_seconds: int = 300,
) -> bool:
    """Verify authenticity and reject replayable, stale requests."""
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - sent_at) > max_skew_seconds:
        return False
    expected = sign_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def selector_query(request: FamilyGreenhouseRequest) -> str:
    """Add coarse species selectors without allowing household prose into generation."""
    species = sorted(
        {plant.species.casefold(): plant.species for plant in request.plants}.values(),
        key=str.casefold,
    )
    if not species:
        return request.question
    return f"{request.question} Plant species context: {', '.join(species[:12])}."


def household_observations(request: FamilyGreenhouseRequest) -> list[dict[str, object]]:
    """Deterministic, non-horticultural facts labeled as household provenance."""
    overdue = sum(task.due_in_days < 0 for task in request.tasks)
    due_today = sum(task.due_in_days == 0 for task in request.tasks)
    return [
        {
            "kind": "collection",
            "value": {
                "plant_count": len(request.plants),
                "species_count": len({p.species.casefold() for p in request.plants}),
            },
            "provenance": "household",
        },
        {
            "kind": "tasks",
            "value": {"overdue_count": overdue, "due_today_count": due_today},
            "provenance": "household",
        },
    ]
