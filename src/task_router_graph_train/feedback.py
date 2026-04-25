from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .admissions import build_admission_fingerprint, load_admission_rows
from .artifacts import TEACHER_DECISIONS_ARTIFACT_TYPE, to_safe_path, utc_now_iso, write_json
from .dataset import load_manual_protocol_samples, read_jsonl, write_jsonl
from .rounds import load_round_manifest, resolve_round_asset_path
from .runtime_adapter import build_controller_state_input, validate_runtime_controller_action
from .train.controller_grpo_teacher import parse_candidate_action, resolve_teacher_config, review_badcase_for_sft, validate_protocol_action
from .types import SftAdmissionRow, TeacherQueueRow
import yaml

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
        admissions_count=None,
        dedup_count=len(appended),
    )
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "input_count": len(input_rows),
        "queued_count": len(appended),
        "teacher_queue_count": len(merged),
        "teacher_queue_path": to_safe_path(queue_path),
    }


def admit_sft_admissions(
    *,
    round_id: str | None = None,
    round_manifest: Path | None = None,
    teacher_decisions_path: Path,
) -> dict[str, Any]:
    manifest = load_round_manifest(round_id=round_id, manifest_path=round_manifest)
    admissions_path = resolve_round_asset_path(manifest, "sft_admissions")

    decision_rows = read_jsonl(Path(teacher_decisions_path).resolve())
    valid_admissions: list[SftAdmissionRow] = []
    for row in decision_rows:
        if not bool(row.get("admission", False)):
            continue
        sample_id = str(row.get("sample_id", "")).strip()
        reason = str(row.get("reason", "")).strip()
        state_input = row.get("state_input", {})
        reference_action = row.get("reference_action", {})
        if not sample_id or not reason or not isinstance(state_input, dict) or not isinstance(reference_action, dict):
            continue
        valid, _ = validate_runtime_controller_action(reference_action)
        protocol_valid, _ = validate_protocol_action(reference_action) if valid else (False, [])
        if not valid or not protocol_valid:
            continue
        valid_admissions.append(
            SftAdmissionRow(
                sample_id=sample_id,
                state_input=copy.deepcopy(state_input),
                reference_action=copy.deepcopy(reference_action),
                reason=reason,
                source_round=str(row.get("source_round", manifest.get("round_id", round_id or ""))).strip()
                or str(manifest.get("round_id", round_id or "")),
            )
        )

    existing = read_jsonl(admissions_path) if admissions_path.exists() and admissions_path.read_text(encoding="utf-8").strip() else []
    seen_ids = {str(row.get("sample_id", "")).strip() for row in existing}
    seen_fingerprints = _collect_round_training_fingerprints(manifest)
    appended: list[dict[str, Any]] = []
    for row in valid_admissions:
        payload = row.to_dict()
        fingerprint = build_admission_fingerprint(row.state_input, row.reference_action)
        if payload["sample_id"] in seen_ids or fingerprint in seen_fingerprints:
            continue
        appended.append(payload)
        seen_ids.add(payload["sample_id"])
        seen_fingerprints.add(fingerprint)

    merged = existing + appended
    write_jsonl(admissions_path, merged)
    _update_round_manifest(
        manifest,
        queue_count=None,
        admissions_count=len(merged),
        dedup_count=len(appended),
    )
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "input_count": len(decision_rows),
        "admitted_count": len(appended),
        "sft_admissions_count": len(merged),
        "sft_admissions_path": to_safe_path(admissions_path),
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
        if not sample_id or not isinstance(state_input, dict) or not isinstance(policy_output, dict):
            continue
        decision = review_badcase_for_sft(
            sample_id=sample_id,
            state_input=copy.deepcopy(state_input),
            policy_output=copy.deepcopy(policy_output),
            source=str(row.get("source", "")).strip(),
            trigger_reason=str(row.get("trigger_reason", "")).strip(),
            teacher_config=teacher_config,
        )
        decision["state_input"] = copy.deepcopy(state_input)
        decision["source_round"] = str(manifest.get("round_id", round_id or ""))
        decisions.append(decision)

    write_jsonl(decisions_path, decisions)
    admission_report = admit_sft_admissions(round_manifest=Path(str(manifest["_manifest_path"])), teacher_decisions_path=decisions_path)
    _update_round_manifest(
        manifest,
        queue_count=None,
        admissions_count=admission_report["sft_admissions_count"],
        dedup_count=len(decisions),
    )
    manifest_path = Path(str(manifest.get("_manifest_path", ""))).resolve()
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest_payload.setdefault("assets", {})
    assets["teacher_decisions"] = {
        "artifact_type": TEACHER_DECISIONS_ARTIFACT_TYPE,
        "path": str(decisions_path),
    }
    write_json(manifest_path, manifest_payload)
    return {
        "round_id": str(manifest.get("round_id", round_id or "")),
        "teacher_queue_count": len(queue_rows),
        "decision_count": len(decisions),
        "teacher_decisions_path": to_safe_path(decisions_path),
        "sft_admissions_count": admission_report["sft_admissions_count"],
    }


def _select_teacher_queue_rows(rows: list[dict[str, Any]]) -> list[TeacherQueueRow]:
    explicit_failures: list[TeacherQueueRow] = []
    grouped_candidates: dict[str, list[dict[str, Any]]] = {}

    for index, raw in enumerate(rows, start=1):
        sample_id = str(raw.get("sample_id", "")).strip() or f"badcase_{index:06d}"
        state_input = raw.get("state_input", {})
        if not isinstance(state_input, dict):
            continue
        policy_output = _extract_policy_output(raw)
        trigger_reason = str(raw.get("trigger_reason", "")).strip()
        source = str(raw.get("source", "")).strip() or "unknown"

        if _is_explicit_failure(raw=raw, policy_output=policy_output):
            explicit_failures.append(
                TeacherQueueRow(
                    sample_id=sample_id,
                    source=source,
                    trigger_reason=trigger_reason or "explicit_failure",
                    state_input=copy.deepcopy(state_input),
                    policy_output=copy.deepcopy(policy_output),
                    dedup_key=str(raw.get("dedup_key", "")).strip() or _build_dedup_key(state_input, policy_output),
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
                    "teacher_rank": int(raw.get("teacher_rank", raw.get("rank", 0)) or 0),
                    "dedup_key": str(raw.get("dedup_key", "")).strip() or _build_dedup_key(state_input, policy_output),
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
                dedup_key=worst["dedup_key"],
            )
        )

    return selected


def _extract_policy_output(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("policy_output"), dict):
        return copy.deepcopy(row["policy_output"])
    if isinstance(row.get("policy_output_action"), dict):
        return copy.deepcopy(row["policy_output_action"])

    for key in ("policy_output_text", "prediction", "response"):
        raw_text = row.get(key)
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        parsed, _ = parse_candidate_action(raw_text)
        if isinstance(parsed, dict):
            return parsed
    return {}


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
    valid, _ = validate_runtime_controller_action(policy_output)
    return not valid


def _build_dedup_key(state_input: dict[str, Any], policy_output: dict[str, Any]) -> str:
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
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _collect_round_training_fingerprints(manifest: dict[str, Any]) -> set[str]:
    fingerprints: set[str] = set()
    lineage = manifest.get("lineage", {})
    if isinstance(lineage, dict):
        manual_protocol_root = str(lineage.get("manual_protocol", "")).strip()
        if manual_protocol_root:
            for row in load_manual_protocol_samples(Path(manual_protocol_root).resolve()):
                if row["split"] == "holdout":
                    continue
                state_input = build_controller_state_input(
                    user_input=row["user_input"],
                    environment_payload=copy.deepcopy(row["environment"]),
                )
                fingerprints.add(build_admission_fingerprint(state_input, row["target_action"]))

        previous_admissions_path = str(lineage.get("previous_admissions", "")).strip()
        if previous_admissions_path:
            for row in load_admission_rows(Path(previous_admissions_path).resolve()):
                fingerprints.add(build_admission_fingerprint(row.state_input, row.reference_action))

    current_admissions_path = resolve_round_asset_path(manifest, "sft_admissions")
    for row in load_admission_rows(current_admissions_path):
        fingerprints.add(build_admission_fingerprint(row.state_input, row.reference_action))
    return fingerprints


def _update_round_manifest(
    manifest: dict[str, Any],
    *,
    queue_count: int | None,
    admissions_count: int | None,
    dedup_count: int,
) -> None:
    counts = manifest.setdefault("counts_by_split", {})
    if not isinstance(counts, dict):
        counts = {}
        manifest["counts_by_split"] = counts
    if queue_count is not None:
        counts["teacher_queue"] = int(queue_count)
    if admissions_count is not None:
        counts["sft_admissions"] = int(admissions_count)

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
