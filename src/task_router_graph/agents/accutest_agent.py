from __future__ import annotations

from .common import sleep_for_test_agent_mock


class AccutestAgent:
    # Mock implementation; replace with your real accuracy-test workflow executor.
    def run(self, *, task_content: str) -> dict[str, str]:
        delay_sec = sleep_for_test_agent_mock()
        return {
            "task_status": "done",
            "task_result": f"accutest mock finished after {delay_sec:.1f}s: {task_content}",
        }


def run_accutest_task(*, task_content: str) -> dict[str, str]:
    return AccutestAgent().run(task_content=task_content)
