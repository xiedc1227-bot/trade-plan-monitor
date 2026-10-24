# 大盘联动P0：实施验证

## MLV01 — 范围与状态

用户于2026-10-24批准MLP-D01–MLP-D06并要求实施P0；后续“直接使用官方规则”指示已落实到QP06。基线：`c7378a4`，分支 `main`。MLP-T01–MLP-T19及MLP-C01–MLP-C07全部完成并通过本地验收。全量回归失败均已解决，下文记录准确失败用例及相关测试集的重测结果。本次验收覆盖本地实现，不代表部署或真实供应商认证。

现有 `/plans` 流程已接受严格的Schema 6日线联动BUY/TACTICAL计划、完整来源政策和Q0。共用纯政策计算指数状态、对齐的个股／指数强弱、S0/S1/S2路径及合法整笔数量。真实运行时保存不可变判断；来源修订使读取、完成证明、发送和执行权限失效。研究回放及监控循环回放均消费冻结输入。既有Schema 1–5序列化、独立提醒、CORE/T+1记账和明确模拟操作保持回归覆盖。

[任务](../../tasks/market-linkage-p0.zh-CN.md) · [契约盘点](../specifications/monitoring/CONTRACT-market-linkage-p0.zh-CN.md) · [操作指南](../operations/market-linkage-p0.zh-CN.md)。

## MLV02 — 分阶段验收证据

| 检查点 | 任务 | 证据与结果 |
| --- | --- | --- |
| MLP-C01 | MLP-T01–MLP-T03 | 严格联动／固定联合类型、必填但可为null的草稿字段、来源定义参数、有界展开条件树、准确旧格式／哈希及排除D日的指数最低价。`test_market_linkage_contract.py` 与既有领域／指数测试通过。 |
| MLP-C02 | MLP-T04–MLP-T06 | 大盘优先级与三值谓词、严格相等边界、21个对齐交易日、5/20收益、当日MA20、S1/S2全部组成及六条路径通过政策测试。独立进程内把 `<` 变异为 `<=` 导致4项预期失败，证明相等测试能捕获变化；仓库代码未被变异。 |
| MLP-C03 | MLP-T07–MLP-T09 | 合法数量枚举、不向上取整／不按额度缩量、官方规则日期、数量／证据摘要、完整八项展开定义审核、提取及后续继承通过。完整原文与提示词预算保持不变。 |
| MLP-C04 | MLP-T10–MLP-T12 | 临时SQLite重启、冻结数量、原子消费、修订失效、真实生产适配器／共享指数采集通过。存储／API／回放／一致性与统一运行时组合检查：43项通过，21.79s。 |
| MLP-C05 | MLP-T13–MLP-T15 | 当前来源的读取／发送／完成证明防护及只读数据库断言通过。六条真实证据路径的实时／冻结政策判断一致。联动历史提取、明确审核、输入复制、实际任务、任务完成、报告发布及重启通过；最终回放测试：3项通过，57.97s。研究报告包含数量300、下一交易日不可当日执行及零交易原因。 |
| MLP-C06 | MLP-T16–MLP-T18 | 两个API配置保留准确投影的旧模型／路由；28项契约检查通过，31.25s。前端：86个文件的1,232项测试通过，类型检查和949模块生产构建通过。固定版本Chrome的新旧流程均通过：2项，20.0s。 |
| MLP-C07 | MLP-T19 | 全量后端单元测试：3,598项通过，53.97s。非live的集成／契约／历史／原生／回放／浏览器全量运行结束：4,459项通过、16项失败、1项平台跳过、4项live排除，4,532.73s。修复后16项失败统一重测全部通过（18.82s）；相关恢复／工作台／契约79项通过（18.84s）。Ruff、差异空白检查、14对双语文档及生成物摘要检查通过。准确处置见MLV05。 |

阶段测试存在重叠，不能相加当作不重复测试总数。初始契约红灯阶段和中间失败均已修复后继续推进。没有降低断言、超时、资源预算或产品限制。

## MLV03 — 可复现命令与诊断

命令从 `trade-plan-monitor/` 执行，使用已安装依赖和隔离的 `.test-tmp/mlp-*` 目录。前端使用既有固定版本Chrome。

```powershell
.venv/Scripts/python.exe -m pytest tests/unit -m "not live" -q -p no:cacheprovider --basetemp .test-tmp/mlp-all-unit-final
.venv/Scripts/python.exe -m pytest tests/integration tests/contract tests/history tests/native tests/replay tests/browser -m "not live" -q -p no:cacheprovider --basetemp .test-tmp/mlp-all-integration
.venv/Scripts/python.exe -m pytest tests/integration/test_market_linkage_api.py tests/integration/test_backtest_service_contract.py tests/integration/test_openapi_snapshot.py -q -p no:cacheprovider --basetemp .test-tmp/mlp-api-parity
.venv/Scripts/python.exe -m pytest tests/integration/test_market_linkage_replay.py -q -p no:cacheprovider --basetemp .test-tmp/mlp-loop-final6
.venv/Scripts/python.exe -m ruff check src tests
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts tests/e2e/condition-plan.spec.ts
```

根目录单次pytest收集碰到既有同名模块冲突：unit/integration内均有 `test_backtest_service_contract.py`。分开执行unit和其余全部测试目录保留覆盖，不跳过用例。Windows沙箱的asyncio阻塞在 `socket._fallback_socketpair`／`accept`；相同隔离测试在沙箱外执行。两类受阻运行均不记为通过。

中间修正：折叠重复模型及命名类型提示大纲，使完整原文证据保持在既有50,000字符预算内；不支持版本测试改用7，畸形版本6另有专门拒绝测试；依据此前BR02批准，把既有review-context路由补入旧契约白名单。仅结果库的BT019重启检查改为识别准确受支持的结果／审核结构，不强制要求可选任务表；未迁移用户数据库。API测试改为既有422校验响应。回放夹具修正准确来源ID、时序及固定任务时钟，保留全部权限检查。

已知非失败诊断：本地Python启动器路径提示、Starlette/httpx弃用提示及既有浏览器服务Windows管道关闭回调提示。浏览器断言、请求／控制台隔离检查通过。没有安装或升级依赖。

## MLV04 — 界面、审查及发布边界

联动浏览器流程使用已构建前端与真实隔离HTTP/SQLite服务：提取 → 修改／审核 → 保存 → 明确启用 → 登记合成期初持仓 → 确认并冻结300股 → 恰好消费一次 → 展示持续P1例外阻断 → 独立五分钟提醒。最终库存为CORE 100／TACTICAL 300，共400股。320/768/1024/1440视口无横向溢出。已目视检查阻断状态截图，数量、证据及无额外交易动作可读。

五维审查覆盖正确性、来源／权限校验、共用政策归属、有界采集／序列化和可维护性。测试可捕获严格相等变异、过期来源权限和数量摘要篡改。生成的OpenAPI/TypeScript摘要记录在U-MLP，没有新增路由或依赖。

两类P1例外保持阻断。官方数量规则版本为 `cn-equity-buy-grid-2026-07-06`；更早日期及不支持证券为未知，模拟仍使用100股整数倍。Q0和完整S0／政策来源含义需要明确审核。未执行供应商凭据配置、BSE日历／指数就绪认证、实时数据认证、用户数据库操作、部署或人工读屏认证。目前没有等待用户决定的新策略事项。

最终针对性修正：已知BROKEN状态报告 `MARKET_BROKEN`，不再附加错误的缺失大盘原因（126项政策／运行／一致性测试通过）。真实供应商把盘中／日线内容合成不递增的修订哈希；日线内容不变的重新采集保留权限，真实日线修订仍使权限失效。只读修订检查和下一交易日实际300股模拟覆盖该区别；API／存储／路径检查通过（25项，11.29s）。最终较小修订号、生产适配器及实际回放任务测试通过：39项，79.70s。全量回归早于这些最终修正启动；最终单元／针对性／浏览器重跑覆盖这些修正。

[已检查的阻断状态截图](assets/2026-10-24-market-linkage-blocked.png)。

全量回归修正：结果／审核结构的精确校验现由重启及经备份验证的任务表增量迁移共用，并覆盖迁移后表清单。既有准确表集合断言现包含已经实现的 `backtest_review_event`。全部任务、结果及迁移回归通过：83项，17.30s。保留备份授权与完整性检查。

既有日线调度测试适配器已实现明确的联动计划登记接口，并断言非联动计划登记空元组。真实SDK归一化／调度链路及统一运行时合并通过：31项，17.45s。

既有能力传输断言已纳入获批的 `supportedSchemaVersions: [5, 6]` 和 `linkedExecutionVersion: "condition-plan-v2"` 字段，并保留此前所有字段的精确断言。该完整测试文件通过：6项，3.59s。监控证据共享回归也独立通过：20项，45.06s。

## MLV05 — 最终回归处置

耗时75分钟的全量运行在最终修正前已加载模块。这里如实保留首轮结果，不将其描述为一次全绿运行。已从该运行提取完整失败清单，针对最终文件统一执行：**16项全部通过，零失败**。其余全量用例均通过，包括全年容量／内存和大结果集查询／导出预算。唯一跳过项为Windows上的既有POSIX文件所有者检查；4项排除用例需要真实服务。

| 首轮失败 | 修正及最终证据 |
| --- | --- |
| 2项结果／任务结构用例 | 修正准确结果／审核结构和增量迁移；83项相关用例通过。 |
| 10项OpenAPI／TypeScript及实际挂载契约用例 | 同步获批联动结构投影及既有BR02路由清单；28项专项检查及全部准确失败用例通过。 |
| 1项日线调度用例 | 为非联动测试适配器补充明确联动计划登记；31项调度／运行用例通过。 |
| 1项能力传输用例 | 精确响应预期包含两项获批字段；该文件全部6项用例通过。 |
| 1项降级权限清理用例 | 旧断言错误地等待监督任务结束。既有SPEC-monitor-runtime要求已进入DEGRADED的实例意外退出后执行恢复。测试现在控制重启边界，在原5秒限制内验证原始异常、完整清理、业务行不变及新实例恢复已安排。生产恢复行为未改动。 |
| 1项工作台回放用例 | 留存证据显示历史夹具任务被当前时钟的清理流程删除。夹具现将既有受理／任务时间用于真实保留期清理，并等待清理结束后断言公开任务／结果读取。没有绕过保留期规则、超时或权限检查。两种响应模式及重启读取均通过。 |

最后两项修正、监控循环契约和监督任务回归合并通过：79项，18.84s。全量失败清单重测：16项，18.82s。最终代码改动另有3,598项单元、39项运行／生产／回放及两条真实浏览器流程覆盖；后续只调整测试和文档。没有未解决的失败用例。

[首轮全量日志](assets/2026-10-24-market-linkage-full-regression.log) · [16项修复重测](assets/2026-10-24-market-linkage-failure-recheck.log) · [最终单元日志](assets/2026-10-24-market-linkage-unit.log) · [恢复及工作台日志](assets/2026-10-24-market-linkage-recovery.log)。

## MLV06 — 提交前最终复查与修复

用户要求重新审查 P0 全部改动，并授权直接修复、测试和提交。MLV01–MLV05 保留前次实施结果，本节记录随后的复查。检查覆盖六份规格、MLP-T01–MLP-T19、契约边界、新增／修改实现及验收测试；没有改变策略决策。

| 问题 | 修复及回归证据 |
| --- | --- |
| RV01 — 个股原值重取导致冻结信号失效 | 将个股／确认的语义内容与采集编号／时间、复权截至日期分开，并归一化等值 Decimal 表示。真实价格／基准修订仍使信号失效。真实 SQLite 次交易日用例证明：证据不变可整笔模拟300股，最低价变化则阻断执行。 |
| RV02 — 正常状态科创板数量不足被报告为P1例外 | NORMAL_TRANSITION 下 Q0 为100、最小量200时，现返回 `MARKET_QUANTITY_BELOW_MINIMUM`；仅规定的 WEAK／BROKEN 例外使用 `P1_EXCEPTION_REQUIRED`。算术及界面测试通过，QP02／操作说明明确区分。 |
| RV03 — 否定采用的展开定义可能匹配来源授权 | 中英文明确不采用前缀拒绝展开定义绑定。两项原失败用例及正常来源／审核流程通过。 |
| RV04 — 证据卡缺少截止时间及嵌套比较 | 展示上海时区证据截止时间、编号的嵌套 ALL／ANY 证据、实际操作数／日期及人工核验要求。测试覆盖嵌套内容和数量解释；界面不新增执行动作。 |
| RV05 — 仅人工事实的日线回放丢失复权缺失原因 | 单计划回放现使用既有共享数据依赖，包含 OFFICIAL_DAILY_CLOSE。S0 仅含 REVIEWED_FACT 时仍报告 `PRICE_BASIS_UNVERIFIED`。 |
| RV06 — 提取指引及生成说明漂移 | 三个提示词构建器一致选择 condition-plan-v1/v2。修正联动模型说明后重新生成两个 OpenAPI 快照；TypeScript 内容与 MLV05 相同。U-MLP 记录当前摘要。 |
| RV07 — 提醒确认边界及浏览器夹具 | 按钮现将契约允许省略的 `acknowledgedAt` 与 null 一样处理，两种形式均有回归测试。另经浏览器诊断确认，夹具缺少 V2 事件流，反复重连使命令预检查被取消。夹具现接入真实 `RuntimeStatusEventStream`，流程在确认前要求连接正常；生产协议取消保护保持不变。 |

关键边界测试均先在错误实现上失败，修复后通过。对新 WEAK 最小数量分支在独立进程内存中故意反转，得到一项预期失败；未修改仓库源码。没有删除断言、放宽超时，未访问供应商或用户数据库。浏览器确认等待现明确限制为10秒，整体流程仍保持原120秒上限。

最终验证：

- 后端单元测试：**3,599项通过**，53.11s。
- 相关集成回归：**1,057项通过／4项失败**，710.05s。四项均为重新生成前读取的精确生成快照不一致；随后完整受影响契约／API套件 **41/41通过**，35.80s。没有未解决的失败。范围覆盖 market_linkage、unified、monitor_loop、plan_preparation、daily_plan、提取诊断、回测任务／结果／迁移／服务、OpenAPI、传输、工作台及共享指数运行。
- 前端：**86个文件共1,236项通过**，9.70s；类型检查及949模块生产构建通过。
- 真实浏览器：旧计划与联动流程各重复两遍，**4项通过**，35.9s。保留先前超时诊断；修复后的运行验证真实事件流、来源审核、明确启用、整笔数量模拟、独立提醒确认及响应式布局。
- Ruff、生成产物检查、空白检查及 **14组双语文档** 的章节编号和本地链接检查通过。没有改变依赖、路由或生产资源预算。

各组计数存在重叠，不得相加为独立用例总数。先前75分钟运行仍作为无关年度容量／内存及导出测试的证据，未重新运行或改称新的全量零失败运行。P1例外、实时供应商认证和部署仍不在本次验收范围内。

[复查单元日志](assets/2026-10-24-market-linkage-review-unit.log) · [集成日志](assets/2026-10-24-market-linkage-review-integration.log) · [契约重测](assets/2026-10-24-market-linkage-review-contract.log) · [前端日志](assets/2026-10-24-market-linkage-review-web-final.log) · [通过的浏览器重复验证](assets/2026-10-24-market-linkage-review-browser-accepted.log) · [浏览器诊断](assets/2026-10-24-market-linkage-review-ack-state.log) · [变异实验](assets/2026-10-24-market-linkage-review-mutation.log)。

[最终已检查的证据卡](assets/2026-10-24-market-linkage-review-blocked.png)：截止时间、整笔数量回执和持续例外阻断清晰可读。

保存的文本日志仅规范化行尾空白，失败详情和结果均完整保留。
