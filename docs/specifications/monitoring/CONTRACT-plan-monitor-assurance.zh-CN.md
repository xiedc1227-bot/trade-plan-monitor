# 契约：plan-monitor-assurance

状态：实施契约 — 2026-10-27。[已批准总规格](SPEC-plan-monitor-assurance.zh-CN.md) · [英文规范版](CONTRACT-plan-monitor-assurance.md)。基线 `a5546ad`，不授权用户迁移、部署或推送。

## PMA-K01 — 历史边界与原文归属

保留Schema1–9计划字节、`daily-mapping-v1`、原文／内容／审核规范哈希、历史审核派生及冻结运行契约。`build_daily_review`仍是历史来源证据验证器。新增 `assess_source_coverage(draft, mapping, source, *, normalization=None, origin=...)` 独立检查整份原文，不从AI分类或旧零问题推断完整。新公开授权仅在C03/C04防护完成后开放。

在 `tests/fixtures/pma_counterexample.json` 固定追加条件反例：之前145条款／128绑定，之后146／128，候选不变且历史零问题。COMMENTARY/HISTORICAL/ACCOUNT均不能在新评估中解除它。历史结果不等于确认／启用权限。

## PMA-K02 — 当前模型与确定性证据

`source-obligation-v1`拥有准确规范 `clause_id`、`start/end`、`excerpt`（最多512码点）、服务端派生 `obligation_id`、`kind`、`scope`、`state`、有限语义、关系引用及准确绑定路径。kind为DECLARATION/PREDICATE/RELATION/CONTEXT/SCOPE_EXCLUSION/UNKNOWN，scope为PLAN/BUY/SELL/RISK/ALERT/UNKNOWN；state为MAPPED/MAPPED_WITH_REGISTERED_SUPPLEMENT/CONTEXT_VERIFIED/SCOPE_EXCLUDED/UNRESOLVED/UNSUPPORTED/CONFLICT。总义务最多4096、每规范条款64，保留映射条款512、绑定／补充2000及全部原字节／树边界。

服务端有限字段／自然条件语法、关系／等价及正向背景注册表使用 `source-coverage-rules-v1`。全部非标点跨度须有处理，未识别出原子不等于没有要求。显式路径／JSON原文声明与真实候选语义值比较，分块条款保留完整声明和关系，不允许“未命中关键词”或整段背景豁免。

`source-coverage-v1`拥有当前内容／原文／映射哈希、规范化证据哈希、规则版本、完整有序义务／问题及自校验 `evidence_hash`。COMPLETE/BLOCKED只是计算状态，不是人工授权。公开投影另区分LEGACY_UNASSESSED/UNKNOWN及审核绑定。义务／哈希输入不含运行报价／预算／获取标识或计算时间，评估不重开信号、不改数量。

新AI规范化证据绑定AI_NEW来源、准确前／后候选哈希、规范化版本及完整有界变化；缺前像不能认证自动忠实度。HUMAN/AI_HISTORICAL明确前像不存在，不虚构原始供应商记录。原文规范函数沿用既有归属，新哈希域不改写旧原像。

## PMA-K03 — 证明存储、切换与授权

在0027后预留 `0028_source_coverage`，创建前检查冲突。新增保证／回执表及可信切换记录，记录既有计划版本标识／哈希，不改旧payload／审核行。legacy只由服务端生成的不可变切换成员及匹配存储标识决定，不由请求版本／标记或客户端倒填时间决定。新记录缺证明为未知／阻断。有新保证／回执或切换后版本会丢失当前授权契约时拒绝降级，临时库验证原始安全降级。

`source-coverage-review-v1`不可变、服务端赋时，将覆盖证据／规则／来源／内容／映射绑定准确原审核ID／版本；确认在既有证券事务内核对预期版本和哈希。同意图同内容重放，内容／证明变化冲突。提取／保存／读取不产生已确认回执，保存保留有效不完整DRAFT。

可信历史解码与当前资格分开。缺保证表返回升级／未知，不建schema。新当前普通／例外授权及受影响可操作通知发送要求准确已绑定覆盖，仅保留SCC-S06已经授权、服务端可识别的独立历史技术风险窄例外；不授新普通／例外权限，也不贴当前覆盖通过标签。UNKNOWN范围在澄清前阻断全部新交易授权。实施测试不迁移用户数据库。

## PMA-K04 — 公开资源与错误

防护完成后仅新增PMA-S05两条GET：`/api/v1/plan-versions/{version_id}/source-coverage`、`/api/v1/plan-versions/{version_id}/monitor-readiness`，均返回字面 `authorityGranted=false`，不写入、不获取供应商、不更新心跳、不启用、不发送、不迁移。覆盖分页默认50／最多100、单页<=1MiB，游标绑定准确来源／内容／映射／规则／证据；分页前验证全证明，未返回行不能隐藏摘要阻断。

原审核命令增加 `coverageEvidenceHash`、`coverageRulesVersion`，当前证明缺失／过期／阻断返回结构化409。无效请求／跨度／哈希仍422，存储损坏用既有无秘密完整性错误。语义不完整但结构有效的提取保留原文／候选／映射／阻断，不抹为INVALID_OUTPUT。准确DTO／生成在T10前继续门控，保留两套API及批准历史投影。

## PMA-K05 — 真实验收与只读安装

`extraction-acceptance-v1`在看响应前固定12例独立原文／真值。v12有24个计划结果，仅指令／模板／输出schema契约变化才另做新版本24例；每例组装提示单独哈希，不因此改变模板版本。客户端真实供应商尝试共用48上限，发送前原子预占，无自动重试，崩溃／送达未知不退款。有界runner／账本及脱敏语料防护完成前不调用。用户已批准D05并明确实施，范围内不重复求许可。

`plan-monitor-readiness-v1`复用当前运行权威，显示六个按依赖的轴、实际范围、target、generation、新鲜度及交付证据；摘要优先级和独立交易资格遵循MRD-S03。仅数据库审计为PERSISTED_ONLY，不能证明当前owner权威。工程／有限语料／真实安装结论分开，不用合成响应或旧心跳冒充live验收。

## PMA-K06 — 已实施有限注册表与规范化表示

当前私有注册表完整消费 `path = JSON` 行，拒绝重复键、非有限／发生舍入的数值及尾随文字。标量声明只能证明自身路径；完整容器必须整体结构等值。候选来源绑定必须指向该准确路径独立证实的来源条款。ALL/ANY与子项保留原文拥有的关系组。未知原文含义及自由政策文字继续阻断；JSON文字相等不能证明名称、注释、费用标签或泛化人工事实内的条件已被监控。

正向背景仅限 `ai/source_context.py` 中的完整文法：准确注册标题、带日期的历史成交、明确零持仓陈述及与已校验候选准确一致的元数据声明。名称还必须符合完整有限标题文法。仅识别完整标记 `A. 执行计划`、`B. 背景说明`、`A. Executable plan`、`B. Background`，标记不豁免语义。只在B出现的新政策与A冲突；准确重复已证实的内容不新增权限。范围排除仅复用准确注册基本面片段，并保留每个技术／未知余项。

自由政策文字文法由 `ai/source_policy_text.py` 拥有。注册人工原子保留技术类别，仍要求后续独立绑定范围的人工证据，不创建已满足事实。明确合成短语仅支持确定性契约夹具，不能计为用户原始来源或真实供应商准确率。未注册名称／文字可能保守误阻断，必须在真实语料结果中保留。缺参补充绑定准确ID／内容／路径／值，不能覆盖明确非null值，不能将未支持条件填入未知文字。原有期限转换仅限完整注册期限句、准确单一规则及明确引用该句的匹配人工补充。

`source-normalization-candidate-v1`对完整前／后JSON对象计算哈希。每项变化使用规范 `{present:false}` 或 `{present:true,value:...}` 信封，区分缺失与null；列表整体变更。重建重新核对原文／前／后哈希、完整有序差异及不重叠准确路径。注册表示／默认值展开及显示变化可无损；可执行政策修复／删除明确报规范化损失。HUMAN/AI_HISTORICAL及含人工调整的义务均不能声称原始自动保真。

## PMA-K07 — 私有前项派生证据

现有更新协议可以只返回操作而没有完整草稿。在T06/T08范围内增加仅服务端使用的 `source-derivation-v1` 证据，不改供应商schema／提示词或历史哈希。区分FULL_DRAFT与PREDECESSOR_PATCH。保存准确准入原始JSON字节及SHA256；补丁证据还绑定完整规范context及其SHA256、准确 `base_hash`。context哈希仅证明身份，不证明当前审核／覆盖授权，T08必须另行重查可信前项及其当前绑定覆盖／回执。

`predecessor-materialization-v1`记录有序完整阶段输出及SHA256：DELTA_EXPANDED、SOURCE_NORMALIZED、MATERIALIZED。补丁证据允许该序列的非空前缀；完整草稿从SOURCE_NORMALIZED开始。重复、逆序或跳阶段无效。raw／context／单阶段各<=1MiB，最多8阶段，证据总<=8MiB，不提高现有供应商／准入上限。阶段／context JSON规范化，raw JSON保留原始空白。证据以 `daily_hash(version, payload_without_evidence_hash)` 自哈希，且 `authority_granted=false`。

使用准确context重放原始准入协议，确定性核对展开、恢复、范围调整及最终物化。服务端派生候选不是供应商原始完整草稿。缺原始补丁、重放无效或缺当前继承证明仍阻断；有效不完整候选保留可检查性。T08分别评估当前原文义务与继承义务，按稳定规则身份合并。这是已批准后续更新流程的证据记账，不新增交易权限、人工豁免或冻结回放输入字段。当前不完整提取、旧历史完整性及完整自动保真仍须分别陈述。


## PMA-K08 — 已实施不可变存储边界

迁移0028增加 `source_coverage_installation`、`source_coverage_cutover`、`source_coverage_input`、`source_coverage_assessment`、`source_coverage_review`。安装标记固定实际版本／来源哈希、原审核／启用身份及完整成员根，不从客户端时间／schema推断成员。私有 `source-coverage-inputs-v1` 显式保留原序列化排除的规范化／派生／初次覆盖／问题；重试比较这些输入及旧序列化结果。`source-coverage-record-v1` 绑定评估、私有输入、命令意图、版本、前条哈希及服务端时间。回执另绑定完整包与原审核身份。自哈希检验对应及完整性，来源真实性由服务端捕获和可信存储建立。

十三项SQLite保护拒绝五表改删、安装／切换表后续插入及不连续评估版本。读取验证准确保护定义，再验证所需完整证明及相邻前条，不在每次轮询解码全部历史。缺表／标记须升级且不写入；证明／保护受损返回净化完整性错误。管理降级独立验证每个切换payload／投影和成员根，存在私有输入、评估、回执或切换后版本均拒绝。故障测试先显式绕过保护再损坏临时库，另证普通SQL修改被拒。未迁移用户数据库。


## PMA-K09 — 当前确认及准备证据

当前确认要求解析时可选的 `coverageEvidenceHash`、`coverageRulesVersion` 在授权边界必须存在且匹配。缺失／阻断返回结构化409 REQUIRED；合法但过期的哈希／规则或变更证明意图返回409 STALE；畸形请求仍422。只有未确认DRAFT首次原审核及独立原文回执在同事务写入。已确认版本保留准确身份／时间，新当前确认须保存新计划版本。同意图确认重放重验当前回执，来源重评本身不授权。

当前详情／列表／筛选／工作台读取独立检查来源覆盖，不改旧daily问题及哈希派生。未核验的纯投影默认缺覆盖。从已存工作台选择发起新运行须重验当前reader；已完成选择的GET／幂等回执重放保留历史契约。既有冻结运行及manifest不改。

准备 `preparation-input-evidence-v1` 记录准备／条目／尝试身份、原始来源绑定、候选哈希、完整私有输入及服务端捕获时间，且authority_granted=false。稳定evidence_key不含时间／私有内容；同意图重试返回原时间，私有内容改变则冲突。辅助 `backtest_preparation_assurance_metadata`、`backtest_preparation_assurance` 与准备数据库共享事务但不改旧文档／哈希codec。新空库初始化两表；既有缺表库仍可读且不自动升级，仅显式 `upgrade_preparation_assurance` 增表，开发只在临时库执行。五项准确SQLite保护封存标记及不可变证明。原子finish现已保留完整原始候选JSON及输入；当前证明／回执／复用仍须独立核验。内存传递或输入自哈希不是当前批准。

## PMA-K10 — 准备当前证明及审核回执

`source-candidate-assurance-v1` 绑定实际准备／条目／来源／候选修订及哈希、实际尝试／私有输入、完整有序前缀、当前来源证明、逐字段原始归属及独立全局义务。初始来源使用完整 `source-coverage-v1`；继承更新使用 `source-change-coverage-v1` 加准确完整的当前前置证明。从不可变INPUT候选JSON重算实际完整前缀，不按相同来源／内容哈希扫描猜owner。自洽哈希、旧VALID／零问题审核或复制manifest不是当前来源证明。未识别来源条件及全局UNKNOWN义务跨后续变更保留。继承BUY/SELL范围只能使用同一稳定规则的完整前置方向证明，并将依赖纳入当前义务身份；未知文字及矛盾方向仍未解决。

事务内当前reader不授人工审核或执行权限。新审核在现有BEGIN IMMEDIATE内、旧记录／幂等写入前，核对准确原始与拟冻结策略。人工政策修正须有已注册操作证明并重新完整评估来源；通用确认或背景标签不豁免强制条件。旧冻结读取及原已完成回执重放保留历史codec及含义。新的复用／运行授权另须匹配当前审核回执并重新核验来源／前缀。

私有 `preparation-review-assurance-v1` 回执kind为REVIEW，绑定 `preparation_id`、`command_id`、`command_request_hash`、`previous_revision`、`reviewed_revision`、`review_revision`、`original_review_hash`、`frozen_manifest_hash`、完整 `proofs`、服务端 `created_at`，且 `authority_granted=false`。修订为严格正安全整数，reviewed_revision=previous_revision+1。1–512份证明须完整、同一准备、实际条目从0连续，且每项前缀准确等于此前完整证明引用。完整回执上限8MiB，不截断。主键 `evidence_key` 仅哈希preparation_id/review_revision；payload `evidence_hash` 覆盖完整版本化回执。当前授权owner另须将其绑定实际存储审核／冻结状态。

复用既有封存通用辅助表，不增加DDL。INPUT保持实际attempt投影不变。对于非INPUT的REVIEW行，SQL列 `attempt_id` 明确作为kind内槽位 `review-<review_revision>`，绝不解读为供应商尝试；实际尝试保留于 `proofs[].binding.attempt_id`。其余来源／候选投影使用最后实际证明绑定。按准确主键读取，完整验证规范payload／哈希／投影及五项保护，读取不写入。同意图重试保留原时间，变更命令／证明报冲突。回执与旧审核／manifest／幂等响应同事务保存，回执故障注入须整体回滚。本附录规定剩余T08i工作，不表示复用／操作验收完成。

## PMA-K11 — 明确人工操作检查点

`preparation-human-operation-v1` 的kind为HUMAN_OPERATION，与原始INPUT及当前REVIEW分离。它记录实际明确的REVIEW_AND_FREEZE或CORRECT_ITEM命令、完整来源／元数据与来源修订、准备／条目身份、前后准备及候选修订／哈希／证明、真实可空 `attempt_id`、原始候选检查点／修订、PRESENT/MISSING原始输入引用、完整改定draft／mapping／update／review、assessment绑定及有序前缀／parent、independent标志、可选最终冻结哈希／前次人工引用及服务端捕获时间。所有授权标志保持false。类型化规范 `command_json` 上限1MiB UTF-8，完整记录上限8MiB。修订为严格正安全整数，前后各修订准确+1。操作哈希不纳入最终当前评估，避免哈希循环。

依赖更新中，`resolved_draft`、`resolved_mapping` 对应 `resolved_update.draft`；`resolved_review.draft` 对应实际物化最终命名空间，两者不必相等。初始／独立来源中改定draft与改定review的draft相等。assessment绑定标识派生review；单计划冻结仍以原提取候选身份做来源评估，并在操作中另外绑定新冻结槽位／哈希。缺原始raw／私有证据记录为MISSING，不伪造或重标。保留原始INPUT字节及完整未绑定来源条款；之前的人工后像不能成为供应商前像。

稳定证明主键哈希preparation_id/item_index/after_candidate_revision。既有通用SQL表使用HUMAN_OPERATION内部的 `attempt_id` 槽位 `human-<item_index>-<after_candidate_revision>`，该槽位绝非供应商尝试。来源／候选投影保留真实来源绑定与后候选哈希。读取最多两次索引点查，验证五项既有保护及准确规范／哈希／投影对应，不写入。同意图重试保留原时间，意图改变报冲突。这些模型／存储检查仅证明完整性，不证明真实人工授权或语义完备。

只有既有授权事务在匹配实际前后状态、明确类型化命令、原检查点／输入、当前来源及前缀后，才能登记该操作。人工来源重评仍须消费每个原始跨度并证明全部受支持政策及关系语义。注册缺参／期限／基本面处理保持有限；未知技术要求不可豁免。Human评估不伪造规范化轨迹，不声称raw-delta、供应商完整草稿或自动忠实度。独立当前REVIEW回执绑定最终完整证明后，才可复用／运行授权。纯人工评估及事务接入在存储切片后仍待完成。
