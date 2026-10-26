# 实施计划与任务：market-linkage-p2

状态：实施中 — 2026-10-26。用户已批准六项决策及实施；任务／检查点标记及验收报告记录实际完成情况。[英文任务](market-linkage-p2.md) · [中文规格](../docs/specifications/monitoring/SPEC-market-linkage-p2.zh-CN.md)。

## MLP2-P01 — 授权与工作方式

MLP2-D01–MLP2-D06 及实施已获授权。基线为8db00c425706945d69a39ae0d3ffe1d85348d626；开始实施时重新核验工作区。保留 tasks/plan.md 和 tasks/todo.md，不另建工作流、不委派代理。

先写具有独立预期值的失败测试，再修改行为。每片目标3–5个文件；表内是归属接口，不代表批量重写授权。超过5个文件时，先记录顺序子任务，再开始编辑。检查点失败须修复后再进行依赖任务；策略语义变化先更新双语规格并审核。依赖可并行不代表授权启动子代理。

## MLP2-P02 — 验证命令

从 trade-plan-monitor/ 执行。p2 测试文件均为拟新增，由对应任务创建；未创建时不能将空选择当通过。开发过程中运行已创建的明确文件，检查点运行该组完整测试。使用临时 SQLite、确定性供应商和冻结样例，禁止以用户数据库验收。

| ID | 命令／检查 |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py tests/unit/test_market_exception_contract.py tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_p2_policy_contract.py tests/unit/test_p2_sizing.py tests/unit/test_p2_economics.py tests/unit/test_p2_composition.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/integration -k p2 -q` |
| V04 | `npm --prefix web run test -- --run tests/unit/p2Review.spec.ts tests/unit/p2Runtime.spec.ts`; `npm --prefix web run type-check` |
| V05 | `npm --prefix web run test:e2e -- tests/e2e/p2-pretrade.spec.ts tests/e2e/market-exceptions.spec.ts tests/e2e/market-linkage.spec.ts` |
| V06 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q`; `npm --prefix web run test -- --run`; `npm --prefix web run build` |
| V07 | `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` (both API profiles); `.\.venv\Scripts\python.exe -m ruff check src tests`; `git diff --check` |
| V08 | 双语段落／ID／枚举／公式／单位／边界／链接一致；逐项对应原文、任务、测试及实际结果。 |

## MLP2-P03 — 顺序实施任务

### MLP2-T01 — 冻结契约及来源清单

- [x] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: approval / 批准.
- 文件／范围: 双语规格、拟新增 CONTRACT-market-linkage-p2 双语附录、原文样例.
- 验收: MLP2-A01, MLP2-A02. 验证: V01,V08.

### MLP2-T02 — 增加严格版本政策模型及算术校验

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T01.
- 文件／范围: domain/p2_policy_models.py（新增）、domain 编解码、tests/unit/test_p2_policy_contract.py（新增）.
- 验收: MLP2-A02, MLP2-A03. 验证: V02.

### MLP2-T03 — 接通 Schema 8 分派、旧读取方拒绝及审核哈希

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T02.
- 文件／范围: 草稿／版本分派、来源绑定模型、现有编解码黄金测试.
- 验收: MLP2-A02. 验证: V01,V02.

### MLP2-C01 — 阶段验收

- [ ] V01,V02 通过；覆盖 MLP2-A02.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

### MLP2-T04 — 实现原文 ATR 档位及合法 Q0 向下取量

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T03.
- 文件／范围: decision/p2_sizing.py（新增）、数量适配器、tests/unit/test_p2_sizing.py（新增）.
- 验收: MLP2-A03, MLP2-A04. 验证: V02.

### MLP2-T05 — 实现精确费用预览及显式数字门槛

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T03.
- 文件／范围: decision/p2_economics.py（新增）、费用值模型、tests/unit/test_p2_economics.py（新增）.
- 验收: MLP2-A05, MLP2-A06. 验证: V02.

### MLP2-T06 — 组合数量、大盘路径及例外数量预览

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T04,T05.
- 文件／范围: decision/market_linkage.py、decision/market_exception_policy.py、tests/unit/test_p2_composition.py（新增）.
- 验收: MLP2-A04, MLP2-A07. 验证: V01,V02.

### MLP2-C02 — 阶段验收

- [ ] V01,V02 通过；覆盖 MLP2-A03–A07.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

### MLP2-T07 — 扩展仅 A 提取及可审核来源依据

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T06.
- 文件／范围: ai/plan_extraction.py、审核接口、tests/integration/test_p2_review.py（新增）.
- 验收: MLP2-A01, MLP2-A02. 验证: V03.

### MLP2-T08 — 以非破坏迁移保存冻结政策依据

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T07.
- 文件／范围: state 权限模型／仓库、新迁移、tests/integration/test_p2_storage.py（新增）.
- 验收: MLP2-A02, MLP2-A09. 验证: V03.

### MLP2-T09 — 应用运行确认、修正及窗口不变约束

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T08.
- 文件／范围: runtime/daily_service.py、信号生命周期适配器、tests/integration/test_p2_runtime.py（新增）.
- 验收: MLP2-A03, MLP2-A07, MLP2-A08. 验证: V03.

### MLP2-C03 — 阶段验收

- [ ] V03,V08 通过；覆盖 MLP2-A01,A02,A07,A08,A09.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

### MLP2-T10 — 以当前费用约束例外批准及原子模拟

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T09.
- 文件／范围: runtime/market_exceptions.py、模拟事务接口、tests/integration/test_p2_simulation.py（新增）.
- 验收: MLP2-A07, MLP2-A08, MLP2-A09. 验证: V03.

### MLP2-T11 — 增加只读预览 API 及运行结果

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T10.
- 文件／范围: web 预览路由（新增）、响应模型、tests/integration/test_p2_api.py（新增）；生成契约另分子任务.
- 验收: MLP2-A09. 验证: V03,V07.

### MLP2-T12 — 增加依据及政策审核界面

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T11.
- 文件／范围: web/src 计划编辑器、新政策组件、API 客户端、web/tests/unit/p2Review.spec.ts（新增）.
- 验收: MLP2-A02, MLP2-A11. 验证: V04.

### MLP2-C04 — 阶段验收

- [ ] V03,V04,V07 通过；覆盖 MLP2-A02,A07,A08,A09,A11.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

### MLP2-T13 — 展示运行档位、费用、门槛及独立例外操作

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T12.
- 文件／范围: web/src 运行／例外组件、通知投影、web/tests/unit/p2Runtime.spec.ts（新增）.
- 验收: MLP2-A07, MLP2-A08, MLP2-A11. 验证: V04.

### MLP2-T14 — 将 P2 冻结依据接入回放输入与运行适配

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T10.
- 文件／范围: backtest 输入／版本适配、共享政策适配、tests/integration/test_p2_replay.py（新增）.
- 验收: MLP2-A02, MLP2-A10. 验证: V03.

### MLP2-T15 — 验证无未来数据、重启／并发及浏览器流程

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T13,T14.
- 文件／范围: tests/integration/test_p2_replay_mutations.py（新增）、tests/integration/test_p2_concurrency.py（新增）、web/tests/e2e/p2-pretrade.spec.ts（新增）.
- 验收: MLP2-A09, MLP2-A10, MLP2-A11. 验证: V03,V05.

### MLP2-C05 — 阶段验收

- [ ] V03,V04,V05 通过；覆盖 MLP2-A07–A11.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

### MLP2-T16 — 运行完整回归并逐项核对失败

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T15.
- 文件／范围: 仅在有依据时修复测试／实现；新增双语验收报告.
- 验收: MLP2-A12. 验证: V01–V08.

### MLP2-T17 — 更新双语提示词、操作文档与能力边界

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T16.
- 文件／范围: README 双语、operations 双语、能力图双语（按文档对拆分子任务）.
- 验收: MLP2-A01, MLP2-A12. 验证: V08.

### MLP2-T18 — 审计验收矩阵并整理交付

- [ ] 完成本片实现及对应独立测试，保留规格全部边界。
- 依赖: T17.
- 文件／范围: 双语规格／任务／报告、限定范围 Git 差异.
- 验收: MLP2-A01–A12. 验证: V07,V08.

### MLP2-C06 — 阶段验收

- [ ] V01–V08 通过；覆盖 MLP2-A01–A12.
- 检查当阶段所有已有测试、历史兼容及权限边界；尚未创建的后续测试必须明确记录为未执行。记录命令、代码版本、结果、失败修复及限制，不以局部通过声称全量验收。

## MLP2-P04 — 交付证据与停止条件

最终双语报告按 MLP2-A01–MLP2-A12 列出测试名、执行命令、结果及限制；不预填通过。保留 P0/P1 权限、原数量、费用及回放黄金样例。任何失败均须修复或如实列为未通过，不降低既有门槛。

只有涉及新策略阈值、费用含义不明、历史权限不兼容或超出本规格范围且无法按已批准边界解决时，才交用户决定。环境或测试失败先定位并修复，不反复询问已有授权。官方费率引用若不能验证，不冒充当前市场事实；可用明确合成样例完成非live验收，并注明未认证市场数据。

完整交付包括双语规格／契约／任务／操作／验收、代码与测试、生成契约，以及按项目中文 Conventional Commit 规范整理的提交。实际用户库迁移、live供应商／通知、部署或推送不在本计划授权内。本次仅交审核文档。

