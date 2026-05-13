# Track 机制说明

本文档描述运行时 `track` 的完整链路。实现以 `src/task_router_graph/` 为准，`track` 是 Environment 内每个 task 的执行轨迹，不是训练侧样本里的单步 action。

## 1. 定位

`TaskRecord.track` 是 `list[dict]`，记录 controller、executor、pyskill、diagnoser、reply 等 agent 在一次 task 生命周期中的关键动作。

它有两个作用：

1. 作为可观测执行日志，支持 CLI 展示、失败复盘和离线分析。
2. 作为轻量状态通道，让后续节点知道前序 agent 已经做过什么。

## 2. 写入链路

`track` 写入 Environment 的主入口是 `update_node`：

```python
track = _controller_trace_to_track(controller_trace)
for step in agent_track:
    if isinstance(step, dict):
        track.append(dict(step))

environment.add_task(
    round_id=round_id,
    track=track,
    task=task,
)
```

主流程可以理解为：

```text
route(controller_trace)
  -> execute(agent_track)
  -> update_node(controller_trace + agent_track)
  -> Environment.add_task(...)
  -> failure_diagnose / final_reply 继续向最后一条 task 追加 track
```

其中：

- controller 的 observe / generate_task 会先通过 `_controller_trace_to_track(...)` 归一化。
- executor / pyskill / workflow 节点产出的 `agent_track` 会直接追加到同一个 list。
- failure diagnose 通过 `annotate_last_failed_task(..., analyzer_track=...)` 追加 `diagnoser` 记录。
- reply 通过 `append_last_task_track(...)` 追加 `reply` 记录。

## 3. 稳定字段约定

每个 track item 是一个 flat dict。以下字段是跨事件类型的稳定约定：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent` | str | 是 | 生产者标识：controller / executor / pyskill / diagnoser / reply / graph |
| `event` | str | 是 | 事件类型：observe / execute / compose / analyze / dispatch_pyskill / ... |
| `ts` | str | 否 | ISO-8601 UTC 时间戳，事件生成时间 |
| `return` | any | 是 | 归一化输出契约。结构化事件为 dict，观测文本为 str |

> **兼容说明**：controller 事件同时保留 `action_kind` 字段（值与 `event` 相同），旧代码可继续使用 `action_kind`，新代码统一使用 `event`。

类型定义见 `src/task_router_graph/schema/track_event.py`，包含每种事件的 TypedDict 和 `return` 字段的预期 schema。可通过 `get_return_schema(agent, event)` 查询。

## 4. 事件类型目录

### 4.1 Controller observe

```json
{
  "agent": "controller",
  "event": "observe",
  "action_kind": "observe",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "tool": "build_context_view",
  "args": {"round_limit": 3},
  "reason": "需要了解当前任务状态",
  "observation": "...",
  "return": "..."
}
```

### 4.2 Controller generate_task

```json
{
  "agent": "controller",
  "event": "generate_task",
  "action_kind": "generate_task",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "task_type": "executor",
  "task_content": "用户目标：...\n任务限制：...",
  "reason": "...",
  "return": {
    "task_type": "executor",
    "task_content": "用户目标：...\n任务限制：..."
  }
}
```

### 4.3 Executor observe

```json
{
  "agent": "executor",
  "event": "observe",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "tool": "read",
  "args": {"path": "src/task_router_graph/skills/executor/xxx/SKILL.md"},
  "reason": "...",
  "return": "..."
}
```

### 4.4 Executor execute / skip

```json
{
  "agent": "executor",
  "event": "execute",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "task_status": "done",
  "task_result": "...",
  "return": {
    "task_status": "done",
    "task_result": "..."
  }
}
```

### 4.5 Executor delegate_skill

```json
{
  "agent": "executor",
  "event": "delegate_skill",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "skill_name": "xxx",
  "tool_name": "yyy",
  "args": {"input": {...}},
  "reason": "...",
  "task_status": "running",
  "task_result": "正在执行",
  "return": {
    "skill_name": "xxx",
    "tool_name": "yyy",
    "input": {...}
  }
}
```

### 4.6 PySkill dispatch / completion

```json
{
  "agent": "pyskill",
  "event": "dispatch_pyskill",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "workflow_type": "pyskill",
  "run_id": "pyskill:a1b2c3...",
  "pid": 12345,
  "task_status": "running",
  "task_result": "正在执行",
  "return": {
    "accepted": true,
    "run_id": "pyskill:a1b2c3...",
    "pid": 12345
  }
}
```

```json
{
  "agent": "pyskill",
  "event": "workflow_complete",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "workflow_type": "pyskill",
  "run_id": "pyskill:a1b2c3...",
  "pid": 12345,
  "source_round_id": 1,
  "source_task_id": 1,
  "task_status": "done",
  "task_result": "...",
  "return": {
    "workflow_type": "pyskill",
    "task_status": "done",
    "task_result": "...",
    "run_id": "pyskill:a1b2c3...",
    "pid": 12345
  }
}
```

### 4.7 PySkill link_pyskill_result

```json
{
  "agent": "pyskill",
  "event": "link_pyskill_result",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "run_id": "pyskill:a1b2c3...",
  "task_status": "done",
  "task_result": "pyskill_task(round_id=1, task_id=2)",
  "return": {
    "run_id": "pyskill:a1b2c3...",
    "source_round_id": 1,
    "source_task_id": 1,
    "pyskill_round_id": 1,
    "pyskill_task_id": 2
  }
}
```

### 4.8 Diagnoser analyze

```json
{
  "agent": "diagnoser",
  "event": "analyze",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "task_status": "failed",
  "task_result": "...",
  "analysis": "失败原因是...",
  "return": {
    "analysis": "失败原因是...",
    "task_result": "..."
  }
}
```

### 4.9 Reply compose / retry

```json
{
  "agent": "reply",
  "event": "compose",
  "ts": "2026-05-13T08:30:00.123456+00:00",
  "task_status": "done",
  "task_result": "...",
  "reply": "你的任务已完成，结果是...",
  "return": {
    "task_status": "done",
    "task_result": "...",
    "reply": "你的任务已完成，结果是..."
  }
}
```

### 4.10 Graph infrastructure events

- `status_shortcut` (agent="graph") — 状态追问快捷汇总
- `workflow_route_failed` (agent="graph") — workflow 路由失败
- `reply_completion_patch` (agent="graph") — 回复补丁
- `workflow_skip` (agent="pyskill") — workflow 跳过
- `dispatch_pyskill_failed` (agent="pyskill") — 分发失败

## 5. 关键设计

### 5.1 Track item 只追加、不回写

`Environment.add_task(...)`、`append_last_task_track(...)` 和 `annotate_last_failed_task(...)` 都使用副本写入或追加。已有 track item 不会被原地修改。

需要注意：failure diagnose 会更新失败 task 的 `task.result`，但这是 task 状态修正，不是修改历史 track item。

### 5.2 Track 对 controller 默认不可见

默认 context view 不带 trace：

```python
environment.build_context_view(include_trace=False)
```

只有显式请求时才会携带 track：

```python
environment.build_context_view(include_trace=True)
```

`build_context_view` 的工具入口还会限制视图大小：

```python
MAX_OBSERVATION_VIEW_TASKS = 20
MAX_OBSERVATION_VIEW_WITH_TRACE_TASKS = 5
```

也就是说，带 trace 的视图会被收得更窄，避免把低密度执行日志自动灌进 controller 上下文。

### 5.3 Track 支撑同 round 的隐式状态共享

`_build_round_skill_read_context(...)` 会在 executor 执行前扫描当前 round 内已有 task 的 track，避免重复读取同一个 skill 文件。

这也是 `track` 不只是日志的原因：它还承担了 agent 间低耦合的执行事实传递。

### 5.4 失败任务 track 受裁剪保护

失败任务的 track 在视图中不会被裁剪到 L2（激进裁剪）以下。排障时可以确信失败任务保留了完整的事件结构。

## 6. 视图裁剪策略

`build_context_view()` 支持 `trim_level` 参数，控制 AI 上下文中 track 数据的裁剪程度：

| 级别 | 常量 | 行为 | 适用场景 |
|------|------|------|----------|
| L0 | `TRIM_LEVEL_NONE` | 不裁剪，完整 track | 排障调试、持久化 |
| L1 | `TRIM_LEVEL_LIGHT` | 压缩 `return` 中的长文本（保留 head+tail，中段替换为 `[COMPACTED_VIEW]`） | AI 上下文窗口（默认） |
| L2 | `TRIM_LEVEL_AGGRESSIVE` | 删除 `observation`/`reason`/`analysis`/`reply` 等冗余文本字段，仅保留结构化字段和 `return` | 高密度上下文窗口 |
| L3 | `TRIM_LEVEL_HISTORY` | 不携带 track，仅保留 task 级状态 | 历史回滚摘要 |

**裁剪保护规则**：
- 失败任务（`task.status == "failed"`）的 track 最低裁剪到 L1，不会被 L2/L3 裁剪。
- `return` 字段始终保留（它本身就是摘要契约）。
- 历史回滚（L3）由 `_rollup_environment_if_needed()` 触发，与其他裁剪级别独立。

使用示例：

```python
from src.task_router_graph.schema import TRIM_LEVEL_LIGHT, TRIM_LEVEL_AGGRESSIVE

# AI 上下文：轻量裁剪
view = environment.build_context_view(include_trace=True, trim_level=TRIM_LEVEL_LIGHT)

# 排障：不裁剪
view = environment.build_context_view(include_trace=True, trim_level=TRIM_LEVEL_NONE)
```

向后兼容：`compress=True` 等价于 `trim_level=TRIM_LEVEL_LIGHT`。

## 7. 排障读取入口

### 7.1 三级入口

| 级别 | 入口 | 用途 | 展示内容 |
|------|------|------|----------|
| 快速诊断 | `previous_failed_track` 工具 | 运行时自动排障 | 最近失败任务的**完整** track |
| 上下文排查 | `build_context_view(include_trace=True)` 工具 | Controller 深度排查 | 最近 5 个任务（带 track，默认 L0） |
| 终端调试 | `show_environment(show_trace=True)` 工具 | 人工 CLI 调试 | 全量 Environment 文本转储（含 ts） |
| 离线分析 | `var/runs/*/environment.json` | 事后分析 | 完整持久化数据（`to_dict(include_trace=True)`） |

### 7.2 排障路径示例

**场景 A：当前轮任务失败，需要看 controller 做了什么**

```
1. previous_failed_track {}  → 获取失败任务完整 track
2. 检查 track 中 agent="controller" 的事件，看 observe 步骤和最终 generate_task
3. 如果 controller 信息不足，用 build_context_view(include_trace=True, round_limit=3) 扩大上下文
```

**场景 B：Executor 工具调用返回异常**

```
1. previous_failed_track {}  → 获取失败任务 track
2. 定位 agent="executor", event="observe" 的事件
3. 检查 tool 名称、args 参数、return 内容
4. 对比前一个 controller observe 步骤，看是否有矛盾信息
```

**场景 C：PySkill 异步任务未完成**

```
1. show_environment(show_trace=True)  → 终端查看全量状态
2. 搜索 event="dispatch_pyskill" 找 run_id
3. 搜索相同 run_id 的 event="workflow_complete" 或 "workflow_fail"
4. 如果不存在完成事件，说明任务仍在执行或进程已死
```

## 8. 使用约束

1. 读执行历史时，优先把 `return` 当成该步的归一化输出。
2. 所有新代码统一使用 `event` 字段（非 `action_kind`）。
3. controller 默认不要带 trace 观察全局环境；需要排障时再显式读取。
4. 新增 agent 或节点时，优先追加结构化 `return`，避免只写自然语言日志。
5. `track` 可以用于复盘和局部状态共享，但不应替代 Environment 的正式 task/status/result 字段。
6. 排障时失败任务的 track 不会被裁剪，可以放心依赖其完整性。
7. 离线分析从 `var/runs/*/environment.json` 入手，数据最完整。
