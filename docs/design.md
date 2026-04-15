# 设计说明

## 文档导航

- Environment 设计：`docs/environment.md`
- 数据格式：`docs/data_format.md`

说明：实现以 `src/task_router_graph/` 代码为准；文档用于约束语义口径与对齐协作。

## Graph 主流程（最新）

`init -> route -> (normal|functest|accutest|perftest) -> update -> (failure_diagnose | route | final_reply) -> end`

关键分支规则：

1. `task.status == done`：进入 `final_reply`，然后结束。
2. `task.status == failed` 且 `failed_retry_count <= max_failed_retries`（默认 3）：进入 `failure_diagnose`，再回 `route` 重试。
3. `task.status == failed` 且超过重试上限：进入 `final_reply`，然后结束。
4. 达到 `max_task_turns`：进入 `final_reply`，然后结束。

## 节点职责

### init

- 创建新 round（`Environment.start_round(user_input=...)`）
- 初始化 graph 运行状态（`run_id/task_turn/failed_retry_count`）

### route（controller）

- 只负责：`observe` / `generate_task`
- 输出：`Task + controller_trace`
- 观察工具含：`build_observation_view`、`previous_failed_track` 等

### execute（normal/functest/accutest/perftest）

- Execute nodes only run the task and do not compose final user-facing reply.
- Unified output semantics: update only `task_status` and `task_result`.
- Mock test async workflows (`functest` / `accutest` / `perftest`) include a placeholder `sleep` to simulate long-running workflow execution.
- Mock delay is fixed to `5` seconds for now.
- This `sleep` is intentionally a placeholder. Replace logic in `src/task_router_graph/agents/async_workflows/*_async_workflow.py` with your own workflow executor.
### update

- 持久化当前 task 到 environment（`add_task`）
- 写入 `track`（controller 多步路由 loop + executor agentic loop + test async workflows）
- 更新 `failed_retry_count`

### failure_diagnose

- 触发条件：failed 且仍允许重试
- 输入：上一失败 task + 完整失败 track
- 行为：给出失败分析，回写 `task.result`，并写入 `diagnoser` 轨迹

### final_reply（reply agent）

- 只在 round 结束时触发
- 输入：`user_input + final_task + environment observation view(include_trace=false)`
- 输出：最终 `output.reply`
- 额外写入 `track`：`agent=reply,event=compose`

## 关键语义口径

1. `task_result` 归执行链负责（normal/test/diagnoser）。
2. `output.reply` 归 `reply agent` 负责（round 结束统一生成）。
3. `TaskRecord.reply` 是执行阶段回执字段；当前可为空字符串，不等同最终用户回复。
4. `track` 是统一轨迹字段，不再使用 `controller_trace` 作为持久化主字段。
5. 每个关键轨迹步骤可带 `return`，用于记录该步骤返回值。

## 失败重试与纠偏

1. 第一次失败：进入 `failure_diagnose`，分析失败原因并回 route。
2. 后续失败：重复上述流程，直到超过 `max_failed_retries`。
3. 超限后不再路由重试，直接进入 `final_reply` 对用户收敛输出。

## CLI 入口

- `scripts/run/run_cli.py`：标准 CLI
- `scripts/run/run_cli_show.py`：同流程，但每轮结束额外打印 `show_environment(show_trace=True)`

