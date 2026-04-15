from __future__ import annotations

import time


FIXED_TEST_ASYNC_WORKFLOW_MOCK_SLEEP_SEC = 5.0


def sleep_for_test_async_workflow_mock() -> float:
    # Placeholder delay for mock async workflows to simulate long-running execution.
    time.sleep(FIXED_TEST_ASYNC_WORKFLOW_MOCK_SLEEP_SEC)
    return FIXED_TEST_ASYNC_WORKFLOW_MOCK_SLEEP_SEC
