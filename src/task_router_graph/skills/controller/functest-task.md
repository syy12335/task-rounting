# Funtest Task Reference

定位：`functest` 用于功能测试、协议行为检查、字段校验、断言验证。

## 常见情况

- 做一次功能测试
- 再跑一次功能测试
- 检查某个协议是否符合要求
- 验证 headers / body / assert

## 最小信息要求

生成 `functest` 的 `task_content` 前，controller 至少应知道：

1. 测试对象是什么
2. 核心协议或配置是什么
3. 当前重点关注哪些部分（headers / body / assert / response）

## 信息不足时优先 observe 什么

优先级建议：

1. `functest-task.md` 自身
2. 当前协议的配置或 reference
3. 最近一次 functest 相关输出
4. 当前目录下相关测试产物

## 何时可以 generate_task

当以下条件满足时，可以生成 `functest` task：

- 已明确是功能测试，而不是结果解释
- 已知测试对象
- 已知测试的关键关注点
- 不再缺少生成 task 的关键上下文

## `task_content` 写法

推荐写法：

- 针对 anthropic_ver_1 执行功能测试，重点检查 headers、body 与 assert
- 基于现有配置执行功能测试，重点验证协议字段与断言结果
- 对目标请求执行功能正确性检查，重点关注返回结构与断言是否通过

不推荐写法：

- 做一个功能测试
- 跑一下试试
- 根据情况执行 workflow
