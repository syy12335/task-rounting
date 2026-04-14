from __future__ import annotations

import json
import re
import time
from typing import Any


FIXED_TEST_AGENT_MOCK_SLEEP_SEC = 5.0


def sleep_for_test_agent_mock() -> float:
    # Placeholder delay for mock test agents to simulate long-running workflow execution.
    time.sleep(FIXED_TEST_AGENT_MOCK_SLEEP_SEC)
    return FIXED_TEST_AGENT_MOCK_SLEEP_SEC


def extract_text(content: Any) -> str:
    # 兼容不同 LLM SDK 的 content 结构，统一提取为纯文本。
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    return str(content).strip()


def replace_last(text: str, old: str, new: str) -> str:
    head, sep, tail = text.rpartition(old)
    if not sep:
        raise ValueError(f"placeholder not found: {old}")
    return head + new + tail


def merge_invoke_config(
    base_config: dict[str, Any] | None,
    *,
    run_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(base_config or {})

    if run_name:
        config["run_name"] = run_name

    if tags:
        existing_tags = config.get("tags", [])
        if not isinstance(existing_tags, list):
            existing_tags = []
        merged_tags: list[str] = []
        for item in list(existing_tags) + tags:
            value = str(item).strip()
            if value and value not in merged_tags:
                merged_tags.append(value)
        config["tags"] = merged_tags

    if metadata:
        existing_metadata = config.get("metadata", {})
        if not isinstance(existing_metadata, dict):
            existing_metadata = {}
        config["metadata"] = {**existing_metadata, **metadata}

    return config


def _extract_first_json_object(text: str) -> str | None:
    in_string = False
    escape = False
    depth = 0
    start = -1

    for idx, ch in enumerate(text):
        if start < 0:
            if ch == "{":
                start = idx
                depth = 1
            continue

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def parse_json_object(text: str) -> dict[str, Any]:
    # 将模型输出强约束为 JSON object，兼容常见 markdown 包裹格式。
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Model output is empty")

    candidates: list[str] = [raw]

    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        fenced = fence_match.group(1).strip()
        if fenced:
            candidates.append(fenced)

    for match in re.findall(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL):
        snippet = match.strip()
        if snippet:
            candidates.append(snippet)

    extracted = _extract_first_json_object(raw)
    if extracted:
        candidates.append(extracted)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(payload, dict):
            raise ValueError("Model output JSON is not an object")
        return payload

    raise ValueError(f"Model output is not a valid JSON object: {raw[:200]}")
