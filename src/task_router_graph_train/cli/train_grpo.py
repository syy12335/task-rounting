from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..train.controller_grpo import DEFAULT_GRPO_CONFIG_PATH
from ..train import train_controller_grpo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train controller with online teacher GRPO updates on verl backend.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_GRPO_CONFIG_PATH),
        help="Path to the main online GRPO config yaml.",
    )
    parser.add_argument(
        "--output-dir",
        default="var/runs/task_router_graph_train/grpo/latest",
        help="Directory for RL dataset, verl requests, logs, and reports.",
    )
    parser.add_argument(
        "--round-id",
        default="",
        help="Round id to read controller records from. Default: latest prepared round.",
    )
    parser.add_argument(
        "--round-manifest",
        default="",
        help="Optional explicit round_manifest.json path.",
    )
    parser.add_argument(
        "--train-records",
        default="",
        help="Unsafe override path to controller train records jsonl.",
    )
    parser.add_argument(
        "--eval-records",
        default="",
        help="Unsafe override path to controller eval records jsonl.",
    )
    parser.add_argument(
        "--allow-unsafe-path-input",
        action="store_true",
        help="Allow direct --train-records/--eval-records paths instead of round manifest.",
    )
    parser.add_argument(
        "--teacher-mode",
        choices=["online", "oracle", "file"],
        default=None,
        help="Teacher backend override. Default comes from --config.",
    )
    parser.add_argument(
        "--teacher-rankings",
        default="",
        help="Path to teacher ranking jsonl when --teacher-mode file.",
    )
    parser.add_argument("--teacher-base-url", default="", help="Override teacher.base_url from config.")
    parser.add_argument("--teacher-model", default="", help="Override teacher.model from config.")
    parser.add_argument("--teacher-api-key-env", default="", help="Override teacher.api_key_env from config.")
    parser.add_argument("--teacher-timeout-sec", type=float, default=None, help="Override teacher.timeout_sec from config.")
    parser.add_argument("--teacher-rubric-id", default="", help="Override teacher.rubric_id from config.")
    parser.add_argument("--teacher-max-batch-size", type=int, default=None, help="Override teacher.max_batch_size from config.")
    parser.add_argument("--runtime-root", default="", help="Repository root used to resolve runtime paths.")
    parser.add_argument("--num-candidates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument(
        "--run-verl-update",
        action="store_true",
        help="Deprecated compatibility flag. Direct verl update is already the default.",
    )
    parser.add_argument(
        "--execute-verl-command",
        action="store_true",
        help="Deprecated compatibility flag kept for CLI stability.",
    )
    parser.add_argument(
        "--verl-command-template",
        default="",
        help="Deprecated compatibility flag. The direct-update path ignores this template.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export RL dataset and verl request artifacts; do not run the verl update.",
    )

    parser.add_argument(
        "--model-name-or-path",
        default="",
        help="Policy model path override. Required unless config already provides model.path.",
    )
    parser.add_argument(
        "--lora-target-modules",
        nargs="+",
        default=[],
        help="LoRA target modules, for example: q_proj v_proj.",
    )
    parser.add_argument("--num-train-epochs", type=int, default=1)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--n-gpus-per-node", type=int, default=None)
    parser.add_argument("--nnodes", type=int, default=None)
    parser.add_argument("--tensor-model-parallel-size", type=int, default=None)
    parser.add_argument("--data-parallel-size", type=int, default=None)
    parser.add_argument("--rollout-gpu-memory-utilization", type=float, default=None)
    parser.add_argument("--rollout-max-num-batched-tokens", type=int, default=None)
    parser.add_argument("--rollout-max-num-seqs", type=int, default=None)
    parser.add_argument("--actor-use-torch-compile", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--enable-activation-offload", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--actor-param-offload", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--actor-optimizer-offload", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--ref-param-offload", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--ref-optimizer-offload", action=argparse.BooleanOptionalAction, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ranking_path = Path(args.teacher_rankings).resolve() if args.teacher_rankings.strip() else None
    report = train_controller_grpo(
        output_dir=Path(args.output_dir).resolve(),
        config_path=Path(args.config).resolve(),
        round_id=args.round_id.strip() or None,
        round_manifest=Path(args.round_manifest).resolve() if args.round_manifest.strip() else None,
        train_records=Path(args.train_records).resolve() if args.train_records.strip() else None,
        eval_records=Path(args.eval_records).resolve() if args.eval_records.strip() else None,
        allow_unsafe_path_input=bool(args.allow_unsafe_path_input),
        teacher_mode=args.teacher_mode,
        teacher_base_url=args.teacher_base_url or None,
        teacher_model=args.teacher_model or None,
        teacher_api_key_env=args.teacher_api_key_env or None,
        teacher_timeout_sec=args.teacher_timeout_sec,
        teacher_rubric_id=args.teacher_rubric_id or None,
        teacher_max_batch_size=args.teacher_max_batch_size,
        teacher_rankings_path=ranking_path,
        runtime_root=Path(args.runtime_root).resolve() if args.runtime_root.strip() else None,
        num_candidates=args.num_candidates,
        seed=args.seed,
        run_verl_update=True if args.run_verl_update else None,
        execute_verl_command=bool(args.execute_verl_command),
        verl_command_template=str(args.verl_command_template),
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
        n_gpus_per_node=args.n_gpus_per_node,
        nnodes=args.nnodes,
        tensor_model_parallel_size=args.tensor_model_parallel_size,
        data_parallel_size=args.data_parallel_size,
        rollout_gpu_memory_utilization=args.rollout_gpu_memory_utilization,
        rollout_max_num_batched_tokens=args.rollout_max_num_batched_tokens,
        rollout_max_num_seqs=args.rollout_max_num_seqs,
        actor_use_torch_compile=args.actor_use_torch_compile,
        enable_activation_offload=args.enable_activation_offload,
        actor_param_offload=args.actor_param_offload,
        actor_optimizer_offload=args.actor_optimizer_offload,
        ref_param_offload=args.ref_param_offload,
        ref_optimizer_offload=args.ref_optimizer_offload,
        export_only=bool(args.export_only),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
