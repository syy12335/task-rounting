"""Training-only package for task router RL and evaluation workflows."""

from __future__ import annotations

from pathlib import Path

from .dataset import (
    FORMAL_ENVIRONMENT_KEYS,
    ROLE_CONTROLLER,
    ROLE_EXECUTOR_EVAL,
    ROLE_GRAPH_EVAL,
    ROLE_REPLY,
    build_k20_holdout_records,
    load_eval_sample_triplets,
    read_jsonl,
    rewrite_k20_snapshots_with_sidecar,
    sanitize_environment_payload,
    write_jsonl,
)
from .eval import evaluate_prediction_records
from .reward_specs import REWARD_SPECS
from .runtime_adapter import (
    ASSETS_ROOT,
    CONFIGS_ROOT,
    DOCS_ROOT,
    PACKAGE_ROOT,
    REPO_ROOT,
    build_controller_state_input,
    build_reply_state_input,
)

__all__ = [
    "ASSETS_ROOT",
    "CONFIGS_ROOT",
    "DOCS_ROOT",
    "FORMAL_ENVIRONMENT_KEYS",
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "REWARD_SPECS",
    "ROLE_CONTROLLER",
    "ROLE_EXECUTOR_EVAL",
    "ROLE_GRAPH_EVAL",
    "ROLE_REPLY",
    "build_controller_state_input",
    "build_k20_holdout_records",
    "build_reply_state_input",
    "evaluate_prediction_records",
    "load_eval_sample_triplets",
    "read_jsonl",
    "rewrite_k20_snapshots_with_sidecar",
    "sanitize_environment_payload",
    "write_jsonl",
]
