"""Reminder scheduler: add/list/due/complete/remove, rescheduling, persistence, errors.

Reminders are local user data, so the store is a single JSON file with an injectable
clock. These tests pin the scheduling arithmetic and the round-trip so behaviour is
deterministic and offline.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sprout.reminders import Reminder, ReminderError, ReminderStore


def _store(tmp_path: Path, today: date = date(2026, 6, 1)) -> ReminderStore:
    return ReminderStore(tmp_path / "reminders.json", clock=lambda: today)


def test_add_sets_created_and_next_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    r = store.add(plant="pothos", kind="water", interval_days=7)
    assert r.created_at == "2026-06-01"
    assert r.next_due == "2026-06-08"
    assert r.plant == "pothos" and r.kind == "water"


def test_list_sorted_and_persisted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(plant="monstera", kind="fertilize", interval_days=30)
    store.add(plant="pothos", kind="water", interval_days=7)
    # Reload from disk: persistence round-trips.
    reloaded = _store(tmp_path)
    reminders = reloaded.all_reminders()
    assert len(reminders) == 2
    assert reminders[0].next_due <= reminders[1].next_due


def test_due_uses_clock_and_as_of(tmp_path: Path) -> None:
    store = _store(tmp_path, today=date(2026, 6, 1))
    store.add(plant="pothos", kind="water", interval_days=7)  # due 2026-06-08
    assert store.due() == []  # nothing due yet on 2026-06-01
    assert len(store.due(as_of=date(2026, 6, 9))) == 1


def test_complete_reschedules(tmp_path: Path) -> None:
    store = _store(tmp_path, today=date(2026, 6, 1))
    r = store.add(plant="pothos", kind="water", interval_days=7)
    done = store.complete(r.reminder_id, as_of=date(2026, 6, 9))
    assert done.last_done == "2026-06-09"
    assert done.next_due == "2026-06-16"
    # Persisted.
    assert _store(tmp_path).get(r.reminder_id).next_due == "2026-06-16"


def test_complete_unknown_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ReminderError):
        store.complete("nope")
    with pytest.raises(ReminderError):
        store.get("nope")


def test_remove(tmp_path: Path) -> None:
    store = _store(tmp_path)
    r = store.add(plant="pothos", kind="water", interval_days=7)
    assert store.remove(r.reminder_id) is True
    assert store.remove(r.reminder_id) is False
    assert store.all_reminders() == []


def test_capacity_limit(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "r.json", max_reminders=1, clock=lambda: date(2026, 6, 1))
    store.add(plant="pothos", kind="water", interval_days=7)
    with pytest.raises(ReminderError):
        store.add(plant="monstera", kind="water", interval_days=7)


def test_ids_are_deterministic_and_distinct(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a = store.add(plant="pothos", kind="water", interval_days=7)
    b = store.add(plant="pothos", kind="water", interval_days=7)
    # Same content but different position -> distinct, reproducible ids.
    assert a.reminder_id != b.reminder_id
    assert len(a.reminder_id) == 12


def test_first_due_override(tmp_path: Path) -> None:
    store = _store(tmp_path, today=date(2026, 6, 1))
    r = store.add(plant="pothos", kind="water", interval_days=7, first_due=date(2026, 6, 2))
    assert r.next_due == "2026-06-02"


def test_unsupported_format_raises(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text('{"format_version": 99, "reminders": []}', encoding="utf-8")
    with pytest.raises(ReminderError):
        ReminderStore(path)


def test_reminder_is_due_and_completed_helpers() -> None:
    r = Reminder(
        reminder_id="x",
        plant="pothos",
        kind="water",
        interval_days=7,
        created_at="2026-06-01",
        next_due="2026-06-08",
    )
    assert r.is_due(date(2026, 6, 8)) is True
    assert r.is_due(date(2026, 6, 7)) is False
    assert r.completed(date(2026, 6, 9)).next_due == "2026-06-16"
