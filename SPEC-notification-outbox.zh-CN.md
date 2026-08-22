# 规格：notification-outbox（提醒发件箱）

> 中文审阅版。英文权威版为 `SPEC-notification-outbox.md`；两份文档必须保持语义一致。

## 目标

持久化并渲染可执行决策对应的确定性文本提醒，可靠地投递到本地 Web 应用，并可选投递到控制台或通用 Webhook；在重试和重启过程中避免重复提醒。

本模块不判断交易条件是否成立。它接收已经验证的 `SignalIntent`，依据证据使用固定模板生成提醒。AI 不得编写实时提醒文本。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- 通过 `strategy-state` 使用 SQLite 事务发件箱
- 使用 Pydantic 2 定义事件载荷
- 使用无 Jinja 的强类型 Python 渲染器，避免模板注入
- 使用 `httpx` 支持可选的通用 HTTPS Webhook
- 使用 `local-web` 提供的 FastAPI WebSocket 发布器

## 命令

```powershell
python -m pytest tests/unit/test_notification_outbox.py -q
python -m pytest tests/integration/test_notification_delivery.py -q
python -m ruff check src/trade_plan_monitor/notifications tests/unit/test_notification_outbox.py tests/integration/test_notification_delivery.py
```

## 项目结构

```text
src/trade_plan_monitor/notifications/
├── models.py       # 提醒、事件与渠道契约
├── identity.py     # 稳定的去重键
├── render.py       # 确定性中文文本渲染
├── outbox.py       # 仓储与服务契约
├── dispatcher.py   # 有界重试投递
└── channels.py     # 应用内、控制台及可选 Webhook 适配器
tests/unit/
└── test_notification_outbox.py
tests/integration/
└── test_notification_delivery.py
```

## 事件契约

```python
class AlertPayload(BaseModel):
    event_id: UUID
    dedup_key: str
    plan_id: str
    plan_version: int
    plan_hash: str
    symbol: str
    name: str
    signal_type: ActionableSignalType
    severity: Literal["INFO", "ACTION", "RISK", "CRITICAL"]
    trading_date: date
    cause_id: str
    evaluated_at: datetime
    market_data_at: datetime | None
    data_age_seconds: int | None
    price_fen: int | None
    quantity: int | None
    bucket: PositionBucket | None
    target_lot_id: str | None
    matched_conditions: tuple[ConditionEvidence, ...]
    satisfied_conditions: tuple[EvaluationEvidence, ...]
    unmet_conditions: tuple[EvaluationEvidence, ...]
    blockers: tuple[EvaluationEvidence, ...]
    zone: DecisionZone
    relevant_zone: AlertPriceZone | None
    risk_line_fen: int | None
    next_step: NextStep

class AlertEvent(AlertPayload):
    sequence: int
    message_text: str
    created_at: datetime
    acknowledged_at: datetime | None
```

载荷为严格、冻结且复制时重新校验的值。`BUY_CORE_READY` 与
`BUY_TACTICAL_READY` 映射为 `ACTION`；`PRESSURE_REDUCE_READY` 与
`RISK_BREACH` 映射为 `RISK`；`RISK_EXIT_READY` 与
`RISK_EXIT_PENDING_SETTLEMENT` 映射为 `CRITICAL`。`RISK_BREACH` 不携带数量、
仓位桶或目标批次；其余五种可操作信号保留已经由 `SignalIntent` 校验的准确
数量、仓位桶及目标批次形态。

去重前像严格由五个竖线分隔字段组成，不含首尾空白：

```text
plan_hash|trading_date.isoformat()|signal_type.value|cause_id|quantity_text
```

`quantity_text` 为十进制整数；数量为 `None` 时使用空字符串。SHA-256 对该准确
前像的 UTF-8 字节进行哈希，并返回小写十六进制。经过校验的字段域均排除 `|`，
因此该编码无歧义。

数据库唯一约束以原子方式认领事件。信号状态转换、审计记录和事件入队必须使用同一个事务。

`AlertOutbox` 绑定 Session，并通过 `UnitOfWork.alerts` 暴露。`enqueue` 在分配下一个
序号前通过持久化单例高水位行串行化 SQLite 写者，保存规范严格 JSON，并只 flush 而
不自行提交。删除保留期内的提醒历史不能使该高水位倒退。使用相同
去重标识且其余语义相同的重试会返回原始事件 ID、序号、文本和创建时间，即使调用方
重新生成了事件 ID；Decimal scale 与有符号零不会产生伪冲突，其他语义冲突则以
`ALERT_IDENTITY_CONFLICT` 失败。读取时重新校验
载荷，并要求其中的事件 ID 和去重键与所属数据库行一致。

## 文本提醒

每条可执行提醒必须包含：

- 信号标签和严重级别、股票名称及代码；
- 评估时间、行情数据时间及数据年龄；
- 当前价格，以及适用时的建议数量；
- 信号匹配条件，以及从 `EvaluationResult` 原样复制的完整已成立、未成立和阻断
  分区；
- 相关价格区间、风险线、计划版本及事件 ID；
- 下一步操作；
- `仅提醒，不会自动下单`。

示例格式：

```text
【低吸底仓买点成立｜ACTION】华亚智能（003043.SZ）
时间：2026-08-07 10:25  行情：2026-08-07 10:25（延迟18秒）
价格：64.20元  建议：低吸底仓100股
区间：低吸区63.00～64.50元（含下界、含上界）
信号成立：价格位于低吸区【成立】（当前价=64.20元）
结果成立：价格位于低吸区【成立】（当前价=64.20元）
结果未成立：无
阻断：无
风险线：60.80元  计划：huaya-smart-v1
下一步：人工确认后自行决定是否下单
原因：episode-001
事件：00000000-0000-0000-0000-000000000001
仅提醒，不会自动下单。
```

常规 `WAIT` 状态在监控总览快照中可见，但不生成提醒事件；只有被配置为需要提醒的健康状态转换例外。

证据渲染保留复合 `ALL`/`ANY` 分组、每个节点的三值结果、父节点事实、子节点
顺序、缺失输入代码及全部补充 `RuleEvidence`。Decimal 文本不受上下文影响，
并规范化 scale 与有符号零，因此规范等价的决策事实会生成相同文本。
`data_age_seconds` 从实际展示的 `market_data_at` 推导，而不是取可能更新的健康
摘要事实。

## 投递语义

- `IN_APP` 为必选渠道：已提交事件可在提醒中心查询，并作为带序号的 WebSocket 更新发布。
- `CONSOLE` 用于本地诊断，显示相同的事件 ID。
- `WEBHOOK` 以通用 JSON 渠道实现，但默认关闭。仅允许 HTTPS 白名单主机，并拒绝重定向。
- 每个渠道采用至少一次投递语义，并通过幂等事件 ID 去重。各渠道状态分别跟踪。
- 失败事件保持待投递状态，并使用有界重试和退避。某个渠道失败不得隐藏应用内事件。
- 确认提醒仅表示“用户已看到该事件”；不代表投递成功、成交或持仓更新。

在 T027 中，`IN_APP` 投递成功表示分发器已经恢复一条已提交 Outbox 记录，且提醒在
本地提醒中心中仍可查询；它不声称浏览器已经收到 WebSocket 帧。实际 WebSocket 发布
和回放由 T039 负责。分发器始终加入 `IN_APP`，默认启用 `CONSOLE`，跳过关闭的
`WEBHOOK` 且不创建尝试，并按事件序号后接 `IN_APP`、`CONSOLE`、`WEBHOOK` 的顺序
处理到期工作。

`dispatch_pending(limit=100)` 接受 1～100 的上限，并最多尝试这么多组到期的事件/渠道。
它在短读事务中只重建已提交事件，在渠道 I/O 前关闭该事务，再用新的短事务保存结果。
因此，重启后可以扫描没有任何投递尝试的已提交事件。如果进程在外部发送完成后、结果
保存前停止，后续尝试可能再次发送同一个稳定事件 ID；这是有意的至少一次边界。

每次逻辑尝试先在短事务中进入 `CLAIMED`，并获得固定 60 秒租约。只有认领成功的
分发器执行渠道 I/O；竞争分发器跳过该事件/渠道组合。重启后使用同一尝试行和序号
重新认领过期租约，因此发送前停止不会消耗一次重试。发送后、完成状态保存前停止时，
可能按至少一次语义再次发送同一稳定事件 ID。最终状态为 `DELIVERED`、
`RETRY_PENDING` 或 `FAILED`。首次尝试立即执行。默认持久化重试延迟严格为 30、60
和 300 秒，逻辑尝试次数最多四次；恰好到达 `next_retry_at` 时即可再次尝试。重试
tuple 可注入测试或后续运行时配置，但最多包含 10 个正延迟，且每个不超过一天。
终态投递或失败永不再次选中。

`WebhookConfig` 为严格、冻结且默认关闭的配置。启用的端点必须使用 HTTPS，最长
2,048 个字符，不得包含内嵌账号密码、查询或片段；其精确且大小写不敏感的主机必须
位于最多 64 项且不重复的白名单中；禁止通配主机和重定向。超时默认 5 秒，范围为
1～30 秒。JSON 正文只包含 `createdAt`、`eventId`、`messageText`、`sequence`、
`severity`、`signalType` 和 `symbol`。

配置复制会重新校验全部字段，构造渠道时会再次校验具体配置实例，且渠道启用状态是
已验证冻结配置的只读视图。这些边界防止通过复制/更新或构造后切换绕过 HTTPS 和白名单。

Webhook 任意 2xx 结果为 `DELIVERED`。HTTP 408、429、5xx、超时和传输故障可重试；
其他 4xx 响应及所有 3xx 重定向均为终态。适配器从不读取或保留响应体。公开配置和
存储错误移除验证输入、SQL 参数、异常 context 和异常 cause；渠道结果只保留稳定
错误码及可选 HTTP 状态。控制台、Webhook 或意外适配器故障均与其他渠道隔离。

逻辑表：

```text
alert_event(id, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
alert_sequence(singleton_id PRIMARY KEY CHECK(singleton_id = 1), last_sequence CHECK(last_sequence >= 0))
delivery_attempt(id, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code)
```

追加迁移 `0004_alert_sequence` 创建该单例，并从既有事件最大序号回填
`last_sequence`；空 Outbox 则回填为零。

WebSocket 回放默认保留 7 天；提醒历史默认保留 1 年，且可配置。

`replay_after(sequence, limit=1000)` 使用排他性的非负序号游标，按升序返回事件，
并包含恰好创建于配置保留截止时刻的事件。`acknowledge(event_id)` 只记录第一次确认
时间，并在同一事务中追加一条 `ALERT_ACKNOWLEDGED` 审计；重复确认是幂等的。两项
操作都不会创建投递尝试，也不会修改策略状态或持仓批次。T026 仅提供这些持久化查询；
渠道投递和 WebSocket 发布分别由 T027 与 T039 负责。存储数据或确认完整性失败只暴露
脱敏 Outbox 错误，不保留原始 SQL、参数、载荷、context 或 cause。

## 代码风格

```python
def render_alert(event: AlertPayload) -> str:
    lines = [render_heading(event), render_market_time(event)]
    lines.extend(render_evidence(event))
    lines.append("仅提醒，不会自动下单。")
    return "\n".join(lines)
```

用户或 AI 产生的文本必须作为经过转义且有长度限制的纯文本渲染，不得渲染任意
HTML。最终消息最多 16,384 个字符，并按照增量剩余字符预算构建。每个证据分区
最多包含 50 个顶层项；单个载荷最多包含 250 个待渲染证据节点、512 个事实，且
任一待显示数值的系数或整数最多为 256 位。插值名称拒绝控制、格式、代理、行分隔
和段落分隔字符（`Cc`、`Cf`、`Cs`、`Zl`、`Zp`）；最终文本只允许渲染器自身
加入的换行符。

## 测试策略

- 为每种可执行信号及缺少可选字段的情况编写完整文本黄金样例测试。
- 复合证据测试保留三值子节点结果、分组、父节点事实及补充规则证据。
- 覆盖 Decimal scale、有符号零及环境上下文不变性。
- 覆盖重复评估、重试、重启和并发入队的去重测试。
- 证明状态与提醒要么同时提交、要么同时回滚的事务测试。
- WebSocket 序号、回放及 7 天保留边界测试。
- 覆盖超时、2xx、4xx、5xx、有界重试、主机白名单、拒绝重定向和密钥脱敏的 Webhook 测试。
- 证明确认提醒不能修改持仓的测试。
- XSS、控制字符及超长证据测试。

## 边界

- 始终：先持久化再发布，且仅发布已提交事件。
- 始终：保持稳定事件 ID 和序号顺序。
- 始终：区分投递、提醒确认和成交语义。
- 需先确认：增加短信、邮件、微信、钉钉、飞书或浏览器操作系统通知渠道。
- 禁止：让渲染器改变信号类型、数量或规则证据。
- 禁止：发送密钥、原始供应商错误或隐藏的提示词内容。
- 禁止：使用 AI 改写实时提醒。

## 验收标准

- 同一可执行事件在重试或重启后只在 Web 提醒中心出现一次。
- WebSocket 断开不会丢失事件；重连后通过快照或回放恢复。
- 提醒文本包含完整的证据契约和免责声明。
- 控制台或 Webhook 失败不能阻止应用内持久化。
- 确认提醒不能改变策略状态或持仓批次。
- 用户及 AI 文本均以安全纯文本显示。

## 待确认问题

- 尚未选择外部消息产品；通用 Webhook 默认保持关闭。
