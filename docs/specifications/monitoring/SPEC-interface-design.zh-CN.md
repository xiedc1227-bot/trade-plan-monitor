# 界面设计契约

## 范围

`UI01`：优化已安装的 monitor-contract `2` 界面，以及兼容界面共用的外壳、市场组件与控件。保留所有路由、REST/WebSocket 字段、权威来源、有效期限与用户命令边界。这是展示层变更；无需供应商请求、生产数据变更、部署或新增依赖。

## 方向与参考

采用原创的精密工作台视觉：暖墨色表面、矿物白文字、琥珀色操作、克制的海玻璃绿与朱红状态色、自定义阈值标志、等宽数字和编号导航。总览优先展示监控事实。

- [Terminal Industries / Awwwards](https://www.awwwards.com/sites/terminal-industries)：参考统一的技术视觉与明确层级，不复制布局或素材。
- [Google Fonts](https://fonts.google.com/) 与 [Webby Best User Interface](https://winners.webbyawards.com/winners/websites-and-mobile-sites/features-design/best-user-interface)：参考易读排版、结构化控件与浏览顺序。
- [FWA](https://thefwa.com/)：创意品质参考。奖项是品质标杆，不代表本次实现获得认证。Awwwards/FWA 的实时视觉访问受限，不声称已完成全面参考审计。

## 组件边界

| 组件 | 职责 | 契约 |
|---|---|---|
| `AppShell.vue` | 品牌、导航、连接提示和路由焦点 | 既有路由/连接状态与插槽 |
| `PageIntro.vue` | 一致的页面层级 | `title`、`eyebrow`、`description`；操作插槽 |
| `runtime-status` 中的 `DashboardView.vue` | 组合当前事实、市场、状态与活动计划 | 既有运行时上下文，不计算策略 |
| `OverviewStatus.vue` | 区分传输确定性与监控就绪状态 | 既有只读 status/live 属性 |
| `PlanDraftingView.vue`、`PlanWorkbench.vue` | 独立于配置加载，组合 AI 审核工作区 | `runtimeLoading` 控制依赖配置的操作，保留提前输入的原文 |
| `AIProviderSelector.vue`、`SourceTextEditor.vue` | 展示局部配置进度，分开编辑与提交资格 | `loading`、`submitDisabled`，既有选择/输入事件 |
| `MarketIndexDataStrip.vue` 与市场卡片 | 选择并展示权威市场事实 | 既有属性/事件不变 |
| `tokens.css`、`runtime.css` | 共用排版、色彩、控件、动效与响应式布局 | 语义令牌，无远程资源 |

## 验收标准

- `UI02` 排版与留白：一个明确的页面标题、易读辅助文字、等宽数字与 4px 间距节奏，突出主要事实。
- `UI03` 层级与色彩：区分操作、事实、诊断、不可用/缓存状态。普通文字对比度至少 4.5:1，大字至少 3:1。状态始终附带文字。
- `UI04` 动效与微交互：克制的入场、悬停与按压反馈，明确的键盘焦点，可用的移动导航与 Escape 操作。`prefers-reduced-motion` 关闭非必要运动。不劫持滚动，不使用装饰性的实时数据动画。
- `UI05` 响应式：检查 320px、768px、1024px 和 1440px。页面无横向溢出，密集表格可局部滚动。移动控件保持可用，目标尺寸 44px。宽屏工作区中，监控面板顶部与指数标题下方的实际指数框体对齐；窄屏保持监控状态优先的纵向排列。空间允许时，将走势错误文字与重试放在预测全天成交额右侧，小屏幕纵向排列在下方；没有操作插槽时不预留操作列。
- `UI06` 原创性：自定义品牌标志、编号导航与有目的的总览结构；不用模板首屏、虚构指标、复制图片或通用渐变/卡片网格。
- `UI07` 验证：类型检查、单元测试、生产构建、相关浏览器流程与 axe 检查；视觉检查总览、计划、提醒、系统和回测。在配套中英验证报告中记录真实结果与限制。
- `UI08` 计划页启动：配置响应前显示 AI 审核标题、原文编辑器与审核区域。允许提前填写原文，具备已配置且启用的供应商后才开放提交；配置返回或失败时保留已填原文。提交前应用实际供应商的原文长度限制，配置错误保持可见，不能自动触发提取。

## 迭代规则

首个可用增量完成后，检查用户要求的八个维度。修复截图或测试发现的具体问题，并重跑受影响的检查。完成表示已检查状态中没有明显可处理问题；不保证主观奖项认可。
