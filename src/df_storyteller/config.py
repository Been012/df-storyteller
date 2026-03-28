"""Application configuration loaded from TOML."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_DIR = Path.home() / ".df-storyteller"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"


class PathsConfig(BaseModel):
    df_install: str = ""
    gamelog: str = ""
    event_dir: str = ""
    legends_xml: str = ""
    output_dir: str = str(Path.home() / ".df-storyteller" / "stories")


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3"


class LLMConfig(BaseModel):
    provider: str = "ollama"  # claude | openai | ollama
    model: str = ""
    api_key: str = ""  # Stored in config — takes priority over env var
    api_key_env: str = ""  # Legacy: env var name fallback
    max_tokens: int = 4096
    temperature: float = 0.8
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


class WatchConfig(BaseModel):
    poll_interval_seconds: int = 2
    process_backlog: bool = True


class StoryConfig(BaseModel):
    chronicle_auto_generate: bool = False
    chronicle_trigger: str = "season"  # season | manual
    narrative_style: str = "dramatic"  # dramatic | factual | humorous
    biography_max_tokens: int = 1024  # Bios should be short — they get updated over time
    chronicle_max_tokens: int = 4096
    saga_max_tokens: int = 4096
    chat_summary_max_tokens: int = 2048
    quest_generation_max_tokens: int = 2048
    quest_narrative_max_tokens: int = 1024


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    story: StoryConfig = Field(default_factory=StoryConfig)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config from TOML file, falling back to defaults."""
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return AppConfig.model_validate(data)
    return AppConfig()


def save_config(config: AppConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Save config to TOML file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    def write_section(prefix: str, data: dict) -> None:
        scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
        nested = {k: v for k, v in data.items() if isinstance(v, dict)}

        if scalars:
            lines.append(f"[{prefix}]")
            for key, value in scalars.items():
                if isinstance(value, bool):
                    lines.append(f"{key} = {str(value).lower()}")
                elif isinstance(value, str):
                    escaped = value.replace("\\", "\\\\")
                    lines.append(f'{key} = "{escaped}"')
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")

        for key, value in nested.items():
            write_section(f"{prefix}.{key}", value)

    config_dict = config.model_dump()
    for section, data in config_dict.items():
        if isinstance(data, dict):
            write_section(section, data)
        else:
            lines.append(f"{section} = {data}")

    path.write_text("\n".join(lines), encoding="utf-8")
