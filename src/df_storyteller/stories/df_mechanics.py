"""Dwarf Fortress mechanics reference for LLM prompts.

This module provides a single source of truth about how DF actually works,
shared across all story generators (chronicles, biographies, diaries, quests,
eulogies, sagas) to prevent the LLM from hallucinating game mechanics.
"""

DF_MECHANICS_REFERENCE = """
DWARF FORTRESS MECHANICS — Ground all narrative in these facts:

MILITARY:
- Squads have a maximum of 10 dwarves each. A fortress can have multiple squads.
- Dwarves must be ASSIGNED to a squad to train. Unassigned dwarves do not practice combat.
- Training happens in a barracks (a room designated from a bed, weapon rack, or armor stand).
- Dwarves spar with each other to gain combat skill. They don't train alone.
- Militia commanders and captains lead squads. They are appointed, not elected.
- Equipment (weapons, armor, shields) must be assigned via the military screen. Dwarves don't pick up weapons on their own unless drafted.
- Sieges only occur when the fortress has 80+ population. Before that, only ambushes and thieving.
- Soldiers on duty follow patrol routes or station orders. Off-duty soldiers return to civilian jobs.

FORTRESS LIFE:
- Dwarves eat in dining rooms, sleep in bedrooms, and drink booze (not water unless desperate).
- Dwarves have needs: socializing, praying, drinking, eating, creating, fighting (varies by personality).
- Unhappy dwarves throw tantrums, start fights, or break things. Extremely unhappy ones go berserk or catatonic.
- Dwarves do NOT talk to each other in organized meetings — socialization happens passively in shared spaces (taverns, dining rooms, temples).
- Migrants arrive in waves, usually in spring and autumn. The player cannot control who arrives.
- Children cannot work or fight. They grow up after about 12 years.

PROFESSIONS & LABOR:
- Each dwarf can have multiple labors enabled. They choose tasks from enabled labors.
- Skill improves through practice. Legendary is the highest level (level 20+).
- Professions are determined by their highest skill, not assigned by the player.
- Noble positions (mayor, manager, bookkeeper) are appointed or elected, not trained into.

CONSTRUCTION:
- Players build structures tile by tile: walls, floors, ramps, stairs, fortifications.
- Materials: stone blocks, wood, glass panes, metal bars, bricks. Each must be produced first.
- Smoothing and engraving are done by masons/engravers on natural stone walls.
- Furniture (tables, chairs, beds, statues, etc.) is built at workshops then placed.
- Zone value comes from placed furniture quality, smoothed/engraved walls, and flooring.

CRAFTING:
- Workshops are where items are made: mason, carpenter, metalsmith, jeweler, etc.
- Strange moods are RANDOM — the player cannot trigger them. The game selects an eligible dwarf.
- Artifacts from moods are unique named items. The dwarf chooses what to make based on their skills.
- Trade caravans arrive seasonally. Players select items to trade at a trade depot.

RELIGION & TEMPLES:
- Each dwarf worships deities from their civilization's pantheon. They may worship multiple gods.
- Temples are zones designated for a specific religion/deity. Value determines rank (shrine/temple/complex).
- Priests are appointed by the temple's religion, not by the player directly.
- Dwarves pray at temples to fulfill religious needs.

EXPLORATION & UNDERGROUND:
- There are typically 3 cavern layers underground, each deeper and more dangerous.
- The magma sea is at the deepest level. Magma is used for fuel-free forging.
- Forgotten beasts emerge from breached cavern walls. They are unique procedurally generated creatures.
- Adamantine is found in veins above the magma sea. Mining too deep risks breaching the HFS (demons).

SOCIAL:
- Dwarves form relationships (friends, lovers, grudges) based on proximity and personality.
- Marriage happens between dwarves who develop romantic feelings — the player cannot arrange it.
- Taverns attract visitors (performers, mercenaries, scholars) when properly furnished with a tavern keeper.
- Guilds form when enough dwarves practice the same craft. They petition for a guild hall.

MISSIONS (off-map squad operations):
- Military squads can be sent on missions to distant sites via the Civilization screen.
- Mission types: Raid (stealth theft), Pillage (open assault + theft), Raze (assault + destroy site), Demand Tribute (diplomatic + payment), Conquer (military takeover), Recover Artifact/Citizen.
- Squads operate entirely off-screen. The player gets reports when they return.
- Success depends on military tactics skill and ambusher skill vs defender strength.
- Conquered sites become holdings with a dwarf administrator appointed.

DIPLOMACY & FOREIGN RELATIONS:
- Diplomatic states: No Contact → Peace → Alliance → Skirmishing → War.
- Outpost liaisons arrive yearly with the dwarven caravan. They handle trade agreements, noble promotions, and deliver news.
- Killing or letting diplomats die at your fortress triggers war with their civilization.
- Seizing caravan goods, harming traders, or exceeding elf tree-cutting limits strains relations toward war.
- During war: no caravans, no visitors, no tribute from that civilization. Sieges increase.
- Peace can be negotiated when diplomats visit during wartime.

TRADE & CARAVANS:
- Caravans arrive seasonally: elves in spring, humans in summer, dwarves in autumn. No winter trade.
- They travel to the trade depot, unload, and stay for about 25-33 days.
- The fortress broker handles trade negotiations. Appraisal skill affects price accuracy.
- Caravans bring goods based on the civilization's resources and previous trade requests.
- Destroying or seizing caravans has diplomatic consequences escalating toward war.

NEWS & RUMORS:
- News spreads through the world via witnesses, travelers, and diplomats.
- Tavern visitors bring rumors when served drinks by the tavern keeper.
- The outpost liaison brings yearly news from the mountainhomes.
- Major events (wars, megabeast attacks, artifact creation) spread faster than minor ones.

GOBLINS & SIEGES:
- Goblin civilizations are led by demons who escaped the underworld.
- Early attacks: baby-snatchers try to kidnap children; thieves steal items.
- Sieges: organized military assaults with copper/iron weapons. Goblins are cowardly — they flee when outmatched.
- Defeating most attackers causes the rest to rout.

NECROMANCERS & UNDEAD:
- Necromancer towers within 20 tiles can send undead sieges ("The dead walk. Hide while you still can!").
- Undead are reanimated corpses hostile to all living creatures. Severed body parts can be individually reanimated.
- Blunt weapons are better than edged against undead (slashing creates more reanimatable parts).
- Destroying corpses completely (magma, atom-smashing) prevents reanimation.

MEGABEASTS & TITANS:
- Forgotten beasts emerge from breached cavern walls. They are procedurally generated with unique abilities.
- Titans attack the surface. They require 80+ population and 100,000+ fortress wealth.
- Dragons have fixed lairs — nearby ones are more likely to attack.
- Megabeast attacks increase as fortress wealth grows — wealth attracts danger.

ARTIFACT THEFT:
- Visitors at the fortress may attempt to steal artifacts.
- Theft requires an accomplice inside the fortress to hand off the artifact to a visitor.
- Stolen artifacts trigger the message "X is missing from its proper place!"
- Storing artifacts in built containers (chests, display cases) helps prevent theft.
- Refusing to give up a legendary artifact when demanded can trigger war.

FORTRESS WEALTH & CONSEQUENCES:
- Wealth is the sum of all fortress output: buildings, engravings, goods, furniture, artifacts.
- Higher wealth attracts more migrants, enables noble titles (baron/count/duke), but also attracts more attacks.
- Noble titles require both population and exported wealth thresholds.
- There is an inherent tension: building a grand fortress makes it a bigger target.

WHAT THE PLAYER CANNOT CONTROL:
- Who migrates to the fortress
- Strange moods (random)
- Who falls in love or forms friendships
- Weather and seasons
- Which forgotten beast appears or what abilities it has
- Whether vampires or werebeasts arrive (random migrant events)
- Artifact properties (chosen by the moody dwarf)
- Caravan contents
- When sieges or megabeast attacks occur (triggered by population/wealth thresholds)
- News/rumor spread timing
"""
