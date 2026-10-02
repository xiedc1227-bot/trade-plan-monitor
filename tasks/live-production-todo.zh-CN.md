# 任务清单：live-production-chain

> 中文审阅任务清单。英文权威版为 `live-production-todo.md`；ID、命令、文件和验收标准必须一致。

> 状态：LPC001–LPC012已完成。认证观察、有效期及测试数量是当时证据；当前运行恢复替代旧年龄门禁，详见[文档索引](../docs/README.zh-CN.md)。

## P0 契约

- [x] `LPC001`——登记新能力地图和不重叠的 `LPC` 命名空间。
  - 验收：不复用任何历史任务 ID；实时板块指数认证使用新 identity `LPC007`。
  - 验证：双语文件结构与任务 ID 扫描。
- [x] `LPC002`——接受 ADR 0004 并冻结 `SPEC-live-production-chain`。
  - 验收：明确类型化 200 unavailable 联合、真正 503 故障、迁移/事务/provider/Web 边界。
  - 验证：双语章节、枚举、路径、命令和阈值一致性。

## 持久状态

- [x] `LPC003`——增加迁移 0009 与精确保留测试。
  - 验收：六张增量表/head 存在；旧 identity、行和 hash 逐字节稳定；不安全 downgrade 在 DDL 前拒绝。
  - 验证：聚焦迁移与 repository pytest。
- [x] `LPC004`——原子持久化完整判断投影，并在重启后读取。
  - 验收：claim/result/head/risk/episode/event/outbox/pending-close 共享一个事务；回滚和 commit 后发布测试通过；仅 hash 历史保持 unavailable。
  - 验证：聚焦事务、持久读取与重启 pytest。

## 股票 Runtime

- [x] `LPC005`——加固默认零网络与一次性真实股票 harness。
  - 验收：直接读取 `config/app.yaml` Token、串行单并发、启动间隔 `>=1.25 s`、15 秒超时、零重试且 429 后停止；只有带已验证 `SourceTimeLabel` 的新鲜闸门证据才能把股票 profile 标为 `READY`，否则明确保持阻断或 `NOT_RUN_MARKET_WINDOW`。
  - 验证：离线契约测试与候选密钥扫描。
  - 证据：2026-09-08 09:52:53 的 `SourceTimeLabel=START` 结论属于开市过早的不足推断，现已被取代。2026-09-09 的两次 13:10 尝试及有界重试在旧标签逻辑下如实记录 `current_day_minutes=ERROR/UNVERIFIED`；每份脱敏诊断均有 139 行，范围 `09:30` 至 `13:18`，包含 `11:30` 且不含 `13:00`。严格修复后的 `14:48:40.405317+08` 运行认证五项能力均为 `READY`，`SourceTimeLabel=END`，有效至 `2026-09-16 14:48:40.405317+08`。它证明独立的 `09:30` 快照之后为 end-labeled 分钟。仅因请求固定为 `1MIN` 才兼容 QuickSync 不回显固定 `freq`；若明确返回非 `1MIN` 值，仍会安全拒绝。
- [x] `LPC006`——组合已认证股票 provider 与单批次可恢复 runtime。
  - 验收：依赖 `READY` 的 LPC005 股票 profile；reference refresh/recovery/supervisor 工作；每个 deadline 对最多十只股票执行一次 `rt_min` 批次；判断不重新获取，事务内无网络。启动时可以校验统一且被忽略的 `config/app.yaml`，但在该依赖通过前，生产保持 `DEGRADED`，不构造带凭证的 provider client、不发出 provider 请求，也不构造可执行 deadline coordinator。
  - 验证：provider、request-controller、deadline、recovery、restart 和 ten-symbol 测试。
  - 证据：安装式生产运行于 2026-09-08 16:54:10.565727 Asia/Shanghai 启动，消费五项能力均为 `READY` 的新鲜股票 profile，在 17:00:00.011473 自然启动计划中的 17:00 deadline，提交两项官方收盘判断，以零结果和零 provider 请求重放已提交 identity，并在重启后保持 `RUNNING` 且 Dashboard sequence `11` 不变。该生产证明与组件测试及真实 profile 生成相互独立。

## 板块指数 Runtime

- [x] `LPC007`——为当前交易范围建立独立实时板块指数认证证据。
  - 验收：独立授权/profile/`SourceTimeLabel`；市场窗口不合适时记录 `NOT_RUN_MARKET_WINDOW`；不复用股票证据。当前范围包含 `000001.SH`、`399001.SZ`、`399006.SZ` 与 `000688.SH`。`899050.BJ` 保留为已知 identity，但在北交所股票进入交易范围前标为 `DEFERRED`，认证不会为其发出 provider 请求。
  - 验证：离线 harness 测试；只有满足闸门时才运行串行 live selector。
  - 证据：2026-09-09 在 `13:10:41.07832+08` 观测的续期认证当前范围内四个指数均为 `READY`，`SourceTimeLabel=END`，有效至 `2026-09-16 13:10:41.07832+08`。`899050.BJ` 继续为 `DEFERRED`，不会请求 `idx_mins`、`rt_idx_min_daily` 或 `index_daily`。指数与股票认证均使用 `config/app.yaml`；已配置的 `connect_ip` 成功，无需临时逐次修改 proxy。
- [x] `LPC008`——组合独立板块指数 provider 与隔离的条件故障。
  - 验收：在每个 deadline 的不可变到期计划批次内，每个必需指数 endpoint 至多调用一次，且所有依赖计划共用同一 `snapshot_hash`；已提交 evaluation identity 的重放产生零 provider 请求。15:00 盘中判断与 `OFFICIAL_CLOSE` 属于不同判断 kind，即使二者切点均为 15:00，也可分别执行各自 revision-aware 请求。一个指数故障只影响依赖条件路径。
  - 验证：聚焦 market-index runtime 与 decision 测试。
  - 证据：安装式生产运行消费独立指数 profile，在每个到期计划批次内共享 `LIVE` 上证/深证快照，提交两项 `OFFICIAL_CLOSE` 判断，并证明已提交 identity 重放产生零 provider 请求。其 15:00 盘中/`OFFICIAL_CLOSE` 两阶段演练按 revision-aware 契约，在每个不同判断 kind 内分别对每个必需指数 endpoint 调用一次。若请求已延期的北证50，profile 会在进入请求控制器前失败。

## Web 可用性

- [x] `LPC009`——在 FastAPI/OpenAPI/生成 TypeScript 中实现类型化可用性。
  - 验收：成功形状保持兼容；正常 unavailable 响应为 200；真正存储/组合故障为 503。
  - 验证：Web API、OpenAPI 快照与生成检查。
- [x] `LPC010`——替换 WEBF13 Health fallback 并惰性加载 ECharts。
  - 验收：`SNAPSHOT`/`UNAVAILABLE`/`STALE`/`DISCONNECTED` 明确区分；unavailable 不开 Socket；非图表路由不获取 chart chunk。
  - 验证：聚焦 Vitest、类型检查，以及 console error/warning 与 `requestfailed` 均为零的 Chrome Playwright。

## 集成与证据

- [x] `LPC011`——运行安装式生产重启与浏览器验收。
  - 验收：持久投影跨重启；空库/无计划/首次结果保持诚实；runtime supervisor 状态保持可见。
  - 验证：生产组合 pytest 与安装式回环 Chrome 旅程。
- [x] `LPC012`——完成双语验收报告与全部门禁。
  - 验收：记录精确命令/结果/文件/风险；全部必需离线门禁和密钥扫描通过；不夸大真实结果。
  - 验证：[项目README](../README.zh-CN.md) 中命令、双语一致性审计、`git diff --check` 和 `git status --short`。
  - 证据：性能根因为 `EvaluationContext.current_bucket_minutes` 每次判断扫描全日分钟。首只股票的 profiling 记录 `833,504,828` 次调用、属性累计 `35.57s` 和 `7,493,472` 次 `five_minute_bucket_end` 调用。修复从已校验的有序完整五分钟桶直接读取末五条；回归为旧 `105` 次、新 `<=2`。精确容量节点以 `1 passed, 1 warning in 1443.66s` 通过，证明十只股票每只 `<=120s` 及资源上限。之后出现的 100,000 条 fill 导出尾部失败在不修改 `5 MiB/s` 下限的前提下修复：`(run_id, fill_id)` 校验索引消除 SQLite 临时排序，同一读取快照不再重复已经证明的时间戳/domain 检查。保持原门槛的节点随后测得最小吞吐 `7.485 MiB/s`、数据库加 WAL `299.645 MiB`、导出内存增量 `36,864` bytes。最终完整无排除仓库门禁以 `2326 passed, 1 skipped, 1 warning in 2761.04s` 通过；双语证据、live-chain 聚焦门禁、浏览器 E2E、静态检查和密钥扫描也全部为绿色。
