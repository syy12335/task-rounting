# task-router

一个面向小场景 Agent 的任务路由仓库，用于验证 **Controller 驱动的任务分发、执行、失败纠偏与统一落盘** 这条最小闭环。

当前实现基于 LangGraph，围绕一次用户请求完成以下过程：识别任务类型、生成任务内容、执行任务、记录轨迹，并在需要时进行失败诊断后再次路由。

## 项目概览

`task-router` 关注的不是“大而全”的通用 Agent 能力，而是更具体的问题：在小场景下，如何把一次请求变成一条 **可运行、可观测、可复盘** 的任务链路。

当前仓库已支持四类任务：

- `normal`
- `functest`
- `accutest`
- `perftest`

在实现上，仓库将路由、执行、更新、回复拆分为独立节点，并将每次运行的中间状态与轨迹统一写入 `environment.json`，便于后续调试、复盘和评测。

## 核心流程

当前主流程如下：

```text
init
  -> route
  -> (normal | functest | accutest | perftest)
  -> update
  -> (failure_diagnose | route | final_reply)
  -> end
```

关键分支规则：

- `task.status == done`：直接进入 `final_reply`
- `task.status == failed` 且未超过 `max_failed_retries`：进入 `failure_diagnose` 后回到 `route`
- `task.status == failed` 且超过 `max_failed_retries`：进入 `final_reply`
- 达到 `max_task_turns`：进入 `final_reply`

各节点职责如下：

- `init`：初始化本次运行状态，创建 round，准备运行目录
- `route`：由 controller 判断是否继续观察，或直接生成下一步 task
- `normal / functest / accutest / perftest`：执行对应类型的任务
- `update`：将本轮 task、结果与轨迹写回 environment
- `failure_diagnose`：在失败且仍可重试时分析原因，并回到路由节点
- `final_reply`：在 round 结束时统一生成最终回复

## 仓库结构

```text
.
├─ app/                     # 应用层入口（预留）
├─ configs/                 # 运行配置
├─ data/cases/              # 示例 case
├─ docs/                    # 设计与数据格式文档
├─ notebooks/               # 实验与模型效果验证
├─ scripts/run/             # CLI、批量运行、可视化入口
├─ scripts/sglang/          # 本地 sglang 启停脚本
├─ src/task_router_graph/   # 核心实现
├─ tests/                   # 测试代码
└─ var/runs/                # 运行输出目录
```

核心代码位于 `src/task_router_graph/`：

- `graph.py`：LangGraph 主流程定义
- `nodes.py`：各节点执行逻辑封装
- `agents/`：controller/normal/test/diagnosis/reply 等 agent
- `schema/`：Task、Environment、Output 等数据结构
- `prompt/`：各节点使用的 prompt
- `skills/`：controller 与 normal 的 skills index / reference

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

选择模型后端并设置环境变量：

```bash
# 阿里云百炼
export MODEL_PROVIDER=aliyun
export API_KEY_Qwen=<your_key>

# 或本地 sglang
export MODEL_PROVIDER=sglang
export SGLANG_API_KEY=EMPTY
```

运行单个 case：

```bash
python scripts/run/run_case.py --config configs/graph.yaml --case data/cases/case_01.json
```

## 运行方式

### 1. 单 case 运行

```bash
python scripts/run/run_case.py --config configs/graph.yaml --case data/cases/case_01.json
```

### 2. CLI 单次输入

```bash
python scripts/run/run_cli.py --config configs/graph.yaml --input "帮我总结最近一次测试结果"
```

### 3. CLI 交互模式

```bash
python scripts/run/run_cli.py --config configs/graph.yaml --interactive
```

### 4. 批量运行 case

```bash
python scripts/run/run_cases.py --config configs/graph.yaml
```

### 5. 可视化运行

```bash
streamlit run scripts/run/streamlit_app.py
```

### 6. 调试模式（打印 show track）

```bash
python scripts/run/run_cli_show.py --config configs/graph.yaml --input "帮我总结最近一次测试结果"
```

## 配置说明

主配置文件为：

```text
configs/graph.yaml
```

配置主要分为三部分：

- `model`：模型后端、API 地址、超参数与 provider 切换
- `paths`：输入 case、日志与运行输出目录
- `runtime`：最大轮数、最大 task turn、失败重试次数等运行参数

默认 provider 由 `configs/graph.yaml` 中的 `model.provider` 指定，也可以通过环境变量 `MODEL_PROVIDER` 覆盖。

当前默认运行参数（可按需调整）：

- `max_rounds: 4`
- `max_task_turns: 4`
- `max_controller_steps: 3`
- `max_executor_steps: 4`
- `max_failed_retries: 3`

## 本地 SGLang

本地使用 sglang 时，可直接通过脚本启动、查看状态和停止：

```bash
./scripts/sglang/start.sh
./scripts/sglang/status.sh
./scripts/sglang/stop.sh
```

也可以手动启动 OpenAI-compatible 服务，再通过 `MODEL_PROVIDER=sglang` 接入。

## 输出与调试

每次运行都会在 `var/runs/` 下生成对应的运行目录，并落盘当前环境状态，例如：

```text
var/runs/run_YYYYMMDD_HHMMSS/environment.json
```

日常使用中可按下面方式选择入口：

- 只关心最终输出：`run_cli.py`
- 需要查看完整结果 JSON：`--raw`
- 需要查看 environment：`--show-environment`
- 需要查看可读轨迹：`run_cli_show.py`

## LangSmith Tracing

仓库已接入 LangChain / LangGraph tracing。

- graph 顶层 run：`task-router.graph`
- 节点级 run：`task-router.<node>`

常用环境变量如下：

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_ENDPOINT=https://api.smith.langchain.com
export LANGSMITH_API_KEY=<your_langsmith_api_key>
export LANGSMITH_PROJECT=task-router
export LANGCHAIN_CALLBACKS_BACKGROUND=false
```

开启后可直接使用现有 CLI / case 入口运行。

## 文档导航

详细设计与数据格式见：

- `docs/design.md`
- `docs/environment.md`
- `docs/data_format.md`

如果需要进一步理解当前实现，建议按以下顺序阅读：

1. `README.md`
2. `src/task_router_graph/graph.py`
3. `docs/design.md`
4. `docs/environment.md`
5. `docs/data_format.md`

## 当前状态

当前仓库已经具备一条完整的最小闭环：

- controller 路由
- 多 task_type 执行
- 失败诊断与重试
- environment 落盘
- CLI / 批量 / 可视化入口
- tracing 与调试支持

后续扩展可以继续围绕两类方向推进：

- 更稳定的执行链与观察工具
- 基于轨迹与样本的评测、蒸馏与优化
