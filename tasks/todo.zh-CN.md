# 任务清单：market-index-context

> 中文审阅任务清单。英文权威版为 `todo.md`；ID、文件、命令和验收标准必须一致。

## 基础

- [x] `IDX001`——实现封闭板块指数身份映射。
  - 验收：五条映射和所有非法/回退场景均确定；绑定不可变且可重新计算。
  - 验证：`python -m pytest tests/unit/test_market_index_identity.py -q`。
  - 文件：`tests/unit/test_market_index_identity.py`、`src/trade_plan_monitor/market_index/identity.py`、`src/trade_plan_monitor/market_index/__init__.py`。
- [x] `IDX002`——实现指数 K 线、规范哈希、公式和健康状态。
  - 验收：准确完整周期校验、SMA/回看/涨跌幅黄金值、问题代码和内容哈希符合规格。
  - 验证：`python -m pytest tests/unit/test_market_index_data.py -q`。
  - 文件：`tests/unit/test_market_index_data.py`、`market_index/models.py`、`market_index/canonical.py`、`market_index/formulas.py`。
- [x] `IDX003`——实现供应商边界和共用截止时间快照协调器。
  - 验收：合并请求只获取一次；相同并发键共用；板块故障隔离；不泄露供应商密钥。
  - 验证：`python -m pytest tests/integration/test_market_index_snapshots.py -q`。
  - 文件：`tests/integration/test_market_index_snapshots.py`、`market_index/provider.py`、`market_index/requirements.py`、`market_index/snapshots.py`。

## 计划判断

- [x] `IDX004`——增加明确 Schema v2 绑定和六种条件模型。
  - 验收：v1 拒绝新字段/叶子且哈希不漂移；v2 要求重算绑定和准确范围。
  - 验证：`python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py -q`。
  - 文件：`tests/unit/test_plan_index_conditions.py`、`domain/plan_models.py`、`domain/plan_validation.py`、`domain/plan_codec.py`。
- [x] `IDX005`——使用准确计划路径和缺失证据判断指数叶子。
  - 验收：等号、全部策略根、三值组合、两计划分歧和无条件行为通过。
  - 验证：`python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q`。
  - 文件：`decision/models.py`、`decision/conditions.py`、`decision/episodes.py`、`decision/risk.py`、`tests/unit/test_plan_index_conditions.py`。

## 监控

- [x] `IDX006`——把共用快照注入实时判断，并分开保存最新共用/计划投影。
  - 验收：每个截止/指数一份快照、无条件故障隔离和运行证据持久化通过。
  - 验证：`python -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_ten_symbol_runtime.py -q`。
  - 文件：`tests/integration/test_market_index_runtime.py`、`runtime/service.py`、`runtime/symbol_service.py`、`web/lifespan.py`。
- [x] `IDX007`——增加监控 API、历史端点、失效通知、OpenAPI 和生成类型。
  - 验收：有界安全 Schema/端点/事件和可空迁移字段通过契约测试。
  - 验证：`python -m pytest tests/integration/test_market_index_web.py tests/integration/test_openapi_snapshot.py tests/integration/test_websocket.py -q`；`python scripts/generate_frontend_types.py --check`。
  - 文件：`web/schemas.py`、`web/routers/market_indexes.py`、`web/app.py`、`web/websocket.py`、生成契约/测试。
- [x] `IDX008`——测试先行增加监控 Vue 组件和序列组合函数。
  - 验收：共用数据和计划结果明显分开；加载/故障/未使用/键盘/响应式状态通过。
  - 验证：`npm --prefix web run type-check`；`npm --prefix web run test -- --run`。
  - 文件：`web/src/components/market-index/*`、`web/src/composables/useMarketIndexSeries.ts`、总览/详情页面、单元测试。

## 回测

- [x] `IDX009`——增加 v2 指数 artifact、动态覆盖/预热、共用回放快照和 v3 运行身份。
  - 验收：禁止未来数据、实时/回放字节一致、旧黄金值不变、无条件覆盖隔离、零网络。
  - 验证：`python -m pytest tests/unit/test_backtest_index_data.py tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q`。
  - 文件：`backtest/index_data.py`、`backtest/dataset.py`、`backtest/market_store.py`、`backtest/runner.py`、测试。
- [x] `IDX010`——持久化/投影回测指数证据，增加序列 API，并版本化正式导出。
  - 验收：旧运行可空、准确身份/数量、512 点限制、保留明细和稳定导出通过。
  - 验证：`python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q`；OpenAPI 检查。
  - 文件：`backtest/results.py`、`web/backtest_schemas.py`、`web/routers/backtest_results.py`、`web/backtest_export.py`、测试/生成契约。
- [x] `IDX011`——测试先行增加回测指数表单/摘要/页签组件。
  - 验收：后端覆盖只读、摘要/路径身份一致、全部可用状态和无障碍通过。
  - 验证：`npm --prefix web run type-check`；`npm --prefix web run test -- --run`；聚焦 Playwright。
  - 文件：回测指数组件/组合函数、新建/详情页面、API 适配器、单元/E2E 测试。

## 完成

- [x] `IDX012`——完成配对 README/API/测试报告并运行全部离线门禁。
  - 验收：双语一致、记录供应商限制、完整文件/测试/风险报告、密钥扫描干净、全部必需门禁通过。
  - 验证：`tasks/plan.md` 中全部命令、`git diff --check`、`git status --short`。
  - 文件：`README.md`、`README.zh-CN.md`、`docs/README*`、配对验证报告、`openapi.json`、生成 TypeScript。
