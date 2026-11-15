# 计划监控保证：操作指南

本指南帮助检查原文覆盖、理解监控就绪，并识别仍需人工完成的步骤。工程证据不代表语料验收或实际安装就绪。

## PMA-O01 — 检查覆盖并修复准确原文

在 `/plans` 中对照已保存规则查看原文覆盖及阻断位置。不完整草稿可保留以供修正。就绪查询仅对原生校验合法、未审核、未启用且owner身份完整唯一的Schema5缺值DRAFT解释NEEDS_REVIEW；保留null／原文字节及未知事实，不授予权限，并保留升级原因、二次读取绑定及既有响应／准入预算。Schema6–9不完整草稿及owner身份缺失或重复的Schema5草稿仍返回不可用／503；该有限路径不通过删去owner声称部分支持（[R141](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r141--有界缺值草稿就绪查询不缩小规则范围)）。恢复完整的原文条件，另存新版本并审核准确版本后再启用。原文、参数或映射变化会使旧绑定失效。强制条件不存在通用忽略／背景豁免。4000-fen条款修复流程属于人工辅助修复，不代表原始自动提取通过（[R102](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r102--来源修正与实际版本切换取消保护)）。

明确路径文字仅有有限语法支持：十二类既有标量在严格JSON语法解析失败后，可按原生约束接受未加引号的值。未支持路径、否定和强制条件尾句仍阻断。四类完整账户事实可被识别为上下文；这不证明事实真实、不初始化持仓、不授予批准（[R132](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r132--有限的明确条件语法与账户事实识别)）。

## PMA-O02 — 使用归属明确的数据自动求值

准确的定义经审核，且适用的启用及数据前提满足后，受支持条件由既有运行时求值器处理。自动提醒流程证明原生评估可反复进行，无需新增计划审核或FACT记录。必需证据缺失会撤销当前就绪；准确恢复只能在原有效期内重新验证原证明，新的原生周期才产生新评估证据。打开或刷新就绪信息不会采集、求值或续期证明（[R101](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r101--首组原生浏览器就绪流程)、[R104](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r104--同页面原生数据丢失还原与恢复)）。

## PMA-O03 — 澄清定义并保留必要确认

缺失定义通过既有澄清／补充及审核步骤解决。未变的已审核定义无需每日重新定义；含义、范围、周期或绑定变化时，仍需适用的重新审核。澄清不代表运行时事件已发生。保留明确计划审核／启用、适用的持仓／成本及官方事实确认，以及逐机会例外批准。

已验证的H04登记流程仅覆盖Schema5 ordinary `REVIEWED_FACT/TRADE_DATE`准确叶子。A=true不满足B，明确登记的B=false保持为false；其它归属和范围不属于该已验收流程。这些例子证明具体行为，不提供总体人工步骤数或减少比例（[R103](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r103--精确逐叶登记与完整日历重评)）。

## PMA-O04 — 分别理解条件、执行及通知

完整FALSE结果表示条件已经检查且未满足。首次评估、证据缺失／过期及正常官方收盘等待各有独立原因；已验收的历史数据缺失流程返回UNKNOWN/AUTHORITY_UNAVAILABLE。库存变化可以保留行情比较，同时撤销旧执行资格。技术风险已确认义务可在当前比较变为FALSE后保留；这不证明可执行股数或卖出许可。QUEUED及历史DELIVERED回执不能证明当前通知服务有效（[R106](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r106--原生官方收盘等待与必需历史数据失效)、[R126](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r126--库存读取竞态保留条件结果而非过期执行资格)、[R107](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r107--独立风险浏览器工程验收)、[R105](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r105--原生通知回执与当前服务失效)）。

运行时要求重启时，失败进度及原期限保留至真实停止清理；心跳刷新不能掩盖STALLED或恢复执行资格（[R138](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r138--撤销后的失败进度保留至明确停止)）。就绪信息提供解释，不授予交易权限。

## PMA-O05 — 区分历史与当前资格

历史原文／响应字节、哈希及聚焦语义审核保持保留。历史零问题、局部更新就绪或公开JSON往返成功，不证明当前覆盖完整。录制样本保留准确的当前BLOCKED／UNRESOLVED结果，包括规范化丢失；被阻断的前序不能使新的当前链获得资格（[R137](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r137--录制历史语义保留当前阻断)、[覆盖契约](../specifications/monitoring/SPEC-source-condition-coverage.zh-CN.md#scc-s05--版本化证明与历史兼容)）。

## PMA-O06 — 核对实际验收与安装限制

工程检查、准确版本的有限语料验收及实际安装就绪分别报告。完整11门禁运行仍为FAILED（[R140](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r140--完整冻结回归保留七项失败)）。随后定向验证修复原草稿就绪503（[R141](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r141--有界缺值草稿就绪查询不缩小规则范围)）及五个联动／P3浏览器失败（[R142](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r142--完整来源浏览器正例保留原计划阻断)）。后者保留原缩略来源BLOCKED用例，另用完整来源和独立人工补充验证正例。仅该离线夹具的输入预算从50,000字符调整为既有界面声明的200,000字符，原超限失败保留。这是人工辅助流程验证，不代表原始自动提取验收或新的完整测试通过。完整T22/A12及最终验收仍开放。T15/C05及原始03/04正例验收仍阻断，包括F083；真实提取为0/48。不能据这些工程流程宣称某个已部署提取版本通过或任意自然语言准确率。持续入场前禁买取消仍不属于已实现范围（[R48](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r48--t13的用户选定范围边界)、[R136](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r136--联动回放审核与应用启动隔离)）。

唯一一次实际安装审计在打开SQLite前，以 `WAL_SIDECARS_UNAVAILABLE` 和 `PERSISTED_ONLY NOT_READY` 停止。schema、计划、评估及渠道事实均未采集；空数组不表示没有记录。该尝试未重试。这些检查未迁移用户数据库、真实启用计划、采集行情或发送外部通知。实际状态见[安装报告](../verification/plan-readiness-installation.zh-CN.md)和[主验收报告](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md)。
