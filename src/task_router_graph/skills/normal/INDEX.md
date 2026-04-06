# Normal Task Skill Index

本文件是 `normal` tasks 的执行参考。

当当前 task type 已确定为 `normal` 时，normal executor 应结合：
- 当前 task content
- recent rounds
- 本 skill index
来确定回复模式与执行边界。

---

## I. Core Principles

1. `reply` 面向用户。
2. `task_result` 面向系统。
3. 仅基于可用上下文回答。
4. 关键事实缺失时必须明确说明。
5. 不伪造已执行测试或指标。
6. 不讨论内部路由逻辑。

---

## II. Explanation Tasks

### Goal
- 直接解释已有结果
- 指出关键失败点或关键指标
- 不扩展为新 workflow

### Preferred patterns
- 最近一次测试的核心结论是……
- 主要失败点集中在……
- 该结果表明……

---

## III. Summarization Tasks

### Goal
- 压缩历史结果
- 提炼关键信息
- 保持事实化

### Preferred patterns
- recent rounds 的关键信息可概括为……
- 历史结果主要体现为……
- 当前可确认结论包括……

---

## IV. Guidance Tasks

### Goal
- 提供直接指导
- 保持简短、可执行
- 不伪造环境状态

### Preferred patterns
- 更合适的下一步是……
- 若要继续推进，建议先补充……
- 当前场景下通常先做……

---

## V. Lookup-Based Response Tasks

### Goal
- 只基于已有材料回答
- 不补造不存在细节

### Preferred patterns
- 现有记录显示……
- 基于最近一次任务结果……
- 从当前上下文可确认……

---

## VI. `task_status` Criteria

### `done`
可用上下文足以完成当前 normal task。

### `failed`
关键事实缺失，无法可靠完成当前 normal task。

---

## VII. `task_result` Style

`task_result` 要求：
- 一句话
- 事实化
- 简短

Preferred examples：
- 已基于历史输出完成结果解释
- 已完成最近一次任务结果总结
- 因关键事实缺失导致执行失败
