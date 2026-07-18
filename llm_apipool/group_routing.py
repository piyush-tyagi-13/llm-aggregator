"""Group-based routing utilities for the dashboard."""

from __future__ import annotations

import re
from typing import Any

# Group pattern: gN where N is one or more digits
_GROUP_PATTERN = re.compile(r"^g(\d+)$")


def extract_group(model_name: str) -> str:
    """Extract group from model name.

    - If model matches gN pattern (e.g., 'g1', 'g2'), returns 'gN'.
    - Otherwise returns 'default'.
    """
    if _GROUP_PATTERN.match(model_name):
        return model_name
    return "default"


def parse_context_filter(model_param: str) -> tuple[str, int] | None:
    """Parse model parameter for context window filtering.

    Syntax: {prefix}.{number}{k|M} (e.g., 'g1.128k', 'opus.1M', 'default.64k').
    Returns (group, min_context_tokens) or None if no filter syntax.

    - If prefix matches gN, filter applies to that specific group.
    - Otherwise filter applies to 'default' group.
    - 'k' multiplies by 1,000; 'M' multiplies by 1,000,000.
    """
    match = re.match(r"^([a-zA-Z0-9_-]+)\.(\d+)(k|M)$", model_param, re.IGNORECASE)
    if not match:
        return None
    prefix, number, suffix = match.groups()
    min_context = int(number) * (1000 if suffix.lower() == "k" else 1000000)
    group = prefix if _GROUP_PATTERN.match(prefix) else "default"
    return group, min_context


def get_keys_with_context(
    keys: list[dict[str, Any]],
    group: str,
    min_context: int | None,
) -> list[dict[str, Any]]:
    """Filter keys by group and minimum context size."""
    filtered = [
        k
        for k in keys
        if k.get("group_name", "default") == group and k.get("is_active")
    ]
    if min_context is not None:
        filtered = [
            k
            for k in filtered
            if k.get("context_size") is None or k.get("context_size", 0) >= min_context
        ]
    return filtered
