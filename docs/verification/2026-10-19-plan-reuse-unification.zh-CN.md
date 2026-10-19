# 计划复用统一验证，2026-10-19

最终检查：PR-V07 记录提交前的限定范围审查。取消审计与窄屏布局均已解决（PR-V05–PR-V06）；较早章节保留当时证据及独立的扩展检查限制。

## PR-V01. 范围与授权

用户批准首期方案，并明确要求删除 JSON/YAML 导入接口。[PRU01–PRU11](../specifications/backtesting/SPEC-plan-reuse-unification.zh-CN.md) 定义边界，[操作说明](../operations/plan-reuse.zh-CN.md) 描述最终流程。本次全部使用合成离线数据，未使用生产数据库、真实计划审核、真实 AI／行情供应商、部署或 Git 推送。

工作台版本保留原来源、审核身份和可执行快照。历史研究上下文单独确认并冻结，已接受运行复制到结果自有输入。现有原文准备和多计划连续回测继续可用。准备存储仅增加一张不可变选择表。交易引擎、报告公式、行情供应商、提示词及任务／结果读取线程上限保持不变。

## PR-V02. 自动检查

| 检查 | 结果 |
|---|---|
| 接口／存储／工作台／导入删除／OpenAPI 专项矩阵 | 236项通过，后续选择／契约补充由下方检查覆盖 |
| 最终选择及双契约兼容矩阵 | 28项通过，包括并发、严格 Origin／上下文、脱敏 SQLITE_BUSY、真实旧单计划／组合存储格式及来源库缺失后重启 |
| 前端完整单元测试 | 75个文件共1121项通过（`--maxWorkers=2`，原超时阈值未变） |
| 前端类型检查及生产构建 | 通过 |
| Ruff（`src tests`）及双契约生成一致性 | 通过 |
| 真实 Chrome 原准备流程 | 5项通过，包括四计划连续账户回放和自动准备历史数据 |
| Chrome 工作台提交／历史／上下文专项 | 最终3项运行中，完整提交和历史决策展示通过；上下文布局／axe断言通过，但严格审计记录一次初始目录 GET 被取消。该上下文测试在局部栅格修正后独立运行通过。 |
| 更广的受影响后端功能矩阵 | 初次运行1671项通过、1项 Windows/POSIX 所有者检查跳过、6项契约断言失败。这些准确契约用例已修正并在最终28项矩阵通过，没有交易／历史用例失败。 |

后端接口矩阵命令：`.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/integration/test_workbench_plan_selection.py tests/integration/test_plan_production_composition.py tests/integration/test_openapi_snapshot.py tests/integration/test_plan_preparation_store.py tests/integration/test_current_plan_api.py tests/integration/test_web_api.py -q`。最终选择／兼容命令：`.venv/Scripts/python.exe -m pytest tests/integration/test_workbench_plan_selection.py tests/integration/test_backtest_service_contract.py tests/integration/test_monitor_loop_contract.py -q`。前端命令：`npm --prefix web test -- --run --maxWorkers=2`、`npm --prefix web run type-check`、`npm --prefix web run build`。静态契约：`.venv/Scripts/python.exe -m ruff check --no-cache src tests` 和 `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`。

浏览器命令：`npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`，以及 `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts --grep 'workbench structured|submits a complete|historical typed'`。Chrome 核对新上下文在320／1440像素、200%字体下的使用、字段边界、严重／关键 axe 问题、真实请求体、原幂等 key 及历史类型化决策展示。结构化表单的栅格固有宽度溢出已在组件内修正，未修改 AppShell CSS。

需独立收集的服务边界单元模块18项也通过，命令为 `pytest tests/unit/test_backtest_service_contract.py -q`。

## PR-V03. 兼容性证据

- 两套 OpenAPI 对比修改前 `81aae039`，全部保留组件 schema 一致，仅删除 `PlanDocumentFormat` 和 `PlanImportCommand`。增加两条选择路由，删除 `/api/v1/plan-imports`，仅改变数据检查／运行／结果联合类型。扣除这些准确扩展后，继续强制比较既有操作／schema。U27记录两套生成快照哈希。
- 核对真实持久化、未启用的工作台审核，拒绝未审核或引用变化版本。`FOLLOW_REMINDERS` 在既有真实工作线程中产生预期成交，`OBSERVE_ONLY` 不产生成交。
- 同 key 选择重试可跨重启，并发冻结仅产生一个资源／回执。同 key 运行重试保持同一运行／任务，意图变化冲突。接受后禁用原读取器并重命名准备数据库，执行、完整结果／成交读取及新应用重启均成功，且未重建来源数据库。
- 升级两种有效旧准备格式，准确保留文档／回执行。保留原单计划及日程编解码，以及准备链继承／账户断言。新增工作台输入身份绑定完整选择，不改变旧输入／哈希域。
- 四计划 Chrome 夹具在首次审核明确提供历史 KNOWN 现金账户，保持原有准确现金／权益／费用断言，同时当前准备默认仍为 `POSITION_LIMIT_ONLY`，生产审核／默认逻辑未改。保留的脚本研究表单19项测试迁到测试专用装配中，因为正常页面已改用结构化工作台上下文。
- 保留原有无关工作改动。既有双语统一计划规格仅增加必要的当前 API 列表／U27内容，其余原有修改文件均核对哈希未变。

## PR-V04. 限制与扩展检查发现

默认完整后端收集存在同名的单元／集成模块（`test_backtest_service_contract.py`），因此显式运行受影响模块，未改变导入规则。大型10标的／252日容量基准在未修改的行情数据准备阶段中止。未降低性能阈值、执行上限或测试，不宣称完成新的容量认证。

更广的回测页面 Chrome 检查最初为 **5项通过／5项失败**，包含刷新／导航期间严格请求审计记录 `net::ERR_ABORTED`，以及320像素／200%字体布局观测。审计保持严格，未过滤请求失败来获得通过。后续工作台／历史／上下文专项结果在上方单独记录。这不代表全部全站浏览器回归通过，也未将无关公共框架／导航行为扩进本次修改。前端全量检查曾出现的超时在不改变原超时阈值的前提下重跑。

未打开或迁移生产存储。旧程序无法读取带标记准备 schema 2，操作说明记录了回退影响。不保证真实 AI／Tushare 可用性、生产负载或部署就绪。

## PR-V05. 取消请求审计后续修复

用户要求在不降低门槛的前提下定位并修复剩余取消审计。系统 Chrome `155.0.8059.80` 可复现 [Chromium 问题568852319](https://issues.chromium.org/issues/568852319/dupes)：no-store 响应已完整读完，但当 EOF 单独晚于最后数据到达时，仍产生 `Network.loadingFailed`／`net::ERR_ABORTED`。官方[修复8508456](https://chromium-review.googlesource.com/c/chromium/src/+/8508456)，commit `62473ad0f747e245e514c93e741bb8e168a2a207`、main revision `1712735`，在通知消费者前先记录终止状态。2026-10-19核对公开 [Chrome for Testing 元数据](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json)，固定 Beta `157.0.8103.6` 的 revision `1717349` 包含此修改；Stable 155 的分支基点更早。

修复前证据：最小页面完整解析1000个响应，但生产读取器回归仅收到985次请求结束事件。未修改的扩展浏览器套件复现为9项通过／2项失败，其中一项取消审计、一项窄屏布局。真实 HTTP 及替代读流实验仅降低频率，未消除缺陷；这些实验性的应用／测试处理器修改均已撤回。

最终仅固定隔离测试浏览器、增加显式准备脚本／缓存忽略项，以及 `streamCompletion.spec.ts`。`backtests.spec.ts`、`monitor-loop-backtest.spec.ts`、全部 `src/` 和 `web/src/` 文件、生成契约及历史夹具均与本次后续修复起点的哈希一致。`expect(audit.requestFailures).toEqual([])`、其余全部既有审计／数量／指标断言、视口、`expect.timeout=5000`、`retries=0`、npm／Python 包版本及生产行为保持不变。系统 Chrome 仍为 `155.0.8059.80`。

| 后续检查 | 结果 |
|---|---|
| `streamCompletion.spec.ts --repeat-each 3` | 9项通过，3000／3000份 JSON 响应及请求结束事件，零取消错误；单独 EOF 成功；真实调用方取消仍产生 `net::ERR_ABORTED`，且没有请求结束事件 |
| 原 `backtests.spec.ts` 与 `monitor-loop-backtest.spec.ts` | 15项通过／1项既有布局失败；5项真实准备／连续流程及历史结果检查均通过，没有取消审计失败 |
| 原有前端全量单元测试，保持原超时 | 75个文件共1121项通过（`--maxWorkers=2`） |
| 既有历史输入／报告／连续回测／研究输入检查 | 61项通过 |
| 类型检查、生产构建、准备脚本 Ruff 及缓存准备重跑 | 通过 |

下载的 Windows 压缩包为210043639字节，SHA-256 为 `128c0f5f1f7e894d9b416c28f1e8db08698a7fd57945495c216589f75ae4e5b8`。浏览器二进制仅位于本地已忽略的测试缓存中。准备命令见操作说明 PR-O04；脚本支持 Linux／macOS 包路径，但本次 Windows 验证未执行这些平台。320像素／200%字体布局观测仍作为独立失败保留，没有被本次取消修复跳过或放宽。


## PR-V06. 窄屏布局后续修复

用户要求修复剩余窄屏布局失败，保持原测试门槛、多计划回测及历史结果。未修改的布局测试复现：320像素视口、根字体32像素（200%）时，整页滚动宽度为477像素。现有 R13 DOM 测量与截图将溢出定位至 `DatasetScopeForm.vue` 的三个筛选输入框：每个从 x=82 延伸至 x=477（395像素），而所属标签／表单容器只有156像素宽。其他三个回测路由的整页宽度均为320像素。导航列表在既有局部滚动容器中延伸，不是整页溢出的来源。

应用代码仅增加 `.dataset-filters__fields input` 的一条局部 CSS 规则：`min-width: 0; width: 100%`，允许输入框随现有网格／弹性容器收缩。没有全局裁剪溢出、缩小字体、新增断点或删除内容。脚本、模板、筛选校验／事件、AppShell、API、交易／账户计算、持久化结果及全部原测试／配置字节，均与本轮开始时哈希一致。已忽略的生成构建产物不计入源码比对。

| 后续检查 | 结果 |
|---|---|
| 原布局门槛：320/768/1024/1440像素 × 四个回测路由，200%根字体 | 16组全部通过；原 `scrollWidth <= clientWidth` 断言不变 |
| 现有 R13 即时／稳定布局诊断 | 通过；四个路由稳定后的整页宽度均为320像素，无未受局部容器约束的元素越出视口；已查看修复前后截图 |
| 原回测页、真实连续回测及响应完成浏览器套件 | 19项通过（7.1分钟），包含全部5项真实准备／连续流程及历史结果检查，无取消审计失败。四计划样本保留2笔成交、最终现金1019000分、费用1000分、已实现盈亏19000分及原7点权益／现金序列。 |
| 原有前端全量单元测试 | 75个文件共1121项通过，原超时不变（`--maxWorkers=2`） |
| 前端类型检查与生产构建 | 通过 |

命令：`npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts --grep 'keeps 320/768/1024/1440|R13 records' --reporter=json`、`npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts`、`npm --prefix web test -- --run --maxWorkers=2`、`npm --prefix web run type-check`、`npm --prefix web run build`。

保留固定浏览器、零请求失败审计断言、5秒期望、零重试、请求／DOM／轮询／ECharts 上限及原账户／现金／权益／历史断言。本轮没有新增容量认证或生产数据／部署验证，PR-V04 的其他限制继续保留。


## PR-V07. 最终检查与提交边界

用户要求最终检查计划来源统一及两项后续修复，明确保留多计划连续回测和历史结果，然后限定范围提交。审查覆盖排除原有保留文案改动后的准确候选树（九个整文件，以及两份统一计划规范的 U22 段落）。当前 API 列表与 U27 新增内容仍纳入。`.tmp/`、浏览器二进制／缓存、生成构建产物及无关改动均排除。

独立后端审查确认：旧单计划／连续输入模型、codec 分支和哈希公式保持不变；已准备多计划执行保留原账户状态转换和执行器。准备库升级保留真实旧单计划／集合文档及幂等回执。已接受的运行拥有完整输入副本，执行、重启、历史报告及导出不依赖可变的原计划库。

提交前修复了一项审查发现：首次工作台读取的 SQLAlchemy 包装 SQLite BUSY/LOCKED 异常可能落入通用500。现在仅在该新增调用处解包 `OperationalError.orig`，将 BUSY/LOCKED 转为脱敏503并携带 `Retry-After: 1`；其他数据库错误保留原失败行为。六组 API 故障用例覆盖原始／包装 BUSY、LOCKED、IOERR，无私有路径泄露、同键恢复及持久化幂等回放。修复前四组忙锁失败／两组非忙锁通过，修复后完整选择模块通过。独立复核关闭此问题，未发现剩余阻断项。

临时反转新增前端研究信息相等校验后，原准确响应测试能够失败；正常验证前已恢复原字节。保留的脚本研究测试套件被识别为重命名，除已批准移除的客户端成员及当前选择器文案外，行为断言不变。没有放宽重试、超时、审计、布局、账户、现金／权益或历史门槛。

| 最终检查 | 结果 |
|---|---|
| 后端完整离线单元测试 | 3331项通过 |
| 审查修复后上下文、旧循环输入及服务边界单元测试 | 47项通过 |
| 完整工作台选择集成套件，含六组新增故障用例 | 15项通过 |
| 原来源、旧库、回测、结果／导出及两套契约集成矩阵 | 526项通过（359.34秒），无跳过或失败 |
| 前端完整单元测试 | 75个文件共1121项通过 |
| 回测页面、五项真实准备／连续流程及响应完成浏览器套件 | 19项通过（6.0分钟），包括全部5项真实准备／连续流程、原四计划账户／现金／权益数值及历史结果，无取消或布局失败。 |
| Ruff、两套生成契约、Vue 类型检查及生产构建 | 通过 |

单元测试命令：`.venv/Scripts/python.exe -m pytest tests/unit -q -m 'not live'`；`.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/unit/test_monitor_loop_input.py tests/unit/test_backtest_service_contract.py -q`；`.venv/Scripts/python.exe -m pytest tests/integration/test_workbench_plan_selection.py -q`。前端、浏览器和静态检查命令同 PR-V02／PR-V06。集成矩阵明确覆盖 `tests/integration/` 下 `test_current_plan_api`、`test_plan_production_composition`、`test_plan_preparation_store`、`test_plan_preparation_review`、`test_single_plan_library`、`test_backtest_service_contract`、`test_monitor_loop_contract`、`test_openapi_snapshot`、`test_monitor_loop_input_store`、`test_monitor_loop_submission`、`test_monitor_loop_result_api`、`test_monitor_loop_retention`、`test_monitor_loop_plan_switch`、`test_monitor_loop_parity`、`test_loop_position_funding`、`test_unified_replay`、`test_unified_replay_parity`、`test_unified_replay_boundaries`、`test_backtest_compatibility`、`test_backtest_result_api`、`test_backtest_exports` 及 `test_web_api`，使用 `-q -m 'not live'`。

审查仅覆盖本次功能改动及所述回归证据，不新增真实供应商、部署或此前未完成容量基准的认证。原有无关工作改动不进入提交，逐字节保留。
