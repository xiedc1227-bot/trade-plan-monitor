# C1 股票分钟权限 owner 契约

> 规范英文版为 `2026-09-27-c1-stock-minute-permission-owner-contract.md`；本文为语义等价的中文审阅版。

## SMWO-01 状态与范围

- 日期：2026-09-27。
- 状态：**Preparation design reviewed/approved for bounded implementation; execution not approved pending boundary code/owner execution validation**，即准备设计已评审并批准有界实现，执行片尚未批准，等待边界代码及 owner 执行验证。
- 主协调转述：独立 Sol 最终核验通过双语 parity 和全部必需钉点，无新 P1/P2。纯准备片（候选、身份/日历准备、排序/游标结构、零预约、零 SDK 调用）已批准有界实现。因 `production.py` 当前由 SDK 边界 writer 占用，尚未启动。SMWO-11 既有 OPEN P2 正由另一切片修复，尚未通过验证。owner 准备/执行仍未实现，owner 测试尚未运行。
- 基线：已提交 `95feccb` 的纯 provider 证明契约与实现，见[provider 契约](2026-09-27-c1-stock-minute-permission-proof-contract.zh-CN.md)。该已完成切片与本次未实现的 owner 接线分开。
- 提议范围：`CURRENT_DAY_MINUTES`、`REALTIME_MINUTES` 的候选选择、准备及内部 owner 入口。准备与物理执行分为两个薄步。
- 自动 scheduler 接入、RUNNING/DEGRADED 双时钟 dispatcher、状态 API 变更、启动退避变更、市场 deadline cursor 变更及完整 C1 验收均不在本片。
- 设计时参考的 DAILY_BARS 接线继续仅供参考原则，不能替代 owner 验证。本次文档变更不修改 production/provider/controller 代码、其他文档或数据库 schema。仅这两份契约获准本地文档提交。
- 后续实现证据仅使用 temporary SQLite、fake SDK/transport 和可控时钟。不包括真实服务请求、用户数据库访问、发送、推送或部署。

## SMWO-02 实际消费者与原身份

`RuntimeDeadlineCoordinator.run_deadline()` 会为 legacy 计划和 `ExplicitTradePlan` 获取股票分钟数据；显式规则消费由此形成的完整五分钟数据。启动恢复也使用今天有效的 active symbols。因此两类计划均可产生 `CURRENT_DAY_MINUTES` 和 `REALTIME_MINUTES` 需求，不能复用 DAILY_BARS 的 legacy-only 集合。

消费者必须是完整可执行、当前持久激活、满足 `activation_is_eligible_on(..., today)` 且对应运行服务已经组合的计划。未来、过期、停用、草稿以及仅存在历史 pending 工作的计划，不产生今日分钟需求。缺库存、风险输入或其他业务依赖，不自动否定分钟消费者资格；业务 READY 不是权限修复前提。也不要求已经持久化分钟缺口或当天分钟行，否则启动阻断可能无法恢复。

在一份 owned 准备快照中核对 `ActivePlan`、`PlanActivationState`、`PlanVersion`。沿用最多十个 ACTIVE 计划和有界 payload 读取。必须同时满足：

- `ActivePlan.plan_version_id == PlanActivationState.plan_version_id == PlanVersion.id`：两个当前指针指向同一个版本行。
- `ActivePlan.symbol == PlanActivationState.symbol == PlanVersion.symbol == decoded_plan.symbol`：三个持久 symbol 与解码计划完全一致。
- `ActivePlan.revision == PlanActivationState.revision > 0`。
- `ActivePlan.activated_at == PlanActivationState.changed_at`：两个相等的时间戳为 canonical Shanghai 时间，且不晚于捕获时刻。
- `PlanVersion.status == ACTIVE`；其 `plan_id`、`version`、`plan_hash` 和 `payload_json` 与完整 decoded canonical plan 一致，包括重新计算的 canonical hash。

至少冻结：

```text
symbol
plan_version_id
plan_hash
family
activation_revision
activated_at
request_date
```

`plan_hash` 已绑定执行版本、公式版本和激活策略。响应重复上述检查，且只能匹配原始身份。同股票换版、停用后重新激活或 activation ABA，不能借用其他有效计划清除阻塞。这些检查足以证明 permission-only 当前身份，但不证明完整历史 activation 审计合法性。不新增历史 activation audit 或 legacy 历史收盘扫描。

## SMWO-03 内部签名与两个薄步

提议的内部入口共用一个实现：

```python
async def _maybe_recheck_current_day_minutes_permission(
    self,
) -> PermissionMaintenanceResult: ...

async def _maybe_recheck_realtime_minutes_permission(
    self,
) -> PermissionMaintenanceResult: ...

def _prepare_stock_minute_permission_locked(
    self, operation: TushareOperation,
) -> _StockMinutePermissionPreparation: ...
```

准备返回不可变的 `PREPARED / UNKNOWN / SKIPPED` 结果，携带原 candidate、消费者身份、捕获时间、STOCK 语义模式/revision、标签、provider、session factory 及日历 epoch/event。

1. **候选/准备薄步：**候选、身份/日历准备、八作用域排序及游标结构，包含两个独立 symbol 游标；零预约、零 SDK 调用、零 provider 改动。独立最终核验及主协调批准已完成。实现等待 SDK 边界 writer 释放 `production.py` 并由主协调安排；本次文档工作不开始编码。
2. **执行薄步：**先完成独立切片的最小 wrapper/provider 适配及其独立验证，再在连接 provider proof 和 controller 时执行 `SMW-04` 及 `SMW-06` 至 `SMW-14` 的 RED→GREEN。最终验证通过后仅清对应权限阻塞。此片仍未获批准，等待边界代码和 owner 执行验证。

准备片不修改 provider 文件。执行所需的最小 wrapper/provider 适配是 SMWO-11 下的独立工作；准备片边界不排除该适配，本契约不批准其结果。两个薄步均不修改 controller、自动调度、启动退避、状态 API 或市场 deadline cursor。

## SMWO-04 请求窗口与日历

沿用此前提议的保守维护窗口。仅可在以下上海时间区间开始请求：

```text
[09:31:12, 11:30:00)
[13:00:00, 15:00:00)
```

`09:31:12` 是首根一分钟结束后经过既有 12 秒 grace 的门槛。`13:00:00` 时，当日 session 结构中已存在完成的上午分钟；不添加未经批准的 `13:01:12` 门槛。实际响应仍须包含 A 类证明行。

请求日要求唯一、精确、持久化的 SSE 工作日开市事实，沿用既有实时主日历和 SSE epoch 范围。仅凭星期几不能证明开市。不能将其描述为其他交易所的独立认证。

- 缺日历、closed、无需求或无授权时，零预约、零 SDK 调用。实际维护检查记录固定 30 秒本地复查。
- 已知首根分钟门槛或午后开盘时刻时，记录对应最早检查时间。getter 不滑动已记录期限。
- 午夜重新建立今日身份和锚点。
- 午休或 `15:00:00` 及以后不启动分钟探针。合法启动的请求，其响应不能仅因跨越这些 session 边界而被拒绝。
- 响应验证不再要求未来 31.25 秒容量窗口。

失败写入留下的 revoked 日历 token，仅能在新的 owner 持久读取后替换，且须同时比较为该读取捕获的 epoch 和 Event identity 与当前值一致。只安装新 Event，绝不对旧 Event 调用 `clear()`。旧调用保留原 token，不能取得新 token 后续命。

## SMWO-05 八作用域与股票公平性

在现有六项后追加 `CURRENT_DAY_MINUTES` 和 `REALTIME_MINUTES`，保留原有相对顺序：

```text
TRADING_CALENDAR
INDEX_HISTORICAL_MINUTES
INDEX_REALTIME_MINUTES
DAILY_LIMITS
DAILY_BARS
INDEX_DAILY
CURRENT_DAY_MINUTES
REALTIME_MINUTES
```

候选 selector 的作用域集合和廉价 next-due getter 的作用域集合必须同时更新为这八项。保留原六项顺序及 DAILY_BARS O/F 状态；仅更新一个集合不够。

```text
effective_due = max(raw_due, local_defer, shared_429)
selection = raw_due + round-robin tie among currently runnable candidates
```

每个分钟作用域各持有一个独立 symbol 游标。按合格 symbol 升序取严格后继，末尾回绕。候选消失或集合暂时为空时保留游标；新增或重新合格的股票可以再次进入。

只有成功持久化 300 秒预约后的 `on_reserved` 才推进全局作用域位置和本作用域 symbol 游标，各一次。保存失败、peek、无候选和合并等待者均不推进。预约后取消、排队否决、无正向证明或超时，保留这次推进。物理开始时延长预约 floor 及成功清锁，不再次调用 callback。

持有共享维护锁，预计算一次不可变状态替换，并保留 DAILY_BARS O/F 状态。对稳定的合格集合，每个股票在本作用域相应数量的预约机会内获得机会。这是条件性公平，不是五分钟恢复 SLA。游标仍为进程内状态。

本片可测试八作用域选择契约，但不能证明现有自动入口已使用公平的统一 dispatcher。统一 dispatch、RUNNING/DEGRADED 双时钟和无候选唤醒仍属后续工作。

## SMWO-06 准入、来源授权与取消

在入口首次 await 前捕获 `owner_task = asyncio.current_task()`，并创建每次调用独立的 `threading.Event`。持有共享维护锁时重新准备恰好一次，不使用外部保留的旧准备。

```text
latest_start = captured_at + 15s
market_guard = 31.25s
```

在四处检查：预约前、queue admission、worker 入口、紧邻 SDK 调用。各处均检查同日、时钟未回退、冻结的最晚开始时间、合法请求窗口、冻结市场窗口、配置、语义、provider/source 身份、generation、stop、日历 epoch/event 和取消 Event。worker 不访问 Task 对象或数据库。

这些是提议要求，不是当前 production wrapper 已成立的属性。最后物理开始边界及 S 的获取位置仍为 SMWO-11 中的 OPEN 项。

使用既有 controller，每次最多一次准确 endpoint 的 SDK 调用，仅一个 symbol，固定 `freq="1MIN"`。两个 endpoint 保持独立权限阻塞/预约，共享 429 cooldown、单物理 worker 和 1.25 秒 pacing。使用 `RequestPriority.RECOVERY`，市场工作继续优先。保留原 `RequestNotStartedError` sentinel。预约前撤销不创建预约；预约后撤销保留持久预约。

STOCK 语义模式使用既有兼容性检查，不额外套用旧认证的到期门槛。legacy certification 模式保留既有有效性规则。缺失 STOCK binding 不回退到历史分钟认证。

发生 `CancelledError` 时先设置本次 Event 再抛出；`finally` 也永久设置 Event。响应读取前及返回 true 前，owner validator 检查捕获的 `owner_task.cancelling() == 0`，而不是 controller 的共享任务。即使外层 catch 尚未运行，已请求取消也必须阻止清锁。

不保证 Event 设置前 SDK 绝无启动。controller 保留槽位并排空已经启动的物理工作；不为等待排空继续持有维护锁。

## SMWO-07 冻结证明与一份新响应快照

既有 controller 的 `validate_after` 不接收结果参数。使用本次调用独立的结果槽传递不可变 `MinutePermissionEvidence`，并独立记录实际回调返回的 S，不能使用共享 pipeline 状态。owner 必须将 `evidence.started_at` 与准确记录的 S 比较，不能只检查是否位于允许范围内。空槽、错误结果类型或身份不符均不能成功。迟到 worker 只能写自己已废弃调用的槽，不能填入后续调用的槽或恢复清锁授权。

核对原 operation、symbol、request date、已认证标签及本次 `physical_start` 返回的准确 S：

```text
captured_at <= S <= latest_start
0 <= R - S <= 15s
response_validation_time >= R
```

保持 provider 在冻结 S/R 下的 A/B/C 分类；推进验证时钟不能重分类。至少要求一条 A，并保留 provider 契约中日期集合和计数的类型/上限。

响应后使用捕获的 factory，打开恰好一份新的 owned explicit-BEGIN 读取快照：

1. 重新验证原消费者身份及今日资格，不改选其他股票。
2. 核对请求日精确的持久 SSE 开市行。
3. 核对每个 A/B/C `source_dates` 条目的精确持久 SSE 开市行，包括仅由 B 行表示的日期。
4. 在快照前后复核 authority、epoch/event、取消和时间围栏。

`rt_min` 最多有 1,000 个来源日期。请求日不一定在该集合中，因此 **1,001 个不同日期事实**是来源日期与请求日并集的上限，不是增加来源日期配额。使用有界精确集合查询，可分块但必须位于同一显式事务。不能复用另开 session 的 helper 或 366 日范围 helper。不得展开 min/max 范围，不得添加五日或 366 日限制，不得追加 `trade_cal` 网络请求。

不能调用另开 UnitOfWork 的日历 helper。缺失 factory 可以延后；已提供借用、预使用或错误绑定的 Session，则按 `require_owned_recovery_session` 视为配置错误，应暴露该错误，且不关闭或回滚调用方状态。SQL、保存和本地编程错误继续传播。

factory 必须使用具有 explicit-BEGIN 事务 hook 的应用配置 engine。`require_owned_recovery_session` 检查所有权与绑定；其本身不能证明任意自定义 engine 具有 explicit-BEGIN 语义。

配置/语义撤销使用既有单调 revoked 状态：已观察到变化后再恢复原值，不能复活旧请求。支持的日历写入通过 epoch 撤销覆盖相同值重写及 ABA。这不声称能检测绕过这些路径、且未被观察到的外部瞬时修改。

快照验证与 controller 随后的权限 reset 不是同一个原子数据库事务。证明仅建立 endpoint 可读性，不授予业务执行权。

## SMWO-08 结果与副作用

- 合法证明仅清自身 scope；成功时仅移除自身 local defer。
- `NO_POSITIVE_PROOF` 保留既有 `INVALID_RESPONSE` 失败路径、阻塞和预约。不能正常返回空成功，也不能伪造新的 HTTP 403。
- 已知 permission、429、transient、timeout 和 invalid-response 错误返回 `FAILED`。
- `RequestNotStartedError` 映射为 `DEFERRED`：适用时使用既有 market blocker 让行期限，否则固定本地复查。
- `ERROR/CLOSED/QUEUE_FULL`、SQL、checkpoint、callback 错误及取消继续传播。不能吞成普通失败，也不在这里关闭 controller。
- 15 秒是证据区间及既有 controller 边界，不是 SDK 被强制中断的证明。迟到成功不能再次清锁。
- 除 controller 恢复检查点外，不写分钟、日线、cache、health/READY、评估、风险、通知或 pending 状态。

## SMWO-09 必需 RED 矩阵

| ID | 必需边界 |
| --- | --- |
| SMW-01 | 今日 legacy、explicit、混合计划可成为实际消费者；未来、过期、停用、草稿和仅历史 pending 情况不产生需求。 |
| SMW-02 | SMWO-02 中准确的三表指针/symbol/revision/时间戳及完整 canonical plan 一致性；换版、同哈希重新激活及 ABA 拒绝原响应；不扫描历史 audit。 |
| SMW-03 | 准确 `09:31:12`、提前一微秒、`11:30`、`13:00`、`15:00`；closed、unknown、伪周末开市事实；跨日重新准备。 |
| SMW-04 | 每个 endpoint 准确单次调用且仅清自身阻塞；普通分钟读取及其他权限状态不受影响。 |
| SMW-05 | 八作用域 selector/getter 集合一致、原六项顺序、raw-due/tie、两个独立 symbol 后继、删除/新增/空集合；重复 peek 不推进。 |
| SMW-06 | 保存失败零推进；预约后否决/失败一次推进；物理开始延长 floor 不重复 callback；O/F 状态保留。 |
| SMW-07 | 四处准入围栏、固定最晚开始时间和不滑动窗口；31.25 秒等号与排队等待后撤销。 |
| SMW-08 | 已认证 source/mode/revision、provider、factory、配置/generation/stop 变化；日历重建比较 epoch 和 Event identity，只安装新 Event、不 clear 旧 Event，不使旧调用续命；无历史认证兜底。 |
| SMW-09 | 真实 provider 配合 fake SDK：A+B/C 成功；B/C-only、typed empty、坏行及原 sentinel 传播。 |
| SMW-10 | 每个 A/B/C 日期精确核验，未知 B-only 日期拒绝；1,000 个稀疏来源日期与请求日并集最多 1,001 日；分块保持同一显式事务，不使用另开 session 或 366 日 helper。 |
| SMW-11 | 响应恰好一份使用应用配置 engine 的新 explicit-BEGIN 快照；所有权预检不能单独认证任意自定义 engine；并发身份/日历变化；worker 不访问 SQL 或 Task。 |
| SMW-12 | 与本次调用回调 S 准确相等，不仅检查范围；合法开始的请求可跨午休/收盘验证；响应时不重查未来容量；R 后回拨拒绝。 |
| SMW-13 | 排队取消、SDK 中取消、外层 catch 前已请求取消；迟到 worker 仅写自己的已废弃槽；迟到成功不清锁，槽位排空前不启动第二个物理请求。 |
| SMW-14 | shared429、持久 300 秒、1.25 秒 pacing、重开 temporary SQLite 后恢复状态；save/callback/SQL 故障传播。 |
| SMW-15 | getter 不滑动固定本地复查；无需求/日历零预约；零业务 SQL 写、READY、发送或自动调度调用。 |

## SMWO-10 剩余门槛与文档状态

内部方案不需要新增业务参数。扩大午休/盘后请求窗口、证明真实 `rt_min` 提供 A 类证明行，以及完整自动恢复验收仍在本片之外。fake 混合行证据不能关闭 C1。

准备设计已评审并批准有界实现。独立最终核验通过 parity 和全部明确化内容，无新 P1/P2。执行片仍为 PROPOSED 且未获批准；SMWO-11 既有 OPEN P2 正由另一切片修复，尚未通过验证。准备片等待 `production.py` 可用并由主协调安排。owner 准备和执行仍未实现，其 RED 矩阵尚未运行。执行片必须通过边界代码验证及独立评审，再进行 `SMW-04` 及 `SMW-06` 至 `SMW-14` 的 RED→GREEN。文档对齐/格式检查不是实现测试。

## SMWO-11 OPEN：生产 wrapper 物理开始边界

独立评审已离线复现该边界；另一切片正在修复，但尚未通过验证，发现仍为 OPEN。已复现路径中，纯 provider 在 `endpoint(...)` 前调用 `physical_start`，但 production 中的 endpoint 是 `_CertifiedTushareClient.request`。wrapper 随后才执行 `_current()` 证书/配置文件检查，再调用内层 SDK：

```text
provider physical_start -> S
endpoint(...) -> _CertifiedTushareClient.request
_current() certificate/configuration checks
inner SDK invocation
SDK return -> R
```

wrapper 检查可能使时钟越过 `captured_at + 15s`，也可能在中间间隔发生授权撤销。S 仍记录此前回调的时刻。因此，即使 `S <= latest_start` 和 `R - S <= 15s` 同时成立，也不能建立所要求的物理 SDK 最晚开始边界。当前 seam 尚未建立这项最后准入属性。

主协调转述的独立 reviewer 离线 inline 复现为：`10:00:00` 捕获，最晚开始为 `10:00:15`，`physical_start` 在 `10:00:14`；随后认证检查耗时 2 秒，内层 fake SDK 到 `10:00:16` 才开始，但 proof 仍可通过。这是主协调报告的 reviewer 证据，不是本文档作者执行的测试。它证明迟开始反例，不代表修复已经实现、已新增 RED 测试或 owner RED 矩阵已经完成。

解决方案要求把每次调用独立的 guard 和 S 获取放到 wrapper 检查之后、真实 SDK 入口边界。最小 wrapper/provider 协议适配由独立切片处理；边界代码尚未通过验证，本契约不予批准。不得临时替换共享 callback，也不得把私有 hook 参数透传给真实 SDK。

该发现可能同样影响既有 daily/index admission seam；分钟复现尚未分别证明对它们的影响。该边界仍为 OPEN：另一切片正在修复不等于修复已通过验证。本轮仅文档工作不修改已有 source/tests；主协调另行报告了 HEAD `453cc0c` 的完整 offline 运行。独立边界工作及评审通过后，本提案才能声称最后物理开始保证成立或批准 owner 执行。
