from __future__ import annotations

import sys
import types

from task_router_graph.llm import build_chat_model, resolve_provider_and_model


def _config() -> dict:
    return {
        "model": {
            "provider": "sglang",
            "provider_env": "MODEL_PROVIDER",
            "temperature": 0,
            "providers": {
                "sglang": {
                    "name": "qwen3-4b",
                    "name_env": "SGLANG_MODEL",
                    "base_url": "http://127.0.0.1:30000/v1",
                    "base_url_env": "SGLANG_BASE_URL",
                    "api_key_env": "SGLANG_API_KEY",
                }
            },
        }
    }


def test_resolve_provider_and_model_prefers_name_env(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("SGLANG_MODEL", "qwen-local")

    provider, model = resolve_provider_and_model(_config())

    assert provider == "sglang"
    assert model == "qwen-local"


def test_build_chat_model_prefers_base_url_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("SGLANG_MODEL", "qwen-local")
    monkeypatch.setenv("SGLANG_BASE_URL", "http://127.0.0.1:31000/v1")
    monkeypatch.setenv("SGLANG_API_KEY", "EMPTY")

    build_chat_model(_config())

    assert captured["model"] == "qwen-local"
    assert captured["base_url"] == "http://127.0.0.1:31000/v1"
