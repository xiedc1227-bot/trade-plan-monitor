# 日线模拟交易清理 — 2026-10-02

英文版本为 canonical；对应副本：`2026-10-02-daily-plan-simulation-cleanup.zh-CN.md`。状态：COMPLETE。用户已明确纠正产品范围并授权清理，不需再次批准。依据：[SPEC-daily-plan](../docs/specifications/monitoring/SPEC-daily-plan.md) D01/D02/D06/D08–D10及DP-A01–DP-A20；既有module/task ID保持。

## C01. 产品契约

本产品是监测加模拟。提醒绝不改仓。独立用户命令校验当前计划/审核、普通信号或技术风险cause、库存revision、报价、交易时段、T+1、CORE范围及最大量。提供的正100股倍数数量一笔事务全部成功或零变更失败。普通模拟一次消费完整原信号；风险模拟消费服务器推导受影响bucket的当前完整整手减持量，不可用持仓仍为风险义务。没有券商提交、部分结果、未知订单或异步订单状态。

`POST /api/v1/daily-simulated-trades` 仅接受 `planVersionId`、`causeId`、`expectedCauseRevision`、`expectedInventoryRevision`、`quantity`，以及 `Idempotency-Key`。方向、范围、内部批次扣账、当前核验价和服务器时间均推导。响应含 `simulationId`、方向、数量、`priceFen`、`simulatedAt`、库存revision/当前结果及适用的普通消费。同key重试返回同回执，换key不能复用已消费普通权限。结构/数量非法422，当前权限/revision冲突409，资源不存在404。不新增手工/不关联交易API或现金账本。

`POST /api/v1/daily-position-confirmations` 改为最小模拟初始化：`symbol`、`coreQty`、`tacticalQty`、`expectedRevision`。数量为非负100股倍数，基线是设置前已交收的模拟股票，在设置当日或之后首个认证开放时段可用；后续买入按模拟日期计算T+1。不接受 `outstandingComplete`、`includedLotIds`、`openingAllocations`、人工可卖量或券商证明。精确重试不加仓，冲突设置不能覆盖既有模拟交易或已消费信号。

整手字段校验同时覆盖期初CORE/TACTICAL、`max_qty`、持仓/普通/风险目标、可卖和显示执行量：0或100股倍数，交易严格为正。不全局修改 `Qty`，revision/计数也使用它。官方收盘时序的技术风险 `PENDING` 保留，只删券商订单状态。

删除可配置 `buy_min_qty`、`buy_increment`、`sell_increment`、`odd_lot_liquidation`及券商规则 `evidence`/`as_of`。软件固定100股单位、`settlement=NEXT_EXCHANGE_SESSION`、`tick_size_fen=1`和 `special_state_restrictions=BLOCK_UNVERIFIED`，来源审核按产品常量绑定。AI/UI均不要求用户逐计划配置券商规则或证明它们，不新建全局policy/证据确认层。

## C02. 存储与兼容

使用既有通用daily存储中的带模拟标记 `POSITION` 与 `SIMULATION` 回执，采用daily独立revision，仅保留T+1/最新优先风险所需的取得日期批次。不写旧/共享 `PositionLot`、`PositionInventoryConfirmation`、opening balance、真实库存revision或legacy sync。不自动将真实持仓复制为模拟，旧Schema1/2/3读写行为不变。

未发布0024 CHECK/model可原地识别 `SIMULATION` 用于新开发数据库。不新增迁移系列、不破坏式改写、不检查生产数据库。既有不兼容开发表结构在变更前明确失败。旧 `REPORT`、券商 `POSITION`、部分/未知/已成交信号及旧evaluation head保留为证据，不成为模拟回执或500错误。受影响股票设置/模拟返回 `409 DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`，读取返回有界旧数据结果；技术风险/来源历史可见。不抹旧消费、不建重置向导、不重放旧成交、不自动转数据库；新夹具可重建。

## C03. 删除与保留边界

删除daily专用券商执行报告路由/服务/契约、external/report订单身份、PENDING/CANCELLED/UNKNOWN订单转移、部分40+60/新单余量计算、BUY/SELL占额、未知订单容量、未成交完整性断言、客户lot分配/扣账字段表单、券商成交价/时间/证据输入，以及只验证被删除模型的夹具/测试。现在授权删除这些测试属于范围清理，不是弱化保留策略要求。同步删除过时生成客户端字段和隐藏handler，不保留报告到模拟的兼容别名。

保留技术事实、官方可交易/停牌证据（不是券商证明）、来源审核/启用、官方完整收盘、下一交易所时段到期、独立事件/reset lineage、持久消费、max300样例、CORE保护、T+1、普通首破/次收盘风险顺序、严重两证据顺序、目标完成/重评、不同风险cause/outbox权限及已修复500观察/3033日历恢复边界。基本面仍排除；指数及冻结schema/prompt/公式不变。内部最小模拟批次是实现数据，不是用户执行跟踪控件。

## C04. 实施顺序与验证

| 状态 / ID | 切片及必要证明 |
|---|---|
| [x] DSC01 | 收紧未发布日线模拟模型/API契约并删除旧报告/订单字段；DP-A11/12结构/数量拒绝，旧schema夹具不变。 |
| [x] DSC02 | 用隔离持仓/回执事务替换daily记账；证明整笔100一次、回滚、revision冲突、max300、T+1及不写旧表。 |
| [x] DSC03 | 生命周期/风险/运行/发送改用模拟消费且无占额；保留风险失效/cause/recovery和新独立信号，旧开发数据受控处理。 |
| [x] DSC04 | API/UI券商表单替换为聚合设置及显式全量模拟，服务器选内部批次；重新生成双OpenAPI/TypeScript契约。 |
| [x] DSC05 | 被删模型测试替换为DP-A11/12/18/20整手模拟判定、真实临时DB生产集成与真实浏览器链路；保留来源/技术/旧兼容/指数测试。 |
| [x] DSC06 | Astra high独立审核→Sol修复→Astra复查；协调员选择新的相关/全量门禁；双语2026-10-02验证记录真实命令/数量及历史范围区分。 |

切片保持小，机械生成文件与行为分开。daily专用既有文件可简化/删除，共享旧API及其测试不属于清理目标。每片稳定后执行定向领域/API/事务验证，再执行前端单元/type/build、双契约检查及Chrome。完整命令基线仍为 `.venv/Scripts/python.exe -m pytest -q -m "not live"`；协调员在源码/审查稳定后安排，不因每次文档/测试追加重复运行未变化53分钟容量组。

## C05. 验收与交接

保留DP-A01–DP-A20。DP-A11现证明原子BUY100/整手拒绝/提醒不改仓；DP-A12证明当前模拟容量、T+1/CORE及订单契约不存在；DP-A18证明事务/竞态/重启/去重及旧开发证据保留；DP-A20证明真实用户触发模拟UI且无券商跟踪。其他标准在当前模拟持仓措辞下继续有效。原40+60/UNKNOWN结果不证明新标准。

2026-10-01功能/独立审核报告和6065后端通过保留为被替代范围的历史成果，不批准此次清理。保留正文并加范围变更提示。本设计、规格、能力地图、计划、任务双语全部保存后启动Sol/high实现。不授权实时调用、生产数据访问、commit/push/deploy。
