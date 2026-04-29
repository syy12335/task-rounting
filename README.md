# Environment-Runtime

Environment-Runtime 是一个面向稳定、可复用工程流程的任务路由框架，对齐 OpenClaw 的基础需求，在稳定工程场景下实现极低 token 消耗，并提供更流畅的等待体验与更稳定的 Skill 工程化能力。

核心设计思路是按任务不确定性做双重截留：controller 一次截留 + executor pyskill 二次截留。`functest / accutest / perftest` 只是当前仓库的占位示例 task type，用于演示高确定性任务如何更早离开高成本路径；`skill / pyskill` 属于受约束的 agentic loop；仅将剩余高不确定性任务送入自由度最高的 executor loop。这个双重截留策略一方面显著降低 token 消耗，另一方面也能大幅减少幻觉；在高确定性任务占主导的场景下，经验消耗约为 OpenClaw 的 7%。

除运行时能力外，仓库还提供了面向 controller 的后训练框架，用 `SFT warm start -> GRPO online rollout -> DPO` 的闭环持续优化路由决策质量。SFT 负责把 controller 拉到稳定的协议输入输出空间，GRPO 负责在当前 policy 上采样候选动作并暴露真实错误分布；teacher 在 rollout 后生成 gold answer / chosen response，并把它和 bad output 组成 `preference_admissions`，作为 DPO 消费的 `state_input / chosen / rejected` 训练队列。

---

## 为什么要分层

通用 agentic 框架会倾向于让所有输入都走完整的 agentic loop，但工程场景里很多任务的执行路径其实是固定的；README 里用测试类任务举例，只是为了把分层路由讲清楚，并不代表框架只服务测试场景。

Environment-Runtime 的做法是：把任务按确定性拆成多层执行路径，越确定的任务越早截流。

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

## 各执行层的额外 LLM 消耗

说明：这里比较的是 controller 完成路由之后，不同执行层新增的 LLM 消耗；所有请求仍会先经过 controller。

| 执行层 | 额外 LLM 消耗 | 说明 |
|--------|---------------|------|
| 内置示例 task type（`functest / accutest / perftest`） | 极低 | controller 路由后直接 dispatch 到 `ThreadPoolExecutor`，执行阶段不再进入 executor loop |
| pyskill（`skill-mode=pyskill`） | 极少 | LLM 只参与“是否启动该 skill”，实际执行由 subprocess 异步完成 |
| sync skill（`skill-mode=sync`） | 少 | LLM 决策命中 skill，具体执行由脚本完成 |
| executor 自由发挥 | 最多 | 进入完整 executor agentic loop（默认 `max_steps=4`） |

---

## 核心机制

### 1. Environment：运行时协议真源

`environment` 是整个 graph 的共享状态载体。多轮任务、异步回填、失败重试和历史摘要都围绕它展开；controller 运行时读取的是从它派生出的 context view，训练侧也复用同一口径构造 `ENVIRONMENT_JSON`。

仓库内置的 controller 后训练也是围绕这件事设计的：小模型做长程任务时容易逐步偏离 environment 事实，SFT 先把协议输入输出对齐，GRPO 再通过 online rollout 暴露当前 policy 的错误分布，teacher gold answer 与 bad output 组成 preference pair，用于持续强化“基于 environment 做下一步决策”的能力。

### 2. 异步非阻塞回填

当前内置的三类示例 task type `functest / accutest / perftest` 通过 `ThreadPoolExecutor` 异步执行。当前对话轮会立即返回 `running`，不阻塞用户继续交互。任务完成后，在下一轮的 `collect_workflows` 阶段回填结果，新增 `pyskill_task` 记录并回链 source task。

```text
Round 1: 用户发起功能测试 -> task.status=running，立即回复“已提交”
Round 2: 用户问“怎么样了” -> collect_workflows 回收结果 -> 快捷汇总路径 -> 直接回复结果
```

### 3. pyskill：进程级非阻塞执行

对于流程固定但耗时较长的 skill，可声明 `skill-mode: pyskill`。executor 命中后通过 `subprocess.Popen` 非阻塞派发，LLM 只参与“是否启动”这一步，后续执行与 LLM 解耦。

当前仓库内的 `time_range_info` 就是一个 pyskill 样板。

进程管理要点：

- 每个 pyskill 进程有唯一 `run_id`，stdout/stderr 落盘到 skill 目录下的 `.pyskill_runtime/`
- `pre_reply_collect` 会在每轮回复前巡检死进程和超时任务，自动 failed 收敛
- `collect_workflows` 与 `pre_reply_collect` 都可回收结果，但同一 `run_id` 只会被幂等回填一次

### 4. Skill 插件化

新增 executor skill 只需要添加目录、`SKILL.md` 和可选脚本，不需要修改 `graph.py` 或维护中心索引：

```text
src/task_router_graph/skills/executor/
  your_skill/
    SKILL.md
    scripts/
      your_tool.py
```

`SKILL.md` frontmatter 约定：

```yaml
---
name: your-skill-name
description: 这个 skill 解决什么问题
when_to_use: 什么时候应该命中这个 skill
skill-mode: sync        # 或 pyskill
allowed-tools: ["your_tool"]
---
# 具体执行规则写在正文
```

运行时链路：

`扫描 SKILL.md -> 校验 frontmatter 与脚本映射 -> 注入元数据到 executor prompt -> 模型命中后 read path -> 按规则执行 skill_tool`

### 5. 失败治理

失败任务进入 `failure_diagnose -> route` 循环，最多重试 `max_failed_retries` 次，默认是 3。失败上下文通过 `previous_failed_track` 在多轮之间传递，避免“下一轮失忆”；超过上限后自动收敛到 `final_reply`。

### 6. Agent Memory 压缩

各 agent 会按角色维护上下文视图；当上下文超过 `context_window_tokens`（默认 3000）时触发摘要压缩。工具返回过大时按 `head + mid_hits + tail` 规则裁剪，尽量保留证据密度，避免原样整段灌入模型。

## Quick Start

```bash
pip install -r requirements.txt

# 阿里云百炼
export MODEL_PROVIDER=aliyun
export EMBEDDING_PROVIDER=aliyun
export API_KEY_Qwen=<your_key>

# 本地 sglang
export MODEL_PROVIDER=sglang
export EMBEDDING_PROVIDER=sglang
export SGLANG_API_KEY=EMPTY

# 单次输入
python scripts/run/run_cli.py --config configs/graph.yaml --input "帮我做一次功能测试"

# 交互模式（多轮复用同一 environment）
python scripts/run/run_cli.py --config configs/graph.yaml --interactive
```

主配置文件是 `configs/graph.yaml`，常用运行参数已经直接写在文件里并附中文注释，主要包括：

- `model` / `embedding`
- `paths`
- `runtime`

更多运行入口：

```bash
# 打印完整轨迹（含 show_environment）
python scripts/run/run_cli_show.py --config configs/graph.yaml --input "帮我做一次功能测试"

# 运行单个 case（使用你自己的 case.json）
python scripts/run/run_case.py --config configs/graph.yaml --case /path/to/case.json

# 批量运行（目录内需要是 case json 文件）
python scripts/run/run_cases.py --config configs/graph.yaml --cases-dir /path/to/cases_dir

```

运行输出默认落到：`var/runs/run_YYYYMMDD_HHMMSS/environment.json`

看执行路径时，可以优先关注 `track`：

- 若存在 `agent=pyskill, event=dispatch_pyskill`，说明任务已经进入异步 workflow / pyskill 派发
- 若当前轮直接生成 `done/failed` 结果且没有 `dispatch_pyskill`，通常说明任务在同步 skill 或 executor 路径内完成

## 本地 SGLang

运行入口默认优先使用已就绪的本地 SGLang；若服务不可达，会快速回退到阿里云。需要让运行入口自动拉起 SGLang 时，可设置 `SGLANG_AUTO_START=1`。

```bash
./scripts/sglang/start.sh
./scripts/sglang/status.sh
./scripts/sglang/stop.sh
```

---

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
- `src/task_router_graph_train/README.md`：controller 的 environment-grounded 后训练闭环
- `src/task_router_graph_train/docs/grpo_dpo_loop_v1.md`：controller 的 GRPO / DPO 候选演进方案
- `docs/data_format.md`：输入输出与样本格式
- `docs/changelog.md`：近期更新

## 更新计划

下一步训练侧会把 badcase 回流改成 DPO 偏好优化链路。

核心变化是：badcase 不再只沉淀为下一轮 SFT 的修正样本，而是和 teacher 给出的更优 action 组成同一状态下的偏好样本。DPO 会消费这些偏好样本，继续优化 controller 的 environment-grounded 决策能力。
