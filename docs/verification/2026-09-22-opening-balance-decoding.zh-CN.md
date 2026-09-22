# 期初持仓减仓解码 — 2026-09-22

> 英文规范版的中文评审副本。在既有 `codex/consolidate-r19-r32` 分支续接 `8d14bb6`。未创建或切换分支。

## 范围与契约

纯函数 `decode_opening_balance_mutation` 校验单条期初持仓减仓审计，不校验整段历史。结果为不可变 `ValidatedOpeningMutation` 或 `UnknownOpeningMutation`，区分证据缺失、不支持版本及内容无效。验证后保留原始写入/关闭字符串；日期使用类型化不可变日期。解码器通过 `OpeningBalanceRecord` JSON 重算既有哈希，保留存储 UTC `+00:00` 与 DTO `Z` 的区别。校验固定字段、元数据绑定、正操作数量/交易单位、准确余额/版本算术及一致的关闭状态。

固定双快照记录的详情预算明确为 16384 个 UTF-8 字节，在解析前检查字符/字节上限。期初持仓/实体 ID 按既有减仓查询语义限制为 36 字符；确认 ID 采用保守的 128 字符读取上限。时间戳限制为 64 字符，哈希准确为 64 个小写十六进制字符。重复键、非标准数字常量、强制转换、畸形 Unicode、过深嵌套及多余/缺失字段不能成为有效证据。解析器复用既有严格基础函数，不修改批次解码器，不引入通用框架/依赖。

这些是局部读取上限，不是新的写入限制或未来确认成员清单预算。继续支持当日可卖、非 UUID ID、非整百原始/剩余数量、不同交易单位及迟报/倒序来源日期。不虚构全局数量/版本公式或写入/关闭/有效时间顺序。SHA-256 检查用于内部一致性，不认证可写数据库者提供的数据。不引入数据库访问、修改、迁移、行情源调用、通知、生产消费者或回放权限。

## 测试先行与独立审查

主任务在模块存在之前编写对抗性单元测试；独立的 `gpt-6-astra` / `high` 子任务编写实际写入/数据库重开测试。两者初始运行均以预期的模块缺失收集错误失败。实现后通过 71 项单元测试和 10 项集成测试。合并运行暴露了既有 pytest 加载方式下测试模块同名冲突；将集成文件重命名为 `test_opening_balance_evidence_roundtrip.py`，未改变测试配置或跳过覆盖。

独立上下文设计及最终审查使用 `gpt-6-astra` / `xhigh`；这些设置不证明父任务的模型/推理强度。设计审查明确了期初持仓 ID 查询上限及余额为零/关闭时间的准确等价关系，实现前均已纳入。最终审查未发现必改问题。审查者另外独立检查了 1000 条不同交易单位、版本及时区偏移的写入形状变更，以及 357 次畸形字段替换，没有异常逃逸。按用户此前选择，继续跳过额外跨模型审查。

单元测试覆盖输出不可变、输入不变、严格元数据、畸形 JSON、准确 UTF-8 预算、旧版/版本区分、重新计算哈希后仍需满足的不变量，以及原始 UTC 与 DTO 哈希。集成测试覆盖真实持久化部分/完整减仓、自定义 ID、不同交易单位、当日可卖、非单调日期、引擎重建、旧行不变和错误范围。持久化状态比较确认解码不修改存储；引擎重建不是实际进程重启验收。

## 已执行验证

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_opening_balance_evidence.py -q --tb=short` | 71 passed；0.41 秒 |
| 独立实际写入/重开集成选择集 | 10 passed，1 项既有警告；2.29 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py tests/unit/test_position_lot_evidence.py tests/integration/test_position_lot_history.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py -q --tb=short` | 328 passed，1 项既有警告；17.73 秒 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 新源码/单元测试文件格式化后通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照和前端类型仍为最新 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3734 passed，4 项既有失败，1 项既有跳过，4 项 live 未选中，1 项既有警告；478.00 秒 |

最终回归包含全部 81 项新增用例，没有新增失败。四项基线失败保持不变：指数头更新时间（10:36 与 10:38）、待处理收盘指数错误的参考行情健康状态（LIVE 与 BLOCKED）、行情源 TIMEOUT 与 TRANSIENT，以及 R14 模拟请求缺少必填 temperature、在到达模拟传输前被拒绝。本次不修复或豁免这些问题。未改动的重型回测文件及真实行情源测试不在本轮范围内；不宣称全套或最终验收通过。既有跳过是 Windows/POSIX 所有权边界；警告为 Starlette/httpx 弃用提示。

成对标题/技术字面量一致性及暂存内容空白检查通过。对全部 9 个变更文件执行限定范围的高置信敏感凭证模式扫描，未发现匹配，不代表完整凭证审计。既有源码/测试未改动；未减弱、删除或新增跳过测试。增量在同一分支保存于本地，不推送或部署。

## 剩余工作

本步骤只完成期初持仓减仓的单条记录解码。确认和自动持仓变更收据解码器仍需明确外层/嵌套预算及字段级契约。持久化来源/链条/当前行/发布校验与历史完整性策略仍属独立工作。期初持仓创建内嵌于确认证据，没有独立根发布；不能直接照搬单批次证明规则。风险来源有效日期、安全顺序执行、发送准入、生命周期/状态/UI 集成及实际进程重启验收仍阻止 RR009/C2 和第 3 阶段完成。不包含推送、合并、部署或生产切换。
