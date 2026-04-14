from __future__ import annotations

from .common import sleep_for_test_agent_mock


class PerftestAgent:
    # Mock implementation; replace with your real performance-test workflow executor.
    def run(self, *, task_content: str) -> dict[str, str]:
        delay_sec = sleep_for_test_agent_mock()
        return {
            "task_status": "done",
            "task_result": f"perftest mock finished after {delay_sec:.1f}s: {task_content}",
        }


def run_perftest_task(*, task_content: str) -> dict[str, str]:
    return PerftestAgent().run(task_content=task_content)
