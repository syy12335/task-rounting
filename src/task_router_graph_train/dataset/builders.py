from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from ..admissions import load_admission_rows
from ..artifacts import (
    CONTROLLER_TRAINING_RECORDS_ARTIFACT_TYPE,
    HOLDOUT_RECORDS_ARTIFACT_TYPE,
    ROUND_MANIFEST_ARTIFACT_TYPE,
    SFT_ADMISSIONS_ARTIFACT_TYPE,
    SFT_EXAMPLES_ARTIFACT_TYPE,
    TEACHER_QUEUE_ARTIFACT_TYPE,
    utc_now_iso,
    write_json,
)
from ..reward_specs import CONTROLLER_REWARD_SPEC_ID
from ..rounds import resolve_round_assets_root, resolve_round_dir
from ..runtime_adapter import ASSETS_ROOT, REPO_ROOT, build_controller_state_input, validate_runtime_controller_action
from ..types import ControllerGrpoRecord, SftAdmissionRow, SftExample, TrainingRecord, VerifierSidecar
from .io import read_jsonl, write_jsonl

FORMAL_ENVIRONMENT_KEYS = (
    "rounds",
    "cur_round",
    "updated_at",
    "history_summaries",
    "history_meta_summary",
)
ROLE_CONTROLLER = "controller"

DEFAULT_MANUAL_PROTOCOL_DIR = ASSETS_ROOT / "manual_protocol_v1"
ROUND_MANIFEST_NAME = "round_manifest.json"


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

    return formal_payload, sidecar_payload


def render_controller_prompt(state_input: dict[str, Any]) -> str:
    user_input = str(state_input.get("USER_INPUT", ""))
    environment_payload = state_input.get("ENVIRONMENT_JSON", {})
    skills_index = str(state_input.get("SKILLS_INDEX", "")).strip()
    environment_json = json.dumps(environment_payload, ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "你是 task_router_graph 的 controller。",
            "请阅读下面的训练态 state，并只输出一个 JSON 对象。",
            "不要输出解释、不要输出 markdown，只输出结构化动作。",
            "",
            "USER_INPUT",
            user_input,
            "",
            "ENVIRONMENT_JSON",
            environment_json,
            "",
            "SKILLS_INDEX",
            skills_index,
        ]
    ).strip()


def render_controller_target_text(target_action: dict[str, Any]) -> str:
    return json.dumps(target_action, ensure_ascii=False, indent=2)


def build_controller_sft_examples(records: list[TrainingRecord]) -> list[SftExample]:
    examples: list[SftExample] = []
    for record in records:
        if record.role != ROLE_CONTROLLER:
            raise ValueError(f"controller SFT only supports controller records: {record.sample_id}")
        if record.split not in {"train", "eval"}:
            continue
        examples.append(
            SftExample(
                sample_id=record.sample_id,
                split=record.split,
                prompt=render_controller_prompt(record.state_input),
                target_text=render_controller_target_text(record.gold_output),
                metadata=copy.deepcopy(record.metadata),
            )
        )
    return examples


def write_controller_sft_assets(
    *,
    output_root: Path,
    records: list[TrainingRecord],
    manifest: dict[str, Any],
) -> dict[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    train_records = [record.to_dict() for record in records if record.split == "train"]
    eval_records = [record.to_dict() for record in records if record.split == "eval"]
    examples = build_controller_sft_examples(records)
    train_examples = [item.to_dict() for item in examples if item.split == "train"]
    eval_examples = [item.to_dict() for item in examples if item.split == "eval"]

    record_train_path = output_root / "controller_train_records.jsonl"
    record_eval_path = output_root / "controller_eval_records.jsonl"
    example_train_path = output_root / "controller_sft_train.jsonl"
    example_eval_path = output_root / "controller_sft_eval.jsonl"
    manifest_path = output_root / "manifest.json"

    write_jsonl(record_train_path, train_records)
    write_jsonl(record_eval_path, eval_records)
    write_jsonl(example_train_path, train_examples)
    write_jsonl(example_eval_path, eval_examples)
    write_json(manifest_path, manifest)
    return {
        "record_train_path": record_train_path,
        "record_eval_path": record_eval_path,
        "example_train_path": example_train_path,
        "example_eval_path": example_eval_path,
        "manifest_path": manifest_path,
    }


def load_manual_protocol_samples(manual_protocol_dir: Path | None = None) -> list[dict[str, Any]]:
    base_dir = (manual_protocol_dir or DEFAULT_MANUAL_PROTOCOL_DIR).resolve()
    samples_path = base_dir / "samples.jsonl"
    rows = read_jsonl(samples_path)
    validated: list[dict[str, Any]] = []
    for row in rows:
        sample_id = str(row.get("sample_id", "")).strip()
        split = str(row.get("split", "")).strip()
        user_input = str(row.get("user_input", ""))
        environment = row.get("environment", {})
        target_action = row.get("target_action", {})
        if not sample_id:
            raise ValueError("manual_protocol sample_id is required")
        if split not in {"sft_train", "sft_eval", "holdout"}:
            raise ValueError(f"unsupported split in manual_protocol_v1: {split} ({sample_id})")
        if not isinstance(environment, dict):
            raise ValueError(f"environment must be object: {sample_id}")
        if not isinstance(target_action, dict):
            raise ValueError(f"target_action must be object: {sample_id}")
        valid, errors = validate_runtime_controller_action(target_action)
        if not valid:
            raise ValueError(f"target_action must satisfy controller schema: {sample_id}: {errors[0]}")
        formal_environment, _ = sanitize_environment_payload(environment)
        validated.append(
            {
                "sample_id": sample_id,
                "split": split,
                "user_input": user_input,
                "environment": formal_environment,
                "target_action": copy.deepcopy(target_action),
                "bucket_key": str(row.get("bucket_key", "")).strip(),
            }
        )
    return validated


def prepare_round_assets(
    *,
    round_id: str,
    previous_round_id: str | None = None,
    round_assets_root: Path | None = None,
    manual_protocol_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    runtime_root = (workspace_root or REPO_ROOT).resolve()
    rounds_root = resolve_round_assets_root(round_assets_root)
    round_dir = resolve_round_dir(round_id=round_id, root=rounds_root)
    round_dir.mkdir(parents=True, exist_ok=True)

    manual_rows = load_manual_protocol_samples(manual_protocol_dir)
    admissions_path = _resolve_previous_admissions_path(
        round_assets_root=rounds_root,
        previous_round_id=previous_round_id,
    )
    admission_rows = load_admission_rows(admissions_path)

    sft_records: list[TrainingRecord] = []
    grpo_records: list[ControllerGrpoRecord] = []
    holdout_rows: list[dict[str, Any]] = []

    for row in manual_rows:
        state_input = build_controller_state_input(
            user_input=row["user_input"],
            environment_payload=copy.deepcopy(row["environment"]),
            workspace_root=runtime_root,
        )
        split = row["split"]
        if split == "holdout":
            holdout_rows.append(
                {
                    "sample_id": row["sample_id"],
                    "state_input": state_input,
                    "gold_action": copy.deepcopy(row["target_action"]),
                    "split": "holdout",
                    "metadata": {"source": "manual_protocol_v1", "bucket_key": row["bucket_key"]},
                }
            )
            continue

        mapped_split = "train" if split == "sft_train" else "eval"
        sft_records.append(
            TrainingRecord(
                sample_id=row["sample_id"],
                role=ROLE_CONTROLLER,
                state_input=state_input,
                gold_output=copy.deepcopy(row["target_action"]),
                verifier_sidecar=VerifierSidecar(),
                reward_spec_id=CONTROLLER_REWARD_SPEC_ID,
                split=mapped_split,
                metadata={"source": "manual_protocol_v1", "bucket_key": row["bucket_key"]},
            )
        )
        grpo_records.append(
            ControllerGrpoRecord(
                sample_id=row["sample_id"],
                role=ROLE_CONTROLLER,
                state_input=copy.deepcopy(state_input),
                reward_spec_id=CONTROLLER_REWARD_SPEC_ID,
                split=mapped_split,
                metadata={"source": "manual_protocol_v1", "bucket_key": row["bucket_key"]},
            )
        )

    sft_records.extend(_build_admission_sft_records(admission_rows))

    sft_examples = build_controller_sft_examples(sft_records)
    sft_train_examples = [row.to_dict() for row in sft_examples if row.split == "train"]
    sft_eval_examples = [row.to_dict() for row in sft_examples if row.split == "eval"]

    sft_train_path = round_dir / "sft_examples_train.jsonl"
    sft_eval_path = round_dir / "sft_examples_eval.jsonl"
    grpo_train_path = round_dir / "controller_records_train.jsonl"
    grpo_eval_path = round_dir / "controller_records_eval.jsonl"
    holdout_path = round_dir / "holdout_records.jsonl"
    teacher_queue_path = round_dir / "teacher_queue.jsonl"
    sft_admissions_path = round_dir / "sft_admissions.jsonl"

    write_jsonl(sft_train_path, sft_train_examples)
    write_jsonl(sft_eval_path, sft_eval_examples)
    write_jsonl(grpo_train_path, [row.to_dict() for row in grpo_records if row.split == "train"])
    write_jsonl(grpo_eval_path, [row.to_dict() for row in grpo_records if row.split == "eval"])
    write_jsonl(holdout_path, holdout_rows)

    if not teacher_queue_path.exists():
        teacher_queue_path.write_text("", encoding="utf-8")
    if not sft_admissions_path.exists():
        sft_admissions_path.write_text("", encoding="utf-8")
    current_admissions = read_jsonl(sft_admissions_path) if sft_admissions_path.read_text(encoding="utf-8").strip() else []

    counts_by_split = {
        "sft_train": len(sft_train_examples),
        "sft_eval": len(sft_eval_examples),
        "grpo_train": len([row for row in grpo_records if row.split == "train"]),
        "grpo_eval": len([row for row in grpo_records if row.split == "eval"]),
        "holdout": len(holdout_rows),
        "sft_admissions": len(current_admissions),
    }

    manifest = {
        "artifact_type": ROUND_MANIFEST_ARTIFACT_TYPE,
        "round_id": str(round_id),
        "previous_round_id": str(previous_round_id or ""),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "counts_by_split": counts_by_split,
        "assets": {
            "sft_examples_train": {
                "artifact_type": SFT_EXAMPLES_ARTIFACT_TYPE,
                "path": str(sft_train_path.resolve()),
            },
            "sft_examples_eval": {
                "artifact_type": SFT_EXAMPLES_ARTIFACT_TYPE,
                "path": str(sft_eval_path.resolve()),
            },
            "controller_records_train": {
                "artifact_type": CONTROLLER_TRAINING_RECORDS_ARTIFACT_TYPE,
                "path": str(grpo_train_path.resolve()),
            },
            "controller_records_eval": {
                "artifact_type": CONTROLLER_TRAINING_RECORDS_ARTIFACT_TYPE,
                "path": str(grpo_eval_path.resolve()),
            },
            "holdout_records": {
                "artifact_type": HOLDOUT_RECORDS_ARTIFACT_TYPE,
                "path": str(holdout_path.resolve()),
            },
            "teacher_queue": {
                "artifact_type": TEACHER_QUEUE_ARTIFACT_TYPE,
                "path": str(teacher_queue_path.resolve()),
            },
            "sft_admissions": {
                "artifact_type": SFT_ADMISSIONS_ARTIFACT_TYPE,
                "path": str(sft_admissions_path.resolve()),
            },
        },
        "lineage": {
            "manual_protocol": str((manual_protocol_dir or DEFAULT_MANUAL_PROTOCOL_DIR).resolve()),
            "previous_admissions": str(admissions_path.resolve()) if admissions_path else "",
        },
    }
    write_json(round_dir / ROUND_MANIFEST_NAME, manifest)

    return {
        "round_id": str(round_id),
        "round_dir": str(round_dir.resolve()),
        "manifest_path": str((round_dir / ROUND_MANIFEST_NAME).resolve()),
        "counts_by_split": counts_by_split,
    }


def _build_admission_sft_records(admissions: list[SftAdmissionRow]) -> list[TrainingRecord]:
    sft_records: list[TrainingRecord] = []
    for row in admissions:
        split = _resolve_admission_split(row.sample_id)
        metadata = {"source": "sft_admissions", "source_round": row.source_round}
        sft_records.append(
            TrainingRecord(
                sample_id=row.sample_id,
                role=ROLE_CONTROLLER,
                state_input=copy.deepcopy(row.state_input),
                gold_output=copy.deepcopy(row.reference_action),
                verifier_sidecar=VerifierSidecar(),
                reward_spec_id=CONTROLLER_REWARD_SPEC_ID,
                split=split,
                metadata=copy.deepcopy(metadata),
            )
        )
    return sft_records


def _resolve_previous_admissions_path(*, round_assets_root: Path, previous_round_id: str | None) -> Path | None:
    if not previous_round_id:
        return None
    previous_dir = resolve_round_dir(round_id=previous_round_id, root=round_assets_root)
    path = previous_dir / "sft_admissions.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"previous round admissions not found: {path}")
    return path
def _resolve_admission_split(sample_id: str) -> str:
    digest = hashlib.sha256(sample_id.encode("utf-8")).hexdigest()
    return "eval" if int(digest[:2], 16) < 26 else "train"
