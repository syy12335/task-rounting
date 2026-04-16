# 评测规范（训练前锁口径）

本规范用于 `data/mock` 的离线评测。目标是保证训练前后可同口径比较。

## 1. 评测对象

- Phase A：`data/mock/phase_a_100/`
- Phase B：`data/mock/phase_b_1k/`（Phase A 通过后启用）

输入文件：

- `scenarios.jsonl`
- `snapshots.jsonl`
- `labels.jsonl`
- `manifest.json`

## 2. 字段约束

每条样本最小字段（必须）：

- `sample_id`：字符串，唯一。
- `scenario_id`：字符串，对应 `scenarios.jsonl`。
- `seed`：整数或数字字符串。
- `environment_snapshot_id`：字符串，对应 `snapshots.jsonl`。
- `error_code`：`E1_ENV_LOOP_READ|E2_STATUS_REPLY_MISMATCH|E3_ENV_FACT_IGNORED|E4_STEP_EXHAUST_NO_TOOL`。
- `expected_action`：字符串，描述期望执行动作。

## 3. 指标定义

### 3.1 流程可靠性

1. `required_tool_call_rate`
- 定义：应触发关键工具调用的样本中，实际触发比例。
- 公式：`hit_required_tool / total_required_tool_samples`

2. `max_steps_exhausted_rate`
- 定义：执行达到步数上限并以该原因失败的比例。
- 公式：`step_exhausted_failures / total_samples`

3. `deadloop_read_rate`
- 定义：发生“重复 read 同一路径且未推进关键动作”的比例。
- 公式：`deadloop_read_samples / total_samples`

4. `dispatch_success_rate`
- 定义：应 dispatch 的样本中，dispatch 成功比例。
- 公式：`dispatch_success / total_dispatch_required`

### 3.2 状态一致性

1. `status_text_mismatch_rate`
- 定义：任务状态与回复语义冲突比例（重点关注 running vs failed 口吻冲突）。
- 公式：`status_reply_mismatch / total_samples`

2. `running_progress_reply_rate`
- 定义：`status=running` 且回复为进度型文案比例。
- 公式：`running_with_progress_reply / total_running_samples`

### 3.3 文本质量（离线）

1. `grounded_reply_score`
- 范围：0~1。
- 计算：基于结果字段与回复的事实对齐规则打分。

2. `conciseness_score`
- 范围：0~1。
- 计算：按冗余程度与目标长度窗评分。

## 4. 统计口径

1. 默认输出：
- `mean`
- `p50/p90`
- `95% CI`（bootstrap）

2. 稳定性判定（Phase B）：
- 同一数据集多次回放，关键比率类指标绝对波动 <= 2.0 个百分点。

## 5. 采样与复现

1. 复现主键：`sample_id + seed + environment_snapshot_id`。
2. 每次评测必须记录：
- `dataset_version`
- `evaluation_time`
- `runner_version`

## 6. 通过阈值（本轮门禁）

### Phase A（100条）

1. 可解析率 = 100%
2. 复放成功率 >= 99%
3. E1~E4 覆盖率 = 100%

### Phase B（1K+）

1. 字段兼容率 = 100%（相对 Phase A）
2. 统计波动满足稳定性判定
3. 可直接用于后续 SFT/GRPO 样本构建

## 7. 输出建议

评测输出建议至少包含：

1. `metrics_summary.json`
2. `metrics_by_error_code.json`
3. `run_manifest.json`
