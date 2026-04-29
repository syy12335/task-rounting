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

## 3. 常见 Track Item

### 3.1 Controller observe

controller observe 会保留工具调用参数、原因、观察结果，并把 `observation` 复制到统一的 `return` 字段：

```json
{
  "agent": "controller",
  "action_kind": "observe",
  "tool": "build_context_view",
  "args": {
    "round_limit": 3
  },
  "reason": "需要了解当前任务状态",
  "observation": "...",
  "return": "..."
}
```

### 3.2 Controller generate_task

controller 生成 task 时，`return` 只保留 task type 和 task content：

```json
{
  "agent": "controller",
  "action_kind": "generate_task",
  "task_type": "executor",
  "task_content": "用户目标：...\n任务限制：...",
  "reason": "...",
  "return": {
    "task_type": "executor",
    "task_content": "用户目标：...\n任务限制：..."
  }
}
```

### 3.3 Executor observe

executor 每次工具调用会被归一化成 `event=observe`。落盘 track 不保留内部 `observation_raw`，只保留裁剪后的工具结果到 `return`：

```json
{
  "agent": "executor",
  "event": "observe",
  "tool": "read",
  "args": {
    "path": "src/task_router_graph/skills/executor/xxx/SKILL.md"
  },
  "reason": "...",
  "return": "..."
}
```

### 3.4 Executor execute

executor 完成或跳过执行时，会追加一条摘要事件：

```json
{
  "agent": "executor",
  "event": "execute",
  "task_status": "done",
  "task_result": "...",
  "return": {
    "task_status": "done",
    "task_result": "..."
  }
}
```

`functest_async_workflow`、`accutest_async_workflow`、`perftest_async_workflow` 也复用同一类摘要结构，`agent` 和 `event` 会换成对应 workflow 名称与阶段。

### 3.5 PySkill dispatch

当 executor 命中 `skill-mode=pyskill`，会追加 dispatch 记录：

```json
{
  "agent": "pyskill",
  "event": "dispatch_pyskill",
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

### 3.6 Diagnoser analyze

失败诊断会读取失败 task 的完整 track，生成分析后追加：

```json
{
  "agent": "diagnoser",
  "event": "analyze",
  "task_status": "failed",
  "task_result": "...",
  "analysis": "失败原因是...",
  "return": {
    "analysis": "失败原因是...",
    "task_result": "..."
  }
}
```

### 3.7 Reply compose

最终回复会追加到当前最后一条 task：

```json
{
  "agent": "reply",
  "event": "compose",
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

## 4. 关键设计

### 4.1 Track item 只追加、不回写

`Environment.add_task(...)`、`append_last_task_track(...)` 和 `annotate_last_failed_task(...)` 都使用副本写入或追加。已有 track item 不会被原地修改。

需要注意：failure diagnose 会更新失败 task 的 `task.result`，但这是 task 状态修正，不是修改历史 track item。

### 4.2 Track 对 controller 默认不可见

默认 context view 不带 trace：

```python
environment.build_context_view(include_trace=False)
```

只有显式请求时才会携带 track：

```python
environment.build_context_view(include_trace=True)
```

或者通过工具读取最近失败任务的完整轨迹：

```python
previous_failed_track {}
```

`build_context_view` 的工具入口还会限制视图大小：

```python
MAX_OBSERVATION_VIEW_TASKS = 20
MAX_OBSERVATION_VIEW_WITH_TRACE_TASKS = 5
```

也就是说，带 trace 的视图会被收得更窄，避免把低密度执行日志自动灌进 controller 上下文。controller 想看失败轨迹，应该显式调用 `previous_failed_track`。

### 4.3 Track 支撑同 round 的隐式状态共享

`_build_round_skill_read_context(...)` 会在 executor 执行前扫描当前 round 内已有 task 的 track：

```python
for task_item in round_item.tasks:
    for step in task_item.track:
        if step.get("tool") != "read":
            continue
        path = step["args"].get("path")
        if Path(path).name == "SKILL.md":
            ...
```

只要某个 executor 在当前 round 里读过某个 `SKILL.md`，后续 executor 就能通过 `round_skill_reads` 感知这件事，避免重复读取同一个 skill 文件。

这也是 `track` 不只是日志的原因：它还承担了 agent 间低耦合的执行事实传递。

## 5. 使用约束

1. 读执行历史时，优先把 `return` 当成该步的归一化输出。
2. 不要假设所有 track item 都有同一组字段；不同 agent 的事件结构不同。
3. controller 默认不要带 trace 观察全局环境；需要排障时再显式读取。
4. 新增 agent 或节点时，优先追加结构化 `return`，避免只写自然语言日志。
5. `track` 可以用于复盘和局部状态共享，但不应替代 Environment 的正式 task/status/result 字段。

