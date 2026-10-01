# 界面设计验证 — 2026-10-01

## 范围与结果

依据[设计契约](../specifications/monitoring/SPEC-interface-design.zh-CN.md)中的 `UI01`–`UI08`，优化已安装的 monitor-contract `2` 界面及共用的兼容组件。已检查状态中没有剩余的明显可处理布局或交互缺陷。奖项认可仍属于主观评价。

采用暖墨色、矿物白文字、琥珀色操作、原创阈值标志、编号导航与等宽数字。监控事实、市场背景、操作和诊断具有不同层级。路由、REST/WebSocket 契约、供应商权威来源、监控规则、来源日期、启用/审核边界及人工交易决策保持不变。

## 八维自检

| 维度 | 实现与最终检查 |
|---|---|
| 排版 | 共用页面引导区、响应式 30–44px 标题、较小的辅助文字和一致的数字字体；检查中文与长诊断文字。 |
| 留白 | 统一页面边距、4px 间距节奏、对齐的分隔线、受控面板内边距与桌面双列诊断；移除重复页面内边距。 |
| 视觉层级 | 快照统计位于工作区之前；宽屏分开市场与监控状态，窄屏先显示监控状态；空计划提供明确的下一步操作。 |
| 色彩 | 语义化琥珀/绿/红/青色，状态保留文字含义；已测试路由与状态通过 WCAG 2.1 A/AA 自动检查，包括新版总览的 200% 文字缩放。 |
| 动效 | 克制的 360ms 入场位移和 160ms 控件反馈；减少动效偏好关闭非必要运动；移除导致瞬时对比度下降的透明度入场效果。 |
| 微交互 | 明确的导航/指数选中态、悬停与按压反馈、可见焦点；Escape 关闭移动导航并恢复按钮焦点，下一次 Tab 到达主要操作。 |
| 响应式 | 验证 320/768/1024/1440px 和 100%/200% 文字缩放，页面无横向溢出；表格保留局部滚动，图表容器约束画布尺寸调整。 |
| 原创性 | 自定义阈值标志、PLAN / MONITOR 视觉、编号导航、有目的的监控结构和空计划插图；没有复制素材或虚构数据。 |

## 验证结果

从 `web/` 运行：

| 检查 | 结果 |
|---|---|
| `npm run type-check` | 通过 |
| `npm test -- --run` | 提交前最终回归：820 项测试、58 个文件通过 |
| `npm run build` | 通过，已刷新安装资源 |
| `npm run build:runtime-status-preview` | 通过 |
| `npx playwright test tests/e2e/accessibility.spec.ts tests/e2e/dashboard.spec.ts tests/e2e/plans.spec.ts tests/e2e/alerts.spec.ts tests/e2e/backtests.spec.ts tests/e2e/interface-design.spec.ts` | 提交前最终回归：20 项测试通过，36.0s |
| `npx playwright test tests/e2e/runtime-status-sqlite.spec.ts tests/e2e/runtime-recovery.spec.ts` | 2 项测试通过，约 4.4 分钟 |
| `git diff --check` | 通过 |

两项真实运行检查使用独立、受控的 Python 运行时与 SQLite，覆盖提醒来源日期、真实协调器停滞及正常安装入口的重启恢复。它们在后续展示与计划页启动调整之前运行；最终单元、类型、构建和 20 项浏览器检查覆盖了这些调整。保留已有阈值和断言，标题与色彩预期同步为本次设计。新增新版检查覆盖空/活动计划、四个断点、200% 文字、完整 WCAG A/AA 检查、键盘焦点及减少动效。

## 视觉证据

检查既有本地服务 `http://127.0.0.1:8765/` 提供的生产构建：总览、计划、提醒、系统与回测。浏览器截图保存在 [assets/interface-design](assets/interface-design/)：

- [桌面总览](assets/interface-design/dashboard-desktop.jpg)
- [手机总览](assets/interface-design/dashboard-mobile.jpg)
- [手机下部内容](assets/interface-design/dashboard-mobile-market.jpg)
- [平板状态与市场细节](assets/interface-design/dashboard-tablet.jpg)
- [计划工作台](assets/interface-design/plans-desktop.jpg)
- [提醒中心](assets/interface-design/alerts-desktop.jpg)
- [系统诊断](assets/interface-design/system-desktop.jpg)
- [回测工作台](assets/interface-design/backtests-desktop.jpg)

## 迭代与边界

后续框体对齐：宽屏工作区通过共享网格行，让监控面板从指数标题下方的指数框体顶部开始。这依据 [MDN subgrid 指南](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Grid_layout/Subgrid)，避免文字换行时依赖固定偏移。窄屏保留监控状态优先排列。`interface-design.spec.ts` 两项检查在 4.8s 内通过，覆盖空/活动计划、320/768/1024/1440px、100%/200% 文字、宽屏框体顶部差小于 1px 及 WCAG A/AA 检查。`npm run build` 通过。更新截图：[框体对齐](assets/interface-design/dashboard-aligned.jpg)。

后续指数栏滚动修正：移除不必要的 `overflow-x: auto`，该设置同时使垂直溢出变成 `auto`。四列/两列指数网格无需内部滚动容器，长标签与数值允许换行。新增浏览器回归检查 320px/1440px 下的焦点、持续按压反馈、无垂直滚动容器和正常指数切换。回归断言在原有垂直溢出设置下失败，修复后通过。总览与界面浏览器测试共 7 项在 8.4s 内通过，类型检查与生产构建通过。截图：[无内部滚动的指数栏](assets/interface-design/dashboard-selector-no-scroll.jpg)。

后续成交额操作布局：将走势错误文字与重试按钮移到预测全天成交额旁边。条件性展示类仅在操作插槽存在时增加操作列，40rem 以下将操作排列在数值下方。相关单元检查 23 项通过，总览/界面浏览器检查 7 项在 8.1s 内通过；类型、生产构建及 diff 检查通过。实际错误状态确认操作区位于预测值右侧，间距 24px，垂直边界一致。截图：[右侧成交额操作](assets/interface-design/dashboard-turnover-actions.jpg)。

后续走势图边框统一：移除走势卡片左侧的状态色边框及按健康状态覆盖边框颜色的样式。四周统一由指数外框提供中性细边框，已在实际浏览器中确认。状态标签保留现有语义。市场指数单元检查 21 项、生产构建及 diff 检查通过。截图：[统一走势图边框](assets/interface-design/dashboard-uniform-border.jpg)。

后续计划页启动（`UI08`）：`PlanWorkbench` 的渲染独立于 AI 配置请求，进度仅展示在供应商面板内。提前填写的原文可编辑，请求成功后在同一个编辑器中保留；配置失败时也保留工作区与原文。具备已启用且已配置的供应商后才允许提交，并重新检查实际供应商的长度限制，不丢弃提前填写的原文。回归断言复现了原有等待/失败状态下工作区缺失的问题。相关单元测试 37 项、计划浏览器流程 3 项（7.8s）、类型检查、生产构建及 diff 检查通过。延迟响应浏览器检查覆盖 1440px/320px，确认不会自动发送修改请求；改善截图取景后再次在 2.1s 内通过。截图：[独立浏览器中的配置等待状态](assets/interface-design/plans-config-loading.jpg)、[已安装的本地计划工作区](assets/interface-design/plans-immediate-live.jpg)。

修正 200% 文字下的 320px/768px 顶部溢出、总览导航选中范围过宽、入场瞬时对比度、重复页面边距、竞争性计划标题、不清晰的空图表展示和窄屏监控优先级。最终入口检查还复现了首次加载总览标题缺失：同时观察路由标题与路径，修正启动行为，并保留仅查询参数变化时的焦点行为。回归断言在修复前失败，修复后通过。随后重跑受影响检查及最终回归批次。

本地服务当时没有活动计划，也没有可用的当日日内指数序列。截图展示真实已存点位、原始截止时间、序列不可用说明与重试控件，没有添加装饰曲线或替代市场数据。活动计划与图表序列另用确定性样例验证，提醒/来源/恢复行为通过独立真实运行时验证。截图属于时点检查，自动 axe 检查不等同于完整辅助技术审计。

本次设计变更没有新增依赖、修改后端、提交生产计划、发送外部 AI 请求或部署。按用户要求，Git 交付将修改分为工作台/市场展示与计划页启动体验两次提交，附中英配套设计与验证文档及截图。提交前审查没有发现必须修正的正确性、安全或性能问题；提交前远端分支与本地基线一致。
