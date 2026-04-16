# 后训练作战手册（统一评测样本口径）

本文档只服务一个核心目标：
让模型真正读懂 `environment / task / round / track` 机制，并做出正确下一步动作。

## 1. 北极星问题

1. 不能稳定读取并复用 `TASKS_JSON/environment` 事实。
2. 不能把 `task.status`（尤其 `running`）映射到正确回复语义。
3. 在重试与异步链路中经常卡在无效循环。

## 2. 训练目标

- P0：状态机理解（running/done/failed 边界、回填关系、状态追问语义）
- P1：执行推进（在步数预算内完成必要工具闭环）
- P2：回复质量（在 P0/P1 稳定后优化）

## 3. 数据口径（不区分 mock/real）

统一使用：`data/eval_samples`

首批验收集：`data/eval_samples/k20_manual`

- 样本为手工编写
- 每条语义不同
- 不使用模板批量灌数据

字段契约：

- 必填：`sample_id, scenario_id, seed, environment_snapshot_id, error_code, expected_action`
- 扩展：`run_id, round_id, task_id, decision_step, gold_outcome`

## 4. 错误模式词典

- `E1_ENV_LOOP_READ`：重复 read，不推进关键动作
- `E2_STATUS_REPLY_MISMATCH`：状态与回复语义冲突
- `E3_ENV_FACT_IGNORED`：忽略 environment 已有事实
- `E4_STEP_EXHAUST_NO_TOOL`：步数耗尽且未完成必要工具调用

## 5. 验收门禁

1. `k20_manual` 三个 JSONL 可逐行解析。
2. `sample_id` 全局唯一。
3. E1~E4 全覆盖。
4. 样本语义不重复，快照结构有明显多样性。

## 6. 历史数据策略

- 过时数据已迁移到 `data/archive_legacy/2026-04`。
- 归档可回溯，但不再作为主评测输入。

## 7. 面试讲述建议

按“问题 -> 证据 -> 修复 -> 指标”四段式讲：

1. 为什么是机制问题而非单纯回答质量问题
2. 如何用样本对准 E1~E4
3. 如何用同口径指标验证修复
4. 如何从 k20 扩展到更大规模集
