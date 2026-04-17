from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..runtime_adapter import ASSETS_ROOT
from ..train import train_controller_sft


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the minimal controller SFT warm-start adapter.")
    parser.add_argument("--model-name-or-path", required=True, help="Model id or local model directory.")
    parser.add_argument(
        "--lora-target-modules",
        required=True,
        nargs="+",
        help="Explicit LoRA target modules, for example: q_proj v_proj.",
    )
    parser.add_argument(
        "--train-examples",
        default=str(ASSETS_ROOT / "sft_v1" / "examples" / "controller_sft_train.jsonl"),
        help="Path to generated controller train examples.",
    )
    parser.add_argument(
        "--eval-examples",
        default=str(ASSETS_ROOT / "sft_v1" / "examples" / "controller_sft_eval.jsonl"),
        help="Path to generated controller eval examples.",
    )
    parser.add_argument(
        "--output-dir",
        default="var/runs/task_router_graph_train/sft/latest",
        help="Directory for adapter weights and metrics.",
    )
    parser.add_argument("--num-train-epochs", type=int, default=5)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = train_controller_sft(
        model_name_or_path=args.model_name_or_path,
        lora_target_modules=list(args.lora_target_modules),
        train_examples=Path(args.train_examples).resolve(),
        eval_examples=Path(args.eval_examples).resolve(),
        output_dir=Path(args.output_dir).resolve(),
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        max_seq_length=args.max_seq_length,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        seed=args.seed,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
