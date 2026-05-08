---
name: functest
description: 生成 functest workflow 任务，明确本轮功能测试对象、目标与关注方向。
when_to_use: 用户明确要求执行功能测试、功能复测，或请求可归类为功能行为验证。
allowed-tools: []
task-mode: workflow
workflow-entry: scripts/run.py
status-aliases:
  - 功能测试
  - 功能复测
---
# Functest Workflow Type

## 定位

- `functest` 用于生成“功能测试目标（target）”。
- controller 负责确定：本轮测什么、围绕什么测、重点朝哪个方向测。
- 该 type 命中后会直接进入 workflow，不再交给 executor agent loop。

## 场景步骤模板

1. 明确对象的直接功能测试：直接 `generate_task(functest)`。
2. 带关注点的功能测试：把用户显式关注点写入 `task_content`。
3. 基于失败点复测：可使用 `previous_failed_track {}` 补全事实后 `generate_task(functest)`。
4. 对象不明确：必要时 `build_context_view` 后再生成任务。

## 生成原则

- `task_content` 是当前任务 target，不是完整执行配置。
- 写清测试对象、本轮目标、必要关注方向。
- 对“对象明确、任务类型明确”的请求，不得默认继续 observe。

## Workflow I/O

- 入口：`scripts/run.py`
- 调用：`run(*, task_content: str) -> dict`
- 返回：`{"task_status": "done|failed", "task_result": "..."}`
