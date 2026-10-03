# 单一计划流程验证

## V01. 范围与状态

日期：2026-10-03，Asia/Shanghai。状态：**LOCALLY_VERIFIED**。本报告覆盖当前 [U01–U07 契约](../specifications/monitoring/SPEC-unified-plan.zh-CN.md)，不沿用已取代的日线计划验收。基线：`880c76fecfbf002bbc1b73d717c54d542429e7e8`。改动仅在本地，尚未提交；未修改生产数据库、忽略的配置、凭证、实时供应商、部署或外部发布。

当前提取和操作使用一个 `/plans` 工作台、Schema 5 和 `plan-extract-v8`。条件保留各自周期，完整日线与完整五分钟证据可共存。原文规定的纯提醒规则不得转换成退出交易指令。基本面仍为生成时审核背景。明确模拟一次应用正数100股整数倍完整数量，并校验 T+1、CORE、容量、报价、审核及修订。

## V02. 删除的在线入口

- 独立日线提取模块、页面、工作台、路由、composable及重复组件；全部 `/daily-*` 公开操作及在线计划类型选择。
- 未使用的在线旧版/显式编辑器和运行面板；当前提取不再分派到 prompt v1–v7 或旧候选类型。
- AI 供应商/凭证写入及连接测试 HTTP 操作。保留配置读取与启动时不可变配置。
- 真实持仓成交/关闭/确认及持续人工事件风险写入操作，以及孤立界面。保留既有历史读取和存储记录。
- 旧一次性 AI 验收运行脚本及专用旧输出测试。原始源码仍可从 Git 基线 `880c76fecfbf002bbc1b73d717c54d542429e7e8` 恢复；既有请求授权不绑定到新提示词。

## V03. 具体保留依赖

| 依赖 | 当前或历史使用方 | 保留原因 |
|---|---|---|
| 冻结 Schema 1–4 编解码和模型图 | 既有计划/版本读取及历史回测输入 | 保留原始字节、哈希解释和审计证据；旧计划不能作为当前计划启用或模拟。 |
| `ai/daily_review.py` 与 `dailyMapping` 字段 | 当前准确原文/内容审核及历史审核解码 | 共用原文范围、排除、人工补充和审核哈希；名称是兼容细节，不是第二条提取路径。 |
| `runtime/daily_service.py`、`web/daily_service.py`、`state/daily_repository.py`、`state/daily_accounting.py` | 单一当前评估器和原子模拟账本 | 复用已验证事务、风险时序、T+1、CORE、幂等和原因记账，不转换真实持仓。 |
| 已核验分钟规范化/聚合及正式日线序列/指标 | 当前条件与恢复 | 保留数据源截止时序、完整性、复权和公式证据。纯日线规则不依赖旧分钟指标。 |
| 旧决策/指数模块和显式读取 DTO | 冻结历史/回测重放及兼容历史解码 | 保留研究解释；移除在线操作路由及旧计划可执行投影。 |
| 真实持仓与人工事件风险仓库/读取服务 | 历史记录读取及隔离研究/恢复证据 | 删除写入界面/API，不抹除或重写历史库存和风险证据。 |
| 保留的限额验收辅助代码 | 行情/恢复假数据源测试及封存的历史预算门禁 | 保留具体依赖，不恢复已退役在线提取，不续签旧授权。 |

冻结语义语料继续通过冻结领域/读取校验验证准确值、单位、组合、未支持含义、遗漏及原文审核权威，不调用退役在线提取。当前 HTTP 适配器及原文/审核检查另行依据当前契约验证。不能把有意义的安全断言替换成伪造成功运行结果。

## V04. 已执行验证

| 门禁 | 结果 |
|---|---|
| 当前模拟晚期故障、完整 SQLite dump、重试/幂等 | 2项通过：记账/信号写入后及回执创建后失败，全部数据行保持不变。 |
| 冻结 Schema3 语义原文语料 | 27项通过：保留原始值、组合、遗漏及审核阻断。 |
| Python 单元及契约门禁 | 最终源码上2695项通过，4项实时测试取消选择（`pytest tests/unit tests/contract -q -m 'not live'`，21.68秒）。包含两种 HTTP 监测版本的当前入口检查。 |
| Python 集成门禁 | 最终源码上3289项通过，1项跳过，4项取消选择，耗时1435.31秒，未忽略任何测试文件。既有 `test_cursor_key_rejects_foreign_posix_owner_before_use` 需要 POSIX 文件归属语义，不能在 Windows 运行。取消选择的四项容量场景已单独通过，见下行。包含真实操作系统进程重启、原文/审核绑定、晚期激活、状态证明及原子回滚场景。 |
| 未变化的回测容量门禁 | 四项耗时容量场景已单独全部通过：十股票/252日重放、traced heap、稳定 BUY/T+1 退出字节，以及大查询/100k导出。604800行原始分钟数据及原有固定预算不变。最终集成检查只排除这四项已验证场景。 |
| 前端单元/类型/构建及浏览器流程 | 56个文件中的802项单元测试通过；类型检查及生产构建通过。保留的31项 Playwright 测试全部通过（55.0秒），包括当前提取/审核/激活、完整模拟、风险提醒筛选/确认、原文修改失效及打包进程重启。 |
| 生成 API/类型一致性、lint及文档 | `python scripts/generate_frontend_types.py --check` 在两种监测契约版本下通过。`ruff check src tests scripts` 和 `git diff --check` 通过。15对改动双语文档均有对应版本；新规范/报告的 U/V/H 章节编号、API 路径及数字一致。当前规范 OpenAPI 哈希仍为 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`；公开传输格式未增加证明元数据。 |
| 独立最终审核 | 已修复提取审计提交、旧记账旁的纯提醒访问，以及此前信号/风险和提醒自身激活日期的保留。发送/缓存/状态现依据原始一分钟源复核事实和全部已消费五分钟桶。完成证明绑定准确的不可变评估 ID、配置、运行代次、激活、日历及适用目标；GET 不生成证明，也不扫描全部评估历史。缺失日线日历或复权基础会阻断依赖证据。到期提醒在状态和取数中均不能继承旧风险；真正已锁存风险可延续。生产与状态共用周期判断，包含纯人工事实确认及仅重置条件需要分钟数据的场景。已发现的限定范围缺口均已修复并独立复查。最终受影响运行和状态组分别160项、28项通过；它们与完整集成门禁重叠，不计入其总数。 |

探索结果不计入最终总数。发现的陈旧截止时序、过宽分钟前缀要求、旧权限需求、提醒建模、旧可执行投影及过时夹具请求类型，均在最终检查前修正。新增回归保留否定技术事实、每个已消费组合风险证据 ID、重启后的提取来源，以及当前提醒旁不变的旧记账记录。

最终 Python 命令，从 `trade-plan-monitor/` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'
.venv/Scripts/python.exe -u -m pytest tests/integration -v -rs -m 'not live' -k 'not ten_symbol_252_day_replays_meet_capacity_budgets and not 252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget and not each_fixture_symbol_has_stable_buy_and_t1_exit_bytes and not large_queries_and_100k_export_meet_fixed_budgets' --maxfail=15
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

前端命令，从 `trade-plan-monitor/web/` 执行：`npm run test -- --run`、`npm run type-check`、`npm run build`、`npm run test:e2e`。

推送前文档维护复核：2696项单元/契约测试通过（排除4项真实服务测试）、37项针对性集成测试通过、前端802项测试及类型检查通过。冻结 T059 发布报告与操作指南现位于 `tests/history/t059`；未改变的验收/双语/密钥断言之前校验准确 Git 源码 SHA-256。新增字节变更拒绝回归，不把历史验收绑定到当前流程。

## V05. 限制

确定性测试使用隔离临时 SQLite 数据库、假 SDK 证据，或通过真实 AI 适配器的 HTTP mock transport。它们不认证实时 Tushare/AI/Webhook 可用性，也不批准用户策略。读取只能校验本地已观察、已准入证据；尚未观察的远端日线修订要在下一次取数后才能发现。历史验收不证明当前行为。不静默升级历史审批，未执行生产数据迁移/重置。本地验证不包含人工 NVDA 和当前真实环境上线证据。
