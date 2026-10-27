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
