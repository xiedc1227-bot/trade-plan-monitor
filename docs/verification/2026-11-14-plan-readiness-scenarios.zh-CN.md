# T19 — 原生就绪组合场景

## T19-V01 — 范围与实际结果

基线 HEAD：`9a04ca0`；代码基线：`4dd617f`（T18 已冻结，后续提交记录其验收／任务文档）。本片仅新增 `tests/integration/test_plan_readiness_scenarios.py` 和本双语报告。现有夹具、生产代码、生成契约及共享任务／报告文件均未改变。所有场景使用项目内临时 SQLite、现有来源／保存／审核／启用流程、离线 SDK 输入及真实所有者生产周期。未注入成功完成证明、风险证据、送达回执或成本簿。

最新已验证结果覆盖 **11 个不同用例：9 个新增组合和 2 个未改动邻近用例**。11 项批次得到 **8 passed、3 failed／71.12s**；三项 H04 失败源于新测试对公开证据引用的错误预期。修正后仅复测这三项：**3 passed／19.99s**。最终为 8+3 的集合，不是一次 11 项全绿运行，也不累加中间重复通过数。两轮均报告既有 Starlette/httpx 弃用警告。

| ID | `tests/integration/test_plan_readiness_scenarios.py` 中的新增节点 | 实际验收 |
| --- | --- | --- |
| T19-S01 | `test_missing_p3_cost_does_not_disable_independent_native_risk[capital_case0]` | `OPEN_COST_CAP` BUY 需要成本依据；原生资本／输入结论保持 UNKNOWN，且不存在成本簿。真实官方收盘周期产生严重风险 TRUE／CONFIRMED，并匹配原始 EVALUATION 出处。下一官方收盘周期产生当前 FALSE，同时保留 CONFIRMED、原始出处及 maintenance PASS。破坏义务 revision 撤销 maintenance；破坏原始 EVALUATION revision 还撤销出处。两个负例都保留独立有效的当前 FALSE。 |
| T19-S02 | `test_public_same_kind_leaves_remain_distinct_through_owned_readiness[delete/revision/content]`；`test_invalid_public_leaf_binding_cannot_supply_the_missing_sibling[owner/path/version]` | 公开登记 A=true 后 B 仍缺失；公开登记 B=false 后得到真实完整 FALSE。真实所有者周期保留准确原生路径和各自 FACT id；公开叶子引用该真实 EVALUATION。删除 B、修改 revision 或 payload 均撤销原结果。错误 owner／path 和未知版本不能补足 B，也不能新增 FACT。 |
| T19-S03 | `test_public_notification_receipts_remain_history_when_current_service_is_lost[expired/closed]` | 两条真实 TRUE 提醒仅完成一次受守卫的 IN_APP 送达时，通知轴保持 UNKNOWN。第二次真实 dispatcher 检查产生两个准确 DELIVERED 尝试及通知 PASS。原服务到期或 dispatcher 停止接收后，当前状态 UNKNOWN／无新鲜期，但原目标、创建时间和尝试保留为历史；`eligible` 始终为 null。 |

T19-S01 **没有**证明可执行 100 股卖出。15:21 时原始 `in_session` 守卫为 false（`runtime/daily_service.py`），因此原生风险动作仍为 `RISK_EXIT`、待退出 TACTICAL 100、当前可执行 TACTICAL 0，准确阻断为 `WAIT_FOR_CERTIFIED_TRADABILITY`。更早的官方人工证据不能越过闭市守卫。既有 `test_plan_readiness_risk_reads.py::test_real_fulfillment_skip_and_new_birth_keep_distinct_original_causes` 中下一交易日 10:05 数量正例继续作为独立既有证据（PMA-R86），不计作本轮 P3 组合的新执行结果。

## T19-V02 — 准备阶段与 GET 观察窗口

合法准备都发生在 `observation_only` **之外**：公开计划／来源审核与启用；公开 FACT 登记；通过离线类型化 SDK 输入取得股票／指数数据；原生官方／分钟周期；真实守卫下 dispatcher 送达；受控时钟变化；明确的临时记录破坏负例。公开 FACT 写入将不存在的后台监控重评延后，随后由测试显式驱动现有所有者 pipeline。不初始化成本簿。

每次新增公开 `GET /api/v1/plan-versions/{version_id}/monitor-readiness` 均经过真实 reader 及物理读取所有者。每个 GET 窗口内，SQL 拒绝业务／DDL 写入；守卫拒绝股票／指数采集、pipeline 准备／恢复／评估、资本／收益／执行重算、风险求值、发送和外部 HTTP。新测试的自动连接守卫全程拒绝非回环 socket 连接，允许 Windows 事件循环所需本机回环 socket pair。响应保留 `authorityGranted=false`、准确版本／内容身份和 1 MiB 上限。这些断言仅针对观察窗口，不把合法准备写入说成零写入。

## T19-V03 — MRD-S07 验收映射

“既有”指[原验收报告](2026-10-27-plan-monitor-assurance.zh-CN.md)中已验收证据，除明确标注外，**本轮未重跑**。以下具体节点相对于 `tests/`；各 R 段保留其原范围和限制。

| MRD-S07 场景 | 具体证据 | 重跑／限制 |
| --- | --- | --- |
| 健康的仅提醒计划、未知库存 | `unit/test_plan_readiness.py::test_alert_only_has_no_inventory_book_or_cost_dependency`；`integration/test_plan_readiness_profile_ownership.py::test_real_composition_supplies_current_readiness_in_both_profiles`（PMA-R65/R92） | 既有；纯策略与真实仅提醒 composition，不新增交易输入要求。 |
| 市值上限无成本簿 | `integration/test_plan_readiness_money_reads.py::test_market_value_inputs_do_not_require_or_create_a_cost_book`（PMA-R77） | 既有。 |
| 成本上限 BUY 缺成本、独立技术风险 SELL 义务 | T19-S01；`integration/test_plan_readiness_money_reads.py::test_nonempty_open_cost_inputs_do_not_invent_retained_basis` | 新增＋重跑邻近节点；保留闭市执行门槛。 |
| 完整 FALSE | T19-S02；`integration/test_plan_readiness_confirmation.py::test_complete_current_false_keeps_its_actual_result_and_bounded_context`（PMA-R72） | 新增 H04 组合；既有通用 FALSE 节点未重跑。 |
| 预计当日官方收盘 | `integration/test_plan_readiness_confirmation.py::test_daily_future_event_preserves_all_prior_leaves_and_exact_target`（PMA-R72） | 既有；不承诺未来必定采集。 |
| 缺少此前官方输入 | `unit/test_plan_readiness.py::test_expected_wait_requires_current_owner_calendar_target_and_previous_inputs[prior_missing-BLOCKED-MISSING_DATA]`；原完整准入失败证据（PMA-R71/R72） | 既有；模型守卫／准入证据，不新增此前交易日组合正例。 |
| 首次评估 | `integration/test_plan_readiness_confirmation.py::test_actual_new_activation_has_all_leaves_before_its_first_evaluation`（PMA-R72） | 既有。 |
| 报价／供应商／日历／证明过期 | `integration/test_plan_readiness_money_reads.py::test_expired_quote_is_unknown_and_get_never_renews_its_time`；`integration/test_plan_readiness_confirmation.py::test_future_daily_event_never_hides_a_changed_prior_dependency`；`integration/test_plan_readiness_reads.py::test_expired_progress_cannot_be_renewed_by_a_read`；采集所有者／供应商接受及撤销证据（PMA-R71/R72/R77） | 既有；已观察准入不能认证尚未观察到的供应商变化。 |
| 启用／runtime generation 变化 | `integration/test_plan_readiness_reads.py::test_read_context_change_does_not_certify_an_old_activation`；`integration/test_plan_readiness_profile_ownership.py::test_real_generation_replacement_never_borrows_old_current_proof`（PMA-R67/R92） | 既有；不复制所有者平台。 |
| CACHED／UNAVAILABLE | `unit/test_plan_readiness.py::test_noncurrent_observations_never_certify_runtime_or_false`；`integration/test_plan_readiness_reads.py::test_persisted_or_cached_rows_cannot_certify_current_owner`（PMA-R65/R67） | 既有；历史观察不能提供当前许可。 |
| 等待／重试／送达／抑制通知 | T19-S03；`integration/test_plan_readiness_notification_reads.py::test_actual_inflight_claim_is_not_reported_as_success`、`test_only_exact_latest_attempt_is_projected_with_closed_safe_fields`、`test_captured_native_classification_is_separate_from_current_channel_eligibility`（PMA-R88/R90） | 新增准确履行／服务失效组合；其余状态沿用既有证据，不推断当前发送资格。 |
| 已过期／已消耗信号 | `integration/test_plan_readiness_execution_reads.py::test_expired_evaluation_cannot_keep_old_executable_quantity_eligible`、`test_atomic_public_consumption_is_read_from_the_exact_signal_row`；`integration/test_plan_readiness_staged_waits.py::test_public_whole_fill_and_real_daily_false_can_wait_for_next_confirmation`（PMA-R77/R91） | 既有；同日分钟完成时间及未支持的人工分阶段等待仍未验收。 |
| 缺少升级 | `integration/test_plan_readiness_api.py::test_http_persisted_installations_preserve_original_unknown_and_review_states[upgrade-1]`（PMA-R93） | 既有；GET 不创建 assurance 存储。 |
| 并发读取／零副作用 | `integration/test_plan_readiness_profile_ownership.py::test_cancelled_observers_fill_one_lease_and_shutdown_drains_before_disposal`；`integration/test_plan_readiness_reads.py::test_real_read_has_no_business_sql_network_or_new_evaluation`（PMA-R67/R92）；所有新增 GET 窗口 | 既有并发证据＋新增受守卫观察；不新增容量结论。 |
| 无新 occurrence 时的报价／账本变化 | `integration/test_plan_readiness_money_reads.py::test_actual_book_changes_are_fenced_only_for_the_relevant_policy`、`test_actual_quote_loss_between_reads_cannot_reuse_the_old_quote`（PMA-R75/R77） | 既有；不合成 occurrence 或批准。 |
| 当前比较／义务维护／原始出处 | T19-S01；`integration/test_plan_readiness_risk_reads.py::test_exact_current_risk_revision_is_required_for_maintenance` | 新增＋重跑邻近节点；不把 ordinary skip 语义套到严重风险当前比较。 |
| H04 准确叶子及公开／UI 边界 | T19-S02；PMA-R97/R98 | 新增后端／公开组合；T18 UI 沿用既有证据，真实浏览器闭环仍属 T21。 |

## T19-V04 — 命令、失败与最终证据

从 `trade-plan-monitor/` 运行，临时路径均在项目内。Windows asyncio 使用已获自动审批、允许本机回环的执行环境；外部连接始终被拒绝。

```powershell
.\.venv\Scripts\python.exe -u -m pytest -q tests/integration/test_plan_readiness_scenarios.py tests/integration/test_plan_readiness_risk_reads.py::test_exact_current_risk_revision_is_required_for_maintenance tests/integration/test_plan_readiness_money_reads.py::test_nonempty_open_cost_inputs_do_not_invent_retained_basis --basetemp .pytest_cache/t19-scenarios-final --junitxml .pytest_cache/pma/t19-scenarios-final.xml
.\.venv\Scripts\python.exe -u -m pytest -q tests/integration/test_plan_readiness_scenarios.py::test_public_same_kind_leaves_remain_distinct_through_owned_readiness --basetemp .pytest_cache/t19-scenarios-h04-final --junitxml .pytest_cache/pma/t19-h04-final.xml
.\.venv\Scripts\python.exe -m ruff check tests/integration/test_plan_readiness_scenarios.py
.\.venv\Scripts\python.exe -m ruff format --check tests/integration/test_plan_readiness_scenarios.py
```

前两个 JUnit 文件分别保留 8-pass／3-fail 与修正后 3-pass 结果。此前 P3 焦点通过与之重叠，不另累加。未声称重跑 a1–a25 全量回归、浏览器、type/build 或 generator。

11 项批次后，唯一测试行为变更位于三项参数化 H04 用例共享的函数：将公开 `evidenceRefs` 中错误的 FACT id 包含／排除断言，替换为原始 EVALUATION id 非空及引用准确匹配的断言。之后未改变夹具、辅助函数、GET 守卫、其他测试行为或生产代码；仅新增／澄清双语报告。三项复测覆盖了这一完整行为差异。

JUnit SHA256：`t19-scenarios-final.xml` = `049a8431705909844de95d502eaebf2d1440c4835683fc7cb67138125681b5e2`；`t19-h04-final.xml` = `27a405f8b515fe9518d5df97caf2a7a83159a14e740ec53b2dfd7d8ebe8a75d4`。Ruff check/format、双语 ID／命令／代码标记一致性及空白检查均通过。四份生成契约文件保持 HEAD 原字节。

最终前的失败均为测试／环境问题，无生产修复：两轮受限环境运行停在 Windows socket-pair 准备；来源审核拒绝新编描述性语句（夹具现复用已接受来源值和准确 H04 要求）；修正严格 JSON／模型／UUID 及夹具路径假设。改变日线准入后复用旧分钟截止点没有产生新的官方比较；实际官方收盘周期解决了目标错误。错误假设包括风险 revision 会清除有效比较、`review_issues_json` 说明变化会撤销原权威、闭市证据可允许 100 股执行量、公开 `evidenceRefs` 含 FACT id；均已改为上述准确原生契约。原始 EVALUATION revision 的真实破坏负例已通过。未绕过来源审核、真值断言或原生阻断。中间 JUnit 和临时库保留于 `.pytest_cache/`。

## T19-V05 — 保留边界

本片验证已分派组合，不代表整个父任务 T19/T21 或最终发布完成。未进行真实供应商提取（仍为 **0/48**）、用户数据库／配置访问或迁移、外部发送、默认服务启动、推送或部署。原03/04/C05 仍阻断。未新增策略、worker、表、TTL、证明生产者或测试平台。H04 提醒／风险／重置／SIGNAL／Schema6–9 选择，以及未支持的分阶段／分钟边界保持不变。真实浏览器验收仍属 T21。由 root 负责审查、提交及共享任务／报告更新。
