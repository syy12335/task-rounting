# Task Router Train Assets

本目录存放训练模块自己的资产，不是项目根数据目录。

## 子目录

- `eval_samples/`: 人工维护的样本源
- `rl_v1/holdout/`: 清洗后的正式 holdout
- `rl_v1/reward_specs/`: 程序化奖励配置
- `rl_v1/reports/`: 默认评测输出目录

## 生成命令

```bash
PYTHONPATH=src python -m task_router_graph_train.cli.build_assets
```
