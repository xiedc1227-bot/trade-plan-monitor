# ADR 0005：版本化显式计划规则并保留历史含义

> `0005-version-explicit-plan-rules.md` 是英文正式版；本文为语义等价的中文审阅副本。

- 状态：`Accepted`
- 当前范围：冻结兼容设计依据；新实时操作遵循 `SPEC-unified-plan.md`。
- 复核版本修订：[ADR 0006](0006-review-mixed-source-with-bounded-treatments.zh-CN.md) 只取代新服务端映射/证据版本；历史 v1 快照及全部提示词契约继续冻结。
- 日期：`2026-09-12`
- 工作项：`F06 / R08–R12`
- 模块：`plan-domain`、`decision-engine`、`ai-plan-drafting`、`strategy-state`、`notification-outbox`、`local-web`、`backtest-engine`

## 背景

在 `beff0410150813e64a242a3821a299090d963e9b`，`TradePlan` 支持 Schema 1/2，但仍强制要求 entry/reduction/risk/levels 和 CORE/TACTICAL 目标。`TradePlanDraft` 继承完整模型。`EvaluationResult` 及运行时/outbox 消费一个带分仓限制的交易意图；官方风险具有持久副作用。合成计划需要算术均量、直接数量100、普通卖出和五分钟纯风险。如果把它当成另一份低吸 fixture，会改变用户含义。

R03 在 import 时以生成 Schema 摘要保护提示词。R04/R05 把审核绑定到精确原文和文档哈希；编辑后 AI 草稿尚无完整的当前内容重审流程，因此仍待审核。R07 人工风险也使用同一精确计划哈希。文档哈希包含 `version`，不能重命名为语义内容哈希。历史事件迁移使用冻结校验器，不能安全消费持续演进的应用类型联合。

## 决策

1. 按[扩展规格](../specifications/monitoring/SPEC-plan-domain.zh-CN.md)新增有界的平行模型 Schema 3 / `EXPLICIT_RULES` / `explicit-rules-v1`。保留旧 `TradePlan`、条件联合和提示词可见模型图。复用标量类型、价格算术、三值求值辅助、日历/数据校验和事务参与者，在消费者处增加类型化分派。不得先扩展旧条件联合再修黄金哈希。
2. 保留 Schema 1/2 规范 JSON/YAML 往返及 SHA-256。派生读取/展示模式为 `LEGACY_LOW_BUY`，不向存储字节注入此字段。当前修复后低吸实现使用 `legacy-low-buy-r06` 标签，写入新的运行/审计元数据。未记录执行版本的历史执行，其外部来源标识保持 `UNRECORDED`；不能回填对原运行算法的断言。
3. v3 精确计划哈希沿用规范文档 SHA-256。仅 v3 的语义 `contentHash` 使用 `plan-review-content-v1` 域，只排除 E07 的四个元数据/身份字段。它补充而非取代 sourceHash、精确 planHash、reviewEvidenceHash、不可变 planVersionId 和 active revision。R04/R05/R07 历史绑定不变。相同内容重存，仅在相同原文/证据来源链经校验且服务端绑定到新版本时才能保留语义审核；交易含义编辑总是重置。
4. `ExplicitEvaluationResult` 和 v3 提醒 payload 使用独立判别分支。保留 `decision-result-v1` 和旧提醒/去重字节。新结果使用 `decision-result-v2`、明确执行版本及已消费状态 revision；新提醒使用 `explicit-rule-alert-v1`。通过版本分派复用既有结果存储、outbox 和事件日志；键/CHECK/payload 约束需要时进行追加迁移。不得把普通 SELL 塞进 `PRESSURE_REDUCE_READY`，或把五分钟风险塞进 `RISK_BREACH`。
5. 新旧实时求值/发生身份不能碰撞。新键增加 execution/activation 身份，不改写旧行，可通过附加版本键列/约束，或同一工作单元中的 v3 专用参与者实现。R09 分片必须在开放任何 v3 写入前选择并验证最小无损存储改动。不得用 `formula_version=ta-v1` 代替执行版本。
6. 部分 v3 草稿有明确类型，只作为非活动候选持久化。仅完整可执行分支能进入激活/运行时。结构非法是错误；业务含义缺失是未解决审核项。仅原文提取不完整可以是有效审核结果，不是成功可执行转换。
7. 保留既有回测报告、run ID、dataset hash、result hash、冻结迁移校验器和模拟成交语义。当前 `backtest/runner.py`、`execution.py` 假设单个旧意图/分仓。在另有经过审核的回测版本前，v3 研究成交提交必须返回 `UNSUPPORTED_BACKTEST_PLAN_VERSION`。R09–R13 可以回放纯 v3 监控及临时 SQLite 路径而不生成模拟成交；这不代表 v3 组合回测。修复后旧代码产生的新运行是新证据，不是对 R06 前带缺陷历史结果的复现。

## 提示词兼容矩阵

这些值来自 R03 及当前本地源代码。黄金提示词值使用既有 `GOLDEN_PLAN_SOURCE`，不是新的合成原文；保持不可变。

| 提示词 | 计划契约 | 生成 Schema SHA-256 | 黄金提示词 SHA-256 |
|---|---|---|---|
| `plan-extract-v1` | 历史 Schema 1 | `fbf241167c4e3960c98b59faf62e46b590185a8711ba22209720d683562d18a1` | `420e06c0a8ab136a1b95c8218474fccd7f134d1bc5c9e1365e0c6a4a099e3d8d` |
| `plan-extract-v2` | 历史 Schema 2，五指数 allowlist | `fd5f2f42184ea0fa5b361087f869aa73a7a8e26d961c203d80e1e506d98cc0a3` | `6d9ba53055700e508251fc62ce3a10c2c719b68874ac78aee9f27cbd40127daf` |
| `plan-extract-v3` | 既有 Schema 2，六指数 allowlist | `0de88a7a9bdec1a84ad0d458d2963fcdc2b68bfee591dea270b0f35bc5fa0f95` | `df606ede45e58263b669f092cfaeb575becf1ea314076823b23f275a1768ae5d` |
| `plan-extract-v4` | 显式 Schema 3 部分草稿 + `plan-mapping-v1`，由 R11 负责 | `9461d3099a923e5f9fe172eeba010e0dbe44cbe9d8f93c9465be9626d08965a1` | `e91f6b32a69a60b1f35da3e5deee5acd17d326cecd0efcadd2aa99bdb36b4eb7` |

R09 首先证明增加平行 v3 领域类型后，v1/v2/v3 整个提示词 Schema 图仍逐字节相同。保留 `_render_frozen_schema` 检查。如果共享辅助类型改变生成的标题/默认值/定义，应隔离具有精确旧模型图的历史提示词模型/序列化器，或使用经验证的入库快照，并保留独立摘要/篡改检查；不得更新旧预期摘要、绕过检查，或捕获漂移异常后继续。不得把 `TradePlanDraft` 的继承关系放宽成新联合。

R11 创建单独的 v4 输出模型，并按提示词版本选择解析器，同时增加 prompt-to-schema 支持测试：v1 只接收历史契约；v2 保留旧指数 allowlist；v3 不能返回 Schema 3；v4 只返回新显式草稿契约。模型输出不能自行选择提示词身份。保留旧模板文字、字段含义、枚举范围和解析支持。新字段/枚举在刻意变更 Schema 的 guard 测试中必须失败，除非声明了新版本。

R08–R10 期间既有默认值保持 v3。R11 在离线闸门通过后把 v4 发布为省略版本时的默认值，但不修改真实配置，也不替换提取供应商/模型。旧的显式版本设置继续选择其旧契约。每条新 v4 提取审核记录提示词版本、原文哈希、精确草稿哈希、语义 content hash、映射快照、review-evidence hash 和未解决问题。历史提取行不会仅因为新代码能读取就被重算或标记为已批准。

## 读写与回退矩阵

| 存储/输入数据 | 读取/导出 | 新写入/执行 |
|---|---|---|
| 旧 Schema 1/2 | 精确旧编解码及哈希；旧证据仍可读 | 既有严格审核/日期规则及旧模式；不静默迁移 |
| v3 部分草稿 | 类型化非活动草稿及待填字段 | 只可保存，不可激活/执行 |
| 完整已审核 v3 | 版本化编解码、content/source/review/plan 身份 | 所有必需消费者均支持 explicit-rules-v1 后才可执行；由 R09–R12 实现 |
| 未知 schema/execution/result/alert 版本 | 明确不支持错误；为受控恢复保留原存储证据 | 拒绝，不按最接近版本解释 |
| 历史回测结果 | 既有不可变读取/导出/保留 | 不原地重算或改写 |
| v3 输入旧回测 | 识别并解释不支持模式 | 入队前拒绝研究成交运行 |

在 `0012_manual_event_risk` 后追加迁移，绝不原地修改 `0001–0012`。保留旧哈希/行，并通过兼容 fixture 校验旧读取。允许 v3 写入前，新部署必须先能读取旧数据。旧应用二进制不能安全读取 v3 数据；不得让其访问含新分支的升级数据库。回退应禁用 v3 并保留历史，或使用明确兼容二进制恢复独立验证的备份；绝不剥除新字段/批准来通过旧解析器。降级如会丢失 v3 审核、持仓、规则状态、结果或事件证据，必须拒绝。R08 不执行数据库迁移。

## 考虑过的方案

### 向旧 entry/reduction/risk 添加字段

拒绝：会保留隐藏 episode/TACTICAL 优先级，并危及旧提示词/Schema 哈希。直接 SELL 和纯风险会被迫使用误导信号名及副作用。

### 替换整个计划/求值平台

拒绝：有界平行模型和明确分派可以复用既有引擎辅助和原子流水线；无需新服务、语言或框架。

### 选择全局重复/冲突默认值

拒绝：原文未提供。应提供有限的逐规则选择和未解决字段；安全拒绝仍表示支持范围有限，不能证明原计划完整执行。

### 每次编辑都当成新原文提取

拒绝：会模糊原始来源，也不能忠实表示可信修正。应保留提取历史并增加当前内容审核绑定。

## 影响

R09 需要超出原两个 M 子任务的工作：兼容、编解码、完整持仓事实、规则发生状态、版本化结果/outbox 和提交保护是忠实 BUY 的独立前置。遵循 [R08 映射](../../remediation/R08-mapping.zh-CN.md)中的有序内部切片，每片独立验证、聚焦提交。R10 完成 SELL/风险/冲突，R11 完成审核/提取，R12 完成普通表单。不完整阶段可以证明隔离行为，但不能开放不完整的端到端能力。

## 配置与回退

R08 不改变真实配置、供应商默认、计划、持仓、数据库或凭据。技术版本名是授权范围内的设计决策；具体交易政策仍待明确原文/用户证据确认。实施前可撤销这些文档修订；实施后按上述不丢数据的版本/能力策略回退。
