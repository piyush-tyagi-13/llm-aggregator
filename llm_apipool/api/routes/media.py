"""Media generation endpoints — /v1/images/generations and /v1/audio/speech.

Routes through the dispatch/rotator system, selecting keys whose
models are tagged with the required media capability.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    pass

from llm_apipool.api.errors import ROUTING_ERROR, error_response


class _ImageRequest(BaseModel):
    model_config = {"extra": "ignore"}
    model: str | None = "auto"
    prompt: str
    n: int | None = 1
    size: str | None = None
    quality: str | None = None
    response_format: str | None = None
    user: str | None = None


class _SpeechRequest(BaseModel):
    model_config = {"extra": "ignore"}
    model: str | None = "auto"
    input: str
    voice: str | None = "alloy"
    response_format: str | None = "mp3"
    speed: float | None = 1.0


def _create_media_router(
    store: Any, rotator: Any, configs: dict[str, Any], default_capabilities: list[str]
) -> APIRouter:
    from llm_apipool.providers.dispatch import complete as dispatch_complete

    router = APIRouter()

    @router.post("/v1/images/generations")
    async def image_generation(
        req: _ImageRequest,
        x_subscriber_id: Annotated[str | None, Header()] = None,
    ) -> Any:
        subscriber = x_subscriber_id or "images"
        caps = list(default_capabilities)
        if "image_generation" not in caps:
            caps.append("image_generation")

        # Find a key with image generation capability
        key_data = rotator.get_best_key(caps, subscriber_id=subscriber)
        if not key_data:
            return error_response(
                503,
                "No image-capable model available",
                ROUTING_ERROR,
                code="no_image_model",
            )

        provider = key_data.get("provider", "unknown")
        model = key_data.get("model", "unknown")

        # Forward to the provider via dispatch
        try:
            result, _kd = await dispatch_complete(
                rotator,
                capabilities=caps,
                messages=[{"role": "user", "content": req.prompt}],
                subscriber_id=subscriber,
                model=model,
                max_tokens=1024,
            )

            # Return the image prompt result — clients expect image URLs/b64
            # from the generation, but since we forward through chat models,
            # we return the generated description.
            return JSONResponse(
                content={
                    "created": int(time.time()),
                    "data": [
                        {
                            "url": None,
                            "b64_json": None,
                            "revised_prompt": req.prompt,
                            "content": result.text if result and result.text else None,
                            "provider": provider,
                        },
                    ],
                    "model": model,
                    "provider": provider,
                },
                headers={
                    "X-Routed-Via": f"{provider}/{model}",
                },
            )
        except Exception as exc:
            return error_response(502, f"Image generation error: {exc}", "server_error")

    @router.post("/v1/audio/speech")
    async def text_to_speech(
        req: _SpeechRequest,
        x_subscriber_id: Annotated[str | None, Header()] = None,
    ) -> Any:
        subscriber = x_subscriber_id or "speech"
        caps = list(default_capabilities)
        if "tts" not in caps:
            caps.append("tts")

        key_data = rotator.get_best_key(caps, subscriber_id=subscriber)
        if not key_data:
            return error_response(
                503,
                "No TTS-capable model available",
                ROUTING_ERROR,
                code="no_tts_model",
            )

        provider = key_data.get("provider", "unknown")
        model = key_data.get("model", "unknown")

        try:
            result, _kd = await dispatch_complete(
                rotator,
                capabilities=caps,
                messages=[
                    {"role": "user", "content": f"Generate speech for: {req.input}"}
                ],
                subscriber_id=subscriber,
                model=model,
                max_tokens=1024,
            )

            return JSONResponse(
                content={
                    "text": req.input,
                    "voice": req.voice,
                    "model": model,
                    "provider": provider,
                    "content": result.text if result and result.text else None,
                },
                headers={
                    "X-Routed-Via": f"{provider}/{model}",
                },
            )
        except Exception as exc:
            return error_response(
                502, f"Speech generation error: {exc}", "server_error"
            )

    return router


__all__ = ["_create_media_router"]
