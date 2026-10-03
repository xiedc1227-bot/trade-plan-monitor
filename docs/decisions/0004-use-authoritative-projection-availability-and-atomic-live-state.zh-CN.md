# ADR 0004：使用权威投影可用性与原子实时状态

> 中文审阅版。英文权威版为 `0004-use-authoritative-projection-availability-and-atomic-live-state.md`；两份文档必须保持语义一致。

- 状态：`Accepted`
- 日期：`2026-09-05`
- 项目：`live-production-chain`
- 模块：`projection-availability`、`live-state-store`、`live-market-runtime`、`live-index-runtime`、`web-availability`

## 背景

安装式 Web 应用可以保持健康，但尚不存在权威 Dashboard 或股票判断投影。临时浏览器方案把 Dashboard `503` 当作探测 Health 的信号，这会让 Vue 根据传输失败推断正常领域状态。当前仅含 hash 的 evaluation ledger 也无法在重启后还原完整判断；生产 runtime 还会在供应商工作前有意停止，因为实时股票和板块指数时间戳契约仍未验证。

## 决策

1. 正常投影缺失是以后端为权威来源的类型化 HTTP `200` 结果。`DashboardResponse` 与成功股票响应结构保持不变；对应端点使用与 `ProjectionUnavailableResponse` 的增量联合。
2. `ProjectionUnavailableResponse` 包含 `availability=UNAVAILABLE`、权威原因（`EMPTY_DATABASE`、`NO_ACTIVE_PLANS`、`NO_ACTIVE_PLAN` 或 `AWAITING_FIRST_EVALUATION`）、`observedAt` 和已提交 `sequence`。它不包含伪造统计、股票摘要、判断、K 线、指数快照或健康升级。
3. HTTP `503 SERVICE_UNAVAILABLE` 只用于真正的存储、迁移、损坏或组合故障。缺少首次投影绝不能转换为 503。
4. 迁移 `0009` 为增量迁移。它存储完整规范 `evaluation_result`、`symbol_decision_head`、`symbol_health_projection`、`pending_official_close`、`market_index_snapshot` 和 `market_index_snapshot_head` 数据，同时不改变既有 `evaluation_ledger` identity 或 hash。
5. 历史仅 hash ledger 行绝不重新计算，也不补造 payload。在新的完整结果提交前，其投影为 `AWAITING_FIRST_EVALUATION`。
6. 判断 claim、完整结果、判断 head、episode/risk intent、已提交监控事件、提醒/outbox 和待处理收盘清除共享一个短事务。供应商调用与纯判断位于事务外。内存失效事件只在 commit 后发布，且绝不是回放来源。
7. 股票实时与板块指数实时使用独立供应商契约、认证记录和 `SourceTimeLabel` 值。指数故障只影响显式条件路径依赖该指数的计划。
8. Vue 只有在收到经过校验的权威快照后才打开 WebSocket。它不发起 Health fallback 请求，并区分 `SNAPSHOT`、类型化 `UNAVAILABLE`、`STALE` 与真实 `DISCONNECTED`。

## 已考虑的替代方案

### 保留 Dashboard 503 后 Health 探测

否决，因为传输错误无法权威地区分空数据库、无活动计划、等待首次判断和损坏的投影存储。

### 返回空的成功 Dashboard

否决，因为零统计和零股票会在不存在已判断投影时伪装成业务事实。

### 根据既有 hash 重新计算旧结果

否决，因为原始输入快照不可用，任何还原都会在旧 identity 下创造新语义。

### 把网络响应和状态变更放入一个长事务

否决，因为网络延迟会长期持有数据库锁，且迟到失败会模糊供应商边界与提交边界。

## 后果

- Web 行为由单个后端响应确定，预期 503 产生的浏览器原生控制台噪音会消失。
- 成功 Dashboard payload 保持兼容，但生成客户端必须接受增量 unavailable 联合。
- 迁移与重启测试必须证明 identity/hash 保留和原子回滚。
- 在合法市场窗口通过股票和指数认证前，实时 readiness 可能继续不可用；应用必须如实报告。

## 配置与回退

根据用户在 2026-09-07 针对这款个人工具作出的修订，供应商凭证可以直接保存在被 Git 忽略的 `config/app.yaml` 中，并由所选进程读取。原 Windows 凭据存储与一次性子进程边界已移除。回退通过代码和已验证的迁移前数据库备份完成；不得重写 Schema v1 行或编造逆向数据转换。
