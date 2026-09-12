# 规格：source-treatment-review（R11 混合原文闭环）

`SPEC-source-treatment-review.md` 为英文正式版；本文为等价中文副本。日期：2026-09-12。按授权修正 R08 C01/C02/C09/C10 与 E04/E07；参见 ADR 0006。

## S01. 目标与兼容性

完成既有原文 → 部分草稿 → 当前内容复核流程，支持混合的交易、持仓和产品边界语句。`plan-extract-v1/v2/v3/v4` 输出图、模板和冻结摘要保持不变。新 API 保存使用 `plan-mapping-v2`，包含服务端推导的 `source_processing` 快照（`source-processing-v1`）。v4 提取仍返回 `plan-mapping-v1`；这是服务端复核扩展，不是赋予模型输出新的权限。历史 v1 复核快照保留原解释及证据哈希。

## S02. 有限处理契约

服务端从完整匹配的相邻原文子句推导类型化记录，保留 Unicode code-point 区段。`INVENTORY_ASSERTION` 接受有限语法 `<symbol>当前持仓<integer>股，均为测试日前已持有且当日可卖；`（子句之间允许空白）。symbol 和数量是参数，不固定为验收值。记录 symbol、原文总量/可卖量、测试日前持有的结算声明及独立持仓确认入口。独立 symbol 子区段映射到当前精确 `symbol`；数量和结算子区段继续可见。原文绝不创建 lot、期初余额、成交或已知库存。

`PRODUCT_GUARANTEE` 接受完整双子句 `提醒及确认收到提醒不代表成交，未登记成交时持仓不变。`，只绑定 `alert-position-isolation-v1`：普通提醒、重试和已读不改变持仓，只有独立持仓命令可以改变。契约由既有显式判断/发件箱、提醒已读和持仓服务实现，并必须有集成回归证据。它不是通用的 `CONTRACT` 字段绑定豁免。

每个处理记录含精确区段、类型、受支持契约 ID 和确定性 treatment ID。保存/读取/复核时，持久化列表必须等于服务端重新推导的结果。任意 ID、错误数量/symbol/可卖语义、否定、附加条件、不完整子句对、缺失记录和篡改区段都会拒绝或保留必需未解析问题。完整匹配防止交易条件夹带在持仓/产品子句中。包含保留语族 `当前持仓`、`均为测试日前`、`提醒及确认收到提醒` 或 `未登记成交时` 的无法识别子句，即使被提供商局部映射到计划字段，仍保持 `UNRESOLVED_MIXED_SOURCE`。这是有限语法，不是通用中文语义分类器。其余子句保留原有字段/结构映射和语义检查。没有 IGNORE 或通用 ACK 桶。

## S03. 内容复核与运行时就绪

原文数量为 `0..9007199254740991` 内的精确整数，不按整手取整；超限值保持未解析，不带着精度损失进入 Web 边界。该边界不豁免独立登记接口自己的规则。

两类记录均要求 `CONFIRM_SOURCE_TREATMENT`，通过 `binding_path=source_processing.treatments[index]` 绑定服务端必审问题及精确快照。对持仓，它确认提取出的声明及独立登记路径，**不确认账本真实完整**。可见指引要求选择 as-of 日期、登记/指定完整账本，再调用 `POST /api/v1/position-inventory-confirmations`。日期、激活、重复、冲突及成交量历史政策继续由人工明确选择。仅原文缺失选择时不得取得 reviewId。

所有当前映射、处理记录和补充政策完成审核后，完整草稿取得有效 reviewId，内容 `canActivate=true`。公开激活接口仍受 R12 表单能力门禁拒绝。`executionReadiness=NOT_EVALUATED` 明确独立存在：消费者查询 `GET /api/v1/position-inventory?symbol=...&asOfTradeDate=...`；未独立确认时是 UNKNOWN/null，仅阻断依赖库存的 BUY/SELL。纯 RISK_ALERT 不要求库存。实际持仓变化不会让内容复核失效；运行时每次求值消费当前账本 revision/cutoff。登记、重试或新 key 再确认不得把同一期初余额重复计入。

## S04. 持久化、API 与身份

复用既有不可变版本、JSON 映射存储、问题/解决记录及事务 revision 校验。来源处理不需要数据库迁移或库存写入。新 `plan-review-evidence-v2` 哈希包含完整 v2 映射/处理快照、补充值/时间及必审问题；v1 哈希原像不变。编辑必须确认精确新版本；旧哈希、旧处理身份、伪造已解决列表及篡改持久化处理均失败关闭。计划详情和保存返回类型化 camelCase 处理记录，R12 可直接展示，无需自行分类。

V2 `REPLACED_BY_REVIEWED_CONTENT` 要求保存新的受支持版本，不能用作当前快照的已读确认。孤立补录不能消除未解析来源问题。提交的无效映射返回 422；存储证据损坏沿用不泄露内部信息的 500 `INTERNAL_ERROR`。来源映射确认仍是人工语义判断，并非自动证明任意原文就代表所提交的交易规则。

## S05. 验收原文与验证

新 fixture 保存协调任务提供的逐字中文原文及换行。唯一替换是 `测试股票` → `003043.SZ`，在原文旁明确记录。此前 `_ORIGINAL_SOURCE` 是派生简写 fixture，不是这份逐字原文；保留其历史测试并更正描述。

验证仅原文缺选择；当前内容审核完成与公开激活拒绝；独立库存 UNKNOWN → 已知100及幂等重试/再确认；未知库存下纯风险；提醒/已读不改变持仓；附加条件/否定/错值/遗漏子句/处理记录/伪造契约及旧复核。保留此前 69 项聚焦测试与冻结 golden 检查。使用 `.venv/Scripts/python.exe -m pytest` 执行新增目标文件及既有 AI、计划 API、持仓和显式运行时组，不跑长容量套件。对变更文件运行 `.venv/Scripts/python.exe -m ruff check`，并运行 `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`。

## S06. 实施顺序与边界

1. 类型化服务端处理和有限识别；聚焦对抗单元测试。
2. 版本化问题/哈希、持久化/API 集成及精确完整原文验收。
3. 相关兼容/运行时回归、生成 API 契约、双语报告与交接。

遵循既有 Python 四空格/snake_case 和严格 Pydantic 边界模型。领域识别放在 `ai/`，传输放在 `web/`，持久化解决记录校验放在 `state/`；不增加依赖。仅使用合成数据与临时 SQLite。禁止真实 AI/行情/网络/通知/交易/生产数据、push、R12 任务或表单。只暂存本次修正，保留用户既有 hunk。
