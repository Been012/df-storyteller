"""Human-readable descriptions for legends historical events."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from df_storyteller.ingestion.legends_parser import LegendsData


def _resolve_hf(legends: LegendsData, hfid: str | None) -> str:
    """Resolve a historical figure ID to a name, or return 'someone'."""
    if not hfid or hfid == "-1":
        return "someone"
    try:
        hf = legends.get_figure(int(hfid))
        return hf.name if hf and hf.name else f"figure #{hfid}"
    except (ValueError, TypeError):
        return f"figure #{hfid}"


def _resolve_site(legends: LegendsData, site_id: str | None) -> str:
    """Resolve a site ID to a name, or return empty string."""
    if not site_id or site_id == "-1":
        return ""
    try:
        site = legends.get_site(int(site_id))
        return site.name if site else ""
    except (ValueError, TypeError):
        return ""


def _resolve_civ(legends: LegendsData, ent_id: str | None) -> str:
    """Resolve an entity/civ ID to a name, or return empty string."""
    if not ent_id or ent_id == "-1":
        return ""
    try:
        civ = legends.get_civilization(int(ent_id))
        return civ.name if civ else ""
    except (ValueError, TypeError):
        return ""


def _resolve_artifact(legends: LegendsData, art_id: str | None) -> str:
    """Resolve an artifact ID to a name, or return empty string."""
    if not art_id or art_id == "-1":
        return ""
    try:
        art = legends.get_artifact(int(art_id))
        return art.name if art else ""
    except (ValueError, TypeError):
        return ""


def _resolve_position(legends: LegendsData, civ_id: str | None, position_id: str | None) -> str:
    """Resolve a position ID within a civilization to its name (e.g. 'king', 'general')."""
    if not civ_id or not position_id or civ_id == "-1" or position_id == "":
        return ""
    try:
        civ = legends.get_civilization(int(civ_id))
        if civ:
            positions = getattr(civ, '_entity_positions', [])
            for pos in positions:
                if str(pos.get("id", "")) == str(position_id):
                    return pos.get("name", "")
    except (ValueError, TypeError):
        pass
    return ""


def _at_site(legends: LegendsData, event: dict[str, Any]) -> str:
    """Return ' at SiteName' if site_id is present, else ''."""
    site = _resolve_site(legends, event.get("site_id"))
    return f" at {site}" if site else ""


def describe_event(event: dict[str, Any], legends: LegendsData) -> str:
    """Convert a raw historical event dict into a human-readable sentence.

    Covers ~25 common event types with meaningful descriptions.
    Falls back to a formatted type string for unknown types.
    """
    etype = event.get("type", "unknown")
    year = event.get("year", "")
    site_str = _at_site(legends, event)

    match etype:
        case "hf died":
            victim = _resolve_hf(legends, event.get("hfid"))
            slayer = _resolve_hf(legends, event.get("slayer_hfid"))
            cause = event.get("cause", "").replace("_", " ")
            if slayer != "someone":
                return f"{victim} was killed by {slayer}{site_str}"
            if cause:
                return f"{victim} died ({cause}){site_str}"
            return f"{victim} died{site_str}"

        case "hf simple battle event":
            hf1 = _resolve_hf(legends, event.get("group_1_hfid"))
            hf2 = _resolve_hf(legends, event.get("group_2_hfid"))
            return f"{hf1} fought {hf2}{site_str}"

        case "hf wounded":
            victim = _resolve_hf(legends, event.get("woundee_hfid"))
            attacker = _resolve_hf(legends, event.get("wounder_hfid"))
            part = event.get("body_part", "")
            part_str = f" ({part.replace('_', ' ')})" if part else ""
            return f"{attacker} wounded {victim}{part_str}{site_str}"

        case "hf attacked site":
            hf = _resolve_hf(legends, event.get("attacker_hfid"))
            site = _resolve_site(legends, event.get("site_id"))
            civ = _resolve_civ(legends, event.get("defender_civ_id"))
            target = f" ({civ})" if civ else ""
            return f"{hf} attacked {site}{target}" if site else f"{hf} attacked a site"

        case "hf destroyed site":
            hf = _resolve_hf(legends, event.get("attacker_hfid"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{hf} destroyed {site}" if site else f"{hf} destroyed a site"

        case "artifact created":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{hf} created {name}{site_str}"

        case "artifact found" | "artifact recovered":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            verb = "found" if etype == "artifact found" else "recovered"
            return f"{hf} {verb} {name}{site_str}"

        case "artifact given":
            giver = _resolve_hf(legends, event.get("giver_hfid"))
            receiver = _resolve_hf(legends, event.get("receiver_hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{giver} gave {name} to {receiver}{site_str}"

        case "artifact lost" | "artifact destroyed":
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            verb = "was lost" if etype == "artifact lost" else "was destroyed"
            return f"{name} {verb}{site_str}"

        case "artifact stored":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{hf} stored {name}{site_str}"

        case "artifact possessed":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{hf} claimed {name}{site_str}"

        case "change hf state" | "change_hf_state":
            hf = _resolve_hf(legends, event.get("hfid"))
            state = event.get("state", "").replace("_", " ")
            reason = event.get("reason", "").replace("_", " ")
            mood = event.get("mood", "").replace("_", " ")
            parts = []
            if mood:
                parts.append(f"{hf} entered a {mood} mood{site_str}")
            elif state == "settled":
                parts.append(f"{hf} settled{site_str}")
            elif state == "wandering":
                parts.append(f"{hf} began wandering")
            elif state == "visiting":
                parts.append(f"{hf} visited{site_str}")
            elif state == "refugee":
                parts.append(f"{hf} became a refugee{site_str}")
            elif state:
                parts.append(f"{hf} became {state}{site_str}")
            else:
                parts.append(f"{hf} changed state{site_str}")
            if reason:
                parts[0] += f" ({reason})"
            return parts[0]

        case "change hf job" | "change_hf_job":
            hf = _resolve_hf(legends, event.get("hfid"))
            new_job = event.get("new_job", "").replace("_", " ")
            old_job = event.get("old_job", "").replace("_", " ")
            if new_job and old_job:
                return f"{hf} changed profession from {old_job} to {new_job}{site_str}"
            if new_job:
                return f"{hf} became a {new_job}{site_str}"
            return f"{hf} changed profession{site_str}"

        case "add hf entity link" | "add_hf_entity_link":
            hf = _resolve_hf(legends, event.get("hfid"))
            civ = _resolve_civ(legends, event.get("civ_id"))
            link = event.get("link", event.get("link_type", "")).replace("_", " ")
            position_id = event.get("position_id", "")
            # Resolve position name from civilization's entity_position data
            position_name = _resolve_position(legends, event.get("civ_id"), position_id)
            if link == "position" and position_name and civ:
                return f"{hf} became {position_name} of {civ}"
            if link == "position" and civ:
                return f"{hf} gained a position in {civ}"
            if link == "member" and civ:
                return f"{hf} became a member of {civ}"
            if link == "enemy" and civ:
                return f"{hf} became an enemy of {civ}"
            if link == "prisoner" and civ:
                return f"{hf} was imprisoned by {civ}"
            if link == "slave" and civ:
                return f"{hf} was enslaved by {civ}"
            if civ and link:
                return f"{hf} became {link} of {civ}"
            if civ:
                return f"{hf} joined {civ}"
            return f"{hf} gained a position"

        case "remove hf entity link" | "remove_hf_entity_link":
            hf = _resolve_hf(legends, event.get("hfid"))
            civ = _resolve_civ(legends, event.get("civ_id"))
            link = event.get("link", event.get("link_type", "")).replace("_", " ")
            position_id = event.get("position_id", "")
            position_name = _resolve_position(legends, event.get("civ_id"), position_id)
            if link == "position" and position_name and civ:
                return f"{hf} was removed as {position_name} of {civ}"
            if link == "position" and civ:
                return f"{hf} lost a position in {civ}"
            if link == "member" and civ:
                return f"{hf} left {civ}"
            if link == "enemy" and civ:
                return f"{hf} is no longer an enemy of {civ}"
            if link == "prisoner" and civ:
                return f"{hf} was freed from {civ}"
            if link == "slave" and civ:
                return f"{hf} was freed from slavery by {civ}"
            if civ and link:
                return f"{hf} was removed as {link} of {civ}"
            if civ:
                return f"{hf} left {civ}"
            return f"{hf} lost a position"

        case "assume identity" | "assume_identity":
            hf = _resolve_hf(legends, event.get("trickster_hfid"))
            target = _resolve_hf(legends, event.get("identity_hfid"))
            return f"{hf} assumed the identity of {target}{site_str}"

        case "creature devoured":
            eater = _resolve_hf(legends, event.get("eater_hfid"))
            victim = _resolve_hf(legends, event.get("victim_hfid"))
            return f"{eater} devoured {victim}{site_str}"

        case "item stolen":
            thief = _resolve_hf(legends, event.get("histfig"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{thief} stole an item from {site}" if site else f"{thief} stole an item"

        case "hf confronted":
            hf = _resolve_hf(legends, event.get("hfid"))
            situation = event.get("situation", "").replace("_", " ")
            return f"{hf} was confronted ({situation}){site_str}" if situation else f"{hf} was confronted{site_str}"

        case "hf new pet":
            hf = _resolve_hf(legends, event.get("group_hfid"))
            pet = event.get("pets", "a creature").replace("_", " ")
            return f"{hf} tamed {pet}{site_str}"

        case "hf razed structure" | "hf_razed_structure":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} razed a structure{site_str}"

        case "created site":
            civ = _resolve_civ(legends, event.get("civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            if civ and site:
                return f"{civ} founded {site}"
            return f"A site was founded{site_str}"

        case "destroyed site":
            civ = _resolve_civ(legends, event.get("attacker_civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            defender = _resolve_civ(legends, event.get("defender_civ_id"))
            if civ and site:
                return f"{civ} destroyed {site}" + (f" ({defender})" if defender else "")
            return f"A site was destroyed"

        case "hf learns secret" | "hf_learns_secret":
            hf = _resolve_hf(legends, event.get("student_hfid"))
            secret = event.get("secret_text", "").replace("_", " ")
            teacher = _resolve_hf(legends, event.get("teacher_hfid"))
            if secret:
                return f"{hf} learned the secrets of {secret}"
            return f"{hf} learned a secret"

        case "masterpiece created item" | "masterpiece_created_item":
            hf = _resolve_hf(legends, event.get("hfid"))
            item = event.get("item_type", "").replace("_", " ")
            mat = event.get("mat", "").replace("_", " ")
            if item:
                desc = f"{mat} {item}".strip() if mat else item
                return f"{hf} created a masterwork {desc}{site_str}"
            return f"{hf} created a masterwork{site_str}"

        case "peace accepted":
            return f"Peace was accepted{site_str}"

        case "peace rejected":
            return f"Peace was rejected{site_str}"

        case "site dispute":
            site = _resolve_site(legends, event.get("site_id"))
            dispute = event.get("dispute", "").replace("_", " ")
            return f"A dispute arose over {site} ({dispute})" if site else f"A site dispute occurred"

        case "hf travel":
            hf = _resolve_hf(legends, event.get("group_hfid"))
            return f"{hf} traveled{site_str}"

        case "hf abducted":
            target = _resolve_hf(legends, event.get("target_hfid"))
            snatcher = _resolve_hf(legends, event.get("snatcher_hfid"))
            return f"{target} was abducted by {snatcher}{site_str}"

        case "hf revived":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} was raised from the dead{site_str}"

        case "created structure":
            civ = _resolve_civ(legends, event.get("civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} built a structure in {site}" if civ and site else f"A structure was built{site_str}"

        case "razed structure":
            civ = _resolve_civ(legends, event.get("civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} razed a structure in {site}" if civ and site else f"A structure was razed{site_str}"

        case "entity created":
            civ = _resolve_civ(legends, event.get("entity_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} was founded" + (f" in {site}" if site else "")

        case "hf does interaction":
            doer = _resolve_hf(legends, event.get("doer_hfid"))
            target = _resolve_hf(legends, event.get("target_hfid"))
            interaction = event.get("interaction_action", "").replace("_", " ").lower()
            if interaction:
                return f"{doer} {interaction} {target}{site_str}"
            return f"{doer} performed an interaction on {target}{site_str}"

        case "written content composed":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} composed a written work{site_str}"

        case "knowledge discovered":
            hf = _resolve_hf(legends, event.get("hfid"))
            knowledge = event.get("knowledge", "").replace("_", " ").replace(":", ": ")
            if knowledge:
                return f"{hf} discovered knowledge of {knowledge}"
            return f"{hf} made a discovery"

        case "insurrection started":
            civ = _resolve_civ(legends, event.get("target_civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            if civ and site:
                return f"An insurrection started against {civ} in {site}"
            return f"An insurrection started{site_str}"

        case "field battle":
            attacker = _resolve_civ(legends, event.get("attacker_civ_id"))
            defender = _resolve_civ(legends, event.get("defender_civ_id"))
            if attacker and defender:
                return f"{attacker} fought {defender} in a field battle{site_str}"
            return f"A field battle occurred{site_str}"

        case "body abused":
            hf = _resolve_hf(legends, event.get("hfid"))
            abuser = _resolve_hf(legends, event.get("abuser_hfid"))
            abuse_type = event.get("abuse_type", "").replace("_", " ")
            if abuse_type:
                return f"The body of {hf} was {abuse_type}{site_str}"
            return f"The body of {hf} was abused{site_str}"

        case "add hf hf link" | "add_hf_hf_link":
            hf1 = _resolve_hf(legends, event.get("hfid"))
            hf2 = _resolve_hf(legends, event.get("hfid_target"))
            link_type = event.get("link_type", "").replace("_", " ")
            if link_type and hf2 != "someone":
                return f"{hf1} became {link_type} of {hf2}"
            return f"{hf1} formed a bond with {hf2}"

        case "remove hf hf link" | "remove_hf_hf_link":
            hf1 = _resolve_hf(legends, event.get("hfid"))
            hf2 = _resolve_hf(legends, event.get("hfid_target"))
            link_type = event.get("link_type", "").replace("_", " ")
            if link_type and hf2 != "someone":
                return f"{hf1} is no longer {link_type} of {hf2}"
            return f"{hf1} severed a bond with {hf2}"

        case "hfs formed reputation relationship":
            hf1 = _resolve_hf(legends, event.get("hfid1"))
            hf2 = _resolve_hf(legends, event.get("hfid2"))
            rep = event.get("rep_1_of_2", event.get("identity_rep", "")).replace("_", " ")
            if rep:
                return f"{hf1} gained a reputation as {rep} with {hf2}"
            return f"{hf1} formed a reputation with {hf2}"

        case "hfs formed intrigue relationship":
            hf1 = _resolve_hf(legends, event.get("corruptor_hfid"))
            hf2 = _resolve_hf(legends, event.get("target_hfid"))
            action = event.get("action", "").replace("_", " ")
            method = event.get("method", "").replace("_", " ")
            if action:
                return f"{hf1} {action} {hf2}{site_str}"
            return f"{hf1} formed an intrigue with {hf2}{site_str}"

        case "hf relationship denied":
            hf1 = _resolve_hf(legends, event.get("seeker_hfid"))
            hf2 = _resolve_hf(legends, event.get("target_hfid"))
            relationship = event.get("relationship", "").replace("_", " ")
            reason = event.get("reason", "").replace("_", " ")
            if relationship:
                return f"{hf1} was denied a {relationship} with {hf2}" + (f" ({reason})" if reason else "")
            return f"{hf1} was rejected by {hf2}"

        case "changed creature type":
            hf = _resolve_hf(legends, event.get("changee_hfid"))
            changer = _resolve_hf(legends, event.get("changer_hfid"))
            old_race = event.get("old_race", "").replace("_", " ").title()
            new_race = event.get("new_race", "").replace("_", " ").title()
            if old_race and new_race:
                if changer != "someone":
                    return f"{hf} was transformed from {old_race} to {new_race} by {changer}"
                return f"{hf} was transformed from {old_race} to {new_race}"
            return f"{hf} underwent a transformation"

        case "hf convicted":
            hf = _resolve_hf(legends, event.get("convicted_hfid"))
            convict_civ = _resolve_civ(legends, event.get("convict_civ_id"))
            crime = event.get("crime", "").replace("_", " ")
            if crime and convict_civ:
                return f"{hf} was convicted of {crime} by {convict_civ}{site_str}"
            if crime:
                return f"{hf} was convicted of {crime}{site_str}"
            return f"{hf} was convicted{site_str}"

        case "entity persecuted":
            persecutor = _resolve_civ(legends, event.get("persecutor_enid"))
            target = _resolve_civ(legends, event.get("target_enid"))
            site = _resolve_site(legends, event.get("site_id"))
            if persecutor and target:
                return f"{persecutor} persecuted {target}" + (f" at {site}" if site else "")
            return f"A persecution occurred{site_str}"

        case "agreement formed":
            return f"An agreement was formed{site_str}"

        case "hf recruited unit type for entity":
            hf = _resolve_hf(legends, event.get("hfid"))
            civ = _resolve_civ(legends, event.get("entity_id"))
            unit_type = event.get("unit_type", "").replace("_", " ")
            if unit_type and civ:
                return f"{hf} recruited {unit_type} for {civ}{site_str}"
            return f"{hf} recruited units{site_str}"

        case "hf preach":
            hf = _resolve_hf(legends, event.get("speaker_hfid"))
            civ = _resolve_civ(legends, event.get("entity_id"))
            topic = event.get("topic", "").replace("_", " ")
            if topic and civ:
                return f"{hf} preached {topic} for {civ}{site_str}"
            return f"{hf} preached{site_str}"

        case "hf prayed inside structure":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} prayed inside a structure{site_str}"

        case "competition":
            civ = _resolve_civ(legends, event.get("civ_id"))
            return f"A competition was held{site_str}" + (f" by {civ}" if civ else "")

        case "ceremony":
            civ = _resolve_civ(legends, event.get("civ_id"))
            return f"A ceremony was held{site_str}" + (f" by {civ}" if civ else "")

        case "performance":
            civ = _resolve_civ(legends, event.get("civ_id"))
            return f"A performance was held{site_str}" + (f" by {civ}" if civ else "")

        case "procession":
            civ = _resolve_civ(legends, event.get("civ_id"))
            return f"A procession was held{site_str}" + (f" by {civ}" if civ else "")

        case "trade":
            return f"Trade occurred{site_str}"

        case "gamble":
            hf = _resolve_hf(legends, event.get("gambler_hfid"))
            return f"{hf} gambled{site_str}"

        case "artifact copied":
            hf = _resolve_hf(legends, event.get("dest_entity_id"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{name} was copied{site_str}"

        case "artifact claim formed":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            claim = event.get("claim", "").replace("_", " ")
            name = art if art else "an artifact"
            if claim:
                return f"{hf} formed a {claim} claim on {name}"
            return f"{hf} claimed {name}"

        case "hf gains secret goal":
            hf = _resolve_hf(legends, event.get("hfid"))
            goal = event.get("secret_goal", "").replace("_", " ")
            if goal:
                return f"{hf} gained the secret goal of {goal}"
            return f"{hf} gained a secret goal"

        case "create entity position":
            civ = _resolve_civ(legends, event.get("civ_id"))
            position = event.get("position", "").replace("_", " ")
            if position and civ:
                return f"The position of {position} was created in {civ}"
            return f"A new position was created{site_str}"

        case "failed intrigue corruption":
            corruptor = _resolve_hf(legends, event.get("corruptor_hfid"))
            target = _resolve_hf(legends, event.get("target_hfid"))
            return f"{corruptor} failed to corrupt {target}{site_str}"

        case "failed frame attempt":
            framer = _resolve_hf(legends, event.get("framer_hfid"))
            target = _resolve_hf(legends, event.get("target_hfid"))
            crime = event.get("crime", "").replace("_", " ")
            if crime:
                return f"{framer} failed to frame {target} for {crime}{site_str}"
            return f"{framer} failed to frame {target}{site_str}"

        case "hf equipment purchase" | "entity equipment purchase":
            hf = _resolve_hf(legends, event.get("group_hfid"))
            return f"{hf} purchased equipment{site_str}"

        case "add hf site link" | "add_hf_site_link":
            hf = _resolve_hf(legends, event.get("hfid"))
            site = _resolve_site(legends, event.get("site_id"))
            link_type = event.get("link_type", "").replace("_", " ")
            if link_type and site:
                return f"{hf} became {link_type} of {site}"
            return f"{hf} linked to a site{site_str}"

        case "remove hf site link" | "remove_hf_site_link":
            hf = _resolve_hf(legends, event.get("hfid"))
            site = _resolve_site(legends, event.get("site_id"))
            link_type = event.get("link_type", "").replace("_", " ")
            if link_type and site:
                return f"{hf} is no longer {link_type} of {site}"
            return f"{hf} left a site{site_str}"

        case "hf viewed artifact":
            hf = _resolve_hf(legends, event.get("hfid"))
            art = _resolve_artifact(legends, event.get("artifact_id"))
            name = art if art else "an artifact"
            return f"{hf} viewed {name}{site_str}"

        case "hf profaned structure":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} profaned a structure{site_str}"

        case "hf disturbed structure":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} disturbed a structure{site_str}"

        case "hf performed horrible experiments":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} performed horrible experiments{site_str}"

        case "hf reunion":
            hf1 = _resolve_hf(legends, event.get("group_1_hfid"))
            hf2 = _resolve_hf(legends, event.get("group_2_hfid"))
            return f"{hf1} was reunited with {hf2}{site_str}"

        case "attacked site":
            attacker = _resolve_civ(legends, event.get("attacker_civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            defender = _resolve_civ(legends, event.get("defender_civ_id"))
            if attacker and site:
                return f"{attacker} attacked {site}" + (f" ({defender})" if defender else "")
            return f"A site was attacked{site_str}"

        case "plundered site":
            attacker = _resolve_civ(legends, event.get("attacker_civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            defender = _resolve_civ(legends, event.get("defender_civ_id"))
            if attacker and site:
                return f"{attacker} plundered {site}" + (f" ({defender})" if defender else "")
            return f"A site was plundered{site_str}"

        case "site taken over":
            attacker = _resolve_civ(legends, event.get("attacker_civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{attacker} took over {site}" if attacker and site else f"A site was taken over{site_str}"

        case "reclaim site":
            civ = _resolve_civ(legends, event.get("civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} reclaimed {site}" if civ and site else f"A site was reclaimed{site_str}"

        case "new site leader":
            hf = _resolve_hf(legends, event.get("hfid"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{hf} became the leader of {site}" if site else f"{hf} became a site leader"

        case "entity dissolved":
            civ = _resolve_civ(legends, event.get("entity_id"))
            return f"{civ} was dissolved" if civ else "An entity was dissolved"

        case "entity alliance formed":
            return f"An alliance was formed{site_str}"

        case "entity incorporated":
            joiner = _resolve_civ(legends, event.get("joined_entity_id"))
            target = _resolve_civ(legends, event.get("joining_entity_id"))
            if joiner and target:
                return f"{target} was incorporated into {joiner}"
            return f"An entity was incorporated"

        case "entity relocate":
            civ = _resolve_civ(legends, event.get("entity_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} relocated to {site}" if civ and site else f"An entity relocated{site_str}"

        case "entity overthrown":
            civ = _resolve_civ(legends, event.get("entity_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} was overthrown" + (f" at {site}" if site else "")

        case "entity primary criminals":
            civ = _resolve_civ(legends, event.get("entity_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} became the primary criminals" + (f" of {site}" if site else "")

        case "holy city declaration":
            civ = _resolve_civ(legends, event.get("entity_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} declared {site} a holy city" if civ and site else f"A holy city was declared{site_str}"

        case "hf enslaved":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} was enslaved{site_str}"

        case "hf interrogated":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} was interrogated{site_str}"

        case "change hf body state" | "change_hf_body_state":
            hf = _resolve_hf(legends, event.get("hfid"))
            state = event.get("body_state", "").replace("_", " ")
            if state:
                return f"The remains of {hf} became {state}{site_str}"
            return f"The remains of {hf} changed state{site_str}"

        case "modified building":
            site = _resolve_site(legends, event.get("site_id"))
            return f"A building was modified" + (f" at {site}" if site else "")

        case "replaced structure":
            site = _resolve_site(legends, event.get("site_id"))
            return f"A structure was replaced" + (f" at {site}" if site else "")

        case "created world construction":
            civ = _resolve_civ(legends, event.get("civ_id"))
            name = event.get("name", "").replace("_", " ")
            wc_type = event.get("type", event.get("construction_type", "")).replace("_", " ")
            if name:
                return f"{civ} built {name}" if civ else f"{name} was built"
            if wc_type:
                return f"A {wc_type} was built{site_str}"
            return f"A construction was built{site_str}"

        case "regionpop incorporated into entity":
            civ = _resolve_civ(legends, event.get("join_entity_id"))
            return f"A population was incorporated into {civ}" if civ else f"A population was incorporated"

        case "add hf entity honor":
            hf = _resolve_hf(legends, event.get("hfid"))
            civ = _resolve_civ(legends, event.get("entity_id"))
            return f"{hf} was honored by {civ}" if civ else f"{hf} received an honor"

        case "musical form created":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} created a new musical form{site_str}"

        case "poetic form created":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} created a new poetic form{site_str}"

        case "dance form created":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} created a new dance form{site_str}"

        case "building profile acquired":
            hf = _resolve_hf(legends, event.get("hfid"))
            return f"{hf} acquired a building profile{site_str}"

        case "entity breach feature layer":
            civ = _resolve_civ(legends, event.get("civ_id"))
            site = _resolve_site(legends, event.get("site_id"))
            return f"{civ} breached a feature layer" + (f" at {site}" if site else "")

        case _:
            # Fallback: format the type nicely and include any resolvable names
            readable = etype.replace("_", " ").replace("hf ", "").title()
            hf = _resolve_hf(legends, event.get("hfid"))
            if hf != "someone":
                return f"{readable}: {hf}{site_str}"
            return f"{readable}{site_str}"


def describe_event_html(event: dict[str, Any], legends: LegendsData) -> str:
    """Like describe_event but wraps entity names in lore-link anchors."""
    # For now, return plain text — HTML linking will be added in Phase 1c
    return describe_event(event, legends)
