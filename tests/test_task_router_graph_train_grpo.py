from __future__ import annotations

import inspect
from pathlib import Path

from task_router_graph_train.dataset import prepare_round_assets
from task_router_graph_train.train import controller_grpo
from task_router_graph_train.train import controller_grpo_teacher


def test_train_controller_grpo_signature_drops_legacy_inputs() -> None:
    params = inspect.signature(controller_grpo.train_controller_grpo).parameters
    assert "teacher_source_dir" not in params
    assert "holdout_records" not in params
    assert "holdout_predictions" not in params


def test_grpo_input_resolution_reads_round_records(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)

    resolved = controller_grpo._resolve_grpo_input_artifacts(
        round_id=None,
        round_manifest=Path(report["manifest_path"]),
        train_records=None,
        eval_records=None,
        allow_unsafe_path_input=False,
    )
    assert resolved["controller_records"]
    assert not resolved["unsafe_path_input"]


def test_inspect_candidate_action_separates_parse_schema_protocol() -> None:
    protocol_bad = controller_grpo_teacher.inspect_candidate_action(
        '{"action_kind":"generate_task","task_type":"executor","task_content":"单段内容","reason":"x"}'
    )
    assert protocol_bad["parse_ok"] is True
    assert protocol_bad["schema_ok"] is True
    assert protocol_bad["protocol_ok"] is False
    assert protocol_bad["failure_stage"] == "protocol"


def test_normalize_teacher_result_blends_dimension_scores() -> None:
    result = controller_grpo_teacher.normalize_teacher_result(
        group_id="g1",
        raw_result={
            "dimension_scores_by_candidate": {
                "c1": {
                    "environment_raw_score": 1.0,
                    "action_raw_score": 0.3,
                    "args_raw_score": 0.2,
                },
                "c2": {
                    "environment_raw_score": 0.4,
                    "action_raw_score": 1.0,
                    "args_raw_score": 1.0,
                },
            },
            "confidence": 1.0,
            "reason": "ok",
        },
        candidate_ids=["c1", "c2"],
    )
    assert result["alpha"] == 0.9
    assert result["weights"] == {"environment": 0.5, "action": 0.3, "args": 0.2}
    assert set(result["ranking"]) == {"c1", "c2"}


def test_judge_controller_group_appends_hard_gate_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        controller_grpo_teacher,
        "_chat_json",
        lambda **_: {
            "dimension_scores_by_candidate": {
                "good": {
                    "environment_raw_score": 0.9,
                    "action_raw_score": 0.9,
                    "args_raw_score": 0.9,
                }
            },
            "confidence": 1.0,
            "reason": "ok",
        },
    )
    result = controller_grpo_teacher.judge_controller_group(
        group_id="g1",
        state_input={"USER_INPUT": "u", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
        prompt_text="p",
        teacher_config={"mode": "online", "base_url": "http://x", "model": "m", "api_key": "k", "timeout_sec": 1, "rubric_id": "controller_grpo_pairwise_v1"},
        candidates=[
            {
                "candidate_id": "good",
                "raw_text": '{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":false,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"ok"}',
                "action": {},
            },
            {
                "candidate_id": "bad",
                "raw_text": '{"action_kind":"generate_task","task_type":"executor","task_content":"bad","reason":"bad"}',
                "action": {},
            },
        ],
    )
    assert result["ranking"][-1] == "bad"
    assert result["hard_gate_results"]["bad"]["failure_stage"] == "protocol"
