from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..runtime_adapter import ASSETS_ROOT, REPO_ROOT
from ..train import train_controller_grpo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train controller with teacher-ranked GRPO-style updates.")
    parser.add_argument(
        "--output-dir",
        default="var/runs/task_router_graph_train/grpo/latest",
        help="Directory for rollout groups, rankings, training examples, and reports.",
    )
    parser.add_argument(
        "--teacher-mode",
        choices=["oracle", "file"],
        default="oracle",
        help="Teacher ranking source: oracle (gold-first) or file (teacher_rankings.jsonl).",
    )
    parser.add_argument(
        "--teacher-rankings",
        default="",
        help="Path to teacher ranking jsonl when --teacher-mode file.",
    )
    parser.add_argument(
        "--teacher-source-dir",
        default=str(ASSETS_ROOT / "sft_v1" / "teacher_source"),
        help="Path to controller teacher source directory.",
    )
    parser.add_argument(
        "--runtime-root",
        default=str(REPO_ROOT),
        help="Repository root used to resolve runtime skills.",
    )
    parser.add_argument("--num-candidates", type=int, default=4)
    parser.add_argument("--keep-top-k", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument(
        "--run-sft-update",
        action="store_true",
        help="Run SFT update on generated GRPO examples.",
    )
    parser.add_argument("--model-name-or-path", default="", help="Required when --run-sft-update.")
    parser.add_argument(
        "--lora-target-modules",
        nargs="+",
        default=[],
        help="Required when --run-sft-update, for example: q_proj v_proj.",
    )
    parser.add_argument("--num-train-epochs", type=int, default=1)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)

    parser.add_argument(
        "--holdout-records",
        default="",
        help="Optional holdout records path for non-blocking monitoring.",
    )
    parser.add_argument(
        "--holdout-predictions",
        default="",
        help="Optional predictions path for non-blocking monitoring.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ranking_path = Path(args.teacher_rankings).resolve() if args.teacher_rankings.strip() else None
    holdout_records = Path(args.holdout_records).resolve() if args.holdout_records.strip() else None
    holdout_predictions = Path(args.holdout_predictions).resolve() if args.holdout_predictions.strip() else None
    report = train_controller_grpo(
        output_dir=Path(args.output_dir).resolve(),
        teacher_mode=args.teacher_mode,
        teacher_rankings_path=ranking_path,
        teacher_source_dir=Path(args.teacher_source_dir).resolve(),
        runtime_root=Path(args.runtime_root).resolve(),
        num_candidates=args.num_candidates,
        keep_top_k=args.keep_top_k,
        seed=args.seed,
        run_sft_update=bool(args.run_sft_update),
        model_name_or_path=args.model_name_or_path,
        lora_target_modules=list(args.lora_target_modules),
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        max_seq_length=args.max_seq_length,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        holdout_records=holdout_records,
        holdout_predictions=holdout_predictions,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
