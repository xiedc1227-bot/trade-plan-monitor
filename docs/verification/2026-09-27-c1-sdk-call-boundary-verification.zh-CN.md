# C1 SDK 调用边界验证

## SCBV-01 状态与范围

状态：**REVIEWED / approved for local commit**。

主协调在基线完整测试结束后解除源码冻结，授权实现[已评审边界契约](2026-09-27-c1-sdk-call-boundary-contract.zh-CN.md)。最初两轮独立 Sol 评审只批准了设计；随后独立代码评审发现 P2，修复后独立复审确认源码无剩余 P1/P2。本文区分作者运行与评审者运行，不宣称整个仓库测试通过。主协调已确认双语文档一致，仅授权本片 10 文件的本地提交。

resolver 在每次调用的最终 guard 前完成真实认证 wrapper 准备并解析内层 SDK callable，使用名义类型识别，不探测可选动态属性协议，不使用共享可变 hook。私有 callback 参数在本地消费。公共模块只导入标准库，既有 sentinel 类与 controller 保持不变。

纳入路径为两个股票分钟证明端点、DAILY_BARS、DAILY_LIMITS、INDEX_DAILY 和 INDEX_REALTIME_MINUTES。production 最终 guard 在 authority 读取后重验时间，包括原 legacy 认证边界和实时指数严格语义过期条件。STOCK semantic 模式不新增 legacy 过期规则。未传可选 hook 的普通调用保留既有 wrapper 路径。

## SCBV-02 精确文件归属

本片仅拥有以下 **10 个文件**：

| 文件 | 改动 |
| --- | --- |
| `src/trade_plan_monitor/market_data/sdk_call_boundary.py` | 新增名义 resolver 契约及 callable 校验 |
| `src/trade_plan_monitor/market_data/tushare.py` | 股票权限调用先准备再执行最终 guard，保留普通路径 |
| `src/trade_plan_monitor/market_index/tushare.py` | 日线/实时指数权限调用先准备再执行最终 guard/S |
| `src/trade_plan_monitor/runtime/production.py` | 认证 resolver 实现及最终同一时间的模式/窗口检查 |
| `tests/unit/test_sdk_call_boundary.py` | 73 项离线协议/provider 用例 |
| `tests/integration/test_production_sdk_call_boundary.py` | 49 项 owner/controller/持久化用例 |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-contract.md` | 英文契约及设计评审记录 |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-contract.zh-CN.md` | 对应中文契约 |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-verification.md` | 英文实现验证 |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-verification.zh-CN.md` | 对应中文验证 |

未删除、弱化、跳过或标记 xfail 任何既有测试断言。其他工作区改动，包括 position/R13/R14/R17 fixture 对齐及 A07 启动分钟覆盖，属于其他任务，本片未编辑、暂存，也未将它们纳入测试命令。`tushare_client.py` 与 `request_control.py` 保持不变。

## SCBV-03 RED 到 GREEN 证据

| 阶段 | 实际结果 |
| --- | --- |
| 生产修改前 PB01 | **2 failed**：两个真实 wrapper 股票分钟用例均在认证将 fake clock 从 14 秒推进到 16 秒后调用 SDK，未抛出预期异常 |
| 实现名义 resolver 与 provider 顺序 | PB01 加既有日线/分钟/指数 parser 及 transport 选择集：**364 passed** |
| 时间 guard 修复前实时指数最终过期用例 | **2 failed, 20 passed**：最终 S 达到或超过有效期后仍进入 SDK，随后才失败，而非在 SDK 前返回 DEFERRED |
| 时间 guard 修复前 legacy 股票过期用例 | **2 failed, 4 passed**：DAILY_BARS 与 DAILY_LIMITS 同样在进入后才失败；legacy 等号及 STOCK semantic 兼容性对照通过 |
| 代码评审 P2 前的新增边界文件 | **114 passed**：73 项 unit、41 项 integration |
| P2 前历史相邻 provider/transport/普通路径回归 | 8 个既有 unit 文件共 **471 passed** |
| P2 前历史相邻 production 权限/认证回归 | 11 个既有 integration 文件共 **310 passed** |
| 作者 P2 后边界复跑（A1） | **122 passed**：73 项 unit、49 项 integration |
| 作者 P2 后受影响 production 复跑（A2） | 5 个既有 integration 文件共 **178 passed** |
| 主协调转达的独立 P2 后代码复审运行（I1） | **146 passed, 1 warning in 45.92s**：122 项边界加 24 项既有实时指数用例 |

**114/471/310** 是 P2 前的历史证据，在当时版本合计 **21 个文件、895 passed**，不是 P2 修复的最终验收。P2 后作者 A1/A2 合计 **7 个文件、300 passed**。独立 I1 与 A1 全部重叠，并与 A2 的 24 项实时指数用例重叠。不得把 I1 与 A1/A2 相加，也不得把 P2 后运行与历史 895 相加为独立测试数量。命令及文件选择集见 SCBV-05。integration 组出现既有 Starlette/httpx 弃用警告。四个源码文件及两个新增测试的 Ruff 通过，P2 修改的两个文件再次通过 Ruff；限定范围差异/空白及双语结构检查通过。

hash 稳定说明仅适用于对应版本的验证时间段。历史 114/895 运行与 P2 修复之间确实修改过源码/测试。作者 P2 后 A1/A2 运行结束后，报告核对期间未再编辑源码/测试；独立 I1 针对该修复版本。这不表示 hash 跨越 P2 修改仍保持不变。

编写测试时修正的 fixture 构造问题不计作行为 RED 证据。不以较早完整测试结果或此前边界冻结计数替代上述新增测试。

## SCBV-04 PB01–PB13 证据映射

| ID | 本地证据 |
| --- | --- |
| PB01 | `test_pb01_real_wrapper_cannot_enter_at_16_seconds_after_guard_at_14`，覆盖两个股票分钟端点 |
| PB02 | `test_all_proofs_resolve_and_certify_before_final_guard`：合法认证/解析耗时、精确顺序、单次 S 及匹配 evidence |
| PB03 | 同一六端点矩阵在动态端点解析中推进时间，准入过期时 SDK 零调用 |
| PB04 | `test_realtime_index_final_s_rechecks_expiry_after_authority_io` 和 `test_stock_final_time_preserves_legacy_and_semantic_rules`：指数严格过期、legacy 包含等号、跨过有效期及回拨到 observed_at 之前 |
| PB05 | 股票最终时间矩阵中的 STOCK semantic 用例超过 legacy 证据有效期仍成功 |
| PB06 | 真实 wrapper production 矩阵对四个 owner 路径覆盖合法耗时、过期、epoch 撤销、市场碰撞、stop 及配置变化；排空测试覆盖 DAILY_BARS 认证期间取消。`test_final_authority_io_rechecks_memory_fences_before_sdk` 对四个 owner 新增 wrapper 准备完成后最终 authority IO 内部的 generation/admission 撤销 |
| PB07 | 六端点 sentinel 身份矩阵及真实 controller/持久化状态检查；取消/超时排空测试区分迟到 sentinel 与此前已记账的 timeout backoff |
| PB08 | 动态 fake SDK 拒绝任何非 operation 查找。installed DataApi 查找跟踪只允许真实 operation，并断言精确 endpoint kwargs |
| PB09 | installed 默认/直连 query 路径外包真实认证 wrapper，经离线 transport 替身到达股票分钟 strict parser |
| PB10 | 并发及嵌套 provider 调用保留各自 hook/S；嵌套名义 wrapper 在 guard 前完成全部检查，不共享 callable 准备 |
| PB11 | 股票分钟 S/latest 和 R-S 边界用例；真实 DAILY_BARS owner 在认证或 SDK 执行期间取消/超时后保留权限阻塞，释放维护锁，物理 slot 排空后才允许后续工作 |
| PB12 | DAILY_BARS、DAILY_LIMITS、INDEX_DAILY、INDEX_REALTIME_MINUTES 使用真实 wrapper、真实 owner/controller 与临时 SQLite；重开库检查预约，本地拒绝不增加供应商 backoff，既有轮转 callback 恰好一次，worker 零 SQL |
| PB13 | 普通 daily/history kwargs 与官方记录、普通 wrapper 拒绝，以及相邻 provider/client/index/historical 回归 |

股票分钟 owner 接线仍是独立片：这些测试覆盖其 provider 证明边界，不代表新增了股票分钟 owner。保留既有 INDEX_REALTIME_MINUTES 轮转行为，未新增预约 callback。

## SCBV-05 复现

在 `trade-plan-monitor/` 下使用现有虚拟环境执行。以下可复现选择集排除在线服务、独立 A07 测试及无关 fixture 对齐工作。A1/A2 是作者 P2 后选择集，I1 是主协调转达的独立复审选择集。历史 114/895 计数属于 P2 前源码/测试版本，不能把更新后的文件视作旧版本来复现这些计数。

```powershell
# A1: author post-P2 boundary selection, 122 passed
.venv/Scripts/python -m pytest tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
# H1: historical pre-P2 provider/transport selection, 471 passed
.venv/Scripts/python -m pytest tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_daily_permission_proofs.py tests/unit/test_realtime_index_permission_parser.py tests/unit/test_tushare_client.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_historical.py -q --tb=short
# H2: historical pre-P2 production selection, 310 passed
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_certification_gate.py -q --tb=short
# A2: author post-P2 affected production selection, 178 passed
.venv/Scripts/python -m pytest tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_certification_gate.py -q --tb=short
# I1: independent post-P2 review selection, 146 passed
.venv/Scripts/python -m pytest tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py tests/integration/test_production_index_realtime_permission_probe.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/market_data/sdk_call_boundary.py src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py src/trade_plan_monitor/runtime/production.py tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py
git diff --check -- src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py src/trade_plan_monitor/runtime/production.py
```

## SCBV-06 保留边界与交接

S 是调用已准备内层 SDK callable 前的调用点标记，不是 socket 发包时刻。S 后仅做纯值/内存检查及调用，操作系统调度和 SDK 内部工作仍可能发生。不宣称强制中断或对外部状态的原子观察。响应快照验证与 controller 清权限仍是两个操作。

INDEX_HISTORICAL_MINUTES 仍缺最终 provider seam。日历权限、历史股票及普通业务路径没有新增最终边界验收，其兼容性测试通过不能关闭该缺口。不包含 scheduler 或 A07 生产改动。

主协调改动前完整测试结果为 **18 failed, 4778 passed, 1 skipped, 4 deselected**。这些 position/R13/R14/R17 失败由独立任务调查，本片不宣称整个仓库测试通过。独立 A07 预期 RED 不计入上述 895 项通过。

独立复核及双语文档核对通过后，主协调授权仅本片精确 10 个文件的本地提交。提交后释放 `production.py` 写入权供下一 owner 接手。本片不关闭 INDEX_HISTORICAL_MINUTES、股票分钟 owner 接线、A07、C1 或 C3。未推送、部署、调用真实 provider 或访问用户数据库。

## SCBV-07 独立代码评审 P2 与修复

主协调转达独立 Sol 代码评审结果：评审者最初 **114 passed** 的运行未覆盖最终 authority 读取内部撤销。评审者复现了在最后一次 `_index_certification_current()` 调用中撤销 admission 后仍调用一次 SDK。`_realtime_index_probe_current()` 已在该读取前检查 generation/admission；响应验证随后失败，但不能阻止 SDK 调用。

新增八项矩阵仅在真实 wrapper 准备结束后、owner 最终认证读取内部注入撤销。修复前得到 **2 failed, 6 passed, 41 deselected**：实时指数的 generation 和 admission 均失败，DAILY_BARS、DAILY_LIMITS、INDEX_DAILY 的两项对照均通过。每项失败都观察到一次 SDK 调用，而非零调用。

生产修复仅将实时指数原有认证检查移到原有 generation/admission 检查之前，不新增谓词，历史指数代码仍在约定范围外。针对性 GREEN：**8 passed, 41 deselected**。拒绝后保留持久化预约，不新增供应商 backoff/cooldown。其他纳入 owner 原本已在认证后检查这两个 fence，未修改的对照继续通过。股票分钟 owner 接线仍属于独立片。

修复及针对性 GREEN 后已声明源码/测试稳定。之后主协调转达独立复审结果：I1 为 **146 passed, 1 warning in 45.92s**；另行内联复跑原 P2 场景得到 **SDK calls=0 / DEFERRED**。评审者确认无剩余 P1/P2、Ruff/diff 通过、该修复版本复跑期间源码/测试 hash 稳定，并接受双语文档对 P2 前后证据的区分。P2 已独立确认修复，主协调授权本片 10 文件的本地提交。本次仅文档核对，不修改源码或测试。
