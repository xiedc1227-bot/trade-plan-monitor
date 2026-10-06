# 空 WAL 启动恢复验证

## 范围

修复空 `backtest-market.sqlite3-wal` 与残留 `-shm` 导致的本地 Web 启动错误 `SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT`。行情库、结果库与任务存储构造器共用启动恢复边界。无需修改依赖或数据库结构。

## 恢复边界

- 要求主文件存在且为有效 SQLite 文件、`-wal` 为空，且不存在 `-wal`/`-shm` 以外的伴随文件。
- 恢复前检查不可变主文件并记录全部源文件指纹。要求对应领域结构为完整当前版本，没有迁移或元数据修正原因，再重新核对指纹。
- 使用 SQLite `PRAGMA wal_checkpoint(TRUNCATE)` 与配置的 busy timeout，并关闭恢复连接。绝不手动删除文件。
- 恢复后重新执行严格预检。伴随文件仍存在、checkpoint 失败/被占用或源文件不可读时，阻止初始化。
- 迁移预检保持只读，拒绝所有伴随文件。有内容的 WAL、回滚日志、孤立文件、旧/未知结构、待扩展结构及 UTC/无效元数据均不自动恢复。

## 自动化证据

- 修复前，三个新增启动回归用例因原错误失败；三个迁移保留用例通过。
- 迁移与生产组合专项检查：`python -m pytest tests/integration/test_backtest_migrations.py tests/integration/test_backtest_production_composition.py -q` — **76 通过，1 跳过**。原有平台跳过项保持不变。
- 覆盖冻结数据集/主文件保留、行情/结果/任务存储重新打开、严格迁移预检、旧/未知/待扩展/UTC 源、不安全伴随文件、并发读写连接以及 FastAPI lifespan 启停。
- 在内存中反转当前结构的恢复条件后，三个成功恢复回归用例全部失败。变异检查未修改源文件。
- 修改的 Python 文件通过 Ruff 代码检查；实现与迁移回归文件通过 Ruff 格式检查。生产组合测试中无关的既有格式保持原样。`git diff --check` 通过。
- 离线功能测试：`python -m pytest -q -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py` — **6085 通过、1 失败、1 跳过、4 未选中**，耗时 1474.95 秒。唯一失败项为 `test_openapi_change_requires_bilingual_spec_approval`；独立复跑出现相同失败。
- 基线验证确认该失败早于启动修复：`HEAD:openapi.json` 与未修改的当前快照哈希均为 `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`，但 `HEAD` 中两种语言的规格均记录 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`。本修复未修改 API 快照或规格批准记录。
- 初始完整离线测试在十只股票、每只 252 个交易日的容量基准中停止。当时未报告失败；这不代表容量/性能验收已完成。未修改任何测试、阈值或标记来绕过该项。

## 本地恢复证据

先用本地行情库副本验证恢复成功，再在准备实际回测库前将两个数据库备份到 `data/startup-recovery-20261006-9135cf8e/`。两个库现在均通过检查，状态为 `CURRENT`，伴随文件数量为零；SHA-256 比较确认两个主文件与恢复前逐字节一致。备份属于被忽略的运行时数据。

## 限制

生产回测组合与 lifespan 使用临时数据库及注入的离线监控运行时验证。未启动已配置的真实监控或外部供应商。容量验收仍未完成，且既有 OpenAPI 批准记录失败意味着不能宣称整个测试套件全绿。现有 FastAPI 测试客户端弃用警告与本修复无关。
