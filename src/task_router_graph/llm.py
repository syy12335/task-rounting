from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .provider_config import resolve_provider_value, resolved_provider_cfg


def resolve_provider_and_model(config: dict[str, Any]) -> tuple[str, str]:
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        raise ValueError("config.model must be a mapping")

    providers = model_cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("model.providers must be a non-empty mapping")

    provider_env = str(model_cfg.get("provider_env", "MODEL_PROVIDER")).strip() or "MODEL_PROVIDER"
    default_provider = str(model_cfg.get("provider", "")).strip()
    selected_provider = os.getenv(provider_env, default_provider).strip()
    if not selected_provider:
        raise ValueError(
            "No provider selected. Configure model.provider or set env "
            f"{provider_env}."
        )

    provider_cfg = providers.get(selected_provider)
    if not isinstance(provider_cfg, dict):
        supported = ", ".join(sorted(str(k) for k in providers.keys()))
        raise ValueError(
            f"Unknown model provider {selected_provider}. "
            f"Supported providers: {supported}"
        )

    model_name = resolve_provider_value(provider_cfg, "name")
    if not model_name:
        raise ValueError(f"Provider {selected_provider} missing model name")

    return selected_provider, model_name


def _is_local_base_url(base_url: str) -> bool:
    try:
        host = (urlparse(base_url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def _resolve_api_key(*, selected_provider: str, provider_cfg: dict[str, Any], base_url: str) -> str:
    api_key_env = str(provider_cfg.get("api_key_env", "")).strip()
    api_key = os.getenv(api_key_env) if api_key_env else ""
    if api_key:
        return api_key

    explicit_api_key = str(provider_cfg.get("api_key", "")).strip()
    if explicit_api_key:
        return explicit_api_key

    allow_missing = bool(provider_cfg.get("allow_missing_api_key", False))
    if allow_missing or selected_provider == "sglang" or _is_local_base_url(base_url):
        # 本地 OpenAI-compatible 服务通常不做鉴权；统一回退占位 key。
        return "EMPTY"

    if api_key_env:
        raise ValueError(f"Missing required environment variable: {api_key_env}")

    raise ValueError(f"Provider {selected_provider} missing api_key_env")


def build_chat_model(config: dict[str, Any]) -> Any:
    # 延迟导入，避免在纯数据处理场景下强依赖 langchain-openai。
    from langchain_openai import ChatOpenAI

    selected_provider, model_name = resolve_provider_and_model(config)

    model_cfg = config["model"]
    providers = model_cfg["providers"]
    provider_cfg = resolved_provider_cfg(providers[selected_provider])

    base_url = str(provider_cfg.get("base_url", "")).strip()
    if not base_url:
        raise ValueError(f"Provider {selected_provider} missing base_url")

    api_key = _resolve_api_key(
        selected_provider=selected_provider,
        provider_cfg=provider_cfg,
        base_url=base_url,
    )

    temperature = float(model_cfg.get("temperature", provider_cfg.get("temperature", 0)))

    request_timeout_sec = float(
        provider_cfg.get(
            "request_timeout_sec",
            model_cfg.get("request_timeout_sec", model_cfg.get("timeout_sec", 90)),
        )
    )
    max_retries = int(provider_cfg.get("max_retries", model_cfg.get("max_retries", 1)))

    # 限制单次生成长度，避免请求长时间卡在解码阶段。
    max_tokens_raw = provider_cfg.get("max_tokens", model_cfg.get("max_tokens", 0))
    max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else 0

    chat_kwargs: dict[str, Any] = {
        "model": model_name,
        "base_url": base_url,
        "api_key": api_key,
        "temperature": temperature,
        "timeout": request_timeout_sec,
        "max_retries": max_retries,
    }
    if max_tokens > 0:
        chat_kwargs["max_tokens"] = max_tokens

    return ChatOpenAI(**chat_kwargs)
