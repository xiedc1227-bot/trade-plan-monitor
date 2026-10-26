# 契约：market-linkage-p2

状态：实施契约 — 2026-10-26。细化已批准的六项决策，不新增策略阈值。

## MLP2-K01 — 版本及字段归属

Schema 8 / condition-plan-v4 / pretrade-policy-v1。审核哈希域：plan-review-content-v5。固定数量保留 quantity_policy.mode=MARKET_FACTOR 和 base_quantity=Q0。ATR 数量改用 quantity_policy.mode=DERIVED_MARKET_FACTOR，禁止 base_quantity，其余大盘因子／舍入／容量／冻结字段仍明确。pretrade_policy.sizing 包含 mode=ATR_RATIO_TIERS、metric=ATR14_OVER_CLOSE、base_qty、tiers[{lower,upper,multiplier}]。FIXED_Q0 仅含 mode。拒绝不一致／混合形式。Decimal 输入必须为字符串；数量／分为 JavaScript 安全整数范围内的严格整数。

## MLP2-K02 — 费用与来源依据

Economics 按 mode 区分：NONE 不含其他字段；PREVIEW_ONLY／REQUIRED 含 entry_price_mode、target_price_fen、risk_price_fen、fee_schedule；REQUIRED 另含 gates，至少一个非空阈值。fee_schedule 含 schedule_id、version、currency、symbols（1–100个准确证券标识）、effective_from、effective_through、provenance、commission_rate、minimum_commission_fen、components（最多20项）、buy_slippage_fen、sell_slippage_fen。费用项含 id、side BUY/SELL/BOTH、kind TAX/TRANSFER/HANDLING、rate、included_in（null、COMMISSION或另一费用项ID）。包含关系必须兼容收费侧。Provenance 记录 source、excerpt、as_of（可空）、classification=ESTIMATE。除明确的联合类型分支外，字段均必填，缺失不代表0。

## MLP2-K03 — 依据、API及冻结

来源绑定沿用审核的叶路径覆盖，包含P2字段。价位依据沿用现有来源审核并补充 level、dimension（PRICE_STRUCTURE/TREND/VOLUME_OR_CANDLE/VOLATILITY）、source、excerpt、as_of、indicator（可空）；MA20／BOLL_MIDDLE共享TREND维度。人工决定由现有明确审核收据记录，不能由模型提供reviewed=true。决策依据版本为p2-pretrade-evidence-v1，费用计算为p2-economics-v1，连续性为p2-consumed-v1；使用规范Decimal格式。旧依据字节兼容，衍生Q0不重写来源计划哈希。

当前提取版本为 plan-extract-v11。审核候选保留 null 缺失值，同时保留标量及集合边界；可执行模型仍严格校验。POST /api/v1/plan-economics-previews 只读，occurrenceId 指例外 candidate_id，authorityGranted 固定为字面值 false。Schema 8 研究使用 backtest-run-v9。ResearchDecisionEvent.signal_pretrade 和 ResearchSignalReference.pretrade_ref 对冻结 P2 依据去重；报告准入前必须解析所有引用，并重新校验完整 DailySignalState。新可选字段不写入旧记录，32 KiB 结果条目上限不变。

## MLP2-K04 — 兼容与顺序接入点

清单：plan_codec/plan_hash → 当前草稿分派／AI提取／审核 → 持久化计划读取 → 日线运行／confirm_signal／例外权限 → 模拟事务 → web DTO／OpenAPI／UI → 回放输入／计划／读取 → 通知。显式版本集合和类型联合仅在完整权限链就绪时允许8；此前公开可执行加载器继续拒绝8，独立模型／纯函数不代表已交付。仅在公开准入开启时将现有版本8拒绝测试改为真正不支持的版本，保留拒绝覆盖。

## MLP2-K05 — 回退及阶段证据

不改写历史。必要时新增存储；回退保留Schema 8记录，旧程序不得据此执行。迁移测试全用临时SQLite。T01基线V01：2026-10-26行为修改前74项通过，0.65秒。T02–T03拆为模型／纯契约及有保护的分派；T10权限校验完整前不开放公开准入。广泛类型读取适配拆为每片最多五文件的顺序子任务，分别进行定向测试。



包含 T10 公开权限防护的全部阶段已完成，参见[最终验收报告](../../verification/2026-10-26-market-linkage-p2.zh-CN.md)。
