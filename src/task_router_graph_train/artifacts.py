from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_adapter import REPO_ROOT

ROUND_MANIFEST_ARTIFACT_TYPE = "post_training_round_v1"
SFT_EXAMPLES_ARTIFACT_TYPE = "sft_examples_v1"
CONTROLLER_TRAINING_RECORDS_ARTIFACT_TYPE = "controller_training_records_v1"
HOLDOUT_RECORDS_ARTIFACT_TYPE = "holdout_records_v1"
TEACHER_QUEUE_ARTIFACT_TYPE = "teacher_queue_v1"
TEACHER_DECISIONS_ARTIFACT_TYPE = "teacher_decisions_v1"
SFT_ADMISSIONS_ARTIFACT_TYPE = "sft_admissions_v1"
PREFERENCE_ADMISSIONS_ARTIFACT_TYPE = "preference_admissions_v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json payload must be an object: {path}")
    return payload


def to_safe_path(path: Path | str, *, base: Path | None = None) -> str:
    value = str(path).strip()
    if not value:
        return ""
    target = Path(value)
    if not target.is_absolute():
        return target.as_posix()
    anchor = (base or REPO_ROOT).resolve()
    resolved = target.resolve()
    try:
        return resolved.relative_to(anchor).as_posix()
    except Exception:
        return Path(os.path.relpath(str(resolved), str(anchor))).as_posix()
