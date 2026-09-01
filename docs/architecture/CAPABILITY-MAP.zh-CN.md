# 能力地图：本地 AI 辅助交易计划监控系统

> 中文审阅版。英文权威版为 `CAPABILITY-MAP.md`；两份文档必须保持语义一致。

## 产品边界

- 独立的本地 Web 应用，仅供一名用户使用，并且只监听 `127.0.0.1`。
- 最多同时启用并监控 10 只 A 股股票。
- 支持粘贴自然语言交易计划，由用户配置的 AI 服务生成结构化草稿。
- AI 草稿必须经过确定性校验和用户明确激活，才能进入监控系统。
- 实时链路只提供文字与可视化提醒，绝不提交、撤销或推断券商成交。隔离的离线 `BACKTEST` 模式可以为研究生成版本化模拟成交。
- 已批准的回测重新设计通过持久化且有界的任务层增加本地 Vue 工作台和增量 REST 资源；在各模块规格、计划和任务分别通过审核前，Web 界面仍未实现。
- 实时状态使用一个 SQLite WAL 数据库，回测使用隔离的行情/结果 SQLite 数据库；不建设集群、主从或高可用系统。

## 能力模块

| 模块 ID | 职责 | 依赖 |
|---|---|---|
| `plan-domain` | 版本化计划模型、价格区间、监控条件、激活策略、校验规则和不可变活动版本 | 无 |
| `ai-plan-drafting` | AI 服务配置、提示词版本、自然语言转结构化草稿、证据、不确定项和连通性测试 | `plan-domain` |
| `market-data` | Tushare 接口、交易日历、涨跌停价、1 分钟/5 分钟/日线、数据新鲜度、请求控制和指标 | 无 |
| `strategy-state` | 人工持仓批次、T+1、低吸事件、风险状态、计划激活状态、行情历史和审计记录 | `plan-domain` |
| `decision-engine` | 根据活动计划、完整行情、指标、阻断项和策略状态进行纯函数式确定性判断 | `plan-domain`、`market-data`、`strategy-state` |
| `notification-outbox` | 信号去重、文字提醒渲染、确认、重试、站内提醒、控制台和通用 Webhook | `decision-engine` |
| `monitor-runtime` | 最多 10 只股票的交易时段调度、受控并发、恢复、健康状态、回放和优雅停止 | `market-data`、`strategy-state`、`decision-engine`、`notification-outbox` |
| `backtest-data` | 历史能力映射、经授权的增量同步、覆盖检查、不可变修订、数据集校验和冻结的 `dataset_hash` identity | `market-data` |
| `backtest-engine` | 纯离线事件时间回放、禁止未来数据、版本化模拟成交、确定性指标和 `run_id` identity | `backtest-data`、`plan-domain`、`market-data`、`strategy-state`、`decision-engine` |
| `backtest-results` | materialized 运行摘要、成交、有界详情、分页、导出、置顶、保留和完整性校验重建 | `backtest-engine` |
| `backtest-jobs` | 持久化且有界的同步/校验/运行任务生命周期、专用单线程执行槽、原子幂等认领与任务/结果 Unit of Work、进度、协作取消、重启恢复和单机资源准入 | `backtest-data`、`backtest-engine`、`backtest-results` |
| `backtest` | 只供研究的离线回测全局稳定不变量与目标 CLI 兼容索引；详细契约由六份子模块规格拥有 | `backtest-data`、`backtest-engine`、`backtest-results`、`backtest-jobs` |
| `local-web` | 面向实时视图的共享仅回环 FastAPI/Vue 平台、同源安全、OpenAPI 生成、应用壳和设计 Token | 全部实时模块 |
| `backtest-api` | 数据集、任务、运行、结果、计划快照、幂等、分页和生成式前端契约的增量类型化 REST 资源 | `backtest-data`、`backtest-jobs`、`backtest-results`、`plan-domain`、`local-web` |
| `backtest-web` | 覆盖历史数据、运行提交、进度/取消、分页历史和结果检查的 Vue 回测工作台 | `backtest-api`、`local-web` |

## 构建顺序

```text
plan-domain ──→ ai-plan-drafting
     │
     └──→ strategy-state ───────────────┐
                                        ▼
market-data ───────────────────→ decision-engine
                                        │
                   ▼
        notification-outbox
                   │
                   ▼
            monitor-runtime ─────────────────────────→ local-web

market-data ──→ backtest-data ──→ backtest-engine ──→ backtest-results
                      │                  │                    │
                      └──────────────────┴────────────────────┘
                                         │
                                         └──→ backtest-jobs ──┬──→ backtest（CLI 兼容/索引）
                                                              └──→ backtest-api ──→ backtest-web
                                                                       ▲                 ▲
                                                                       └──── local-web ──┘
```

`plan-domain` 通过后，`ai-plan-drafting`、`market-data` 和 `strategy-state` 可以分别规格化和实现。实盘决策链路不会调用 AI。`backtest` 复用纯决策契约，但执行期间与实时存储、调度器、通知和网络保持隔离。

已批准的回测模块构建顺序为 `backtest-data` → `backtest-engine` → `backtest-results` → `backtest-jobs` → `backtest-api` → `backtest-web`。稳定 `backtest` ID 保留为文档总览和目标 CLI 兼容契约，不会被重命名或复用。当前直接 CLI MVP 在获批任务把适配器迁移到 `backtest-jobs` 前继续作为基线，但不能成为第二条编排路径。现有已验证代码映射到前三个模块；此次拆分不授权重写正常工作的确定性逻辑。`backtest-jobs` 负责原子任务/结果 Unit of Work 并调用结果事务参与者；`backtest-results` 绝不导入任务协调器。

## AI 信任边界

1. 用户粘贴或编辑自然语言交易计划。
2. AI 返回符合公开草稿 Schema 的 JSON，并附带原文证据、不确定项和未映射内容。
3. 后端把 AI 输出视为不可信输入，执行类型、数值范围、日期、区间重叠、仓位和白名单条件校验。
4. Web 界面同时展示原文、提取结果、遗漏、警告和版本差异。
5. 用户完成修改并明确激活一个不可变计划版本。
6. 盘中只有 `decision-engine` 能读取活动计划并作出判断。

AI 输出不能直接激活计划、写 SQL、执行代码、调用券商或绕过校验。AI 不可用时，仍可使用结构化表单以及 YAML/JSON 导入。

## 文字提醒契约

“文字提醒”是指触发买点、减仓或风险事件后，系统生成完整、可读、可追溯的消息，而不只是改变图表颜色或播放声音。首版将消息保存在 Web 提醒中心，并显示站内弹窗；控制台输出用于诊断，外部 Webhook 默认关闭。

每条可操作提醒必须包含：

- 信号类型和严重程度；
- 股票名称与代码；
- 判断时间、行情时间和数据延迟；
- 当前价格和建议数量；
- 已满足条件和剩余阻断项；
- 相关价格区间、风险线、计划版本和事件 ID；
- 下一步说明；
- `仅提醒，不会自动下单`。

## 已确认假设

1. “需要文本”同时指自然语言计划输入和完整可读的文字提醒。
2. 首版 AI 接入采用 OpenAI-compatible HTTP 契约，用户可配置服务名称、Base URL、模型、超时、重试、Token 上限和密钥引用。
3. AI 密钥不写入计划、日志或普通 API 响应；界面只显示脱敏状态。
4. Tushare 是首版唯一行情源；Token、批量代码、节流、权限探测和 1–10 只股票的请求限制可配置。
5. 系统只监听本机回环地址，因此首版不建设登录系统；仍需限制 Origin/CORS、设置 CSP、校验输入并保护密钥。
6. 实际成交后由用户人工登记持仓；提醒和提醒确认都不等于成交。
7. 回测成交只是模拟研究记录。历史 `stk_mins` 能力独立于实时 `rt_min`/`rt_min_daily`，不能完成 `T058`。
8. 历史回测日历当前只显式支持 SSE/SZSE；在存在经验证的 BSE 日历前阻断 `.BJ`。读取冻结 artifact 时重算哈希，信号/成交时间保留 `receivedAt`/`openAt` identity，materialized 长期摘要/成交行可重建缺失的摘要 JSON/成交 CSV，但不能恢复已过期详情。
9. 每个活动回测时间戳——包括行情、回放、任务生命周期、审计、结果发布、持久化、API 和 Web 展示——都使用带时区的 `Asia/Shanghai` 业务时间。规范 RFC 3339 传输/存储文本显式携带 `+08:00`；拒绝 `Z`、无时区值和其他偏移。仅日期值使用中国市场日历。现有 UTC 规范化本地 MVP 结果/导出字节保持为隔离的不可变兼容 artifact，在完成版本化采纳迁移前不能成为活动/公开结果。

## 文档语言与双语一致性

- 无语言后缀的文档是供智能体和实现流程使用的英文权威版。
- 同名 `.zh-CN.md` 文档是供用户审阅的中文版本。
- 后续每份面向用户的项目文档在新建或实质修改时，必须在同一次变更中同步更新两个语言版本。
- 两个版本必须保持相同的章节结构、稳定 ID、数值阈值、API 路径、JSON 字段、命令、边界和验收标准。
- 模块 ID、文件名、API 路径、JSON 字段、代码标识符、命令和第三方接口名在两个版本中都保持原样。
- 如果两个版本存在冲突或缺少对应文件，在恢复一致之前，不得通过规格审批或继续下游实现。

## 审核状态

原能力地图已于 2026-08-18 经用户确认。隔离的“混合同步/离线回测”范围、`SPEC-backtest.md` 和有界保留策略已于 2026-08-25 获批。用户于 2026-08-26 批准六模块回测拆分、英文权威/中文审阅的文档规则和推荐的单计划/单股票 Web 范围，随后确认详细规格集合及 `local-web` Backtest Extension Boundary。双语跨模块一致性审计修正了 UUID/CLI 查找 identity、精确 `FenText` 输出、统一 `Asia/Shanghai`/`+08:00` 时间契约、旧结果复用、增量导出、item 发布大小及取消/置顶幂等条款，且不改变已批准模块边界。用户已于 2026-08-26 明确确认中国时区选择及其余修正契约；聚合详细规格集合现按修正内容获批。双语实施计划第 15 节已于 2026-08-26 获批。该批准仅授权生成双语 `BT009`～`BT050` 任务清单。生成后的任务清单仍需单独明确批准；实现、提交、推送、依赖安装和任何联网访问仍未获授权。本地 CLI MVP 与完整性回归仍是实现基线，开放的 `BC01` 验收工作继续保留。任何回测任务都不重编号或完成 `T058` 或 `T059`。
