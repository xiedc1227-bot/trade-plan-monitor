# R17 契约修复与失败定位

## 1. 范围与证据

本文是 `R17-execution-20260914-afternoon.md` 之后的离线修复记录，不是另一次真实验收。原 R17 证据与业务验收失败结论仍然有效。未新增 AI 或行情供应商请求，未复用一次性授权，未修改生产数据库或凭据。保留了原有 12 项 tracked 改动及四份 R00 untracked 文档。

## 2. 已确认的契约修复

- 后端已返回 `diagnosticStatus`，但客户端字段白名单及过期的 OpenAPI/TypeScript 生成文件未包含它。客户端现接受省略/null，以及准确的 `RECORDED` / `WRITE_FAILED` 枚举。非法值和无关未知字段仍被拒绝。
- 保存的三份 R17 HTTP 200 响应现在可以原样通过实际 TypeScript 客户端，保留真实的 `PROVIDER_ERROR` / `INVALID_OUTPUT` 终态；响应被接受不代表提取成功。
- 状态 GET 失败时保留已受理操作及最后已知状态。新增重新查询按钮，仅对同一操作发起 GET，不会再次提交付费提取。用户明确停止本地等待时释放编辑器，不声称服务端任务已取消。
- 使用实际后端序列化器另复现了一处成功响应差异：v4 部分草稿允许零个字段映射，客户端却要求至少一个，且上限也不同。现已与后端的 0–10,000 范围一致。序列化的合成样本仍含阻断激活的审核问题。Python 样本一致性检查与 TypeScript 消费测试共同保护此契约。

## 3. 日历定位

R17 审计记录恰好一次 `trade_cal` 物理尝试，联网前额度拒绝为零。即使没有活动计划，运行时启动也会先获取 SSE 日历。因此，计划库为空不能解释日历请求为什么失败；它能解释为什么后续没有计划求值或激活。

失败位置在启动参考数据刷新链路：请求准入/传输/归一化、当日数据可用性检查，或参考数据持久化。旧组合层将所有异常统一成 `REFERENCE_REFRESH_FAILED`。保留的健康响应、审计及空参考表无法区分这些路径，不能据此认定历史请求的根因是 token、额度、网络、响应 Schema 或数据库。

修复后的组合层在供应商健康状态及不含内容的警告中保留有界类别：

| 类别 | 含义 |
| --- | --- |
| `REFERENCE_BLOCKED_PERMISSION`、`REFERENCE_RATE_LIMITED`、`REFERENCE_TRANSIENT`、`REFERENCE_TIMEOUT`、`REFERENCE_INVALID_RESPONSE`、`REFERENCE_ERROR` | 已有的安全请求控制器结果；不复制供应商文本 |
| `REFERENCE_QUEUE_FULL`、`REFERENCE_CLOSED` | 本地请求准入/生命周期结果 |
| `REFERENCE_DATA_UNAVAILABLE` | 请求已完成，但缺少可用的当日日历/参考历史数据 |
| `REFERENCE_STORAGE_ERROR` | 参考数据持久化抛出 SQLAlchemy 错误 |
| `REFERENCE_REFRESH_FAILED` | 其他尚未分类的异常；不作推测性解释 |

请求控制器提供 `nextRetryAt` 时保留该元数据；这不会增加重试策略。参考刷新成功后清除旧参考错误及重试元数据。权限、限频、暂态、超时、响应、准入、缺数据、存储、一般错误及恢复路径均有离线覆盖。新增诊断不记录异常文本、堆栈、原文、token 或供应商正文。

## 4. 提取定位

- **LITERAL：**保留结果是供应商阶段一次尝试后超时，模型响应尚未进入解析。这不能证明 JSON 或映射解析器失败。离线实际适配器测试保留 30 秒配置及零重试，注入传输超时，确认一次尝试、无草稿、无用量及无敏感异常文本。它不能确定历史请求远端延迟的原因或计费。
- **SEM-AMB-01 / SEM-UNS-01：**模型返回 `finishReason=stop`，通过 JSON/Schema 解析后，在原文/当前草稿映射边界失败。旧诊断只有 `MAPPING / unknown`，且未保留模型原始输出，因此无法还原具体错误字段。
- 映射失败现可保留服务端构造的位置，例如 `source_clauses[0].excerpt`、`.start`、`.end`、`.clause_id`，或 `field_bindings[0].path`、`.unit`、`.value`、`.origin`、`.clause_ids`。领域模型校验保留安全的 Schema 路径/类型。索引仍有上限，不回显不可信字段路径或内容。已有原文证据检查继续执行。
- 另发现一项离线缺陷：`STRUCTURE` 映射指向标量时会抛出 `AttributeError`，可能被误报为供应商失败。现会返回 `INVALID_OUTPUT` 并标识映射字段位置。这是独立复现的缺陷，不能认定它就是历史两份 R17 输出的问题。

## 5. 验证

除特别注明外，命令从 `trade-plan-monitor/` 执行。新增行为回归均在对应修复前证明失败。

| 检查 | 结果 |
| --- | --- |
| `npm --prefix web test -- --run` | 665 项通过 |
| `npm --prefix web run type-check` | 通过 |
| `npm --prefix web run build` | 通过；更新浏览器产物及 Python 包内网页资源 |
| `npm --prefix web run test:e2e -- tests/e2e/ai-diagnostic-contract.spec.ts` | 真实 Chrome、本地拦截响应的 3 项通过；无外部请求或重复 POST |
| Python 定向回归测试 | 覆盖 134 项不同检查：初次 133 项通过，中英文规格指纹过期一项失败；同步两份规格后，重跑的 14 项 OpenAPI 检查全部通过 |
| `python -m scripts.generate_frontend_types --check`、定向 Ruff 检查、`git diff --check` | 通过 |
| Python 完整测试，`python -m pytest -m "not live" -q` | 运行超过十分钟后，在额外的十只股票/252 日回测容量测试期间中止；此前未报告失败断言，但不声称完整测试通过 |

Python 定向范围包含 `test_r17_failure_diagnostics.py`、`test_ai_plan_extraction_v4.py`、`test_ai_diagnostics.py`、`test_ai_browser_contract.py`、`test_ai_provider_contract.py`、`test_r15_extraction_diagnostics.py`、`test_certified_production_runtime.py`、`test_monitor_production_composition.py`、`test_explicit_runtime_production.py` 和 `test_openapi_snapshot.py`。没有禁用或弱化测试、容量阈值或授权保护。额外完整测试进程已停止，其他运行中进程未受影响。

浏览器验证覆盖两个诊断枚举值下的 QUEUED → RUNNING → 失败，以及非法状态响应后的查询恢复。这是真实浏览器配合模拟 API 响应，不是真实供应商验收。历史 R17 响应另在 TypeScript 测试中原样回放。新增成功样本明确为合成数据，并与后端序列化结果比较。

## 6. 尚存的证据边界

页面契约回归已修复。未来获准执行时，日历及映射失败能够保留更有效的诊断。由于当时未捕获必要证据，历史日历的精确错误、两份映射的具体错误字段，以及 LITERAL 超时的远端原因仍未证实。新的有界真实会话需要新的授权，不能复用 R17 一次性会话。真实提取、审核、激活、新鲜行情求值及可见 IN_APP 送达仍是单独未完成的验收条件。
