# 任务清单：live-production-chain

> 中文审阅任务清单。英文权威版为 `live-production-todo.md`；ID、命令、文件和验收标准必须一致。

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

- [ ] `LPC005`——加固默认零网络与一次性真实股票 harness。
  - 验收：串行单并发、启动间隔 `>=1.25 s`、15 秒超时、零重试、429 后停止、无密钥制品；只有带已验证 `SourceTimeLabel` 的新鲜闸门证据才能把股票 profile 标为 `READY`，否则明确保持阻断或 `NOT_RUN_MARKET_WINDOW`。
  - 验证：离线契约测试与候选密钥扫描。
  - 阻断证据：离线 harness 已安全失败关闭，但仍缺少所需的仅子进程 secret-store 注入适配器和新鲜开市窗口 `SourceTimeLabel` 证据；未读取 Token，也未尝试真实调用。
- [ ] `LPC006`——组合已认证股票 provider 与单批次可恢复 runtime。
  - 验收：依赖 `READY` 的 LPC005 股票 profile；reference refresh/recovery/supervisor 工作；每个 deadline 对最多十只股票执行一次 `rt_min` 批次；判断不重新获取，事务内无网络。在该依赖通过前，生产保持 `DEGRADED`，不读取 Token、不调用 provider，也不构造可执行 deadline coordinator。
  - 验证：provider、request-controller、deadline、recovery、restart 和 ten-symbol 测试。
  - 阻断证据：runtime 路径已实现并通过离线测试，但生产会有意只暴露不可执行的 `DEGRADED` composition，直至 `LPC005` 变为 `READY`。

## 板块指数 Runtime

- [ ] `LPC007`——建立独立实时板块指数认证证据。
  - 验收：独立授权/profile/`SourceTimeLabel`；市场窗口不合适时记录 `NOT_RUN_MARKET_WINDOW`；不复用股票证据。
  - 验证：离线 harness 测试；只有满足闸门时才运行串行 live selector。
  - 阻断证据：未执行单独授权的开市窗口板块指数观测。
- [ ] `LPC008`——组合独立板块指数 provider 与隔离的条件故障。
  - 验收：每个必需指数每个截止最多获取一次；一个故障只影响依赖条件路径。
  - 验证：聚焦 market-index runtime 与 decision 测试。
  - 阻断证据：离线隔离已实现，但可执行生产 composition 仍受 `LPC007` 闸门阻断。

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
- [ ] `LPC012`——完成双语验收报告与全部门禁。
  - 验收：记录精确命令/结果/文件/风险；全部必需离线门禁和密钥扫描通过；不夸大真实结果。
  - 验证：`tasks/live-production-plan.md` 中命令、双语一致性审计、`git diff --check` 和 `git status --short`。
  - 阻断证据：全部 live-chain 聚焦门禁与密钥扫描均通过，但仓库级全量离线 pytest 仍在既有 252 日回测性能预算上为红；真实股票与板块指数闸门也继续有意保持未完成。
