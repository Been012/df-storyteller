"""Pure helper functions shared across routers.

These functions have no mutable state. They may import from ``state``
for ``get_fortress_dir`` but never modify globals.
"""

from __future__ import annotations

import re
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.web.state import get_fortress_dir


# ---------------------------------------------------------------------------
# Dwarf name linking
# ---------------------------------------------------------------------------


def build_dwarf_name_map(character_tracker) -> dict[str, int]:
    """Build a map of all name variations to unit IDs for hotlinking.

    For a dwarf named 'Ezum Rabmebzuth "Glowoars", Miner':
    - Full name: 'Ezum Rabmebzuth "Glowoars", Miner'
    - Without profession: 'Ezum Rabmebzuth "Glowoars"'
    - First + last: 'Ezum Rabmebzuth'
    - Nickname: 'Glowoars'
    - First name: 'Ezum'
    """
    name_map: dict[str, int] = {}
    for dwarf, _ in character_tracker.ranked_characters():
        full = dwarf.name
        uid = dwarf.unit_id

        # Full name (may include profession suffix)
        name_map[full] = uid

        # Strip profession suffix (everything after last comma)
        if ", " in full:
            without_prof = full.rsplit(", ", 1)[0]
            name_map[without_prof] = uid

        # Extract parts: "FirstName LastName "Nickname""
        base = without_prof if ", " in full else full
        nickname_match = re.search(r'"([^"]+)"', base)
        if nickname_match:
            nickname = nickname_match.group(1)
            if len(nickname) > 2:
                name_map[nickname] = uid
            without_nick = re.sub(r'\s*"[^"]*"', '', base).strip()
            if without_nick:
                name_map[without_nick] = uid
                first = without_nick.split()[0]
                if len(first) >= 3:
                    name_map[first] = uid
        else:
            parts = base.split()
            if parts and len(parts[0]) >= 3:
                name_map[parts[0]] = uid

    return name_map


def linkify_dwarf_names(text: str, dwarf_map: dict[str, int]) -> str:
    """Replace dwarf names in text with links to their character sheets.

    dwarf_map: {name_fragment: unit_id} — maps various name forms to unit IDs.
    Longest names are matched first to avoid partial matches.
    Only replaces names that aren't already inside an <a> tag.
    """
    if not dwarf_map:
        return text

    sorted_names = sorted(dwarf_map.keys(), key=len, reverse=True)

    for name in sorted_names:
        if name not in text:
            continue
        unit_id = dwarf_map[name]
        link = f'<a href="/dwarves/{unit_id}" class="dwarf-link">{name}</a>'
        parts = re.split(r'(<a\b[^>]*>.*?</a>)', text)
        for i, part in enumerate(parts):
            if not part.startswith('<a '):
                parts[i] = part.replace(name, link)
        text = "".join(parts)

    return text


# ---------------------------------------------------------------------------
# Markdown conversion
# ---------------------------------------------------------------------------


def markdown_to_html(text: str) -> str:
    """Basic markdown to HTML conversion for story text."""
    lines = text.split("\n")
    html_lines = []
    in_paragraph = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("### "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading">{stripped[4:]}</p>')
            continue
        if stripped.startswith("## "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading">{stripped[3:]}</p>')
            continue
        if stripped.startswith("# "):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(f'<p class="story-heading story-title">{stripped[2:]}</p>')
            continue

        if stripped in ("---", "***", "___"):
            html_lines.append("<hr>")
            continue

        # Image references get their own block (not wrapped in <p>)
        if re.match(r"^\{\{img:[0-9a-f]{32}\.\w+\}\}$", stripped):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append(stripped)
            continue

        if not stripped:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            continue

        stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        stripped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", stripped)

        if not in_paragraph:
            html_lines.append("<p>")
            in_paragraph = True

        html_lines.append(stripped + " ")

    if in_paragraph:
        html_lines.append("</p>")

    return "\n".join(html_lines)


# ---------------------------------------------------------------------------
# Journal parsing
# ---------------------------------------------------------------------------


def _extract_image_ids(text: str) -> tuple[str, list[str]]:
    """Extract ``<!-- img:UUID.ext -->`` markers from text.

    Returns (clean_text, image_ids) where image markers are stripped.
    """
    ids = re.findall(r"<!-- img:([0-9a-f]{32}\.\w+) -->", text)
    clean = re.sub(r"\s*<!-- img:[0-9a-f]{32}\.\w+ -->\s*", "\n", text).strip()
    return clean, ids


def parse_journal(config: AppConfig, metadata: dict | None = None) -> list[dict]:
    """Parse the fortress journal markdown into entries."""
    fortress_dir = get_fortress_dir(config, metadata)
    journal_path = fortress_dir / "fortress_journal.md"
    if not journal_path.exists():
        return []

    text = journal_path.read_text(encoding="utf-8", errors="replace")
    entries = []

    parts = re.split(r"\n---\n", text)
    for part in parts:
        part = part.strip()
        if not part or part.startswith("# Fortress Journal"):
            continue

        header = ""
        body = part
        header_match = re.match(r"##\s+([^\n]+)\n\n(.*)", part, re.DOTALL)
        if header_match:
            header = header_match.group(1)
            body = header_match.group(2)

        if body.strip():
            raw_body = body.strip()
            is_manual = raw_body.startswith("<!-- source:manual -->")
            if is_manual:
                raw_body = raw_body.replace("<!-- source:manual -->", "").strip()

            # Extract image attachments from markers
            raw_body, image_ids = _extract_image_ids(raw_body)

            season_match = re.match(r"(\w+) of Year (\d+)", header)
            entry_season = season_match.group(1).lower() if season_match else ""
            entry_year = int(season_match.group(2)) if season_match else 0

            entries.append({
                "header": header,
                "text": markdown_to_html(raw_body),
                "raw_text": raw_body,
                "season": entry_season,
                "year": entry_year,
                "is_manual": is_manual,
                "images": image_ids,
            })

    return entries
