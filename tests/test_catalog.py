from __future__ import annotations

from llm_apipool.core.catalog import get_model_info, list_models, list_providers


def test_list_providers_returns_list():
    result = list_providers()
    assert isinstance(result, list)
    assert len(result) > 0
    assert "name" in result[0]
    assert "base_url" in result[0]


def test_get_model_info_known():
    info = get_model_info("groq", "llama-3.3-70b-versatile")
    assert info is not None, "get_model_info should return data for known model"
    assert "platform" in info
    assert "context_window" in info


def test_get_model_info_unknown():
    info = get_model_info("nonexistent_provider", "nonexistent_model")
    assert info is None


def test_list_models_returns_list():
    models = list_models()
    assert isinstance(models, list)
    assert len(models) > 0
    for model in models:
        assert "platform" in model
        assert "model_id" in model
        assert "display_name" in model


def test_list_models_by_provider():
    models = list_models(platform="groq")
    for model in models:
        assert model["platform"] == "groq"


def test_list_models_nonexistent_provider():
    models = list_models(platform="nonexistent")
    assert models == []
