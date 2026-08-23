# 规格：local-web（本地 Web 应用）

> 中文审阅版。英文权威版为 `SPEC-local-web.md`；两份文档必须保持语义一致。

## 目标

提供唯一的本地操作界面，用于监控最多 10 只股票、粘贴自然语言交易计划、配置 AI、审核提取规则、启用不可变计划版本、查看实时证据与图表、维护人工持仓、阅读文本提醒，以及诊断系统健康状态。

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
    └── health.py
web/src/
├── api/
├── assets/
├── components/{common,dashboard,symbol,plans,ai,alerts,health}/
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
    "message": "交易计划无法启用",
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

只读资源：

```text
GET /dashboard
GET /symbols
GET /symbols/{symbol}
GET /symbols/{symbol}/bars
GET /symbols/{symbol}/events
GET /plan-versions
GET /plan-versions/{id}
GET /plan-extractions/{id}
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

OpenAPI 快照纳入版本控制并用于生成 TypeScript 类型；不得在前端手工复制契约。

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
- `snapshot.required`

心跳间隔为 20 秒。客户端使用带上限的指数退避和抖动重连。序号缺口或回放窗口过期时，必须重新获取 REST 快照。断连或陈旧数据必须明确标注，绝不能展示为实时数据。

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

### `/system` — 系统与 AI 设置

- Tushare 能力、延迟、冷却、下次轮询、缺口、线程池、数据库和 WAL、备份及投递健康状态。
- AI 供应商、基础 URL、模型、限制和提示词版本配置。
- 只写 API 密钥替换、已配置状态掩码和有界连接测试。
- 不展示密钥值或原始授权错误。

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
| `PositionLots` | 持仓批次和 T+1 状态 | 持仓摘要 | 增加或关闭请求 |
| `PlanWorkbench` | 编排提取、审核、编辑和启用 | 草稿与提取结果 | 保存或启用 |
| `SourceTextEditor` | 纯文本计划输入 | 原文 | 更新文本 |
| `AIProviderSelector` | 选择或测试已配置供应商 | 供应商与状态 | 选择或测试 |
| `ExtractionEvidence` | 展示证据、不确定性和遗漏 | 提取结果 | 解决问题 |
| `StructuredPlanEditor` | 分区编辑强类型草稿 | 计划草稿与问题 | 更新草稿 |
| `ActivationDiffDialog` | 确认不可变版本切换 | 变更前后内容与问题 | 确认或取消 |
| `HealthMatrix` | 供应商及股票健康矩阵 | 健康数据行 | 选择股票 |

`monitor` Pinia store 管理规范化快照和事件状态，通过只读视图及明确的 `applySnapshot`、`applyEvent` 和恢复操作修改。路由内计划表单保持局部状态。`useMonitorStream`、`useSymbolFilters` 和 `useChartSeries` 封装生命周期与派生逻辑。ECharts 实例和大型不可变序列使用 shallow ref。组件使用强类型 props 和 emits，绝不直接修改共享记录。

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

- 生产命令只绑定 `127.0.0.1`；远程或局域网模式不在范围内。
- 单页应用、API 和 WebSocket 同源；生产环境关闭 CORS，并拒绝异常 HTTP 或 WebSocket Origin。
- MVP 不实现登录或身份认证。文档必须明确禁止端口转发或公开暴露。
- 设置 CSP、禁止嵌入、内容类型、Referrer 和 Permissions 等安全响应头。
- 限制请求体、文本和导入文件大小；YAML 必须安全加载。
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
- Playwright 端到端流程：配置模拟 AI 供应商、粘贴计划、提取、解决警告、启用、回放行情、接收一条提醒、确认提醒，并验证持仓未变化。
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
- AI 配置可正常使用，密钥提交后保持不可读取。
- 存在重大遗漏或验证错误时，计划不得启用。
- 一个确定性买入事件只生成一条带证据和免责声明的文本提醒。
- 界面满足键盘操作、对比度、响应式、减少动态效果和非纯颜色表达等要求。
- 正常启动路径不监听回环地址以外的网络接口。

## 待确认问题

- 无阻断问题。操作系统级浏览器通知和指定聊天平台保留为未来可选渠道。
