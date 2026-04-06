# Perftest Task Reference

## Definition

`perftest` 用于延迟、吞吐、并发、压测等性能评估。

## Common Scenarios

- 执行性能测试
- 测量延迟
- 执行压测
- 查看吞吐与 p95

## Minimal Information Requirements

在生成 `perftest` task 前，controller 至少应明确：

1. 测试对象是什么
2. 相关性能维度是什么
3. 当前请求是执行性能评估，而不是解释历史结果

## What to Observe First When Information Is Insufficient

优先级：

1. `perftest-task.md` 本身
2. 最近一次 perftest 结果
3. 当前目标对象的性能相关上下文

## When It Is Safe to Generate Task

仅当以下条件成立时生成 `perftest` task：

- 当前请求是性能测试
- 测试对象已明确
- 核心性能指标或维度已明确

## Task Content Patterns

Preferred patterns：

- 针对目标执行性能测试，重点关注延迟、吞吐与并发
- 对当前接口执行压测，重点检查 p95 与 qps
- 执行性能评估并生成核心指标摘要
