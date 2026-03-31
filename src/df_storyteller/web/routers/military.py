"""Military dashboard routes."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    base_context as _base_context,
    SEASON_ORDER_MAP,
)
from df_storyteller.web.templates_setup import templates

logger = logging.getLogger(__name__)

router = APIRouter()

COMBAT_SKILL_KEYWORDS = {
    "axe", "sword", "spear", "mace", "hammer", "crossbow", "shield",
    "dodge", "wrestling", "armor", "melee", "striker", "kicker", "biter",
}


def _is_combat_skill(skill_name: str) -> bool:
    lower = skill_name.lower()
    return any(kw in lower for kw in COMBAT_SKILL_KEYWORDS)


def _season_sort_key(year: int, season: str) -> tuple[int, int]:
    return (year, SEASON_ORDER_MAP.get(season, 0))


@router.get("/military", response_class=HTMLResponse)
async def military_page(request: Request):
    config = _get_config()
    event_store, character_tracker, _, metadata = _load_game_state_safe(config)
    ctx = _base_context(config, "military", metadata)

    from df_storyteller.schema.events import EventType as ET
    from df_storyteller.context.narrative_formatter import _skill_level_name, _resolve_skill_name

    ranked = character_tracker.ranked_characters()

    # --- A. Squad roster ---
    squads: dict[str, list[dict]] = defaultdict(list)
    all_soldiers: list[dict] = []
    unassigned_fighters: list[dict] = []

    for dwarf, _score in ranked:
        combat_skills = []
        for s in dwarf.skills:
            resolved = _resolve_skill_name(s.name)
            if _is_combat_skill(resolved):
                level_num = int(s.level) if str(s.level).isdigit() else 0
                combat_skills.append({
                    "name": resolved,
                    "level": _skill_level_name(level_num),
                    "level_num": level_num,
                })
        combat_skills.sort(key=lambda x: x["level_num"], reverse=True)

        member_data = {
            "unit_id": dwarf.unit_id,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "combat_skills": combat_skills,
            "equipment": dwarf.equipment,
            "wounds": dwarf.wounds,
        }

        if dwarf.military_squad:
            squads[dwarf.military_squad].append(member_data)
            all_soldiers.append(member_data)
        elif combat_skills:
            unassigned_fighters.append(member_data)

    # Mark squad leaders (position 0 = first member added per squad)
    squad_list = []
    for squad_name, members in sorted(squads.items()):
        for i, m in enumerate(members):
            m["is_leader"] = (i == 0)
        squad_list.append({"name": squad_name, "members": members})

    # --- B. Combat stats per dwarf ---
    # Build name→unit_id mapping so we can attribute gamelog events (unit_id=0)
    # to real dwarves by matching on name or title.
    name_to_uid: dict[str, int] = {}
    for dwarf, _ in ranked:
        short = dwarf.name.split(",")[0].strip()
        name_to_uid[short.lower()] = dwarf.unit_id
        name_to_uid[dwarf.name.lower()] = dwarf.unit_id
        # Also map by profession/title (e.g. "recruit", "militia commander")
        if dwarf.profession:
            # Only map title if it's unique — multiple "recruit"s would collide
            title_key = dwarf.profession.lower()
            if title_key not in name_to_uid:
                name_to_uid[title_key] = dwarf.unit_id

    def _resolve_uid(unit_ref: object) -> int:
        """Resolve a combat participant to a unit_id, falling back to name match."""
        uid = getattr(unit_ref, "unit_id", 0)
        if uid:
            return uid
        name = getattr(unit_ref, "name", "")
        if name:
            return name_to_uid.get(name.lower(), 0)
        return 0

    attack_counts: Counter[int] = Counter()
    defense_counts: Counter[int] = Counter()
    kill_counts: Counter[int] = Counter()

    for e in event_store.events_by_type(ET.COMBAT):
        d = e.data
        if hasattr(d, "attacker"):
            uid = _resolve_uid(d.attacker)
            if uid:
                attack_counts[uid] += 1
        if hasattr(d, "defender"):
            uid = _resolve_uid(d.defender)
            if uid:
                defense_counts[uid] += 1

    for e in event_store.events_by_type(ET.DEATH):
        d = e.data
        if hasattr(d, "killer") and d.killer:
            uid = _resolve_uid(d.killer)
            if uid:
                kill_counts[uid] += 1

    # Build leaderboard: all dwarves with any combat involvement
    warrior_ids = set(attack_counts.keys()) | set(defense_counts.keys()) | set(kill_counts.keys())
    # Filter out unit_id=0 (unresolved) and non-fortress units (animals etc.)
    warrior_ids.discard(0)
    leaderboard: list[dict] = []
    for uid in warrior_ids:
        dwarf = character_tracker.get_dwarf(uid)
        if not dwarf:
            continue  # Skip non-fortress units (animals, invaders)
        leaderboard.append({
            "unit_id": uid,
            "name": dwarf.name,
            "profession": dwarf.profession,
            "is_alive": dwarf.is_alive,
            "kills": kill_counts.get(uid, 0),
            "attacks": attack_counts.get(uid, 0),
            "defenses": defense_counts.get(uid, 0),
            "total_combat": attack_counts.get(uid, 0) + defense_counts.get(uid, 0),
        })
    # Sort by kills desc, then total combat desc
    leaderboard.sort(key=lambda w: (w["kills"], w["total_combat"]), reverse=True)
    top_warriors = leaderboard[:10]

    # --- C. Recent engagements ---
    TICK_THRESHOLD = config.web.combat_tick_threshold
    all_combat = list(event_store.events_by_type(ET.COMBAT))
    # Sort by tick for grouping
    all_combat.sort(key=lambda e: e.game_tick)

    engagement_groups: list[list] = []
    current_group: list = []
    for event in all_combat:
        if current_group and abs(event.game_tick - current_group[-1].game_tick) > TICK_THRESHOLD:
            engagement_groups.append(current_group)
            current_group = []
        current_group.append(event)
    if current_group:
        engagement_groups.append(current_group)

    # Build recent engagements (newest first), last 10.
    # Group fights by target (animal/enemy) within each engagement.
    recent_engagements: list[dict] = []
    for group in reversed(engagement_groups):
        fortress_fighters: set[str] = set()
        enemies: set[str] = set()
        total_blows = 0
        casualties = 0
        # Track fights by target for breakdown
        target_fights: dict[str, dict] = defaultdict(lambda: {
            "blows": 0, "fights": 0, "attackers": set(), "defeated": False,
        })

        for event in group:
            d = event.data
            att_name = getattr(d.attacker, "name", "Unknown") if hasattr(d, "attacker") else "Unknown"
            def_name = getattr(d.defender, "name", "Unknown") if hasattr(d, "defender") else "Unknown"
            att_uid = _resolve_uid(d.attacker) if hasattr(d, "attacker") else 0
            def_uid = _resolve_uid(d.defender) if hasattr(d, "defender") else 0
            blow_count = getattr(d, "blow_count", 0) or (len(d.blows) if hasattr(d, "blows") else 0)
            total_blows += blow_count

            # Classify as fortress dwarf or enemy
            att_is_ours = att_uid and character_tracker.get_dwarf(att_uid) is not None
            def_is_ours = def_uid and character_tracker.get_dwarf(def_uid) is not None

            if att_is_ours:
                fortress_fighters.add(att_name)
                # Defender is the enemy/target
                if def_name and def_name != "Unknown":
                    enemies.add(def_name)
                    target_fights[def_name]["blows"] += blow_count
                    target_fights[def_name]["fights"] += 1
                    target_fights[def_name]["attackers"].add(att_name)
            elif def_is_ours:
                fortress_fighters.add(def_name)
                if att_name and att_name != "Unknown":
                    enemies.add(att_name)
            else:
                # Neither resolved — add both as participants
                if att_name != "Unknown":
                    enemies.add(att_name)
                if def_name != "Unknown":
                    enemies.add(def_name)

            if getattr(d, "is_lethal", False):
                casualties += 1
            # Check outcome text for defeat indicators
            outcome = getattr(d, "outcome", "")
            if outcome and any(w in outcome.lower() for w in ("gives in", "knocked unconscious", "explodes")):
                if def_name in target_fights:
                    target_fights[def_name]["defeated"] = True

        # Convert target sets for JSON
        targets = []
        for tname, tdata in sorted(target_fights.items(), key=lambda x: x[1]["blows"], reverse=True):
            targets.append({
                "name": tname,
                "blows": tdata["blows"],
                "fights": tdata["fights"],
                "attackers": sorted(tdata["attackers"]),
                "defeated": tdata["defeated"],
            })

        recent_engagements.append({
            "season": group[0].season.value.title(),
            "year": group[0].game_year,
            "date_label": f"{group[0].day} {group[0].month_name}" if group[0].month_name and group[0].day else group[0].season.value.title(),
            "fortress_fighters": sorted(fortress_fighters),
            "enemies": sorted(enemies),
            "targets": targets,
            "blow_count": total_blows,
            "fight_count": len(group),
            "casualties": casualties,
        })
        if len(recent_engagements) >= 10:
            break

    # --- D. Military events timeline ---
    military_timeline: list[dict] = []
    for e in event_store.events_by_type(ET.MILITARY_CHANGE):
        d = e.data
        if isinstance(d, dict):
            unit_name = d.get("unit", {}).get("name", "Unknown")
            squad = d.get("squad_name", "")
        else:
            unit_name = d.unit.name if hasattr(d, "unit") else "Unknown"
            squad = getattr(d, "squad_name", "")
        military_timeline.append({
            "type": "military_change",
            "season": e.season.value.title(),
            "year": e.game_year,
            "description": f"{unit_name} assigned to {squad}" if squad else f"{unit_name} military status changed",
            "_sort": _season_sort_key(e.game_year, e.season.value),
        })

    from df_storyteller.schema.events import SiegeData
    for e in event_store.events_by_type(ET.SIEGE):
        d = e.data
        if isinstance(d, SiegeData):
            if d.status == "started":
                desc = f"Siege! {d.invader_count} {d.invader_race.replace('_', ' ').title() if d.invader_race else 'unknown'} invaders from {d.civilization or 'unknown'}"
            else:
                desc = "Siege ended"
        else:
            desc = "Siege event"
        military_timeline.append({
            "type": "siege",
            "season": e.season.value.title(),
            "year": e.game_year,
            "description": desc,
            "_sort": _season_sort_key(e.game_year, e.season.value),
        })

    military_timeline.sort(key=lambda x: x["_sort"])
    for item in military_timeline:
        del item["_sort"]

    # --- E. Chart data ---
    combat_by_season: Counter[tuple[int, str]] = Counter()
    for e in event_store.events_by_type(ET.COMBAT):
        combat_by_season[(e.game_year, e.season.value)] += 1
    combat_series = [
        {"label": f"{s.title()} Y{y}", "value": c}
        for (y, s), c in sorted(combat_by_season.items(), key=lambda x: _season_sort_key(*x[0]))
    ]

    kills_by_season: Counter[tuple[int, str]] = Counter()
    for e in event_store.events_by_type(ET.DEATH):
        d = e.data
        if hasattr(d, "killer") and d.killer and d.killer.unit_id:
            kills_by_season[(e.game_year, e.season.value)] += 1
    kills_series = [
        {"label": f"{s.title()} Y{y}", "value": c}
        for (y, s), c in sorted(kills_by_season.items(), key=lambda x: _season_sort_key(*x[0]))
    ]

    # --- F. Summary stats ---
    total_kills = sum(kill_counts.values())
    total_casualties = len(event_store.events_by_type(ET.DEATH))
    total_battles = len(engagement_groups)
    total_sieges = sum(
        1 for e in event_store.events_by_type(ET.SIEGE)
        if isinstance(e.data, SiegeData) and e.data.status == "started"
    )

    summary = {
        "total_soldiers": len(all_soldiers),
        "total_squads": len(squad_list),
        "total_kills": total_kills,
        "total_battles": total_battles,
        "total_casualties": total_casualties,
        "total_sieges": total_sieges,
    }

    military = {
        "summary": summary,
        "squads": squad_list,
        "top_warriors": top_warriors,
        "combat_series": combat_series,
        "kills_series": kills_series,
        "recent_engagements": recent_engagements,
        "military_timeline": military_timeline,
        "unassigned_fighters": unassigned_fighters,
    }

    return templates.TemplateResponse(request=request, name="military.html", context={
        **ctx, "content_class": "content-wide", "military": military,
    })
