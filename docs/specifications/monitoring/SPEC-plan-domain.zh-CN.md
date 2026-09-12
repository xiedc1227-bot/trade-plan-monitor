# 规格：plan-domain（交易计划领域模型）

> 中文审阅版。英文权威版为 `SPEC-plan-domain.md`；两份文档必须保持语义一致。

## 目标

定义系统唯一可执行的交易计划契约。该模块负责版本化计划、激活策略、价格区间、仓位限制、白名单条件、跨字段校验和稳定哈希。

用户审核结构化计划时，必须能够明确看到系统将判断哪些条件。活动计划不可原地修改，任何调整都生成新草稿版本。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- Pydantic 2：边界和领域校验
- `Decimal`：接收用户价格；整数“分”：比较和存储价格
- YAML/JSON：可移植导入导出格式
- SHA-256：根据规范化 JSON 生成计划标识

具体补丁版本在脚手架阶段写入 `pyproject.toml` 和锁文件。

## 命令

```powershell
python -m pytest tests/unit/test_plan_domain.py -q
python -m ruff check src/trade_plan_monitor/domain tests/unit/test_plan_domain.py
python -m compileall -q src/trade_plan_monitor/domain
```

## 项目结构

```text
src/trade_plan_monitor/domain/
├── plan_models.py       # 计划、激活、价格、仓位和条件联合类型
├── plan_validation.py   # 跨字段校验和激活就绪判断
├── plan_codec.py        # 规范化 JSON 与安全 YAML/JSON 导入导出
└── plan_hash.py         # 稳定内容哈希
tests/unit/
└── test_plan_domain.py
config/plans/
└── 003043.SZ.sample.yaml
```

## R08 版本范围

下述 Schema 1 契约及 `SPEC-plan-index-conditions.md` 中的追加 Schema 2 契约描述 `LEGACY_LOW_BUY`。已授权 R08 设计在 [SPEC-executable-plan-extension](SPEC-executable-plan-extension.zh-CN.md) 中新增独立 Schema 3 / `EXPLICIT_RULES` / `explicit-rules-v1` 契约，明确字段、部分草稿与可执行校验、显式动作数量、独立确认持仓、待解决政策和错误码。本次文档变更不代表已经实现。[ADR 0005](../../decisions/0005-version-explicit-plan-rules.zh-CN.md) 规定新旧读写/hash/回放兼容，禁止放宽旧模型图或修改旧哈希。设计不为任何待解决的具体计划授予激活批准。

## 公共契约

### 版本化计划

```python
class TradePlan(BaseModel):
    schema_version: Literal[1]
    plan_id: str
    version: int
    symbol: str
    name: str
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: PlanMetadata
    activation: ActivationPolicy
    position: PositionPolicy
    levels: PriceLevels
    entry: EntryPolicy
    reduction: ReductionPolicy
    risk: RiskPolicy
    blockers: BlockerPolicy
    monitoring: MonitoringPolicy
```

激活策略使用带判别字段的联合类型：

- `MANUAL`：持续有效，直到用户明确停用。
- `TRADING_DAY`：只在指定交易日有效。
- `DATE_RANGE`：在起止日期内有效，并以交易日历为准。

`activation_is_eligible_on` 是回放与生产共用的正式日期策略。它使用求值目标携带的市场日期，
而不是延迟任务或重启恢复发生时更晚的墙钟时间。`TRADING_DAY` 按日期精确匹配，
`DATE_RANGE` 两个端点均包含；`MANUAL` 在明确停用前始终有资格。

同一股票最多只有一个活动版本。编辑活动版本时必须生成新草稿，激活新版本时原子地停用旧版本。

### 白名单条件 DSL

监控条件只能是类型化数据，不能是表达式字符串。Schema v1 支持：

- `PRICE_IN_ZONE`
- `NO_NEW_LOW_FOR_BARS`
- `NON_DECREASING_CLOSE`
- `VOLUME_TO_PREVIOUS_LTE`
- `VOLUME_TO_MEDIAN_LTE`
- `VOLUME_TO_MEDIAN_GTE`
- `MACD_HIST_IMPROVEMENT_GTE`
- `PRICE_RECLAIMS_INDICATOR`
- `UPPER_WICK_RATIO_GTE`
- `RETREAT_FROM_SESSION_HIGH_GTE`
- `CLOSE_IN_BAR_LOWER_HALF`
- `CONSECUTIVE_CLOSES_BELOW_LEVEL`
- `OFFICIAL_CLOSE_BELOW_LEVEL`
- `NEXT_TRADING_DAY_RECOVERY`
- `POSITION_BUCKET_AVAILABLE`
- `SELLABLE_QUANTITY_GTE`
- `MANUAL_EVENT_RISK_CLEAR`
- `DISTANCE_FROM_LIMIT_DOWN_GTE`
- `LOWER_BAND_HITS_LTE`

每种条件都有独立的 Pydantic 模型和参数范围。逻辑组合只允许 `ALL` 与 `ANY`，最大嵌套深度为 4，单份计划最多 50 个叶子条件。

`VOLUME_TO_MEDIAN_LTE` 使用 `max_ratio`；`VOLUME_TO_MEDIAN_GTE` 使用 `minimum_ratio`。两者均将最新完整 K 线成交量与指定数量的此前完整 K 线成交量中位数比较。`SELLABLE_QUANTITY_GTE` 必须同时明确 `bucket`（`CORE` 或 `TACTICAL`）和整手 `quantity`，因此一个仓位桶的可卖数量绝不能满足另一个仓位桶的可卖规则。

`PRICE_IN_ZONE` 使用最新有效规范完整分钟收盘价。`PRICE_RECLAIMS_INDICATOR` 将当前精确 5 分钟周期内的每个相邻分钟对与同一个所选当前日期指标值比较，要求至少一个分钟对满足 `previous_price < indicator <= current_price`，且周期结束价仍位于指标之上或与其相等；进入周期时已经位于指标上方不算重新站上。`LOWER_BAND_HITS_LTE` 将每根所选完整 5 分钟 K 线收盘与相同 identity 的 `ta-v1` 5 分钟下轨点逐一比较，并把相等计为命中。`CONSECUTIVE_CLOSES_BELOW_LEVEL` 本身只要求配置数量的相邻完整 K 线收盘严格低于命名价位。压力专用的触价后资格由后续 T023 编排施加，不是隐藏的叶子参数。

配置中的四种压力拒绝备选共同构成不能站稳的完整定义；Schema v1 不新增第五个压力条件。

未知条件、任意公式、脚本、SQL、字段路径、动态导入或外部接口调用均为非法输入。

### 校验规则

校验范围包括：

- A 股代码格式及交易所一致性；
- 合法最小价位、价格精度和整数手数；
- `0 < core_target_qty + tactical_target_qty <= max_qty`；
- 可执行价格区间互不重叠，开闭边界明确；
- 风险线和压力参考价处于合理配置范围；
- 窗口、比例、超时和 K 线数量均为正数且有上限；
- 只使用受支持的指标公式版本与时间周期；
- 激活日期字段完整；
- 每项条件需要的行情证据都能由 `market-data` 提供；
- 激活时不存在未解决的重大 AI 警告或未映射原文。

校验结果统一包含 `code`、`path`、`severity`、`message` 和 `activationBlocking`。错误禁止保存；普通警告允许保存草稿，但激活阻断警告必须先处理。

## 代码风格

```python
class PriceZone(BaseModel):
    low_fen: int = Field(gt=0)
    high_fen: int = Field(gt=0)
    include_low: bool = True
    include_high: bool = True

    @model_validator(mode="after")
    def validate_order(self) -> "PriceZone":
        if self.low_fen > self.high_fen:
            raise ValueError("价格区间下限不能大于上限")
        return self
```

Python 使用 `snake_case`、显式枚举以及尽可能不可变的值对象。本模块不得包含行情、数据库或网络 I/O。

## 测试策略

- 为每种条件和边界编写表驱动单元测试。
- 对价格区间、规范化序列化和哈希稳定性进行属性测试。
- 测试 YAML/JSON 安全往返导入导出。
- 为华亚智能示例计划建立黄金样例。
- 验证价格改变一分钱或仓位改变一股都会改变计划哈希。
- 覆盖未知字段、任意表达式、过深嵌套、NaN/Infinity、超长文本和危险 YAML 标签。

## 边界

- 始终：在导入、API、AI 输出、保存和激活边界执行校验。
- 始终：生产计划选择、上下文构建和最终事务 fence 都使用目标市场日期执行正式激活策略。
- 始终：保留原文和草稿来源，但不得使其具有可执行性。
- 先确认：新增条件类型、Schema 版本或激活模式。
- 禁止：执行用户或 AI 提供的代码、公式或 SQL。
- 禁止：根据提醒或提醒确认推断成交。
- 禁止：原地修改活动计划。

## 验收标准

- 示例计划往返导入导出不丢失精度，并产生稳定哈希。
- 数据库能够事务性保证每只股票只有一个活动版本。
- 存在重大 AI 遗漏时计划不能激活。
- 所有可执行规则都对应一个类型化白名单条件。
- 64.50、68.80 等边界只有一个明确归属。
- 任意导入路径都不能实例化危险对象或执行代码。

## 待确认事项

无阻断事项。经 2026-08-21 批准的修正，在尚未发布的 Schema v1 契约中新增 `VOLUME_TO_MEDIAN_GTE`，并将 `SELLABLE_QUANTITY_GTE.bucket` 改为必填。Schema v1 发布后，新增条件类型必须升级 Schema 并重新审核。
