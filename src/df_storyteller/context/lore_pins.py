"""Lore pin storage — bookmark legends entities for cross-referencing in stories."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _pins_path(fortress_dir: Path) -> Path:
    return fortress_dir / "lore_pins.json"


def load_pins(fortress_dir: Path) -> list[dict[str, Any]]:
    """Load all lore pins for the current fortress."""
    path = _pins_path(fortress_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return []


def save_pins(fortress_dir: Path, pins: list[dict[str, Any]]) -> None:
    """Save all lore pins."""
    path = _pins_path(fortress_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pins, indent=2), encoding="utf-8")


def add_pin(
    fortress_dir: Path,
    entity_type: str,
    entity_id: str | int,
    name: str,
    note: str = "",
) -> dict[str, Any]:
    """Add a new lore pin. Returns the created pin."""
    pins = load_pins(fortress_dir)
    # Don't duplicate
    for p in pins:
        if str(p.get("entity_id")) == str(entity_id) and p.get("entity_type") == entity_type:
            # Update note if provided
            if note:
                p["note"] = note
                save_pins(fortress_dir, pins)
            return p

    pin = {
        "id": str(uuid.uuid4())[:8],
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "name": name,
        "note": note,
    }
    pins.append(pin)
    save_pins(fortress_dir, pins)
    return pin


def remove_pin(fortress_dir: Path, pin_id: str) -> bool:
    """Remove a pin by ID. Returns True if found and removed."""
    pins = load_pins(fortress_dir)
    new_pins = [p for p in pins if p.get("id") != pin_id]
    if len(new_pins) < len(pins):
        save_pins(fortress_dir, new_pins)
        return True
    return False


def update_pin_note(fortress_dir: Path, pin_id: str, note: str) -> bool:
    """Update a pin's note. Returns True if found."""
    pins = load_pins(fortress_dir)
    for p in pins:
        if p.get("id") == pin_id:
            p["note"] = note
            save_pins(fortress_dir, pins)
            return True
    return False
