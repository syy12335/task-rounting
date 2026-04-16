# time_range_info worker graph 链路说明（Agentic CRAG）

本文描述的是 `time_range_info` 的 worker graph（子流程 graph），不是主编排 graph `src/task_router_graph/graph.py`。

## 1. 节点拓扑

`validate_input -> bootstrap_retrieval -> build_local_semantic_index -> hybrid_retrieve -> llm_grade_relevance -> heuristic_guardrail -> (rewrite_query | synthesize_answer)`

- 当判定证据不足且未达到迭代上限时，走 `rewrite_query -> hybrid_retrieve` 继续循环。
- 当证据足够、禁止重写或达到最大迭代轮次时，进入 `synthesize_answer`。

## 2. 节点契约

### `validate_input`
- 输入：`input_payload`
- 输出：`query`, `current_query`, `limit`, `iteration=1`, `query_history`
- 失败条件：输入不是 JSON object、query 为空、query 超长。

### `bootstrap_retrieval`
- 输入：`current_query`
- 输出：`bootstrap_docs`
- 行为：先做一轮 Web 检索，为本地语义索引提供语料基础。
- 失败条件：无可用检索结果。

### `build_local_semantic_index`
- 输入：`bootstrap_docs`
- 输出：`semantic_chunks`（带 embedding 向量）
- 行为：对检索文本分块并向量化，构建本轮运行内存索引。
- 失败条件：embedding 失败或索引构建为空。

### `hybrid_retrieve`
- 输入：`current_query`, `semantic_chunks`
- 输出：`hybrid_docs`
- 行为：并行组合 Web 检索与本地语义召回结果，再做去重。
- 失败条件：混合召回为空。

### `llm_grade_relevance`
- 输入：`query`, `current_query`, `hybrid_docs`
- 输出：`grade_decision`, `grade_confidence`, `grade_reason`, `selected_docs`
- 行为：LLM 对证据充分性主判，并返回建议保留的证据索引。

### `heuristic_guardrail`
- 输入：`selected_docs`, `grade_*`
- 输出：`heuristic`, `grade_decision`
- 行为：用通用统计信号做兜底（文档数量、去重率、摘要长度等），不依赖业务关键词规则。

### `rewrite_query`
- 输入：`query`, `current_query`, `grade_reason`, `hybrid_docs`
- 输出：`current_query`, `query_history`, `iteration+1`
- 行为：在不改变用户目标的前提下改写 query，提升下一轮召回质量。

### `synthesize_answer`
- 输入：`selected_docs`, `query`
- 输出：`task_status`, `task_result`
- 行为：基于证据生成答案；证据不足时输出失败结构。

## 3. 运行时约束

- query 长度上限 120，用户请求 limit 上限 5。
- 最大迭代轮次、混合召回参数、评分阈值由 `config/retrieval_policy.yaml` 控制。
- embedding / model 配置从仓库 `configs/graph.yaml` 读取。
- 缺少 embedding 配置或配置非法：worker 直接 `failed`，不回退规则匹配。

## 4. stdout 输出契约

worker 输出 JSON：

```json
{
  "task_status": "done|failed",
  "task_result": "string"
}
```

- `task_status` 只允许 `done` 或 `failed`
- `task_result` 为字符串；done 时通常是结构化 JSON 字符串。

## 5. 与主流程衔接（接口级）

- dispatch：主流程通过 `skill_tool(name=web_search)` 派发。
- collect：主流程在回收阶段读取 worker stdout。
- link：主流程将回收结果按 run_id 回链 source task。

以上由主流程负责，本文只约束 skill 内部 CRAG graph。
