from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..feedback import annotate_teacher_queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Annotate current round teacher_queue and append valid sft_admissions.")
    parser.add_argument(
        "--round-id",
        default="",
        help="Round id to read teacher_queue from. Default: latest prepared round.",
    )
    parser.add_argument(
        "--round-manifest",
        default="",
        help="Optional explicit round_manifest.json path.",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optional teacher config path (defaults to controller_grpo_online.yaml).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of queued rows to annotate.",
    )
    parser.add_argument(
        "--output-decisions",
        default="",
        help="Optional explicit output path for teacher_decisions.jsonl.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = annotate_teacher_queue(
        round_id=args.round_id.strip() or None,
        round_manifest=Path(args.round_manifest).resolve() if args.round_manifest.strip() else None,
        config_path=Path(args.config).resolve() if args.config.strip() else None,
        limit=args.limit,
        output_decisions_path=Path(args.output_decisions).resolve() if args.output_decisions.strip() else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
