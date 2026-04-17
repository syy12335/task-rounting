# Controller SFT v1 Assets

本目录存放 `controller SFT` 的最小可运行资产。

## 目录

- `teacher_source/`
  - 手工编写的小份 teacher bootstrap 样本
- `records/`
  - `build_sft_assets` 生成的标准 `TrainingRecord`
- `examples/`
  - `build_sft_assets` 生成的 SFT `prompt -> target_text` 样本

## 使用顺序

1. 先维护 `teacher_source/`
2. 再运行：

```bash
PYTHONPATH=src python -m task_router_graph_train.cli.build_sft_assets
```

3. 然后再运行：

```bash
PYTHONPATH=src python -m task_router_graph_train.cli.train_sft \
  --model-name-or-path <your-model> \
  --lora-target-modules q_proj v_proj
```
