from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

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
    first = resolved["controller_records"][0]
    assert not hasattr(first, "gold_output")
    assert not hasattr(first, "verifier_sidecar")


def test_grpo_input_resolution_rejects_legacy_reference_fields(tmp_path: Path) -> None:
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    row = {
        "sample_id": "g1",
        "role": "controller",
        "state_input": {"USER_INPUT": "u", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
        "reward_spec_id": "controller_grpo_v1",
        "split": "train",
        "metadata": {},
        "gold_output": {},
    }
    train_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    eval_row = dict(row)
    eval_row["sample_id"] = "g2"
    eval_row["split"] = "eval"
    eval_path.write_text(json.dumps(eval_row, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        controller_grpo._resolve_grpo_input_artifacts(
            round_id=None,
            round_manifest=None,
            train_records=train_path,
            eval_records=eval_path,
            allow_unsafe_path_input=True,
        )
    except ValueError as exc:
        assert "must not include gold_output" in str(exc)
    else:
        raise AssertionError("expected GRPO parser to reject legacy gold_output rows")


def test_verl_overrides_include_ref_log_prob_micro_batch_size(tmp_path: Path) -> None:
    overrides = controller_grpo._build_verl_overrides(
        config={
            "model": {"path": "/model/default", "target_modules": ["q_proj", "v_proj"], "attn_implementation": "eager"},
            "rollout": {"backend": "sglang", "num_candidates": 4, "tensor_model_parallel_size": 2, "data_parallel_size": 2},
            "update": {
                "logger": ["console"],
                "learning_rate": 2e-4,
                "per_device_train_batch_size": 1,
                "n_gpus_per_node": 4,
                "nnodes": 1,
                "ref_log_prob_micro_batch_size_per_gpu": 1,
                "rollout_log_prob_micro_batch_size_per_gpu": 1,
                "actor_use_torch_compile": False,
                "enable_activation_offload": True,
                "actor_param_offload": True,
                "actor_optimizer_offload": True,
                "ref_param_offload": True,
                "ref_optimizer_offload": False,
            },
            "data": {
                "train_batch_size": 8,
                "val_batch_size": 4,
                "max_prompt_length": 2048,
                "max_response_length": 512,
            },
        },
        train_dataset_path=tmp_path / "train.jsonl",
        eval_dataset_path=tmp_path / "eval.jsonl",
        reward_manager_path=tmp_path / "reward.py",
    )
    assert "actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1" in overrides
    assert "actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1" in overrides
    assert '+actor_rollout_ref.model.override_config.attn_implementation="eager"' in overrides
    assert "trainer.n_gpus_per_node=4" in overrides
    assert "actor_rollout_ref.rollout.tensor_model_parallel_size=2" in overrides
    assert "actor_rollout_ref.rollout.data_parallel_size=2" in overrides
    assert "actor_rollout_ref.actor.use_torch_compile=false" in overrides
    assert "actor_rollout_ref.actor.fsdp_config.param_offload=true" in overrides
    assert "actor_rollout_ref.model.enable_activation_offload=true" in overrides


def test_validate_verl_parallelism_rejects_invalid_rollout_parallelism() -> None:
    with pytest.raises(ValueError):
        controller_grpo._validate_verl_parallelism_config(
            {
                "rollout": {"tensor_model_parallel_size": 3, "data_parallel_size": 2},
                "update": {"n_gpus_per_node": 4, "nnodes": 1},
            }
        )


def test_validate_verl_parallelism_warns_when_multi_gpu_rollout_is_single_shard() -> None:
    warnings = controller_grpo._validate_verl_parallelism_config(
        {
            "rollout": {"tensor_model_parallel_size": 1, "data_parallel_size": 1},
            "update": {"n_gpus_per_node": 4, "nnodes": 1},
        }
    )
    assert warnings


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
