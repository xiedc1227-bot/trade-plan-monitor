# 日线模拟清理验证 — 2026-10-02

规范英文版：`2026-10-02-daily-simulation-cleanup.md`；本文件供用户中文复核。状态：完成。当前范围内的清理、独立审查及离线验证门禁均已完成。

## V01. 范围与授权

用户已明确授权删除日线监测中的券商订单执行跟踪。监测不会下单，提醒不会改变仓位。单独的显式模拟操作要么完成当前授权的整笔数量，要么不改变任何记录。当前契约为[日线模拟清理](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/030075c4946bf34833a0155fde6b4deda3c79055/tasks/2026-10-02-daily-plan-simulation-cleanup.zh-CN.md)，并保留 [SPEC-daily-plan](../specifications/monitoring/SPEC-daily-plan.zh-CN.md) 的 DP-A01–DP-A20。

此前的 [2026-10-01 验证报告](2026-10-01-daily-plan.zh-CN.md)和[独立审查](2026-10-01-daily-plan-independent-review.zh-CN.md)记录的是已被替代的范围。6065 项通过仅作为历史证据，不是本次清理的结果。

## V02. 必须达成的结果

- 删除日线成交报告接口、券商订单标识与状态、部分成交、未知订单、占额、客户端批次扣减控件，以及对应的生成契约、界面和测试。
- 整笔模拟交易必须为正的 100 股整数倍；所有仓位数量只能为零或 100 股整数倍。普通信号消耗量只能为零或整笔计划数量。
- 模拟仓位与共享真实持仓表隔离。只保留 T+1 和策略扣减顺序所需的内部取得日期批次。
- 保留当前来源审核、技术事实、已确认风险义务、普通信号到期、CORE 保护、最大仓位、持久防重、通知发送资格及生产路径恢复。基本面仍退出监测。现有指数行为与 Schema 1/2/3 保持不变。
- 保留过时开发数据的证据，对不兼容的模拟操作明确拒绝；不把券商成交报告转换为模拟交易。

以下当前验收追踪指向永久测试；重叠文件不代表独立测试数量。完整测试完成状态单独记录在 V03。

| 验收标准 | 永久证据 |
|---|---|
| DP-A01 | 既有 `test_plan_domain.py`、`test_ai_plan_extraction_v4.py`、`test_explicit_plan_review.py`、旧版决策/回测测试；`test_daily_plan.py` 中的日线模型兼容性。 |
| DP-A02–03 | `test_daily_extraction.py::test_historical_source_stays_partial_and_ai_cannot_supply_human_authority`、`test_daily_review.py::test_complete_review_has_no_issues_and_semantic_edit_invalidates_supplements`、`test_daily_plan_chain.py` 的公开来源/审核/激活流程，以及两条 Chrome 流程。 |
| DP-A04 | `test_daily_plan.py::test_daily_zone_never_defaults_endpoints_or_accepts_empty_ticks`、`test_daily_conditions.py::test_daily_all_any_missing_retains_each_evidence`、`test_daily_lifecycle.py::test_holiday_calendar_and_included_endpoints_do_not_allow_chasing`。 |
| DP-A05–09 | `test_daily_lifecycle.py`、`test_daily_plan_chain.py::test_daily_public_review_confirmation_next_session_and_expiry`、`test_daily_plan_chain.py::test_same_completed_date_can_reevaluate_current_quote_reentry`、`test_daily_plan_boundaries.py::test_unconsumed_expiry_restart_later_close_requires_new_independent_evidence`。 |
| DP-A10 | `test_daily_plan_boundaries.py::test_real_sell_pressure_never_sells_core_and_complete_tactical_simulation`、`test_daily_safety_boundaries.py` 的普通 SELL/CORE/T+1 用例，以及 `test_daily_simulation.py` 的显式聚合初始化。 |
| DP-A11 | `test_daily_simulation.py::test_full_simulation_retry_restart_tplusone_and_no_actual_tables`、`test_invalid_or_partial_quantity_is_zero_mutation`、`test_planned200_partial100_is_rejected_with_zero_mutation`、`test_two_distinct_confirmation_keys_cannot_consume_one_signal`；完整模拟测试及 Chrome 中的提醒/确认不改仓位断言。 |
| DP-A12 | `test_daily_simulation.py::test_current200_plus_buy100_reaches_max300_and_blocks_independent_new_buy`、`test_removed_order_endpoint_and_editor_fields`、上述 T+1/完整模拟及普通 CORE 保护；`test_daily_simulation_contract.py`。 |
| DP-A13–14 | `test_daily_risk.py`、`test_daily_plan_chain.py::test_ordinary_rebound_below_line_confirms_then_executes_next_session`、`test_daily_safety_boundaries.py` 的技术严重风险时序，以及完整风险浏览器流程。 |
| DP-A15 | `test_daily_source_exclusions.py`、`test_daily_scope_exclusion.py`、`test_daily_scope_http.py` 的精确背景/来源/重新标记/嵌套/API 拒绝断言。 |
| DP-A16 | `test_daily_safety_boundaries.py::test_risk_aggregate_offer_preserves_core_and_tplusone_unavailable` 及同文件的审核目标/范围/未知输入用例、`test_daily_simulation.py::test_risk_simulation_keeps_tplusone_obligation_then_fulfills_without_reviving_buy`，以及 `test_daily_simulation_review_regressions.py` 的到期/重启流程。 |
| DP-A17 | `test_daily_conditions.py::test_raw_or_incoherent_daily_basis_cannot_be_admitted`、`test_v2_histogram_doubles_v1_without_changing_dif_dea`、`test_daily_plan.py::test_500_bar_contract_counts_condition_and_reference_offsets`、`test_daily_sparse_calendar_regression.py`。 |
| DP-A18 | `test_daily_simulation.py` 的回滚/并发键/幂等/重试/过时数据断言；`test_daily_simulation_review_regressions.py` 的当前事实发送校验、旧 outbox/ACTIVE 隔离、真实组合重启及模拟后失效事实。 |
| DP-A19 | `test_daily_scope_http.py::test_background_rebound_review_preserves_same_technical_runtime_result`、`test_daily_safety_boundaries.py::test_confirmed_technical_risk_survives_unknown_quantity_and_missing_auxiliary_close`、已确认风险缺少辅助数据用例，以及共享旧版/指数测试。 |
| DP-A20 | `web/tests/e2e/daily-plan.spec.ts`、`web/tests/e2e/daily-review-batches.spec.ts`、`test_daily_production_reevaluation.py`，以及前端 `dailySimulation.spec.ts`、`dailyAlertCompatibility.spec.ts`、`plansApi.spec.ts`。 |

上述后端文件位于 `tests/unit/` 或 `tests/integration/`；完整模块节点后省略模块名的测试仍属同一模块。C1–C7 永久修复用例位于 `tests/integration/test_daily_simulation_review_regressions.py`；C6 还在 `web/tests/unit/fixtures/` 保留真实审核前后 API 夹具，并由 `plansApi.spec.ts` 提供严格解析断言。

## V03. 验证结果

实现已冻结并完成独立审查，新的后台全量运行结束时有一处旧的精确字段测试期望失败。严格契约断言已修正并独立复核，其余离线测试随后复跑通过。最终覆盖门禁由此次通过的复跑与完整运行中已通过且未变更的八项容量/验收测试共同构成，不会沿用此前全量测试的数量。前端检查使用最后生成的契约及已修复的真实日线审核响应解析器。

| 检查 / 执行方 | 实际结果及边界 |
|---|---|
| Sol 界面代理：`npm run test -- --run` | 62 个文件，865 项通过，耗时 6.21s。原始日志：`../../../Temp/daily-simulation-ui-final-c6-reviewed/frontend-units-final-schema.log`。 |
| Sol 界面代理：`npm run type-check` | 退出码 0。原始日志：`../../../Temp/daily-simulation-ui-final-c6-reviewed/frontend-type-final-schema.log`。 |
| Sol 界面代理：`npm run build`、`npm run build:runtime-status-preview`、`npm run build:legacy-test` | 最终契约生成后按顺序运行，全部退出码 0；日志为同目录中的 `build-standard-final-schema.log`、`build-runtime-status-final-schema.log`、`build-legacy-test-final-schema.log`。 |
| Sol 界面代理：`npm run test:e2e -- tests/e2e/daily-plan.spec.ts tests/e2e/daily-review-batches.spec.ts --project=chrome` | 2 项通过，耗时 14.0s；审计未发现控制台警告/错误或请求失败。使用真实离线接口与临时 SQLite，覆盖整笔 BUY100、T+1、风险 SELL200、重试/拒绝及两批补充后刷新恢复。仅运行器出现 NO_COLOR 提示。原始日志：`../../../Temp/daily-simulation-ui-final-c6-reviewed/browser-daily-final-schema.log`。 |
| 协调者：`.venv/Scripts/python.exe -m ruff check --no-cache src tests` | 退出码 0，全部检查通过。 |
| 协调者：`.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 退出码 0；canonical monitor v2 与 compatibility monitor v1 的快照和类型均为当前版本。 |
| 协调者：清理基线与文档检查 | 选取的八份共享持仓/运行/指标/条件/范围/组合文件 SHA-256 未变；十对文档的稳定章节 ID 与复选状态相同。初次 122 个及最终 146 个本地 Markdown 链接全部有效，V02 的 18 个完整测试节点引用均存在，清理检查点全部完成。已在完整测试结束前另存源码/测试/资源冻结清单。最终 `git diff --check` 退出码 0，仅有既存 LF/CRLF 转换提示。 |
| 协调者：`.venv/Scripts/python.exe -m pytest -q -m "not live"` | 退出码 1：**6081 项通过，1 项失败，1 项跳过，4 项未选择，1 条警告，耗时 3279.22s（0:54:39）**。唯一失败为 `test_web_api.py::test_plan_versions_are_paginated_and_details_revalidate_canonical_identity`，精确摘要字段集合漏掉新增可空字段 `obsoleteReason`。完整容量组已通过。原始日志：`../../../Temp/daily-simulation-cleanup-final-backend.log`。 |
| Sol 实现代理：`.venv/Scripts/python.exe -m pytest tests/integration/test_web_api.py tests/integration/test_openapi_snapshot.py -q --tb=short` | 三行纯测试修正后 **160 项通过，1 条警告，耗时 19.70s**。精确集合加入 `obsoleteReason`，正常摘要/详情的值必须为 `None`。此前规范身份、分页、缺失资源和服务调用断言全部保留。定向 Ruff 通过，Astra 独立接受该差异。 |
| 协调者：`.venv/Scripts/python.exe -m pytest -q -m "not live" --ignore=tests/integration/test_backtest_acceptance.py` | 退出码 0：**6074 项通过，1 项跳过，4 项未选择，1 条警告，耗时 1204.62s（0:20:04）**。唯一未重跑文件包含刚才完整运行中已通过且未变更的八项容量/验收测试；另行收集确认共八项。原始日志：`../../../Temp/daily-simulation-cleanup-final-backend-recheck.log`。 |

通过的复跑结束后再次比较 851 份冻结文件，只发现 `tests/integration/test_web_api.py` 改变，没有冻结文件缺失。完整运行后，业务源码、生成契约和前端资源均未改变。后续验证按计划中纯测试修正不重复容量组的边界，保留此前已通过的容量证据。必需的离线覆盖门禁已满足。这不是单次全量全绿，相互重叠的定向数量不得相加。警告为既有 Starlette/httpx TestClient 弃用提示。

界面代理已检查浏览器截图，协调者另行检查了此前 BUY/T+1 与风险 200 股截图。最终浏览器证据和日志位于 `../../../Temp/daily-simulation-ui-final-c6-reviewed/`；永久断言保存在上述两份浏览器测试中。此前前端及浏览器运行属于中间证据，不与最终数量相加。

## V04. 独立审查

参见单独维护的[独立审查](2026-10-02-daily-simulation-independent-review.zh-CN.md)。Astra 在最终源码及解析器检查后独立关闭 C1–C7，未发现剩余实质问题。独立运行的 79 项日线组、89 项共享提醒组及 8 项最终数量检查均通过；真实审核前后接口响应通过实际 Vite SSR 解析器。相互重叠的定向数量不相加为全量结果。协调者已完成上述覆盖门禁，Astra 也独立接受了最后三行严格测试契约修正。

## V05. 运行边界

验证使用离线合成计划与供应商、临时 SQLite 数据库和本地浏览器夹具。本任务不涉及生产数据库、真实行情或 AI 供应商、外部通知、真实下单、提交、推送或部署。历史用户计划不会因这些测试而获准或激活。

## V06. 后续发布交接

2026-10-02，用户另行授权整理修改、清理无用测试文件，并提交、推送到 GitHub。删除了仅剩单个用例的冗余文件 `test_daily_risk_allocations.py`；其中有效的完整聚合执行量/CORE/T+1 断言原样合并到 `test_daily_safety_boundaries.py`，函数 AST 和断言完全一致。生命周期夹具移除了四个过时券商订单字段，没有删除有效回归。上文历史命令/结果保留原文件名；DP-A16 现已指向保留的测试。

此次纯测试合并后，**当前 23 份日线测试文件共 229 项通过，1 条既有警告，耗时 51.56s**，退出码 0。命令枚举 `tests/unit/test_daily*.py` 与 `tests/integration/test_daily*.py`，执行 `.venv/Scripts/python.exe -m pytest <files> -q --tb=short`；日志：`../../../Temp/daily-simulation-publication-tests.log`。`src tests` 的 Ruff 与两版生成契约检查再次通过。业务源码/资源及生成契约仍与已验收冻结版本相同。暂存空白检查另行清除了两份测试及一份 Vue 文件中的空行空白，Python AST 与 Vue 内容均不变，不需为未变的测试断言重复容量运行。运行数据、密钥、缓存、构建产物及临时复现均不进入发布内容；暂存路径和密钥模式检查通过。
