"""CLI entry point — simplified flat commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from df_storyteller.config import AppConfig, load_config, save_config, DEFAULT_CONFIG_PATH

console = Console()


def get_config(ctx: click.Context) -> AppConfig:
    return ctx.obj or load_config()


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    """df-storyteller: Turn Dwarf Fortress events into epic narratives."""
    ctx.ensure_object(dict)
    ctx.obj = load_config()


# ==================== init ====================

@main.command()
@click.option("--df-path", default=None, help="Path to DF installation (skips prompt)")
@click.pass_context
def init(ctx: click.Context, df_path: str | None) -> None:
    """One-time setup: configure DF path, LLM provider, and deploy scripts."""

    # 1. DF path
    if not df_path:
        df_path = click.prompt("Path to Dwarf Fortress installation")
    df_dir = Path(df_path)
    if not df_dir.exists():
        console.print(f"[red]Directory not found:[/red] {df_path}")
        raise SystemExit(1)

    config = get_config(ctx)
    config.paths.df_install = str(df_dir)
    config.paths.gamelog = str(df_dir / "gamelog.txt")
    config.paths.event_dir = str(df_dir / "storyteller_events")

    # 2. LLM provider
    provider = click.prompt(
        "LLM provider",
        type=click.Choice(["claude", "openai", "ollama"]),
        default="ollama",
    )
    config.llm.provider = provider

    # 3. Provider-specific config
    if provider in ("claude", "openai"):
        api_key = click.prompt("API key", hide_input=True)
        config.llm.api_key = api_key
    elif provider == "ollama":
        console.print("\n[bold]Ollama setup[/bold]")
        console.print("Make sure Ollama is installed and running ([bold]ollama serve[/bold])")
        console.print("You can see available models with: [bold]ollama list[/bold]")
        ollama_model = click.prompt(
            "Ollama model name",
            default="llama3",
        )
        config.llm.ollama.model = ollama_model
        ollama_url = click.prompt(
            "Ollama URL",
            default="http://localhost:11434",
        )
        config.llm.ollama.base_url = ollama_url

    # 4. Save config
    save_config(config)
    console.print(f"\n[green]Config saved to {DEFAULT_CONFIG_PATH}[/green]")

    # 5. Create event directory
    event_dir = Path(config.paths.event_dir)
    event_dir.mkdir(parents=True, exist_ok=True)
    (event_dir / "processed").mkdir(exist_ok=True)

    # 6. Deploy DFHack scripts
    from df_storyteller.deploy import deploy_scripts
    deploy_scripts(df_dir)

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("\nNext steps:")
    console.print("  1. Launch Dwarf Fortress and load a fortress")
    console.print("  2. In DFHack console, type: [bold]storyteller-begin[/bold]")
    console.print("  3. Launch the web UI: [bold]python -m df_storyteller serve[/bold]")
    console.print("  4. Start generating stories!")


# ==================== status ====================

@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show what game data is available and current configuration."""
    config = get_config(ctx)

    # Count available data — find the most recent world subfolder
    base_dir = Path(config.paths.event_dir) if config.paths.event_dir else None
    event_dir = None
    world_name = ""
    snapshot_count = 0
    event_count = 0
    citizen_count = 0
    legends_found = False

    if base_dir and base_dir.exists():
        world_dirs = [d for d in base_dir.iterdir() if d.is_dir() and d.name != "processed"]
        if world_dirs:
            event_dir = max(world_dirs, key=lambda d: d.stat().st_mtime)
            world_name = event_dir.name

    if event_dir and event_dir.exists():
        snapshots = list(event_dir.glob("snapshot_*.json"))
        processed = event_dir / "processed"
        if processed.exists():
            snapshots += list(processed.glob("snapshot_*.json"))
        snapshot_count = len(snapshots)

        events = [f for f in event_dir.glob("*.json") if not f.name.startswith("snapshot_")]
        if processed.exists():
            events += [f for f in processed.glob("*.json") if not f.name.startswith("snapshot_")]
        event_count = len(events)

        # Quick peek at latest snapshot for citizen count
        if snapshots:
            import json
            latest = sorted(snapshots, reverse=True)[0]
            try:
                with open(latest, encoding="utf-8", errors="replace") as f:
                    snap = json.load(f)
                citizen_count = snap.get("data", {}).get("population", 0)
            except Exception:
                pass

    # Check for legends XML
    if config.paths.legends_xml and Path(config.paths.legends_xml).exists():
        legends_found = True
    elif config.paths.df_install:
        df_dir = Path(config.paths.df_install)
        legends_files = list(df_dir.glob("*-legends.xml")) + list(df_dir.glob("*-world_history.xml"))
        legends_found = len(legends_files) > 0

    # API key status
    import os
    has_key = bool(config.llm.api_key) or bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))

    table = Table(title="df-storyteller status", show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("DF Install", config.paths.df_install or "[red]not configured[/red]")
    table.add_row("Active World", world_name or "[yellow]none[/yellow]")
    table.add_row("Citizens tracked", f"{citizen_count}" if citizen_count else "[yellow]no snapshot yet[/yellow]")
    table.add_row("Snapshots", str(snapshot_count))
    table.add_row("Events captured", str(event_count))
    table.add_row("Legends data", "[green]found[/green]" if legends_found else "[yellow]not exported yet[/yellow]")
    table.add_row("LLM Provider", config.llm.provider)
    table.add_row("API Key", "[green]configured[/green]" if has_key else "[red]missing[/red]")

    console.print(table)

    if not config.paths.df_install:
        console.print("\nRun [bold]python -m df_storyteller init[/bold] to get started.")


# ==================== dwarves ====================

@main.command()
@click.option("--detail", is_flag=True, help="Show full narrative context per dwarf")
@click.pass_context
def dwarves(ctx: click.Context, detail: bool) -> None:
    """List all known dwarves from the latest snapshot."""
    config = get_config(ctx)

    from df_storyteller.context.loader import load_game_state
    from df_storyteller.context.narrative_formatter import format_dwarf_narrative, format_fortress_context
    event_store, character_tracker, world_lore, metadata = load_game_state(config)

    ranked = character_tracker.ranked_characters()
    if not ranked:
        console.print("No dwarves found. Take a snapshot first (run 'storyteller-begin' in DFHack).")
        return

    # Show fortress setting
    console.print(format_fortress_context(metadata))
    console.print("")

    if detail:
        # Show full narrative text (what the LLM would see)
        for dwarf, _ in ranked:
            console.print(format_dwarf_narrative(dwarf))
            console.print("")
    else:
        table = Table(title=f"Citizens ({len(ranked)} dwarves)")
        table.add_column("Name", style="bold")
        table.add_column("Profession")
        table.add_column("Age")
        table.add_column("Notable Traits")

        for dwarf, score in ranked:
            traits = ""
            if dwarf.personality and dwarf.personality.notable_facets:
                trait_list = [f.description for f in dwarf.personality.notable_facets[:3] if f.description]
                traits = "; ".join(trait_list)
            age = f"{dwarf.age:.0f}" if dwarf.age else "?"
            table.add_row(dwarf.name, dwarf.profession, age, traits or "-")

        console.print(table)


# ==================== chronicle ====================

@main.command()
@click.option("--season", default=None, help="Season to cover (e.g. 'autumn 205')")
@click.pass_context
def chronicle(ctx: click.Context, season: str | None) -> None:
    """Generate a fortress chronicle from captured game data."""
    from df_storyteller.stories.chronicle import generate_chronicle

    config = get_config(ctx)
    console.print("[bold]Generating chronicle...[/bold]")
    try:
        result = asyncio.run(generate_chronicle(config, season))
        console.print("\n" + result)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")


# ==================== bio ====================

@main.command()
@click.argument("dwarf_name")
@click.pass_context
def bio(ctx: click.Context, dwarf_name: str) -> None:
    """Generate a biography for a dwarf. Supports ASCII names (urist matches Urist)."""
    from df_storyteller.stories.biography import generate_biography

    config = get_config(ctx)
    console.print(f"[bold]Generating biography for {dwarf_name}...[/bold]")
    try:
        result = asyncio.run(generate_biography(config, dwarf_name))
        console.print("\n" + result)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")


# ==================== saga ====================

@main.command()
@click.option("--scope", type=click.Choice(["civ", "war", "artifact", "full"]), default="full")
@click.pass_context
def saga(ctx: click.Context, scope: str) -> None:
    """Generate an epic world history saga from legends data."""
    from df_storyteller.stories.saga import generate_saga

    config = get_config(ctx)
    console.print("[bold]Generating saga...[/bold]")
    try:
        result = asyncio.run(generate_saga(config, scope))
        console.print("\n" + result)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")


# ==================== config ====================

@main.group("config")
def config_group() -> None:
    """View and edit configuration."""


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    config = get_config(ctx)
    from rich.syntax import Syntax
    import json

    # Hide API key in display
    data = config.model_dump()
    if data.get("llm", {}).get("api_key"):
        data["llm"]["api_key"] = "***configured***"

    text = json.dumps(data, indent=2)
    console.print(Syntax(text, "json", theme="monokai"))


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a config value (e.g. llm.provider claude)."""
    config = get_config(ctx)
    parts = key.split(".")

    obj = config
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)

    save_config(config)
    console.print(f"[green]Set {key} = {value}[/green]")


# ==================== deploy ====================

@main.command()
@click.pass_context
def deploy(ctx: click.Context) -> None:
    """Re-deploy DFHack Lua scripts to the DF installation."""
    from df_storyteller.deploy import deploy_scripts

    config = get_config(ctx)
    df_dir = Path(config.paths.df_install)
    if not df_dir.exists():
        console.print("[red]DF install path not configured. Run 'python -m df_storyteller init' first.[/red]")
        raise SystemExit(1)
    deploy_scripts(df_dir)


# ==================== serve ====================

@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8000, help="Port to serve on")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Launch the web UI in your browser."""
    import webbrowser
    from df_storyteller.web.app import run_server

    url = f"http://{host}:{port}"
    console.print(f"[bold]Starting df-storyteller web UI at {url}[/bold]")
    webbrowser.open(url)
    run_server(host=host, port=port)
