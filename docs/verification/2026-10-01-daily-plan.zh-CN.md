# 日线计划离线验证 — 2026-10-01

> 2026-10-02范围已变更：用户授权删除日线券商订单/部分/未知跟踪，改为显式原子整手模拟。本文件记录此前范围，其完成/测试结论不批准新清理。请依据[当前清理契约/任务](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/030075c4946bf34833a0155fde6b4deda3c79055/tasks/2026-10-02-daily-plan-simulation-cleanup.zh-CN.md)及修订后的canonical规格继续。以下历史证据保留。

英文规范为权威输入；本文是 `2026-10-01-daily-plan.md` 的中文审阅副本。[SPEC-daily-plan](../specifications/monitoring/SPEC-daily-plan.zh-CN.md)。[任务清单](../../tasks/daily-plan-todo.zh-CN.md)。

## V01. 范围与当前状态

实现采用 Schema 4 / `daily-close-v1`、`daily-ta-v2` 和 `plan-extract-v7`。基本面和公告仅在用户生成计划时审核。原文保留为可见的排除背景，不授予监控事实、条件、买卖前置门槛、风险触发或执行阻断。技术结构/量能/指标条件与可交易/停牌事实仍在范围内。Schema 1/2/3、prompt v1–v6 和既有指数行为保持不变。

全新上下文 Astra/high 已审查全部未提交日线链路，Sol/high 修复并经独立复核后 F1–F11 全部关闭。源码冻结。协调代理的**最终完整离线后端回归已通过**，之后另行执行新增稀疏日历回归。此前中断或失败运行仍只作为历史证据。外部行情/AI/provider 调用由离线夹具和临时 SQLite 替代；完整可执行计划及事实证据是经合成人工审核的示例。用户未修改的原始模板保留为只有原文、参数缺失的负例。不认证真实供应商、通知投递、生产数据库、原文计划批准、提交、推送或部署。

## V02. 已执行验证

数量表示各命令实际收集的测试，含复用/导入夹具；不表示新增用例数量，重叠组不得相加。

| 验证 | 实际结果 |
|---|---|
| P04 兼容性：`test_explicit_conditions.py`、`test_explicit_rules.py`、`test_explicit_plan_review.py`、`test_ai_plan_extraction_v4.py`、`test_decision_engine.py` | 范围和审查修复后重跑，**351 passed / 3.75s**。 |
| `.venv/Scripts/python.exe -m pytest tests/unit -k daily -q` | **290 passed, 2403 deselected / 5.14s**。 |
| 下列 11 文件关键集成/领域组 | **88 passed / 23.55s**。最终日历分批/输入上限改动另由下述真实 composition 验证。 |
| `tests/integration/test_daily_accounting.py` | **2 passed / 0.99s**，逐股幂等与未知占额。 |
| `tests/integration/test_openapi_snapshot.py` | 同步双语指纹后 **14 passed / 8.80s**。 |
| 真实 `ProductionMonitorPipeline` composition | helper 验证公开 FACT/POSITION/REPORT 提交和 startup/realtime 两个恢复入口通过。Astra 独立复现最终稀疏日历反例通过：1500 日历天、1044 运行时日期、500 认证 bars/series 日期、无 blockers，原风险时序保留。其 production/boundary/condition 组 **12 passed / 9.04s**。 |
| 单独追加稀疏日历回归 | `tests/integration/test_daily_sparse_calendar_regression.py`：**1 passed, 1 warning / 5.94s**，Ruff 通过。完整运行结束后加入，证明50个认证假日强制750→1500，全部1533日历行落库，runtime1044日期完整，并保留series500 bars/500精确区间日期与内部缺日校验。与6065-test完整结果分开记录。 |
| 独立审查回归 | Astra 对 F4/F8、范围和历史上限修复 **63 passed / 12.32s**；最终生产复核后 F1–F11 全部关闭。 |
| 前端全量单元测试，协调代理最新重跑 | **60 files, 828 passed / 6.55s**。 |
| 前端类型/构建 | 协调代理最新重跑 `npm run type-check`、普通 build 与 runtime-status-preview build 均通过。 |
| 真实 Chrome | `web/tests/e2e/daily-plan.spec.ts` 和 `daily-review-batches.spec.ts` 均通过。风险流程实际操作技术/可交易证据表单，验证下一交易日时序及折叠的 40/60 内部扣账明细。分批流程保存 partial v1，通过真实链接 reload，再补第二批、另存不可变 v2、审核/启用。未观察到 console 或失败请求错误。 |
| 静态/契约 | `src tests` Ruff、compileall 和两版生成契约 `--check` 均通过。RuntimeInputs 的 3033 日期上限为内部契约，不改变下列公开指纹。 |
| 最终 `.venv/Scripts/python.exe -m pytest -m 'not live' -q` | **6065 passed, 1 skipped, 4 deselected, 1 warning / 3208.19s (0:53:28), exit0**；含 `test_backtest_acceptance.py`。 |

11 文件实际命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_history_regression.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_scope_http.py tests/integration/test_daily_orders_regression.py tests/integration/test_daily_production_reevaluation.py tests/integration/test_daily_supplement_batches.py tests/unit/test_daily_safety_boundaries.py tests/unit/test_daily_risk.py tests/unit/test_daily_source_exclusions.py tests/unit/test_daily_plan.py -q
```

两版生成快照均含 **60 paths = previous 51 + nine daily resources**：

- `openapi.json`：`69109c2620cca5c6467753a459e9c033faaa22862d7f68ba8dec19b8c717220b`。
- `openapi.runtime-status.json`：`027cafb61579a33e006bcf5874524c54e976715e166d6eea6029a5503513f484`。

## V03. DP-A01–DP-A20 验证映射

下表定位已执行定向证据，并由 V02 已完成全量门禁及单独追加回归支持。各行不认证真实市场或未完成的历史原文计划。Python 文件名相对 `tests/`，浏览器路径相对仓库。

| ID | 已执行证据与边界 |
|---|---|
| DP-A01 | P04 351-pass 兼容性组；`unit/test_daily_plan.py` codec/hash round trip；`unit/test_daily_extraction.py` 冻结版本及人工权限拒绝；6065-test全量 legacy/index 门禁已通过。 |
| DP-A02 | `unit/test_daily_extraction.py::test_historical_source_stays_partial_and_ai_cannot_supply_human_authority`；`unit/test_daily_review.py::test_partial_missing_condition_cannot_be_acknowledged_away`；Chrome 原文提取保留技术缺口。 |
| DP-A03 | `unit/test_daily_plan_review_service.py` 实际持久审核/启用/重启；`unit/test_daily_review.py` 语义修改使补充失效；`integration/test_daily_supplement_batches.py` 精确 digest/revision、重复不可变版本 409 与 reload 启用；两条 Chrome 流程。 |
| DP-A04 | `unit/test_daily_lifecycle.py::test_holiday_calendar_and_included_endpoints_do_not_allow_chasing`；`unit/test_daily_plan.py` 显式端点校验；`unit/test_daily_conditions.py::test_daily_all_any_missing_retains_each_evidence`；`integration/test_daily_scope_http.py` 拒绝三维退化成一个事实/指标或 ANY 成功路径绕过。 |
| DP-A05 | `integration/test_daily_plan_chain.py::test_daily_public_review_confirmation_next_session_and_expiry`；`unit/test_daily_safety_boundaries.py` 认证 bar 发布时间/cutoff 拒绝；Chrome 严重风险输入当日仍等待。 |
| DP-A06 | `unit/test_daily_lifecycle.py` 认证 Friday→Tuesday 假日与 Tuesday 收盘过期；`unit/test_daily_risk.py::test_both_reviewed_suspension_choices_have_distinct_resumption_behavior`；生产日历证明及最终稀疏日历恢复验证。 |
| DP-A07 | `integration/test_daily_history_regression.py::test_first_offline_close_recovers_only_current_next_session_ordinary_window`；`test_successor_expires_old_ready_before_accepting_later_independent_event` 验证原日期和旧 new-order 数量为零。 |
| DP-A08 | `integration/test_daily_plan_chain.py::test_same_completed_date_can_reevaluate_current_quote_reentry`；`integration/test_daily_plan_boundaries.py` 发送时报价年龄；`unit/test_daily_safety_boundaries.py` 风险、CORE/TAC、容量与未知输入阻断。 |
| DP-A09 | `integration/test_daily_plan_boundaries.py::test_partial_expiry_restart_later_close_requires_new_independent_evidence`；`integration/test_daily_history_regression.py` 后继版本过期及风险完成后独立事件；旧信号同窗权限保持永久撤销。 |
| DP-A10 | `integration/test_daily_plan_boundaries.py::test_real_sell_pressure_never_sells_core_and_today_buy_is_not_sellable`；safety 测试区分实际 CORE100/TAC0 与审核目标；Chrome 独立库存登记。 |
| DP-A11 | `integration/test_daily_accounting.py::test_partial_fill40_then60_uses_one_ledger_and_retry_never_restores`；链路实际部分报告/重启；`integration/test_daily_orders_regression.py` 同一 external order 的真实 BUY 和 SELL 40+60。这是成交/内部扣账，不是独立 40/60 股申报。 |
| DP-A12 | `unit/test_daily_safety_boundaries.py` actual200+pending100/max300 与自己完整 PENDING BUY/SELL；`integration/test_daily_orders_regression.py` 累计量、external identity 不可变、UNKNOWN 正余额锁定及余额零完成对账。 |
| DP-A13 | `unit/test_daily_risk.py::test_rebounding_second_close_still_confirms_then_third_session_exit`；`integration/test_daily_plan_chain.py::test_ordinary_rebound_below_line_confirms_then_executes_next_session`；生产漏收盘恢复保留 Tuesday 确认/Wednesday 执行。 |
| DP-A14 | `integration/test_daily_plan_chain.py::test_official_tradability_fact_immediately_reevaluates_without_fundamental_gate`；Chrome 实际 SEVERE_STRUCTURE + SEVERE_DETERIORATION 表单操作、缺一组/当日等待及下一交易日风险。 |
| DP-A15 | `unit/test_daily_scope_exclusion.py` 先合法基线再仅替换被排除 kind 的 domain/API/storage 及嵌套拒绝；`unit/test_daily_source_exclusions.py` 精确背景/混合余文/伪造排除拒绝；`integration/test_daily_scope_http.py` 实际 422 且 DB/outbox 不变、背景审核/启用及常见技术隐藏反例。 |
| DP-A16 | `unit/test_daily_risk_allocations.py` 优先最新已结算机动批次与保护 CORE；safety 仅受影响 bucket 组合目标、挂单 SELL 从目标扣账及 UNKNOWN 锁；history 重评/完成消费旧原因、保留审计并允许同日稍后新官方原因。 |
| DP-A17 | `unit/test_daily_conditions.py` QFQ/basis 拒绝及 histogram 为 v1 两倍、DIF/DEA 相同；`unit/test_daily_safety_boundaries.py` 未来 basis/receipt 拒绝；实际 production 当前 QFQ anchor；unit 和 HTTP preview 拒绝预热加偏移超过 500。 |
| DP-A18 | `integration/test_daily_plan_chain.py::test_activation_change_and_admission_failure_roll_back_all_daily_state`；实际报告重试/重启、`test_queued_risk_quantity_is_rechecked_after_actual_inventory_changes`；boundary 发送时年龄与 history 不同风险原因 outbox 测试。 |
| DP-A19 | `integration/test_daily_scope_http.py::test_background_rebound_review_preserves_same_technical_runtime_result`；`unit/test_daily_risk.py::test_excluded_fundamental_fact_does_not_confirm_any_technical_risk`；safety 已确认风险面对未知持仓/辅助证据；production 和 Chrome 验证可交易/T+1。背景修改仍先正常重审 source。 |
| DP-A20 | `web/tests/e2e/daily-plan.spec.ts`：paste→v7 gaps→supplement→save/review/activate→CORE100/TAC0→UNKNOWN/cancel→actual40+60→真实技术/官方证据表单→下一交易日退出→过期/原文失效。`daily-review-batches.spec.ts`：两批补充、preview/reload 恢复、不可变 v1→v2 及启用。无基本面表单或公告放行门槛。 |

## V04. 审查修复与实际限制

F1/F11 修复审核 bucket 范围/目标权限。F2 在变更前拒绝关联报告累计超量及 external order identity 修改；真实外部超限交易仍通过显式 unlinked 审计记录。F3 在后继版本检查前过期旧普通权限。F4 从可卖量及待减仓量同时扣除 SELL 占额；UNKNOWN 剩余量锁定执行，真实 40+60 对账后余额为零不会永久阻塞后续风险。F5 拒绝已知价格/买入与收盘跌破/停止加仓隐藏反例，同时保留真实库存叙述及可见技术余文。F6 验证 ALL/ANY 每条成功路径的三维独立证据。F7 用实际 production Clock 协议立即重评公开提交。F8 持久化已消费原因证据及精确 cutover 时间，永久撤销旧普通权限，实际达到目标转 FULFILLED，后续官方原因有独立 outbox 身份/发送时校验。F9 在同 digest preview/reload 保留已登记分批补充，重复不可变版本返回 409。F10 只恢复实际生效后的漏官方收盘，保留原 pending 风险线时序和当前 QFQ basis，并准备有界认证历史。

日线专用日历从 750 天开始，扩为 1500、最多 3000 天，以取得 500 个认证 open sessions；全部真实日历行按每批最多 1000 条在同一事务保存。运行时证明最多 3033 个日历日期（历史加未来 32 天，含端点）。每个 DailySeries 保留实际 bar 区间内完整日历/停牌证明，最多 500 bars 和 1000 dates；区间内部缺日仍拒绝。新上市/长期停牌/供应商不足绝不补造：所需条件维持 MISSING_INPUT，必要日历覆盖不足有明确原因。启用校验参数理论可支持，不新增实时历史请求。

自然语言排除采用有限 source-span 处理加显式人工范围选择，不证明任意文本语义或基本面真伪。AI 不能自证人工选择；已知混合/技术反例拒绝，技术余文仍可见并待审核。真实 40/60 部分成交保留账本并折叠为非独立委托明细。经审核申报规则控制新数量；CORE与TACTICAL分别申报和登记，内部批次仅在同一 bucket 合并。

## V05. 最终门禁与历史运行

固定源码的完整后端命令 `.venv/Scripts/python.exe -m pytest -m 'not live' -q` exit0：**6065 passed, 1 skipped, 4 deselected, 1 warning in3208.19s (0:53:28)**。协调代理保留日志 `$env:TEMP/daily-plan-final-backend.log`。唯一警告是已有的 TestClient/httpx StarletteDeprecationWarning，未修改依赖。新鲜独立审查及完整门禁均完成；DPT09/C4 已完成。

完整运行结束后，已独立审核的稀疏日历回归复制为 `tests/integration/test_daily_sparse_calendar_regression.py`，单独执行 `.venv/Scripts/python.exe -m pytest tests/integration/test_daily_sparse_calendar_regression.py -q --tb=short`：**1 passed, 1 warning in5.94s**；Ruff 通过。警告仍为同一已有 StarletteDeprecationWarning。生产源码保持冻结。证据是完整运行6065项，之后单独执行新增1项；**6066并不是完整测试结果**。

暂停前完整运行是 **5926 passed, 22 failed, 1 skipped, 4 deselected / 3324.78s**，并未通过。范围修订阶段 `-k daily` 的 639 collected tests 通过早于审查修复。之后 fast backend 载入了旧源码快照，主动停止，无最终结果。这些都不替代上述最终完整运行。
