# 验收：plan-monitor-assurance

状态：实施中 — 2026-10-27。用户已批准PMA-D01–D06、全部实施任务及共用48次真实提取上限；仍禁止迁移用户数据库。基线 `a5546ad`。[英文规范版](2026-10-27-plan-monitor-assurance.md) · [任务](../../tasks/plan-monitor-assurance.zh-CN.md)。

## PMA-R01 — T01契约与基线

既有基线：62项单元通过，3.00秒；21项当前P3审核／操作／通知集成通过，6.84秒，1条既有Starlette警告。独立历史反例夹具／测试10项通过，0.52秒；修正1条常规长行后最终Ruff通过。这是83项既有及10项新增历史边界检查，不是当前遗漏防护验收，不能证明真实供应商准确率。

固定夹具复现两种语言及COMMENTARY/HISTORICAL/ACCOUNT：145条款／128绑定变为146／128，候选不变、历史零问题；AMBIGUOUS仍被原验证器拒绝。固定来源／证据哈希变化及无授权。新当前防护测试尚未实施，不声称已通过。契约固定新证明／模型归属、可信历史切换、下个可用0028预留、API／错误边界及物理次数记账。

当前日志保留在忽略目录 `.pytest_cache/pma-v01.log`、`.pytest_cache/pma-v01-integration.log`、`.pytest_cache/pma/t01-baseline.log`、`t01-baseline-ruff.log`，最终验收归档准确原失败／结果及命令。没有用户数据、live供应商、迁移、启用、库存／成本确认或通知发送。保留 `tasks/plan.md`、`tasks/todo.md`。

## PMA-R02 — 剩余验收

T01–T06及C01–C02完成，T07–T24及C03–C08待完成。不能从纯测试或批准契约推断完整流程覆盖已完成。真实尝试0/48，调用前只读调查原文语料资格。工程完成、准确版本真实提取、实际安装就绪将分别报告。

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
