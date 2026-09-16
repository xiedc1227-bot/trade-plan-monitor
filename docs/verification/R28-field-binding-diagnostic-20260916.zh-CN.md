# R28 字段绑定契约与安全诊断验证

英文原版为 `R28-field-binding-diagnostic-20260916.md`，本文是等价中文审阅副本。状态 **OFFLINE_COMPLETE / PROSPECTIVE_DIAGNOSTIC_FIXED / V6_CANDIDATE_ONLY / ZERO_EXTERNAL_CALLS**。

## 范围与证据边界

R28 在不重放 R27 的前提下排查了 R27 终态 `INVALID_OUTPUT / schema / SCHEMA / field_bindings[4] / value_error`。本轮没有 DeepSeek POST、行情调用、claim、激活、交易或业务数据写入。已保留的 R27 证据排除了原始响应和验证器消息，因此 R28 无法识别历史上究竟违反了哪条 `FieldBinding` 不变量。下述合成失败只证明原有诊断碰撞及前瞻修复，不是对 R27 第五个绑定的还原。

## 验证器与提示词审计

`FieldBinding` 模型强制六类不同的跨字段不变量，但 Pydantic 过去把每类失败都报告为同一个通用 `value_error`。生成的 JSON Schema 不包含这些模型验证器。`plan-extract-v5` 规则 5 和 6 从高层描述了来源归属、契约限制与结构绑定，但没有明确互斥引用字段、唯一条款引用和绑定身份、完整单位映射、`STRUCTURE` 值限制，以及提取信封不含持久 `user_supplements` 的事实。

| ID | 强制不变量 | 前瞻安全 `schemaErrorType` |
|---|---|---|
| R28-FB01 | `clause_ids` 不得重复。 | `field_binding_clause_ids_not_unique` |
| R28-FB02 | `SOURCE` 的 `clause_ids` 非空，且 `supplement_id` / `contract_id` 为 null。 | `field_binding_source_reference_invalid` |
| R28-FB03 | `USER_SUPPLEMENT` 的 `clause_ids` 为空、`supplement_id` 非 null、`contract_id` 为 null。 | `field_binding_user_supplement_reference_invalid` |
| R28-FB04 | `CONTRACT` 的 `clause_ids` 为空、`supplement_id` 为 null、`contract_id` 非 null。 | `field_binding_contract_reference_invalid` |
| R28-FB05 | `CONTRACT` 只指向有效技术标量或 `.rule_id`；schema 校验不再接受不可到达的对象路径 `metadata`。 | `field_binding_contract_path_forbidden` |
| R28-FB06 | `STRUCTURE` 绑定值只能是 `ALL` 或 `ANY`。 | `field_binding_structure_value_invalid` |

schema 校验之后，服务端映射校验继续保持失败关闭：它针对当前类型化草稿解析每个路径；要求 `STRUCTURE` 指向条件对象、`VALUE` 指向标量；检查精确 JSON 类型/值与按路径推导的单位；检查 SOURCE 条款存在、处于 `MAPPED` 状态且路径双向对应；拒绝把来源处理当作交易参数；检查持久 USER_SUPPLEMENT 完全一致；并限制 CONTRACT 路径。缺少标量/结构绑定及未双向对应的已映射条款仍形成服务端复核阻断项，不会补造执行语义。

## 已实施修正

每个 `FieldBinding` 自定义验证器现在都会抛出固定的 `PydanticCustomError` 类型。提取边界只允许上述六个固定类型；任何未识别的自定义类型仍回退为 `other`。读取 Pydantic 错误时依然排除 input、context 与 URL，结果序列化和 sidecar 都不保存异常正文或供应商内容。

sidecar 继续使用版本 `2`：没有新增、删除字段，也没有把字段改为必填。既有可空 `schemaErrorType` 字段现在允许更多固定值。历史 v1/v2 记录与冻结的 R27 记录保持不变；当前 R27 风格读取器本来就只复制该字段，不解释不受信任文本。

新增 `plan-extract-v6` 作为显式候选，并复用未变化的 `PlanExtractionOutputV4` schema 哈希。它通过规则 12–14 明确来源引用矩阵、唯一身份、禁止 AI 生成 USER_SUPPLEMENT 绑定、标量/类型/值/单位规则、`ALL|ANY` 结构规则及 SOURCE 双向映射。默认值仍为 `plan-extract-v5`；`config/app.yaml`、R25/R27 提示词字节、哈希、审阅包和历史记录均未修改。未来任何外部请求若选择 v6，提示词字节就会变化，因此必须重新展示精确载荷并取得明确批准。

## 离线验证

修复前，六个合成最小输出都产生 `field_bindings[0] / value_error`，复现了诊断碰撞。修复后：

- R28 聚焦测试 `10/10` 通过，覆盖六个固定映射、sidecar/结果不泄漏、未知代码回退、合法绑定接受、v6 契约、冻结的 v6 字节和 v6 映射解析器；
- 提示词、提取与显式复核回归测试 `102/102` 通过，另有一个既存 Starlette/httpx 弃用警告；
- 没有跳过或放宽测试，也没有删除或放宽验证器。

最终组合回归、Ruff、格式与差异检查记录在 R28 交接中。

## 最小未来真实验证建议

不得自动开始。未来候选只回答一个问题：固定的精确 `LITERAL` 原文配合重新审阅的 `plan-extract-v6` 提示词，能否到达 `SUCCEEDED`、通过字面 oracle 并保持仅供复核。最多允许一次 AI POST、零重试、零行情调用，不探测余额/模型列表，不持久化或激活计划，也不执行交易。必须冻结原文、提示词、请求体、目的地、模型别名、Token 上限、temperature、thinking 模式、response format 和停止规则；派发前立即复查当前官方路由与价格。

成功要求 `completed / NONE`、模型匹配、存在时已验证 usage、字面 oracle 接受、一个内存复核回执以及业务表零写入。任一供应商错误、超时、非 stop 结束、JSON/schema/映射失败、oracle 不匹配、诊断缺失、隔离失败或回执不确定均立即停止且不重试。未来 schema 失败现在可以前瞻性标识 R28-FB01–R28-FB06 之一；`other` 仍是安全回退。任何未来结果都不能追溯识别已被排除的 R27 响应。
