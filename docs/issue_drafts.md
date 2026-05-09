# Issue Drafts

来源：`docs/pyskill.md` 第 6 节 TODO。

## 1. 统一细粒度进度事件协议

**标题**
`feat(pyskill): 统一 heartbeat / workflow_step / sub-agent 进度事件`

**背景**
当前稳定事件只有 `dispatch_pyskill`、`workflow_complete`、`workflow_fail`、`link_pyskill_result`，缺少统一的细粒度进度写入口径。

**范围**
- 定义 `heartbeat`、`workflow_step`、`sub-agent` 事件 schema。
- 在默认实现中写入这些事件。
- 保持 `track` 结构兼容现有读取链路。
- 同步更新相关文档和示例。

**验收**
- 长任务能稳定产出进度事件。
- `track` 中可以看到最近一次 heartbeat / step。
- 旧有事件继续可用，不破坏现有回放。

## 2. 抽象 Environment 通用终态接口

**标题**
`refactor(environment): 提供 finalize_running_task 统一终态回填 API`

**背景**
当前终态回填逻辑集中在 graph 层，缺少统一的 Environment API，导致回收、失败收敛、异步回填的路径分散。

**范围**
- 在 Environment 层抽象终态回填接口。
- 将 graph 层的终态处理收敛到该接口。
- 保证幂等回填语义不变。
- 维持现有 task / track / result 结构。

**验收**
- 所有终态回填走统一入口。
- 逻辑不再散落在多个 graph 节点里。
- 现有流程回归通过。

## 3. 支持重启后继续执行

**标题**
`feat(pyskill): 支持跨实例恢复运行中的任务`

**背景**
当前重启策略是默认 failed 收敛，历史 running 任务不会继续执行。

**范围**
- 识别可恢复的 running 任务。
- 恢复后继续回收或继续执行未完成任务。
- 对不可恢复任务保留失败收敛兜底。
- 记录恢复过程的 track / 状态变化。

**验收**
- 模拟重启后，运行中的任务可以继续推进。
- 无法恢复的任务仍能安全收敛。
- 不会出现长期悬挂的 running 状态。

## 暂不拆分

以下两项建议先留在设计稿里，等前面基础能力落地后再单独拆：
- 进度可视化增强
- 结果协议进一步标准化

