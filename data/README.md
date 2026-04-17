# Data Directory

本目录只保留项目级共享数据与历史归档。

## 当前主目录

- `archive_legacy/`: 历史数据归档（可回溯，不参与当前主评测）

## 约定

1. 历史目录 `cases/environments/rl/mock` 已迁移到 `archive_legacy`。
2. 运行过程输出仍写入 `var/runs`。
3. 训练模块相关样本、holdout、reward spec 与评测输出已迁入 `src/task_router_graph_train/assets/`。
