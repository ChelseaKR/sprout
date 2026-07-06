"""Local-first watering/fertilizing reminders — offline, privacy-preserving.

Reminders are user data, so they live in one JSON file on the user's own machine (no
database, no network, nothing leaves the device) and the feature is opt-in: the file is
created lazily the first time a reminder is added. A reminder ties a care cadence to a
plant (a corpus species slug or a free label) and, optionally, to the citation that
motivated it — but the cadence is the user's own setting, never presented as a cited
horticultural fact, consistent with the grounding contract.

Everything is deterministic and clock-injectable so tests are hermetic and reminder ids
are reproducible. The store is intentionally tiny: load, add, list, due, complete (which
reschedules ``next_due``), and remove.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .determinism import sha256_of_obj, short

ReminderKind = Literal["water", "fertilize", "repot", "mist", "rotate"]

_FORMAT_VERSION = 1


class Reminder(BaseModel):
    """One care reminder. Immutable; ``complete`` returns a rescheduled copy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reminder_id: str
    plant: str  # corpus species slug or a free-text label (stays local)
    kind: ReminderKind
    interval_days: int = Field(ge=1, le=3650)
    created_at: str  # ISO-8601 date
    next_due: str  # ISO-8601 date
    last_done: str | None = None
    language: str = "en"
    note: str = ""  # optional, local-only
    source: str | None = None  # citation label / "as of" that motivated it

    def is_due(self, today: date) -> bool:
        return date.fromisoformat(self.next_due) <= today

    def completed(self, today: date) -> Reminder:
        nxt = (today + timedelta(days=self.interval_days)).isoformat()
        return self.model_copy(update={"last_done": today.isoformat(), "next_due": nxt})


class ReminderError(ValueError):
    """Raised on an invalid reminder operation (unknown id, capacity exceeded)."""


class ReminderStore:
    """A JSON-file-backed collection of reminders. Clock-injectable for determinism."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_reminders: int = 200,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._path = Path(path)
        self._max = max_reminders
        self._clock = clock
        self._reminders: list[Reminder] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if raw.get("format_version") != _FORMAT_VERSION:
            raise ReminderError(f"unsupported reminders format: {raw.get('format_version')!r}")
        self._reminders = [Reminder.model_validate(r) for r in raw.get("reminders", [])]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": _FORMAT_VERSION,
            "reminders": [r.model_dump() for r in self._reminders],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )

    def all_reminders(self) -> list[Reminder]:
        """All reminders, soonest-due first."""
        return sorted(self._reminders, key=lambda r: (r.next_due, r.reminder_id))

    def due(self, as_of: date | None = None) -> list[Reminder]:
        """Reminders due on or before ``as_of`` (defaults to today)."""
        today = as_of or self._clock()
        return [r for r in self.all_reminders() if r.is_due(today)]

    def get(self, reminder_id: str) -> Reminder:
        for r in self._reminders:
            if r.reminder_id == reminder_id:
                return r
        raise ReminderError(f"no reminder with id {reminder_id!r}")

    def add(
        self,
        *,
        plant: str,
        kind: ReminderKind,
        interval_days: int,
        language: str = "en",
        note: str = "",
        source: str | None = None,
        first_due: date | None = None,
    ) -> Reminder:
        if len(self._reminders) >= self._max:
            raise ReminderError(f"reminder limit reached ({self._max})")
        today = self._clock()
        due = first_due or (today + timedelta(days=interval_days))
        # Deterministic, collision-resistant id: content + position, clock-injectable.
        rid = short(
            sha256_of_obj([plant, kind, interval_days, today.isoformat(), len(self._reminders)])
        )
        reminder = Reminder(
            reminder_id=rid,
            plant=plant,
            kind=kind,
            interval_days=interval_days,
            created_at=today.isoformat(),
            next_due=due.isoformat(),
            language=language,
            note=note,
            source=source,
        )
        self._reminders.append(reminder)
        self._save()
        return reminder

    def complete(self, reminder_id: str, as_of: date | None = None) -> Reminder:
        """Mark a reminder done and reschedule its next due date."""
        today = as_of or self._clock()
        updated = self.get(reminder_id).completed(today)
        self._reminders = [updated if r.reminder_id == reminder_id else r for r in self._reminders]
        self._save()
        return updated

    def remove(self, reminder_id: str) -> bool:
        before = len(self._reminders)
        self._reminders = [r for r in self._reminders if r.reminder_id != reminder_id]
        removed = len(self._reminders) != before
        if removed:
            self._save()
        return removed
