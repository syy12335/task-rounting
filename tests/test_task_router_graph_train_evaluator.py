from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.dataset import prepare_round_assets
from task_router_graph_train.eval import build_holdout_badcase_candidates, evaluate_holdout_predictions


def test_evaluate_holdout_predictions_uses_semantic_pass(monkeypatch, tmp_path: Path) -> None:
    records_path = tmp_path / "holdout_records.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"

    holdout_row = {
        "sample_id": "h1",
        "state_input": {
            "USER_INPUT": "进展如何",
            "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
            "SKILLS_INDEX": "[]",
        },
        "gold_action": {
            "action_kind": "observe",
            "tool": "build_context_view",
            "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
            "reason": "观察",
        },
        "metadata": {"bucket_key": "holdout"},
    }
    records_path.write_text(json.dumps(holdout_row, ensure_ascii=False) + "\n", encoding="utf-8")

    predictions_path.write_text(
        json.dumps({"sample_id": "h1", "prediction": holdout_row["gold_action"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator._resolve_regression_teacher",
        lambda _cfg: {"mode": "online", "base_url": "http://x", "model": "m", "api_key": "k", "timeout_sec": 1, "rubric_id": "controller_regression_judge_v1"},
    )
    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator.judge_action_semantic_equivalence",
        lambda **_: {"semantic_equivalent": True, "score": 1.0, "reason": "equivalent"},
    )

    report = evaluate_holdout_predictions(record_path=records_path, prediction_path=predictions_path)
    assert report["metrics_summary"]["semantic_pass_rate"] == 1.0
    assert report["evidence_rows"][0]["semantic_pass"] is True


def test_evaluate_holdout_predictions_respects_max_samples(monkeypatch, tmp_path: Path) -> None:
    records_path = tmp_path / "holdout_records.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"

    def build_row(sample_id: str) -> dict[str, object]:
        return {
            "sample_id": sample_id,
            "state_input": {
                "USER_INPUT": "进展如何",
                "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
                "SKILLS_INDEX": "[]",
            },
            "gold_action": {
                "action_kind": "observe",
                "tool": "build_context_view",
                "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
                "reason": "观察",
            },
            "metadata": {"bucket_key": "holdout"},
        }

    records_path.write_text(
        "\n".join(json.dumps(build_row(sample_id), ensure_ascii=False) for sample_id in ("h1", "h2")) + "\n",
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps({"sample_id": "h1", "prediction": build_row("h1")["gold_action"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator._resolve_regression_teacher",
        lambda _cfg: {"mode": "online", "base_url": "http://x", "model": "m", "api_key": "k", "timeout_sec": 1, "rubric_id": "controller_regression_judge_v1"},
    )
    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator.judge_action_semantic_equivalence",
        lambda **_: {"semantic_equivalent": True, "score": 1.0, "reason": "equivalent"},
    )

    report = evaluate_holdout_predictions(record_path=records_path, prediction_path=predictions_path, max_samples=1)

    assert report["run_manifest"]["evaluated_count"] == 1
    assert report["metrics_summary"]["row_count"] == 1
    assert report["metrics_summary"]["semantic_pass_rate"] == 1.0


def test_build_holdout_badcase_candidates_skips_passed_rows() -> None:
    rows = [
        {
            "sample_id": "p1",
            "state_input": {"USER_INPUT": "u"},
            "prediction_action": {},
            "semantic_pass": True,
        },
        {
            "sample_id": "f1",
            "state_input": {"USER_INPUT": "u"},
            "prediction_action": {"action_kind": "observe"},
            "prediction_raw_text": '{"action_kind":"observe"}',
            "semantic_pass": False,
            "trigger_reason": "holdout_failed",
            "parse_valid": True,
            "schema_valid": True,
            "protocol_valid": False,
        },
    ]
    candidates = build_holdout_badcase_candidates(rows)
    assert len(candidates) == 1
    assert candidates[0]["sample_id"] == "f1"
    assert candidates[0]["policy_output_raw_text"] == '{"action_kind":"observe"}'


def test_evaluate_holdout_predictions_can_enqueue_failed_badcases(monkeypatch, tmp_path: Path) -> None:
    round_root = tmp_path / "rounds"
    round_report = prepare_round_assets(round_id="round_0001", round_assets_root=round_root)
    records_path = tmp_path / "holdout_records.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"

    holdout_row = {
        "sample_id": "h2",
        "state_input": {
            "USER_INPUT": "进展如何",
            "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summaries": [], "history_meta_summary": ""},
            "SKILLS_INDEX": "[]",
        },
        "gold_action": {
            "action_kind": "observe",
            "tool": "build_context_view",
            "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
            "reason": "观察",
        },
        "metadata": {"bucket_key": "holdout"},
    }
    records_path.write_text(json.dumps(holdout_row, ensure_ascii=False) + "\n", encoding="utf-8")
    predictions_path.write_text(
        json.dumps({"sample_id": "h2", "prediction": {"action_kind": "generate_task", "task_type": "executor", "task_content": "bad", "reason": "x"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator._resolve_regression_teacher",
        lambda _cfg: {"mode": "online", "base_url": "http://x", "model": "m", "api_key": "k", "timeout_sec": 1, "rubric_id": "controller_regression_judge_v1"},
    )
    monkeypatch.setattr(
        "task_router_graph_train.eval.evaluator.enqueue_teacher_queue",
        lambda **_: {"queued_count": 1, "teacher_queue_count": 1},
    )

    report = evaluate_holdout_predictions(
        record_path=records_path,
        prediction_path=predictions_path,
        enqueue_failed_badcases=True,
        badcase_round_manifest=Path(round_report["manifest_path"]),
    )
    assert report["evidence_rows"][0]["protocol_valid"] is False
    assert report["badcase_enqueue_report"]["queued_count"] == 1
