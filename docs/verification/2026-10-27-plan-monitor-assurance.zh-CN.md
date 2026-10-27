# 验收：plan-monitor-assurance

状态：实施中 — 2026-10-27。用户已批准PMA-D01–D06、全部实施任务及共用48次真实提取上限；仍禁止迁移用户数据库。基线 `a5546ad`。[英文规范版](2026-10-27-plan-monitor-assurance.md) · [任务](../../tasks/plan-monitor-assurance.zh-CN.md)。

## PMA-R01 — T01契约与基线

既有基线：62项单元通过，3.00秒；21项当前P3审核／操作／通知集成通过，6.84秒，1条既有Starlette警告。独立历史反例夹具／测试10项通过，0.52秒；修正1条常规长行后最终Ruff通过。这是83项既有及10项新增历史边界检查，不是当前遗漏防护验收，不能证明真实供应商准确率。

固定夹具复现两种语言及COMMENTARY/HISTORICAL/ACCOUNT：145条款／128绑定变为146／128，候选不变、历史零问题；AMBIGUOUS仍被原验证器拒绝。固定来源／证据哈希变化及无授权。新当前防护测试尚未实施，不声称已通过。契约固定新证明／模型归属、可信历史切换、下个可用0028预留、API／错误边界及物理次数记账。

当前日志保留在忽略目录 `.pytest_cache/pma-v01.log`、`.pytest_cache/pma-v01-integration.log`、`.pytest_cache/pma/t01-baseline.log`、`t01-baseline-ruff.log`，最终验收归档准确原失败／结果及命令。没有用户数据、live供应商、迁移、启用、库存／成本确认或通知发送。保留 `tasks/plan.md`、`tasks/todo.md`。

## PMA-R02 — 剩余验收

T01–T07及C01–C02完成，T08–T24及C03–C08待完成。不能从纯测试或批准契约推断完整流程覆盖已完成。真实尝试0/48，调用前只读调查原文语料资格。工程完成、准确版本真实提取、实际安装就绪将分别报告。

## PMA-R03 — T02有界证据模型

新增模型测试先因模块不存在失败，最终模型／历史聚焦组28项通过，0.73秒，Ruff通过。覆盖严格标量、有限规范JSON、证明／义务篡改、总4096/4097、逐条64/65边界、重复证据、处理变化时原文标识稳定及AI_NEW缺前像阻断。纯模型不授权，当前接口仍门控。日志：`.pytest_cache/pma/t02-red.log`、`t02-final.log`、`t02-ruff.log`。

## PMA-R04 — T03及C01原文背景防护

当前防护、正向注册表、解析器、模型、历史边界及初步语义变异组合161项通过，2.18秒（`.pytest_cache/pma/c01.log`）；最终聚焦Ruff通过。私有防护阻断三种背景角色、无关键词及混合句强制要求；完整path=JSON声明必须与候选完整语义一致。历史验证不变。正向背景仅限准确标题／历史／账户／元数据文法，不靠未命中关键词。公共授权待C03/C04后开放。

两个独立回归发现真实缺陷并修复：来源开头空格被去除（1失败／18通过，修复后29通过），以及JSON声明重复键（1失败／6通过，修复后组合161通过）。日志：`t02-span-red.log`、`t02-span-green.log`、`t03-parser-red.log`。18项初步语义测试修正自身可空位置诊断后，在完整声明防护下已通过；该诊断失败不记为生产缺陷或T04完整验收。

## PMA-R05 — T04/T05语义、规范化与混合来源

最终适用阶段覆盖／模型／解析器／背景、独立语义／注释／容器对抗、规范化／处理／分区及既有历史审核／排除／期限／来源解析组合342项通过，11.69秒，1条既有Starlette警告（`.pytest_cache/pma/t05-final-checkpoint.log`）。全部变更来源模块／测试通过聚焦Ruff。这是确定性本地契约证据，不是真实提取准确率或当前运行授权。

独立对抗发现标量ALL/ANY证明未声明后代、同值字段交换作用域、显示／注释／人工事实／费用文字夹带新条件、未支持人工文字补充及畸形关系对象异常逃出。修复保留准确来源跨度、双向来源对应、完整原生谓词／关系原子及明确UNKNOWN/UNSUPPORTED/LIMIT阻断。4096原子完整返回，4097明确失败。最初64标量测试误以为逗号仍在同一canonical条款内，已修正，未放宽每条64的模型边界，该失败不算生产缺陷。原始／最终日志：`t04-adversarial-independent2.log`、`t04-adversarial-text-carriers-red.log`、`t04-kind-red.log`、`t04-label-red.log`、`t04-container-atoms-red.log`、`t04-container-atoms-boundary.log`、`t04-container-atoms-independent-final.log`。

规范化初始14失败／3通过（模块不存在），后17通过；完整轨迹不能掩盖仅评估处理删除BUY规则。注册基本面排除保留准确混合余项；缺参要求准确人工补充，不能覆盖明确已知值。A/B标记不豁免，强制字段移B报冲突。准确注册期限转换仍记为人工调整。处理及边界初始分别7失败／5通过、7失败／8通过，后续聚焦组通过。日志：`t05-normalization-red.log`、`t05-normalization-final.log`、`t05-treatments-red.log`、`t05-treatments-green.log`、`t05-boundaries-red.log`、`t05-boundaries-green.log`、`t05-human-text-red.log`、`t05-human-text-green.log`。

## PMA-R06 — T06及C02提取证明

直接当前提取原像／可检查阻断测试初始13失败／8通过（缺载体）；实施后与既有安全测试39项通过，2.93秒。既有提取／v12预算／P3编解码及新增直接测试88项通过，3.84秒（`t06-current-green.log`、`t06-compat.log`）。固定当前输出schema规范SHA256为 `7a7d35473a44ebb8de02d6fea035b005c5b3d0774644f68aebc1ef455653c3f4`，固定来源提示词SHA256为 `6649fd2feca4ad6d7384838ee66ede890afbdc647c9e54d39728abd571084b6f`，均未变化；服务端私有证明不进入供应商输出契约。合成提取夹具声明自身本地输入预算，不改变真实调用活动配置。


compact及前序补丁证明现保留准确原始JSON、上下文、按序扩展／规范化／物化及复制后的私有阻断。聚焦修正缺少依赖时仍阻断。派生模型57项通过、回放36、更新提取10、物化26；物化／回放／提取组合72项通过，3.50秒。保留原始缺模块／字段失败及真实超限分类失败；时间序列化／超限措辞的测试修正不算生产缺陷。历史payload／审核哈希仍固定。日志：`t06-derivation-green.log`、`t06-derivation-extraction-agent-green2.log`、`readiness-materialization-expanded-02.log`、`t06-materialize-root-final.log`。

C02提取回归277项通过，13.96秒（`c02-extraction.log`）；既有集成21项通过，6.39秒（`c02-existing-integration.log`）；来源组567项通过，20.08秒（`c02-final-source.log`）。原生支持修复后，`rg --files tests/unit -g 'test_source_*.py'` 加 `test_daily_review.py`、`test_daily_source_exclusions.py`、`test_persistent_rule_validity.py`：528项通过，16.18秒（`c02-source-confirm.log`）。先前一次选择含不存在文件、未运行测试，不记验收。保留1条既有Starlette警告。原生支持／提取组60项通过，3.40秒；Ruff通过。未调用供应商、迁移用户库或开放新运行授权。

作用域对抗先5项失败，后增加未知文字失败；只有原文证明的方向才能确定交易义务范围，未注册文字即使放入BUY容器也保持UNKNOWN。一次过严容器回归已修复，相关32项通过。原生支持对抗：7失败／3通过，后10项通过。新防护阻断不可计算的指标参数／单位组合，不改历史schema／引擎默认值。仅PMA新增正例辅助改为MA20 period20，旧夹具不变。


## PMA-R07 — T07不可变持久化

增量0028及五张侧表保留旧计划／来源／审核字节。独立迁移19项及缺表只读6项通过。原始RED为缺表；另一真实缺陷是成员受损仍可降级，现降级完整验证标记／成员自哈希、投影及成员根，任何证明或切换后版本（含回填旧日期草稿）均拒绝。迁移测试仅用临时库。

核心存储18项初因缺Store模块收集失败，后3.42秒通过。独立攻击复现5项历史完整性失败（非相邻删除及祖先投影不符），数据库封存及准确保护定义检查已修复。新增3项SQL保护测试先失败，后保护／核心／迁移／旧资本组合47项通过，8.42秒。独立存储对抗50项通过，10.48秒，覆盖13项保护、私有原字节、回执绑定及24版本后最多2条assessment查询。首轮对抗有两处测试自身的类型化模型／事务错误，修正但不计生产缺陷。最终持久化／旧P3审核组合112项通过，19.28秒（`t07-checkpoint.log`），保留2条既有SQLAlchemy反射警告。最终来源组532项通过，19.10秒（`t07-source-final.log`），保留1条既有Starlette警告；Ruff通过。原始失败：`readiness-migration-red-02.log`、`readiness-migration-down-red-01.log`、`t07-storage-red.log`、`t07-storage-adversarial-agent-red2.log`、`t07-seal-red.log`。

独立审查新增的注释／未知路径回归也通过：初始2项COMPLETE绕过及2项错误BUY范围已修，未知标签不能借标点获得已注册含义。有限注册仍有意保守，当前流程防护及真实自然原文语料签收仍待完成。真实供应商0/48；未迁移用户库、启用计划或发送通知。


## PMA-R08 — T08当前流程进展

T08仍在实施，C03未关闭。当前保存／确认／仓库启用测试先发现14项授权失败，后独立16项通过，含回执写入失败回滚。保存私有输入使缺原像明确可见，不追溯伪造保真。版本分配的真实哈希错误已修；之后自哈希合法但after不符的轨迹使自动分配版本丢弃可检查DRAFT，两条版本路径现均保留原轨迹为AI_NEW/BLOCKED。保存／读取16项通过，5.02秒；当前重验不写入。测试自身的类型化义务构造错误另记，不当生产缺陷。

HTTP先2项失败，扩展后14失败／1通过（缺新绑定）。当前HTTP19项及投影7项独立通过；最终保存／授权／HTTP／投影组合58项通过，20.14秒（`t08-web-final.log`），保留1条既有Starlette警告。合法当前确认同事务写绑定回执；变更请求／证明及过期重放冲突，畸形哈希仍422。详情／列表／筛选及工作台reader不再把legacy／过期证明显示为当前可用，旧审核ID／时间／问题保持。投影测试11张业务表快照完全不变，已确认版本的新确认须新建版本。

工作台新运行复用先10失败／2通过，后新边界及既有纯上下文15项通过，1.82秒（`t08-workbench.log`）；已完成选择GET／回执重放仍属历史操作。worker私有传递初因缺inputs失败，最终新增8项及既有worker组合53项通过，10.18秒（`t08-worker.log`）。准确原始delta／context、规范化及MATERIALIZED阶段跨JSON重验保留，旧候选JSON／哈希不变；派生字符串转有界类型问题。仅内存传递不是持久批准。

准备辅助存储先17失败／2通过，另有缺模型单元收集失败；最终新增33项独立3.62秒通过，模型／辅助／旧存储组合107项通过，6.13秒（`t08-prep-store.log`），Ruff通过。新空库创建独立标记辅助表；旧v1/v2不自动加表。显式升级、回滚、原生备份、同尝试私有字节变化、5项不可变保护及只读访问均在临时库验证。实际worker finish原子持久化已于下文验证；当前前缀／继承授权仍待完成。

忽略证据目录已准备独立12案真值草稿，不是冻结manifest或真实验收。现有配置输入上限50,000字符、输出4,096 tokens；部分完整v12草稿组装提示超过输入上限，未删来源、提高上限或调用供应商。T13–T15须如实保留基线预检失败，并处理已批准候选版本分支。真实供应商仍0/48；未迁移用户库、真实启用、确认库存、获取行情或发送通知。

## PMA-R09 — T08逐来源变更证明

原子finish现将完整原始候选JSON及私有输入与成功尝试在同一事务保存。新增17项独立测试与worker／store回归合计177项通过，15.45秒（`t08-atomic-final.log`）。初始来源当前证明51项通过，8.42秒（`t08-initial-final.log`）；共享全来源分析重构的适用来源测试587项通过，22.26秒（`t08-core-final.log`）。历史审核／哈希契约不变；这些计数重叠，不可相加。

新增变更证明核对准确前置上下文、当前原文／元数据、候选／尝试身份、原始回放、本次每项声明及实际物化变更。未改叶子保留原证据；派生delta不能冒称供应商提供完整计划的保真。缺原始证据或前置证明不完整时，保留可检查BLOCKED候选。最终原20项加独立12项语义／头信息攻击及18项模型攻击：50项通过，6.98秒（`t08-change-final-03.log`），聚焦Ruff通过；提交 `a03d9ce`、`1121226`。较大来源／delta选择在最后新增保留模型约束前586项通过，29.44秒（`t08-change-slice-02.log`）；最终50项已覆盖最后约束。这是本地确定性证据，不表示C03完成。

原失败均保留：缺变更模块、把扩展器未使用默认值误当实际当前授权（`t08-change-01.log`）、身份／哈希／模型攻击（`t08-change-proof-red.log`）、无效原始完整计划标记（`t08-change-proof-followup.log`）、集合编号／空态归属（`t08-change-proof-final.log`、`t08-change-empty-red.log`）。测试自身的提前拒绝作用域和无效空计划夹具已修正，未降低拒绝标准。root两次测试选择使用不存在的通配符／字面路径、未运行测试，均不计通过。仍须完成注册变更语义、继承范围、聚合来源归属、当前准备审核／复用原子接入及T09操作防护。T08／C03仍开放。供应商0/48，用户迁移0。

忽略目录中的候选预算设计实测，可逆schema／context编码保留完整来源及约束后，最大草稿案输入48,693字符，低于未变的50,000上限。它不是已实现提示词／decoder、冻结真值或真实提取结果；4,096-token输出仍须真实验证。旧已审核前驱快照缺少当前完整性，不能升级为当前真值或授权。

## PMA-R10 — T08继承、控制与准备审核

聚合归属10项及独立攻击13项验证准确两跳原owner／义务ID、未绑定UNKNOWN条件保留、完整前缀身份、删除／重排及无隐式人工回执。初始／当前／变更组合111项通过，14.61秒（`t08-composition-final.log`）。真实完整loop输出协议包含未改变开户事实，验证时不删除供应商字段；初始／loop／聚合组64项通过，10.01秒（`t08-loop-raw-final.log`）。一个来源哈希测试最初构造的输入已被既有模型拒绝，已改为验证该拒绝，不算新增生产缺陷。

标量BUY/SELL范围继承使用同一稳定规则的完整前置方向证明；34项helper及2项完整更新接入测试通过。首个compact夹具缺少数量绑定，改用完整更新后发现把私有原像对象差异误当公开输出差异；现比较公开内容并单独保留私有证明，随后合法语义RED转绿。日志：`t08-change-scope-final.log`、`t08-scope-wire-red.log`、`t08-scope-wire-red-02.log`、`t08-scope-wire-red-03.log`、`t08-scope-wire-final.log`（组合109项通过，11.79秒）。容器范围扩展仍待完成；helper不重新分类未知文字。

独立控制解析完整原文陈述并对照准确前置计划，不以AI操作作为输入。57项helper及9项接入测试覆盖准确撤销／保留、严格三键JSON、无新增指令、未知限定／示例、错误目标、重复序号及引述／跨行控制。风险撤销尚未注册，保持UNKNOWN；原条件／引述／序号失败均保留。完整适用来源／delta回归715项通过，39.67秒（`t08-controls-combined.log`），聚焦Ruff通过；提交 `6cbbd04`、`88823e7`。注册控制不豁免其他来源跨度，也不新增数量。

事务内准备reader无写入地重建准确原始候选／输入／来源／前缀证明。新增与临时存储回归130项通过，11.61秒（`t08i-current-final.log`），含合法单／双来源冻结、背景／缺输入阻断、旧回执重放及注入回滚；提交 `67ae4f7`。REVIEW辅助存储48项独立通过，12.88秒（`t08-review-storage-root.log`），覆盖准确重试、五项保护、投影损坏、严格修订／前缀及完整8MiB边界；提交 `010dd94`。SQL的REVIEW槽位不能当提取尝试。

原子当前审核核对实际旧审核、完整来源证明、冻结清单、原幂等响应及人工审核时点。新增原9项、独立4项分类攻击及来源／存储回归76项通过，25.47秒（`t08-review-atomic-verified.log`）；新增时间绑定后，当前审核／对抗／当前来源组合29项通过，12.55秒（`t08-review-time-final.log`），Ruff通过；提交 `cded14b`。这些计数重叠。真实原失败：缺当前getter／原子回执（`t08-review-atomic-red.log`）、资源错误误分类（`t08-review-limit-red.log`）、存储响应受损／manifest／post-review错误（`t08-review-adversarial-red.log`）、自洽时间替换（`t08-review-time-red-02.log`）。首个时间注入只改payload未同步SQL投影，该夹具失败修正后才计为语义RED。

T08／C03仍开放。合法人工修正仍须独立已注册操作回执及完整来源重评；当前策略必须不变的门控不是其最终验收。继承／组合血缘、新复用／运行重验及T09操作／发送防护待完成；语料、公共覆盖／就绪接口、UI及全量验收也待完成。供应商发送0/48，未迁移用户库、真实启用、确认库存、获取行情或发送通知。

## PMA-R11 — T08独立Human重评

完整变更语义分析及来源归属组合由独立AI／Human包装共享。四份固定AI变更输出及四份固定聚合输出保留准确序列化字节和证明哈希。Human初始重评18项及依赖更新重评27项覆盖合法空参数补充、拒绝覆盖明确值、三种背景角色下的未知条款、准确命令／来源／前置绑定及独立人工操作归属。Human证明不声称供应商／完整草稿／raw自动忠实度。最终完整来源／delta单元选择780项通过，43.43秒（`t08-human-change-final.log`）；与之前聚焦结果重叠，不可相加。

不可变Human操作存储34项通过，8.96秒（`t08-human-storage-root.log`）。增量真实命令／响应登记字段44项独立通过，8.36秒（`t08-human-registration-root.log`）；可选字段缺省时保留全部既有未登记artifact字节。这些检查证明有界结构、不可变对应及纯语义，本身不证明实际命令登记或当前审核授权。提交 `67bc3ec`、`3136fc8`、`adbbeb7`、`76e65c7`、`174d2f6`、`3d501cb` 分别包含这些已验证切片。

实际Human事务接入新增22项测试，关联组120项通过，28.63秒（`human-authority-agent-final.log`）。root独立验证当前来源／审核／Human组合51项通过，19.55秒（`t08-human-authority-root-01.log`），Ruff通过；提交 `1419bbd`。登记绑定真实原命令／响应、检查点／输入、前后候选及准确前缀。明确条目修正不产生整计划审核；单计划策略修正将Human证明与独立REVIEW原子登记，任一插入后失败都整体回滚。合法自哈希原可替换前次Human前缀；独立RED及修正后的链接验证保存在 `human-authority-agent-link-red.log` 和最终组合。

Human范围连续性新增23项测试，初始7项真实失败／16项通过（`t08-human-scope-final-red.log`）。修复允许已证明的原文方向及准确注册的空方向补充继续继承，并保留原始回执。当前Human来源证明不能借其他owner标签隐藏缺回执；补充语义保持准确。helper／wire组合59项通过，5.77秒（`t08-human-scope-root-01.log`）；完整来源／delta组合803项通过，47.41秒（`t08-human-scope-regression-01.log`）。独立审查另实跑两跳Human链，确认早期BASE回执不被当前操作哈希替换。这些计数重叠。

旧准备工作流组合保留39项失败／157项通过（`human-authority-agent-old-regression.log`）：旧审核夹具缺原始INPUT或已登记Human证明，使用泛补充。该选择中的store／worker模块通过。当前工作流夹具正通过合法来源／输入／操作路径更新，旧冻结断言、哈希及golden不豁免。不声称关闭T08／C03或通过新继承／组合／复用／运行／操作验收。完整自然原文语料验收及就绪仍待完成。供应商发送仍0/48，用户数据库未迁移。

## PMA-R12 — T08账户背景与复用基础

完整非零持仓、准确每股成本及明确账户快照句初始22项失败／20项通过（`t08-account-context-red.log`）。有限正向识别仍将账户真实性／初始化保留为独立权威。独立探测36项附带条件案例保持阻断，并发现Python的24:00归一；新增准确时间RED为1失败／42通过，之后账户／背景／开户／基线组合175项通过，6.98秒（`t08-account-clock-red.log`、`t08-account-context-final.log`）。Ruff通过；提交 `d041320`。

旧审核工作流夹具现使用完整支持的来源声明、原始合成raw／私有输入及真实登记的空参数修正。review／store／worker组合198项通过，33.43秒（`workflow-fixtures-agent-regression.log`），含两项新增旧来源拒绝案例。AST对比保留34个测试函数的全部108个原始Assert节点（`workflow-fixtures-agent-assert-parity.log`）；原账户／成本、CAS、回滚及冻结篡改断言保持。历史自然语言单元夹具及旧golden不变。提交 `8d41e13`，之前39项失败仍保留记录。

明确复用alias新增42项纯测试，相邻组合185项通过（`readiness-reuse-alias-adjacent-green-01.log`）。完整来源／delta组合888项通过，46.13秒（`t08-reuse-source-final.log`），保留四份AI变更及四份聚合字节／哈希固定检查。Ruff通过；提交 `c1737e7`。alias保留原始叶子证据及全部来源／Human归属，本身不证明实际父项审核授权。

LINEAGE存储初步38项通过（`t08-lineage-storage-02.log`）。独立21项随后发现6项真实失败：同owner哈希矛盾、消费方叶子自引用及解析前文本／字节边界缺失（`lineage-storage-agent-adversarial-red.log`）。现已修复，新增与既有INPUT/HUMAN/REVIEW/LINEAGE存储174项通过，21.24秒（`t08-lineage-storage-final.log`），Ruff通过；提交 `fd46297`。首轮另发现严格修订序列化缺陷及pytest参数过长造成环境错误，原始日志仍保留。实际继承／组合writer登记、递归当前授权及新运行／操作核对仍待完成。T08／C03继续开放；真实提取仍0/48，未迁移用户数据库，未操作真实账户／行情／通知。

## PMA-R13 — T08风险控制与剩余来源／复用接缝

独立有限风险控制解析新增56项测试，关联风险／来源控制组合153项通过，8.69秒（`t08-risk-control-final.log`）。root独立验证新增56项通过，3.92秒（`t08-risk-control-root.log`），Ruff通过；提交 `860b1ab`。类型化前后校验保留每个非scope风险字段，准确求范围交集，保留未知来源单元。原缺模块RED及证明超限错误分类RED仍保存在 `t08-risk-control-red.log`、`t08-risk-control-limit-red.log`。这些是helper检查，完整来源风险／价格角色接入仍待完成。

独立来源物理提取不需要前置策略许可；依赖前驱的begin_call则必须在既有writer事务内取得其真实当前证明。新增测试现复现3项真实失败／4项通过（`current-reuse-agent-independent-red.log`）：两类未证明的VALID前驱被接收，正例路径未重验当前INPUT。独立context／base、取消、CAS及旧回执重试继续覆盖。该待补防护、完整JSON容器范围继承、实际血缘writer／复用接入及混合表格角色均未因helper结果获得验收。中间结果不关闭阶段／检查点，供应商尝试仍0/48。

## PMA-R14 — T08当前血缘、完整容器及最终运行进展

实际SINGLE继承／自有尾项修正及COMPOSITION，在原事务中验证真实创建命令／响应及父项当前审核。root最终相邻组合180项通过，67.76秒（`t08-lineage-authority-final.log`）；提交 `cb4e60b`、`8263c33`。三类存储owner损坏原误报STALE，现报INTEGRITY。独立SQL测试发现同连接跨事务缓存问题，context现检测事务／写入／data／schema变化，同事务只读缓存仍有效；独立生命周期3项通过，2.79秒。root较早组合179通过／1失败，因无用的单来源私有keyword打断既有资源错误注入；删除该无用参数后恢复原合同。原失败均保留。

完整原文JSON容器及ALL/ANY关系，独立重建全来源后，仅继承同一已验证稳定规则方向。新增27项通过（`container-scopes-agent-final2.log`），完整source选择在最后新增未知余项测试之前1008项通过，55.37秒；root最终容器／Human／固定输出组合70项通过，8.03秒（`t08-container-scope-root.log`）；提交 `a6c144e`。混合风险表格helper新增53项，保留独立范围与结构价格含义；相关206项通过，10.26秒，root109项通过，6.73秒（`t08-risk-table-final.log`、`t08-risk-table-root.log`）；提交 `41d0df1`。计数重叠；整来源表格角色消费仍待完成。

物理调用预检初始5失败／7通过，随后12项通过，4.10秒（`t08-current-call-red.log`、`t08-current-call-01.log`）；提交 `655ccfd`。未启动的来源失败准确结束，无供应商调用、重试或未知物理状态。既有相关组合225通过／11失败，因旧worker种子缺原始INPUT／Human登记（`t08-current-call-existing.log`）。合法worker夹具随后聚焦79项通过，14.96秒，保留全部189条原始断言及共享旧结果helper完整源码（`readiness-current-worker-all-01.log`、`readiness-current-worker-assert-audit-01.log`）；提交 `90132ec`。

准备库持有writer栅栏6项通过，10.35秒（`t08-run-fence-01.log`）；独立调用／栅栏组合18项通过，12.78秒（`t08-call-run-independent-review.log`）；提交 `d37aabb`。最终任务准入factory16项通过，8.14秒；扩大jobs／input检查51通过／1个旧自然来源夹具在任务提交前失败（`t08-job-admission-guard-regression.log`）；提交 `dfacba9`。真实Facade新增18场景通过，16.38秒（`t08-current-submission-01.log`），含拷贝后原文／同文元数据变更、缺审核／能力及已完成回执重放。最终Facade组合67项通过，39.61秒（`t08-current-submission-final.log`），独立审查未发现必改项；提交 `e7881cc`。T08／C03继续开放，含剩余自然来源／表格语义、操作／发送防护及后续公共接口／UI／语料／就绪阶段。真实供应商尝试仍0/48，用户数据库未迁移。

## PMA-R15 — T08实际风险操作与独立根计划夹具

完整来源风险控制现于AI及Human路径核对准确完整操作对应。最终粗体序号修复前，source选择1042项通过，61.10秒（`risk-control-agent-source-regression.log`）。root审查随后复现一个真实绕过：已识别的粗体ordinary JSON操作可与普通risk操作重复序号，仍误报COMPLETE；合法对照通过而冲突案例失败（`risk-control-agent-bold-red.log`）。修复仅改变已识别控制的序号读取。最终风险／控制／core／aggregate聚焦组合121项通过，16.37秒（`risk-control-agent-bold-green2.log`），含新增35项及旧8组准确字节／哈希固定校验；Ruff通过；提交 `48d2c3a`。中间一次命令指定不存在测试，未运行任何测试，不计为验收证据。表格角色接入仍待完成。

旧独立根组合夹具复制其他计划的Human候选，却无自身实际操作／输入证明。原失败保留于 `t08-library-independent-red.log`。现建立自身完整合成来源、原始输入及真实提取／审核命令。原57条Assert节点全部一致。library组合15项通过／1项未选中，7.66秒（`t08-library-independent-green.log`）；提交 `9254f5c`。未选中的四来源测试采用混合合成文字及非JSON字段拼写，并非四份原始盛新来源；其当前来源夹具仍待在不改变原始来源夹具、历史／golden的前提下校正。不主张自然语言语料验收完成。计数重叠；真实供应商发送仍0/48，用户数据库未迁移。

## PMA-R16 — T08有限来源载体与合成来源校正

闭合仓位句新增71项纯测试及16项完整wire测试。最终相邻组合191项通过，25.33秒（`readiness-position-directive-final-01.log`），含原input-store全部20项及原有准确自然语言仓位／保留句；提交 `ea57e0c`。真实MODIFY和同值RETAIN通过；数值错配、抹除修改、条件、引用、否定及额外来源文字均阻断。旧4组change及4组aggregate字节／哈希固定校验保持准确。原始纯测试及完整wire RED日志均保留。

有限现金／标题／独立事件文本载体初始6失败／13通过（`t08-continuity-carriers-red.log`）。独立审查发现真实低精度Decimal绕过，边界测试2失败／21通过（`t08-continuity-cash-precision-red.log`）。整数分解析已修复；最终相邻组合169项通过，2.74秒（`t08-continuity-carriers-final.log`），Ruff通过；提交 `b5a5d87`。中间一次命令引用不存在文件，未运行测试。识别不推断现金真实或事件已满足。

合成continuity来源工厂现将全部策略值以规范JSON输出，含null、布尔值及空集合，准确绑定原文并分开账户／范围语句。原始叙述／快照夹具文件、历史／golden及全部39条既有断言不变。新增8项合同测试初始失败（`t08-continuity-source-red.log`）；最终来源／raw／未知执行组合13项通过／3项未选中，2.38秒（`t08-continuity-source-final.log`），Ruff通过；提交 `19bdcd9`。较早扩大组合保留13通过／1项存储前驱失败：首来源当前覆盖完整，但后续完整替换控制尚未注册（`t08-continuity-source-green.log`）。该项继续待办，不豁免回归或宣称语料通过。T08／C03及后续阶段继续开放；真实供应商发送0/48，用户迁移0。
