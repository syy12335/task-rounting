# Controller GRPO Reward Draft

## Scope

这份文档只定义 controller 的 `GRPO` reward 协议。

## Core Position

- `GRPO` 主路径不保留 reference
- 最终 reward 完全基于 teacher ranking
- teacher ranking 固定看三个维度：
  - `environment = 0.5`
  - `action = 0.3`
  - `args = 0.2`

## Controller State

controller 的输入就是训练时真实可见的 state：

```text
USER_INPUT + ENVIRONMENT_JSON + SKILLS_INDEX
```

当前只记三条边界：

- `ENVIRONMENT_JSON` 是 `rounds` 视图，不是 runtime full state
- `previous_failed_task` 只是失败摘要
- 完整失败轨迹默认不可见；如果需要，必须显式 `observe(previous_failed_track, {})`

## Controller Output

controller 只允许输出一个 JSON object。

### `observe`

必须包含：

- `action_kind`
- `tool`
- `args`
- `reason`

不得包含：

- `task_type`
- `task_content`

合法 `tool`：

- `read`
- `ls`
- `build_context_view`
- `previous_failed_track`
- `beijing_time`
- `skill_tool`

### `generate_task`

必须包含：

- `action_kind`
- `task_type`
- `task_content`
- `reason`

不得包含：

- `tool`
- `args`

合法 `task_type`：

- `executor`
- `functest`
- `accutest`
- `perftest`

`task_content` 固定两段：

```text
用户目标：...
任务限制：...
```

## Reward Pipeline

reward 分两步：

1. hard gate
2. teacher ranking

### 1. Hard Gate

如果 candidate 在 `parse / schema / protocol` 任一层失败，则直接排最后，不进入后续 ranking。

- `parse`
  - 输出不能解析成单个 JSON object
- `schema`
  - 输出不是 runtime 合法的 controller action
- `protocol`
  - 输出虽然 schema 合法，但不符合当前 controller 输出约束

这里不做：

- branch exact-match
- reference 对照

#### Demo: parse

```text
我觉得应该先看看状态
```

结果：

- 不是 JSON object
- `parse` 失败
- 直接排最后

#### Demo: schema

```json
{
  "action_kind": "observe",
  "tool": "build_context_view"
}
```

结果：

- 缺少 `args`
- 缺少 `reason`
- `schema` 失败
- 直接排最后

#### Demo: protocol

```json
{
  "action_kind": "generate_task",
  "tool": "build_context_view",
  "task_type": "functest",
  "task_content": "执行登录测试",
  "reason": "创建任务"
}
```

结果：

- `generate_task` 混入 `tool`
- `task_content` 不符合两段式
- `protocol` 失败
- 直接排最后

### 2. Teacher Ranking

通过 hard gate 后，使用一个 teacher 同时评估同一组 candidates 的三个维度：

- `environment`
- `action`
- `args`

teacher 对每个 candidate 给出三维打分：

- `environment_raw_score`
- `action_raw_score`
- `args_raw_score`
- `reason`

取值范围固定为 `[0, 1]`。

这些分数的目的不是直接充当最终 reward，而是先形成每个维度内的相对排序。

#### `environment`

权重：

- `environment = 0.5`

只判断 candidate 是否 grounded in 当前可见 state。

必须遵守：

- 只能依据当前可见的 `USER_INPUT / ENVIRONMENT_JSON / SKILLS_INDEX`
- 不允许使用 hidden facts
- 不允许根据不可见 `track` 脑补细节
- 不允许忽略已经显式可见的环境事实
- 不允许和显式环境事实直接冲突

重点检查：

- `running`
- `failed`
- `history_summary_latest`
- `history_meta_summary`
- `previous_failed_task`

排序原则：

- 更好利用显式环境事实的 candidate 排前面
- 编造 hidden facts 的 candidate 排后面
- 和当前环境直接冲突的 candidate 明显降级
- 当前信息不足时，保守补观察优先于臆造结论

#### `action`

权重：

- `action = 0.3`

只判断下一步动作方向是否正确。

必须检查：

- 当前更应该 `observe` 还是 `generate_task`
- 如果是 `observe`，`tool` 是否合适
- 如果是 `generate_task`，`task_type` 是否合适

排序原则：

- 动作大方向更正确的 candidate 排前面
- 同为 `observe` 时，tool 更贴合当前状态的 candidate 排前面
- 同为 `generate_task` 时，task_type 更贴合当前目标和状态的 candidate 排前面
- 明显重复 observe、重复派发、或忽略当前已在运行任务的 candidate 降级

#### `args`

权重：

- `args = 0.2`

只判断动作内部内容质量。

必须检查：

- `observe.args` 是否最小且充分
- `build_context_view` 参数是否有明确目的
- `previous_failed_track` 是否保持空参数对象
- `generate_task.task_content` 是否具体、可执行、与当前 state 对齐
- `generate_task.task_content` 是否编造了环境里没有的细节
- `task_content` 是否保持两段式

排序原则：

- 参数更准确、更克制、更有执行价值的 candidate 排前面
- `task_content` 更具体、更可执行、更贴合用户目标的 candidate 排前面
- 空泛、冗余、跑题、或夹带隐含事实的 candidate 排后面

`reason` 只用于解释打分依据，不单独计分。

## Final Score

先把每个维度的原始分排序，得到对应的 `rank_score`。

对长度为 `N` 的 candidate 列表，定义：

```text
rank_score = (N - rank_index - 1) / (N - 1)
```

固定：

- `alpha = 0.9`
- `environment_weight = 0.5`
- `action_weight = 0.3`
- `args_weight = 0.2`

并按下面的方式混合“排序分”和“原始分”：

```text
environment_score =
  alpha * environment_rank_score +
  (1 - alpha) * environment_raw_score

action_score =
  alpha * action_rank_score +
  (1 - alpha) * action_raw_score

args_score =
  alpha * args_rank_score +
  (1 - alpha) * args_raw_score
```

最终总分固定为：

```text
final_score =
  0.5 * environment_score +
  0.3 * action_score +
  0.2 * args_score
```

也就是说：

- teacher 会打分
- 但打分的主要目的，是形成稳定排序
- 原始分只作为排序之外的弱修正
- 因为打分主观性更强，所以 `alpha` 固定取 `0.9`

group 内按 `final_score` 从高到低排序。
