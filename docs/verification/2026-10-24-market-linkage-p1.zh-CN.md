# 验证：market-linkage-p1

状态：PASS — MLP1-T01–MLP1-T21、MLP1-C01–MLP1-C07、MLP1-A01–MLP1-A14 已完成。MLV1-23 为最终结果；此前条目保留按时间记录的失败和阶段检查点，不代表尚未完成的工作。

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


## MLV1-19 — 全项目回归（MLP1-T19 / MLP1-T20，进行中）

默认 V12 收集遇到既有同名文件 `tests/unit/test_backtest_service_contract.py` / `tests/integration/test_backtest_service_contract.py`，未进入测试执行。因此将所有非联网目录分进程执行，除 `-m "not live"` 外不作排除：`tests/unit`、`tests/integration`、`tests/contract tests/replay`。完整集成进程仍在运行，包括固定的10证券／252交易日容量与跟踪内存预算；目前不宣称完整后端通过。

单元回归首次为 **3653 项通过／6 项失败**，修正夹具断言过程中第二次为 **3657 项通过／2 项失败**。四个文件的修复将默认／当前请求的准确版本期望更新为获批的 `plan-extract-v10`，仍检查旧配置标签分派到当前版本，并逐条核对紧凑来源的准确 ID／起止位置／摘录及空输出占位语义。不改变应用行为、限制或授权负向断言。最终单元运行：**3659 项通过、2 条警告，46.26 秒**。契约／重放目录：**13 项通过、4 项联网测试未选中，8.44 秒**。完整集成运行还加载了两条旧提取版本期望；已更新与生产序列化完全匹配的夹具和适配器断言，两个完整相关模块共 **52 项通过，2.63 秒**。

首次完整前端测试与生产构建重叠，已安装分发目录不可变测试检测到并发写入（**1258 项通过／1 项失败**）。这是执行编排错误，没有因此更改断言。独立重跑：**89 个文件／1259 项通过，9.13 秒**；生产构建与类型检查通过。V10 重跑：**9 条真实浏览器场景通过，1.6m**；已检查并保留最终批准状态截图（[WEAK_MINIMUM](assets/2026-10-24-market-linkage-p1-weak.png)、[BROKEN_STRONG](assets/2026-10-24-market-linkage-p1-broken.png)）。数量、证据、原到期时间及独立模拟／撤销操作清晰，四种视口检查通过。本地 Windows 服务在连接清理时记录了一条 `ConnectionResetError`；浏览器控制台／请求断言及全部场景通过，未放宽生产异常处理来隐藏它。

原始证据：[初次收集](assets/2026-10-24-market-linkage-p1-full.log)、[单元验收](assets/2026-10-24-market-linkage-p1-unit-accepted.log)、[集成进度](assets/2026-10-24-market-linkage-p1-integration.log)、[契约／重放](assets/2026-10-24-market-linkage-p1-other.log)、[前端](assets/2026-10-24-market-linkage-p1-web-final.log)、[构建](assets/2026-10-24-market-linkage-p1-build.log)、[浏览器](assets/2026-10-24-market-linkage-p1-browser-final.log)。等待完整后端验收期间已准备 T21a/b 文档切片；T19–T21 及 C07 尚未验收。

## MLV1-20 — 最终回归修复

完整现行计划／来源审核 API 模块发现另六条过时的当前请求版本断言。保留明确的历史配置夹具；当前响应／分派预期改为 `plan-extract-v10`。两个完整模块 **13 项通过，5.82 秒**（[红灯](assets/2026-10-24-market-linkage-p1-api-fixtures-red.log)、[绿灯](assets/2026-10-24-market-linkage-p1-api-fixtures-final.log)）。已启动的集成进程此前载入旧夹具，因此最终失败列表仍须与这些完整模块复跑结果逐一核对。

增加两条阻断原因文案检查后，前端 **1261 项**、类型检查及构建通过。随后浏览器出现 **8 项通过／1 项超时**（[日志](assets/2026-10-24-market-linkage-p1-browser-accepted.log)）：初始异步仓位刷新替换了内容相同的绑定对象，清空加载期间已填写的数量。修复前的确定性表单测试复现已填 `100` 丢失。`PlanOperationForm` 现仅在结构定义身份与全部绑定字段均未变化时保留输入；权限绑定变化仍清空并阻止提交。未放宽超时或验收断言。该两文件修复后的完整前端：**89 个文件／1262 项通过，9.22 秒**（[日志](assets/2026-10-24-market-linkage-p1-web-final-accepted.log)）；类型检查及随后生产构建通过（[构建](assets/2026-10-24-market-linkage-p1-build-final-accepted.log)）。最终浏览器复跑：**9 项通过，1.5m**（[日志](assets/2026-10-24-market-linkage-p1-browser-final-accepted.log)）。两套 API 生成检查及完整 Ruff 通过。本检查点仍等待完整后端验收。

最终输入复查发现，重新封装候选后可以更改 `minimum` 或 `increment`，却不改变另行保留的原始数量规则证据。运行时映射已拒绝这种不一致，但导入入口未立即拒绝。补充两字段绑定检查前，四条独立反例失败。完整七模块 C06 复跑涵盖真实冻结工作进程、两条路径及旧版本兼容，现 **92 项通过，1 条既有警告，186.58 秒**（[日志](assets/2026-10-24-market-linkage-p1-replay-final-accepted.log)）。相比之前全量收集新增四项，最终覆盖统计须单独计入。未改变公开结构、数量规则或运行时授权策略。

## MLV1-21 — 显式操作者审计及最终契约复验

规格对照发现，既有转换路径区分了明确决定和系统效果，但没有持久保存要求的操作者类别。六条用例因缺少 `actor_kind` 失败；禁止客户端声明操作者的测试原已通过。事件模型现在要求服务端产生且纳入哈希的类别，拒绝缺失／未知／重新封装后不一致的类别，保留既有严格命令输入。不据此推断账户身份认证或自动批准。MLC1-07 记录准确事件编码及独立研究来源边界，两套生成配置同步更新。

完整存储／授权／并发／模拟／运行／API／回放／工作进程兼容测试：**152 项通过，1 条既有警告，216.13 秒**（[日志](assets/2026-10-24-market-linkage-p1-authority-final-accepted.log)）。包含此前集成收集没有的七条审计测试及四条数量规则测试。最终后端单元复跑：**3659 项通过，2 条警告，49.64 秒**（[日志](assets/2026-10-24-market-linkage-p1-unit-release.log)）。最终前端：**89 个文件／1262 项通过，9.66 秒**（[日志](assets/2026-10-24-market-linkage-p1-web-release.log)）；类型检查及顺序构建通过（[构建](assets/2026-10-24-market-linkage-p1-build-release.log)）；**9 条浏览器场景通过，1.4m**（[日志](assets/2026-10-24-market-linkage-p1-browser-release.log)）。两套生成检查、完整 Ruff 及空白检查通过。

长时集成进程在生成文件变化前已载入修复前模型，因此其两项生成服务对比使用了不一致的内存／磁盘版本。重新启动并完整运行数据商序列化、数据商分派、现行计划 API、显式审核 API、生成服务契约模块，**71 项通过，1 条警告，16.29 秒**（[日志](assets/2026-10-24-market-linkage-p1-fixtures-release.log)）。该结果也覆盖前述过时 v10 断言，不代表仍在运行的原集成进程已正常通过；C07 前仍须核对其最终失败／跳过清单。

## MLV1-22 — 能力及迁移回归修复

完整集成运行发现旧 `[5,6]` 能力断言及旧迁移头版本断言。独立复现为 **3 项失败／5 项通过**（[红灯](assets/2026-10-24-market-linkage-p1-restart-red.log)）；两个完整模块现 **8 项通过，13.21 秒**（[绿灯](assets/2026-10-24-market-linkage-p1-restart-release.log)）。仓库模块随后复现 **13 项失败／96 项通过**，均为仍期待 `0025_index_close_display` 的精确头版本比较（[红灯](assets/2026-10-24-market-linkage-p1-migration-red.log)）。现要求 `0026_market_exceptions`；未删除数据行保留、回退、权限或完整性断言。

独立运行历史批次索引模块还复现了导入顺序缺陷：如果其他测试没有先导入 `DailyRecord`，Alembic 元数据就未注册该表。迁移环境现显式加载该映射模型并使用其共享元数据。此前完整收集掩盖了该问题，保留独立测试。仓库／批次索引／例外存储／进程重启联合回归：**127 项通过，5 条警告，22.28 秒**（[日志](assets/2026-10-24-market-linkage-p1-migration-release.log)）。独立批次索引模块：**4 项通过，2 条警告，0.95 秒**（[日志](assets/2026-10-24-market-linkage-p1-lot-release.log)）。SQLite 无法为自动元数据对比反射表达式唯一命令索引，既有显式重复命令及并发测试继续验证其约束有效；未抑制警告。完整 Ruff 通过。

原集成进程的批准重启测试还遇到旧操作者结构父进程与当前结构子进程混用。MLV1-21 的最终 152 项授权运行已用两端一致的当前事件契约通过整个并发模块。最终核对仍等待原集成进程结束。

## MLV1-23 — 最终验收（MLP1-T19–MLP1-T21 / MLP1-C07）

完整集成运行已结束：**4606 项通过、35 项失败、1 项跳过、5 条警告，4508.52 秒**。全部 35 项失败均已在[机器可读核对清单](assets/2026-10-24-market-linkage-p1-reconciliation.json)中对应到完整模块复验通过记录。原始运行没有以全绿结束。最终覆盖合并其未受影响的通过项、修复后的完整模块及新增十一条数量规则／操作者测试，不将其表述为一次从头到尾全绿的运行。

最后检查：OpenAPI 模块复现 **2 项失败／12 项通过**，原因为遗漏 P1 批准／哈希记录及测试白名单中的三个已批准路径。补充准确的已批准端点及双语 U-MLP1 批准记录，保留集合精确匹配和错误结构断言后，**14 项通过，17.79 秒**（[日志](assets/2026-10-24-market-linkage-p1-openapi-release.log)）。完整连续监测契约模块 **13 项通过，8.88 秒**（[日志](assets/2026-10-24-market-linkage-p1-loop-contract-release.log)）。最后的诊断失败使用了已导入的旧 v9 夹具；当前夹具下整个模块 **4 项通过，3.13 秒**（[日志](assets/2026-10-24-market-linkage-p1-diagnostic-release.log)），该诊断问题无需再修改应用。

| 最终检查 | 已验收证据 |
| --- | --- |
| 后端单元 | **3659 项通过**，2 条警告，44.16 秒；[最终日志](assets/2026-10-24-market-linkage-p1-backend-unit-final.log) |
| 后端集成 | 完整运行／复验核对后，**4652 个独立用例通过**，保留 1 项 Windows 跳过；包含最终 152 项授权运行中通过的 11 条新增用例 |
| 契约与重放目录 | **13 项通过**，4 项 live 测试未选择，7.87 秒；[最终日志](assets/2026-10-24-market-linkage-p1-backend-other-final.log) |
| 非 live 后端总计 | **8324 个独立用例通过**，1 项平台跳过；4 条 live 用例不在此次本地范围 |
| 前端 | **89 个文件／1262 项通过**，9.66 秒；类型检查与生产构建通过，见 MLV1-21 最终日志 |
| 浏览器 | **9 项通过**，1.4m；覆盖两条路径、旧联动／独立提醒流程及四种宽度，已检查最终截图 |
| 契约与质量 | 两套生成产物一致；完整 Ruff 及空白检查通过；最终哈希记录于 U-MLP1 及核对清单 |

平台跳过为 `test_cursor_key_rejects_foreign_posix_owner_before_use`，既有条件为 Windows，原因为 `requires POSIX ownership semantics`。没有新增跳过、xfail、弱化断言或放宽超时／容量／载荷预算。十证券／252 交易日容量、追踪内存和十万条导出预算通过。SQLite 表达式索引反射及既有 Starlette 诊断保留可见；显式唯一性／并发测试验证无法反射的索引确实生效。

| 标准 | 实际证据／检查点 | 结果 |
| --- | --- | --- |
| MLP1-A01 | [契约用例](../../tests/unit/test_market_exception_contract.py)、[旧 API 精确投影](../../tests/integration/test_market_linkage_api.py)；MLV1-03/12/18 | PASS |
| MLP1-A02 | [策略矩阵](../../tests/unit/test_market_exception_policy.py)；MLV1-04 | PASS |
| MLP1-A03 | [数量独立预期](../../tests/unit/test_market_exception_quantity.py)、MLP1-Q01–MLP1-Q12；MLV1-04/08/11 | PASS |
| MLP1-A04 | [来源审核](../../tests/integration/test_market_exception_review.py)、[更新](../../tests/integration/test_market_exception_updates.py)；MLV1-05/06/14 | PASS |
| MLP1-A05 | [明确权限](../../tests/integration/test_market_exception_authorization.py)、[API](../../tests/integration/test_market_exception_api.py)；MLV1-08/12/21 | PASS |
| MLP1-A06 | [生命周期／运行](../../tests/integration/test_market_exception_runtime.py)；MLV1-09/10/18/21 | PASS |
| MLP1-A07 | [并发／重启](../../tests/integration/test_market_exception_concurrency.py)、[存储](../../tests/integration/test_market_exception_storage.py)；MLV1-07/09/11/21/22 | PASS |
| MLP1-A08 | [实际使用证据／读取／发送保护](../../tests/integration/test_market_exception_runtime.py)；MLV1-10/18/21 | PASS |
| MLP1-A09 | [整笔模拟](../../tests/integration/test_market_exception_simulation.py)、[冻结工作进程](../../tests/integration/test_market_exception_frozen_workers.py)；MLV1-11/18/21 | PASS |
| MLP1-A10 | [API 快照／错误契约](../../tests/integration/test_openapi_snapshot.py)、[旧投影](../../tests/integration/test_market_linkage_api.py)；MLV1-12/21/23 | PASS |
| MLP1-A11 | [浏览器例外流程](../../web/tests/e2e/market-exceptions.spec.ts)、[旧联动流程](../../web/tests/e2e/market-linkage.spec.ts)、[重试／阻断 UI](../../web/tests/unit/marketExceptionRuntime.spec.ts)；MLV1-16/20/21 | PASS |
| MLP1-A12 | [回放变异](../../tests/integration/test_market_exception_replay_mutations.py)、[实际冻结工作进程](../../tests/integration/test_market_exception_frozen_workers.py)；MLV1-18/20/21 | PASS |
| MLP1-A13 | [完整运行／复验核对](assets/2026-10-24-market-linkage-p1-reconciliation.json)及上述最终检查表 | PASS |
| MLP1-A14 | [操作指南](../operations/market-linkage-p1.zh-CN.md)、[规格](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md)、双语任务／README／能力图／索引及本报告；V16 | PASS |

最终差异复查覆盖权限／正确性、可维护性、性能、恢复／错误行为及安全边界。双语章节 ID、全部 28 个任务／检查点勾选、十四项标准、数字规则、枚举／API／JSON 标识、生成哈希及本地链接已核对。仅有代码跨度内的公式文字翻译，表达同一整数集合交集。没有改变依赖或策略决策。T21a–T21d 及 C07 通过。两条例外均要求独立明确人工批准和整笔模拟；冻结回放保留来源及明确操作。未迁移用户数据库，未调用真实数据商／发送真实通知或订单，未推送或部署。真实服务可用性仍不在本地验收范围内。
