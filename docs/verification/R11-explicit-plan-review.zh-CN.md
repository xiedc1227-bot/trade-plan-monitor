# R11 显式计划复核验证报告

## 范围与更正后的结论

本报告离线验证 R11 显式计划复核边界。未调用真实 AI 提供商、行情提供商、通知渠道、交易接口或生产数据库，也未使用凭据、额度或网络请求。

初版报告把 `explicit-plan-semantic-corpus-v1.json` 中通过的 20 例描述为固定语义语料，这一表述范围过大。这些案例把任意原文绑定到通用风险提醒草稿，只断言关键词推导出的语义码。它们保持原样，继续作为有用的词法分类器回归证据，但其 **20/20 结果不属于原文到计划的语义验收证据**。

修正后的验收语料为 `tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json`。每个案例都有自己的原文、独立预期类型化字段与单位、边界、动作、数量、时间语义、逻辑结构、未解析路径、不支持原因片段、模拟提供商部分响应及来源映射。测试把响应送入真实的 v4 提供商边界、解析器和服务端复核构建器。它是确定性的模拟提供商证据，不代表真实模型准确率。

## V2 原文到计划语义结果

“实际”记录提供商/解析器/服务端复核链的输出。`MATCH` 表示每个 oracle 字段值与单位、引用原文片段、逻辑父节点与子节点、未解析路径集合和语义码集合都一致，而不只是表中摘录的重点。

| ID | 原文 | 独立预期语义 | 实际 |
|---|---|---|---|
| SEM-EXP-01 | `003043.SZ` 已完成 5 分钟收盘价位于 9.80–10.00 元（含两端）时买入 100 股 | symbol；5 `MINUTES`；980–1000 `FEN` 且含端点；`BUY` 100 `SHARES`；无语义阻断 | MATCH；`NONE` |
| SEM-EXP-02 | 已完成 5 分钟收盘价低于 9.50 元时风险提醒 | 5 `MINUTES`；950 `FEN`；`RISK_ALERT`；无语义阻断 | MATCH；`NONE` |
| SEM-EXP-03 | 含端点价格区间 AND 当前量不少于此前 5 根已完成 5 分钟 K 线成交量算术均值的 1.5 倍；买入 100 股 | `ALL` 价格与成交量子条件；980–1000 `FEN`；5 `BARS`；1.5 `RATIO`；`CONTIGUOUS_TRADING_BARS`；100 `SHARES` | MATCH；`NONE` |
| SEM-EXP-04 | 已完成 5 分钟收盘价位于 10.80–11.00 元（含两端）时卖出已登记持仓 100 股 | 1080–1100 `FEN` 且含端点；`SELL` 100 `SHARES`；`ALL_REGISTERED` | MATCH；`NONE` |
| SEM-EXP-05 | 手动激活；低于 9.50 元风险提醒；每次激活仅一次 | `MANUAL`；950 `FEN`；`RISK_ALERT`；`ONCE_PER_ACTIVATION` | MATCH；`NONE` |
| SEM-EXP-06 | 买入规则、卖出规则，以及交易同时命中时阻止两者 | `BUY` 100；`SELL` 100；`trade_conflict=BLOCK_BOTH` | MATCH；`NONE` |
| SEM-EXP-07 | 买入规则、风险规则，以及风险与交易同时命中时仅保留风险 | `BUY`；950 `FEN` 风险提醒；`risk_conflict=RISK_ONLY` | MATCH；`NONE` |
| SEM-EXP-08 | `003043.SZ` 最大持仓 300 股；明确区间买入 100 股 | symbol；300 与 100 `SHARES`；明确已完成 K 线区间 | MATCH；`NONE` |
| SEM-AMB-01 | 价格“企稳”后买入 100 股 | 保留 `BUY` 100；条件未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-AMB-02 | “明显放量”时买入 100 股 | 保留 `BUY` 100；成交量阈值/窗口未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-AMB-03 | 上涨“受阻”时卖出 100 股 | 保留 `SELL` 100；价格条件未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-AMB-04 | 已完成 5 分钟收盘价“企稳” AND “放量”时买入 100 股 | 保留 5 `MINUTES` 与 100 `SHARES`；组合条件未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-AMB-05 | 价格“受阻”且“明显放量”时卖出 100 股 | 保留 `SELL` 100；父子条件未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-AMB-06 | 已完成 5 分钟收盘价在 10 元“附近企稳”时风险提醒 | 保留 5 `MINUTES` 与 `RISK_ALERT`；数值区间未解析 | MATCH；`UNRESOLVED_SEMANTICS` |
| SEM-UNS-01 | “有效跌破”9.50 元时卖出已登记持仓 100 股 | 保留 950 `FEN`、`SELL` 100；确认语义不支持 | MATCH；`UNSUPPORTED_SEMANTICS` |
| SEM-UNS-02 | 先企稳，再放量，然后买入 100 股 | 保留 `BUY` 100；术语未解析且顺序语义不支持 | MATCH；两个语义码 |
| SEM-UNS-03 | 先买入 100 股，价格上涨后再卖出 100 股 | 保留两个数量；跨子句顺序语义不支持 | MATCH；`UNSUPPORTED_SEMANTICS` |
| SEM-UNS-04 | 未限定周期的收盘价低于 9.50 元时风险提醒 | 保留 950 `FEN` 与提醒；已完成 5 分钟确认未解析 | MATCH；`UNSUPPORTED_SEMANTICS` |
| SEM-UNS-05 | 突破后随后回踩再买入 100 股 | 保留 `BUY` 100；顺序语义不支持 | MATCH；`UNSUPPORTED_SEMANTICS` |
| SEM-UNS-06 | 有效跌破后再等下一次收盘确认 | 保留提醒意图；阈值/时间未解析；顺序与收盘限定不支持 | MATCH；`UNSUPPORTED_SEMANTICS` |

结果：**20/20 个 v2 原文到计划案例通过**，其中明确 8 例、歧义 6 例、不支持 6 例。该结果仅覆盖模拟提供商契约，不能替代另行授权的真实模型评估。

## 反误报与对抗证据

- `SEM-CTX-01` 证明“仅监控已完成 5 分钟 K 线”的全局上下文可以限定后续收盘子句，不产生“未限定收盘”误报。
- `SEM-DEF-01` 证明对“放量”（此前 5 根已完成 K 线、算术平均值、1.5 倍）和“有效跌破”（已完成 5 分钟收盘价低于 9.50 元）的有界定义不会触发仅由术语造成的阻断；未定义用法仍被阻断。
- 错误业务单位被拒绝为无效提供商输出；遗漏成交量窗口映射及额外持仓上限会产生 `UNMAPPED_PLAN_FIELD`。
- 内部自洽但与原文不符的数量、动作、`ALL`→`ANY` 及逻辑父节点子句归属仍不可启用，并要求精确来源映射复核。
- 从历史派生三规则 fixture 中移除卖出子句或风险提醒子句映射，会使对应原文保持 `UNRESOLVED`，对应动作字段保持未映射。

## 历史派生简写 API 链路（非用户逐字原文）

历史 `_ORIGINAL_SOURCE` 是派生的三规则简写，并非用户逐字原文。撤回此前称其为未改动完整用户原文的表述；它保持不变，继续作为回归证据。部分草稿保存时精确报告六条缺失执行政策路径：激活、冲突政策、成交量历史范围，以及三条重复策略。`safety_conditions=null` 是可选值，不再被误报为缺失政策。

当前内容编辑把上述七个具体政策值作为持久化 `USER_SUPPLEMENT` 记录加入，并与 `SOURCE` 分离。提交确认前，测试逐项比对来源问题与当前类型化值及服务端原文子句，也逐项比对政策问题与补录路径/值。确认完成后，启用仍为 false：组合的当前持仓子句与“提醒/确认不代表成交”子句仍未解析，`symbol` 也保持未映射，不会借组合子句的局部信息伪装成完整证据。

该链路暴露并修复了一个映射重整变量遮蔽缺陷；此前它会在编辑时错误地把无引用子句改成 `MAPPED`。

## 逐字原文闭环修正（2026-09-13）

`explicit-plan-literal-source-v3.json` 保存提供的精确原文及换行、唯一明确记录的替换 `测试股票` → `003043.SZ`，以及独立的字段/单位/原文子句和人工补录 oracle。模拟响应经过真实 v4 提供商/解析器边界，再在临时 SQLite 通过普通部分保存、读取、编辑及复核 API。该 fixture 不代表真实模型准确率。

| 边界 | 预期与实际 |
|---|---|
| 仅原文 | 六条缺失政策路径；无 reviewId，内容 canActivate=false |
| 当前编辑 | 八项明确人工测试补录：TRADING_DAY 与 2026-09-14、三条重复选择、两条冲突选择、成交量历史范围 |
| 当前映射已审核、处理项未确认 | 精确剩余两项 SOURCE_TREATMENT_REVIEW_REQUIRED；内容 canActivate=false |
| 当前值与处理均已审核 | 有效 reviewId；内容 canActivate=true；executionReadiness=NOT_EVALUATED；公开激活返回409 |
| 库存隔离 | 保存/编辑/复核后仍为 UNKNOWN/null；独立公开确认登记100；同 key 重试和新 key 再确认仍为100且期初余额不变 |
| 运行时/提醒 | 真实隔离显式运行时在 UNKNOWN 库存下提交纯 RISK_ALERT；BUY/SELL/RISK 提醒入队及公开已读/重试不改变已登记库存 |
| 兼容性 | 不含 source_processing 的已复核/未复核旧 v1 记录重启后保留修正前冻结的来源/内容/证据哈希 |

`INVENTORY_ASSERTION` 保留独立 symbol、数量及结算区段；`PRODUCT_GUARANTEE` 保留两条精确子句且仅绑定 `alert-position-isolation-v1`。服务端重新推导每条存储记录、要求精确当前确认，绝不从文本初始化持仓。有限语法及保留语族边界见 SPEC-source-treatment-review；任意中文语义仍需人工复核。

独立审查发现新验收测试初版只检查提取 oracle，未检查编辑后的当前值。交付前已修正：每次确认都先独立核验当前值、单位、结构、原文子句及补录。把980改为970、数量改为200、ALL→ANY 或引用错误子句的变异探针必须在确认前失败。附加条件、否定、伪造数量/可卖量/契约/区段、缺失子句/处理、错误解决绑定、旧哈希及存储处理/解决记录篡改也有反例覆盖。无效提交返回422；存储损坏沿用不泄露内部信息的500 INTERNAL_ERROR。

## 自动化证据

- 原有 v1/v2/提供商/解析器/复核/API 聚焦链路保留：**69 passed**；加上45项新处理/逐字原文/库存/旧版本测试后：**114 passed**。
- 本次完整后端单元测试：**1,382 passed**，仅有一条既有 Starlette `httpx` 弃用警告。
- 本次相关计划/SQLite/持仓/显式运行时/传输/提醒集成组：**189 passed**。
- 此前 **1,362 unit / 269 integration** 属于上一轮语义语料修正，不属于本轮逐字原文闭环运行。
- 所有变更 Python 文件的 `ruff check` 与 `ruff format --check` 通过。
- 早期 R11 的 433 项发布门槛、29 项旧显式运行时/传输及 684 项广泛回归仅保留为初始实现提交的历史背景；更正后的结论以上述最新运行结果为依据。
- 尝试执行全体测试时进入既有长耗时集成段，最终被中止且没有结果，因此不计入证据。

前端类型检查仍报告 R10 已存在的 `AlertTable.vue` 与 `AlertsView.vue` 告警联合类型错误。R11 未修改或压制这些错误。

从 `trade-plan-monitor/` 复现：`.venv/Scripts/python.exe -m pytest tests/unit -q`。114项命令选择单元文件 `tests/unit/test_explicit_plan_semantic_corpus.py`、`test_explicit_plan_semantic_acceptance.py`、`test_ai_plan_extraction_v4.py`、`test_explicit_plan_review.py`、`test_source_processing.py`，以及集成文件 `test_explicit_plan_review_api.py`、`test_source_treatment_review_api.py`、`test_source_treatment_inventory_isolation.py`、`test_source_treatment_legacy_compatibility.py`。189项组选择集成文件 `test_plan_production_composition.py`、`test_sqlite_repositories.py`、`test_explicit_plan_review_api.py`、`test_position_inventory.py`、`test_explicit_transport.py`、`test_explicit_runtime_production.py`、`test_explicit_decision_persistence.py`、`test_alert_production_composition.py`，再加三个新增 `test_source_treatment_*` 集成文件。全部使用 `-q`；各组存在重叠，不得相加计数。

## 发布边界

公开能力继续保持 `publicActivationAvailable=false`。有效且属于当前内容的复核是公开启用的必要条件，但由于 R12 普通计划表单仍不存在，它刻意不是充分条件。R12、真实 AI、导入、通知投递、交易执行、网络访问、推送及生产部署均不在本次修正范围内。
