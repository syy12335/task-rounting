# Accutest Task Reference

## Definition

`accutest` 用于准确性、质量、评分与效果评估。

## Common Scenarios

- 执行一次准确性测试
- 评估输出质量
- 对结果打分
- 检查模型表现

## Minimal Information Requirements

在生成 `accutest` task 前，controller 至少应明确：

1. 评估对象是什么
2. 关注维度是准确性、质量还是评分
3. 当前请求是执行评估，而不是解释历史结果

## What to Observe First When Information Is Insufficient

优先级：

1. `accutest-task.md` 本身
2. 最近一次 accutest 或相关评估结果
3. 与评估对象相关的输入/输出材料

## When It Is Safe to Generate Task

仅当以下条件成立时生成 `accutest` task：

- 当前目标是执行评估
- 评估对象已明确
- 核心评估维度已明确

## Task Content Patterns

Preferred patterns：

- 针对当前对象执行准确性评估，重点关注回答质量与评分
- 对目标输出执行质量评估，重点检查准确性与整体效果
- 执行准确性测试并生成质量评分摘要
