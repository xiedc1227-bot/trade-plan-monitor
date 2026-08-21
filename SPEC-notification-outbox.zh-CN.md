# 规格：notification-outbox（提醒发件箱）

> 中文审阅版。英文权威版为 `SPEC-notification-outbox.md`；两份文档必须保持语义一致。

## 目标

持久化并渲染可执行决策对应的确定性文本提醒，可靠地投递到本地 Web 应用，并可选投递到控制台或通用 Webhook；在重试和重启过程中避免重复提醒。

本模块不判断交易条件是否成立。它接收已经验证的 `SignalIntent`，依据证据使用固定模板生成提醒。AI 不得编写实时提醒文本。

## 技术栈

- Python 3.11+
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
class AlertEvent(BaseModel):
    event_id: UUID
    sequence: int
    dedup_key: str
    plan_id: str
    plan_hash: str
    symbol: str
    name: str
    signal_type: SignalType
    severity: Literal["INFO", "ACTION", "RISK", "CRITICAL"]
    evaluated_at: datetime
    market_data_at: datetime | None
    data_age_seconds: int | None
    price_fen: int | None
    quantity: int
    matched_conditions: list[ConditionEvidence]
    blockers: list[ConditionEvidence]
    risk_line_fen: int | None
    next_step: str
    message_text: str
```

去重键：

```text
sha256(plan_hash | trading_date | signal_type | episode_or_risk_transition_id | quantity)
```

数据库唯一约束以原子方式认领事件。信号状态转换、审计记录和事件入队必须使用同一个事务。

## 文本提醒

每条可执行提醒必须包含：

- 信号标签和严重级别、股票名称及代码；
- 评估时间、行情数据时间及数据年龄；
- 当前价格，以及适用时的建议数量；
- 已成立条件与阻断条件；
- 相关价格区间、风险线、计划版本及事件 ID；
- 下一步操作；
- `仅提醒，不会自动下单`。

示例格式：

```text
【低吸买点成立】华亚智能（003043.SZ）
时间：2026-08-07 10:25  行情：10:25（延迟18秒）
价格：64.20元  建议：低吸100股
成立：位于低吸区；两根5分钟K线未创新低；成交量收缩；MACD负柱改善
风险线：60.80元  计划：huaya-smart-v1
下一步：人工确认后自行决定是否下单
事件：<event-id>
仅提醒，不会自动下单。
```

常规 `WAIT` 状态在监控总览快照中可见，但不生成提醒事件；只有被配置为需要提醒的健康状态转换例外。

## 投递语义

- `IN_APP` 为必选渠道：已提交事件可在提醒中心查询，并作为带序号的 WebSocket 更新发布。
- `CONSOLE` 用于本地诊断，显示相同的事件 ID。
- `WEBHOOK` 以通用 JSON 渠道实现，但默认关闭。仅允许 HTTPS 白名单主机，并拒绝重定向。
- 每个渠道采用至少一次投递语义，并通过幂等事件 ID 去重。各渠道状态分别跟踪。
- 失败事件保持待投递状态，并使用有界重试和退避。某个渠道失败不得隐藏应用内事件。
- 确认提醒仅表示“用户已看到该事件”；不代表投递成功、成交或持仓更新。

逻辑表：

```text
alert_event(id, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
delivery_attempt(id, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code)
```

WebSocket 回放默认保留 7 天；提醒历史默认保留 1 年，且可配置。

## 代码风格

```python
def render_alert(event: AlertPayload) -> str:
    lines = [render_heading(event), render_market_time(event)]
    lines.extend(render_evidence(event))
    lines.append("仅提醒，不会自动下单。")
    return "\n".join(lines)
```

用户或 AI 产生的文本必须作为经过转义且有长度限制的纯文本渲染，不得渲染任意 HTML。

## 测试策略

- 为每种可执行信号及缺少可选字段的情况编写文本黄金样例测试。
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
