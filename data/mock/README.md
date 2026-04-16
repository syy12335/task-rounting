# Mock Dataset

用于后训练前评测与验收的数据目录。

## 目录

- `phase_a_100/`: Phase A 验收集（已生成，100条）
- `phase_b_1k/`: Phase B 扩容集（模板已建，待 Phase A 通过后生成）

## 统一字段

每条样本必须包含：

- `sample_id`
- `scenario_id`
- `seed`
- `environment_snapshot_id`
- `error_code`
- `expected_action`

## 说明

- 复放主键：`sample_id + seed + environment_snapshot_id`
- 当前 schema：`mock_eval_v1`
