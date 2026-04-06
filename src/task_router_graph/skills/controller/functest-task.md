# Funtest Task Reference

## Definition

`functest` 用于功能测试、协议行为检查、字段校验与断言验证。

## Common Scenarios

- 执行一次功能测试
- 重新执行功能测试
- 校验协议是否正确
- 验证 headers / body / assert

## Minimal Information Requirements

在生成 `functest` task 前，controller 至少应明确：

1. 测试对象是什么
2. 相关协议或配置是什么
3. 核心关注点是 headers、body、assert、response 或 behavior

## What to Observe First When Information Is Insufficient

优先级：

1. `functest-task.md` 本身
2. 协议配置或协议 reference
3. 最近一次 functest 相关输出
4. 当前 run 目录下相关文件

## When It Is Safe to Generate Task

仅当以下条件成立时生成 `functest` task：

- 当前请求是执行功能测试，而不是解释结果
- 测试对象已明确
- 核心关注点已明确
- 不再缺少生成任务所需关键上下文

## Task Content Patterns

Preferred patterns：

- 针对 anthropic_ver_1 执行功能测试，重点检查 headers、body 与 assert
- 基于当前配置执行功能测试，重点验证协议字段与断言结果
- 对目标请求进行功能正确性检查，重点关注 response 结构与 assertion pass/fail

Disallowed patterns：

- run a test
- try it once
- execute a workflow depending on the situation
