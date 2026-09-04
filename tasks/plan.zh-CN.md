# 实施计划：共用板块指数数据，使用方式由计划决定

> 中文审阅计划。英文权威版为 `plan.md`；两份文档必须保持语义一致。

## 总览

按依赖顺序实施六个获批模块，同时保留干净的两个本地提交基线、Schema v1 计划/结果字节、DeepSeek/Web AI 工作以及全部离线/安全边界。每个代码切片先写失败的聚焦测试，最后完成聚焦验证。本计划不包含提交、推送、安装依赖、部署或真实供应商请求。

## 架构决定

- 只使用封闭 `board-index-map-v1` 解析器；不存在回退或行业映射。
- 同一指数/截止/请求集合只产生一份不可变快照；条件结果继续属于具体计划/路径。
- Schema v2 明确且增量；Schema v1 规范 JSON、哈希、数据行和历史结果保持不变。
- 实时与回放共用指数模型、公式、快照构造、条件计算器、截止规则、证据和哈希。
- OpenAPI 是后端契约来源；生成 TypeScript 通过重新生成同步，绝不手工设计第二套 Schema。
- Vue 使用 Composition API、`<script setup lang="ts">`、只读 props、类型化事件，并禁止策略计算。

## 组件图

| 组件/组合函数 | 职责 | 契约 |
|---|---|---|
| `MarketIndexDataStrip.vue` | 共用监控事实/健康 | 输入只读快照 |
| `IndexConditionProgress.vue` | 一份计划的数量/未使用状态 | 输入只读进度 |
| `ReferenceMarketPanel.vue` | 一只股票的绑定/快照身份 | 输入只读参考市场 |
| `MarketIndexChart.vue` | 已校验服务端序列和表格替代 | 输入只读点位 |
| `BacktestIndexConditionSummary.vue` | 路径级回测数量 | 输入只读摘要 |
| `BacktestMarketIndexPanel.vue` | 组合回测身份/图表/健康/日期导航 | props 向下，日期事件向上 |
| `useMarketIndexSeries.ts` | 有界可取消序列请求 | 只读状态和明确加载/取消动作 |

## 阶段与检查点

1. 基础：`IDX001`–`IDX003`——身份、事实、共用快照缓存。
2. 计划判断：`IDX004`–`IDX005`——Schema v2、条件、路径和证据。
3. 监控：`IDX006`–`IDX008`——运行时、API/OpenAPI、Vue。
4. 回测：`IDX009`–`IDX011`——回放数据/身份、API/导出、Vue。
5. 完成：`IDX012`——双语一致、README/API/测试报告和完整离线门禁。
6. WEBF13 路由与旅程收口——证明真实路由/新建回测边界，保持冻结的 42 路径契约，并且只记录实际运行的离线证据。

每个阶段后设置检查点。检查点要求聚焦测试通过、修改表面的 Ruff/类型检查通过、`git diff --check` 通过，并确认差异中没有密钥或无关文件。

WEBF13 检查点还要验证精确的 10 路由地图以及 `submit → /backtests/:runId?jobId=<jobId> → poll → remove jobId → materialized result` 新建回测链路。在把配对证据标记为 `PASS` 前，必须运行 OpenAPI 一致性检查、聚焦后端/前端测试、Ruff、`vue-tsc`、生产构建和确定性浏览器套件；不得增加 API 字段、重新生成发生变更的契约、读取 token 或调用供应商。

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 现有 v1 哈希变化 | 历史审计破坏 | 空的新字段不序列化、保留黄金测试、为新数据集/运行/报告域设置版本 |
| 运行时重复获取 | 限额浪费/数据分歧 | 先合并需求，同一键共用一个进行中的不可变快照 |
| 指数故障变成全局阻断 | 违反 ADR | 只判断明确叶子；增加无条件回归测试 |
| 浏览器重复策略 | 判断分歧 | 使用生成类型、只展示组件、测试直接提供权威结果 |
| 回测未来数据 | 研究无效 | 截止过滤回放、观察时间测试、共用公式/证据黄金值 |
| 供应商能力未知 | 生产不可用 | 安全 `UNVERIFIED` 适配器和离线 fake；报告真实能力未验证 |
| 与 DeepSeek/Web 修改重叠 | 工作丢失 | 保留 HEAD 基线，编辑前检查每个重叠差异 |

## 验证门禁

```powershell
python -m ruff check src tests
python -m pytest -m "not live"
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

后端套件只排除标记为 `live` 的测试；除非仓库已有文档化的独立资源门禁，否则包含原有重型验收测试。禁止跳过/删除测试或降低阈值。

## 开放问题

离线实施没有阻断性设计问题。准确 Tushare 指数接口、五个代码权限、时间/字段语义、限额和最长历史仍明确留到另行授权后验证。
