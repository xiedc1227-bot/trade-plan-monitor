# C1 SDK 调用边界契约

## SCB-01 状态与证据

- 状态：**REVIEWED / approved for local commit**。最初仅交付设计时的状态为 **DESIGN REVIEWED / implementation pending**。
- 已检查的源码基线：`453cc0c7c9f15d977776c98671f0d419f37e9545`。
- 本文记录 Astra 的只读设计及两轮独立 Sol 设计评审。设计评审本身未授权实现或测试修改；之后主协调解除源码冻结并另行授权本有界实现。独立代码复审及双语文档核对通过后，主协调授权仅本片精确 10 个文件的本地提交。推送、部署、scheduler 接入及 A07 生产修复仍不在授权范围内。
- 主协调的改动前完整离线测试结果为 18 failed、4778 passed、1 skipped、4 deselected。Position/R13/R14/R17 失败由其他任务处理，不宣称由本片修复。
- 主协调转达了已确认的离线内联复现：使用真实 `_CertifiedTushareClient` 与内层 fake SDK，无文件写入、外部服务或数据库访问。设计评审时尚无新增 RED regression；之后的 PB01 RED 及本地验证见[实现报告](2026-09-27-c1-sdk-call-boundary-verification.zh-CN.md)。
- 此前 248/281/291 项通过不能证明此次新发现的 SDK 边界。独立代码复审已接受修复后的实现，无剩余 P1/P2；其独立 146 项证据记于实现报告。

## SCB-02 已确认缺口与内联复现

当前权限路径可能按以下顺序执行：

```text
provider physical_start -> old S
endpoint(...) -> _CertifiedTushareClient.request
_current() certification/configuration checks
getattr(inner_client, operation)
inner SDK callable invocation
SDK return -> R
```

wrapper 在 provider guard 之后执行可能耗时的检查及 callable 解析，因此该 guard 不能证明最终内层 SDK 的准入时刻。

已确认的内联复现冻结 `captured_at=10:00:00`、`latest_start=10:00:15`，旧 physical guard 在 `10:00:14` 放行。真实 wrapper 的认证回调将 fake clock 推进两秒，内层 fake SDK 到 `10:00:16` 才进入；产生的 proof 为 `S=10:00:14`、`R=10:00:16`、`A=1`，旧 proof 检查仍接受。PB01 必须在实现前将该复现转为失败的回归测试。

## SCB-03 范围与明确保留的缺口

| Scope/路径 | 当前发现 | 计划边界范围 |
| --- | --- | --- |
| `CURRENT_DAY_MINUTES` / `rt_min_daily` 权限证明 | S 早于 wrapper 认证及内层端点解析 | 纳入 |
| `REALTIME_MINUTES` / `rt_min` 权限证明 | 同样存在 S 过早的问题 | 纳入 |
| `DAILY_BARS` / `daily`，包括 `453cc0c` | 最终 provider guard 早于 wrapper 工作 | 纳入 |
| `DAILY_LIMITS` / `stk_limit` | 最终 provider guard 早于 wrapper 工作 | 纳入 |
| `INDEX_DAILY` / `index_daily` | 最终 guard 早于 wrapper 工作及日期参数构造 | 纳入 |
| `INDEX_REALTIME_MINUTES` / `rt_idx_min_daily` | S 过早影响最终准入及响应行时间解释 | 纳入 |
| `INDEX_HISTORICAL_MINUTES` / `idx_mins` | 有 worker 入口 guard，但没有 provider physical-start seam；其间工作仍未受最终边界校验保护 | 排除在本实现范围外，明确保留为未解决缺口。新增 seam 须另行授权并保留原窗口契约 |
| 交易日历权限、历史股票路径及普通业务调用 | 本次评审未证明这些路径的最终内层 SDK 边界 | 排除；不得宣称验收或默默扩展其保证 |

普通业务路径保留既有调用路由、参数、解析及异常行为。共享 `_daily_bars` 路径可以仅在 `_physical_start is not None` 时使用新 resolver，普通 daily/history 调用保留现有路径。未传可选 hook 的纯 parser 权限调用不能证明新的最终启动保证。

## SCB-04 最小名义 resolver 协议

新增只依赖标准库的公共模块 `market_data/sdk_call_boundary.py`，包含内部名义基类 `PermissionEndpointResolver` 及 `resolve_permission_endpoint(client, operation) -> Callable`。

1. 仅通过名义基类识别自有 wrapper。不得使用 `runtime_checkable Protocol`、虚拟注册、自定义实例检查或 `getattr`/`hasattr` 来发现可选私有协议。已安装的 Tushare `DataApi.__getattr__` 会将任意名称变为端点 callable。
2. `_CertifiedTushareClient` 显式实现 `prepare_permission_endpoint(operation)`。在当前 worker 完成 `_current()`；返回 false 时抛出既有 `RequestNotStartedError`。然后解析内层端点，返回已解包的 SDK callable，不能返回调用时仍执行认证工作的原 `request` closure。
3. 仅当嵌套 wrapper 显式实现名义协议时才继续解析。对于 raw fake client 和 installed DataApi，仅解析真实 operation 并要求结果可调用。后续加入此调用链的每个自有 wrapper 都必须遵守相同准备契约。
4. endpoint、参数及 hook 都属于本次调用的局部值。不得跨调用缓存已准备 callable、临时替换共享 callback、monkeypatch 实例，或在共享 client 上存储单次调用的准入状态。
5. 不得向真实 SDK 传递私有 hook 或协议参数。最终调用只接收既有端点的业务 kwargs。
6. 公共模块不导入 runtime 模块。保留既有 `RequestNotStartedError` 类及身份，production wrapper 可使用现有导入。不得为支持该协议移动或重定义异常，也不得引入 runtime 循环导入。

## SCB-05 最终 guard 与唯一 S

每次调用必须遵循以下顺序：

```text
validate and construct all SDK arguments
-> wrapper certification/configuration checks and inner callable resolution
-> complete any remaining time-consuming authority checks
-> sample one S
-> evaluate existing time predicates using S and frozen epoch/event/cancel facts
-> directly invoke the already resolved inner SDK callable
-> sample R after return where the proof requires it
```

最终 callback 可以在采样 S 之前完成 authority 准备。S 之后仅允许纯值校验、内存准入检查以及紧接着的直接 Python 调用；不得读取配置/认证文件、动态解析端点、查询数据库或重新采样启动时间。

既有 generation/admission fence 必须在最后一次耗时认证读取后判断，包括 wrapper 准备完成后最终 authority callback 内的读取。wrapper 准备阶段的较早检查不能满足这一顺序。此约束保留原谓词，不新增策略。

保留 `captured_at <= S <= latest_start`，其中 `latest_start = captured_at + 15s`；保留原 31.25 秒冻结市场 guard、同日及回拨检查，以及既有 generation/stop/日历 epoch/event/取消语义。worker 检查不读取数据库，也不访问 Task 对象。hook 及记录的 S 仅属于本次调用。

S 指完成本地准备后、调用已解析内层 SDK callable 前的调用点时间标记，不是 socket 发包时刻。SDK 内部参数序列化及传输工作发生在该 callable 内。本契约不承诺零操作系统调度间隙、对所有外部状态的原子观察、强制中断 SDK，或取消 Event 设置前 SDK 绝无启动。

## SCB-06 保留各模式原有时间规则

冻结证据身份及请求 scope/mode 原本要求的时间条件。在全部耗时读取完成后，使用同一 S 再次判断这些条件，不再读取文件：

- `INDEX_REALTIME_MINUTES` 保留 `S < semantics.provenance.valid_until`。
- legacy 认证保留原 `observed_at <= S <= valid_until` 规则及比较边界。
- STOCK semantic 模式保留既有兼容性要求，不得向该模式新增 legacy freshness/expiry 条件。
- 其他纳入路径保留原 scope/mode 条件；本协议不创造统一过期策略。

这可以阻止“读取开始时凭证有效、读取结束前已过期，但 S 仍满足请求最晚启动及市场窗口”的启动。等号边界必须保留既有比较运算。

## SCB-07 异常、记账与副作用

wrapper 准备和最终 guard 在 provider 的宽泛异常清洗之外执行。仅已准备 SDK callable 的实际调用沿用既有 SDK 失败分类。保留显式 `except RequestNotStartedError: raise`，使 trusted sentinel 以同一对象跨越 provider/controller 边界，不转换为权限拒绝或其他供应商失败。

认证检查返回 false 属于本地 not-started。准备/配置读取的意外异常和非 callable 解析结果不得伪造成 HTTP 403；既有 controller 仍可能将未知 worker 异常包装为 `ERROR`。

既有 controller 的普通 `RequestNotStartedError` 路径直接传播它。迟到失败分类器目前将该类型映射为 `ERROR`，但不会因此写入权限阻塞、cooldown 或 backoff。sentinel 本身不得追加供应商失败记账。如果 sentinel 到达前 controller 的墙钟超时已发生，则保留既有超时记账，不承诺可以撤销。

保留原持久化 300 秒预约及游标 callback 恰好一次的语义，包括预约后拒绝。保留既有 controller floor 延长和物理 slot 排空行为；本设计不移动 controller 的持久化边界，也不声称它与内层 SDK 进入原子发生。取消释放维护锁后，已启动物理工作通过既有 controller slot 排空。迟到成功不能再次清除权限。不授权业务写入或 scheduler 接入。

## SCB-08 必需 RED 矩阵

下列条目是设计要求的证据，后续本地测试结果另记于实现报告。使用临时数据库、fake SDK/transport、受控时钟/Event，并在指定场景使用真实 wrapper/controller，无需在线 provider 或用户数据库。

| ID | 必需失败场景与验收证据 |
| --- | --- |
| PB01 | 复现 `captured=10:00:00`、`latest_start=10:00:15`、旧 S 在 `10:00:14`，真实 wrapper 认证将进入时刻推进到 `10:00:16`。修改后最终 guard 拒绝，内层 SDK 调用数为零 |
| PB02 | 认证耗时但仍合法。S 在认证结束后采样且恰好一次，分钟 evidence/owner 检查使用同一个 S |
| PB03 | 内层动态 `getattr` 推进时间或撤销 authority。最终 guard 在解析后执行并拒绝，内层 SDK 零调用 |
| PB04 | 认证开始时有效，结束时越过既有生效时间边界，但 latest-start 仍合法。拒绝且 SDK 零调用；按各模式原比较覆盖 `observed_at` 下界及 `valid_until` 等号 |
| PB05 | STOCK semantic 兼容性不误继承 legacy freshness/expiry 拒绝 |
| PB06 | 认证/解析期间触发冻结的 31.25 秒市场窗口、epoch/event 撤销、取消、stop 或配置变化。另在 wrapper 准备完成后的最终 authority 读取内部撤销 generation/admission。拒绝且 SDK 零调用；保留已持久化预约及恰好一次的原游标推进 |
| PB07 | 同一 trusted sentinel 跨 provider/controller 原样传播，不新增供应商失败、429 或 backoff 记账。分别覆盖迟到 sentinel 与 controller 已记录超时的情形 |
| PB08 | raw fake client 及动态 DataApi 只解析真实 operation。无可选私有协议查找、私有端点调用或私有 SDK kwargs 泄漏 |
| PB09 | installed 默认及直连地址 query 路径均经离线 transport 替身运行，并到达既有 strict parser |
| PB10 | 两次并发或嵌套调用分别保留 hook、endpoint、S 状态；无 callback 替换、跨调用覆盖或准备缓存复用 |
| PB11 | 股票分钟证据覆盖 `S=latest_start`、`S>latest_start`、`R-S=15s`、`R-S>15s`。已请求取消及迟到成功不能清权限，排空不重复预约 callback |
| PB12 | DAILY_BARS、DAILY_LIMITS、INDEX_DAILY、INDEX_REALTIME_MINUTES 分别经真实认证 wrapper 覆盖合法启动、跨界及撤销场景。通过真实 controller 和临时 SQLite 检查持久化预约，断言 worker 零 SQL |
| PB13 | 普通业务路径保留调用次数、kwargs、解析及错误行为；未传可选 hook 的纯 parser 调用不计入最终边界验收 |

## SCB-09 独立设计评审与实现门槛

Astra 提案由独立 Sol 子代理进行了两轮只读评审：

1. 首轮发现一项 P2：authority 读取后采样 S 仍不足，最终 guard 还须重验该 scope/mode 既有认证时间边界。具体而言，`_realtime_index_probe_current` 在后续配置/认证读取前检查 `valid_until`。评审者未发现其他有代码依据的 P1/P2。
2. 修订增加了原有时间条件的同一 S 校验，保留比较边界，排除给 STOCK semantic 模式新增 legacy 过期规则，并扩展 PB04/PB05。第二轮确认 P2 已解决，无剩余 P1/P2。

两轮均仅检查源码/设计：评审者未修改文件，未运行测试或真实请求。这两次批准针对设计，不针对已实现行为。之后主协调解除冻结并授权实现，从 PB01 RED 开始，并对纳入路径进行有界回归。后续独立代码复审接受 P2 修复及双语文档，主协调仅授权本片 10 文件的本地提交。这不关闭 INDEX_HISTORICAL_MINUTES、股票分钟 owner 接线、A07、C1 或 C3。排除范围的缺口继续明确保留。
