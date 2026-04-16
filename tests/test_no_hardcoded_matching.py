from __future__ import annotations

import subprocess
from pathlib import Path


def test_no_hardcoded_matching_patterns() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts/ops/check_no_hardcoded_matching.py"
    result = subprocess.run(
        ["python", str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
