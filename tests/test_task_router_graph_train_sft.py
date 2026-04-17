from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.dataset import (
    build_controller_sft_examples,
    build_controller_train_records,
    read_jsonl,
    write_controller_sft_assets,
)
from task_router_graph_train.runtime_adapter import ASSETS_ROOT, REPO_ROOT
from task_router_graph_train.train import build_sft_token_labels, tokenize_sft_example
from task_router_graph_train.types import SftExample


class FakeTokenizer:
    eos_token_id = 99

    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        del add_special_tokens
        return [index + 1 for index, _ in enumerate(text)]


def test_build_controller_train_records_from_teacher_source() -> None:
    records, manifest = build_controller_train_records(
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        workspace_root=REPO_ROOT,
    )

    assert len(records) == 16
    assert manifest["counts_by_split"] == {"train": 12, "eval": 4}
    assert {record.role for record in records} == {"controller"}
    assert {record.reward_spec_id for record in records} == {"controller_v1"}

    sample = next(record for record in records if record.sample_id == "teacher_train_009_retry_failed_task_step1")
    assert set(sample.state_input) == {"USER_INPUT", "TASKS_JSON", "SKILLS_INDEX"}
    assert "running_refs" not in json.dumps(sample.state_input, ensure_ascii=False)
    assert sample.metadata["allowed_action_kinds"] == ["observe", "generate_task"]
    assert sample.gold_output["action_kind"] == "generate_task"


def test_build_controller_sft_examples_contains_prompt_sections() -> None:
    records, _ = build_controller_train_records(
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        workspace_root=REPO_ROOT,
    )
    examples = build_controller_sft_examples(records)

    assert len(examples) == 16
    example = next(row for row in examples if row.sample_id == "teacher_eval_003_history_summary_step1")
    assert "USER_INPUT" in example.prompt
    assert "TASKS_JSON" in example.prompt
    assert "SKILLS_INDEX" in example.prompt
    target_json = json.loads(example.target_text)
    assert isinstance(target_json, dict)
    assert target_json["action_kind"] == "generate_task"


def test_build_sft_token_labels_masks_prompt_tokens() -> None:
    feature_row = build_sft_token_labels(
        prompt_token_ids=[1, 2, 3],
        target_token_ids=[4, 5],
        eos_token_id=99,
        max_seq_length=8,
    )

    assert feature_row["input_ids"] == [1, 2, 3, 4, 5, 99]
    assert feature_row["labels"] == [-100, -100, -100, 4, 5, 99]


def test_tokenize_sft_example_uses_only_target_tokens_for_loss() -> None:
    example = SftExample(
        sample_id="demo",
        split="train",
        prompt="USER_INPUT\n继续",
        target_text='{"action_kind": "observe"}',
        metadata={"step": 1},
    )

    feature_row = tokenize_sft_example(
        example=example,
        tokenizer=FakeTokenizer(),
        max_seq_length=128,
    )

    prompt_length = len(FakeTokenizer().encode(example.prompt))
    assert feature_row["labels"][:prompt_length] == [-100] * prompt_length
    assert feature_row["labels"][-1] == FakeTokenizer.eos_token_id
    assert feature_row["metadata"]["step"] == 1


def test_write_controller_sft_assets_smoke(tmp_path: Path) -> None:
    records, manifest = build_controller_train_records(
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        workspace_root=REPO_ROOT,
    )
    output_paths = write_controller_sft_assets(
        output_root=tmp_path / "sft_v1",
        records=records,
        manifest=manifest,
    )

    assert output_paths["manifest_path"].exists()
    assert len(read_jsonl(output_paths["record_train_path"])) == 12
    assert len(read_jsonl(output_paths["record_eval_path"])) == 4
    assert len(read_jsonl(output_paths["example_train_path"])) == 12
    assert len(read_jsonl(output_paths["example_eval_path"])) == 4
