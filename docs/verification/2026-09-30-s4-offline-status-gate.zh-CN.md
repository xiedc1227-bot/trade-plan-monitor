# 业务第 4 步：离线状态与页面门禁

## 状态与固定范围

**在批准的第四步离线范围内 COMPLETE。C4 CLOSED。** 后端/前端源码、真实 Chrome 证据及成对收尾评审已获独立批准；最终冻结全量回归通过。 最终冻结后端源码/测试 HEAD：`0f1df66d20cdc52bc542cd69052b2995c1bfe614`。生产恢复源码仍为已批准的 `2775f2b` 候选。首次后端全量 HEAD：`d5e045c234ca8b91aefe3c41f472e0147e1b49e1`。绕过构造函数的夹具对齐已提交为 `6b35a1a`；已评审前端已提交为 `3589186`。最终全量运行期间，后端源码、收集到的测试及脚本保持不变。实际测试的浏览器夹具/规格及留存证据已提交为 `1747a9e`；该提交不改变已测试后端源码或收集到的测试。

范围是已批准离线环境内的 RR002、RR015–RR019 和业务第 4 步/C4。默认生产构造和已安装资源保留版本 `1`。版本 `2` 需要显式选择组合/应用及独立预览构建。RR020、第 5 步/C5、完整 A01–A14 发布验收和真实运行仍独立。

全部证据使用临时 SQLite、fake SDK/HTTP/channel 边界和受控时钟。没有访问真实行情源、真实 LLM、外部通知、用户数据库迁移、push 或部署。配置替换仍要求安全停止 → 人工编辑 → 新进程；本次没有增加热加载。

## 已实现边界

| 门禁 | 具体证据与保留行为 |
| --- | --- |
| RR015 / A11 | 实际 owner 的启动、本地复核、采集、验证/持久化和逐计划提交报告有界完成单位。读取、持久化 owner 心跳、连接帧和原始 provider 成功不报告进展。单调时钟逾期工作保持 `STALLED`，直到实际完成；物理清理先于 `STOPPED`。本地 30 秒唤醒保留已经选定的市场任务截止。 |
| RR016 / A06, A12 | 两类计划读取各自已提交存储。首次结果缺失是局部 `UNAVAILABLE` 条目；身份有效的历史结果是 `CACHED`。六个状态 GET 和心跳读取执行零 SQL 写入。完成证明绑定运行代次、配置、活动身份、精确目标及实际消费输入。 |
| RR016 / D5 | 当前提醒资格仍由后端逐规则判定。盘中有效期使用原回执截止，包括恰好到期边界。状态风险保留原分类器和恢复屏障。`ONCE_ALREADY_EMITTED` 的 R2 保留原 R1 的 event/hash/评估时间；缓存结果不获得资格。 |
| RR017 | 精确请求头 `X-Monitor-Contract-Version: 2` 在请求体解析/服务执行前保护六个 GET 和十个 POST。重复、逗号拼接、缺失及非规范版本安全失败。独立 OpenAPI/类型和构建 manifest 保留默认版本 `1`。已提交事件 payload 仍为 schema version `1`；v2 心跳携带已投递回放游标和真实 owner 状态。 |
| RR018 | 传输状态与业务就绪独立。连接/快照/静默截止为 20/20/40 秒。资格定时器使用后端观察/截止减去完整单调请求耗时，只撤回展示。epoch、运行代次、游标和激活屏障拒绝迟到结果。每个受保护命令先进行经过验证的同源 health 预检。 |
| RR019 | 首页、系统和个股页展示原因、重试/复核时间及局部进度。全局生命周期/故障失权撤回当前展示。受阻可选指数或等待计划不能授权或抑制无关计划。原 bars/events、图表、持仓和命令页保留端点。 |

单个指数快照可能消费三次有界 controller 执行。其截止在启动时按实际最大预算冻结：`3 × 3 × (15 seconds admission + 15 seconds physical wait) + 30 seconds validation = 300 seconds`。这是单个经过验证的不可变快照，不是整个指数批次，也不是额外超时宽限。单调时钟到 290 秒时，兄弟完成不能延长另一个快照原本的 300 秒截止；301 秒是 `STALLED`。原始阶段不更新进展。合法晚到快照可以通过实际完成恢复进展。

受控重试处置只有在 `TIMEOUT`、`TRANSIENT`、`RATE_LIMITED` 或 `BLOCKED_PERMISSION` 且实际已安装 `next_retry_at` 时才能完成本地进展。这不释放超时物理 worker。未知失败和取消保留未完成工作；停止仍等待真实 controller drain。

## 评审发现与修正

独立 `gpt-6-astra` / `xhigh` 源码评审批准上述固定 HEAD 的后端候选和当前前端候选，在已评审范围内没有剩余 P1/P2。有界实现及独立 reader 工作遵循现有任务模型分工。评审发现并验证了这些实质修正：

- 官方收盘输入证明包含实际历史日线及 `daily_indicator_snapshot.source_bar`。最大合法集合是 500 条历史加当日一条，共 501 条。待补收盘义务成功移除后，保留匹配当前运行代次的 `OFFICIAL_CLOSE` 证明；新适用目标、配置或身份撤回证明。
- 留存提醒历史没有人为的 256 行业务上限。真实 `DATE_RANGE`/`EACH_QUALIFYING_BAR` 风险计划在六个交易日提交 257 条提醒。当前规则按激活/规则/动作读取来源，验证原意图并保持只读。legacy 盘中来源使用精确意图身份；持续风险独立考虑三个风险阶段并保留原分类器。
- 时钟跨过截止时，本地进度唤醒不再跳过睡眠前已选定的市场任务。
- 生命周期 `STOPPING` 和根级运行故障即使在协调器仍有工作时，也撤回前端资格。严格前端验证与后端生命周期、计划 symbol 唯一性及显式当前目标约束一致。
- 已断开的连接在失败清理时不再抛出第二个传输异常；失败仍以代码 `1011` 关闭，绝不发出健康心跳。
- 历史响应比较经过验证、语义等价的上海时间，不再要求小数秒格式完全一致；UUID 版本 `[1-5]` 与 `SymbolEventView` 保持一致。保留真实一分钟/五分钟历史及原始 R1 事件。

真实 Chrome 路径发现恢复缺口：源分钟可以补齐，但缺失的五分钟 K 线没有补建。下一次真实结果因缺少 `ROLLING_VOLUME_WINDOW` 而正确保持 `CACHED`。已批准修正通过实际股票所有者任务，仅补建经过验证、冻结范围内的完整 K 线；源分钟已存在时不请求行情源。部分/跨时段 K 线以及运行代次/配置/激活/取消变化均不能写入。错过的目标不产生求值、提醒、资格或投递记录；只有后续真实市场任务才恢复完整证明及 `CURRENT`。两个实际所有者入口用例在旧方法下为 RED、修正后为 GREEN。最终 Chrome 验收、冻结全量回归及成对收尾评审均已通过。

## 验证结果

这些是独立且有重叠的运行，不能相加计数。

| 验证 | 实际结果 |
| --- | --- |
| 独立后端最终组合 | 151 passed，1 条既有 Starlette warning，26.39 秒；覆盖 progress、owner、真实 pipeline、commit observer、composition、official close、projection、WebSocket 和 negotiation |
| 默认 API/OpenAPI/WebSocket/composition 回归 | 206 passed，1 条既有 Starlette warning，27.82 秒 |
| WebSocket 失败清理增量及相邻回归 | 27 passed，1 条既有 Starlette warning，5.79 秒；独立新增失败清理测试也通过 |
| 独立前端状态/命令/截止/UI 验证 | 124 项通过；独立构建隔离验证另有 2 项通过，共 126 项不同测试 |
| 独立历史/parser/UI 增量 | symbols、validators、UI 和 route-read 共 62 项通过 |
| 独立恢复成交量窗口增量 | 新增 7 项及相邻 4 项通过，共 11 项不同测试；覆盖实际所有者入口、完整历史、不重放、部分/时段及身份/取消屏障 |
| 前端全量单元和类型检查 | 56 个文件 / 807 项测试通过；类型检查和隔离预览构建通过；最终 Chrome 验收已通过 |
| 首次后端完整离线回归 | 固定 `d5e045c`：5910 passed、3 failed、1 skipped、4 deselected、1 条既有 warning，1437.61 秒；不能视为通过 |
| 测试夹具对齐及相邻回归 | 67 passed，47.89 秒；两个绕过构造函数的夹具将新增可选进展字段初始化为 `None`，保留全部既有断言 |
| 第二次后端完整离线回归 | 固定 `2775f2b`：5915 passed、5 failed、1 skipped、4 deselected、1 条既有 warning，1169.90 秒；不能视为通过 |
| 精确派生历史夹具对齐 | 实现组合：46 passed、1 条既有 warning，45.89 秒；独立完整双文件运行：39 passed、1 条既有 warning，14.69 秒 |
| 最终后端完整离线回归 | 固定 `0f1df66d20cdc52bc542cd69052b2995c1bfe614`：5920 passed、1 skipped、4 deselected、1 条既有 warning，1140.87 秒 |
| Ruff、空白和生成契约 | 最终全量运行后通过；默认版本 `1` 与独立版本 `2` 快照/类型均最新；已测试后端路径保持不变 |
| 实际 Chrome 旅程 | 2 passed（2.6m），project `chrome`；原始 JSON、精确源码/测试 hash 及八张截图已获独立批准 |
| 双语一致性和最终 C4 评审 | 已批准：结构、稳定 ID、内联契约、命令、阈值、证据映射及范围边界一致；C4 仅在本离线范围关闭 |

项目根目录的后端命令：

```text
.venv/Scripts/python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check --monitor-contract-version 2
git diff --check
```

`web/` 下的前端命令：

```text
npm run test -- --run
npm run type-check
npm run build:runtime-status-preview
npm run test:e2e -- runtime-status-sqlite.spec.ts runtime-status-old-server.spec.ts --project=chrome
```

完整离线命令保留已批准 S3 的重型回测排除，并不选择标记为 `live` 的测试。保留的 Windows 跳过为 `test_cursor_key_rejects_foreign_posix_owner_before_use`，需要 POSIX 所有权语义。既有 Starlette/httpx 弃用警告仍明确列出；两者都不是新放宽。

首次全量运行失败的是 `test_completed_close_pending_clear_without_health_event_still_requires_commit_admission` 的两个参数，以及 `test_missing_current_calendar_has_a_distinct_local_category`。这些夹具绕过生产构造函数。仅增加 `_progress_unit` 和 `_status_progress_owner` 初始化；没有引入生产容错后门、跳过用例或弱化断言。

第二次全量运行发现四项 A06 准备断言把派生五分钟历史视为禁止写入，以及一个完整前缀夹具仅准备源分钟。已批准的纯测试对齐逐个独立重算新增完整冻结 K 线并精确比较存储字段，保留全部既有历史行，并保持其余全部业务表不变。完整前缀夹具在原事务中准备六条规范完整 K 线；其 `READY`、30 秒唤醒和零行情请求断言均保持不变。纯测试修正提交即上述最终冻结 HEAD；没有为这些失败修改生产源码。

## 浏览器验收与保留限制

Chrome 夹具启动时没有活动计划或库存。旅程通过普通 UI 使用 fake HTTP transport 提取、人工复核、激活及库存命令，然后由实际 scheduler/provider/SQLite 求值。只有真实库存 POST 响应 `200` 才作为保存证据；被 epoch 取消的零 POST 尝试不是保存。显式风险 tape 在 R1 后保持风险条件满足，使 R2 抑制能够证明来源保留，而不是掩盖已解除风险。

双家族控制通过领域仓储安装真实 legacy 计划，提供合法参考事实并保留分钟缺失。截止控制冻结实际 SDK 分钟输出，不替换状态 JSON。停滞控制将实际 owned 操作保持到冻结截止之后，同时兼容传输心跳继续，再释放操作以实际完成。生产心跳仍为 20 秒；只有隔离夹具以 0.2 秒观察。

最终运行的[选取原始观察及回执](assets/s4-final/browser-summary.json)保留实际 scope、progress、eligibility、来源、请求和错误字段。该文件还记录精确前端/测试 SHA256 及完整原始 JSON、服务日志所在的隔离路径。

| 2026-09-14 受控上海时间 | 实际后端及页面结果 |
| --- | --- |
| 10:20:15 → 10:25:15 | R2 为 `ONCE_ALREADY_EMITTED` 时保留有效 R1 风险和完整原始来源；R2 结果 hash 不同 |
| 10:30:15 | 显式 `003043.SZ` 为 `CURRENT`/`READY`；legacy `600000.SH` 为 `RECOVERING`/`UNAVAILABLE` |
| 10:35:15 | `RECOVERING`/`CACHED` 的 10:30 结果；进度数量未知、risk false、原始来源时间 10:20 |
| 10:36:15 | `WAITING`/`CACHED` 的 10:30 结果，risk false；历史修复不重放错过的结果 |
| 10:40:15 | 真实五分钟任务：10:40 的 `CURRENT` 结果、`READY` 进度 3/3、R1 risk true |
| 10:41:01，任务被阻塞 | 传输 `LIVE`、生命周期 `RUNNING`、协调器 `STALLED`、模式 `BLOCKED`；10:40 结果为 `CACHED`、risk false；后续连接观察中 `lastProgressAt` 始终为 10:40:45 |
| 10:41:01，释放任务 | 协调器为 `SCHEDULED`；计划为 `RECOVERING`/`CACHED` 的 10:40 结果，risk false |
| 10:41:15 | 真实分钟任务恢复匹配证明：10:40 的 `CURRENT` 结果、`READY` 进度 3/3、R1 risk true，没有重放 10:40 求值 |
| 10:45:15 | 新的真实五分钟任务：10:45 的 `CURRENT` 结果、`READY` 进度 3/3、R1 risk true |

R1 始终为 event `d0277a64-c054-57d7-9dc3-7d79c89a4190`、结果 hash `4186b620f5fe44808cb3d7e32001f602bc97e14dc0a5c6d2ad4fcb7965e08a32`，评估时间 10:20:15、截止 10:20:00。停滞控制选中的是 10:40:45 的真实维护任务。10:41:01 释放后，夹具先推进到 10:41:15，使假 SDK 分钟匹配实际选中的任务。此前直接从 10:41:01 每次跳一分钟，错过了所需源分钟；已观察到后续修复正确地不重放错过的五分钟结果。没有放宽生产调度或 `CURRENT` 要求。

总览在 320/768/1024/1440 像素下均无横向溢出。1440 像素总览在选定的 WCAG 2.1 A/AA tags 下 axe 违规为零；不代表每个页面或宽度均已认证。实际验证了系统、股票一分钟/五分钟历史、原始事件及深层命令页面。八张实际截图保留在 `assets/s4-final/`，包括 [320 像素](assets/s4-final/s4-v2-320.png)、[停滞](assets/s4-final/s4-v2-stalled.png)、[恢复](assets/s4-final/s4-v2-last-page.png)和[旧服务命令](assets/s4-final/s4-v2-old-server-command.png)。

最终 v2 路径记录 55 个版本 2 socket，原始控制台错误、失败 HTTP 响应/503、诊断错误、未捕获页面错误及外部请求均为零。旧服务深层库存尝试记录六个 GET、零 POST，控制台/页面/外部请求错误为零；health 响应没有版本 2 头。日志均已保留。最终运行没有执行受保护的 503 分类分支；此前失败的探索运行不能被描述为无错误验收。两个隔离服务均正常关闭。最终冻结后端回归及成对报告评审已通过；C4 在此范围内关闭。

本门禁之后，默认启用及完整进程/发布验收仍属于 RR020 和第 5 步。这里不认证真实 provider 权限、OS 级多实例互斥或外部 exactly-once 投递。
