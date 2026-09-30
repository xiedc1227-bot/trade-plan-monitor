# 原第四步：运行恢复最终离线验收

## 状态与范围

**OFFLINE_IMPLEMENTATION_COMPLETE。** 本报告记录原四步改造内剩余的集成、验证与文档工作，不新增第五步或交易规则。基线 HEAD：`e09c3ea30b5ce0c32dea4ec6734ded3aebf45b26`；冻结最终后端 HEAD：`185263aa5d78065c40ffc3287023d35faa16cbed`。完整浏览器通过 HEAD 为 `d4db557b19aeda20c034db09a8e151193f0476e0`；之后仅隔离两个 Python 测试夹具，生产、前端或浏览器输入均未变化。此前两次完整浏览器候选为 `0e0621868d13c847e45089d904ab6aa33cdb1e23` 和 `a00af51555e277a50b719e3e4a4e9a9d93a9786d`。最终后端门禁已通过；C5 用户证据审核仍待完成。

范围：已批准的 D1–D8 / A01–A13、正常生产入口与配套 monitor contract version `2`、真实临时数据库进程重启、既有崩溃/发送/迁移矩阵、提案第 7 节全部离线门禁和双语运维文档。D9/A14 提醒关联卖出登记仍为 API 未批准的后续工作，不实现、不计入完成声明。既有持仓登记和提醒已读行为保持不变。

全部状态为临时状态，行情源/LLM/渠道边界离线，不使用用户数据库、真实行情源、外部通知、推送或部署。配置替换仍要求成功停止 → 人工编辑 → 新进程。本次收尾不引入热加载、新依赖或新迁移。

## 最终集成修改

- `create_production_app` 默认 monitor contract version `2`，普通 CLI 使用该工厂。延迟组装保持构造期间不执行行情源/数据库工作，并在启动前校验实际生命周期读取服务，失败时完成清理。
- 正常前端构建与 Python 安装包包含匹配的 v2 资源及 `monitor-contract.json`。已检查本地实际构建的 wheel，包含版本 `2` 标记和 HTML 入口。
- 默认契约生成/检查覆盖规范 v2 与明确的 v1 兼容夹具。两个快照保持批准的线上字段契约。
- 既有 v1 浏览器及有界 R14 诊断夹具使用隔离的 `web/dist-legacy-test` 资源。业务断言和诊断预算保持不变。R14 工具要求 `npm --prefix web run build:legacy-test`，这不会选择正常 CLI 的资源。
- 正常入口进程/时段及浏览器重启测试验证已安装路径。复用既有崩溃、投递、权限、失效和迁移测试，不替换它们。

## 验收追踪

历史报告保留其被测版本与限定结论。其证据与新增正常入口验收及最终完整回归组合；历史通过本身不构成新的全量通过。

| IDs | 证据与保留边界 |
| --- | --- |
| A01, A02, A04, A05 / C1 | [S3 汇总](2026-09-27-s3-final-offline-gate.zh-CN.md)：兼容语义导入、八操作分 scope 权限恢复、持久冷却、独立重试时钟及有界串行请求。 |
| A03, A07, A10 | [S3 汇总](2026-09-27-s3-final-offline-gate.zh-CN.md)、`test_anytime_runtime_recovery.py`：时段目标、未知/不完整数据、时钟/时段变化及正常入口顺序进程。待机/缓存展示不授予当前交易资格。 |
| A06, A09 | [S3 身份/故障矩阵](2026-09-27-s3-final-offline-gate.zh-CN.md)、[S4 状态验收](2026-09-30-s4-offline-status-gate.zh-CN.md)：两类计划、必需/可选依赖隔离及代次/配置/启用围栏。 |
| A08 | [遗漏收盘终止测试](2026-09-27-s3-missed-close-kill-restart.zh-CN.md)、[通知终止测试](2026-09-27-s3-notification-kill-restart.zh-CN.md)、[S3 汇总](2026-09-27-s3-final-offline-gate.zh-CN.md)：原子意图、提交/发送中断、不确定回执处理及实际停止/排空。不声称外部投递普遍恰好一次。 |
| A11, A12 / C4 | [S4 状态验收](2026-09-30-s4-offline-status-gate.zh-CN.md)、最终正常入口浏览器验收：权威状态、GET/WS 代次一致、缓存结果、明确兼容性拒绝及匹配的安装资源。 |
| A13 | `test_runtime_liveness.py`、`test_runtime_plan_expiry.py`、S3 汇总：中断基于合法所有者持久存活记录；`>120` 小时使计划失效，恰好相等不会失效。未知历史保持阻断，保留持仓与确认交易。 |
| Migration/rollback | `test_index_permission_scope_migration.py`、`test_runtime_recovery_storage.py`、`test_sqlite_backup.py`：临时数据库上的增量迁移中断回滚、保留状态时拒绝降级、包含 WAL 的备份/恢复。 |
| D9/A14 | 独立且 API 未批准的后续工作，不新增提醒关联卖出接口或修改卖出/提醒规则。 |

C2 还直接依据[历史收盘证据测试](../../tests/integration/test_historical_close_evidence.py)（最近已提交收盘、长时间活动计划、损坏锚点及有界的连续无变化收盘查询）、[遗漏收盘执行测试](../../tests/integration/test_missed_close_execution.py)（两个因果顺序收盘、历史持仓、风险来源时间、最近适用意图及过期启用拒绝）、[持仓边界测试](../../tests/integration/test_inventory_history_boundaries.py)和[持仓事务测试](../../tests/integration/test_position_inventory_recovery_transactions.py)。契约保留在 [runtime-recovery](../specifications/monitoring/SPEC-runtime-recovery.zh-CN.md)；实际接续证据见 [restart continuation](runtime-recovery-acceptance.md#restart-continuation-cleanup-and-health-visibility--2026-09-23) 与 [latest node/opening holdings](runtime-recovery-acceptance.md#latest-node-continuation-and-opening-holdings--2026-09-23)。有限、无效或不完整的历史证明仍仅阻断受影响计划，不增加无限历史恢复承诺。

## 已执行检查

各次运行互相重叠，数量不累加。最终完整后端和浏览器套件在记录的冻结输入上均通过，已批准离线实现已完成。

| 检查 | 实际结果 |
| --- | --- |
| 正常入口组装与读取服务防护 | 10 passed，1 条既有警告，1.79 秒；两个新增行为用例先在旧源码上失败。 |
| 相邻默认/显式兼容组装 | 最终正常安装资源构建之前为 71 passed、1 条既有警告、10.01 秒。之后完整尝试发现三个旧测试实例仍读取正常包资源；其修正及最终回归另行记录。 |
| 安装包测试 | 12 passed，1 条既有警告，1.65 秒；实际本地 wheel 也包含版本 `2` 标记。 |
| 默认契约生成器 / 启用 / 快照 | 25 passed，1 条既有警告，27.38 秒；默认检查两个已批准契约。 |
| 保留的 R14 离线诊断 | 24 passed，1 条既有警告，15.23 秒。未执行付费诊断。 |
| 正常入口时段/进程矩阵 | 6 passed，33.69 秒；11 个独立操作系统进程，五个时段及缺凭证阻断。保留计划/启用/结果/提醒来源；GET/WS 使用实际同一代次，心跳不延长进展期限。 |
| 复用的崩溃/迁移/失效矩阵 | 51 passed，82.17 秒：遗漏收盘终止、通知终止、投影迁移及计划失效。 |
| 已安装午休/存活回归 | 8 passed，4.32 秒。 |
| 新增正常入口 Chrome 路径 | 1 passed，1.5 分钟；实际进程 `57572 → 6200` 均正常退出，完整旧提醒行保留，验证 `CURRENT → CACHED → CURRENT` 及正常 20 秒 WebSocket 节奏。两项同源 GET 取消与意外失败分别留证；无控制台/页面/外部错误。 |
| 完整前端单元测试 | 56 个文件 / 808 passed；类型检查通过。 |
| 旧版浏览器夹具隔离 | 31 passed，38.1 秒，保留原断言。 |
| 正常前端构建 | 通过；正常与安装资源各 58 个文件，目录标记 SHA-256 一致，为 `71caaaef6a0a540c3a10fc87aa82060a071cf1d301d341a5f41275d3b1c9796d`。两处协议标记均为 `2`。 |
| 完整后端 `not live`，包含重型回测验收 | `185263aa` 上 5948 passed、1 skipped、4 项 live deselected、1 条既有警告，3291.64 秒，退出码 `0`。8 项重型回测验收全部通过，不新增排除项或降低阈值。[完整结果与测量值](assets/rr-final/backend-final-summary.json)。 |
| `d4db557b` 上首次完整后端尝试 | 确认夹具不匹配后在 33% / 2018 个已报告标记处停止，1 项失败、1 项既有跳过，不计为全量通过。直接 AI 夹具复现为 1 failed、1.66 秒；两个 R15 诊断参数因同一 v1 夹具/v2 包资源不匹配而 2 failed、1.72 秒。[保留运行与诊断](assets/rr-final/backend-first-interrupted-summary.json)。仅修正测试资源隔离，完整后端门禁重新执行，不排除用例或修改阈值。 |
| 旧版 Python 资源隔离 | 3 个失败实例 → 两个整文件共 9 passed，1 条既有警告，2.69 秒。各旧版夹具读取带明确版本 `1` 标记的临时包，原 AI 配置、诊断及客户端关闭断言保持不变。正常包版本 `2` 和生产资源校验不变。 |
| `0e062186` 上首次完整 Chrome 套件 | 18 个规格共 43 项，39 passed、4 failed，9.6 分钟，不计为通过。一项旧夹具缺少缓存指数历史，三项旧夹具跳过实际维护/市场唤醒。正常生产重启、正常恢复及两条 C4 路径通过。原严格断言保留，仅修正测试夹具。 |
| 有界旧夹具修正 | 四项原失败均通过：三项 R13 耗时 2.0 分钟，R12 耗时 42.3 秒。缓存指数事实保持 `BLOCKED` 且无 indicator facts；精确释放旧版唤醒保留最终时钟目标。未修改生产/前端/规格断言。 |
| `a00af515` 上第二次完整 Chrome 套件 | 42 passed、1 failed，9.1 分钟，不计为通过。剩余严格分类器拒绝 `market-duty-10:20` 的一次已脱敏总览 `503`；页面在 57.6ms 后撤回风险资格，后续实际 `CURRENT` / 原 R1 证据通过。内部原因未记录，因此不追溯认定为 authority race。已加入纯测试原因观察，未知/存储失败仍不可接受。 |
| 读取失败观察防护 | root 复核为 4 passed、1 条既有警告、2.48 秒。真实正常读取、两次尝试的权威状态竞争、存储失败及读取服务不可用路径，在观察前后保持响应字节、响应头及 SQL 语句完全一致。浏览器边界阶段仅接受精确的原权威状态竞争异常；每个 `503` 必须匹配真实请求 ID 并撤回操作资格。生产读取服务和重试策略未变化。 |
| 最终完整 Chrome 套件 | 冻结 `d4db557b` 上 18 个规格共 43 passed，9.0 分钟，单 worker、零 retries、退出码 `0`。 |
| 最终代码与契约检查 | Ruff `src tests scripts` 通过。默认生成器核对规范版本 `2` 和兼容版本 `1`。完整非 live 收集为 5949 项选中 / 5953 项总计，4 项 live 排除；不排除回测验收。 |
| 最终源码评审 / 双语一致性 | 通过：root 审查正常工厂/实际读取服务/资源、有界夹具修正及原因观察防护，汇总既有 S3/S4 独立评审与最终范围评审，并核对成对章节、IDs、命令及阈值。无未解决的实质问题。不声称新增跨模型评审；用户已免除额外评审。 |

已完成的专项与完整命令（从仓库根目录执行）：

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_status_composition.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_packaging.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_frontend_contract_promotion.py tests/integration/test_openapi_snapshot.py tests/integration/test_runtime_status_routes.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_r14_bounded_acceptance.py tests/integration/test_r14_offline_wiring.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_anytime_runtime_recovery.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_browser_read_diagnostics.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_configured_ai_web.py tests/integration/test_r15_extraction_diagnostics.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py tests/integration/test_s3_notification_kill_restart.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_runtime_plan_expiry.py -q
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -u -m pytest -m "not live" -v --tb=short --durations=10 -o junit_logging=system-out --junitxml=<temporary XML>
npm --prefix web run test:e2e -- --project=chrome
git diff --check
```

最终重型门禁测量：十项 252 日回放每项为 81.32 至 83.22 秒（上限 120）；容量工作集增量 116412416 bytes（上限 768 MiB）、行情/WAL 519073792 bytes（上限 512 MiB）、结果/WAL 184918016 bytes（上限 192 MiB）、跟踪堆 126174567 bytes（上限 384 MiB）。端点查询最大 p95 为 95.61ms（上限 250ms），CSV 最低吞吐量为 9.02 MiB/s（最低 5）。唯一跳过为 `test_cursor_key_rejects_foreign_posix_owner_before_use`，需要 Windows 不具备的 POSIX 文件所有权语义；唯一警告为既有 Starlette/httpx 弃用提示。原始采样、八项用例时长及完整日志保存在[后端结果](assets/rr-final/backend-final-summary.json)。

专项浏览器原始证据为 `C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-gobvmg3k/normal-runtime-recovery.json`，SHA-256 为 `e39b7b7b92071ed5f62cc18f64dfea0547d9bf835faf2e2c65031df0ff43aef8`。该临时记录与最终全套结果分别记录。最终完整 Chrome 在冻结 HEAD 上使用 `npm --prefix web run test:e2e -- --project=chrome`：18 个规格共 43 passed，单 worker、零 retries、9.0 分钟。完整日志：`C:/Users/xiedc/AppData/Local/Temp/tpm-rr020-all-chrome-d4db557b-final-20260930.log`。

指数失败使用基线 `e09c3ea` 历史读取服务、相同 v1 路由和同一失败临时数据库只读复现：四项精确查询均返回 `404`。基线/当前读取服务、路由和旧版趋势 UI 未变化。这是基线读取边界复现，不是完整基线浏览器运行。四项修正仅使用诚实的不可用历史缓存与真实已安装唤醒顺序。R12/active/replace 报告控制台/外部错误为零；stream 规格不采集控制台观察，不能对它额外声称为零。

最终持久证据保存在 [`assets/rr-final`](assets/rr-final/browser-gate-summary.json)，包含完整 Chrome 通过日志、此前两次失败日志及第二次 C4 的未改动原始记录。最终正常入口在进程 `55224 → 80172` 间使用同一临时 SQLite，两次均正常退出：10:10 为 `CURRENT` → 重启后不可操作的 `CACHED` → 10:15 实际 `CURRENT`。错误/外部请求为空；两条实际导航 GET `net::ERR_ABORTED` 取消单独保留。最终 C4 记录有 54 条实际 v2 socket，控制台观察、`503` 响应、读取诊断、诊断/页面错误及外部请求均为零。10:45 决策为实际 `CURRENT`，原 R1 的 event ID/hash/求值时间/cutoff 保持不变。旧服务收到六个 GET、零 POST，health 无 v2 响应头，未记录错误/外部请求。

| 保留证据 | SHA-256 |
| --- | --- |
| [浏览器汇总](assets/rr-final/browser-gate-summary.json) | `06a469b1507211260490dab5bceeaf48a9eb4dfb02f0259a7ac40529a700ec0c` |
| [正常重启](assets/rr-final/normal-runtime-recovery.json) | `7777e30bc98c2b7baf48a62db0c16733875032f86160503335d8d133184d9588` |
| [最终 C4](assets/rr-final/runtime-status-final.json) | `d3a33e9105e6d75ca4510a2b6cddff5e49b64b8b3be217992c4b888da4943cd9` |
| [旧服务](assets/rr-final/old-server-evidence.json) | `884223baa49137b94824c42971c9503b1ff48f7c884418fb8e9db68dcd2ae0b3` |
| [只读基线指数边界](assets/rr-final/baseline-index-404-proof.json) | `260b1b85a7e9af51da600f3d9f3ddef85f038216e67d4600f9121c52210a864c` |
| [完整后端结果](assets/rr-final/backend-final-summary.json) | `6ecfb31289aeeed07406cdab9b22da99b993de4d56fc0f05b34a3fb498fc0992` |
| [完整后端日志](assets/rr-final/backend-final.log) | `7ad0772fc42dc2fd6b54a540d73ce4be4c8f8dbbfd3c7967d2f31c8045fecadf` |
| [前端源码清单](assets/rr-final/frontend-source.manifest.txt) | `4a3f15bb77b73207834b04eef4aeea0b91a98b65d0dec74b2c8eb60a2d299481` |

前端源码清单采用 Windows 原生 Path 排序（不区分大小写），正斜杠路径后接空格和小写文件 SHA-256，以 LF 连接、不含末尾 LF。正常/安装资源保持记录的相同 58 文件哈希；隔离旧版资源为 44 文件、协议 `1`、清单哈希 `79423aa649fecb6295e288fd658d86b6fe5b119f2c802fd3d78623b975a6bc9e`。证据目录禁用 Git 文本转换以保留原始文件字节；局部属性保留原始日志的 Windows 换行及尾随空格，不改变源码检查。

## 完成与交接边界

RR001–RR022、C0–C4 依据实际最终门禁及汇总源码/证据评审，仅按已批准 D1–D8 / A01–A13 离线交付完成。C5 仍为用户对已完成证据的审核，不是剩余实现任务。生产备份、真实行情源验收和部署需另行授权。既有限定历史报告不改写为不受限制的历史恢复。不声称操作系统层并发实例锁或无限恢复容量。

V1d 按已批准 D8/A13 和 `SPEC-runtime-recovery.md` 的存活记录及旧计划处置条款验收。缺少心跳时阻断准入，通过既有预览、指纹和独立确认进行带审计的作废；损坏/未来心跳保持阻断并调查。无法分类的旧提醒保留脱敏审计，不编造终态回执。清理失败记录 `ALERT_SWEEP_FAILED`、保留游标并重试，不中断所有者心跳。旧 V1d 关于额外提醒复核流程和 Web 维护状态字段的建议不属于已批准 D8/A13 或 RS04 契约，未实现，也不加入本次改造。证据为 `test_runtime_plan_expiry.py` 中 `test_old_alert_sweep_audits_corrupt_alert_without_losing_later_valid_one` 和 `test_long_outage_sweeps_receiptless_old_alert_after_transient_failure`。

## 验收后修正：保留总览走势图 — 2026-09-30

用户截图暴露正常 v2 总览仅保留指数文字快照，遗漏既有四指数走势图。这是接线回归，不是获准删除的功能。`web/src/runtime-status/DashboardView.vue` 现复用原 `MarketIndexDataStrip.vue`、`useDashboardMarketIndexTrends.ts` 和历史 API，恢复指数切换、图表、空数据/断连缓存状态及成交额卡片，同时保留运行状态面板。仅通过已提交快照及注入的 fetch 上下文读取展示数据；不修改生产 Python、采集、协议、依赖、交易规则或原四步方案。

两项有效夹具回归测试先在未修复页面失败，再通过。最终前端为 57 文件 / 810 passed，类型、正常构建、双版本生成契约和 Ruff 均通过；安装包/组装/读取诊断专项 26 passed、1 条既有警告、3.21 秒。两条真实 Chrome 重启/状态场景共 2 passed、4.0 分钟；随后加强正常入口的已加载历史数据断言，单项重跑 1 passed、1.5 分钟。重启测试保留原提醒来源、当前资格及零错误断言，另验证四个选择器、真实 Canvas、指数切换和图表已加载历史数据。C4 场景记录 55 条 v2 socket，控制台/页面/响应失败/诊断/外部请求均为零。

首次正常入口浏览器运行因离线 SDK 无指数历史，出现四个 `404`；将既有历史缓存夹具扩展至 v2 后通过，缓存仍为 `BLOCKED`，无指标事实，不编造实时准入。一次前端运行与正常构建同时执行，资源替换使构建隔离检查失败；串行完整重跑通过，未降低断言。原始记录路径和哈希、失败原因及最终检查汇总见[修正证据](assets/rr-final/dashboard-trend-restoration-summary.json)。[图表截图](assets/rr-final/normal-dashboard-trends-restored.png)为临时数据库中的阻断历史数据，已核对实际加载点位，不代表真实行情源验收。

修正后正常与 Python 安装资源仍各 58 文件、协议 `2`，清单 SHA-256 为 `b09c61c481978f8c6164141499ef44f34831f44ca52ab397caacba2f49d8bb4f`；前文旧哈希及完整后端/43 项浏览器通过仍指各自原冻结版本，不追溯改写为此次全部重跑。只读检查确认本地 `http://127.0.0.1:8765/` 返回当前构建 HTML，未重启用户进程或修改用户数据库，刷新页面即可加载修正资源。
