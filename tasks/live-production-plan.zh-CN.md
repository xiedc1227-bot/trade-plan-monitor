# 实施计划：实时监控生产链路

> 中文审阅版。英文权威版为 `live-production-plan.md`；两份文档必须保持语义一致。

## 总览

以契约优先的垂直切片实施已接受的 P0 `LPC` 工作包，同时保留 9 个既有 WEBF13 修改与全部历史 identity。用户已经批准实施；每个行为仍遵循 RED → GREEN → 聚焦验证。

## 架构决定

- ADR 0004 负责类型化正常未就绪、成功形状兼容、增量迁移 0009、完整持久结果、原子状态/event/outbox，以及 commit 后发布。
- 股票与板块指数 provider 认证彼此独立。允许测试 Tushare 不代表允许暴露密钥或猜测市场窗口。
- 浏览器只消费生成契约，绝不通过探测 Health 重新解释 Dashboard 错误。

## 阶段与检查点

1. P0 契约与登记：`LPC001`～`LPC002`。
2. 持久状态：`LPC003`～`LPC004`。
3. 股票 runtime：`LPC005`～`LPC006`。
4. 独立板块指数 runtime/认证：`LPC007`～`LPC008`。
5. Web 契约与浏览器：`LPC009`～`LPC010`。
6. 集成生产与证据：`LPC011`～`LPC012`。

每阶段结束后运行聚焦测试、修改表面的 Ruff/类型检查、`git diff --check` 和候选密钥扫描。最终检查点运行全部离线 pytest、Ruff、迁移/重启/事务测试、OpenAPI/类型生成、Vitest、`vue-tsc`、Google Chrome Playwright、Vite build 和双语报告一致性。

## 并行工作

- `LPC002` 后，`live-state-store` 与 provider/harness 测试可以并行。
- 存储/runtime 实现期间，可针对冻结联合契约并行编写 OpenAPI/Vue RED 测试。
- 迁移顺序、runtime 整合、生成制品、生产进程验收和全部真实 Tushare 调用必须串行。

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 旧 ledger 看似可还原 | 伪造判断 | 要求完整 `evaluation_result`；否则返回类型化 `AWAITING_FIRST_EVALUATION` |
| 事务部分提交 | head/event/alert 分歧 | 单 Unit of Work，加回滚和重启测试 |
| 重复获取报价 | 浪费限额且证据不一致 | 每个 deadline 一个批次对象，注入全部判断 |
| 指数故障阻断全部计划 | 违反 ADR 0003 | 显式路径依赖测试和逐指数失败值 |
| 浏览器把传输当领域状态 | 误导可用性 | 类型化 200 联合；删除 Health fallback |
| Token 进入制品 | 凭据泄漏 | 一次性密钥注入、固定错误码、内容扫描 |
| 不合适窗口执行认证 | 错误时间戳声明 | 记录 `NOT_RUN_MARKET_WINDOW`；延后标签决定 |
| 健康启动后 runner 退出 | 健康状态错误保持 live 或任务泄漏 | 使用全新 runtime 的 supervisor，按 `1`/`2`/`4` 秒最多重启三次，退避/耗尽期间保持降级，清理失败属于终止性错误 |

## 开放问题

离线实施没有阻断问题。LPC006 的可执行股票组合继续依赖 LPC005 记录带已验证 `SourceTimeLabel` 的新鲜 `READY` profile；新鲜指数 readiness 仍由独立证据闸门控制。
