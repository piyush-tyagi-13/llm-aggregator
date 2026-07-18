"""Fallback manager implementing user-specified 3+3+3+next strategy."""

from __future__ import annotations

import time
from typing import Any


class AllModelsExhaustedError(Exception):
    """Raised when every candidate model has been tried and failed."""


class FallbackManager:
    """
    Implements config-driven fallback strategy (loaded from
    ``config/default_strategies.json``):
    - Phase 1: N attempts on same model + same key (only when no 429)
    - Phase 2: N attempts on same model + other keys from same provider
    - Phase 3: N attempts on same model + all other providers
    - Phase 4: Move to next model in priority order
    - If a model fails N times -> cooldown for M minutes
    """

    def __init__(self, store: Any):
        from ..config.loader import load_settings

        cfg = load_settings().fallback
        self.MAX_ATTEMPTS_SAME_KEY = cfg.max_attempts_same_key
        self.MAX_ATTEMPTS_SAME_PROVIDER = cfg.max_attempts_same_provider
        self.MAX_ATTEMPTS_ALL_PROVIDERS = cfg.max_attempts_all_providers
        self.COOLDOWN_ON_FAILURE_MS = cfg.cooldown_on_failure_ms
        self.store = store
        self._key_attempts: dict[int, int] = {}
        self._provider_attempts: dict[str, int] = {}
        self._model_attempts: dict[str, int] = {}

    def _reset(self) -> None:
        self._key_attempts.clear()
        self._provider_attempts.clear()
        self._model_attempts.clear()

    def _apply_cooldown(self, key_id: int, platform: str, model: str) -> None:
        now = time.time()
        expires_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now + 1800))
        self.store.record_usage(
            key_id, tokens=0, was_429=True, cooldown_until=expires_at
        )

    def _get_ordered_candidates(
        self,
        capabilities: list[str] | None = None,
        min_context: int | None = None,
        require_tools: bool | None = None,
        require_vision: bool | None = None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        chain = (
            self.store.get_enabled_models()
            if hasattr(self.store, "get_enabled_models")
            else []
        )
        for entry in chain:
            platform = entry.get("platform", "")
            model_id = entry.get("model_id", "")
            model_db_id = entry.get("model_db_id") or entry.get("id", 0)
            keys = self.store.get_active_keys(capabilities=capabilities or [])
            # Post-filter by additional constraints
            if platform:
                keys = [k for k in keys if k.get("provider") == platform]
            if model_id:
                keys = [k for k in keys if k.get("model") == model_id]
            if min_context is not None:
                keys = [
                    k for k in keys if (k.get("context_size") or 8192) >= min_context
                ]
            if require_tools is True:
                keys = [k for k in keys if "tools" in k.get("capabilities", "[]")]
            if require_vision is True:
                keys = [k for k in keys if "vision" in k.get("capabilities", "[]")]
            if keys:
                candidates.append(
                    {
                        "model_db_id": model_db_id,
                        "model_id": model_id,
                        "platform": platform,
                        "keys": list(keys),
                    }
                )
        return candidates

    def _should_skip_key(self, key_id: int) -> bool:
        return self._key_attempts.get(key_id, 0) >= self.MAX_ATTEMPTS_SAME_KEY

    def _should_skip_provider(self, platform: str) -> bool:
        return (
            self._provider_attempts.get(platform, 0) >= self.MAX_ATTEMPTS_SAME_PROVIDER
        )

    async def route_with_fallback(self, request: dict[str, Any]) -> Any:
        capabilities = request.get("capabilities", [])
        min_context = request.get("min_context")
        require_tools = request.get("require_tools")
        require_vision = request.get("require_vision")
        subscriber_id = request.get("subscriber_id", "unknown")
        messages = request.get("messages", [])

        candidates = self._get_ordered_candidates(
            capabilities=capabilities,
            min_context=min_context,
            require_tools=require_tools,
            require_vision=require_vision,
        )
        if not candidates:
            raise AllModelsExhaustedError("No candidate models available")

        for model_group in candidates:
            self._reset()
            model_id = model_group["model_id"]
            platform = model_group["platform"]
            keys = model_group["keys"]

            for key in keys:
                if self._should_skip_key(key["id"]):
                    continue
                result = await self._try_key(
                    key, model_id, platform, messages, subscriber_id
                )
                if result is not None:
                    return result

            if self._model_attempts.get(model_id, 0) > 0:
                for key in keys:
                    self._apply_cooldown(key["id"], platform, model_id)

        raise AllModelsExhaustedError(
            f"All models exhausted after {len(candidates)} candidates"
        )

    async def _try_key(
        self,
        key: dict[str, Any],
        model_id: str,
        platform: str,
        messages: list[dict[str, Any]],
        subscriber_id: str,
    ) -> Any:
        from ..providers.dispatch import call_complete as _call_complete

        key_id = key["id"]
        # Patch the key's model to the target model for this attempt
        key_data = {**key, "model": model_id}
        try:
            response = await _call_complete(
                key_data=key_data,
                messages=messages,
                subscriber_id=subscriber_id,
            )
            was_429 = False
            if isinstance(response, dict):
                was_429 = response.get("was_429", False)
            elif hasattr(response, "was_429"):
                was_429 = response.was_429

            if was_429:
                return None

            self._key_attempts[key_id] = self._key_attempts.get(key_id, 0) + 1
            self._provider_attempts[platform] = (
                self._provider_attempts.get(platform, 0) + 1
            )
            self._model_attempts[model_id] = self._model_attempts.get(model_id, 0) + 1
            return response
        except Exception:
            self._key_attempts[key_id] = self._key_attempts.get(key_id, 0) + 1
            self._provider_attempts[platform] = (
                self._provider_attempts.get(platform, 0) + 1
            )
            self._model_attempts[model_id] = self._model_attempts.get(model_id, 0) + 1
            return None
