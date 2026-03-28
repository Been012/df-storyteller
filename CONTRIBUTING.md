# Contributing to df-storyteller

Thanks for your interest in contributing! This project welcomes contributions of all kinds.

## Getting Started

```bash
git clone https://github.com/Been012/df-storyteller.git
cd df-storyteller
pip install -e ".[dev]"
pytest  # Verify everything works
```

## Ways to Contribute

### Report Bugs
Use the [Bug Report](https://github.com/Been012/df-storyteller/issues/new?template=bug_report.md) template. Include your environment details and steps to reproduce.

### Suggest Features
Use the [Feature Request](https://github.com/Been012/df-storyteller/issues/new?template=feature_request.md) template. Explain the DF gameplay context for your idea.

### Suggest Quest Types
Use the [Quest Idea](https://github.com/Been012/df-storyteller/issues/new?template=quest_idea.md) template. Make sure the quest is achievable in vanilla Dwarf Fortress and has a narrative hook.

### Submit Code
1. Fork the repo and create a branch
2. Make your changes
3. Run `pytest` to verify tests pass
4. Submit a PR using the template

## Development Guidelines

### DF Compatibility
- **Target DF Premium (Steam release)** — not classic DF
- Use `histfig_links` on historical figures for relationships, not `unit.relations`
- Wrap all DFHack Lua callbacks in `pcall` for error resilience
- Use `dfhack.df2utf()` on names from `getReadableName()`
- Test that DFHack APIs exist before using them (they vary between versions)

### Python Code
- Python 3.11+ with modern syntax
- Pydantic v2 for data models
- Type hints on all function signatures
- No bare `except` — always catch specific exceptions
- Async for LLM calls

### LLM Prompts
- All prompts include the DF mechanics reference (`df_mechanics.py`) to prevent hallucination
- Don't suggest things the player cannot control (strange moods, migrations, love)
- Use actual dwarf/deity/civilization names from the data
- Frame quests and narratives around story, not task lists

### Web UI
- Vanilla JS only (no npm, no build step)
- Use `createElement`/`textContent` for dynamic content (no `innerHTML` for user data)
- All generation buttons must use `finally` blocks to re-enable on error
- Check `response.ok` on all fetch calls

### Testing
- All parsers need tests with fixtures in `tests/fixtures/`
- Never call real LLM APIs in tests
- No test requires a running Dwarf Fortress instance

## Project Structure

See the [Architecture](https://github.com/Been012/df-storyteller/wiki/Architecture) wiki page for details.
