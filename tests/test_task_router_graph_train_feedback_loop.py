from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.dataset import prepare_round_assets, read_jsonl
from task_router_graph_train.feedback import admit_preference_admissions, annotate_teacher_queue, enqueue_teacher_queue
from task_router_graph_train.runtime_adapter import build_controller_state_input


def _state_input() -> dict:
    return build_controller_state_input(
        user_input="继续",
        environment_payload={"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
    )


def _valid_action(reason: str = "admit") -> dict:
    return {
        "action_kind": "observe",
        "tool": "build_context_view",
        "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
        "reason": reason,
    }


def test_enqueue_teacher_queue_preserves_raw_and_parsed_payloads(tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    candidates_path = tmp_path / "candidates.jsonl"
    raw_json = json.dumps(_valid_action("raw"), ensure_ascii=False)
    rows = [
        {
            "sample_id": "dict_1",
            "source": "holdout",
            "trigger_reason": "schema_failed",
            "state_input": _state_input(),
            "policy_output": {"action_kind": "unknown"},
        },
        {
            "sample_id": "raw_1",
            "source": "holdout",
            "trigger_reason": "holdout_failed",
            "state_input": _state_input(),
            "policy_output_raw_text": raw_json,
        },
        {
            "sample_id": "bad_raw_1",
            "source": "holdout",
            "trigger_reason": "parse_failed",
            "state_input": _state_input(),
            "policy_output_raw_text": "not-json",
            "parse_ok": False,
        },
    ]
    candidates_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    queue_report = enqueue_teacher_queue(round_manifest=Path(report["manifest_path"]), candidates_path=candidates_path)
    queue_rows = read_jsonl(Path(report["round_dir"]) / "teacher_queue.jsonl")

    assert queue_report["queued_count"] == 3
    assert queue_rows[0]["policy_output_raw_text"].startswith("{")
    assert queue_rows[0]["metadata"]["policy_output_raw_text_is_fallback"] is True
    assert queue_rows[1]["policy_output"]["reason"] == "raw"
    assert queue_rows[1]["policy_output_raw_text"] == raw_json
    assert queue_rows[2]["policy_output"] == {}
    assert queue_rows[2]["policy_output_raw_text"] == "not-json"


def test_enqueue_teacher_queue_selects_group_worst(tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    candidates_path = tmp_path / "candidates.jsonl"
    rows = [
        {"sample_id": "g1_a", "source": "rollout", "group_id": "g1", "teacher_rank": 0, "state_input": _state_input(), "policy_output": _valid_action("ok")},
        {"sample_id": "g1_b", "source": "rollout", "group_id": "g1", "teacher_rank": 9, "state_input": _state_input(), "policy_output": _valid_action("worse")},
    ]
    candidates_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    queue_report = enqueue_teacher_queue(round_manifest=Path(report["manifest_path"]), candidates_path=candidates_path)
    queue_rows = read_jsonl(Path(report["round_dir"]) / "teacher_queue.jsonl")

    assert queue_report["queued_count"] == 1
    assert queue_rows[0]["sample_id"] == "g1_b"


def test_admit_preference_admissions_accepts_only_valid_gold(tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    decisions_path = tmp_path / "decisions.jsonl"
    rows = [
        {
            "sample_id": "p1",
            "admission": True,
            "state_input": _state_input(),
            "chosen_response": _valid_action("gold"),
            "rejected_response": _valid_action("bad"),
            "rejected_raw_text": json.dumps(_valid_action("bad"), ensure_ascii=False),
            "source": "holdout",
            "trigger_reason": "holdout_failed",
            "reason": "ok",
            "confidence": 1.0,
        },
        {
            "sample_id": "p2",
            "admission": True,
            "state_input": _state_input(),
            "chosen_response": {"action_kind": "bad"},
            "rejected_response": _valid_action("bad"),
            "rejected_raw_text": json.dumps(_valid_action("bad"), ensure_ascii=False),
            "reason": "bad",
        },
    ]
    decisions_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    admission_report = admit_preference_admissions(round_manifest=Path(report["manifest_path"]), teacher_decisions_path=decisions_path)
    preference_rows = read_jsonl(Path(report["round_dir"]) / "preference_admissions.jsonl")

    assert admission_report["admitted_count"] == 1
    assert preference_rows[0]["chosen_response"]["reason"] == "gold"
    assert preference_rows[0]["rejected_raw_text"]


def test_admit_preference_admissions_rejects_empty_reason_and_duplicates(tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    decision = {
        "sample_id": "p1",
        "admission": True,
        "state_input": _state_input(),
        "chosen_response": _valid_action("gold"),
        "rejected_response": _valid_action("bad"),
        "rejected_raw_text": json.dumps(_valid_action("bad"), ensure_ascii=False),
        "source": "holdout",
        "trigger_reason": "holdout_failed",
        "reason": "ok",
        "confidence": 1.0,
    }
    decisions_path = tmp_path / "decisions.jsonl"
    decisions_path.write_text(
        json.dumps({**decision, "reason": ""}, ensure_ascii=False) + "\n" + json.dumps(decision, ensure_ascii=False) + "\n" + json.dumps({**decision, "sample_id": "p2"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    admission_report = admit_preference_admissions(round_manifest=Path(report["manifest_path"]), teacher_decisions_path=decisions_path)
    preference_rows = read_jsonl(Path(report["round_dir"]) / "preference_admissions.jsonl")

    assert admission_report["admitted_count"] == 1
    assert len(preference_rows) == 1


def test_annotate_teacher_queue_generates_decisions_and_preference_admissions(monkeypatch, tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    queue_manifest = Path(report["manifest_path"])
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(
        json.dumps(
            {
                "sample_id": "q1",
                "source": "holdout",
                "trigger_reason": "holdout_failed",
                "state_input": _state_input(),
                "policy_output": _valid_action("bad"),
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
                    "rubric_id": "controller_preference_admission_v1",
                },
            }
        },
    )
    monkeypatch.setattr(
        "task_router_graph_train.feedback.review_badcase_for_preference",
        lambda **kwargs: {
            "sample_id": kwargs["sample_id"],
            "admission": True,
            "chosen_response": _valid_action("gold"),
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
    assert annotate_report["preference_admissions_count"] == 1
    assert "sft_admissions_count" not in annotate_report
