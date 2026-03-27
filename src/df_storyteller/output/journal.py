"""Append-mode fortress journal for chronicle entries.

One entry per season/year. If an entry already exists for a given season,
it is replaced rather than duplicated.
"""

from __future__ import annotations

import re
from pathlib import Path

from df_storyteller.config import AppConfig


def _journal_path(config: AppConfig) -> Path:
    output_dir = Path(config.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "fortress_journal.md"


def get_existing_seasons(config: AppConfig) -> list[tuple[str, int]]:
    """Return list of (season, year) that already have chronicle entries."""
    path = _journal_path(config)
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    return re.findall(r"## (\w+) of Year (\d+)", text)


def has_entry_for(config: AppConfig, season: str, year: int) -> bool:
    """Check if a chronicle entry already exists for this season/year."""
    existing = get_existing_seasons(config)
    return any(s.lower() == season.lower() and int(y) == year for s, y in existing)


def append_to_journal(config: AppConfig, entry: str, year: int, season: str) -> Path:
    """Add or replace a chronicle entry in the fortress journal."""
    path = _journal_path(config)

    season_header = f"## {season.title()} of Year {year}"

    if not path.exists() or path.stat().st_size == 0:
        # New journal
        content = f"# Fortress Journal\n\nA chronicle of our fortress.\n\n---\n\n{season_header}\n\n{entry}\n"
        path.write_text(content, encoding="utf-8")
        return path

    text = path.read_text(encoding="utf-8", errors="replace")

    # Check if entry for this season/year already exists — replace it
    pattern = rf"(---\n\n)?## {re.escape(season.title())} of Year {year}\n\n.*?(?=\n---\n|$)"
    if re.search(pattern, text, re.DOTALL):
        replacement = f"---\n\n{season_header}\n\n{entry}"
        text = re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)
        path.write_text(text, encoding="utf-8")
    else:
        # New season — append
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{season_header}\n\n{entry}\n")

    return path
