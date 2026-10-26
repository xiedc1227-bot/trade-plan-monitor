# 验收：market-linkage-p2

状态：PASS — 2026-10-26。MLP2-T01–MLP2-T18 及 C01–C06 已完成；MLP2-A01–MLP2-A12 在批准的非 live 范围内全部通过。基线：`8db00c425706945d69a39ae0d3ffe1d85348d626`。用户于2026-10-26批准六项决策及实施。[英文规范版](2026-10-26-market-linkage-p2.md) · [任务](../../tasks/market-linkage-p2.zh-CN.md) · [操作说明](../operations/market-linkage-p2.zh-CN.md)。

## MLP2-V01 — 契约与算术阶段

T01 原数量／例外基线：74项通过，0.65秒。T02–T06 专项政策和历史编解码／哈希回归：303项通过，2.41秒，包含最初46项 P2 单元用例。初始核心用例在实现前失败；后续边界用例按独立预期数量及金额分值核验。C01/C02 通过。各组有重叠，不能相加视为独立用例总数。

Schema8 须显式选用，使用 condition-plan-v4、pretrade-policy-v1 和审核哈希 plan-review-content-v5。严格模型拒绝固定／衍生数量混用、不完整档位、不安全算术和隐含费用／门槛。来源定义的档位先形成 Q0，再应用不变的 P0/P1 大盘系数。合成费用样例验证最低佣金、逐项向上取整、包含关系、范围／期限、等号、溢出及收益风险算术。

## MLP2-V02 — 来源、存储与执行阶段

P0/P1/P2 来源审核：27项通过，1.46秒。初始 P2 生命周期／存储／权限组：57项通过，3.21秒。实际 API 审核→启用→运行→模拟覆盖普通、WEAK_MINIMUM 和 BROKEN_STRONG。扩展 P2 集成组在最终工作器／来源补测前通过79项，42.77秒。REQUIRED 在报价175时阻断、161时恢复，不改量；PREVIEW_ONLY 不否决交易。实际风险 SELL 模拟在不可能满足的 BUY 门槛下仍成功。只读预览拒绝客户端价格，不能授予权限。

存储复用版本化 JSON，无需 SQL 结构迁移。新可选字段不写入旧记录。临时 SQLite 重开、篡改、版本冲突、并发消耗及原子回滚均有覆盖；实际用户数据库未改动。历史 OpenAPI 精确比较只剥离枚举列出的 P2 新增项，保留原路由／字段的全部断言。

## MLP2-V03 — 回放与浏览器阶段

带 REQUIRED 费用的回放／并发组：26项通过，27.93秒。真实冻结工作器、发布及投影检查连同 P1 回归：14项通过，157.50秒。两条路径均保留明确授权事件及独立操作、实时状态隔离，以及记录／研究假设来源。未来接收／可用时间变异不影响过去决策。相同 OHLC 仅条目 ID 或 Decimal 尾零不同保持已消费权限；技术值修正则改变权限。

P0/P1/P2 Chrome 流程在最后文案修整前通过15项，3.1分钟，覆盖来源缺失／人工审核、两条例外、费用模式、门槛失败／恢复、修正、消耗和重载。320/768/1024/1440 宽度无横向溢出，外部请求审计为空。最终界面还使用可读且去重的费用原因，并在计划版本变化时拒绝迟到响应。最终组合流程15项通过，3.2分钟；展开可读费用明细后，6项 P2 流程再次通过，1.5分钟。已检查截图：[WEAK_MINIMUM](assets/2026-10-26-market-linkage-p2-weak.png)、[BROKEN_STRONG](assets/2026-10-26-market-linkage-p2-broken.png)。

## MLP2-V04 — 失败与修复

- Windows 受限环境的 asyncio socketpair 初始化在业务逻辑前停滞。栈转储定位环境限制；中断受影响命令后，在允许本地通信的环境重跑，使用工作区临时数据库。中断不算通过。
- 默认合并收集遇到现有单元／集成模块重名；importlib 收集会破坏既有裸 fixture 导入。因此 V06 将单元、集成、契约／回放目录分进程运行，保留全部用例，仅排除 live。
- P2 完整 schema 最初超过现有50000字符提取预算。提示词改用既有具名 schema 摘要表示，运行时仍完整严格解析；44项预算／来源／安全用例通过，2.36秒。未提高预算。
- 长未解决来源理由超过通用 API 错误字段512字符。现在限制摘要长度，完整 daily 审核依据仍保留，API 用例验证两者。预览冲突改用既有类型化错误契约。
- 非法小数字符串原先抛出 InvalidOperation，现在返回校验错误。可空草稿保留集合边界；P2 技术值统一 Decimal 格式，等值书写变化不再导致权限失效。
- 浏览器夹具最初在候选出现前发起例外预览。现在等待真实候选并断言请求身份；生产代码没有绕过当前依据要求。
- P2 研究完整证据在信号间重复，超过既有32KiB结果限制。现在对联动和交易前依据去重，解析全部引用后重新校验完整信号；原限制、篡改断言及 Schema7 表示保持不变。
- 当前能力／部分提取夹具仍预期 Schema5–7 或 plan-extract-v10。仅更新明确新增字段／版本，历史快照和原规则断言继续固定。已批准的预览路由及生成契约摘要已登记到路径白名单和两份统一规格。长周期集成进程此前加载的是旧夹具；由此产生的14项失败均已在当前代码通过复验。
- 目标验证最初额外限制只能采用区间端点，这并非已批准要求。现在接受原文明确定义、位于审核压力区间内且遵守端点包含定义的目标，拒绝区间外目标，不推断目标价。

既有 Starlette/httpx、故意重复 ZIP 及 SQLite 表达式索引反射警告保持可见；保留 Windows 下既有 POSIX 所有权跳过项。未新增 skip/xfail、依赖、放宽超时／容量／载荷上限或调用 live 供应商。

## MLP2-V05 — 最终回归台账

每项已观察到的失败均已在当前代码通过复验。测试组有重叠，不能相加为独立用例总数。完整集成进程启动早于最后契约修复；最终专项组及准确失败节点复验覆盖修复项和新增用例。命令见双语任务清单 V01–V08；准确失败／容量命令保存在核对产物中。

| 检查 | 已执行证据 |
| --- | --- |
| 最终后端单元 | [3712项通过，2条警告，66.88秒](assets/2026-10-26-market-linkage-p2-unit-final.log) |
| 契约／回放目录 | [13项通过，排除4项 live，9.73秒](assets/2026-10-26-market-linkage-p2-replay-contract-final.log) |
| 最终 P2／历史 API 组 | [115项通过，175.29秒](assets/2026-10-26-market-linkage-p2-focused-final.log) |
| OpenAPI／循环契约 | [27项通过，33.53秒](assets/2026-10-26-market-linkage-p2-contracts-final.log) |
| 最终前端 | [91文件／1270项通过，13.33秒](assets/2026-10-26-market-linkage-p2-frontend-final.log) |
| 浏览器 | [15项 P0/P1/P2 流程](assets/2026-10-26-market-linkage-p2-browser-all-final.log)；[6项最终 P2 流程](assets/2026-10-26-market-linkage-p2-browser-p2-final.log) |
| 类型检查／构建／最终 UI 测试 | [通过；8项专项测试](assets/2026-10-26-market-linkage-p2-ui-build-final.log) |
| 生成契约／质量 | [两种配置均一致，Ruff通过](assets/2026-10-26-market-linkage-p2-quality-final.log)；空白检查通过 |
| 容量模块外的完整集成 | [初次：4709项通过、14项失败、1项既有平台跳过、5条警告，3065.66秒](assets/2026-10-26-market-linkage-p2-integration-initial.log)；[14项失败均在当前代码复验通过，25.03秒](assets/2026-10-26-market-linkage-p2-failure-recheck.log) |
| 容量模块 | 初次已完成前缀：7项通过、1项失败。[十证券独立复验：1项通过、1条警告、1377.64秒](assets/2026-10-26-market-linkage-p2-capacity-final.log)；容量模块8项全部核对完成。[准确核对记录](assets/2026-10-26-market-linkage-p2-reconciliation.json) |

独立容量检查保留每证券120秒、工作集增量768MiB、行情库／WAL 512MiB、结果库／WAL 192MiB。最终实测文件体积分别为 519073792 和 184938496 字节。初始进程仅在容量模块全部执行后中断，七项通过按已保存的有序前缀对应。首次失败的延后错误栈未取得，因此不宣称已证实具体原因；相同失败节点在独立运行中通过，未改动上限或实现。未输出逐证券耗时值及工作集增量，但原断言全部通过。

[文档核验](assets/2026-10-26-market-linkage-p2-doc-audit.log)检查对应文档、P2 编号／检查点、本地链接和受保护任务文件未改动；另已人工核对两种语言的来源、数字阈值、公式及权限边界。

## MLP2-V06 — 验收对照

| 条款 | 实际测试证据／边界 |
| --- | --- |
| MLP2-A01 | [原文哈希及5段摘录核验通过](assets/2026-10-26-market-linkage-p2-source-audit.json)，夹具为 tests/fixtures/p2_original_prompt.json；双语规格 G01–G14；README A/B 政策、能力地图及操作说明 |
| MLP2-A02 | test_p2_policy_contract.py、test_p2_review.py、test_p2_storage.py、历史编解码／哈希及 test_market_linkage_api.py 精确 schema 投影 |
| MLP2-A03 | test_p2_sizing.py、test_p2_replay_mutations.py：档位边界、缺失／未来数据、网格交集及修正／重复获取 |
| MLP2-A04 | test_p2_composition.py：1000→500→200；100→无合法 Q0；200→100，P1 例外边界 |
| MLP2-A05 | test_p2_economics.py：合成 B100500、T109500、Z94500、收益9000、损失6000、成本1000、价差10 |
| MLP2-A06 | test_p2_economics.py、test_p2_policy_contract.py：精确算术、最低／包含费用、过期／无效／溢出及明确包含等号的门槛 |
| MLP2-A07 | test_p2_chain.py、test_p2_simulation.py、test_p2_concurrency.py、p2-pretrade.spec.ts：明确批准和独立单次整笔成交 |
| MLP2-A08 | test_p2_runtime.py、test_p2_simulation.py、test_p2_risk_notifications.py：冻结政策失效、报价恢复及实际风险 SELL 绕过 |
| MLP2-A09 | test_p2_api.py、test_p2_storage.py、test_p2_concurrency.py：只读预览、拒绝、重开及原子权限 |
| MLP2-A10 | test_p2_replay.py、test_p2_replay_mutations.py、test_p2_frozen_workers.py：真实读取／工作器／发布、未来事件不变性及既有回测费用用例 |
| MLP2-A11 | p2Review.spec.ts、p2Runtime.spec.ts、p2-pretrade.spec.ts 及 P0/P1 浏览器回归 |
| MLP2-A12 | 最终台账、准确失败核对及双语核验：PASS |

代表性可执行测试节点（完整覆盖还包括上表测试组）：

- MLP2-A02: `tests/unit/test_p2_policy_contract.py::test_old_reader_still_refuses_schema8`.
- MLP2-A03: `tests/unit/test_p2_sizing.py::test_exact_half_open_boundaries`.
- MLP2-A04: `tests/unit/test_p2_composition.py::test_volatility_then_market_reduction_not_reversed_or_replaced`.
- MLP2-A05: `tests/unit/test_p2_economics.py::test_specification_scenario_and_exact_gate_equality`.
- MLP2-A06: `tests/unit/test_p2_economics.py::test_included_fee_is_not_charged_twice_and_fractional_fees_round_up`.
- MLP2-A07: `tests/integration/test_p2_concurrency.py::test_full_simulation_consumes_approval_once`.
- MLP2-A08: `tests/integration/test_p2_risk_notifications.py::test_risk_exit_bypasses_failed_buy_economics`.
- MLP2-A09: `tests/integration/test_p2_concurrency.py::test_failure_after_inventory_write_rolls_back_every_effect`.
- MLP2-A10: `tests/integration/test_p2_replay_mutations.py::test_future_approval_does_not_change_prior_private_state`.

G01 保留 P0/P1 联动／强势／例外契约。G02/G03 是新增确定性政策；G04 检查来源／依据维度并保留人工审核。G05 金额上限、G06 券商／部分成交账本、G07 非100股模拟、G08 自动事件期限、G09 基本面、G10 新供应商覆盖、G11 日线联动五分钟确认和 G12 自主研究仍明确暂缓或属于人工边界。G13 仅 A 来源权限及 G14 既有整笔信号记账保持不变。测试不声称自动化这些排除能力。

## MLP2-V07 — 交付范围

本次实施不修改实际用户库，不发送 live 通知、不请求供应商、不发券商订单。验收费用／价格是明确的合成估算，不是当前市场认证。推送和部署不在授权内。保留 tasks/plan.md 和 tasks/todo.md。提交遵循中文 Conventional Commit 格式。全部检查已核对，T16–T18/C06 已完成。实现和证据仅本地提交，不包含推送或部署。

实现交付提交：`ac7cac1`（批准契约／来源）、`471ebd4`（严格政策／哈希）、`fa2ae86`（精确数量／费用）、`642e66c`（审核、运行、界面及冻结回放）。最终审查无未解决验收问题。

归档日志仅统一换行并去除行尾空白，保留测试结果、失败和警告。
