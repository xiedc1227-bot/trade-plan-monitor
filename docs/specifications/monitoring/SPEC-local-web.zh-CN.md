# 规格：local-web（本地 Web 应用）

> 中文审阅版。英文权威版为 `SPEC-local-web.md`；两份文档必须保持语义一致。

## 目标

提供唯一的本地操作界面，用于监控最多 10 只股票、使用配置文件指定的 AI 提取粘贴的自然语言交易计划、审核提取规则、启用不可变计划版本、查看实时证据与图表、维护人工持仓、阅读文本提醒，以及诊断系统健康状态。

FastAPI 负责 REST 和 WebSocket 契约，并在 `127.0.0.1` 提供 Vue 3 单页应用。所有交易条件以后端为唯一权威来源；前端只管理展示状态和用户明确发出的命令。

## 技术栈

后端版本系列：

- Python 3.14.x（`>=3.14,<3.15`）、FastAPI、Uvicorn、Pydantic 2
- 根据 OpenAPI 生成前端类型
- 生产模式下同源提供静态资源

前端版本系列：

- Vue 3，使用组合式 API 和 `<script setup lang="ts">`
- TypeScript、Vite、Vue Router、Pinia
- Apache ECharts
- Vitest、Vue Test Utils、Playwright、axe-core

搭建项目时从官方发布版本中选择具体补丁版本，并固定到锁文件。

## 命令

```powershell
# 后端 API 契约
python -m pytest tests/integration/test_web_api.py -q
python -m pytest tests/integration/test_openapi_snapshot.py -q
python scripts/generate_frontend_types.py --check
python -m trade_plan_monitor web --host 127.0.0.1 --port 8765

# 前端
Set-Location web
npm run test -- --run
npm run type-check
npm run build
npm run test:e2e
```

## 项目结构

```text
src/trade_plan_monitor/web/
├── app.py
├── lifespan.py
├── errors.py
├── schemas.py
├── websocket.py
├── origin_guard.py
└── routers/
    ├── dashboard.py
    ├── symbols.py
    ├── plans.py
    ├── ai.py
    ├── positions.py
    ├── alerts.py
    ├── market_indexes.py
    └── health.py
web/src/
├── api/
├── assets/
├── components/{common,dashboard,symbol,market-index,plans,ai,alerts,health}/
├── composables/
├── layouts/
├── stores/
├── views/
├── App.vue
├── main.ts
└── router.ts
```

## REST 契约

基础路径：`/api/v1`。JSON 字段使用 camelCase，枚举值使用 `UPPER_SNAKE`，列表资源均须分页。所有错误使用统一格式：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Plan cannot be activated",
    "details": [],
    "requestId": "..."
  }
}
```

### T035 应用与错误边界

- `create_app(...)` 只构造 FastAPI 适配器。导入和构造不会加载配置、打开 SQLite、调用供应商、创建任务或绑定网络套接字；不存在通过模块级应用实例启动的隐藏工作。
- 明确注入的运行时工厂只在 FastAPI lifespan 启动时调用。lifespan 恰好持有一个运行时实例，等待 `start()`，接受有效的 `DEGRADED` 只读启动，通过依赖注入提供当前活跃实例，并在清除实例前始终等待 `stop()`。缺少工厂时启动会封闭失败。
- 每个请求都会生成新的 32 字符小写十六进制 request ID。忽略调用方提供的 ID；经过校验的同一值同时出现在 `X-Request-ID` 响应头和错误正文的 `requestId` 中。
- `ApiError`、请求校验错误、HTTP 错误和未预期异常都映射到上述唯一 envelope。对外顶层消息从固定错误码中选择。校验详情最多 100 项；每个 location 最多包含 16 个有界部分，只暴露脱敏 code 以及 `Field required` 或 `Invalid value`。拒绝的输入、Pydantic context、异常 cause、密钥值和供应商/存储原始响应体绝不序列化。
- 共享错误 Schema 严格、冻结、兼容 camelCase，并对 `model_copy(update=...)` 重新校验。T035 不增加监控总览、股票、健康、计划、持仓、提醒、WebSocket、Origin/安全响应头、静态文件或网络监听行为；这些仍属于 T036 及后续任务。

### T036 监控只读边界

- `create_app(read_service=...)` 接收一个明确注入的 `MonitorReadService`，但不构造该服务或启动 I/O。T036 的七个路由都是该服务之上的异步传输适配器；缺少服务时返回 `SERVICE_UNAVAILABLE`。每个服务结果都必须在序列化前通过封闭、不可变的响应模型重新校验；非法内部结果只进入通用错误边界，且不暴露被拒绝的值。
- T036 在 `/api/v1` 下实现 `GET /dashboard`、`GET /symbols`、`GET /symbols/{symbol}`、`GET /symbols/{symbol}/bars`、`GET /symbols/{symbol}/events`、`GET /health` 和 `GET /health/symbols/{symbol}`。它不实现 T037+ 命令、提醒中心查询、计划/AI 资源、WebSocket 传输、Origin/安全响应头、静态资源提供或生产组合。
- 列表分页使用 `offset`（默认 `0`，范围 `0..10000`）和 `limit`（默认 `20`，范围 `1..100`），并返回精确的 `items`、`offset`、`limit` 和 `total`。股票总数最多 10，K 线/事件总数最多 10,000。K 线与事件读取必须显式提供 `Asia/Shanghai` 闭区间时间戳 `startAt` 和 `endAt`；范围反转时返回 `BAD_REQUEST`。K 线读取还接受 `interval=ONE_MINUTE|FIVE_MINUTES`。响应中的分页、范围、周期和股票 identity 必须与请求一致。股票格式非法时返回请求校验失败；格式合法但不存在时返回 `NOT_FOUND`。
- 监控总览返回已提交的 `sequence`、观测/连接/数据年龄状态条、六项已批准统计和最多 10 个相互隔离的股票摘要。每个摘要包含一个权威确定性判断投影，其中保留 `symbol`、`resultHash`、精确计划 identity、判断/行情时间、数据年龄、价格、区间、信号、仓位、阶段/风险状态、强类型证据和下一步。适配器绝不判断条件、修改优先级、重算判断哈希或读取第二套报价流。跨股票 identity、矛盾风险状态、与仓位批次/T+1 可用量不一致以及不一致年龄都封闭失败。
- K 线响应保留规范化整数分 OHLC、股数、精确元成交额、回执时间和聚合公式 provenance。事件响应保留股票、序号、稳定事件 ID/类型、时间戳、可选信号/结果哈希和有界的服务端纯文本。所有 JSON 字段名均为 camelCase，所有枚举值均为 `UPPER_SNAKE`。
- 运行时健康只暴露稳定的生命周期/资源/能力状态、重试/冷却/轮询时间、有序缺口、有界执行器计数、数据库/WAL/检查点/备份事实及投递计数。股票健康暴露精确的数据年龄/完整性/新鲜度/缺口事实。`LIVE` 必须具有新鲜、完整且带最新时间戳的数据；断连、陈旧、有缺口、阻断或其他矛盾数据都不能标为实时或可执行。任何响应 Schema 都不包含密钥、授权详情、供应商原始响应体或存储原始错误字段。

### T037 计划与 AI 操作边界

- `create_app(plan_service=..., ai_service=...)` 接收明确注入的 `PlanOperationService` 和 `AIOperationService` 适配器，但不构造服务，也不启动数据库、供应商、任务或网络工作。缺少服务时以 `SERVICE_UNAVAILABLE` 封闭失败。应用服务负责原子完成幂等占用/回放、乐观修订检查、持久化和审计写入；HTTP 层把经过校验的 `Idempotency-Key` 与服务端生成的 `requestId` 组成一个 `MutationContext` 传入。
- T037 实现 `GET /plan-versions`、`GET /plan-versions/{id}`、`GET /plan-extractions/{id}`、`GET /ai-providers`、`POST /plan-drafts`、`POST /plan-imports`、`POST /plan-extractions`、`POST /plan-activations`、`POST /plan-deactivations`、`POST /ai-providers`、`PATCH /ai-providers/{id}`、`POST /ai-provider-secrets` 和 `POST /ai-provider-tests`。它不实现 T038 持仓/提醒/诊断资源、WebSocket 发布、Origin/安全响应头、静态资源提供、生产服务组合或任何 T024 判断行为。
- 计划版本暴露一个规范、有界的 `planJson` 文档，以及精确的计划/版本/股票/hash identity、保留的有界 `sourceText`、审核问题、确定性校验问题、`canActivate`、状态、修订和创建时间。服务输出会被重新校验，并且必须匹配请求草稿/导入的 identity 与 provenance。`planJson` 保持为规范 `plan-domain` JSON 文档；外围 API 字段仍使用 camelCase。当 `offset` 超过 `total` 时，空分页仍然合法。
- 草稿保存接收 `planJson`、`sourceText`、`reviewIssues` 和 `expectedRevision`。导入接收 `format=JSON|YAML`、安全有界的 `document` 和 `expectedRevision`。启用是针对不可变 `planVersionId` 的独立命令；停用是独立的股票命令。任何未解决的假设、警告、缺失证据、重大遗漏或阻断启用的校验问题都会使 `canActivate=false`，应用服务必须以冲突拒绝启用。
- 计划提取和 AI 供应商测试只接受有界提交命令，并返回带强类型 `QUEUED` 回执的 `202`。路由只等待服务的持久提交边界；既不调用供应商，也不创建或运行提取工作，并且绝不启用计划。提取状态封闭为 `QUEUED`、`RUNNING`、`SUCCEEDED`、`INVALID_OUTPUT`、`PROVIDER_ERROR` 和 `CANCELLED`；成功结果保留恰好一个阻断启用的 `AI_EVIDENCE_REVIEW_REQUIRED`，并且只暴露规范草稿 JSON、有界证据/问题、确定性校验结果、脱敏用量、hash 和时间戳。供应商/模型原始响应体和授权材料没有任何响应字段。
- AI 供应商创建/更新使用完整的不含密钥配置。`PATCH` 是带修订保护的完整替换，其正文 `providerId` 必须与路径一致。API 通过具体 `AIProviderConfig` 的 class-local 脱敏校验器重新校验配置，包括 HTTPS/回环 URL 策略和资源限制。密钥替换接收现有 class-local `SecretWrite` 值，但响应只包含等价于 `SecretStatus` 的已配置状态、来源、固定掩码和代数元数据。服务返回的配置必须与提交的规范化配置一致；额外密钥或供应商原始字段会封闭失败。
- 每个 T037 状态变更端点都要求 1～128 个白名单字符组成的 `Idempotency-Key` 和 `expectedRevision`。重复的执行中意图映射为 409；同一键配合不同请求 hash 映射为 422；已完成的相同意图回放其规范响应。应用服务必须原子完成这些检查与审计写入；路由绝不重建仓储、校验或决策引擎行为。
- 生产 Web 组合在 FastAPI lifespan 启动时，从 `config/app.yaml` 精确加载一个 AI 供应商。它在禁用环境变量后备的情况下，从有大小限制的项目密钥文件读取指定键，构造一个供应商客户端，并在关闭前复用这份不可变绑定。`GET /ai-runtime` 只返回供应商 ID、显示名、Base URL、模型、启用/已配置状态、输入/输出上限和固定修订号 `0`；没有密钥值、密钥路径、密钥键名或 Authorization 字段。通用供应商变更路由仍是注入式适配器契约，但配置文件驱动的生产服务对创建、更新、密钥替换和供应商测试统一返回 `METHOD_NOT_ALLOWED`。修改配置后必须重启 Web。

### T038 持仓、提醒与诊断边界

- `create_app(position_service=..., alert_service=...)` 接收明确注入的 `PositionOperationService` 和 `AlertOperationService` 适配器，但不构造仓储、不打开 SQLite、不判断计划，也不启动工作。缺少服务时以 `SERVICE_UNAVAILABLE` 封闭失败。应用服务负责原子幂等、乐观修订检查、计划所属最大仓位策略、T+1/日历策略、持久化和审计写入。
- T038 实现 `GET /position-lots`、`POST /position-lots`、`POST /position-lot-closures`、`GET /alerts`、`POST /alert-acknowledgements` 和 `POST /diagnostic-evaluations`。它不实现 T039 WebSocket 发布/回放、T040 Origin/安全/静态资源提供、生产服务组合，也不修改任何 T024 判断优先级、hash 或回放行为。
- 持仓分页要求一个精确股票和显式 `asOfTradeDate`，回显请求的分页/筛选 identity，并且只暴露有界的人工批次事实与 T+1 可卖投影。人工建仓要求显式的 100 股整手数量、仓位桶、买入交易日、整数分成本、可选关联提醒和 `expectedRevision=0`；新批次从修订 `0` 开始。减仓是针对一个批次、数量、交易日和预期修订的独立明确命令。批次的持久修订为 `(quantity - remainingQuantity) / 100`，因此每减少一手就前进一步，且无需新增存储列。减仓响应将精确应用数量和交易日绑定到操作前/后的剩余数量及结果批次，且不能报告买入当日或更早日期的成功减仓。应用服务必须在提交持仓审计前拒绝最大仓位、剩余数量、交易日历 T+1 和过期修订冲突。
- 提醒分页使用有界 `offset`/`limit`，并可按股票、可操作信号类型、确认状态和成对的上海时区闭区间时间筛选。分页回显这些筛选条件，拒绝重复事件 ID 或序号，并重新校验每个完整规范 `AlertEvent`，包括去重 identity、严重级别、相关区间、下一步、证据/节点/事实/数值预算、确定性渲染结果和确认时间戳。持仓预填是不提交的值，其股票、数量、仓位桶、目标批次和事件 identity 必须与提醒精确一致；它绝不调用持仓服务。
- 提醒确认是独立的幂等审计命令。提醒修订就是持久确认状态：未确认时为 `0`，确认后为 `1`。首次确认要求修订 `0` 并返回 `1`；对已确认修订 `1` 再次确认是仍保持 `1` 的 no-op；其他过期修订均冲突。响应必须标识请求事件并包含确认时间。该路由不能创建、关闭或以其他方式修改持仓；提醒确认继续与投递成功和成交相互独立。
- 诊断命令必须且只能指定一个规范 `INTRADAY` 五分钟交易时段边界，或一个 `OFFICIAL_CLOSE` 交易日期。服务返回一个规范且自校验的 `EvaluationResult`；适配器在投影权威判断前重新校验其 `resultHash`、内嵌 evaluation identity 和完整结果。该内嵌 identity 的 `planHash`、股票、kind、强类型目标和 `formulaVersion` 必须同时匹配结果与请求，并携带精确来源修订。严格响应要求 `stateMutationApplied=false`、`alertEnqueued=false` 和 `positionChanged=false`；唯一允许的写入是可选诊断审计。路由既不调用也不重新实现决策引擎。
- 每个 T038 POST 都要求有界 `Idempotency-Key` 和 `expectedRevision`。重复的执行中意图映射为 409；同一键配合不同请求 hash 映射为 422；已完成的相同命令回放其规范响应。服务响应的分页、筛选、identity、目标、修订、严重级别、证据分区和持仓形态会在序列化前重新校验；额外供应商/存储/密钥字段在通用错误边界后封闭失败。

### T040 本地 Origin 与静态构建边界

- `create_app(bind_host="127.0.0.1", bind_port=8765, static_directory=...)` 在不绑定套接字的情况下校验监听 identity。唯一允许的主机字面量是 `127.0.0.1`，端口范围限制为 `1..65535`；预留的 `web` CLI 会拒绝通配、局域网、别名和越界值，并给出明确的禁止公开暴露警告。该命令保持无动作，直到 T052 负责生产组合。
- HTTP 或 WebSocket 存在 `Origin` 请求头时，它必须是唯一且精确配置的 `http://127.0.0.1:<port>` Origin；重复、非法、外部、HTTPS、别名或错误端口值均封闭失败。HTTP 以固定 `FORBIDDEN` envelope 和 403 状态拒绝；WebSocket 则在接受前以关闭码 1008 拒绝。缺少 `Origin` 时仍允许非浏览器回环客户端；生产环境不存在 CORS，并移除下游任何 `Access-Control-*` 响应头。
- 每个 HTTP 响应都带固定 CSP、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`，以及关闭摄像头/地理位置/麦克风/支付/USB 的 `Permissions-Policy`。共享错误构造器也会为用户中间件之外生成的未预期 500 响应增加这些响应头。被拒绝的 Origin、正文和异常详情绝不回显。
- 原始 HTTP 请求体按 `Content-Length` 和实际流式分块同时限制为精确 4 MiB（`4194304` 字节）；第一个越界字节返回固定的 413 `PAYLOAD_TOO_LARGE` envelope。该传输预算可容纳既有 200,000 字符 AI 来源文本在最坏 JSON 转义下的大小。既有计划 JSON/YAML 导入和字段级文本上限仍更严格且为权威限制；安全 YAML 加载保持不变。
- 静态服务只接受一个明确注入且已存在的目录，其解析后的本地 `index.html` 必须是普通文件。提供既有文件时不会跟随逃逸 symlink。不存在且无扩展名的 GET/HEAD 路径，以及明确接受 `text/html` 的不存在导航路径会回退到 `index.html`，包括 `/stocks/003043.SZ` 等股票路由；即使构建目录包含 `404.html`，缺失的类资源路径仍使用固定 404 envelope。`/api/v1` 和 `/ws/v1` 在静态路由匹配阶段被排除，因此静态内容不能覆盖 API/WebSocket 路径或改变其方法语义。T040 不执行默认构建发现，也不创建 SPA 入口；T041 提供 `web/index.html`，T052 负责已安装生产资源的发现与组合。

### T041 冻结 OpenAPI 与前端类型边界

OpenAPI 快照 SHA-256：`18ce84db8156ad5c4db94a193157e6509b46ab4a03bfdc1ea2b2dceb88fe9d0c`

- 无副作用的 `create_app()` 是 OpenAPI 的唯一来源。其文档精确包含 41 个已批准 REST 路径：26 个实时路径（包含只读 `GET /ai-runtime` 和 `GET /market-indexes/{indexCode}/bars`）加精确 15 个回测路径，其中包括参考市场覆盖和冻结指数序列读取。文档用 `ErrorResponse` 记录每个稳定公开错误状态；FastAPI 默认的 `HTTPValidationError`/`ValidationError` Schema 被排除，因为运行时校验已经使用有界且不泄密的统一 envelope。
- `scripts/generate_frontend_types.py` 把 `openapi.json` 序列化为排序、缩进的 UTF-8，使用 LF 换行并以一个换行结束。它从同一文档派生 TypeScript 组件 Schema、路径方法、分组参数、请求体、响应状态、媒体类型、引用、联合、交叉、数组、对象、枚举和字面量；绝不手工复制 API 字段。
- `python scripts/generate_frontend_types.py --check` 是只读检查，只要任一已提交生成文件存在逐字节差异就失败。生成过程遇到不支持或悬空的 Schema 引用、参数位置、Schema 类型或非法 TypeScript 标识符时会封闭失败，而不是静默弱化契约。
- `web/index.html` 是稳定的 Vite 应用文档，包含一个 `#app` 根节点和一个外部模块入口，不含违反 T040 CSP 的内联脚本或样式。Vite 现在执行会生成 `dist/index.html` 的文档式应用构建；T042 仍负责首个应用外壳、路由和组件挂载，T052 仍负责已安装资源发现及生产组合。

### T042 无障碍 Vue 应用外壳边界

- `main.ts` 只在 `#app` 存在时挂载根 `App.vue`，为该生产根安装唯一应用路由，并保留工具链测试使用的强类型未挂载组件工厂。导入模块不会创建 API 客户端、store、Socket、定时器或领域状态。
- 生产路由精确声明十条路径。`/plans` 是延迟加载的真实草稿视图，四条 `/backtests...` 路径是延迟加载的真实研究视图，其余五条历史路由在获批视图接通前仍为带标签占位页。路由层不包含领域规则或可变共享行情状态。
- `AppShell` 只负责 landmark、桌面端与移动端导航、路由出口、一个强类型可选 `connectionBanner` 插槽，以及一个局部移动菜单布尔值。只有提供插槽时才渲染横幅包装器，并使用礼貌级状态语义；连接与健康状态所有权仍位于外壳之外。
- 跳转链接把焦点移到持久的 `#main-content` landmark。导航使用原生链接和原生菜单按钮，具备清晰焦点、`aria-controls` 与 `aria-expanded`；Escape 把焦点恢复到菜单按钮，而移动端链接导航会关闭隐藏菜单并把焦点移到主内容。
- 桌面导航在 `48rem` 替代移动端 disclosure。外壳动态效果仅限展示 CSS，`prefers-reduced-motion: reduce` 分支把动画/过渡时长缩短到 `0.01ms`。T043 设计变量、API 客户端、Pinia/store 与恢复行为，T044 流生命周期，后续业务视图、T052 已安装组合、T041 生成契约和 T024 判断语义均保持不变。

### T043 前端状态基础边界

- `App.vue` 加载一份全局变量表。石墨/墨色表面、矿物色文字、琥珀观察、海玻璃绿实时、朱红风险、青色信息、清晰焦点、间距和数字字体变量是语义输入，而非业务判断；`AppShell` 使用这些变量，但不增加领域视图或只依赖颜色的状态。
- 同源 API 客户端当前只负责 `GET /api/v1/dashboard`。它使用生成的 `DashboardResponse` 和 `ErrorResponse` 契约，在 JSON 解析前最多读取 4 MiB 原始响应字节，拒绝未声明字段或敏感字段，校验封闭 camelCase 领域值及精确的上海时区/Gregorian 微秒关系，并且只抛出固定、不会泄密的客户端错误。它不持有响应式或共享状态。
- setup 风格 Pinia store 把冻结的股票快照规范化为有序 ID 和 ID 映射。组件只取得只读状态与 computed 选择器；只有 `applySnapshot`、`applyEvent` 和 `requestSnapshotRecovery` 可以修改 store。语义连接对象始终同时提供代码、中文标签和文本标记，因此状态不只依赖颜色。
- 快照不能让当前序号倒退。精确的下一事件会推进游标并记录冻结的失效提示；重复和更旧事件会被拒绝，而格式错误事件、序号缺口、服务端恢复请求以及 JavaScript 安全整数序号耗尽会在不消费游标的情况下创建明确快照恢复意图。
- T043 只校验封闭的已提交事件信封并记录恢复意图。它不会创建 `WebSocket`、心跳、重连定时器、退避策略、回放请求或快照获取协调器；全部流生命周期行为仍属于 T044。生成的 OpenAPI/TypeScript 工件、后续业务视图、T052 已安装组合及 T024 判断语义保持不变。

只读资源：

```text
GET /dashboard
GET /symbols
GET /symbols/{symbol}
GET /symbols/{symbol}/bars
GET /symbols/{symbol}/events
GET /market-indexes/{indexCode}/bars
GET /plan-versions
GET /plan-versions/{id}
GET /plan-extractions/{id}
GET /ai-runtime
GET /ai-providers
GET /alerts
GET /position-lots
GET /health
GET /health/symbols/{symbol}
```

写入资源：

```text
POST  /plan-drafts                 创建或编辑结构化草稿
POST  /plan-imports                将安全的 YAML/JSON 导入为草稿
POST  /plan-extractions            提交自然语言 AI 提取，返回 202 和任务 ID
POST  /plan-activations            启用一个已验证的不可变版本
POST  /plan-deactivations          停用某只股票的当前计划
POST  /ai-providers                创建不含密钥的供应商配置
PATCH /ai-providers/{id}           更新不含密钥的配置和修订号
POST  /ai-provider-secrets         写入或替换密钥，禁止读取
POST  /ai-provider-tests           创建有界的连接测试任务
POST  /position-lots               记录人工成交
POST  /position-lot-closures       记录人工减仓
POST  /alert-acknowledgements      确认一条提醒
POST  /diagnostic-evaluations      请求不改变状态的人工诊断评估
```

所有改变状态的请求都必须包含 `Idempotency-Key`；可变资源必须包含 `expectedRevision`。重复的执行中意图返回 409；使用相同幂等键但请求哈希不同则返回 422。计划提取和供应商测试均为有界异步任务，返回 202 后不得继续占用请求处理器执行。

OpenAPI 作为规范快照纳入版本控制并用于生成 TypeScript 组件与路径类型；`--check` 会拒绝 API 或生成文件漂移，且不得在前端手工复制契约。

## WebSocket 契约

端点：`/ws/v1/monitor?after=<sequence>`。

浏览器先加载包含序号的权威 REST 监控总览快照，再应用增量事件。已提交事件类型包括：

- `symbol.snapshot.updated`
- `symbol.health.updated`
- `alert.created`
- `alert.acknowledged`
- `plan.extraction.updated`
- `plan.activated`
- `plan.deactivated`
- `position.updated`
- `ai.provider.updated`
- `system.health.updated`
- `market.index.updated`

每个已提交事件使用一个严格、带版本、camelCase 的 envelope：

```json
{
  "type": "symbol.health.updated",
  "sequence": 42,
  "eventId": "00000000-0000-0000-0000-000000000001",
  "aggregateId": "003043.SZ",
  "payload": {
    "entityId": "003043.SZ",
    "symbol": "003043.SZ",
    "revision": 4,
    "status": "STALE"
  },
  "occurredAt": "2026-08-24T10:30:00+08:00",
  "schemaVersion": 1
}
```

载荷是有界失效提示，包含 `entityId`，以及仅在适用时出现的 `symbol`、位于 `0..2^63-1` 的 `revision`、大写 `status` 或小写 SHA-256 `resultHash`；客户端重新读取权威 REST 状态，不能把事件当成状态替代。负责组装总览快照的注入式 `MonitorReadService` 必须在同一个工作单元内读取状态和 `monitor_sequence`，因此返回的 `sequence` 是该快照的准确高水位。T039 强制该传输契约和带序号事件流；默认生产读取服务组合仍明确延后到 T052，且不得用独立采样的序号代替。

Schema 版本 1 封闭每种事件的非空载荷字段集合及 identity 规则：快照使用 `entityId`、`symbol` 和 `resultHash`；股票健康使用 `entityId`、`symbol`、`revision` 和 `status`；两者都要求 `aggregateId == entityId == symbol`。提醒创建/确认使用 `entityId`、`symbol` 和 `revision`；两者都要求规范 UUID `aggregateId == entityId`，创建还要求 `eventId == aggregateId` 且 revision 为 `0`，确认要求 revision 为 `1`。提取使用 `entityId`、`revision` 和 `status`；激活使用计划版本 `entityId`、`symbol` 和正数 `revision`，且 `aggregateId == symbol`；停用使用 `entityId`、`symbol` 和正数 `revision`，且三个 identity 相等。持仓使用 `entityId`、`symbol` 和 `OPEN`/`CLOSED` `status`；AI 供应商使用 `entityId` 和 `revision`；系统健康使用 `entityId` 和 `status`；板块指数失效通知精确使用 `entityId`、正数 `revision` 和 `status`。这些实体自有类型要求 `aggregateId == entityId`。持久化前会拒绝缺少必需字段或包含任何不适用非空字段的事件。

`monitor_event` 是唯一追加式回放来源，`monitor_sequence` 是唯一全局高水位域。状态变更和对应事件追加共享一个事务。事件 UUID 是幂等 identity：相同 ID 及语义返回原序号，语义不同则封闭失败。删除保留期内的行绝不重置序号。默认回放窗口为 7 天，每页最多 1,000 个事件；服务端在发送任何分页前校验完整 `(after, high_water]` 范围，因此页外缺口不能先泄漏部分旧页。

`heartbeat` 和 `snapshot.required` 是传输控制帧，不是已提交业务事件，也不占用持久序号。心跳间隔为 20 秒。缺失、重复、非规范、负数或大于 `2^63-1` 的 `after` 游标均被拒绝。未来游标、序号缺口、高水位损坏或回放窗口过期时，服务端发送携带持久高水位的 `snapshot.required` 并正常关闭。内存发布只在精确校验已提交事件后用于唤醒；重连和进程重启始终从 SQLite 回放。客户端使用带上限的指数退避和抖动重连。断连或陈旧数据必须明确标注，绝不能展示为实时数据。

T044 浏览器生命周期由 `AppShell` 挂载通过单个 `useMonitorStream` 实例拥有；Socket、定时器和可变行情状态都不是全局对象。它先使用 20 秒 Abort deadline 获取 `GET /api/v1/dashboard`，原子应用该权威快照，然后才使用 `after=<snapshot.sequence>` 打开同源 `ws:`/`wss:` 端点。有序已提交事件只是失效提示，会触发重新获取权威快照；缺口、格式错误帧、游标不匹配及 `snapshot.required` 也会执行相同恢复，且不会把陈旧数据展示为实时。Socket 建连 deadline 为 20 秒。由于服务端每 20 秒发送一次心跳，已打开连接只有在漏掉两次心跳间隔（40 秒）后才视为静默，从而避免相同 deadline 竞态。只有心跳游标匹配且权威总览状态为 `CONNECTED` 时才进入 `LIVE`；否则横幅保持 `STALE`。

重连的指数基数依次为 1、2、4、8、16 秒，之后最多为 30 秒；先限制该基数再应用 `0.8..1.2` 抖动，最终延迟绝不超过 30 秒。明确恢复会中止当前快照、关闭活动 Socket、清除全部存活/重试 deadline，并从 REST 重新开始。卸载执行相同清理，但不会重连。外壳向强类型连接横幅插槽暴露只读语义状态，并提供包含文字标记和标签的默认礼貌级状态，因此颜色绝不是唯一提示。该生命周期不包含领域规则、API 字段复制、业务视图、持久浏览器状态、T052 资源发现或 T024 判断行为。

### T045 AI 计划工作台边界

T045 `PlanWorkbench` 只通过强类型 props/emits 组合 setup 风格 Vue 组件。`AIProviderSelector` 展示只读 `ConfiguredAIRuntimeView`：显示名、模型、安全 Base URL、输入上限、启用状态和密钥是否已加载。页面没有密钥输入、供应商创建/修改、连接测试或浏览器持久化功能。页面明确提示用户修改 `config/app.yaml` 或项目 `.env` 后重启 Web。

`PlanDraftingView` 与 `usePlanDrafting` 负责同源 API 流程。挂载时读取 `GET /api/v1/ai-runtime`；提交时生成一个幂等 Key，调用 `POST /api/v1/plan-extractions`，把 `QUEUED` 回执显示为当前任务，然后轮询 `GET /api/v1/plan-extractions/{operationId}`，直到进入封闭的终态。局部同时只运行一组提交/轮询。卸载会中止请求和计时器。“停止等待”只停止浏览器轮询，并明确说明服务端已经接收的任务可能继续；它不会谎称服务端任务已取消。错误使用固定中文文本，不包含供应商、密钥或传输原始详情。

`SourceTextEditor` 拥有一个局部纯文本模型。上限来自选中的运行配置，按与 Python 一致的 Unicode code point 计数，在第一个被拒绝的 code point 处停止扫描，并原子拒绝超限编辑而不截断。`ExtractionEvidence` 只通过已转义的 Vue 文本插值渲染经过校验的证据、假设、警告、遗漏、校验问题、用量和有界状态。成功的规范草稿也只作为转义文本显示并保持待审核；任何提取响应都不能启用计划。T046 继续负责结构化编辑、差异、校验编排和启用。

### T046 结构化计划编辑与激活边界

T046 `PlansView` 只通过生成的命令/视图契约组合路由局部版本选择、`StructuredPlanEditor` 和 `ActivationDiffDialog`。九个分区编辑器保留未知顶层计划内容，生成不求值条件的人类可读预览，并发出带修订保护的草稿/导入/导出意图。JSON/YAML 解析、规范化、确定性校验、交易规则、持久化和传输仍由后端或后续组合负责。活动版本绝不通过 props 改写；编辑只发出新草稿命令，dirty 局部内容在修订冲突、重复选择和分页移除版本时继续保留，直到用户明确重新载入或放弃。

导入文档及最终紧凑草稿/导出文档使用有界单遍检查和原子拒绝限制为 256 KiB UTF-8。pretty-print 的局部编辑缓冲使用独立 4 MiB 安全上限，避免合法紧凑计划仅因缩进膨胀而被拒绝。服务端和导入文本只作为已转义内容渲染；任何原始文本都不进入 `v-html`、日志、URL、持久浏览器状态或可变共享状态。

存在未解决重大审核项、激活阻断校验项、dirty 编辑、busy 状态、缺失计划状态、跨股票 identity、缺失活动版本内容或修订漂移时，激活都会封闭失败。前后差异对话框使用真实模态边界，具备初始焦点、原生焦点约束、Escape/取消处理和焦点恢复。候选/当前计划的哈希、文档、状态、股票、修订及预期活动状态修订发生任何变化都会撤销确认；父级权威状态失配会关闭对话框，且不会静默重开。激活和停用保持为两个独立明确命令。T047+ 业务视图、API/store 组合、T052 已安装组合、T041 生成契约和 T024 判断语义保持不变。

### T047 多股票总览边界

T047 `DashboardView` 从只读规范化 `SymbolSummaryView` 快照组合带标签工具栏、无障碍原生监控表格、条件计数展示和强类型可执行提醒栏插槽。它最多展示由 store 强制保证的十只股票，并显示权威价格、区间、已满足/总条件数、信号、持仓数量、风险距离、精确行情时间、数据健康、连接和年龄。搜索在展示匹配前限制为 128 个 Unicode 码点；筛选和排序只作用于复制的展示数组，使可空值始终排在最后，并且绝不修改输入快照。

Vue 不计算条件 DSL、指标、区间、信号优先级、风险状态、新鲜度或服务端计数。只有已连接、健康为 `LIVE` 且新鲜的行才在展示层视为实时；其他每种合法健康组合都在陈旧/降级筛选中明确可见，且不能改变或隐藏健康同伴。加载和有界转义错误可以与缓存行并存，而零行快照不可用时不会误报成业务监控列表为空。原生链接和带标签控件均可通过键盘访问，所有颜色状态都带语义文字。API/WebSocket/Pinia 路由组合、图表与证据（`T048`）、已安装组合（`T052`）、T041 生成契约和 T024 判断语义保持不变。

### T048 个股图表与证据边界

T048 严格从只读 `SymbolDetailResponse`、`BarView` 和 `SymbolEventView` 输入组合 `SymbolDetailView`、`PriceChart`、`EpisodeTimeline` 与 `useChartSeries`。composable 复制并排序后端 OHLC、展平权威证据层级、只映射白名单内的服务端价格/指标事实、在缺少图表坐标时仍保留提醒，并发布一个 shallow 不可变序列。它不计算指标、条件、区间、信号优先级、风险、新鲜度或任何交易规则。

指标点只使用同一证据节点中的 sibling `DATE` 或 `DATETIME` 证据事实。`DATE` 只能锚定该日期的最后一根 K 线；缺少日期、来源时间戳或同日 K 线时，`time` 和/或 `plotTime` 保持不可用；图表数值非有限或发生 underflow 时则不绘制，但不会丢弃表格事实。无障碍替代内容逐字保留后端精确 Decimal 文本，绝不以 ECharts 舍入后的显示数据替换。由于公共契约没有提供低点时间戳，`episodeLowFen` 保持为发生时间未知的水平数值。Vue 文本插值使事件/错误/证据文本保持惰性，陈旧或降级状态在明确警告下仍保留可见事实，并且只有 `PriceChart` 管理 ECharts 初始化、缩放处理、区间 emits、释放和非 HTML tooltip。API/store/router 组合、人工持仓命令（`T049`）、后续业务视图、已安装组合（`T052`）、生成契约和 T024 判断语义保持不变。

### T050 文字提醒中心边界

`AlertsView` 只拥有路由局部查询意图、权威分页替换、有界实时失效事件去重，以及一个注入式幂等确认操作。`AlertTable` 管理带标签筛选、原生分页、安全的服务端正文、完整的 matched/satisfied/unmet/blocker 证据展开、事件 identity、图表时间链接，以及明确的“确认不等于成交”文案。`AlertRail` 只报告同步状态，不复制提醒实体，也不把 WebSocket 失效提示当作提醒正文。

每个成功列表结果都必须回显请求分页与筛选，事件 ID 和序号不得重复，并且每行都必须符合股票、信号、确认状态及创建时间闭区间筛选。已提交的 `alert.created` 或 `alert.acknowledged` 失效提示只有在更新的权威分页成功后才标记为已同步；失败保持可重试，pending 与已记忆 identity 都有界。陈旧列表 generation 不能覆盖更新的查询或确认状态。

确认操作在传输前预留有界容量，只发送一条绑定 revision 的幂等命令，绝不把确认回执直接写入展示分页，并且始终通过权威读取核对。有效、无效、冲突和不确定结果都保留固定的密钥安全文案，直至任一后续权威分页证明已确认、未确认或仍不确定。持久礼貌级状态和焦点 fallback 在筛选移除行后继续存在。确认绝不调用持仓操作，也不改变展示的持仓事实。API client/store/router 生产组合、系统健康（`T051`）、已安装资源（`T052`）、生成契约和 T024 判断语义保持不变。

### T051 系统健康与无障碍边界

`SystemView` 是基于可选生成 `RuntimeHealthResponse` 的薄只读组合表面。它区分加载、不可用、失败和安全缓存状态，不渲染原始传输/供应商错误，并且只发出明确的刷新或股票选择意图。`MarketStatusStrip` 展示后端生成的生命周期、观察时间、成对的已完成分钟/判断时间戳与年龄、轮询、重试和冷却事实。`HealthMatrix` 展示供应商能力/延迟、有界缺口、执行器利用率、数据库/WAL/检查点/备份及投递状态。每个供应商/资源状态都拥有自己的文字、形状和 `data-status`；稳定诊断代码通过白名单展示，其他值一律掩码。

该切片不调用 API、不写 Pinia、不组合 router、不计算供应商/规则或新鲜度，也不处理密钥。原生控件、带标签表格和滚动区域、持久清晰焦点、礼貌级状态、减少动态效果，以及 320/768/1024/1440 像素布局，均由单元测试和真实 Chromium/axe WCAG 2.1 A/AA 门禁验证。已安装资源发现和生产组合仍属于 T052；完整浏览器流程仍属于 T055；生成契约和 T024 判断语义保持不变。

### T052 安装式生产启动与资源边界

- 安装后的 `trade-plan-monitor` 控制台入口解析到 `trade_plan_monitor.cli:console_main`。CLI 导入和解析器构造继续保持无副作用；`web` 分支只有在精确回环主机和有界端口解析成功后，才惰性创建一个生产应用上下文并导入/运行 Uvicorn。
- Vite 继续以 `web/index.html` 为文档输入，并继续生成 `web/dist/index.html`。仅构建时启用的插件会用同一份完整 distribution 替换被忽略的 `src/trade_plan_monitor/web/dist` 暂存目录；setuptools 只打包其中的 `index.html` 和本地 `assets/*`。两个生成目录都不纳入版本控制。
- 生产资源发现通过 `importlib.resources` 在整个服务生命周期内访问 `trade_plan_monitor.web/dist`。它绝不搜索当前工作目录、仓库根目录、`web/dist` 或其他源码树 fallback。缺少目录、`index.html`、`assets/` 或实际资源时，会在 Uvicorn 启动前只以 `WEB_ASSETS_UNAVAILABLE` 和固定文案 `Installed Web assets are unavailable.` 失败；绝不暴露路径、资源异常、context 或 cause。
- `create_production_app(...)` 通过既有 `create_app(...)` 组合发现的 distribution，因此冻结的 41 个 REST 路径（26 个实时路径加 15 个回测路径）、`/ws/v1/monitor`、Origin/正文/安全响应头策略以及 SPA 排除与 fallback 语义均不改变。资源上下文保持到服务 runner 退出，随后 FastAPI lifespan 执行其自有关闭，并释放可能解压的资源。
- T052 的通用监控生命周期仍使用明确的 `DEGRADED` 只读 fallback，但现在负责配置文件驱动的 AI 生命周期。启动顺序是监控运行时、AI、回测，关闭严格反向执行。AI 启动时只读取一次 `config/app.yaml`，并尝试读取选中的、被忽略的项目密钥文件。YAML 非法会导致启动失败；选中的密钥文件缺失、格式非法、键重复、值为空、超大或不可读时，以 `configured=false` 启动，因此页面不能提交提取。明确注入的测试/应用服务继续保持权威。不增加环境变量后备、CDN、远程运行资源、备用监听器或开发目录 fallback。

### 已批准的回测扩展边界

六模块回测方向和本边界已于 2026-08-26 获批。用户也确认了 [`backtest-api`](../backtesting/SPEC-backtest-api.zh-CN.md) 并批准 [`backtest-web`](../backtesting/SPEC-backtest-web.zh-CN.md)。用户已于 2026-08-26 确认修正后的 `planVersionId`、金额投影、结果/任务一致性、版本化兼容及统一中国时间条款。以下数值约束当前生成契约和继续分别受闸门约束的后续 Router 工作：

- 当前冻结契约精确为 41 条 REST 路径：26 条实时路径（包含只读 AI 运行配置和板块指数历史）加精确 15 条回测资源路径，OpenAPI 快照、哈希、生成 TypeScript 和运行时保护已同步更新；
- 生产 Router 精确包含十条路径：一条真实 `/plans` 视图、四条真实或延迟加载的 `/backtests...` 视图，以及五条剩余历史占位路由；两个静态回测子路由继续排在动态路由之前；
- 增加真实计划与回测路由不能证明五条剩余历史占位路由已经接入业务视图；
- 全部 15 条回测路径、四条路由、生成类型、运行时保护、URL 日期时间/日期筛选和机器可读 Web 值都继承已批准的规范 `Asia/Shanghai` 契约：日期时间输入使用 `+08:00` 和 0～6 位小数秒，日期输入使用规范 `YYYY-MM-DD`，适用的日期时间输出/存储固定六位，并拒绝 `Z`、无偏移、超精度、其他偏移或非法日历值；
- 首个版本对持久化任务采用有界 REST 轮询，不增加回测 WebSocket 事件；
- 未显式注入生产服务时，`create_production_app(...)` 继续处于 `DEGRADED`/`SERVICE_UNAVAILABLE`。仅注册 Router Protocol 不等于产品可用组合。

## 信息架构

### `/` — 监控总览

- 行情、数据供应商、连接和数据年龄状态条。
- 可执行、低吸观察、阻断、风险、陈旧和正常状态的数量统计。
- 最多 10 只股票的紧凑可排序自选表：价格、区间、条件进度、信号、持仓、风险距离、行情时间及健康状态。
- 搜索与筛选，以及独立的可执行提醒栏。

### `/stocks/:symbol` — 个股详情

- K 线图展示低吸区、压力区、风险线、指标、当前阶段低点和提醒标记。
- 数据源时间与年龄、计划版本、持仓批次、T+1 状态和当前决策。
- 含数值证据及阻断原因的条件清单。
- 阶段与风险时间线、指标表格、提醒和数据供应商诊断。
- 为图表信息提供无障碍表格替代视图。

### `/plans` 和 `/plans/:id` — 计划工作台

- 版本列表，以及已启用或草稿状态。
- 自然语言原文编辑器。
- AI 供应商选择和提取进度。
- 并排展示原文证据、结构化字段、假设、警告、遗漏和验证问题。
- 分区结构化编辑器和人类可读的可执行预览。
- 版本差异，以及明确的启用或停用确认。
- YAML/JSON 导入与导出。

### `/alerts` — 提醒中心

- 分页显示文本交易提醒和健康提醒。
- 按股票、类型、时间及确认状态筛选。
- 展开查看证据、阻断条件、事件 ID 和图表时间链接。
- 确认文案必须明确说明“确认提醒不代表成交”。

### `/system` — 系统健康

- Tushare 能力、延迟、冷却、下次轮询、缺口、线程池、数据库和 WAL、备份及投递健康状态。
- 此页面不修改 AI 配置。`/plans` 只显示安全的只读运行摘要，项目配置文件始终是权威来源。

### `/backtests`、`/backtests/new`、`/backtests/data` 和 `/backtests/:runId` — 回测研究

- 浏览有界的已完成运行摘要并打开一个不可变结果。
- 提交前选择一个经审核计划版本、一只股票、一个冻结数据集、显式现金/持仓输入和成交假设。
- 检查历史覆盖、提交经授权同步或离线校验，并跟踪一个持久化任务而不阻塞 HTTP 请求。
- 审阅精确指标、假设、带完整表格替代的每日权益、分页成交/详情、导出、置顶状态、进度、取消、过期和失败状态。
- 历史研究继续与实时监控、提醒、通知投递、券商操作和 `T058` 证据隔离。

## Vue 组件地图

路由视图只负责组合页面。

| 组件 | 职责 | 输入 | 输出 |
|---|---|---|---|
| `AppShell` | 导航、连接横幅和路由出口 | 连接与健康状态 | 导航 |
| `MarketStatusStrip` | 行情、供应商和轮询健康状态 | 系统健康状态 | 打开系统页 |
| `WatchlistToolbar` | 搜索、筛选、排序和视图模式 | 用户偏好 | 强类型变更事件 |
| `WatchlistTable` / `WatchlistRow` | 渲染规范化股票摘要 | 股票摘要 | 选择股票 |
| `ConditionProgress` | 展示成立、部分成立和阻断证据 | 条件状态 | 无 |
| `AlertRail` / `AlertTable` | 最近及历史提醒 | 提醒摘要或分页数据 | 选择或确认 |
| `PriceChart` | ECharts K 线、区间和标记 | 不可变图表序列 | 区间变更 |
| `EpisodeTimeline` | 阶段与风险状态转换 | 时间线事件 | 选择时间 |
| `PositionLots` | 局部批次表单、T+1 展示和显式确认 | 权威分页/预填/操作网关 | 已确认的增加或关闭命令 |
| `PlanWorkbench` | 编排提取、审核、编辑和启用 | 草稿与提取结果 | 保存或启用 |
| `SourceTextEditor` | 纯文本计划输入 | 原文 | 更新文本 |
| `AIProviderSelector` | 显示或选择配置文件中的供应商 | 安全运行摘要 | 选择 |
| `ExtractionEvidence` | 展示证据、不确定性和遗漏 | 提取结果 | 解决问题 |
| `StructuredPlanEditor` | 分区编辑强类型草稿 | 计划草稿与问题 | 更新草稿 |
| `ActivationDiffDialog` | 确认不可变版本切换 | 变更前后内容与问题 | 确认或取消 |
| `HealthMatrix` | 供应商及股票健康矩阵 | 健康数据行 | 选择股票 |

`monitor` Pinia store 管理规范化快照和事件状态，通过只读视图及明确的 `applySnapshot`、`applyEvent` 和恢复操作修改。路由内计划与持仓表单保持局部状态。`useMonitorStream`、`useSymbolFilters`、`useChartSeries` 和 `usePositions` 封装生命周期或派生逻辑。ECharts 实例和大型不可变序列使用 shallow ref。组件使用强类型 props 和 emits，绝不直接修改共享记录。

`SymbolDetailView` 只是 T049 的组合表面。`PositionLots` 管理带标签的原生控件、由提醒拥有的预填字段、确认对话框状态和焦点恢复。`usePositions` 接受 maybe-reactive 股票/日期/分页/上限/预填输入和注入的普通函数操作网关；它暴露 shallow-readonly 权威状态及显式变更方法。提醒可以预填表单但不能提交，提醒确认不能创建或减少批次，每条命令都绑定已复核批次 revision 和新的幂等键。只有建仓/减仓回执与随后刷新的权威分页一致时才报告成功。冲突刷新使用原始变更上下文，generation 闸门阻止较旧响应覆盖较新分页，不完整分页不能用于推断最大持仓总量。浏览器可以实施输入形状、整手展示保护及不超过后端 `sellableQuantity` 的数量保护，但绝不计算交易日历或 T+1 资格。T050 提醒视图、生产 API/store/router 组合、安装后资源发现和 T024 判断行为均不属于该边界。

## 视觉与无障碍方向

采用“工业信号控制台”风格：石墨与墨色表面、细密技术网格、矿物白文字、黄铜或琥珀色观察状态、低饱和海玻璃绿实时状态、只用于真实风险的朱红色，以及少量青色信息强调。数字使用等宽表格字体并对齐小数点。避免紫色渐变、过量玻璃卡片、超大 KPI 卡片和装饰性股票图片。

- 以 WCAG 2.1 AA 对比度为目标。
- 不只依赖红绿颜色表达状态，同时使用标签、图标和形状。
- 支持完整键盘导航、清晰焦点、跳转到主内容，以及有标签的表单、对话框和表格。
- 普通状态使用礼貌级 `aria-live`；只有时效性可执行提醒或风险提醒使用强提示。
- 尊重减少动态效果设置。
- 适配 320、768、1024 和 1440 像素宽度。
- 禁止使用未净化的 `v-html`；计划和 AI 文本必须作为经过转义的纯文本显示。

## 本地安全边界

- 生产命令只绑定 `127.0.0.1`；远程/局域网模式、主机别名、端口转发和公开暴露均不在范围内。
- 单页应用、API 和 WebSocket 同源；生产环境关闭 CORS，并拒绝异常 HTTP 或 WebSocket Origin。
- MVP 不实现登录或身份认证。文档必须明确禁止端口转发或公开暴露。
- 设置 CSP、禁止嵌入、内容类型、Referrer 和 Permissions 等安全响应头。
- 原始请求体限制为 4 MiB，既有字段/导入限制保持更严格，YAML 必须安全加载。
- AI 基础 URL 只允许 HTTPS，但允许用户自建本地模型使用明确的回环地址例外；拒绝重定向和内嵌凭证。
- 密钥只写，并从响应、前端状态、导出、日志和错误中脱敏。
- 所有计划、供应商、持仓、提醒确认和启用变更都必须写入审计记录。

## 代码风格

```vue
<script setup lang="ts">
interface Props {
  extraction: PlanExtraction
}

interface Emits {
  resolveIssue: [issueId: string]
}

defineProps<Props>()
const emit = defineEmits<Emits>()
</script>

<template>
  <button type="button" @click="emit('resolveIssue', extraction.id)">
    标记为已处理
  </button>
</template>
```

统一使用 `<script setup lang="ts">`、PascalCase 单文件组件、script/template/scoped-style 顺序、功能目录、纯计算派生状态；watcher 只用于带清理逻辑的副作用。

## 测试策略

- 后端契约测试覆盖所有端点、schema、错误格式、分页、幂等、乐观冲突、Origin 防护、密钥脱敏和 OpenAPI 快照。
- WebSocket 测试覆盖快照一致性、顺序、回放、序号缺口、重连和重启。
- Vue 单元测试覆盖 store、计划工作台、AI 提取审核、启用闸门、自选表、详情、提醒、设置、加载、错误、空状态及键盘交互。
- 图表映射测试及无障碍表格替代视图测试。
- Playwright 端到端流程：使用项目测试配置中的模拟 AI 供应商启动、粘贴计划、提取、解决警告、启用、回放行情、接收一条提醒、确认提醒，并验证持仓未变化。
- 使用 axe 执行无障碍自动化测试，并补充键盘和人工检查。
- 在桌面、平板和移动端宽度下进行浏览器验证。

## 边界

- 始终：可执行规则和验证以后端为权威来源。
- 始终：如实展示数据新鲜度和连接状态。
- 始终：启用计划和修改持仓必须显式确认。
- 需先确认：增加身份认证、远程访问、操作系统级浏览器通知或新的外部消息渠道。
- 禁止：暴露密钥、在 Vue 中复制规则逻辑，或把提醒确认当作成交。
- 禁止：把 AI 或用户文本作为原始 HTML 渲染。
- 禁止：让提取请求直接启用计划。

## 验收标准

- 一个本地 URL 支持从粘贴文本计划、审核到启用计划的完整流程。
- 监控总览和详情页独立展示全部 10 只股票，并在不刷新整页的情况下更新。
- 浏览器断连后从一致快照恢复，且绝不把陈旧数据显示为实时。
- Web 使用项目配置加载的 AI 供应商，不显示修改控件，也绝不接收密钥值或其文件/键引用。
- 存在重大遗漏或验证错误时，计划不得启用。
- 一个确定性买入事件只生成一条带证据和免责声明的文本提醒。
- 界面满足键盘操作、对比度、响应式、减少动态效果和非纯颜色表达等要求。
- 正常启动路径不监听回环地址以外的网络接口。

## 待确认问题

- 无阻断问题。操作系统级浏览器通知和指定聊天平台保留为未来可选渠道。

## 审核状态

基础 `local-web` 规格和已完成的 `T035`～`T056` 实现历史继续保持此前已批准状态。用户于 2026-08-26 批准 `Backtest Extension Boundary` 和 `backtest-web`，确认 `backtest-api`，随后确认统一 `Asia/Shanghai`/`+08:00` 时间契约及其余 API/engine/results/jobs 一致性修正。聚合详细规格闸门现已关闭。双语实施计划第 15 节和生成的 `BT009`～`BT050` 任务清单已分别获批。板块指数扩展于 2026-09-02 获批并获离线实施授权。当前 OpenAPI 契约精确包含 41 条路径，其中 26 条为实时路径、15 条为回测路径；生产 Router 精确包含 10 条路径，其中 `/plans` 和四条回测路径是真实视图，其余五条仍为占位页。提交、推送、依赖安装和联网访问继续需要分别授权。
