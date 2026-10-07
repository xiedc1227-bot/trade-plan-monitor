# 验证记录：监控闭环回测

英文权威版；中文审阅副本：[monitor-loop-backtest.zh-CN.md](monitor-loop-backtest.zh-CN.md)。更新于 2026-10-07，Asia/Shanghai。本记录为已执行的部分证据，不是最终验收。基线：`main` `e95de03`，保留已有未提交设计与盛新研究文件。实施已获授权；用户随后于 2026-10-07 授权清理、提交并推送至 GitHub。付费请求、生产迁移和部署仍在范围外。

当前进展见 MV12：ML-T33、ML-T34 与 ML-C12 已验证，既有统一研究 OpenAPI 的陈旧批准已具体审阅并纠正。MV01–MV10 保留为当时证据；MV11 启动解耦 PASS 保持不变。以下历史待定/失败文字不代表当前阻断。

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
