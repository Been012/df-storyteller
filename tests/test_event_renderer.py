"""Tests for the event renderer — converts raw legends event dicts to prose.

Covers the most common event types plus resolution helpers and linked mode.
"""

from __future__ import annotations

import pytest

from df_storyteller.context.event_renderer import (
    describe_event,
    describe_event_linked,
    _resolve_hf,
    _resolve_site,
    _resolve_civ,
    _resolve_artifact,
    _at_site,
)
from df_storyteller.ingestion.legends_parser import LegendsData
from df_storyteller.schema.entities import (
    Artifact,
    Civilization,
    HistoricalFigure,
    Site,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def legends():
    """Minimal LegendsData with a few entities for resolution testing."""
    ld = LegendsData()
    ld.historical_figures = {
        1: HistoricalFigure(hf_id=1, name="Urist McHero"),
        2: HistoricalFigure(hf_id=2, name="Goblin Bonecrusher"),
        3: HistoricalFigure(hf_id=3, name="Elf Treewalker"),
    }
    ld.sites = {
        10: Site(site_id=10, name="Mountainhome"),
        11: Site(site_id=11, name="Dark Fortress"),
    }
    ld.civilizations = {
        5: Civilization(entity_id=5, name="The Dwarven Realm"),
        6: Civilization(entity_id=6, name="The Goblin Horde"),
    }
    ld.artifacts = {
        20: Artifact(artifact_id=20, name="The Axe of Legends"),
    }
    ld.identities = [
        {"id": "50", "name": "Shadow the Thief"},
    ]
    return ld


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


class TestResolutionHelpers:
    """Test the _resolve_* functions that convert IDs to names."""

    def test_resolve_hf_found(self, legends):
        assert _resolve_hf(legends, "1") == "Urist McHero"

    def test_resolve_hf_not_found(self, legends):
        assert _resolve_hf(legends, "999") == "figure #999"

    def test_resolve_hf_none(self, legends):
        assert _resolve_hf(legends, None) == "someone"

    def test_resolve_hf_negative_one(self, legends):
        assert _resolve_hf(legends, "-1") == "someone"

    def test_resolve_hf_invalid_string(self, legends):
        assert _resolve_hf(legends, "not_a_number") == "figure #not_a_number"

    def test_resolve_site_found(self, legends):
        assert _resolve_site(legends, "10") == "Mountainhome"

    def test_resolve_site_not_found(self, legends):
        assert _resolve_site(legends, "999") == ""

    def test_resolve_site_none(self, legends):
        assert _resolve_site(legends, None) == ""

    def test_resolve_civ_found(self, legends):
        assert _resolve_civ(legends, "5") == "The Dwarven Realm"

    def test_resolve_civ_not_found(self, legends):
        assert _resolve_civ(legends, "999") == ""

    def test_resolve_artifact_found(self, legends):
        assert _resolve_artifact(legends, "20") == "The Axe of Legends"

    def test_resolve_artifact_not_found(self, legends):
        assert _resolve_artifact(legends, "999") == ""

    def test_at_site_with_site(self, legends):
        event = {"site_id": "10"}
        assert _at_site(legends, event) == " at Mountainhome"

    def test_at_site_without_site(self, legends):
        event = {}
        assert _at_site(legends, event) == ""

    def test_at_site_unknown_site(self, legends):
        event = {"site_id": "999"}
        assert _at_site(legends, event) == ""


# ---------------------------------------------------------------------------
# describe_event — death events
# ---------------------------------------------------------------------------


class TestDeathEvents:
    """hf died event type."""

    def test_death_with_slayer(self, legends):
        event = {"type": "hf died", "hfid": "1", "slayer_hfid": "2", "site_id": "10"}
        result = describe_event(event, legends)
        assert "Urist McHero" in result
        assert "killed by" in result
        assert "Goblin Bonecrusher" in result
        assert "Mountainhome" in result

    def test_death_with_cause(self, legends):
        event = {"type": "hf died", "hfid": "1", "cause": "old_age"}
        result = describe_event(event, legends)
        assert "died" in result
        assert "old age" in result  # underscores replaced

    def test_death_no_slayer_no_cause(self, legends):
        event = {"type": "hf died", "hfid": "1"}
        result = describe_event(event, legends)
        assert "Urist McHero" in result
        assert "died" in result

    def test_death_unknown_victim(self, legends):
        event = {"type": "hf died", "hfid": "999"}
        result = describe_event(event, legends)
        assert "figure #999" in result


# ---------------------------------------------------------------------------
# describe_event — combat events
# ---------------------------------------------------------------------------


class TestCombatEvents:
    """Combat-related event types."""

    def test_simple_battle(self, legends):
        event = {"type": "hf simple battle event", "group_1_hfid": "1", "group_2_hfid": "2", "site_id": "10"}
        result = describe_event(event, legends)
        assert "Urist McHero" in result
        assert "fought" in result
        assert "Goblin Bonecrusher" in result

    def test_wounded(self, legends):
        event = {"type": "hf wounded", "woundee_hfid": "1", "wounder_hfid": "2", "body_part": "upper_body"}
        result = describe_event(event, legends)
        assert "wounded" in result
        assert "upper body" in result  # underscores replaced

    def test_creature_devoured(self, legends):
        event = {"type": "creature devoured", "eater_hfid": "2", "victim_hfid": "3"}
        result = describe_event(event, legends)
        assert "devoured" in result
        assert "Goblin Bonecrusher" in result
        assert "Elf Treewalker" in result


# ---------------------------------------------------------------------------
# describe_event — artifacts
# ---------------------------------------------------------------------------


class TestArtifactEvents:
    """Artifact-related event types."""

    def test_artifact_created(self, legends):
        event = {"type": "artifact created", "hfid": "1", "artifact_id": "20", "site_id": "10"}
        result = describe_event(event, legends)
        assert "created" in result
        assert "The Axe of Legends" in result
        assert "Mountainhome" in result

    def test_artifact_found(self, legends):
        event = {"type": "artifact found", "hfid": "1", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "found" in result
        assert "The Axe of Legends" in result

    def test_artifact_given(self, legends):
        event = {"type": "artifact given", "giver_hfid": "1", "receiver_hfid": "3", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "gave" in result
        assert "Urist McHero" in result
        assert "Elf Treewalker" in result

    def test_artifact_lost(self, legends):
        event = {"type": "artifact lost", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "was lost" in result
        assert "The Axe of Legends" in result

    def test_artifact_destroyed(self, legends):
        event = {"type": "artifact destroyed", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "was destroyed" in result

    def test_artifact_stored(self, legends):
        event = {"type": "artifact stored", "hfid": "1", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "stored" in result

    def test_artifact_possessed(self, legends):
        event = {"type": "artifact possessed", "hfid": "1", "artifact_id": "20"}
        result = describe_event(event, legends)
        assert "claimed" in result


# ---------------------------------------------------------------------------
# describe_event — state changes
# ---------------------------------------------------------------------------


class TestStateChangeEvents:
    """change hf state, change hf job, etc."""

    def test_mood_state(self, legends):
        event = {"type": "change hf state", "hfid": "1", "mood": "berserk"}
        result = describe_event(event, legends)
        assert "berserk mood" in result

    def test_settled_state(self, legends):
        event = {"type": "change hf state", "hfid": "1", "state": "settled", "site_id": "10"}
        result = describe_event(event, legends)
        assert "settled" in result
        assert "Mountainhome" in result

    def test_wandering_state(self, legends):
        event = {"type": "change hf state", "hfid": "1", "state": "wandering"}
        result = describe_event(event, legends)
        assert "wandering" in result

    def test_job_change_both(self, legends):
        event = {"type": "change hf job", "hfid": "1", "old_job": "miner", "new_job": "blacksmith"}
        result = describe_event(event, legends)
        assert "changed profession" in result
        assert "miner" in result
        assert "blacksmith" in result

    def test_job_change_new_only(self, legends):
        event = {"type": "change hf job", "hfid": "1", "new_job": "farmer"}
        result = describe_event(event, legends)
        assert "became a farmer" in result


# ---------------------------------------------------------------------------
# describe_event — political
# ---------------------------------------------------------------------------


class TestPoliticalEvents:
    """Entity links, positions, alliances."""

    def test_add_entity_link_member(self, legends):
        event = {"type": "add hf entity link", "hfid": "1", "civ_id": "5", "link": "member"}
        result = describe_event(event, legends)
        assert "became a member" in result
        assert "The Dwarven Realm" in result

    def test_add_entity_link_prisoner(self, legends):
        event = {"type": "add hf entity link", "hfid": "1", "civ_id": "6", "link": "prisoner"}
        result = describe_event(event, legends)
        assert "imprisoned" in result
        assert "The Goblin Horde" in result

    def test_remove_entity_link_member(self, legends):
        event = {"type": "remove hf entity link", "hfid": "1", "civ_id": "5", "link": "member"}
        result = describe_event(event, legends)
        assert "left" in result
        assert "The Dwarven Realm" in result

    def test_add_entity_link_no_civ(self, legends):
        event = {"type": "add hf entity link", "hfid": "1", "civ_id": "999"}
        result = describe_event(event, legends)
        assert "gained a position" in result

    def test_assume_identity(self, legends):
        event = {"type": "assume identity", "trickster_hfid": "1", "identity_id": "50"}
        result = describe_event(event, legends)
        assert "assumed the identity" in result
        assert "Shadow the Thief" in result

    def test_assume_identity_unknown(self, legends):
        event = {"type": "assume identity", "trickster_hfid": "1", "identity_id": "999"}
        result = describe_event(event, legends)
        assert "false identity" in result


# ---------------------------------------------------------------------------
# describe_event — sites
# ---------------------------------------------------------------------------


class TestSiteEvents:
    """Site-related event types."""

    def test_created_site(self, legends):
        event = {"type": "created site", "civ_id": "5", "site_id": "10"}
        result = describe_event(event, legends)
        assert "founded" in result
        assert "Mountainhome" in result

    def test_destroyed_site(self, legends):
        event = {"type": "destroyed site", "attacker_civ_id": "6", "site_id": "10", "defender_civ_id": "5"}
        result = describe_event(event, legends)
        assert "destroyed" in result

    def test_attacked_site(self, legends):
        event = {"type": "attacked site", "attacker_civ_id": "6", "site_id": "10", "defender_civ_id": "5"}
        result = describe_event(event, legends)
        assert "attacked" in result

    def test_field_battle(self, legends):
        event = {"type": "field battle", "attacker_civ_id": "5", "defender_civ_id": "6"}
        result = describe_event(event, legends)
        assert "field battle" in result


# ---------------------------------------------------------------------------
# describe_event — miscellaneous
# ---------------------------------------------------------------------------


class TestMiscEvents:
    """Less common event types and the fallback."""

    def test_item_stolen(self, legends):
        event = {"type": "item stolen", "histfig": "2", "site_id": "10"}
        result = describe_event(event, legends)
        assert "stole" in result
        assert "Mountainhome" in result

    def test_hf_new_pet(self, legends):
        event = {"type": "hf new pet", "group_hfid": "1", "pets": "giant_cave_spider"}
        result = describe_event(event, legends)
        assert "tamed" in result
        assert "giant cave spider" in result

    def test_peace_accepted(self, legends):
        result = describe_event({"type": "peace accepted"}, legends)
        assert "Peace was accepted" in result

    def test_peace_rejected(self, legends):
        result = describe_event({"type": "peace rejected"}, legends)
        assert "Peace was rejected" in result

    def test_knowledge_discovered(self, legends):
        event = {"type": "knowledge discovered", "hfid": "1", "knowledge": "metallurgy"}
        result = describe_event(event, legends)
        assert "discovered" in result
        assert "metallurgy" in result

    def test_written_content_composed(self, legends):
        event = {"type": "written content composed", "hfid": "1", "site_id": "10"}
        result = describe_event(event, legends)
        assert "composed" in result

    def test_insurrection(self, legends):
        event = {"type": "insurrection started", "target_civ_id": "5", "site_id": "10"}
        result = describe_event(event, legends)
        assert "insurrection" in result

    def test_unknown_type_fallback(self, legends):
        event = {"type": "completely_new_event_type", "hfid": "1"}
        result = describe_event(event, legends)
        # Should not crash — uses fallback formatting
        assert result  # Non-empty string
        assert "Urist McHero" in result

    def test_unknown_type_no_hf(self, legends):
        event = {"type": "something_weird"}
        result = describe_event(event, legends)
        assert result  # Non-empty
        assert "Something Weird" in result  # Title-cased


# ---------------------------------------------------------------------------
# describe_event_linked — wraps names in [[]]
# ---------------------------------------------------------------------------


class TestLinkedMode:
    """describe_event_linked wraps entity names in [[]] for hotlink processing."""

    def test_linked_death(self, legends):
        event = {"type": "hf died", "hfid": "1", "slayer_hfid": "2", "site_id": "10"}
        result = describe_event_linked(event, legends)
        assert "[[Urist McHero]]" in result
        assert "[[Goblin Bonecrusher]]" in result
        assert "[[Mountainhome]]" in result

    def test_linked_artifact(self, legends):
        event = {"type": "artifact created", "hfid": "1", "artifact_id": "20"}
        result = describe_event_linked(event, legends)
        assert "[[Urist McHero]]" in result
        assert "[[The Axe of Legends]]" in result

    def test_linked_mode_resets(self, legends):
        """Linked mode should not leak into subsequent describe_event calls."""
        event = {"type": "hf died", "hfid": "1"}
        describe_event_linked(event, legends)
        # Normal call should NOT have [[]]
        result = describe_event(event, legends)
        assert "[[" not in result

    def test_linked_unknown_hf(self, legends):
        event = {"type": "hf died", "hfid": "999"}
        result = describe_event_linked(event, legends)
        # "someone" and unknown IDs should NOT be wrapped
        assert "[[" not in result or "[[figure #999]]" not in result
