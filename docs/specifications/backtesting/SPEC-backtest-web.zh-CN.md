# 规格：backtest-web

> `SPEC-backtest-web.md` 是面向 Agent 的英文权威版；`SPEC-backtest-web.zh-CN.md` 是中文审阅版；两份文档必须保持语义一致。

## 目标

提供接入生产路由的 Vue 3 回测工作台，覆盖历史数据同步/校验、单计划/单股票运行提交、持久化任务进度/取消、分页运行历史和无障碍结果检查，同时不复制后端规则，也不把模拟活动呈现为实时交易。

## 关系与范围

`backtest-web` 只消费生成的 `backtest-api` 契约，以及共享 `local-web` 应用壳、安全边界和设计 Token。后端是校验、数据覆盖、任务状态、计划资格、成交、指标、保留和结果可用性的权威。Vue 只负责展示状态、明确用户意图、请求生命周期、安全格式化、导航和无障碍。

产品界面继续使用中文（`zh-CN`）。项目双语规则适用于规格、计划、任务、README/API/运维/测试文档；增加运行时 UI 国际化属于独立能力，不包含在本次范围。

## 命令

在 `trade-plan-monitor/web` 运行：

```powershell
npm test -- --run
npm run type-check
npm run build
npm run test:e2e
```

OpenAPI 类型通过后端 `python scripts/generate_frontend_types.py` 生成；绝不手工编辑 `web/src/api/generated.ts`。

## 路由与信息架构

增加四个真实或延迟加载 Route View：

```text
/backtests
/backtests/new
/backtests/data
/backtests/:runId
```

静态 `new` 和 `data` 路由必须位于动态 `:runId` 之前。`/backtests` 是分页运行历史；`/backtests/new` 是运行配置/提交流程；`/backtests/data` 负责历史范围、同步、校验和数据集列表；`/backtests/:runId` 负责活动任务或已完成结果详情。

运行提交被接受后导航到 `/backtests/:runId?jobId=<jobId>`。可选且有界的 `jobId` Query 精确选择一个持久化任务。页面使用生成契约校验两个路由值，获取该任务，并要求 `job.kind=BACKTEST_RUN` 且 `job.runId === route.params.runId` 后才能展示其进度或诊断。不匹配时以 identity 错误失败关闭，绝不把任务关联到该运行，并提供返回历史的安全链接。没有 `jobId` 的深链接只读取 materialized 结果。任务进入 `COMPLETED` 后，规范导航使用 `router.replace` 移除 `jobId`；`FAILED` 或 `CANCELLED` 会保留任务 identity，以展示仅属于任务的诊断和发起新意图重试。同步/校验任务 identity 保留在 `/backtests/data?jobId=<jobId>`，并且必须具有匹配的 `DATA_SYNC|DATASET_VERIFY` kind。Query 参数不会增加生产路由数量。

Route 加规范化 URL Query 是每个可刷新/分享视图选择的事实源：资源 identity、过滤、排序、Cursor/页面遍历、已选结果 `tab`、详情 `kind` 和 `jobId`。组件直接从 `route` 派生，或使用显式无循环双向 Route 同步；绝不维护第二份隐藏权威副本。前进/后退导航会取消过期工作并重建精确视图。服务端规范化 `filters` 会替换等价的非规范 Query 拼写，但不增加 History Entry。任务列表分页 `409 CONFLICT` 会清除过期 Cursor、返回首页，并播报列表已变化。

历史提案基线中的六条生产路由曾是 `createRoutePlaceholder` 条目。当前生产 Router 精确包含 10 条真实或惰性加载的 SFC 路由：曾经的占位路由 `/`、`/stocks/:symbol`、`/plans/:id`、`/alerts` 和 `/system`，既有 `/plans`，以及上述四条回测路由。WEBF13 记录该已完成的路由边界和精确的新建回测旅程；只增加占位路由仍不能算完成。

`AppShell` 桌面端和移动端导航都增加一个顶级 `回测` 链接。回测子导航使用原生链接展示 `运行记录`、`新建回测` 和 `历史数据`。

## 组件地图

Route View 继续作为薄组合面。

| 组件/Composable | 单一职责 |
|---|---|
| `BacktestRunsView` | 组合过滤、分页运行列表和查询状态 |
| `BacktestNewView` | 组合计划/数据集选择、假设、初始持仓和提交 |
| `BacktestDataView` | 组合范围、同步/校验任务、覆盖/阻断和数据集 |
| `BacktestRunDetailView` | 按匹配的 `runId` 组合精确可选 `jobId` 尝试和已完成结果模块 |
| `BacktestRunFilters` | 编辑 URL 驱动的运行过滤条件 |
| `BacktestRunTable` | 渲染只读摘要和原生导航 |
| `BacktestRunForm` | 编辑类型化运行输入并发出明确提交意图 |
| `BacktestPlanVersionSelector` | 渲染后端允许的不可变计划版本分页，并发出选择/翻页意图 |
| `DatasetScopeForm` | 编辑股票/日期/预热范围及明确联网意图 |
| `DatasetCoveragePanel` | 渲染后端生成的覆盖与阻断事实 |
| `BacktestJobStatus` | 渲染阶段/进度/失败并发出取消意图 |
| `BacktestMetricsSummary` | 渲染精确指标、成本、假设和限制 |
| `BacktestEquityChart` | 渲染 ECharts 每日权益/回撤投影 |
| `BacktestEquityTable` | 提供完整文字/表格图表替代 |
| `BacktestFillTable` | 渲染一页服务端分页模拟成交 |
| `BacktestDetailTable` | 渲染一页可判别判断/信号/执行 outcome |
| `useBacktestRuns` | 负责过滤、cursor 请求、generation guard 和只读状态 |
| `useBacktestPlanVersions` | 负责合格计划版本请求、分页、中止、选择和只读状态 |
| `useBacktestRunForm` | 负责本地草稿、精确值解析、校验提示和幂等提交 |
| `useBacktestJob` | 负责一个有界轮询循环、取消、可见性和清理 |
| `useBacktestResults` | 负责独立分页摘要/权益/成交/详情请求 |

组件使用只读 Props 和向上的类型化事件。Composable 返回只读状态和显式 Action。纯格式化器继续作为 Utility。ECharts 实例和大型不可变序列使用 `shallowRef`；派生展示使用纯 `computed`；Watcher 仅用于带清理的可取消副作用。

## 状态与 API 边界

回测状态不进入现有实时 `monitor` Pinia Store。首版使用 URL 状态加 Route-scoped Composable，不需要新增 Pinia Store。如果后续证据支持并单独批准回测 Store，URL 仍是 identity、过滤、排序、分页/Cursor、Tab、详情 kind 和 `jobId` 的权威；Store 只能保存已从服务端加载的权威 Entity、请求 generation/轮询状态和短期表单草稿。它不能复制计算后的服务端结果，也不能隐藏 URL 视图状态。Setup-style Store 返回全部 Reactive State，使 DevTools/HMR 可观察。组件解构 State/Getter 时使用 `storeToRefs`；只有 Action 可以直接解构。

`web/src/api/transport.ts` 拥有一份由现有 Client 和 `web/src/api/backtests.ts` 共用的有界 JSON/错误 Transport；两个 Adapter 都不能复制其 Reader 或错误 Parser。`readBoundedJson` 会在读取前拒绝过大的 `Content-Length`，增量计算 Chunked Bytes，在超过 `MAX_RESPONSE_BYTES = 4 * 1024 * 1024` 时取消 Body，只执行一次 fatal UTF-8 解码，把遍历限制在 `MAX_VALIDATION_DEPTH = 32` 和 `MAX_VALIDATION_NODES = 50_000`，并拒绝畸形/空/尾随 JSON。`parseApiError` 只接受闭合的生成 `ErrorResponse`，把 `ApiErrorCode` 映射到本地固定中文文案，并且绝不显示原始服务端/供应商文字。Abort/Network/Invalid-response 错误继续类型化且不泄密。

`web/src/api/backtests.ts` 消费生成类型，对每个闭合回测 Schema 和跨字段判别关系执行有界运行时校验，深度冻结已接纳记录，并公开类型化 Method 而不是原始 `fetch`。每个 JSON 响应继续低于共享 4 MiB 限制。其日期时间保护复用共享严格上海时间 Parser：输入必须携带 `+08:00` 和 0～6 位小数秒，接纳值在构造 URL/请求前规范化，每个响应必须精确使用 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`；`Z`、无偏移、超精度和其他偏移均封闭失败。`buildBacktestExportHref` 只接受已校验 `runId` 加 `SUMMARY_JSON|FILLS_CSV`，并返回对应同源 API URL。导出使用原生 `<a>`/浏览器导航，让浏览器把服务端 `Content-Disposition` 响应流式落盘；绝不把文件 Fetch 为完整 `Blob`、使用 File System Access API、接受路径或暴露路径。可选预检只读取运行摘要/availability，绝不下载导出内容。

表单值保留精确后端契约。金额使用明确元/分标签输入，并且不经过二进制浮点运算转换；公开分值输入必须不超过 `9007199254740991`。费用/费率继续使用 `0..1` 范围内的规范十进制字符串，滑点继续使用 `0..<10000` 范围内的规范十进制字符串。`BacktestInitialLotInput` 行公开稳定 `lotKey`，最多 200 行，并在校验前保留精确字符串草稿。每个输出 `FenText` 都从 String 或 `BigInt` 格式化，绝不经过 `Number`，因此超过 JavaScript 安全整数范围的值仍保持精确。浏览器可以提前拒绝非法形状，但绝不计算计划资格、持仓上限、交易日历、T+1、成交、指标或数据完整性。

`/backtests/new` 只从服务端分页的 `GET /plan-versions?canActivate=true&offset=<n>&limit=20` 获取真实不可变选项。页面按返回的摘要 identity 展示并翻页，不会合并多个状态查询，也不会在浏览器中过滤不完整页面。合格但未启用的版本仍可选择；只有用户明确提交准确 `planVersionId` 时，后端才重新校验资格。应用服务在返回已接受的运行回执前，把所选版本的规范计划快照及哈希持久化到耐久任务输入。之后的计划编辑会创建其他版本，不能改写该冻结输入、旧结果或既有运行哈希。幂等重放使用已经持久化的绑定，不会重新读取较新的计划。浏览器在此流程中不会缓存或提交 `planJson`，并提供固定、不泄密的加载、空、失败、重试和分页状态。

URL 日期时间筛选、服务端回显筛选和 `<time datetime>` 值都保留规范中国时间。用户可见的表格及图表时间统一使用 `YYYY-MM-DD HH:mm:ss`，同时保留来源钟面时间；机器可读 `datetime` 继续保留固定六位 `+08:00` 值。回测代码绝不对契约值调用 `Date.toISOString()`，也绝不通过主机/浏览器时区转换。

## 异步交互契约

查询状态为 `IDLE|LOADING|READY|EMPTY|FAILED`。提交状态为 `IDLE|SUBMITTING|ACCEPTED|CONFLICT|UNCERTAIN|FAILED`。

- 超时或响应丢失进入 `UNCERTAIN`，并保留同一 Idempotency Key 以安全重试。
- 只有用户开始新的语义意图或修改已提交输入时才生成新 key。
- 每个提交成功都作为 `202 BacktestJobReceipt` 处理。非终态 Receipt 跟随 `Location` 和 `Retry-After`；立即复用的 `status=COMPLETED` Receipt 不要求 `Retry-After`，跳过活动轮询并加载其 materialized 运行。
- 路由/过滤/cursor 变化会中止此前请求；旧 generation 不能覆盖新状态。
- 每个资源最多一个请求，每个活动任务最多一个轮询 Timer。
- 页面可见时，活动任务最多每 2 秒轮询一次，并且前一次结束前不启动第二次；`Retry-After` 控制更慢节奏。
- 页面隐藏/卸载时停止轮询并中止在途工作；恢复可见时立即刷新一次。
- 终态停止 Timer。首版不增加回测 WebSocket。
- 取消按钮只表达意图。`QUEUED -> 200 CANCELLED` 渲染终态；`RUNNING -> 202 CANCEL_REQUESTED` 和重放的 `CANCEL_REQUESTED -> 202` 继续轮询；重放的 `CANCELLED -> 200` 为终态；`COMPLETED|FAILED -> 409 CONFLICT` 会刷新权威任务并说明取消不可用。UI 绝不乐观宣称取消或完成。
- 刷新期间可以保留缓存事实，但必须标注正在刷新/不可用，不能标成当前成功。

## 结果展示

详情页首先加载运行摘要。权益、成交以及仅限 `DECISION|SIGNAL|EXECUTION_OUTCOME` 的详情类型独立加载，并且只在 URL 选择的对应 Tab 激活时加载。绝不把多年成交/详情累积到一个响应式数组。运行字段级 `decisionDetails`、`signalDetails`、`executionOutcomeDetails` 和 `equitySeries` availability 驱动请求与展示。`AVAILABLE`、`EXPIRED` 和 `NOT_RECORDED` 使用不同文案与操作；不可用投影绝不触发推测性重建。失败/取消诊断只从匹配的任务资源渲染，绝不作为运行详情 Tab。

所有成交明确标记 `模拟成交（仅供研究）`。指标展示精确定义和限制 Token；不复权价格与不支持公司行动继续显著展示。导出按钮只请求 `runId` 和 `SUMMARY_JSON` 或 `FILLS_CSV`，不暴露文件系统位置。

## 视觉、响应式与无障碍契约

复用现有 graphite/ink、mineral text、amber、sea-glass、vermilion、cyan、间距、边框、焦点和表格数字 Token。避免装饰性渐变、通用卡片网格、过度圆角/阴影和股票图片。内容层级按工作流优先级组织，而不是等权 KPI 方块。

- 每个路由有一个 `<h1>`、有序标题层级和描述性中文 `document.title`。客户端导航把焦点移至新的 `<h1>`；普通轮询绝不抢夺焦点。
- 每个表单控件都有可见 Label、单位、必填状态和关联字段错误。非法控件设置 `aria-invalid=true`，并通过 `aria-describedby` 关联稳定 Help/Error ID。提交失败后聚焦错误摘要标题，其中的链接把焦点移至对应控件；修正后重试会清除过期关联。
- 优先使用原生 Button/Link/Select/Table/Progress/Dialog 语义。已知总量使用 `<progress>`；未知总量使用阶段文字。
- 关键状态变化使用 `role="status"`/`aria-live="polite"`；一次失败迁移可使用 `role="alert"`，但绝不反复播报轮询次数。
- 取消确认限制焦点、支持 Escape，并在关闭后把焦点还给触发器。
- URL 驱动的结果 Tab 使用原生链接和 `aria-current`；可排序表头公开当前 `aria-sort`；分页控件具有资源/页面 Label，且 Disabled 状态不只用颜色表示。
- 图表具有无障碍名称和完整表格/文字替代，包含相同点位和精确 `FenText` 值。盈亏/风险/任务状态绝不只依赖红绿颜色。
- 焦点始终可见，文本可放大到 200%，遵守 reduced motion，移动端触控目标至少 44×44px。
- 320px 下表单单列，宽表使用带 Label 且可聚焦的横向滚动区域；768px 可以双列但不改变逻辑 Tab 顺序；1024px 可以使用主内容/侧边状态布局；1440px 保持可读最大宽度。

自动化检查不能替代 Windows 上的手工 NVDA 检查。验收覆盖全部四个路由、Landmark/标题播报、表单 Label/错误及错误摘要焦点、无轮询噪音的任务进度/失败、取消 Dialog 焦点恢复、Tab/排序/分页、图表与表格等价、过期文案和下载命名，并在 Chrome 与 Firefox 中只使用键盘导航。

## 安全与性能

所有计划/供应商/错误文字通过 Vue 转义插值渲染；禁止 `v-html`、动态脚本、任意 URL、本地路径和原始服务端异常。用户必须明确确认唯一允许联网的同步操作；UI 绝不接受或显示 Tushare Token。

回测路由使用路由级延迟加载。ECharts 只由结果详情图表 Subchunk 加载，并且只在选择权益 Tab 后加载；运行记录/新建/数据页面不加载图表运行时。每个表格页面 DOM 最多存在 100 行结果，权益最多 2,000 个每日点，每个资源最多一个请求，每个活动任务最多一个轮询 Timer，最大 JSON 页面低于 4 MiB。这些是结构闸门。实现计划必须在性能实现开始前定义固定 Fixture/设备、Route Chunk 预算、请求数场景、LCP/INP/CLS 和交互阈值；本规格未批准任何经验性能数字。

## 项目结构

使用 `web/src/components/backtests/` 功能目录、`web/src/views/` Route View、`web/src/composables/` 或功能目录下的聚焦 Composable、`web/src/api/transport.ts` 中的共享有界 Transport、`web/src/api/backtests.ts` 中的回测 Method/Validator，以及现有 `web/src/assets/tokens.css`。Route View 不能增长为包含多个区段完整实现的大组件。

## 代码风格

使用 Vue 3 Composition API、`<script setup lang="ts">`、PascalCase SFC、script/template/scoped-style 顺序、Scoped CSS Class Selector、用于命令式焦点/DOM Handle 的 `useTemplateRef`、用于 Primitive/本地草稿的 `ref`、用于 ECharts 和大型不可变服务端记录的 `shallowRef`、类型化 `defineProps`/`defineEmits`、稳定 `v-for` key，以及根据生命周期选择的 `v-if`/`v-show`。绝不直接修改 Props 或共享记录。如果后续批准 Setup-style Pinia Store，则返回全部 Reactive State，使用 `storeToRefs` 解构 State/Getter，并且只直接解构 Action。

## 测试策略

Vitest 覆盖每个组件/Composable 状态、只读/Action 边界、请求中止/generation 竞态、`UNCERTAIN` 下 Idempotency Key 复用、立即完成 `202`、轮询时序/清理、完整取消矩阵、字段级可用性文案、精确 `FenText`/`BigInt` 展示和有界十进制输入、全部日期时间字段与 0～6 位到固定六位 `Asia/Shanghai` 规范化、拒绝 `Z`/无偏移/超精度/其他偏移、`<time datetime>` 保留、契约值零次 `Date.toISOString()` 转换、图表映射/表格等价、焦点管理和 100 行边界。共享 Transport 测试覆盖过大声明/Chunked Body、Body 取消、fatal UTF-8、畸形/尾随 JSON、Depth/Node 限制、闭合安全错误解析、Abort、Network Failure 和脱敏。导出测试证明只构造白名单同源 Anchor URL，并且不使用导出内容 `fetch`、完整文件 `Blob`、File System Access API 或路径输入。

Router 测试固定精确 10 条路径，并证明四个回测路径都渲染真实 View。测试通过刷新/前进/后退往返验证规范 `+08:00` 日期时间筛选、其他筛选、排序、Cursor/页面、Tab、详情 kind 和 `jobId`；证明 `/backtests/:runId?jobId=<jobId>` 只接受 `runId` 完全相同的 `BACKTEST_RUN` 任务；证明不匹配/畸形 ID 失败关闭；证明无 `jobId` 深链接只读取 materialized 运行；并证明规范 Query 替换不会形成循环。如果后续批准 Pinia Store，测试还强制 URL 权威、完整 Setup State 返回和 `storeToRefs` 使用。

浏览器测试覆盖完整假供应商数据同步 → 校验 → 提交 → 轮询 → 结果 → 置顶/导出流程、立即复用、Cursor membership 重启、全部可用性状态、Console/Network 失败、320/768/1024/1440 布局、键盘顺序、200% 文本、reduced motion 和 axe WCAG 2.1 A/AA。手工 NVDA 验收遵循上文清单。性能 Fixture 和实测阈值来自获批准的实现计划，而结构化延迟加载/DOM/请求/Timer/响应边界继续作为本规格测试闸门。

## 边界

- 始终：使用生成契约、共享有界 Transport、服务端权威状态、URL 权威可分享视图状态、明确幂等意图、有界请求、薄 View、类型化 Props/Event、安全转义文字及完整 loading/empty/error/uncertain/cancel 状态。
- 始终：标明模拟/研究限制，并让历史数据独立于实时监控。
- 先询问：增加 Pinia 回测 Store、WebSocket、UI 国际化、新图表库、浏览器通知、比较/寻优流程或远程访问。
- 禁止：复制策略/T+1/指标逻辑、复用 Monitor Store、把过滤/排序/页面/Tab/`jobId` 隐藏在 Store 中、渲染原始 HTML、暴露 Token/路径、累积无界详情、把任务诊断公开为运行详情、乐观编造终态或只增加占位路由。

## 验收标准

- 生产路由精确包含 10 条已批准路径，每个回测路径都渲染真实延迟加载 Route View。
- 用户可以明确同步/校验数据、提交一个已校验计划/股票运行、观察/取消持久化任务，并在不刷新页面的情况下检查完成结果。
- 重复点击/超时重试不会创建重复任务或运行。
- 刷新/分享/前进/后退保留 URL 选择的过滤、排序、页面、Tab 和正确映射的 `jobId`，且不会被过期请求覆盖。
- 所有 JSON 和错误都通过唯一有界 Transport；精确 `FenText` 绝不丢失精度。
- 每个 API/URL/机器可读日期时间都保持规范 `Asia/Shanghai`/`+08:00`；用户可见日期时间统一使用 `YYYY-MM-DD HH:mm:ss`，且绝不依赖主机/浏览器时区。
- 摘要优先、独立分页的结果加载保持每页低于 4 MiB 和每页 100 个 DOM 行。
- 模拟、过期、数据限制和服务端状态始终通过文字诚实表示，不能只靠颜色。
- 键盘、焦点、手工 NVDA、响应式、reduced motion、200% 文本、axe、单测、Type Check、Build 和真实浏览器闸门全部通过。
- 生产组合可以访问真实回测服务；Router 加 `SERVICE_UNAVAILABLE` Stub 不能算完成。

## 开放问题

首个工作台提案没有阻断问题。运行时国际化、多运行比较、组合/共享资金回测、参数寻优、WebSocket 进度、浏览器/OS 通知、跨路由 Pinia Store 和经验性能预算继续作为独立未来能力或相应实现计划决策。
