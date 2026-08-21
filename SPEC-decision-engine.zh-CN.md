# 规格：decision-engine（确定性决策引擎）

> 中文审阅版。英文权威版为 `SPEC-decision-engine.md`；两份文档必须保持语义一致。

## 目标

使用一份活动计划、一个不可变行情快照和一个策略状态快照，返回可解释判断及拟执行状态迁移，全程不执行 I/O。相同输入必须始终产生相同结果，以支持测试、回放和审计。

该引擎是价格区间、确认条件、阻断项、仓位约束、压力减仓和收盘风险的唯一权威。AI 和 Vue 前端不得复制这些规则。

## 技术栈

- Python 3.11+
- 来自 `plan-domain`、`market-data`、`strategy-state` 的不可变 dataclass/Pydantic 值对象
- 纯函数与 pytest 表驱动测试
- 整数“分”价格比较

## 命令

```powershell
python -m pytest tests/unit/test_decision_engine.py -q
python -m pytest tests/replay/test_decision_replay.py -q
python -m ruff check src/trade_plan_monitor/decision tests/unit/test_decision_engine.py tests/replay
```

## 项目结构

```text
src/trade_plan_monitor/decision/
├── models.py       # 判断上下文、结果、证据和迁移意图
├── conditions.py   # 类型化条件计算器
├── episodes.py     # 低吸事件状态迁移
├── risk.py         # 官方收盘风险迁移
└── engine.py       # 优先级和 evaluate 入口
tests/unit/
└── test_decision_engine.py
tests/replay/
└── test_decision_replay.py
```

## 公共契约

```python
def evaluate(context: EvaluationContext) -> EvaluationResult:
    """纯函数判断：不访问数据库、网络、系统时钟、日志或随机数。"""
```

`EvaluationContext` 显式包含判断时间、活动计划及哈希、完整 K 线、指标与公式版本、实际涨跌停、数据健康、持仓、当前低吸/风险状态和交易日历事实。

`EvaluationResult` 包含：

- 一份权威 `SymbolDecisionSnapshot`；
- 零到多个 `StateTransitionIntent`；
- 零到一个可操作 `SignalIntent`；
- 已满足条件、未满足条件、阻断项和数值证据；
- 下一步观察或动作；
- 判断唯一标识和确定性结果哈希。

运行时在一个事务中应用迁移意图并写入提醒意图。

## 判断优先级

1. 校验计划激活、日历/交易时段、完整 K 线、指标版本、参考数据和新鲜度。
2. 应用立即失败关闭的阻断项。
3. 判断官方收盘风险迁移。
4. 判断机动仓压力减仓。
5. 判断低吸底仓/机动仓事件。
6. 返回中性或区间外观察状态。

高优先级结果会阻止低优先级信号，但仍保留低优先级证据用于界面展示。

## 信号类型

- `WAIT`
- `LOW_ZONE_WATCH`
- `BLOCKED_DATA`
- `BLOCKED_RISK`
- `BUY_CORE_READY`
- `BUY_TACTICAL_READY`
- `PRESSURE_REDUCE_READY`
- `RISK_BREACH`
- `RISK_RECOVERED`
- `RISK_EXIT_READY`
- `RISK_EXIT_PENDING_SETTLEMENT`

默认只有 `BUY_*_READY`、`PRESSURE_REDUCE_READY`、`RISK_BREACH` 和 `RISK_EXIT_*` 产生文字提醒。普通 `WAIT` 和观察进度只更新界面。

## 华亚智能计划规则

### 价格区间

- 低吸区：`[63.00, 64.50]`。
- 观察区：`(64.50, 68.80)`。
- 压力区：`[68.80, 70.20]`。
- 风险线：官方收盘低于 `60.80`。
- 64.50 只属于低吸区，68.80 只属于压力区。

### 低吸事件

1. 分钟价格首次触及低吸区时建立事件，触价本身不产生买入提醒。
2. `episode_low` 是事件开始后的最低价。
3. 后续完整 K 线低点至少低一个最小价位时，确认进度清零。
4. 最近最低点之后至少两根完整 5 分钟 K 线不创新低，且后一根收盘不低于前一根。
5. 最新成交量不高于前一根，并且不高于此前 20 根中位数的 1.5 倍。
6. 临时日线 MACD 柱改善至少 0.02，或者最新有效价格重新站上日线 EMA10。
7. 所有阻断项均已解除。
8. 没有底仓时可产生一次 100 股 `BUY_CORE_READY`；已有底仓且出现后续独立事件时可产生一次 100 股 `BUY_TACTICAL_READY`；总仓位不超过 200 股。
9. 未提醒事件离开低吸区两根完整 5 分钟 K 线后关闭。已提醒事件保持去重，必须重新进入形成新事件才能再次提醒。

### 买入阻断项

- 所需行情过期或不完整；
- 交易日历或实际涨跌停价未知；
- 阴线 5 分钟成交量超过配置中位数倍数；
- 当前价过于接近实际跌停价；
- 沿布林下轨运行；
- 人工事件风险标记；
- 风险线跌破待确认；
- 指标无效或缺失；
- 已达到最大仓位。

### 压力减仓

要求价格触及压力区、不能站稳压力参考价、至少有 100 股可卖机动仓，并满足任一形态：

- 上影线占 K 线振幅至少 40%；
- 从当日高点回落至少 1%；
- 成交量至少为滚动中位数 1.5 倍且收于 K 线下半部；
- 触价后连续两根完整 K 线收在压力参考价下方。

没有持仓或只有底仓时，只展示压力证据，不产生减仓提醒。

### 官方收盘风险

- 盘中价或临时收盘低于 60.80 不推进风险状态。
- 第一次官方收盘低于 60.80 时产生 `RISK_BREACH`，禁止加仓并记录跌破交易日。
- 下一交易日官方收盘回到 60.80 及以上时产生 `RISK_RECOVERED` 并清除状态。
- 若仍低于 60.80，必须同时满足持续恶化：收盘不高于跌破日，且成交量不低或日线 MACD 柱没有改善，才产生风险退出。
- 退出优先选择最新可卖的 100 股，机动仓优先于底仓；若目标仓位受 T+1 限制，则产生 `RISK_EXIT_PENDING_SETTLEMENT`。

## 幂等标识

- 盘中判断：`(plan_hash, symbol, completed_5m_bucket_end, formula_version)`。
- 收盘判断：`(plan_hash, symbol, official_trade_date, formula_version)`。
- 提醒：`(plan_hash, trading_date, signal_type, episode_or_risk_transition_id, quantity)`。

重复行情、恢复行情或重启只能补充证据，不能产生第二个相同动作。

## 代码风格

```python
def evaluate_condition(
    condition: Condition,
    context: EvaluationContext,
) -> ConditionEvidence:
    evaluator = CONDITION_EVALUATORS[type(condition)]
    return evaluator(condition, context)
```

每种 DSL 条件使用独立计算器并返回证据，不修改状态，避免巨型嵌套条件。

## 测试策略

- 覆盖全部信号、阻断项、价格边界和优先级冲突。
- 验证触及低吸区不提醒，创新低会清零。
- 覆盖 64.50、68.80 和一分钱边界变化。
- 覆盖底仓优先、最大仓位、T+1 和只有底仓时不减仓。
- 覆盖首次风险跌破、收回、尚未恶化、恶化退出、官方日线延迟和受限仓位。
- 重复运行相同上下文并比较结果哈希。
- 回放有效买点、持续下跌、行情过期、重复/恢复行情、重启和独立事件。

## 边界

- 始终：上下文显式提供时间、日历和行情事实。
- 始终：每个结果返回完整证据和下一步。
- 先确认：新增信号、修改优先级或改变华亚智能阈值。
- 禁止：访问数据库、调用 Tushare/AI、渲染文字、发送通知或读取系统时间。
- 禁止：修改输入状态或推断成交。
- 禁止：运行时解释含糊的计划原文。

## 验收标准

- 相同输入产生字节稳定的规范化结果和哈希。
- 一个有效低吸事件最多产生一次买入意图。
- 每个动作都能从保存的数值证据解释。
- 行情或参考数据缺失、过期、不完整时按股票失败关闭。
- 风险和 T+1 行为符合交易计划与交易日历。
- 10 只股票状态完全隔离。

## 待确认事项

无阻断事项。阈值均属于计划版本数据，修改时必须生成新版本。
