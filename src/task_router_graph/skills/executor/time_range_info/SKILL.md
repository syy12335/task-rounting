---
name: time-range-info
description: 查询某个时间段的时效信息；需要先锚定当前时间，再检索外部信息并输出证据化结论。
when_to_use: 用户请求中同时出现“相对时间表达”（如昨天/今天/明天、最近N天、上周/本周/下周、过去N天/未来N天）与“时效主题”（如新闻、天气、事件、资讯、预报）时使用。
skill-mode: pyskill
allowed-tools: ["web_search"]
---
# 时间段信息查询（通用时效资讯）

本 skill 以 `pyskill` 方式运行，内部使用 **Agentic CRAG + 混合检索子代理**：

- 初始检索（bootstrap retrieval）
- 本地语义索引构建（local semantic index）
- 混合召回（web + local semantic）
- 相关性评估（LLM grader + heuristic guardrail）
- 证据不足时 query rewrite 后继续检索
- 证据充分后 synthesis 输出

实现文档与策略配置：

- `time_range_info worker graph` 说明（非主 `graph.py`）：`docs/graph_flow.md`
- 检索策略配置：`config/retrieval_policy.yaml`

## 必须顺序

1. 第一步调用 `beijing_time {}`
2. 第二步调用 `skill_tool {"name":"web_search","input":{"query":"...","limit":...}}`

禁止：

- 未完成时间锚定就检索
- 未完成时间锚定就给出“最近/本周/上周”等结论

## 执行步骤

1. 获取北京时间，读取 `date`（必要时结合 `iso`）作为当前时间锚点。
2. 将相对时间词（最近 N 天、上周、本周、未来 N 天）转成绝对日期范围。
3. 构造检索 query：包含主题词 + 日期线索 + 地域/对象。
4. 在 `task_result` 中明确写出：
   - 查询时间范围（绝对日期）
   - 关键结论
   - 不确定性提示（请以官方发布为准）

## 失败止损（强制）

- 若达到最大迭代轮次后证据仍不足：立即 `finish`。
- 若出现脚本失败、超时、配置错误：立即 `finish` 并给出诊断信息。
- 失败返回应包含：已锚定的绝对日期范围、已尝试的检索方向、建议补充更具体对象。

## 完成判定

- `done`：已完成时间锚定 + 证据检索 + 结论整合
- `failed`：关键输入缺失或证据不足无法给出可靠结论
