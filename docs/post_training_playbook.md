# 后训练作战手册（验收导向：文档 + Mock 数据）

本文档定义本项目当前后训练落地策略。  
本轮验收只交付两类产物：`docs` 与 `data/mock`，不包含训练脚本与模型权重。

## 1. 目标与边界

核心目标：

1. 先稳定识别“哪里该做后训练”，再进入 SFT/GRPO。
2. 先产出可评测、可复现、可展示的数据闭环。
3. 用分阶段门禁控制数据规模：先 100 条验收，再扩到 1K 左右。

本轮不做：

1. 训练执行与模型发布。
2. 在线服务接入与灰度开关开发。
3. 可视化 dashboard 实装（仅先定义指标与数据口径，下一轮直接接入）。

## 2. 靶点识别（E1~E4）

优先以 `environment` 理解能力为切入口，统一错误模式词典：

- `E1_ENV_LOOP_READ`：重复读取同一 skill 文档，未推进到关键工具调用。
- `E2_STATUS_REPLY_MISMATCH`：`task_status=running` 但 reply 为失败终态口吻。
- `E3_ENV_FACT_IGNORED`：`TASKS_JSON/previous_failed_task` 已有事实却继续“信息不足”循环。
- `E4_STEP_EXHAUST_NO_TOOL`：达到 `max_steps` 失败且未执行必要工具闭环。

每条样本必须标注：

- `sample_id`
- `scenario_id`
- `seed`
- `environment_snapshot_id`
- `error_code`（E1~E4）
- `expected_action`

## 3. Mock 分层设计

### 3.1 I/O Mock

- 固定 web 检索、embedding、外部网络返回。
- 控制延迟、空结果、噪声结果、连接失败等注入。

### 3.2 Policy Mock

- 固定 LLM grader/rewrite 行为模板（同输入同输出）。
- 避免训练前评测被模型随机性污染。

### 3.3 Runtime Mock

- 固定 pyskill dispatch/collect/link 时序。
- 可注入超时、死进程、回填缺失、重试窗口竞态。

## 4. 指标锁定（训练前）

本轮先锁口径，不在训练后改定义。

流程可靠性：

1. `required_tool_call_rate`
2. `max_steps_exhausted_rate`
3. `deadloop_read_rate`
4. `dispatch_success_rate`

状态一致性：

1. `status_text_mismatch_rate`
2. `running_progress_reply_rate`

文本质量（离线）：

1. `grounded_reply_score`
2. `conciseness_score`

详细公式见 [eval_spec.md](/root/WORK/task-rounting/docs/eval_spec.md)。

## 5. 数据门禁：100 -> 1K

### Phase A（先验收 100 条）

目录：`data/mock/phase_a_100/`

通过条件：

1. JSONL 全部可解析。
2. 同 seed 可复放，复放成功率 >= 99%。
3. E1~E4 全覆盖，且每类有有效样本。

### Phase B（Phase A 通过后扩到 1K）

目录：`data/mock/phase_b_1k/`

要求：

1. 字段与 Phase A 完全兼容。
2. 总量 1000~1200。
3. 指标统计波动进入稳定区间（口径见 eval_spec）。

## 6. 面试展示口径

推荐按四步讲清楚：

1. 问题定义：为什么先做“靶点识别”而不是直接训。
2. 数据设计：如何用 mock 三层构造可复现失败场景。
3. 指标基线：训练前先锁公式和阈值，避免“改口径赢指标”。
4. 迭代策略：100 条门禁通过后再扩到 1K，降低试错成本。

## 7. 后续 ToDo

1. 生成静态指标曲线（PNG/SVG）与评测报告。
2. 增加交互式 dashboard（按 error_code/run_id 钻取轨迹）。
3. 接入 SFT/GRPO 训练流水线并复用同一评测集。
