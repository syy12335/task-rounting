from __future__ import annotations

import json
from pathlib import Path

import pytest

from task_router_graph_train.dataset import prepare_round_assets
from task_router_graph_train.train import controller_dpo


def test_build_dpo_dataset_rows_prefers_raw_rejected() -> None:
    rows = [
        {
            "state_input": {"USER_INPUT": "继续", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
            "chosen_response": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "gold"},
            "chosen_raw_text": '{"chosen": true}',
            "rejected_response": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "parsed"},
            "rejected_raw_text": "not-json",
        }
    ]

    dataset_rows = controller_dpo.build_dpo_dataset_rows(rows)

    assert set(dataset_rows[0]) == {"prompt", "chosen", "rejected"}
    assert dataset_rows[0]["chosen"] == '{"chosen": true}'
    assert dataset_rows[0]["rejected"] == "not-json"


def test_build_dpo_dataset_rows_falls_back_to_parsed_rejected() -> None:
    rejected = {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "parsed"}
    rows = [
        {
            "state_input": {"USER_INPUT": "继续", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
            "chosen_response": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "gold"},
            "rejected_response": rejected,
        }
    ]

    dataset_rows = controller_dpo.build_dpo_dataset_rows(rows)

    assert json.loads(dataset_rows[0]["rejected"]) == rejected


def test_dpo_input_resolution_requires_unsafe_flag(tmp_path: Path) -> None:
    path = tmp_path / "preference.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        controller_dpo._resolve_dpo_input_path(
            preference_admissions=path,
            round_id=None,
            round_manifest=None,
            allow_unsafe_path_input=False,
        )


def test_dpo_input_resolution_reads_round_manifest(tmp_path: Path) -> None:
    report = prepare_round_assets(round_id="round_0001", round_assets_root=tmp_path / "rounds")
    path, manifest_path, unsafe = controller_dpo._resolve_dpo_input_path(
        preference_admissions=None,
        round_id=None,
        round_manifest=Path(report["manifest_path"]),
        allow_unsafe_path_input=False,
    )

    assert path.name == "preference_admissions.jsonl"
    assert manifest_path.endswith("round_manifest.json")
    assert unsafe is False


def test_train_dpo_missing_dependencies_has_clear_error(monkeypatch, tmp_path: Path) -> None:
    preference_path = tmp_path / "preference.jsonl"
    preference_path.write_text(
        json.dumps(
            {
                "state_input": {"USER_INPUT": "继续", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
                "chosen_response": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "gold"},
                "rejected_response": {"action_kind": "observe", "tool": "build_context_view", "args": {}, "reason": "bad"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        controller_dpo,
        "_require_dpo_training_dependencies",
        lambda: (_ for _ in ()).throw(RuntimeError("Controller DPO training dependencies are missing.")),
    )

    with pytest.raises(RuntimeError, match="DPO training dependencies"):
        controller_dpo.train_controller_dpo(
            model_name_or_path="models/default",
            preference_admissions=preference_path,
            allow_unsafe_path_input=True,
            output_dir=tmp_path / "out",
        )


def test_train_controller_dpo_uses_full_checkpoint_trainer(monkeypatch, tmp_path: Path) -> None:
    preference_path = tmp_path / "preference.jsonl"
    preference_path.write_text(
        json.dumps(
            {
                "state_input": {"USER_INPUT": "继续", "ENVIRONMENT_JSON": {}, "SKILLS_INDEX": "[]"},
                "chosen_raw_text": '{"action_kind":"observe","reason":"gold"}',
                "rejected_raw_text": "bad raw",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeDataset:
        @classmethod
        def from_list(cls, rows: list[dict[str, str]]) -> list[dict[str, str]]:
            captured["dataset_rows"] = rows
            return rows

    class FakeTokenizer:
        pad_token_id = 0
        eos_token = "</s>"

        @classmethod
        def from_pretrained(cls, path: str, use_fast: bool) -> "FakeTokenizer":
            captured["tokenizer_path"] = path
            captured["use_fast"] = use_fast
            return cls()

        def save_pretrained(self, output_dir: Path) -> None:
            captured["tokenizer_saved_to"] = str(output_dir)

    class FakeModel:
        def __init__(self, path: str) -> None:
            self.path = path

        @classmethod
        def from_pretrained(cls, path: str) -> "FakeModel":
            captured.setdefault("model_paths", []).append(path)  # type: ignore[union-attr]
            return cls(path)

    class FakeDPOConfig:
        def __init__(
            self,
            output_dir: str,
            num_train_epochs: int,
            per_device_train_batch_size: int,
            gradient_accumulation_steps: int,
            learning_rate: float,
            max_prompt_length: int,
            max_length: int,
            beta: float,
            bf16: bool,
            fp16: bool,
            remove_unused_columns: bool,
            report_to: list[str],
            seed: int,
        ) -> None:
            captured["dpo_config"] = {
                "output_dir": output_dir,
                "num_train_epochs": num_train_epochs,
                "per_device_train_batch_size": per_device_train_batch_size,
                "gradient_accumulation_steps": gradient_accumulation_steps,
                "learning_rate": learning_rate,
                "max_prompt_length": max_prompt_length,
                "max_length": max_length,
                "beta": beta,
                "bf16": bf16,
                "fp16": fp16,
                "remove_unused_columns": remove_unused_columns,
                "report_to": report_to,
                "seed": seed,
            }

    class FakeTrainResult:
        metrics = {"loss": 0.25}

    class FakeDPOTrainer:
        def __init__(self, model: FakeModel, ref_model: FakeModel, args: FakeDPOConfig, train_dataset: list[dict[str, str]], processing_class: FakeTokenizer) -> None:
            captured["trainer_kwargs"] = {
                "model": model.path,
                "ref_model": ref_model.path,
                "args": args,
                "train_dataset": train_dataset,
                "processing_class": processing_class,
            }

        def train(self) -> FakeTrainResult:
            captured["train_called"] = True
            return FakeTrainResult()

        def save_model(self, output_dir: str) -> None:
            captured["model_saved_to"] = output_dir

    monkeypatch.setattr(
        controller_dpo,
        "_require_dpo_training_dependencies",
        lambda: {
            "Dataset": FakeDataset,
            "AutoModelForCausalLM": FakeModel,
            "AutoTokenizer": FakeTokenizer,
            "DPOConfig": FakeDPOConfig,
            "DPOTrainer": FakeDPOTrainer,
            "set_seed": lambda seed: captured.setdefault("seed", seed),
        },
    )

    report = controller_dpo.train_controller_dpo(
        model_name_or_path="/model/policy",
        preference_admissions=preference_path,
        allow_unsafe_path_input=True,
        output_dir=tmp_path / "dpo_out",
        num_train_epochs=2,
        per_device_train_batch_size=3,
        gradient_accumulation_steps=5,
        learning_rate=1e-6,
        max_prompt_length=1024,
        max_length=1536,
        beta=0.2,
        seed=123,
    )

    trainer_kwargs = captured["trainer_kwargs"]
    assert isinstance(trainer_kwargs, dict)
    assert trainer_kwargs["model"] == "/model/policy"
    assert trainer_kwargs["ref_model"] == "/model/policy"
    assert set(captured["dataset_rows"][0]) == {"prompt", "chosen", "rejected"}  # type: ignore[index]
    assert captured["dpo_config"]["beta"] == 0.2  # type: ignore[index]
    assert "peft_config" not in trainer_kwargs
    assert captured["train_called"] is True
    assert report["train_metrics"]["train_dataset_size"] == 1
    assert (tmp_path / "dpo_out" / "training_report.json").exists()
