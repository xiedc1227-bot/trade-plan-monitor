# 任务表：任意时段重启与自动恢复

> 状态：自 2026-09-21 获得实现授权起 IN PROGRESS。英文规范输入：`runtime-recovery-todo.md`；本文件为中文副本。
> 上位提案：`runtime-recovery-plan.zh-CN.md`。原 D1–D7/A01–A12 及 D8/A13 已获批准；D9/A14 业务意图已确认，但 API 待评审。
> 后续分配遵循提案第 2 节：架构、质疑式评审及疑难故障使用 `gpt-6-astra` / `xhigh`；有界实现使用 `gpt-6-sol` / `high`，已确定内容的文档同步使用 `gpt-6-sol` / `medium`。历史执行记录保留当时实际模型/强度。检查点评审仅在实际执行后才构成证据。

## 执行规则

### 当前交付顺序 — 更新于 2026-09-24

执行遵循提案第 7.1 节。以下五项成果作为面向用户的进度口径；下方 RR 任务仍是实现/验收索引，不是额外五个阶段。顺序决策基线：`1f50439`，分支为 `codex/consolidate-r19-r32`。**业务第 1 步已于 2026-09-23 通过用户批准的限定离线三进程重启标准。** 这是有范围的验收，不代表 C0–C5 或完整发布门禁已关闭；实际证据记录如下。

| 业务步骤 | 当前状态 | 完成证据 / RR 对应 |
|---|---|---|
| 1. 历史状态恢复 | 已按批准的限定离线标准完成：三个独立进程使用已接通的生产组合和同一临时 SQLite 数据库，补齐一次遗漏的官方收盘，保留活动计划，并在再次重启后不增加结果/提醒。五天准入门禁仍在前置。高交易量证据上限及完整跨日/故障矩阵仍待完成 | 限定重启证据见成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`；不受限制的历史恢复、真实行情源验证及完整 RR007–RR010/C2/A13 发布验收另行处理 |
| 2. 提醒安全 | 已接通离线实现：生产组合原子写入初始 HOLD，并在每次渠道调用前复核已提交的身份、风险、持仓、已完成目标及恢复屏障。已有模拟渠道/重启专项证据；完整发布门禁和真实运行仍待完成 | 两类计划在模拟渠道准入前使用重新读取的风险/持仓/恢复门禁证据；过时提醒抑制，相同且适用的退出提醒只保留最新，证据不足等待；保留不确定发送处理。RR011–RR013 |
| 3. 实际启停集成 | 五天准入与定期心跳已接入生产生命周期。RR010 拒绝所捕获激活身份变化；有界 RR004/RR006/A06 修正隔离指数展示并稳定实时传输退避。类型化传输故障保留本地所有者及重试下限。生产环境于准入后绑定持久行情恢复状态，在受控跨进程重启后恢复 429 冷却，冻结初始配置，并在物理排空失败时保持数据库打开。有界只读权限探针覆盖 `TRADING_CALENDAR`、`idx_mins` 和 `rt_idx_min_daily`，各自保留持久 300 秒预约；缺少可信锚点时可见受阻。其他权限接口、更广的依赖隔离及完整关闭验收仍待完成 | 同一应用组装能从依赖不可用中恢复；配置变更需要安全停止、人工编辑并启动新进程。验收须证明冻结的启动配置、漂移后不在进程内替换、旧任务围栏以及释放所有者/存储前完整排空。RR004–RR006、RR010、RR014、C1/C3 |
| 4. 状态接口和页面 | 仅有契约草案 | 真实后端状态到达页面，区分待机/恢复中/受阻/连接异常并提供原因和重试信息；旧客户端安全失败。RR002、RR015–RR019、C4 |
| 5. 重启/故障验收 | 第一阶段限定三进程重启及第二阶段模拟渠道场景已通过；完整跨日/故障矩阵仍未完成 | 完成全部 A01–A14 场景、第 7 节全部离线门禁、迁移/回滚证据及最终独立审查；部署仍须单独批准。RR020–RR022、C5 |

主线顺序为 1 → 2 → 3 → 4 → 5。离线组装/重启测试基础提前到第 1 步，依赖重试测试随第 3 步执行，不等到第 5 步才首次运行。RR002 评审通过后，可并行准备独立的状态/客户端工作，但不能据此宣称第 4 步完成。原任务依赖仍是验收/默认启用门禁，不禁止提前测试注入式集成。

### 业务第 3 步离线测试顺序 — 2026-09-24

以下是计划中的分片，不是已完成的检查点。缺少行为时，各片先写失败的离线测试，使用临时 SQLite 和模拟行情源/渠道边界，再运行列明的专项与相邻回归文件。已批准的 `INDEX_MINUTES` 决策记录在 D4/D6；检查点迁移与两个离线端点探针已实现，真实端点认证尚未执行。不得凭单个切片关闭 C1 或 C3，也不得将本顺序视为第 4 步页面完成或第 5 步发布验收。

| 顺序 / 门槛 | 前置条件 | 最小验收 | 专项与相邻回归 |
|---|---|---|---|
| S3-01 A04 | 既有所有者/存活证据及类型化传输恢复 | 连续四次瞬态故障保留同一所有者和运行代次、本地读取可用、遵守 30/60/120/300 秒重试下限，随后由调度器提交一个精确目标；普通故障不消耗崩溃监督次数。改变重试时序前，先评审可中断的测试计时接口。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_runtime_lifecycle.py -q --tb=short` |
| S3-02 A05 | S3-01 及已批准的 D4/D6 端点范围 | 在临时 SQLite 中，旧 `INDEX_MINUTES` 经幂等/中断迁移后同时阻断 `idx_mins` 与 `rt_idx_min_daily`；各自 300 秒受控探针仅解除自身封锁。共享 429 冷却、1.25 秒节流及失败后重新封锁保持有效。不声称真实权限。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_storage.py tests/integration/test_production_certification_gate.py tests/integration/test_market_index_runtime.py -q --tb=short` |
| S3-03 C1 | S3-01–S3-02 | A01/A02/A04/A05 离线证据、有界串行请求、旧状态安全阻断迁移及独立 `xhigh` 评审；全部条件通过前 C1 保持开放。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_storage.py tests/integration/test_provider_cooldown_process_restart.py tests/integration/test_production_certification_gate.py tests/integration/test_runtime_lifecycle.py -q --tb=short`，另加下方补充命令 |
| S3-04 A03/A07/A10 | C1 及可信会话/日历证据 | 开盘前、午休、收盘后、跨日及时钟回拨选择正确目标；空/部分批次不能证明就绪，未完成收盘义务保留，封顶工作在内存有界的前提下公平推进。 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_missed_close_execution.py -q --tb=short` |
| S3-05 A06 | S3-02 及 S3-04 | 单个股票/指数故障仍让无关 Schema v1/v2 和 Schema v3 计划及展示指数推进；必需 `INDEX_*` 依赖仅阻断其计划。指数重试跨正常 OS 进程停止/重启及调度器唤醒保留，纯指数路径不发股票请求或通知。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py tests/integration/test_market_index_runtime.py -q --tb=short` |
| S3-06 A09 | S3-04–S3-05 及冻结配置 | 捕获至提交期间计划停用/替换/重激活、语义或来源漂移、停止所有权变化，均不得发布旧结果、待收盘变更或通知；仅刷新元数据不受影响。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_activation_fences.py tests/integration/test_production_certification_gate.py -q --tb=short` |
| S3-07 A08/D5 | S3-06 及既有发送准入 | 提交/发送窗口停止或被杀后，业务意图保持唯一，不确定发送处理保留。物理工作、已开始发送、持久回执和所有者心跳须在 WAL/数据库/所有者释放前排空；排空失败保留所有权并允许安全清理重试。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py -q --tb=short` |
| S3-08 A11 | S3-01 及 S3-04–S3-07 | 已安装运行时的本地读取服务报告存活、待机、恢复中或受阻，并显示原因及下一唤醒/重试；旧缓存事实和连接正常的心跳不能代表业务进展。这是提前验证最小后端状态，不代表第 4 步完整页面/协议。 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_persistent_monitor_read_service.py tests/integration/test_monitor_production_composition.py tests/integration/test_runtime_lifecycle.py -q --tb=short` |
| S3-09 C3 | C1 及 S3-04–S3-08 | 汇总 A04/A08–A11 及相关 A03/A05–A07 证据、迁移/回滚和停机矩阵，并完成独立 `xhigh` 提交/崩溃/发送评审。仍有实质故障时 C3 保持开放；C4/C5、第 4 步和第 5 步另行处理。 | `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` 与 `.\.venv\Scripts\python.exe -m ruff check src tests scripts` |

S3-03 补充矩阵：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_contract.py tests/unit/test_live_certification_profiles.py tests/unit/test_request_recovery_admission.py tests/integration/test_certified_production_runtime.py tests/integration/test_production_a04_retry_timeline.py tests/integration/test_index_permission_scope_migration.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_index_permission_process_restart.py -q --tb=short`。另运行 `tests/unit/test_monitor_runtime.py` 中的 `test_live_tushare_request_profile_is_serial_paced_bounded_and_never_retries`、`test_request_concurrency_rejects_work_beyond_bounded_tushare_queue` 和 `test_recovery_timeout_keeps_late_physical_call_serial_before_next_symbol`。成对的 `docs/verification/2026-09-25-c1-provider-recovery-evidence.zh-CN.md` 记录有界结果；C1 在最终独立复核前保持开放。

2026-09-25 的独立 C1 复核发现 P1 功能缺口：当时 `DAILY_LIMITS`、`DAILY_BARS`、`CURRENT_DAY_MINUTES`、`REALTIME_MINUTES` 与 `INDEX_DAILY` 尚无受控生产权限复核。它们的持久阻断在同端点更换 token 后仍可能锁存。双进程指数测试不能关闭 A05 或 C1；后续有界进展记录于下方，完整调度验收仍开放。

有界 S1/S2 离线修正现让官方默认 URL 客户端保留 401/403/429 状态，使既有控制器能够持久化权限阻断与共享冷却。其假 HTTP 的 RED→GREEN 证据、408/500 与 2xx 回归、58 项专项及 190 项相邻测试通过结果和独立 Sol/`xhigh` 评审，记录在成对的 `docs/verification/2026-09-25-c1-default-url-http-status.zh-CN.md`。当时独立的基线 `test_market_data.py` `requests.Timeout` 预期与未改动的 HEAD 映射冲突（`TRANSIENT` 对 `TIMEOUT`）；后续仅测试校正记录在 `docs/verification/2026-09-25-c1-timeout-test-alignment.zh-CN.md`。上述五个权限复核作用域、真实服务认证及 C1 关闭仍待完成。

`DAILY_LIMITS`、`DAILY_BARS` 和 `INDEX_DAILY` 的**纯 provider 证明**已完成并通过独立复审；离线专项 53 项、相邻 266 项测试通过（排除 14 项既有基线用例）。`DAILY_LIMITS` 在股票本地 640 字符/位安全边界下检查全市场每条原始记录，不转换为分单位。`DAILY_BARS` 与 `INDEX_DAILY` 要求准确的官方交易日身份；指数探针还保留安全的 401/403/429 控制器分类及物理请求未开始信号。成对的 `docs/verification/2026-09-25-c1-daily-permission-probes.zh-CN.md` 记录证据。生产锚点选择、五个作用域的 300 秒维护接线，以及另行发现的普通指数请求及既有指数权限复核中的 SDK HTTP 分类缺口仍开放；C1 保持 **OPEN**。

普通 `idx_mins`、`rt_idx_min_daily`、`index_daily` 请求及两个既有指数权限探针现复用一个私有安全 SDK 调用分类器。模拟 HTTP 401/403 保留各自受影响 operation 的权限阻断和 300 秒预约；429 启动共享冷却；`RequestNotStartedError` 仍表示物理请求未开始。成对的 `docs/verification/2026-09-25-c1-index-http-classification.zh-CN.md` 记录 **16 项 RED → 17 项 GREEN** 专项用例、**198 项相邻**测试通过及独立 Sol/`xhigh` 批准。五个业务权限作用域仍需接入生产维护调度；C1 保持 **OPEN**。

### 业务第 3 步 B1/B2 截至 a1eb84f 的进展 — 同步于 2026-09-27

截至 `a1eb84f268dbc5685a9e7154858753c0f4562703`，以下离线切片已完成并通过独立评审。它们更新上方历史权限缺口的状态，不代表 RUNNING/DEGRADED 自动维护完成，也不关闭 C1/C3。

- **B1 只读选择：**六作用域（`TRADING_CALENDAR`、`INDEX_HISTORICAL_MINUTES`、`INDEX_REALTIME_MINUTES`、`DAILY_LIMITS`、`DAILY_BARS`、`INDEX_DAILY`）使用有界持久证据及原始到期排序。证据最多包含 10 个 ACTIVE 计划及 366 个已结束日历日；O/F 池合计最多 3,660 个 `(S,D)` 对。重复窥视不调用 SDK，也不预约。证据：`docs/verification/2026-09-26-b1-permission-candidate-selection.md` 及其 `.zh-CN.md` 配对文件。
- **B2 持久确认：**`on_reserved` 仅在 300 秒预约提交后、探针工作启动前执行。持久化失败不推进游标；回调故障保持为脱敏的本地故障。证据：`docs/verification/2026-09-26-b2-controller-reservation-ack.md` 及其 `.zh-CN.md` 配对文件。
- **B2 轮转：**作用域并列位置及独立的 `DAILY_BARS` O/F 游标仅由持久确认推进，包括随后在 SDK 启动前中止的预约。已覆盖 O/F 交替、候选消失与空池恢复；游标仍为进程内状态。证据：`docs/verification/2026-09-26-b2-permission-candidate-rotation.md` 及其 `.zh-CN.md` 配对文件。
- **INDEX_DAILY 内部入口：**串行维护重新选择全局到期候选，响应前后检查准确的持久工作日开市锚点，并在物理启动前各阶段检查授权与日历 epoch。响应时钟回拨被拒绝。证据：`docs/verification/2026-09-26-b2-index-daily-permission-maintenance.md` 及其 `.zh-CN.md` 配对文件。
- **DAILY_LIMITS 内部入口：**同一串行边界支持显式 STOCK 语义及 legacy 认证，在需求/锚点/授权不可用时固定本地延后 30 秒，并由所有者线程检查终态需求与锚点，worker 不访问数据库。整市场日期证明不写业务缓存。证据：`docs/verification/2026-09-26-b2-daily-limits-permission-maintenance.md` 及其 `.zh-CN.md` 配对文件。
- **周末一致性：**已结束指数锚点排除错误的周末开市记录；实时指数候选要求工作日。日历权限证明仍可使用已结束的周末记录。证据：`docs/verification/2026-09-26-b2-weekend-permission-candidate-consistency.md` 及其 `.zh-CN.md` 配对文件。

DAILY_LIMITS 配对记录中的 **138 项相关离线测试通过**、全量 Ruff 及差异检查，来自上一实现批次和独立评审。本次文档同步未重跑这些测试，也不新增运行时验证结论。

下一步仍为 OPEN：经评审的 `DAILY_BARS` 消费需求与身份判定及其内部接线；股票分钟权限探针（`CURRENT_DAY_MINUTES`、`REALTIME_MINUTES`）；统一 RUNNING/DEGRADED 维护，包括 B3 无候选时 30 秒唤醒行为，以及权限工作不消耗市场截止点游标的证明；完整跨进程 C1 验收。S3-04–S3-09 仍未完成，C1/C3 保持未勾选。此处不采纳尚未审定的 DAILY_BARS 方案。

在该检查点，物理 SDK 工作跨越市场截止点、期间进程被强制终止，以及重启后的义务重建（或等价持久证据）仍须验证。仅凭 31.25 秒准入保护不能证明强杀安全，也不能证明遗漏义务可被重建。下方限定测试证据现已覆盖一条官方收盘路径，而非全部中断义务。

### 业务第 3 步截至 233e7ad 的进展 — 同步于 2026-09-27

以下经过独立复核的本地提交更新上方对应薄步的未完成状态，但不关闭 C1/C3：

- `d0f2443`：DAILY_BARS 只读需求 helper 通过激活身份和有界可续查过程区分今日参考需求与历史收盘需求。正常 pending 标记既不能证明需求，也不能否决独立证明的历史需求。最终证据：42 项专项及 283 项合并测试通过；配对 `docs/verification/2026-09-27-b2-daily-bar-permission-demand.md`。
- `233f969`：生产准备层使用独立权限 reader，不启用业务恢复；一份自有快照内每次最多调查一页历史及复核 10 个 receipt。不调用 SDK、不预约、不写业务数据、不推进 scope/O/F。证据：28 项专项及 137 项合并测试通过，独立复跑同样通过；配对 `docs/verification/2026-09-27-b2-daily-bar-permission-preparation.md`。
- `95feccb`：纯 CURRENT_DAY_MINUTES/REALTIME_MINUTES 证明验证整批响应、冻结请求时间与标签、保留全部来源日期供后续 owner 验证，并保持安全的传输错误分类。两项评审发现均在提交前复现并修复。作者最终运行：291 项专项及 773 项相邻测试通过；独立运行：291 项专项、297 项相邻及额外 32 项断言通过。中止的全量运行不计为通过。证据：配对 `docs/verification/2026-09-27-c1-stock-minute-permission-proof-contract.md` 与 `docs/verification/2026-09-27-c1-stock-minute-permission-proof-verification.md`。
- `233e7ad`：一个合法激活 legacy 计划的假 SDK 请求跨过截止点后进程被强杀，实际 composition 能恢复其缺失官方收盘。同日/次日重启及已完成对照通过；第三个进程不产生重复业务状态或发送。无需修改生产代码或迁移。证据：4 项专项及 33 项合并测试通过，独立复跑 4 项通过；配对 `docs/verification/2026-09-27-s3-missed-close-kill-restart.md`。这关闭该证据缺口，不代表全部盘中恢复、跨日通知活性或崩溃/发送窗口已验收。

协调会话另在配对 `docs/verification/2026-09-27-s3-coordination-baseline.md`（`c5ca53d`）记录了既有 S3-04–S3-08 基线 368 项通过。上述数字来自不同运行，其中存在重叠；不能相加为一次最终门槛总数。

在该检查点，仍为 OPEN：DAILY_BARS 物理请求 owner 接线；股票分钟的 owner 需求/日历/身份验证及接线；统一 RUNNING/DEGRADED 权限维护和完整 C1 验收；真实启动的空/部分覆盖、有界公平性以及 S3-04–S3-09 剩余矩阵。未提交实现及只读设计不属于完成证据。已测试的强杀重启路径不能替代这些剩余门槛。本次进展更新不授权真实服务、用户数据库迁移、推送或部署。

### 业务第 3 步截至 8b4ed99 的进展 — 同步于 2026-09-27

- `453cc0c` 接通 DAILY_BARS 内部 owner 入口，包含冻结需求、持久预约、取消及响应快照围栏。作者验证：58 项专项和 248 项合并测试通过；独立验证：281 项通过，其中包含 58 项专项。配对 `docs/verification/2026-09-27-b2-daily-bar-permission-wiring.md` 记录范围。后续独立评审复现了更深一层的认证 wrapper SDK 启动边界缺口，影响本路径及相关权限路径；拟议修正及尚未提交的测试还不能关闭该发现或 C1。
- `e9c6ac5` 记录协调会话在源码 `453cc0c` 上的汇总离线运行：**18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning**，670.06 秒。按计划排除了大型回测并仅选择非 live 测试。新的启动覆盖测试在收集后才出现，不包含在内。见配对 `docs/verification/2026-09-27-s3-offline-regression.md`；该检查点仍是失败结果。
- `8b4ed99` 修正造成上述 18 项失败的四组旧测试前提，不改变生产安全规则：激活前合法初始化存活记录、真实当前投递准入、必需 AI 请求字段及完整诊断替身。原有 157 条断言和 29 个测试函数均保留，并新增拒绝对照。作者运行：53 项专项和 172 项相邻测试通过；独立运行：53 项专项及单独一项时钟恢复检查通过。配对 `docs/verification/2026-09-27-s3-regression-fixture-alignment.md` 明确区分这些共享工作树运行与最终干净版本汇总通过。
- `3c22bff` 在配对 `docs/verification/2026-09-27-c1-stock-minute-permission-owner-contract.md` 中记录已独立评审的股票分钟 owner 准备契约。候选/身份/日历准备获批进行有界实现；未声称 owner 已实现或执行已验收。执行仍受 SDK 边界修正及自身验证门槛约束。

另一组尚未提交的真实启动覆盖矩阵具有合格证据，但产品未通过：作者与独立运行均为 **3 failed, 10 passed**。空/部分输入仍然安全，但正常 INCOMPLETE 结果触发运行器故障；迟到的启动响应还会持久化超过冻结获取截止点的分钟。当前进度依赖自动替换代次成功，尚不是正常局部恢复。增强后的当前决策断言能够拒绝过期回放。配对 `docs/verification/2026-09-27-s3-startup-minute-coverage.md` 记录证据；修复设计与实现仍开放。

上述数字均不构成新的汇总总数。C1、C3、S3-04–S3-09 和业务第三步保持 OPEN。剩余工作包含 SDK 边界、股票分钟 owner 准备/执行、统一权限调度、正常有界启动前缀恢复及完整生命周期/故障矩阵。最终集成后须在集成版本重跑计划离线门禁；定向修正测试前提不能追溯地把此前汇总运行改为通过。

### 业务第 3 步截至 47a803b 的进展 — 同步于 2026-09-27

以下本地、已独立评审的检查点更新此前各日期记录中对应的开放项；不关闭 C1/C3 或业务第三步。

- `4804207` 关闭配对 `docs/verification/2026-09-27-c1-sdk-call-boundary-verification.md` 所列权限路径已复现的认证 wrapper SDK 入口缺口。wrapper 准备及端点解析先于最终校验；唯一启动时间戳之后，仅进行原模式时间校验与内存围栏，再调用已解析的 SDK。最终独立运行通过 146 项测试。`INDEX_HISTORICAL_MINUTES` 和普通业务恢复明确不在该实现范围内，不能借其结果声称通过。
- `ae3c68e` 记录分钟 owner 执行在准备片验收后的有条件批准。`47a803b` 完成并独立验收纯准备片：精确当前身份、owned 快照、日历/窗口检查、epoch/Event 检查、八作用域选择及独立 symbol 游标。作者最终运行通过 74 项专项和 175 项组合测试；独立重复同一组合命令通过 175 项。配对 `docs/verification/2026-09-27-c1-stock-minute-permission-preparation.md` 区分较早的 501 项运行与最终版本证据。准备不预约、不调用 SDK、不写业务数据。owner 执行现已放行实现；执行验收和自动派发仍开放。
- `ae942d1` 在配对 `docs/verification/2026-09-27-s3-startup-minute-repair-contract.md` 定稿已独立批准的 A07 修复设计：F1 精确原始身份结果及正常提交前过期处理；F2 冻结逐调用获取范围及提交围栏；F3 有界自主前缀恢复。F1 正在实现。F2/F3 需要串行源码交接及各自验收；设计批准不是实现证据。F1 可能移除此前使进度用例通过的意外崩溃/重启，因此过渡期进度失败必须保留，直到 F3 解决。

下一步：独立验收分钟 owner 执行和 F1；实现/评审 F2/F3 及统一八作用域 RUNNING/DEGRADED 权限维护；再完成剩余 S3-04–S3-09 故障矩阵并重跑集成离线门禁。此前汇总结果仍是失败，直到新汇总运行证明通过。本进展更新不勾选任何检查项，也不授权真实行情源、真实通知、用户数据库迁移、推送或部署。

### 业务第 3 步截至 b3e04a4 的进展 — 同步于 2026-09-27

- `f4a5050` 完成并独立验收 A07 F1：每个正常不完整或带类型的提交前失效结果保留原始计划/激活身份。真实重新激活、持仓及风险竞争拒绝旧业务写入，且不替换运行器。最终自包含专项/相邻验证通过 142 项；独立源码验证通过 44 项专项和 98 项相邻测试。配对 `docs/verification/2026-09-27-s3-startup-outcome-association.md` 分别记录重叠运行。未修改的 A07 矩阵仍为 **3 failed, 10 passed**：两项正常前缀恢复进度缺口及一项冻结截止点缺口；此前不完整结果引发的运行器故障已修复。F2/F3 仍必需。
- `e7c6d8f` 增加已批准的逐调用业务 `current_day_minutes` 最终 SDK hook，不改变 generic provider protocol。独立验证通过 17 项专项和 293 项相邻测试。这仅是 F2 前置条件，不是范围捕获或持久化实现。证据：配对 `docs/verification/2026-09-27-s3-current-day-business-sdk-boundary.md`。
- `fbdcaed` 完成股票分钟权限执行 owner。独立评审复现并关闭 legacy 到期边界 P2，保留到期等号有效。最终 writer 验证通过 104 项专项和 335 项组合测试；独立修后验证通过 104 项。证据：配对 `docs/verification/2026-09-27-c1-stock-minute-permission-execution.md`。自动维护仍属独立工作。
- `26b15e2` 批准统一八作用域派发设计，包括一次有界准备、固定无候选延后、行情游标保留和 DEGRADED 独立启动/权限时钟。`b3e04a4` 仅实现其中 UPD-S1 日历/历史指数 provider hook。writer 验证通过 904 项组合测试；独立验证通过 62 项专项和 237 项相邻测试。证据：配对 `docs/verification/2026-09-27-c1-unified-permission-dispatch-contract.md` 和 `docs/verification/2026-09-27-c1-calendar-history-permission-sdk-boundary.md`。UPD-S2–S5 尚未实现。

当前工作：串行持有源码写入权，实施并独立验证 A07 F2/F3；完成 UPD-S2–S5；补齐剩余真实进程依赖/提交/发送及本地读取验收矩阵。S3-07 强杀测试可并行准备，但不因此关闭其前置门槛。随后在固定集成版本运行离线汇总测试和最终独立评审。C1/C3 及 S3-04–S3-09 保持 OPEN；以上数字不能相加，也不能替代此前失败的汇总检查点。仅进行本地离线改动，不使用真实服务、真实通知、用户数据库迁移、推送或部署。

### D5 受控重启决策 — 2026-09-24

用户将运行中重载方案改为安全停止 → 人工编辑配置 → 启动新进程。范围内不包含 watcher、`reload_configuration`、候选运行时或自动数据源/代次安装。运行中相关配置变化或无效 YAML 必须锁存可见的 `NEEDS_RESTART` 阻断：不再启动行情请求/通知工作，监督器不替换运行时，且把文件改回也不得清除锁存。普通网络/429/权限故障仍走自动恢复路径。成功停止须在数据库检查点/关闭前排空物理请求、迟到的恢复检查点写入、已开始的发送及持久回执、在途所有者心跳；停止失败则保留所有权，禁止第二实例取得同一数据库。新进程在工作前校验一份冻结配置及既有持久冷却/预约；启动配置无效时行情/通知调用均为零，可修正后再次启动。相同端点的令牌更换保留恢复身份及 1.25 秒节流。120 小时门禁只使用本地合法所有者持久 `last_alive_at`；该进程运行时行情源/协调器故障不计为停机。仅刷新语义元数据无需重启。失败先行离线测试及完整 A05/A06/A09/C1/C3 验收仍开放。

禁止第二实例属于受控操作规则：须等待旧进程成功退出。本切片不实现防止人为并发启动另一实例的操作系统锁。下文较早日期的重载表述均由当前 D5 决策取代，D7/A12 的浏览器协议刷新除外。

有界 A09 提交准入切片现于同步业务提交前检查冻结配置、相应股票或指数认证、运行代次及停止所有权。覆盖旧版与显式决策及初始 `HOLD` outbox 行、官方收盘 pending 状态、历史事实与独立指数捕获。暂存阶段令牌漂移测试及 pending 清理测试已通过；纯只读重复项及清理写入仍可通过。完整旧任务写入/通知矩阵、并发与跨进程所有者验收仍开放；这不完成 A09、C3 或第 3 步。证据见成对运行恢复验收记录。

独立 P1 挑战促成进程级冻结 Tushare/语义基线及工作线程设置的单调撤销 Event。factory 窗口修改令牌或语义不再安装替代运行时；最终业务谓词前由工作线程撤销，即使文件改回也会阻断提交及新的物理请求。重复官方收盘 claim 即使没有健康事件，删除 pending 行也须通过门禁。这修复了已复现竞态，但正常停止事务覆盖、候选启动交错及生产纯指数依赖隔离仍开放。

后续 D5 修正关闭另外两个已复现窗口：组合停止现撤销并等待尚未公布的替代候选；生产发送在最后一次持久权威查询后、进入渠道 I/O 前复核撤销 Event。有界所有者事件循环提交顺序记录在成对恢复规格中。完整停止/发送路径验收仍开放；生产纯指数依赖工作属于独立切片。

另一项候选清理重试修正会保留尚未公布候选的引用，直到其停止真正成功。若分发器排空失败，后续组合停止会重试同一候选；持续失败继续报错，排空恢复后才关闭数据库并释放行情所有者。这关闭已复现的引用丢失窗口，但不代表完整 D5 关闭矩阵已通过。

### 业务第 3 步首个生命周期切片 — 2026-09-24

生产组合在一次模拟实时传输中断后现保留原运行时及请求控制器；稳定的 `realtime:stock` 故障键防止下一分钟绕过控制器退避。生命周期只重试类型化的 `TRANSIENT`、`TIMEOUT` 和 `RATE_LIMITED` 请求错误；重试时间遵守控制器截止点，关闭可中断等待。存储、契约及未分类供应方故障不再被悄悄转换为无期限启动恢复。既有 RR004 测试现设置有效的运行心跳证据，并验证当前语义记录缺失/损坏；冷参考缓存可以重新刷新参考数据，但不会重复提交既有决策或提醒。本切片尚未接通生产检查点仓储、受控权限复核、完整依赖隔离、已校验重载或完整物理工作者清理。失败先行及通过证据见成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`。

### 业务第 3 步行情状态绑定切片 — 2026-09-24

生产环境在模式及五天准入后，按有效端点身份绑定单个行情检查点所有者，并在构建实时管线前恢复检查点。缺失令牌时不建立管线；缺失端点时不产生恢复身份。无效检查点安全失败并释放所有者。新绑定的所有者在首次物理请求前等待完整的 1.25 秒间隔。已观察并提交的 429 在同一临时 SQLite 数据库上的受控独立进程重启后保持共享冷却，冷却内没有第二次物理请求。重复能力探查复用同一管线；配置变更或当前语义无效会阻断后续物理请求。物理控制器排空失败时，关闭过程保留数据库打开以供后续清理。本有界保护尚未实现已校验配置重载或受控权限复核。证据见成对验收文档；未迁移用户数据库，未使用真实行情源、外部发送、部署或推送。

### 业务第 3 步日历权限切片 — 2026-09-24

首个生产权限复核覆盖 `TRADING_CALENDAR`。其已持久化的 300 秒预约及任何共享 429 冷却到期后，从最近七天已持久化的已完成 `SSE` 日期选取一个锚点，仅对该日期执行一次严格、只读的 `trade_cal` 请求。缺少锚点时不发探针，行情健康持续显示 `BLOCKED_PERMISSION`。空表、混入不符记录、畸形及重复响应均不能解锁。控制器在物理结果之后、清除封锁之前再次检查当前配置、股票语义及运行代次；失败保留封锁及预约。探针成功不会写入业务日历记录。后续 S3-02 工作增加独立的 `idx_mins` 与 `rt_idx_min_daily` 探针及旧状态检查点迁移。其他 API 权限、完整 A05 验收与业务第 3 步仍未完成。证据见成对 S3-02 与 C1 记录。

### 业务第 3 步参考数据提交围栏 — 2026-09-24

每个日历、每日涨跌停及历史日线参考数据事务现于提交前再次核对捕获的激活/计划依赖键、当前配置、股票语义及运行代次。若物理请求期间任一项改变，其结果回滚，且不启动后续行情调用。这属于有界旧参考数据围栏，尚非已校验配置重载或所有决策/发送路径的证明。证据见成对验收文档。

### 业务第 3 步相关配置比较 — 2026-09-24

行情边界每次检查仍完整解析并校验 YAML 文件，但只比较解析后的 `tushare` 投影，以判定实时报价传输快照是否变化。有效的 `web` 或 `ai` 编辑不再使既有行情管线失效；端点、令牌、`connect_ip` 及超时变化需要安全停止、人工编辑并启动新进程。无效 YAML 仍是错误，不能授权旧行情源。此比较本身不会安装替代运行代次。证据见成对验收文档。

### 业务第 3 步发送排空切片 — 2026-09-24

分发器关闭现先阻断新发送，再至多等待五秒让已开始的渠道 IO 及回执最终写入，只有排空成功才关闭渠道。取消单个分发等待方不会取消其发送/回执。超时后发送保持运行，可稍后重试清理。若分发器排空失败，运行时关闭过程会保持行情所有者及数据库打开，不会在迟到回执期间执行检查点或释放存储。这属于有界关闭安全修正；配置重载及完整 C3 验收矩阵仍开放。证据见成对验收文档。

### 第二阶段接通检查点 — 2026-09-24

生产组合现将两类评估器接入原子初始 `HOLD`，并把 `CurrentDeliveryAdmission` 交给发送器。每次模拟渠道投递都在认领前及认领后、实际 I/O 前重新读取已提交权威状态；数据库事务不跨渠道 I/O。旧版官方风险提醒准入证明原始归属、当前计划/激活、到期收盘、最新官方风险阶段及已确认持仓（含只指定数量的期初余额）；已解除、被取代或不适用的提醒进入终态抑制，未知事实保持 `HOLD`。相同退出指令只释放已证明的最新一条。显式风险及操作提醒核对当前计划、已完成时段、结果、持仓和规则证据；操作提醒保留来源后 90 秒失效。重复的相同分类不增加审计修订。不确定发送仍沿用既有状态机。测试范围及剩余发布门禁见成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`。下方较早日期的检查点保留其历史状态。

### 业务第 3 步的有界 RR010 修正 — 2026-09-24

截止任务在等待参考数据刷新和历史恢复时保留入口处捕获的参考依赖键，并在准入计划前拒绝激活身份或语义变化。此前失败的同计划重激活用例和新增的历史等待用例均通过。另两项单独复现的市场指数失败共用一处持久化短路：它用旧快照头替代新的规范捕获；移除短路后，快照头按捕获时间更新，指数获取失败也会阻止受影响的历史决策。完整离线指数回归通过。在该检查点，另有四项不同的无计划/股票绑定语义门禁测试仍在本次身份校验前失败，原因是仅应独立展示指数时 `run_deadline` 却请求股票交易日历。下文后续有界修正解决了这四项具体失败；该 RR010 检查点并未关闭业务第 3 步或 C0–C5。

### 独立指数准入修正 — 2026-09-24

未捕获活动计划时，`run_deadline` 现直接执行独立展示指数工作，不刷新股票参考数据。捕获到活动计划但股票认证无效时，在请求股票行情源前阻断；指数工作仍可独立调用。这解决此前开放的四项 `test_production_semantic_gate.py` 失败，同时保留逐请求指数绑定核对。语义门禁文件 11 项通过；相邻生产/指数/激活集成文件 91 项通过，仅有 1 项既有弃用警告。这是有界 RR004/RR006/A06 依赖准入结果，尚非调度器接续、完整 A06 故障矩阵、业务第 3 步或 C0–C5 的证明。详见成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`。

### 生产纯指数接续 — 2026-09-24

存在可信的已持久化 `SSE` 开市日历及有效指数语义时，即使缺少股票语义或认证，生产进程仍可为指数采集保持 `RUNNING`，且不获取股票行情、不判断、不产生新股票提醒。股票供应方健康保持 `ERROR` 并标注 `STOCK_SEMANTICS_UNAVAILABLE`；状态条明确显示仅指数采集、股票计划受阻。没有可信日历时，启动保持 `DEGRADED`，不推断开市日或发起请求。纯指数 deadline 或直接调用分发器时，旧股票 outbox 行均不得进入渠道。冻结进程基线后新增股票语义 sidecar 会锁存重启要求，删除该文件也不能解除。直接调用 `ProductionMonitorPipeline` 时，缺少认证的活动股票工作仍被拒绝。这是有界 P2/A06 切片，不代表完整依赖故障矩阵或业务第 3 步完成。

后续 P2/A06 切片在纯指数重启时恢复已持久化且未过期的指数重试，不进入股票恢复。五个受阻指数快照保留重试截止点，到期处理时不请求股票行情、不产生判断或发送。若旧股票权限预约覆盖供应方状态，健康信息保留 `BLOCKED_PERMISSION` 及重试时间，同时保留 `STOCK_SEMANTICS_UNAVAILABLE` 作为纯指数界面提示的原因。该切片的权限预约本身不变；独立的 `INDEX_MINUTES` 检查点设计现已获批，但尚未实现。

后续仅加测试的 A06 生产组合矩阵在股票响应畸形用例中同时激活 Schema v1 `TradePlan` 与 Schema v3 `ExplicitTradePlan`，在指数依赖用例中同时激活 Schema v2 `TradePlan` 与 Schema v3 `ExplicitTradePlan`。任一族的一条股票响应畸形时，另一族仍提交判断，五个展示指数仍可用；受控停止后在同一进程内创建第二个组合并恢复模拟数据，两族均为精确的 10:05 目标及当前计划身份各提交一条结果。Schema v2 计划必需的 `INDEX_*` 参考指数发生瞬态故障时，产生精确缺失输入证据且没有旧版行动提醒，而独立 Schema v3 规则提交并进入模拟渠道；另四个指数保持实时。其持久重试由第二个组合恢复：一组非空的纯指数物理请求使原截止点的持久快照在下一目标前变为 `LIVE`，恢复期间不新增股票判断、提醒或发送。负控具有相同的 `reference_market`，但没有 `INDEX_*` 叶子，因此保持独立。四项测试在既有运行时代码上全部通过，这只增加证据，不虚称产品修复。截止点由测试直接调用；在该检查点尚未证明跨进程重启或调度器接续。更广的 A06/C3 矩阵仍开放；Schema v3 不增加指数条件。

后续两项参数化离线 A06 用例各使用两个独立 OS 进程及已安装调度器，不直接调用 `run_deadline`。第一进程让模拟时钟推进到 10:00，一条 Schema v1 或 Schema v3 股票响应畸形仅阻断本族结果，另一族仍提交且五个指数代码持久保存；随后正常停止并成功退出。只有确认第一进程退出后才启动第二进程，让模拟时钟推进到 10:05；两族当前计划身份均提交精确的 10:05 结果。每个进程均发起一次模拟 `rt_min` 物理请求，模拟渠道没有发送，持久提醒总数保持为零。既有运行时代码直接通过该用例，没有产品变更。这证明两种单行计划族故障方向的受控跨进程调度接续；其他依赖故障、指数重试跨进程、跨日时间及完整停止/发送矩阵仍开放。

当前实现交接：提醒不是成交；只有人工登记在登记时刻改变仓位。长期活动计划的历史读取器从最近经验证的已完成收盘之后开始，仅判断有界的遗漏后缀；已确认期初持仓无需虚构批次细节即可支撑只指定数量的旧版风险退出。生产组合按时间顺序补算收盘并按激活身份重试。可恢复提醒进入持久 `HOLD`；发送器在释放适用提醒前重新核对当前权威状态。V1c/业务第 1 步已于 2026-09-23 通过批准的限定离线三进程重启标准，第二阶段于 2026-09-24 通过接通的模拟渠道回归。RR010 的同计划重激活失败及四项无计划/股票绑定语义门禁失败已修复；高交易量证明预算、完整跨日/故障矩阵、更广的依赖恢复及调度器接续矩阵、独立评审及 C0–C5/完整发布门禁仍待完成。未使用真实行情源、外部发送器、用户数据库迁移或部署。命令和结果见成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`。

### 五天范围修订 — 2026-09-23

- [ ] **V1d — 实现已批准的 D8/A13。** 120 小时边界、持久最后存活证据和未知/旧数据库处理已批准。增量结构 `0022_runtime_liveness`、持久化/判定及临时数据库的边界/损坏/旧库/降级测试已实现。生产启动在加载活动标的、请求行情或发送前准入或原子作废计划；30 秒心跳在降级模式运行，并在关闭数据库前结束。休眠空白超过 120 小时时停止运行，不刷新旧证据。作废会清理待收盘任务、抑制现有回执并审计原因；注入故障时整笔回滚。独立 Python 进程证明提交后退出与事务中途被杀都不会留下部分或重复作废。有效旧版/显式计划定义和持仓保持不变。缺心跳人工路径在没有监控工作的情况下展示 `BLOCKED` 系统状态，预览准确计划并要求二次确认；一个事务将其作废且保留持仓，重启后建立新证据。准入后每轮心跳最多处理 100 条提醒，仅为准确已停用版本还有长停机/人工作废审计的规范旧提醒补记终态回执；普通停用不符合该条件。此类终态作废版本不得重新激活，普通再激活保持允许。畸形证据仅记录不含原文的审计，暂时清理失败不拖延心跳。**V1d 仍未完成：**无法分类的旧记录需确定安全复核处置，清理失败需在维护状态中明确显示，还需更广的发布门禁评审。本阶段不对用户数据库运行批量作废。
- [ ] **V2a — 评审 D9/A14 提醒页操作契约。** 保持风险与卖出信号独立；区分确认已读、未卖出及登记实际卖出数量。复用带幂等和审计的持仓扣减边界，再测试过时提醒、部分卖出及重复确认。五天准入决策后实现，不改变评估规则。

### 已完成的限定成果：一次可证明的遗漏收盘

以下内部工作单元属于 RR009/C2。提交保持有界，不再给每个解码器单列业务里程碑或验证报告。已满足获批的限定第 1 步标准；完整 C2/发布验收前仍须扩展跨日及故障覆盖。

- [x] **V1a — 明确历史重建契约。** 依赖：既有写入/解码证据及 RR001。一次集中评审明确历史观察截止点与已接受生效日期的关系、迟到/非单调登记处理、风险来源有效时间，以及明确的字节/成员/历史预算。保留可变交易单位、原始快照及旧规范哈希。验收：成对规格包含示例时间线和明确的已知/未知结果；未决业务选择在实现使用方前交由用户判断。文件：成对 `docs/specifications/monitoring/SPEC-runtime-recovery.md` 及本成对任务表。验证：示例追踪到写入字段和 D3/D5，核对双语一致性并处理新安全发现；不重复评审未变更决策。
- [x] **V1b — 读取一次完整历史持仓。** 依赖：V1a。将确认/持仓变更解码与持久化持仓读取器一起完成，复用已有批次/期初校验及自有快照保护。验收：真实写入记录能还原请求目标的一致持仓；断链、成员缺失、超预算或矛盾历史返回类型化未知；不接受未提交/外部事务证据。源码范围：`src/trade_plan_monitor/state/`；测试：已有持仓审计/事务/批次历史测试及 NEW 专项持仓历史测试。验证：先失败的写入到读取用例，以及损坏/事务/预算用例，再运行受影响持仓回归组。内部源码/测试提交保持有界，不新增通用历史框架。
- [x] **V1c — 按已批准的限定离线标准执行遗漏收盘并重启验证。** 依赖：V1b、已评审的风险来源重建及既有 RR008/RR010 保护。使用模拟行情源和临时 SQLite 接通发现、历史输入及初始 `HOLD` 的评估事务；未使用外部发送器。一次遗漏收盘只提交一次；提交时故障会回滚，重复恢复不增加规范结果/提醒，三个独立的生产组合进程证明 120 小时内的重启接续。证据：`tests/integration/test_missed_close_execution.py`、`tests/integration/test_runtime_restart_gap_acceptance.py` 及成对 `docs/verification/runtime-recovery-acceptance.zh-CN.md`。这仅按限定标准关闭 V1c/业务第 1 步。另行发现的重激活准入失败已在上文 RR010 检查点修复；高交易量证明预算、完整跨日/故障覆盖及 C2/完整发布评审仍待完成。没有把仅重新打开 SQLite 当作进程重启证明。

### 验证节奏与交付

- 修改期间：有意义的先失败测试、受影响测试组和静态检查；涉及代次/事务/身份边界时补充对应回归。同一完整成果内测试使用方，不只测试每个解析器。
- 完整成果检查点：运行该成果的集成恢复/故障场景和跨模块回归组；评审接通后的整体修改。一份成对成果报告记录命令、受测版本/修改和结果。修复后重跑受影响检查；无需重复生成未变化的成功证据。
- 最终验收/默认启用前：提案第 7 节全部命令，包括不新增排除项的完整 `not live` 测试及隔离状态下的浏览器验收。既有失败不能豁免或改为跳过。专项通过不关闭 C0–C5。
- 基线失败保持未解决：此前报告 `docs/verification/2026-09-22-opening-balance-decoding.md` 记录排除重型回测文件后的 3734 通过 / 4 失败 / 1 跳过 / 4 未选中。这是历史有范围证据，不是全量通过。涉及有关边界时复现相关失败；最终验收前解决全部四项。不在纯文档修改后反复花费一次全量运行重新发现未变化失败。
- 交付格式：业务步骤；已接通场景（或明确仅为基础组件）；实际证据；剩余决策/失败；下一项完整动作。不按提交/测试数量推算百分比。保持当前分支；本流程调整不授权推送、切换/合并分支、真实行情/渠道操作或部署。

### 实现检查点 — 2026-09-21

成对证据见 `docs/verification/2026-09-21-runtime-recovery-foundations.md`。完成基础切片不代表 C0–C5 通过，也不代表启用生产恢复路径。

| 任务 | 当前状态 |
|---|---|
| RR001 | 已编写成对行情源/恢复规格；完整契约评审尚未完成 |
| RR003 | 已实现并独立评审；完整性、兼容性及并发不覆盖导入测试通过 |
| RR004 | 已实现并评审注入式运行门禁；装配及所选股票失败后的独立调度尚未完成 |
| RR005 | 已实现并评审检查点模型/仓储/迁移及 SQLite 最新 head 断言 |
| RR006 | 已实现/评审持久化准入、`RecoverySchedule` 与注入式单所有者 `RecoveryCoordinator`；生产生命周期集成尚未完成 |
| RR007–RR008 | 纯目标计算及注入式单证券获取验证准确的已提交覆盖；已组合测试协调器/控制器/SQLite 恢复；历史获取/重放及生产集成尚未完成 |
| RR010 | 参考键已绑定计划类型/内容、真实激活与股票语义；已评审等待后的缓存/准入校验；更完整的 generation/重配置义务尚未完成 |
| RR002 | 已增加成对的详细状态/协议草案供评审；未改变协议源码/默认路径，不关闭 C0/C4 |
| RR011–RR013 策略/存储切片 | 显式风险分类器与旧版来源证明已独立评审；已增加隔离的旧版适用性分类器、交付迁移/仓储及可选原子 HOLD 入队；RR012 初始 HOLD 评估事务接线已实现并独立审查，未在生产装配启用；当前证据持久化重建及发送器集成仍未完成 |
| RR009 | 已增加有界发现及只读 SQLite 发生/激活证据读取器；超出证明预算的直接来源、历史状态重建及顺序执行尚未完成 |
| RR011–RR022 | 尚未完成；继续遵守下方依赖，不以此增量检查点作为发布批准 |

- 用户于 2026-09-21 授权实现已批准提案/职责图。由其细化的行情源/恢复契约与隔离、注入式基础切片同步落地；未评审的协议/业务变化及生产默认切换仍受门禁约束。此授权不包括真实迁移或部署。
- 每个编码任务先编写有意义的失败测试；保留无关修改及旧规范身份的黄金测试。不能因测试描述旧行为而跳过：只用已批准新契约测试替换明确被取代的断言。
- 下列路径相对仓库；NEW 表示拟新增。内部代码修改控制在约 3–5 个源码/测试文件；超出时在同一完整成果内拆分，不新增业务里程碑。相关修改同步成对规格/契约；RR017/RR021 保留生成契约/运维验收义务。
- 新路径通过相应检查点前，复用当前默认生产行为。通过依赖注入和现有组装提前集成，不永久维护第二套生产框架。只有 RR020 且所有前置契约和保护就绪后，才启用新默认路径；不能等到 RR020 才首次集成测试。
- 每个任务记录修改路径、精确命令、实际结果及剩余失败。执行无法确认时，不得声称使用了指定模型/强度。

### 继续实现检查点 — 2026-09-21

本轮增加隔离的 RR006/RR008/RR010 切片，不将这些完整任务标记完成。细节与实际验证见 `docs/verification/2026-09-21-runtime-recovery-increments.md` 及其中文副本。新协调器在类型化依赖重试期间持续存活，本地维护上限为 30 秒，存储/程序错误仍明确暴露。按范围获取不会将部分、未来或日期错误的数据判为就绪。排队期间的本地取消保留原有行情源退避。参考缓存不能跨计划类型或真实激活变化复用。

显式风险最新状态和旧版只读来源切片均经独立评审；用户批准的重复退出提醒只补最新一条规则已记录，但未接入发送。最终功能验证为 3095 通过、4 项既有失败；未改动的重型回测文件已在此前全量运行中通过。R32 依赖真实日期的测试已修正，未改动实际执行门禁。本检查点不授权默认切换、真实操作、合并或部署。

### 交付安全检查点 — 2026-09-21

后续隔离增量增加迁移 `0019_alert_delivery_eligibility`、带 revision 校验的分类/审计、有界缺失记录初始化，以及显式启用的 `enqueue_recoverable`。规范提醒/结果身份及现有生产默认行为不变。可操作提醒的来源过期与状态风险适用性分离；已存 ELIGIBLE 不是持续有效的发送许可。旧版纯策略核对原始证据、最新官方风险阶段、当前持仓/T+1，以及已批准的重复退出只保留最新一条规则。其日历和当前状态输入仍靠注入，不是已完成的持久化读取器。

详见 `docs/verification/2026-09-21-recovery-delivery-metadata.md` 及 ADR 0007 和对应中文副本。评估事务、当前权威事实、最终逐渠道准入及端到端崩溃/重启证据完成集成之前，RR011–RR013 和 C0/C2/C3 仍未完成。本增量不授权真实迁移、通知、生产切换或部署。

### 评估事务检查点 — 2026-09-21

本次继续工作前，已按要求将 `964fde2` 和 `6dff7ae` 同步到既有 GitHub 分支。RR012 继续采用隔离事务切片：严格的构造参数显式启用后，将旧版两条评估路径及显式提醒写入接到既有 HOLD 辅助方法。辅助方法在初始化元数据前规范化入队层的带时区时钟。判断回滚须涵盖认领/结果/转换/提醒/元数据/审计，不回滚此前已提交的行情事实。细节及最终验证记录在成对 `docs/verification/2026-09-21-recovery-evaluation-transactions.md`。

当前仍处于恢复核心/通知安全阶段，尚未完成生产集成：这些切片不关闭 C0–C5。既有工厂不启用选项；该选项不使发送器强制执行 HOLD。当前权威事实重建、最终发送准入、生命周期/状态/UI 接线和进程重启验收仍是 RR020 的前置条件。按要求推送之后产生的本地提交，不自动推送或部署。

### 遗漏收盘发现检查点 — 2026-09-21

隔离的 RR009 扫描器不依赖待处理标记，即可发现已到期的旧版收盘候选。实际激活、历史策略、权威日历及准确完成证据仍是不同输入。每次最多覆盖 32 个自然日；窗口结束不证明整体恢复完成。无法归属和可能乱序的历史均显式呈现。它不将今天的状态送入当前评估器处理历史日期，不改变生产启动路径，也不发送通知。证据记录在成对 `docs/verification/2026-09-21-missed-close-discovery.md`。

RR009 保持未勾选：有界持久化归属见下一检查点；权威历史状态重建及带激活/generation 校验的顺序执行仍未完成。既有仅哈希认领、缺口之后已有结果、当前持仓上下文及风险写入时间语义，均须在不重写规范身份、不改变交易规则的前提下处理。扫描器不是恢复屏障或发布门禁。

### 持久化收盘证据检查点 — 2026-09-21

下一 RR009 切片共享已有测试覆盖的激活链证明，并在一个自有 SQLite 快照中读取激活范围、日历、认领、完整结果及发布。发生证明不依赖是否创建提醒或风险信号类型。缺失/损坏/过大/错误激活证据保持未知，确认不存在还必须经过有界孤立发布检查。正常长期运行也可能保守地耗尽发布历史预算；这是已记录的启用前直接来源要求，不声称任意长度历史都已可恢复。

详见成对 `docs/verification/2026-09-21-close-recovery-evidence.md`。RR009 的权威历史状态重建及安全顺序执行仍未完成；未启用回放、真实通知、结构迁移或生产默认行为。当前快照事实不是持久有效的修改/发送许可。

### 持仓批次证据检查点 — 2026-09-22

RR009 的下一项前置工作在既有审计事务中，为未来手工批次买入和减仓保存版本化命令日期及完整前后快照。它保留批次哈希、事件身份、持仓规则和幂等行为，不重建历史组合，也不启用回放。旧记录不变，不能从写入时间获得缺失的减仓日期。契约见配套双语运行时恢复规范；验证记录见双语 `docs/verification/2026-09-22-position-lot-recovery-evidence.md`。

后续历史状态工作仍须验证这些记录，证明逐批次/持仓历史完整性，明确期初余额和确认语义，并单独处理风险来源有效日期。现有证据预算和因果缺口仍会阻断未知范围。RR009 和 C2 保持未勾选；不启用生产恢复、真实服务、迁移或真实发送。

### 持仓批次解码检查点 — 2026-09-22

隔离的纯解码器校验单条版本化批次变更审计：有界严格 JSON、元数据绑定、准确的旧版哈希及买入/减仓不变量。旧版证据缺失、版本不支持和数据无效返回类型化未知，不从写入时间推断。它兼容既有非 UUID/自定义交易单位约定，不改变变更准入。测试先行及独立审查证据见双语 `docs/verification/2026-09-22-position-lot-evidence-decoder.md`。

本检查点仅完成单条记录解码。持久化逐批次读取器仍须在同一快照内证明有界唯一链条、已提交发布及与当前批次的一致性。仅限制审计查询返回行数不能限制数据库扫描工作量；既有审计表没有实体类型/实体 ID 索引。完整持仓、期初余额/确认、风险来源有效日期和安全顺序执行仍未完成。RR009/C2 和生产集成尚未完成。

### 单批次历史检查点 — 2026-09-22

RR009 的下一增量在自行管理的单个 SQLite 快照内读取一个批次的完整已存审计/发布链。要求唯一买入根节点、每次准确减仓、当前行一致及有序确定性发布。证据缺失、冲突、损坏或超过预算时保持未知。该证据不是完整持仓，也不是回放/发送许可。不会用七天客户端回放过滤器排除更早的已存发布。

增量迁移 `0020_lot_history_indexes` 支持准确审计范围及按序聚合事件查询；仅改变索引，在临时数据库验证。读取器、迁移及审查证据见双语 `docs/verification/2026-09-22-position-lot-history.md`。完整持仓、期初余额/确认、风险来源有效时间语义及顺序执行仍阻止 RR009/C2 关闭及生产集成。

- 此处识别的事务归属待办由下方检查点处理；单批次增量本身并未认证相邻读取器。

### 恢复读取器事务归属检查点 — 2026-09-22

`LegacyCloseRecoveryReader`、`LegacyAlertOriginReader` 和 `PositionLotHistoryReader` 共用小型预检，要求会话全新，且每个 mapper/表级绑定均使用同一个应用 SQLite Engine。在进入上下文或执行 SQL 前拒绝外部 Connection 和跨引擎绑定，不改变调用方事务。真实测试复现了两个旧读取器在修复前错误证明未提交证据的问题。本次关闭已识别的绑定缺口，不代表历史状态重建或整个恢复读取器信任边界完成。

详见成对 `docs/verification/2026-09-22-recovery-reader-transactions.md`。RR009 下一切片须先保存期初持仓和持仓确认历史，才能重建完整历史持仓。风险来源有效时间、历史预算、因果顺序执行及更广泛的集成门禁仍未完成。不启用生产默认路径、行情/通知渠道操作、数据库结构迁移或部署。

### 持仓写入证据检查点 — 2026-09-22

未来确认保存完整原始前后行及新建的期初持仓。期初持仓减仓保存已接受的交易日期、交易单位及原始前后行。每次批次买入/减仓和期初持仓减仓，还独立记录关联来源的持仓变化，包括确认缺失/过期的情况。既有准入、响应、哈希、发布身份、ID/时钟调用次数和事务归属不变；不包含迁移或历史猜补。

详见双语 `docs/verification/2026-09-22-inventory-recovery-evidence.md`。本增量完成写入保存，不表示完成历史持仓重建。RR009/C2 保持未勾选：有界解码、来源/链条校验、完整性截止点、迟报/倒序登记、风险来源有效时间及顺序执行仍未完成。最终发送准入、生命周期/状态集成及实际进程重启验收属于后续门禁；未启用真实行情源、真实通知、生产默认路径或部署。

### 期初持仓减仓解码检查点 — 2026-09-22

`decode_opening_balance_mutation` 现可校验单条有界期初持仓减仓审计，返回不可变自洽证据或类型化未知。保留原始时间戳，同时校验既有 DTO 哈希、准确范围和变更算术。继续支持当日可卖、不同交易单位、非整百余额及相互独立的写入/关闭/有效日期。复用严格解析基础函数，不修改既有写入器或批次解码器。

详见双语 `docs/verification/2026-09-22-opening-balance-decoding.md`。这是三种持仓相关解码切片中的第一种，不是持久化历史读取器。确认和持仓变更收据解码、来源/链条证明、明确的完整性策略及顺序执行仍未完成；RR009/C2 保持未勾选。不包含分支创建/切换、迁移、生产恢复、真实通知、推送或部署。

## 规格门禁

- [ ] RR001 — 确定语义和恢复规格。强度：`xhigh`。依赖：提案/职责图批准。
  - 验收：D1–D6、A01–A10 精确；模块接口、实际激活边界、全部信号投递分类和增量迁移明确批准，不靠推测。
  - 文件：在 `docs/specifications/monitoring/` 下 NEW 成对 provider-contract 规格和成对 runtime-recovery 规格（4 个文件）。
  - 验证：逐项追踪决策/验收 ID，检查双语一致，取得规格批准。
- [ ] RR002 — 确定状态/协议及发布契约。强度：`xhigh`。依赖：RR001。
  - 验收：D7 定义可区分状态、精确协议/版本协商、旧客户端安全刷新、两类计划及局部不可用行为；旧全局 `readOnly` 字段无歧义。
  - 文件：NEW 成对 runtime-status 规格及 `docs/specifications/monitoring/SPEC-local-web.md` / `SPEC-local-web.zh-CN.md`（4 个文件）。
  - 验证：评审有效/无效状态及新旧客户端消息示例、A11–A12 可追踪性和双语一致。

### 检查点 C0 — 契约已批准

- [ ] 对照用户已批准提案完成 RR001–RR002 评审；数据源语义、提醒资格、数据库结构及兼容性变化明确。2026-09-21 的实现指令允许推进隔离基础切片；本门禁通过前不切换生产默认路径、不扩大未批准语义。

## 行情源与恢复基础

- [x] RR003 — 引入兼容语义记录导入。强度：`high`。依赖：C0（2026-09-21 指令授权隔离基础切片）。
  - 验收：A01–A02；迁移幂等、仅导入已验证范围、原证据不变；语义版本忽略元数据但检查适配器兼容性。
  - 文件：NEW `src/trade_plan_monitor/runtime/provider_contract.py`、`src/trade_plan_monitor/live_profiles.py`、`tests/unit/test_live_certification_profiles.py`、NEW `tests/unit/test_provider_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_live_certification_profiles.py tests/unit/test_provider_contract.py -q`。
- [ ] RR004 — 替换整份证据运行门禁。强度：`high`。依赖：RR003。
  - 验收：股票/指数门禁独立；旧 READY 不授予当前健康；元数据刷新无害，不兼容变化在物理请求前被拒绝。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/web/monitor_composition.py`、`tests/integration/test_production_certification_gate.py`、`tests/integration/test_certified_production_runtime.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_certified_production_runtime.py -q`；RR020 前使用注入的组装。
- [x] RR005 — 持久化有界行情恢复检查点。强度：`high`。依赖：RR003、临时数据库迁移批准。
  - 验收：重启保留冷却/重试状态，不保存凭证；迁移增量、幂等，拒绝破坏性丢失待完成状态。
  - 文件：`src/trade_plan_monitor/state/migrations/versions/` 下 NEW 迁移、`src/trade_plan_monitor/state/models.py`、NEW `src/trade_plan_monitor/state/runtime_recovery.py`、NEW `tests/integration/test_runtime_recovery_storage.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_storage.py -q`，使用临时数据库升级/重启用例。
- [ ] RR006 — 增加受控协调/重试准入。强度：`high`。依赖：RR004–RR005。
  - 验收：A04–A05；故障键稳定、单次权限复检、保留共享冷却、工作有界且合并；不陷入永久权限封锁循环。
  - 文件：NEW `src/trade_plan_monitor/runtime/reconciliation.py`、`src/trade_plan_monitor/runtime/request_control.py`、`tests/unit/test_monitor_runtime.py`、NEW `tests/unit/test_runtime_reconciliation.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q`，使用假时钟和物理请求计数。

### 检查点 C1 — 行情源恢复

- [ ] A01、A02、A04、A05 离线通过；串行请求/冷却上限不变；使用 `xhigh` 检查迁移和新记录完整性。

## 交易时段与业务状态恢复

- [ ] RR007 — 计算交易时段感知恢复目标。强度：`high`。依赖：C1。
  - 验收：A03/A10；日历未知仍有重试唤醒，待机不意味着可操作实时数据，跨日和回拨不使用未来数据。
  - 文件：`src/trade_plan_monitor/runtime/scheduler.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、`tests/unit/test_monitor_runtime.py`、`tests/unit/test_runtime_reconciliation.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q`，覆盖完整时段矩阵。
- [ ] RR008 — 用有界步骤恢复精确局部覆盖。强度：`high`。依赖：RR007。
  - 验收：空/部分记录不能证明就绪；截止点冻结；各范围公平推进，不由启动全股票批次独占，保留指数现有重试上限。
  - 文件：`src/trade_plan_monitor/runtime/recovery.py`、`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、NEW `tests/integration/test_runtime_recovery_coverage.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_coverage.py -q`；包含部分/跨日获取及容量受限用例。
- [ ] RR009 — 发现完整错过的收盘义务。强度：`high`。依赖：RR008。
  - 验收：15:20 前停止/17:00 后重启及多日停机，按因果顺序恢复符合条件的缺失收盘；未知历史状态仅阻止依赖计划。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、NEW `tests/integration/test_missed_close_recovery.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_recovery.py -q`；RR012–RR013 前不投递历史提醒。
- [ ] RR010 — 隔离依赖变化及两类计划恢复。强度：`high`。依赖：RR008–RR009。
  - 验收：A06/A09；参考键覆盖需求和激活；同股票显式转旧计划补取缺失资料；旧代次不能提交当前决策。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/production_context.py`、`tests/integration/test_explicit_runtime_production.py`、NEW `tests/integration/test_recovery_activation_fences.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_explicit_runtime_production.py tests/integration/test_recovery_activation_fences.py -q`。

### 检查点 C2 — 恢复目标正确

- [ ] A03、A06、A07、A09、A10 离线通过；使用 `xhigh` 独立检查收盘发现、状态重建及激活语义。

## 通知安全与生命周期

- [ ] RR011 — 增加持久投递资格，不改变哈希。强度：`high`。依赖：C0、C2、迁移批准。
  - 验收：历史资格/过期/抑制持久化，事件载荷/哈希不变；旧待发送记录按安全关闭方式分类，不删除。
  - 文件：NEW 增量迁移、`src/trade_plan_monitor/state/models.py`、`src/trade_plan_monitor/notifications/outbox.py`、`tests/unit/test_notification_outbox.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_notification_outbox.py -q`，包含迁移中断/黄金载荷用例。
- [ ] RR012 — 两类评估事务都应用提醒资格。强度：`high`。依赖：RR010–RR011。
  - 验收：A08；状态/声明和投递资格原子提交；保留历史结果哈希、真实风险通知及显式激活身份；不提交无条件可投递的陈旧意图。
  - 文件：`src/trade_plan_monitor/runtime/service.py`、`src/trade_plan_monitor/runtime/explicit_service.py`、`tests/integration/test_explicit_runtime_production.py`、NEW `tests/integration/test_recovery_alert_eligibility.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_eligibility.py tests/integration/test_explicit_runtime_production.py -q`。
- [ ] RR013 — 停机后待发送提醒增加投递门禁。强度：`high`。依赖：RR012。
  - 验收：过时未发送操作消息被抑制且有审计原因；风险消息等待每计划当前状态恢复门禁及最新状态复核（D1 突破/D2 解除）；两类计划加载器及现有不确定发送处理正常。
  - 文件：`src/trade_plan_monitor/notifications/dispatcher.py`、`src/trade_plan_monitor/notifications/outbox.py`、`tests/integration/test_notification_delivery.py`、`tests/integration/test_recovery_alert_eligibility.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_recovery_alert_eligibility.py -q`，仅使用假渠道。
- [ ] RR014 — 降级启动期间保持协调器运行。强度：`high`。依赖：RR006–RR013。
  - 验收：A04/A11；本地启动独立于行情 IO；唯一所有者、可中断等待、进展截止时间及安全停止；预期错误不耗尽崩溃监督预算。
  - 文件：`src/trade_plan_monitor/runtime/service.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、`src/trade_plan_monitor/web/monitor_composition.py`、`tests/integration/test_runtime_lifecycle.py`、`tests/integration/test_monitor_production_composition.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q`，针对注入的新生命周期；公开默认切换保留到 RR020。

### 检查点 C3 — 安全自主运行

- [ ] A04、A08–A11 离线通过；使用 `xhigh` 审查提交/崩溃/发送窗口、代次变化和物理工作线程清理。

## 状态与用户可见恢复

- [ ] RR015 — 如实投影生命周期和局部状态。强度：`high`。依赖：C3、RR002。
  - 验收：存活/恢复/待机/阻止区分有效；全局布尔值不授权工作；正常连接不能掩盖协调器进展逾期。
  - 文件：`src/trade_plan_monitor/runtime/health.py`、`src/trade_plan_monitor/web/routers/health.py`、`tests/integration/test_runtime_lifecycle.py`、NEW `tests/integration/test_runtime_status_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_status_contract.py tests/integration/test_runtime_lifecycle.py -q`。
- [ ] RR016 — 返回兼容两类计划的局部总览投影。强度：`high`。依赖：RR015。
  - 验收：A06/A12；等待/新股票不隐藏健康条目，显式规则结果读取正确存储，缓存决策不升级为可操作。
  - 文件：`src/trade_plan_monitor/web/persistent_monitor_read_service.py`、`src/trade_plan_monitor/web/routers/dashboard.py`、`src/trade_plan_monitor/web/routers/symbols.py`、`tests/integration/test_persistent_monitor_read_service.py`、`tests/integration/test_runtime_status_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_persistent_monitor_read_service.py tests/integration/test_runtime_status_contract.py -q`；保留现有未提交指数读取测试。
- [ ] RR017 — 版本化传输并重新生成契约。强度：`high`。依赖：RR016。
  - 验收：精确实现 RR002 版本握手、安全拒绝不兼容客户端、序号/代次刷新语义；OpenAPI 和生成类型一致。
  - 文件：`src/trade_plan_monitor/web/websocket.py`、`tests/integration/test_websocket.py`、`tests/integration/test_openapi_snapshot.py`、`openapi.json`、`web/src/api/generated.ts`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_websocket.py tests/integration/test_openapi_snapshot.py -q`；批准生成后运行 `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check`。
- [ ] RR018 — 前端分离传输与业务恢复状态。强度：`high`。依赖：RR017。
  - 验收：保留代次刷新、重连和快照序号保护；后台降级不会形成含糊不清的无限 STALE/重连循环。
  - 文件：`web/src/composables/useMonitorStream.ts`、`web/src/stores/monitor.ts`、`web/tests/unit/useMonitorStream.spec.ts`、`web/src/api/health.ts`。
  - 验证：`npm --prefix web run test -- --run tests/unit/useMonitorStream.spec.ts`；`npm --prefix web run type-check`。
- [ ] RR019 — 展示待机、重试和局部进展。强度：`high`。依赖：RR018。
  - 验收：原因/下次重试或必要操作明确；没有工作时不展示恢复横幅；缓存截止时间可见，健康条目仍可用。
  - 文件：`web/src/views/SystemRouteView.vue`、`web/src/components/health/MarketStatusStrip.vue`、`web/tests/unit/SystemHealthRoute.spec.ts`、NEW `web/tests/unit/RuntimeRecoveryStatus.spec.ts`（若需额外指数卡片工作，另拆任务）。
  - 验证：`npm --prefix web run test -- --run tests/unit/SystemHealthRoute.spec.ts tests/unit/RuntimeRecoveryStatus.spec.ts`；`npm --prefix web run type-check`。

### 检查点 C4 — 端到端状态契约

- [ ] A06、A11、A12 及类型/契约门禁通过；`xhigh` 评审检查旧缓存客户端、显式计划读取及真实进展与连接活动的区别。

## 集成与交付

- [ ] RR020 — 启用完整路径并离线证明真实进程重启。强度：`high`；故障分析/评审：`xhigh`。依赖：C4。
  - 验收：所有目标时段覆盖 A01–A14；在提交和投递窗口停止/终止/重启；迁移中断安全；不访问行情源，不发送真实通知。
  - 文件：`src/trade_plan_monitor/web/monitor_composition.py`、NEW `tests/integration/test_anytime_runtime_recovery.py`、`web/tests/e2e/production-restart.spec.ts`、`web/tests/e2e/r13-active-process-restart.spec.ts`、NEW `web/tests/e2e/runtime-recovery.spec.ts`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_anytime_runtime_recovery.py -q`；`npm --prefix web run test:e2e -- production-restart.spec.ts r13-active-process-restart.spec.ts runtime-recovery.spec.ts`，使用隔离测试状态。
- [ ] RR021 — 同步运维与验证证据。强度：`high`。依赖：RR020。
  - 验收：重启/首次数据源验证/重新配置/回滚说明准确；仅记录实际执行的测试；中英文一致。
  - 文件：`docs/operations/live-certification.md`、`docs/operations/live-certification.zh-CN.md`、NEW 成对 `docs/verification/runtime-recovery-acceptance.md` / `runtime-recovery-acceptance.zh-CN.md`。
  - 验证：对照两种语言的 ID/命令/阈值/字段；逐项追踪 A01–A14 结果证据。
- [ ] RR022 — 运行全量离线门禁和最终质疑评审。强度：`xhigh`。依赖：RR021。
  - 验收：提案第 7 节全部门禁通过，保留现有无关修改，无未解决实质问题，差异不包含密钥或放宽的测试；真实环境限制如实列出。
  - 文件：成对验收报告及本成对任务表（4 个文件）；不在评审任务中夹带修复，修复返回有界实现任务。
  - 验证：执行提案第 7 节全部完整命令，检查差异和崩溃矩阵；可核验时记录实际模型/强度及用户评审结果。

### 检查点 C5 — 可进入部署评审，尚未部署

- [ ] 用户评审已完成的离线证据。生产备份、真实行情验收和上线另行授权。仅当明确批准的范围实际达成时，才将专项标为完成。
