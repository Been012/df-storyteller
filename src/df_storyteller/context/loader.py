"""Load game state from DFHack JSON files and gamelog into context objects.

This is the bridge between raw files on disk and the story generators.
It reads snapshots, event files, and gamelog to populate the event store
and character tracker.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.context.character_tracker import CharacterTracker
from df_storyteller.context.context_builder import ContextBuilder
from df_storyteller.context.event_store import EventStore
from df_storyteller.context.world_lore import WorldLore
from df_storyteller.ingestion.dfhack_json_parser import parse_dfhack_file
from df_storyteller.schema.entities import Animal, Dwarf, Relationship, Skill
from df_storyteller.schema.events import EventType, GameEvent, Season
from df_storyteller.schema.personality import Belief, Facet, Goal, Personality

logger = logging.getLogger(__name__)


def _load_appearance(raw: dict) -> "DwarfAppearance":
    """Parse appearance data from a snapshot citizen entry."""
    from df_storyteller.schema.entities import DwarfAppearance
    a = raw.get("appearance", {})
    if not a:
        return DwarfAppearance()
    return DwarfAppearance(
        skin_color=a.get("skin_color", ""),
        hair_color=a.get("hair_color", ""),
        beard_color=a.get("beard_color", ""),
        eyebrow_color=a.get("eyebrow_color", ""),
        hair_length=a.get("hair_length", 0),
        hair_style=a.get("hair_style", ""),
        hair_curly=a.get("hair_curly", 0),
        beard_length=a.get("beard_length", 0),
        beard_style=a.get("beard_style", ""),
        body_broadness=a.get("body_broadness", 100),
        eye_round_vs_narrow=a.get("eye_round_vs_narrow", 100),
        eye_deep_set=a.get("eye_deep_set", 100),
        eyebrow_density=a.get("eyebrow_density", 100),
        nose_upturned=a.get("nose_upturned", 100),
        nose_length=a.get("nose_length", 100),
        nose_broadness=a.get("nose_broadness", 100),
    )


def _load_personality(raw: dict) -> Personality:
    """Parse personality data from a snapshot citizen entry."""
    p = raw.get("personality", {})
    if not p:
        return Personality()

    facets = [Facet(name=f["name"], value=f["value"]) for f in p.get("facets", [])]
    beliefs = [Belief(name=b["name"], value=b["value"]) for b in p.get("beliefs", [])]
    goals = [
        Goal(name=g["name"], achieved=g.get("achieved", False))
        for g in p.get("goals", [])
    ]
    return Personality(facets=facets, beliefs=beliefs, goals=goals)


def _describe_animal_traits(raw: dict) -> list[str]:
    """Derive readable trait descriptions from an animal's physical attributes."""
    phys = raw.get("physical_attributes", {})
    traits: list[str] = []
    _DESCRIPTIONS = {
        "STRENGTH": {True: "very strong", False: "weak"},
        "AGILITY": {True: "very agile", False: "clumsy"},
        "TOUGHNESS": {True: "very tough", False: "fragile"},
        "ENDURANCE": {True: "tireless", False: "tires easily"},
        "RECUPERATION": {True: "heals quickly", False: "recovers slowly"},
        "DISEASE_RESISTANCE": {True: "hardy", False: "sickly"},
    }
    for attr, labels in _DESCRIPTIONS.items():
        val = phys.get(attr)
        if val is None:
            continue
        if val >= 1500:
            traits.append(labels[True])
        elif val <= 400:
            traits.append(labels[False])
    return traits


def _load_animal_from_snapshot(raw: dict) -> Animal:
    """Create an Animal entity from a snapshot animal entry."""
    profession = raw.get("profession", "")
    is_pet = raw.get("is_pet", False)
    available_for_adoption = raw.get("available_for_adoption", False)
    is_tame = raw.get("is_tame", False)
    is_wildlife = raw.get("is_wildlife", False)
    prof_lower = profession.lower()

    if is_pet:
        category = "pet"
    elif "war" in prof_lower:
        category = "war"
    elif "hunting" in prof_lower:
        category = "hunting"
    elif available_for_adoption:
        category = "adoptable"
    elif is_wildlife:
        category = "wild"
    elif is_tame:
        category = "tame"
    elif raw.get("civ_id", -1) >= 0:
        category = "tame"
    else:
        category = "wild"

    # Prefer pet_name (e.g. "Whipwayward") over generic name (e.g. "Cat (tame)")
    name = raw.get("pet_name", "") or raw.get("name", "")

    return Animal(
        unit_id=raw.get("unit_id", 0),
        name=name,
        race=raw.get("race", "").replace("_", " ").lower(),
        profession=profession,
        age=raw.get("age", 0),
        sex=raw.get("sex", "unknown"),
        is_alive=raw.get("is_alive", True),
        is_pet=is_pet,
        available_for_adoption=available_for_adoption,
        owner_id=raw.get("owner_id", -1),
        owner_name=raw.get("owner_name", ""),
        category=category,
        traits=_describe_animal_traits(raw),
    )


def _load_dwarf_from_snapshot(citizen: dict) -> Dwarf:
    """Create a Dwarf entity from a snapshot citizen entry."""
    skills = [
        Skill(
            name=s.get("name", ""),
            level=str(s.get("level", "")),
            experience=s.get("experience", 0),
        )
        for s in citizen.get("skills", [])
    ]

    # Parse relationships
    relationships = [
        Relationship(
            target_unit_id=r.get("target_id", 0),
            target_name=r.get("target_name", ""),
            relationship_type=r.get("type", ""),
        )
        for r in citizen.get("relationships", [])
    ]

    # Parse military
    mil = citizen.get("military", {})
    military_squad = mil.get("squad_name", "") if isinstance(mil, dict) else ""

    # Parse equipment — preserve all fields for portrait rendering
    # Legacy format: {description, mode}
    # New format adds: {item_type, item_subtype, slot, material_flags, material_color, material_type}
    equipment = [
        e for e in citizen.get("equipment", [])
        if isinstance(e, dict) and e.get("description")
    ]

    return Dwarf(
        unit_id=citizen.get("unit_id", 0),
        hist_figure_id=citizen.get("hist_figure_id", -1),
        name=citizen.get("name", "Unknown"),
        profession=citizen.get("profession", ""),
        race=citizen.get("race", "DWARF"),
        sex=citizen.get("sex", "unknown"),
        age=citizen.get("age", 0),
        skills=skills,
        stress_category=citizen.get("stress_category", 3),
        happiness=citizen.get("happiness", 0),
        relationships=relationships,
        birth_year=citizen.get("birth_year", 0),
        is_alive=citizen.get("is_alive", True),
        personality=_load_personality(citizen),
        noble_positions=citizen.get("noble_positions", []),
        military_squad=military_squad,
        current_job=citizen.get("current_job", ""),
        equipment=equipment,
        wounds=citizen.get("wounds", []),
        pets=citizen.get("pets", []),
        physical_attributes=citizen.get("physical_attributes", {}),
        mental_attributes=citizen.get("mental_attributes", {}),
        is_vampire=citizen.get("is_vampire", False),
        is_werebeast=citizen.get("is_werebeast", False),
        assumed_identity=citizen.get("assumed_identity", ""),
        appearance=_load_appearance(citizen),
    )



# Gamelog parsing was removed — chat/conversation data is now captured via
# DFHack onReport hooks and written as CHAT events. See storyteller-events.lua.


def _get_valid_session_ids(folder: Path) -> set[str]:
    """Get all valid session_ids for the current site in a folder.

    Reads .session_info and returns all session_ids from session_ids_by_site
    for the current site_id. This handles retire/reclaim cycles where a
    fortress may have multiple sessions across different play stints.
    Falls back to just the single session_id for older formats.
    """
    info_file = folder / ".session_info"
    if not info_file.exists():
        return set()
    try:
        info = json.loads(info_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    site_id = str(info.get("site_id", -1))
    by_site = info.get("session_ids_by_site", {})
    if site_id in by_site:
        return set(by_site[site_id])

    # Fallback: just the single session_id
    sid = info.get("session_id", "")
    return {sid} if sid else set()


def _get_folder_identity(folder: Path) -> str | None:
    """Get a stable identity for a world folder based on fortress identity.

    Returns 'site_id:civ_id:fortress_name' — the same across all save slots
    (region2, autosave 1, test1) for the same fortress. This allows
    merging event data from multiple save folders.

    site_id is the primary differentiator — unique per site in the world,
    handles retire-and-restart scenarios where civ_id could be the same.

    Session_id is NOT included in the identity — it's only used for
    filtering stale events within a folder that was reused by a different
    fortress (handled separately in the event loading code).
    """
    # Check .session_info first (new format — has validated identity fields)
    session_info_file = folder / ".session_info"
    if session_info_file.exists():
        try:
            info = json.loads(session_info_file.read_text(encoding="utf-8"))
            site_id = info.get("site_id", -1)
            civ_id = info.get("civ_id", -1)
            name = info.get("fortress_name", "")
            if site_id is not None and site_id >= 0:
                return f"{site_id}:{civ_id}:{name}"
            if civ_id is not None and civ_id >= 0:
                return f"{civ_id}:{name}"
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: read from most recent snapshot by mtime (not filename).
    # Without .session_info the folder may contain mixed data from multiple
    # fortresses that reused the same save slot. Use mtime to get the
    # currently-active fortress, and prefix with "legacy:" so these
    # identities never merge with validated .session_info folders.
    snapshots = sorted(folder.glob("snapshot_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if not snapshots:
        return None
    try:
        with open(snapshots[0], encoding="utf-8", errors="replace") as f:
            snap = json.load(f)
        fi = snap.get("data", {}).get("fortress_info", {})
        site_id = fi.get("site_id", -1)
        civ_id = fi.get("civ_id", -1)
        name = fi.get("fortress_name", "")
        if site_id is not None and site_id >= 0:
            return f"{site_id}:{civ_id}:{name}"
        # Legacy folder — use a unique prefix so it only merges with other
        # legacy folders that have matching session_id (stronger signal).
        sid = fi.get("session_id", "")
        if sid:
            return f"legacy:{civ_id}:{name}:{sid}"
        # No session_id at all — make identity folder-unique to prevent
        # merging mixed data across folders.
        return f"legacy:{folder.name}:{civ_id}:{name}"
    except (json.JSONDecodeError, OSError):
        pass
    return None




def get_fortress_output_dir(config: AppConfig, metadata: dict | None = None) -> Path:
    """Get the per-fortress output directory for stories, notes, etc.

    Uses site_id + fortress_name to create isolated directories per fortress.
    site_id handles retire-and-restart scenarios where civ_id could be the same.
    Falls back to civ_id + fortress_name for older data without site_id.
    """
    base = Path(config.paths.output_dir)
    if metadata:
        fi = metadata.get("fortress_info", {})
        site_id = fi.get("site_id", -1)
        civ_id = fi.get("civ_id", "")
        name = metadata.get("fortress_name", "")
        if name:
            safe_name = name.lower().replace(" ", "_")
            if site_id is not None and site_id >= 0:
                fortress_dir = base / f"s{site_id}_{safe_name}"
            elif civ_id:
                fortress_dir = base / f"{civ_id}_{safe_name}"
            else:
                fortress_dir = base / safe_name
            # Migrate: if old civ_id-based dir exists but new site_id-based doesn't,
            # rename it so stories carry over
            if site_id is not None and site_id >= 0 and civ_id:
                old_dir = base / f"{civ_id}_{safe_name}"
                if old_dir.exists() and not fortress_dir.exists():
                    try:
                        old_dir.rename(fortress_dir)
                    except OSError:
                        pass
            fortress_dir.mkdir(parents=True, exist_ok=True)
            return fortress_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


def load_game_state(config: AppConfig, skip_legends: bool = False, active_world: str = "") -> tuple[EventStore, CharacterTracker, WorldLore, dict]:
    """Load all available game data from disk.

    Args:
        config: Application configuration.
        skip_legends: If True, skip loading legends XML (expensive for large files).
        active_world: If set, use this world folder as the primary instead of the most recent.

    Reads:
    - Snapshot JSON files (fortress state with citizens, visitors, buildings)
    - Event JSON files (deaths, combat, moods, etc.)
    - Gamelog (if configured)

    Returns:
        Tuple of (event_store, character_tracker, world_lore, metadata)
        where metadata contains fortress_name, year, season, etc.
    """
    event_store = EventStore()
    character_tracker = CharacterTracker()
    world_lore = WorldLore()
    metadata: dict = {
        "fortress_name": "", "site_name": "", "civ_name": "", "biome": "",
        "year": 0, "season": "spring", "population": 0,
        "visitors": [], "animals": [], "buildings": [],
        "fortress_info": {},
    }

    base_event_dir = Path(config.paths.event_dir) if config.paths.event_dir else None

    # Find all world subfolders that belong to the same fortress.
    # DF save folder names can change (region2 vs autosave 1) for the same world,
    # so we merge all folders that share the same fortress identity.
    event_dirs: list[Path] = []
    event_dir = None
    if base_event_dir and base_event_dir.exists():
        world_dirs = [
            d for d in base_event_dir.iterdir()
            if d.is_dir() and d.name != "processed"
        ]
        if world_dirs:
            # Use active_world if specified and exists, otherwise most recent
            primary_dir = None
            if active_world:
                candidate = base_event_dir / active_world
                if candidate.exists() and candidate.is_dir():
                    primary_dir = candidate
            if not primary_dir:
                primary_dir = max(world_dirs, key=lambda d: d.stat().st_mtime)

            event_dir = primary_dir
            event_dirs = [primary_dir]

            # Read its fortress identity to find sibling folders.
            # Folders with the same identity (including session_id) are merged —
            # this handles DF renaming save folders on autosave.
            primary_identity = _get_folder_identity(primary_dir)
            if primary_identity:
                for wd in world_dirs:
                    if wd == primary_dir:
                        continue
                    if _get_folder_identity(wd) == primary_identity:
                        event_dirs.append(wd)
                        logger.info("Merging sibling folder: %s", wd.name)

            logger.info("Using world folder: %s (%d total)", event_dir.name, len(event_dirs))

    processed_dir = event_dir / "processed" if event_dir else None

    # 1. Load the most recent snapshot across all matching folders.
    # Filter by per-folder session_ids to avoid loading a stale snapshot
    # from a previous fortress that shared the same save folder.
    # Uses session_ids_by_site so reclaimed fortresses keep their old snapshots.
    snapshots: list[Path] = []
    if event_dirs:
        for ed in event_dirs:
            valid_sids = _get_valid_session_ids(ed)

            for snap_path in list(ed.glob("snapshot_*.json")) + (
                list((ed / "processed").glob("snapshot_*.json")) if (ed / "processed").exists() else []
            ):
                if valid_sids:
                    try:
                        with open(snap_path, encoding="utf-8", errors="replace") as f:
                            snap_data = json.load(f)
                        snap_sid = snap_data.get("data", {}).get("fortress_info", {}).get("session_id", "")
                        if snap_sid and snap_sid not in valid_sids:
                            continue  # Stale snapshot from different fortress
                    except (json.JSONDecodeError, OSError):
                        pass
                snapshots.append(snap_path)
        snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if event_dirs:

        if snapshots:
            latest_snapshot = snapshots[0]
            logger.info("Loading snapshot: %s", latest_snapshot)
            try:
                with open(latest_snapshot, encoding="utf-8", errors="replace") as f:
                    snap = json.load(f)

                data = snap.get("data", {})
                metadata["year"] = snap.get("game_year", 0)
                metadata["season"] = snap.get("season", "spring")
                metadata["population"] = data.get("population", 0)

                # Fortress info (new comprehensive format)
                fi = data.get("fortress_info", {})
                metadata["fortress_info"] = fi
                metadata["fortress_name"] = fi.get("fortress_name", "") or data.get("fortress_name", "")
                metadata["site_name"] = fi.get("site_name", "")
                metadata["civ_name"] = fi.get("civ_name", "")
                metadata["biome"] = fi.get("biome", "")
                metadata["session_id"] = fi.get("session_id", "")

                # Store visitors, animals, buildings in metadata
                metadata["visitors"] = data.get("visitors", [])
                metadata["animals"] = [
                    _load_animal_from_snapshot(a) for a in data.get("animals", [])
                ]
                metadata["buildings"] = data.get("buildings", [])
                metadata["artifacts"] = data.get("artifacts", [])

                # Register citizens
                for citizen in data.get("citizens", []):
                    dwarf = _load_dwarf_from_snapshot(citizen)
                    character_tracker.register_dwarf(dwarf)

                # Store visitors in metadata for context
                metadata["visitors"] = data.get("visitors", [])

                logger.info(
                    "Snapshot loaded: %d citizens, %d visitors",
                    len(data.get("citizens", [])),
                    len(data.get("visitors", [])),
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load snapshot %s: %s", latest_snapshot, e)

        # Apply the most recent delta snapshot (lightweight updates to citizen data).
        # Filter by per-folder session_ids to skip stale deltas.
        deltas = []
        for ed in event_dirs:
            valid_sids = _get_valid_session_ids(ed)
            for delta_path in ed.glob("delta_*.json"):
                if valid_sids:
                    try:
                        with open(delta_path, encoding="utf-8", errors="replace") as f:
                            d = json.load(f)
                        delta_sid = d.get("session_id", "")
                        if delta_sid and delta_sid not in valid_sids:
                            continue
                    except (json.JSONDecodeError, OSError):
                        pass
                deltas.append(delta_path)
        deltas.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if deltas:
            try:
                with open(deltas[0], encoding="utf-8", errors="replace") as f:
                    delta = json.load(f)
                delta_data = delta.get("data", {})
                updated = 0
                for citizen in delta_data.get("citizens", []):
                    uid = citizen.get("unit_id", 0)
                    dwarf = character_tracker.get_dwarf(uid)
                    if dwarf:
                        dwarf.stress_category = citizen.get("stress_category", dwarf.stress_category)
                        dwarf.happiness = citizen.get("happiness", dwarf.happiness)
                        dwarf.current_job = citizen.get("current_job", dwarf.current_job)
                        dwarf.profession = citizen.get("profession", dwarf.profession)
                        dwarf.is_alive = citizen.get("is_alive", dwarf.is_alive)
                        if citizen.get("wounds"):
                            dwarf.wounds = citizen["wounds"]
                        updated += 1
                if updated:
                    metadata["population"] = delta_data.get("population", metadata.get("population", 0))
                    logger.info("Delta snapshot applied: %d citizens updated", updated)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load delta snapshot: %s", e)

    # 2. Load event files from all matching folders.
    # Each folder may have been reused by a different fortress (e.g. "autosave 1"
    # overwritten). Use per-folder session_id from .session_info to filter out
    # stale events that belong to a previous fortress in the same folder.
    if event_dirs:
        # Build a map of valid session_ids per folder directory.
        # Uses session_ids_by_site so reclaimed fortresses keep their old events.
        valid_session_ids: dict[str, set[str]] = {}
        for ed in event_dirs:
            sids = _get_valid_session_ids(ed)
            if not sids:
                # Fallback: session_id from snapshot metadata (primary folder)
                sid = metadata.get("session_id", "")
                sids = {sid} if sid else set()
            valid_session_ids[str(ed)] = sids

        event_files: list[Path] = []
        for ed in event_dirs:
            event_files += list(ed.glob("*.json"))
            proc = ed / "processed"
            if proc.exists():
                event_files += list(proc.glob("*.json"))
        event_files.sort()

        for path in event_files:
            if path.name.startswith("snapshot_") or path.name.startswith("delta_"):
                continue
            # Per-folder session_id check to filter stale events
            folder_key = str(path.parent)
            if folder_key.endswith("processed"):
                folder_key = str(path.parent.parent)
            folder_sids = valid_session_ids.get(folder_key, set())
            if folder_sids:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        raw = json.load(f)
                    event_sid = raw.get("session_id", "")
                    # Skip events from different sessions (keep events without session_id for compat)
                    if event_sid and event_sid not in folder_sids:
                        continue
                except (json.JSONDecodeError, OSError):
                    pass
            event = parse_dfhack_file(path)
            if event:
                idx = event_store.add(event)
                for uid in event_store._extract_unit_ids(event):
                    character_tracker.add_event(uid, event)

    # 3. Gamelog parsing removed — combat, chat, and other events are now captured
    # directly via DFHack hooks (onUnitAttack, onReport) and written as JSON events.
    # See storyteller-events.lua for the event capture implementation.

    # 4. Load legends if available (skip if told to — expensive for large files)
    if skip_legends:
        logger.info("Skipping legends loading (skip_legends=True)")
        event_store.sort_chronologically()
        return event_store, character_tracker, world_lore, metadata

    legends_path = None
    legends_plus_path = None
    if config.paths.legends_xml and Path(config.paths.legends_xml).exists():
        legends_path = Path(config.paths.legends_xml)
    elif config.paths.df_install:
        # Auto-detect: DFHack exportlegends creates files like:
        #   region2-00100-01-01-legends.xml
        #   region2-00100-01-01-legends_plus.xml
        # Filter to the active world's region name so we don't load
        # legends from a different world.
        df_dir = Path(config.paths.df_install)

        # DF legends exports can be named:
        #   region2-00100-01-01-legends.xml (from legends mode)
        #   autosave 1-00100-04-03-legends.xml (from open-legends command)
        # open-legends gives a full export that supersedes previous ones.
        # Always pick the most recently modified files — if you just exported,
        # those are the right ones for your active world.
        plus_candidates = sorted(
            list(df_dir.glob("*-legends_plus.xml")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        basic_candidates = sorted(
            [f for f in df_dir.glob("*-legends.xml") if "legends_plus" not in f.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if plus_candidates:
            legends_plus_path = plus_candidates[0]
            logger.info("Auto-detected legends_plus XML: %s", legends_plus_path)
        if basic_candidates:
            legends_path = basic_candidates[0]
            logger.info("Auto-detected legends XML: %s", legends_path)

    if legends_path or legends_plus_path:
        from df_storyteller.ingestion.legends_parser import parse_legends_xml
        from concurrent.futures import ThreadPoolExecutor, Future

        # Parse both XML files in parallel — they're independent until merge
        legends = None
        legends_plus = None
        with ThreadPoolExecutor(max_workers=2) as executor:
            basic_future: Future | None = None
            plus_future: Future | None = None
            if legends_path:
                basic_future = executor.submit(parse_legends_xml, legends_path)
            if legends_plus_path:
                plus_future = executor.submit(parse_legends_xml, legends_plus_path)
            if basic_future:
                legends = basic_future.result()
            if plus_future:
                legends_plus = plus_future.result()

        # Merge legends_plus into basic — it has richer data (race, type, etc.)
        # Basic legends has: names, birth/death years, events, event collections
        # legends_plus has: race, type, sex, relationships, written contents, etc.
        if legends_plus:
            if legends is None:
                legends = legends_plus
            else:
                # Merge entity race and type from plus into basic
                for eid, plus_civ in legends_plus.civilizations.items():
                    if eid in legends.civilizations:
                        if plus_civ.race:
                            legends.civilizations[eid].race = plus_civ.race
                        # Store entity type as a custom attribute for filtering
                        if hasattr(plus_civ, '_entity_type'):
                            legends.civilizations[eid]._entity_type = plus_civ._entity_type

                # Merge HF data from plus into basic (basic has names, plus has race/type/etc.)
                for hfid, plus_hf in legends_plus.historical_figures.items():
                    if hfid in legends.historical_figures:
                        basic_hf = legends.historical_figures[hfid]
                        if plus_hf.race:
                            basic_hf.race = plus_hf.race
                        if plus_hf.caste:
                            basic_hf.caste = plus_hf.caste
                        if plus_hf.hf_type:
                            basic_hf.hf_type = plus_hf.hf_type
                        if plus_hf.hf_links and not basic_hf.hf_links:
                            basic_hf.hf_links = plus_hf.hf_links
                        if plus_hf.entity_links:
                            basic_hf.entity_links = plus_hf.entity_links
                        if plus_hf.active_interactions:
                            basic_hf.active_interactions = plus_hf.active_interactions
                        if plus_hf.skills:
                            basic_hf.skills = plus_hf.skills
                        if plus_hf.journey_pets:
                            basic_hf.journey_pets = plus_hf.journey_pets
                        if plus_hf.intrigue_plots and not basic_hf.intrigue_plots:
                            basic_hf.intrigue_plots = plus_hf.intrigue_plots
                        if plus_hf.emotional_bonds and not basic_hf.emotional_bonds:
                            basic_hf.emotional_bonds = plus_hf.emotional_bonds
                        if plus_hf.vague_relationships and not basic_hf.vague_relationships:
                            basic_hf.vague_relationships = plus_hf.vague_relationships
                        if plus_hf.former_positions and not basic_hf.former_positions:
                            basic_hf.former_positions = plus_hf.former_positions
                        if plus_hf.notable_deeds and not basic_hf.notable_deeds:
                            basic_hf.notable_deeds = plus_hf.notable_deeds
                    else:
                        legends.historical_figures[hfid] = plus_hf

                # Merge site data from plus
                for sid, plus_site in legends_plus.sites.items():
                    if sid in legends.sites:
                        basic_site = legends.sites[sid]
                        if plus_site.site_type:
                            basic_site.site_type = plus_site.site_type
                        if plus_site.owner_civ_id is not None and basic_site.owner_civ_id is None:
                            basic_site.owner_civ_id = plus_site.owner_civ_id
                        if plus_site.structures and not basic_site.structures:
                            basic_site.structures = plus_site.structures
                        if plus_site.coordinates and not basic_site.coordinates:
                            basic_site.coordinates = plus_site.coordinates
                        if plus_site.properties and not basic_site.properties:
                            basic_site.properties = plus_site.properties
                    else:
                        legends.sites[sid] = plus_site

                # Merge artifact details from plus (plus has type/material, basic has names)
                for aid, plus_art in legends_plus.artifacts.items():
                    if aid in legends.artifacts:
                        basic_art = legends.artifacts[aid]
                        if plus_art.item_type:
                            basic_art.item_type = plus_art.item_type
                        if plus_art.material:
                            basic_art.material = plus_art.material
                        if plus_art.site_id is not None and basic_art.site_id is None:
                            basic_art.site_id = plus_art.site_id
                        if plus_art.description and not basic_art.description:
                            basic_art.description = plus_art.description
                        if plus_art.pages and not basic_art.pages:
                            basic_art.pages = plus_art.pages
                    else:
                        legends.artifacts[aid] = plus_art

                # Copy entity metadata from plus to basic
                for eid, plus_civ in legends_plus.civilizations.items():
                    if eid in legends.civilizations:
                        basic_civ = legends.civilizations[eid]
                        for attr in ('_entity_type', '_child_ids', '_worship_id', '_profession', '_entity_positions', '_occasions', '_honors'):
                            val = getattr(plus_civ, attr, None)
                            if val:
                                setattr(basic_civ, attr, val)
                        if plus_civ.sites and not basic_civ.sites:
                            basic_civ.sites = plus_civ.sites
                        if plus_civ.leader_hf_ids and not basic_civ.leader_hf_ids:
                            basic_civ.leader_hf_ids = plus_civ.leader_hf_ids
                    else:
                        legends.civilizations[eid] = plus_civ

                # Copy extended data lists from plus (these don't exist in basic)
                if legends_plus.relationships:
                    legends.relationships = legends_plus.relationships
                if legends_plus.written_contents:
                    legends.written_contents = legends_plus.written_contents
                if legends_plus.identities:
                    legends.identities = legends_plus.identities
                if legends_plus.world_constructions:
                    legends.world_constructions = legends_plus.world_constructions
                if legends_plus.landmasses:
                    legends.landmasses = legends_plus.landmasses
                if legends_plus.mountain_peaks:
                    legends.mountain_peaks = legends_plus.mountain_peaks
                if legends_plus.rivers:
                    legends.rivers = legends_plus.rivers
                # Merge cultural forms: basic has descriptions, plus has names
                # Merge by index/id so each form gets both name and description
                def _merge_forms(basic_list: list, plus_list: list) -> list:
                    basic_by_id = {f.get("id", str(i)): f for i, f in enumerate(basic_list)}
                    for pf in plus_list:
                        pid = pf.get("id", "")
                        if pid in basic_by_id:
                            basic_by_id[pid].update({k: v for k, v in pf.items() if v})
                        else:
                            basic_by_id[pid] = pf
                    return list(basic_by_id.values())

                if legends_plus.poetic_forms:
                    legends.poetic_forms = _merge_forms(legends.poetic_forms, legends_plus.poetic_forms)
                if legends_plus.musical_forms:
                    legends.musical_forms = _merge_forms(legends.musical_forms, legends_plus.musical_forms)
                if legends_plus.dance_forms:
                    legends.dance_forms = _merge_forms(legends.dance_forms, legends_plus.dance_forms)
                # Merge regions: basic has name/type, plus has coords/evilness
                if legends_plus.regions:
                    legends.regions = _merge_forms(legends.regions, legends_plus.regions)
                if legends_plus.entity_populations:
                    legends.entity_populations = legends_plus.entity_populations

        if legends:
            world_lore.load(legends)

    event_store.sort_chronologically()
    logger.info(
        "Game state loaded: %d events, %d characters tracked",
        event_store.count,
        len(character_tracker._characters),
    )

    return event_store, character_tracker, world_lore, metadata
