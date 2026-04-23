# task_router_graph_train

`task_router_graph_train` 聚焦训练、回流和离线评测；产品运行逻辑保留在 `task_router_graph` 运行时模块中。

最近这轮实现已经把口径收口到一条可执行闭环：

- `teacher_source -> TrainingRecord -> SFT examples -> train_sft`
- `badcase_pool -> build_feedback_assets -> feedback_manifest`
- `feedback_manifest -> train_grpo / evaluate_controller_regression`
- `failed evidence -> harvest_failed_badcases -> next round badcase_pool`

当前主线已经收口到“controller-only 的安全训练输入 + badcase 回流 + 单步 GRPO + regression 验证”。

## 当前能力

- `runtime_adapter.py`
  - 把运行时 `Environment` 适配成训练态输入
  - 提供 `build_controller_state_input(...)` 与 `build_reply_state_input(...)`
- `dataset/`
  - 清洗 `environment`
  - 构造 `TrainingRecord`、`SftExample`
  - 构建 holdout 与最小 SFT 资产
- `feedback.py`
  - 标准化 badcase pool
  - 生成 run-scoped feedback assets
  - 输出 `feedback_manifest.json`
  - 回收 regression 失败样本进入下一轮 badcase pool
- `train/`
  - 提供 `train_controller_sft(...)`
  - 提供 `train_controller_grpo(...)`
  - 当前 GRPO 是 single-step controller，update backend 为 `verl`
- `eval/`
  - 提供 holdout evaluator
  - 提供 `evaluate_controller_regression(...)`
- `artifacts.py`
  - 统一 feedback manifest / asset 解析
  - 收口 repo-relative 的安全路径输出

## 当前关键约定

- 默认安全输入优先使用 `--asset-manifest` 或 `--run-dir`
- 直接传 `--train-examples`、`--eval-examples`、`--train-records`、`--eval-records` 属于 unsafe override，必须显式加 `--allow-unsafe-path-input`
- `feedback_manifest.json` 是 badcase 回流产物的统一入口，不鼓励手动拼 jsonl 路径
- 训练和评测报告中的路径默认会脱敏成 repo-relative 形式，不再输出仓库绝对路径
- 三路 teacher 职责分离：
  - `reward_judge`：给 GRPO rollout candidates 打 scalar reward
  - `reference_generator`：给 badcase 生成 `reference_action`
  - `regression_judge`：独立判断 `prediction` 与 `reference_action` 是否语义等价

## 当前产物类型

- `sft_examples_v1`
  - `train_controller_sft(...)` 默认消费的训练样本
- `controller_training_records_v1`
  - `train_controller_grpo(...)` 默认消费的 controller records
- `controller_regression_records_v1`
  - `evaluate_controller_regression(...)` 默认消费的回流评测样本
- `verl_rl_dataset_v1`
  - 预渲染的 verl RL dataset；`train_controller_grpo(...)` 也可从 manifest 中直接消费
- `feedback_run_v1`
  - 一次 badcase 回流构建的总 manifest

## 现在怎么跑

构建 holdout 与基础资产：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.build_assets
```

从最小 `teacher_source` 生成 controller SFT 记录与 examples：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.build_sft_assets
```

安全方式运行 controller SFT：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.train_sft \
  --model-name-or-path <your-model> \
  --lora-target-modules q_proj v_proj \
  --asset-manifest var/runs/task_router_graph_train/feedback/<run-id>/feedback_manifest.json
```

把标准化 badcase pool 构造成 run-scoped feedback assets：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.build_feedback_assets \
  --badcase-pool var/runs/task_router_graph_train/badcases/normalized.jsonl \
  --output-root var/runs/task_router_graph_train/feedback
```

安全方式运行 controller GRPO：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.train_grpo \
  --config src/task_router_graph_train/configs/controller_grpo_online.yaml \
  --output-dir var/runs/task_router_graph_train/grpo/latest \
  --asset-manifest var/runs/task_router_graph_train/feedback/<run-id>/feedback_manifest.json \
  --model-name-or-path <your-model> \
  --lora-target-modules q_proj v_proj
```

如果只想导出 RL dataset、verl request 和审计产物，不执行 update：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.train_grpo \
  --config src/task_router_graph_train/configs/controller_grpo_online.yaml \
  --output-dir var/runs/task_router_graph_train/grpo/export_only \
  --asset-manifest var/runs/task_router_graph_train/feedback/<run-id>/feedback_manifest.json \
  --model-name-or-path <your-model> \
  --export-only
```

对 badcase 回流样本做 controller regression：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.evaluate_controller_regression \
  --predictions var/runs/task_router_graph_train/predictions/controller.jsonl \
  --asset-manifest var/runs/task_router_graph_train/feedback/<run-id>/feedback_manifest.json
```

把 regression 失败样本收回下一轮 badcase pool：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.harvest_failed_badcases \
  --evidence var/runs/task_router_graph_train/controller_regression/latest/evidence_rows.jsonl \
  --output var/runs/task_router_graph_train/badcases/next_round.jsonl
```

跑固定 holdout 的离线评测：

```bash
cd <repo-root>
PYTHONPATH=src python -m task_router_graph_train.cli.evaluate \
  --predictions src/task_router_graph_train/assets/rl_v1/holdout/k20_manual_records.jsonl
```

## Docs 导航

正式文档在 `src/task_router_graph_train/docs/`：

- `overview.md`
  - 模块定位、闭环总览、主要入口和输出约定
- `data_contract.md`
  - teacher_source、TrainingRecord、feedback manifest 和 badcase 回流契约
- `eval_spec.md`
  - holdout evaluator、controller regression、coverage 面板与失败回流
- `training_plan_v1.md`
  - controller-only v1 训练路线与非目标

学习材料在 `.private/task_router_graph_train/`：

- `.private/task_router_graph_train/README.md`
- `.private/task_router_graph_train/notebooks/`
- `.private/task_router_graph_train/notes/`

## 当前还不做什么

- 不把 `reply` 训练闭环当作当前主线
- 不把多步 / 全轨迹 GRPO 当作当前已承诺实现
- 不把 reward model、critic、checkpoint 恢复训练写成当前版本能力
- 不鼓励直接从散落 jsonl 路径启动训练入口
