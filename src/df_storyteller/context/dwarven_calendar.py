"""Dwarven calendar utilities for converting DF ticks to dates."""

from __future__ import annotations

MONTHS = [
    "Granite", "Slate", "Felsite",       # Spring
    "Hematite", "Malachite", "Galena",    # Summer
    "Limestone", "Sandstone", "Timber",   # Autumn
    "Moonstone", "Opal", "Obsidian",      # Winter
]

SEASONS = [
    "Spring", "Spring", "Spring",
    "Summer", "Summer", "Summer",
    "Autumn", "Autumn", "Autumn",
    "Winter", "Winter", "Winter",
]

TICKS_PER_DAY = 1200
TICKS_PER_MONTH = 28 * TICKS_PER_DAY  # 33600
TICKS_PER_YEAR = 12 * TICKS_PER_MONTH  # 403200


def ticks_to_date(seconds72: int | str | None) -> dict | None:
    """Convert seconds72 (DF ticks) to a dwarven calendar date.

    Returns: {month, season, day, month_idx} or None if invalid.
    """
    if seconds72 is None:
        return None
    try:
        t = int(seconds72)
    except (ValueError, TypeError):
        return None
    if t < 0:
        return None

    month_idx = min(t // TICKS_PER_MONTH, 11)
    day = (t % TICKS_PER_MONTH) // TICKS_PER_DAY + 1

    return {
        "month": MONTHS[month_idx],
        "season": SEASONS[month_idx],
        "day": day,
        "month_idx": month_idx,
    }


def _ordinal(n: int) -> str:
    """Return ordinal string: 1st, 2nd, 3rd, 4th, ..."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd'][min(n % 10, 3)] if n % 10 < 4 else 'th'}"


def format_date(seconds72: int | str | None) -> str:
    """Format seconds72 as '24th of Timber' style string."""
    date = ticks_to_date(seconds72)
    if not date:
        return ""
    return f"{_ordinal(date['day'])} of {date['month']}"


def format_date_range(start_seconds72: int | str | None, end_seconds72: int | str | None) -> str:
    """Format a date range like '24th–27th of Timber (Autumn)'."""
    start = ticks_to_date(start_seconds72)
    end = ticks_to_date(end_seconds72)
    if not start:
        return ""
    if not end or (start["month"] == end["month"] and start["day"] == end["day"]):
        return f"{_ordinal(start['day'])} of {start['month']} ({start['season']})"
    if start["month"] == end["month"]:
        return f"{_ordinal(start['day'])}–{_ordinal(end['day'])} of {start['month']} ({start['season']})"
    return f"{_ordinal(start['day'])} of {start['month']} – {_ordinal(end['day'])} of {end['month']}"
