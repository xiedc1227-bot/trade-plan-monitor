# 规格：quantity-policy

状态：APPROVED — 用户于2026-10-24批准六项决策及规格，并明确授权按任务清单实施。实施进度按验收记录；未完成任务不代表已交付。
实施证据维护在[验收报告](../../verification/2026-10-24-market-linkage-p0.zh-CN.md)。

## QP01 — 目标与契约

把一条合格大盘路径转换成一个有上限且不可变的模拟数量。依赖 `confirmation-selection` 及现有持仓／信号事务规则。`quantity_policy` 字段：`mode=MARKET_FACTOR`、`base_quantity=Q0`、`normal_factor="1"`、`weak_factor="0.5"`、`rounding=LEGAL_FLOOR`、`capacity_policy=BLOCK_FULL`、`signal_quantity_policy=FREEZE`。Decimal系数保持字符串。这些策略值须有来源／审核证据，不是凭空补入的产品默认值。

Q0为既有领域整数上限内的正100股整数倍，先根据研究确定，再按大盘折减；不得猜测、为抵消取整而提高，或根据实时波动重算。最大持仓仍必填。联动规则不能同时提供固定 `quantity`；既有固定普通规则保持原义。

## QP02 — 算法与约束

1. NORMAL_TRANSITION选系数1，普通WEAK选0.5。其他路径授权为零，不构造可执行的零数量动作。
2. 精确计算 `ceiling = factor * Q0`。候选数量为不超过ceiling、同时符合已核验市场规则和当前100股模拟契约的最大正数量。没有共同合法数量则无普通订单。区分市场规则不兼容和普通折减后低于最低量；两者都不能向上取整。
3. 要求选中S0／S1完整满足、无更高优先级风险、模拟库存已知且 `position.max_qty - inventory.total_qty >= candidate_quantity`；否则授权为零并保留原因。不按剩余额度缩量。
4. 信号确认时将候选数量固定为 `planned_qty`，同时记录路径、Q0、系数、规则／证据哈希及使用的库存修订。执行时在事务内重新验证全部既有门槛和当前库存，整笔执行或完全不执行。

市场规则或持仓未知时阻止依赖它们的买入。实际账户文字不初始化模拟持仓。大盘系数不重新定义SELL数量、T+1、CORE保护或技术风险数量。使用现有已核验市场规则数据；支持非100股执行属于P1。

NORMAL_TRANSITION 下 Q0 本身低于官方最小量时（例如 STAR 的 Q0 为100、最小量为200），使用 `MARKET_QUANTITY_BELOW_MINIMUM`。这是普通数量阻断，不属于 WEAK 折减例外；`P1_EXCEPTION_REQUIRED` 仅用于规格规定的 WEAK／BROKEN 例外路径。

## QP03 — 验收计算示例

以下为合成算术测试数据，不是交易建议。假设标的允许正100股整数倍，其他门槛均通过。

| Q0 | 状态 | 额度 | 候选／结果 |
| --- | --- | --- | --- |
| 300 | NORMAL_TRANSITION | 500 | 授权300 |
| 300 | WEAK | 500 | 上限150；候选100并授权 |
| 100 | WEAK | 500 | 上限50；无普通数量；P1例外保持阻断 |
| 300 | NORMAL_TRANSITION | 200 | 候选300；授权零，整笔阻断 |
| 300 | WEAK | 0 | 候选100；授权零 |

确认与执行均要求 `authorized_quantity <= Q0`，且授权数量不超过额度。条件未满足、证据不完整或存在P1例外阻断时，即使算术可计算也不能得到正授权。

## QP04 — 不可变性与重启

对外提供可操作信号前先持久化计算结果。重复轮询或重启使用同一信号事件和固定数量，改善不能扩量。已使用来源事实修订时按CS04使待执行权限失效，不修改已完成执行。并发库存变动触发完整数量重新验证；已完成命令的幂等重放返回原回执，不再成交。额度不足可以阻止执行但不删除信号证据；在原窗口内额度恢复不产生新信号。

已准入的个股数值及复权基准未变时，重取记录编号／时间、复权截至日期及等值 Decimal 表示变化不打断信号连续性。这些采集字段仍保留在不可变审计证据中；价格或基准变化仍使待执行信号失效。连续性归一化不得绕过准入和截止时间检查。

## QP05 — 验收与验证

| ID | 必需证据 |
| --- | --- |
| QP-A01 | 严格互斥的固定／政策契约、字符串系数、有来源Q0和正100股限制拒绝无效候选。 |
| QP-A02 | 全部示例及精确边界、市场规则不兼容场景证明只向下取整、不按额度缩量。 |
| QP-A03 | 大盘、库存或市场规则未知，S0／S1未通过，P1阻断及更高风险均授权零。 |
| QP-A04 | 重启、轮询与状态改善不得扩量、重复消费或部分消费信号。 |
| QP-A05 | 真实临时SQLite并发与幂等测试验证整笔执行、上限、T+1和库存隔离。 |

实现文件：`domain/market_linkage_models.py`、`decision/quantity_policy.py`、共用生命周期／事务接点及针对性测试。从 `trade-plan-monitor/` 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py tests/integration/test_market_linkage_runtime.py tests/integration/test_unified_simulation_transactions.py -q`。遵循MLP07精确算术／风格；不访问用户数据库。

## QP06 — 已批准的官方规则来源增补（2026-10-24）

用户明确要求直接使用官方交易所规则。因此 P0 内置带日期和版本的最小量/递增单位规则，不增加逐证券人工证明流程。版本 `cn-equity-buy-grid-2026-07-06` 自 2026-07-06 生效：沪深普通 A 股及创业板最小量 100、递增单位 100；科创板为 200 / 1；北交所为 100 / 1。与现有模拟交易规则求交后，仍只能使用 100 股整数倍。每次计算保留规则版本、生效日期、条款、来源 URL 和内容哈希。不支持的证券前缀或更早历史日期保持 `MARKET_RULES_UNKNOWN`；该规则表不代表行情供应商覆盖认证，也不实现券商订单上限。

官方来源：[上交所 2026 交易规则第 3.3.8、6.7 条](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)、[上交所科创板投教](https://edu.sse.com.cn/tib/qa/)、[深交所 2026 交易规则第 3.3.8 条](https://investor.szse.cn/lawrules/rule/trade/t20260424_620190.html)、[北交所 2026 交易规则第 3.3.8 条](https://www.bse.cn/jygl_list/200028217.html)、[北交所官方数量示例](https://www.bse.cn/uploads/6/file/public/202509/20250916143055_4sxt0kkec4.pdf)。交易规则于 2026-04-24 发布，2026-07-06 生效。
