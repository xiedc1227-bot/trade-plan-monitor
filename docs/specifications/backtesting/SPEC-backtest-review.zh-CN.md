# 回测结果审阅 — P0 + 最小 P1

状态：用户于 2026-10-20 授权实施。英文为规范输入；[英文原版](SPEC-backtest-review.md)。细化[现有方案](PROPOSAL-backtest-result-ux.zh-CN.md)；已有引擎和结果完整性契约继续生效。

## BR01. 交付范围

通过概览、已完成成交、未成交原因、计划与来源、审计事件审阅已完成的监控闭环回测。最多两次导航操作从成交打开记录原因；一次操作从代表性诊断打开准确序号，支持前 100 条以外的记录。保留 summary/fills/details/equity 链接与历史结果读取器。

## BR02. 读取契约

新增 `GET /api/v1/backtest-runs/{run_id}/review-context`。选择器三选一：`fillId`（公开模拟成交 ID）、`eventId`（64 位小写十六进制）或 `sequence`（有界正整数）。可选 `relation=CAUSES|EFFECTS`（默认 `CAUSES`）、`limit`（默认 20，最大 100）、`cursor`。重复、未知或不兼容参数使用既有 `VALIDATION_ERROR`；运行或身份不存在使用 `NOT_FOUND`。游标绑定运行、选择器、关系、条数及选中记录身份与哈希。

响应字段：`runId`、`selector`、`relation`、`selected`（类型化闭环事件或 null）、`fill`（长期保留的类型化成交或 null）、`items`（类型化关联事件，不超过 limit）、`evidence`（最多 100 项确定性条件依据：`sequence`、`ruleId`、`at`、`rootOutcome`、`requirement`、`actual`、`reason`）、`availability=AVAILABLE|EXPIRED|NOT_RECORDED`、`projectionStatus=READY|NOT_READY`、`completeness=COMPLETE|PARTIAL`、`missingEventId`、`limit`、`hasMore`、`nextCursor`。序号范围为 1..420001。CAUSES 沿真实父边向根追溯；EFFECTS 按序号列出直接子事件。选中记录独立于分页。下一游标继续当前关系，不遍历整次运行。分页 JSON 小于 4 MiB，事件维持现有单项大小限制。`COMPLETE` 表示已加载页没有已知缺失关联，不替代 `hasMore`。

仅展示已物化结果。在同一读取事务内验证规范行哈希和索引／记录身份。GET 不访问供应商、AI、重放、实盘状态，也不构建索引。原因过期时保留仍存续的成交并明确提示部分证据。旧运行缺少索引时报告 `NOT_READY`，不表示没有成交。前端不扫描全部分页寻找原因。

## BR03. 派生索引与会计口径

明细暂存时在同一事务内维护派生事件索引，包括事件 ID、序号、父事件、规范明细 ID 和哈希。外键删除跟随明细保留策略。发布可见性继续由已有 materialized 标记控制。在迁移清单中登记可选增量结构，兼容旧结构且不重建规范数据。提供显式维护入口，每批最多读取 100 条保留中的已验证记录，并返回继续边界；不重写载荷、报告哈希或重建过期记录。历史结果保持原有读取能力。

本阶段不交付逐笔盈亏投影或排序。展示权威回执中的价格、数量、费用、释放成本和结果持仓，明确标注累计已实现损益，未知金额保持未知。`POSITION_LIMIT_ONLY` 不展示本金收益率、权益、回撤指标块。

## BR04. 组件与导航契约

`BacktestRunDetailView` 组合已有资源与审阅控件。`BacktestFillTable` 接收只读列表并发出选中成交身份。`PlanExecutionDiagnostics` 接收诊断／响应方式并发出序号；保留抽样提示和原有计数单位。`MonitorLoopTimeline` 发出选中事件／父事件身份。`BacktestEvidencePanel` 接收只读上下文、加载及错误状态，发出关系／继续／关闭／选择事件，展示结果、结构化依据及审计折叠区。`useBacktestReview` 管理 URL 选择、取消、过期请求隔离和关系读取。纯展示函数映射记录枚举，不生成 AI 解释。

现有结果 URL 使用 `fillId|eventId|sequence`、`relation`、`reviewCursor`。只允许一个选择器；无效组合显示错误且不查询。打开／关闭保留资源游标；浏览器前进／后退恢复选择。上一页仅使用访问过的签名游标。选中后焦点移至证据标题，关闭后回到触发控件；所有控件具有可见焦点和 44px 操作目标。桌面记录与证据并排，1024px 以下堆叠；验证 320/768/1024/1440px，使用现有设计变量。

## BR05. 验收与验证

- BR-A01：真实已发布成交和诊断序号可跨页定位原因，不下载整次运行；直接子事件和原因分页无重复，拒绝游标跨选择器／运行复用。
- BR-A02：明确区分证据缺失／过期、未知资金、`OBSERVE_ONLY`、执行受阻、抽样诊断和未知原因代码；不补造总数或单笔盈亏。
- BR-A03：选择变化或切换运行后不展示旧记录；深链接、前进／后退、关闭及键盘焦点有效；移动端页面无溢出，axe 无严重／重大违规。
- BR-A04：暂存／发布、哈希损坏、旧结构重新打开和保留策略测试通过；前端契约生成一致，单元测试／类型检查／构建及浏览器交互通过。

## BR06. 后续范围

全运行 `review-events` 筛选、指数日期筛选、经验证的逐笔盈亏、图表联动和运行比较留待后续 P1/P2/P3 阶段。本范围交付精确原因导航及可读结果；对抽样诊断的分类控件必须明确其局部作用范围。30/60 秒可用性目标待用户研究测量。
