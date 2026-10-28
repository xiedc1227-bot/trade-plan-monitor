# 实施计划与任务：plan-monitor-assurance

状态：实施中 — 2026-10-27。PMA-D01–D06及实施已批准，任务标记以实际证据为准。[英文规范版](plan-monitor-assurance.md) · [六项建议决策及模块地图](../docs/specifications/monitoring/SPEC-plan-monitor-assurance.zh-CN.md)。

## PMA-P01 — 授权、依赖与切片

用户已批准 PMA-D01–D06，明确授权持续实施至全部完成或必须由用户决定的阻断；真实提取共用48次尝试上限，已有授权无需重复确认，仍禁止迁移用户数据库。保留 `tasks/plan.md`、`tasks/todo.md`。调查基线为 `a5546ad`，T01记录未来实际起始版本，不覆盖历史证据。

先实现 `source-condition-coverage`，再做语料签收和当前就绪，最后联合验收。复用严格的原文／审核／运行权威。每片目标3–5文件；涉及多个独立接缝的父任务已明确顺序子片，每片最多5文件并单独验证，不一次扫改全部接缝。独立只读审核／语料准备可委派，共同契约／存储／授权修改仍顺序进行。

未来增量迁移开发／测试仅使用临时库。用户迁移、真实计划审核／启用、库存／成本确认、通知测试及live行情获取仍分别授权。真实提取须D05及明确实施指令，不能用合成替代关闭检查点。真值歧义、资源／版本／预算扩展及不可避免兼容变化需决定，不能静默放松验收。

## PMA-P02 — 验证命令与证据规则

从 `trade-plan-monitor/` 运行。下列新测试／脚本名是计划：先创建测试、观察独立预期失败，再实施。文件不存在、空选择、中断、跳过断言或规格已批准，都不是通过。后端目录分别进程运行以避开既有重名。需要socket的测试使用允许本地通信的环境及项目临时 `--basetemp`，不动真实存储。

| ID | 验证／完整命令 |
| --- | --- |
| PMA-V01 | 既有基线：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/unit/test_p3_policy_contract.py tests/unit/test_p3_codec.py tests/unit/test_preparation_prompt_budget.py -q --basetemp=.pytest_cache/pma-v01`；另跑 `.\.venv\Scripts\python.exe -m pytest tests/integration/test_p3_review.py tests/integration/test_p3_chain.py tests/integration/test_p3_notifications.py -q --basetemp=.pytest_cache/pma-v01-integration` |
| PMA-V02 | 新纯覆盖：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_source_obligations.py tests/unit/test_source_coverage.py tests/unit/test_source_coverage_semantics.py tests/unit/test_source_coverage_normalization.py tests/unit/test_source_coverage_context.py -q --basetemp=.pytest_cache/pma-v02` |
| PMA-V03 | 新授权／存储／HTTP：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_source_coverage_storage.py tests/integration/test_source_coverage_authority.py tests/integration/test_source_coverage_api.py tests/integration/test_source_coverage_compatibility.py tests/integration/test_source_coverage_actions.py -q --basetemp=.pytest_cache/pma-v03` |
| PMA-V04 | 语料／评分离线：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_acceptance_corpus.py tests/unit/test_extraction_acceptance_grading.py tests/integration/test_extraction_acceptance_runner.py -q --basetemp=.pytest_cache/pma-v04`；就绪：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_readiness.py tests/integration/test_plan_readiness_api.py tests/integration/test_plan_readiness_scenarios.py -q --basetemp=.pytest_cache/pma-v04-readiness` |
| PMA-V05 | 前端：`npm --prefix web run test -- --run tests/unit/SourceCoverageReview.spec.ts tests/unit/PlanReadiness.spec.ts tests/unit/PlanWorkbench.spec.ts tests/unit/ReviewedPlanDetails.spec.ts`；`npm --prefix web run type-check`；`npm --prefix web run build`；真实隔离Chrome：`npm --prefix web run test:e2e -- tests/e2e/source-coverage.spec.ts tests/e2e/plan-readiness.spec.ts tests/e2e/p3-capital.spec.ts tests/e2e/market-linkage.spec.ts` |
| PMA-V06 | 全量回归：`.\.venv\Scripts\python.exe -m pytest tests/unit -m "not live" -q --basetemp=.pytest_cache/pma-full-unit`；`.\.venv\Scripts\python.exe -m pytest tests/integration -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --basetemp=.pytest_cache/pma-full-integration`；`.\.venv\Scripts\python.exe -m pytest tests/contract tests/replay -m "not live" -q --basetemp=.pytest_cache/pma-full-contract`；`npm --prefix web run test -- --run` |
| PMA-V07 | 独立容量：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_backtest_acceptance.py -m "not live" -q --basetemp=.pytest_cache/pma-capacity`，不并发重型测试／构建／浏览器。保留120秒／证券、768MiB工作集增量、512MiB行情／WAL、192MiB结果／WAL及原堆／查询／导出限制。静态／契约：`.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check`；`.\.venv\Scripts\ruff.exe check src tests`；`git diff --check` |
| PMA-V08 | 文档／来源审核：双语章节ID／决策／API字段／枚举／阈值／链接，原提示词哈希／摘录、受保护任务、旧黄金样例差异、无秘密／原始敏感用户材料，原文→标准→实际证据，最终暂存／基线审查。文档审核不声称跑过测试 |
| PMA-V09 | 仅未来D05及实施获授权后真实提取：`.\.venv\Scripts\python.exe scripts/run_extraction_acceptance.py --manifest tests/fixtures/plan_assurance/manifest.json --evidence-dir .pytest_cache/pma-real-acceptance --version plan-extract-v12 --max-provider-attempts 48 --no-retries --allow-real-provider`。未来入口须共用整个验收活动调用账，48上限不能每条命令重置；候选版本使用实际冻结版本及同一账，不隐含新增调用 |
| PMA-V10 | 未来真实安装只读审计：`.\.venv\Scripts\python.exe scripts/audit_plan_readiness.py --database data/monitor.sqlite3 --read-only --output-dir .pytest_cache/pma-installation-audit`。仅数据库证据为PERSISTED_ONLY，不启动／迁移应用或调用供应商；缺当前owner权威是UNKNOWN/NOT_READY，不能猜PASS |

记录准确命令／版本／计数、原始失败及准确复验，真实供应商与安装结果和非live工程结果分开。终端空白需规范时保留原字节、可读副本及哈希清单，不为格式隐藏失败。

## PMA-P03 — 有序任务与检查点

### PMA-T01 — 固定反例、契约与基线

- [x] 交付并验证。
- 依赖：审核包获批及明确实施指令。
- 文件／范围：新增双语 `CONTRACT-plan-monitor-assurance` 附录、中立反例夹具与聚焦基线测试，最多4文件。冻结准确DTO／哈希归属、正向背景规则、可信历史切换、下个可用迁移及提示／传输基线。
- 验收：A01、A05、A06；验证：V01、V08。两种语言均复现145→146条款、128绑定不变、旧零问题；再证明新当前评估阻断，不声称已启用。

### PMA-T02 — 定义有界义务与证明模型

- [x] 交付并验证。
- 依赖：T01。
- 文件／范围：`ai/source_coverage_models.py`、`ai/source_obligations.py`、`tests/unit/test_source_obligations.py`，3文件。
- 验收：A02–A04；验证：聚焦V02。准确跨度／ID／关系、已知／未知范围、总4096／每条64及原512／2000边界，超限阻断不截断。

### PMA-T03 — 关闭背景标签及未命中关键词放行

- [x] 交付并验证。
- 依赖：T02。
- 文件／范围：`ai/source_coverage.py`、`ai/source_resolution.py`正向处理接缝、`test_source_coverage.py`、`test_source_coverage_context.py`，4文件。
- 验收：A01、A03；验证：聚焦V02。三种背景角色、非空理由及无关键词条件均阻断，除非准确跨度有合法正向非政策处理；保留真实背景，不编交易。

### PMA-C01 — 义务与背景检查点

- [x] V01、V02、V08适用阶段检查通过，A01/A03/A04有真实证据。不能仅建模型就开放当前／冻结授权。

### PMA-T04 — 比较完整谓词及关系语义

- [x] 交付并验证。
- 依赖：T03。
- 文件／范围：聚焦语义比较器、注册等价适配、`test_source_coverage_semantics.py`及最多2个辅助／测试文件。
- 验收：A02、A04；验证：聚焦V02。同句遗漏前提、AND/OR、否定／例外、比较符／单位、周期／offset、日期、数量、权限及机会变异须独立于既有绑定检出。

### PMA-T05 — 审计规范化及准确混合来源处理

- [x] 交付并验证。
- 依赖：T04。
- 文件／范围：聚焦规范化轨迹适配、原规范化／排除接缝、`test_source_coverage_normalization.py`及混合来源回归，最多5文件。
- 验收：A03、A04；验证：V02及既有来源处理测试。记录前后变化、防仅观察清空、保留原码点、登记基本面排除／技术余段及受限补充／期限改定。

### PMA-T06 — 保留不完整候选及覆盖阻断

- [x] 交付并验证。
- 依赖：T05。
- 文件／范围：顺序T06a直接提取（3文件）、T06b compact传递（4）、T06c私有派生模型（2）、T06d确定性回放（2）、T06e更新结果证明（2）、T06f物化（4），逐片独立测试。原文作用域及实际引擎支持另做聚焦回归切片；公共持久化／授权仍属T07–T09。
- 验收：A01、A04、A05；验证：V01、V02。区分结构／篡改无效与有效不完整覆盖，保留原文／候选／映射，不把SUCCEEDED当可审核；固定v12字节或如实声明新提示版本。

### PMA-C02 — 提取覆盖检查点

- [x] 新纯覆盖及既有来源／提取回归通过，A01–A04覆盖；规范化不能隐藏强制遗漏。存储／启用仍待完成。

### PMA-T07 — 保存保证证明且不破坏历史

- [x] 交付并验证。
- 依赖：T06。
- 文件／范围：顺序T07a SQL元数据／迁移／注册及独立迁移测试（4文件）；T07b有界证明／存储及核心／缺表测试（4）；T07c不可变保护及故障注入（5）；T07d独立存储攻击（1）。逐片验证，仍禁止用户迁移。
- 验收：A05、A06；验证：聚焦V03。临时已填充旧库按历史验证重开，新证明历史／CAS／重试／备份准确，切换身份不可伪造，拒绝有损降级；不迁移用户库。

### PMA-T08 — 绑定保存、审核、启用与复用

- [x] 交付并验证。
- 依赖：T07。
- 文件／范围：顺序T08a保存／重读／首次确认／仓库防护及独立测试（5文件）；T08b未证实版本轨迹保留（2）；T08c HTTP绑定／投影／当前工作台reader（5）；T08d工作台新运行防护（2）；T08e worker私有传递（3）；T08f准备标记辅助存储（4）；T08g原子finish接入（4）；T08h1初始来源证明（4）、T08h2共享全来源分析（3）、T08h3准确变更／前置证明（5）、T08h4独立攻击（2）、T08h5继承范围／注册操作按独立验证子片实施（每片最多4）、T08h6聚合归属（3）、T08h7共享AI／人工语义分析（3）；T08i1事务内当前reader／审核防护（3）、T08i2不可变审核回执存储（3）、T08i3原子当前审核绑定（4），再做T08i4人工操作／来源重评、T08i5继承／组合血缘及T08i6新复用／运行防护。剩余子片各最多5文件并独立验证。原历史codec及冻结输入不变。
- 验收：A05、A06；验证：聚焦V03及当前计划API测试。不完整DRAFT可保存，旧哈希有效，新证明缺失／过期／阻断不可确认／启用，客户端不可自选legacy。

### PMA-T09 — 将覆盖接入当前操作与交付

- [x] 交付并验证。
- 依赖：T08。
- 文件／范围：顺序T09a操作来源reader、普通模拟、runtime生成／输入帧、私有冻结loop及研究适配器，分别测试的子片各不超过5文件；T09b1预览／决定／消费及真实replay调用方（5），T09b2拒绝清理测试（1），T09b3真实P3来源／审核夹具（2），T09b4冻结worker准备／调用方（1）；实际读取及消费者绑定修复独立分片，各不超过5文件。T09c1发送时防护（4）、T09c2 outbox读取（2）、T09c3私有冻结捕获（5）、T09d完整逐字分钟句式（4）及真实当前／合成正例测试对账（2）分别验证。完整相邻组合回归记于PMA-R30。
- 验收：A05、A06；验证：聚焦V03及P1/P2/P3操作／竞争／通知测试。适用准确覆盖在既有写防护内重验，过期／竞争／重试／回滚只有一个结果；BUY专属遗漏不否决独立技术风险SELL，不产生新机会／窗口／数量。

### PMA-C03 — 持久授权检查点

- [x] 本阶段适用V01–V03来源／存储／授权／操作／发送时选择通过，A01–A06对应历史／当前分离、原子防护和风险连续性已证明（PMA-R30）；不存在API／界面专属授权旁路。新增覆盖资源／界面工作流检查仍属T10–T12／C04。

### PMA-T10 — 提供覆盖资源与准确审核绑定

- [ ] 交付并验证。
- 依赖：T09。
- 文件／范围：顺序T10a1 DTO／读取组合／GET／service／HTTP测试（5）；T10a2同一fresh record的计划列表／详情／保存／工作台摘要及精确ACTIVE DTO处理（3）；T10a3实际提取摘要与聚焦测试（最多4）。既有准确审核命令字段／防护不变。随后T10b两套OpenAPI和TypeScript及投影测试（5）；T10c双语API归属附录及兼容测试（最多4）；T10d0可选逐请求原始字节响应上限及传输测试（2）；T10d1共享typed覆盖解码／读取client、准确适配已有计划解码及聚焦测试（3）；T10d2准确适配已有提取解码及聚焦测试（2）。每子片独立测试、提交后才编辑下一个共享归属。保留默认4MiB传输上限，新资源在JSON解析前执行更严格1MiB原始线上字节上限。已有响应封闭字段名单仅加入已批准增量，历史缺省字段保持兼容。
- 验收：A05、A06、A10；验证：聚焦V03、V07。准确原文分页、读取无写入、409/422／完整性错误、字面false授权，只移除已批准新增后原投影保持。

### PMA-T11 — 展示原文到规则覆盖及阻断修复

- [ ] 交付并验证。
- 依赖：T10。
- 文件／范围：覆盖组件、聚焦composable、计划工作台适配及 `SourceCoverageReview.spec.ts`／工作台回归，5文件。
- 验收：A01、A03、A11；验证：V05单元／类型／构建。原文跨度、部分条件、AI与服务端处理、人工改定及无通用豁免均明确；上下文过期丢响应，不默认确认阻断。

### PMA-T12 — 关闭历史／legacy回归边界

- [ ] 交付并验证。
- 依赖：T11。
- 文件／范围：`test_source_coverage_compatibility.py`、聚焦历史／哈希／输入测试及有依据的适配修复，3–5文件。
- 验收：A05、A06；验证：V03及历史codec／回放。准确legacy读取和冻结字节保持，legacy不授新覆盖，新来源保存／读取／复用不可降级政策或重开消耗信号。

### PMA-C04 — 已审核来源工作流检查点

- [ ] 覆盖界面／API／当前防护及历史回归通过，A01–A06与适用A10/A11覆盖。真实供应商和就绪验收仍待完成。

### PMA-T13 — 冻结语料、来源分类与独立真值

- [ ] 交付并验证。
- 依赖：T01；本次选定顺序在C04后执行。
- 文件／范围：来源包、真值包、清单、`test_extraction_acceptance_corpus.py`，4文件；原文脱敏资产需要时再拆已审核3–5文件子片。
- 验收：A07、A08；验证：V04、V08。12例、原始／自然语言最低数量、准确哈希、正向／阻断预期及独立原子／关系真值，在看响应前固定；意图争议先解决再调用。

### PMA-T14 — 实现独立评分及离线重放

- [ ] 交付并验证。
- 依赖：T13。
- 文件／范围：有界评分模块／入口、`test_extraction_acceptance_grading.py`、`test_extraction_acceptance_runner.py`及中立预期分数夹具，最多5文件。
- 验收：A01、A02、A07、A08；验证：V04。刻意遗漏／编造／逻辑改变不能PASS，正确阻断与误阻断分开，原始／回放／人工修正结果不能混淆。

### PMA-T15 — 执行有界真实提取验收

- [ ] 交付并验证。
- 依赖：T14、C04，以及D05／实施授权和冻结无歧义真值。
- 文件／范围：T15a显式runner／共用调用账／离线防护测试3–5文件，T15b不可变脱敏活动证据，T15c双语真实验收报告及证据索引3文件；不写真实计划。
- 验收：A07、A08；验证：V04、V09、V08。v12的24个计划结果；提示改变再做实际新版本24个结果，总物理尝试最多48。无自动重试、不替失败，完整签收或明确未关闭失败；不能暗扩预算／限制或拿离线替代。

### PMA-C05 — 真实提取检查点

- [ ] 冻结矩阵已评分，准确部署版本所需真实运行通过，基线失败另保留；A07/A08完成。缺授权／证据保持待完成，不走捷径。

### PMA-T16 — 定义就绪状态与依赖聚合

- [ ] 交付并验证。
- 依赖：C04；本次选定顺序在C05后执行。
- 文件／范围：`web/plan_readiness_models.py`、纯依赖／摘要辅助及 `test_plan_readiness.py`，3文件。
- 验收：A09、A10；验证：聚焦V04。六轴、摘要优先级、纯提醒／金额口径N/A、FALSE与缺输入／首次／正常收盘等待、执行状态分离均准确。

### PMA-T17 — 通过只读权威投影当前就绪

- [ ] 交付并验证。
- 依赖：T16。
- 文件／范围：T17a service／GET／router及 `test_plan_readiness_api.py`最多5；T17b两套生成配置及投影测试5；T17c双语API归属及契约回归最多4。
- 验收：A05、A09、A10；验证：V04、V07。同一当前generation／启用／target／新鲜度，零供应商／业务写入／心跳，升级／缓存／未知明确，不产生READY令牌，不借当前账或研究值补齐。

### PMA-T18 — 展示逐规则就绪与通知真相

- [ ] 交付并验证。
- 依赖：T17。
- 文件／范围：就绪组件／composable、工作台适配、`PlanReadiness.spec.ts`及既有详情聚焦回归，5文件。
- 验收：A09–A11；验证：V05单元／类型／构建。六轴、真实范围、收盘等待、首次、过期／未知、队列／重试／送达区别及来源链接；不一键修复／启用。

### PMA-C06 — 就绪投影检查点

- [ ] V04／V05／V07聚焦检查覆盖A09/A10及适用A11，读取不补采、不授权；这不表示用户实际安装已就绪。

### PMA-T19 — 证明就绪边界及风险独立

- [ ] 交付并验证。
- 依赖：T18。
- 文件／范围：`test_plan_readiness_scenarios.py`、纯摘要测试、适用当前通知／风险回归及有据修复，3–5文件。
- 验收：A05、A06、A09、A10；验证：V04及既有读取所有权、官方收盘、P3风险测试。覆盖全部MRD-S07、迟到响应／上下文竞争、只读副作用及报价／预算变化不产生新机会。

### PMA-T20 — 只读审计实际安装

- [ ] 交付并验证。
- 依赖：T19。
- 文件／范围：显式 `scripts/audit_plan_readiness.py`、离线审计测试、双语安装报告，4文件。
- 验收：A09、A10；验证：V10、V08。附时间记录实际schema／计划／范围／审核／启用／运行／评估／渠道事实，前提缺失保持NOT_READY；不启动／迁移／启用／发送／补采制造成功。缺少真实正向就绪时，明确它是未满足的运行结果，不能用工程PASS冒充。

### PMA-T21 — 验收完整浏览器流程

- [ ] 交付并验证。
- 依赖：T15、T20。
- 文件／范围：`source-coverage.spec.ts`、`plan-readiness.spec.ts`、隔离夹具服务及有界截图／证据资产，3–5源码文件。
- 验收：A01、A05、A09–A11；验证：V05。复现强制条款误标并阻断、合法修复并重审、旧证明拒绝、健康FALSE／收盘等待／缺数、独立风险、通知真相、重载和320/768/1024/1440／可访问性；单独获批提取活动外零外部请求。

### PMA-C07 — 联合目的检查点

- [ ] A01–A11各有对应真实证据，区分原文完整性、真实提取结果、安装诊断；截图或ACTIVE标签不能替代缺失轴。

### PMA-T22 — 完成非live回归与容量

- [ ] 交付并验证。
- 依赖：T21。
- 文件／范围：有据失败按根因拆最多5文件修复，更新双语验收报告。
- 验收：A12；验证：V06、V07。对账原始失败／准确复验、排除及重叠计数，容量单跑；不改旧黄金、不削弱断言、不加skip、不提高门槛来通过。

### PMA-T23 — 更新双语操作与能力文档

- [ ] 交付并验证。
- 依赖：T22。
- 文件／范围：T23a操作／报告对4文件，T23b README／文档索引对4文件，T23c能力地图对2文件；阶段状态及链接准确。
- 验收：A03、A07–A12；验证：V08。说明遗漏阻断、允许的人工改动、实际验收提取版本、有限语料局限、legacy及安装NOT_READY原因，不宣称交付排除能力。

### PMA-T24 — 全标准审核并准备本地交付

- [ ] 交付并验证。
- 依赖：T23。
- 文件／范围：T24a报告／任务对4文件，T24b规格／契约对分成每片最多4文件，T24c限定Git审核及中文Conventional Commits，默认不推送／部署。
- 验收：A01–A12；验证：V07、V08及准确真实运行／安装证据对账。仅关闭真实完成检查，保留原文和受保护任务，提交不带敏感或临时数据库。

### PMA-C08 — 最终验收

- [ ] 24项任务、八个检查点及A01–A12均有必需证据。工程、准确版本语料、实际安装分别报告；按D06真实安装可如实NOT_READY，但缺所需真实提取验收不能标完成。

## PMA-P04 — 风险与审核边界

| 风险 | 必需措施 |
| --- | --- |
| 扩大背景黑名单仍漏同义／隐含前提 | 窄正向处理、默认未决及独立义务／关系判据 |
| 收紧旧验证器破坏已保存审核 | 历史版本分派／当前附属证明，准确已填充旧库测试 |
| 安全误阻断导致提取不可用 | 代表性正向语料、明确误阻断指标、合法受支持修复，不设通用遗漏豁免 |
| 有限验收被当普遍准确率 | 冻结独立真值、来源分类分母、自动／辅助分开及版本限定结论 |
| 完整计划超过当前提示／输出资源 | 保留原限制失败，请求具体资源／版本决定，不截原文或改用例标签 |
| ACTIVE／缓存／队列或无关成本被推为READY | 逐依赖六轴、当前目标／所有者绑定及只读副作用测试 |
| “验收”暗扩外发预算或用户写入 | 共用物理调用账、明确D05，迁移／启用／测试消息独立授权 |

这是供审核的实施提案，不是已执行工作；写出复选框不代表任务完成。
