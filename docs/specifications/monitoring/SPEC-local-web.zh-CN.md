# 规格：local-web

## 当前范围

安装式 `trade-plan-monitor web` 命令绑定 `127.0.0.1`，提供匹配的监控协议 `2` 资源、REST 和 WebSocket。[单一交易计划流程](SPEC-unified-plan.zh-CN.md) 负责 Schema 5 提取、审核、启用和隔离整单模拟。API 读取不可变启动 AI 配置；没有密钥/配置写入或连接测试接口、真实成交登记接口、基本面/事件风险写入接口或独立日线计划工作台。

## 路由与权威

`/`、`/stocks/:symbol`、`/plans`、`/plans/:id`、`/alerts` 和 `/system` 提供监控、原文审核、提醒及诊断。`/backtests`、`/backtests/new`、`/backtests/data` 和 `/backtests/:runId` 提供独立历史研究。Vue 展示生成的后端契约，绝不计算资格，也不根据提醒改变库存。冻结计划版本仍是可读的研究/审计输入，不能作为当前计划启用。

正常缺少投影返回类型化 HTTP `200` unavailable 响应；真实存储/组合故障保留脱敏错误。运行进展、数据资格与传输存活分离。监控版本保护、逐计划只读状态、完成证明新鲜度、不匹配/刷新行为及严格 v2 心跳解析由 [runtime-status](SPEC-runtime-status.zh-CN.md) 管理。当前保护清单列于该文档，不能恢复已删除的旧命令路径。

状态变更服务保留幂等、乐观修订及准确原文/审核/启用绑定。API 配置只读，从 `config/app.yaml` 加载一次；密钥绝不进入响应、前端状态、导出、日志或错误。明确模拟交易在当前个股事务内重新校验数量、T+1、CORE、容量、报价及修订。请求处理器不执行研究工作槽/供应商工作。

## 生成契约与构建

`openapi.json` 与 `web/src/api/generated.ts` 从 `create_app` 兼容组装生成。`openapi.runtime-status.json` 与 `web/src/api/generated-runtime-status.ts` 描述安装式 v2 组装。不得手抄或手改生成 Schema；当前批准指纹位于 `SPEC-unified-plan.md`，机器契约是路径清单的权威来源。

```powershell
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

正常构建复制匹配资源及 `monitor-contract.json` 到 Python 包。`build:runtime-status-preview` 保持隔离；`build:legacy-test` 用于显式兼容夹具。清单/协议不匹配时组装失败。后端/前端须匹配发布，详见[操作指南](../../operations/live-certification.zh-CN.md)。

## 应用与错误边界

- `create_app(...)` 只构造 FastAPI 适配器。导入和构造不会加载配置、打开 SQLite、调用供应商、创建任务或绑定网络套接字；不存在通过模块级应用实例启动的隐藏工作。
- 明确注入的运行时工厂只在 FastAPI lifespan 启动时调用。lifespan 恰好持有一个运行时实例，等待 `start()`，接受有效的 `DEGRADED` 只读启动，通过依赖注入提供当前活跃实例，并在清除实例前始终等待 `stop()`。缺少工厂时启动会封闭失败。
- 每个请求都会生成新的 32 字符小写十六进制 request ID。忽略调用方提供的 ID；经过校验的同一值同时出现在 `X-Request-ID` 响应头和错误正文的 `requestId` 中。
- `ApiError`、请求校验错误、HTTP 错误和未预期异常都映射到唯一 `ErrorResponse` envelope。对外顶层消息从固定错误码中选择。校验详情最多 100 项；每个 location 最多包含 16 个有界部分，只暴露脱敏 code 以及 `Field required` 或 `Invalid value`。拒绝的输入、Pydantic context、异常 cause、密钥值和供应商/存储原始响应体绝不序列化。
- 共享错误 Schema 严格、冻结、兼容 camelCase，并对 `model_copy(update=...)` 重新校验。

## Origin、传输限制与静态资源

- `create_app(bind_host="127.0.0.1", bind_port=8765, static_directory=...)` 在不绑定套接字的情况下校验监听 identity。唯一允许的主机字面量是 `127.0.0.1`，端口范围限制为 `1..65535`；安装式 `web` CLI 会拒绝通配、局域网、别名和越界值，并给出明确的禁止公开暴露警告。安装命令使用生产组合。
- HTTP 或 WebSocket 存在 `Origin` 请求头时，它必须是唯一且精确配置的 `http://127.0.0.1:<port>` Origin；重复、非法、外部、HTTPS、别名或错误端口值均封闭失败。HTTP 以固定 `FORBIDDEN` envelope 和 403 状态拒绝；WebSocket 则在接受前以关闭码 1008 拒绝。缺少 `Origin` 时仍允许非浏览器回环客户端；生产环境不存在 CORS，并移除下游任何 `Access-Control-*` 响应头。
- 每个 HTTP 响应都带固定 CSP、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`，以及关闭摄像头/地理位置/麦克风/支付/USB 的 `Permissions-Policy`。共享错误构造器也会为用户中间件之外生成的未预期 500 响应增加这些响应头。被拒绝的 Origin、正文和异常详情绝不回显。
- 原始 HTTP 请求体按 `Content-Length` 和实际流式分块同时限制为精确 4 MiB（`4194304` 字节）；第一个越界字节返回固定的 413 `PAYLOAD_TOO_LARGE` envelope。该传输预算可容纳既有 200,000 字符 AI 来源文本在最坏 JSON 转义下的大小。既有计划 JSON/YAML 导入和字段级文本上限仍更严格且为权威限制；安全 YAML 加载保持不变。
- 静态服务只接受一个明确注入且已存在的目录，其解析后的本地 `index.html` 必须是普通文件。提供既有文件时不会跟随逃逸 symlink。不存在且无扩展名的 GET/HEAD 路径，以及明确接受 `text/html` 的不存在导航路径会回退到 `index.html`，包括 `/stocks/003043.SZ` 等股票路由；即使构建目录包含 `404.html`，缺失的类资源路径仍使用固定 404 envelope。`/api/v1` 和 `/ws/v1` 在静态路由匹配阶段被排除，因此静态内容不能覆盖 API/WebSocket 路径或改变其方法语义。安装资源由 `create_production_app` 组装；静态服务本身不发现构建。

## WebSocket 契约

端点：`/ws/v1/monitor?after=<sequence>`。

浏览器先加载包含序号的权威 REST 监控总览快照，再应用增量事件。已提交事件类型包括：

- `symbol.snapshot.updated`
- `symbol.health.updated`
- `alert.created`
- `alert.acknowledged`
- `plan.extraction.updated`
- `plan.activated`
- `plan.deactivated`
- `position.updated`
- `ai.provider.updated`
- `system.health.updated`
- `market.index.updated`

每个已提交事件使用一个严格、带版本、camelCase 的 envelope：

```json
{
  "type": "symbol.health.updated",
  "sequence": 42,
  "eventId": "00000000-0000-0000-0000-000000000001",
  "aggregateId": "003043.SZ",
  "payload": {
    "entityId": "003043.SZ",
    "symbol": "003043.SZ",
    "revision": 4,
    "status": "STALE"
  },
  "occurredAt": "2026-08-24T10:30:00+08:00",
  "schemaVersion": 1
}
```

载荷是有界失效提示，包含 `entityId`，以及仅在适用时出现的 `symbol`、位于 `0..2^63-1` 的 `revision`、大写 `status` 或小写 SHA-256 `resultHash`；客户端重新读取权威 REST 状态，不能把事件当成状态替代。负责组装总览快照的注入式 `MonitorReadService` 必须在同一个工作单元内读取状态和 `monitor_sequence`，因此返回的 `sequence` 是该快照的准确高水位。不得用独立采样的序号代替该事务快照。

Schema 版本 1 封闭每种事件的非空载荷字段集合及 identity 规则：快照使用 `entityId`、`symbol` 和 `resultHash`；股票健康使用 `entityId`、`symbol`、`revision` 和 `status`；两者都要求 `aggregateId == entityId == symbol`。提醒创建/确认使用 `entityId`、`symbol` 和 `revision`；两者都要求规范 UUID `aggregateId == entityId`，创建还要求 `eventId == aggregateId` 且 revision 为 `0`，确认要求 revision 为 `1`。提取使用 `entityId`、`revision` 和 `status`；激活使用计划版本 `entityId`、`symbol` 和正数 `revision`，且 `aggregateId == symbol`；停用使用 `entityId`、`symbol` 和正数 `revision`，且三个 identity 相等。持仓使用 `entityId`、`symbol` 和 `OPEN`/`CLOSED` `status`；AI 供应商使用 `entityId` 和 `revision`；系统健康使用 `entityId` 和 `status`；板块指数失效通知精确使用 `entityId`、正数 `revision` 和 `status`。这些实体自有类型要求 `aggregateId == entityId`。持久化前会拒绝缺少必需字段或包含任何不适用非空字段的事件。

`monitor_event` 是唯一追加式回放来源，`monitor_sequence` 是唯一全局高水位域。状态变更和对应事件追加共享一个事务。事件 UUID 是幂等 identity：相同 ID 及语义返回原序号，语义不同则封闭失败。删除保留期内的行绝不重置序号。默认回放窗口为 7 天，每页最多 1,000 个事件；服务端在发送任何分页前校验完整 `(after, high_water]` 范围，因此页外缺口不能先泄漏部分旧页。

`heartbeat` 和 `snapshot.required` 是传输控制帧，不是已提交业务事件，也不占用持久序号。心跳间隔为 20 秒，并携带与当前 lifecycle identity 配对的精确可空 `runtimeGeneration`。缺失、重复、非规范、负数或大于 JavaScript 安全整数上限（`2^53-1`）的 `after` 游标以关闭码 `1008` 拒绝。未来游标、保留范围内的序号缺口、回放窗口过期或无法安全表示的持久高水位都不会发送不安全数字；不可信的 `monitor_sequence` 必须以 `1011` 安全失败。内存发布只在精确校验已提交事件后用于唤醒；重连和进程重启从 SQLite 回放。客户端使用带上限的指数退避和抖动重连。断连或陈旧数据必须明确标注，绝不能展示为实时数据。

## 浏览器生命周期与验收

在打开绑定序号的连接前，加载并原子应用权威 REST 总览快照。监控协议 `2` 负责准确心跳/状态形状：心跳仅证明传输，不能证明协调器进展或当前判断。错误帧、序号缺口、generation 替换及 `snapshot.required` 从 REST 重新开始。卸载/恢复取消自有读取、连接和定时器；陈旧响应不能覆盖新 generation。缓存/断线数据保持标注及只读。版本不匹配进入终止性 `RELOAD_REQUIRED` 并阻止受保护命令。

使用 Composition API、类型化生成 DTO、无障碍语义控件、键盘/焦点反馈及颜色旁的文字标签。真实呈现加载、不可用、部分、缓存及错误状态。当前外壳/视觉方向位于 `SPEC-interface-design.md`；回测边界位于 `../backtesting/` 下的 `SPEC-backtest-api.md` 和 `SPEC-backtest-web.md`。

验证须使用临时数据库和确定性供应商，覆盖正式 API、生产组合、当前提取/审核/启用、隔离模拟、已读零库存变更、重启及新旧协议不匹配。[最新本地验收](../../verification/2026-10-03-unified-plan.zh-CN.md) 记录已执行覆盖与限制。真实供应商验收、用户数据库迁移及部署是独立操作。
