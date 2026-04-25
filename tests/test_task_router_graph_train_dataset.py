from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.dataset import prepare_round_assets, read_jsonl
from task_router_graph_train.runtime_adapter import ASSETS_ROOT, build_controller_state_input


def test_prepare_round_assets_builds_required_outputs(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(
        round_id="round_0001",
        round_assets_root=round_root,
        manual_protocol_dir=ASSETS_ROOT / "manual_protocol_v1",
    )

    round_dir = Path(report["round_dir"])
    assert (round_dir / "round_manifest.json").exists()
    assert (round_dir / "sft_examples_train.jsonl").exists()
    assert (round_dir / "sft_examples_eval.jsonl").exists()
    assert (round_dir / "controller_records_train.jsonl").exists()
    assert (round_dir / "controller_records_eval.jsonl").exists()
    assert (round_dir / "holdout_records.jsonl").exists()
    assert (round_dir / "teacher_queue.jsonl").exists()
    assert (round_dir / "sft_admissions.jsonl").exists()

    holdout_rows = read_jsonl(round_dir / "holdout_records.jsonl")
    sft_rows = read_jsonl(round_dir / "sft_examples_train.jsonl") + read_jsonl(round_dir / "sft_examples_eval.jsonl")
    grpo_rows = read_jsonl(round_dir / "controller_records_train.jsonl") + read_jsonl(round_dir / "controller_records_eval.jsonl")
    assert report["counts_by_split"]["sft_admissions"] == 0
    assert (round_dir / "sft_admissions.jsonl").read_text(encoding="utf-8") == ""
    assert holdout_rows
    assert sft_rows
    assert grpo_rows
    holdout_ids = {row["sample_id"] for row in holdout_rows}
    assert not (holdout_ids & {row["sample_id"] for row in sft_rows})
    assert not (holdout_ids & {row["sample_id"] for row in grpo_rows})
    assert all("gold_output" not in row for row in grpo_rows)
    assert all("verifier_sidecar" not in row for row in grpo_rows)


def test_prepare_round_assets_merges_previous_admissions(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    first = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)
    first_dir = Path(first["round_dir"])

    admission_state = build_controller_state_input(
        user_input="请继续处理",
        environment_payload={"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
    )
    (first_dir / "sft_admissions.jsonl").write_text(
        '{"sample_id":"adm_001","state_input":' +
        json.dumps(admission_state, ensure_ascii=False) +
        ',"reference_action":{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":false,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"补充观察"},"reason":"admit","source_round":"round_0001"}\n',
        encoding="utf-8",
    )

    second = prepare_round_assets(
        round_id="round_0002",
        previous_round_id="round_0001",
        round_assets_root=round_root,
    )
    second_dir = Path(second["round_dir"])
    sft_train = read_jsonl(second_dir / "sft_examples_train.jsonl")
    sft_eval = read_jsonl(second_dir / "sft_examples_eval.jsonl")
    grpo_train = read_jsonl(second_dir / "controller_records_train.jsonl")
    grpo_eval = read_jsonl(second_dir / "controller_records_eval.jsonl")
    all_ids = {row["sample_id"] for row in (sft_train + sft_eval)}
    grpo_ids = {row["sample_id"] for row in (grpo_train + grpo_eval)}
    assert "adm_001" in all_ids
    assert "adm_001" not in grpo_ids
    assert (second_dir / "sft_admissions.jsonl").read_text(encoding="utf-8") == ""
    assert second["counts_by_split"]["sft_admissions"] == 0


def test_prepare_round_assets_filters_protocol_invalid_previous_admissions(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    first = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)
    first_dir = Path(first["round_dir"])

    admission_state = build_controller_state_input(
        user_input="请继续处理",
        environment_payload={"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
    )
    (first_dir / "sft_admissions.jsonl").write_text(
        '{"sample_id":"adm_bad","state_input":' +
        json.dumps(admission_state, ensure_ascii=False) +
        ',"reference_action":{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":true,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"补充观察"},"reason":"admit","source_round":"round_0001"}\n',
        encoding="utf-8",
    )

    second = prepare_round_assets(
        round_id="round_0002",
        previous_round_id="round_0001",
        round_assets_root=round_root,
    )
    second_dir = Path(second["round_dir"])
    sft_train = read_jsonl(second_dir / "sft_examples_train.jsonl")
    sft_eval = read_jsonl(second_dir / "sft_examples_eval.jsonl")
    all_ids = {row["sample_id"] for row in (sft_train + sft_eval)}
    assert "adm_bad" not in all_ids
