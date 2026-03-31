"""Settings page routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from df_storyteller.config import save_config
from df_storyteller.web.state import (
    get_config as _get_config,
    invalidate_cache as _invalidate_cache,
    base_context as _base_context,
)
from df_storyteller.web.templates_setup import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    config = _get_config()
    ctx = _base_context(config, "settings", None)

    # Find which legends file is loaded
    legends_file = ""
    if config.paths.df_install:
        df_dir = Path(config.paths.df_install)
        candidates = sorted(
            [f for f in df_dir.glob("*-legends.xml") if "legends_plus" not in f.name],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if candidates:
            legends_file = candidates[0].name

    return templates.TemplateResponse(request=request, name="settings.html", context={
        **ctx, "config": config, "saved": saved, "legends_file": legends_file,
    })


@router.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    config = _get_config()

    config.paths.df_install = form.get("df_install", config.paths.df_install)
    config.story.no_llm_mode = form.get("no_llm_mode") == "true"
    config.llm.provider = form.get("llm_provider", config.llm.provider)
    if form.get("model_name") is not None:
        config.llm.model = form["model_name"]
    if form.get("api_key"):
        config.llm.api_key = form["api_key"]
    if form.get("ollama_model"):
        config.llm.ollama.model = form["ollama_model"]
    if form.get("ollama_base_url"):
        config.llm.ollama.base_url = form["ollama_base_url"]
    try:
        num_ctx = form.get("ollama_num_ctx")
        if num_ctx:
            config.llm.ollama.num_ctx = int(num_ctx)
    except (ValueError, TypeError):
        pass
    config.story.narrative_style = form.get("narrative_style", config.story.narrative_style)
    if form.get("author_instructions") is not None:
        config.story.author_instructions = form["author_instructions"]
    for field in ("temperature", "top_p", "repetition_penalty"):
        try:
            val = form.get(field)
            if val:
                setattr(config.llm, field, float(val))
        except (ValueError, AttributeError):
            pass
    for field in ("chronicle_max_tokens", "biography_max_tokens", "saga_max_tokens", "chat_summary_max_tokens", "gazette_max_tokens", "quest_generation_max_tokens", "quest_narrative_max_tokens"):
        try:
            val = form.get(field)
            if val:
                setattr(config.story, field, int(val))
        except (ValueError, AttributeError):
            pass

    save_config(config)
    _invalidate_cache()
    return RedirectResponse("/settings?saved=true", status_code=303)
