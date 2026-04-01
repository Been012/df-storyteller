"""Jinja2 templates singleton with filters and globals.

Imported by app.py at top level to ensure registration before any request.
Routers import ``templates`` from here.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from df_storyteller.web import state

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Jinja2 global: lore_link
# ---------------------------------------------------------------------------

_URL_MAP = {
    "figure": "figure", "civilization": "civ", "site": "site",
    "artifact": "artifact", "war": "war", "battle": "war",
    "duel": "event", "purge": "event", "beast_attack": "event",
    "abduction": "event", "theft": "event", "persecution": "event",
    "site_conquest": "event", "overthrow": "event",
    "written_work": "work", "festival": "festival",
    "form_poetic": "form", "form_musical": "form", "form_dance": "form",
}


def _lore_link(entity_type: str, entity_id: int | str | None, name: str) -> str:
    """Jinja2 global: render a clickable link to a lore detail page."""
    if entity_id is None or not name:
        return name or ""
    prefix = _URL_MAP.get(entity_type)
    if prefix is None:
        return Markup(f'<span class="lore-link" style="cursor: default; border-bottom-style: none;">{escape(name)}</span>')
    return Markup(f'<a href="/lore/{prefix}/{entity_id}" class="lore-link">{escape(name)}</a>')


templates.env.globals["lore_link"] = _lore_link


# ---------------------------------------------------------------------------
# Jinja2 filter: hotlink  ([[name]] -> clickable lore link)
# ---------------------------------------------------------------------------


def _build_hotlink_cache() -> dict[str, tuple[str, int | str]]:
    """Build a name lookup cache from legends data for [[name]] hotlinks."""
    existing = state.get_hotlink_cache()
    if existing is not None:
        return existing

    cache: dict[str, tuple[str, int | str]] = {}
    try:
        config = state.get_config()
        _, _, world_lore, _ = state.load_game_state_safe(config, skip_legends=False)
        if world_lore.is_loaded and world_lore._legends:
            legends = world_lore._legends
            # Historical figures
            for hfid, hf in legends.historical_figures.items():
                if hf.name:
                    cache[hf.name.lower()] = ("figure", hfid)
                    first = hf.name.split(",")[0].split(" the ")[0].strip()
                    if first and len(first) > 3 and first.lower() not in cache:
                        cache[first.lower()] = ("figure", hfid)
            # Sites
            for sid, site in legends.sites.items():
                if site.name:
                    cache[site.name.lower()] = ("site", sid)
            # Civilizations
            for eid, civ in legends.civilizations.items():
                if civ.name:
                    cache[civ.name.lower()] = ("civilization", eid)
            # Event collections
            _ec_type_map = {"war": "war", "battle": "battle", "duel": "duel",
                            "purge": "purge", "entity overthrown": "overthrow",
                            "beast attack": "beast_attack", "abduction": "abduction",
                            "theft": "theft", "persecution": "persecution",
                            "site conquered": "site_conquest"}
            for ec in legends.event_collections:
                name = ec.get("name", "")
                ec_type = ec.get("type", "")
                ec_id = ec.get("id", "")
                mapped = _ec_type_map.get(ec_type)
                if name and ec_id and mapped:
                    cache[name.lower()] = (mapped, ec_id)
            # Artifacts
            for aid, art in legends.artifacts.items():
                if art.name:
                    cache[art.name.lower()] = ("artifact", aid)
            # Written works
            for wc in legends.written_contents:
                title = wc.get("title", "")
                wc_id = wc.get("id", "")
                if title and wc_id:
                    cache[title.lower()] = ("written_work", wc_id)
            # Cultural forms
            for form_type, forms in [("poetic", legends.poetic_forms), ("musical", legends.musical_forms), ("dance", legends.dance_forms)]:
                for f in forms:
                    name = f.get("name", "")
                    fid = f.get("id", "")
                    if name and fid:
                        cache[name.lower()] = (f"form_{form_type}", f"{form_type}/{fid}")
            # Festivals
            for civ in legends.civilizations.values():
                for occ in getattr(civ, '_occasions', []):
                    name = occ.get("name", "")
                    oid = occ.get("id", "")
                    if name:
                        cache[name.lower()] = ("festival", f"{civ.entity_id}/{oid}")
    except Exception:
        pass

    state.set_hotlink_cache(cache)
    return cache


def _hotlink_filter(text: str) -> str:
    """Jinja2 filter: convert [[name]] patterns to clickable lore links."""
    if "[[" not in text:
        return text

    cache = _build_hotlink_cache()
    if not cache:
        return text.replace("[[", "").replace("]]", "")

    def replace_match(m: re.Match) -> str:
        name = m.group(1).strip()
        lookup = name.lower()
        if lookup in cache:
            entity_type, entity_id = cache[lookup]
            prefix = _URL_MAP.get(entity_type)
            if prefix:
                return f'<a href="/lore/{prefix}/{entity_id}" class="lore-link">{escape(name)}</a>'
            return str(escape(name))
        return f'<span style="border-bottom: 1px dashed var(--ink-faded);" title="Not found in legends">{escape(name)}</span>'

    result = re.sub(r'\[\[(.+?)\]\]', replace_match, text)
    return Markup(result)


templates.env.filters["hotlink"] = _hotlink_filter


def _inline_images_filter(text: str) -> str:
    """Jinja2 filter: convert {{img:uuid.ext}} to inline <img> tags."""
    if "{{img:" not in text:
        return text

    def replace_img(m: re.Match) -> str:
        filename = m.group(1)
        return (
            f'<a href="/api/images/{filename}" target="_blank" class="inline-image-link">'
            f'<img src="/api/images/{filename}" alt="Screenshot" class="inline-image" loading="lazy">'
            f'</a>'
        )

    result = re.sub(r'\{\{img:([0-9a-f]{32}\.\w+)\}\}', replace_img, text)
    return Markup(result)


templates.env.filters["inline_images"] = _inline_images_filter
