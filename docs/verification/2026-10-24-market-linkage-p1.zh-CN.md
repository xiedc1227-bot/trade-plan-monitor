# 验证：market-linkage-p1

## MLV1-01 — 范围与授权

用户在 2026-10-24 批准 MLP1-D01–MLP1-D06 并指示分阶段实施。基线 `dbeff32`。本报告只记录已经执行的检查，不记录设想结果。[规格](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md) · [任务](../../tasks/market-linkage-p1.zh-CN.md) · [规范英文版](2026-10-24-market-linkage-p1.md)。

## MLV1-02 — 基线与边界清单

MLP1-T01：已核对实际领域／草稿／编解码／哈希／审核／运行／状态／API／回放边界，记录在双语[契约清单](../specifications/monitoring/CONTRACT-market-linkage-p1.zh-CN.md)。未访问用户数据库或外部数据商。

在 `trade-plan-monitor/` 已执行 V01：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

结果：**91 passed in 1.20s**。Python 启动器出现既有安装位置诊断，但测试正常完成，退出码为 0。此基线不代表 P1 功能验收。其余任务结果仅在实际执行后追加。

## MLV1-03 — 严格 Schema 7 契约（MLP1-T02）

RED：初始契约测试因缺少 Schema 7 模型／分发产生 9 失败／1 通过；新增不完整草稿及共用构造器检查在实现前另有两项预期失败。GREEN：52 项例外／联动／统一领域测试在 1.58s 通过；176 项旧计划／日线／有界编解码测试在 0.45s 通过。由于明确支持 7，未知版本样本改为 8，保留拒绝断言。针对性 Ruff 和空白检查通过。

首次扩大范围误用了不存在的 `test_daily_plan_domain.py`，没有运行测试，随后改为实际文件。默认临时目录初始化失败；明确使用工作区临时目录解决该问题。后续堆栈将剩余等待定位到 Windows `asyncio` 创建 socketpair，允许本机通信后离线测试通过。没有修改应用逻辑绕过环境限制。

已通过命令（临时路径按运行区分）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_unified_plan_domain.py -q --basetemp .test-tmp/p1-t02-accepted
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_bounded_validation_codec.py -q --basetemp .test-tmp/p1-t02-legacy-fixed
```

本项仅验收严格领域／草稿／编解码／哈希切片。来源审核、启用、运行、批准及执行集成仍为未勾选任务。

## MLV1-04 — 纯资格与数量（MLP1-T03 / MLP1-C01）

实现前加入独立路径／数量样本，缺少模块时按预期收集失败。数量切片通过 24 项测试。另两项测试发现 Q0 内不存在合法数量时仍产生 BROKEN 候选；补充数量可行性准入后，V01–V03 联合套件 **144 项在 1.33s 通过**，针对性 Ruff 通过。覆盖 P0 状态／强势／确认的相等边界和新例外边界。

已验证精确最低量替代、明显破坏数量不自动填写、合法数量可在半数 Q0 两侧、额度／未知／非法输入阻断，以及普通路径独立性。即使符合资格，纯策略始终返回零授权数量。MLP1-Q12 的持久过时／他次批准场景仍由授权集成负责，不将纯函数测试当作持久化验收。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

MLP1-C01 仅验收契约与算术。后续权限、运行、UI 和回放任务仍未完成。

## MLV1-05 — 来源绑定提取（MLP1-T04）

Schema 7 提取使用 `plan-extract-v10`，要求完整例外定义及逐路径来源许可，不能生成批准。字面绑定和解释绑定都检查否定许可。中英文定义保持等价边界。已有 v8/v9 记录继续可读。

RED：扩展格式暴露了实际的 50,000 字符输入上限回归，两项提示词预算测试失败。共享相同格式定义修复了回归，没有提高上限或删除校验约束。最终提取、审核、安全及提示词预算测试 **73 项通过，耗时 2.55s**；默认版本回归 **63 项通过，耗时 0.97s**。完整 `ruff check src tests` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/integration/test_market_exception_review.py tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py tests/unit/test_preparation_prompt_budget.py -q --basetemp .test-tmp/p1-t04-verified
```

MLP1-T04 验收通过。更新／准备、持久化授权及后续检查点仍待完成。

## MLV1-06 — 保留许可的更新（MLP1-T05）

RED：四项新测试暴露 Schema 7 精简准备格式和前序快照序列化缺失，一项授权注入测试已通过。精简准备、增量提示词及前序上下文增加明确的 Schema 7 类型分派。许可修改会改变审核标识，无关原文不能授权许可变化；计划复制拒绝单次授权。缺失许可仍不能生成可执行计划。一项测试最初预期抛出异常，而既有 `to_executable()` 约定为返回 None；已修正断言以验证该约定。

GREEN：**95 项测试通过，耗时 2.20s**，覆盖例外／联动审核、例外更新、增量物化、保留证据、提示词预算及既有准备更新。完整 Ruff 通过。MLP1-T05 验收通过；MLP1-C02 仍须完成持久化存储验收。

## MLV1-07 — 持久化状态（MLP1-T06 / MLP1-C02）

RED：新模型尚未实现时，存储测试收集失败。增加封闭候选／事件模型、分域哈希、终态转换校验、不可修改的事件写入及带修订号校验的投影。SQLite 现有种类约束需要增量迁移 `0026_market_exceptions`；迁移保持载荷字节、增加命令唯一性，并在存在例外证据时拒绝降级。测试仅使用临时数据库。

GREEN：来源／更新／新旧存储共 33 项通过，耗时 4.41s；增加持久化命令索引后，9 项存储回归通过，耗时 3.72s。最终 5 项新存储测试也通过。已验证提交前回滚、重新打开、终态复用、未知版本、哈希修改、事件不可变、旧字节保持及跨候选命令唯一性。完整 Ruff 通过。MLP1-C02 仅验收来源契约与存储，不声称生产批准或执行能力完成。

## MLV1-08 — 精确预览与明确决定（MLP1-T07）

RED：授权服务尚未实现时，测试收集失败。增加严格预览／决定命令、不可变预览、服务端上下文修订绑定、精确数量校验、命令重放及明确拒绝。该服务不写入库存。两条路径只冻结合法的已展示数量；明显破坏路径输入缺失／不合法时不会填默认值。

GREEN：**21 项授权／存储测试通过，耗时 3.49s**，完整 Ruff 通过。覆盖偏弱精确最低量、低于／高于半数 Q0 的合法明显破坏数量、空／零／不符单位／超过上限、库存／评估／证据变化、未知容量、风险阻断、相同重试及拒绝。生产权限采集和信号创建仍归 MLP1-T09；当前尚未开放 HTTP 接口。

## MLV1-09 — 终态与并发争用（MLP1-T08）

实现明确撤销、服务端过期／失效及不可变重试回执。首次双连接并发测试暴露 SQLite 从读取快照升级写入时的争用。服务现先取得写入锁再读取命令权限，将繁忙争用映射为明确冲突，其他数据库故障不会被当作成功。终态命令构造先于首次新增生命周期测试；并发修复遵循先失败后修复。

GREEN：**31 项测试通过，耗时 5.94s**，包括独立连接的批准对批准／拒绝、全新进程重新打开、撤销／重试、拒绝／过期／失效保持、禁止回填时间及提前过期。Ruff 通过。执行竞争仍归 MLP1-T10。生产更正及独立重置连续性将在 MLP1-T09 完成。

## MLV1-10 — 生产运行权限（MLP1-T09 / MLP1-C03）

增加 v2 决策／数量证据，保持 v1 校验器；共享独立机会准入，持久化候选，并在调用方同一事务内由明确批准创建信号。Schema 7 接入审核激活及生产指数适配器。运行缓存标识包含候选修订。待审核提醒没有数量；发送／读取／完成检查校验当前候选状态和所用证据。

GREEN：决策／授权／并发／新旧运行联合 45 项通过，耗时 13.23s。最终 10 项真实运行测试通过，耗时 6.94s；Ruff 通过。覆盖两条路径、批准不成交、同一时刻刷新、无变化重取、更正失效、复制／拒绝连续性、撤销后读取／发送阻断及完成证明失效。夹具修正使用实际指数请求字段与提醒仓储；未变化的提供方快照保持原接收时间。

扩大 API 运行发现 3 项预期契约投影失败：旧断言仅允许两个草稿分支和版本 [5,6]。明确留待 MLP1-T11/T12 验证准确增量变化及旧投影，不计为通过。MLP1-C03 仅验收逐次运行权限。模拟消费、公开命令、界面及回放尚未完成。

## MLV1-11 — 完整模拟消费（MLP1-T10）

RED：两条路径测试暴露批准未消费及撤销后仍可执行；独立连接的执行／撤销竞争随后暴露模拟入口先读后写的锁升级问题。模拟现先取得权限写入锁再读取，核验当前授权，并在同一事务消费候选、信号与库存。重新评估也保留已采集的联动指数来源。

GREEN：**39 项测试通过，耗时 19.10s**，包括 12 项例外模拟、授权争用及旧日线／联动链路。整理导入后 Ruff 通过。覆盖完整数量、容量不足／恢复不改数量、库存写入后故障注入及全部回滚、同键回执重放、不同键防重复、撤销对执行顺序及已消费历史不可撤回。没有真实账户或券商执行。

## MLV1-12 — 公共 API 与生成契约（MLP1-T11–MLP1-T12 / MLP1-C04）

RED：六项公共命令测试最初返回 404；完整 HTTP 重评随后发现测试日历不完整以及错误详情位置无效。均按生产契约修正。服务现提供预览、决策与撤销，具备同源、严格输入、不可变回执和幂等保护。首次组合 API／运行／模拟测试 32 项通过，耗时 20.19s。精确旧投影测试 8 项通过，耗时 7.73s；关闭 MLV1-10 记录的三项 API 断言差异，未放宽旧版比较。

已生成两套 API 契约。类型检查发现三个共用展示组件仍限定旧变体；独立三文件适配切片显式扩展联合类型。类型检查与生成 `--check` 通过。最终完整 V06–V08 **68 项通过，耗时 31.66s**，有一项既有 Starlette httpx 弃用警告。完整 Ruff 与 `git diff --check` 通过。本阶段验收 MLP1-C04，不代表界面或回放完成。

| 产物 | SHA-256 |
| --- | --- |
| `openapi.json` | `bcf1c2591cb94b704d15d36ccfa681e540851c938e002bc5bddff9fb0dc3212f` |
| `openapi.runtime-status.json` | `e4115049f8ea95a90cfbe54383ab5a924cd5cc0cc274d7d151750657aef286a2` |
| `web/src/api/generated.ts` | `8d471ec572961e771f7d88cc859833c854bee25ce2def932b1783340fbc6826a` |
| `web/src/api/generated-runtime-status.ts` | `d7e2d8844e64be6347db5a2c248120e94ff8c351578233c2cf7b5140fc9b0107` |

## MLV1-13 — 界面切片清单（MLP1-T13–MLP1-T15；待完成）

组件职责图：`usePlanWorkspace` 管理编辑状态与服务端定义的结构；`PlanExceptionPermissions` 只展示计划级路径规则；`PlanExceptionApproval` 通过例外 composable 管理单个候选交互；`PlanSimulationPanel` 管理刷新和既有独立模拟操作。props 传递服务端证据，事件请求刷新。Vue 中的计算不授予数量或权限。

顺序切片：T13a 测试、`conditionPlans.ts`、`usePlanWorkspace.ts`、`planSchema.ts`；T13b 权限组件、既有审核工作区接入和测试。T14a 类型化例外传输／响应校验、composable 和单元测试；T14b 候选组件、模拟面板接入和测试。T15 增加隔离服务端夹具与真实浏览器测试。每片最多五个实现／测试文件；本清单先于编辑记录。

## MLV1-14 — 计划许可审核与逐次界面（MLP1-T13–MLP1-T14）

两个新增组件测试套件首先因实现缺失失败。增加显式 Schema 7 编辑分派、服务端策略定义与独立许可标签，再加入只读许可摘要。编辑许可会清除旧审核／启用绑定。增加响应校验和逐次 composable／组件，提供初始为空的破位数量、固定偏弱最小量、精确预览、理由、独立拒绝／撤销、终态展示及不确定重试时稳定命令身份。既有模拟操作保持独立。

首次交互测试发现 Vue 数字输入自动转换；接收字符串／数字并归一化空值后修复，未增加默认数量。最终专项 **34 项通过，耗时 1.27s**。类型检查和生产构建在最后补充编辑失效测试前通过，将在 C05 重跑。一次受限运行因 Windows 临时缓存重命名权限失败；相同离线测试在已授权本地环境通过。真实浏览器 T15 与回放仍未完成。

## MLV1-15 — 浏览器驱动修复与回放切片清单（进行中）

真实浏览器发现三项独立复现的遗漏：通用传输层拒绝公开的 `exceptionPolicyDefinitions.authorization` 说明；提取读取器遗漏 `plan-extract-v10`；完整例外原文因重复空的输出分类占位字段而超过既有 50,000 字符提示词限额。仅按精确端点与父路径放行该公开说明（16 项传输测试通过，包含凭据拒绝反例）；显式 v10 分派通过 10 项读取测试；复用精确压缩片段证据后，46 项提取／安全／审核测试通过，耗时 2.12s。保留原文、片段 ID／位置／摘录与全部校验约束，未删除输入限额或安全断言。

浏览器检查另发现窄屏网格固有宽度溢出以及批准后仍提示重新预览。隔离 WEAK_MINIMUM 完整流程现已通过（10.9s），包括明确原文审核、批准不改变仓位、重新打开保存版本、四种视口宽度及独立整笔消耗。最初恢复测试错误刷新未保存的 `/plans` 路由，现改为打开实际保存版本地址。完整 T15／C05 仍待九场景运行与前端回归完成。

T16–T18 顺序清单：(a) 严格冻结授权封装／事件流与因果测试；(b) 单次研究与循环／版本计划输入的显式 Schema 7／run-v8 准入；(c) 冻结数据／指数／准备适配；(d) 私有会话共享事件应用与原绑定检查；(e) 单次回放时间排序和类型化结果；(f) 监控循环时间排序与显式例外执行脚本；(g) 两入口变异／一致性测试与生成契约更新。每个源码／测试切片最多五个文件；技术版本增补在依赖实现前同步双语文档。冻结事件不查询当前本地批准库，也不直接改变仓位。

## MLV1-16 — 真实浏览器流程检查点（MLP1-T15 / MLP1-C05）

最终 V10：**9 条真实浏览器场景通过，耗时 1.5m**，使用全新本地 SQLite 夹具和真实 API（两条例外各覆盖成交／撤销／拒绝／证据更正，加旧版联动及独立提醒流程）。验证键盘批准、破位数量初始为空、偏弱最小量只读、刷新清除过期预览、批准／撤销不改变仓位、重开保存版本、冻结整笔消耗、终态持久化及无外部请求。既有审计夹具未发现控制台错误、警告或失败请求。四种视口（320/768/1024/1440）均通过横向适配检查。已目视检查两条路径的批准截图：数量、依据、到期、独立模拟与撤销控件清晰；已修正原始调试阻断文字和批准后重新预览提示。

完整前端回归：**88 个文件／1253 项测试通过，耗时 10.18s**。类型检查、生产构建与完整 Ruff 通过。公开定义、v10 读取、提示词预算和布局修复已关闭此前记录的浏览器失败。MLP1-C05 验收通过；冻结回放及最终全项目验收尚未完成。

## MLV1-17 — 冻结回放接入与修复切片（进行中）

T16–T18 按输入与排程准入、共享私有命令转换、单次研究执行器、连续监测请求与报告、实际复制数据工作进程、变异测试依次实施。真实复制数据测试发现：开盘前价格基准暂缺会错误终结已批准机会。三个文件的运行链与测试修复使必要来源暂缺时无法执行，但保留原授权；已提供的修正来源仍会使授权失效。运行链加两类真实工作进程：**14 项通过，36.39 秒**。两条入口的负向场景：**36 项通过，34.70 秒**；未来事件加入前的连续监测前缀比较：**2 项通过，3.91 秒**。这些是中间结果，尚不表示 C06 验收。

下一组接口切片：(a) 配套报告头与原生读取器；(b) 准备记录传输读取器与针对性测试；(c) 有边界的连续监测结果及事件读取器、现有汇总中的来源展示；(d) 生成 API/类型产物并核对旧投影。前端失败测试已复现 Schema 6/7 准备记录与结果被拒，以及例外来源未展示的问题（实现前 3 项失败）。保留现有载荷与深度限制，拒绝未知的执行版本组合。研究结果不得新增批准操作或推断授权。


## MLV1-18 — 冻结回放检查点（MLP1-T16–MLP1-T18 / MLP1-C06）

最终联合运行：**88 项通过、1 条既有 Starlette 弃用警告，184.99 秒**。命令：`python -m pytest tests/integration/test_market_exception_replay.py tests/integration/test_market_exception_replay_mutations.py tests/integration/test_market_exception_frozen_workers.py tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_market_linkage_api.py tests/integration/test_market_exception_runtime.py -q --tb=short --basetemp .test-tmp/p1-c06-53`，使用 `.venv/Scripts/python.exe`。两类真实冻结工作进程均验证两条路径、明确整笔执行、无隐式成交、复制输入后的发布及库存隔离。未来批准不改变较早决策；拒绝、撤销、迟到、证据修正、数量不符均被阻断。原计划范围不符、重复事件和同一时点顺序歧义均被拒绝。

后续切片：(a) 持久化结果身份／来源、原始操作与审计绑定及工作进程测试；(b) `research_signal_projection.py`、报告／执行器及工作进程测试，在既有 32 KiB 单条上限内保留完整证据；(c) 既有运行接点／服务／测试中的日历、原始回执和候选重置风险校验；(d) 单次研究输入／结果传输、共享有界回放读取器及结果展示；(e) 明确循环程序传输及针对性前端测试。持久化测试先复现重复证据导致记录超限；引用现在解析到同一决策内完整证据，替换会被拒绝。日历修正与重新封装批准回执的测试在修复前复现 **4 项失败**；风险阻断的候选重置现在复用既有信号风险门槛。

最初扩展 V11 运行有 **68 项通过／2 项失败**，失败位于旧 API 投影比较。仅排除获准新增的输入／报告／引用联合类型及生成的联合类型标题；未变路径和旧组件仍与 `c7378a4` 精确比较。两套契约现在均通过。两套生成检查、完整 Ruff、前端类型检查通过。针对性前端：**4 个文件／188 项通过，1.41 秒**，覆盖明确程序原样提交、Schema 6/7 准备／结果分派和两种来源标签。最初指定的两个前端测试路径不存在；验收命令实际使用 `UnifiedReplay.spec.ts`、`marketExceptionReplay.spec.ts`、`PlanPreparation.spec.ts`、`backtestsApi.spec.ts`。

对抗审查曾临时关闭冻结封装哈希比较。两条损坏测试均按预期失败（**2 项失败，3.04 秒**）；`finally` 已恢复原始文件字节，没有遗留放宽的校验。已核对中英文契约、规格、任务和报告的章节 ID、代码标识、数量、路径与验收含义。C06 验收通过；T19–T21 尚待完成。未调用真实数据商、发送外部通知、迁移用户数据库、推送或部署。
