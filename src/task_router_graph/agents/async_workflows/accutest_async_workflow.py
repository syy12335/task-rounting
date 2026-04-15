from __future__ import annotations

from .async_workflow_common import sleep_for_test_async_workflow_mock


class AccutestAsyncWorkflow:
    # Mock implementation; replace with your real accutest async workflow executor.
    def run(self, *, task_content: str) -> dict[str, str]:
        delay_sec = sleep_for_test_async_workflow_mock()
        return {
            "task_status": "done",
            "task_result": f"accutest mock async workflow finished after {delay_sec:.1f}s: {task_content}",
        }


def run_accutest_async_workflow(*, task_content: str) -> dict[str, str]:
    return AccutestAsyncWorkflow().run(task_content=task_content)
