# task_router_graph_train

`task_router_graph_train` 是 `task_router_graph` 的训练与离线评测模块，不是产品运行模块。

它当前承接的是训练侧骨架，而不是完整训练引擎：已经有运行时输入适配、样本清洗、holdout 构建、reward spec 和离线 evaluator；还没有真正可执行的 `train/`、`train_sft`、`train_rl` 和训练样本生成流水线。

## 当前有什么

- `runtime_adapter.py`
  - 负责把正式 runtime `Environment` 适配成训练态输入
  - 提供 `build_controller_state_input(...)`
  - 提供 `build_reply_state_input(...)`
- `dataset/`
  - 负责 `environment` 清洗、`verifier_sidecar` 剥离和 holdout 构建
- `eval/`
  - 负责离线评测与指标汇总
- `reward_specs/`
  - 提供 `controller_v1`、`reply_v1`、`graph_eval_v1`、`executor_guardrail_v1`
- `assets/`
  - 存放样本源、holdout、reward spec 和默认 reports 目录
- `configs/`
  - 存放课程顺序、配比和门禁阈值

## 当前没有什么

- 没有 `train/` 目录
- 没有 `train_sft.py`
- 没有 `train_rl.py`
- 没有 `controller/reply` 训练样本生成器
- 没有 optimizer、checkpoint 和恢复训练逻辑

当前真正打通的是：

- `k20_manual -> sanitized holdout -> graph_eval evaluator`

还没有打通的是：

- `controller/reply` 的训练数据与训练闭环

## docs 导航

训练模块的正式文档都在 `src/task_router_graph_train/docs/`。

- `overview.md`
  - 模块定位、边界、目录结构和当前命令入口
- `data_contract.md`
  - 训练 record 契约、formal environment 约束和输入形状
- `eval_spec.md`
  - 四榜评测口径、反作弊门禁和通过阈值
- `training_plan_v1.md`
  - RL v1 的正式训练路线、v1 范围和学习/实现分层

建议阅读顺序：`overview.md -> data_contract.md -> eval_spec.md -> training_plan_v1.md`。

## 学习材料

面向个人学习和逐步实验的 notebook 不放在正式 docs 中，而是放在仓库根下的 `.private/task_router_graph_train/`。

- `.private/task_router_graph_train/README.md`
  - notebook 学习顺序和启动方式
- `.private/task_router_graph_train/notebooks/`
  - `01` 到 `06` 的 RL v1 学习路径
- `.private/task_router_graph_train/notes/`
  - 个人笔记、踩坑记录和实验观察

## 当前怎么跑

构建模块内资产：

```bash
cd /root/WORK/task-rounting
PYTHONPATH=src python3 -m task_router_graph_train.cli.build_assets
```

跑离线评测：

```bash
cd /root/WORK/task-rounting
PYTHONPATH=src python3 -m task_router_graph_train.cli.evaluate \
  --predictions src/task_router_graph_train/assets/rl_v1/holdout/k20_manual_records.jsonl
```

默认输出目录：`src/task_router_graph_train/assets/rl_v1/reports/latest/`

## 当前测试

- `tests/test_task_router_graph_train_dataset.py`
- `tests/test_task_router_graph_train_evaluator.py`
- `tests/test_task_router_graph_train_structure.py`
