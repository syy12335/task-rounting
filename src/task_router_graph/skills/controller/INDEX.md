# Controller Encyclopedia

本文件是 controller 的百科全书入口。

controller 在每一步决策中，必须结合：

- 当前 `user_input`
- `rounds` 中已有的 environment
- 本 encyclopedia 及对应 reference

来决定当前的下一步动作。

## Controller 的工作方式

controller 的策略固定如下：

1. 先观察：读取 `environment`、相关 `reference files` 与可用观察工具结果
2. 再决策：判断当前是否还需要继续 `observe`
3. 若信息足够：判断当前 task 属于哪一种 `type`
4. 再根据对应 type 的 `Reference` 生成 `task_content`
5. 若信息不足：继续 `observe`

controller 不直接执行任务，也不直接面向用户回复。

---

## `normal` task

定位：强体验需求任务，通常需要尽快反馈，后续交给 `normal/chat agent` 执行，而不是继续进入测试 workflow。

常见情况：

- 历史报告查阅
- 历史结果分析
- 使用指导
- 联系人工 oncall
- 基于已有测试结果继续回答
- 解释最近一次测试失败原因
- 总结最近几轮任务输出

何时优先考虑：

- 当前请求的目标是解释、总结、查阅、引导，而不是重新执行测试
- 当前轮次中已经有一定历史结果可供利用
- 用户更关心“结果是什么意思”而不是“再跑一次测试”

Observe 关注点：

- 最近一次相关 task 的 `result`
- 最近一次相关 round 的 `reply`
- 最近一次相关报告或输出文件
- 与当前请求直接相关的历史产物

Reference：`normal-task.md`

---

## `functest` task

定位：功能测试任务，用于验证接口、协议、字段、断言或行为是否符合预期。

常见情况：

- 要做功能测试
- 使用昨天的配置进行测试
- 验证某协议 body 是否符合要求
- 检查某组断言是否通过
- 重新执行某次功能测试

何时优先考虑：

- 用户明确要求“做功能测试”
- 当前目标是验证功能正确性，而不是解释历史结果
- 当前请求关注 headers / body / assert / response / 行为正确性

Observe 关注点：

- 当前协议或配置
- 最近一次 functest 输出
- 相关测试产物是否存在
- functest reference 中要求的最小输入是否齐备

Reference：`functest-task.md`

---

## `accutest` task

定位：精度测试 / 质量评估任务，用于判断输出质量、准确性或评分表现。

常见情况：

- 做精度测试
- 评估当前输出质量
- 给效果打分
- 检查模型效果
- 比较两版结果质量

何时优先考虑：

- 用户明确要求“评估”“打分”“精度测试”
- 当前目标是执行评估，而不是解释已有指标
- 当前请求关注准确性、质量、评分或整体效果

Observe 关注点：

- 评估对象
- 最近一次 accutest 结果
- 与评估目标相关的输入 / 输出材料
- accutest reference 中要求的最小输入是否齐备

Reference：`accutest-task.md`

---

## `perftest` task

定位：性能测试任务，用于评估延迟、吞吐、并发、压测表现等性能维度。

常见情况：

- 做性能测试
- 测一下延迟
- 做压测
- 看吞吐和 p95
- 检查某接口的性能瓶颈

何时优先考虑：

- 用户明确要求“性能测试”“压测”“延迟”“吞吐”“并发”
- 当前目标是执行性能评估，而不是解释历史性能指标
- 当前请求关注 latency / throughput / qps / p95 / 并发

Observe 关注点：

- 测试对象
- 最近一次 perftest 结果
- 当前目标对象的性能相关上下文
- perftest reference 中要求的最小输入是否齐备

Reference：`perftest-task.md`

---

## Controller 决策准则

1. 不要机械继承上一轮 `task.type`
2. 不要在信息不足时直接生成 `task_content`
3. 先判断是否需要继续 `observe`
4. 信息足够后，再判断 task `type`
5. 只有在对应 `Reference` 所要求的最小信息已满足时，才生成 `task_content`
6. 每一轮只输出一个直接下一步动作
