# 文件命名

## 范围

使用能说明文件职责的名称。本规范适用于 `trade-plan-monitor` 中维护的源码、测试、脚本、配置和新增文档。可执行文件的主体名称不使用 `r13` 等临时任务编号。需求编号保留在注释和验收报告中。

## 约定

| 文件类型 | 约定 | 示例 |
|---|---|---|
| Python 模块或脚本 | `snake_case.py` | `bounded_live_acceptance.py` |
| Python 测试 | `test_<behavior>.py` | `test_ai_timeout_budget.py` |
| Vue 组件或页面 | `PascalCase.vue` | `SourceTextEditor.vue` |
| TypeScript 工具或组合函数 | 沿用 `camelCase.ts`，组合函数以 `use` 开头 | `marketIndexChartOptions.ts`、`usePlans.ts` |
| 组件单元测试 | 与组件同名，加 `.spec.ts` | `PlanWorkbench.spec.ts` |
| 工具单元测试 | 与工具同名，加 `.spec.ts` | `transport.spec.ts` |
| 浏览器测试 | 用 `kebab-case.spec.ts` 描述行为 | `active-plan-process-restart.spec.ts` |
| 指南或任务文档 | 用 `kebab-case.md` 描述主题 | `file-naming.md` |
| 中文文档副本 | 相同主体名称加 `.zh-CN.md` | `file-naming.zh-CN.md` |

## 稳定约定与历史记录

保留工具约定的 `README.md`、`pyproject.toml`、`package.json`、`__init__.py`、`__main__.py`、`conftest.py` 及使用点号的 Vite 配置文件名。保留既有 `SPEC-`、`CAPABILITY-MAP-`、`PROPOSAL-` 文档角色、编号 ADR 和迁移版本、日期验证记录、股票代码标识及有语义的测试样例版本。

历史任务计划、验收报告、已记录命令和冻结证据可以保留 `R13` 等编号。它们属于记录身份，不作为新增可执行文件命名的模板。命名迁移期间，`remediation/evidence/`、既有 `docs/verification/assets/` 和已记录运行数据保持逐字节不变，不把历史执行记录改写成使用了新命令。

## 重命名流程

1. 检查受版本管理及未被忽略的项目文件，排除依赖、生成构建、缓存、密钥和本地运行数据。
2. 使用描述用途的名称，确保在不区分大小写的文件系统上也不冲突。
3. 移动既有文件，同步导入、子进程模块参数、当前操作命令及中英文档，保留尚未提交的修改。
4. 记录旧名到新名的映射，为历史可执行路径提供新命令。不增加会造成测试重复执行的兼容副本。
5. 对比测试发现结果，检查导入并运行受影响的离线测试。保留授权编号、预算、Schema 版本及真实供应商显式授权边界。

## 本次迁移

2026-10-01 审计检查了全部 1,448 个受版本管理的文件名，重命名 38 个维护中的可执行文件。完整信息见[路径映射](../verification/assets/file-naming/renames.json)和[验证报告](../verification/2026-10-01-file-naming.zh-CN.md)。例如，使用 `python -m scripts.bounded_live_acceptance` 替代原有 `scripts.r14_bounded_acceptance` 入口。默认离线行为及既有执行授权要求保持不变。
