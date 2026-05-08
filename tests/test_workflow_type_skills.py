from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from task_router_graph.agents.skill_registry import SkillRegistryError, load_workflow_runner, load_workflow_type_catalog
from task_router_graph.graph import TaskRouterGraph
from task_router_graph.schema import Task


def _write_workflow_skill(root: Path, *, name: str, workflow_entry: str = "scripts/run.py") -> None:
    skill_dir = root / "skills" / "controller" / name
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {name} workflow
            when_to_use: use {name}
            allowed-tools: []
            task-mode: workflow
            workflow-entry: {workflow_entry}
            status-aliases:
              - {name} alias
            ---
            # {name}
            """
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "run.py").write_text(
        textwrap.dedent(
            """\
            from __future__ import annotations

            def run(*, task_content: str) -> dict[str, str]:
                return {"task_status": "done", "task_result": "custom: " + task_content}
            """
        ),
        encoding="utf-8",
    )


def test_workflow_type_catalog_loads_runner_from_controller_skill(tmp_path: Path) -> None:
    _write_workflow_skill(tmp_path, name="customflow")

    catalog = load_workflow_type_catalog(workspace_root=tmp_path, skills_root="skills")

    assert list(catalog) == ["customflow"]
    entry = catalog["customflow"]
    assert entry["name"] == "customflow"
    assert entry["task_mode"] == "workflow"
    assert entry["status_aliases"] == ["customflow alias"]

    runner = load_workflow_runner(entry)
    assert runner(task_content="hello") == {"task_status": "done", "task_result": "custom: hello"}


def test_workflow_type_catalog_requires_workflow_entry(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "controller" / "brokenflow"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: brokenflow
            description: broken workflow
            when_to_use: use broken
            allowed-tools: []
            task-mode: workflow
            ---
            # Broken
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillRegistryError, match="workflow-entry"):
        load_workflow_type_catalog(workspace_root=tmp_path, skills_root="skills")


def test_graph_workflow_step_dispatches_registered_runner(monkeypatch) -> None:
    graph = TaskRouterGraph.__new__(TaskRouterGraph)
    graph._workflow_runners = {
        "customflow": lambda *, task_content: {
            "task_status": "done",
            "task_result": "custom workflow completed: " + task_content,
        }
    }

    submitted: dict[str, object] = {}

    class _FakeExecutor:
        def submit(self, runner, **kwargs):  # type: ignore[no-untyped-def]
            submitted["runner"] = runner
            submitted["kwargs"] = dict(kwargs)
            return object()

    graph._workflow_executor = _FakeExecutor()
    graph._workflow_lock = _NullLock()
    graph._workflow_jobs = {}
    graph._build_workflow_key = lambda **_: "customflow:run:1:1"

    task = Task(type="customflow", content="payload")
    result = graph._workflow_step(
        {
            "task": task,
            "run_id": "run",
            "round_id": 1,
            "task_turn": 0,
        }
    )

    assert result["workflow_pending"] is True
    assert result["workflow_key"] == "customflow:run:1:1"
    assert submitted["kwargs"] == {"task_content": "payload"}
    assert graph._workflow_jobs["customflow:run:1:1"]["workflow_type"] == "customflow"


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None
