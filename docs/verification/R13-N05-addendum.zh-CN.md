# R13-N05 回测重排验收补记

日期：2026-09-13，Asia/Shanghai。任务 `01a0990a-a495-7fd1-8819-60e2adf011ab`；协调任务 `01a093fc-f8d3-73d1-b759-ad76c7451697`。无后缀英文文件为规范输入；本文件是等义中文审阅副本。

## A1. 有界结论

**N05 在已测试的离线浏览器范围内闭合。** `a4984d7458183fdb4e44d25a74648d70ef4a2b84` 最终源码通过稳定的四路由 × 四宽度 × 200% 文字边界门禁及完整 35 项 Chromium 套件。本补记只更新 N05。原 [R13 复验报告](R13-reacceptance.zh-CN.md)、[矩阵](../../remediation/R13-reacceptance-matrix.zh-CN.md) 和交接保留其准确的历史 **NOT PASSED** 结论。C6 合并检查点由协调任务判断。R14 真实供应商／用户可见验收仍为 **NOT_RUN**。

N05 未新增回测能力、监控规则、业务后端、真实供应商、收费 AI 或行情请求。

## A2. 相反的红绿观察

| 观察 | 实际结果 |
| --- | --- |
| `c6bef15ec40c7853be06030efc0e6d80be4ee87e` 上原 R13 完整浏览器门禁及有界专项重复 | 布局门禁失败；专项重复 0/5。320px 视口下，`/backtests`、`/backtests/new`、`/backtests/data` 和结果页的稳定文档宽度为 338/476/617/411px。 |
| 协调任务随后在同一未改源码上的专项运行 | 1/1 和 3/3 通过。这些观察保留为真实记录，但未记录各路由稳定宽度或计算文字字号。 |
| N05 修 CSS 前的同 fixture 诊断 | 设置 200% 根文字后立即测得四页文档宽度均为 320px；等待 `document.fonts.ready` 和两个动画帧后为 338/476/617/411px。加强后的原门禁随即在 `/backtests` 的 338px 处失败。 |
| N05 修 CSS 后的最终诊断 | 四页稳定文档宽度均为 320px；未测得脱离有意滚动祖先的溢出元素。最终门禁还在 Chrome 项目中核验计算根文字字号为 32px。 |

立即与稳定测量的分歧解释了旧的一次性门禁如何在渲染页面已变宽时仍报绿。无法追溯协调任务先前绿灯运行的准确渲染帧；将那几次运行归于此时序竞态，是基于已复现分歧的推断，不是当时捕获的事实。`openRoute` 对每个路由重新 `page.goto`，因此文字字号每页重新设置；测试使用同一 Vite 开发 harness、Chrome 项目和假 API 契约。最终门禁先观察各路由的真实 grid 样式，再应用 200% 文字，等待字体及两个渲染帧，断言计算根文字为 32px，随后对全部 16 个组合保留原 `scrollWidth <= clientWidth` 边界。未放宽阈值、宽度、文字倍率、断言或全局重试。

## A3. 最小修复与可见行为

四个回测视图及受影响的表单／结果后代现采用可收缩 grid 列。原生 input/select 在分配的轨道内定宽；eyebrow 和含 `canActivate=true` 等长串的计划版本说明可换行。视口不宽于 `30rem` 时，仅减少回测页面嵌套水平留白，使 200% 文字与控件获得可用行宽。带标签的 AppShell 导航和回测表格仍各自横向滚动。未引入全局裁切、删除字段、隐藏内容、缩小字号或降低控件高度的规则。

[对照](../../remediation/evidence/R13-N05/layout-comparison.json)、[最终测量](../../remediation/evidence/R13-N05/final-layout-measurements.json)、修前／修后原始诊断 reporter 记录及四张[最终截图](../../remediation/evidence/R13-N05/final-layout-1.png)记录了变化。诊断探针执行成功本身不计为布局断言通过；加强后的原门禁才计入。

## A4. 最终验证与边界

| 最终范围 | 实际结果 |
| --- | --- |
| `npm run test:e2e -- tests/e2e/backtests.spec.ts` | 5/5 通过：键盘操作、serious 级 axe 检查、16 个响应式／200% 组合、诊断探针、请求／DOM／轮询／ECharts 边界。 |
| 最终就绪检查后 `npm run test:e2e -- tests/e2e/backtests.spec.ts --grep "keeps 320/768/1024/1440" --repeat-each=3` | 3/3 通过；未启用 Playwright retry。 |
| 最终 `npm run test:e2e` | 35/35 通过，耗时 4.2 分钟，退出码 0。包含原文 ALL、修订、自动提醒恢复及 ACTIVE/REPLACE/DISABLE/EXPIRE 四种真实本地 OS 进程重启。 |
| `npm run test -- --run`；`npm run type-check`；`npm run build` | 45 个文件的 644/644 单测通过；类型检查与生产构建通过。 |
| 后端、真实 AI／行情／时段／渠道、R14 | 未改后端源码。先前独立 R13 后端结果仍为 2634 通过／1 项 Windows POSIX 跳过／4 项 live 排除；本任务未复跑。真实供应商与 R14 检查仍为 NOT_RUN。 |

最终浏览器运行打印了既有 Starlette/httpx 弃用警告，以及一次隔离测试进程在本地连接关闭后的 Windows Python `ConnectionResetError`。浏览器审计及完整命令仍通过；这些 stderr 行不冒充浏览器 console 错误，也未被静默删除。它们不构成回测布局失败证据。

全部 16 个受保护输入均与既有保护清单逐字节一致，包括 12 个 tracked 用户修改及 4 个 R00 untracked 文件；dashboard 原 09:35/10:35 两根 bar、第二根 `openPoints="1231.25"` hunk 保留。受保护的 AppShell、market-index、accessibility/config/规范修改、原文源文件及历史 R13 记录未暂存或编辑。未执行 reset、stash、切换分支、安装依赖、生产库／持仓／订单、外部通知、push 或发布。
