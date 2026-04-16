# Data Directory

本项目开发与评测数据统一放在 `data/`。

## 当前主目录

- `eval_samples/`: 后训练评测主入口（统一样本口径，不区分 mock/real）
- `archive_legacy/`: 历史数据归档（可回溯，不参与当前主评测）

## 约定

1. 新评测样本统一写入 `data/eval_samples`。
2. 历史目录 `cases/environments/rl/mock` 已迁移到 `archive_legacy`。
3. 运行过程输出仍写入 `var/runs`。
