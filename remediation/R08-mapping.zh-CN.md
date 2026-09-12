# R08：原文映射、实施切片与审核预期

日期：2026-09-12。`R08-mapping.md` 是英文正式版；本文为语义等价中文审阅副本。基线：`main/beff0410150813e64a242a3821a299090d963e9b`。**R08-A 设计完成；R09–R12 尚待实施。**

## M01. 不可变来源与状态词表

验收材料保持不变，位于 `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a093fc-f8d3-73d1-b759-ad76c7451697/business-acceptance/`。`acceptance-report.md` 第6节“Requested scenarios”记录以下目标；这是报告的正式原句，不是新编造的用户原文逐字转录：

> The synthetic plan uses `003043.SZ` as its test identifier. Prices and quantities are acceptance-only synthetic values. The target is preserved in full: existing 100 shares sellable that day; maximum 300; buy 100 when a completed five-minute close is in inclusive [9.80,10.00] AND its volume is at least 1.5 times the arithmetic mean of the preceding five completed five-minute bars; sell 100 for a completed close in inclusive [10.80,11.00]; risk alert below 9.50 on a completed five-minute close; alerts and acknowledgements never change actual positions.

`baseline.md` 和 R00–R07 交接是历史证据，不是 R08 新执行通过。设计依据为 [SPEC-executable-plan-extension](../docs/specifications/monitoring/SPEC-executable-plan-extension.zh-CN.md) E01–E10 和 [ADR 0005](../docs/decisions/0005-version-explicit-plan-rules.zh-CN.md)。

- `SUPPORTED_COMPONENT`：当前代码具有所述有限行为，不代表整个 v3 原文计划已经运行。
- `IMPLEMENTATION_REQUIRED`：R08 可以表达，仍需指定后续切片实现。
- `CONFIRMATION_REQUIRED`：原文不能确定必要选择/事实。保留类型化 null + 服务端 `UNRESOLVED`，不静默默认。
- `UNSUPPORTED`：首版显式模式不能表达；保留原文、阻止激活，不声称完整支持。

## M02. 原文条款到字段映射

| ID | 保持不变的含义 | 精确目的字段 | 当前状态 / 负责人 |
|---|---|---|---|
| C01 | 测试标识 `003043.SZ` | `symbol`、已校验 `market=SZSE`；合成标记为测试元数据 | `SUPPORTED_COMPONENT`；v3 分派由 R09 负责 |
| C02 | 原有100、当日可卖100 | 独立持仓确认 `totalQuantity=100`、`sellableQuantity=100`、明确选择的 `asOfTradeDate`；如无 lot 表示它，则建立普通期初余额 | `IMPLEMENTATION_REQUIRED`，R09 持仓 / R12 表单；绝不作为 AI 成交或目标仓位。登记日/完整账本声明是单独可信输入。 |
| C03 | 最大300 | `position.max_qty=300`、`inventory_scope=ALL_REGISTERED`、`lot_size=100` | 既有最大值/整手算术为 `SUPPORTED_COMPONENT`；包含普通持仓的已知总量需要 R09 |
| C04 | 完成五分钟收盘在含两端 [9.80,10.00] | `rules[0].confirmation={kind:COMPLETED_BAR_CLOSE,timeframe_minutes:5}`；`condition.conditions[0]={type:COMPLETED_CLOSE_IN_RANGE,low_fen:980,high_fen:1000,include_low:true,include_high:true}` | 既有区间/完成K线组件；v3 直接规则为 `IMPLEMENTATION_REQUIRED`，R09 |
| C05 | AND、前五根完成K线、算术均量、当前>=1.5倍、排除当前 | `rules[0].condition.type=ALL`；第二子节点 `VOLUME_TO_MEAN_GTE`、`window_bars=5`、`minimum_ratio="1.5"`；当前根永不进入此前窗口 | `IMPLEMENTATION_REQUIRED`，R09；不可用中位数替代。`history_scope` 审核见 Q03。 |
| C06 | 在已审核重复政策下，首个合格完成条件满足时买100 | `rules[0].action={type:BUY,quantity:100}`；重复与数量独立 | `IMPLEMENTATION_REQUIRED`，R09；不要求首次只触碰建 episode、核心仓优先或未声明 MACD |
| C07 | 完成收盘在含两端 [10.80,11.00]，卖100 | `rules[1].condition={type:COMPLETED_CLOSE_IN_RANGE,low_fen:1080,high_fen:1100,include_low:true,include_high:true}`；相同完成时机；`action={type:SELL,quantity:100,inventory_scope:ALL_REGISTERED}` | `IMPLEMENTATION_REQUIRED`，R10；普通/仅 CORE 可卖持仓无需压力拒绝形态即可合格 |
| C08 | 完成五分钟收盘<9.50，纯风险 | `rules[2].condition={type:COMPLETED_CLOSE_BELOW,price_fen:950}`；相同完成时机；`action={type:RISK_ALERT}` | `IMPLEMENTATION_REQUIRED`，R10；949真、950假；无数量、日收盘等待、持久官方风险锁定或自动卖出 |
| C09 | 提醒和已读不是成交 | `signal_intents` / outbox 与持仓命令分离 | 既有隔离为 `SUPPORTED_COMPONENT`；R09/R10/R12 将证据扩展到 v3 BUY/SELL/RISK_ALERT 和期初余额 |
| C10 | 未提供 episode、指数、指标、安全阈值或 CORE/TACTICAL 指令 | 新 `execution_mode=EXPLICIT_RULES`，无旧策略字段；`safety_conditions=null` 不携带额外阻断 | 契约选择的模式/缺省必须可见，不能当成原文或默认用户确认；R11/R12 展示所有补充。 |

受支持的条件/动作内容可以无损映射。但由于缺少以下执行选择，**仅原文仍不可激活**。这没有改变 S01 的条件预期：存在明确已审核测试输入且两条件为真时，必须 BUY 100；没有这些输入时，仅原文审核必须可见地保持未完成。

## M03. 缺失选择与不支持语义

| ID | 缺失或补充问题 | 处理方式 |
|---|---|---|
| Q01 | 提醒后的 repeat/rearm，包括实际成交登记之前 | 逐规则 `repeat_policy=null` + `UNRESOLVED_EXECUTION_POLICY`。提供 `ONCE_PER_ACTIVATION` 或 `EACH_QUALIFYING_BAR`，R08 不选定任何一个。同次激活重新布防/每日一次/等待成交需要不支持标记。 |
| Q02 | 有效日期和终止 | `activation=null`，直到用户选择既有 MANUAL/TRADING_DAY/DATE_RANGE。不推断“今天”、持续时间或到期日；选定后 R01 有效期规则继续强制执行。 |
| Q03 | 窗口是否跨午休/前交易日 | 展示 `CONTIGUOUS_TRADING_BARS` 及日历邻接，要求明确确认。不静默每日重置；仅同日变体 v1 不支持。只有盘中 fixture 不能证明此未选择边界政策。 |
| Q04 | 同时 BUY/SELL 和风险/交易冲突 | `conflict_policy=null`，直到审核选择 E05 有限政策。原文区间不重叠，但不存在已批准的隐藏全局优先级。 |
| Q05 | 独立持仓完整性/as-of 日期 | 人工明确登记全部当前 lot/余额及日期。原文声明不证明生产账本已初始化。未知保持 null；已知零必须明确声明。 |
| Q06 | 附加/人工风险安全要求 | 原文未提供，展示没有额外声明安全树。如用户增加，将值/path 绑定到用户证据，只在声明处消费 R07。不得插入强制 CLEAR 前置。 |
| U01 | “先A再B”、确认成交后、假转真重新触发、分批 | `UNSUPPORTED`；v1 没有时序状态机/跨规则依赖。不得转换为 ALL、数组顺序或旧 episode。 |
| U02 | 显式模式中的其他周期、每日重置均量、指数/指标/公式条件 | `UNSUPPORTED`；受支持的旧计划仍可使用明确的旧/指数契约。模式切换必须真正重新审核。 |
| U03 | 部分/未知结算期初余额；未指定成本/购入事实 | 保留事实和缺失项。首版期初余额要求余量已知全部可卖，绝不编造成本/日期或分类为 TACTICAL。 |
| U04 | v3 研究模拟成交 / 组合回测 | `UNSUPPORTED_BACKTEST_PLAN_VERSION`；仍可纯监控回放。旧历史回测数据保持可读。 |

R08 曾提出一个关于 Q01 的可选用户问题。协调会话明确：完成契约不需要全局答案；未答即未解决。本设计未记录任何选定重复政策的回复。之后的答案必须作为带范围的来源补充记录，不能倒填到未改动原文。其他选择可以保持可见待填字段，不阻碍有限契约的实施。

## M04. 可审核草稿示例

这是**部分合成 v3 草稿示意**，当前基线解析器不接收它；它不是可执行 fixture，也不是真实计划。`plan_id`、名称、版本和技术字面量属于测试/契约元数据。`null` 选择仍待解决；`safety_conditions=null` 表示未声明额外树，不代表用户已审核其不存在。C02 有意不放入本文档。

```json
{
  "schema_version": 3,
  "execution_mode": "EXPLICIT_RULES",
  "execution_version": "explicit-rules-v1",
  "plan_id": "synthetic-f06",
  "version": 1,
  "symbol": "003043.SZ",
  "name": "SYNTHETIC F06",
  "market": "SZSE",
  "metadata": {},
  "activation": null,
  "position": {"inventory_scope": "ALL_REGISTERED", "lot_size": 100, "max_qty": 300},
  "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
  "rules": [
    {
      "rule_id": "buy-100",
      "condition": {"type": "ALL", "conditions": [
        {"type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 980, "high_fen": 1000, "include_low": true, "include_high": true},
        {"type": "VOLUME_TO_MEAN_GTE", "window_bars": 5, "minimum_ratio": "1.5", "history_scope": null}
      ]},
      "action": {"type": "BUY", "quantity": 100},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    },
    {
      "rule_id": "sell-100",
      "condition": {"type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 1080, "high_fen": 1100, "include_low": true, "include_high": true},
      "action": {"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    },
    {
      "rule_id": "risk-950",
      "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
      "action": {"type": "RISK_ALERT"},
      "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
      "repeat_policy": null,
      "safety_conditions": null
    }
  ],
  "conflict_policy": null
}
```

## M05. 不降低原预期的 S01–S09

| 场景 | 保留原预期 | 基线证据 / 缺失实现 | 必需新证据 |
|---|---|---|---|
| S01 | 仅价格不能买；完成时价格 AND 均量为真 -> BUY 100 | 既有逻辑组件；F06 仍为 `IMPLEMENTATION_REQUIRED`，R09 | 非均匀历史量、首个合格目标、已知原有持仓、明确分离的 Q01–Q05 可信测试补充；完整仅原文草稿仍阻断 |
| S02 | 9.80/10.00 含端点，恰好1.5倍允许 | 只有区间/中位比较组件；不继承均量通过 | 979/980/981/999/1000/1001 分；均量200下量299/300/301；不替换为中位数 |
| S03 | 完成前满足但最终失败，不产生完成K线提醒 | 既有完成/无缺口行情保护 | 同一 v3 计划在完成前、最终收盘/量失败、重复/未完成目标，均无提前意图 |
| S04 | 完成卖出区间 -> SELL 100；完成收盘<9.50 -> 纯风险 | 旧压力/官方收盘测试不能证明本项，需 R10 | 1079/1080/1100/1101；949/950/951；普通及仅 CORE 可卖100；无日收盘等待或虚构数量 |
| S05 | 模糊“企稳后买入、放量突破”不虚构参数 | R04 关闭 API 省略问题；语义提取仍不完整 | null 字段及保留原文遗漏；无关伪造引用不能建立审核；R11/R12；真实模型准确性仅 R14 |
| S06 | AI 错误/格式错误/遗漏不能激活或破坏活动计划 | 既有解析/失败和 R04/R05 屏障；未上报遗漏/当前编辑重审完成仍由 R11 负责 | 完整及部分 v4 候选；服务端强制问题覆盖；缺政策不激活；编辑后当前内容确认；提取失败不改活动指针 |
| S07 | 陈旧/乱序/重复/断线/部分数据不虚构信号，健康可见 | 既有数据边界及 R02 恢复；仍需 v3 消费 | 逐规则缺失依赖、全部目标/cutoff 保护；无关成交量缺失时风险仍可见；前端恢复刷新新提醒分支 |
| S08 | 重试/重启去重；已读不改变实际持仓 | 既有隔离/去重组件，不能笼统继承 v3 通过 | 两种重复政策、逐规则原因、风险+卖出双意图原子回滚/重试；提醒/已读不改变期初余额/lot；外部仍至少一次 |
| S09 | 更新/停用/到期停止有效新增旧版本操作 | R01 日期/轮换保护；排队提醒查询回归在 R09 前仍待修复 | 新执行/审核/hash/active revision 保护；目标及当前投递日到期；历史标记；RISK_ALERT 不走旧跨日风险例外 |

## M06. 消费位置与有序 R09 切片

以下 Python 路径均相对 `src/trade_plan_monitor/`。这是 R09-A/B 的内部细化，不是新增侧栏任务或申请权限。同一 R09 任务按顺序执行；每项可独立审阅，聚焦检查通过后提交。如果仍横跨额外独立职责，继续拆分，不降低门禁。协调任务先负责独立 R01 outbox 修复。

| 切片 | 复用 / 必需新边界 | 继续前验收 |
|---|---|---|
| R09.1 兼容与模型边界 | `domain/plan_models.py`、`plan_codec.py`、`plan_hash.py`；平行 v3 类型/分派；保持 `ai/models.py::TradePlanDraft` 和 `ai/prompts.py` 模型图不变 | 旧计划字节/哈希、三个 Schema/提示词摘要、旧回放 payload 不变；明确不支持版本错误；v3 部分草稿不能执行；双语 Schema 一致 |
| R09.2 纯均量/区间叶子 | `decision/conditions.py` 精确算术、`_recent_bars`、日历邻接及逻辑辅助；v3 path 证据 | T01–T04，含非均匀均量、相等、排除当前、全部经认证零量、缺口、午休/跨日；无 episode/指标依赖 |
| R09.3 权威持仓 | `state/models.py`、`repositories.py`、追加迁移、`web/position_service.py`；独立完整持仓/期初余额和 revision | T05/T06：未知与显式零、原可卖100/最大300、不要求活动计划、不编造成本/日期、不重复计数、幂等/重启；提醒和计划编辑都不改变持仓 |
| R09.4 v3 纯规则/结果契约 | `decision/models.py`、`engine.py`、可选小模块 `decision/explicit_rules.py`；`ExplicitEvaluationResult`、直接 BUY 和重复状态转移建议 | 首个合格目标提醒100；成交前后 ONCE/EACH；无旧锁定；当前持仓保护；证据保留；新结果哈希确定且兼容旧结果 |
| R09.5 持久规则/结果/outbox 参与者 | `state/repositories.py` 及投影参与者、`notifications/models.py`、`identity.py`、`render.py`、`outbox.py`；追加身份/payload 约束与规则发生状态 | 原子提交结果/状态/BUY提醒；入队后回滚不留占用；重启/重试保持 eventId 和重复抑制；旧事件/迁移字节不变；不支持消费者明确拒绝能力 |
| R09.6 生产分派与状态保护 | `runtime/production.py`、`production_context.py`、`service.py`；只构造显式模式必需证据，消费持仓/人工风险 revision，提交时校验 | 临时真实 SQLite/调度组合验证 S01/S02/S03 及到期；并发激活/持仓/人工风险编辑不能提交陈旧 BUY；可选指标/指数/人工风险缺失不成为全局阻断 |
| R09.7 本地传输与集成检查点 | 既有计划/持仓/提醒 DTO、投影、`openapi.json`、生成客户端类型；服务端权威 v3 能力/就绪字段 | 契约生成/检查；仅原文不完整计划阻断；明确可信测试审核适配器标为隔离；新 BUY 提醒可查询；旧聚焦回归；在 R11 审核/R12 必需消费者就绪前，公开 v3 激活仍不可用 |

R09.1–R09.2 实现原 R09-A 意图；R09.3–R09.7 是 R09-B 的必要拆分，不代表这些功能已存在。仅 BUY 的隔离 fixture 是**派生子集**，不得重标成完整三规则验收计划。消费者可以分别声明动作支持能力；请求未实现动作的计划必须无法通过能力校验。完整原计划不可能仅靠 R09 通过。

| 后续步骤 | 必须消费的内容 |
|---|---|
| R10-A | 扩展直接动作求值器和当前持仓减仓路径，支持普通 SELL；结算/数量不足及旧分仓兼容 |
| R10-B | 新纯风险叶子/动作、显式冲突、多意图结果 -> 事务 -> payload -> 查询 -> 渲染；不复用持久官方风险转移或旧历史投递例外 |
| R11-A | **已实施并完成离线验证。** `ai/models.py`、`prompts.py`、`extraction.py`、持久复核记录及 `web/plan_service.py`；独立 v4 解析、部分草稿、原文区段到叶子与叶子到来源覆盖、当前编辑内容确认 |
| R11-B | **经修正复验后已实施并完成离线验证。** 不可变 v1 20 例仅作为词法分类器证据。独立 v2 模拟提供商语料为 8 明确 / 6 模糊 / 6 不支持案例逐例提供原文、独立类型化语义/单位/逻辑/未解析 oracle、部分响应及映射，并全部经过 v4 提供商/解析器/服务端复核链；未调用真实 AI |
| R12-A/B | 既有计划表单/预览、持仓确认/减仓表单、逐规则政策选择、原文/当前值/差异/来源、全部规则结果/提醒、服务端权威 `canActivate` 与 `executionReadiness`；不强制 JSON |

## M07. 针对性测试预期

下列是未来测试，不是 R08 已运行测试。复用既有单元/回放/集成套件及临时 SQLite/Fake SDK；不使用真实 AI、行情、通知或交易。附加政策通过命名为 `human_confirmed_test_supplement` 的输入测试，明确 sourceHash/选择 path/值及确认时间。另行保留仅原文提取断言。Fixture 日期、成本（若旧 lot fixture 必需）、重复和冲突选择绝不能归因于原文。

| 测试 | 独立预期结果 |
|---|---|
| T01 | 前量[100,100,100,100,600] -> 均量200、中位100；1.5倍时当前200/299假、300/301真；均量排除当前；环境 Decimal 精度不影响结果 |
| T02 | 合格量下买价979假、980/981/999/1000真、1001假；卖1079假、1080/1100真、1101假；风险949真、950/951假 |
| T03 | 未完成目标、缺一根前量、重复/倒序/未来/混合股票K线或所需日历缺失，不能发出依赖提醒；只有 Q03 测试确认后才接受精确午休/前开市日邻接 |
| T04 | 五根经认证零量应用算术零阈值；缺失量不得变零；只有价格满足而量失败的 ALL 不买；ANY 真分支加缺失备选仍为真 |
| T05 | 无持仓确认 -> null 且阻断 BUY/SELL；显式零 -> 已知0；原确认100加BUY100 -> 实际仍100、候选允许；已知200+100到300允许、已知300+100阻断；未确认无关原文不能初始化它 |
| T06 | 普通期初100或仅 CORE 可卖100满足 SELL100；已知不足阻断、未知结算仍未知；不编造成本/日期，遵守 T+1 限制和缺日历；幂等重确认不重复加100 |
| T07 | ONCE 在首个合格完成目标发出；之后真/假/真/换日/已读/成交/重启不重新布防。EACH 在无成交时也每个不同合格目标各发一次；两者实际持仓均不变 |
| T08 | 同目标 BUY+SELL -> 两者均不发；风险+SELL 遵守选定政策；已提醒但仍为真的风险保留冲突效果；可能冲突根未知阻断受影响交易；纯风险不受无关量/持仓缺失影响 |
| T09 | 风险+SELL 其中一条入队后崩溃，双提醒、结果及规则状态全回滚；重试各创建一次且去重身份独立；后续投递重试保持 eventId；清理不能重新布防 |
| T10 | 求值到提交间并发持仓更新，或已声明人工风险 CLEAR -> RISK_PRESENT，使陈旧意图中止；重试读取新 revision。未声明的人工风险无影响。 |
| T11 | 价格/比较符/ALL-ANY/数量/周期/重复/冲突/安全/有效期/执行版本编辑改变 contentHash 并使审核失效；仅名称/metadata/版本编辑保留 contentHash，但要求精确新版本绑定。原文/证据编辑要求重新审核映射。 |
| T12 | 改版本改变 planHash，即使 contentHash 相等，R07 确认仍变未知；同 hash 重启保留未过期且早于 cutoff 的确认；过期/晚于 cutoff/缺失均未知 |
| T13 | 开始前/结束+1/停用/轮换/陈旧 active revision -> 无新的有效旧版本交易；历史行可见且不可操作；v3 风险绝不使用跨日官方收盘例外 |
| T14 | v1/v2 文档往返及结果哈希、prompt v1/v2/v3 摘要；刻意改变旧 Schema 触发 guard；错误 prompt/output schema 被拒绝；新 v4 有单独审核摘要 |
| T15 | 仅原文合成草稿保留 C01–C10 全部含义及未解决 Q01–Q05；不声称完整支持/可激活。“企稳后买入、放量突破”不虚构阈值。不支持时序不能靠通用已读解决。 |
| T16 | 编辑后 AI 草稿可存为待审核，随后明确当前快照审核可完成；陈旧/伪造/省略问题列表、重新导入及供应商失败输出均不能激活或替换活动计划 |
| T17 | 完整离线原文 + 单独补充 -> 审核/保存/激活 -> 调度 -> resultHash -> 全部 eventId -> 浏览器展示/已读 -> 持仓不变；重启后重复及 R02 快照恢复；无需编辑 JSON |
| T18 | 旧回测文件/ID/结果不变；v3 研究成交提交在入队前明确失败；纯 v3 回放标为监控回放，不声称组合回测支持 |

## M08. 当前源码审阅与剩余集成问题

已检查实际代码，而不只看旧交接：`plan_models.py::TradePlan`；`plan_codec.py::_plan_json_data`；`plan_hash.py::plan_sha256`；`ai/models.py::TradePlanDraft`；`ai/prompts.py::_render_frozen_schema`；`web/plan_service.py::_resolve_server_review` / `_pending_edited_review`；`runtime/production_context.py::ProductionContextBuilder` / `_manual_event_risk_for_plan`；`decision/conditions.py::_median_volume_facts`；`decision/engine.py::_position_summary`；`decision/models.py::SignalIntent` / `_EvaluationResultPayload`；`runtime/service.py::run_intraday`；`web/position_service.py`；`notifications/outbox.py`；`backtest/runner.py` 及 `run_input.py`。

关键耦合：当前 context 即使面对简单规则也要求官方历史并计算指标；当前汇总将空 lot 求和为零；期初 lot 登记要求活动计划、分仓/成本/日期；结果/outbox 假设单意图及卖出目标 lot。这些是新模式真实实现缺口，不是无害存储字段。R09/R10 必须处理实际消费路径，同时保留旧历史契约。

`AlertOutbox._active_plan_for_event` 当前在活动计划缺失/不匹配两个分支返回 `False`，调用者随后依据 `TradePlan | None` 契约访问 `.activation`。**两个错误返回均来自 R01 提交 `099e41e`，不是最初验收基线。**R04–R07 中“已有基线”的说法是指各自 R01 之后的本地基线，不是原审查提交。协调会话已在 R09 前安排独立 R01 回归补修。R08 不修它，也不把提醒组合算作全绿。补修必须保留无当前计划/计划不匹配时的历史标记与失败关闭投递，并有聚焦回归。

## M09. R08 完成边界

R08 交付双语设计、精确映射和实施约束，没有 v3 代码、迁移、真实计划、持仓或供应商操作。缺失原文选择被忠实表示为待填，完成设计不需要必要的全局业务答案。R09–R12 仍为实施工作，R13 为离线独立验收，R14 为另行授权的真实证据。只有协调任务创建后继，本 R08 任务不创建任何后继。
