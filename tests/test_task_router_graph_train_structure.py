from __future__ import annotations

from importlib import import_module
from pathlib import Path

from task_router_graph_train.runtime_adapter import PACKAGE_ROOT


def test_only_new_cli_entrypoints_exist() -> None:
    cli_dir = PACKAGE_ROOT / "cli"
    existing = {path.name for path in cli_dir.glob("*.py")}
    assert {"prepare_round.py", "train_sft.py", "train_grpo.py", "evaluate.py", "annotate_queue.py"}.issubset(existing)

    removed = {
        "build_assets.py",
        "build_sft_assets.py",
        "build_feedback_assets.py",
        "evaluate_controller_regression.py",
        "harvest_failed_badcases.py",
        "ingest_badcases.py",
    }
    assert not (removed & existing)


def test_removed_legacy_assets_are_absent() -> None:
    assets_root = PACKAGE_ROOT / "assets"
    assert not (assets_root / "sft_v1").exists()
    assert not (assets_root / "rl_v1").exists()
    assert not (assets_root / "eval_samples" / "manual_eval").exists()


def test_new_cli_modules_are_importable() -> None:
    modules = [
        "task_router_graph_train.cli.prepare_round",
        "task_router_graph_train.cli.train_sft",
        "task_router_graph_train.cli.train_grpo",
        "task_router_graph_train.cli.evaluate",
        "task_router_graph_train.cli.annotate_queue",
    ]
    for module in modules:
        assert import_module(module)
