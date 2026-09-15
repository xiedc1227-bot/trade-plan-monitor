# R19 AI 输出截断修复——离线验证

英文原版为 `R19-output-truncation-remediation.md`，本文是等价中文审阅副本。状态 **OFFLINE_PASS / REAL_PROVIDER_NOT_RUN / BUSINESS_ACCEPTANCE_STILL_FAILED**。

## 诊断

保留的 R18 重启证据确认：向已配置的 `deepseek-v4-pro` 发起一次受控 `LITERAL` 请求，结果为 `finishReason=length`、提示 5,077 Token、完成 4,096 Token、合计 9,173 Token。没有创建草稿、映射、复核、保存、激活或监控记录。应用配置与历史 R18 启动器都显式选择了 4,096 输出 Token。这足以把“达到已配置上限后的输出截断”确定为直接失败原因；但不能证明供应商是否也触及上下文边界。

公开适配器只保留提示/完成/总用量及脱敏停止原因，没有保存原始响应内容或 `completion_tokens_details.reasoning_tokens`。请求显式关闭思考，因此没有证据表明隐藏推理消耗了上限，但可见 JSON 与推理的准确拆分仍未知。历史 R17 的供应商及映射原因也继续未知。

DeepSeek 当前 Chat Completions 文档把 `finish_reason=length` 定义为达到请求 Token 上限或上下文长度，列出非思考模式默认 8K，并建议为 JSON 输出设置合理的 `max_tokens` 以避免中途截断：

- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/json_mode/

## 修复

- 新的省略配置使用有界 8,192 Token 默认值；硬上限仍为 16,384。已离线验证实际 DeepSeek profile 请求体包含 `max_tokens=8192`、`thinking={"type":"disabled"}` 和 JSON 输出，网络调用为零且未暴露密钥。
- 新提取使用不可变 `plan-extract-v5`。它与 v4 共用 Schema 摘要 `9461d3099a923e5f9fe172eeba010e0dbe44cbe9d8f93c9465be9626d08965a1`，要求压缩 JSON，只允许省略顶层空 `assumptions`/`warnings`，黄金提示词摘要为 `8ec7e564eb9348ca6c00acee92405222b6ad13423da95dcc1b4fb167252cf4d6`。V4 黄金摘要保持 `e91f6b32a69a60b1f35da3e5deee5acd17d326cecd0efcadd2aa99bdb36b4eb7`。
- `finish_reason=length` 现在返回 `INVALID_OUTPUT`、固定代码 `AI_OUTPUT_TRUNCATED` 和文案 `AI output was truncated before completion; no draft was created.`；不返回草稿或映射，诊断继续记录阶段 `response`、原因 `FINISH_REASON`。
- V5 继续兼容既有封闭映射、权威复核、不可变保存和显式激活边界。不会自动修复输出，也不会自动激活计划。

读取被 Git 忽略的真实 `config/app.yaml` 时未输出密钥，也未修改该文件；其显式输出上限仍为 4,096。8,192 是安全的代码/示例默认值，不是对用户配置的静默覆盖。

## 离线证据与限制

- 聚焦后端及生成契约套件：**173 项通过**，另有一个既存 Starlette/httpx 弃用警告。范围包括供应商请求格式、提示词不可变性、v4/v5 解析、显式复核/激活、配置、供应商契约、已配置 Web 组合及 OpenAPI 确定性。
- R19 聚焦项加公开复核/激活集成：**9 项通过**。来源忠实的 15 条款/23 绑定字面夹具在允许省略空列表后完成往返：UTF-8 从 7,819 降至 7,788 字节，草稿与映射完全一致。这些是序列化字节，不是 Token 估算。
- 历史 R14/R17/R18 边界及受控离线接线套件：**55 项通过**；其生成测试配置显式固定冻结的 `plan-extract-v4`，未改变任何已消耗启动器或占位。
- 浏览器恢复单元切片：**33 项通过**。查询失败后保留一次已接受操作；一次 POST 后恰好执行两次 GET 恢复，绝不重新提交付费任务。
- 定向浏览器测试后，前端类型检查与生产构建均通过。
- 一条 v5 集成路径先激活既有已复核计划，再运行合成 `finish_reason=length` 提取，确认无草稿/映射，然后读取完全未变的活动状态。

R19 未发起任何外部 AI 或行情请求，未发送 webhook、未交易、未修改真实数据库，也未改变凭据/真实配置。这些检查证明契约行为，不证明真实供应商必然在 8,192 Token 内完成或语义一定正确。因此，在另行授权候选端到端成功之前，业务验收仍失败。
