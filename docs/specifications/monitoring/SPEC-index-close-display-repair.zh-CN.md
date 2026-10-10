# 设计：index-close-display-repair

> 英文规范源：[SPEC-index-close-display-repair.md](SPEC-index-close-display-repair.md)。本文是语义等价的中文审阅版。
> 状态：IMPLEMENTED — 2026-10-09 用户授权实施；验收与本地发布证据见配套验收报告。
> 本方案是现有 monitor-index-trends 能力的一项集中修复，不新增监控子系统。

## ICDR01 目标、范围与假设

后续采集失败及进程重启后，仍能展示已经验证的指数行情；交易时段与数据完整性分别呈现；选中指数的点位和曲线对应同一份已提交数据。默认选中指数继续为上证指数（`000001.SH`）。

用户已于 2026-10-09 授权参照此方案实施并完成验收。现有盘中频率、接口权限、数据源接口选择、官方日线核对、计划判断和提醒发送准入均予以保留。范围包括交易时段最后一根行情的独立、有次数限制的补查。不新增依赖或数据源权限。

关联规范：[index-data](SPEC-index-data.zh-CN.md)、[monitor-index-view](SPEC-monitor-index-view.zh-CN.md)、[monitor-index-trends](SPEC-monitor-index-trends.zh-CN.md)、[runtime-status](SPEC-runtime-status.zh-CN.md)、[runtime-recovery](SPEC-runtime-recovery.zh-CN.md)。现有 index-data 规范已禁止失败结果覆盖相同截止时间的成功记录；本设计将该规则落实到持久化层。展示接口是已授权的范围扩展，明确取代此前 trends 不增加公共 API 的限定；既有 DTO 和计划契约保持有效。

## ICDR02 已复现故障与证据边界

2026-10-09 对 `000001.SH` 的本地观察，时间均为 `Asia/Shanghai`：

| 观察时间 | 数据截止 | 结果 |
|---|---|---|
| 15:00:14 | 14:55 | `STALE`，点位 3814.466 |
| 15:20:01 | 15:00 | `LIVE`，点位 3813.791；已存入包含最后一根的完整五分钟数据 |
| 16:00:16 | null | `BLOCKED`、`PROVIDER_UNAVAILABLE`；空采集结果 |
| 16:41 读取 | null / 14:55 | 总览顶部无点位；历史接口返回 47 根，末点 3814.466；运行时指数范围显示 `READY` |

15:20 的成功历史快照仍然存在。历史展示丢失最后一根，是因为读取时跟随当前记录引用，而 15:00 的引用已指向空失败快照。这是引用选择缺陷，成功的不可变数据并未被删除。错误记录能证明采集失败，但不足以确定具体网络或上游原因。3813.791 是已完成五分钟行情的末点，不是本次新核实的官方日线收盘值。

代码路径：`runtime/market_indexes.py` 在内存中保留相同截止时间的成功值，`runtime/service.py` 却持久化传入的失败批次。`state/projections.py` 按观察时间更新引用。总览与 `web/persistent_market_index_history.py` 读取这些持久化引用。组件直接将 `BLOCKED` 映射为“阻断”，没有交易时段状态。

## ICDR03 必须满足的不变量

1. 临时采集失败不能清空或替换相同身份、相同目标的已验证成功快照。重启后选中的有效数据必须与运行中的进程一致。
2. 保留的较早目标或较早交易日数据不能升级为当前数据。旧请求集合不能满足新计划增加的事实要求。
3. 同一目标后续通过验证的数据修订可以替换成功快照。数据源 revision 是内容标识，不是按时间递增的计数器；按采集顺序比较，不能按 revision 数值大小比较。
4. 展示兜底不能授予判断或发送权限。计划消费者保留实际采集结果，并继续执行现有新鲜度、依赖和权限检查。
5. 最近采集失败与已保留数据分别可查。“有效最终点位 + 后续刷新失败”是合法状态，不是互相矛盾的状态。
6. REST 读取不发起数据源调用、修复或业务写入。快照内容、哈希和历史决策证据保持不可变。

## ICDR04 持久化数据与采集结果选择

保留 `market_index_snapshot` 作为不可变采集快照存储。保留 `market_index_snapshot_head` 作为现有精确键 `(mappingVersion, indexCode, decisionCutoff, requestSetHash)` 对应的有效快照引用。新增有界的最近采集表，命名为 `market_index_acquisition_state`，键为 `(mappingVersion, indexCode)`，字段包含 `attemptId`、`decisionCutoff`、`requestSetHash`、`observedAt`、`snapshotHash`、`health`、`issues` 及已提交的 `sequence`。只保存封闭的脱敏代码。下次重试时间从恢复状态读取，不在此重复保存。采集准入绑定现有来源／配置身份和运行代次，表内不保存凭据。来源变化时，即使指数和日期仍匹配，旧数据也失去当前有效资格。

内部来源字段为 `sourceIdentity`、`effectiveSourceIdentity`、`effectiveSnapshotHash`，用于证明所选有效引用来自当前配置／语义来源。旧记录无法证明来源时保留显示并标记 `CACHED`，不能猜测当前有效资格；这些字段不扩展公共 DTO。

后续采集复用已经存储的内容修订时，应以本次实际采集时间与有效引用的 `updated_at` 比较。保留所复用不可变快照的原始 `observed_at`；随后到达的中间时刻旧修订不得回退有效引用或最近采集记录。

持久化、运行时恢复和读取共用一个纯选择规则：

| 当前有效引用 | 相同精确键的新结果 | 有效引用 |
|---|---|---|
| 无 | 任意通过快照结构验证的结果 | 使用新结果 |
| `LIVE` | 采集失败、陈旧返回或缺口返回 | 保留当前数据；更新最近采集记录 |
| `LIVE` | 后续通过验证的 `LIVE` 修订 | 接受新修订 |
| 非实时 | 后续通过验证的 `LIVE` 结果 | 接受新结果 |
| 非实时 | 后续非实时结果 | 记录最新结果；此前可展示数据仍可单独读取 |
| 任意 | 更旧或已被取代的采集 | 不回退有效引用或最近采集状态 |

持久化在同一事务中提交不可变快照、最近采集记录、允许的有效引用变化、恢复状态和现有 `market.index.updated` 失效事件，提交后发布。事件仍只是失效通知，客户端重新读取权威数据。即使有效数据引用保留不变，只要最近采集发生变化，也要发出失效事件。实际尝试快照与有效展示快照必须是明确分开的返回值，不能将失败的计划输入替换为保留的展示值。

展示优先寻找所需目标及当前数据源身份对应的可用数据；否则在选定展示交易日内，选择最近一份经过本地验证且含可展示行情的快照，标记为不完整或缓存。单张卡片不能拼接不同修订。已知身份、时间戳、公式或来源完整性错误必须提示待核验；可保留旧数据作为缓存，但不能标记为完整、当前有效证据。权限错误在采集诊断中保持可见，现有计划限制继续生效。

保留原有快照健康状态词表。`LIVE` 表示快照在采集目标上的验证状态；当前展示完整性另行对照应有目标和交易日计算。现有指数范围表达目标数据是否就绪，采集诊断表达最近请求结果。两者都依据同一提交后的选择规则，不能互相推导出未经验证的就绪状态。

## ICDR05 一致的展示读取契约

建议新增一个只读接口：`GET /api/v1/market-indexes/overview`。在一次本地读取事务中组装四张指数卡片及市场成交额。不接受调用方指定日期、代码、分页或数据源选项。固定顺序为 `000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`；隐藏的 `399107.SZ` 继续仅用于市场成交额。

原因：现有总览摘要和单独读取的历史曲线可能看到不同修订。一个有界展示投影可以解决该问题，无需重定义现有 `snapshotHash`、历史签名游标、计划 DTO 或监控契约 `2`。不能向严格的现有 DTO 静默添加字段。新接口自带 `schemaVersion=1`，沿用本地 Origin/访问保护，返回 `Cache-Control: no-store`；它是展示资源，不作为执行操作的预检。

| 对象 | 拟议的精确字段／含义 |
|---|---|
| 外层 | `schemaVersion`、`observedAt`、`runtimeGeneration`、`sequence`、`marketSession`、`indexes`、`marketTurnover` |
| `marketSession` | `phase`、`calendarStatus`、`sessionDate`、`displayTradeDate`、`expectedBucketAt` |
| 每个指数 | `indexCode`、`displayName`、`board`、`dataStatus`、`data`、`latestAcquisition` |
| `data`（可为空） | `snapshotHash`、`observedAt`、`completedBucketAt`、`sourceKind`、`closePoints`、`priorClosePoints`、`sessionChangeRatio`、`highPoints`、`lowPoints`、`amount`、`bars` |
| `latestAcquisition`（可为空） | `decisionCutoff`、`observedAt`、`health`、`issues`、`nextRetryAt` |

时间和十进制字符串遵循现有规范；可空字段显式返回。`runtimeGeneration` 遵循当前运行时所有者的可空 UUID 契约。`sequence` 使用现有已提交事件序号，不新增事件流。即使全部无数据，也固定返回四个指数。`bars` 使用已有五分钟行情 DTO，单个展示日最多 48 根。响应上限为 512 KiB，必须检查边界，不能静默截断。某个指数无数据时返回对应空卡片，不导致其他健康指数读取失败。实际存储或完整性故障使用现有脱敏服务错误结构，不伪装为空数据成功响应。

`data` 内所有字段来自同一个不可变快照。行情限制在 `displayTradeDate`；`completedBucketAt` 等于最后一根的时间，`closePoints` 等于该根收盘点位。最高/最低取返回行情的极值；需要的返回行情成交额有任何缺失时，`amount` 为空。昨收取严格早于展示日的最近已认证官方日线收盘值；缺失时保留点位和曲线，但将 `priorClosePoints`、`sessionChangeRatio` 留空并标记待核验。计算使用后端 `Decimal`。保留数据原始观察时间，读取时间仅放在外层。

`dataStatus` 为 `CURRENT`、`INCOMPLETE`、`CACHED`、`EMPTY` 或 `UNVERIFIED`。`CURRENT` 要求包含截至 `expectedBucketAt` 的全部应有行情、展示日期匹配、来源及昨收已验证。`INCOMPLETE` 表示缺少末端或中间行情。`CACHED` 表示保留的数据缺乏当前交易时段或来源的有效性证明。`EMPTY` 表示无展示数据。`UNVERIFIED` 表达日历、来源或完整性的不确定性。任何展示状态都不代表交易操作许可。不插值补齐缺失行情。

`marketTurnover` 复用现有可空成交额 DTO 和精确公式。在同一读取事务中使用两个已批准基准的对齐有效快照；保留既有截止时间、前一交易日和成交额完整性检查。不能合计不同截止时间的数据，不能用深证成指替代深证A指。

保留现有总览、历史和个股 API，并同时修复其有效引用选择。已有历史签名遍历语义保持有效。前后端配套发布后，总览区域才切换到新接口；接口不受支持时提示版本更新，不能拼接旧摘要和新曲线。

## ICDR06 交易时段与界面行为

后端根据现有可信交易日历和上海时区时段规则计算 `phase=PREOPEN|OPEN|BREAK|CLOSED|UNKNOWN`。日历状态为 `KNOWN|UNKNOWN`。已知非交易日使用 `CLOSED`；日历缺失使用 `UNKNOWN`，不能仅凭星期或浏览器时间猜测已收市。交易日时段为：[09:30, 11:30) 和 [13:00, 15:00) 交易中，[11:30, 13:00) 午间休市，15:00 起收市，09:30 前未开市。该状态切换不排除既有 11:30 或 15:00 已完成行情。最终应有目标为 15:00，收市后也保持 15:00，不变成 16:00 或 17:00。全天完整要求 48 根合法五分钟行情，不包含 09:30 开盘快照。

交易日自 09:30 起，`displayTradeDate` 为当天，即使尚未有数据。开盘前及非交易日显示最近已认证交易日的数据，并明确标注日期，不能称为当日数据。`sessionDate` 是当前上海日期。日历未知时可展示最近存储日期的缓存数据；`expectedBucketAt` 为空，不得声称数据当前有效或完整。盘中沿用已有完成周期和 12 秒宽限规则；两个休市边界到达时明确最终目标，数据到达前保持不完整状态。首根行情完成前应有目标为空，卡片不得声称完整。展示此前已认证交易日时，目标为该日 15:00。

| 时段／数据 | 卡片主文案及行为 |
|---|---|
| `OPEN` + `CURRENT` | 实时；正常显示点位和曲线 |
| `OPEN` + `INCOMPLETE` | 数据待更新；保留点位、曲线和明确截止时间 |
| `BREAK` + `CURRENT` | 午间休市；保留上午曲线 |
| `BREAK` + `INCOMPLETE` | 午间休市 · 数据待补齐 |
| `CLOSED` + `CURRENT` | 已收市；完整点位和曲线，该交易日数据截止 15:00 |
| `CLOSED` + `INCOMPLETE` | 已收市 · 数据待补齐；保留已验证的部分数据 |
| `PREOPEN` | 未开市；标明展示的历史交易日 |
| `EMPTY` | 不生成点位；显示时段文案和暂无行情 |
| `CACHED` / `UNVERIFIED` | 显示原始日期、截止时间及已缓存／数据待核验；不能声称当前完整 |

后续采集失败以次要提示“最近更新失败，保留已取得行情”呈现，并保留系统诊断。不能把完整收市卡片替换为红色“阻断”。传输断开作为单独的缓存展示提示，不改变后端交易时段，也不证明数据有效。五分钟末点继续明确标注其数据性质，不能改称官方日线结算值。

`MarketIndexDataStrip.vue` 保留选择状态，首次挂载默认选中上证指数。`MarketIndexTrendCard.vue` 渲染完整的单个指数对象。`MarketIndexSparkline.vue` 继续只负责绘图，在缺少应有盘中行情处断开曲线；正常午休区间不属于数据缺口。专用 composable 管理 overview 读取、取消和整个响应的原子替换。不能更新顶部点位却保留另一个修订的曲线。刷新失败时保留整个旧响应并标记缓存。复用现有监控失效事件、序号变化和时段边界观察触发刷新，同一时刻仅一个请求并合并重复触发；不新增浏览器向数据源轮询。取消和代次保护丢弃旧响应。保留原生选择按钮、键盘导航、减少动态效果及 320/768/1024/1440 布局要求。

## ICDR07 时段最后一根行情补查

当前下一分钟发布延迟恢复依赖交易分钟。15:00 后不存在 15:01 交易分钟，因此延迟可能持续到 15:20。新增独立调度的最后一根恢复，不依赖后续交易分钟是否存在。同时应用于 11:30 和 15:00，避免在午休边界保留同类缺陷。

固定策略：符合末端缺失条件的快照，最多补查 3 次，时间为目标后 +72 秒、+132 秒、+252 秒；目标后 +5 分钟关闭窗口。首次补查与普通“下一分钟 +12 秒”对齐。指数采集继续共享，并受频率与准入控制。与普通延迟补查、临时失败恢复和盘后核对去重：每个指数及目标同时最多一个采集任务。权限、配额和完整性错误不能借此绕过原有限制。

在现有恢复仓储中以明确的恢复类型保存目标、原因、次数、下次到期时间和过期时间。普通临时失败的 30/60/120 秒策略单独保留。同一最终目标的所有补充物理请求共用最多 3 次的上限，即使故障原因变化也不能重置次数。控制器准入或冷却延期在请求实际开始前不消耗次数，但不能延长过期时间。目标数据完整、窗口到期、出现新目标、来源或运行代次被取代时停止。重启仅恢复兼容且未过期任务；时钟回退遵循既有运行时保护。不重放已完成的计划判断或提醒。

最终目标耗尽的 `attempts=3` 记录保留到目标后 +5 分钟，即使最初类型为 `TRANSIENT`，也不能被后续发布延迟重新开启预算。既有 pending DTO 只读取 `attempts<3`。恢复记录保存 `sourceIdentity`；来源不一致时不恢复。降级拒绝丢弃 `FINAL_BUCKET` 或 `attempts>2` 记录。

进程较晚恢复时，最多立即执行一个当前符合条件的逾期尝试，其余尝试不得早于该次完成后 60 秒且必须在窗口内，不能集中补发。窗口结束后保持明确的不完整展示，继续沿用 15:20/16:00/17:00 核对。本提案不停止官方日线刷新，不改变正常盘中频率。

## ICDR08 既有数据修复与发布

通过现有 Alembic 流程新增兼容结构，迁移版本为 `0025_index_close_display`。最近采集和恢复类型存储规模受现有支持的指数身份及待处理目标约束。本设计交付不包含对运行中用户数据库执行手工 SQL。

发布前通过正常排空流程停止所有者，并创建包含已提交 WAL 状态的一致 SQLite 备份。在批准的迁移／启动流程中执行幂等本地修复：针对受影响的当前展示日及精确引用键，检查保留的不可变快照，验证哈希、身份和来源；若成功 `LIVE` 引用被后续失败覆盖，则恢复同一键下最新成功采集的引用。最近失败尝试单独保留。不能删除失败快照或改写决策引用；不能跨请求集合、映射版本或交易日恢复。候选损坏时修复失败，不能静默当作当前数据。

本次故障应恢复 15:20 的快照，其截止为 15:00、点位为 3813.791，历史接口恢复 48 根行情。最近采集元数据依据已提交采集事件顺序及关联快照回填；关联不足时显式留为未知，不编造时间。脱敏诊断记录修复数量。重复执行不得再次修复或重复发事件。

后端选择规则和迁移先于新前端生效。恢复数据可见时发布正常失效事件，加载匹配的前端构建并验证实际读取。回退使用停机备份或兼容的旧读取程序；没有经过验证的降级流程时，不能让旧写入程序操作新恢复类型结构。验收必须覆盖重新打开及进程重启，不限于一次新页面加载。

## ICDR09 验收与回归矩阵

| ID | 场景 | 必须满足的结果 |
|---|---|---|
| A01 | 成功取得 15:00 数据，随后 16:00 临时失败 | 点位、涨跌幅和 48 根行情保留；显示收市；最近失败单独可见 |
| A02 | A01 后重启 | 重启前后有效哈希、数据及最近采集结果一致 |
| A03 | 旧目标成功，新目标失败 | 旧数据明确为不完整或缓存；不能满足新计划证据 |
| A04 | 同一目标的新有效修订，其数据源 revision 数值更小 | 接受新修订；点位与曲线原子更新 |
| A05 | 15:00 或 11:30 末端缺失 | 没有下一交易分钟也执行补查；仅请求滞后指数 |
| A06 | 重启、冷却、慢请求未结束、故障原因变化、过期 | 不重复、不集中补发；跨重启保持最多 3 次及 5 分钟窗口；不重放计划 |
| A07 | 已到 15:00 但只有 47 根，或存在中间缺口 | 已收市 · 数据待补齐；不生成虚假最终点位或完整成交额 |
| A08 | 非交易日、开盘前、日历未知、跨午夜 | 时段正确、展示日期明确；不误称当日数据或已收市 |
| A09 | 有效数据后发生权限撤销或身份／完整性错误 | 保留事实有正确标签；诊断及计划限制仍生效 |
| A10 | 浏览器刷新期间快照变化 | 整个一致响应保留或替换；丢弃旧响应；健康指数仍可用 |
| A11 | 历史错误引用及重复修复 | 从有效已存快照恢复完整曲线；不可变哈希和决策不变；修复幂等 |
| A12 | 空数据、昨收缺失、成交额缺失、传输断开 | 如实展示占位或部分事实；不编造涨跌幅、总额或实时状态 |
| A13 | 既有监控、签名历史、官方日线和成交额契约 | 无不兼容 DTO 修改、签名游标回归、权限升级或公式变化 |

实现前必须用确定性假时钟和假数据源重现已观察到的成功／失败顺序。现有仅验证内存的测试不充分，必须覆盖实际持久化事务、重新打开仓储、REST 响应和组件。浏览器测试同时核对点位与曲线末点，不能只检查标签文案。

## ICDR10 代码位置、命令与交付边界

预计职责：选择规则和采集元数据位于 `runtime/market_indexes.py`、`runtime/service.py`、`state/projections.py` 和 `state/models.py`；新增迁移位于 `state/migrations/versions/`；最后一根调度位于 `runtime/scheduler.py` 和 `runtime/production.py`；展示投影及交易时段组装位于 Web 读取服务层；overview 路由与 `web/routers/market_indexes.py` 相邻；前端使用只读客户端／类型、composable 和现有指数组件。采用 Python 4 空格缩进、带类型的小型纯选择函数、规范 `Decimal`，以及带类型 props 和 events 的 Vue Composition API。不要在 Vue 模板中实现数据选择规则。

在项目根目录使用现有虚拟环境运行。以下为回归命令；已执行结果及完整目录回归记录见配套验收报告：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_market_index_snapshots.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_market_index_history.py tests/integration/test_market_index_web.py tests/unit/test_monitor_runtime.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_status_projection.py tests/integration/test_runtime_status_official_close.py tests/integration/test_runtime_status_websocket.py tests/unit/test_market_turnover.py -q
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e -- dashboard.spec.ts
```

实现后将新 overview 契约、迁移和最后一根恢复的专项验收测试加入上述命令。后端发布还需运行完整离线测试；回归证明不需要调用真实数据源。实现时同步更新对应的中英文源规范与生成契约，包括明确的 overview API 范围扩展。不得削弱既有断言来容纳矛盾。

实施和验收仅覆盖 ICDR01 范围。任务记录为 `tasks/index-close-display-repair-plan.md` 及中文副本，不替换其他进行中的任务。验收证据、备份、迁移和实际服务结果见 [验收报告](../../verification/2026-10-09-index-close-display-repair.zh-CN.md)。
