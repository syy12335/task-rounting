from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .artifacts import PREFERENCE_ADMISSIONS_ARTIFACT_TYPE, TEACHER_DECISIONS_ARTIFACT_TYPE, to_safe_path, utc_now_iso, write_json
from .dataset import read_jsonl, render_controller_target_text, write_jsonl
from .rounds import load_round_manifest, resolve_round_asset_path
from .train.controller_grpo_teacher import (
    parse_candidate_action,
    resolve_teacher_config,
    review_badcase_for_preference,
    validate_action_dict,
    validate_protocol_action,
)
from .types import PreferenceAdmissionRow, TeacherQueueRow

DEFAULT_FEEDBACK_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "controller_grpo_online.yaml"


def enqueue_teacher_queue(
    *,
    round_id: str | None = None,
    round_manifest: Path | None = None,
    candidates_path: Path,
) -> dict[str, Any]:
    manifest = load_round_manifest(round_id=round_id, manifest_path=round_manifest)
    queue_path = resolve_round_asset_path(manifest, "teacher_queue")

    input_rows = read_jsonl(Path(candidates_path).resolve())
    selected = _select_teacher_queue_rows(input_rows)

    existing = read_jsonl(queue_path) if queue_path.exists() and queue_path.read_text(encoding="utf-8").strip() else []
    existing_keys = {str(row.get("dedup_key", "")).strip() for row in existing}
    appended: list[dict[str, Any]] = []
    for row in selected:
        payload = row.to_dict()
        if payload["dedup_key"] in existing_keys:
            continue
        appended.append(payload)
        existing_keys.add(payload["dedup_key"])

    merged = existing + appended
    write_jsonl(queue_path, merged)
    _update_round_manifest(
        manifest,
        queue_count=len(merged),
        preference_count=None,
        dedup_count=len(appended),
    )
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "input_count": len(input_rows),
        "queued_count": len(appended),
        "teacher_queue_count": len(merged),
        "teacher_queue_path": to_safe_path(queue_path),
    }


def admit_preference_admissions(
    *,
    round_id: str | None = None,
    round_manifest: Path | None = None,
    teacher_decisions_path: Path,
) -> dict[str, Any]:
    manifest = load_round_manifest(round_id=round_id, manifest_path=round_manifest)
    admissions_path = resolve_round_asset_path(manifest, "preference_admissions")
    decision_rows = read_jsonl(Path(teacher_decisions_path).resolve())

    valid_admissions: list[PreferenceAdmissionRow] = []
    for row in decision_rows:
        if not bool(row.get("admission", False)):
            continue
        preference = _build_preference_admission_from_decision(
            row=row,
            fallback_source_round=str(manifest.get("round_id", round_id or "")),
        )
        if preference is not None:
            valid_admissions.append(preference)

    existing = read_jsonl(admissions_path) if admissions_path.exists() and admissions_path.read_text(encoding="utf-8").strip() else []
    seen_fingerprints = {_build_preference_fingerprint_from_payload(row) for row in existing}
    appended: list[dict[str, Any]] = []
    for row in valid_admissions:
        payload = row.to_dict()
        fingerprint = build_preference_fingerprint(row.state_input, row.chosen_response, row.rejected_raw_text)
        if fingerprint in seen_fingerprints:
            continue
        payload.setdefault("metadata", {})["preference_fingerprint"] = fingerprint
        appended.append(payload)
        seen_fingerprints.add(fingerprint)

    merged = existing + appended
    write_jsonl(admissions_path, merged)
    _update_round_manifest(
        manifest,
        queue_count=None,
        preference_count=len(merged),
        dedup_count=len(appended),
    )
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "input_count": len(decision_rows),
        "admitted_count": len(appended),
        "preference_admissions_count": len(merged),
        "preference_admissions_path": to_safe_path(admissions_path),
    }


def annotate_teacher_queue(
    *,
    round_id: str | None = None,
    round_manifest: Path | None = None,
    config_path: Path | None = None,
    limit: int | None = None,
    output_decisions_path: Path | None = None,
) -> dict[str, Any]:
    manifest = load_round_manifest(round_id=round_id, manifest_path=round_manifest)
    queue_path = resolve_round_asset_path(manifest, "teacher_queue")
    queue_rows = read_jsonl(queue_path) if queue_path.exists() and queue_path.read_text(encoding="utf-8").strip() else []
    if limit is not None and limit >= 0:
        queue_rows = queue_rows[:limit]

    config = _load_feedback_config(config_path)
    teacher_config = resolve_teacher_config(config, role="admission_judge")
    decisions_path = output_decisions_path.resolve() if output_decisions_path is not None else (Path(str(manifest["_round_dir"])) / "teacher_decisions.jsonl").resolve()

    decisions: list[dict[str, Any]] = []
    for row in queue_rows:
        sample_id = str(row.get("sample_id", "")).strip()
        state_input = row.get("state_input", {})
        policy_output = row.get("policy_output", {})
        rejected_raw_text = _resolve_rejected_raw_text(row)
        if not sample_id or not isinstance(state_input, dict) or not isinstance(policy_output, dict) or not rejected_raw_text:
            continue
        decision = review_badcase_for_preference(
            sample_id=sample_id,
            state_input=copy.deepcopy(state_input),
            policy_output=copy.deepcopy(policy_output),
            policy_output_raw_text=rejected_raw_text,
            source=str(row.get("source", "")).strip(),
            trigger_reason=str(row.get("trigger_reason", "")).strip(),
            teacher_config=teacher_config,
        )
        decision["state_input"] = copy.deepcopy(state_input)
        decision["rejected_response"] = copy.deepcopy(policy_output)
        decision["rejected_raw_text"] = rejected_raw_text
        decision["source"] = str(row.get("source", "")).strip()
        decision["trigger_reason"] = str(row.get("trigger_reason", "")).strip()
        decision["source_round"] = str(manifest.get("round_id", round_id or ""))
        decision["queue_metadata"] = copy.deepcopy(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
        decisions.append(decision)

    write_jsonl(decisions_path, decisions)
    preference_report = admit_preference_admissions(round_manifest=Path(str(manifest["_manifest_path"])), teacher_decisions_path=decisions_path)
    _update_round_manifest(
        manifest,
        queue_count=None,
        preference_count=preference_report["preference_admissions_count"],
        dedup_count=preference_report["admitted_count"],
    )
    manifest_path = Path(str(manifest.get("_manifest_path", ""))).resolve()
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest_payload.setdefault("assets", {})
    assets["teacher_decisions"] = {
        "artifact_type": TEACHER_DECISIONS_ARTIFACT_TYPE,
        "path": str(decisions_path),
    }
    assets["preference_admissions"] = {
        "artifact_type": PREFERENCE_ADMISSIONS_ARTIFACT_TYPE,
        "path": str(resolve_round_asset_path(manifest, "preference_admissions")),
    }
    write_json(manifest_path, manifest_payload)
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "teacher_queue_count": len(queue_rows),
        "decision_count": len(decisions),
        "teacher_decisions_path": to_safe_path(decisions_path),
        "preference_admissions_count": preference_report["preference_admissions_count"],
        "preference_admissions_path": preference_report["preference_admissions_path"],
    }


def build_preference_fingerprint(state_input: dict[str, Any], chosen_response: dict[str, Any], rejected_raw_text: str) -> str:
    signature = json.dumps(
        {
            "state_input": copy.deepcopy(state_input),
            "chosen_response": copy.deepcopy(chosen_response),
            "rejected_raw_text": str(rejected_raw_text),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _build_preference_admission_from_decision(*, row: dict[str, Any], fallback_source_round: str) -> PreferenceAdmissionRow | None:
    sample_id = str(row.get("sample_id", "")).strip()
    teacher_reason = str(row.get("reason") or row.get("teacher_reason", "")).strip()
    state_input = row.get("state_input", {})
    chosen_response = row.get("chosen_response")
    if not isinstance(chosen_response, dict):
        chosen_response = row.get("gold_case")
    rejected_response = row.get("rejected_response", {})
    rejected_raw_text = str(row.get("rejected_raw_text", "")).strip()
    if not sample_id or not teacher_reason or not isinstance(state_input, dict):
        return None
    if not isinstance(chosen_response, dict) or not isinstance(rejected_response, dict) or not rejected_raw_text:
        return None

    schema_valid, _ = validate_action_dict(chosen_response)
    protocol_valid, _ = validate_protocol_action(chosen_response) if schema_valid else (False, [])
    if not schema_valid or not protocol_valid:
        return None

    try:
        confidence = float(row.get("confidence", 1.0))
    except (TypeError, ValueError):
        return None

    queue_metadata = row.get("queue_metadata", {})
    metadata = copy.deepcopy(queue_metadata) if isinstance(queue_metadata, dict) else {}
    metadata.update(
        {
            "chosen_source": str(row.get("chosen_source", "teacher_gold")).strip() or "teacher_gold",
            "rejected_source": str(row.get("rejected_source", "policy_output")).strip() or "policy_output",
            "hard_gate_failure": _resolve_hard_gate_failure(row),
        }
    )
    return PreferenceAdmissionRow(
        sample_id=sample_id,
        state_input=copy.deepcopy(state_input),
        chosen_response=copy.deepcopy(chosen_response),
        chosen_raw_text=render_controller_target_text(chosen_response),
        rejected_response=copy.deepcopy(rejected_response),
        rejected_raw_text=rejected_raw_text,
        source=str(row.get("source", "")).strip() or "unknown",
        trigger_reason=str(row.get("trigger_reason", "")).strip(),
        source_round=str(row.get("source_round", fallback_source_round)).strip() or fallback_source_round,
        teacher_reason=teacher_reason,
        confidence=confidence,
        metadata=metadata,
    )


def _select_teacher_queue_rows(rows: list[dict[str, Any]]) -> list[TeacherQueueRow]:
    explicit_failures: list[TeacherQueueRow] = []
    grouped_candidates: dict[str, list[dict[str, Any]]] = {}

    for index, raw in enumerate(rows, start=1):
        sample_id = str(raw.get("sample_id", "")).strip() or f"badcase_{index:06d}"
        state_input = raw.get("state_input", {})
        if not isinstance(state_input, dict):
            continue
        policy_output, raw_text, raw_text_is_fallback = _extract_policy_payload(raw)
        trigger_reason = str(raw.get("trigger_reason", "")).strip()
        source = str(raw.get("source", "")).strip() or "unknown"
        parse_ok, schema_ok, protocol_ok = _resolve_gate_flags(raw=raw, policy_output=policy_output)
        metadata = _build_queue_metadata(raw=raw, raw_text_is_fallback=raw_text_is_fallback)

        if _is_explicit_failure(raw=raw, policy_output=policy_output):
            explicit_failures.append(
                TeacherQueueRow(
                    sample_id=sample_id,
                    source=source,
                    trigger_reason=trigger_reason or "explicit_failure",
                    state_input=copy.deepcopy(state_input),
                    policy_output=copy.deepcopy(policy_output),
                    policy_output_raw_text=raw_text,
                    parse_ok=parse_ok,
                    schema_ok=schema_ok,
                    protocol_ok=protocol_ok,
                    dedup_key=str(raw.get("dedup_key", "")).strip() or _build_dedup_key(state_input, policy_output, raw_text),
                    metadata=metadata,
                )
            )
            continue

        group_id = str(raw.get("group_id", "")).strip()
        if group_id:
            grouped_candidates.setdefault(group_id, []).append(
                {
                    "sample_id": sample_id,
                    "source": source,
                    "trigger_reason": trigger_reason or "rollout_group_worst",
                    "state_input": copy.deepcopy(state_input),
                    "policy_output": copy.deepcopy(policy_output),
                    "policy_output_raw_text": raw_text,
                    "parse_ok": parse_ok,
                    "schema_ok": schema_ok,
                    "protocol_ok": protocol_ok,
                    "teacher_rank": int(raw.get("teacher_rank", raw.get("rank", 0)) or 0),
                    "dedup_key": str(raw.get("dedup_key", "")).strip() or _build_dedup_key(state_input, policy_output, raw_text),
                    "metadata": metadata,
                }
            )

    selected = list(explicit_failures)
    for rows in grouped_candidates.values():
        worst = sorted(rows, key=lambda item: (item["teacher_rank"], item["sample_id"]), reverse=True)[0]
        selected.append(
            TeacherQueueRow(
                sample_id=worst["sample_id"],
                source=worst["source"],
                trigger_reason=worst["trigger_reason"],
                state_input=copy.deepcopy(worst["state_input"]),
                policy_output=copy.deepcopy(worst["policy_output"]),
                policy_output_raw_text=worst["policy_output_raw_text"],
                parse_ok=bool(worst["parse_ok"]),
                schema_ok=bool(worst["schema_ok"]),
                protocol_ok=bool(worst["protocol_ok"]),
                dedup_key=worst["dedup_key"],
                metadata=copy.deepcopy(worst["metadata"]),
            )
        )

    return selected


def _extract_policy_payload(row: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    for raw_key in ("policy_output_raw_text", "policy_output_text", "prediction_raw_text", "raw_text", "response"):
        raw_text = row.get(raw_key)
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        parsed, _ = parse_candidate_action(raw_text)
        return (copy.deepcopy(parsed) if isinstance(parsed, dict) else _extract_policy_output_dict(row), raw_text, False)

    if isinstance(row.get("prediction"), str):
        raw_text = str(row["prediction"])
        parsed, _ = parse_candidate_action(raw_text)
        return (copy.deepcopy(parsed) if isinstance(parsed, dict) else _extract_policy_output_dict(row), raw_text, False)

    policy_output = _extract_policy_output_dict(row)
    if policy_output:
        return policy_output, render_controller_target_text(policy_output), True
    return {}, "", False


def _extract_policy_output_dict(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("policy_output", "policy_output_action", "prediction"):
        if isinstance(row.get(key), dict):
            return copy.deepcopy(row[key])
    return {}


def _resolve_gate_flags(*, raw: dict[str, Any], policy_output: dict[str, Any]) -> tuple[bool, bool, bool]:
    parse_ok = raw.get("parse_ok")
    schema_ok = raw.get("schema_ok")
    protocol_ok = raw.get("protocol_ok")
    if parse_ok is None:
        parse_ok = bool(policy_output)
    if schema_ok is None:
        valid, _ = validate_action_dict(policy_output) if policy_output else (False, [])
        schema_ok = valid
    if protocol_ok is None:
        protocol_valid, _ = validate_protocol_action(policy_output) if bool(schema_ok) and policy_output else (False, [])
        protocol_ok = protocol_valid
    return bool(parse_ok), bool(schema_ok), bool(protocol_ok)


def _is_explicit_failure(*, raw: dict[str, Any], policy_output: dict[str, Any]) -> bool:
    normalized_reason = str(raw.get("trigger_reason", "")).strip().lower()
    if normalized_reason in {
        "parse_failed",
        "schema_failed",
        "protocol_failed",
        "holdout_failed",
        "user_negative_feedback",
        "environment_conflict",
        "hidden_fact_dependency",
    }:
        return True

    parse_ok = raw.get("parse_ok")
    schema_ok = raw.get("schema_ok")
    protocol_ok = raw.get("protocol_ok")
    if parse_ok is False or schema_ok is False or protocol_ok is False:
        return True

    if not policy_output:
        return True
    valid, _ = validate_action_dict(policy_output)
    return not valid


def _resolve_rejected_raw_text(row: dict[str, Any]) -> str:
    raw_text = str(row.get("policy_output_raw_text", "")).strip()
    if raw_text:
        return raw_text
    policy_output = row.get("policy_output", {})
    if isinstance(policy_output, dict) and policy_output:
        return render_controller_target_text(policy_output)
    return ""


def _build_dedup_key(state_input: dict[str, Any], policy_output: dict[str, Any], raw_text: str) -> str:
    user_input = str(state_input.get("USER_INPUT", "")).strip()
    environment = state_input.get("ENVIRONMENT_JSON", {}) if isinstance(state_input.get("ENVIRONMENT_JSON", {}), dict) else {}
    action_kind = str(policy_output.get("action_kind", "")).strip()
    tool = str(policy_output.get("tool", "")).strip()
    task_type = str(policy_output.get("task_type", "")).strip()
    signature = json.dumps(
        {
            "user_input": user_input,
            "environment": environment,
            "action_kind": action_kind,
            "tool": tool,
            "task_type": task_type,
            "raw_text": str(raw_text),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _build_queue_metadata(*, raw: dict[str, Any], raw_text_is_fallback: bool) -> dict[str, Any]:
    metadata = copy.deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), dict) else {}
    raw_fallback = raw.get("policy_output_raw_text_is_fallback", raw.get("prediction_raw_text_is_fallback", raw_text_is_fallback))
    metadata["policy_output_raw_text_is_fallback"] = bool(raw_fallback)
    return metadata


def _build_preference_fingerprint_from_payload(row: dict[str, Any]) -> str:
    metadata = row.get("metadata", {})
    if isinstance(metadata, dict):
        existing = str(metadata.get("preference_fingerprint", "")).strip()
        if existing:
            return existing
    state_input = row.get("state_input", {}) if isinstance(row.get("state_input", {}), dict) else {}
    chosen_response = row.get("chosen_response", {}) if isinstance(row.get("chosen_response", {}), dict) else {}
    return build_preference_fingerprint(state_input, chosen_response, str(row.get("rejected_raw_text", "")))


def _resolve_hard_gate_failure(row: dict[str, Any]) -> str:
    trigger = str(row.get("trigger_reason", "")).strip()
    if trigger in {"parse_failed", "schema_failed", "protocol_failed"}:
        return trigger.replace("_failed", "")
    return ""


def _update_round_manifest(
    manifest: dict[str, Any],
    *,
    queue_count: int | None,
    preference_count: int | None,
    dedup_count: int,
) -> None:
    counts = manifest.setdefault("counts_by_split", {})
    if not isinstance(counts, dict):
        counts = {}
        manifest["counts_by_split"] = counts
    if queue_count is not None:
        counts["teacher_queue"] = int(queue_count)
    if preference_count is not None:
        counts["preference_admissions"] = int(preference_count)

    dedup = manifest.setdefault("dedup", {})
    if isinstance(dedup, dict):
        dedup["last_append_count"] = int(dedup_count)

    manifest["updated_at"] = utc_now_iso()
    path = Path(str(manifest.get("_manifest_path", ""))).resolve()
    payload = {key: value for key, value in manifest.items() if not str(key).startswith("_")}
    write_json(path, payload)


def _load_feedback_config(config_path: Path | None) -> dict[str, Any]:
    effective_path = (config_path or DEFAULT_FEEDBACK_CONFIG_PATH).resolve()
    payload = yaml.safe_load(effective_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"feedback config must be a mapping: {effective_path}")
    return payload
