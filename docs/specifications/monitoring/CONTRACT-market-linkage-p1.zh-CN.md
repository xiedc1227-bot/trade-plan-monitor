# 契约清单：market-linkage-p1

## MLC1-01 — 已批准权限与基线

2026-10-24 用户批准 MLP1-D01–MLP1-D06，并明确授权顺序完成全部 P1 任务及分阶段验收，无需重复确认。基线 `dbeff32`，分支 `main`；此前未提交改动仅为八份 P1 提案／索引文档。[规格](SPEC-market-linkage-p1.zh-CN.md) · [任务](../../../tasks/market-linkage-p1.zh-CN.md) · [规范英文版](CONTRACT-market-linkage-p1.md)。

V01 基线通过：91 项测试，1.20s。这证明既有行为，不代表 P1 验收。T01 文档切片为批准／状态（四份文件）、边界清单／报告（四份文件），再更新索引措辞（四份文件）。

## MLC1-02 — 读写端清单

除另有说明外，源路径位于 `src/trade_plan_monitor/`。扩展明确分支及分发，不扩大 Schema 6 以授权例外。

| 边界 | 已核对的负责位置 | P1 变更 |
| --- | --- | --- |
| 严格计划与草稿 | `domain/market_linkage_models.py`、`market_linkage_validation.py`、`unified_plan_validation.py`、`daily_plan_validation.py` | 独立 Schema 7 规则／计划及可空草稿策略；继承共用校验，不改旧字段 |
| 编解码与哈希 | `domain/plan_codec.py`、`plan_hash.py`、`daily_plan_validation.py` | 明确分发 7，使用 `plan-review-content-v4`；完整规范计划 SHA-256 保持精确 |
| 提取／审核 | `ai/plan_extraction.py`、`extraction.py`、`loop_plan_extraction.py`、`models.py`、`prompts.py`、`daily_review.py`、`semantic_validation.py`、`domain/market_linkage_definitions.py` | `plan-extract-v10`，完整例外绑定，不导入批准 |
| 更新／准备 | `ai/plan_delta_wire.py`、`preparation_wire.py`、`plan_update_extraction.py`、`predecessor_patch.py`、`update_review.py` | 保留明确 Schema 7 许可，变化必须审核 |
| 共用判断 | `decision/confirmation_selection.py`、`quantity_policy.py`、`market_linkage.py`、`unified_lifecycle.py` | 专用 v2 证据／计算及纯例外校验；旧评估器保持精确 |
| 持久权限 | `state/daily_repository.py`、`daily_state_models.py`、`market_linkage_authority.py`、`daily_models.py` | 既有事务存储中的版本化候选／事件，确定性唯一 ID、哈希校验及修订保护 |
| 生产运行 | `runtime/daily_service.py`、`production.py`、`service.py`、`market_indexes.py` | Schema 7 分发，复用采集及稳定机会策略，候选与可执行信号分别持久保存 |
| 执行／读取／发送 | `state/simulation.py`、`web/daily_service.py`、运行完成／读取及通知准入 | 精确持久授权加当前门槛；原子整笔消费；批准不改持仓 |
| HTTP 与 UI | `web/routers/plans.py`、`daily_plans.py`、服务装配；`web/src/composables/usePlanWorkspace.ts` 及计划组件 | MLP1-09 三个新命令族、版本化运行视图；生成两套 API 配置；本地保护不变 |
| 回放 | `backtest/run_input.py`、`loop_input_store.py`、`loop_dataset.py`、`loop_replay.py`、`runner.py`、`loop_runner.py`、`research_runner.py`、`composition.py`、`plan_schedule.py`、`plan_updates.py`、`preparation_review.py` | `backtest-run-v8` 和冻结明确授权事件，覆盖运行／研究两种入口 |

## MLC1-03 — 版本与存储决策

拟议版本名称在现有源码定义中没有冲突。保留已批准 Schema 7 / `condition-plan-v3` / `market-linkage-v2` 身份。审核使用 `plan-review-content-v4`；证据／计算使用 `market-linkage-evidence-v2`、`market-linkage-calculation-v2`；候选及授权使用 `market-linkage-exception-candidate-v1`、`market-linkage-exception-authorization-v1`。每个哈希使用规范 JSON 和既有 domain/NUL/SHA-256。不向旧对象序列化新默认字段。

保留市场／指数公式及 Q0／普通数量字段。每条规则的 `market_policy.exception_routes` 包含两个必要许可字段；明确 DISABLED/DISABLED 仍有效。草稿可有缺失值，但不能通过可执行校验。保留既有计划／展开条件树限制。

复用 `DailyRecord`，通过确定性候选、事件及命令身份和既有写事务／修订检查实现，其主键提供持久唯一性。候选状态为带修订保护的可变投影；授权和终态事件载荷只追加。事件 ID 包含机会和转换身份，防止不同命令键重复批准或消费。保存前和加载后均须精确字段校验；不能靠宽松的未知记录处理授予权限。既有幂等回执保护请求正文，并与效果处于同一事务。除非后续检查证明必要，否则无需新建物理表／迁移；若确需新增，须先记录并以增量方式测试。

候选绑定 MLP1-08 全部身份、合格 D 日证据、算出的下一交易日及服务端收盘时间、冻结输入计算及原有独立事件连续性。批准冻结确切数量，并创建绑定候选／批准 ID 的信号。新证据／计算模型区分未批准候选数量及正数量批准权限；不改 v1 将普通计算等同冻结信号数量的校验器。预览是展示内容的不可变审计快照，不产生权限或持仓效果；批准时按当前修订重新计算。

## MLC1-04 — 兼容与完成门槛

| 输入／状态 | 新读取端 | 旧读取端／回退 |
| --- | --- | --- |
| Schema 1–6 及既有研究／状态 | 原有精确分发、序列化字节和哈希 | 不变 |
| 例外关闭的 Schema 7 | 普通行为及明确关闭原因，不授予例外 | 拒绝不支持版本，不降级 |
| 例外开启的 Schema 7 | 资格加精确本地批准 | 拒绝不支持版本，保留记录 |
| 新候选／授权／研究事件 | 验证版本、摘要、机会、截止时点和状态 | 保留字节，阻断操作，不当作普通信号 |

T02 顺序切片：T02a 模型、编解码及契约测试；T02b 草稿模型／分发及测试；T02c 审核哈希、问题分发及测试。每片最多五份源码／测试文件。公共启用、提取及执行支持在所属任务完成前保持不可用；仅领域编解码不代表已交付支持。

T04 顺序切片：T04a 完整双语定义、语义审核及集成测试（四份文件）；T04b 当前提示词／版本分发及测试（最多五份文件）；T04c 数据商／配置默认值及循环提示词兼容（最多五份文件）。T05 负责紧凑准备及前序补丁传递。许可字段和完整定义即使声称为字面 SOURCE 绑定，也必须校验来源含义，不只检查 SOURCE_SEMANTIC。

T01 需 V01 和双语文档检查才能通过。后续任务须在 [P1 验收报告](../../verification/2026-10-24-market-linkage-p1.zh-CN.md)记录已执行证据；未勾选任务不代表已完成能力。

T06 检查发现 `ck_daily_record_kind` 不接受新证据种类。增量迁移 `0026_market_exceptions` 扩展该约束、保持原载荷字节并增加事件命令唯一索引。存在新记录时拒绝降级。实施期间不迁移用户数据库。T06a 为模型／仓储／测试；T06b 为种类校验、仓储不可变保护及迁移；各切片分别验证。

T09 已验证切片：(a) v2 数量／证据、零权限机会种子及持久化联合类型；(b) 既有激活／审核分派；(c) 生产候选／批准接点及运行组合；(d) 读取／发送／完成权限及聚焦竞争回归。生成产物和明确的旧契约投影变化归 T11/T12。
