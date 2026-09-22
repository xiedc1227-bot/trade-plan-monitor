# 恢复读取器事务归属 — 2026-09-22

> 英文为规范输入，本文件为中文审阅副本。接续 `2536856`；属于隔离安全修正，不代表任意时段重启验收通过。

## 范围与根因

`LegacyCloseRecoveryReader` 和 `LegacyAlertOriginReader` 只检查 Session 状态是否全新，没有检查底层绑定。全新 Session 仍可借用另一写入者的 Connection，读取其未提交证据。单批次读取器此前已拒绝该配置。共享 `require_owned_recovery_session` 预检现将同一策略应用于三个读取器，不改变证据解释、哈希、身份、数据库结构或生产默认行为。

要求会话全新，默认绑定为 SQLite Engine，且每个证明模型的 mapper/表级查询绑定都解析到同一 Engine。在进入上下文或执行 SQL 前拒绝无效工厂，校验位于证据验证异常处理之外。拒绝不刷新、提交、回滚或关闭调用方持有的状态。普通存储错误仍直接传播，无效存储内容仍遵循各读取器既有未知规则。应用的文件数据库引擎及显式 BEGIN 钩子仍是前提；这不认证任意引擎、恶意 Session 重写或数据库真实性。

SQLAlchemy 文档说明了[参与外部事务](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)和 [mapper/查询绑定解析](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.get_bind)。这些支持上述绑定边界，不意味着全新 Session 本身就能认证已提交数据。依赖及引擎钩子不变。

## 测试先行证据

独立测试编写使用 `gpt-6-astra` / `high`。独立方案与最终源码/测试评审使用 `gpt-6-astra` / `xhigh`；这些设置不证明主任务使用的模型/强度。按用户此前选择，继续跳过额外跨模型评审。

复现先删除收盘/提醒证据并提交，再在写入事务内恢复证据但不提交。普通独立读取器正确看到 `ABSENT` 或 `UNKNOWN`，而两个原读取器使用全新 Connection 绑定 Session 时都错误返回 `PROVEN`。针对性 RED 运行中两个用例均失败。完整新增套件修复前为 46 失败、10 通过，修复后为 56 通过（7.80 秒）。

覆盖直接活动/空闲 Connection、全部证明模型的 mapper 和表级路由、指向同一数据库文件的两个 Engine、未绑定会话、调用方活动/待新增/脏状态以及合法同引擎路由。拒绝时验证零 SQL、零会话生命周期副作用。真实未提交证据用例额外证明调用方之后仍能成功提交。既有单批次回归保留外部事务回滚和不同数据库覆盖。既有并发提交测试保留一致快照行为验证。

## 已执行验证

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_close_recovery_session_ownership.py -q` | 56 通过；7.80 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_close_recovery_evidence.py tests/integration/test_recovery_alert_provenance.py tests/integration/test_position_lot_history.py tests/integration/test_close_recovery_session_ownership.py -q` | 256 通过、1 个既有警告；36.09 秒 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 修正导入顺序和一处行长后通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照及前端类型保持最新 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3616 通过、4 个既有失败、1 个既有跳过、4 个真实调用用例未选中、1 个既有警告；501.94 秒 |

独立方案及最终代码评审在既定工厂契约下未发现可操作问题。未使用真实行情源、通知渠道、真实数据库或数据库结构迁移。最终功能运行包含全部 56 个新增测试，未观察到新增失败。四个基线失败仍是：规范指数头更新时间（10:36 与 10:38）、待补收盘的指数错误参考健康状态（LIVE 与 BLOCKED）、行情源 TIMEOUT 与 TRANSIENT，以及 R14 模拟请求缺少要求的 temperature，因而在假传输前被拒绝。本增量不豁免也未修复它们。未重跑未改动的重型回测文件；这不代表完整套件或最终验收通过。既有跳过为 Windows/POSIX 所有权边界，警告为 Starlette/httpx 弃用提示。

对成对标题/技术字面量检查时，规范化有意指向另一语言副本的链接后通过；暂存区空白检查通过。针对全部 11 个变更文件的高置信度密钥模式扫描未命中，但这不是全面凭证审计。本次未跳过、删除或削弱任何测试。修正保存为单个本地增量，远端同步另行进行。

## 剩余工作

这三个读取器已关闭已识别的事务绑定缺口。RR009/C2 仍未完成：期初持仓和持仓确认历史、完整历史持仓、风险来源有效时间语义、证明预算和安全顺序执行仍需实现。渠道最终准入、生命周期/状态/页面集成和真实进程重启验收仍是独立门禁。本次不包含推送、合并、生产默认切换或部署。

另一次只读 `gpt-6-astra` / `xhigh` 调研确定下一写入增量范围：保存完整确认行的前后状态、本次新建期初持仓、已接受的期初持仓减仓日期及交易单位，以及批次买入、批次减仓、期初持仓减仓对应的持仓 revision/确认同步。当前确认行会被覆盖；自动同步修改数量但不保存每个中间状态，所以只增加减仓日期仍不足。既有严格批次证据版本 1 不得追加未预期字段；额外持仓事实使用独立持仓审计作用域。全部证据仍在既有事务内，保留准入、原哈希/事件及旧审计字节。这是下一步建议，不代表已实现历史或已批准回放策略。历史完整性截止点、延迟/逆序登记和旧证据缺失，仍须在消费前明确契约。
