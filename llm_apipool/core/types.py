"""Shared type definitions for llm-apipool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KeyData:
    """Typed key data used throughout the routing and dispatch pipeline.

    Fields
    ------
    api_key:
        The raw API key string.
    provider:
        Provider/platform name (e.g. ``"groq"``, ``"openai"``).
    model:
        Model identifier to use.
    key_id:
        Database row id for the key.
    base_url:
        Base URL for the provider API.
    no_auth:
        Whether the provider requires no authentication.
    openai_compatible:
        Whether the provider speaks the OpenAI chat-completions format.
    capabilities:
        List of capability tags (e.g. ``["general_purpose", "fast"]``).
    extra_params:
        Provider-specific extra parameters (stored as JSON in DB).
    cap_key:
        Sorted comma-joined capabilities used as a rotation key.
    requests_today:
        Number of requests made with this key today.
    cycle_position:
        Current position in the key rotation cycle.
    rotate_every:
        Requests per key before rotating.
    account_id:
        Account identifier (used for URL templating like ``{account_id}``).
    base_url_override:
        Per-key base URL override.
    rpm_limit:
        Per-key requests-per-minute limit override.
    rpd_limit:
        Per-key requests-per-day limit override.
    cooldown_until:
        Unix timestamp until which the key is in cooldown, or ``None``.
    """

    api_key: str
    provider: str
    model: str | None = None
    key_id: int = 0
    base_url: str = ""
    no_auth: bool = False
    openai_compatible: bool = True
    capabilities: list[str] = field(default_factory=list)
    extra_params: dict[str, Any] = field(default_factory=dict)
    cap_key: str = "general_purpose"
    requests_today: int = 0
    cycle_position: int = 0
    rotate_every: int = 0
    account_id: str | None = None
    # Provider-specific overrides
    base_url_override: str | None = None
    rpm_limit: int | None = None
    rpd_limit: int | None = None
    # Cooldown state
    cooldown_until: float | None = None

    def masked_key(self) -> str:
        """Return a masked version of the API key (first 4 + last 4 chars visible)."""
        if len(self.api_key) <= 8:
            return self.api_key[:4] + "..."
        return (
            self.api_key[:4]
            + "*" * (len(self.api_key) - 8)
            + self.api_key[-4:]
        )


__all__ = ["KeyData"]
