# 单次监控规范化校验

状态：已授权实施，2026-10-21。基线：`ba4156e`。[英文主文档](SPEC-single-monitor-verification.md)。[分析](PROPOSAL-single-monitor-verification.zh-CN.md)。现有[共享契约](SPEC-monitor-evidence-sharing.zh-CN.md)继续有效。

## SMV01. 可用性前置条件

先定位当前 version-2 dashboard 503，再将响应用于性能基线。仅记录有界的失败阶段/类别，不记录凭据或证据正文。权威状态未知时仍须拒绝读取。仅重启不算根因修复。用确定性测试复现已定位的边界；在修改规范化校验前，使用真实所有者恢复成功读取并建立基线。

## SMV02. P0 表示与等价性

在 `MarketIndexSnapshot.model_validate_json` 后，每行只规范化一棵基本类型树。统一校验核心检查精确 snapshot/bar/tuple 类型边界、类型化 bar 排序、规范化 request 排序、全部带域隔离的 bar/request/root 哈希、公式定义与每条 fact 公式。复用该树生成完整规范化字符串。保留公开哈希辅助函数，以及 `validate_market_index_snapshot_integrity` 返回 `None` 的行为。保留 Decimal 限制、浮点拒绝、enum/子类边界、时区/微秒/Unicode 表示与 JSON 字面相等检查。每行结束释放树，不保留规范化历史。

仓储调用 `verified_market_index_snapshot_json(snapshot) -> str`。该辅助函数与原有仅校验完整性的函数共同使用 `_verified_market_index_value`；后者避免编码调用者不需要的最终字符串。只保留一套完整性算法，不新增 HTTP 接口。

仓储仍对全部历史候选（包括未选中候选）检查每个元数据列、schema version、provider revision、缺失 payload、head identity 与校验后排序。禁止完成证明缓存、仅哈希捷径、只读最新记录、减少保留数据、改变 API/schema/timeout/worker，或跳过模型校验构造对象。

## SMV03. 独立所有权

每次读取保留自己的观察时间、显式 `BEGIN` 事务、前后权威检查（token、generation、configuration、lifecycle、block/standby/absence、plans、dependencies、progress）、activation 重读和最多 2 次尝试。inventory、risk、calendar、completion proof 与当前可用性检查仍独立。socket cursor/replay/cadence 不变。保留 8 个受管读取、1 个物理校验、1 个不同输入排队所有者、64 MiB 原始输入保留上限、128 行批次和原有 15 秒截止时间。观察者取消不能放弃物理所有权；存储清理前必须排空物理工作。所有权未知及进度过期仍须拒绝。

## SMV04. 验收证据

与 `ba4156e` 比较冻结样本全部 2,008 个候选和完整输出；另外覆盖活动计划、非空 requests/facts、requests 重排、小 payload 与较大/接近上限 payload。测试未选中证据损坏、同大小/恢复时间篡改、缺失/BLOB payload、hash/domain/formula/provider/head 改变、规范化表示、数值/类型边界，以及删除完整性检查的变异。重复独立权威、90 秒/target/date/clock 边界、取消/排空、保留规则、完成竞态与并发上限验证。

同一冻结 2,008 候选样本至少执行 10 轮交替无插桩测量：wall 和 CPU 中位数改善 >=30%，wall 中位数 <=2.5 秒。2/8 monitor-plus-result 与错开到达场景的 CPU/wall 中位数退化须 <=10%。在新进程测量临时分配及进程峰值内存；单次读取峰值内存退化须 <=10%，原始输入上限不变。插桩剖析不计入延迟统计；不对小样本声称 p95。记录真实浏览器 monitor/result/heartbeat 成功流程、失败和业务写入，并运行确定性浏览器套件。

## SMV05. 条件式 P1 与交付

先剖析正式 P0。仅当剩余成本确实值得时，才评估有界、单次物理校验内的不可变表示复用，同时检查 key/equality/memory 与生命周期。禁止跨请求完成结果复用。如果 P0 达标而 P1 只增加不必要复杂度，以测量说明暂缓。提供双语实施任务、最终验证报告、原始观察与局限。保留已有改动与真实数据。本次请求不包含提交/推送授权。
