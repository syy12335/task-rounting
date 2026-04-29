# 设计说明

## 文档导航

- Skill 机制：`docs/skills.md`
- Skill Runtime 细节：`docs/skills_runtime.md`
- Environment 设计：`docs/environment.md`
- Track 机制：`docs/track.md`
- Agent Memory 与视图压缩：`docs/agent_memory.md`
- 数据格式：`docs/data_format.md`
- 近期更新：`docs/changelog.md`

说明：实现以 `src/task_router_graph/` 代码为准；文档用于对齐语义与协作口径。

## Graph 主流程（2026-04-16，含 PySkill 收敛增强）

```text
init
  -> collect_workflows
  -> (route | update)
  -> (executor | functest | accutest | perftest)
  -> update
  -> (failure_diagnose | route | pre_reply_collect)
  -> final_reply
  -> end
```

关键分支规则：

1. `collect_workflows`：优先回收已完成异步 workflow；命中状态追问时可直接生成汇总 task 并进入 `update`。
2. `task.status == running`：进入 `pre_reply_collect`，先做活跃任务收敛检查，再进入 `final_reply`。
3. `task.status == done`：进入 `final_reply`，本轮收敛结束。
4. `task.status == failed` 且 `failed_retry_count <= max_failed_retries`（默认 3）：进入 `failure_diagnose` 后回 `route`。
5. 失败超限、路由失败或达到 `max_task_turns`：进入 `final_reply`。

## 节点职责

### init

- 创建新 round（`Environment.start_round(user_input=...)`）
- 初始化 graph 运行状态（`run_id/task_turn/failed_retry_count`）

### collect_workflows

- 非阻塞回收完成态 workflow future
- 非阻塞回收 `pyskill` 后台进程完成态
- 对丢失句柄/已死亡的 `running` pyskill 任务做 failed 收敛
- 在当前 round 新增 `pyskill_task`
- 回链源 task：把 source task 改为 `done/failed`，`result` 指向 `pyskill_task(round_id=..., task_id=...)`
- 对状态追问触发快捷汇总，降低 controller 无效 observe 循环

### route（controller）

- 只负责：`observe` / `generate_task`
- 输出：`Task + controller_trace`
- 观察工具含：`read`、`ls`、`build_context_view`、`previous_failed_track`、`beijing_time`、`skill_tool`
- controller skills 通过 `paths.skills_root/controller/<skill>/SKILL.md` 统一组织
- LLM 输入通过 agent memory 组装；在超窗时可触发压缩

### execute（executor/functest/accutest/perftest）

- execute 节点只产出 `task_status/task_result`，不负责最终用户回复
- `functest/accutest/perftest` 走异步 dispatch：
  - 当前 task 立即置为 `running`
  - `result=正在执行`
  - 记录 `dispatch_pyskill` 轨迹
- `executor` 支持 skill 插件化：
  - 自动扫描 `paths.skills_root/executor/<skill>/SKILL.md`
  - 注入元数据（`name/description/when_to_use/skill-mode/path/allowed-tools`）到 `EXECUTOR_SKILLS_INDEX`
  - 命中后再 `read path` 加载 skill 正文
  - skill 脚本工具通过 `skill_tool(name,input)` 调用（仅允许当前激活 skill 的 `allowed-tools`）
- `skill-mode=pyskill` 时：
  - `skill_tool` 走 `Popen` 非阻塞派发
  - source task 立即进入 `running`
  - source task `content` 追加 `[pyskill pid=... run_id=...]` 作为运行引用

### update

- 持久化当前 task 到 environment（`add_task`）
- 写入 `track`（controller loop + executor/pyskill/diagnoser/reply）
- 更新 `failed_retry_count`
- 绑定 workflow 与 source task 的映射关系

### failure_diagnose

- 触发条件：failed 且允许重试
- 输入：上一失败 task + 完整失败 track
- 行为：给出失败分析，回写 `task.result`，并写入 `diagnoser` 轨迹

### final_reply（reply agent）

- 只在 round 结束时触发
- 输入：`user_input + final_task + environment observation view(include_trace=false)`
- 输出：最终 `output.reply`
- 写入 `track`：`agent=reply,event=compose`
- reply 与 failure_diagnose 也复用同一 memory 机制（统一上下文构造）

### pre_reply_collect

- 每轮进入 `final_reply` 前统一执行
- 回收已完成 pyskill 结果并回填 `pyskill_task`
- 处理超时任务（`runtime.pyskill_timeout_sec`）并 failed 收敛
- 处理“进程已死但未回填”场景，避免 source task 长期停在 `running`

## Skill 注入链路（关键）

1. Graph 层传统一根路径 `paths.skills_root`，再派生 `controller` 与 `executor` 子目录。
2. 运行时扫描 `SKILL.md`，解析并严格校验 frontmatter 与 `allowed-tools` 脚本映射。
3. 系统预注入可选取元数据：`name/description/when_to_use/path/allowed-tools`。
4. 模型命中 skill 后，先 `read path` 激活 skill，再按规则执行。
5. 工具脚本统一走 `skill_tool`；全局 `web_search` 已下沉为 skill 脚本示例。

## 设计亮点

1. 异步非阻塞执行：长任务不阻塞当前对话轮。
2. Pre-reply 收敛守门：每轮回复前都做活跃任务巡检，避免“已死进程仍显示 running”。
3. 幂等回填：同一 `run_id` 多入口回收只会落一条终态，降低重复回填风险。
4. 同轮多任务落盘：`pyskill_task` 与后续汇总任务可共存，利于追问场景。
5. 强一致回链：source task 与异步结果通过 `run_id + pyskill_task ref` 关联。
6. Skill 解耦扩展：executor skill 增删不侵入 graph，实现插件化演进。
7. 轨迹统一：所有关键行为都落到 `track`，支持 CLI show 和离线复盘。

## CLI 入口

- `scripts/run/run_cli.py`：标准 CLI
- `scripts/run/run_cli_show.py`：同流程，每轮额外打印 `show_environment(show_trace=True)`
