# Environment 设计说明

本文档定义运行时 Environment 的统一结构，代码以 `src/task_router_graph/schema/environment.py` 为准。

## 1. 核心原则

1. Environment 按 round 组织。
2. 一个 round 对应一次用户输入。
3. 一个 round 内可有多个 task（重试会追加新 task）。
4. `cur_round` 是 Environment 正式状态字段。
5. `track` 统一记录 controller 与各执行/诊断/回复 agent 轨迹。
6. observation view 是读取视图，不等于 Environment full state。

## 2. 数据模型

### 2.1 Environment（full state）

- case_id: str（由 graph 落盘时注入）
- rounds: list[RoundRecord]
- cur_round: int
- updated_at: str

### 2.2 RoundRecord

- round_id: int
- user_input: str
- tasks: list[TaskRecord]

### 2.3 TaskRecord

- task_id: int
- track: list[dict]（完整轨迹）
- task: Task
- reply: str（执行阶段回执字段；可为空）

### 2.4 Task

- task_id: int（镜像 TaskRecord.task_id）
- type: str
- content: str
- status: str
- result: str

## 3. Track 约定

### 3.1 controller 步骤（示例）

- observe：
  - `agent=controller`
  - `action_kind=observe`
  - `tool/args/observation/reason`
  - `return`（通常为 `observation` 内容）

- generate_task：
  - `agent=controller`
  - `action_kind=generate_task`
  - `task_type/task_content/reason`
  - `return`（通常为 `{task_type, task_content}`）

### 3.2 执行/诊断/回复步骤（示例）

- `agent=normal|functest|accutest|perftest|diagnoser|reply`
- `event=execute|skip|analyze|compose`
- `task_status/task_result`
- 可选 `reply`（仅 reply 代理或特定步骤）
- 可选 `return`（步骤返回值）

## 4. 写入接口

### start_round(user_input=...)

- 创建新 round，`round_id = max(round_id) + 1`
- 同步更新 `cur_round`

### add_task(round_id=..., track=..., task=..., reply=...)

- 向目标 round 追加 TaskRecord
- `task_id = len(round.tasks) + 1`
- task/track 采用副本写入，避免外部引用污染历史

### annotate_last_failed_task(...)

- 定位“最后一条失败 task”
- 回写失败分析结果（`task.result`）
- 可追加诊断轨迹

### append_last_task_track(track_item=...)

- 向最后一条 task 追加轨迹
- 当前用于 `reply agent` 的 compose 记录

## 5. 读取接口

### to_dict(include_trace=True)

返回 Environment full state：`rounds/cur_round/updated_at`；落盘时额外注入 `case_id`。

### build_observation_view(...)

返回默认 AI 读取视图（可控是否包含 trace）。

### build_controller_input_view(default_task_limit=5)

controller 输入组装：

- 正常：最近 N 条无 trace 任务视图。
- 若最近 task 为 failed：
  - 自动放宽到当前 round 全量无 trace 视图；
  - 仅附 `previous_failed_task` 摘要（不注入失败 track）。

失败 track 若需要，必须通过 `previous_failed_track` 工具显式读取。

### get_previous_failed_track_view()

返回上一失败 task 的完整轨迹视图（用于 controller 失败重试纠偏）。

### show_environment(show_trace=True)

打印可读文本；当 `show_trace=True` 时展示每步 agent/event/reason，并附 `return`（若存在）。

## 6. 常见误区

1. `reply` 字段等于最终用户回复：错误（最终回复来自 `output.reply`）。
2. 失败轨迹默认注入 controller 输入：错误（需工具显式读取）。
3. full state 与 observation view 混用：错误。

