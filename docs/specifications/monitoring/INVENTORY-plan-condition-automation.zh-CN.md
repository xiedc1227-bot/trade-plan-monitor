# 来源条件自动化清单

PMA-H01/H02/H04准备 · 2026-11-01 · 代码基线`95dfc7f` · [英文规范版](INVENTORY-plan-condition-automation.md) · [生成补充](../../operations/trade-plan-automation-prompt-supplement.zh-CN.md)。

## PAI-S01 — 证据及限制

本清单对照来源与代码，不是独立冻结的语料真值、完整覆盖矩阵或已批准的策略解释。下列每组均读取原始文本及生产代码，不以模型候选或工程witness充当真值。“自动”“缺定义”“必要人工”“不支持”仅为文档分类，不是API枚举。同一组可以包含多个分类：公式存在不等于模糊定义完整，定义已审核也不等于运行时为真。

来源定位使用从1开始、包含两端的行号，不是字符偏移。下表hash为保留CRLF的未变原始字节SHA256；S0另有规范UTF-8 SHA256 `f17e12b88f4c12d7af7b67caabede2e9d7c2712142a64e67a212c7621865f731`（去BOM，将CRLF／CR统一为LF）。规范化字符数不是原始码点span，本清单不分配此类span。S03／S04 hash仅识别来源副本，不证明前序已审核或当前SQL归属。

| 来源 | 准确位置 | 原始SHA256 |
| --- | --- | --- |
| S0 | [原始提示词](../../../../docs/TradingAgents/reports/新提示词.txt)，第1–155行 | `0d923053c35245bc4f125993f7c456f1d80f237facd170c00f0438fc704b3120` |
| S1 | [中文README](../../../README.zh-CN.md)，提示词第450–724行；hash覆盖全文件 | `85d4fc3c106a52265fd6595e33bd877aed60d12109561c24273446f89840d342` |
| S1-EN | [英文README](../../../README.md)，对应生成提示词；hash覆盖全文件 | `958b5b987baefa7b767a5df02ece19c57009fa4d4379af4c4c6f8e5222c445ef` |
| S03 | [原始03](../../../tests/fixtures/shengxin_sources/03-20260930-095728.txt)，第1–55行 | `ed0addcd166735798111a6a22e9951270a2e4a8b1fc4448d0f49443baf8eb6bc` |
| S04 | [原始04](../../../tests/fixtures/shengxin_sources/04-20261009-091956.txt)，第1–81行 | `e71ab6dbfda744c92358b14ffd1ef8c09b2af13d6a12f6bc2d0e3255ea4f7d2b` |

下表共用的生产代码依据：

- C1：[日线原生条件](../../../src/trade_plan_monitor/domain/daily_plan_models.py)、[evaluate_daily_condition](../../../src/trade_plan_monitor/decision/daily_conditions.py)、[calculate_daily_ta_v2](../../../src/trade_plan_monitor/market_data/daily_indicators.py)、[已注册提取默认值](../../../src/trade_plan_monitor/ai/plan_extraction.py)。
- C2：[unified原生条件](../../../src/trade_plan_monitor/domain/unified_plan_models.py)、[evaluate_unified_condition](../../../src/trade_plan_monitor/decision/unified_conditions.py)、[五分钟聚合](../../../src/trade_plan_monitor/market_data/aggregation.py)。
- C3：个股数据归属[ProductionMonitorPipeline.prepare_daily_inputs / persist_minutes / persist_five_minute](../../../src/trade_plan_monitor/runtime/production.py)；[DailySeries认证](../../../src/trade_plan_monitor/market_data/daily_data.py)。恢复由既有采集权限、调度及重评负责，就绪读取不采集。研究优先使用东方财富不证明runtime已经实现对应provider。
- C4：[指数公式](../../../src/trade_plan_monitor/market_index/formulas.py)、[市场状态](../../../src/trade_plan_monitor/decision/market_regime.py)、[相对强弱](../../../src/trade_plan_monitor/decision/relative_strength.py)、[确认选择](../../../src/trade_plan_monitor/decision/confirmation_selection.py)、[大盘联动](../../../src/trade_plan_monitor/decision/market_linkage.py)。数据归属：既有生产指数路径及C3对齐后的个股／日历数据。
- C5：[P2数量](../../../src/trade_plan_monitor/decision/p2_sizing.py)、[P2费用](../../../src/trade_plan_monitor/decision/p2_economics.py)、[P3金额](../../../src/trade_plan_monitor/decision/p3_capital.py)、[当前金额输入](../../../src/trade_plan_monitor/state/p3_current.py)。数据归属：C3报价／官方申报规则及明确确认的模拟账本／成本声明。
- C6：[日线风险](../../../src/trade_plan_monitor/decision/daily_risk.py)、[信号生命周期](../../../src/trade_plan_monitor/decision/unified_lifecycle.py)、[日线核算](../../../src/trade_plan_monitor/state/daily_accounting.py)、[动作来源权限](../../../src/trade_plan_monitor/state/source_action_authority.py)。风险归属、持仓及确认窗口独立于条件真假。
- C7：[原生目标resolver](../../../src/trade_plan_monitor/domain/reviewed_fact_targets.py)、[私有准入](../../../src/trade_plan_monitor/web/daily_service.py)、[实际SQL证据重检](../../../src/trade_plan_monitor/state/reviewed_fact_authority.py)、[公开DailyFactCommand](../../../src/trade_plan_monitor/web/routers/daily_plans.py)。归属：实际原始版本／审核、准确条件及已完成观察；公开准确选择尚未接线。

## PAI-S02 — 原提示词中的行情定义

| ID | 来源／要求 | 分类 | 原生模型／求值器及数据归属 | 当前交付／缺口 |
| --- | --- | --- | --- | --- |
| PAI-01 | S0:15–43；S1:471–504。完整同口径日线；MA20/MA60、MACD(12,26,9)、RSI14/ATR14、BOLL(20,2)；盘中累计量不与全天量混比。 | 准确受支持输入可自动；口径／时间未明则缺定义。 | C1/C3：`daily-ta-v2`；既有指标／历史／可用性gate。 | 公式存在；历史遵循准确准入的`monitoring.macd_min_observations`及已注册来源定义，保持原生1..500范围。笼统250日说明不能替代所需历史。缺历史／口径等待归属明确的数据，不由人工替代计算。 |
| PAI-02 | S0:61–70,152–153；S1:528–548。价位用途、包含端点、固定／动态引用；收盘在区间不等于盘中触及。 | 比较可自动；原始价位选择属必要人工；触及／收盘歧义属缺定义。 | C1/C2：`DAILY_PRICE_IN_RANGE`、`DAILY_PRICE_COMPARE`、`MINUTE_CLOSE_IN_RANGE`；C3。 | 不自动发现新平台／支撑，不移动风险线启用买入。周期及准确字段须由来源明确；区间本身不是信号。 |
| PAI-03 | S0:52–56,80–82；S1:550–558。普通价格结构AND量价／K线证据AND技术辅助；明确的企稳备选证据保留ANY。 | 准确定义可自动；“企稳、有效下影、受阻”缺定义。 | C1：`DAILY_CANDLE_RATIO`、`DAILY_CLOSE_SEQUENCE`；C2 ALL/ANY；C3。 | 实际定义为相邻两个收盘不再下移时可表达。不能编造影线／实体部位、分母及阈值。三个证据维度不能合成一个泛化事实。 |
| PAI-04 | S0:32,80–82；S1:495–504,554–556。此前20日均量不含当日；“不再异常放大”、缩量上涨及连续放量下跌保留各自含义。 | 准确量比可自动；定性异常缺定义。 | C1 `DAILY_VOLUME_RATIO`；C2 `MINUTE_VOLUME_TO_MEAN_GTE`仅用于明确的五分钟历史；C3。 | 20日基准存在不代表比较符／比值已确定。完整五分钟量能比较不能替代日线比较。 |
| PAI-05 | S0:52–56,80–82；S1:490–504,552–558。至少一个已定义MA/BOLL/MACD/RSI改善／转弱；单独交叉、触轨或超买不足。 | 准确比较可自动；未说明的改善缺定义。 | C1 `DAILY_INDICATOR_COMPARE`、动态引用／offset及C1/C3指标。 | 自动化前明确实际指标／比较符／引用，保留ANY及外围硬条件。既有分钟原语不提供通用分钟K线／指标树。 |
| PAI-06 | S0:35–43；S1:593–661。板块派生指数、有优先级的市场状态、对齐5/20收益、S0/S1/S2及数量政策。 | 已注册日线子集可自动；许可例外的逐机会批准属必要人工。 | C4及C3；`BROKEN`、`WEAK`、`NORMAL_TRANSITION`、`UNKNOWN`；原生Schema6/7政策。 | 已有准确注册公式；不完整S0不能使S1/S2通过。Schema6阻断例外；Schema7许可不是批准。不支持联动五分钟确认，也不能用未批准5/20比较替代原文定性相对强弱。 |
| PAI-07 | S0:98–110；S1:663–681。原始数量／持仓上限、ATR档位、费用及经济含义；不从金额反推Q0。 | 准确政策可自动；未给门槛／金额含义则缺定义；适用账本／成本声明属必要人工。 | C5/C3；Schema8 `PREVIEW_ONLY`/`REQUIRED`、Schema9 `OPEN_COST_CAP`/`MARKET_VALUE_CAP`。 | 保留来源明确输入／默认值，不新增通用最低收益或比值。预览不是门槛；不编造现金／账户，不缩量求通过，不以成本条件否决风险SELL。 |

## PAI-S03 — 时间、风险及必要人工边界

| ID | 来源／要求 | 分类 | 原生模型／求值器及数据归属 | 当前交付／缺口 |
| --- | --- | --- | --- | --- |
| PAI-08 | S0:9,84–86,152；S1:560–568,587–591。正式收盘后下一交易日窗口、无明示到期则持续有效、独立新信号及一笔计划数量。 | 既有时间／occurrence规则可自动；首次审核／启用属必要人工。 | C6生命周期、C3日历、C7当前来源／审核。 | 刷新／receipt改变不是新occurrence。准确独立／reset政策须与来源一致；定义变化需审核，不是每日重定义。 |
| PAI-09 | S0:90–96；S1:570–585。普通双收盘风险；严重单收盘结构AND量价恶化；保留目标、范围、停牌及来源更及时退出。 | 已定义价格／日历分支可自动；不可约定性严重证据属缺定义或必要人工。 | C6风险及C3；C1/C2严重条件树；C7原始风险owner。 | 不编造阈值延后已确认风控。若澄清后仍需人工证据，准确`RISK_BRANCH`人工准入／实际生产是有来源依据的后续接缝；已存工程风险测试不等于该能力交付。 |
| PAI-10 | S0:19,45–47,92,154–155；S1:487,576–581,671–681。官方事件／基本面解释、首次计划审核、明确模拟持仓／成本及每次许可例外批准。 | 必要人工；不支持自动基本面判断。 | C7审核／官方证据、C6账本、C5成本声明及既有例外决策路径。 | 定义答案、A/B文字、预览及保存计划不认证官方事实、不批准机会、不初始化持仓或记录成交。不要求人工代替可计算OHLC／指标证据。 |
| PAI-11 | S0:86,100–108,154–155；S1:671–681。真实／部分成交和未成交委托与明确整笔模拟分开；CORE不是普通TACTICAL BUY。 | 真实账户处理属必要人工；不支持券商／委托／部分成交或普通建立CORE。 | C2 `UnifiedRule`、C6账本及既有模拟契约；真实记录保持在该契约之外。 | 不把来源交易规则改写为正100股模拟网格。保留真实数量，不兼容导入须拒绝，保留适用官方交易状态检查。 |

## PAI-S04 — 原始03/04：保留实际硬要求

| ID | 来源／要求 | 分类 | 原生模型／求值器及数据归属 | 当前交付／缺口 |
| --- | --- | --- | --- | --- |
| PAI-12 | S03:45–51。完整日线收复25.99在前，之后25.5–26.0回踩不破并再次收起，AND成交不异常放大AND相对深证成指不再转弱，才考虑第一笔100股。 | 明确顺序／价格片段可自动；回踩／量能／强弱细节缺定义。 | C2 `DAILY_PRIOR_CLOSE`及C1比较／序列；C3/C4。 | 保留先后及全部限定。不自动选择触及／收盘、端点、收起门槛或相对窗口。当前价高于25.99、单根反弹或工程witness均不是完整来源规则。 |
| PAI-13 | S04:59–73。首次完整收复25.99，再25.7–26.0回踩／收起为首笔100；进一步站稳26.40并回踩为第二笔100；末笔100保留，上限300。 | 已定义阶段／数量片段可自动；不破／收起／站稳缺定义。 | C2/C6 `AFTER_RULE_COMPLETED`及准确首条逻辑规则身份；C3。 | 首阶段限定不自动成为第二阶段门槛；S04:65“最好”仍是偏好。不产生第三笔或重复第二笔。仍须实际前序／来源／审核证明，原始03不是已审核父版本。 |
| PAI-14 | S03:51及S04:75。再次跌破24.20创新低后持续空仓；原始03等待新底部结构，不下移25.99。 | 不支持持续入场前取消；恢复定义未决。 | C2/C6具有`RISK_OR_REVIEWED_INVALIDATION`及信号后reset，不承载该持续入场前义务。 | PMA-R48继续约束：不用单个当前bar判断、泛化`REVIEWED_FACT`、新风险线或虚构自动恢复近似。两份原始正例继续阻断，不能标为已验收负例。 |

## PAI-S05 — 已交付证据及下一最小接缝

[PMA-R59](../../verification/2026-10-27-plan-monitor-assurance.zh-CN.md)记录提交`5cb9656`：269项集成＋202项单测＋31项行情＋3项生产邻近＝505项不同聚焦离线检查，与前片有重叠。本次文档未新跑测试。它证明已测schema5普通TRADE_DATE正式日线／分钟目标路径，不证明语料提取、全部schema／owner、实际安装或真实发送。输入匹配本身不授予动作权限；实际本地源复核仍拒绝缺失／纠正观察。

本库存支持的眼前H04接缝，是为已经测试的普通子集公开准确选择／登记，并保留旧无目标字节及服务端派生目标／观察的权限边界。既有`POST /api/v1/plan-facts`及`DailyFactCommand`尚未公开该选择器。契约／代码／测试及四项生成产物须顺序小片同步后才能整体验收。本文件不新增API字段或枚举。

PAI-09支持在澄清后证据仍需人工时，核对准确严重风险归属。本清单不证明有必要开放全部提醒／reset／Schema6–9／SIGNAL组合。先从已审核来源确定各必需单元，保留其原生日期／signal及来源／大盘／例外／金额gate。T18负责既有UI选择／就绪展示，T19负责联合边界／风险独立验收，不另建平台。

原始03/04、X09表示／含义、X12实际已审核前序证明及未冻结语料／资源问题保持未决（[PMA-R48/R59](../../verification/2026-10-27-plan-monitor-assurance.zh-CN.md)、[EVA-S02–S04](SPEC-extraction-v12-acceptance.zh-CN.md)）。不编造缺失日期，不降低来源／资源边界，不冻结未审核真值，不宣称正向完整矩阵。真实提取保持0/48；本片文档不涉及provider、服务、用户数据库、迁移、真实采集或发送。README、`plan-extract-v12`及原始报告保持不变。
