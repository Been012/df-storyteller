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


def resolve_wiki_links(text: str, world_lore=None, fortress_dir=None) -> str:
    """Convert [[wiki-style links]] to clickable links.

    Tries to match against: lore pins, historical figures, sites,
    entities, artifacts, wars in the world lore. Falls back to a styled
    span if no match is found.

    Syntax: [[name]] or [[display text|search term]]
    """
    import re as _re

    def _replace_link(m: _re.Match) -> str:
        content = m.group(1).strip()
        # Support [[display|search]] syntax
        if "|" in content:
            display, search = content.split("|", 1)
            display = display.strip()
            search = search.strip()
        else:
            display = content
            search = content

        search_lower = search.lower()

        # Search legends data FIRST (authoritative source for named entities)
        if world_lore and hasattr(world_lore, "_legends") and world_lore._legends:
            legends = world_lore._legends

            # Search historical figures (id field: hf_id)
            if hasattr(legends, "historical_figures"):
                for hf in legends.historical_figures.values():
                    hf_name = getattr(hf, "name", "")
                    if hf_name and search_lower in hf_name.lower():
                        return f'<a href="/lore/figure/{hf.hf_id}" class="dwarf-link">{display}</a>'

            # Search sites (id field: site_id)
            if hasattr(legends, "sites"):
                for site in legends.sites.values():
                    site_name = getattr(site, "name", "")
                    if site_name and search_lower in site_name.lower():
                        return f'<a href="/lore/site/{site.site_id}" class="dwarf-link">{display}</a>'

            # Search civilizations/entities (id field: entity_id)
            if hasattr(legends, "civilizations"):
                civs = legends.civilizations
                civ_iter = civs.values() if isinstance(civs, dict) else civs
                for ent in civ_iter:
                    ent_name = getattr(ent, "name", "")
                    if ent_name and search_lower in ent_name.lower():
                        return f'<a href="/lore/civ/{ent.entity_id}" class="dwarf-link">{display}</a>'

            # Search artifacts (id field: artifact_id)
            if hasattr(legends, "artifacts"):
                for art in legends.artifacts.values():
                    art_name = getattr(art, "name", "")
                    if art_name and search_lower in art_name.lower():
                        return f'<a href="/lore/artifact/{art.artifact_id}" class="dwarf-link">{display}</a>'

            # Search regions (list of dicts or Pydantic models)
            if hasattr(legends, "regions"):
                regions = legends.regions
                region_iter = regions.values() if isinstance(regions, dict) else regions
                for region in region_iter:
                    region_name = region.get("name", "") if isinstance(region, dict) else getattr(region, "name", "")
                    if region_name and search_lower in region_name.lower():
                        region_id = region.get("id", 0) if isinstance(region, dict) else getattr(region, "region_id", getattr(region, "id", 0))
                        return f'<a href="/lore/region/{region_id}" class="dwarf-link">{display}</a>'

            # Search wars/event collections (list of dicts or Pydantic models)
            if hasattr(legends, "event_collections"):
                ecs = legends.event_collections
                ec_iter = ecs.values() if isinstance(ecs, dict) else ecs
                for ec in ec_iter:
                    ec_name = ec.get("name", "") if isinstance(ec, dict) else getattr(ec, "name", "")
                    ec_type = ec.get("type", "") if isinstance(ec, dict) else getattr(ec, "ec_type", "")
                    if ec_name and search_lower in ec_name.lower():
                        ec_id = ec.get("id", 0) if isinstance(ec, dict) else getattr(ec, "ec_id", getattr(ec, "id", 0))
                        if ec_type == "war":
                            return f'<a href="/lore/war/{ec_id}" class="dwarf-link">{display}</a>'
                        return f'<a href="/lore/event/{ec_id}" class="dwarf-link">{display}</a>'

        # Fallback: check lore pins (user-labeled references for events, duels, etc.)
        if fortress_dir:
            try:
                from df_storyteller.context.lore_pins import load_pins
                for pin in load_pins(fortress_dir):
                    pin_name = pin.get("name", "").lower()
                    pin_note = pin.get("note", "").lower()
                    if search_lower in pin_name or search_lower in pin_note:
                        etype = pin.get("entity_type", "")
                        eid = pin.get("entity_id", "")
                        url_map = {
                            "figure": f"/lore/figure/{eid}",
                            "site": f"/lore/site/{eid}",
                            "entity": f"/lore/civ/{eid}",
                            "civilization": f"/lore/civ/{eid}",
                            "artifact": f"/lore/artifact/{eid}",
                            "war": f"/lore/war/{eid}",
                            "battle": f"/lore/war/{eid}",
                            "region": f"/lore/region/{eid}",
                            "geography": f"/lore/region/{eid}",
                            "written_work": f"/lore/work/{eid}",
                            "cultural_form": f"/lore/form/poetic/{eid}",
                            "landmass": f"/lore/landmass/{eid}",
                            "peak": f"/lore/peak/{eid}",
                            "construction": f"/lore/construction/{eid}",
                        }
                        url = url_map.get(etype, f"/lore/event/{eid}")
                        return f'<a href="{url}" class="dwarf-link">{display}</a>'
            except Exception:
                pass

        # No match — render as styled text
        return f'<span class="wiki-link-unresolved" title="Not found in legends">{display}</span>'

    return _re.sub(r"\[\[([^\]]+)\]\]", _replace_link, text)


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
