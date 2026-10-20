# 回测创建体验验证 — 2026-10-20

## BC-V01 范围

契约：[SPEC-backtest-creation-ux](../specifications/backtesting/SPEC-backtest-creation-ux.zh-CN.md)。实施保留默认工作台来源和现有准备、审核、提交规则，增加元数据搜索、紧凑时间线条目、显式新建/更新准备区、已选路径定位与焦点，以及折叠生效日期明细的紧凑回测设置。保留已有结果审阅和费用默认值改动。

## BC-V02 自动检查

- `npm run test -- --run`：80 个文件、1192 项测试通过。最终账户摘要排版调整后，`MonitorLoopRunForm.spec.ts`、`BacktestAccessibility.spec.ts`、`BacktestServiceState.spec.ts` 和 `PlanPreparationReview.spec.ts` 中的 113 项相关测试再次通过。
- `npm run type-check` 和 `npm run build`：通过，已更新本地打包的网页资源。
- `npm run test:e2e -- tests/e2e/plan-library-versions.spec.ts tests/e2e/monitor-loop-backtest.spec.ts`：完整执行与针对性复验累计验证 9 条不同的 Chrome 流程。完整执行通过 7 条；修正取消期间原文应保持可见锁定的旧断言，以及测试页面缺少网页标题的问题。针对性复验的全部 6 条流程通过，包含上述两项。
- 覆盖：键盘搜索/清除/定位；30 条时间线分页并保留选择身份；8 份记录保留为 2 条独立链；读取失败重试与旧结果保留；显式进入/收起准备区与脏草稿锁定；上传/编辑/审核/回测；取消及恢复未结束任务；自动补齐数据；4 次连续已审核更新使用同一账户与运行；提取前必须确认日期；历史只读查看。
- `git diff --check`：通过。双语章节/任务 ID、行内技术值和勾选状态已核对一致。

## BC-V03 真实页面浏览器证据

使用新的隔离 Chrome 上下文打开 `http://127.0.0.1:8765/backtests/new`。页面加载 2 条时间线和 8 份已审核计划。初始时间线模式不显示未使用的原文表单。选择末端后聚焦回测设置区；更新后聚焦原文标题；收起未修改的准备区后，焦点返回新建时间线入口。

计划库和最终设置页均在 320/768/1024/1440px 宽度与 200% 文字下核查，各情况下文档宽度均等于视口宽度。Axe 对 `wcag2a`、`wcag2aa`、`wcag21aa` 的检查没有发现违规项。真实页面的 axe 检查使用浏览器运行时求值，未改变页面 CSP。

生效日期明细初始折叠，通过键盘可展开 4 条记录。佣金和结束日期草稿仍可编辑。真实页面核验没有非 GET/HEAD 请求，也没有页面异常；未提交原文、准备或运行。创建与回放的写入测试使用隔离的测试存储。

截图：

- [时间线选择](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-creation-updated.png)
- [回测设置](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-creation-settings.png)

## BC-V04 限制

此记录是 UI 与本地浏览器验收，不证明真实 AI/行情服务可用，也不包含人工读屏验证。真实历史证据说明当前加载的已审核记录仍可读取，不代表重建了所有历史记录的完整取证过程。本次创建页改动没有增加后端或数据库迁移。
