# 运行恢复：完整流程验收证据

> IN PROGRESS — 业务第 1 步尚未验收。本报告按完整成果累积证据，不为每个辅助组件另立完成里程碑。不代表生产恢复或部署批准。

## 有界流程接通 — 2026-09-23

基线版本：`ac9da66705829d5da769af616363533f2f6caf7a`，分支为 `codex/consolidate-r19-r32`；检查覆盖尚未提交的接通修改。可选的 `LegacyHistoricalCloseReader` 和 `HistoricalOfficialContextBuilder` 从一次有界自有快照向既有收盘评估器提供输入。历史风险使用可归因的来源收盘时间；提交结果保存准确的已证明历史批次。D2 登记的人工卖出减少 D2 数量，但即使其生效交易日为 D1，也不减少 D1 数量。补算产生的两条风险提醒均从 `HOLD` 开始。

真实临时 SQLite 场景用 200 股提交 D1，重开后用 100 股提交 D2，再次重开仅得到重复结果。结果保存前和提醒插入后模拟退出，会一起回滚占用、结果、风险及投递资格。提交后发布失败保留唯一持久结果。并发持仓/风险变化、全局发布、旧激活，以及保护核对后占用前插入的写入，均拒绝过期输入。乱序 D2 不留下待收盘标记。持仓/日历资料不足及先前受阻结果不能被占用。旧版批次模型无法表达的期初持仓保持不可用，不会从评估数量中消失。

- 修复审计前驱问题前：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_historical_close_evidence.py tests/integration/test_recovery_activation_fences.py tests/integration/test_close_recovery_evidence.py tests/integration/test_close_recovery_session_ownership.py tests/unit/test_missed_close_recovery.py tests/integration/test_position_inventory_history.py tests/integration/test_inventory_history_boundaries.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_sqlite_repositories.py tests/integration/test_certified_production_runtime.py -q --tb=short` — 469 通过、1 项既有 Starlette/httpx 警告，80.93 秒。
- 新的只读 `gpt-6-astra` / `xhigh` 评审确认了期初持仓和缺失日历问题，随后复现物理版本大于 1 时本激活首条风险变更缺少前驱审计连接。每一项均先有专项失败测试，再补保护/连接。先前 `BLOCKED_DATA` 记录也由失败测试证实后改为未知。
- 评审修复后：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_historical_close_evidence.py tests/integration/test_recovery_activation_fences.py -q --tb=short` — 64 通过、1 项既有 Starlette/httpx 警告，17.03 秒。既有 OpenAPI/前端类型快照检查通过。未使用真实行情源、发送器、生产配置、用户数据库迁移或部署。
- 单计划共享指数顺序修复：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py -q --tb=short` — 17 通过，4.86 秒；无效的较晚目标不会准备指数，已有占用的目标保留原有重复入口行为。
- 修复后受影响回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_recovery_activation_fences.py -q --tb=short` — 75 通过、1 项既有 Starlette/httpx 警告，14.75 秒。源码修改后 Ruff 与 `git diff --check` 均通过。一次有界只读复查未发现该单计划预检存在必改问题。

V1a、V1b 基础已完成。V1c、RR009 和业务第 1 步仍未完成：当前使用方仅覆盖激活起最多 32 个自然日，且无法评估历史期初持仓。仍需生产协调器接入、更完整的进程重启/故障覆盖，以及解决先前记录的 4 项全量测试失败。单计划共享指数路径现已预检尚未占用的目标；多计划批处理在生产集成前仍需逐计划时间顺序准入规则。本报告不表示任意时段重启或投递安全已经完成。

## 此前范围 — 2026-09-22

基线版本：`1f50439`，分支为 `codex/consolidate-r19-r32`；下述命令测试了包含 `state/inventory_evidence.py`、`state/position_inventory_history.py`、四个新测试文件、模型索引及仅新增索引的迁移 `0021_inventory_history_index` 的工作区修改。更新了既有最新迁移版本断言，未改变历史迁移目标。此前仅调整流程的计划/任务表修改仍在范围内，作为独立文档修改。未改变依赖、规范哈希、通知行为或生产默认值；未迁移用户数据库。

确认和自动持仓变更记录现在共用有界一致性解码器。真实写入到解码用例覆盖确认缺失/过期/同步、原始 UTC 表示、复用确认 ID、零股余额/可变交易单位及回滚/重开。故意允许解码尚未提交的记录；解码不是已提交历史证明或回放许可。

完整读取器已在一次自有 SQLite 快照中，证明包含登记时间等于截止点的已登记持仓。它消费连续版本回执、来源变更及发布，核对确认当时的成员，并将重建末态与包含已关闭持仓的全部当前记录比较。批次和期初持仓保持独立。已落实用户批准规则：没有人工确认就不减仓；较晚登记的回溯卖出不改变此前仓位。没有确认的已证明登记账本，不代表完整券商账户。超过 256 项变更/成员或 8388608 字节已读取文本的历史仍返回 `HISTORY_LIMIT`；无限制生产恢复仍需后续检查点/来源证明路径。

## 已执行检查

- RED：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py -q` — 新模块尚不存在，1 项收集错误。独立编写的集成测试在实现前也因相同的模块缺失而失败。
- GREEN：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py -q --tb=short` — 49 通过。首次组合运行暴露了多余的派生数据类字段，以及测试时钟对仅接受上海时区的监控发布使用 UTC；实现已改用派生元组属性，测试仅对确认写入使用 UTC，保留覆盖而不改变生产写入方。
- 受影响回归：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_inventory_evidence.py tests/integration/test_inventory_evidence_roundtrip.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory.py tests/integration/test_position_lot_history.py tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py -q --tb=short` — 最初 300 通过；评审修复后 305 通过，1 项既有 Starlette/httpx 弃用警告，21.73 秒。最终包含 53 项新单元用例及 19 项新真实写入集成用例。
- 读取器 RED：在 `state/position_inventory_history.py` 存在前，独立编写的测试收集失败；在 `ix_position_lot_symbol` 存在前，索引测试失败。初次实现：27 通过 / 4 失败，暴露了严格原始整数校验前的 SQLAlchemy 布尔转换。将选出的确认标志转换为整数，同时保留 SQLite 存储类型校验后修复根因；首轮完整读取测试：31 通过。
- 完整读取相关回归：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_history.py tests/integration/test_inventory_history_boundaries.py tests/integration/test_lot_history_indexes.py tests/integration/test_sqlite_repositories.py tests/unit/test_inventory_evidence.py tests/integration/test_inventory_evidence_roundtrip.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory.py tests/integration/test_position_lot_history.py tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py -q --tb=short` — 465 通过，1 项既有 Starlette/httpx 警告，48.00 秒。包含 50 项新读取/边界用例：迟到登记、零账户持仓确认、同时间变更、关闭、回滚/重开、重复读取、并发写入、借用/分离会话、缺失/孤立证据、发布顺序改变、错误原始类型、256 项接受 / 257 项拒绝、累计字节耗尽，以及保留批次的索引降级/再升级。
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts` — 通过。
- `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` — 快照/类型为当前版本。
- `git diff --check` — 通过；仅有普通 Windows 行尾提示。

不声称本次重新运行全量/浏览器测试。`2026-09-22-opening-balance-decoding.md` 中记录的 4 项既有失败仍未解决，也未豁免。最终完整门禁仍须执行。

## 评审及剩余工作

独立的 `gpt-6-astra` / `xhigh` 契约评审指出迟到登记业务选择、历史批次保存不一致和恢复写入时间导致的风险不一致。发现已记录到成对运行恢复规格，处理状态见下文。独立测试工作使用 `gpt-6-astra` / `high`。另一项只读 `gpt-6-astra` / `xhigh` 实现审查发现两项须修复问题：JSON 转义后的孤立代理字符 ID 绕过原始字节检查，以及额外的 NUL 限制拒绝写入方允许的 ID。4 项单元 RED 用例和 1 项真实写入 RED 用例复现问题。解析 ID 后严格验证 UTF-8、移除额外 NUL 限制后，两项均已修复；有界复查未发现剩余必改问题。按用户要求继续跳过额外跨模型审查；本报告不证明父任务的模型/强度。

用户已明确迟到登记选择：数量仅在人工登记时改变，不因提醒或较早生效交易日期而改变。新的只读 `gpt-6-astra` / `xhigh` 审查未发现完整读取器存在须处理的正确性/安全问题；其建议补充的覆盖（实际 256/257 边界、未来关闭时间、错误原始类型及零持仓确认）已在上述最终回归前补齐。迟到登记不再有待定决策。

有界持仓读取及其时间/来源/发布/成员证明已实现。风险重建及真实评估事务集成仍未完成。不关闭 V1a–V1c、RR009 或 C2。下一验收结果仍是一次遗漏收盘恢复后重开不增加结果/意图，再扩展跨日/故障覆盖。历史评估须保存同一份已证明的批次输入，并将风险绑定来源有效时间；仅有读取器尚不能启用这条路径。
