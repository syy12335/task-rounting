from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..reward_specs import GRAPH_EVAL_SPEC_ID
from ..runtime_adapter import ASSETS_ROOT, REPO_ROOT, build_controller_state_input, build_reply_state_input
from ..types import EvalManifest, TrainingRecord, VerifierSidecar
from .io import read_jsonl, write_jsonl

FORMAL_ENVIRONMENT_KEYS = (
    "rounds",
    "cur_round",
    "updated_at",
    "history_summaries",
    "history_meta_summary",
)
VERIFIER_ONLY_ENVIRONMENT_KEYS = (
    "running_refs",
    "pending_collect",
    "runtime_probe",
    "idempotent_guard",
    "skill_index_hint",
    "collected_items",
)
ROLE_CONTROLLER = "controller"
ROLE_REPLY = "reply"
ROLE_GRAPH_EVAL = "graph_eval"
ROLE_EXECUTOR_EVAL = "executor_eval"
ALLOWED_ROLES = {
    ROLE_CONTROLLER,
    ROLE_REPLY,
    ROLE_GRAPH_EVAL,
    ROLE_EXECUTOR_EVAL,
}

RAW_SAMPLE_FILE_SCENARIOS = "scenarios.jsonl"
RAW_SAMPLE_FILE_SNAPSHOTS = "snapshots.jsonl"
RAW_SAMPLE_FILE_LABELS = "labels.jsonl"
DEFAULT_K20_DATASET_DIR = ASSETS_ROOT / "eval_samples" / "k20_manual"

K20_SCENARIO_LEADERBOARDS: dict[str, list[str]] = {
    "s01_status_running_progress": ["reply_core"],
    "s02_retry_use_failed_track": ["controller_core"],
    "s03_time_anchor_then_tool": ["controller_core", "executor_guardrail"],
    "s04_greeting_no_tool": ["executor_guardrail"],
    "s05_loop_read_break": ["controller_core", "executor_guardrail"],
    "s06_collect_done_linked": ["reply_core", "graph_deterministic"],
    "s07_collect_failed_explain": ["reply_core", "graph_deterministic"],
    "s08_status_shortcut_with_running": ["reply_core", "graph_deterministic"],
    "s09_retry_reply_before_execute": ["controller_core", "graph_deterministic"],
    "s10_running_no_new_input_needed": ["reply_core"],
    "s11_done_should_not_retry": ["reply_core"],
    "s12_failed_route_stop": ["controller_core", "graph_deterministic"],
    "s13_tool_quota_respect": ["executor_guardrail"],
    "s14_skill_not_activated": ["executor_guardrail"],
    "s15_running_then_collect_same_round": ["reply_core", "graph_deterministic"],
    "s16_missing_process_fail_collect": ["reply_core", "graph_deterministic"],
    "s17_previous_failed_track_priority": ["controller_core"],
    "s18_non_time_query_no_beijing_time": ["executor_guardrail"],
    "s19_status_query_with_collected_items": ["reply_core", "graph_deterministic"],
    "s20_async_link_idempotent": ["graph_deterministic"],
}


def sanitize_environment_payload(environment_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    formal_payload: dict[str, Any] = {}
    sidecar_payload: dict[str, Any] = {}
    for key, value in environment_payload.items():
        target = formal_payload if key in FORMAL_ENVIRONMENT_KEYS else sidecar_payload
        target[key] = copy.deepcopy(value)

    for key in FORMAL_ENVIRONMENT_KEYS:
        if key in formal_payload:
            continue
        if key == "rounds":
            formal_payload[key] = []
        elif key == "cur_round":
            formal_payload[key] = 0
        elif key == "updated_at":
            continue
        elif key == "history_summaries":
            formal_payload[key] = []
        elif key == "history_meta_summary":
            formal_payload[key] = ""

    unexpected_formal_keys = [key for key in sidecar_payload if key in VERIFIER_ONLY_ENVIRONMENT_KEYS]
    if unexpected_formal_keys:
        sidecar_payload["verifier_only_environment_keys"] = sorted(unexpected_formal_keys)

    return formal_payload, sidecar_payload


def load_eval_sample_triplets(dataset_dir: Path | None = None) -> list[dict[str, Any]]:
    resolved_dir = (dataset_dir or DEFAULT_K20_DATASET_DIR).resolve()
    scenario_rows = read_jsonl(resolved_dir / RAW_SAMPLE_FILE_SCENARIOS)
    snapshot_rows = read_jsonl(resolved_dir / RAW_SAMPLE_FILE_SNAPSHOTS)
    label_rows = read_jsonl(resolved_dir / RAW_SAMPLE_FILE_LABELS)

    scenarios_by_id = _index_rows_by_sample_id(scenario_rows, source_name=RAW_SAMPLE_FILE_SCENARIOS)
    snapshots_by_id = _index_rows_by_sample_id(snapshot_rows, source_name=RAW_SAMPLE_FILE_SNAPSHOTS)
    labels_by_id = _index_rows_by_sample_id(label_rows, source_name=RAW_SAMPLE_FILE_LABELS)

    sample_ids = sorted(set(scenarios_by_id) | set(snapshots_by_id) | set(labels_by_id))
    missing_errors: list[str] = []
    bundles: list[dict[str, Any]] = []
    for sample_id in sample_ids:
        if sample_id not in scenarios_by_id:
            missing_errors.append(f"missing scenario row: {sample_id}")
            continue
        if sample_id not in snapshots_by_id:
            missing_errors.append(f"missing snapshot row: {sample_id}")
            continue
        if sample_id not in labels_by_id:
            missing_errors.append(f"missing label row: {sample_id}")
            continue
        bundles.append(
            {
                "sample_id": sample_id,
                "scenario": copy.deepcopy(scenarios_by_id[sample_id]),
                "snapshot": copy.deepcopy(snapshots_by_id[sample_id]),
                "label": copy.deepcopy(labels_by_id[sample_id]),
            }
        )

    if missing_errors:
        raise ValueError("; ".join(missing_errors))

    return bundles


def rewrite_k20_snapshots_with_sidecar(dataset_dir: Path | None = None) -> list[dict[str, Any]]:
    resolved_dir = (dataset_dir or DEFAULT_K20_DATASET_DIR).resolve()
    snapshot_path = resolved_dir / RAW_SAMPLE_FILE_SNAPSHOTS
    snapshot_rows = read_jsonl(snapshot_path)
    updated_rows: list[dict[str, Any]] = []

    for row in snapshot_rows:
        environment_payload = row.get("environment", {})
        if not isinstance(environment_payload, dict):
            raise ValueError(f"environment must be an object: {row.get('sample_id')}")
        sanitized_environment, verifier_sidecar = sanitize_environment_payload(environment_payload)
        updated_row = copy.deepcopy(row)
        updated_row["environment"] = sanitized_environment
        if verifier_sidecar:
            merged_sidecar = copy.deepcopy(updated_row.get("verifier_sidecar", {}))
            if not isinstance(merged_sidecar, dict):
                merged_sidecar = {}
            merged_sidecar.update(verifier_sidecar)
            updated_row["verifier_sidecar"] = merged_sidecar
        updated_rows.append(updated_row)

    write_jsonl(snapshot_path, updated_rows)
    return updated_rows


def build_k20_holdout_records(
    *,
    dataset_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> tuple[list[TrainingRecord], EvalManifest]:
    resolved_dir = (dataset_dir or DEFAULT_K20_DATASET_DIR).resolve()
    runtime_root = (workspace_root or REPO_ROOT).resolve()
    bundles = load_eval_sample_triplets(resolved_dir)
    records: list[TrainingRecord] = []

    for bundle in bundles:
        scenario = bundle["scenario"]
        snapshot = bundle["snapshot"]
        label = bundle["label"]
        environment_payload = snapshot.get("environment", {})
        if not isinstance(environment_payload, dict):
            raise ValueError(f"snapshot.environment must be an object: {bundle['sample_id']}")

        final_task = _build_expected_final_task(bundle)
        reply_preview = build_reply_state_input(
            user_input=str(scenario.get("user_input", "")),
            environment_payload=environment_payload,
            final_task=final_task,
        )
        record = TrainingRecord(
            sample_id=bundle["sample_id"],
            role=ROLE_GRAPH_EVAL,
            split="holdout",
            reward_spec_id=GRAPH_EVAL_SPEC_ID,
            state_input={
                "USER_INPUT": str(scenario.get("user_input", "")),
                "ENVIRONMENT": copy.deepcopy(environment_payload),
            },
            gold_output={
                "error_code": str(label.get("error_code", "")),
                "expected_action": str(label.get("expected_action", "")),
                "final_task": final_task,
                "reply_style": str(
                    scenario.get("gold_outcome", {}).get("reply_style", "")
                    if isinstance(scenario.get("gold_outcome"), dict)
                    else ""
                ),
            },
            verifier_sidecar=VerifierSidecar(
                environment_snapshot_id=str(snapshot.get("environment_snapshot_id", "")),
                annotation=str(label.get("annotation", "")),
                task_focus=str(scenario.get("task_focus", "")),
                leaderboards=list(
                    K20_SCENARIO_LEADERBOARDS.get(str(scenario.get("scenario_id", "")), [])
                ),
                environment_extras=copy.deepcopy(snapshot.get("verifier_sidecar", {})),
                runtime_shape_preview={
                    "controller": build_controller_state_input(
                        user_input=str(scenario.get("user_input", "")),
                        environment_payload=environment_payload,
                        workspace_root=runtime_root,
                    ),
                    "reply": reply_preview,
                },
            ),
        )
        records.append(record)

    manifest = EvalManifest(
        dataset="task_router_graph_train_rl_v1_k20_holdout",
        version="v1.0.0",
        record_count=len(records),
        split="holdout",
        roles=[ROLE_GRAPH_EVAL],
        reward_spec_ids=[GRAPH_EVAL_SPEC_ID],
        notes=[
            "Built from src/task_router_graph_train/assets/eval_samples/k20_manual after stripping verifier-only environment keys.",
            "runtime_shape_preview stays in verifier_sidecar and must never be fed to the model in graph_eval mode.",
        ],
    )
    return records, manifest


def _index_rows_by_sample_id(rows: list[dict[str, Any]], *, source_name: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_id = str(row.get("sample_id", "")).strip()
        if not sample_id:
            raise ValueError(f"sample_id is required: {source_name}")
        if sample_id in indexed:
            raise ValueError(f"duplicate sample_id in {source_name}: {sample_id}")
        indexed[sample_id] = copy.deepcopy(row)
    return indexed


def _build_expected_final_task(bundle: dict[str, Any]) -> dict[str, Any]:
    scenario = bundle["scenario"]
    snapshot = bundle["snapshot"]
    label = bundle["label"]
    gold_outcome = label.get("gold_outcome", {})
    if not isinstance(gold_outcome, dict):
        gold_outcome = {}

    target_round_id = int(label.get("round_id", 0) or 0)
    target_task_id = int(label.get("task_id", 0) or 0)
    task_payload = _find_task_payload(
        environment_payload=snapshot.get("environment", {}),
        round_id=target_round_id,
        task_id=target_task_id,
    )
    if task_payload is None:
        task_payload = {
            "task_id": target_task_id or 1,
            "type": "executor",
            "content": str(scenario.get("task_focus", "")).strip() or "graph_eval expected task",
        }
    else:
        task_payload = copy.deepcopy(task_payload)

    task_payload["task_id"] = target_task_id or int(task_payload.get("task_id", 1) or 1)
    task_payload["status"] = str(gold_outcome.get("task_status", task_payload.get("status", ""))).strip()
    task_payload["result"] = str(gold_outcome.get("task_result", task_payload.get("result", ""))).strip()
    return task_payload


def _find_task_payload(
    *,
    environment_payload: dict[str, Any],
    round_id: int,
    task_id: int,
) -> dict[str, Any] | None:
    if not isinstance(environment_payload, dict):
        return None
    rounds = environment_payload.get("rounds", [])
    if not isinstance(rounds, list):
        return None
    for round_item in rounds:
        if not isinstance(round_item, dict):
            continue
        if int(round_item.get("round_id", 0) or 0) != round_id:
            continue
        tasks = round_item.get("tasks", [])
        if not isinstance(tasks, list):
            continue
        for task_item in tasks:
            if not isinstance(task_item, dict):
                continue
            if int(task_item.get("task_id", 0) or 0) != task_id:
                continue
            task_payload = task_item.get("task")
            if isinstance(task_payload, dict):
                return copy.deepcopy(task_payload)
    return None
