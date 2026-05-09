from __future__ import annotations

import os
from typing import Any


def resolve_provider_value(provider_cfg: dict[str, Any], key: str) -> str:
    env_key = f"{key}_env"
    env_name = str(provider_cfg.get(env_key, "")).strip()
    if env_name:
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value
    return str(provider_cfg.get(key, "")).strip()


def resolved_provider_cfg(provider_cfg: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(provider_cfg)
    for key in ("name", "base_url"):
        value = resolve_provider_value(provider_cfg, key)
        if value:
            resolved[key] = value
    return resolved
