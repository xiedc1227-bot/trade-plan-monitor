# 实施计划：daily-plan

英文版本为 canonical；对应副本：`daily-plan-plan.zh-CN.md`。日期：2026-10-02。用户已授权设计→Sol/high实现→全新Astra/high独立审核→修复/复查，不需再次许可。本计划不覆盖其他项目计划。

## P01. 目标与依赖顺序

实施当前[规格](../docs/specifications/monitoring/SPEC-daily-plan.md)及[能力地图](../docs/architecture/CAPABILITY-MAP-daily-plan.md)。当前增量为[2026-10-02模拟清理](2026-10-02-daily-plan-simulation-cleanup.md)：契约→隔离daily模拟状态→运行/风险/发送→公开UI/API→独立验证。[任务](daily-plan-todo.md)保留DPT ID追溯，DSC01–DSC06定义清理切片。

监测/提醒绝不改仓。一次用户显式且合格的模拟原子消费完整提供的100股倍数量。删除本轮券商报告/部分/未知/占额子系统，隐藏控件或改状态名不算删除。最小模拟持仓/回执/日期批次用通用daily存储，不触碰旧真实库存。

## P02. 最小完整交付

完整审核合成计划经真实来源/审核/启用UI及真实生产适配器。官方收盘确认普通信号，仅下一交易所时段可提供模拟，用户单独模拟完整数量。命令前提醒/已读不改仓。精确重试及为已消费信号换key均不重复交易。CORE100/TACTICAL0、max300可在就绪时模拟BUY100至总量200；当日新增TACTICAL受T+1不可卖，普通SELL不扣CORE。风险模拟按审核目标和服务器内部批次执行，无用户分配表单。

保留来源缺项、基本面排除、技术/运行事实、当前审核绑定、正确MACD2×公式、日线/QFQ准入、认证日历恢复、风险范围/cause/完成及旧schema/指数。全部持仓/动作/目标/显示数量为完整100股单位，非交易字段允许0。旧开发记录保留并明确不支持，不成为模拟成功或失控500。

## P03. 文件与删除纪律

- 领域/AI：仅收紧未发布daily模型、信号/持仓/回执契约及V7产品语义，冻结Schema1/2/3、v1–v6和ta-v1。
- 状态：daily记账替换为隔离、带模拟标记的POSITION/SIMULATION通用记录及原子revision/幂等。未发布0024 kind CHECK/model可对新夹具修改，不加迁移系列、不改生产、不sync共享库存、不写真实PositionLot/PositionInventoryConfirmation。
- 决策/运行/提醒：删除订单/占额/部分计算及券商状态，保留技术风险PENDING、时序、风险失效/cause及已修provider恢复。当前发送检查已消费模拟权限。
- API/Vue：删除daily-execution-reports及所有券商/客户allocation表单字段，新增最小daily-simulated-trades与聚合初始化。服务器选择批次及价/时刻，机械重生成双契约。
- 测试：只删被移除daily券商行为测试，替换为完整模拟事务、旧表隔离、当前权限、风险/恢复及真实UI验证。保留共享旧/指数测试，不把旧40+60/UNKNOWN夹具暗中留作新正例。

尽量按3–5文件切片，分开机械生成文件。不做无关格式化、凭据/配置修改、原模板改动、实时调用、生产数据访问、commit/push/deploy。期初模拟基线明确已交收，后续T+1按模拟日期和认证时段计算。不自动导入持仓或建立数据库重置/重分类流程。

## P04. 验证命令

后端命令在 `trade-plan-monitor/`，前端在 `web/`；新文件可拆分但不改验收：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_daily_plan.py tests/unit/test_daily_lifecycle.py tests/unit/test_daily_risk.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_plan_chain.py tests/integration/test_daily_production_reevaluation.py tests/integration/test_daily_sparse_calendar_regression.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_explicit_conditions.py tests/unit/test_explicit_rules.py tests/unit/test_explicit_plan_review.py tests/unit/test_ai_plan_extraction_v4.py tests/unit/test_decision_engine.py -q
.venv/Scripts/python.exe -m ruff check --no-cache src tests
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m pytest -q -m "not live"
npm test -- --run
npm run type-check
npm run build
npm run test:e2e -- tests/e2e/daily-plan.spec.ts
```

追加DP-A11/12/18/20、共享旧表隔离、旧开发数据和权限缺失的模拟定向测试。按仓库现有命令执行双生成契约检查。协调员在源码稳定和独立审查后安排完整后端，不因文档/测试追加重复运行未变53分钟容量组。真实记录排除项/数量，不把旧6065结果改称新范围验证。

## P05. 风险与保留内容问题

| 风险 | 必要缓解 |
|---|---|
| 模拟活动冒充券商现实 | 明确模拟标签、隔离daily持仓/回执，断言旧库存表不变。 |
| 重复点击或改计划恢复数量 | 原子幂等、持久普通消费、当前计划/cause/库存约束及重启验证。 |
| 目标保留40/60再产生零股 | 期初/max/目标/动作/显示逐字段0或100倍校验，不改全局revision类型。 |
| 删除券商UNKNOWN误删风险PENDING | 区分技术确认状态，保留首/次收盘测试。 |
| 被删券商字段在隐藏路径残留 | API拒绝、生成schema缺席、运行/源码搜索和真实浏览器验证。 |
| 清理回归审核/风险/恢复 | 保留独立cause、QFQ/日历、严重/普通范围及来源排除回归。 |

历史计划缺失的策略值和显式停牌策略仍是待补用户内容，不是实现默认值。本次已授权清理不需进一步阶段审批。

删除可编辑券商手数/零股选项及规则证据/日期。100股单位、1分模拟tick、下一时段交收与特殊状态核验为服务器提供的固定产品语义，不是逐计划券商断言。

## P06. 保留此前基本面范围修订

2026-10-01修订已从Schema4/V7、精确来源排除、API/UI全面移除基本面/公告监测，同时保留技术/运行证据。该边界不变。DP-A15/DP-A19仍为反向验收，指数及旧schema/prompt保持。当前模拟清理不恢复基本面、不增加风险分支。

## P07. 历史验证检查点

已被替代的2026-10-01实现获独立F1–F11关闭、后端6065 passed/1 skipped/4 deselected/1 warning，3208.19s，另追加稀疏日历1 passed/5.94s，前端828/type/build及两Chrome链路通过。[历史验证](../docs/verification/2026-10-01-daily-plan.md)及[历史审核](../docs/verification/2026-10-01-daily-plan-independent-review.md)保留证据。当时验证的券商部分/未知/占额现在明确删除，因此不能批准当前范围。

## P08. 当前清理门槛

实施、DSC01–DSC06/DPT09/C4及当前验证已完成。新鲜Astra/high审查经独立后端、重启及真实前端解析验证后关闭C1–C7。[最终双语报告](../docs/verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)保留首次全量失败及严格的纯测试修正，再记录通过的非容量复跑与未变容量组此前的通过结果。Root冻结比较确认业务源码/契约/资源未变。不代表用户计划启用或真实provider认证。
