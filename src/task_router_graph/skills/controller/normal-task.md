# Normal Task Reference

## Definition

`normal` 用于解释、总结、查阅、指导和持续回应类任务。
它不用于重新执行测试或评估。

## Common Scenarios

- 解释最近一次测试结果
- 总结最近几轮任务输出
- 查阅历史报告并提炼结论
- 提供使用指导
- 基于现有上下文继续回答

## Minimal Information Requirements

在生成 `normal` task 前，controller 至少应明确：

1. 当前目标是解释、总结、查阅还是指导
2. 回复所依赖的核心上下文
3. 若是历史追问，至少具备最近一次相关任务结果摘要

## What to Observe First When Information Is Insufficient

优先级：

1. 最近一次相关任务结果
2. 最近一次相关报告或输出文件
3. 相关历史轮次

## When It Is Safe to Generate Task

仅当以下条件成立时生成 `normal` task：

- 任务目标已明确为解释/总结/查阅/指导之一
- 已有足够历史事实支撑回复
- 不再缺少关键文件或关键结果

## Task Content Patterns

Preferred patterns：

- 总结最近一次 functest 失败原因
- 总结 recent rounds 的关键信息
- 解释最近一次 accutest 的核心结论
- 基于现有上下文提供使用指导

Disallowed patterns：

- answer the user
- take a look and decide later
- analyze this task
- handle this task
