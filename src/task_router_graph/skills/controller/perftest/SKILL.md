---
name: perftest
description: 生成 perftest workflow 任务，面向延迟、吞吐、并发和压测评估。
when_to_use: 用户请求性能测试、压测、延迟吞吐指标评估，且目标是执行性能评估。
allowed-tools: []
task-mode: workflow
workflow-entry: scripts/run.py
status-aliases:
  - 性能测试
  - 压测
  - 延迟
  - 吞吐
---
# Perftest Workflow Type

定位：`perftest` 用于延迟、吞吐、并发、压测等性能评估。

## 常见情况

- 做一次性能测试
- 测一下延迟
- 跑压测
- 看吞吐和 p95

## 生成原则

- 明确测试对象
- 明确核心性能维度或指标（如 p95、qps、并发）
- 若信息不足，可先 `build_context_view` 补全再生成任务

## task_content 写法

推荐：

- 针对目标对象执行性能测试，重点关注延迟、吞吐与并发表现
- 对当前接口执行压测，重点检查 p95 与 qps
- 执行性能评估，生成核心指标摘要

## Workflow I/O

- 入口：`scripts/run.py`
- 调用：`run(*, task_content: str) -> dict`
- 返回：`{"task_status": "done|failed", "task_result": "..."}`
