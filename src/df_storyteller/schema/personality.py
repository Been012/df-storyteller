"""Dwarf personality models — facets, beliefs, and goals.

Dwarf Fortress gives each dwarf 50 personality facets (0-100 scale),
a set of beliefs/values, and life goals. These shape behavior, stress
responses, and social interactions.

Ref: https://dwarffortresswiki.org/index.php/DF2014:Personality_trait
DFHack access: unit.status.current_soul.personality
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# Facet descriptions keyed by name, with (low_desc, high_desc) for narrative use.
# Values 0-39 = low end, 40-60 = neutral, 61-100 = high end.
FACET_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "LOVE_PROPENSITY": ("does not easily fall in love", "can easily fall in love"),
    "HATE_PROPENSITY": ("does not easily hate", "quick to form negative views"),
    "ENVY_PROPENSITY": ("doesn't often feel envious", "often feels envious"),
    "CHEER_PROPENSITY": ("rarely happy or enthusiastic", "often cheerful"),
    "DEPRESSION_PROPENSITY": ("rarely feels discouraged", "often feels discouraged"),
    "ANGER_PROPENSITY": ("slow to anger", "quick to anger"),
    "ANXIETY_PROPENSITY": ("calm demeanor", "often nervous"),
    "LUST_PROPENSITY": ("does not often feel lustful", "often feels lustful"),
    "STRESS_VULNERABILITY": ("can handle stress", "doesn't handle stress well"),
    "GREED": ("doesn't focus on material goods", "has a greedy streak"),
    "IMMODERATION": ("doesn't often experience strong cravings", "occasionally overindulges"),
    "VIOLENT": ("tends to avoid physical confrontations", "likes to brawl"),
    "PERSEVERANCE": ("lacks perseverance", "is stubborn"),
    "WASTEFULNESS": ("tight with resources", "tends to be wasteful"),
    "DISCORD": ("prefers harmonious living", "doesn't mind a little tumult"),
    "FRIENDLINESS": ("somewhat quarrelsome", "friendly individual"),
    "POLITENESS": ("could be considered rude", "quite polite"),
    "DISDAIN_ADVICE": ("tends to ask others for help", "has tendency to go it alone"),
    "BRAVERY": ("somewhat fearful", "brave in the face of danger"),
    "CONFIDENCE": ("sometimes acts with little determination", "generally quite confident"),
    "VANITY": ("not inherently proud", "pleased by own appearance and talents"),
    "AMBITION": ("isn't particularly ambitious", "quite ambitious"),
    "GRATITUDE": ("takes help without feeling grateful", "grateful and tries to return favors"),
    "IMMODESTY": ("prefers modest presentation", "doesn't mind wearing something special"),
    "HUMOR": ("little interest in joking around", "has an active sense of humor"),
    "VENGEFUL": ("doesn't tend to hold on to grievances", "tends to hang on to grievances"),
    "PRIDE": ("very humble", "thinks self fairly important"),
    "CRUELTY": ("often acts with compassion", "generally acts impartially"),
    "SINGLEMINDED": ("can occasionally lose focus", "acts with narrow focus"),
    "HOPEFUL": ("tends to assume the worst outcome", "generally finds self hopeful"),
    "CURIOUS": ("isn't particularly curious", "curious and eager to learn"),
    "BASHFUL": ("not particularly interested in what others think", "tends to consider what others think"),
    "PRIVACY": ("tends to share experiences and thoughts", "tends not to reveal personal information"),
    "PERFECTIONIST": ("doesn't try to do things perfectly", "tries to do things correctly"),
    "CLOSEMINDED": ("doesn't cling tightly to ideas", "tends to be stubborn about changing mind"),
    "TOLERANT": ("somewhat uncomfortable around unusual others", "quite comfortable with different others"),
    "EMOTIONALLY_OBSESSIVE": ("tends to form only tenuous bonds", "has tendency toward deep emotional bonds"),
    "SWAYED_BY_EMOTIONS": ("tends not to be swayed by emotional appeals", "tends to be swayed by emotions"),
    "ALTRUISM": ("does not go out of way to help others", "finds helping others rewarding"),
    "DUTIFULNESS": ("finds obligations confining", "has a sense of duty"),
    "THOUGHTLESSNESS": ("tends to think before acting", "can sometimes act without deliberation"),
    "ORDERLINESS": ("tends to make a mess with possessions", "tries to keep things orderly"),
    "TRUST": ("is slow to trust others", "is trusting"),
    "GREGARIOUSNESS": ("tends to avoid crowds", "enjoys the company of others"),
    "ASSERTIVENESS": ("tends to be passive in discussions", "is assertive"),
    "ACTIVITY_LEVEL": ("likes to take it easy", "lives a fast-paced life"),
    "EXCITEMENT_SEEKING": ("doesn't seek out excitement", "likes a little excitement"),
    "IMAGINATION": ("isn't given to flights of fancy", "has an active imagination"),
    "ABSTRACT_INCLINED": ("likes to keep things practical", "has tendency to consider ideas"),
    "ART_INCLINED": ("does not have great aesthetic sensitivity", "is moved by art and natural beauty"),
}

# Belief/value names used in DF
BELIEF_NAMES: list[str] = [
    "LAW", "LOYALTY", "FAMILY", "FRIENDSHIP", "POWER", "TRUTH",
    "CUNNING", "ELOQUENCE", "FAIRNESS", "DECORUM", "TRADITION",
    "ARTWORK", "COOPERATION", "INDEPENDENCE", "STOICISM",
    "INTROSPECTION", "SELF_CONTROL", "TRANQUILITY", "HARMONY",
    "MERRIMENT", "CRAFTSMANSHIP", "MARTIAL_PROWESS", "SKILL",
    "HARD_WORK", "SACRIFICE", "COMPETITION", "PERSEVERANCE",
    "LEISURE_TIME", "COMMERCE", "ROMANCE", "NATURE", "PEACE",
    "KNOWLEDGE",
]

# Goal/dream types
GOAL_NAMES: list[str] = [
    "STAY_ALIVE", "MAINTAIN_ENTITY_STATUS", "START_A_FAMILY",
    "RULE_THE_WORLD", "CREATE_A_GREAT_WORK_OF_ART",
    "CRAFT_A_MASTERWORK", "BRING_PEACE_TO_THE_WORLD",
    "BECOME_A_LEGENDARY_WARRIOR", "MASTER_A_SKILL",
    "FALL_IN_LOVE", "SEE_THE_GREAT_NATURAL_SITES",
    "IMMORTALITY", "MAKE_A_GREAT_DISCOVERY",
    "ATTAIN_RANK_IN_SOCIETY", "BATHE_WORLD_IN_CHAOS",
]


class Facet(BaseModel):
    """A single personality facet with its 0-100 value."""

    name: str
    value: int  # 0-100 scale

    @property
    def description(self) -> str:
        """Human-readable description based on the value."""
        descs = FACET_DESCRIPTIONS.get(self.name)
        if not descs:
            return f"{self.name}: {self.value}"
        low_desc, high_desc = descs
        if self.value < 25:
            return f"strongly {low_desc}"
        elif self.value < 40:
            return low_desc
        elif self.value <= 60:
            return ""  # Neutral — no notable trait
        elif self.value <= 75:
            return high_desc
        else:
            return f"strongly {high_desc}"

    @property
    def is_notable(self) -> bool:
        """Whether this facet is far enough from neutral to be worth mentioning."""
        return self.value < 25 or self.value > 75


class Belief(BaseModel):
    """A belief/value with its strength."""

    name: str
    value: int  # Negative = against, 0 = neutral, positive = for

    @property
    def description(self) -> str:
        if self.value > 10:
            return f"deeply values {self.name.lower().replace('_', ' ')}"
        elif self.value < -10:
            return f"opposes {self.name.lower().replace('_', ' ')}"
        return ""

    @property
    def is_notable(self) -> bool:
        return abs(self.value) > 10


class Goal(BaseModel):
    """A life goal/dream."""

    name: str
    achieved: bool = False

    @property
    def description(self) -> str:
        readable = self.name.lower().replace("_", " ")
        if self.achieved:
            return f"fulfilled their dream to {readable}"
        return f"dreams of: {readable}"


class Personality(BaseModel):
    """Complete personality profile for a dwarf."""

    facets: list[Facet] = Field(default_factory=list)
    beliefs: list[Belief] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)

    @property
    def notable_facets(self) -> list[Facet]:
        """Facets that deviate significantly from neutral."""
        return [f for f in self.facets if f.is_notable]

    @property
    def notable_beliefs(self) -> list[Belief]:
        """Beliefs with strong positive or negative values."""
        return [b for b in self.beliefs if b.is_notable]

    def narrative_summary(self) -> str:
        """Generate a prose summary of this personality for LLM context.

        Focuses on notable traits only — neutral facets are omitted
        to keep context concise and narratively interesting.
        """
        parts: list[str] = []

        # Notable facets
        facet_descs = [f.description for f in self.notable_facets if f.description]
        if facet_descs:
            parts.append("Personality: " + "; ".join(facet_descs) + ".")

        # Notable beliefs
        belief_descs = [b.description for b in self.notable_beliefs if b.description]
        if belief_descs:
            parts.append("Values: " + "; ".join(belief_descs) + ".")

        # Goals
        goal_descs = [g.description for g in self.goals]
        if goal_descs:
            parts.append("Goals: " + "; ".join(goal_descs) + ".")

        return " ".join(parts) if parts else "An unremarkable personality."
