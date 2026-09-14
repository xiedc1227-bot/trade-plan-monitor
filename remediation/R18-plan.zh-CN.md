# R18 独立复核与下次验收准备

英文原版为 `R18-plan.md`，本文是等价中文审阅副本。状态 **OFFLINE_REVIEW_COMPLETE / LIVE_NOT_AUTHORIZED / LIVE_NOT_RUN**。本步从 `c7f3e8a7e592af0a84606ab9834d8349892fc4e4` 开始，R17 修复当时仍未提交；保留更早的 12 项 tracked 改动及四份 R00 untracked 文件，不改写 R17 业务验收失败的结论。

## R18-1. 契约与诊断结论

- 将保留的三份 R17 HTTP 200 失败 DTO 送入 `createAIPlanApi`：接受新增 `diagnosticStatus` 后，必须保留 `PROVIDER_ERROR` / `INVALID_OUTPUT`、空草稿及阻断激活问题。检查省略/null/`RECORDED`/`WRITE_FAILED`；拒绝非法枚举或未知字段。将部分成功草稿样本与后端序列化比较，并让未解决政策继续阻断激活。
- 在实际组合逻辑与浏览器中检查 QUEUED → RUNNING → 失败、GET 失败、同一操作的 GET 恢复及停止本地等待。恢复可以增加 GET，绝不能再次发起付费 POST。停止本地等待不等于取消服务端任务。
- 沿生产管线及请求控制器追踪启动时的 `trade_cal`。保留有界 `REFERENCE_*` 分类与 `nextRetryAt`，恢复后清理；健康信息与日志不包含供应商正文、原文、异常文本或凭据。历史日历根因仍不能确定。
- 检查 `STRUCTURE` 指向标量、原文/映射字段级位置及来源证据校验。历史两份映射具体字段仍未知；新增标量缺陷是独立的离线发现。
- 核对 OpenAPI 快照、生成的 TypeScript、类型检查、生产构建、安装资源一致性、拦截本地 API 的真实 Chrome、定向 Python 测试及全部 16 项受保护哈希。历史 `reproduce-client-contract.cjs` 只证明旧版拒绝，不能用作修复后成功标准。未找到实现关联前，不把已中止的十只股票/252 日回测容量测试作为监控核心阻断项。

## R18-2. 可追溯实施与下一次有界会话

独立检查后，R17 修复提交为 `0f1dea5`（`fix: 修复提取契约与失败诊断`）。新日期有界启动器及离线边界测试提交为 `6a97265`（`feat: 准备次日独立有界验收入口`）。`scripts.r18_bounded_acceptance` 默认无网络干运行，只允许新的 2026-09-15 14:30–14:40 窗口、独立 `data/r18-acceptance/_session_claimed`，并沿用 R17 三次 AI / 60 次行情 / 900 秒物理调用闸门。其执行模式尚未使用。精确业务步骤、费用不确定性与失败停止规则见 `docs/verification/R18-execution-proposal.md`；需要用户重新直接批准，旧占位或代码短语不能替代授权。

## R18-3. 证据边界与交接

R18 检查仅证实离线契约行为及受控接线。R17 的完整 Python 非 live 测试在独立回测容量项中中止，本步没有机械重跑，也不声称完整通过。真实供应商权限、明日开市状态、费用、字面解析、人工审核、激活、新鲜行情求值及可见提醒，在另行获批会话前均未验证。若固定测试价格当天自然未触发，提醒投递为 `NOT_OBSERVED`，绝不伪造 PASS。不创建 R19 或定时任务。
