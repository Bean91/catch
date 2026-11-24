"""Session 36 follow-up: an iCalendar (RFC 5545) file of planned sessions and events. Pure, no I/O (the DB half is
catch/sync/calendar_export.py). No library: the subset written here is small and the rules are spelled out —

  * lines end CRLF and are folded at 75 octets (a continuation line starts with one space, never splitting a UTF-8 character);
  * TEXT values escape backslash, semicolon, comma and newline;
  * a date-only item is an all-day VEVENT (`VALUE=DATE`, DTEND the next day); a timed one is written in UTC (`…Z`), so no
    VTIMEZONE block is needed;
  * UIDs are stable per row, so importing the file again updates the same entries instead of adding copies.

Plans and events only: a completed workout is never written as a calendar entry here."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

PRODID = "-//Catch//Training calendar//EN"


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fold(line: str) -> str:
    """Split one content line into ≤ 75-octet pieces joined by CRLF + space."""
    out: list[str] = []
    current = ""
    size = 0
    limit = 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(current)
            current, size, limit = ch, n, 74  # a continuation line's leading space counts toward its 75
        else:
            current += ch
            size += n
    out.append(current)
    return "\r\n ".join(out)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _day(d: date) -> str:
    return d.strftime("%Y%m%d")


def vevent(*, uid: str, stamp: datetime, summary: str, day: date, start: Optional[datetime] = None, minutes: Optional[float] = None,
           description: Optional[str] = None, location: Optional[str] = None, cancelled: bool = False, categories: Optional[str] = None) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_utc(stamp)}"]
    if start is not None:
        lines.append(f"DTSTART:{_utc(start)}")
        lines.append(f"DTEND:{_utc(start + timedelta(minutes=minutes or 60))}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{_day(day)}")
        lines.append(f"DTEND;VALUE=DATE:{_day(day + timedelta(days=1))}")
    lines.append(f"SUMMARY:{escape(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{escape(description)}")
    if location:
        lines.append(f"LOCATION:{escape(location)}")
    if categories:
        lines.append(f"CATEGORIES:{escape(categories)}")
    if cancelled:
        lines.append("STATUS:CANCELLED")
    lines.append("TRANSP:TRANSPARENT")
    lines.append("END:VEVENT")
    return lines


def calendar(events: list[list[str]], *, name: str = "Catch training") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{escape(name)}"]
    for e in events:
        lines.extend(e)
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
