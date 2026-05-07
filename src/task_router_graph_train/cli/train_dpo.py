from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..train import train_controller_dpo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train controller with DPO from preference_admissions.")
    parser.add_argument("--model-name-or-path", required=True, help="Current policy checkpoint to optimize with DPO.")
    parser.add_argument("--ref-model-name-or-path", default="", help="Reference model checkpoint. Defaults to --model-name-or-path.")
    parser.add_argument(
        "--round-id",
        default="",
        help="Round id to read preference_admissions from. Default: latest prepared round.",
    )
    parser.add_argument(
        "--round-manifest",
        default="",
        help="Optional explicit round_manifest.json path.",
    )
    parser.add_argument(
        "--preference-admissions",
        default="",
        help="Unsafe direct preference_admissions jsonl path.",
    )
    parser.add_argument(
        "--allow-unsafe-path-input",
        action="store_true",
        help="Allow direct --preference-admissions path instead of round manifest.",
    )
    parser.add_argument("--output-dir", default="var/runs/task_router_graph_train/dpo/latest")
    parser.add_argument("--num-train-epochs", type=int, default=1)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--max-prompt-length", type=int, default=2048)
    parser.add_argument("--max-length", type=int, default=2560)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = train_controller_dpo(
        model_name_or_path=args.model_name_or_path,
        ref_model_name_or_path=args.ref_model_name_or_path.strip() or None,
        round_id=args.round_id.strip() or None,
        round_manifest=Path(args.round_manifest).resolve() if args.round_manifest.strip() else None,
        preference_admissions=Path(args.preference_admissions).resolve() if args.preference_admissions.strip() else None,
        allow_unsafe_path_input=bool(args.allow_unsafe_path_input),
        output_dir=Path(args.output_dir).resolve(),
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        max_prompt_length=args.max_prompt_length,
        max_length=args.max_length,
        beta=args.beta,
        seed=args.seed,
        bf16=bool(args.bf16),
        fp16=bool(args.fp16),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
