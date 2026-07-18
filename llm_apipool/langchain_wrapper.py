"""LangChain-compatible wrapper for llm-apipool.

Drop into any LangChain pipeline as a chat model::

    from llm_apipool import AggregatorChat

    llm = AggregatorChat(
        capabilities=["general_purpose", "fast"],
        subscriber_id="mdcore.ingest",
    )

Config examples:

    # general inference
    AggregatorChat(capabilities=["general_purpose"])

    # hermes main loop - agentic models only
    AggregatorChat(capabilities=["agentic"], subscriber_id="hermes.main")

    # mdcore synthesis - fast formatter models
    AggregatorChat(capabilities=["general_purpose", "fast"], subscriber_id="mdcore.synth")

    # deprecated single-category style still works
    AggregatorChat(category="general_purpose")
"""

from __future__ import annotations


import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.json"


def _build_rotator(rotate_every: int = 5) -> Any:  # noqa: ANN401
    """Build a Rotator from the provider config file."""
    from .key_store import KeyStore  # noqa: PLC0415
    from .rotator import Rotator  # noqa: PLC0415

    with _CONFIG_PATH.open() as f:
        configs = json.load(f)["providers"]
    return Rotator(KeyStore(), configs, rotate_every=rotate_every)


def _msgs_to_dicts(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    role_map = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "chat": "user",
    }
    result = []
    for m in messages:
        role = role_map.get(m.type, "user")
        result.append({"role": role, "content": m.content})
    return result


def _run_async(coro: Any) -> Any:  # noqa: ANN401
    """Run async coroutine from sync context safely."""
    try:
        asyncio.get_running_loop()
        import concurrent.futures  # noqa: PLC0415

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)


class AggregatorChat(BaseChatModel):
    """LangChain ChatModel backed by llm-apipool.

    Handles key selection, rotation, 429 retries, and audit logging transparently.

    Parameters
    ----------
    capabilities : list[str]
        Key capabilities to draw from. Keys must have at least one matching
        capability. Defaults to ["general_purpose"].
        Known values: general_purpose, agentic, fast, code, vision, large_context.
    subscriber_id : str
        Identifier for this client, written to the audit log.
        Use a dotted hierarchy: "mdcore.ingest", "hermes.main", "mdcore.synth".
    max_tokens : int
        Maximum tokens to generate. Default 4096.
    temperature : float
        Sampling temperature. Default 0.7.
    rotate_every : int
        Number of requests before rotating to the next key. Default 5.

    """

    capabilities: list[str] = ["general_purpose"]  # noqa: RUF012
    subscriber_id: str = "unknown"
    max_tokens: int = 4096
    temperature: float = 0.7
    rotate_every: int = 5

    _rotator: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_rotator(self) -> Any:  # noqa: ANN401
        """Lazy-init and return the Rotator instance."""
        if self._rotator is None:
            self._rotator = _build_rotator(self.rotate_every)
        return self._rotator

    @property
    def _llm_type(self) -> str:
        return "llm_apipool"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": f"apipool/{','.join(self.capabilities)}",
            "capabilities": self.capabilities,
            "subscriber_id": self.subscriber_id,
        }

    def current_key(self) -> dict[str, Any] | None:
        """Return the key that would be selected for the next request.

        Does not make any API call or mutate rotation state.
        """
        return self._get_rotator().peek_current_key(self.capabilities)  # type: ignore[no-any-return]

    def pool_status(self) -> list[dict[str, Any]]:
        """Return current quota state for all active keys matching capabilities.

        Does not make any API call.
        """
        from .key_store import KeyStore  # noqa: PLC0415

        store = KeyStore()
        now = datetime.now(UTC).isoformat()
        keys = store.get_active_keys(self.capabilities)
        result = []
        for k in keys:
            cd = k.get("cooldown_until")
            available = not cd or cd < now
            result.append(
                {
                    "key_id": k["id"],
                    "provider": k["provider"],
                    "model": k["model"] or "(provider default)",
                    "capabilities": store.parse_capabilities(k),
                    "requests_today": k["requests_today"],
                    "tokens_used_today": k["tokens_used_today"],
                    "cooldown_until": cd,
                    "is_available": available,
                }
            )
        return result

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> ChatResult:
        return _run_async(
            self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )  # type: ignore[no-any-return]

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: Any | None = None,  # noqa: ARG002, ANN401
        **kwargs: Any,  # noqa: ANN401, ARG002
    ) -> ChatResult:
        from .providers.dispatch import complete as _complete  # noqa: PLC0415
        from .providers.base import CompletionResult

        msgs = _msgs_to_dicts(messages)
        result, key_data = await _complete(
            self._get_rotator(),
            capabilities=self.capabilities,
            messages=msgs,
            subscriber_id=self.subscriber_id,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        if not isinstance(result, CompletionResult):
            raise RuntimeError(
                "llm-apipool error: unexpected streaming result in non-streaming mode"
            )

        if result.error:
            msg = f"llm-apipool error: {result.error}"
            raise RuntimeError(msg)

        if key_data is None:
            raise RuntimeError("No key_data available from dispatch")
        model_name = key_data["model"] or key_data["provider"]
        tokens = result.tokens_used or 0

        ai_msg = AIMessage(
            content=result.text,
            usage_metadata={
                "input_tokens": 0,
                "output_tokens": tokens,
                "total_tokens": tokens,
            },
            response_metadata={
                "provider": key_data["provider"],
                "model": model_name,
                "model_name": model_name,
                "tokens_used": tokens,
                "requests_today": key_data.get("requests_today", 0) + 1,
                "tokens_used_today": key_data.get("tokens_used_today", 0) + tokens,
                "remaining_requests": result.remaining_requests,
                "key_id": key_data["key_id"],
                "subscriber_id": self.subscriber_id,
                "capabilities": key_data.get("capabilities", self.capabilities),
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=ai_msg)],
            llm_output={
                "model_name": model_name,
                "provider": key_data["provider"],
                "subscriber_id": self.subscriber_id,
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": tokens,
                    "total_tokens": tokens,
                },
            },
        )
