# 实施计划与任务：market-linkage-p0

状态：APPROVED — 用户于2026-10-24批准六项决策及规格，并明确授权按任务清单实施。实施进度按验收记录；未完成任务不代表已交付。
以下进度绑定中英文验收报告，原验收要求保持不变。
[英文正式版](market-linkage-p0.md) · [规格审核包](../docs/specifications/monitoring/SPEC-market-linkage-p0.zh-CN.md)。

当前进度：MLP-T01–MLP-T19及MLP-C01–MLP-C07全部完成并通过本地验收。全量回归发现的失败均已解决并重测；见[验收记录](../docs/verification/2026-10-24-market-linkage-p0.zh-CN.md)。

## MLP-P01 — 授权与实施方法

本专题任务清单保留既有任务记录。用户于2026-10-24批准六项决策，并明确授权实施和分阶段验收。

实施遵循MLP-D01–MLP-D06及六份获批规格。变更前已检查基线c7378a4与适用AGENTS.md，保留其他工作。

复用指数基础设施和单一共用决策路径。先交付严格契约，再交付纯政策、提取／审核、持久权限、生产运行时、回放和用户流程验证。每项行为先写测试，预期值独立计算。每项任务目标3–5个文件；准确文件盘点超出时，先拆成顺序子任务再编辑。共用领域／生命周期／API文件按顺序负责；本计划不授权并行代理工作。

## MLP-P02 — 命令目录

后端命令均从 `trade-plan-monitor/` 运行。以下测试文件已实现，实际命令与结果见验收报告。

| ID | 命令／验证 |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_regime.py tests/unit/test_market_index_data.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_relative_strength.py -q` |
| V04 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_confirmation_selection.py -q` |
| V05 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py -q` |
| V06 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py -q` |
| V07 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_storage.py -q` |
| V08 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_runtime.py tests/integration/test_unified_simulation_transactions.py -q` |
| V09 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py -q` |
| V10 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_api.py -q` |
| V11 | `npm --prefix web run test -- --run tests/unit/marketLinkage.spec.ts` 以及 `npm --prefix web run type-check` |
| V12 | `npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts` |
| V13 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q` 以及 `.\.venv\Scripts\python.exe -m ruff check src tests` |
| V14 | `npm --prefix web run test -- --run`、`npm --prefix web run type-check`、`npm --prefix web run build` |
| V15 | 检查双语章节／验收／任务ID、数字阈值、枚举、API路径、命令、相对链接及语义一致性；审查范围内Git差异。 |

使用现有本地环境，不为文档检查安装依赖。浏览器场景使用本地样例。生产供应商调用、用户数据库升级、推送与部署各需相应授权；本清单不授予这些权限。

## MLP-P03 — 顺序实施任务

### MLP-T01 — 固定边界契约

- [x] 盘点新联动格式的全部读写端、准确字段形状、序列化器、哈希、有界展开条件、审核证据及生成API变体。在代码前将版本／回退矩阵写入双语规格。
- 依赖：用户批准及实施指令。验收：MLP-D01–MLP-D06、WF-A02；没有未解决的序列化或权限歧义。
- 文件／规模：本审核包，必要时新增双语契约附录；仅文档，S。
- 验证：V15；对照实际代码确认盘点，不依赖记忆中的架构。

### MLP-T02 — 增加明确联动计划模型

- [x] 增加严格的新联动／固定变体、派生参考身份和展开政策校验，以及供路径与数量共用的纯数量可行性预检。拒绝数量形式混用、缺来源参数及五分钟联动确认，保留现有编解码器。
- 依赖：MLP-T01。验收：QP-A01、CS-A05、WF-A02。
- 文件／规模：新增 `domain/market_linkage_models.py`、草稿／分派接点、新增 `tests/unit/test_market_linkage_contract.py`；M。
- 验证：V01，加旧Schema 1–5黄金样例往返和不支持读取端的明确拒绝。

### MLP-T03 — 增加带日期的指数低点证据

- [x] 扩展带版本指数事实，增加此前20交易日最低值及精确日期要求，保留旧事实字节。复用均线／回看与板块映射。
- 依赖：MLP-T02。验收：MR-A01、MR-A02、MR-A04。
- 文件／规模：`market_index/models.py`、`formulas.py`、`canonical.py`、针对性指数测试；M。
- 验证：V02；独立序列捕捉错误包含D、窗口偏移一日和未来修订。

### MLP-T04 — 实现四类状态政策

- [x] 增加纯优先级分类器，输出精确操作数及各谓词未知状态；有来源的大盘状态不影响非联动计划。
- 依赖：MLP-T03。验收：MR-A02、MR-A03、MR-A04。
- 文件／规模：新增 `decision/market_regime.py`、证据模型、`tests/unit/test_market_regime.py`；M。
- 验证：V02；每个严格相等边界和更高状态歧义均有明确预期。

### MLP-T05 — 实现对齐的相对强势

- [x] 增加5／20交易日个股／指数收益比较及当日MA20条件，固定端点、复权基准并输出三值证据。
- 依赖：MLP-T04。验收：RS-A01–RS-A04。
- 文件／规模：新增 `decision/relative_strength.py`、证据适配器、`tests/unit/test_relative_strength.py`；M。
- 验证：V03；包含停牌缺口、混合基准、精确相等和未来数据变异。

### MLP-T06 — 选择S0／S1／S2路径

- [x] 组合精确条件和六行路径表；保留S0含义、各自当日MA20、仅必要的强弱依赖及两类持续P1阻断。
- 依赖：MLP-T05。验收：CS-A01、CS-A02、CS-A03、CS-A05。
- 文件／规模：新增 `decision/confirmation_selection.py`、条件组合接点、`tests/unit/test_confirmation_selection.py`；M。
- 验证：V04；S1／S2每项独立失败，覆盖六条路径。

### MLP-T07 — 计算有边界数量

- [x] 实现有来源Q0、精确系数、合法向下取整和整笔额度阻断；返回计算证据，不生成零股动作。
- 依赖：MLP-T06。验收：QP-A01、QP-A02、QP-A03。
- 文件／规模：新增 `decision/quantity_policy.py`、联动模型接点、`tests/unit/test_quantity_policy.py`；M。
- 验证：V05；断言QP03全部示例，拒绝不兼容市场／模拟规则。

### MLP-T08 — 提取完整政策

- [x] 扩展当前AI候选／提示词边界，保留联动定义与来源证据；服务端派生指数身份，拒绝不支持形式，不虚构批准。
- 依赖：MLP-T07。验收：WF-A01、QP-A01、CS-A05。
- 文件／规模：`ai/plan_extraction.py`、`ai/extraction.py`、候选模型接点、新提取／审核样例与测试；M。
- 验证：V06；确定性AI输出覆盖缺Q0／S0、遗漏指数条件、错误基准及假人工证据。

### MLP-T09 — 绑定审核与后续更新

- [x] 扩展审核／来源绑定及既有准备／更新处理，展示政策变化并使旧审核失效。完整表达的P1路径保持禁用；未解决策略含义阻止批准。
- 依赖：MLP-T08。验收：WF-A01、WF-A02、CS-A04。
- 文件／规模：`ai/daily_review.py`、当前更新／审核接点、`tests/integration/test_market_linkage_review.py`；M。
- 验证：V06；原文／内容／公式编辑、继承政策变化、删除限制均不能保留旧批准。

### MLP-T10 — 持久化不可变联动证据

- [x] 增加带版本的证据／信号存储及必要的增量迁移；保留旧字节／哈希、重启身份和回退可读性。
- 依赖：MLP-T09。验收：WF-A02、QP-A04。
- 文件／规模：状态仓储／模型接点、必要时的增量迁移、新增 `tests/integration/test_market_linkage_storage.py`；M。
- 验证：V07；临时SQLite重开、新旧共存和重复迁移测试；不使用用户数据库。

### MLP-T11 — 在生产流程获取双方证据

- [x] 将所需个股／指数事实接入真实自有运行时，包含共用请求、精确截止准入、恢复和启用栅栏。
- 依赖：MLP-T10。验收：MR-A05、RS-A04、WF-A03。
- 文件／规模：现有运行时／需求／供应商组合接点、新增 `tests/integration/test_market_linkage_runtime.py`；M。
- 验证：V08；证明真实组合、共享请求、缺D行为及启用变化后的拒绝。

### MLP-T12 — 约束固定信号和原子数量

- [x] 将路径／计算绑定到信号，保留独立事件／窗口，在事务中重新校验并仅消费完整固定数量。
- 依赖：MLP-T11。验收：CS-A04、CS-A05、QP-A04、QP-A05。
- 文件／规模：统一生命周期、模拟事务和信号仓储接点、运行时／事务测试；M。
- 验证：V08；并发、重启、来源修订、改善、重复命令和额度恢复不重复交易、不改量。

### MLP-T13 — 保护读取和提醒权限

- [x] 完成证明和发送资格纳入双方证据，展示过期／阻断原因，独立提醒保持不受影响。
- 依赖：MLP-T12。验收：MR-A05、WF-A03。
- 文件／规模：运行时证明、投影和出站资格接点、运行时测试；M。
- 验证：V08；发送前修订抑制过期建议，只读访问不采集数据、不修改业务。

### MLP-T14 — 准入冻结回放依赖

- [x] 扩展当前回放输入／预检，包含准确的联动个股／指数证据、日历、复权基准和可用时间截止。
- 依赖：MLP-T13。验收：RS-A04、WF-A02、WF-A05。
- 文件／规模：回测输入、指数数据和回放适配接点、新增 `tests/integration/test_market_linkage_replay.py`；M。
- 验证：V09；历史范围缺失时如实拒绝，旧冻结载荷／哈希保持一致。

### MLP-T15 — 发布可追溯回放结果

- [x] 通过既有结果发布记录选中路径、数量操作数、授权和零交易原因；证明与实时适配的政策一致性。
- 依赖：MLP-T14。验收：WF-A05、QP-A04。
- 文件／规模：回测报告／投影、发布和场景样例／测试；M。
- 验证：V09；六条路径、未来变异、取消及重启保留因果关系和原子发布。

### MLP-T16 — 提供正式类型化契约

- [x] 扩展既有请求／响应变体与运行投影，重新生成实际OpenAPI／TypeScript产物，验证服务端权限。
- 依赖：MLP-T15。验收：WF-A01、WF-A02、WF-A03。
- 文件／规模：API模式／服务接点、生成契约产物、新增 `tests/integration/test_market_linkage_api.py`；M。
- 验证：V10；拒绝不兼容版本、旧修订和客户端覆盖数量；路由留在现有操作族。

### MLP-T17 — 展示审核与判断解释

- [x] 在现有工作台增加联动政策审核和运行展示，包含数量、实际比较与准确阻断状态，只呈现服务端权威效果。
- 依赖：MLP-T16。验收：WF-A04。
- 文件／规模：`web/src/composables/usePlanWorkspace.ts`、现有计划视图／组件、新增 `web/tests/unit/marketLinkage.spec.ts`；M。
- 验证：V11；不可用／未知状态具备可读解释且没有未授权交易动作，普通流程不展示技术版本。

### MLP-T18 — 验证完整用户路径

- [x] 增加确定性浏览器路径及跨入口场景，从提取到明确启用和整笔模拟，另包含P1阻断与独立提醒示例。
- 依赖：MLP-T17。验收：WF-A04、WF-A05、QP-A05。
- 文件／规模：新增 `web/tests/e2e/market-linkage.spec.ts`、本地样例和针对性集成场景；M。
- 验证：V12及V08–V10；记录实际输出、控制台／网络错误与隔离断言。

### MLP-T19 — 同步文档和发布证据

- [x] 执行回归／构建门槛，审查差异和证据，更新双语提示词／能力／操作文档，编写包含真实限制的双语验证报告。
- 依赖：MLP-T18。验收：WF-A06及全部模块验收ID。
- 文件／规模：双语README提示词、能力地图、操作／报告及任务完成记录；必要时拆分为纯文档子任务，M。
- 验证：V13–V15和浏览器证据；未运行测试、未认证供应商范围不宣称通过。只对已实现且验收的路径更新不支持能力说明。

## MLP-P04 — 检查点与追踪

| 检查点 | 对应任务完成后 | 继续前所需结果 |
| --- | --- | --- |
| MLP-C01 | MLP-T01–MLP-T03 | 准确契约盘点及兼容／证据测试，无隐式升级 |
| MLP-C02 | MLP-T04–MLP-T06 | 状态、强弱和路径真值表分别通过 |
| MLP-C03 | MLP-T07–MLP-T09 | 正确数量及完整来源／审核绑定，无策略猜测 |
| MLP-C04 | MLP-T10–MLP-T12 | 持久真实运行时与原子整笔模拟通过 |
| MLP-C05 | MLP-T13–MLP-T15 | 读取／发送权限和冻结回放一致性通过 |
| MLP-C06 | MLP-T16–MLP-T18 | 正式API和真实浏览器路径通过 |
| MLP-C07 | MLP-T19 | 完整验收证据、双语一致及真实发布边界 |

检查点失败须在范围内修复，不能跳过断言或降低阈值。实施获授权后，常规检查点通过无需反复申请许可；范围／策略变更须修订规格。任务验收引用构成追踪表：MR → MLP-T03/T04/T11/T13；RS → MLP-T05/T11/T14；CS → MLP-T02/T06/T09/T12；QP → MLP-T02/T07/T08/T10/T12/T15/T18；WF → MLP-T01/T02/T08–MLP-T19。

## MLP-P05 — 审核交接

实施遵循MLP-D01–MLP-D06及六份获批规格。变更前已检查基线c7378a4与适用AGENTS.md，保留其他工作。

实现和本地验证记录在中英文报告中。勾选表示任务已有验收证据，不表示真实供应商认证或部署。
