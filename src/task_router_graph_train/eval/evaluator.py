from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

from ..dataset import read_jsonl
from ..feedback import enqueue_teacher_queue
from ..runtime_adapter import CONFIGS_ROOT
from ..train.controller_grpo_teacher import (
    judge_action_semantic_equivalence,
    parse_candidate_action,
    resolve_teacher_config,
    validate_action_dict,
    validate_protocol_action,
)

DEFAULT_EVAL_CONFIG_PATH = CONFIGS_ROOT / "controller_grpo_online.yaml"


def evaluate_holdout_predictions(
    *,
    record_path: Path,
    prediction_path: Path,
    config_path: Path | None = None,
    enqueue_failed_badcases: bool = False,
    badcase_round_id: str | None = None,
    badcase_round_manifest: Path | None = None,
) -> dict[str, Any]:
    records = read_jsonl(Path(record_path).resolve())
    predictions = read_jsonl(Path(prediction_path).resolve())
    predictions_by_id = {
        str(row.get("sample_id", "")).strip(): row
        for row in predictions
        if str(row.get("sample_id", "")).strip()
    }

    teacher_config = _resolve_regression_teacher(config_path)

    evidence_rows: list[dict[str, Any]] = []
    for record in records:
        sample_id = str(record.get("sample_id", "")).strip()
        state_input = record.get("state_input", {}) if isinstance(record.get("state_input", {}), dict) else {}
        gold_action = record.get("gold_action", {}) if isinstance(record.get("gold_action", {}), dict) else {}
        if not sample_id or not state_input or not gold_action:
            continue

        gold_valid, gold_errors = validate_action_dict(gold_action)
        if not gold_valid:
            raise ValueError(f"holdout gold_action must be schema-valid: {sample_id}: {gold_errors[0]}")

        prediction_row = predictions_by_id.get(sample_id, {})
        predicted_action, parse_errors = _extract_predicted_action(prediction_row)
        prediction_found = bool(prediction_row)

        schema_valid = False
        schema_errors: list[str] = []
        protocol_valid = False
        protocol_errors: list[str] = []
        semantic_pass = False
        semantic_score = 0.0
        judge_reason = ""
        if predicted_action is not None:
            schema_valid, schema_errors = validate_action_dict(predicted_action)
            if schema_valid:
                protocol_valid, protocol_errors = validate_protocol_action(predicted_action)
            if schema_valid and protocol_valid:
                judge_result = judge_action_semantic_equivalence(
                    sample_id=sample_id,
                    bucket_key=str(record.get("metadata", {}).get("bucket_key", "holdout"))
                    if isinstance(record.get("metadata", {}), dict)
                    else "holdout",
                    state_input=copy.deepcopy(state_input),
                    reference_action=copy.deepcopy(gold_action),
                    predicted_action=copy.deepcopy(predicted_action),
                    teacher_config=teacher_config,
                )
                semantic_pass = bool(judge_result["semantic_equivalent"])
                semantic_score = float(judge_result["score"])
                judge_reason = str(judge_result["reason"])

        evidence_rows.append(
            {
                "sample_id": sample_id,
                "state_input": copy.deepcopy(state_input),
                "gold_action": copy.deepcopy(gold_action),
                "prediction_action": copy.deepcopy(predicted_action or {}),
                "semantic_pass": semantic_pass,
                "judge_reason": judge_reason,
                "prediction_found": prediction_found,
                "parse_valid": predicted_action is not None and not parse_errors,
                "parse_errors": list(parse_errors),
                "schema_valid": schema_valid,
                "schema_errors": list(schema_errors),
                "protocol_valid": protocol_valid,
                "protocol_errors": list(protocol_errors),
                "semantic_score": semantic_score,
                "failure_reason": _resolve_failure_reason(
                    prediction_found=prediction_found,
                    parse_errors=parse_errors,
                    schema_valid=schema_valid,
                    protocol_valid=protocol_valid,
                    semantic_pass=semantic_pass,
                ),
                "trigger_reason": _resolve_trigger_reason(
                    prediction_found=prediction_found,
                    parse_errors=parse_errors,
                    schema_valid=schema_valid,
                    protocol_valid=protocol_valid,
                    semantic_pass=semantic_pass,
                ),
            }
        )

    summary = _aggregate(evidence_rows)
    report = {
        "metrics_summary": summary,
        "run_manifest": {
            "record_count": len(records),
            "prediction_count": len(predictions_by_id),
            "record_path": str(Path(record_path).resolve()),
            "prediction_path": str(Path(prediction_path).resolve()),
        },
        "evidence_rows": evidence_rows,
    }
    if enqueue_failed_badcases:
        candidates = build_holdout_badcase_candidates(evidence_rows)
        enqueue_report = _enqueue_failed_badcases(
            candidates=candidates,
            badcase_round_id=badcase_round_id,
            badcase_round_manifest=badcase_round_manifest,
        )
        report["badcase_enqueue_report"] = enqueue_report
    return report


def build_holdout_badcase_candidates(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in evidence_rows:
        if bool(row.get("semantic_pass", False)):
            continue
        trigger_reason = str(row.get("trigger_reason", "")).strip() or "holdout_failed"
        candidates.append(
            {
                "sample_id": str(row.get("sample_id", "")).strip(),
                "source": "holdout",
                "trigger_reason": trigger_reason,
                "state_input": copy.deepcopy(row.get("state_input", {})),
                "policy_output": copy.deepcopy(row.get("prediction_action", {})),
                "parse_ok": bool(row.get("parse_valid", False)),
                "schema_ok": bool(row.get("schema_valid", False)),
                "protocol_ok": bool(row.get("protocol_valid", False)),
            }
        )
    return candidates


def _resolve_regression_teacher(config_path: Path | None) -> dict[str, Any]:
    effective_path = (config_path or DEFAULT_EVAL_CONFIG_PATH).resolve()
    payload = yaml.safe_load(effective_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"config must be mapping: {effective_path}")
    return resolve_teacher_config(payload, role="regression_judge")


def _extract_predicted_action(prediction_row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(prediction_row, dict) or not prediction_row:
        return None, ["missing_prediction"]

    payload = prediction_row.get("prediction")
    if isinstance(payload, dict):
        return payload, []
    if isinstance(payload, str):
        return parse_candidate_action(payload)

    if isinstance(prediction_row.get("response"), str):
        return parse_candidate_action(str(prediction_row["response"]))

    return None, ["unsupported_prediction_shape"]


def _resolve_failure_reason(
    *,
    prediction_found: bool,
    parse_errors: list[str],
    schema_valid: bool,
    protocol_valid: bool,
    semantic_pass: bool,
) -> str:
    if not prediction_found:
        return "missing_prediction"
    if parse_errors:
        return "parse_failed"
    if not schema_valid:
        return "schema_failed"
    if not protocol_valid:
        return "protocol_failed"
    if not semantic_pass:
        return "holdout_failed"
    return ""


def _resolve_trigger_reason(
    *,
    prediction_found: bool,
    parse_errors: list[str],
    schema_valid: bool,
    protocol_valid: bool,
    semantic_pass: bool,
) -> str:
    return _resolve_failure_reason(
        prediction_found=prediction_found,
        parse_errors=parse_errors,
        schema_valid=schema_valid,
        protocol_valid=protocol_valid,
        semantic_pass=semantic_pass,
    )


def _enqueue_failed_badcases(
    *,
    candidates: list[dict[str, Any]],
    badcase_round_id: str | None,
    badcase_round_manifest: Path | None,
) -> dict[str, Any]:
    if not candidates:
        return {
            "queued_count": 0,
            "teacher_queue_count": 0,
        }
    temp_path = Path("/tmp/task_router_graph_train_holdout_badcases.jsonl").resolve()
    temp_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in candidates) + "\n",
        encoding="utf-8",
    )
    return enqueue_teacher_queue(
        round_id=badcase_round_id,
        round_manifest=badcase_round_manifest,
        candidates_path=temp_path,
    )


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if count == 0:
        return {
            "count": 0,
            "semantic_pass_rate": 0.0,
            "parse_valid_rate": 0.0,
            "schema_valid_rate": 0.0,
            "mean_semantic_score": 0.0,
        }

    semantic_pass = sum(1 for row in rows if bool(row.get("semantic_pass", False)))
    parse_valid = sum(1 for row in rows if bool(row.get("parse_valid", False)))
    schema_valid = sum(1 for row in rows if bool(row.get("schema_valid", False)))
    semantic_scores = [float(row.get("semantic_score", 0.0) or 0.0) for row in rows]

    return {
        "count": count,
        "semantic_pass_rate": round(semantic_pass / count, 6),
        "parse_valid_rate": round(parse_valid / count, 6),
        "schema_valid_rate": round(schema_valid / count, 6),
        "mean_semantic_score": round(sum(semantic_scores) / count, 6),
    }
