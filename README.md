# Environment-Runtime

中文 | [English](README.en.md)

[![Tests](https://github.com/syy12335/task-rounting/actions/workflows/tests.yml/badge.svg)](https://github.com/syy12335/task-rounting/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Environment-Runtime 是一个面向工程型 agent 的任务路由运行时：把高确定性任务提前分流到固定 workflow / skill，把低确定性任务留给完整 executor loop，从而降低 token 消耗、减少幻觉，并让长任务可以异步运行和回填。

它适合这类场景：

- 任务大多是稳定工程流程，例如测试、评测、巡检、查询、批处理、发布前检查
- 一部分任务可以由固定脚本或 workflow 完成，但仍需要 agent 负责路由、追问、汇总和失败恢复
- 你希望 controller 只基于显式 Environment 状态决策，而不是依赖隐式上下文或完整 trace
- 长任务需要先返回 `running`，后续由进程级 skill / workflow 异步回填结果

它不适合这类场景：

- 每个请求都需要开放式推理，几乎没有可沉淀的确定性 workflow
- 你只需要一个聊天机器人，不需要结构化 task、Environment、track 或训练闭环
- 你需要开箱即用的业务 task type；当前内置的 `functest / accutest / perftest` 是示例 task family，真实落地时应替换成你的领域任务

## 优势

- **更低 token 消耗**：在高确定性任务占主导的分布里，稳定任务不必每次都走完整 agentic loop；相对 OpenClaw-style baseline，经验消耗约为 7%。
- **更少无效等待**：长任务可以先返回 `running`，后续异步回填结果；用户不用在一个同步 agent 回合里干等。
- **更少幻觉空间**：controller 只根据显式 Environment 视图做决策，减少“凭记忆补事实”或把隐藏 trace 当依据的问题。
- **更稳定的工程复用**：能沉淀成脚本、workflow、skill 的路径会逐步固定下来，让 agent 负责调度和异常收敛，而不是反复重新推理流程。
- **更容易复盘 badcase**：每轮任务、失败、重试、异步回填和最终回复都有结构化轨迹，方便定位 controller / executor / skill 的具体问题。

这些收益依赖任务分布：确定性 workflow 越多，收益越明显；如果大多数请求都是开放式推理，它会更接近普通 executor agent。当前仓库仍需要补充可复现 benchmark，更适合作为机制验证和二次开发起点。

---

## 核心机制

### 1. Environment：唯一状态真源与训练/推理统一口径

`Environment` 是整个 graph 的共享状态载体，多轮任务、异步回填、失败重试、历史摘要和最终回复都围绕它展开。controller 运行时不直接读取杂散上下文，而是读取从 Environment 派生出的正式 view。

训练侧复用同一套入口：`build_controller_state_input(...)` 会把 runtime Environment 收敛成 `{ USER_INPUT, ENVIRONMENT_JSON, SKILLS_INDEX }`。这意味着训练样本和线上 controller 推理看到的是同一种状态结构，减少“训练时一套 context、运行时另一套 context”的口径漂移。

### 2. 双重截留：按任务不确定性选择执行层

通用 agentic 框架会倾向于让所有输入都走完整的 agentic loop，但工程场景里很多任务的执行路径其实是固定的；README 里用测试类任务举例，只是为了把分层路由讲清楚，并不代表框架只服务测试场景。

Environment-Runtime 的做法是：把任务按确定性拆成多层执行路径，越确定的任务越早离开高成本 LLM 路径。controller 只负责路由和结构化 task 生成，默认 `max_steps=3`；只有剩余高不确定性任务才进入完整 executor loop（默认 `max_steps=4`）。

```text
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Controller Agent   （LLM，max_steps=3，strict schema） │
│ 识别任务类型，输出结构化 Task                           │
└──────────────┬──────────────────────────────┬───────────┘
               │                              │
    ┌──────────▼──────────┐         ┌─────────▼──────────┐
    │ functest /          │         │      executor       │
    │ accutest / perftest │         │   需要灵活处理       │
    └──────────┬──────────┘         └─────────┬──────────┘
               │                              │
    ┌──────────▼──────────┐     ┌─────────────┼──────────────┐
    │ ThreadPoolExecutor  │     │             │              │
    │ 异步 dispatch       │     │ 无 skill    │ sync skill   │ pyskill
    │ 立即返回 running    │     │ 自由发挥    │ 脚本同步执行 │ subprocess
    │ 不阻塞当前轮         │     │ 消耗最大    │ 阻塞有返回值 │ 非阻塞派发
    └─────────────────────┘     └────────────────────────────┘
```

说明：图中的 `functest / accutest / perftest` 是当前仓库内置的占位示例 task family，用于演示高确定性任务的低成本分流路径；实际落地时可替换为你的业务任务类型。

核心直觉是：重试越多、每次 IO 带入的上下文越大，workflow 成本差异就越明显；能用确定性路径解决的任务，越早离开 agentic loop 越划算。

额外 LLM 消耗：

说明：这里比较的是 controller 完成路由之后，不同执行层新增的 LLM 消耗；所有请求仍会先经过 controller。

| 执行层 | 额外 LLM 消耗 | 说明 |
|--------|---------------|------|
| 内置示例 task type（`functest / accutest / perftest`） | 极低 | controller 路由后直接 dispatch 到 `ThreadPoolExecutor`，执行阶段不再进入 executor loop |
| pyskill（`skill-mode=pyskill`） | 极少 | LLM 只参与“是否启动该 skill”，实际执行由 subprocess 异步完成 |
| sync skill（`skill-mode=sync`） | 少 | LLM 决策命中 skill，具体执行由脚本完成 |
| executor 自由发挥 | 最多 | 进入完整 executor agentic loop（默认 `max_steps=4`） |

### 3. PySkill：进程级非阻塞与幂等回填

对于流程固定但耗时较长的 skill，可声明 `skill-mode: pyskill`。executor 命中后通过 `subprocess.Popen` 非阻塞派发，source task 立即进入 `running`，并在 `track` 中记录 `run_id / pid / dispatch_pyskill`。

进程管理要点：

- 每个 pyskill 进程有唯一 `run_id`，stdout/stderr 落盘到 skill 目录下的 `.pyskill_runtime/`
- `collect_workflows` 与 `pre_reply_collect` 都可回收结果，但同一 `run_id` 只会被幂等回填一次
- `pre_reply_collect` 会在每轮回复前巡检死进程、超时任务和句柄丢失任务，自动 failed 收敛
- 回填时会新增 `pyskill_task`，并把 source task 的 `result` 回链到 `pyskill_task(round_id=..., task_id=...)`

### 4. Controller 后训练：数据回流闭环

controller 后训练主线围绕同一套 Environment 状态协议展开，形成一条从基础协议样本、on-policy rollout、badcase 筛选到偏好优化的连续回流链路：

```text
manual_protocol_v1 -> SFT warm start -> GRPO -> holdout evaluate -> teacher_queue / annotate_queue -> preference_admissions -> DPO -> next GRPO ...
```

SFT 先把 controller 拉到稳定的协议输入输出空间；GRPO 在当前 policy 上采样候选动作并暴露真实错误分布；teacher 在筛选 badcase 时生成同一状态下的 gold case，让 gold output 和当前 policy bad output 组成 `chosen / rejected` 偏好样本，进入 `preference_admissions`；DPO 再消费这些 pair 继续优化 controller，并进入下一轮 GRPO。

controller 后训练的 reward 不是只看“是否像 gold action”，而是把是否基于可见状态做决策放在最高权重：

```text
environment = 0.5
action      = 0.3
args        = 0.2
```

`environment` 维度只判断 candidate 是否 grounded in 当前可见 state。reward teacher 只能依据 `USER_INPUT + ENVIRONMENT_JSON + SKILLS_INDEX`，不使用 hidden state、verifier sidecar 或默认不可见的完整 trace。这个约束会把 controller 的主要训练压力放在“不要编造不可见事实、不要忽略显式 Environment 状态”上。

### 5. Track：可观测日志与低耦合状态通道

`TaskRecord.track` 是 controller、executor、pyskill、diagnoser、reply 的统一执行轨迹。`update_node` 会把 controller trace 与 agent track 合并写入 Environment；failure diagnose 和 final reply 会继续向最后一条 task 追加结构化事件。

track 默认不自动暴露给 controller，只有 `include_trace=true` 或 `previous_failed_track` 这类显式读取才会带出完整轨迹，避免 trace 膨胀影响常规路由。

同时，track 也承担轻量状态共享：`_build_round_skill_read_context(...)` 会扫描当前 round 里已记录的 `read SKILL.md` 事件，让后续 executor 知道哪些 skill 文件已经读过，从而减少同一 round 内的重复读取。

### 6. Context 压缩：三层防线

上下文治理分三层：

1. Agent Memory 私有压缩：各 agent 维护自己的 memory，超过 `context_window_tokens` 后触发摘要压缩。
2. Tool 结果规则裁剪：工具返回过大时按 `head + mid_hits + tail` 规则保留首尾和中段命中证据。
3. Environment History Rollup：旧轮次折叠成 `history_summaries` 和 `history_meta_summary`。

Rollup 不会无条件折叠所有历史；`running` 相关轮、最近失败轮、source / pyskill 链接相关轮会被保护，避免压缩后丢失回收、重试和溯源所需的关键状态。

## Quick Start

```bash
python -m pip install -e ".[dev]"

# 可选：controller 后训练依赖（SFT / GRPO / DPO；CUDA 环境需匹配 verl + SGLang）
# pip install -r requirements-post-training.txt

# 默认：阿里云百炼
export MODEL_PROVIDER=aliyun
export EMBEDDING_PROVIDER=aliyun
export API_KEY_Qwen=<your_key>

# 可选：改用本地 SGLang
# export SGLANG_MODEL_PATH=/path/to/Qwen3-4B
# export SGLANG_SERVED_MODEL_NAME=qwen3-4b
# export SGLANG_API_KEY=EMPTY
# ./scripts/sglang/start.sh
# ./scripts/sglang/status.sh
# export MODEL_PROVIDER=sglang
# export EMBEDDING_PROVIDER=aliyun
# 若本地 SGLang 也提供 embedding，再改成：
# export EMBEDDING_PROVIDER=sglang
# 停止本地服务时：
# ./scripts/sglang/stop.sh

# 交互模式（多轮复用同一 environment）
environment-runtime --config configs/graph.yaml --interactive

# 可选：单次输入
# environment-runtime --config configs/graph.yaml --input "帮我做一次功能测试"
```

主配置文件是 `configs/graph.yaml`，常用运行参数已经直接写在文件里并附中文注释，主要包括：

- `model` / `embedding`
- `paths`
- `runtime`

更多运行入口：

```bash
# 打印完整轨迹（含 show_environment）
environment-runtime-show --config configs/graph.yaml --input "帮我做一次功能测试"

# 运行单个 case（使用你自己的 case.json）
environment-runtime-case --config configs/graph.yaml --case /path/to/case.json

# 批量运行（目录内需要是 case json 文件）
environment-runtime-cases --config configs/graph.yaml --cases-dir /path/to/cases_dir

```

运行输出默认落到：`var/runs/run_YYYYMMDD_HHMMSS/environment.json`

看执行路径时，可以优先关注 `track`：

- 若存在 `agent=pyskill, event=dispatch_pyskill`，说明任务已经进入异步 workflow / pyskill 派发
- 若当前轮直接生成 `done/failed` 结果且没有 `dispatch_pyskill`，通常说明任务在同步 skill 或 executor 路径内完成

## 开发与测试

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

当前 GitHub Actions 会在 push / pull request 时运行基础 pytest。后训练依赖没有放进默认安装路径；需要运行 SFT / GRPO / DPO 时再安装 `requirements-post-training.txt`，并确保 CUDA、verl 和 SGLang 环境匹配。

## 局限性

- token 节省比例依赖确定性任务分布：Controller 一次分流命中的高确定性任务越多，节省越明显；README 里用 `functest / accutest / perftest` 作为示例 task family 来说明这件事。如果大多数任务都落到 executor，自然收益会变小
- pyskill / sync skill 需要人工维护：确定性场景越多，配套脚本也越需要持续演进
- 评测集规模还小：当前评测依赖 `src/task_router_graph_train/assets/manual_protocol_v1/` 的 `holdout` split，适合机制验证，不代表全量线上分布
- 业务落地仍需定制：当前 README 里的 `functest / accutest / perftest` 只是占位示例；迁移到其他工程场景时，需要重新定义 task type、skill 和失败治理口径

## 文档

- `docs/design.md`：节点职责、执行流程与分支规则
- `docs/skills.md`：skill 目录规范与元数据注入机制
- `docs/skills_runtime.md`：skill 加载校验与 `skill_tool` 执行契约
- `docs/pyskill.md`：pyskill 的 dispatch / collect / link 机制
- `docs/agent_memory.md`：memory 压缩与 environment 视图裁剪策略
- `docs/environment.md`：environment 数据结构与 task / track 语义
- `docs/track.md`：track 写入链路、trace 暴露策略与 agent 间状态共享
- `src/task_router_graph_train/README.md`：controller 的 environment-grounded 后训练闭环
- `src/task_router_graph_train/docs/grpo_dpo_loop_v1.md`：controller 的 GRPO / DPO 下一阶段方案
- `docs/data_format.md`：输入输出与样本格式
- `docs/changelog.md`：近期更新

## 更新计划

- 当前 DPO 回流改造已完成代码侧切换，下一步需要补一轮真实训练链路测试，重点验证截断配置、`prompt/chosen/rejected` 长度分布和超长样本处理。
- 双重截留的确定性判断需要插件化：当前 `functest / accutest / perftest` 等确定性分流仍偏硬编码，后续要改成可注册、可替换的插件机制。
- 运行时侧继续细化 Environment 中的 trace / track：补齐更稳定的事件结构、视图裁剪和排障读取口径。
- 细化 Environment 压缩机制：history / view 压缩要依据当前 task 的目标、状态和证据需求选择保留内容，不能无目的地压缩。
- 优化 agent 策略以提高 KV-cache 命中率：收敛 prompt 稳定前缀、agent 调度和上下文注入顺序，减少可复用 cache 被动态片段打断。
- 细化 tool 结果裁剪：当前仍是掐头去尾 + 中间 BM25 命中片段的规则策略，后续需要补齐更稳定的相关性评分、去重和结构化保真。
- 补一组可复现 benchmark：固定 case 分布、运行配置和 token 统计口径，用可复跑数据证明双重截留带来的 token 节省。
- 继续补齐项目工程化基础：完善发布配置、版本策略和更多 CI 检查。
- 拆分运行时大文件：按 graph 编排、node 实现、工具执行和 skill worker 边界拆分 `graph.py`、`nodes.py`、`web_search.py`。
