# 规格：统一计划选择与复用

## PRU01. 状态、目标与假设

状态：**2026-10-19 已批准按限定范围实施；包含删除 JSON/YAML 计划导入 API。** 日期：2026-10-19，Asia/Shanghai。本规格属于既有 `backtest-web`、`backtest-api` 与 `backtest-engine` 边界内的一项能力：复用已审核计划，无需重复提取，也无需用户选择回放实现方式。

用户没有外部计划生成器、环境迁移或 JSON/YAML 文件工作流。正常路径是：准备并审核计划 → 选择已审核版本 → 确认缺少的研究上下文 → 回测或再次回测。已保存但未审核的草稿不属于可复用执行计划。无需实时启用。

范围假设：本次“来源统一”指通过同一可复用计划选择契约覆盖两套现有存储，**不代表**合并数据库或替换各自不同的准备／审核流程。默认来源为工作台计划，已有回测准备计划继续可复用。发布说明必须明确此区别，不得声称已实现单一物理计划仓库或单一编写流程。


用户补充，2026-10-19：删除 `POST /api/v1/plan-imports`、其传输命令／客户端／表单及直接相关测试／文档。保留内部 JSON/YAML 编解码、历史计划／结果及原文提取。用户已明确授权删除，无需延迟废弃。

## PRU02. 已核实的现状与实际缺口

| 现有入口 | 实际职责 | 相关源码 |
|---|---|---|
| `/plans` | 保存不可变 Schema 5 候选；明确审核；单独启用 | `web/src/composables/usePlanWorkspace.ts`、`state/daily_review_store.py` |
| `GET /api/v1/plan-versions?canActivate=true` | 从 `plan_version` 读取合格的工作台版本；当前回测版本选择器使用此接口 | `web/src/composables/useBacktestPlanVersions.ts`、`web/plan_service.py` |
| `GET /api/v1/backtest-plan-library` | 从 `backtest_preparation` 读取已审核准备条目 | `backtest/plan_library.py` |
| 已有版本运行 | 单计划研究；Schema 5 需要 `researchInput`；空操作脚本不会模拟成交 | `backtest/composition.py`、`backtest/research_runner.py` |
| 准备计划运行 | 冻结计划、历史日期及期初账户；支持自动响应与关联前序的连续回放 | `backtest/preparation_review.py`、`backtest/plan_schedule.py` |

上表未带目录前缀的源码路径位于 `src/trade_plan_monitor/` 下。两套当前流程都使用 `UnifiedTradePlan`，但审核封装和研究上下文不同。工作台的 `planHash` 对应存储草稿，必须经过已验证转换后重新计算可执行快照哈希，两者不能互相替代。

因此，缺口不只是存在两个列表：当前选择工作台计划后，还会进入另一套执行输入流程。仅合并列表无法消除 JSON 要求及模拟行为差异。

## PRU03. 推荐的用户流程

1. `/backtests/new` 显示一个“选择已审核计划”区域。默认工作台计划；已有准备计划在同一选择器中展示，并保留来源标签供追溯。两类来源各自保留服务端分页，不得把浏览器不完整的合并结果呈现为完整的全局排序列表。
2. 工作台条目显示股票、名称／版本、审核状态；准备条目显示股票、名称、生效日期。按真实含义展示日期，不虚构共同的版本／日期。选择绑定准确身份，不绑定“最新版本”。
3. 选择工作台版本后，仅针对已验证存储数据中缺少的信息，显示结构化“研究起点信息”表单。随后使用与准备计划回放相同的响应选择、结束日期及费用设置。正常复用不要求填写 `researchInput` JSON、数据集哈希或再次调用 AI 提取。
4. 选择已有准备计划／有效组合时，直接复用已冻结账户、日期及原审核，保留现有前序选择校验和账户连续性。
5. 点击“开始回测”后冻结选择及上下文，按既有流程检查、补齐历史数据并提交一次。修改费用或结束日期可以复用已冻结选择；带 `selectionId` 重新加载时恢复已确认上下文，无需重填。

现有原文准备能力通过次级“准备计划”操作继续提供；保留继承、审核、恢复及深链接行为。本次不把编辑器搬到 `/plans`，不修改提取提示词，也不删除其写接口。通过任一当前流程创建并审核的产物都能在共用选择器中选取，不向另一套存储复制。

正常选择流程不再要求用户选择 `LEGACY`／`PREPARED`，它们仅保留为内部兼容细节。已有版本的脚本研究 API 和冻结结果保持原意；普通工作台复用路径通过下文适配器进入既有监控循环执行器。

## PRU04. 同一引用契约、两个读取适配器

复用当前列表及详情 API。增加小型共用前端选择器／组合式函数和后端只读工作台适配器，不新增第三套计划目录表或聚合列表 API。

```typescript
type ReusablePlanRef =
  | {
      origin: "WORKBENCH";
      planVersionId: string;
      planHash: string;
      contentHash: string;
      sourceHash: string;
      reviewEvidenceHash: string;
      reviewId: string;
      reviewRevision: number;
    }
  | {
      origin: "PREPARATION";
      preparationId: string;
      manifestHash: string;
    };
```

工作台条目须先读取既有详情再构造引用，摘要不足以提供完整审核绑定。后端通过现有计划服务／工作单元边界读取准确版本、原文、映射、审核确认及时间，复用既有来源审核校验和已验证的草稿转可执行计划逻辑。未审核、已过时、不支持或引用不匹配时拒绝。不得读取当前启用计划的库存／事实，不改变启用状态，不写监控记录。

准备计划引用使用既有冻结准备读取器及组合 API。不得把准备 ID 当成工作台 UUID，不按相同原文推断等价，也不在不同来源间自动转移审核。

**首期限制：**每次运行选择一个工作台版本；已有准备组合保持最多 256 个条目的现有上限。跨来源混合日程、多工作台版本不在本次范围内，须在下载数据前明确提示选择错误。已有准备链不会退化为单版本。这样限制新增日期／继承工作，同时让每份合格的工作台单计划都能直接复用。

## PRU05. 研究上下文与计划审核分开

工作台审核批准的是交易规则，不是历史期初账户。不能从目标仓位推断实际持仓，不能把今天的模拟库存当成历史库存，也不能用后续计划的文字描述重置账户。

上下文包括 `effectiveTradeDate`、可选历史 `availableAt`、`informationCutoff`、`initialAccount` 以及明确的 `confirmed`／`evidence` 声明。`initialAccount` 复用 `LoopAccountInput` 及其现有嵌套字段名和校验器。能从已验证存储事实读取的直接读取，否则只通过有业务标签的字段补充缺失事实。表单旁展示原文供核对，不为获取账户事实再次运行提取器。

- 库存、成本、取得日期、可卖数量未知时保持未知；空仓必须明确确认。未知库存按既有规则阻断模拟执行。
- 新资金输入默认使用已支持的 `POSITION_LIMIT_ONLY`，说明其按计划最大持仓执行、无现金预算。不补造现金，不要求任意期初资金。保留已有历史资金模式。
- 复用现有激活约束及日历。缺少历史可用时间时，可以采用现有生效日 09:30 假设，但必须明确展示；不能把今天的导入／审核时间当成历史起点。未知编写时间保持未知。`informationCutoff` 不能晚于可用时间，须有实际证据或明确确认的研究假设，不能据此证明没有未来信息。
- 复用现有起点、T+1、CORE、数量、报价、费用及未知值规则。可用时间、期初快照、期初估值须满足现有循环输入边界校验。上下文确认不能扩大计划自身激活／有效期窗口，也不能修改规则。

确认这些研究事实不等于对未变更计划规则再次审核，更不会授予实时启用权限。修改规则或原文时，返回其既有编写／审核流程。

## PRU06. 最小 API 与持久化扩展

新外层 JSON 字段使用 camelCase；复用的嵌套领域字段保留原名。以下是拟议契约，不是已经存在的 API。

| 入口 | 拟议修改 |
|---|---|
| `POST /api/v1/backtest-plan-selections` | 接收 `schemaVersion: workbench-loop-selection-v1`、`plan` 中的一个 `WORKBENCH` 引用和 PRU05 `context`。要求现有 Origin 防护及 `Idempotency-Key`。返回 `201`，包含 `selectionId`、`selectionHash`、相同 schema 版本及冻结上下文／计划摘要。 |
| `GET /api/v1/backtest-plan-selections/{selection_id}` | 读取不可变选择，不读实时计划，不调用 AI、不同步数据、不启动工作线程。返回 `200` 和相同选择视图。 |
| `GET /api/v1/backtest-run-data` | 在现有 `preparationId`／`manifestHash` 参数对之外，新增互斥的 `selectionId`／`selectionHash` 参数对；保留 `endDate`。缺少参数对或混用时拒绝。增加对应的类型化响应分支，旧响应保持不变。 |
| `POST /api/v1/backtest-runs` | 新增 `schemaVersion: workbench-loop-selection-v1` 命令，包含 `selectionId`、`selectionHash`、现有 `response`、`costs` 及可选 `endDate`。保留全部既有命令分支。 |

复用现有错误信封：引用不存在为 `404`，审核／哈希变化或幂等冲突为 `409`，不支持的选择／上下文为 `422`，服务不可用保持既有脱敏 `503`／重试行为。提示可执行的处理办法，不得把不支持计划静默转为另一种回放模式。

允许仅在 `data/backtest-preparation.sqlite3` 增加一张 `backtest_plan_selection` 表，保存 `selection_id` 及规范不可变 `document_json`。通过独立类型的选择操作复用现有准备幂等表，保留旧准备解码。带标记的准备存储 schema 进行事务式升级，保持全部原文档和回执不变。不修改监控、行情或结果 SQL schema，不迁移数据，也不增加数据库。这是研究输入快照，不是新的可编辑计划库。旧程序会拒绝升级后的带标记存储，不宣称可直接降级兼容。

文档冻结准确原草稿／哈希、可执行快照／哈希、原文／映射／审核绑定及真实确认时间，以及单独确认的研究上下文，使用 `workbench-loop-selection-v1` 域计算哈希。读取实时计划之前先解析已持久化幂等记录；同 key／同请求体返回已存选择，不同请求体冲突。选择与回执原子发布。返回运行已接受回执前，把不可变选择复制进结果自有输入；此后即使两套原计划存储都丢失／不可用，运行、恢复及结果读取仍须成立。

## PRU07. 执行复用与历史兼容

从工作台可执行快照及原审核构造真实的 `LoopPlanVersion`，进入既有 `MonitorLoopInput` 单版本路径。原计划审核时间与研究上下文确认时间分别保留。不得为满足类型而伪造提取 ID、准备原文哈希、期初账户提取证据或 `FrozenPreparedPlan`。

增加独立的 `WorkbenchStoredLoopInput` 封装，拟用 `monitor-loop-stored-input-v3`，保存复制选择、绑定选择的循环输入、数据集和日哈希。增量扩展产物解码及相关结果投影。只提取接受已验证日程／起点／账户所需的小型数据请求构造边界，既有准备计划包装及其输出保持不变。不增加第二套规则评估器、行情供应商、执行循环或工作线程所有者。

新增输入使用独立的 `workbench-loop-input-v1` 输入／哈希域，包含 `selection_hash`，避免单独确认的来源／上下文声明发生标识碰撞。执行公式仍为 `backtest-run-v5`，复用现有执行器；共享输入解码器仅增加此类型分支。全部既有输入／哈希域保持不变。来源身份与研究假设保持明确，不得按跨来源原文相同授权运行去重。全部旧编解码、报告内容、运行 ID／哈希、导出格式和保留规则保持不变。新结果通过新增类型化来源投影展示工作台版本身份及研究上下文，不能虚构准备 ID 或审核链。既有准备计划专属规则变更视图保持不变，不为工作台单版本编造变更链。

历史数据自动准备顺序、单个未完成重任务限制、提交预留、重启恢复及独立结果读取线程继续作为权威。选择冻结是有界元数据操作，不是 AI 任务。数据检查结果属于预检查，已接受运行只冻结一次提交边界，幂等重试复用该边界。

## PRU08. 修改边界与替代方案

| 允许修改的范围 | 目的 |
|---|---|
| `web/plan_service.py` 与小型只读适配器 | 通过当前所有权边界获取已验证、绑定审核的工作台快照 |
| `backtest/` 下新增选择模型／服务／存储方法 | 仅冻结缺少的研究上下文及计划引用 |
| `backtest/composition.py`、`automatic_data.py`、`loop_input.py`、`loop_input_store.py` 及必要结果投影 | 把新来源接入既有数据、执行及复制输入路径 |
| 现有运行 schema／路由、API 客户端及生成契约 | 增加选择命令／数据检查分支和两个资源路由 |
| 共用选择器／上下文组件、`BacktestNewView.vue` 及相关组合式函数 | 结构化输入的统一复用交互，保留准备入口 |
| 聚焦测试及对应英文／中文契约、操作文档 | 证明兼容性，记录准确扩展 |

不修改规则模型、AI 提示词、前序推断、在线监控决策、启用指针、模拟库存、行情 schema／供应商、任务限制、读取线程预算或 CI／依赖。不重写整个工作台，不移动现有准备编辑器，不把历史计划迁入 `plan_version`，不增加双向同步，不删除脚本研究 API，不清理无关代码。保留工作区已有未提交修改。

不采用的方案：仅在浏览器合并列表仍有执行差异；要求工作台用户重新提取原文违背复用目标；伪造准备计划清单会丢失审计含义；合并两库或复制审核引入迁移／双写范围。所有编写操作归到一个工作台、多工作台版本或跨来源日程，均需单独确认及设计。

## PRU09. 验收标准

- **AC01：**同一选择器覆盖两类现有来源，独立分页及准确身份正确。工作台为默认来源；选择任一来源不触发 AI、同步或运行。
- **AC02：**合格、已审核但未启用的工作台版本，无需原始 JSON、重新提取、再次审核规则或实时启用，即可使用 `FOLLOW_REMINDERS` 与 `OBSERVE_ONLY`。确定性的已授权夹具在前者产生成交、后者不产生成交；提醒本身不能绕过执行阻断。
- **AC03：**缺失账户／时间事实通过结构化输入补齐。未知持仓不变成零，成本／取得日期／可卖量未知时保持未知。默认及限制符合 PRU05。原文／审核哈希变化、非法日期及不支持日程在联网前失败。
- **AC04：**选择冻结后，修改／审核另一个工作台版本或改变启用指针，不影响已冻结选择。运行接受后，执行、重启及完整结果读取对两套来源计划存储均为零读写。
- **AC05：**选择及运行的同 key／同请求体重试，包括回执丢失、并发提交，均返回已持久化绑定。不同请求体冲突。取消保持现有任务所有权；不准入重复冻结结果或重复重任务。
- **AC06：**既有准备单计划及有效多计划链保留日期、继承、账户连续性、自动数据及结果行为。既有 `preparationId` 链接和未完成准备恢复继续可用。跨来源和多工作台版本日程有明确错误。
- **AC07：**旧准备／研究输入、报告响应及导出的黄金样本规范字节／哈希保持不变。复制依赖缺失／损坏仍明确报错。新结果标明实际工作台来源及已确认研究假设。
- **AC08：**包含两种既有准备格式／幂等回执的夹具升级后，其字节不变；不兼容存储事务式失败。新命令严格互斥，OpenAPI／生成契约一致，本地 Origin 防护有效。

## PRU10. 验证、命令与约定

实施验证及其限制记录在 `../../verification/2026-10-19-plan-reuse-unification.zh-CN.md`。使用确定性离线夹具，不需要真实 AI、Tushare 调用、真实计划审核或生产数据库修改即可验收。

新增聚焦测试放在 `tests/unit/test_workbench_selection_context.py`、`tests/integration/test_workbench_plan_selection.py`、`web/tests/unit/WorkbenchPlanReuse.spec.ts` 和 `web/tests/unit/WorkbenchReplayContext.spec.ts`、`web/tests/e2e/backtests.spec.ts`。循环产物／API 及准备链测试的边界发生变化时，在原测试中补充。遵循 Python 3.14、严格冻结 Pydantic 值及既有错误／幂等风格；前端使用 Vue Composition API、`<script setup lang="ts">`、明确 props／events 及当前 API 校验器。分支逻辑放在适配边界，不进入规则评估。

实施完成后，从 `trade-plan-monitor/` 运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/integration/test_workbench_plan_selection.py tests/integration/test_single_plan_library.py tests/integration/test_unified_replay.py tests/integration/test_backtest_result_api.py -q -m "not live"
.venv/Scripts/python.exe -m pytest tests -q -m "not live"
.venv/Scripts/python.exe -m ruff check --no-cache src tests
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts
```

始终保留现有交易及审计检查，使用已验证读取边界，中英文文档同步更新。若需增加另一张表／另一套存储、扩大日程支持，或改变既有引擎／契约含义，先重新讨论本设计。禁止复制实时库存到历史、弱化审核、伪造证据或改写冻结历史。实施审批前核对相关既有双语规格的一致性；已批准 API 增加／删除及当前快照哈希记录在 `../monitoring/SPEC-unified-plan.zh-CN.md` U27。

## PRU11. 已批准决策

推荐首期：同一选择／引用流程，工作台已审核单版本直接复用自动循环，已有准备链复用保持不变，不合并数据库。本有界提案没有未明确的业务需求。用户已于2026-10-19确认 PRU01 对统一范围的定义，以及 PRU04 单工作台版本／跨来源限制。若要求单一编写入口、单一物理仓库或跨来源连续执行，属于范围变化，不得静默吸收。
