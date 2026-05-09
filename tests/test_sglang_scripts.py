from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = PROJECT_ROOT / "scripts" / "sglang" / "start.sh"


def _clean_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("SGLANG_")}
    env.pop("CONDA_DEFAULT_ENV", None)
    return env


def _fake_activate(tmp_path: Path) -> Path:
    activate = tmp_path / "activate"
    activate.write_text("# fake activate\n", encoding="utf-8")
    return activate


def test_start_dry_run_prefers_cli_and_openai_env(tmp_path) -> None:
    env = _clean_env()
    env.update(
        {
            "SGLANG_BASE_URL": "http://0.0.0.0:31000/v1",
            "SGLANG_MODEL": "env-model",
            "SGLANG_MODEL_PATH": "/models/env",
            "SGLANG_CONDA_ENV": "env-conda",
        }
    )

    completed = subprocess.run(
        [
            str(START_SCRIPT),
            "--dry-run",
            "--base-url",
            "http://127.0.0.1:32000/v1",
            "--model",
            "cli-model",
            "--model-path",
            "/models/cli",
            "--conda-env",
            "cli-conda",
            "--conda-activate",
            str(_fake_activate(tmp_path)),
            "--",
            "--tp-size",
            "1",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    output = completed.stdout
    assert "model_path=/models/cli" in output
    assert "model=cli-model" in output
    assert "base_url=http://127.0.0.1:32000/v1" in output
    assert "host=127.0.0.1" in output
    assert "port=32000" in output
    assert "conda_env=cli-conda" in output
    assert "passthrough_args=--tp-size 1 " in output


def test_start_dry_run_uses_legacy_host_port_and_model(tmp_path) -> None:
    env = _clean_env()
    env.update(
        {
            "SGLANG_HOST": "0.0.0.0",
            "SGLANG_PORT": "31001",
            "SGLANG_SERVED_MODEL_NAME": "legacy-model",
            "SGLANG_MODEL_PATH": "/models/legacy",
            "CONDA_DEFAULT_ENV": "current-conda",
        }
    )

    completed = subprocess.run(
        [
            str(START_SCRIPT),
            "--dry-run",
            "--conda-activate",
            str(_fake_activate(tmp_path)),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    output = completed.stdout
    assert "model=legacy-model" in output
    assert "base_url=http://0.0.0.0:31001/v1" in output
    assert "host=0.0.0.0" in output
    assert "port=31001" in output
    assert "conda_env=current-conda" in output
