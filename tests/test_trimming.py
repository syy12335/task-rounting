from __future__ import annotations

import pytest
from task_router_graph.schema import Environment, Task
from task_router_graph.schema.environment import (
    TRIM_LEVEL_NONE,
    TRIM_LEVEL_LIGHT,
    TRIM_LEVEL_AGGRESSIVE,
    TRIM_LEVEL_HISTORY,
    _compact_return_value,
    _compact_text_value,
    _trim_track_for_view,
    _safe_target_tokens,
)


# ---------------------------------------------------------------------------
# _compact_return_value
# ---------------------------------------------------------------------------

def test_compact_return_value_preserves_dict_structure():
    value = {"summary": "ok", "details": "x" * 5000}
    result = _compact_return_value(value, target_tokens=200)
    assert isinstance(result, dict)
    assert result["summary"] == "ok"
    assert "[COMPACTED_VIEW]" in result["details"]


def test_compact_return_value_preserves_list_structure():
    value = ["short", "y" * 5000, 42]
    result = _compact_return_value(value, target_tokens=200)
    assert isinstance(result, list)
    assert result[0] == "short"
    assert "[COMPACTED_VIEW]" in result[1]
    assert result[2] == 42


def test_compact_return_value_nested_dict():
    value = {"a": {"b": "z" * 5000, "c": 1}, "d": True}
    result = _compact_return_value(value, target_tokens=200)
    assert isinstance(result["a"], dict)
    assert "[COMPACTED_VIEW]" in result["a"]["b"]
    assert result["a"]["c"] == 1
    assert result["d"] is True


def test_compact_return_value_passes_non_string_scalars():
    assert _compact_return_value(42, target_tokens=200) == 42
    assert _compact_return_value(True, target_tokens=200) is True
    assert _compact_return_value(None, target_tokens=200) is None
    assert _compact_return_value(3.14, target_tokens=200) == 3.14


def test_compact_return_value_short_string_unchanged():
    assert _compact_return_value("hello", target_tokens=200) == "hello"


# ---------------------------------------------------------------------------
# _trim_track_for_view — L0 (no trim)
# ---------------------------------------------------------------------------

def test_trim_l0_returns_full_track():
    track = [
        {"agent": "executor", "event": "execute", "return": "done", "observation": "saw X"},
        {"agent": "controller", "event": "observe", "return": "ok", "reason": "check"},
    ]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_NONE, target_tokens=200)
    assert len(result) == 2
    assert result[0]["observation"] == "saw X"
    assert result[1]["reason"] == "check"


# ---------------------------------------------------------------------------
# _trim_track_for_view — L1 (light compact)
# ---------------------------------------------------------------------------

def test_trim_l1_compacts_long_return_text():
    track = [{"agent": "executor", "event": "execute", "return": "x" * 5000}]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_LIGHT, target_tokens=200)
    assert "[COMPACTED_VIEW]" in result[0]["return"]


def test_trim_l1_preserves_dict_return_structure():
    track = [{"agent": "pyskill", "event": "dispatch_pyskill", "return": {"msg": "ok", "log": "y" * 5000}}]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_LIGHT, target_tokens=200)
    ret = result[0]["return"]
    assert isinstance(ret, dict)
    assert ret["msg"] == "ok"
    assert "[COMPACTED_VIEW]" in ret["log"]


def test_trim_l1_preserves_list_return_structure():
    track = [{"agent": "executor", "event": "execute", "return": ["a", "b" * 5000, 3]}]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_LIGHT, target_tokens=200)
    ret = result[0]["return"]
    assert isinstance(ret, list)
    assert ret[0] == "a"
    assert "[COMPACTED_VIEW]" in ret[1]
    assert ret[2] == 3


def test_trim_l1_short_return_unchanged():
    track = [{"agent": "executor", "event": "execute", "return": "short"}]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_LIGHT, target_tokens=200)
    assert result[0]["return"] == "short"


# ---------------------------------------------------------------------------
# _trim_track_for_view — L2 (aggressive)
# ---------------------------------------------------------------------------

def test_trim_l2_drops_verbose_fields():
    track = [
        {
            "agent": "executor",
            "event": "execute",
            "return": "ok",
            "observation": "verbose obs",
            "reason": "verbose reason",
            "analysis": "verbose analysis",
            "reply": "verbose reply",
        }
    ]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_AGGRESSIVE, target_tokens=200)
    item = result[0]
    assert "observation" not in item
    assert "reason" not in item
    assert "analysis" not in item
    assert "reply" not in item
    assert item["return"] == "ok"


def test_trim_l2_preserves_dict_return_structure():
    track = [
        {
            "agent": "pyskill",
            "event": "dispatch_pyskill",
            "return": {"out": "z" * 5000},
            "observation": "drop me",
            "reason": "drop me too",
        }
    ]
    result = _trim_track_for_view(track, trim_level=TRIM_LEVEL_AGGRESSIVE, target_tokens=200)
    item = result[0]
    assert "observation" not in item
    assert "reason" not in item
    assert isinstance(item["return"], dict)
    assert "[COMPACTED_VIEW]" in item["return"]["out"]


# ---------------------------------------------------------------------------
# _trim_track_for_view — L3 (history) and failed-task protection
# ---------------------------------------------------------------------------

def test_trim_l3_normal_task_returns_empty_track():
    track = [{"agent": "executor", "event": "execute", "return": "done"}]
    result = _trim_track_for_view(
        track, trim_level=TRIM_LEVEL_HISTORY, target_tokens=200, is_failed_task=False
    )
    assert result == []


def test_trim_l3_failed_task_keeps_l1_track():
    track = [{"agent": "executor", "event": "execute", "return": "x" * 5000}]
    result = _trim_track_for_view(
        track, trim_level=TRIM_LEVEL_HISTORY, target_tokens=200, is_failed_task=True
    )
    assert len(result) == 1
    # L1 protection: return is compacted but present
    assert "[COMPACTED_VIEW]" in result[0]["return"]


def test_trim_l2_failed_task_demoted_to_l1():
    """Failed tasks at L2 get L1 instead — verbose fields survive."""
    track = [
        {
            "agent": "executor",
            "event": "execute",
            "return": "ok",
            "observation": "must survive",
        }
    ]
    result = _trim_track_for_view(
        track, trim_level=TRIM_LEVEL_AGGRESSIVE, target_tokens=200, is_failed_task=True
    )
    assert result[0]["observation"] == "must survive"


# ---------------------------------------------------------------------------
# build_context_view — L3 with failed tasks
# ---------------------------------------------------------------------------

def _make_env_with_task(status: str, track: list | None = None):
    env = Environment()
    round_item = env.start_round(user_input="test")
    env.add_task(
        round_id=round_item.round_id,
        track=track or [],
        task=Task(type="executor", content="do thing", status=status, result="some result"),
    )
    return env


def test_build_context_view_l3_failed_task_has_track():
    track = [{"agent": "executor", "event": "execute", "return": "x" * 5000}]
    env = _make_env_with_task("failed", track=track)
    view = env.build_context_view(include_trace=True, trim_level=TRIM_LEVEL_HISTORY)
    task_view = view["rounds"][0]["tasks"][0]
    assert "track" in task_view
    assert len(task_view["track"]) == 1
    assert "[COMPACTED_VIEW]" in task_view["track"][0]["return"]


def test_build_context_view_l3_normal_task_no_track():
    track = [{"agent": "executor", "event": "execute", "return": "done"}]
    env = _make_env_with_task("done", track=track)
    view = env.build_context_view(include_trace=True, trim_level=TRIM_LEVEL_HISTORY)
    task_view = view["rounds"][0]["tasks"][0]
    assert task_view.get("track", []) == []


def test_build_context_view_l3_multiple_tasks_mixed():
    """L3: failed task keeps L1 track, normal task gets empty track."""
    env = Environment()
    round_item = env.start_round(user_input="test")
    # Task 1: normal (done)
    env.add_task(
        round_id=round_item.round_id,
        track=[{"agent": "executor", "event": "execute", "return": "normal_out"}],
        task=Task(type="executor", content="normal", status="done", result="ok"),
    )
    # Task 2: failed
    env.add_task(
        round_id=round_item.round_id,
        track=[{"agent": "executor", "event": "execute", "return": "fail_out"}],
        task=Task(type="executor", content="broken", status="failed", result="error"),
    )

    view = env.build_context_view(include_trace=True, trim_level=TRIM_LEVEL_HISTORY)
    tasks = view["rounds"][0]["tasks"]
    # Normal task: empty track
    assert tasks[0].get("track", []) == []
    # Failed task: L1 track preserved
    assert len(tasks[1]["track"]) == 1
    assert tasks[1]["track"][0]["return"] == "fail_out"
