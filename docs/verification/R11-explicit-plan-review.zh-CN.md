# R11 显式计划复核验证报告

## 范围

本报告使用固定且独立分类的语义语料，验证 R11 显式计划复核边界。验证全程确定性离线执行：未调用真实 AI 提供商、行情提供商、通知渠道、交易接口或生产数据库，也未使用任何密钥。

R11 接受 Schema 3 部分草稿，保留精确原文子句及双向来源映射，由服务端推导必需复核问题，将复核确认精确绑定到内容与来源哈希，并在 R12 普通计划表单门槛实现前继续关闭公开启用。

## 固定语料结果

独立判定基准在实现验收前记录于 `tests/fixtures/ai/explicit-plan-semantic-corpus-v1.json`。`NONE` 表示服务端没有生成语义阻断项。

| ID | 类别 | 预期语义码 | 实际语义码 | 状态 |
|---|---|---|---|---|
| EXP-01 | EXPLICIT | NONE | NONE | PASS |
| EXP-02 | EXPLICIT | NONE | NONE | PASS |
| EXP-03 | EXPLICIT | NONE | NONE | PASS |
| EXP-04 | EXPLICIT | NONE | NONE | PASS |
| EXP-05 | EXPLICIT | NONE | NONE | PASS |
| EXP-06 | EXPLICIT | NONE | NONE | PASS |
| EXP-07 | EXPLICIT | NONE | NONE | PASS |
| EXP-08 | EXPLICIT | NONE | NONE | PASS |
| AMB-01 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-02 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-03 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-04 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-05 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-06 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| UNS-01 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-02 | UNSUPPORTED | `UNRESOLVED_SEMANTICS`、`UNSUPPORTED_SEMANTICS` | `UNRESOLVED_SEMANTICS`、`UNSUPPORTED_SEMANTICS` | PASS |
| UNS-03 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-04 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-05 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-06 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |

结果：**20/20 案例通过**，其中明确语义 8 例、歧义语义 6 例、不支持语义 6 例。

## 自动化证据

- R11 聚焦复核与安全检查：49 项通过。
- AI、Web、OpenAPI、仓储与 R11 集成发布门槛：最终加固后 433 项通过。
- 旧版显式执行与传输回归组：29 项通过。
- 其余计划、决策、发件箱、风险、持仓、通知与生产回归组：684 项通过。
- 配置回归组：22 项通过。
- 生成的前端 API 类型与 OpenAPI 快照一致。

前端类型检查仍报告 R10 已存在的 `AlertTable.vue` 与 `AlertsView.vue` 告警联合类型错误。R11 未修改这些文件，也没有削弱该检查。

## 发布边界

公开能力继续保持 `publicActivationAvailable=false`。有效且属于当前内容的复核确认是公开启用的必要条件，但刻意不是充分条件：API 仍返回 R12 普通计划表单门槛。导入、通知投递、交易执行与生产部署仍不在本阶段范围内。
