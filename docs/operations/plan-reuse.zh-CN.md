# 已审核计划复用

## PR-O01. 工作台来源

打开**回测 → 新建回测 → 工作台已审核计划**，选择准确的已审核版本。计划可以未启用；未审核草稿不可选。选择计划不会调用 AI 或启动运行，需要时可核对原文。

确认生效交易日、历史可用时间（可选，默认该日09:30）、信息截止时间、期初持仓时间、库存是否已知，以及核对依据或明确研究假设。这些日期描述研究假设，不是计划历史发布证明。库存未知继续保持未知并阻止模拟交易；有依据时才选择已核对空仓。已知批次使用 CORE/TACTICAL 分仓和100股单位数量，可选填元单位总成本、取得日期及可卖数量。未知事实留空。资金使用 `POSITION_LIMIT_ONLY`，无现金预算，不读取实时持仓。

确认一次研究上下文后，设置响应、费用及可选结束日期，开始回测。复用现有历史数据自动准备及监测循环。`FOLLOW_REMINDERS` 模拟满足条件的操作，`OBSERVE_ONLY` 不产生成交，现有阻断和执行规则继续生效。含 `selectionId` 的链接可恢复冻结上下文，之后工作台编辑或启用状态变化不会改变它。保存或提交结果不确定时，使用页面提供的同一请求重试，保留原 key／请求体。

## PR-O02. 已有准备计划与结果

次级**回测已审核计划与原文准备**入口保留现有计划库、原文准备、提取／审核、未完成准备恢复及多计划连续回测，当前链条上限为256项。首期每次运行使用一个工作台版本，不支持跨来源混合或多个工作台版本日程。两套计划存储保留当前编写／审核职责。

已有 `preparationId` 链接、历史结果链接、明细及导出继续可用。新增工作台结果展示真实计划版本／审核及冻结研究选择。已接受运行拥有复制输入，执行及结果读取不再依赖任一来源计划存储。删除当前 JSON/YAML 计划导入：`POST /api/v1/plan-imports` 返回404，直接客户端／表单同步移除。内部编解码和原文准备继续支持。

## PR-O03. 存储及运维边界

首次使用准备存储时，带标记 schema 1 通过事务升级到2，仅增加 `backtest_plan_selection`。原准备文档和幂等回执保留准确字节。测试不会修改生产数据库。旧程序会拒绝升级后的存储；如果部署后可能回退程序，应事先保留一致数据库备份。不增加监控／行情／结果 SQL 迁移、供应商、依赖、工作线程所有者或并发上限。

新增复制输入使用 `monitor-loop-stored-input-v3`，其绑定选择的输入使用 `workbench-loop-input-v1` 和既有 `backtest-run-v5` 执行公式。既有输入／报告编解码、哈希、导出及准备链语义保持不变。准确契约及实际检查见[设计](../specifications/backtesting/SPEC-plan-reuse-unification.zh-CN.md)及[验证记录](../verification/2026-10-19-plan-reuse-unification.zh-CN.md)。

## PR-O04. 可复现的浏览器验证

浏览器测试使用隔离 Chrome for Testing `157.0.8103.6`，版本固定在 `web/test-browser.json`。此版本包含 Chromium 在 main revision `1712735` 的[完整 no-store 响应修复](https://chromium-review.googlesource.com/c/chromium/src/+/8508456)，所选构建 revision 为 `1717349`。系统 Chrome `155.0.8059.80` 会把已完整读取的响应报告为 `net::ERR_ABORTED`，无需修改应用请求处理或过滤这些事件。

从项目根目录先准备一次测试浏览器，再执行检查：

```powershell
.venv/Scripts/python.exe scripts/setup_test_browser.py
npm --prefix web run test:e2e -- tests/e2e/streamCompletion.spec.ts
npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts
```

Python 已在 PATH 时，`npm --prefix web run setup:test-browser` 等价。安装脚本从官方地址下载准确版本到已忽略的 `web/.test-browsers/157.0.8103.6/` 缓存，并复用完整安装。它不安装／更新系统 Chrome，普通测试运行也不会下载文件。浏览器缺失时直接提示准备命令，不静默回退到受影响版本。Chrome for Testing 属于开发验证前提，不是产品运行依赖。

现有 Chrome 项目、视口、断言、5秒期望超时及零重试保持不变。新增回归要求1000次完整流读取且无失败请求，检查单独到达的响应结束，并确认真实调用方取消仍产生失败请求。取消审计结果见验证报告 PR-V05，后续窄屏布局修复见 PR-V06。
