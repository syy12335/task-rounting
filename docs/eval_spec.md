# 评测规范（统一样本口径）

本规范用于评估“模型是否读懂 environment/task 机制”。

## 1. 评测对象

- 首批：`data/eval_samples/k20_manual`
- 扩展：`data/eval_samples/kN_expand`（后续阶段）

不区分 mock/real，统一按样本字段契约执行。

## 2. 字段契约

每条样本必填：

- `sample_id`
- `scenario_id`
- `seed`
- `environment_snapshot_id`
- `error_code`
- `expected_action`

扩展字段：

- `run_id`
- `round_id`
- `task_id`
- `decision_step`
- `gold_outcome`

## 3. 指标定义

机制理解（核心）：

1. `env_fact_ignored_rate`
2. `status_text_mismatch_rate`
3. `next_action_accuracy`

执行推进：

1. `required_tool_call_rate`
2. `step_exhausted_without_tool_rate`
3. `deadloop_read_rate`

质量（次级）：

1. `grounded_reply_score`
2. `conciseness_score`

说明：质量指标只有在机制指标不退化时才解释。

## 4. 统计口径

输出至少包含：

- `mean`
- `p50/p90`
- `95% CI`（bootstrap）

## 5. 通过阈值（k20_manual）

1. 可解析率 = 100%
2. 字段完整率 = 100%
3. `sample_id` 唯一性 = 100%
4. E1~E4 覆盖率 = 100%

## 6. 输出产物

建议输出：

1. `metrics_summary.json`
2. `metrics_by_error_code.json`
3. `run_manifest.json`
4. `evidence_samples.jsonl`
