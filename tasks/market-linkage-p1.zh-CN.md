# 实施计划与任务：market-linkage-p1

状态：APPROVED — 用户在 2026-10-24 批准[规格](../docs/specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md)、六项决策及有序实施和分阶段测试验收。进度绑定已执行验证。[规范英文版](market-linkage-p1.md)。

## MLP1-P01 — 授权、顺序与范围

用户已批准 MLP1-D01–MLP1-D06 并明确指示实施 P1。本专题计划沿用 `tasks/market-linkage-p0.md` 约定，保留无关的 `tasks/plan.md` 和 `tasks/todo.md`。审核基线为 `dbeff32`；实施开始时重新核对实际工作区和基线。

保留既有模块边界。两条例外沿同一生产权限链交付，共用资格／数量策略。不另建计划工作区，本计划不授权并行代理。决策及实施获批后，下面的有序任务无需反复请求用户确认。检查点失败时暂停其依赖工作，修复后继续；策略决策变化需要双语修订及用户审核。

每次行为变更前先写具有独立预期结果的失败测试，再实现并运行针对性测试。使用临时 SQLite 和确定性数据商。每个实现切片以 3–5 个文件为目标；实际清单超过 5 个文件时，先记录顺序子任务再修改。文件清单标明职责边界，不是重写整个子系统的许可。下列新路径为拟交付内容，并非今天已经存在／通过的测试。每个切片后应用保持可用；新路径在完整权限链就绪前保持不可用。

## MLP1-P02 — 验证命令目录

在 `trade-plan-monitor/` 使用已安装环境执行。各任务将建立新的例外测试文件。命令是后续验证要求，不是本轮文档工作的测试结果。

| ID | 命令／检查 |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py -q` |
| V04 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_review.py tests/integration/test_market_exception_updates.py tests/integration/test_market_linkage_review.py -q` |
| V05 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_storage.py -q` |
| V06 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_authorization.py tests/integration/test_market_exception_concurrency.py -q` |
| V07 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_runtime.py tests/integration/test_market_exception_simulation.py tests/integration/test_unified_simulation_transactions.py -q` |
| V08 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_api.py tests/integration/test_market_linkage_api.py -q` |
| V09 | `npm --prefix web run test -- --run tests/unit/marketExceptionReview.spec.ts tests/unit/marketExceptionRuntime.spec.ts` 和 `npm --prefix web run type-check` |
| V10 | `npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts tests/e2e/market-exceptions.spec.ts` |
| V11 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_replay.py tests/integration/test_market_exception_replay_mutations.py tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py -q` |
| V12 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q` |
| V13 | `npm --prefix web run test -- --run`、`npm --prefix web run type-check`、`npm --prefix web run build` |
| V14 | `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check`（两套 API 配置） |
| V15 | `.\.venv\Scripts\python.exe -m ruff check src tests` 和 `git diff --check` |
| V16 | 检查双语章节／决策／验收／任务 ID、数量约束、枚举、API 路径、命令、链接及语义等价；记录准确范围与结果。 |

某任务尚在建立一组命令中的其他测试时，可先执行相关文件子集；到检查点时运行整组。实施时使用 `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py` 生成契约，再验证 V14。本计划不授权安装依赖、修改用户数据库、调用真实数据商／AI／Webhook、推送或部署。

## MLP1-P03 — 有序实施任务

### MLP1-T01 — 冻结 P1 边界清单

- [x] 盘点计划／草稿／提取／更新／审核／状态／运行／通知／API／回放读写端，核对拟议版本和准确权限字段；在双语规格中记录新旧哈希及回退矩阵。
- 依赖：用户批准及实施指示。验收：数量／权限／版本无未决歧义；对应 MLP1-A01、MLP1-A05、MLP1-A14。
- 文件／范围：P1 规格双语版，必要时新增双语契约附录；S–M，仅文档。
- 验证：V01 基线及 V16；记录基线失败，不能隐藏。

### MLP1-T02 — 增加严格启用的计划契约

- [x] 增加 Schema 7 策略／路径分支、草稿分发和精确审核哈希；保留 Schema 1–6 往返及 Schema 6 `BLOCK_P1`；缺少标志不能授予许可。
- 依赖：MLP1-T01。验收：MLP1-A01；覆盖非法固定／策略混用、边界和不支持的读取行为。
- 文件／范围：`domain/market_exception_models.py`（新增）、编解码／草稿／哈希接点、`tests/unit/test_market_exception_contract.py`；M，必要时拆分分发接点。
- 验证：V02 及既有黄金样本；V01 继续通过。

### MLP1-T03 — 实现资格与数量策略

- [x] 扩展共用路径选择及纯数量校验，支持两条例外；区分候选资格和批准；保留全部普通路径，不隐式读取时钟／数据商。
- 依赖：MLP1-T02。验收：MLP1-A02–MLP1-A03、全部 MLP1-Q01–MLP1-Q12，以及精确／未知／不兼容网格边界。
- 文件／范围：`decision/confirmation_selection.py`、`decision/market_exception_policy.py`（新增）、共用数量接点、V03 两个新增单元测试文件；M。
- 验证：V03 及 V01；独立算术样本包括明显破坏路径合法数量高于和低于半数 Q0 的情况。

### MLP1-C01 — 契约与算术检查点

- [x] V01–V03 和 V16 通过；对应 MLP1-A01–MLP1-A03。两条路径可表达，但任何测试或生产适配器均不能推断批准。旧计划保持精确字节和行为。

### MLP1-T04 — 将提取和审核绑定到来源许可

- [x] 扩展提取／审核以包含完整路径语义、来源绑定和明确关闭状态；拒绝伪造批准、否定许可及缺失定义；不能推断明显破坏路径数量。
- 依赖：MLP1-C01。验收：MLP1-A04–MLP1-A05；中英文来源得到等价权限边界。
- 文件／范围：`ai/plan_extraction.py`、`ai/daily_review.py`、`ai/semantic_validation.py`、策略定义接点、`tests/integration/test_market_exception_review.py`；M。
- 验证：相关 V04 测试、错误／否定原文及既有审核回归。

### MLP1-T05 — 在更新与准备中保留许可

- [x] 完整更新、补丁、准备及继承均保留准确路径许可；许可变化要求重新审核；导入／复制计划不得复制单次批准。
- 依赖：MLP1-T04。验收：MLP1-A01、MLP1-A04；不退回固定规则或旧联动格式，不继承实时授权。
- 文件／范围：`ai/plan_update_extraction.py`、`ai/preparation_wire.py`、`ai/predecessor_patch.py`、更新审核接点、`tests/integration/test_market_exception_updates.py`；M。
- 验证：完整 V04；覆盖开启→关闭、关闭→开启、缺少字段、过时审核和复制计划。

### MLP1-T06 — 持久保存不可变候选及授权事件

- [x] 增加版本化候选／事件模型、唯一机会／命令约束、已验证哈希及持久投影；在临时数据库测试增量存储和回退；不改用户数据库。
- 依赖：MLP1-T02、MLP1-T03。验收：MLP1-A01、MLP1-A06–MLP1-A07；重启保留 PENDING 和终态历史，不产生新机会。
- 文件／范围：新增状态模型／仓库模块、既有仓库事务／迁移接点、`tests/integration/test_market_exception_storage.py`；M，必要时拆分迁移。
- 验证：V05、损坏／不支持版本测试及字节完全相同的旧状态样本。

### MLP1-C02 — 来源与持久状态检查点

- [x] V04–V05 和 V16 通过；对应 MLP1-A04–MLP1-A06 及 MLP1-A07 存储部分。所有授权仍须明确本地命令，原文、计划副本或启动均不能生成已批准事件。

### MLP1-T07 — 实现预览与精确批准命令

- [x] 建立服务端预览及批准／拒绝服务，绑定准确摘要／修订号、服务端接收时间、明确理由、完整数量检查及命令回执；首次批准时原子冻结数量。
- 依赖：MLP1-C02。验收：MLP1-A05–MLP1-A07；明显破坏数量为空不能批准；非法／过时预览及额度未知保持阻断。
- 文件／范围：新增例外应用服务、类型化命令模型、仓库接点、`tests/integration/test_market_exception_authorization.py`；M。
- 验证：相关 V06 测试；证明批准不改持仓，只接受已展示的准确数量。

### MLP1-T08 — 强制终态生命周期及并发命令

- [x] 实现撤销、到期和失效，不重新开启机会；用持久约束及原子修订保护重复命令和并发批准／撤销。
- 依赖：MLP1-T07。验收：MLP1-A06–MLP1-A08；覆盖节假日、迟到证据、倒填时间、数量变化及跨计划／路径复用。
- 文件／范围：例外服务／仓库、既有独立信号权限接点、`tests/integration/test_market_exception_concurrency.py`、V06 授权测试；M。
- 验证：完整 V06，使用真实临时 SQLite、事务失败注入及新进程重新打开；与执行的竞争在 MLP1-T10 补齐。

### MLP1-T09 — 接入既有运行及提醒权限

- [ ] 生产装配持久保存合格候选并只暴露当前权限；复用既有数据采集和截止时点；将读取／完成／发送检查及稳定提醒绑定到候选／批准状态。
- 依赖：MLP1-T08。验收：MLP1-A06、MLP1-A08；已用事实修订使权限失效，无害重新抓取不会；普通／五分钟路径仍独立。
- 文件／范围：`runtime/daily_service.py`、`state/market_linkage_authority.py`、完成／读取接点、outbox／发送接点、`tests/integration/test_market_exception_runtime.py`；M，必要时拆分适配接点。
- 验证：相关 V07 测试，使用实际生产装配、模拟数据商、过时提醒竞争及重启。

### MLP1-C03 — 单次机会授权检查点

- [ ] V05–V07 已涉及文件及 V16 通过；对应 MLP1-A05–MLP1-A08。两条路径具备持久批准及全部终态；运行／提醒不会变更持仓或自动批准。

### MLP1-T10 — 在整笔模拟执行时消费批准

- [ ] 将已批准冻结数量接入既有模拟，复核全部当前门槛，原子消费批准、信号及持仓；确定拒绝／撤销与执行的竞争顺序。
- 依赖：MLP1-C03。验收：MLP1-A07–MLP1-A09；额度恢复不改变数量，重复命令不重复成交，不延长窗口。
- 文件／范围：`state/simulation.py`、生命周期／权限接点、例外仓库、`tests/integration/test_market_exception_simulation.py`、V06 并发测试；M。
- 验证：完整 V06–V07；测试不同连接竞争、提交前后崩溃、相同／不同命令键及持仓隔离。

### MLP1-T11 — 暴露类型化 API 命令与运行视图

- [ ] 增加三个拟议命令族和 Schema 7 运行投影；保留既有保护／错误／幂等约定；拒绝客户端提供授权，如实暴露服务失败。
- 依赖：MLP1-T10。验收：MLP1-A05、MLP1-A10；准确路径、必要字段、状态码及普通投影符合已审核清单。
- 文件／范围：新增 `web/routers/plan_exceptions.py`、`web/routers/daily_plans.py`、服务／装配注册接点、`tests/integration/test_market_exception_api.py`；M。
- 验证：V08，覆盖跨来源、伪造身份、非法数量、存储不可用及批准／执行分离。

### MLP1-T12 — 生成并验证两套客户端契约

- [ ] 从服务端模型生成两份 OpenAPI 和两份 TypeScript 产物；比较旧投影及严格的新命令分支；不得手改生成类型隐藏服务端差异。
- 依赖：MLP1-T11。验收：MLP1-A01、MLP1-A10；记录精确快照哈希及兼容差异。
- 文件／范围：`openapi.json`、`openapi.runtime-status.json`、`web/src/api/generated.ts`、`web/src/api/generated-runtime-status.ts`、契约测试；M。
- 验证：V08、V14 及前端类型检查；如需修复生成器／模型，另记小切片。

### MLP1-C04 — 后端完整权限检查点

- [ ] V06–V08、V14–V16 通过；对应 MLP1-A05–MLP1-A10。完整本地服务流程批准准确数量，再单独消费一次；每个绕过／竞争场景均有否定断言。

### MLP1-T13 — 在审核中展示计划级路径许可

- [ ] 在既有计划审核中展示独立开启／关闭的路径、完整条件及不同数量规则；修改许可使审核失效；此界面不批准单次机会。
- 依赖：MLP1-C04。验收：MLP1-A04、MLP1-A10–MLP1-A11；用户文案清晰，绑定服务端来源，不增加技术版本选择器。
- 文件／范围：`web/src/components/plans/ExplicitPlanReviewPanel.vue`、`web/src/composables/usePlanWorkspace.ts`、专用例外审核组件／辅助函数、`web/tests/unit/marketExceptionReview.spec.ts`；M。
- 验证：相关 V09 测试及类型检查；来源遗漏和关闭路径仍然可见。

### MLP1-T14 — 构建单次批准与撤销交互

- [ ] 展示资格／证据、只读走弱数量、初始为空的明显破坏数量、理由及精确预览；支持批准／拒绝／撤销和独立模拟操作，覆盖终态／过时／错误状态。
- 依赖：MLP1-T13。验收：MLP1-A05–MLP1-A06、MLP1-A10–MLP1-A11；不自动提交／调整数量，重试复用命令身份，Vue 不重算服务端判断。
- 文件／范围：新增例外运行组件／composable、既有工作区接入、`web/tests/unit/marketExceptionRuntime.spec.ts`；M。
- 验证：完整 V09；键盘／焦点行为、请求中重复点击、额度变化、到期及服务不可用。

### MLP1-T15 — 验证两条浏览器流程

- [ ] 对两条路径测试原文→审核→启用→合格候选→预览→批准→独立整笔模拟；另覆盖拒绝／撤销、过时预览、重试／重启、缺失证据及旧普通路径。
- 依赖：MLP1-T14。验收：MLP1-A11；使用实际本地服务／API、合成数据及健康事件流，不只在浏览器伪造权限。
- 文件／范围：`web/tests/e2e/market-exceptions.spec.ts`、本地后端测试装置，必要时涉及既有 `market-linkage.spec.ts`；M。
- 验证：V10；保留有用截图／日志，检查数量／证据展示，证明批准本身不改持仓。

### MLP1-C05 — 用户流程检查点

- [ ] V09–V10 和 V13 通过；对应 MLP1-A10–MLP1-A11。两条例外及终态／错误路径在真实浏览器通过，旧计划和独立提醒继续正常。

### MLP1-T16 — 在研究输入中冻结授权事件

- [ ] 增加版本化研究输入及完整性校验的事件流，区分真实记录与假设来源；保留旧运行，强制截止时点／身份准入，工作进程不能访问当前本地批准。
- 依赖：MLP1-T10、MLP1-T12。验收：MLP1-A01、MLP1-A12；无事件即无例外授权，未来事件不能提前使用。
- 文件／范围：`backtest/run_input.py`、`backtest/loop_dataset.py`、序列化／准入接点、`tests/integration/test_market_exception_replay.py`；M。
- 验证：相关 V11 测试及旧研究黄金样本；损坏、不支持事件类型、错误计划和缺少历史日历／规则范围均明确拒绝。

### MLP1-T17 — 回放共用授权及执行生命周期

- [ ] 按确定时间顺序将冻结事件送入共用策略；批准不单独成交，仍需操作脚本、原始窗口和完整执行门槛；结果标明研究假设。
- 依赖：MLP1-T16。验收：MLP1-A09、MLP1-A12；相同输入的运行／回放等价，空事件为零例外交易。
- 文件／范围：`backtest/runner.py`、`backtest/loop_runner.py`、计划调度／结果投影接点、V11 回放测试；M。
- 验证：相关 V11 测试，覆盖两条路径、拒绝／撤销／迟到事件及本地／回测持仓隔离。

### MLP1-T18 — 证明回放因果性与更新兼容

- [ ] 增加未来批准／撤销、修订价格／基准、更新计划、数量变化及重复事件的变异测试；检查两种回放入口、准备／更新和结果来源。
- 依赖：MLP1-T17。验收：MLP1-A04、MLP1-A08、MLP1-A12；无事后授权、静默策略降级或实时授权导出。
- 文件／范围：`tests/integration/test_market_exception_replay_mutations.py`、V11 回放／等价测试及相关更新／结果样本；M。
- 验证：完整 V11；未来变异后，截止时点前输出保持相等，受影响的后续判断正确变化。

### MLP1-C06 — 冻结回放检查点

- [ ] V11 和 V14–V16 通过；对应 MLP1-A01、MLP1-A04、MLP1-A08–MLP1-A09、MLP1-A12。如实报告缺失或假设授权，所有运行／回放比较使用冻结输入。

### MLP1-T19 — 完成后端回归与失败修复

- [ ] 运行全部非 live 后端测试和质量检查；不削减覆盖／断言地修复失败并复测受影响范围；在双语验收报告保留命令、数量、耗时、跳过项及局限。
- 依赖：MLP1-C05、MLP1-C06。验收：MLP1-A13 及全部后端验收 ID；任何未解决失败都不能描述为完成。
- 文件／范围：带实际日期的双语 `docs/verification/*-market-linkage-p1.md` 报告及限定证据；修复另记为 3–5 文件切片。
- 验证：V12 和 V15；区分既有／环境失败及真正未执行的检查。

### MLP1-T20 — 完成前端与生成契约验收

- [ ] 运行全量前端测试、类型检查、生产构建、浏览器流程和生成检查；检查最终界面、原有路径和错误处理；将准确结果追加到两份验收报告。
- 依赖：MLP1-T19。验收：MLP1-A10–MLP1-A11、MLP1-A13；无过时生成产物，不把仅浏览器通过当作全链路通过。
- 文件／范围：双语验收报告及限定浏览器证据；必要修复使用小型顺序切片。
- 验证：V10、V13–V15；修复后复测受影响范围，不因仅修改文档就重复测试。

### MLP1-T21 — 整理文档与最终验收

- [ ] 顺序完成文档子步骤：T21a，双语 P1 操作指南及 README 能力／提示词；T21b，双语能力图及文档索引；T21c，双语 P1 规格及任务状态；T21d，双语最终验收报告及限定差异复查。每步最多修改 4 份文档。
- 依赖：MLP1-T20。验收：MLP1-A14；全部 MLP1-A01–MLP1-A14 链接到实际证据；验收前不能把拟议能力描述为已交付。
- 文件／范围：上述双语文档；四个顺序 S–M 文档切片。保留 P0 历史及无关工作。
- 验证：V16 和 `git diff --check`；确认未弱化依赖／阈值，未误入用户数据或秘密。不推断已授权推送、部署或用户数据库迁移。

### MLP1-C07 — P1 完成检查点

- [ ] MLP1-T01–MLP1-T21 和全部十四项验收均有通过、双语、可追溯的证据；两条路径、数量示例、批准生命周期、完整模拟和冻结回放均通过。剩余真实服务认证限制单列。此时才能报告实施全部完成。

## MLP1-P04 — 验收追溯

| 验收 ID | 负责的任务 | 检查点 |
| --- | --- | --- |
| MLP1-A01–MLP1-A03 | MLP1-T01–MLP1-T03；MLP1-T12 和 MLP1-T16 再检查兼容 | MLP1-C01、MLP1-C04、MLP1-C06 |
| MLP1-A04 | MLP1-T04–MLP1-T05、MLP1-T13、MLP1-T18 | MLP1-C02、MLP1-C05、MLP1-C06 |
| MLP1-A05–MLP1-A08 | MLP1-T06–MLP1-T10、MLP1-T14、MLP1-T18 | MLP1-C02–MLP1-C04、MLP1-C06 |
| MLP1-A09 | MLP1-T10、MLP1-T17 | MLP1-C04、MLP1-C06 |
| MLP1-A10–MLP1-A11 | MLP1-T11–MLP1-T15、MLP1-T20 | MLP1-C04–MLP1-C05、MLP1-C07 |
| MLP1-A12 | MLP1-T16–MLP1-T18 | MLP1-C06 |
| MLP1-A13–MLP1-A14 | MLP1-T19–MLP1-T21 | MLP1-C07 |

## MLP1-P05 — 风险与审核条件

| 风险 | 防护／证据 |
| --- | --- |
| “最低量例外”变成一般向上取整 | 仅限官方最低量，普通／例外分开，不兼容最低量及超 Q0 否定样本 |
| 明显破坏数量被默认减半或取满 | 初始空值，明确合法数量及精确预览；MLP1-D03 需审核 |
| 计划审核或技术事实被当成批准 | 区分计划许可和单次事件，严格导入／API 边界，浏览器和服务绕过测试 |
| 再次批准或复制计划绕过独立信号限制 | 稳定机会连续性、终态、跨版本和并发测试 |
| 证据修订或过时提醒暴露失效权限 | 绑定实际使用证据，读取／发送／执行防护，回执变化连续性测试 |
| 历史评估假定人工同意 | 冻结事件，缺少事件零成交，明确研究来源及未来变异测试 |
| 广泛契约变化损坏旧计划 | 新显式版本、精确旧样本、不支持的读取拒绝及回退保留 |

MLP1-D01–MLP1-D06 已批准。已完成检查记录在双语[验收报告](../docs/verification/2026-10-24-market-linkage-p1.zh-CN.md)；未勾选任务仍未完成。
