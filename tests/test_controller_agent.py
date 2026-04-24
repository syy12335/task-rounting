from __future__ import annotations

import json
from types import SimpleNamespace

from task_router_graph.agents.controller_agent import ControllerAgent
from task_router_graph.schema import CONTROLLER_ACTION_SCHEMA, CONTROLLER_OUTPUT_CONSTRAINTS


class _FakeLLM:
    def __init__(self) -> None:
        self.bound_response_format: dict[str, object] | None = None
        self.invoke_messages: list[list[object]] = []

    def bind(self, **kwargs: object) -> "_FakeLLM":
        self.bound_response_format = kwargs.get("response_format")  # type: ignore[assignment]
        return self

    def invoke(self, messages: list[object], config: dict[str, object] | None = None) -> SimpleNamespace:
        del config
        self.invoke_messages.append(messages)
        return SimpleNamespace(
            content=json.dumps(
                {
                    "action_kind": "generate_task",
                    "task_type": "executor",
                    "task_content": "处理用户请求",
                    "reason": "已有足够信息，直接生成执行任务。",
                },
                ensure_ascii=False,
            )
        )


def test_controller_agent_injects_shared_output_constraints_for_generate_task() -> None:
    llm = _FakeLLM()
    agent = ControllerAgent(
        llm=llm,
        system_prompt="USER={{USER_INPUT}}\nENV={{ENVIRONMENT_JSON}}\nSKILLS={{SKILLS_INDEX}}",
    )

    result = agent.run(
        user_input="你好",
        tasks={"rounds": [], "cur_round": 0},
        skills_index="[]",
        observe_tools={},
    )

    assert llm.bound_response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "controller_action",
            "strict": True,
            "schema": CONTROLLER_ACTION_SCHEMA,
        },
    }
    assert len(llm.invoke_messages) == 1

    last_message = llm.invoke_messages[0][-1]
    payload = json.loads(last_message.content)
    assert payload["output_constraints"] == CONTROLLER_OUTPUT_CONSTRAINTS

    assert result["task_type"] == "executor"
    assert result["task_content"] == "处理用户请求"
    assert result["controller_trace"] == []
