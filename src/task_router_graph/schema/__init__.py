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
    build_controller_action_schema,
    build_controller_output_constraints,
    normalize_controller_task_types,
    validate_controller_action_dict,
    validate_controller_action_payload,
)
from .environment import (
    TRIM_LEVEL_AGGRESSIVE,
    TRIM_LEVEL_HISTORY,
    TRIM_LEVEL_LIGHT,
    TRIM_LEVEL_NONE,
    Environment,
)
from .output import Output
from .round_record import RoundRecord
from .task import Task
from .task_record import TaskRecord
from .track_event import (
    TrackEvent,
    TrackEventBase,
    get_return_schema,
)

__all__ = [
    "ControllerAction",
    "CONTROLLER_ACTION_SCHEMA",
    "CONTROLLER_ALLOWED_ACTION_KINDS",
    "CONTROLLER_ALLOWED_OBSERVE_TOOLS",
    "CONTROLLER_ALLOWED_TASK_TYPES",
    "CONTROLLER_OUTPUT_CONSTRAINTS",
    "build_controller_action_schema",
    "build_controller_output_constraints",
    "normalize_controller_task_types",
    "Task",
    "TaskRecord",
    "RoundRecord",
    "Environment",
    "Output",
    "TrackEvent",
    "TrackEventBase",
    "TRIM_LEVEL_NONE",
    "TRIM_LEVEL_LIGHT",
    "TRIM_LEVEL_AGGRESSIVE",
    "TRIM_LEVEL_HISTORY",
    "get_return_schema",
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
