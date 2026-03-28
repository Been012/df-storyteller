"""Deploy DFHack Lua scripts to the DF installation."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console

console = Console()

DFHACK_SCRIPTS_DIR = Path(__file__).parent / "dfhack_scripts"


def deploy_scripts(df_install: Path) -> None:
    """Copy Lua scripts to DF's hack/scripts/ directory."""
    target_dir = df_install / "hack" / "scripts"

    if not target_dir.exists():
        console.print(f"[yellow]Warning: {target_dir} does not exist. Creating it.[/yellow]")
        target_dir.mkdir(parents=True, exist_ok=True)

    for script in DFHACK_SCRIPTS_DIR.glob("*.lua"):
        dest = target_dir / script.name
        shutil.copy2(script, dest)
        console.print(f"  [green]Deployed:[/green] {script.name} -> {dest}")

    # Add auto-start to dfhack.init so events start when a fortress loads
    _setup_autostart(df_install)

    console.print("[green]DFHack scripts deployed successfully.[/green]")


AUTOSTART_MARKER = "# df-storyteller auto-start"


def _setup_autostart(df_install: Path) -> None:
    """Create onMapLoad.init entry so events auto-start when a fortress loads.

    DFHack runs onMapLoad*.init files when a map loads in fortress or adventure mode.
    Ref: https://docs.dfhack.org/en/stable/docs/Core.html
    """
    init_dir = df_install / "dfhack-config" / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    init_path = init_dir / "onMapLoad.init"

    # Check if already added
    if init_path.exists():
        content = init_path.read_text(encoding="utf-8", errors="replace")
        if AUTOSTART_MARKER in content:
            return  # Already configured
    else:
        content = ""

    # Append auto-start command
    with open(init_path, "a", encoding="utf-8") as f:
        f.write(f"\n{AUTOSTART_MARKER}\nstoryteller-events start\n")

    console.print("  [green]Auto-start added:[/green] events will start automatically when a fortress loads")
