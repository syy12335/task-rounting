# Controller Encyclopedia

本文件是 controller 的知识入口。

在每一步决策中，controller 必须结合：
- 当前 `user_input`
- recent `rounds`
- 本 encyclopedia
来判断：

1. 是否还需要补充观察
2. 若不需要，当前请求属于哪类 `task_type`
3. 应使用哪个 reference 文件
4. 当前信息是否足以生成 `task_content`
5. 若不足，下一步应观察什么

---

## I. Global Principles

1. 不要假设信息天然充分。
2. 生成任务前，先判断是否需要观察。
3. task type 必须基于当前请求、recent rounds 与 references 判定，不能机械继承上一轮。
4. 只有在最小信息齐备时才能生成 `task_content`。
5. 信息不足时优先 `observe`。

---

## II. Task Types

### `normal`
Definition：解释、总结、查阅、指导、持续回应类任务。  
Reference：`normal-task.md`

### `functest`
Definition：功能测试类任务。  
Reference：`functest-task.md`

### `accutest`
Definition：准确性/质量评估类任务。  
Reference：`accutest-task.md`

### `perftest`
Definition：性能评估类任务。  
Reference：`perftest-task.md`

---

## III. Base Decision Order

### Step 1：先判断是否仍需 observation
自检问题：

- recent rounds 中是否已有足够事实？
- 对应 task reference 是否已明确？
- 当前信息是否足以写出稳定 `task_content`？

任一问题答案为否，则优先 `observe`。

### Step 2：若需 observation，优先观察什么
Observation 优先级：

1. 最相关 task reference
2. 最近一次相关任务输出
3. 最近一次 run 产物
4. 必要目录结构或文件存在性

### Step 3：信息足够后再判定 `task_type`
不要先定类型再反向找证据。

### Step 4：读取对应 reference
利用 reference 判断：
- 当前信息是否足够
- 若不足，下一步观察目标是什么

### Step 5：生成 `task_content`
只有在 reference 要求的最小信息已满足时才能生成 `task_content`。
