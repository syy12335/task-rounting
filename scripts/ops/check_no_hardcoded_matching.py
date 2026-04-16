#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_patterns(path: Path, patterns: list[tuple[str, str]]) -> list[str]:
    text = _read(path)
    failures: list[str] = []
    for expr, message in patterns:
        if re.search(expr, text, flags=re.MULTILINE):
            failures.append(f"{path}: {message}")
    return failures


def _check_required_patterns(path: Path, patterns: list[tuple[str, str]]) -> list[str]:
    text = _read(path)
    failures: list[str] = []
    for expr, message in patterns:
        if not re.search(expr, text, flags=re.MULTILINE):
            failures.append(f"{path}: {message}")
    return failures


def main() -> int:
    checks: list[tuple[Path, list[tuple[str, str]]]] = [
        (
            REPO_ROOT / "src/task_router_graph/skills/executor/time_range_info/scripts/web_search.py",
            [
                (r"\bWEATHER_HINT_WORDS\b", "forbidden hardcoded keyword constant"),
                (r"\bTRUSTED_WEATHER_DOMAINS\b", "forbidden hardcoded domain constant"),
                (r"\branking_hint_words\b", "forbidden business keyword weighting pattern"),
                (r"\branking_trusted_domains\b", "forbidden business domain weighting pattern"),
                (r"\bquery_templates\b", "forbidden template-driven query expansion pattern"),
                (
                    r'if\s+"[^"]+"\s+in\s+query',
                    "forbidden direct literal-in-query matching",
                ),
                (
                    r'if\s+"[^"]+"\s+in\s+content',
                    "forbidden direct literal-in-content matching",
                ),
            ],
        ),
        (
            REPO_ROOT / "src/task_router_graph/skills/executor/time_range_info/config/retrieval_policy.yaml",
            [
                (r"^\s*hint_words\s*:", "forbidden business keyword list in policy"),
                (r"^\s*trusted_domains\s*:", "forbidden domain whitelist in policy"),
                (r"^\s*templates\s*:", "forbidden rule-template query expansion in policy"),
            ],
        ),
        (
            REPO_ROOT / "src/task_router_graph/graph.py",
            [
                (
                    r"keywords\s*=\s*\[",
                    "forbidden inline keyword list for status shortcuts",
                ),
            ],
        ),
        (
            REPO_ROOT / "docs/changelog.md",
            [
                (
                    r"pyskill\s*内部\s*graph",
                    "forbidden ambiguous phrase; use '<skill> worker graph' instead",
                ),
            ],
        ),
        (
            REPO_ROOT / "docs/pyskill.md",
            [
                (
                    r"pyskill\s*内部\s*graph",
                    "forbidden ambiguous phrase; use '<skill> worker graph' instead",
                ),
            ],
        ),
    ]

    required_checks: list[tuple[Path, list[tuple[str, str]]]] = [
        (
            REPO_ROOT / "src/task_router_graph/skills/executor/time_range_info/docs/graph_flow.md",
            [
                (
                    r"worker graph.*graph\.py|graph\.py.*worker graph",
                    "must explicitly clarify worker graph vs main graph.py",
                ),
            ],
        ),
    ]

    failures: list[str] = []
    for path, patterns in checks:
        if not path.exists():
            failures.append(f"{path}: missing file to check")
            continue
        failures.extend(_check_patterns(path, patterns))

    for path, patterns in required_checks:
        if not path.exists():
            failures.append(f"{path}: missing file to check")
            continue
        failures.extend(_check_required_patterns(path, patterns))

    if failures:
        for item in failures:
            print(item)
        return 1

    print("hardcoded matching checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
