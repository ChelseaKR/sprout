"""RFC 5545 iCalendar export for local reminders — read-only, one direction only.

`sprout remind export --ics` (EXP-10, ``docs/ideation/03-expansions.md``) turns the
local :class:`~sprout.reminders.ReminderStore` into a standards-based ``.ics`` text
so any calendar app (Apple Calendar, Google Calendar, Thunderbird, ...) can notify
the user on the reminder's cadence. This closes the honest limit ADR-0011 states:
reminders have no sync/push channel of their own, so the user's own calendar
becomes the notifier instead.

This module is a pure function from reminders to text — no file I/O, no network,
no new state. There is deliberately no import path: this is export only, one
direction, no merge logic, so the reminders JSON file remains the single source of
truth (ADR-0011). Nothing here is presented as horticultural fact; a reminder's
cadence is the user's own setting, carried through unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime

from .reminders import Reminder

_PRODID = "-//Sprout//Reminders Export 1.0//EN"
_UID_DOMAIN = "sprout.local"
_CRLF = "\r\n"
_FOLD_LIMIT = 75  # RFC 5545 §3.1: content lines SHOULD NOT be longer than 75 octets.

# Reminder kind -> localized display label. Sprout does not (yet) ship a general
# locale-bundle system (that is FIX-09's job); this small table just keeps the two
# languages the reminder store already supports (``Reminder.language``) legible in
# the exported calendar's SUMMARY line, consistent with EXP-10's excellence bar of
# round-tripping correctly "in both languages."
_KIND_LABELS: dict[str, dict[str, str]] = {
    "water": {"en": "Water", "es": "Regar"},
    "fertilize": {"en": "Fertilize", "es": "Fertilizar"},
    "repot": {"en": "Repot", "es": "Trasplantar"},
    "mist": {"en": "Mist", "es": "Nebulizar"},
    "rotate": {"en": "Rotate", "es": "Girar"},
}


def _kind_label(kind: str, language: str) -> str:
    labels = _KIND_LABELS.get(kind, {})
    return labels.get(language) or labels.get("en") or kind.capitalize()


def _escape_text(value: str) -> str:
    """Escape a TEXT value per RFC 5545 §3.3.11 (backslash, semicolon, comma, newline)."""
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold one content line to RFC 5545's 75-octet limit, UTF-8 safe.

    Continuation lines are prefixed with a single space, per §3.1.
    """
    data = line.encode("utf-8")
    if len(data) <= _FOLD_LIMIT:
        return line
    chunks: list[bytes] = []
    start = 0
    while start < len(data):
        limit = _FOLD_LIMIT if start == 0 else _FOLD_LIMIT - 1
        end = min(start + limit, len(data))
        # Never split a multi-byte UTF-8 sequence across chunks.
        while end < len(data) and (data[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(data[start:end])
        start = end
    out = [chunks[0].decode("utf-8")]
    out += [" " + chunk.decode("utf-8") for chunk in chunks[1:]]
    return _CRLF.join(out)


def _dtstamp(now: datetime) -> str:
    utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _dtdate(value: str) -> str:
    return date.fromisoformat(value).strftime("%Y%m%d")


def _vevent_lines(reminder: Reminder, *, dtstamp: str) -> list[str]:
    label = _kind_label(reminder.kind, reminder.language)
    summary = f"{label}: {reminder.plant}"
    description_parts = [f"Sprout reminder: {label.lower()} '{reminder.plant}'."]
    if reminder.note:
        description_parts.append(f"Note: {reminder.note}")
    if reminder.source:
        description_parts.append(f"Motivated by: {reminder.source}")
    description_parts.append(
        "This cadence is the user's own setting, not a cited horticultural fact."
    )
    description = " ".join(description_parts)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{reminder.reminder_id}@{_UID_DOMAIN}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{_dtdate(reminder.next_due)}",
        f"RRULE:FREQ=DAILY;INTERVAL={reminder.interval_days}",
        f"SUMMARY:{_escape_text(summary)}",
        f"DESCRIPTION:{_escape_text(description)}",
        "CATEGORIES:PLANT-CARE",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return lines


def reminders_to_ics(
    reminders: Iterable[Reminder],
    *,
    calendar_name: str = "Sprout Reminders",
    now: Callable[[], datetime] | None = None,
) -> str:
    """Render ``reminders`` as an RFC 5545 iCalendar (``VCALENDAR``) text.

    Each reminder becomes one all-day, recurring ``VEVENT`` starting on its next
    due date with ``RRULE:FREQ=DAILY;INTERVAL=<interval_days>``, so the calendar
    app takes over notifying the user on the reminder's own cadence — the export
    is one-directional and read-only; nothing here is ever read back by Sprout.
    """
    clock = now or (lambda: datetime.now(UTC))
    stamp = _dtstamp(clock())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(calendar_name)}",
    ]
    for reminder in reminders:
        lines.extend(_vevent_lines(reminder, dtstamp=stamp))
    lines.append("END:VCALENDAR")
    return _CRLF.join(_fold(line) for line in lines) + _CRLF
