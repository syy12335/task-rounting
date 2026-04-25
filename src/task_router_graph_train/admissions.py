from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .dataset.io import read_jsonl
from .runtime_adapter import validate_runtime_controller_action
from .types import SftAdmissionRow


def canonicalize_json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_admission_fingerprint(state_input: dict[str, Any], reference_action: dict[str, Any]) -> str:
    signature = canonicalize_json_payload(
        {
            "state_input": copy.deepcopy(state_input),
            "reference_action": copy.deepcopy(reference_action),
        }
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def load_admission_rows(path: Path | None) -> list[SftAdmissionRow]:
    if path is None:
        return []

    rows = read_jsonl(Path(path).resolve())
    admissions: list[SftAdmissionRow] = []
    seen: set[str] = set()
    for row in rows:
        sample_id = str(row.get("sample_id", "")).strip()
        reason = str(row.get("reason", "")).strip()
        if not sample_id or not reason or sample_id in seen:
            continue
        seen.add(sample_id)

        state_input = row.get("state_input", {})
        reference_action = row.get("reference_action", {})
        if not isinstance(state_input, dict) or not isinstance(reference_action, dict):
            continue

        valid, _ = validate_runtime_controller_action(reference_action)
        protocol_valid, _ = validate_protocol_action(reference_action) if valid else (False, [])
        if not valid or not protocol_valid:
            continue

        admissions.append(
            SftAdmissionRow(
                sample_id=sample_id,
                state_input=copy.deepcopy(state_input),
                reference_action=copy.deepcopy(reference_action),
                reason=reason,
                source_round=str(row.get("source_round", "")).strip(),
            )
        )
    return admissions


def validate_protocol_action(action: dict[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(action, dict):
        return False, ["action must be an object"]

    action_kind = str(action.get("action_kind", "")).strip()
    if action_kind == "observe":
        tool = str(action.get("tool", "")).strip()
        args = action.get("args", {})
        if not isinstance(args, dict):
            return False, ["observe.args must be an object"]
        if tool in {"previous_failed_track", "beijing_time"} and args:
            return False, [f"{tool} args must be empty object"]
        if tool == "build_context_view" and _coerce_truthy(args.get("include_trace", False)):
            return False, ["build_context_view.include_trace must be false in controller protocol"]
        return True, []

    if action_kind == "generate_task":
        task_content = str(action.get("task_content", "")).strip()
        lines = [line.strip() for line in task_content.splitlines() if line.strip()]
        if len(lines) != 2:
            return False, ["generate_task.task_content must be exactly two non-empty lines"]
        if not lines[0].startswith("用户目标："):
            return False, ["generate_task.task_content line 1 must start with 用户目标："]
        if not lines[1].startswith("任务限制："):
            return False, ["generate_task.task_content line 2 must start with 任务限制："]
        return True, []

    return False, [f"unsupported action_kind for protocol validation: {action_kind or '<missing>'}"]


def _coerce_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False
