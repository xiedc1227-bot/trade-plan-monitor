# 验证：market-linkage-p1

## MLV1-01 — 范围与授权

用户在 2026-10-24 批准 MLP1-D01–MLP1-D06 并指示分阶段实施。基线 `dbeff32`。本报告只记录已经执行的检查，不记录设想结果。[规格](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md) · [任务](../../tasks/market-linkage-p1.zh-CN.md) · [规范英文版](2026-10-24-market-linkage-p1.md)。

## MLV1-02 — 基线与边界清单

MLP1-T01：已核对实际领域／草稿／编解码／哈希／审核／运行／状态／API／回放边界，记录在双语[契约清单](../specifications/monitoring/CONTRACT-market-linkage-p1.zh-CN.md)。未访问用户数据库或外部数据商。

在 `trade-plan-monitor/` 已执行 V01：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

结果：**91 passed in 1.20s**。Python 启动器出现既有安装位置诊断，但测试正常完成，退出码为 0。此基线不代表 P1 功能验收。其余任务结果仅在实际执行后追加。

## MLV1-03 — 严格 Schema 7 契约（MLP1-T02）

RED：初始契约测试因缺少 Schema 7 模型／分发产生 9 失败／1 通过；新增不完整草稿及共用构造器检查在实现前另有两项预期失败。GREEN：52 项例外／联动／统一领域测试在 1.58s 通过；176 项旧计划／日线／有界编解码测试在 0.45s 通过。由于明确支持 7，未知版本样本改为 8，保留拒绝断言。针对性 Ruff 和空白检查通过。

首次扩大范围误用了不存在的 `test_daily_plan_domain.py`，没有运行测试，随后改为实际文件。默认临时目录初始化失败；明确使用工作区临时目录解决该问题。后续堆栈将剩余等待定位到 Windows `asyncio` 创建 socketpair，允许本机通信后离线测试通过。没有修改应用逻辑绕过环境限制。

已通过命令（临时路径按运行区分）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_unified_plan_domain.py -q --basetemp .test-tmp/p1-t02-accepted
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_bounded_validation_codec.py -q --basetemp .test-tmp/p1-t02-legacy-fixed
```

本项仅验收严格领域／草稿／编解码／哈希切片。来源审核、启用、运行、批准及执行集成仍为未勾选任务。

## MLV1-04 — 纯资格与数量（MLP1-T03 / MLP1-C01）

实现前加入独立路径／数量样本，缺少模块时按预期收集失败。数量切片通过 24 项测试。另两项测试发现 Q0 内不存在合法数量时仍产生 BROKEN 候选；补充数量可行性准入后，V01–V03 联合套件 **144 项在 1.33s 通过**，针对性 Ruff 通过。覆盖 P0 状态／强势／确认的相等边界和新例外边界。

已验证精确最低量替代、明显破坏数量不自动填写、合法数量可在半数 Q0 两侧、额度／未知／非法输入阻断，以及普通路径独立性。即使符合资格，纯策略始终返回零授权数量。MLP1-Q12 的持久过时／他次批准场景仍由授权集成负责，不将纯函数测试当作持久化验收。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

MLP1-C01 仅验收契约与算术。后续权限、运行、UI 和回放任务仍未完成。

## MLV1-05 — 来源绑定提取（MLP1-T04）

Schema 7 提取使用 `plan-extract-v10`，要求完整例外定义及逐路径来源许可，不能生成批准。字面绑定和解释绑定都检查否定许可。中英文定义保持等价边界。已有 v8/v9 记录继续可读。

RED：扩展格式暴露了实际的 50,000 字符输入上限回归，两项提示词预算测试失败。共享相同格式定义修复了回归，没有提高上限或删除校验约束。最终提取、审核、安全及提示词预算测试 **73 项通过，耗时 2.55s**；默认版本回归 **63 项通过，耗时 0.97s**。完整 `ruff check src tests` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/integration/test_market_exception_review.py tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py tests/unit/test_preparation_prompt_budget.py -q --basetemp .test-tmp/p1-t04-verified
```

MLP1-T04 验收通过。更新／准备、持久化授权及后续检查点仍待完成。

## MLV1-06 — 保留许可的更新（MLP1-T05）

RED：四项新测试暴露 Schema 7 精简准备格式和前序快照序列化缺失，一项授权注入测试已通过。精简准备、增量提示词及前序上下文增加明确的 Schema 7 类型分派。许可修改会改变审核标识，无关原文不能授权许可变化；计划复制拒绝单次授权。缺失许可仍不能生成可执行计划。一项测试最初预期抛出异常，而既有 `to_executable()` 约定为返回 None；已修正断言以验证该约定。

GREEN：**95 项测试通过，耗时 2.20s**，覆盖例外／联动审核、例外更新、增量物化、保留证据、提示词预算及既有准备更新。完整 Ruff 通过。MLP1-T05 验收通过；MLP1-C02 仍须完成持久化存储验收。

## MLV1-07 — 持久化状态（MLP1-T06 / MLP1-C02）

RED：新模型尚未实现时，存储测试收集失败。增加封闭候选／事件模型、分域哈希、终态转换校验、不可修改的事件写入及带修订号校验的投影。SQLite 现有种类约束需要增量迁移 `0026_market_exceptions`；迁移保持载荷字节、增加命令唯一性，并在存在例外证据时拒绝降级。测试仅使用临时数据库。

GREEN：来源／更新／新旧存储共 33 项通过，耗时 4.41s；增加持久化命令索引后，9 项存储回归通过，耗时 3.72s。最终 5 项新存储测试也通过。已验证提交前回滚、重新打开、终态复用、未知版本、哈希修改、事件不可变、旧字节保持及跨候选命令唯一性。完整 Ruff 通过。MLP1-C02 仅验收来源契约与存储，不声称生产批准或执行能力完成。

## MLV1-08 — 精确预览与明确决定（MLP1-T07）

RED：授权服务尚未实现时，测试收集失败。增加严格预览／决定命令、不可变预览、服务端上下文修订绑定、精确数量校验、命令重放及明确拒绝。该服务不写入库存。两条路径只冻结合法的已展示数量；明显破坏路径输入缺失／不合法时不会填默认值。

GREEN：**21 项授权／存储测试通过，耗时 3.49s**，完整 Ruff 通过。覆盖偏弱精确最低量、低于／高于半数 Q0 的合法明显破坏数量、空／零／不符单位／超过上限、库存／评估／证据变化、未知容量、风险阻断、相同重试及拒绝。生产权限采集和信号创建仍归 MLP1-T09；当前尚未开放 HTTP 接口。

## MLV1-09 — 终态与并发争用（MLP1-T08）

实现明确撤销、服务端过期／失效及不可变重试回执。首次双连接并发测试暴露 SQLite 从读取快照升级写入时的争用。服务现先取得写入锁再读取命令权限，将繁忙争用映射为明确冲突，其他数据库故障不会被当作成功。终态命令构造先于首次新增生命周期测试；并发修复遵循先失败后修复。

GREEN：**31 项测试通过，耗时 5.94s**，包括独立连接的批准对批准／拒绝、全新进程重新打开、撤销／重试、拒绝／过期／失效保持、禁止回填时间及提前过期。Ruff 通过。执行竞争仍归 MLP1-T10。生产更正及独立重置连续性将在 MLP1-T09 完成。

## MLV1-10 — 生产运行权限（MLP1-T09 / MLP1-C03）

增加 v2 决策／数量证据，保持 v1 校验器；共享独立机会准入，持久化候选，并在调用方同一事务内由明确批准创建信号。Schema 7 接入审核激活及生产指数适配器。运行缓存标识包含候选修订。待审核提醒没有数量；发送／读取／完成检查校验当前候选状态和所用证据。

GREEN：决策／授权／并发／新旧运行联合 45 项通过，耗时 13.23s。最终 10 项真实运行测试通过，耗时 6.94s；Ruff 通过。覆盖两条路径、批准不成交、同一时刻刷新、无变化重取、更正失效、复制／拒绝连续性、撤销后读取／发送阻断及完成证明失效。夹具修正使用实际指数请求字段与提醒仓储；未变化的提供方快照保持原接收时间。

扩大 API 运行发现 3 项预期契约投影失败：旧断言仅允许两个草稿分支和版本 [5,6]。明确留待 MLP1-T11/T12 验证准确增量变化及旧投影，不计为通过。MLP1-C03 仅验收逐次运行权限。模拟消费、公开命令、界面及回放尚未完成。
