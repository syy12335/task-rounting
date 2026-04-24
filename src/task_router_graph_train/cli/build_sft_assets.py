from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..artifacts import to_safe_path
from ..dataset import (
    DEFAULT_SFT_OUTPUT_ROOT,
    DEFAULT_SFT_TEACHER_SOURCE_DIR,
    build_controller_train_records,
    write_controller_sft_assets,
)
from ..runtime_adapter import REPO_ROOT, normalize_controller_state_view


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build controller SFT assets from teacher bootstrap source.")
    parser.add_argument(
        "--teacher-source-dir",
        default=str(DEFAULT_SFT_TEACHER_SOURCE_DIR),
        help="Path to the static controller teacher bootstrap source directory.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_SFT_OUTPUT_ROOT),
        help="Output directory for generated controller records and SFT examples.",
    )
    parser.add_argument(
        "--runtime-root",
        default=str(REPO_ROOT),
        help="Repository root used to resolve runtime skills for controller state construction.",
    )
    parser.add_argument(
        "--compress-controller-state-view",
        action="store_true",
        help="Build controller teacher bootstrap assets with compressed ENVIRONMENT_JSON view.",
    )
    parser.add_argument(
        "--controller-view-target-tokens",
        type=int,
        default=None,
        help="Optional token budget for compressed controller ENVIRONMENT_JSON view.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    teacher_source_dir = Path(args.teacher_source_dir).resolve()
    output_root = Path(args.output_root).resolve()
    runtime_root = Path(args.runtime_root).resolve()
    controller_state_view = normalize_controller_state_view(
        compress=bool(args.compress_controller_state_view),
        compress_target_tokens=args.controller_view_target_tokens,
    )

    records, manifest = build_controller_train_records(
        teacher_source_dir=teacher_source_dir,
        workspace_root=runtime_root,
        controller_state_view=controller_state_view,
    )
    output_paths = write_controller_sft_assets(
        output_root=output_root,
        records=records,
        manifest=manifest,
    )
    print(
        json.dumps(
            {
                "record_count": len(records),
                "manifest_path": to_safe_path(output_paths["manifest_path"]),
                "train_records": to_safe_path(output_paths["record_train_path"]),
                "eval_records": to_safe_path(output_paths["record_eval_path"]),
                "train_examples": to_safe_path(output_paths["example_train_path"]),
                "eval_examples": to_safe_path(output_paths["example_eval_path"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
