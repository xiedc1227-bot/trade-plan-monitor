# S3 已安装运行时读取存活状态

## S3-READ-01 — 范围

2026-09-27。基于已提交生产基线 `6bcf080` 的纯测试 S3-08 证据。新增 `tests/integration/test_s3_installed_runtime_read_liveness.py`；不修改源码、schema、公开协议、生命周期政策或 UI。仅使用临时 SQLite 数据库、受控时钟及假 SDK，禁止 HTTP 客户端请求。无真实服务、真实通知、用户数据库迁移、推送或部署。

本片覆盖真实午休待机/进展逾期对照。C1 双时钟恢复读取和 F3 事实补齐与业务判断的区别仍待对应实现接线后验证。本片不关闭 S3-08、C1/C3、第 4 步或最终汇总门禁。

## S3-READ-02 — 实际路径与断言

- 携带合法激活的 legacy 计划，在 `11:29:15` 启动已安装组合层。释放真实调度器的 `11:30:12` 等待；实际假 SDK 请求产生恰好一条已提交评估，`market_data_at=11:30:00`、`evaluated_at=11:30:12`。
- 到 `12:00:00`，调度器承诺的下一轮询仍在未来。实际读取服务报告 `RUNNING`、非只读及精确的 `next_poll_at`。总览在原代次下仍为连接状态，当前股票健康仍可操作。已安装流的心跳携带总览精确 sequence、generation 和运行开始时间。历史判断内容及所有捕获的业务行不变；不存在待处理官方收盘。
- 随后有意保持真实调度器许可未释放，将观察时间移至其承诺的 `next_poll_at + 1 microsecond`。调用已获准真实 owner 的 heartbeat，并验证新的持久 `last_alive_at`。owner 保持同代次 `RUNNING`，但实际总览读取显示断开、股票健康不可用，已安装心跳报告 `runtimeLive=false` 且 generation/start time 为 null。因此持久 owner 心跳不能掩盖调度进展逾期。
- 保留历史 LIVE 判断内容，而不是改写为当前信号。停滞观察前后的 SDK 调用、评估 ledger/result/head、alert event、delivery attempt 和 pending close 均不变。测试直接检查已安装流的帧，不是浏览器/socket 传输测试。

fixture 仅使用已提交 helpers。它允许午休期间真实有界维护等待，因此后续可验证 F3 接线，而无需替换调度器或硬编码下午下一唤醒。

## S3-READ-03 — Oracle 修正与验证

本片是既有行为的新证据测试，不是生产修复，也不宣称产品 RED→GREEN。首先，fixture 错用表名 `notification_attempt`，失败后修正为既有 `delivery_attempt`。随后，将 `get_health().runtime_generation` 与内部 owner identity 比较的断言失败。独立 Astra 检查确认两个既有 v1 健康模型均有意将该字段标记为 `exclude=True`，重新校验后因此重建 legacy 内部默认值。这不是公开代次字段，也不是已证明的 S3 产品缺陷。既有公开契约通过总览快照和心跳帧绑定代次。测试现加强这些实际公开路径的检查，同时保留内部同 owner 断言。未修改源码/schema，也未移除已承诺断言。修正后的初次测试 **1 passed, 1 warning, 2.28s**，之后再加入最终精确评估时间断言。

作者最终命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_installed_runtime_read_liveness.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_websocket.py -q --tb=short
```

结果：**47 passed, 1 warning, 7.92s**，包含新增真实组合层用例。warning 为既有 Starlette/httpx 弃用提示。运行前后生产源码指纹一致，并匹配 `6bcf080`：

| `src/trade_plan_monitor/` 下的文件 | SHA256 |
|---|---|
| `runtime/production.py` | `582BAF6F419F6CC2B139020BCD668663BCB4658F252D2BCCD2CB165936A10531` |
| `runtime/service.py` | `72E2EFCE3BFCC3F99FC0BA54B920E6BE20C44FD8AD0161F15C7E982750920989` |
| `runtime/scheduler.py` | `956887081F421DA68CAE222195CD35C3D946785513639C686976C278A542CC30` |
| `web/monitor_composition.py` | `2B32683AAAC03898BAD8AB82FC69930062690ED81A9B36CCCE1FCB8F6FFCEB6C` |
| `web/persistent_monitor_read_service.py` | `AEE9D668B7AECAEA8843B2897AD667E213C925B5B00232C4694188F0BEEFB23C` |
| `web/websocket.py` | `ACFD28A58DF92969C70DFB64FC42634222590072ACE8A2791EC80E077EC2E573` |

独立 Sol 评审通过，无 P1/P2。同一三文件命令独立通过 **47 tests, 1 warning, 7.96s**；新增测试的限定 Ruff 及 no-index 空白检查通过。在这一独立稳定窗口中，`runtime/production.py` 是未提交 F3-A 候选，SHA256 为 `75218CA0FA35DBB1995476D9DB83094C6585691F58D26E3B2C40FE4B74099E6F`；其余五项生产指纹与表中一致。测试 SHA256 保持 `D7B6E9B7D6A6E3E7D11C3B679400B1E0134CDD01A9658365D306ACA99AB0F21E`。本次独立运行不批准 F3-A。最终 F3-C/C1 接线后须重跑本例。作者与独立计数重叠，不可相加；不宣称汇总结果通过。
