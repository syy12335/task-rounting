# Post-Training Scripts

这个目录放 controller 后训练相关入口，和 `notebooks/sglang_model_eval.ipynb` 这类模型评测 notebook 分开。

当前入口：

- `controller_post_training_run.ipynb`：Jupyter 版 runbook，按 `prepare_round -> SFT -> GRPO -> evaluate -> annotate_queue` 顺序跑。

默认配置统一读取 `src/task_router_graph_train/configs/controller_grpo_online.yaml`。notebook 只作为执行入口，不维护第二份训练配置。
其中 `sft.lora_*` 控制 SFT adapter 训练，`model.lora_*` 控制 GRPO/verl 更新；当前 SGLang direct update 默认使用 `model.lora_rank=0`。
GRPO full update 会实时打印关键阶段、heartbeat 和 `critic/score/mean` 等 step 指标；完整 stdout/stderr 仍写在对应 round 的 `verl_stdout.log`、`verl_stderr.log`。

默认长任务都有开关，优先改 `controller_grpo_online.yaml` 里的 `run` 段。本机模型路径可以直接设置环境变量：

```bash
export BASE_MODEL=/path/to/base_model
```

如果要使用另一份配置：

```bash
export POST_TRAINING_RUN_CONFIG=/path/to/controller_grpo_online.yaml
```
