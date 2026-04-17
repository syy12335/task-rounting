# RL v1 训练方案

## 目标

本期目标不是“让模型更会回答”，而是让模型稳定读懂正式 `environment/task/round/track` 机制，并在 `controller/reply` 两个角色上做出正确动作与状态语义。

## 为什么要拆训练和运行

1. 运行时包应该只承载产品执行逻辑。
2. RL 方案仍然可能继续演进，不应该把实验性 contract、holdout、verifier 直接打进运行时包。
3. 训练侧需要更快迭代样本、reward 和评测口径，而运行时语义需要保持稳定。

## v1 训练路线

采用 `离线 RL 优先`：

1. `Stage 0` 数据清洗：统一成正式 environment + verifier sidecar
2. `Stage 1` SFT warm start：先拉到可优化区间
3. `Stage 2` controller batch RL：`1-3 step micro-episode`
4. `Stage 3` reply batch RL：contextual bandit

本期不做：

- 在线 RL
- reward model
- 全链路 PPO
- executor RL

## 角色边界

### 进入 RL

- `controller`
- `reply`

### 只评测不进 RL

- `graph_deterministic`
- `executor_guardrail`

这些部分仍然重要，但它们是确定性机制或 guardrail，不应在 v1 里交给 RL 学。

## 奖励设计

程序化 reward 落在：

- `assets/rl_v1/reward_specs/controller_v1.json`
- `assets/rl_v1/reward_specs/reply_v1.json`
- `assets/rl_v1/reward_specs/graph_eval_v1.json`
- `assets/rl_v1/reward_specs/executor_guardrail_v1.json`

controller 关注：

- schema 合法
- 动作类型正确
- 工具或 task 类型正确
- 正式 environment 事实使用
- observe 预算合理
- 最终 next action 等价

reply 关注：

- 状态语义正确
- source task / pyskill_task 链接解析
- grounded reply
- 幻觉率

## 课程顺序

固定顺序：

1. `P0` 状态机理解
2. `P1` 失败重试 / 异步回填
3. `P2` 长历史与压缩视图稳健性

详细配比和阈值在 `configs/curriculum_v1.json`。
