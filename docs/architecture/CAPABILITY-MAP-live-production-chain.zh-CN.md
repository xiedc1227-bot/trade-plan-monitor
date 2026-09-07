# 能力地图：实时监控生产链路

> 中文审阅版。英文权威版为 `CAPABILITY-MAP-live-production-chain.md`；两份文档必须保持语义一致。

## P0 登记

本文档为 2026-09-05 实时生产修复创建稳定的 `LPC` 工作包命名空间。它不重命名、复用或暗示完成任何历史 `T001`～`T059`、`BT001`～`BT050`、`IDX001`～`IDX012` 或 `WEBF13` 任务。尤其是，`T059` 继续属于已验收的 DeepSeek 发布闸门。实时板块指数认证新登记为 `LPC007`；它不继承任何旧任务号，也不继承 readiness 声明。

## 模块

| 模块 ID | 职责 | 依赖 |
|---|---|---|
| `projection-availability` | 为 Dashboard 与股票投影提供类型化正常未就绪契约，同时保持成功响应形状 | `local-web`、`monitor-runtime` |
| `live-state-store` | 增量 Schema 迁移、完整判断结果、判断/健康/指数 head、待处理收盘恢复和持久读取 | `strategy-state`、`decision-engine`、`index-data` |
| `live-market-runtime` | 已认证股票供应商配置、请求控制、参考数据刷新、恢复、单批次 deadline、判断监督和提交后发布纪律 | `market-data`、`monitor-runtime`、`live-state-store` |
| `live-index-runtime` | 单独认证的实时板块指数供应商及逐指数故障隔离 | `index-data`、`live-market-runtime` |
| `web-availability` | 生成契约、Vue 可用性状态机、WebSocket 资格、Chrome 验收和惰性图表加载 | `projection-availability`、`live-state-store`、`live-market-runtime`、`local-web` |

## 构建顺序

```text
projection-availability
        │
        ├──→ live-state-store ──→ live-market-runtime ──→ live-index-runtime
        │                              │                        │
        └──────────────────────────────┴────────────────────────┴──→ web-availability
```

先冻结契约，再编写代码。契约完成后，存储与供应商工作可独立推进；运行时整合依赖存储边界，Web 只消费服务端生成契约。股票与指数真实认证是两个独立串行操作，绝不共用时间戳证据。

## 受保护基线

- 保留 Schema v1 计划字节、历史 evaluation/event/alert identity、回测数据/结果及全部既有 hash。
- 保留 DeepSeek、Web AI、板块指数、回测以及预先存在的 9 个 `WEBF13` 工作树修改；只有在测试覆盖类型化服务端契约后，才替换临时 Health fallback。
- 不提交、不推送、不下单、不调用 DeepSeek，也不调用明确获准 Tushare 测试边界以外的供应商。

## 审核状态

用户通过 2026-09-05 的明确请求批准实施。不得根据授权推断 runtime readiness：股票与指数供应商证据必须分别通过各自记录的闸门。
