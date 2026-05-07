from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..dataset import prepare_round_assets
from ..rounds import ROUND_ASSETS_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one post-training round from manual_protocol_v1.")
    parser.add_argument("--round-id", required=True, help="Round identifier, for example: round_0001")
    parser.add_argument(
        "--previous-round-id",
        default="",
        help="Previous round id for lineage only. SFT warm start data is not extended from previous admissions.",
    )
    parser.add_argument(
        "--round-assets-root",
        default=str(ROUND_ASSETS_ROOT),
        help="Root directory for round assets.",
    )
    parser.add_argument(
        "--manual-protocol-dir",
        default="",
        help="Override manual_protocol_v1 directory (defaults to package assets/manual_protocol_v1).",
    )
    parser.add_argument(
        "--workspace-root",
        default="",
        help="Repository root used to resolve runtime skill index preview.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = prepare_round_assets(
        round_id=args.round_id,
        previous_round_id=args.previous_round_id.strip() or None,
        round_assets_root=Path(args.round_assets_root).resolve(),
        manual_protocol_dir=Path(args.manual_protocol_dir).resolve() if args.manual_protocol_dir.strip() else None,
        workspace_root=Path(args.workspace_root).resolve() if args.workspace_root.strip() else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
