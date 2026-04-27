from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.eval import (
    find_latest_grpo_checkpoint,
    parse_grpo_step_metrics,
    render_grpo_training_chart_html,
    summarize_grpo_reward_audit,
    write_grpo_diagnostics,
)


def test_parse_grpo_step_metrics_extracts_verl_console_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "verl_stdout.log"
    log_path.write_text(
        "\x1b[36m(TaskRunner pid=1)\x1b[0m step:1 - actor/kl_loss:0.02 - actor/lr:2e-06 "
        "- critic/score/mean:0.5 - critic/rewards/mean:0.5 - response_length/mean:72.0 "
        "- response_length/clip_ratio:0.0 - perf/throughput:123.4\n"
        "[GRPO metrics] step=2 critic/score/mean=0.75 actor/kl_loss=0.03 response_length/mean=80.0\n",
        encoding="utf-8",
    )

    rows = parse_grpo_step_metrics(log_path)

    assert [row["step"] for row in rows] == [1, 2]
    assert rows[0]["critic/score/mean"] == 0.5
    assert rows[0]["actor/lr"] == 2e-6
    assert rows[1]["critic/score/mean"] == 0.75


def test_summarize_grpo_reward_audit_counts_groups_and_candidates(tmp_path: Path) -> None:
    audit_path = tmp_path / "reward_audit.jsonl"
    rows = [
        {
            "group_id": "g1",
            "passed_count": 3,
            "failure_counts_by_stage": {"schema": 1},
            "teacher_called": True,
            "teacher_skipped": False,
            "teacher_confidence": 0.9,
            "teacher_format_errors": [],
            "candidates": [
                {"candidate_id": "c1", "hard_gate_passed": True, "reward_score": 1.0},
                {"candidate_id": "c2", "hard_gate_passed": False, "reward_score": -1.0},
            ],
        },
        {
            "group_id": "g2",
            "passed_count": 0,
            "failure_counts_by_stage": {"parse": 2},
            "teacher_called": False,
            "teacher_skipped": True,
            "teacher_format_errors": ["bad_json"],
            "candidates": [
                {"candidate_id": "c3", "hard_gate_passed": False, "reward_score": -1.0},
            ],
        },
    ]
    audit_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summary = summarize_grpo_reward_audit(audit_path)

    assert summary["group_count"] == 2
    assert summary["teacher_skipped_count"] == 1
    assert summary["format_error_group_count"] == 1
    assert summary["passed_count_distribution"] == {"0": 1, "3": 1}
    assert summary["failure_counts_by_stage"] == {"parse": 2, "schema": 1}
    assert summary["candidate_pass_rate"] == 0.333333


def test_write_grpo_diagnostics_writes_artifacts_and_chart(tmp_path: Path) -> None:
    output_dir = tmp_path / "grpo"
    eval_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "verl_stdout.log").write_text(
        "step:1 - critic/score/mean:0.25 - actor/kl_loss:0.0 - response_length/mean:60.0 - response_length/clip_ratio:0.0\n",
        encoding="utf-8",
    )
    (output_dir / "reward_audit.jsonl").write_text(
        json.dumps({"group_id": "g1", "passed_count": 1, "teacher_called": True, "candidates": []}) + "\n",
        encoding="utf-8",
    )

    diagnostics = write_grpo_diagnostics(output_dir=output_dir, eval_output_dir=eval_dir)
    html = render_grpo_training_chart_html(
        diagnostics["step_metrics"],
        diagnostics["summary"]["reward_audit"],
    )

    assert Path(diagnostics["step_metrics_path"]).exists()
    assert diagnostics["summary"]["step_metrics"]["last_score_mean"] == 0.25
    assert "critic/score/mean" in html
    assert "GRPO Training Diagnostics" in html


def test_find_latest_grpo_checkpoint_detects_hf_actor_model(tmp_path: Path) -> None:
    output_dir = tmp_path / "grpo"
    checkpoint_dir = output_dir / "checkpoints"
    hf_model_dir = checkpoint_dir / "global_step_11" / "actor" / "huggingface"
    hf_model_dir.mkdir(parents=True)
    (checkpoint_dir / "latest_checkpointed_iteration.txt").write_text("11\n", encoding="utf-8")
    (hf_model_dir / "config.json").write_text("{}", encoding="utf-8")
    (hf_model_dir / "model.safetensors").write_text("", encoding="utf-8")

    summary = find_latest_grpo_checkpoint(output_dir=output_dir)

    assert summary["latest_step"] == 11
    assert summary["hf_model_exists"] is True
    assert summary["hf_model_path"] == str(hf_model_dir.resolve())
