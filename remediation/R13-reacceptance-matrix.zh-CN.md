# R13 独立复验矩阵

日期2026-09-13；基准 `main/cc328adb4f79b9673705cb67e67520da2dfd667b` 加受保护工作树。英文稿为规范输入，本文件为中文对照。因 N05，完整离线验收 **NOT PASSED**。[报告](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/880c76fecfbf002bbc1b73d717c54d542429e7e8/docs/verification/R13-reacceptance.zh-CN.md)。

## M01. 证据规则

RUN 表示本任务实际执行；STATIC 表示仅检查代码；UNVERIFIED／NOT_RUN 表示未跨该边界执行验证。后端可信 fixture、fake 供应商的真实生产组合、普通无业务预置浏览器流程、route mock UI fixture 分层记录。测量探针通过不等于布局断言通过。首次30项与最终35项浏览器收集重叠，不累加。后端命令／收集／结果见 `evidence/R13-reacceptance/backend.log` 和 `backend.xml`，场景相关提取结果见 `backend-scenario-results.json`。测试数量和截图不证明真实 AI 准确、新鲜供应商数据或盈利。

下列路径相对于仓库。运行对象行号对照本工作树核实。`evidence/R13-reacceptance/final-journeys/` 保存本次普通 UI／AI 故障／恢复／重启记录；`final-sqlite-lineage.json` 核验事件／版本／revision／cutoff／resultHash 和首次 IN_APP 投递。Full backend RUN:2634 passed,1 Windows/POSIX skip,4 live deselected,1 existing warning;2572.52s.。

## M02. S01–S09 原始场景

| ID | 输入 → 预期 | 实际／证据层级 | 对象与已执行测试 |
| --- | --- | --- | --- |
| S01 | 原 ALL、价格990、已知100／100／上限300、前量[100,100,100,100,600]、当前200／299／300／301 → 仅300／301 BUY100，库存不变。 | RUN 独立生产预期；普通调度／浏览器299→0、300→BUY100。算术均量200不同于中位数100，不以 ANY 替代。 | `tests/integration/test_r13_independent_oracle.py:30` `test_literal_buy_uses_inclusive_price_and_arithmetic_mean`；`web/tests/e2e/explicit-sqlite.spec.ts:39`；`src/trade_plan_monitor/` 下 `runtime/explicit_service.py:115` `run_intraday`、`decision/explicit_conditions.py:198`。 |
| S02 | 买979／980／981／999／1000／1001与四量交叉；卖1079／1080／1081／1099／1100／1101；风险949／950／951 → 两端包含、倍率等值成立、仅949风险且null。 | RUN33个独立数值场景；条件／规则单元回归；实际浏览器等值及卖出／风险提醒。 | `tests/integration/test_r13_independent_oracle.py:30,144` 数值函数；`tests/unit/test_explicit_conditions.py:61,100`；`tests/unit/test_explicit_rules.py:283,346`。 |
| S03 | 未完成 bar 暂满足，最终收盘1001不满足；重试同一期限 → 不提前／误报／重复提醒。 | RUN 未完成期限返回空，完成目标保存无意图结果，同目标重试为空且0提醒。 | `tests/integration/test_r13_independent_oracle.py:192` `test_temporary_intrabar_satisfaction_then_failed_close_never_alerts`；`tests/integration/test_ten_symbol_runtime.py:356`；`src/trade_plan_monitor/runtime/production.py:514` `run_deadline`。 |
| S04 | 已知可卖100时 SELL100；5m收盘<950、库存未知／无关量缺失时纯风险 → 精确卖量、风险无数量、ACK非成交。 | RUN 生产调度、纯规则单元、真实 API／浏览器及 IN_APP。原浏览器10:15 SELL／10:20风险，确认后保持100。 | `tests/integration/test_explicit_runtime_production.py:697,764,817,902`；`tests/unit/test_explicit_rules.py:283,319,346,397,485`；`tests/integration/test_r13_channel_acceptance.py:30`。 |
| S05 | 未定义“企稳、放量”、未支持时序／确认、混合原文注入 → 不发明可执行政策，必需未解决／未支持问题保留。 | RUN 有界20例 semantic-v2 模拟供应商语料及对抗审核。原文缺项／处理确认仍阻断；通用语义和真实模型 NOT_RUN。 | `tests/unit/test_explicit_plan_semantic_acceptance.py:252,317,323,447,478`；`tests/integration/test_source_treatment_review_api.py:334,471,496,524,544`；`src/trade_plan_monitor/ai/review.py:622`。 |
| S06 | 已审核活动版；AI 非法JSON、重复字段、缺draft、503、截断、漏风险／错映射 → 无可执行替代，不破坏旧活动计划。 | RUN 普通浏览器激活后的六种真实 HTTP解析／公开API／SQLite失败：五 INVALID_OUTPUT、一 PROVIDER_ERROR；旧活动内容／库存不变。 | `web/tests/e2e/r13-ai-faults.spec.ts:39`；`tests/browser/r13_fault_server.py`；`final-journeys/faults/r13-faults.json`；prompt／parser 单元契约。 |
| S07 | 陈旧／当前响应缺失、乱序／重复／未来／缺口／partial、供应商恢复失败、无关可选指数不可用 → 不伪造条件，仅阻断依赖范围。 | RUN 生产取数／分范围健康及显式窗口回归。真实浏览器收到 BUY、重连后 SELL、再风险，无手动刷新；无关指数不可用时原计划仍执行。真实供应商断线 NOT_RUN。 | `tests/integration/test_ten_symbol_runtime.py:388,435,505,587,673,853,887,922,1840,1970,2172`；`tests/unit/test_explicit_conditions.py:125,147,200`；`web/tests/e2e/r13-live-stream.spec.ts:39`；`src/trade_plan_monitor/runtime/symbol_service.py:141` `SymbolService`。 |
| S08 | 重复求值／事务重试、第二次enqueue失败、服务重建、真实OS退出重启、阅读／ACK → 原子身份、不轰炸、持仓不变、后续合法出现仍可提醒。 | RUN 事务／重建服务回归加实际无业务seed的OS重启。独立补充 EACH_QUALIFYING_BAR，新PID后 BUY10:10仍一条、同规则BUY10:30正常出现。已查流程13事件均首次投递，库存独立。强制退出不证明优雅关闭／掉电／外部exactly-once。 | `tests/integration/test_explicit_decision_persistence.py:181,228,263`；`tests/integration/test_explicit_runtime_production.py:976`；`web/tests/e2e/r13-active-process-restart.spec.ts:11`；`src/trade_plan_monitor/runtime/explicit_service.py:115,167`；`final-sqlite-lineage.json`。 |
| S09 | 新审核版、公开停用、次日到期、延迟旧工作／消息 → 指针／revision防护，旧提醒非当前，不产生旧计划新动作。 | RUN 原三API生命周期用例、运行／提交／投递防护及三种实际OS状态转换。替换后版本3产生自身SELL，停用／到期无后续事件。 | `tests/integration/test_r13_independent_oracle.py:99` `test_retained_explicit_alert_is_not_current_after_lifecycle_change`；`tests/integration/test_explicit_runtime_production.py:1143,1216,1340,1362`；`web/tests/e2e/r13-active-process-restart.spec.ts:11`；`src/trade_plan_monitor/notifications/outbox.py:290,307,331`。 |

## M03. F01–F09 原始问题

| ID | 输入／闭合预期 | 实际状态与限制 | 本次测试／检查对象 |
| --- | --- | --- | --- |
| F01 P0 | 过期DATE_RANGE／TRADING_DAY及重启 → 无新有效买卖／风险。 | 已测离线有效期范围闭合；选择／提交／展示及次日OS进程用例通过。真实供应商到期 NOT_RUN。 | S09；`test_explicit_runtime_production.py:1143`；`src/trade_plan_monitor/` 下 `domain/plan_models.py:162` `activation_is_eligible_on`。 |
| F02 P1 | snapshot→alert／cursor跳转／浏览器重连 → 自动刷新权威提醒，不漏行。 | 离线闭合；真实未mock业务API流及原恢复变体通过。IN_APP兼容另见N01。 | `web/tests/e2e/r13-live-stream.spec.ts:39`；`web/src/composables/useMonitorStream.ts:117,154`；`final-journeys/stream/r13-stream.json`。 |
| F03 P1 | 空／伪造审核、任意原文归因、漏原文处理 → 不得获得当前可执行批准。 | 在有限服务端审核契约内闭合；任意自然语言等价性仍需人工审阅，真实AI NOT_RUN。 | `tests/integration/test_source_treatment_review_api.py:471,496,524,544`；`tests/integration/test_explicit_plan_review_api.py`；`src/trade_plan_monitor/web/plan_service.py:653`。 |
| F04 P1 | 改价格／数量／逻辑 → 旧审核失效，仅精确重新审核能激活。 | 离线闭合；版本3–8清空审核，各自独立拒绝旧reviewId／contentHash／expectedRevision409，当前审核激活版本5／8。 | `web/tests/e2e/r13-corrections.spec.ts:39`；`src/trade_plan_monitor/web/plan_service.py:653`；`final-journeys/corrections/r13-corrections.json`。 |
| F05 P1 | 已声明人工风险unknown→clear，绑定plan／date／revision且重启 → 普通持久输入可用；未声明则不强制。 | 已声明输入的离线范围闭合，原计划不依赖该输入。 | `tests/integration/test_manual_event_risk.py:45,133,185`；`web/tests/e2e/symbol-detail.spec.ts:468`；`src/trade_plan_monitor/runtime/explicit_service.py:167` 的 R07 消费。 |
| F06 P1 | 完整原文算术均量／普通卖出／纯5m风险 → 可表达执行，不偷换episode／TACTICAL／日收盘。 | 原始有限离线语义、公开流程及可见提醒闭合；未支持语义仍阻断，完整产品门禁N05未闭合。 | S01／S02／S04；`web/tests/e2e/explicit-sqlite.spec.ts:39`；`src/trade_plan_monitor/decision/explicit_rules.py:269`。 |
| F07 P1 | ANY一支满足、无关支不满足／未知 → 不增加隐藏全局策略阻断；原ALL仍需两支。 | 已测旧版和显式逻辑契约闭合。独立改ANY仅价格满足产生BUY200，另测原ALL300预期通过。 | `tests/unit/test_decision_engine.py:5291`；`tests/unit/test_explicit_rules.py:455,485`；`web/tests/e2e/r13-corrections.spec.ts:39`。 |
| F08 P1 | 普通价格／数量／ALL↔ANY改两轮 → 字段仍可编辑，structure／.type映射一致，无JSON编辑即可再审核执行。 | 既有字段／运算符编辑范围闭合；未支持NOT不生成后继。任意规则树插入／重挂仍不支持。 | `web/tests/e2e/r13-corrections.spec.ts:39`；`web/src/components/plans/ExplicitPlanSupplementForm.vue`；对应组件测试；N02。 |
| F09 P2 | 历史prompt／schema／codec及OpenAPI预期摘要 → 不发生无版本漂移或重释历史。 | 离线冻结防护闭合；OpenAPI仍50paths=35live+15backtest，摘要 `1aed810d751d7c1dee623b1eb6afb7f2538928c8ea091bdf79027dd34e58951a`。 | 完整prompt／schema／历史兼容／OpenAPI契约；`tests/integration/test_source_treatment_legacy_compatibility.py`; `tests/integration/test_openapi_snapshot.py:117,145,214`；前端生成检查；未改预期hash。 |

## M04. N01–N05 整改与残留

| ID | 输入 → 预期 | 本次实际／状态 | 证据 |
| --- | --- | --- | --- |
| N01 P1 | 严格旧／显式事件联合、BUY／SELL／null风险 → 必选渠道接受，非法对象仍拒绝。 | 离线 CLOSED。六渠道测试、原浏览器三事件、独立核查13事件均首次IN_APP DELIVERED，浏览器可见另行断言。 | `tests/integration/test_r13_channel_acceptance.py:30,94,184`；`src/trade_plan_monitor/notifications/channels.py:178,348`；`final-sqlite-lineage.json`。 |
| N02 P1 | SOURCE和已改USER_SUPPLEMENT，价格／数量／ALL↔ANY两轮 → 当前审核与普通激活执行。 | 离线 CLOSED。版本5 ANY／BUY200及8 ALL／BUY100；审核后18个单独旧值防护请求409，另有审核前原旧请求；NOT仍拒绝。 | `web/tests/e2e/r13-corrections.spec.ts:39`；`final-journeys/corrections/`；`final-sqlite-lineage.json`。 |
| N03 P2 | 个股详情320／768／1024／1440、200%文字，两日期输入fill／focus → 有界可操作、axe合规。 | route-mock UI范围 CLOSED，响应式及窄屏输入在初次和最终完整门禁均通过；不代表全产品响应式通过。 | `web/tests/e2e/symbol-detail.spec.ts:323,377`；当前详情／库存／风险局部CSS；完整browser trace。 |
| N04 | 精确ACTIVE／dashboard／inventory／manual-risk fixture，安装空服务退出重启，稳定bar／颜色观测 → fixture／阶段断言真实，无多余进程／密钥残留。 | 指定fixture／安装空库生命周期范围 CLOSED；相关用例均通过，原dashboard hunk不变，旧颜色失败仍保留历史。活动OS重启为另加S08证据，不倒算为N04已有证明。 | `web/tests/e2e/dashboard.spec.ts:251,356,403,466`；`symbol-detail.spec.ts:408`；`production-restart.spec.ts:71`；最终完整browser。 |
| N05 P2 | 必选回测四宽度／200%门禁 → document scrollWidth≤clientWidth且控件可用。 | OPEN，已确认。初次及最终完整门禁失败，未改专项5／5失败；320px四页稳定宽338／476／617／411，有意内部滚动导航不是唯一来源。 | `web/tests/e2e/backtests.spec.ts:813` 未改门禁及新增测量探针；`backtest-layout-measurements.json`、截图／trace；`BacktestRunsView.vue:110`、`DatasetScopeForm.vue:411,418,444`及相关视图；需最小CSS整改和未改门禁完整复验。 |

## M05. 边界与最终建议

S01–S09、F01–F09 仅在明确已执行离线契约内闭合，N01–N04仅闭合各自范围。N05阻断完整离线验收／C6建议。R14、真实模型语义、实际市场时序、真实供应商断线恢复及隔离浏览器之外的用户送达仍NOT_RUN。强制本地进程退出单独标注，不以安装空库启动或服务重建替代；不宣称真实持仓、成交、外部投递或盈利结论。

自编源码／文档／JSON采用限定范围空白检查；原始运行日志保留录制时空白。
