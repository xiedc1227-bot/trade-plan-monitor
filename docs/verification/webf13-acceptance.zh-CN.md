# WEBF13 路由与新建回测验收

**状态：**`PASS`

> 中文审阅证据记录。英文权威版为 `webf13-acceptance.md`；两份文档必须保持语义一致。

## 范围与证据边界

WEBF13 记录既有真实生产路由、补齐缺失的浏览器级新建回测旅程证据，并记录后续计划工作台布局。首轮证据于 2026-09-04（Asia/Shanghai）收集。环境为 Windows、CPython 3.14.7、Node 24.13.1、npm 11.8.0，以及锁定的 Playwright 1.62.1 Chromium 项目。

临时的 WEBF13 Dashboard-503 Health-fallback 切片仅具历史意义，已由 `SPEC-live-production-chain`、ADR 0004 和 `live-production-chain-acceptance.md` 取代。本记录不声称当前投影可用性验收。

## 路由证据

必需路由地图为：`/`、`/stocks/:symbol`、`/plans`、`/plans/:id`、`/alerts`、`/system`、`/backtests`、`/backtests/new`、`/backtests/data` 和 `/backtests/:runId`。曾经的五个占位路由 `/`、`/stocks/:symbol`、`/plans/:id`、`/alerts` 和 `/system` 必须解析到真实惰性 SFC Route View；静态回测子路由必须位于 `:runId` 之前。

- `rg -n "createRoutePlaceholder" web/src` 未找到引用。
- `BacktestRouter.spec.ts` 固定精确且有序的 10 路由表面，并逐一惰性加载五条曾经的占位路由、既有计划工作台和四条回测视图。其聚焦运行通过 `12 tests`。
- 完整确定性浏览器套件通过 `20 tests`。既有生产 Router 旅程覆盖 `/`、`/stocks/:symbol`、`/plans/:id` 和 `/alerts`；新增 `/system` 路由用例经过真实 Router 和 `GET /api/v1/health`，断言路由标题/一级标题，并且没有控制台、失败请求、未预期 API 或外部请求问题。

## 计划工作台布局证据

计划页面在持久版本工作区之前展示一个紧凑创建区。结构化 JSON/YAML 导入和可选 AI 提取作为互斥可见的创建方式，不再把两套完整流程纵向堆叠。切换方式会保留未完成的本地输入；解析、校验、草稿创建、激活资格和生命周期判断继续由后端权威负责。

- 初始 RED：聚焦 Vue 测试因不存在创建方式控件和隔离面板而失败。GREEN 增加可访问 tablist，将 AI 提取置于首位并默认选中，通过 `v-show` 保留未完成输入，并支持 Left/Right/Home/End 键盘选择。
- 浏览器 RED 在桌面 fixture 中测得导入面板高 `698 px`，持久版本工作区宽仅 `894 px`。GREEN 将导入面板保持在 `400 px` 以下，并让两个主要区域均超过路由宽度的 `90%`，且不改变请求 payload 或后端调用。
- 响应式 RED 在 `320 px` 视口发现 `81 px` 横向溢出。最终浏览器闸门在 `320`、`768`、`1024`、`1440 px` 均无路由级横向溢出；窄屏标题/操作纵向排列，技术枚举值允许断行，创建控件保持键盘可访问。计划旅程的 WCAG 2.1 A/AA 严重/致命 axe 结果为空。

## 历史可用性说明

临时的 WEBF13 Dashboard-503 Health fallback 已被 live-production-chain 的类型化可用性契约取代。其旧浏览器观察不再构成当前验收证据；新结果只记录在 `live-production-chain-acceptance.md`。

## 新建回测旅程证据

必需的确定性浏览器链路为：选择后端列出的不可变计划版本和已校验数据集；提交一个幂等运行命令；导航至 `/backtests/:runId?jobId=<jobId>`；轮询匹配的 `BACKTEST_RUN` 任务；仅在 `COMPLETED` 后移除 `jobId`；然后渲染 materialized 结果。失败或取消的任务保留其任务 identity，绝不伪造结果。

- 初始 RED：新的聚焦 Chromium 测试失败 `1 test`，因为 fake 契约尚未接受 `POST /api/v1/backtest-runs`；URL 按预期保留在 `/backtests/new`。
- GREEN：确定性 fake 现在返回精确的 `202`、`Location` 和 `Retry-After: 2` 契约。浏览器测试断言准确的生成请求体、JSON Content Type、单个有界幂等键、导航到匹配的 `runId`/`jobId`、首个后端权威 `RUNNING` 任务、两次不重叠轮询、仅在 `COMPLETED` 后规范移除 `jobId`，以及最终 materialized 结果视图。聚焦测试通过 `1 test`，受影响的双文件浏览器闸门通过 `8 tests`，最终完整浏览器闸门通过 `20 tests`。
- 后端 production-fake 节点 `test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged` 另行以 `1 test` 通过 `sync → verify → submit → poll → result → pin → export`，且实时状态不变。更广的聚焦 API/组合集合通过 `284 tests`，在 Windows 上跳过一个仅适用于 POSIX ownership 的用例，并且只产生既有 Starlette `TestClient`/httpx2 弃用 warning。

## 契约证据

冻结契约继续精确包含 42 条 REST 路径：27 条实时路径和 15 条回测路径。`openapi.json` 和 `web/src/api/generated.ts` 必须同时保持最新；WEBF13 不得产生契约差异。

- `openapi.json` 精确包含 `42` 条路径。`tests/integration/test_openapi_snapshot.py` 通过 `14 tests`。
- `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` 报告 `OpenAPI snapshot and frontend types are current`。
- `openapi.json` 与 `web/src/api/generated.ts` 均不在差异中。

## 安全与隔离证据

浏览器使用生成契约校验，后端继续是计划资格/快照、数据集覆盖、运行 identity、任务状态和 materialized 结果的权威。验证必须使用确定性本地 fixture：不允许读取 token、请求供应商、调用券商、投递通知或访问外部网络。

- 所有浏览器 API 均由确定性同源 fake 拦截。回测与系统路由审计没有记录未预期请求、外部请求、失败请求、API 失败、控制台 warning/error 或请求重叠。临时的 Dashboard-503 可用性审计已由 live-production-chain 契约取代，不再构成当前验收证据。
- 未读取任何 `.env` 或凭据值，未打印或返回 token，也未请求 Tushare、DeepSeek、券商、通知或其他供应商。
- Vue 只提交带 `planVersionId` 的生成 `BacktestRunCommand`；它不发送计划快照，也不判断计划资格、数据集、任务完成或结果可用性。既有后端集成证据继续作为这些判断的权威。

## 必需离线命令

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest tests/unit/test_backtest_api_schemas.py tests/unit/test_backtest_api_pagination.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_openapi_snapshot.py -q -rs
.\.venv\Scripts\python.exe -m pytest tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged -q
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

结果：历史 WEBF13 结果仍仅覆盖原始路由与回测范围。被取代的可用性后续工作不增加当前结果计数；live-production-chain 证据只记录在 `live-production-chain-acceptance.md`。历史 Schema v1 数据、回测结果和哈希保持不变。

## 遗留风险

- 确定性 fake 验收不能证明真实 Tushare、DeepSeek、券商或其他供应商的可用性/语义；它们继续使用单独授权闸门。
- Windows 运行会跳过 POSIX 文件 ownership 用例，不能替代该平台专属证据。
- 本布局切片没有重新运行手工 NVDA 或全新性能 profiling；自动键盘、响应式和 axe 证据不能替代这些单独的手工闸门。
