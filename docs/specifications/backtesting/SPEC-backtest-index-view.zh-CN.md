# 规格：backtest-index-view

> 中文审阅版。英文权威版为 `SPEC-backtest-index-view.md`；两份文档必须保持语义一致。

## 目标

公开并展示回测参考市场绑定、覆盖、共用指数序列、路径级条件数量、准确判断证据和正式导出身份，同时禁止编造整次运行的市场分类。浏览器代码继续只读投影后端结果。

## 命令与结构

```powershell
python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

```text
src/trade_plan_monitor/web/backtest_schemas.py
src/trade_plan_monitor/web/routers/backtest_results.py
src/trade_plan_monitor/web/backtest_export.py
web/src/components/backtests/BacktestIndexConditionSummary.vue
web/src/components/backtests/BacktestMarketIndexPanel.vue
web/src/components/market-index/MarketIndexChart.vue
web/src/composables/useMarketIndexSeries.ts
```

## API 契约

全部新增内容对旧运行均为可空/增量。现有 v1/v2 股票专属结果行、哈希、JSON、CSV 和 API 投影绝不重写。

`BacktestRunView.referenceMarket` 可以为空。对于包含指数的 Schema v2 运行，它准确包含：

- `binding`（`selection`、`mappingVersion`、`indexCode`、派生 `displayName`、派生 `board`）；
- `required`、有序唯一 `conditionPaths`、`warmupStart`、`coverageStatus` 和有序 `blockers`；
- `marketIndexDataHash`、`indexRequirementHash`、`formulaDefinitionHash` 和 `datasetHash`；
- 按 `planPath` 排序的 `conditionSummaries`。

每个 `BacktestIndexConditionSummaryView` 包含 `planPath`、`conditionType`、类型化参数、`formulaId`、`satisfiedCount`、`unsatisfiedCount`、`missingCount` 和 `applicableBranchCount`。数量是非负安全整数。任何摘要字段都不能表示整体市场强弱或自动交易影响。

`BacktestAuthoritativeDecisionView.referenceMarket` 可以为空。存在时包含 `indexCode`、`snapshotHash`、`dataAt`、`health` 以及该次判断使用的完整有序路径级 `IndexConditionEvidenceView[]`。它与判断一起持久化，读取时绝不连接到更新的数据。

### 序列资源

`GET /api/v1/backtest-runs/{runId}/market-index-series` 返回 `BacktestMarketIndexSeriesView`。

- 旧运行/无指数运行返回 `referenceMarket=null`、`items=[]` 和 `conditionSummaries=[]`，不合成历史。
- 包含指数的运行返回准确绑定/哈希身份、最多 512 个有序 `OFFICIAL_DAILY` 展示点、请求的指标事实、有界健康时间线，以及与运行资源相同的条件摘要。
- 查询接受可选规范 `startOn`、`endOn` 和 `limit=1..512`；服务端只为展示使用确定的“保留首尾”算法降采样。准确五分钟证据继续保存在分页判断明细中。
- 未知运行、证据不可用/过期、非法范围和身份不一致使用现有安全错误封装。响应保持低于 4 MiB。

### 导出与版本

包含指数叶子的 Schema v2 运行使用规范报告域 `backtest-report-v2` 和摘要导出域 `backtest-report-summary-v3`；现有报告/导出域保持不可变。正式 JSON 导出包含绑定、`marketIndexDataHash`、`indexRequirementHash`、`formulaDefinitionHash`、条件路径/数量，以及每条保留判断的快照/公式证据。成交 CSV 仍只包含成交，但其元数据身份引用运行/报告哈希。导出绝不重新计算过期明细或查询供应商。

## 新建回测与结果 UI

选择计划和股票后，新建表单显示后端确定的指数、映射版本、全部指数条件路径、派生预热和覆盖。只有使用指数叶子的计划才要求指数覆盖。浏览器不能编辑绑定或计算预热。

已完成详情增加原生链接页签“参考指数”。摘要继续把“共用指数数据”和“计划指数条件结果”作为两个区域：

- `BacktestIndexConditionSummary.vue` 渲染每条路径的结果数量和参与适用分支次数。
- `BacktestMarketIndexPanel.vue` 组合绑定/哈希身份、健康时间线、`MarketIndexChart.vue`、日期导航和条件摘要。
- 选择日期会导航到现有判断明细页面/筛选，其权威记录包含准确五分钟证据。

路由页面保持精简。生成的只读记录通过类型化 props 传递；页签/日期/筛选意图向上发送或更新 URL 权威状态。大型不可变序列使用 `shallowRef`；展示派生使用纯 `computed`；可取消获取保留在 `useMarketIndexSeries.ts`。任何 Vue 文件都不能映射股票代码、计算 SMA/涨跌幅、判断条件、根据原始判断统计数量或修改优先级。

## 无障碍与状态

- 使用一套有序标题层级、带 `aria-current` 的原生页签链接、带标签日期控件、表格标题、明确单位/截止，以及完整文本图表替代。
- `AVAILABLE`、`EXPIRED`、`NOT_RECORDED`、加载、刷新、空、缺失、缺口、过期和阻断状态使用不同文字。无指数计划显示“计划未使用指数条件”。
- 健康/结果不能只靠颜色。继续要求键盘、可见焦点、200% 文本、减少动画和 320/768/1024/1440 布局。
- 刷新时可以保留缓存序列，但必须保留原始数据集/快照身份和明确状态。绝不能把更新数据与旧结果组合。

## 测试策略

- 后端测试覆盖可空迁移、准确哈希/路径/数量、512 点限制、确定性展示降采样、保留五分钟明细、安全错误和版本化导出字节。
- Vitest 证明使用生成契约、共用/计划分区、浏览器零计算、无条件行为、全部可用性/健康状态、过期请求取消、URL 页签/日期往返、图表/表格等价和键盘语义。
- Playwright 使用离线假实现覆盖新建 → 校验覆盖 → 提交 → 完成参考指数页签 → 准确判断 → 导出；两份计划共用一个指数数据集但产生不同数量。覆盖全部批准宽度，并且 axe 无严重/致命问题。

## 边界与成功标准

- 始终：保留权威身份，在判断/导出中保留准确证据，并分开数据与计划结果。
- 先确认：增加 API 字段/端点、报告/导出域、浏览器计算或整体分类。
- 禁止：重写历史结果、推断市场标签、在 Vue 中计算策略、暴露本地/供应商密钥或重建过期证据。
- 对相同输入，监控和回测显示相同映射、截止、公式、快照和路径证据。

## 审核状态

已于 `2026-09-02` 授权实施和离线 API/Vue/Playwright 验证；提交、推送、部署、安装依赖和真实供应商访问仍未授权。
