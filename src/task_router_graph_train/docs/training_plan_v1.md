# RL v1 训练方案

## 目标

本期目标不是把完整训练引擎一次性做完，而是把 `controller-only` 的 RL v1 路线定义清楚，并和现有 harness / evaluator 边界对齐。

v1 只解决一件事：

- 让模型稳定读懂正式 `environment/task/round/track` 机制
- 在 `controller` 角色上输出结构化、可校验、环境事实对齐的下一步动作

## 模块边界

正式训练与评测真源继续放在 `src/task_router_graph_train/`。

- `docs/`
  - 对团队有效的正式设计文档
- `dataset/`
  - 正式训练样本与 holdout 的构建逻辑
- `reward_specs/`
  - 程序化奖励与评测口径
- `cli/`
  - 可重复执行的正式命令入口

个人学习与实验材料不放在正式 docs 中，而是放在仓库根下的 `.private/task_router_graph_train/`。

## v1 范围

进入 v1 训练：

- `controller`

本期不进入训练：

- `reply`
- `graph_deterministic`
- `executor_guardrail`
- 在线 RL
- reward model
- PPO / GRPO / 全链路 graph policy 优化

## 训练路线

固定为两阶段：

1. `SFT warm start`
   - 把 controller 拉到可优化区间
   - 重点先解决 JSON schema、动作类别和环境事实引用
2. `offline RL`
   - 对同一 state 采样多个候选动作
   - 用 `controller_v1` 程序化奖励打分
   - 用 reward-weighted policy improvement 做小步更新

本期 episode 语义固定为：

- `1-3 step micro-episode`

本期训练输入固定使用：

- `build_controller_state_input(...)`

本期默认动作空间固定为：

- `observe`
- `generate_task`

## 奖励与门禁

controller 奖励继续使用：

- `assets/rl_v1/reward_specs/controller_v1.json`

重点关注的程序化项：

- `schema_valid`
- `action_kind_correct`
- `tool_or_task_type_correct`
- `formal_env_fact_used`
- `observe_budget_ok`
- `next_action_equivalent`
- `repeated_observe`
- `sidecar_leak`
- `hallucinated_fact`

阶段门禁与正式评测口径继续以：

- `docs/eval_spec.md`
- `configs/curriculum_v1.json`

为准。

## 学习与实现分层

学习与引导采用 notebook-first：

- `.private/task_router_graph_train/README.md`
- `.private/task_router_graph_train/notebooks/`
- `.private/task_router_graph_train/notes/`

正式实现沉淀顺序固定为：

1. 先在 notebook 中把数据、reward、offline RL 流程走通
2. 再把稳定逻辑沉淀到 `dataset/`、训练模块和 `cli/`
3. 最终用现有 evaluator 和 holdout 做门禁

## 后续正式入口

v1 完整实现后应补齐的正式入口包括：

- `build_controller_train_records(...)`
- `score_controller_action(...)`
- `train_controller_sft(...)`
- `train_controller_rl(...)`
- `evaluate_controller_policy(...)`
