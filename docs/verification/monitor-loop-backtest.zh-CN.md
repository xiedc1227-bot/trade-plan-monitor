# 验证记录：监控闭环回测

英文权威版；中文审阅副本：[monitor-loop-backtest.zh-CN.md](monitor-loop-backtest.zh-CN.md)。更新于 2026-10-09，Asia/Shanghai。本记录为已执行的部分证据，不是最终验收。基线：`main` `e95de03`，保留已有未提交设计与盛新研究文件。实施已获授权；用户随后于 2026-10-07 授权清理、提交并推送至 GitHub。付费请求、生产迁移和部署仍在范围外。

当前证据见 MV18–MV28：ML-T01–ML-T05、ML-T07/ML-T08/ML-T10/ML-T11/ML-T12/ML-T13/ML-T14/ML-T15/ML-T16 与 ML-C01/ML-C02/ML-C03/ML-C04/ML-C05 已实现并验证。MV20/MV21 记录私有准备持久化及完整提取，MV22 增加自有提取及实际排空前保留全局准备准入，MV23 验证明确语义审核及单份不可变清单，MV24 验证配假 AI 的准备 HTTP/能力集成；MV25 发布两种准备契约 profile，保留旧契约并记录待批准门禁。MV26 通过隔离真实 Chrome 界面验证单原文输入/进度组件及请求/轮询保护。MV27 通过真实挂载 HTTP 配假 AI 验证精确准备审核、冻结凭据及创建页面。MV18/MV19 记录任务准入及单计划循环。MV17 记录单计划范围，MV16 原子结算，MV15 私有提醒，MV14 输入/共用模拟。MV18 覆盖此前租约过期释放任务槽及准备并发选择。MV01–MV26 保留为历史证据；MV11 启动解耦 PASS，以及已验证 ML-T30–ML-T34/ML-C12 保持。耐久数据集输入/回放工作线程/UI/报告集成及最终验收仍待完成，以下历史不表示当前阻断状态。

## MV01. 已实现边界

ML-T30–ML-T32 定义无副作用生命周期值及有限观察预算，启动时登记未使用管理器，拆分元数据与执行能力，共用首次初始化，并拥有有界准备/元数据线程。取消等待者不会取消共用准备或物理查询。初始化较慢返回带 `Retry-After` 的 503；失败后须明确重试。仅执行初始化失败时，保留已健康的元数据读取并阻止执行；关闭时撤销该读取能力。晚到工作在清理期间继续受归属管理，替换须等待物理排空。用户明确授权了 `web/errors.py` 中允许 503 `Retry-After` 的窄改动。

ML-T33 工作通过当前会话授权任务 ID 约束生产协调器。仅真正新建的耐久任务准入授予权限；重放旧回执或命中旧排队操作不授权。历史读取和执行就绪均保持积压休眠。明确选中恢复保留租约/领取代次，普通任务失败不降级健康服务。取消/发布保护仍由现有仓库执行。关闭超时保留物理 future/执行器，工作线程返回后继续清理。

ML-T33 仍未勾选，等待用户决定过期历史 RUNNING/CANCEL_REQUESTED 任务是否继续占用既有单槽。ML-T34 仍待完成既有有限工作/存储防护回归及历史同步本地限速。2026-10-07 用户移除 AI 提取隔离阻塞项，并要求最小行情范围：不新增全局额度、正式容量预留或跨业务调度，不要求新增 AI/监测连接。原行情连接范围问题不再阻塞本项。ML-C12 和全部业务/UI/负载任务仍待完成。不新增回测 CLI、子进程或每线程硬 CPU/内存保证。

## MV02. 已执行检查

全部命令从 `trade-plan-monitor/` 执行；使用虚拟供应商和临时存储。不启动真实监控或付费供应商调用。

| 检查 | 命令 | 实际结果 |
|---|---|---|
| 基线单元/契约 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m "not live"` | 2744 passed，4 deselected。 |
| 更新后单元/契约 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m "not live"` | 最终能力修正后为 2758 passed，4 deselected。 |
| ML-T30 | `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py -q -m "not live"` | 最初 11 passed；最终针对性检查包含全部 14 项案例。 |
| 启动、归属与组合 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py tests/integration/test_monitor_production_composition.py -q -m "not live"` | 新增元数据归属案例之前为 55 passed，1 skipped；新增案例在针对性 8 项检查中通过。 |
| 恢复、协调器与任务 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py tests/integration/test_backtest_production_composition.py -q -m "not live"` | 新增生产历史/过期领取案例之前为 61 passed，1 skipped；扩展后恢复文件的 5 项案例随后全部通过。 |
| 最终能力与组合回归 | `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_production_composition.py tests/integration/test_monitor_production_composition.py -q -m "not live"` | 修正执行失败后元数据保留能力后为 76 passed，1 skipped。新增回归测试在修正前先失败。 |
| 静态检查 | `.venv/Scripts/python.exe -m ruff check src tests scripts` | 通过。 |
| 两组生成契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | canonical monitor v2 与 compatibility monitor v1 均通过；生成文件未变。 |
| 授权变异 | 临时允许空授权集合领取任意排队任务，运行 `tests/integration/test_backtest_thread_recovery.py::test_scoped_claim_leaves_old_queue_dormant_and_selected_resume_is_explicit`。 | 测试按要求失败，已还原原始源码字节。 |

基线选定集成检查为 97 passed、1 skipped，仅已有 OpenAPI 批准检查失败。扩大后的选定回归在最终执行失败元数据修正前为 281 passed、1 skipped，仅同一批准检查失败，用时 113.57 秒；随后受影响回归的结果已列于上表。这些检查不代表未实现验收项完成。保留现有 Starlette/httpx 弃用警告及平台跳过，不降低测试掩盖结果。

扩大后的选定回归命令：

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_backtest_compatibility.py tests/integration/test_openapi_snapshot.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_production_composition.py tests/integration/test_monitor_production_composition.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py tests/integration/test_backtest_publication.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_exports.py -q -m "not live"
```

## MV03. 已有批准不一致

`tests/integration/test_openapi_snapshot.py::test_openapi_change_requires_bilingual_spec_approval` 在生命周期改动前后均失败。实际快照 SHA-256 为 `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`；双语 `SPEC-unified-plan` 批准记录为 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`。生成快照/类型仍与挂载路由一致，未改批准记录和测试。ML-T29 须审阅最终具体接口差异后才可更新批准摘要。

## MV04. 待完成证据与决策

先解决过期历史活动领取行为，再推进依赖的 ML-T33 改动。在 ML-T34 回归既有有限工作/存储领域防护，实施本地固定同步限速，完成 ML-C12 后推进业务。全局额度设计、容量预留、共用预算认证及额外监测/AI 连接已从本范围移除。低频 AI 提取保留既有防护和批内顺序执行，不作为隔离阻塞项。服务控制路由及生成状态/UI 契约属于 ML-T35/ML-T39/ML-T36。

尚未运行 Windows ML-T37 基线/负载阶段（各 10 分钟、各至少 1000 次状态请求）、p95/p99 门槛和完整故障矩阵。尚未开始页面改动或浏览器验证。原文准备、首份计划账户初始化、每日更新、确定性闭环回放及闭环原子发布仍待完成。同进程/原生崩溃、内存耗尽、磁盘竞争和不协作线程限制仍是已接受边界，不是已测量保证。

## MV05. AI 决策与同步本地限速范围

2026-10-07 用户确认 AI 提取不是资源隔离阻塞项。普通提取已具备单并发槽和幂等回执（`web/ai_service.py`），保留这些防护及准备批次的顺序执行。本次仅修改双语设计/任务记录，不接通供应商、不发真实请求、不改运行代码。

`web/app.py` 中挂载的监测/回测工厂接收同一 `config_path`，各自使用配置的 Tushare 账号构造独立传输。历史同步按缺失股票/交易日循环获取分钟数据（`backtest/sync.py`），使用 `stk_mins`，并调用 `daily`、`trade_cal` 和 `stk_limit`（`market_data/tushare_historical.py`）；当前 inline 控制器直接调用供应商，没有节奏限制。监测已有有界优先/节奏控制，也使用这些参考接口（`runtime/production.py`、`runtime/request_control.py`）。这些发现支持批量同步的简单本地限速，不构成监测竞争的实测证据，也不作为共用额度框架的前置要求。

[官方历史分钟文档](https://tushare.pro/document/2?doc_id=370) 当前标明每分钟 500 次、滚动 24 小时 300,000 次。[官方权限表](https://tushare.pro/document/2?doc_id=290) 分别列出历史与实时分钟权限。这些来源不能证明 `stk_mins` 与 `rt_min` 共用一个合并额度。尚未测量用户实际权限、更广额度范围、实际请求频率、限流及监测延迟影响。不据此推断额度耗尽，也不声明供应商额度隔离保证。

收窄后的本项保留单活跃同步、外部请求开始之间的本地固定间隔（沿用已有 1.25 秒节奏值）、协作取消及既有超时/错误映射。不规划新增重试策略、全局额度池、容量预留、跨业务调度器、共用冷却、账号/接口注册表、动态分配、额度页面或通用准入模块。改动限定于 `backtest/sync.py` 及虚拟间隔/取消测试，正式监测和 AI 请求控制保留既有行为。移除计划中的 `backtest/capability_admission.py` 和 `tests/integration/test_backtest_provider_admission.py`，改用计划中的针对性 `tests/integration/test_backtest_sync_pacing.py`。本次为范围调整，不是实现证据。保留其他资源保护及既有离线负载阈值。

## MV06. 导出兼容与并行范围

2026-10-07 用户确认导出只保留兼容，不新增开发。既有按运行 SUMMARY_JSON/FILLS_CSV 导出保留契约、字节、分块和断开行为。移除计划中的闭环导出支持/测试、新下载 UI、批量打包、导出任务/调度器及导出参与重型操作互斥要求。ML-T22 只新增分页闭环结果/明细 API，既有导出测试保留为兼容回归。浏览器/负载范围不增加导出流程。本次只修改双语设计/任务记录，未修改运行代码，也未新增应用测试结果。

既有耐久任务仓库通过单活跃槽串行执行同步/验证/回放（`backtest/jobs/repository.py`）。全局准备/回放互斥原为减少并发 CPU/内存/磁盘压力而提出；尚未确认实测并行操作故障。按照最小范围方向，从本次范围移除额外互斥，不新增跨操作锁、队列或调度层。保留既有任务槽及批次级修订/冻结保护。同一批审核/冻结后才可回放属于输入前置条件。IP04 要求已提交不可变输入独立于可变准备，因此准备另一批与回放已冻结运行没有必然业务冲突。这不构成硬资源隔离保证，也不表示待完成准备流程已实现。

## MV07. 取消磁盘/日志预算与最新 30 个保留策略

2026-10-07 用户因部署磁盘余量充足取消磁盘/日志预算，要求历史回测记录只保留 30 个，超额删除。从 ML-T34/ML-A23/ML17 移除保留/临时数据字节上限、日志额度/轮转开发及空闲容量准入阈值。普通存储错误处理及既有存储领域防护保留；后续存储决策移除新增深度文件身份检查。未检查或修改生产存储或日志配置。

已授权结果策略合并所有支持模式/状态，总共保留最新 30 个 materialized 历史运行，按发布/保留时间及 run_id 降序。新结果发布后触发既有有界维护，删除最旧超额整份运行及其摘要/成交/详情。置顶不豁免总数上限。保留运行及任务保护共用快照/输入/数据集，排队/运行中任务及其暂存不是删除对象。既有任务/幂等及诊断/暂存过期规则不变。不新增调度器、额度框架或导出功能。此项归 ML-T21，不作为隔离前置条件。

当前 `backtest/results.py` 使用 `_SUCCESS_DETAIL_RUNS = 100`、`_SUCCESS_DETAIL_DAYS = 90` 及 `_DIAGNOSTIC_DETAIL_DAYS = 14`，成功运行数量限制清理的是详情，而非整份摘要/成交。最新 30 个整份运行保留策略已记录到双语 `SPEC-backtest-results` 及设计/方案/任务，但尚未实现或验证为运行行为。未删除用户历史数据，不声明新增应用测试结果。

## MV08. 仅保留既有存储保护与压力评估

2026-10-07 用户采用保留既有存储防护、不深入开发的建议。保留独立默认数据库、路径规范化及 `backtest/storage_guard.py` 对正式监测表和行情/结果领域混用的拒绝。从 ML-A22/ML17/ML-T34 移除新增深度 Windows 文件身份、junction/硬链接及跨文件别名框架要求。此前已执行 `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_results.py -q -k "storage_domains_reject_aliases_and_live_tables or stores_reject_each_plan_web_state_table" -m "not live"`，结果为 3 passed、14 deselected，用时 1.37 秒。本次范围更新只修改双语文档，不声称穷尽别名保护。

内存/压力评估：当前研究运行器累计决策事件，但到 70,000 个事件时拒绝评估；任务有 100 个排队上限及单活跃槽；自有准备/元数据线程限制未完成物理工作；结果读取/导出有界分批。这些是具体已有的有限工作防护。此前 ML17 范围曾提出测量内存/CPU/监控延迟，压力下拒绝或协作取消回测。尚未发现生产压力控制器或校准后的压力阈值，ML-T37 负载证据仍未执行。同进程内存耗尽/CPU 竞争属于已接受风险；此次评估未证明新增压力准入系统的必要性；后续 MV09 用户决策移除该拟议开发。

## MV09. 已采用有限工作范围与剩余保护项

2026-10-07 用户采用保留既有有限工作防护的建议，取消新增动态内存/CPU 压力控制器、采样驱动的阈值及压力触发的准入/取消。移除计划中的 `backtest/resource_control.py` 及通用 `test_backtest_resource_boundaries.py`。ML-T34 现仅两个主要文件：`backtest/sync.py` 及针对性 `test_backtest_sync_pacing.py`，既有防护测试保留为回归检查。保留离线负载验证以发现实际竞争、普通协作取消及已接受的同进程边界。本次仅修改双语文档，不声明新增运行保护或测试结果。

| 剩余项目 | 任务 | 当前状态及待完成内容 |
|---|---|---|
| 明确积压恢复与安全取消 | ML-T33 | 会话授权及物理排空检查已通过；过期历史 RUNNING/CANCEL_REQUESTED 是否占用既有单槽，仍待用户决定后收尾。 |
| 历史同步本地限速 | ML-T34 | 未实现：保留串行同步，仅增加 1.25 秒请求开始间隔、可取消等待及虚拟调用测试。不新增全局额度或监测模块改动。 |
| 最新 30 个整份历史结果 | ML-T21 | 未实现：发布后触发有界、最旧优先的整份结果清理，保护活动任务及共用引用。不作为隔离前置条件。 |
| 状态/停止/重试/选中恢复控制及清晰 UI | ML-T35, ML-T39, ML-T36 | 公开控制、生成契约及页面反馈待完成；打开历史不得恢复积压。既有契约批准不一致留待明确最终审阅。 |
| 故障/负载验证与操作指导 | ML-T37, ML-T38 | 完成剩余 Windows 离线故障/负载检查及双语停止/恢复指导；已有部分测试不代表完整验收。 |

已完成核心保护：ML-T30–ML-T32/ML-C11 的无副作用启动、受保护首次准备、元数据/执行分离、局部初始化失败、有界线程归属及晚到工作保留。既有单执行、队列/事件上限、分页/分批读取及存储领域防护保留，不新增通用资源框架。已移除开发：全局 AI/供应商额度、预留监测容量、跨操作准备/回放/导出互斥、新导出、磁盘/日志预算、深度存储别名检查及动态压力控制。完整监控闭环业务/UI 属于另行待完成工作，此清单仅覆盖保护。

## MV10. 完整验收缺口清单

截至 2026-10-07，既有 39 项任务切片中，3 项完成（ML-T30–ML-T32）、1 项部分完成（ML-T33）、35 项待完成。这描述的是新监控闭环交付，不代表既有产品完成百分比。此前 MV09 只列保护项，不是完整交付缺口。以下七组恰好覆盖全部 36 项未完成任务，每项只归一组，不新增要求或任务 ID。

| 既有工作组 | 任务 | 当前缺口 | 完成证据 |
|---|---|---|---|
| 隔离收尾与本地同步限速 | ML-T33–ML-T34 | ML-T33 部分实现，过期历史活动任务占槽规则未定。本地 1.25 秒同步间隔未实现。 | 仅明确操作才处理积压，取消/发布/租约竞态、排空后替换及虚拟调用间隔/取消检查通过。 |
| 计划准备与审核 | ML-T07–ML-T15 | 新流程的持久批次准备、带前版上下文的顺序提取、修订绑定审核及上传/进度/日历页面未实现。 | 实际 UI/API 支持上传、顺序提取、修改/重试、原文/账户审核及冻结已批准计划链，不修改正式计划。AI 额度管理已排除，但提取业务功能仍在范围内。 |
| 确定性闭环回放与提交 | ML-T01–ML-T06, ML-T16–ML-T20 | 新冻结输入/时间截止、期初账户、提醒、模拟响应、原子账本反馈、每日计划延续/替换、任务分派及因果投影待完成。 | 无未来交易脚本，买卖/账户转换符合独立预期；无未来证据、重复成交、部分提交或结束日期漂移。不支持的原文条款保持可见。 |
| 发布、结果页面与最新 30 个保留 | ML-T21–ML-T25 | 新闭环发布/结果 API、运行表单/时间线/账户视图及最新 30 个整份清理待完成。 | 可查看完整保留结果，失败/取消不发布已完成部分报告；安全删除最旧超额整份运行，保留旧结果的导出兼容。 |
| 服务控制与页面反馈 | ML-T35, ML-T36, ML-T39 | 状态/停止/重试/选中恢复公开控制、生成传输契约及首次使用/降级 UI 待完成。 | 实际页面如实显示服务/任务状态并提供局部恢复；历史/预取不恢复工作，监控页面保持可用。 |
| 集成、浏览器及 Windows 负载验收 | ML-T26, ML-T27, ML-T37 | 新闭环一致性/故障覆盖、真实挂载 UI/API 端到端流程及完整 Windows 负载未执行。 | 浏览器上传→审核→运行→结果；虚拟供应商下 10 分钟 10 只股票监测基线加 10 分钟回测负载，每阶段至少 1,000 次状态请求，通过既有 ML17 延迟及事件完整性门槛。 |
| 最终证据、操作说明与契约审阅 | ML-T28, ML-T29, ML-T38 | 最终操作说明/已执行证据及双语 API 批准对齐待完成，基线已有 OpenAPI 批准不一致。 | 记录实际最终测试/构建/类型生成结果和支持限制，审阅最终具体 API 差异后更新批准记录。此审阅不阻止前序实现。 |

已知待定规则：仅 ML-T33 的过期历史 RUNNING/CANCEL_REQUESTED 是否占用既有执行槽，仍未决定。OpenAPI 不一致属于已知最终审阅问题，不是另一个资源系统要求或实现范围许可。其他行均为既有方案内已授权实现或验证工作。

验收范围仍为实际产品 UI/API/组合接入隔离存储、确定性外部服务替身，以及 ML17 已列 Windows 负载配置。不新增付费 AI/供应商认证、正式通知、券商执行、生产迁移或部署门槛。不隐含新增原文引擎支持，准备/结果中应明确支持和不支持的条款。MV05–MV09 已取消保护项继续排除。后续更新应对照本清单报告进展/失败；若提出新增范围，须明确标为新增，不能静默变成另一个前置条件。

## MV11. 仅启动解耦验收

用户明确，本次询问的是启动解耦验收，不包括监控闭环业务改造。MV10 是完整交付清单，不能作为此较窄验收的前置条件清单。ML-T30–ML-T32/ML-C11 已实现，MV02 已记录通过的自动化证据。其后未修改运行源码，后续范围调整仅改文档。

**结果：启动解耦验收 PASS。** 2026-10-07（Asia/Shanghai）已完成全部三个固定场景，使用真实 Windows Uvicorn 进程、`create_production_app`、实际打包 Vue SPA、真实本机 HTTP 和 Codex In-app Browser。运行源码未改。证据断言全部通过；[summary.json](evidence/2026-10-07-startup-decoupling/summary.json) 记录结果，[commands.json](evidence/2026-10-07-startup-decoupling/commands.json) 记录启动与环境详情。

| 固定验收场景 | 已有自动化证据 | 实际环境结果 |
|---|---|---|
| 不使用回测时正常启动/重启 | 启动注册未使用管理器，路由/接口描述保持挂载，不调用回测工厂，未使用关闭无副作用。生产工厂保持无副作用闭包。 | **PASS。** 服务 PID 20760、37240，地址 `127.0.0.1:58537`；重启复用隔离监测存储。`/`、`/system`、健康及总览 API 返回 200，真实浏览器渲染监测/系统页面。回测保持 `NOT_INITIALIZED`，无工厂/start/存储/密钥/协调器调用或回测线程，无回测文件，无预热。证据位于下述根目录的 `s1-start/`、`s1-restart/`。 |
| 启动时回测专用资源不可用 | 故意失败的回测工厂在启动时不会被调用，监测生命周期保持已启动。 | **PASS。** 服务 PID 25668，地址 `127.0.0.1:58538`；回测 cursor key 故意截断为 16 字节（要求 32 字节，保留仅所有者 ACL）。应用启动及监测页面/API 访问成功。回测保持 `NOT_INITIALIZED`，工厂/密钥读取器未调用，两个回测数据库均未出现。证据：`s2-corrupt/unused-observation.json`、`corrupt-resource.json`、`http.jsonl` 和浏览器文件。 |
| 首次使用回测局部失败 | 重复真实 HTTP 数据集请求返回局部 503，不泄露内部路径；失败被缓存，监测不会被停止，正常生命周期清理仍执行。 | **PASS。** 在已启动的损坏资源服务上，首次 `GET /api/v1/backtest-datasets` 进入真实生产工厂/密钥读取器并因密钥长度失败。四次显式 HTTP 探测及浏览器读取均返回局部 503、`SERVICE_UNAVAILABLE`，无内部路径/原因或 `Retry-After`。78.279 秒缓存观察中工厂调用始终为一次。回测 `DEGRADED`、未完成工作 0；监测健康/总览持续返回 200，浏览器监测/系统页面保持可读且传输连接正常。正常关闭移除运行绑定与自有回测线程。证据：`s3-first-use/`、`s2-corrupt/lifecycle.jsonl`。 |

### MV11.1 环境与实际命令

仓库/运行目录：`D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor`。Python 3.14.7、Uvicorn 0.52.3、FastAPI 0.141.1、Vite 8.2.1。在 `web/` 执行 `npm run build` 通过（854 个模块）；每份 `lifecycle.jsonl` 保存生产挂载资源的 SHA-256。使用默认监测、计划和 AI 组合，配合临时 `{}` 配置与空临时监测存储。回测默认路径由一次性进程工作目录隔离。未替换生产工厂或生命周期结果。profiler/audit hook 观察生产调用并拒绝非本机 socket 连接；被拒绝的外部尝试也是 0。

刻意不配置 Tushare 凭证，因此监测健康为 `DEGRADED`、只读、`TUSHARE_NOT_CONFIGURED`，数据库/WAL 为 `READY`，页面显示空/无数据状态。该证据证明本机启动/读取可用与隔离，不证明真实行情监测健康或负载容量。浏览器 warning/error 捕获为空。指数序列 404 源于离线缺失数据。`BacktestThreadOwner.__init__` 是轻量归属对象，不等于执行器/线程；profiler 中 `MonitorWebComposition.start/stop` 的 call 次数包含协程恢复，不能当作生命周期实例数。

以下三个服务命令均通过 PowerShell `Start-Process -WindowStyle Hidden` 启动，工作目录为仓库，stdout/stderr 重定向至对应场景。每个 `--root` 都是经过标记校验的一次性目录。场景 3 复用已经运行的场景 2 进程，没有构造假的读取服务。

```powershell
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-start --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-restart --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --corrupt-key --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s2-corrupt --port 58538
```

HTTP 探测使用真实 socket 与 `X-Monitor-Contract-Version: 2`，与前端一致。实际探测命令如下（重复缓存检查使用相同参数及记录的 `--label`）：

```powershell
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/health /api/v1/dashboard /api/v1/runtime-status --label normal-start-contract-v2 --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-start --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe / /system /api/v1/health /api/v1/dashboard --label normal-restart --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-restart --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe / /system /api/v1/health /api/v1/dashboard --label corrupt-unused-start --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s2-corrupt --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label first-use-controlled-key-failure --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label cached-failure-later-monitor-still-readable --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label final-cache-and-monitor-check --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
```

初始健康/总览探测因未带必需的版本头返回 409，已纠正；探索性 `/api/v1/system`、`/api/v1/runtime-status` 返回 404，因为这些路径没有挂载。这些准备观察不是产品失败；精简后的 `s1-start/http.jsonl` 保留成功的验收响应。故障夹具最初通过带长度校验的创建器写入非法密钥，在服务启动前退出；冗余夹具日志已在提交整理时删除。纠正后先用安全写入器创建测试材料，再截断文件。[注入故障原因证据](evidence/2026-10-07-startup-decoupling/s3-first-use/injected-failure-cause.json) 确认 `ValueError: cursor key must contain exactly 32 bytes`。

### MV11.2 证据、清理与固定阻断清单

证据根目录：[evidence/2026-10-07-startup-decoupling/](evidence/2026-10-07-startup-decoupling/summary.json)。保留附件包含启动/结果摘要、实际调用/资源/生命周期记录、验收 HTTP 响应、未使用资源与最终缓存快照、受控故障证据及代表性浏览器截图。提交整理时删除重复 PID/状态/哈希清单、stdout/stderr、AX 文本、空控制台捕获和过渡快照。场景 3 浏览器证据包括[局部错误页面](evidence/2026-10-07-startup-decoupling/s3-first-use/backtest-full-page.png)、[失败后监测页面](evidence/2026-10-07-startup-decoupling/s3-first-use/monitor-after-failure.png)、[失败后系统页面](evidence/2026-10-07-startup-decoupling/s3-first-use/system-after-failure.png)。

观察器每 0.5 秒采样。一次请求邻近样本包含之前尚未初始化的状态（`NOT_INITIALIZED`、工厂 0）；该冗余过渡快照已删除。场景 3 状态结论使用保留的 `final-cache-observation.json`（`DEGRADED`、工厂 1）、带时间戳的 HTTP 503 与浏览器证据。

各服务均使用脚本 `--stop` 模式及匹配的 `--root`、`--evidence`、`--port` 停止；它只触发本任务自有服务的正常 Uvicorn 关闭。三个进程均完成应用关闭并退出，未强制结束进程。耗时：首次关闭带浏览器 WebSocket 时 18.043 秒，重启后 0.152 秒，回测首次使用失败后 1.123 秒。首次等待属于 Uvicorn 连接/后台任务排空，不是回测初始化/清理；不声明关闭延迟阈值。本任务创建的浏览器页 1/2/3 已关闭，两个端口均无监听，记录的服务/启动器 PID 均已退出。核对绝对路径后，仅移除带标记的 `data/mv11-normal`、`data/mv11-corrupt`；保留摘要记录端口关闭及源码保留情况。必要证据与可复用脚本保留。源码/研究文件哈希检查的 240 个保留文件全部一致；正式数据库、账号配置及盛新研究文件未改。未发真实付费 AI/行情请求、真实通知，也未提交、推送或部署。

| 清单项 | 状态与处理 |
|---|---|
| MV11-B01 实际启动解耦阻断项 | **未发现。** 三个必需场景全部通过。故意损坏的资源是受控故障，不是新增生产缺陷。本轮验收不需要运行源码修复。 |
| MV11-O01 离线环境与探测/夹具观察 | 上述 `DEGRADED`/无行情数据、契约头 409、未挂载路径 404、非法密钥夹具准备被拒及 WebSocket 关闭排空均已记录，不构成启动隔离失败。 |
| MV11-O02 独立的既有工作 | ML-T33 历史占槽决策、ML-T34 同步限速、最新 30 个结果清理、服务控制/UI、闭环准备/回放/结果、完整 Windows 基线/负载测试及完整交付 API 批准对齐仍在 MV11 范围外。未改已知 `test_openapi_change_requires_bilingual_spec_approval` 基线不一致及批准摘要。 |

本次变更验证：当前前端构建通过；`ruff check scripts/verify_backtest_startup_decoupling.py` 通过；真实服务各场景、缓存行为、正常关闭、端口关闭及源码/研究文件不变的证据断言通过。未重跑 MV02 既有测试，也未用旧测试替代上述观察。不需要更强模型：必需的真实服务/浏览器证据已齐全，没有需要升级处理的未决运行阻断项。

## MV12. 隔离收尾与契约审阅

日期：2026-10-07，Asia/Shanghai。本轮完成 ML-T33/ML-T34/ML-C12，并修复既有统一研究批准记录。不实施监控闭环业务/UI，也不认证未来接口。MV01–MV10 保留原检查结果，包括此前失败的 OpenAPI 批准检查。MV11 保持 **PASS**，不重跑或把真实启动/浏览器证据重新定义为负载验收。

### MV12.1 基线与实现行为

本轮修改前，内部基线记录了初始未提交工作树和 1,188 个文件哈希。提交整理时已删除完整临时清单与重复差异备份，长期结论保留于本文及 Git 历史。既有生命周期/组合/web 改动、未跟踪服务/恢复/启动文件、设计修改及独立盛新研究文件均已存在。本轮修改 `backtest/jobs/repository.py`、`backtest/sync.py`、针对性恢复/限速测试及双语方案/任务/验证/当前批准文档，其他基线文件保留。

用户已决定 ML-T33 采用旧任务休眠、安全释放执行槽。过期历史 RUNNING/CANCEL_REQUESTED 保留原记录，不再占槽；仅打开历史或执行就绪不会授权它们。有效或未知/null 租约同时阻止新排队领取与选中恢复。SQL 写事务串行处理竞争的新领取与恢复；先筛选选中 ID 再排序，更早未选记录不会使选中任务饥饿。明确选择过期 CANCEL_REQUESTED 时确认取消，不执行该任务。保留既有 30 秒租约、最多 3 代领取、幂等及取消/发布保护。旧 token 不能续租、更新进度或发布。不需要新增状态、数据库迁移或公开 API。

协调器仍须等待真实操作 future 返回才请求下一次领取。新增回归在不协作工作线程仍被阻塞时推进时钟至租约过期：下一项保持 QUEUED，仅在物理返回后执行。既有关闭/替换归属测试仍适用。多个休眠记录可与一个有效执行租约共存；原按全部状态数量的断言不再误报存储损坏。

ML-T34 在每次同步供应商回调内部使用 monotonic 请求开始时间及既有 `LIVE_TUSHARE_MIN_INTERVAL`（1.25 秒）限速。覆盖 `trade_cal`、`daily`、`stk_mins`、`stk_limit`，包括控制器延迟/重复回调、失败尝试及连续同步调用。已检查真实供应商适配器，每个对应方法发起一次接口请求。生产每个任务新建阻塞核心，因此由自有工作线程通过 thread-local 保留上次请求开始时间，跨新建核心沿用。不新增执行器、跨操作互斥或账号级调度器。等待每次最多 0.05 秒检查取消，并在调用前再次检查；首个请求立即开始，长请求不额外等待完整间隔，缓存同步无调用/等待。保留既有传输超时/错误映射，同步服务不新增重试。限速仅在两个计划文件实现，监测/AI 请求模块不变。

### MV12.2 实际检查

命令从 `trade-plan-monitor/` 执行，供应商为虚拟服务，数据库为临时存储。各命令存在重叠，不合计为虚构的新套件总数。

| 检查 | 命令 | 实际结果 |
|---|---|---|
| ML-T33 最终租约/恢复/准入/取消/发布 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_leases.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py -q -m 'not live'` | 47 passed，在新建核心时间戳改动后用时 8.47 秒（此前 7.56 秒）。包含新领取/选中恢复竞争、多个休眠记录与一个有效租约共存、未知租约、旧 token 及同协调器物理排空。 |
| 既有事件/时间/取消防护与扩展恢复 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_unified_replay_boundaries.py -q -m 'not live'` | 28 passed，42.55 秒。包含既有 70,000 事件上限在再次运行评估前拒绝，以及有界日历上下文。 |
| 初始限速复现 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py -q -m 'not live'` | 实现前 10 failed、2 passed；实现后 12 passed，1.78 秒，后续新建核心回归将本文件扩展至 13 项。 |
| 限速及既有同步/存储/归属/组合/启动防护 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py tests/integration/test_backtest_sync.py tests/integration/test_backtest_results.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_startup_isolation.py -q -m 'not live'` | 新建核心时间戳修复后为 80 passed、1 skipped，66.37 秒。此前候选版本为 79 passed、1 skipped，66.29 秒。 |
| 既有统一研究 API/任务/结果与旧格式兼容 | `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_entries.py tests/integration/test_backtest_compatibility.py -q -m 'not live'` | 5 passed，6.25 秒。未激活已审核输入、缺失/错误审核拒绝、幂等、冻结工作者输入、结果/权益/导出及取消无发布均通过。 |
| 批准修复前 OpenAPI | `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 1 failed、13 passed，9.76 秒，仅已知批准记录检查失败。 |
| 具体双语审阅后 OpenAPI | 同上完整 `test_openapi_snapshot.py` 命令 | 14 passed，9.27 秒。快照、实际路由、已批准路径、公开错误、生成 TypeScript 及确定性/LF 检查全部通过，未改测试。 |
| 生成与静态检查 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m compileall -q src`; `git diff --check` | 通过。canonical monitor v2 及 compatibility monitor v1 生成物继续与当前契约一致。 |

ML-T33 复现最初为恢复文件 4 failed、6 passed，检测到过期历史阻止新任务/选中恢复，以及物理返回后仍阻止下一项。仓库修复后这些用例通过；加入竞争领取/恢复后最终文件为 11 项。没有删除或降低断言、时间门槛或测试。既有 Windows 跳过项为 `requires POSIX ownership semantics`，保留既有 Starlette/httpx 弃用告警。

### MV12.3 既有 OpenAPI 不一致的具体审阅

[openapi-review.json](evidence/2026-10-07-isolation-wrapup/openapi-review.json) 保存全部 37 处 JSON 路径差异的精简索引及比较结论；完整 schema 内容可按记录的 Git 提交复现。原批准 SHA-256 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255` 精确对应提交 `a0915f71b52a415e55086587e029c38e126c0d49`。当前快照 `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833` 已在 `7a92f75` 提交，且与 HEAD 一致。新增 25 个 schema，5 个既有 schema 内有 12 处差异，无 schema 删除。完整 `paths` 树、非 schema components 和其他既有 schema 均比较相同，包含监测、任务、公开错误、认证、参数与响应声明。这是已授权统一研究接口的陈旧批准，不是启动或限速代码缺陷。

| 审阅组 | 具体变化 | 依据与结论 |
|---|---|---|
| 冻结研究输入（11 个新增 schema、1 处既有 schema 差异） | `BacktestRunCommand.researchInput`；`UnifiedResearchInput`、`ResearchReview`、`ResearchFactor`、`ResearchAdjustmentProof`、`TradingDay`、`ResearchFact`、`DailyOfficialProof`、`ResearchDeactivate`、`ResearchReplace`、`ResearchSimulation`、`ResearchReassessment`。 | UR03/UR04/UR05/UR06：明确审核/起点/库存、冻结认证证据、有界操作及精确模拟原因/数量。保留严格值、明确 +08:00、唯一顺序/ID 及服务端审核校验。不新增文件路径或真实执行权限。 |
| 研究决策/操作详情（12 个新增 schema、3 处既有 schema 差异） | `ResearchDecisionView`、`ResearchDecisionEvent`、`ResearchConditionEvidence`、`ResearchRuleEvidence`、`ResearchReminder`、`DailySignalState`、`DailyRiskState`、`DailyRiskAction`、`DailyInventoryView`、`ResearchOperationView`、`ResearchOperationOutcome`、`ResearchOperationValuation`；`BacktestDetailView` 将三分支 `oneOf`/`kind` discriminator 替换为五个强类型 `anyOf` 分支。 | UR06 对旧回放及研究均保留 DECISION/EXECUTION_OUTCOME 外层 kind，因此仅 `kind` 无法区分全部五个分支。必填 `researchDecision`/`researchOperation` 与旧 payload，以及内部 schema-version 常量用于区分。禁止额外字段，保留详情大小校验。这符合已批准的强类型增量映射，不是接受任意内容。 |
| 研究指标/权益（2 个新增 schema、8 处既有 schema 差异） | `ResearchMetricsView`、`ResearchEquityView`；`BacktestRunSummaryView`/`BacktestRunView` 的 metrics 改为强类型联合（各 3 处），`BacktestEquitySeries.items` 改为强类型联合（2 处）。 | UR05/UR06：独立研究资金投影、可为空的无效估值、安全整数资金值、有界且有序权益输出；旧分支含义及导出字节保持不变。 |

UR01 授权设计/内部审阅/顺序实施/最终独立审阅，UR08 包括回测传输/生成契约及双语记录。此前[统一回放验证](2026-10-03-unified-replay.zh-CN.md) 已记录独立审阅及 UR-A01–UR-A10 证据。本轮另核对具体 schema/源码绑定，执行上述真实入口/兼容与生成/快照检查。依据这些证据，双语 `SPEC-unified-plan` 已纠正当前批准，并记录日期、实施提交、变更摘要、设计依据及保留的历史摘要。`openapi.json`、生成类型和测试保持不变。ML-T29/ML-C10 仍未勾选，因为未来监控闭环接口/依赖尚未完成。

### MV12.4 审阅与剩余范围

使用 `code-review` 技能按起始文件副本审阅安全、正确性/并发、性能及可维护性，将本轮增量与既有未提交改动分开。SQL 值仍参数化，有效/null 租约保持保守阻断，旧 token 和原子发布保护不变，一个物理工作线程仍串行执行。限速只保存常量规模的时间戳，沿用既有回调/错误策略及可取消有界等待。具体最终基线契约审阅未发现尚未解决的范围内缺陷。双语文档 ID/命令/依赖和已完成历史 todo 尾部已检查等价与保留。

ML-T30–ML-T34 及 ML-C11/ML-C12 已完成，既有 39 项任务中仍有 34 项待完成，包括准备/审核、冻结闭环输入及账户/提醒/每日回放、提交/发布/结果/最新 30 个保留、公开服务控制/生成 UI、更广集成/浏览器/Windows 负载以及最终运维/证据/未来契约审阅。这些是既有独立任务，不是新的 MV11 阻断。已取消保护继续排除。未修改或调用生产数据库/配置、独立盛新研究、真实供应商/付费 AI、通知、提交、推送或部署。已接受的同进程/不协作线程边界保留，本轮不宣称完整故障/负载或健康真实行情认证。

## MV13. 提交整理与产物清理

用户于 2026-10-07 授权整理当前改动、删除无用过程/测试产物、提交并推送至 GitHub。生命周期隔离/恢复、本地同步限速及双语设计/任务/验证文档按独立逻辑提交。独立盛新研究文件保留在这些提交范围外。MV01–MV12 关于未提交/推送的文字描述各自原验证轮次；本次后续授权仅为整理提交替代该边界。

删除 36 个冗余过程文件：完整哈希/状态清单、重复差异/检查备份、PID/最新/过渡快照、夹具/stdout/stderr 日志、AX 导出、空控制台捕获及重复截图。保留 22 个必要验收附件。启动 HTTP 文件保留成功验收观察；OpenAPI 索引保留全部 37 个变更路径，不重复已提交 schema。保留可复用离线真实服务脚本及有效生命周期/线程归属/恢复/限速回归测试。未删除或削弱任何既有测试。恢复测试辅助函数现向取消 token 传入 `SYNC_CALENDAR`，真正执行类型化协作取消，而非意外缺参错误。

清理后在 `trade-plan-monitor/` 使用离线夹具和临时数据库执行：

| 检查 | 命令 | 结果 |
|---|---|---|
| 隔离/恢复/限速/契约 | `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_leases.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py tests/integration/test_backtest_sync_pacing.py tests/integration/test_backtest_sync.py tests/integration/test_backtest_results.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_unified_replay_entries.py tests/integration/test_backtest_compatibility.py tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 160 passed，1 skipped，87.89 秒。跳过项需要 POSIX 线程归属语义。 |
| Web/监控及回测 API 兼容 | `.venv/Scripts/python.exe -m pytest tests/integration/test_web_api.py tests/integration/test_monitor_production_composition.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py -q -m 'not live'` | 353 passed，32.31 秒。 |
| 静态/生成产物 | `.venv/Scripts/python.exe -m ruff check src tests scripts`；`.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`；`git diff --check` | PASS；监控 v2 与兼容 v1 均保持最新。 |
| 文档与范围审阅 | 双语 ID/标题结构/相对链接；已完成历史 todo 尾部；明确暂存文件审阅 | 7 对双语文档全部 PASS。清理后链接可解析，独立研究保持未修改。 |

两组 pytest 保留既有 Starlette/httpx 弃用告警。审阅未发现尚未解决的范围内问题。这些检查新增整理提交/兼容证据，不代表完成剩余 34 项业务/UI/负载任务，也不授权部署、付费请求或生产改动。

## MV14. 冻结输入与共用模拟基础

2026-10-07，基于既有业务授权，从 `0db69c9` 开始实施。ML-T01 与 ML-T02 已完成，各限定在四个主要文件内，同时更新成对 todo/验证记录。独立盛新研究文件已保留。本轮未提交、推送、修改生产环境、启动真实监控、调用付费供应商、发送通知或部署。

### MV14.1 已实现行为

ML-T01 新增严格不可变 `monitor-loop-input-v1` / `backtest-run-v5` 值，不改变 v1–v4 编解码。期初事实区分未知/零现金、未知持仓/成本/可卖量、精确 `401050` 分成本与独立市价估值。账户事实可早于监控起点；未来事实/尚不可用的估值被拒绝。现金、成本、数量和市值保留安全整数检查，未知现金时也检查市值。内容审核绑定原始原文哈希和证据哈希，并须在提交时已存在。编写日期/时间、可用时间、信息截止、生效日和审核时间彼此独立；仅有日期时不编造精确时间，后写计划仍标记为回溯研究。日历预检拒绝重复/未知/非交易日期与未覆盖起点。后续版本在日边界切换；同版本沿用保留激活身份，未来版本不重命名早期权限 ID。既有激活/规则有效期仍为权威约束。

注入的带时区提交时钟在 Asia/Shanghai 一次解析缺省/null 或明确结束日期。过去/节假日保留包含式边界，今日冻结在提交时刻。早于起点/未来日期和伪造截止/来源值被拒绝。原文上限为 256 项、UTF-8 合计 8 MiB、单项 150,000 字符；期初批次上限仍为 200。包含刷新的评估、提醒、意图和尝试各上限 70,000。定义批内一个提取槽、可重试失败共 3 次尝试。工作者执行、提交预留与截止数据集连接仍为后续任务，这些值本身未实现上述能力。

ML-T02 将既有校验/写入提取到 `state/simulation.py`，使用类型化命令/回执与不依赖传输的拒绝码。在调用方事务内写入持仓、信号消费、风险完成和回执，内部不提交。Web 保留幂等、提交和错误映射；旧研究模拟不再使用私有 HTTP 辅助函数。测试独立检查精确账本回滚、回执值、修订、完整数量及执行期间不导入 Web。

### MV14.2 已执行检查

所有命令从 `trade-plan-monitor/` 执行，使用离线夹具和临时数据库。新增测试首次因模块缺失而失败。后续红测试检出未来审核准入，修正后通过。新增夹具不匹配（SSE/SZSE 日历、会话检查前先检查报价新鲜度）按既有行为纠正；未修改、跳过或削弱既有测试/断言。

| 检查 | 命令 | 结果 |
|---|---|---|
| ML-T01 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m 'not live'` | 35 passed，0.59 秒。 |
| ML-T02 | `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m 'not live'` | 25 passed，50.86 秒；包含 7 项新增参与者案例。 |
| 在线/共用/冻结兼容 | `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_runtime.py tests/integration/test_unified_replay_parity.py tests/integration/test_backtest_compatibility.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_history_regression.py tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 提取后 56 passed，47.61 秒。 |
| 最终单元/契约回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 最终输入修正后 2793 passed，排除 4 项 live 测试，20.83 秒。 |
| 静态/生成产物 | `.venv/Scripts/python.exe -m ruff check src tests scripts`；`.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`；`git diff --check` | PASS；canonical monitor v2 与 compatibility monitor v1 均保持最新。 |
| 结构审阅 | 成对标题 ID/命令/任务勾选；原已完成 todo 尾部；原执行函数体与提取后函数体的规范化 AST 比对 | PASS。AST 比对仅排除变化的文档字符串/签名，以及传输类型/错误映射名称。 |

### MV14.3 审阅与剩余范围

使用 `code-review` 技能自审，比对提取后的函数体与原辅助函数，检查授权、算术、确定性和上限。已修正原文/证据批准绑定、未知现金时的市值范围、账户/起点时间区分与未来审核准入。公开模式/传输类型及当前分仓/模拟/事务规则不变。保留既有 Starlette/httpx 弃用告警。未批准未来 API 摘要。

ML-C01 仍需 ML-T03 提醒记录。尚未形成自动闭环、原子资金参与者、准备工作流、新结果/API/UI 或完整 Windows 负载验收。既有 39 个薄片中仍有 32 个待完成。下一依赖为 ML-T03、ML-T04 原子账户和 ML-T05 离线单计划循环。本证据不宣称已完成这些能力，也不重新加入已取消范围。

## MV15. 私有提醒与 ML-C01

### MV15.1 已实现行为

ML-T03 分两个薄片完成：未知期初批次的存储/账户计算，再接私有监控/提醒记录。`LoopSession` 仅新建私有 SQLite 文件，写入冻结审阅/激活绑定及日历，向共用运行时注入虚拟时间与因果提醒 ID。原文记录明确标识为已审阅清单，不伪造原始文本。求值和记录不会改变历史期初持仓；不使用真实供应商、发送出口、网络或 Web 执行路径。

`ReminderCapture` 使用 `daily_delivery_allowed`，原子记录 CAPTURED/SUPPRESSED 回执、去重重试、执行 70,000 上限并返回有界分页。过期报价以及已修订的分钟/事实/持仓/审阅/激活证据均抑制送达。新增分钟修订红测试暴露普通发送路径遗漏校验；共用普通资格现使用既有分钟来源检查，有效在线行为仍由回归覆盖。纯技术提醒不携带数量或执行候选资格。明确标记的私有期初批次保留未知买入日期及可卖量；未知/零可卖量阻止卖出，明确整手可卖量则允许既有完整数量检查。不需要生产迁移或 API/生成契约变更。

### MV15.2 已执行检查

所有命令从 `trade-plan-monitor/` 离线执行，使用临时存储。新增测试先因缺少私有会话/状态支持而失败；分钟修订校验在修复前失败。测试夹具修正保留真实的较晚接收时间。未削弱既有测试、断言或门槛。

| 检查 | 命令 | 结果 |
|---|---|---|
| ML-T03 | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m 'not live'` | 40 passed，12.14 秒；包含 18 个新增私有闭环用例。 |
| 共用状态/在线回归 | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py tests/integration/test_daily_simulation.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py -q -m 'not live'` | 79 passed，36.91 秒。 |
| 单元/合同回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2793 passed，4 个 live 测试 deselected，21.68 秒。 |
| 静态/生成产物 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `git diff --check` | PASS；canonical monitor v2 与 compatibility monitor v1 均保持最新。 |

### MV15.3 自审及剩余范围

自审检查冻结授权、原文标识、缺失事实、回滚/幂等、有界读取、时序校验和共用行为。ML-C01 已完成。原子资金、自动响应循环、按日计划切换、准备、结果/API/UI 和完整负载验收仍待完成；39 项任务中尚有 31 项。下一项为 ML-T04/ML-T05。保留既有 Starlette/httpx 弃用告警。本次继续未提交、推送、调用付费/真实服务或部署。

## MV16. 私有账户原子结算

### MV16.1 已实现行为

ML-T04 新增 `LoopAccountParticipant` 以及整分精度的费用/状态/回执类型，仅在新建私有会话组合。共用模拟参与者保留数量、T+1、CORE/风险与信号次数授权。一项调用方控制的事务覆盖资金、批次成本、持仓、信号消耗/风险完成、共用回执及资金回执；参与者本身不提交。私有表无需生产迁移。观察模式拒绝执行。

使用每股绝对分滑点及既有比例费用逐项向上取整。原文示例以 28.70 买入 100 股时，成交价 2871 分、金额 287100、费用 503；以 29.30 卖出 100 股时，分别为 2929、292900 和 650。这些是冻结原文假设，不代表现行法定费率。资金准入使用含费用的完整数量；未知资金或仅差一分均拒绝且不改变状态。费用/资金/成本总额保持安全整数校验。共用回执记录授权行情价；资金回执单独记录含滑点成交价及费用。

期初 401050 分成本原样保留，不生成新买入或重复购买费。卖出成本跟随共用持仓的实际批次扣减。按比例释放成本向下取整到分，尾差留在剩余批次，保持总成本守恒。未知成本保持未知，并使按成本计算的已实现盈亏未知。重复请求键要求命令/费用设置相同，并返回原不可变回执。回执校验核对费用/数量及结果分仓数量。持仓写入后、全部资金/回执写入后的故障，陈旧修订和非法重试均不留下部分效果。提交时复核分钟来源，防止求值后的修订仍授权成交；新增红测试在修复前暴露该缺口。非执行记录类型不能作为资金成交原因。

### MV16.2 已执行检查

所有检查从 `trade-plan-monitor/` 使用离线夹具和临时数据库执行。新增费用/账户测试先因缺少模块或参与者方法而失败。未降低既有断言或门槛。

| 检查 | 命令 | 结果 |
|---|---|---|
| ML-T04 最终目标检查 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m 'not live'` | 最终回执/提交校验后 21 passed，2.11 秒；8 个费用与 13 个账户用例。 |
| 闭环/共用/旧回放 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_simulation_participant.py tests/integration/test_unified_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 76 passed，84.47 秒；在最终私有回执/提交校验之前执行。 |
| 单元/合同回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 回执及分钟来源校验后 2801 passed，4 个 live 测试 deselected，21.11 秒。 |
| 静态/生成产物 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS；monitor v2 和 compatibility v1 不变。 |
| 文档/工作区检查 | `git diff --check`；配对章节 ID、命令、任务状态及原已完成历史清单 | PASS。 |

### MV16.3 自审及剩余范围

自审检查资金范围、精确取整、期初成本保留、共用扣减对账、未知盈亏、回执绑定和回滚。ML-T04 已完成。ML-T05 自动响应时序和完整单计划循环仍待完成；资金参与者本身不实现下一分钟选择、涨跌停准入或结果发布。ML-C02 保持开放。39 项任务中尚有 30 项。未提交/推送、调用付费供应商、生产状态或真实通知。

## MV17. 单计划范围纠正及输入回归

### MV17.1 已接受范围与实现

用户于 2026-10-07 要求仅实现单计划回测。每次运行冻结恰好一份完整已审核计划/原文及一个初始生效绑定。计划有效时可跨交易日延续，执行更新账本而不改变计划内容。按日替换、前版继承/合并、多计划准备及多计划同时回测排除本期。ML-T06/ML-T09 与 ML-A07 为取消，而非通过/完成，保留 ID 及此前证据。活动依赖/检查点排除它们。方案、实施计划和任务清单双语同步。完成 9 项，37 个活动任务剩余 28 项，保留 39 个 ID 和 13 个检查点。

私有原文/输入契约现拒绝第二原文/条目，包括重复版本、模型复制及解码载荷。选择保留跨日同一激活、可用和到期防护，移除后继选择。已审核证据哈希保留独立有界集合。保留可选结束/截止、期初账户精度、费用/原子状态、旧编码及既有隔离/供应商/事件限制。授权不可用报告 `LOOP_PLAN_AUTHORITY_UNAVAILABLE`，不要求切换计划。准备/API/UI 仍为计划中的单原文工作，本次范围纠正未实现这些功能。

### MV17.2 已执行检查

离线检查仅用临时库。新增数量限制用例在原多条目实现下先出现 3 项失败、1 项通过。用户取消该行为，因此原批次/切换正向夹具替换为明确拒绝、固定计划延续/到期及数据集/因果身份用例，其他因果、账户和公开兼容断言保留。静态检查发现两处测试行过长，修正格式且不改变断言。

| 检查 | 命令 | 结果 |
|---|---|---|
| 单计划输入/时间 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m 'not live'` | 39 通过，0.57 秒。 |
| 提醒/账户/费用 | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/unit/test_monitor_loop_costs.py -q -m 'not live'` | 最终授权错误措辞修改后 39 通过，3.53 秒。 |
| 单元/契约回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2805 通过，排除 4 项 live 测试，21.32 秒。 |
| 静态/生成产物 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 格式修正后 PASS，监控 v2 与兼容监控 v1 保持最新。 |
| 文档/工作区 | `git diff --check`；双语标题/ID/依赖/命令/文件/数字阈值及原始已完成 todo 尾部 | PASS。 |

### MV17.3 审阅与剩余范围

自审覆盖单计划数量限制、不可变复制/解码输入防护、跨日激活/到期、独立证据绑定及数据集修订下的因果 ID。既有公开模式/生成文件不变。完整自动响应闭环仍待 ML-T05，本次检查不代表它、准备、结果/UI 或负载验收完成。既有 Starlette/httpx 弃用提示保留。未提交/推送，未使用付费请求、生产状态、真实通知或部署。

## MV18. 单个未完成任务准入

用户最新纠正要求一个未完成任务，不能仅限制一个执行线程。移除 100 任务队列容量、授权累积及多 ID 恢复。现有 SQLite 写事务在任何 QUEUED/RUNNING/CANCEL_REQUESTED 任务存在时拒绝不同的新同步/验证/回放，包括过期/未知租约。未完成快照预留也阻止新操作，直到释放/完成绑定或任务拥有的孤儿清理。同 key 及同操作幂等保留。终态释放准入，请求取消不会释放。选中恢复授权一个任务，保留物理排空、30 秒租约/3 代及旧 token/发布保护。内部 `BACKTEST_BUSY` 使用既有公开 `409 CONFLICT`，未新增 API 字段/数据结构/依赖/迁移。ADR 0009 覆盖此前队列及过期/准备并发选择。准备仍待完成，入口须继承同一规则。

新增准入测试在多任务实现下最初 15 项全部失败。修正并补充过期预留覆盖后，16 项均在以下组合检查中通过。原批量排队夹具改为创建终态历史记录，保留分页、成员变动保护、旧 token 和线程排空断言。

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_single_task.py tests/integration/test_backtest_jobs.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_job_api.py tests/unit/test_backtest_service_contract.py tests/integration/test_monitor_loop_cycle.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/integration/test_simulation_participant.py tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py tests/unit/test_monitor_loop_costs.py -q -m 'not live' --tb=short
```

结果：**278 通过，1 跳过，27.98 秒**。跳过项是 Windows 环境下既有 POSIX 所有权检查。后补日历/成交量用例及最终范围保护见 MV19。没有通过跳过/删除测试使修正通过。无关在线监测请求队列及结果/历史分页不属本次清理范围。

## MV19. 私有单计划响应循环

ML-T05/ML-C02 已实现并验证。冻结因果帧驱动共享监控及合格本地提醒捕获，有界意图使用固定响应延迟和下一完整分钟区间。09:35:12 提醒不能使用 09:35–09:36 区间；夹具在 09:37 买入、09:42 卖出，每次 100 股。独立预期断言现金 `503590` 分、剩余账户成本 `798654` 分、总股数 200、TACTICAL 可卖数为零，以及含成交后刷新在内的 15 次评估。无需未来交易脚本。

首次买卖集成因夹具将十个来源分钟传给只接受最新五分钟桶的发送校验而失败；已按既有来源契约修正夹具，保留发送时保护。风险用例提供在每个虚拟时刻明确已可用的历史日线认证修订。共享风险优先级阻断待处理普通买入，执行授权风险数量，并在计划到期后保留已锁定退出义务。到期普通权限关闭，不切换/重新激活计划。未知/休市交易日、不足成交量、涨跌停与现金阻断完整成交，同一区间不重复尝试。取消及意图/尝试/评估上限阻止额外账户提交。冻结输入上限保持 70000。观察/已记录模式不自动产生交易。

| 检查 | 命令 | 结果 |
|---|---|---|
| 循环、提醒、原子账户和共享模拟 | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/integration/test_simulation_participant.py -q -m 'not live' --tb=short` | 57 通过，9.65 秒；包含 19 个循环用例。 |
| 租约与历史兼容 | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_job_leases.py tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged tests/integration/test_backtest_acceptance.py::test_each_fixture_symbol_has_stable_buy_and_t1_exit_bytes tests/integration/test_backtest_acceptance.py::test_prior_evidence_manifest_and_bilingual_reports_fail_closed -q -m 'not live' --tb=short` | 10 通过，4.24 秒；离线应用、BUY/SELL/T+1 字节可重复及证据清单保留。 |
| 单元/契约回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live' --tb=short` | 2809 通过，排除 4 个 live，21.18 秒。 |
| 静态/生成文件 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS，监控 v2 和兼容 v1 保持最新。 |
| 文档/工作区 | `git diff --check`；双语标题/ID/字面命令、字段、路径、阈值、依赖/检查点计数及原已完成 todo 尾部 | PASS；9 对双语，保留 39 个任务 ID/13 个检查点；10 完成、27 待完成活动、2 取消，原历史不变。 |

两轮较广的既有验收调用在无关全年规模夹具中结束，均不把完整调用计为 PASS。第二轮按名称筛选仍包含全年用例，因此最终相关检查改为上表明确节点选择。容量阈值及测试定义不变，完整闭环负载验收仍待完成。

自审覆盖事务准入/预留竞态、幂等重试、终态释放、单个恢复授权、分钟/报价/限价/日历绑定、精确数量/费用、共享风险权限、到期观察及有界反馈。既有 Starlette/httpx 弃用提示保留。此私有切片未实现准备、已记录动作导入、冻结数据集读取、工作线程/API/UI/报告集成或完整闭环负载验收。完成 10 项、待完成活动任务 27 项，37 活动 / 保留 39 个 ID；ML-T06/ML-T09 继续取消，下一项为 ML-T07。本切片未提交/推送，未使用付费请求、生产状态、真实通知或部署。

## MV20. 单计划准备状态持久化

2026-10-08，ML-T07 从 `main` `91eca25` 继续。三个主要文件为 `backtest/preparation_models.py`、`backtest/preparation_store.py` 和 `tests/integration/test_plan_preparation_store.py`，同步更新中英文方案/任务/验证记录。独立盛新研究继续保留在本次改动之外。

独立 SQLite 文件包含 `backtest_preparation_metadata`、`backtest_preparation` 和 `backtest_preparation_idempotency`。元数据绑定 `backtest-preparation-v1` 和模式版本 1。复用既有路径规范化/存储防护，并检查标记与表集合，拒绝在线、行情、结果/任务、未知、混用及不支持版本的存储。反向以行情/结果仓库打开准备文件也会拒绝；拒绝测试验证文件字节不变。不增加生产迁移/配置或深度文件别名框架。

严格不可变输入恰好包含一份原文。保留原文、SHA-256、已提供的编写/可用/生效日期及独立元数据绑定哈希；缺少历史日期时仍为未知。在持久化入口重新校验创建/编辑类型值，避免手工构造对象绕过原文数量或空白内容检查。每个原文修订最多保留 3 次尝试；未变化的编辑不会重置次数。读取/重启保留未确认尝试，不调用供应商、不自动重试，也不因租约到期释放。

修改原文会提升修订并使候选/审核绑定失效。进行中的编辑或取消保存 `CANCEL_REQUESTED` 及未确认尝试身份，拒绝迟到候选完成。其他准备修改/启动仍被阻止，重启后同样保持。只有显式 `acknowledge_cancellation` 才记录已确认结束。修改后的原文随后可回到草稿；编辑后再明确取消则结束为已取消。这一存储确认不能证明物理工作线程已排空：ML-T10 必须先建立该事实再调用确认，ML-T10/ML-T12 必须将准备接入既有全局任务准入。本项不暴露工作线程或公开准备入口。

候选持久化沿用既有 1 MiB 输出、10000 节点及 64 层深度提取边界，拒绝重复键、损坏/非有限 JSON 和非对象根节点。有界不透明载荷并未实现 ML-T08 的完整计划/期初账户输出。`VALID` 与批准分开。明确保存审核要求字面布尔真值，并绑定精确原文/候选修订、候选哈希和证据哈希。即使输出相同，重新提取也使审核失效。完整原文条款校验、语义审核及不可变提交冻结仍归 ML-T08/ML-T11/ML-T17。

每次修改及其幂等响应在同一个 `BEGIN IMMEDIATE` 事务提交。同键重试在后续编辑之后仍返回原回执，不恢复旧状态；改变请求/操作会冲突。并发创建/编辑/启动测试证明唯一回执、修订保护及唯一未确认准备尝试。注入回执插入失败会回滚此前文档写入，并允许按原请求重试。取消/确认修订及尝试 ID 阻止陈旧完成。

初始目标因模块尚不存在失败；下一切片有 16 项预期的缺少操作失败。空操作编辑及准入测试随后暴露两处真实边界缺口；取消测试暴露提前终态释放及编辑后取消仍重开草稿的问题。手工构造对象测试暴露原文校验绕过。均在最终门槛前修正，没有移除断言或跳过测试。首次默认临时目录运行出现权限错误，实际门槛使用工作区内独立忽略目录。大输入测试标识已缩短以避免 Windows 文件名长度限制。

| 门槛 | 实际执行命令 | 结果 |
|---|---|---|
| 准备及相关集成 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py tests/integration/test_backtest_single_task.py tests/integration/test_monitor_loop_cycle.py tests/integration/test_backtest_results.py::test_backtest_storage_domains_reject_aliases_and_live_tables tests/integration/test_backtest_results.py::test_backtest_stores_reject_each_plan_web_state_table tests/integration/test_backtest_market_store.py::test_market_store_reopens_with_stable_dataset_content -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t07-release` | 92 passed，7.75 秒，包含全部 53 项 ML-T07 案例。 |
| 单元/契约回归 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t07-units-final` | 2809 passed，4 项 live deselected，23.95 秒；在最终两行私有创建/编辑重新校验之前，上方集成门槛覆盖该修改。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts` | 最终源码修改后 PASS。 |
| 既有生成契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | canonical monitor v2 与 compatibility monitor v1 均 PASS，公开模式/类型未修改。 |

自审覆盖原文/元数据权限、精确修订绑定、重启/未知结果、取消占位、显式确认、有界 JSON、幂等快照、回滚、路径分离及并发写入。既有 Starlette/httpx 弃用提示保留。ML-T07 完成；完成 11 项、待完成活动任务 26 项，37 活动 / 保留 39 个 ID，13 个检查点。ML-C03 仍待 ML-T08，ML-T06/ML-T09 继续取消。未调用供应商/付费请求、真实通知、生产状态修改、部署或额外负载夹具。本私有存储切片未增加提取工作线程、跨存储全局准入集成、API、UI 或回测提交入口。

## MV21. 单原文完整计划及期初账户提取

2026-10-08，ML-T08 从 `main` `b3a466c` 继续。修改限定在本项四个主要文件：`ai/loop_plan_extraction.py`、`ai/extraction.py` 的共享接口、`tests/unit/test_monitor_loop_extraction.py` 及 `tests/fixtures/ai/monitor-loop-extraction-cases.json`。同步更新双语方案/任务/验证记录，独立盛新研究不纳入本项。

私有 `monitor-loop-extraction-v1` 输出包含一份完整 Schema 5 候选及强类型期初账户事实。适配器选择 `monitor-loop-extract-v1`；普通提取仍选择 `plan-extract-v9`。两者共用供应商请求限额、响应身份、结束原因检查、脱敏诊断、重复/非有限 JSON 拒绝及既有 1 MiB / 10000 节点 / 64 层深度防护。生成证据和问题后，候选持久化再次应用相同边界。未改变公开结构、路由、工作线程或供应商传输层。

每个经济事实保留精确 Unicode 范围/摘录。有界标签数值及周围语境校验拒绝目标、上限、假想交易、参考行情、否定、建议及原文重叠的重复批次；仓位分组证据必须对应同一个实际数量声明。这些防护不独立验证自然语言真实性，也不授予人工权限。不支持的表述保留供明确审核。原文夹具保留实际 CORE 100、TACTICAL 0 及上限 300；每股 `40.105` 元精确换算总成本 `401050` 分，不先舍入单价，不生成期初 BUY 或取得费用。即使刻意降低 Decimal 精度，不足整分的总成本仍为待解决。参考行情不自动初始化期初估值。

未知现金、分组、取得日期、可卖数量及账户时点保持 null 并阻断；明确零现金和零持仓保持已知。日期证据使用明确标签的精确 ISO 日期/时间戳；取得日期/可卖数量不一致时拒绝。保留可信输入的原文编写/可用/生效元数据并纳入证据摘要，不从导入时间推断，也不用于填充账户日期。原文条款及混合日线/五分钟 ALL/ANY 条件树完整保留，规则数量缺失保持 null。部分成交、挂单容量及基本面退出增加可见的不支持阻断。不接受前版/更新/继承/合并或批准字段。

语义候选可经 ML-T07 持久化/重启往返恢复，保留精确原文及证据摘要、未知可卖数量和完整条款覆盖，不创建审核。不同请求下，相同证据生成相同证据摘要，原文时间修正及账户事实变更会改变摘要。后续工作线程准入/取消排空属于 ML-T10；完整语义审核及冻结属于 ML-T11。

| 检查 | 实际命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t08-release-final` | 93 项通过，2.26 秒；含 70 项新增案例。最终输入类型防护也被以下完整门禁覆盖。 |
| 最终单元/契约及相关集成 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_backtest_single_task.py tests/integration/test_monitor_loop_cycle.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t08-final-gate` | 2967 项通过，4 项 live 测试排除，30.04 秒；包括全部 70 项新增案例及 88 项相关集成。 |
| 普通输出/契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 规范 monitor v2 及兼容 monitor v1 均 PASS。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts --output-format concise`；`.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/ai/loop_plan_extraction.py tests/unit/test_monitor_loop_extraction.py` | PASS。 |
| 变异审查 | 临时反转非实际语境条件，运行 13 项非实际语境案例，在最终门禁前恢复精确原始文件字节。 | 变异下 13 项全部失败；恢复后的最终门禁通过。 |
| 文档/工作区 | `git diff --check`；双语标题/ID/字面契约及原始已完成任务尾部 | PASS；完成 12 项、活动待完成 25 项，37 项活动 / 保留 39 个 ID，13 个检查点。 |

ML-T08 与 ML-C03 完成；ML-T06/ML-T09 保持取消，下一项为 ML-T10。自审覆盖来源保真、精确计算、时序、不得推断事实、传输/解析兼容、有界持久化及明确审核分离。现有 Starlette/httpx 弃用提示保持。检查使用虚拟供应商和临时隔离存储，未进行付费请求、行情下载、真实通知、修改生产状态或部署。该私有适配器无公开准备入口，不绕过既有单个未完成任务要求；后续工作线程/API 集成必须共用该准入规则。不声称完成额外负载验收。

## MV22. 单原文自有提取与显式恢复

ML-T10 已按计划的两个切片完成。可选归属/进度字段扩展既有准备文档，不新增表或数据库版本，旧文档保持可读。仓库只读接口读取精确的既有全局准入 token，包括过期 token。不新增任务类型、队列、数据库、公开路由、全局 AI 预算或通用锁。

新请求在发起前原子绑定一份原文/修订/哈希、代次及服务所有者。自有工作线程在外部调用前持久化 CALLING，HTTP 期间不持有 SQLite 事务。读取与原始幂等回执不发起调用。准入未结束时，RUN/SYNC/VERIFY 及其他准备修改继续被拒绝。取消/原文修正保留准入并丢弃晚到结果；实际工作线程排空后才持久化完成并释放 token。关闭超时及取消等待者仍保留工作归属，直到清理完成。历史编辑回执不能向后来代次的取消 token 发出信号。

配置适配器捕获不可变设置，在自有线程/事件循环中创建、调用并关闭独立 HTTP 客户端。普通提取与回测提取共用既有容量 1。每次持久化尝试禁用传输层重试；配置的已知重试在每原文最多三次持久化尝试内完成。TIMEOUT、不确定传输失败及意外异常保留 UNKNOWN 占位，租约过期/重启后也不释放。显式恢复要求 confirmed_ended true 且本地自有工作已无未结束调用，本身不重发。重启后调用者须明确确认旧工作已结束，因为丢失的付费结果无法证明远端完成。随后新的提取请求消耗剩余尝试额度。精确代次/原文/结果绑定拒绝其他来源或陈旧输出；候选不授予审核或生产启用权限。

| 检查 | 已执行命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t10-release-final` | 29 项通过；覆盖存储兼容、提交前后崩溃、两个服务竞争、晚到原文/结果防护、取消/排空、历史回执重放、过期 UNKNOWN 恢复及三次尝试额度。 |
| 最终单元/契约及相关集成 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_configured_ai_web.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t10-final-regression` | 3000 项通过，排除 4 项 live 测试，34.40 秒。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/backtest/preparation_service.py src/trade_plan_monitor/backtest/preparation_worker.py tests/integration/test_plan_preparation_worker.py` | PASS。 |
| 普通契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | canonical monitor v2 与 compatibility monitor v1 均 PASS；未修改快照/类型/批准摘要。 |
| 变异审查 | 反转历史回执代次相等条件，运行 old-edit 场景，再恢复精确原始源码字节。 | 首次变异暴露缺少另一所有者已取消当前代次的场景；补充后变异导致 1 项失败 / 1 项通过，恢复后检查通过。 |
| 文档/工作区 | 双语 ID/标题/字面契约、原始已完成 todo 历史及 `git diff --check` | PASS；完成 13 项，待完成活动任务 24 项，37 项活动 / 保留 39 个 ID，13 个检查点。 |

下一项为 ML-T11；ML-C04 需 ML-T11/ML-T12 通过后完成。自查覆盖准入/实际工作归属、幂等、陈旧代次/原文/结果防护、已知与未知重试分类、客户端事件循环归属、有界解析及不产生审核权限。检查使用假提供者和临时库，没有付费请求、行情下载、真实通知、生产状态修改或部署。保留既有 Starlette/httpx 弃用提示。独立的概览重试/runtime 修改及盛新研究产物保留在这些提交之外。此私有应用接口没有公开准备入口；语义审核/冻结、API/UI 集成及整体负载验收仍待完成。

## MV23. 明确审核及单份冻结准备清单

2026-10-08 执行 ML-T11，保持其四个主要文件范围。开始本项前，ML-T10 已推送至 GitHub main 的 `75b6c19`。未增加公开准备路由、新表/模式/任务类型/队列、生产激活或运行边界解析。

一次明确确认的审核绑定准备/原文/候选修订及精确提取/证据哈希。AI 输出经过既有来源/字段/账户边界重新验证，VALID 标记、清空的问题列表或旧审核声明不能授予冻结输入权限。只有此人工操作能登记修正草稿/映射、限定补充及有证据的账户修正。缺失技术细节继续阻断，不支持的执行条款不能靠已阅放行。冻结清单同时保留原始期初事实、提取哈希及明确声明的人工账户修正。来源账户的现金、买入日期、可卖数量和期初行情未经明确证据继续未知。冻结前检查历史账户/行情可用时间和持仓上限。

既有事务原子写入一份有界不可变清单、精确审核声明及原始幂等收据。收据写入失败会全部回滚且不占用键。修正原文使当前候选/审核失效，原始收据在重启及其他工作占位时仍可读。修改来源后，已构造的 MonitorLoopInput 保持相同规范字节/哈希。审核、读取及收据重放不产生付费请求或隐式重试。

审核复用既有全局准入令牌和自有有界元数据线程。RUN/SYNC/VERIFY 的 QUEUED/RUNNING/CANCEL_REQUESTED/过期状态、未解决预留（包括同一审核键）及未完成提取清理都会阻止新审核。观察者取消/关闭超时在实际元数据工作结束前保留准入。耐久原始审核收据证明操作已完成，可在提交与释放之间崩溃后清理精确预留；无收据即便过期也不授权抢占。

| 检查 | 已执行命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t11-gate-final` | 51 项通过；覆盖精确绑定、缺失确认/细节/时间、未知事实、不可变输入、伪造来源/旧标记、原文失效、回滚、全局占位、实际排空及提交/释放恢复。 |
| 最终单元/契约及相关集成 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_review.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_configured_ai_web.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t11-final-regression` | 3051 项通过，4 项 live 未选中，34.54 秒。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/backtest/preparation_review.py tests/integration/test_plan_preparation_review.py` | PASS。 |
| 普通契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | canonical monitor v2 与 compatibility monitor v1 均 PASS；未修改快照/类型/批准摘要。 |
| 变异审查 | 反转期初行情可用时间比较，运行 opening_account_information 场景，再恢复精确源码字节。 | 变异：1 项失败 / 1 项通过；恢复：2 项通过。此前失败用例暴露冻结阶段缺少未来期初行情防护，已在最终回归前修复。 |
| 文档/工作区 | 双语 ID/标题/字面契约、原始已完成 todo 历史及 MV01–MV22 历史、`git diff --check` | PASS；完成 14 项，待完成活动任务 23 项，37 项活动 / 保留 39 个 ID，13 个检查点。 |

下一项为 ML-T12；ML-C04 仍待以真实 HTTP 和假 AI 验证公开准备路径后完成。自查覆盖明确权限、规范哈希/修订绑定、原始证据及未知事实、原子存储、历史因果、单槽准入及实际工作归属。检查使用合成输入和临时库，没有付费请求、行情下载、真实通知、生产状态修改或部署。保留既有 Starlette/httpx 弃用提示。独立的概览重试/runtime 修改及盛新研究产物保留在这些提交之外。API/UI/报告集成及整体负载验收仍待完成。

## MV24. 单原文准备 HTTP 与按需归属

2026-10-08 继续 ML-T12 前，ML-T11 已推送至 GitHub main 的 `d2edc5b`。两个既定切片保持在七个主要文件内：`backtest/preparation_store.py`、`backtest/preparation_service.py`、`backtest/composition.py`、`web/preparation_schemas.py`、`web/routers/backtest_preparations.py`、`web/app.py` 及 `tests/integration/test_plan_preparation_api.py`。中英文方案/任务/验证文档同步；独立概览重试/运行时修改及盛新产物继续排除。

应用挂载恰好单原文的创建/读取/编辑/提取/取消/审核/恢复命令。封装字段使用 camel case，内嵌研究值保留既有字段名。原文继续限于 150000 字符，候选持久化限于 1 MiB，公开进度限于 2 MiB，输入传输沿用既有 4 MiB。修订遵守安全整数。投影包含类型化候选/账户/映射或冻结值，以及代次/阶段进度和有界尝试；排除原始候选 JSON、私有归属/准入令牌、供应商诊断及文件系统路径。格式错误的不透明候选和旧审核标记投影为 UNAVAILABLE，不能产生冻结权限。

来源、命令、标识符、查询和变更键校验在能力取得前完成。准备库仅在明确且有效的准备请求时打开；未使用的启动/历史/关闭不打开该库。元数据操作保持任务协调器休眠，不捕获或调用 AI。新提取先检查旧回执和全局准入，再捕获既有配置适配器。缺少 AI 不建立尝试。准备库取得失败会缓存并保持局部影响；监控和普通任务读取仍可用。修复文件不重试取得，既有明确生命周期重试才会重试。

新的创建/编辑/提取/取消/审核命令拒绝 QUEUED/RUNNING/CANCEL_REQUESTED/过期状态的 RUN/SYNC/VERIFY。原创建/编辑/取消/提取/审核回执在后续工作期间仍可读取，不恢复旧状态或分派新调用；GET 返回当前状态。取消/编辑原文在工作线程实际完成前保留全局准入，丢弃晚到结果并保持精确原文/代次保护。未知结果在重启后保留准入；明确绑定代次/修订并确认结束的恢复不重新提交，后续提取要求新的明确请求。已取得准备资源关闭在内部观察超时后继续保持实际归属，排空后才关闭 AI；未用能力关闭不取得资源。

两项 HTTP 回归首先暴露旧编辑/取消回执被其他工作阻断，另一项暴露准入前捕获 AI 配置。修复将旧回执重放移至新工作准入前，将适配器捕获移至准入后。未弱化断言、边界或跳过项。真实本地 Uvicorn/httpx 流程使用假 AI 及临时数据库，验证取消 → 编辑 → 提取 → 审核 → 重启，以及不隐式调用的不可变回执重放。

| 检查 | 实际执行命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q --tb=short -m 'not live' --basetemp=.pytest_cache/ml-t12-release-final` | 53 项通过，17.14 秒。 |
| 最终单元/契约及相关集成 | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_review.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_configured_ai_web.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_index_api.py tests/integration/test_web_api.py tests/integration/test_openapi_snapshot.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t12-final-regression` | 3484 项通过、1 项既有跳过、4 项在线测试未选，113.21 秒；包含全部 53 项任务检查。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts`；`.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/web/preparation_schemas.py src/trade_plan_monitor/web/routers/backtest_preparations.py tests/integration/test_plan_preparation_api.py` | PASS。 |
| 普通契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 权威监控 v2 及兼容监控 v1 均 PASS；未修改快照/类型/批准摘要。 |
| 变异审阅 | 临时反转新增的原变更回执条件，运行编辑/取消重放检查；最终回归前恢复原始文件精确字节。 | 变异下 2 项失败；恢复后最终回归通过。 |
| 文档/工作区 | 双语标题/ID/字面契约、原已完成任务尾部、MV01–MV23 历史及 `git diff --check` | PASS；完成 15 项、待完成活动任务 22 项，37 活动 / 保留 39 个 ID，13 个检查点。 |

ML-T12 与 ML-C04 完成；下一项为 ML-T13。路由已挂载，模式发布仍以 `include_in_schema=False` 暂存；ML-T13 发布该标志并生成契约供具体审阅，不静默批准摘要。自审覆盖边界、类型化投影、全局准入、原回执、精确修订、晚到结果保护、实际归属、重启及明确人工权限。既有 Starlette/httpx 弃用提示保持。未发生付费/供应商/行情调用、真实通知、生产计划变更或部署。UI/运行/结果集成及整体负载验收仍待完成。

## MV25. 发布准备契约并保留兼容性

2026-10-08 继续 ML-T13 前，ML-T12 已推送至 GitHub main `0d5b603`。传输切片提交为 `abf20db`。范围在实施前扩展为三个切片、八个主要文件：`src/trade_plan_monitor/web/preparation_schemas.py`、`src/trade_plan_monitor/web/routers/backtest_preparations.py`、`scripts/generate_frontend_types.py`、`openapi.json`、`openapi.runtime-status.json`、`web/src/api/generated.ts`、`web/src/api/generated-runtime-status.ts` 和 `tests/integration/test_plan_preparation_contract.py`。发布和生成产物共同提交为 `fdf250d`。独立 runtime/overview-retry 修改及盛新文件继续排除。

已挂载路由发布七项单原文操作，保留现有错误、变更键和修订要求。取消记录实际 200/202 结果；成功响应记录 no-store 及有界 Location，受理工作记录 Retry-After 2。公开候选为 EXTRACTION/FROZEN/UNAVAILABLE 可判别联合，各分支载荷互斥且必填。公开内嵌审核、尝试及冻结修订共用安全整数上限；成功字段名称/null 值不变。两种 profile 均检查单原文、最多三次尝试、明确确认恢复、未知/零现金区分和私有状态排除。TypeScript 示例编译验证穷尽候选收窄及有效命令，并拒绝 false 恢复确认和 null 冻结清单，没有使用抑制指令。

发布审核请求后，Pydantic 起初将既有验证/序列化定义拆为含 -Input/-Output 的名称，现有生成器因此拒绝。三个回归用例首先失败。现有生成器现规范化组件名称及全部引用：输出保留原名称，独立输入追加 Input；重名明确失败。验证/序列化结构仍独立。此问题对应官方记录的 [Pydantic 模式行为](https://pydantic.dev/docs/validation/latest/api/pydantic/config/?query=alias_generator)。相对 `0d5b603` 的离线比较确认，全部 52 个旧路径项及 compatibility-v1 的 287 个 / canonical-v2 的 300 个旧模式语义完全相同；每个旧 TypeScript 别名及操作块字节一致。每种 profile 新增七条路径和 71 个模式。全部引用可解析，进度/冻结闭包不含持久化私有记录、归属/准入令牌、不透明载荷 JSON 或服务商诊断。

| 检查 | 执行命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q --tb=short --basetemp=.pytest_cache/ml-t13-type-green` | 20 项通过，8.05 秒；包括两种 profile 及实际 TypeScript 编译。 |
| 最终单元/契约及相关集成 | 单元/契约套件和 MV24 集成选择，另加准备契约及前端契约晋级测试；`-q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t13-final-regression` | 3509 项通过、2 项批准失败、1 项既有跳过、4 项 live 未选择，172.42 秒；包括全部 53 项准备 HTTP 用例。 |
| 既有前端 | `npm --prefix web run test -- --run`; `npm --prefix web run type-check`; `npm --prefix web run build` | 807 项测试 / 57 个文件通过，12.18 秒；类型检查和构建 PASS。 |
| 代码质量 | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check scripts/generate_frontend_types.py src/trade_plan_monitor/web/preparation_schemas.py src/trade_plan_monitor/web/routers/backtest_preparations.py tests/integration/test_plan_preparation_contract.py` | 恢复一致源码格式后 PASS。 |
| 生成产物 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | canonical monitor v2 和 compatibility monitor v1 均 PASS。 |
| 变异审阅 | 临时允许 FROZEN 清单为 null，运行 frozen-missing 候选拒绝用例，然后恢复精确原始字节。 | 1 项预期失败，19 项未选择；恢复后最终回归通过此用例。 |
| 文档/工作树 | 双语标题/ID/字面契约、保留已完成 todo 尾部及 MV01–MV24 历史、无关文件摘要未变、`git diff --check` | PASS；完成 16 项、待完成活动任务 21 项，37 项活动 / 保留 39 个 ID，13 个检查点。 |

批准仍待 ML-T29。未改动的 `test_openapi_change_requires_bilingual_spec_approval` 因候选 v1 快照摘要未在已批准双语规格中而失败；`test_openapi_contains_only_approved_paths_and_public_error_schemas` 因七条准备路径不在 APPROVED_PATHS 中而失败。测试/断言和已批准摘要均未修改、跳过或抑制。已批准基线仍为 `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`。候选 SHA-256，待批准：compatibility v1 `1fd4eea69dbe1827c35ca2f19a0261296be5e447f293d7a2e52c4fc8a5c9e3a4`；canonical v2 `7e5f0a6ebec6ce3cefd440af7d9619e9332e22dd081f3f667b40a7c08473a367`。

ML-T13 实现及生成完成；下一项为 ML-T14，ML-C05 仍待上传/进度/审核 UI。自审覆盖兼容性、模式/名称引用、可判别分支、边界、私有状态排除和实际成功/错误行为。既有 Starlette/httpx 弃用提示仍在。测试使用临时存储及假 AI，没有付费/服务商/行情调用、生产状态修改、通知或部署。最终 API 批准及完整交付验收仍待完成。

## MV26. 单原文输入、进度与稳定请求控制

ML-T13 于 2026-10-08 继续 ML-T14 前推送至 GitHub main，提交为 `c31904d`。三个切片使用五个不同主要文件：`web/src/api/preparations.ts`、`web/src/composables/usePlanPreparation.ts`、`web/src/components/backtests/PlanPreparationSourceForm.vue`、`web/src/components/backtests/PlanPreparationProgress.vue` 及 `web/tests/unit/PlanPreparation.spec.ts`。前两个切片分别提交为 `9f61cdd` 和 `c5018f1`。最后组件切片同时修复同一控制器的未保存原文及旧读取刷新处理（2 / 2 / 4 个文件，共 5 个不同文件）。中英文计划/任务/验证记录及浏览器证据随窄范围代码同步；其他运行时/概览重试修改及盛新研究文件保持排除。

传输复用现有有界、冻结、脱敏的同源 JSON 层，接受一份内嵌原文，校验标识符/安全修订/上海时间顺序、进度信封及候选区分边界，并检查实际成功状态、no-store、Location 和 Retry-After 2。候选语义审核继续由后端负责，审核 UI 接入属于 ML-T15。不修改生成快照/类型/已批准规格或后端。

单份控制器拥有一份草稿/准备及一份不可变的未结束变更意图。重复点击合并；结果未确认时保留原请求键、修订和载荷，供明确重放原回执。读取不会隐含重放变更。旧原始回执及过时读取不能降低当前状态修订。读取失败保留原文编辑；修改原文后须先保存才能提取。明确拒绝的新建恢复可编辑状态。取消等待、UNKNOWN、原文编辑清理及其他未结束实际工作继续阻止新操作，包括表面已处于 FAILED/CANCELLED 的状态。代次/修订绑定的 UNKNOWN 恢复要求明确结束确认，不自动提取。读取不重叠，在空闲/实际排空时停止，页面隐藏时暂停，卸载时停止；取消/晚到读取及变更响应不能更新已销毁状态。

受控表单接受粘贴文本或恰好一份 UTF-8 .txt/.md 文件，上限 600000 字节及 150000 Unicode 字符。可选上海时间戳/日期不补造。无效/多份/超大文件保留此前证据，显示转义错误；手动编辑、原文/禁用状态变化及卸载使晚到文件读取失效。复用原生标签、焦点、状态/错误宣告及现有设计变量。进度组件显示取消等待、尝试次数及明确提取/取消/刷新、同请求安全重试和确认恢复。观察到修订/代次变化时清除恢复确认。生产页面组合及审核计划预览留待 ML-T15，ML-C05 仍待完成。

新增三项回归先暴露新建被拒后编辑仍锁定、未保存原文仍可提取、旧读取使刷新永久忙碌；各项在修复前失败，最终测试全部通过。浏览器夹具采用真实本地 HTTP 与合成候选信封值，只验证进度，不作语义审核或生产路由验收。当前没有 Chrome DevTools MCP，因此使用已安装 Playwright/Chrome 进行真实浏览器验证。临时界面/服务在证据记录后关闭并移除。

| 检查 | 已执行命令/证据 | 结果 |
|---|---|---|
| 本项门禁 | `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts` | 50 项通过，覆盖传输、单份控制器、原文/进度组件及失败/生命周期边界。 |
| 全部前端 | `npm --prefix web run test -- --run`; `npm --prefix web run type-check`; `npm --prefix web run build` | 857 项 / 58 文件通过，8.60 秒；类型检查及构建 PASS。 |
| 相关后端/API 契约 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_contract.py tests/integration/test_frontend_contract_promotion.py tests/integration/test_openapi_snapshot.py -q --tb=short -m 'not live' --basetemp=.pytest_cache/ml-t14-contract-regression` | 92 项通过，恰有 2 项原有批准门禁失败，73.19 秒；全部 53 项准备 HTTP 及 20 项准备契约检查通过。 |
| 生成产物 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | 权威 monitor v2 及兼容 monitor v1 均 PASS；快照/类型保持一致。 |
| 真实浏览器 | [机器可读流程证据](evidence/2026-10-08-plan-preparation-ui/browser-summary.json) | 一次新建、4 次明确提取、一次取消、一次确认恢复及一次原回执重放。先保存才提取、实际结束等待、同键/载荷重放、无效 UTF-8 保留、键盘 Tab 及停止轮询均 PASS。320 / 768 / 1024 / 1440 宽度无横向溢出或 axe 违规；控制台/页面错误及外部请求均为零。 |
| 视觉证据 | [320 宽候选](evidence/2026-10-08-plan-preparation-ui/candidate-320.png)、[1440 宽候选](evidence/2026-10-08-plan-preparation-ui/candidate-1440.png)、[取消等待](evidence/2026-10-08-plan-preparation-ui/cancel-wait-1440.png)、[确认 UNKNOWN 恢复](evidence/2026-10-08-plan-preparation-ui/unknown-confirmation-1440.png) | 已检查响应布局、展开的可选日期、操作控件及恢复确认。 |
| 变异审查 | 反转未结束工作条件，执行实际排空用例后恢复原始字节。 | 变异时 2 失败 / 2 通过（检测 FAILED/CANCELLED 保护），其他测试被筛选；恢复后最终 50 项全部通过。 |
| 文档/工作区 | 成对标题/ID/字面契约、保留既有已完成 todo 尾部及 MV01–MV25、无关文件哈希、`git diff --check` | PASS；完成 17 项、待完成活动任务 20 项，37 项活动 / 保留 39 个 ID，13 个检查点。 |

首次后端检查采用无法访问的 Windows 系统 pytest 临时目录（70 项 setup 错误）；改用以上明确的工作区 basetemp 重跑后全部消除，不改测试。临时浏览器夹具起初将模拟 HTTP 处理器注册在 Vite fallback 之后，导致 404；提前注册后最终流程通过。这两项均是验证环境修正。两项未改动批准失败为 `test_openapi_change_requires_bilingual_spec_approval` 和 `test_openapi_contains_only_approved_paths_and_public_error_schemas`，已在 MV25 记录并待 ML-T29。不改变任何断言/skip/已批准摘要。保留既有 Starlette/httpx 弃用提示。

ML-T14 已完成，下一项为 ML-T15。自审覆盖不可变意图及权威修订处理、未保存原文、原文/文件竞态、单个未结束工作、实际排空、生命周期归属、有界轮询、安全渲染及无障碍。不新增批次/队列/通用锁、付费/供应商/行情调用、生产状态修改、通知或部署。最终 API 批准及整体验收仍待完成。

## MV27. 精确准备审核与创建页面

2026-10-09 开始 ML-T15 前，ML-T14 已推送 GitHub main 的 `9d08083`。ML-T15 使用四个限定切片（5 / 3 / 2 / 5 个主要文件，含共用测试及后端生成样例共八个不同文件）。初始传输/预览和控制器/组件提交为 `f887b7c` 与 `efc6df0`；页面组合和真实 HTTP 凭据修正在最终验证后共同提交。配套更新中英文方案/清单/证据和浏览器产物，已有无关运行时/概览重试及盛新文件均排除。

可读预览保留全部完整规则、原始账户事实/片段、精确 40.105 元每股成本、原文编写/可用/生效日期、全部条款和待解决项。已知但缺少绑定的值要求逐项明确说明；必要技术参数、时间、持仓归属缺失及未解决/不支持条款阻止审核。可保留的未知账户事实保持未知并单独确认。零现金与未知区分，不补造价格、时间、持仓或成本。审核只提交当前原始内容和明确人工补充，不提供操作 JSON 或启用生产计划。

审核使用生成的 `PreparationReviewInput` 和实际 `PreparationFrozenView` 凭据，精确绑定准备/原文/候选修订及摘要。确认凭据后再有界读取最新状态；失败/旧读取不能解锁编辑、再次审核或可用权限，直至观察到审核后的最低修订。不确定操作保留同一不可变命令/请求键。未结束工作、取消等待及 UNKNOWN 保持互斥。确认随原文/候选/审核修订或本地原文变化清除，原文编辑即时使冻结权限失效。迟到完成不能更新已卸载状态。形状校验有界，每次校验仅展开一次原文 Unicode 码点；语义批准仍归后端。

既有创建页面默认显示旧回测表单，明确选择方式后组合单份原文、进度和审核；明确指定准备 ID 可恢复只读/当前状态。仅打开页面不获取准备资源。未结束/不确定准备或旧运行提交阻止切换方式。新闭环回测提交留在 ML-T24，本项不代表完整运行验收。

| 检查 | 已执行命令/证据 | 结果 |
|---|---|---|
| 本项及相关 UI | `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts tests/unit/PlanPreparation.spec.ts tests/unit/BacktestNewView.spec.ts` | 96 项通过，其中本项 27 项，3.29 秒。覆盖真实候选/冻结样例、旧凭据、未知事实、精确重试、最低修订下的失败/旧读取、原文失效、卸载及旧表单。 |
| 全部前端 | `npm --prefix web run test -- --run --maxWorkers=4`; `npm --prefix web run type-check`; `npm --prefix web run build` | 884 项 / 59 文件通过，22.59 秒；类型检查与构建 PASS。 |
| 准备服务端回归 | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_review.py tests/integration/test_plan_preparation_contract.py -q -m 'not live' --basetemp=.pytest_cache/ml-t15-api-review --tb=short` | 124 项通过，42.69 秒，一项已有 Starlette/httpx 弃用提示。 |
| 生成契约 | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --monitor-contract-version 2 --check` | 权威 v2 与兼容 v1 PASS，快照/类型未变化。 |
| 真实挂载 HTTP 与浏览器 | [机器可读流程](evidence/2026-10-09-plan-preparation-review/browser-summary.json) | 真实 `BacktestNewView`、生产准备路由、临时存储及假 AI，仅旧计划查询为替身。一次新提取、明确逐项审核/冻结、精确 401050 分成本及编辑/保存失效 PASS。320 / 768 / 1024 / 1440 宽度：溢出 0，axe 违规 0；控制台/页面错误和外部请求 0。用键盘 Space 确认已标注审核复选框。 |
| 可视证据 | [320 宽候选](evidence/2026-10-09-plan-preparation-review/candidate-320.png)、[1440 宽候选](evidence/2026-10-09-plan-preparation-review/candidate-1440.png)、[已审核](evidence/2026-10-09-plan-preparation-review/reviewed-1440.png)、[编辑原文](evidence/2026-10-09-plan-preparation-review/source-edited-1440.png) | 记录完整规则/账户证据的响应式显示、完整审核及即时原文失效。 |
| 变异审查 | 移除可用准备权限中的原文脏值保护，运行原文编辑用例，再恢复精确字节。 | 变异后 1 项失败，其余筛除；验证精确恢复，最终 96 项门禁通过。 |
| 文档/工作区 | 中英文标题/ID/字面量、历史 todo 尾部和 MV01–MV26 保留、无关文件摘要及 `git diff --check` | PASS；完成 18 项、待完成 19 项、37 项活动 / 保留 39 个 ID、13 个检查点，ML-C05 完成。 |

首次真实浏览器审核暴露前端传输格式错误：接口返回冻结凭据，与其他命令的进度投影不同。后端已审核成功，但客户端对未识别响应保持不确定状态。测试改为实际生成凭据后，在修正传输/控制器前失败；最终真实挂载流程通过。首次前后端并行验证发生两个未改动的 5 秒惰性页面测试超时（880 项通过、2 项超时）；单独限制四个 worker 后完整前端通过，未提高超时或弱化断言。临时浏览器中的日期填入格式也已修正。Chrome DevTools MCP 不可用，使用已安装 Playwright/Chrome 验证；临时服务和界面已关闭并移除。

API 批准仍待 ML-T29。此前两项批准门禁与已批准规格未改变，本项 124 项准备门禁未重复执行它们。已批准摘要：`8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`；未变化候选 v1：`1fd4eea69dbe1827c35ca2f19a0261296be5e447f293d7a2e52c4fc8a5c9e3a4`；v2：`7e5f0a6ebec6ce3cefd440af7d9619e9332e22dd081f3f667b40a7c08473a367`。不改后端/契约/批准，不调用真实或付费服务，不写生产状态、不通知或部署。ML-T15/ML-C05 完成，下一项为 ML-T16。


## MV28. 截止安全的数据选择与部分交易日

2026-10-09，基于已推送 `476c874` 完成 ML-T16，限定 5 个主要实现/测试文件，同步配对任务/计划/验证文档。新增独立 `monitor-loop-dataset-v1` 清单与 `LoopFrozenSymbolDay`，保留旧数据格式及全日就绪判定。

| 验证 | 执行 | 结果 |
| --- | --- | --- |
| 任务门禁 | `tests/integration/test_monitor_loop_dataset.py`、`tests/unit/test_monitor_loop_cutoff.py`、`tests/integration/test_backtest_compatibility.py` | 30 项通过，最终 2.82 秒。 |
| 相关回归 | 上述任务检查，加旧市场存储/指数数据集/目录查询/运行器/输入、闭环输入/计划时间表/循环 | 159 项通过，56.11 秒。 |
| 静态检查 | 5 个改动主要文件的 Ruff 检查和格式检查 | PASS，未增加忽略/跳过。 |
| 变异审阅 | 临时将五分钟预热组成判断 `all` 改为 `any`，执行缺失组成分钟用例 | 1 项预期失败、15 项未选择；恢复精确原始字节，最终任务检查全部通过。 |
| 文档与工作区 | 配对结构/稳定字面量、旧任务历史尾部、MV01–MV27 原文、无关文件摘要与 `git diff --check` | PASS；完成 19 项，待完成 18 项。 |

读取同一 SQLite 快照中的不可变日历/分钟/限价/日线引用，保留截止前到达的分钟修订及到达顺序，排除截止后证据。缺少已闭合区间、必需限价、官方收盘或日线预热时明确拒绝，绝不倒退截止时间。初始分钟预热不足保留原因，受影响规则在足够完整五分钟区间到达前保持 UNKNOWN；预热要求按该份完整计划计算，包括最大 500 个历史五分钟区间。午休/收盘不制造额外区间，节假日结束仍保留请求日期。部分交易日不冒充完整交易日。

部分分钟写入复用原有内容哈希与存储格式，不生成旧全日 `MINUTE` 工件，也不增加目录就绪记录。既有日线/限价的确定性历史到达契约保持；本项不引入新的实时日线写入器。重新读取冻结选择只按工件哈希，缺失/损坏明确失败，不回退当前 head。ML-T17 将清单和依赖工件耐久复制到运行输入，故本项尚不宣称脱离市场库的留存保障。无新数据库/表/迁移、HTTP 契约、批准、真实服务调用或生产状态写入。API 批准仍待 ML-T29。ML-T16 完成，下一项为 ML-T17。
