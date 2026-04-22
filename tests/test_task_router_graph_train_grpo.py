from __future__ import annotations

from pathlib import Path

from task_router_graph_train.dataset import build_controller_train_records
from task_router_graph_train.runtime_adapter import ASSETS_ROOT, REPO_ROOT
from task_router_graph_train.train import (
    build_grpo_rollout_groups,
    build_teacher_rankings,
    train_controller_grpo,
    validate_controller_action,
    validate_teacher_rankings,
)


def test_validate_controller_action_for_observe_and_generate_task() -> None:
    observe_ok, observe_errors = validate_controller_action(
        {
            "action_kind": "observe",
            "reason": "先读状态",
            "tool": "read",
            "args": {"target": "latest_round"},
            "task_type": None,
            "task_content": None,
        }
    )
    assert observe_ok is True
    assert observe_errors == []

    generate_ok, generate_errors = validate_controller_action(
        {
            "action_kind": "generate_task",
            "reason": "创建功能测试任务",
            "tool": None,
            "args": {},
            "task_type": "functest",
            "task_content": "执行登录流程功能测试",
        }
    )
    assert generate_ok is True
    assert generate_errors == []

    invalid_ok, invalid_errors = validate_controller_action({"action_kind": "invalid"})
    assert invalid_ok is False
    assert "action_kind must be one of" in invalid_errors[0]


def test_build_grpo_rollout_groups_smoke() -> None:
    records, _ = build_controller_train_records(
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        workspace_root=REPO_ROOT,
    )
    groups = build_grpo_rollout_groups(records=records, num_candidates=4, seed=7)
    assert len(groups) == len(records)
    first = groups[0]
    assert len(first["candidates"]) == 4
    assert first["candidates"][0]["source"] == "gold"
    assert "group_id" in first


def test_validate_teacher_rankings_rejects_mismatch() -> None:
    records, _ = build_controller_train_records(
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        workspace_root=REPO_ROOT,
    )
    groups = build_grpo_rollout_groups(records=records[:1], num_candidates=3, seed=13)
    ranking_rows = [
        {
            "group_id": groups[0]["group_id"],
            "ranking": ["cand_00", "cand_02"],
        }
    ]
    try:
        validate_teacher_rankings(groups=groups, rankings=ranking_rows)
    except ValueError as exc:
        assert "ranking candidate ids mismatch" in str(exc)
    else:
        raise AssertionError("expected ranking mismatch to fail")


def test_train_controller_grpo_oracle_writes_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "grpo_out"
    report = train_controller_grpo(
        output_dir=output_dir,
        teacher_mode="oracle",
        teacher_source_dir=ASSETS_ROOT / "sft_v1" / "teacher_source",
        runtime_root=REPO_ROOT,
        num_candidates=4,
        keep_top_k=2,
        seed=42,
        run_sft_update=False,
    )
    assert report["group_count"] == 16
    assert report["train_example_count"] > 0
    assert (output_dir / "grpo_rollout_groups.jsonl").exists()
    assert (output_dir / "teacher_rankings.jsonl").exists()
    assert (output_dir / "grpo_train_examples.jsonl").exists()
    assert (output_dir / "grpo_eval_examples.jsonl").exists()
    assert (output_dir / "grpo_train_report.json").exists()

    ranking_rows = build_teacher_rankings(
        groups=[],
        mode="oracle",
    )
    assert ranking_rows == []
