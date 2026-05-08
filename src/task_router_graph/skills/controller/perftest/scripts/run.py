from __future__ import annotations

from task_router_graph.agents.async_workflows.async_workflow_common import sleep_for_test_async_workflow_mock


def run(*, task_content: str) -> dict[str, str]:
    delay_sec = sleep_for_test_async_workflow_mock()
    return {
        "task_status": "done",
        "task_result": f"perftest mock async workflow finished after {delay_sec:.1f}s: {task_content}",
    }
