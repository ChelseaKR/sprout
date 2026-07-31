"""ICS export: RFC 5545 structure, RRULE, deterministic UIDs, escaping, folding.

Export is a pure function from reminders to text (EXP-10). These tests pin the
VCALENDAR/VEVENT shape, the DAILY RRULE with the reminder's own interval, and
that the reminders JSON stays untouched (no import path, no state mutation).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sprout.ics import reminders_to_ics
from sprout.reminders import Reminder, ReminderStore

_CLOCK = lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)  # noqa: E731


def _unfolded(text: str) -> str:
    """Undo RFC 5545 line folding so substring assertions ignore fold points."""
    return text.replace("\r\n ", "")


def _reminder(**overrides: object) -> Reminder:
    base = dict(
        reminder_id="abc123",
        plant="pothos",
        kind="water",
        interval_days=7,
        created_at="2026-06-01",
        next_due="2026-06-08",
        language="en",
        note="",
        source=None,
    )
    base.update(overrides)
    return Reminder.model_validate(base)


def test_wraps_in_valid_vcalendar() -> None:
    text = reminders_to_ics([_reminder()], now=_CLOCK)
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in text
    assert "PRODID:-//Sprout//Reminders Export 1.0//EN\r\n" in text
    assert text.count("BEGIN:VEVENT") == 1
    assert text.count("END:VEVENT") == 1


def test_rrule_uses_daily_freq_and_interval() -> None:
    text = reminders_to_ics([_reminder(interval_days=14)], now=_CLOCK)
    assert "RRULE:FREQ=DAILY;INTERVAL=14\r\n" in text


def test_dtstart_is_next_due_all_day() -> None:
    text = reminders_to_ics([_reminder(next_due="2026-07-04")], now=_CLOCK)
    assert "DTSTART;VALUE=DATE:20260704\r\n" in text


def test_uid_is_deterministic_from_reminder_id() -> None:
    text = reminders_to_ics([_reminder(reminder_id="xyz789")], now=_CLOCK)
    assert "UID:xyz789@sprout.local\r\n" in text
    # Same input -> byte-identical output (determinism, per CLAUDE.md).
    again = reminders_to_ics([_reminder(reminder_id="xyz789")], now=_CLOCK)
    assert text == again


def test_summary_localized_by_reminder_language() -> None:
    en = reminders_to_ics([_reminder(kind="fertilize", language="en", plant="fern")], now=_CLOCK)
    es = reminders_to_ics([_reminder(kind="fertilize", language="es", plant="fern")], now=_CLOCK)
    assert "SUMMARY:Fertilize: fern\r\n" in en
    assert "SUMMARY:Fertilizar: fern\r\n" in es


def test_note_and_source_appear_in_description_never_as_fact() -> None:
    text = _unfolded(
        reminders_to_ics([_reminder(note="by the window", source="ADR-0011")], now=_CLOCK)
    )
    assert "Note: by the window" in text
    assert "Motivated by: ADR-0011" in text
    assert "not a cited horticultural fact" in text


def test_special_characters_are_escaped() -> None:
    text = _unfolded(reminders_to_ics([_reminder(plant="Grandma's Fern, Inc.; #1")], now=_CLOCK))
    assert "Grandma's Fern\\, Inc.\\; #1" in text


def test_long_line_is_folded_at_75_octets() -> None:
    long_note = "x" * 200
    text = reminders_to_ics([_reminder(note=long_note)], now=_CLOCK)
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75


def test_multiple_reminders_each_get_a_vevent() -> None:
    text = reminders_to_ics(
        [_reminder(reminder_id="a"), _reminder(reminder_id="b", plant="monstera")],
        now=_CLOCK,
    )
    assert text.count("BEGIN:VEVENT") == 2
    assert "UID:a@sprout.local\r\n" in text
    assert "UID:b@sprout.local\r\n" in text


def test_empty_store_still_produces_valid_calendar() -> None:
    text = reminders_to_ics([], now=_CLOCK)
    assert "BEGIN:VEVENT" not in text
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")


def test_export_reads_store_without_mutating_it(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    store = ReminderStore(path, clock=lambda: date(2026, 6, 1))
    store.add(plant="pothos", kind="water", interval_days=7)
    before = path.read_text(encoding="utf-8")
    reminders_to_ics(store.all_reminders(), now=_CLOCK)
    after = path.read_text(encoding="utf-8")
    assert before == after
