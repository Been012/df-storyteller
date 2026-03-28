"""Persistent storage for AI-generated quests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from df_storyteller.config import AppConfig
from df_storyteller.schema.quests import Quest, QuestStatus


def _quests_path(config: AppConfig, output_dir: Path | None = None) -> Path:
    d = output_dir or Path(config.paths.output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "quests.json"


def load_all_quests(config: AppConfig, output_dir: Path | None = None) -> list[Quest]:
    path = _quests_path(config, output_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return [Quest.model_validate(q) for q in data]
    except (json.JSONDecodeError, OSError):
        return []


def save_all_quests(config: AppConfig, quests: list[Quest], output_dir: Path | None = None) -> None:
    path = _quests_path(config, output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([q.model_dump(mode="json") for q in quests], f, indent=2, default=str)


def add_quest(config: AppConfig, quest: Quest, output_dir: Path | None = None) -> Quest:
    quests = load_all_quests(config, output_dir)
    quests.append(quest)
    save_all_quests(config, quests, output_dir)
    return quest


def complete_quest(config: AppConfig, quest_id: str, narrative: str, output_dir: Path | None = None) -> bool:
    quests = load_all_quests(config, output_dir)
    for quest in quests:
        if quest.id == quest_id:
            quest.status = QuestStatus.COMPLETED
            quest.completed_at = datetime.now()
            quest.completion_narrative = narrative
            save_all_quests(config, quests, output_dir)
            return True
    return False


def abandon_quest(config: AppConfig, quest_id: str, output_dir: Path | None = None) -> bool:
    quests = load_all_quests(config, output_dir)
    for quest in quests:
        if quest.id == quest_id:
            quest.status = QuestStatus.ABANDONED
            save_all_quests(config, quests, output_dir)
            return True
    return False


def delete_quest(config: AppConfig, quest_id: str, output_dir: Path | None = None) -> bool:
    quests = load_all_quests(config, output_dir)
    original_len = len(quests)
    quests = [q for q in quests if q.id != quest_id]
    if len(quests) < original_len:
        save_all_quests(config, quests, output_dir)
        return True
    return False


def toggle_priority(config: AppConfig, quest_id: str, output_dir: Path | None = None) -> bool:
    quests = load_all_quests(config, output_dir)
    for quest in quests:
        if quest.id == quest_id:
            quest.priority = not quest.priority
            save_all_quests(config, quests, output_dir)
            return True
    return False


def get_active_quests(config: AppConfig, output_dir: Path | None = None) -> list[Quest]:
    return [q for q in load_all_quests(config, output_dir) if q.status == QuestStatus.ACTIVE]


def get_completed_quests(config: AppConfig, output_dir: Path | None = None) -> list[Quest]:
    return [q for q in load_all_quests(config, output_dir) if q.status == QuestStatus.COMPLETED]
