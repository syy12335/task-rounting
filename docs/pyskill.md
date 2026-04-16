# PySkill 机制说明（实现对齐版）

本文档描述 **当前已实现** 的 PySkill 运行机制，并标注与早期设计稿相比尚未落地的能力（TODO）。

## 1. 当前定位

- PySkill 是 `executor` task 的一种执行形态，不是新的路由 task type。
- `task.type` 仍保持现有语义（`executor/functest/accutest/perftest` 等）。
- PySkill 的目标是把长耗时执行从主链路中拆开，并通过 Environment 维持可观测、可回填、可收敛。

### 关系说明（避免概念混淆）

- 主 graph 本体：`src/task_router_graph/graph.py`，负责编排、回收、回填、reply。
- pyskill：主 graph 下的异步触发与回填机制（dispatch/collect/link），不是独立 graph 本体。
- worker graph：具体 skill 的执行流程（例如 `time_range_info worker graph`），由被派发的脚本内部实现。

## 2. 已落地能力（设计亮点）

1. **协议化接入**
- `SKILL.md` 支持 `skill-mode: sync|pyskill`（默认 `sync`）。
- `skill-mode=pyskill` 时强校验：
  - `allowed-tools` 必须且仅 1 个。
  - 工具脚本必须是 `.py` 入口。

2. **非阻塞派发**
- `skill_tool` 在 pyskill 模式下使用 `Popen` 后台启动，不阻塞 executor。
- 返回结构化 dispatch 信息（含 `run_id/pid/accepted`）。

3. **运行态可见**
- source task 立即进入 `running`，`result=正在执行`。
- source task `content` 追加运行引用：`[pyskill pid=... run_id=...]`。

4. **pre-reply 收敛守门**
- Graph 在进入 `final_reply` 前必经 `pre_reply_collect`。
- 该节点会优先执行回收与状态收敛，避免“回复前状态仍陈旧”。

5. **run_id 幂等回填**
- 回填前按 `run_id` 检查终态是否已落地。
- 防止重复追加多个 `pyskill_task`（多入口回收/竞态下仍只回填一次）。

6. **超时与死进程兜底**
- 支持 `runtime.pyskill_timeout_sec` 超时判定。
- 进程已死或句柄丢失时，自动 failed 收敛。
- Linux/posix 下使用进程组终止（`start_new_session + killpg`）降低子进程残留。

7. **重启后 running 收敛**
- 启动时会扫描历史 `running` 的 pyskill source task。
- 默认策略是 failed 收敛，避免任务长期悬挂。

8. **样板能力验证**
- `time_range_info` 已改造为 `pyskill` 样板。
- worker 脚本内使用 `langgraph` 运行最小 workflow（`validate -> fetch -> parse -> build`）。

## 3. 运行机制（按阶段）

### 阶段 A：dispatch

- executor 命中 `skill-mode=pyskill` skill。
- runtime 派发后台进程，返回 `run_id/pid`。
- 当前 task 进入 `running` 并落 `dispatch_pyskill` 轨迹。

### 阶段 B：source 绑定

- `update` 阶段把 `run_id` 绑定到 source task（`round_id/task_id`）。
- 这一步保证后续回填能精确回链到源任务。

### 阶段 C：回收与收敛

回收入口有两处，语义一致：
- `collect_workflows`（每轮开头）
- `pre_reply_collect`（每轮 reply 前）

回收结果：
- 成功：新增 `pyskill_task(status=done)`，并回链 source 为 `done`。
- 失败：新增 `pyskill_task(status=failed)`，并回链 source 为 `failed`。
- source `result` 会指向 `pyskill_task(round_id=..., task_id=...)`。

### 阶段 D：状态追问

- 用户追问“现在怎么样”时，Graph 可基于回收结果与 `running` 列表生成快捷汇总任务。

## 4. Track 事件（当前口径）

当前稳定事件：
- `dispatch_pyskill`
- `workflow_complete`
- `workflow_fail`
- `link_pyskill_result`

关键字段：
- `run_id`：业务唯一标识，作为幂等键。
- `pid`：观测辅助字段，不参与幂等判定。

## 5. 结果解析口径（当前实现）

- 优先从 worker `stdout` 的**最后一行 JSON**解析 `task_status/task_result`。
- 若无法解析，降级使用 `exit_code + stdout/stderr` 形成结果。
- `run_id` 始终作为回填与追踪主键。

## 6. 与设计稿对照：TODO

以下是设计稿中提出、但当前仍未完全落地的亮点：

1. **细粒度进度事件**
- 仍缺少统一的 `heartbeat/workflow_step/sub-agent` 事件写入规范与默认实现。

2. **Environment 通用终态接口**
- 目前终态回填集中在 graph 层，尚未抽象成 `finalize_running_task(...)` 一类的统一 Environment API。

3. **进度可视化增强**
- `build_context_view/show_environment` 尚未专门突出“最近一次 heartbeat/step”。

4. **跨实例恢复执行**
- 目前重启策略是“默认 failed 收敛”，尚未实现“重启后继续执行”的恢复能力。

5. **结果协议进一步标准化**
- 当前是“最后一行 JSON + 降级文本”策略，后续可升级为固定结果文件/IPC 协议。

## 7. 结论

当前 PySkill 已完成“可用闭环”：
- 可派发（非阻塞）
- 可观测（running + run_id/pid）
- 可收敛（pre-reply + 幂等回填）
- 可兜底（超时/死进程/重启）

下一阶段重点应放在“细粒度进度轨迹 + 可视化 + 恢复执行”这三项增强能力。
