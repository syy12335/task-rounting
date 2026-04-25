from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..eval import evaluate_holdout_predictions
from ..rounds import load_round_manifest, resolve_round_asset_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate holdout predictions against latest prepared round.")
    parser.add_argument(
        "--round-id",
        default="",
        help="Round id to read holdout records from. Default: latest prepared round.",
    )
    parser.add_argument(
        "--round-manifest",
        default="",
        help="Optional explicit round_manifest.json path.",
    )
    parser.add_argument(
        "--records",
        default="",
        help="Optional explicit holdout records path override.",
    )
    parser.add_argument("--predictions", required=True, help="Path to the prediction jsonl file.")
    parser.add_argument(
        "--config",
        default="",
        help="Optional teacher config path (defaults to controller_grpo_online.yaml).",
    )
    parser.add_argument(
        "--output-dir",
        default="var/runs/task_router_graph_train/eval/latest",
        help="Directory for evaluation outputs.",
    )
    parser.add_argument(
        "--enqueue-failed-badcases",
        action="store_true",
        help="Enqueue failed holdout samples into the current round teacher_queue.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.records.strip():
        records_path = Path(args.records).resolve()
        manifest_path = ""
    else:
        manifest = load_round_manifest(
            round_id=args.round_id.strip() or None,
            manifest_path=Path(args.round_manifest).resolve() if args.round_manifest.strip() else None,
        )
        records_path = resolve_round_asset_path(manifest, "holdout_records")
        manifest_path = str(manifest.get("_manifest_path", ""))

    report = evaluate_holdout_predictions(
        record_path=records_path,
        prediction_path=Path(args.predictions).resolve(),
        config_path=Path(args.config).resolve() if args.config.strip() else None,
        enqueue_failed_badcases=bool(args.enqueue_failed_badcases),
        badcase_round_manifest=Path(manifest_path).resolve() if manifest_path else None,
    )
    report["run_manifest"]["input_round_manifest"] = manifest_path

    (output_dir / "metrics_summary.json").write_text(
        json.dumps(report["metrics_summary"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "run_manifest.json").write_text(
        json.dumps(report["run_manifest"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence_lines = [json.dumps(row, ensure_ascii=False) for row in report["evidence_rows"]]
    (output_dir / "evidence_rows.jsonl").write_text("\n".join(evidence_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
