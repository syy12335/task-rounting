from __future__ import annotations

import json
from pathlib import Path

from task_router_graph_train.eval import (
    build_holdout_prediction_jobs,
    evaluate_holdout_predictions,
    generate_holdout_predictions_from_hf_model,
    generate_holdout_predictions,
    render_metrics_summary_chart_html,
)
import task_router_graph_train.eval.holdout_inference as holdout_inference_module


def test_build_holdout_prediction_jobs_keeps_sample_id_and_prompt_shape(tmp_path: Path) -> None:
    record_path = tmp_path / "holdout.jsonl"
    record_path.write_text(
        json.dumps(
            {
                "sample_id": "h1",
                "state_input": {
                    "USER_INPUT": "先看下目前的任务视图",
                    "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summary_latest": [], "history_meta_summary": ""},
                    "SKILLS_INDEX": "[]",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    jobs = build_holdout_prediction_jobs(record_path=record_path)
    assert len(jobs) == 1
    assert jobs[0]["sample_id"] == "h1"
    assert "你是 task_router_graph 的 controller。" in jobs[0]["prompt_text"]


def test_generate_holdout_predictions_writes_response_rows(monkeypatch, tmp_path: Path) -> None:
    record_path = tmp_path / "holdout.jsonl"
    output_path = tmp_path / "predictions.jsonl"
    record_path.write_text(
        json.dumps(
            {
                "sample_id": "h1",
                "state_input": {
                    "USER_INPUT": "进展如何",
                    "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summary_latest": [], "history_meta_summary": ""},
                    "SKILLS_INDEX": "[]",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SGLANG_API_KEY", "EMPTY")
    monkeypatch.setattr(
        "task_router_graph_train.eval.holdout_inference._request_openai_compatible_completion",
        lambda **_: '{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":false,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"ok"}',
    )

    report = generate_holdout_predictions(
        record_path=record_path,
        output_path=output_path,
        base_url="http://127.0.0.1:30000/v1",
        api_key_env="SGLANG_API_KEY",
        model="qwen35-4b",
        timeout_sec=30,
        max_tokens=512,
        temperature=0.0,
    )
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert report["count"] == 1
    assert rows == [
        {
            "sample_id": "h1",
            "response": '{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":false,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"ok"}',
        }
    ]


def test_generate_holdout_predictions_from_hf_model_writes_response_rows(monkeypatch, tmp_path: Path) -> None:
    record_path = tmp_path / "holdout.jsonl"
    output_path = tmp_path / "predictions.jsonl"
    model_path = tmp_path / "checkpoint" / "actor" / "huggingface"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir(parents=True)
    tokenizer_path.mkdir()
    record_path.write_text(
        json.dumps(
            {
                "sample_id": "h1",
                "state_input": {
                    "USER_INPUT": "进展如何",
                    "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summary_latest": [], "history_meta_summary": ""},
                    "SKILLS_INDEX": "[]",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTorch:
        cuda = FakeCuda()

        @staticmethod
        def inference_mode() -> FakeContext:
            return FakeContext()

    class FakeTensor:
        shape = (1, 3)

        def to(self, _device: str) -> "FakeTensor":
            return self

    class FakeTokenizer:
        pad_token_id = 0
        eos_token_id = 2
        eos_token = "<eos>"

        @classmethod
        def from_pretrained(cls, path: Path, **_: object) -> "FakeTokenizer":
            assert Path(path) == tokenizer_path.resolve()
            return cls()

        def __call__(self, _prompt: str, **_: object) -> dict[str, FakeTensor]:
            return {"input_ids": FakeTensor(), "attention_mask": FakeTensor()}

        def decode(self, ids: list[int], **_: object) -> str:
            assert ids == [101, 102]
            return '{"action_kind":"observe","tool":"build_context_view","args":{"round_limit":3,"include_trace":false,"include_user_input":true,"include_task":true,"include_reply":true},"reason":"ok"}'

    class FakeModel:
        @classmethod
        def from_pretrained(cls, path: Path, **_: object) -> "FakeModel":
            assert Path(path) == model_path.resolve()
            return cls()

        def to(self, device: str) -> "FakeModel":
            assert device == "cpu"
            return self

        def eval(self) -> None:
            return None

        def generate(self, **_: object) -> list[list[int]]:
            return [[11, 12, 13, 101, 102]]

    monkeypatch.setattr(
        holdout_inference_module,
        "_load_hf_generation_dependencies",
        lambda: (FakeTorch, FakeModel, FakeTokenizer),
    )

    report = generate_holdout_predictions_from_hf_model(
        record_path=record_path,
        output_path=output_path,
        model_path=model_path,
        tokenizer_path=tokenizer_path,
        max_tokens=128,
        temperature=0.0,
    )
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert report["backend"] == "local_hf"
    assert report["count"] == 1
    assert rows[0]["sample_id"] == "h1"
    assert json.loads(rows[0]["response"])["action_kind"] == "observe"


def test_generated_response_rows_are_compatible_with_evaluator(monkeypatch, tmp_path: Path) -> None:
    records_path = tmp_path / "holdout_records.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"

    gold_action = {
        "action_kind": "observe",
        "tool": "build_context_view",
        "args": {"round_limit": 3, "include_trace": False, "include_user_input": True, "include_task": True, "include_reply": True},
        "reason": "观察",
    }
    records_path.write_text(
        json.dumps(
            {
                "sample_id": "h2",
                "state_input": {
                    "USER_INPUT": "进展如何",
                    "ENVIRONMENT_JSON": {"rounds": [], "cur_round": 1, "history_summary_latest": [], "history_meta_summary": ""},
                    "SKILLS_INDEX": "[]",
                },
                "gold_action": gold_action,
                "metadata": {"bucket_key": "holdout"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps({"sample_id": "h2", "response": json.dumps(gold_action, ensure_ascii=False)}, ensure_ascii=False) + "\n",
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


def test_render_metrics_summary_chart_html_contains_expected_metrics() -> None:
    html_output = render_metrics_summary_chart_html(
        {
            "row_count": 10,
            "semantic_failed_count": 2,
            "semantic_pass_rate": 0.8,
            "parse_valid_rate": 0.9,
            "schema_valid_rate": 0.7,
            "protocol_valid_rate": 0.6,
        }
    )
    assert "Holdout Evaluation Summary" in html_output
    assert "语义通过率" in html_output
    assert "80.0%" in html_output


def test_render_metrics_summary_chart_html_degrades_on_empty_input() -> None:
    html_output = render_metrics_summary_chart_html({})
    assert "暂无可视化数据" in html_output
