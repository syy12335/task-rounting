# task_router_graph_train

`task_router_graph_train` 负责 controller-only 的后训练链路。

当前已实现链路：`manual_protocol_v1 -> SFT warm start -> GRPO -> teacher_queue -> annotate_queue -> preference_admissions -> DPO -> next GRPO ...`

## 已实现链路

1. `manual_protocol_v1`
2. `SFT warm start`
3. `GRPO`
4. `badcase -> teacher_queue -> annotate_queue -> preference_admissions`
5. `DPO`

## 主线约定

- 唯一基础真源：`src/task_router_graph_train/assets/manual_protocol_v1/`
- SFT 数据只来自：`manual_protocol_v1.sft`
- 当前轮次 GRPO 数据：仅来自 `manual_protocol_v1.sft` 派生的 `controller_records_*`
- `holdout` 固定从 `manual_protocol_v1.split=holdout` 派生，且不进入训练
- round 资产目录：`src/task_router_graph_train/assets/post_training/rounds/<round_id>/`
- `preference_admissions` 保存 DPO 可消费的 `prompt / chosen / rejected` 证据；原始 badcase 不直接给 DPO 消费

## CLI

- `python -m task_router_graph_train.cli.prepare_round --round-id round_0001`
- `python -m task_router_graph_train.cli.train_sft --model-name-or-path ... --lora-target-modules ...`（只用于最早 warm start）
- `python -m task_router_graph_train.cli.train_grpo --config src/task_router_graph_train/configs/controller_grpo_online.yaml`
- `python -m task_router_graph_train.cli.evaluate --predictions path/to/predictions.jsonl`
- `python -m task_router_graph_train.cli.annotate_queue --round-id round_0001`
- `python -m task_router_graph_train.cli.train_dpo --model-name-or-path path/to/grpo/checkpoint`

`annotate_queue` 生成 `teacher_decisions` 和 `preference_admissions`。teacher 接纳 badcase 时必须同时生成 gold case；当前 policy bad output 作为 rejected 保留 raw text 和 parsed action。

## Docs

- `docs/overview.md`
- `docs/data_contract.md`
- `docs/post_training_v1.md`
- `docs/grpo_dpo_loop_v1.md`（GRPO / DPO 下一阶段方案）
- `docs/controller_grpo_reward_spec.md`
- `docs/manual_protocol_v1_draft.md`（手稿，不作为主线入口）
