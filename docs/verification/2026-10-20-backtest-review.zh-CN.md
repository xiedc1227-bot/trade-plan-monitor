# 回测结果审阅验证 — 2026-10-20

## BR-V01. 交付范围

完成 [BR01–BR06](../specifications/backtesting/SPEC-backtest-review.zh-CN.md) 和 [BT-R01–BT-R03](../../tasks/backtest-review.zh-CN.md)：紧凑概览／成交、独立未成交原因与来源区域、精确成交／事件／序号选择、展示记录中要求与实际依据的原因／后续面板、签名有界关系分页、已访问游标上一页、URL 历史、请求取消及键盘焦点。最终紧凑表格为 7 列，按需展开回执／审计详情。

派生 `backtest_review_event` 索引与规范明细在同一事务暂存，跟随明细删除，兼容缺少索引的旧存储。不重写已有规范载荷和报告／集合哈希。旧运行显式维护使用保留中的已验证记录。明细可用性、索引就绪状态及已知缺失关联分别表达。不生成新 AI 解释或逐笔盈亏。

## BR-V02. 自动检查

下列命令按需从项目根目录或 `web/` 执行，使用隔离夹具。保留已有无关费用展示改动。

| 检查 | 结果 |
|---|---|
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py tests/integration/test_backtest_migrations.py tests/integration/test_monitor_loop_contract.py tests/integration/test_backtest_result_api.py -q` | 120 项通过 |
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py tests/integration/test_monitor_loop_retention.py tests/integration/test_monitor_loop_publication.py -q` | 36 项通过；与上一组重叠 12 项审阅测试 |
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py -k exact_sequence -q` | 1 项通过、11 项未选择；HTTP 读取前后 SQLite `PRAGMA data_version` 保持不变 |
| `npm exec -- vitest run` | 80 个文件、1188 项通过 |
| `npm exec -- vitest run tests/unit/BacktestReview.spec.ts tests/unit/BacktestResultTables.spec.ts` | 最终表格布局调整后，22 项通过 |
| `npm run type-check` | 通过 |
| `npm run build` | 通过；Vite 已同步打包的 SPA 资源 |
| `.venv/Scripts/python scripts/generate_frontend_types.py --check` | 两份 OpenAPI 文档及生成客户端均为当前版本 |
| 对修改的后端模块／测试／脚本运行 Ruff；`git diff --check` | 通过 |

已发布 API 夹具包含 982 条事件。测试直接定位末条序号、每页 1 条追溯真实原因、拒绝签名游标上下文错配及无效查询、明细过期后保留成交（包括关系分页期间过期）、拒绝索引／哈希篡改、重新打开旧／新结构，并对比维护前后规范载荷字节。查询计划使用身份与原因索引，无整表扫描。

环境需要在沙箱外运行本地测试，才能创建不可变证据文件硬链接及重命名临时编译缓存。既有 Starlette TestClient 弃用和 Node 颜色环境警告未导致失败。首轮完整浏览器回归发现两条旧断言仍在原汇总页查找来源信息；同步导航后整组通过。

## BR-V03. 真实浏览器检查

使用固定本地 Chrome 执行：

- `npm exec -- playwright test tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/plan-execution-diagnostics.spec.ts`：6 项通过，包含实际上传／审核／发布、自动准备、四份计划连续会计及代表性诊断。
- `npm exec -- playwright test tests/e2e/backtests.spec.ts --grep "covers the four backtest routes|keeps 320/768|enforces request" --output .pytest_cache/review-legacy-browser`：3 项通过，覆盖历史路由、键盘／axe、响应式／文字缩放、请求／DOM／轮询／ECharts 上限。
- `npm exec -- playwright test tests/e2e/monitor-loop-backtest.spec.ts --grep "real upload/retry/edit/review/run" --output .pytest_cache/review-final-browser`：最终调整为 7 列后，重复验证 1 项通过。

已检查 320/768/1024/1440px，页面无水平溢出，选择 URL、浏览器后退、原因／后续控件、诊断回车操作、标题焦点及关闭后焦点恢复均有效。axe 在结果流程中未报告严重／重大 WCAG 违规，独立诊断检查未报告所选规则违规。浏览器套件检查了控制台／页面错误。已目视复核桌面／移动端截图，并保存在当前会话的可视化产物中。

## BR-V04. 实际边界

缺少查询元数据的旧运行需要显式[维护步骤](../operations/backtest-review.zh-CN.md)，原读取器仍可使用。全运行日期／计划／原因筛选、图表联动和经验证的单笔盈亏属于 BR06 后续范围。浏览器证据来自确定性的隔离数据库，不是生产数据库迁移。未进行主持式用户计时研究或 10000 条事件性能基准；已验证有界查询契约和索引查询计划。
