---
name: accutest
description: 生成 accutest workflow 任务，面向精度、质量、评分、效果评估场景。
when_to_use: 用户请求执行精度测试、质量评估、评分评测；且目标是执行评估而非解释历史结果。
allowed-tools: []
task-mode: workflow
workflow-entry: scripts/run.py
status-aliases:
  - 精度测试
  - 准确率
  - 质量评估
  - 评分
---
# Accutest Workflow Type

定位：`accutest` 用于精度、质量、评分、效果评估。

## 常见情况

- 做一次精度测试
- 评估这版输出质量
- 给这个结果打分
- 看一下模型效果

## 路由边界

- 若用户要“解释上一轮 accutest 含义”，通常应路由到 `executor`。
- 若用户要“执行评估”，应路由到 `accutest`。

## task_content 生成要点

- 明确评估对象
- 明确核心评估维度（准确性/质量/评分）
- 用简洁可执行语言描述本轮评估目标

## Workflow I/O

- 入口：`scripts/run.py`
- 调用：`run(*, task_content: str) -> dict`
- 返回：`{"task_status": "done|failed", "task_result": "..."}`
