# 规格：monitor-index-view

> 中文审阅版。英文权威版为 `SPEC-monitor-index-view.md`；两份文档必须保持语义一致。

## 目标

在监控总览、股票详情、历史接口和失效通知中，分别投影共用板块指数事实与计划专属指数条件结果。后端保持权威；Vue 只校验并渲染返回数据。

## 命令与结构

```powershell
python -m pytest tests/integration/test_market_index_web.py tests/integration/test_websocket.py -q
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
```

```text
src/trade_plan_monitor/web/routers/market_indexes.py
src/trade_plan_monitor/web/schemas.py
src/trade_plan_monitor/web/websocket.py
web/src/components/market-index/
├── MarketIndexDataStrip.vue
├── IndexConditionProgress.vue
├── ReferenceMarketPanel.vue
└── MarketIndexChart.vue
web/src/composables/useMarketIndexSeries.ts
```

## 后端运行投影

每个截止时间，运行时先合并计划事实需求，并获取最多五份共用快照。盘中和正式收盘的多计划入口都会在逐计划判断前只合并一次；快照准备完成后，正式收盘判断仍保持串行。每只股票判断通过不可变引用获得自己的板块快照。运行时分别保存按 `indexCode` 的最新快照和按计划路径的最新证据。一个指数故障仍然可见，并且不会压制其他指数。

Schema v1 计划的 `referenceMarket=null`。没有指数叶子的 Schema v2 计划可以展示共用数据和 `conditionProgress.total=0`；共用数据缺失/故障不能改变股票判断。包含叶子的 Schema v2 计划只能根据计划哈希、快照哈希和截止时间一致的后端权威证据生成进度。

## API 契约

`DashboardResponse.marketIndexes` 是必需数组，最多五个按 `indexCode` 排序的唯一条目。数组可以为空，因此现有响应保持兼容。

`MarketIndexSnapshotView` 准确包含：

- `indexCode`、`displayName`、`board`、`closePoints`、`priorClosePoints`、`sessionChangeRatio`；
- `completedBucketAt`、`observedAt`、`health`、`issues`、`indicatorFacts`；
- `mappedSymbolCount`、`mappingVersion`、`revision`、`snapshotHash`。

点位/比例使用规范十进制字符串。`indicatorFacts` 最多 50 项，字段为 `formulaId`、类型化参数、`value`、`unit`、`sourceBarHash` 和 `formulaDefinitionHash`。共用条目禁止包含市场标签、计划 id、条件结果、`entryAllowed` 或 `decisionEffect`。

`SymbolSummaryView.referenceMarket` 和 `SymbolDetailResponse.referenceMarket` 可以为空。存在时，`SymbolReferenceMarketView` 准确包含 `indexCode`、`displayName`、`board`、`mappingVersion`、可空 `snapshotHash`、可空 `dataAt`、`health`、`issues` 和 `conditionProgress`。`IndexConditionProgressView` 包含非负 `satisfied`、`unsatisfied`、`missing` 和 `total`，前三项之和必须等于 `total`。零表示“计划未使用”，不能解释为“已满足”。

股票详情还公开按准确 `planPath` 排序的 `indexConditionEvidence`。每项都是 `IndexConditionEvidence` 的后端投影；浏览器不能把它与 K 线连接后重新计算结果。

### 指数 K 线

`GET /api/v1/market-indexes/{indexCode}/bars` 必须提供 `interval`、`startAt`、`endAt` 和 `limit`。

- `interval=FIVE_MINUTE|OFFICIAL_DAILY`；`startAt`/`endAt` 为规范 `+08:00`，边界包含。
- `limit` 范围 `1..2000`；五分钟最大查询 31 天，日线最大查询 10 年。
- 页面字段为 `items`、`limit`、`nextCursor`、`hasMore` 和 `snapshotHash`；每项经过校验并按 `barAt ASC` 排序。
- 更多数据使用现有安装级签名游标方式，绑定指数、周期、范围、排序和高水位身份。
- 未知/未批准/身份错误代码和非法游标使用现有安全错误封装，绝不暴露供应商详情。

### 失效通知

WebSocket 联合类型增加 `market.index.updated`，准确字段为 `entityId`、`revision` 和 `status`。WEBF11 通过 `0008_market_index_monitor_event` 使该已批准的失效通知经由既有监控事件账本和全局游标持久化；它不是并行序号。浏览器重新获取总览/详情/历史数据，绝不根据事件创建快照或条件结果。普通断线重连从已应用状态的游标恢复；事件缺口、心跳游标不匹配、格式错误帧或 `snapshot.required` 会在恢复前重新获取权威总览快照。ADR 0004 取代历史上的最后一句：正常缺少总览投影时使用类型化 HTTP `200` unavailable 联合，真正的服务、存储或组合故障仍为 `SERVICE_UNAVAILABLE`。

## Vue 组件图与数据流

| 组件/组合函数 | 单一职责 |
|---|---|
| `MarketIndexDataStrip.vue` | 渲染有界共用事实、截止、健康、问题、指标事实和映射股票数 |
| `IndexConditionProgress.vue` | 渲染一份计划的数量或明确“计划未使用”状态 |
| `ReferenceMarketPanel.vue` | 渲染一只股票的映射和共用快照身份 |
| `MarketIndexChart.vue` | 渲染已校验指数点位和等价文本表格；不计算策略 |
| `useMarketIndexSeries.ts` | 管理有界请求、取消、请求代次和加载/空/错误状态 |

### WEBF12 生产展示完成

- 即使多个计划引用同一份不可变快照，总览的共用指数条带也与每个自选表行的当前计划进度保持分开。
- 个股路由只能依据后端 `referenceMarket` 构造既有板块指数历史请求，使用所选股票历史范围和 `FIVE_MINUTE`，并丢弃取消或陈旧响应。禁止浏览器映射、计算指标、判断条件或推断结果。
- 详情视图分别标注共用参考事实/历史与当前计划 identity/进度/证据。加载、故障、健康、原始截止时间和缓存上下文保持可见；`conditionProgress.total=0` 显示为“计划未使用”。股票和指数图保持分开，并提供文本表格替代。
- 展示前严格传输校验覆盖参考/证据 identity、准确 `planPath` 排序和进度不变量。本次完成复用既有 REST/OpenAPI/生成 TypeScript 契约，不改变 Schema v1 数据、历史回测结果、既有 hash、token 或供应商请求边界。

路由页面继续只负责组合。只读生成类型通过类型化 props 向下传递；导航和范围变化通过类型化事件向上传递。可复用展示派生值使用 `computed`；请求使用带清理的 watcher；大型不可变序列使用 `shallowRef`。组件禁止推导板块映射、SMA、涨跌幅、条件结果、策略优先级或最终判断。

## 展示与无障碍

- 总览在连接/数据年龄状态下方显示“参考板块指数：共用数据”，股票表增加“参考指数”和“计划指数条件”列。
- 股票详情分别使用“参考指数数据”和“计划指数条件”标题。股票图和指数图保持分开。
- 刷新时可以保留缓存事实，但必须显示原始截止时间和明确刷新/健康文字。故障指数继续保留。
- 健康和结果使用文字加图标，不能只使用颜色。表格有标题；变化使用有界礼貌通知。
- 必须支持原生控件、可见焦点、键盘、200% 文本、减少动画，以及 320/768/1024/1440 响应式布局。图表提供等价表格。
- 全部文本使用转义插值；禁止 `v-html`、原始供应商文本、任意 URL 和本地路径渲染。

## 测试策略

- 后端测试证明快照去重、有界/签名历史、准确十进制/时间、安全错误、可空迁移字段、进度不变量、路径证据和失效事件。
- WEBF11 迁移/事件流测试证明 `market.index.updated` 经全局游标持久化和回放、既有行/序号/identity 保留、替换前执行行数与七列复制校验，以及存在板块指数行时在 DDL 前拒绝降级。
- Vitest 覆盖共用/计划分区、无条件文案、缓存/过期/缺口/阻断/空/加载/故障、取消竞态、键盘/表格语义以及浏览器策略函数为零。
- Playwright 覆盖两份计划共用一份快照但结果不同、一个故障板块与一个健康板块并列、无条件行为、各响应宽度，以及 axe 无严重/致命问题。

## 边界与成功标准

- 始终：显示截止和健康，分开共用事实与计划结果，并使用生成契约。
- 先确认：增加接口/字段/事件、浏览器 store、图表计算或新展示结论。
- 禁止：让 Vue 映射股票、计算指标/条件、推断交易影响、隐藏故障指数或暴露密钥。
- 用户能够把显示的计划影响追溯到准确路径和快照；没有指数叶子的计划行为不变。
