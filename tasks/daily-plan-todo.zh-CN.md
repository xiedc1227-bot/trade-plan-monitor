# 任务：daily-plan

> 历史独立日线实现记录。2026-10-02 起由[单一交易计划流程](../docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md)替代。其测试与完成陈述仅证明所记载的旧范围，不能证明当前单一计划流程。保留历史证据；不得据此要求独立日线产品。

英文版本为 canonical；中文审阅副本为 `daily-plan-todo.zh-CN.md`。状态：2026-10-02 已完成实现、独立审核及发布。本文件统一保留 DPT、DSC 和 C1–C4 的完成记录；当前行为以[规格](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/specifications/monitoring/SPEC-daily-plan.zh-CN.md)为准，测试以[最终验证](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)为准。

## T01. 实施顺序

| 状态 / ID | 交付与验收 | 依赖 | 验证追溯 |
|---|---|---|---|
| [x] DPT01a | 日线完整模型及冻结兼容；模拟单位100股，旧schema/prompt/公式不变。 | — | DSC01 / DP-A01 |
| [x] DPT01b | 逐字段整手量；删除可配置券商增量/零股/证据日期选项，绑定固定软件规则，拒绝不兼容完整契约。 | DPT01a | DSC01 / DP-A02–04/11/12 |
| [x] DPT02a | 保留完整日条件/公式与精确固定/动态语义，最终门禁复核。 | DPT01b | DP-A04/05/17 |
| [x] DPT02b | 保留真实QFQ/日历适配、500观察/3033日期恢复及稀疏日历回归。 | DPT02a | DP-A06/17/18 |
| [x] DPT03a | 最小隔离daily POSITION/SIMULATION持久化，不写共享真实库存、不加迁移系列。 | DPT01b | DSC02 / DP-A18 |
| [x] DPT03b | 原子完整模拟、聚合期初、T+1、独立revision/幂等，删除报告/占额。 | DPT03a | DSC02 / DP-A10–12/18 |
| [x] DPT04 | 普通确认/窗口/独立重置/lineage加一次完整SIMULATED消费。 | DPT02b,DPT03b | DSC03 / DP-A05–09/11 |
| [x] DPT05 | 保留两技术风险时序/范围/cause/完成，整手模拟目标且无订单分配投影。 | DPT02b,DPT03b | DSC03 / DP-A13–16/19 |
| [x] DPT06a | 真实调度/绑定审核的模拟事务约束与恢复，监测不自动交易。 | DPT04,DPT05 | DSC03 / DP-A03/18 |
| [x] DPT06b | 当前发送及持久cause/消费，outbox/读取无券商状态或占额字段。 | DPT06a | DSC03 / DP-A07/16/18 |
| [x] DPT07a | V7忠实部分提取，使用当前100股产品语义与来源排除，冻结v1–v6。 | DPT01b | DSC01 / DP-A01/02/15 |
| [x] DPT07b | 收紧完整模型后保留当前来源/内容/证据审核及启用绑定。 | DPT06b,DPT07a | DSC04 / DP-A03 |
| [x] DPT08a | 删除执行报告路由，最小显式simulated-trades与聚合期初，技术事实仍重评。 | DPT06b,DPT07b | DSC04 / DP-A11/12/15/19 |
| [x] DPT08b | 双契约/type重生成，无券商/订单/客户allocation传输字段，审核UI仍可用。 | DPT08a | DSC04 / DP-A02/03/20 |
| [x] DPT08c | 真实UI显式全量模拟/回执/T+1/CORE，无部分/未知/券商证据/内部扣账表单。 | DPT08b | DSC04/05 / DP-A10–16/20 |
| [x] DPT09 | 新DP-A01–20证据、独立审核/修复/复查、适用全量门禁及双语2026-10-02报告。 | DPT08c | DSC05/06 |

## T02. 检查点

- [x] C1：旧兼容不变、模拟存储隔离；全部新数量逐字段100股边界正确。
- [x] C2：真实生产/运行事务保留普通/风险时序、cause/recovery及完整模拟，无订单跟踪。
- [x] C3：真实来源/审核/启用/UI链路，提醒不改仓、显式全量模拟，无券商/基本面门槛。
- [x] C4：新范围独立审核无实质问题，记录当前实际检查及双语报告。

## T03. 交接与边界

当前日线链路为监控加显式整手模拟。提醒和已读不改仓；初始化及每笔交易遵循固定100股单位，模拟持仓与共享真实/旧持仓隔离。保留技术风险 `PENDING`、T+1、CORE保护、计划 `max_qty`、来源审核及500/3033恢复。无券商订单报告、部分/未知订单、占额或客户分配接口；基本面不参与监控，新增大盘指数逻辑暂缓，既有Schema1/2/3和指数行为保留。旧开发数据明确不支持，不转换成模拟成功。

实现提交 `a8ec8e6a2862fca275a8eac5bad0e768e86ce08c` 和文档提交 `030075c4946bf34833a0155fde6b4deda3c79055` 已推送至 GitHub。旧执行计划、暂停恢复说明和清理交接已合并至本记录；其历史内容可从上述文档提交读取。未在此任务中进行实时provider、生产数据库或部署操作。

## T04. 保留此前范围清单

保留2026-10-01基本面范围修订：恰两技术分支，嵌套执行契约无基本面/公告事实，精确非监控来源排除，无基本面运行/UI阻断，DP-A15/19继续反向边界。此前通过测试不完成新模拟验收。

## T05. 当前证据检查点

实施及DSC01–DSC06/DPT09/C4已完成。新鲜Astra/high审查经独立后端及真实前端解析复验后关闭C1–C7。[当前验证](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)记录首次全量中的旧测试期望、严格修正、通过的最终非容量复跑、保留的容量通过证据及最终前端门禁。历史6065后端/828前端及F1–F11关闭保留于[2026-10-01验证](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-01-daily-plan.md)和[审核](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/2026-10-01-daily-plan-independent-review.md)。新DP-A11/12/18/20使用整手模拟证据，不引用已删40+60/UNKNOWN行为。重叠数量不相加，也不表述为单次全量全绿。

## T06. 合并后的清理任务记录

| 状态 / ID | 已完成边界 |
|---|---|
| [x] DSC01 | 固定整手契约与v7来源处理；删除券商规则配置。 |
| [x] DSC02 | 隔离模拟持仓和原子交易；幂等、T+1及旧数据明确不支持。 |
| [x] DSC03 | 普通信号和两个技术风险分支；防重、事务围栏及恢复。 |
| [x] DSC04 | 最小初始化/模拟API、生成契约、审核启用及UI。 |
| [x] DSC05 | 离线后端、前端、真实浏览器和兼容回归证据。 |
| [x] DSC06 | 新范围独立审核、修复复验及双语验收记录。 |

完整接口字段、错误码、存储和兼容边界统一维护在 `SPEC-daily-plan` D08/D09，验收标准为 DP-A01–DP-A20。此表不重复建立另一份契约。
