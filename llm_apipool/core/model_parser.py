"""Model string parser for FreeLLMAPI-style model filtering."""

from __future__ import annotations


import re
from dataclasses import dataclass



@dataclass
class ModelFilter:
    """Filter criteria extracted from model string."""

    context_min: int | None = None
    tools: bool | None = None
    vision: bool | None = None
    provider: str | None = None
    strategy: str | None = None


class ModelParser:
    """Parse model strings like 'auto.-c=>128k.tool=true' into base model and filters."""

    _CONTEXT_PATTERN = re.compile(
        r"-c(?:ontext)?(>=|>|=>|==|<=|<|=|=>)(\d+)(k|M)?",
    )
    _TOOLS_PATTERN = re.compile(r"(?:-tool|tool)=(true|false)", re.IGNORECASE)
    _VISION_PATTERN = re.compile(r"(?:-vision|vision)=(true|false)", re.IGNORECASE)
    _PROVIDER_PATTERN = re.compile(r"-provider=([a-zA-Z0-9_-]+)")
    _PROFILE_PATTERN = re.compile(r"-profile=([a-zA-Z0-9_-]+)")
    _STRATEGY_PATTERN = re.compile(
        r"\.(priority|balanced|smartest|fastest|reliable|custom|auto)$"
    )

    @classmethod
    def parse(cls, model_string: str) -> tuple[str, ModelFilter, str | None]:
        if not model_string:
            return "auto", ModelFilter(), None

        model_string = model_string.strip()
        filter = ModelFilter()
        strategy_override = None

        strategy_match = cls._STRATEGY_PATTERN.search(model_string)
        if strategy_match:
            strategy_override = strategy_match.group(1)

        context_match = cls._CONTEXT_PATTERN.search(model_string)
        if context_match:
            operator, number, suffix = context_match.groups()
            context_tokens = int(number) * (
                1000 if (suffix or "").lower() == "k" else 1000000
            )
            if operator in (">=", ">", "=>"):
                filter.context_min = context_tokens

        tools_match = cls._TOOLS_PATTERN.search(model_string)
        if tools_match:
            filter.tools = tools_match.group(1).lower() == "true"

        vision_match = cls._VISION_PATTERN.search(model_string)
        if vision_match:
            filter.vision = vision_match.group(1).lower() == "true"

        provider_match = cls._PROVIDER_PATTERN.search(model_string)
        if provider_match:
            filter.provider = provider_match.group(1)

        base = "auto"
        return base, filter, strategy_override

    @classmethod
    def apply_to_models(cls, model_ids: list[str], filter: ModelFilter) -> list[str]:
        from .model_metadata import filter_models as _filter

        return _filter(
            models=model_ids,
            context_min=filter.context_min,
            tools=filter.tools,
            vision=filter.vision,
        )
