from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.dataset import prepare_round_assets
from task_router_graph_train.feedback import admit_sft_admissions, annotate_teacher_queue, enqueue_teacher_queue
from task_router_graph_train.runtime_adapter import build_controller_state_input


def _state_input() -> dict:
    return build_controller_state_input(
        user_input="继续",
        environment_payload={"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
    )


def test_enqueue_teacher_queue_selects_explicit_and_group_worst(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)

    candidates_path = tmp_path / "candidates.jsonl"
    rows = [
        {
            "sample_id": "explicit_1",
            "source": "holdout",
            "trigger_reason": "schema_failed",
            "state_input": _state_input(),
            "policy_output": {"action_kind": "unknown"},
        },
        {
            "sample_id": "g1_a",
            "source": "rollout",
            "group_id": "g1",
            "teacher_rank": 0,
            "state_input": _state_input(),
            "policy_output": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "ok"},
        },
        {
            "sample_id": "g1_b",
            "source": "rollout",
            "group_id": "g1",
            "teacher_rank": 9,
            "state_input": _state_input(),
            "policy_output": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "worse"},
        },
    ]
    candidates_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    report = enqueue_teacher_queue(round_manifest=Path(report["manifest_path"]), candidates_path=candidates_path)
    assert report["queued_count"] == 2


def test_admit_sft_admissions_accepts_only_valid_action(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)

    decisions_path = tmp_path / "decisions.jsonl"
    valid_action = {
        "action_kind": "observe",
        "tool": "build_context_view",
        "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
        "reason": "admit",
    }
    rows = [
        {"sample_id": "a1", "admission": True, "state_input": _state_input(), "reference_action": valid_action, "reason": "ok"},
        {"sample_id": "a2", "admission": True, "state_input": _state_input(), "reference_action": {"action_kind": "bad"}, "reason": "bad"},
    ]
    decisions_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    report = admit_sft_admissions(round_manifest=Path(report["manifest_path"]), teacher_decisions_path=decisions_path)
    assert report["admitted_count"] == 1


def test_admit_sft_admissions_rejects_empty_reason(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)

    decisions_path = tmp_path / "decisions.jsonl"
    valid_action = {
        "action_kind": "observe",
        "tool": "build_context_view",
        "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
        "reason": "admit",
    }
    decisions_path.write_text(
        json.dumps({"sample_id": "a1", "admission": True, "state_input": _state_input(), "reference_action": valid_action, "reason": ""}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = admit_sft_admissions(round_manifest=Path(report["manifest_path"]), teacher_decisions_path=decisions_path)
    assert report["admitted_count"] == 0


def test_admit_sft_admissions_rejects_duplicate_training_content(tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)

    decisions_path = tmp_path / "decisions.jsonl"
    state_input = build_controller_state_input(
        user_input="现在进展怎么样了",
        environment_payload={
            "cur_round": 2,
            "rounds": [
                {
                    "round_id": 1,
                    "user_input": "帮我整理最近一周上海AI大会消息",
                    "reply": "",
                    "tasks": [
                        {
                            "task_id": 1,
                            "task": {
                                "task_id": 1,
                                "type": "executor",
                                "content": "用户目标：整理最近一周上海AI大会消息\n任务限制：只基于公开信息收集，不猜测未提供的外部事实",
                                "status": "running",
                                "result": "正在执行",
                            },
                            "track": [],
                        }
                    ],
                },
                {"round_id": 2, "user_input": "现在进展怎么样了", "reply": "", "tasks": []},
            ],
            "history_summaries": [],
            "history_meta_summary": "",
        },
    )
    reference_action = {
        "action_kind": "observe",
        "tool": "build_context_view",
        "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
        "reason": "当前已有运行中任务，先读取正式上下文再决定下一步。",
    }
    decisions_path.write_text(
        json.dumps({"sample_id": "dup_1", "admission": True, "state_input": state_input, "reference_action": reference_action, "reason": "duplicate"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = admit_sft_admissions(round_manifest=Path(report["manifest_path"]), teacher_decisions_path=decisions_path)
    assert report["admitted_count"] == 0


def test_annotate_teacher_queue_generates_decisions_and_admissions(monkeypatch, tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)
    queue_manifest = Path(report["manifest_path"])

    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "sample_id": "q1",
                "source": "holdout",
                "trigger_reason": "holdout_failed",
                "state_input": _state_input(),
                "policy_output": {
                    "action_kind": "observe",
                    "tool": "build_context_view",
                    "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
                    "reason": "x",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    enqueue_teacher_queue(round_manifest=queue_manifest, candidates_path=candidates_path)

    monkeypatch.setattr(
        "task_router_graph_train.feedback._load_feedback_config",
        lambda _path=None: {
            "teacher": {
                "mode": "online",
                "base_url": "http://x",
                "model": "m",
                "api_key_env": "",
                "allow_missing_api_key": True,
                "admission_judge": {
                    "mode": "online",
                    "base_url": "http://x",
                    "model": "m",
                    "allow_missing_api_key": True,
                    "timeout_sec": 1,
                    "rubric_id": "controller_sft_admission_v1",
                },
            }
        },
    )
    monkeypatch.setattr(
        "task_router_graph_train.feedback.review_badcase_for_sft",
        lambda **kwargs: {
            "sample_id": kwargs["sample_id"],
            "admission": True,
            "reference_action": {
                "action_kind": "observe",
                "tool": "build_context_view",
                "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
                "reason": "admit",
            },
            "confidence": 1.0,
            "reason": "ok",
            "schema_valid": True,
            "validation_errors": [],
            "protocol_valid": True,
            "protocol_errors": [],
        },
    )

    annotate_report = annotate_teacher_queue(round_manifest=queue_manifest)
    assert annotate_report["decision_count"] == 1
    assert annotate_report["sft_admissions_count"] >= 1
