"""Schema 聚合入口。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .controller_action import (
    CONTROLLER_ACTION_SCHEMA,
    CONTROLLER_ALLOWED_ACTION_KINDS,
    CONTROLLER_ALLOWED_OBSERVE_TOOLS,
    CONTROLLER_ALLOWED_TASK_TYPES,
    CONTROLLER_OUTPUT_CONSTRAINTS,
    ControllerAction,
    validate_controller_action_dict,
    validate_controller_action_payload,
)
from .environment import Environment
from .output import Output
from .round_record import RoundRecord
from .task import Task
from .task_record import TaskRecord

__all__ = [
    "ControllerAction",
    "CONTROLLER_ACTION_SCHEMA",
    "CONTROLLER_ALLOWED_ACTION_KINDS",
    "CONTROLLER_ALLOWED_OBSERVE_TOOLS",
    "CONTROLLER_ALLOWED_TASK_TYPES",
    "CONTROLLER_OUTPUT_CONSTRAINTS",
    "Task",
    "TaskRecord",
    "RoundRecord",
    "Environment",
    "Output",
    "to_dict",
    "validate_controller_action_dict",
    "validate_controller_action_payload",
]


def to_dict(data: Any) -> Any:
    if hasattr(data, "to_dict") and callable(getattr(data, "to_dict")):
        return data.to_dict()
    if is_dataclass(data):
        return asdict(data)
    return data
