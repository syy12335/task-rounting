from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from ..dataset import (
    build_controller_train_records,
    render_controller_prompt,
    render_controller_target_text,
    write_jsonl,
)
from ..types import SftExample, TrainingRecord
from .controller_sft import train_controller_sft

ALLOWED_ACTION_KINDS = {"observe", "generate_task"}


def validate_controller_action(action: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    action_kind = str(action.get("action_kind", "")).strip()
    if action_kind not in ALLOWED_ACTION_KINDS:
        errors.append(f"action_kind must be one of {sorted(ALLOWED_ACTION_KINDS)}")
        return False, errors

    if action_kind == "observe":
        tool = action.get("tool")
        args = action.get("args")
        if not isinstance(tool, str) or not tool.strip():
            errors.append("observe action must provide non-empty tool")
        if not isinstance(args, dict):
            errors.append("observe action must provide args object")
    elif action_kind == "generate_task":
        task_type = action.get("task_type")
        task_content = action.get("task_content")
        if not isinstance(task_type, str) or not task_type.strip():
            errors.append("generate_task action must provide non-empty task_type")
        if not isinstance(task_content, str) or not task_content.strip():
            errors.append("generate_task action must provide non-empty task_content")

    return len(errors) == 0, errors


def build_grpo_rollout_groups(
    *,
    records: list[TrainingRecord],
    num_candidates: int,
    seed: int,
) -> list[dict[str, Any]]:
    if num_candidates < 2:
        raise ValueError("num_candidates must be >= 2")
    rng = random.Random(seed)
    groups: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if record.role != "controller":
            continue
        group_id = f"group_{index:05d}_{record.sample_id}"
        candidates = _build_candidates_for_record(
            record=record,
            num_candidates=num_candidates,
            rng=rng,
        )
        groups.append(
            {
                "group_id": group_id,
                "sample_id": record.sample_id,
                "split": record.split,
                "state_input": copy.deepcopy(record.state_input),
                "gold_output": copy.deepcopy(record.gold_output),
                "metadata": copy.deepcopy(record.metadata),
                "candidates": candidates,
            }
        )
    return groups


def build_teacher_rankings(
    *,
    groups: list[dict[str, Any]],
    mode: str,
    ranking_path: Path | None = None,
) -> list[dict[str, Any]]:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "oracle":
        return [
            {
                "group_id": str(group.get("group_id", "")),
                "ranking": [str(item.get("candidate_id", "")) for item in group.get("candidates", [])],
                "confidence": 1.0,
                "reason": "oracle ranking uses gold-first candidate construction",
            }
            for group in groups
        ]
    if normalized_mode == "file":
        if ranking_path is None:
            raise ValueError("ranking_path is required when teacher mode is file")
        rows: list[dict[str, Any]] = []
        for line in ranking_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"teacher ranking row must be object: {ranking_path}")
            rows.append(payload)
        return rows
    raise ValueError(f"unsupported teacher mode: {mode}")


def validate_teacher_rankings(
    *,
    groups: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rankings_by_group = {
        str(item.get("group_id", "")).strip(): item
        for item in rankings
        if str(item.get("group_id", "")).strip()
    }
    validated: dict[str, dict[str, Any]] = {}
    for group in groups:
        group_id = str(group.get("group_id", ""))
        ranking_row = rankings_by_group.get(group_id)
        if ranking_row is None:
            raise ValueError(f"missing teacher ranking for group: {group_id}")
        ranking = ranking_row.get("ranking", [])
        if not isinstance(ranking, list) or not ranking:
            raise ValueError(f"ranking must be non-empty list: {group_id}")
        candidate_ids = [str(item.get("candidate_id", "")) for item in group.get("candidates", [])]
        ranking_ids = [str(item).strip() for item in ranking]
        if len(set(ranking_ids)) != len(ranking_ids):
            raise ValueError(f"ranking contains duplicate candidate ids: {group_id}")
        if set(ranking_ids) != set(candidate_ids):
            raise ValueError(
                f"ranking candidate ids mismatch for {group_id}: expected {sorted(candidate_ids)}, got {sorted(ranking_ids)}"
            )
        validated[group_id] = {
            "group_id": group_id,
            "ranking": ranking_ids,
            "confidence": float(ranking_row.get("confidence", 1.0)),
            "reason": str(ranking_row.get("reason", "")),
        }
    return validated


def build_grpo_examples(
    *,
    groups: list[dict[str, Any]],
    rankings_by_group: dict[str, dict[str, Any]],
    keep_top_k: int,
) -> tuple[list[SftExample], list[SftExample], list[dict[str, Any]]]:
    train_examples: list[SftExample] = []
    eval_examples: list[SftExample] = []
    audit_rows: list[dict[str, Any]] = []

    for group in groups:
        group_id = str(group.get("group_id", ""))
        split = str(group.get("split", "train")).strip() or "train"
        ranking = rankings_by_group[group_id]["ranking"]
        candidates = {
            str(item.get("candidate_id", "")): item
            for item in group.get("candidates", [])
            if str(item.get("candidate_id", ""))
        }
        top_ids = ranking[: max(1, min(keep_top_k, len(ranking)))]

        for rank_index, candidate_id in enumerate(top_ids):
            candidate = candidates[candidate_id]
            action = candidate.get("action", {})
            prompt = render_controller_prompt(group.get("state_input", {}))
            target_text = render_controller_target_text(action if isinstance(action, dict) else {})
            advantage = _rank_to_advantage(rank_index=rank_index, size=len(ranking))
            row = SftExample(
                sample_id=f"{group.get('sample_id', '')}#{candidate_id}",
                split=split,
                prompt=prompt,
                target_text=target_text,
                metadata={
                    "terminal": bool(group.get("metadata", {}).get("terminal", False)),
                    "grpo_group_id": group_id,
                    "grpo_rank": rank_index + 1,
                    "grpo_advantage": round(advantage, 6),
                    "candidate_id": candidate_id,
                },
            )
            if split == "eval":
                eval_examples.append(row)
            else:
                train_examples.append(row)

            audit_rows.append(
                {
                    "group_id": group_id,
                    "sample_id": group.get("sample_id", ""),
                    "split": split,
                    "candidate_id": candidate_id,
                    "rank": rank_index + 1,
                    "advantage": round(advantage, 6),
                    "action": copy.deepcopy(action),
                }
            )

    return train_examples, eval_examples, audit_rows


def train_controller_grpo(
    *,
    output_dir: Path,
    teacher_mode: str = "oracle",
    teacher_rankings_path: Path | None = None,
    teacher_source_dir: Path | None = None,
    runtime_root: Path | None = None,
    num_candidates: int = 4,
    keep_top_k: int = 2,
    seed: int = 42,
    run_sft_update: bool = False,
    model_name_or_path: str = "",
    lora_target_modules: list[str] | None = None,
    num_train_epochs: int = 1,
    per_device_train_batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 2048,
    lora_r: int = 8,
    lora_alpha: int = 16,
    lora_dropout: float = 0.05,
    holdout_records: Path | None = None,
    holdout_predictions: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    records, _ = build_controller_train_records(
        teacher_source_dir=teacher_source_dir,
        workspace_root=runtime_root,
    )
    groups = build_grpo_rollout_groups(
        records=records,
        num_candidates=num_candidates,
        seed=seed,
    )
    rankings = build_teacher_rankings(
        groups=groups,
        mode=teacher_mode,
        ranking_path=teacher_rankings_path,
    )
    rankings_by_group = validate_teacher_rankings(groups=groups, rankings=rankings)
    train_examples, eval_examples, audit_rows = build_grpo_examples(
        groups=groups,
        rankings_by_group=rankings_by_group,
        keep_top_k=keep_top_k,
    )

    rollout_path = output_dir / "grpo_rollout_groups.jsonl"
    rankings_path = output_dir / "teacher_rankings.jsonl"
    train_examples_path = output_dir / "grpo_train_examples.jsonl"
    eval_examples_path = output_dir / "grpo_eval_examples.jsonl"
    audit_path = output_dir / "grpo_audit_rows.jsonl"

    write_jsonl(rollout_path, groups)
    write_jsonl(rankings_path, list(rankings_by_group.values()))
    write_jsonl(train_examples_path, train_examples)
    write_jsonl(eval_examples_path, eval_examples)
    write_jsonl(audit_path, audit_rows)

    training_report: dict[str, Any] = {
        "run_sft_update": bool(run_sft_update),
        "output_dir": str(output_dir),
        "rollout_groups_path": str(rollout_path),
        "teacher_rankings_path": str(rankings_path),
        "train_examples_path": str(train_examples_path),
        "eval_examples_path": str(eval_examples_path),
        "audit_rows_path": str(audit_path),
        "group_count": len(groups),
        "train_example_count": len(train_examples),
        "eval_example_count": len(eval_examples),
        "num_candidates": num_candidates,
        "keep_top_k": keep_top_k,
        "teacher_mode": teacher_mode,
    }

    if run_sft_update:
        if not model_name_or_path.strip():
            raise ValueError("model_name_or_path is required when run_sft_update is true")
        if not lora_target_modules:
            raise ValueError("lora_target_modules is required when run_sft_update is true")
        adapter_output_dir = output_dir / "adapter"
        sft_report = train_controller_sft(
            model_name_or_path=model_name_or_path,
            lora_target_modules=list(lora_target_modules),
            train_examples=train_examples_path,
            eval_examples=eval_examples_path,
            output_dir=adapter_output_dir,
            num_train_epochs=num_train_epochs,
            per_device_train_batch_size=per_device_train_batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            learning_rate=learning_rate,
            max_seq_length=max_seq_length,
            lora_r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            seed=seed,
        )
        training_report["sft_update_report"] = sft_report

    if holdout_records is not None and holdout_predictions is not None:
        try:
            from ..eval import evaluate_prediction_records

            monitor_report = evaluate_prediction_records(
                record_path=holdout_records,
                prediction_path=holdout_predictions,
            )
            monitor_dir = output_dir / "holdout_monitor"
            monitor_dir.mkdir(parents=True, exist_ok=True)
            (monitor_dir / "metrics_summary.json").write_text(
                json.dumps(monitor_report["metrics_summary"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (monitor_dir / "metrics_by_error_code.json").write_text(
                json.dumps(monitor_report["metrics_by_error_code"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            training_report["holdout_monitoring"] = {
                "enabled": True,
                "record_path": str(holdout_records),
                "prediction_path": str(holdout_predictions),
                "output_dir": str(monitor_dir),
            }
        except Exception as exc:  # pragma: no cover - best effort monitoring
            training_report["holdout_monitoring"] = {
                "enabled": False,
                "error": str(exc),
            }
    else:
        training_report["holdout_monitoring"] = {
            "enabled": False,
            "reason": "holdout_records or holdout_predictions not provided",
        }

    report_path = output_dir / "grpo_train_report.json"
    report_path.write_text(json.dumps(training_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    training_report["report_path"] = str(report_path)
    return training_report


def _build_candidates_for_record(
    *,
    record: TrainingRecord,
    num_candidates: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    gold = copy.deepcopy(record.gold_output)
    candidates: list[dict[str, Any]] = []

    def append_candidate(action: dict[str, Any], *, source: str) -> None:
        candidate_id = f"cand_{len(candidates):02d}"
        valid, errors = validate_controller_action(action)
        candidates.append(
            {
                "candidate_id": candidate_id,
                "source": source,
                "action": copy.deepcopy(action),
                "is_valid": valid,
                "validation_errors": errors,
            }
        )

    append_candidate(gold, source="gold")
    while len(candidates) < num_candidates:
        mutated = _mutate_action(gold, rng=rng)
        append_candidate(mutated, source="mutation")
    return candidates


def _mutate_action(action: dict[str, Any], *, rng: random.Random) -> dict[str, Any]:
    kind = str(action.get("action_kind", "")).strip()
    mutated = copy.deepcopy(action)
    if kind == "observe":
        variants = [
            {
                "action_kind": "generate_task",
                "reason": "忽略 running 语义直接起新任务。",
                "tool": None,
                "args": {},
                "task_type": "functest",
                "task_content": "重复执行功能测试",
            },
            {
                "action_kind": "observe",
                "reason": "继续观察，但未明确推进条件。",
                "tool": "read",
                "args": {"target": "latest_round"},
                "task_type": None,
                "task_content": None,
            },
            {
                "action_kind": "observe",
                "reason": "虚构状态：系统已经完成全部任务。",
                "tool": "read",
                "args": {"target": "latest_round"},
                "task_type": None,
                "task_content": None,
            },
        ]
        return copy.deepcopy(rng.choice(variants))
    if kind == "generate_task":
        variants = [
            {
                "action_kind": "observe",
                "reason": "先读一下，但忽略了当前应新建任务。",
                "tool": "read",
                "args": {"target": "latest_round"},
                "task_type": None,
                "task_content": None,
            },
            {
                "action_kind": "generate_task",
                "reason": "任务类型选择错误。",
                "tool": None,
                "args": {},
                "task_type": "executor",
                "task_content": str(action.get("task_content", "")) or "执行任务",
            },
            {
                "action_kind": "generate_task",
                "reason": "内容空洞，缺少环境事实。",
                "tool": None,
                "args": {},
                "task_type": str(action.get("task_type", "")) or "functest",
                "task_content": "继续处理",
            },
        ]
        return copy.deepcopy(rng.choice(variants))
    mutated["reason"] = "action_kind 非法，作为坏候选示例。"
    mutated["action_kind"] = "invalid_kind"
    return mutated


def _rank_to_advantage(*, rank_index: int, size: int) -> float:
    if size <= 1:
        return 0.0
    center = (size - 1) / 2.0
    if center <= 0:
        return 0.0
    return (center - float(rank_index)) / center
