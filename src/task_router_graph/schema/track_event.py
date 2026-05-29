"""
Track event type definitions.

Each track item in ``TaskRecord.track`` is a flat dict with at minimum
the keys ``agent``, ``event``, and ``return``.  Additional fields vary by
event type.

.. note::

    The ``return`` field is a reserved Python keyword and cannot appear in
    TypedDict class bodies.  It is documented in each class docstring and
    its expected schema is available via ``get_return_schema(agent, event)``.

The TypedDict classes below are documentation aids — track items are stored
as ``list[dict]`` with no runtime type enforcement.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Shared field conventions
# ---------------------------------------------------------------------------
# agent   — required str, producer identifier
# event   — required str, event type (observe / execute / compose / …)
# ts      — optional str, ISO-8601 UTC timestamp
# return  — required dict | str, normalized output contract for this step
#           (not in TypedDict bodies — see get_return_schema)
# reason  — optional str, human-readable rationale (controller / executor)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class TrackEventBase(TypedDict, total=False):
    """Fields present on every track item (except ``return`` — see module docs)."""
    agent: str
    event: str
    ts: str


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ControllerObserveEvent(TypedDict, total=False):
    """Controller observe step.

    ``return``: ``str`` — same as observation text.
    """
    agent: str          # "controller"
    event: str          # "observe"
    action_kind: str    # "observe" (legacy, kept for backward compat)
    ts: str
    tool: str
    args: dict[str, Any]
    reason: str
    observation: str

    # reserved for backward-compat with ControllerAction serialisation
    task_type: NotRequired[str]
    task_content: NotRequired[str]


class ControllerGenerateTaskEvent(TypedDict, total=False):
    """Controller emitted the final task for this turn.

    ``return``: ``_GenerateTaskReturn`` — {task_type, task_content}.
    """
    agent: str          # "controller"
    event: str          # "generate_task"
    action_kind: str    # "generate_task" (legacy)
    ts: str
    task_type: str
    task_content: str
    reason: str


class _GenerateTaskReturn(TypedDict):
    task_type: str
    task_content: str


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class ExecutorObserveEvent(TypedDict, total=False):
    """Executor observed a tool result.

    ``return``: ``str`` — tool output text.
    """
    agent: str          # "executor"
    event: str          # "observe"
    ts: str
    tool: str
    args: dict[str, Any]
    reason: str


class ExecutorExecuteEvent(TypedDict, total=False):
    """Executor finished executing a task.

    ``return``: ``_TaskStatusReturn`` — {task_status, task_result}.
    """
    agent: str          # "executor"
    event: str          # "execute"
    ts: str
    task_status: str
    task_result: str


class ExecutorSkipEvent(TypedDict, total=False):
    """Executor skipped an already-resolved task.

    ``return``: ``_TaskStatusReturn`` — {task_status, task_result}.
    """
    agent: str          # "executor"
    event: str          # "skip"
    ts: str
    task_status: str
    task_result: str


class _TaskStatusReturn(TypedDict):
    task_status: str
    task_result: str


class ExecutorDelegateSkillEvent(TypedDict, total=False):
    """Executor delegated work to a pyskill.

    ``return``: ``_DelegateSkillReturn`` — {skill_name, tool_name, input}.
    """
    agent: str          # "executor"
    event: str          # "delegate_skill"
    ts: str
    skill_name: str
    tool_name: str
    args: dict[str, Any]
    reason: str
    task_status: str
    task_result: str


class _DelegateSkillReturn(TypedDict):
    skill_name: str
    tool_name: str
    input: Any


# ---------------------------------------------------------------------------
# PySkill
# ---------------------------------------------------------------------------

class PySkillDispatchEvent(TypedDict, total=False):
    """A pyskill workflow was dispatched.

    ``return``: ``dict[str, Any]`` — dispatch payload.
    """
    agent: str          # "pyskill"
    event: str          # "dispatch_pyskill"
    ts: str
    workflow_type: str
    run_id: str
    pid: int
    task_status: str
    task_result: str


class PySkillDispatchFailedEvent(TypedDict, total=False):
    """A pyskill dispatch was rejected or failed immediately.

    ``return``: ``dict[str, Any]`` — error payload.
    """
    agent: str          # "pyskill"
    event: str          # "dispatch_pyskill_failed"
    ts: str
    workflow_type: str
    task_status: str
    task_result: str


class PySkillCompletionEvent(TypedDict, total=False):
    """A pyskill workflow completed (success or failure).

    ``return``: ``_PySkillCompletionReturn`` — {workflow_type, task_status, task_result, run_id, pid}.
    """
    agent: str          # "pyskill"
    event: str          # "workflow_complete" | "workflow_fail"
    ts: str
    workflow_type: str
    run_id: str
    pid: int
    source_round_id: int
    source_task_id: int
    task_status: str
    task_result: str


class _PySkillCompletionReturn(TypedDict):
    workflow_type: str
    task_status: str
    task_result: str
    run_id: str
    pid: int


class PySkillLinkResultEvent(TypedDict, total=False):
    """Back-link from source task to completed pyskill task.

    ``return``: ``_LinkResultReturn`` — {run_id, source_round_id, source_task_id, pyskill_round_id, pyskill_task_id}.
    """
    agent: str          # "pyskill"
    event: str          # "link_pyskill_result"
    ts: str
    run_id: str
    task_status: str
    task_result: str


class _LinkResultReturn(TypedDict):
    run_id: str
    source_round_id: int
    source_task_id: int
    pyskill_round_id: int
    pyskill_task_id: int


class PySkillWorkflowSkipEvent(TypedDict, total=False):
    """A workflow was skipped because the task was already done/failed.

    ``return``: ``_WorkflowSkipReturn`` — {workflow_type, task_status, task_result}.
    """
    agent: str          # "pyskill"
    event: str          # "workflow_skip"
    ts: str
    workflow_type: str
    task_status: str
    task_result: str


class _WorkflowSkipReturn(TypedDict):
    workflow_type: str
    task_status: str
    task_result: str


# ---------------------------------------------------------------------------
# Diagnoser
# ---------------------------------------------------------------------------

class DiagnoserAnalyzeEvent(TypedDict, total=False):
    """Failure diagnoser analysed a failed task's track.

    ``return``: ``_DiagnosisReturn`` — {analysis, task_result}.
    """
    agent: str          # "diagnoser"
    event: str          # "analyze"
    ts: str
    task_status: str    # "failed"
    task_result: str
    analysis: str


class _DiagnosisReturn(TypedDict):
    analysis: str
    task_result: str


# ---------------------------------------------------------------------------
# Reply
# ---------------------------------------------------------------------------

class ReplyComposeEvent(TypedDict, total=False):
    """Final reply composed for the user.

    ``return``: ``_ReplyReturn`` — {task_status, task_result, reply}.
    """
    agent: str          # "reply"
    event: str          # "compose"
    ts: str
    task_status: str
    task_result: str
    reply: str


class _ReplyReturn(TypedDict):
    task_status: str
    task_result: str
    reply: str


class ReplyRetryEvent(TypedDict, total=False):
    """Auto-retry notice emitted before re-routing a failed task.

    ``return``: ``_RetryReplyReturn`` — {reply, retry_count, max_retries}.
    """
    agent: str          # "reply"
    event: str          # "retry_reply"
    ts: str
    task_status: str    # "retrying"
    task_result: str


class _RetryReplyReturn(TypedDict):
    reply: str
    retry_count: int
    max_retries: int


# ---------------------------------------------------------------------------
# Graph (infrastructure events)
# ---------------------------------------------------------------------------

class GraphStatusShortcutEvent(TypedDict, total=False):
    """Graph short-circuited a status query.

    ``return``: ``_StatusShortcutReturn`` — {collected_count}.
    """
    agent: str          # "graph"
    event: str          # "status_shortcut"
    ts: str
    task_status: str
    task_result: str


class _StatusShortcutReturn(TypedDict):
    collected_count: int


class GraphWorkflowRouteFailedEvent(TypedDict, total=False):
    """Graph failed to route to a workflow (unknown task_type).

    ``return``: ``_WorkflowRouteFailedReturn`` — {task_type, registered_workflow_types}.
    """
    agent: str          # "graph"
    event: str          # "workflow_route_failed"
    ts: str
    workflow_type: str
    task_status: str
    task_result: str


class _WorkflowRouteFailedReturn(TypedDict):
    task_type: str
    registered_workflow_types: list[str]


class GraphReplyCompletionPatchEvent(TypedDict, total=False):
    """Graph patched the final reply with workflow completion notice.

    ``return``: ``_ReplyCompletionPatchReturn`` — {workflow_events_count, reply}.
    """
    agent: str          # "graph"
    event: str          # "reply_completion_patch"
    ts: str


class _ReplyCompletionPatchReturn(TypedDict):
    workflow_events_count: int
    reply: str


# ---------------------------------------------------------------------------
# Union type for TaskRecord.track items
# ---------------------------------------------------------------------------

TrackEvent = (
    ControllerObserveEvent
    | ControllerGenerateTaskEvent
    | ExecutorObserveEvent
    | ExecutorExecuteEvent
    | ExecutorSkipEvent
    | ExecutorDelegateSkillEvent
    | PySkillDispatchEvent
    | PySkillDispatchFailedEvent
    | PySkillCompletionEvent
    | PySkillLinkResultEvent
    | PySkillWorkflowSkipEvent
    | DiagnoserAnalyzeEvent
    | ReplyComposeEvent
    | ReplyRetryEvent
    | GraphStatusShortcutEvent
    | GraphWorkflowRouteFailedEvent
    | GraphReplyCompletionPatchEvent
)


# ---------------------------------------------------------------------------
# Return-value schemas — maps (agent, event) → expected return type
# ---------------------------------------------------------------------------

_RETURN_SCHEMAS: dict[tuple[str, str], type[dict[str, Any]] | type[str]] = {
    ("controller", "observe"): str,
    ("controller", "generate_task"): _GenerateTaskReturn,
    ("executor", "observe"): str,
    ("executor", "execute"): _TaskStatusReturn,
    ("executor", "skip"): _TaskStatusReturn,
    ("executor", "delegate_skill"): _DelegateSkillReturn,
    ("pyskill", "dispatch_pyskill"): dict,
    ("pyskill", "dispatch_pyskill_failed"): dict,
    ("pyskill", "workflow_complete"): _PySkillCompletionReturn,
    ("pyskill", "workflow_fail"): _PySkillCompletionReturn,
    ("pyskill", "link_pyskill_result"): _LinkResultReturn,
    ("pyskill", "workflow_skip"): _WorkflowSkipReturn,
    ("diagnoser", "analyze"): _DiagnosisReturn,
    ("reply", "compose"): _ReplyReturn,
    ("reply", "retry_reply"): _RetryReplyReturn,
    ("graph", "status_shortcut"): _StatusShortcutReturn,
    ("graph", "workflow_route_failed"): _WorkflowRouteFailedReturn,
    ("graph", "reply_completion_patch"): _ReplyCompletionPatchReturn,
}


def get_return_schema(agent: str, event: str) -> type[dict[str, Any]] | type[str] | None:
    """Return the expected type of the ``return`` field for *(agent, event)*, or None."""
    return _RETURN_SCHEMAS.get((str(agent).strip().lower(), str(event).strip().lower()))
