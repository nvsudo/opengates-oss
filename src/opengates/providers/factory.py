from __future__ import annotations

from pathlib import Path

from ..settings import Settings
from .base import DecisionProvider
from .heuristic import HeuristicDecisionProvider
from .openai_responses import OpenAIResponsesDecisionProvider


def build_provider(settings: Settings) -> DecisionProvider:
    fallback = HeuristicDecisionProvider()
    if settings.provider_name == "heuristic":
        return fallback
    if settings.provider_name == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when OPENGATES_PROVIDER=openai")
        return OpenAIResponsesDecisionProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            debug_dir=settings.data_dir / "history" if settings.debug_prompts else None,
            fallback_provider=fallback,
            prefilter_provider=fallback,
        )
    raise RuntimeError(f"unsupported provider: {settings.provider_name}")
