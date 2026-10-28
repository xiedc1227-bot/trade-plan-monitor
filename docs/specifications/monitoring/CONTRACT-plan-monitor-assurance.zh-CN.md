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

有限账户注册表还识别完整中文事实句 `实际持仓N股。`、`CORE持仓N股。`、`TACTICAL持仓N股。`、`每股成本D元/股。`、`账户快照YYYY-MM-DDTHH:MM:SS+08:00。`。数量为非负安全整数，成本为既有安全范围内准确非负小数，快照日期／时间须真实且明确。识别不初始化库存，不确认账户、成本、可卖性或真实性；既有OpeningAccountFacts校验及明确审核独立保留。目标／假设、条件、额外单位及未来要求余项不可当事实背景消费，未知余项仍阻断覆盖。40.105等每股成本不在总成本校验前舍入。

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

只有既有授权事务在匹配实际前后状态、明确类型化命令、原检查点／输入、当前来源及前缀后，才能登记该操作。人工来源重评仍须消费每个原始跨度并证明全部受支持政策及关系语义。注册缺参／期限／基本面处理保持有限；未知技术要求不可豁免。Human评估不伪造规范化轨迹，不声称raw-delta、供应商完整草稿或自动忠实度。独立当前REVIEW回执绑定最终完整证明后，才可复用／运行授权。初始及依赖更新的Human纯重评已实施；事务接入及后续复用／操作验收仍须独立完成。

增量字段 `command_id`、`command_request_hash`、`after_record_hash` 为严格字符串／哈希，须全部缺省或全部存在。缺省时不进入序列化，保留既有未登记artifact字节／哈希。当前登记要求三者齐全，并独立核对真实原幂等命令及变更响应；响应哈希使用 `preparation-human-after-record-v1`。字段存在本身绝非登记／状态／授权标志；事务owner核对准确来源／候选变更、前缀及捕获时间后，后续当前审核才能使用。初始Human证明及独立 `source-human-change-coverage-v1` 类型仍保持raw／full／fidelity声明false；缺INPUT不变为虚构供应商记录。

## PMA-K12 — 明确复用血缘与消费位置

可选 `SourceCandidateAssurance.reuse_ref` 为None时完全不序列化，保留旧证明字节／哈希。准确五字段为 `original_owner_binding`、`original_assurance_hash`、`original_current_review_hash`、`original_manifest_hash`、`lineage_hash`。前四项标识实际捕获或明确修正来源的原始叶子，后续复用保持不变；本次不可变LINEAGE标识创建命令直接选中的父项。两类owner均不可按相同来源／内容／候选哈希搜索推断。

复用alias只改变聚合消费位置 `binding.preparation_id`／`item_index`、有序消费前缀／parent及自身引用／哈希。其余binding坐标必须与原证明一致；source assessment及内部binding／parent、来源引用、字段归属、义务ID、全局义务、Human回执、内容和问题全部准确保留。原阻断证明仍阻断。纯builder不认证父项、操作、审核或SQL登记。既有变更分析仍要求父项处于同一消费preparation。

私有 `preparation-lineage-v1` 的kind为LINEAGE，绑定 `preparation_id`、CREATE_SINGLE/COMPOSE_REVIEWED `operation`、规范类型化 `command_json`、真实 `command_id`／`command_request_hash`、`created_revision=1`、`creation_response_hash`、`selection_order`、`placements`、服务端 `created_at`、字面false授权及主键／哈希。每项placement保留消费index、直接 `owner_binding`／修订／审核修订／审核哈希／manifest哈希／proof哈希，以及叶子binding／assurance／review／manifest哈希。保留原命令顺序，selection_order记录确定性位置排列。CREATE_SINGLE复制明确父项的完整前缀并保留新自有尾项；COMPOSITION选择每个明确owner的最后条目。既有256条目、1MiB命令、8MiB完整证明边界不变。

既有封存辅助表使用单一创建主键及LINEAGE内部槽位 `lineage-create`。SQL投影最后真实复用来源／候选，因为继承SINGLE的新尾项在创建时没有候选。同意图重试保留原时间，意图改变报冲突。登记须在既有同一writer事务中，根据实际父项当前审核重建／匹配待写响应，再将lineage、record及原幂等响应原子保存。创建响应哈希使用 `preparation-lineage-creation-response-v1`。后续读取先认证真实命令／响应及新鲜父项授权，再重建alias。血缘缺失或未登记时阻断新授权，历史读取仍可用。

revision1的COMPOSITION以已登记LINEAGE和全部选中项真实当前审核建立复用授权，不伪造previous_revision0的人工REVIEW，不放宽v1 REVIEW codec。新审核的继承SINGLE使用既有真实REVIEW回执及连续消费证明。仅前缀读取和Human修正只使用实际选中前缀，复制父条目不能在消费preparation下获得新Human操作。解析使用事务内memoization、环检测及既有链长边界，无全局缓存、截断或复制INPUT／操作记录。模型／存储与实际writer／复用验收是独立实施检查点。

## PMA-K13 — 独立风险适用范围控制

`source-risk-control-v1`、`source-risk-control-analysis-v1` 针对上游已认证的准确当前前驱，解析有限完整来源单元。它们保留准确来源／binding／生效日期／review／parent身份、原始跨度、类型化前后风险值及其 `source-operation-value-v1` 哈希。`preserved_policy_hash` 使用 `source-risk-policy-v1` 哈希全部before字段，仅排除holding_scope。授权为字面false，analysis不提供覆盖状态或完整性声明。未知跨度保持准确、有界、未解决。

专用risk JSON准确包含target/rule_id/action/scope_assessment，局部MODIFY才额外包含scope_change。整条REVOKE/RETAIN要求ENTIRE_RULE，局部MODIFY要求PARTIAL_RULE及EXISTING_POSITIONS_ONLY或NEW_POSITIONS_ONLY。自然语句为 `source_risk_controls.py` 中明确stable-ID的中英文封闭字典；泛撤销、把部分撤销表示为整条退出、引述／条件／假设及未指名歧义目标继续不支持。额外未知文字、重复目标／操作序号继续阻断。

局部控制仅通过既有restrict_scope，将实际前驱范围与已绑定生效交易日求交，派生holding_scope。缺日期或空交集保持未解决，空交集从不授权撤销。保留其余全部风控字段，含适用时的价格／比较符、TWO_OFFICIAL_CLOSES、零目标、稳定身份及RESUME_FIRST_CLOSE。确定性不变交集仍保留原文MODIFY意图，供后续与实际no-op对照。完整来源覆盖及实际操作／字段归属对应仍须独立消费这些控制后才能开放授权。混合表格价格角色及未识别文字另待完成，该helper不能使原文04或整份计划通过验收。

## PMA-K14 — 物理调用与最终运行栅栏

依赖前驱的collection CALLING变更，必须在既有准备库BEGIN IMMEDIATE内、保存phase／幂等响应前重验真实当前前缀。策略父项须完整，candidate hash须等于实际claim的base_hash。首项／独立来源不获得前置策略继承，context／base_hash保持None。直接begin_call失败不写入。仅匹配owner的READY尝试、无candidate、retryable=false且错误为SOURCE_COVERAGE_REQUIRED、SOURCE_COVERAGE_STALE、SOURCE_COVERAGE_INTEGRITY、SOURCE_COVERAGE_UPGRADE_REQUIRED、SOURCE_COVERAGE_LIMIT_EXCEEDED之一时，才可确定为未启动预检失败。worker仅在begin_call周围捕获这些错误，此时供应商尚未获准调用；正常supervisor结束并释放，不自动重试。CALLING／UNKNOWN物理结果保留原恢复规则。

`current_prepared_run_fence(store, preparation_id, expected_manifest_hash)` 持有真实准备库BEGIN IMMEDIATE，重算当前REVIEW／LINEAGE／来源证明并核对准确冻结manifest；yield冻结值期间持续保留来源writer预约，不写业务行，退出时释放。PreparationService.current_run_fence仅以私有同步能力提供。历史get_frozen、数据读取及已经完成的请求回执保留既有合同。

新的prepared提交在拷贝行情前取得真实服务能力，并向finalize_run_submission传入服务端私有 `admission_guard` factory。任务库writer核对真实预约后，先进入来源栅栏，再复用活动操作或写新任务／响应。锁顺序为jobs→preparation，任务库COMMIT或ROLLBACK完成后才释放准备库栅栏；on_admitted仍在提交之后。两类writer内不调用供应商或获取行情。准入拒绝前已拷贝的不可变输入可以保留为孤立证据，不授予排队任务、已完成响应或coordinator授权。不增加公共请求／哈希／codec字段或legacy模式标志。新key是新准入；准确已完成回执重放在当前检查之前返回原结果。缺服务端能力为unavailable，缺失／过期当前证明为conflict，存储损坏为脱敏integrity失败。既有全局准入／资源限制保持不变。

## PMA-K15 — 完整来源风险控制的操作对应

完整变更分析根据准确当前来源和完整前驱独立重解析风险控制。每个已识别控制必须匹配实际操作的稳定目标、action及完整before/after哈希。只有派生交集令完整分支保持不变时，来源MODIFY才可对应实际RETAIN。仅holding_scope语义叶子获得当前来源派生；不变的价格、确认方式、目标及其余策略继续保留前驱owner。未消费控制、额外策略变化、未知余项、B分区控制及ordinary/risk两registry之间重复操作序号均阻断完成。

序号比较仅消费有限parser已经识别的控制。读取operations索引前，剥一层完整外部Markdown `**` 包装，与既有ordinary parser认可的格式一致；从不提升未识别文字。AI原始重放与已登记Human重评共用同一语义对应；两类协议均不能绕过完整来源，或仅凭控制helper主张新授权。混合表格价格角色须另有独立关系证明。

## PMA-K16 — 有限仓位及账户载体

`source_position_directives.py` 只接受一条完整全来源句子：`调整最大仓位为N股，`、`仅修改最大仓位N股，`、`仅修改最大仓位为N股，` 之一，后接 `其余规则保留。` 或 `其余规则不变。`。N为0至9,007,199,254,740,991的规范整数，原生仓位校验仍独立进行。仓位声明只拥有含逗号的准确前缀；尾句使用既有RETAIN_UNMENTIONED控制，分别对应实际合并结果。引用、未闭合前置条件、混合多行来源及额外后缀不获得此production。解析器从不在未知文字中搜索仓位数量。

完整 `账户现金余额N元。` 语句支持规范非负整数元或一／两位小数。用整数分解析，不依赖Decimal上下文运算，最多9,007,199,254,740,991分。识别仅证明事实句式，不证明现金真实、不构成入金、库存／资金确认或BUY授权。准确匹配的metadata标题 `Synthetic continuity plan` 及 `source_policy_text.py` 中完整独立事件文本，仅支持确定性合成工作流夹具；后者仍是待满足的策略要求，从不成为正向背景或已满足的运行事件。这些载体不豁免附加交易条件，也不计作自然语言语料验收。

## PMA-K17 — 独立混合表格关系与实际读取时钟

已注册混合风险行，在原始跨度输出两个独立来源义务：原有持仓范围控制及 `REGISTERED_STRUCTURAL_RECOVERY_REFERENCE` 关系。关系保留准确上游价格owner／binding、parent身份和原始证明；paths为空，不提供价格／BUY／stop派生。仅属于有效价格依赖组的语法框架获得正向语法处理。缺失关系、错误owner／价格、控制冲突或其他未知行继续阻断。保留有限原文含义，不新增可执行策略字段，也不主张整份原文04完整。

当前daily来源读取，全链使用实际调用方拥有的时钟验证人工补充来源：work绑定读取使用work.daily.clock，仓库审核使用repo._clock。不创建无时钟DailyRepository，不从存储记录猜测时间、不在读取时写入或伪造Human记录。无效／未来登记记录返回脱敏完整性失败；有效但缺失／不匹配的登记仍为来源必需阻断。历史codec／哈希不变。

## PMA-K18 — 完整替换包含明示删除证明

仅完整来源句 `完整替换此前计划。` 注册PLAN/FULL_REPLACEMENT，须对应output.scope、retain_unmentioned=false及准确已映射scope_clause_ids。每个语义后像字段均须独立当前来源证明；产品默认或保留的前驱owner不能替代新的完整快照。仅此已验证替换分支联合范围及字段证据。矛盾的保留／无新增控制、B、引用及未知文字继续阻断。

逐项核对实际changed path，含最终语义图已不存在的可选叶。删除必须有准确已映射null、完整所属类型化后像容器且其全部来源义务完整／范围已知，或准确匹配的专用风险控制后像。剩余兄弟叶和范围句不能证明缺席。整条ordinary／alert移除还须明确整条撤销，或准确完整有序根集合证明稳定ID缺席；整条risk撤销始终要求专用ENTIRE_RULE控制。既有不支持的null形式仍阻断，不引入通用背景处理或放宽codec。

## PMA-K19 — 当前操作依据与独立历史风险

私有事务内 `require_source_action_authority` 重读真实plan／review／activation／cause归属。新ordinary BUY／SELL及例外授权，均要求准确当前完整已审核bundle。真实存储的技术风险cause，仅在核对独立安装成员根、准确捕获的原始active／review身份及未改变的策略／来源／启用对应后，才可使用单独HISTORICAL_TECHNICAL_RISK依据。成员根使用每页100行keyset及恒定内存，每次调用仅核一次；不从时间、ID前缀、旧零issue或调用方标志推断legacy许可。STALE／INTEGRITY／UPGRADE／LIMIT不降级。

风险行须唯一匹配实际active稳定分支、价格／比较符／目标／范围及必要确认／执行日期顺序。严重风险条件树保留准确结构／结果／消费ID；REVIEWED_FACT叶还须解析真实历史FACT、原始存储版本／content归属、kind、日期、结果及可用时间。合法SUPERSEDED owner仍可为原始事实owner；不凭未知SIGNAL绑定捏造证据。原生行情证据继续由既有读取器／求值器及执行防护负责；此来源依据不是完整历史行情重放或可执行token。

模拟交易在既有cause／symbol writer栅栏内核此依据。普通交易不能借风控许可；risk_execution仅消费已验证风险行集合，仍须匹配原完整报价动作／命令数量，不调整数量、不新建窗口或发生次数。准确已完成请求重放仍返回原结果。损坏来源证据走脱敏服务完整性错误；有效但缺失／过期当前证明仍为结构化冲突。既有行情、库存、资金、消费及回滚防护仍必需。运行时生成、例外及发送前检查须各自验收后才关闭C03。
