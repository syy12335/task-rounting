from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from ..artifacts import to_safe_path
from ..dataset import read_jsonl, render_controller_prompt
from ..rounds import load_round_manifest, resolve_round_asset_path


def build_dpo_dataset_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    dataset_rows: list[dict[str, str]] = []
    for row in rows:
        state_input = row.get("state_input", {})
        if not isinstance(state_input, dict):
            continue
        chosen = str(row.get("chosen_raw_text", "")).strip()
        if not chosen:
            chosen_response = row.get("chosen_response", {})
            if isinstance(chosen_response, dict) and chosen_response:
                chosen = json.dumps(chosen_response, ensure_ascii=False, indent=2)
        rejected = str(row.get("rejected_raw_text", "")).strip()
        if not rejected:
            rejected_response = row.get("rejected_response", {})
            if isinstance(rejected_response, dict) and rejected_response:
                rejected = json.dumps(rejected_response, ensure_ascii=False, indent=2)
        if not chosen or not rejected:
            continue
        dataset_rows.append(
            {
                "prompt": render_controller_prompt(state_input),
                "chosen": chosen,
                "rejected": rejected,
            }
        )
    return dataset_rows


def write_dpo_dataset(*, preference_admissions_path: Path, output_path: Path) -> dict[str, Any]:
    rows = read_jsonl(Path(preference_admissions_path).resolve())
    dataset_rows = build_dpo_dataset_rows(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        ("\n".join(json.dumps(row, ensure_ascii=False) for row in dataset_rows) + "\n") if dataset_rows else "",
        encoding="utf-8",
    )
    return {
        "source_path": to_safe_path(Path(preference_admissions_path).resolve()),
        "dataset_path": to_safe_path(output_path),
        "input_count": len(rows),
        "row_count": len(dataset_rows),
    }


def train_controller_dpo(
    *,
    model_name_or_path: str,
    output_dir: Path,
    preference_admissions: Path | None = None,
    round_id: str | None = None,
    round_manifest: Path | None = None,
    allow_unsafe_path_input: bool = False,
    ref_model_name_or_path: str | None = None,
    num_train_epochs: int = 1,
    per_device_train_batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 5e-7,
    max_prompt_length: int = 2048,
    max_length: int = 2560,
    beta: float = 0.1,
    seed: int = 42,
    bf16: bool = False,
    fp16: bool = False,
) -> dict[str, Any]:
    preference_path, input_manifest_path, unsafe_path_input = _resolve_dpo_input_path(
        preference_admissions=preference_admissions,
        round_id=round_id,
        round_manifest=round_manifest,
        allow_unsafe_path_input=allow_unsafe_path_input,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_report = write_dpo_dataset(
        preference_admissions_path=preference_path,
        output_path=output_dir / "dpo_train.jsonl",
    )
    if int(dataset_report["row_count"]) == 0:
        raise ValueError("preference_admissions produced zero DPO rows")

    dependencies = _require_dpo_training_dependencies()
    Dataset = dependencies["Dataset"]
    AutoModelForCausalLM = dependencies["AutoModelForCausalLM"]
    AutoTokenizer = dependencies["AutoTokenizer"]
    DPOConfig = dependencies["DPOConfig"]
    DPOTrainer = dependencies["DPOTrainer"]
    set_seed = dependencies["set_seed"]

    set_seed(seed)
    dataset_rows = [json.loads(line) for line in (output_dir / "dpo_train.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    train_dataset = Dataset.from_list(dataset_rows)

    tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, use_fast=True)
    added_special_tokens = 0
    if tokenizer.pad_token_id is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token
    elif tokenizer.pad_token_id is None:
        added_special_tokens = int(tokenizer.add_special_tokens({"pad_token": "<|pad|>"}))

    model = AutoModelForCausalLM.from_pretrained(model_name_or_path)
    ref_model_path = str(ref_model_name_or_path or model_name_or_path)
    ref_model = AutoModelForCausalLM.from_pretrained(ref_model_path)
    if added_special_tokens:
        _resize_token_embeddings(model, len(tokenizer))
        _resize_token_embeddings(ref_model, len(tokenizer))

    config_kwargs = {
        "output_dir": str(output_dir),
        "num_train_epochs": int(num_train_epochs),
        "per_device_train_batch_size": int(per_device_train_batch_size),
        "gradient_accumulation_steps": int(gradient_accumulation_steps),
        "learning_rate": float(learning_rate),
        "max_prompt_length": int(max_prompt_length),
        "max_length": int(max_length),
        "beta": float(beta),
        "bf16": bool(bf16),
        "fp16": bool(fp16),
        "remove_unused_columns": False,
        "report_to": [],
        "seed": int(seed),
    }
    config_params = inspect.signature(DPOConfig.__init__).parameters
    training_args = DPOConfig(**{key: value for key, value in config_kwargs.items() if key in config_params})
    trainer_kwargs = {
        "model": model,
        "ref_model": ref_model,
        "args": training_args,
        "train_dataset": train_dataset,
        "tokenizer": tokenizer,
        "processing_class": tokenizer,
    }
    trainer_params = inspect.signature(DPOTrainer.__init__).parameters
    trainer = DPOTrainer(**{key: value for key, value in trainer_kwargs.items() if key in trainer_params})
    train_result = trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(output_dir)

    train_metrics = dict(getattr(train_result, "metrics", {}) or {})
    train_metrics["train_dataset_size"] = int(dataset_report["row_count"])
    report = {
        "train_config": {
            "model_name_or_path": model_name_or_path,
            "ref_model_name_or_path": ref_model_path,
            "preference_admissions": to_safe_path(preference_path),
            "input_manifest_path": to_safe_path(input_manifest_path),
            "unsafe_path_input": unsafe_path_input,
            "output_dir": to_safe_path(output_dir),
            "num_train_epochs": int(num_train_epochs),
            "per_device_train_batch_size": int(per_device_train_batch_size),
            "gradient_accumulation_steps": int(gradient_accumulation_steps),
            "learning_rate": float(learning_rate),
            "max_prompt_length": int(max_prompt_length),
            "max_length": int(max_length),
            "beta": float(beta),
            "seed": int(seed),
            "bf16": bool(bf16),
            "fp16": bool(fp16),
        },
        "dataset": dataset_report,
        "train_metrics": train_metrics,
        "output_dir": to_safe_path(output_dir),
    }
    (output_dir / "training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _resolve_dpo_input_path(
    *,
    preference_admissions: Path | None,
    round_id: str | None,
    round_manifest: Path | None,
    allow_unsafe_path_input: bool,
) -> tuple[Path, str, bool]:
    if round_id is not None or round_manifest is not None or preference_admissions is None:
        manifest = load_round_manifest(round_id=round_id, manifest_path=round_manifest)
        return resolve_round_asset_path(manifest, "preference_admissions"), str(manifest.get("_manifest_path", "")), False
    if not allow_unsafe_path_input:
        raise ValueError("direct --preference-admissions usage requires allow_unsafe_path_input=true")
    return Path(preference_admissions).resolve(), "", True


def _resize_token_embeddings(model: Any, vocab_size: int) -> None:
    resize = getattr(model, "resize_token_embeddings", None)
    if callable(resize):
        resize(vocab_size)


def _require_dpo_training_dependencies() -> dict[str, Any]:
    try:
        from datasets import Dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
        from trl import DPOConfig, DPOTrainer
    except ImportError as exc:  # pragma: no cover - exercised manually after installing training deps
        raise RuntimeError(
            "Controller DPO training dependencies are missing. "
            "Please install requirements-post-training.txt before running train_dpo."
        ) from exc
    return {
        "Dataset": Dataset,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "DPOConfig": DPOConfig,
        "DPOTrainer": DPOTrainer,
        "set_seed": set_seed,
    }
