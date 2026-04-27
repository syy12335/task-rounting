from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from task_router_graph.agents.executor_agent import ExecutorAgent
from task_router_graph.schema import Environment, Task
import task_router_graph.nodes as nodes_module


class _FakeDelegateLLM:
    def __init__(self) -> None:
        self.bound_response_format: dict[str, object] | None = None
        self.invoke_messages: list[list[object]] = []

    def bind(self, **kwargs: object) -> "_FakeDelegateLLM":
        self.bound_response_format = kwargs.get("response_format")  # type: ignore[assignment]
        return self

    def invoke(self, messages: list[object], config: dict[str, object] | None = None) -> SimpleNamespace:
        del config
        self.invoke_messages.append(messages)
        return SimpleNamespace(
            content=json.dumps(
                {
                    "action_kind": "delegate_skill",
                    "skill_name": "time-range-info",
                    "tool_name": "web_search",
                    "input": {"query": "昨天 北京 重大事件 新闻", "limit": 3},
                    "reason": "命中时间段资讯查询 skill，委派给 worker 执行。",
                },
                ensure_ascii=False,
            )
        )


def test_executor_agent_accepts_delegate_skill_action() -> None:
    llm = _FakeDelegateLLM()
    agent = ExecutorAgent(
        llm=llm,
        system_prompt="TASK={{TASK_CONTENT}}\nENV={{ENVIRONMENT_JSON}}\nSKILLS={{EXECUTOR_SKILLS_INDEX}}",
    )

    result = agent.run(
        task_content="用户目标：查询昨天北京发生的大事。\n任务限制：基于可靠来源。",
        tasks={"rounds": [], "cur_round": 1, "round_skill_reads": {"skills": []}},
        executor_skills_index="[]",
        observe_tools={},
    )

    assert result["task_status"] == "running"
    assert result["task_result"] == "正在执行"
    assert result["delegated_skill"] == {
        "skill_name": "time-range-info",
        "tool_name": "web_search",
        "input": {"query": "昨天 北京 重大事件 新闻", "limit": 3},
        "reason": "命中时间段资讯查询 skill，委派给 worker 执行。",
    }

    last_message = llm.invoke_messages[0][-1]
    payload = json.loads(last_message.content)
    assert "delegate_skill" in payload["output_constraints"]["action_kind_enum"]


def test_executor_node_dispatches_delegate_skill_and_dedupes_round_skill_read(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_path = "src/task_router_graph/skills/executor/time_range_info/SKILL.md"
    environment = Environment()
    round_item = environment.start_round(user_input="昨天北京发生了什么大事")
    environment.add_task(
        round_id=round_item.round_id,
        track=[
            {
                "agent": "executor",
                "event": "observe",
                "tool": "read",
                "args": {"path": skill_path},
                "return": "---\nname: time-range-info\n---",
            }
        ],
        task=Task(type="executor", content="previous", status="failed", result="failed"),
    )

    captured: dict[str, object] = {}

    def fake_run_executor_task(**kwargs: object) -> dict[str, object]:
        captured["tasks"] = kwargs["tasks"]
        observe_tools = kwargs["observe_tools"]
        assert isinstance(observe_tools, dict)
        read_result = observe_tools["read"](path=skill_path)
        captured["read_result"] = json.loads(read_result)
        return {
            "task_status": "running",
            "task_result": "正在执行",
            "executor_trace": [],
            "delegated_skill": {
                "skill_name": "time-range-info",
                "tool_name": "web_search",
                "input": {"query": "昨天 北京 重大事件 新闻", "limit": 3},
                "reason": "命中 time-range-info。",
            },
        }

    dispatch_calls: list[dict[str, object]] = []

    def fake_dispatch(**kwargs: object) -> dict[str, object]:
        dispatch_calls.append(dict(kwargs))
        return {
            "accepted": True,
            "run_id": "pyskill:delegate-test",
            "pid": 123,
            "workflow_type": "pyskill",
            "skill_name": "time-range-info",
            "tool_name": "web_search",
        }

    monkeypatch.setattr(nodes_module, "run_executor_task", fake_run_executor_task)
    monkeypatch.setattr(nodes_module.PYSKILL_RUNTIME, "dispatch", fake_dispatch)

    task, _reply, track = nodes_module.executor_node(
        llm=object(),
        executor_system="",
        skills_root="src/task_router_graph/skills",
        workspace_root=repo_root,
        environment=environment,
        task=Task(type="executor", content="用户目标：查询昨天北京发生的大事。\n任务限制：基于可靠来源。"),
    )

    assert task.status == "running"
    assert task.result == "正在执行"
    assert "pyskill:delegate-test" in task.content

    read_result = captured["read_result"]
    assert isinstance(read_result, dict)
    assert read_result["skill_read_status"] == "already_read_in_round"

    tasks = captured["tasks"]
    assert isinstance(tasks, dict)
    round_skill_reads = tasks["round_skill_reads"]
    assert isinstance(round_skill_reads, dict)
    assert round_skill_reads["skills"][0]["name"] == "time-range-info"

    assert len(dispatch_calls) == 1
    call = dispatch_calls[0]
    assert call["workflow_type"] == "pyskill"
    assert call["tool_name"] == "web_search"
    assert call["skill_name"] == "time-range-info"
    assert call["input_payload"] == {"query": "昨天 北京 重大事件 新闻", "limit": 3}

    assert any(item.get("event") == "delegate_skill" for item in track)
    assert any(item.get("event") == "dispatch_pyskill" for item in track)
    assert all(item.get("tool") != "skill_tool" for item in track)
