# S3-05 指数重试跨正常 OS 进程重启验证

> 本文是中文复核副本，规范性英文报告为 `2026-09-27-s3-index-retry-process.md`。

## IRP-01 范围与状态

状态：writer 验证及 root 独立评审通过；三文件本地提交获批，无 P1/P2 发现。不声明完整 S3-05 或发布验收通过。

本片仅拥有 `tests/integration/test_s3_index_retry_process.py` 和本配对报告。不修改生产源码、调度政策、数据库 schema 或既有测试。依据是 `tasks/runtime-recovery-todo.md` 中既定的 S3-05 门禁。

## IRP-02 测试边界

夹具建立真实 Schema v2 计划，依赖 `INDEX_CLOSE_GTE_MA`，以及具有合法可发送规则的独立 Schema v3 计划。两者使用完整持久化 activation、calendar、inventory 和 manual-risk 事实。种子控制用例验证没有预造 evaluation、alert、delivery、index snapshot 或 retry。

两个独立 `spawn` 进程创建真实 composition 并启动真实 scheduler。注入时钟只释放 scheduler 自己选出的精确 sleep。不直接调用 `run_deadline` 或 retry service，不强设生命周期状态、不覆盖 timer 政策，也不绕过 admission。假 channel 仅替换传输，保留实际 current-delivery admission。

P1 在 09:59:30 启动，在合法的 10:00:12 行情 deadline 唤醒。只有必需指数故障。依赖计划必须记录指数证据缺失且没有信号；独立计划必须真实发送一次，其它四个展示指数为 LIVE。必须先正常停止 P1 composition 并退出 OS 进程，才创建 P2。

P2 在 10:00:20 使用相同临时数据库启动，行情源故障已解除。必须恢复原 retry/cutoff 和已持久化的失败 head。首次 scheduler 唤醒必须将该指数原 cutoff 的 head 恢复为 LIVE；这一 index-only 段不得新增 stock SDK 请求、evaluation、alert、delivery attempt 或发送。随后普通 scheduler 唤醒推进到 10:05:12；依赖计划必须使用 LIVE 指数证据完成求值，独立兄弟计划不得重复发送。

启动后的业务表必须等于 P1 正常停止时的状态，不统计无关 liveness 记录。最终 cutoff 时，兄弟原 event、首次 DELIVERED receipt 和 explicit evaluation 仍原样保留；每个目标的 evaluation identity 保持唯一。四项负向 oracle 控制在真实观测的独立副本中注入 stock call、evaluation row、alert row 或发送。每项都必须被主路径所用的同一个 index-only 断言拒绝；不修改数据库或生产状态。

## IRP-03 命令与证据

从 `trade-plan-monitor/` 运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_index_retry_process.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_index_retry_process.py --output-format concise
```

- 仅种子增量：**1 passed，1 warning，1.28 秒**。
- 首次真实进程运行：**1 failed，1 passed，7.20 秒**。失败来自夹具将规范 JSON `10:00:00.000000+08:00` 与等价的秒精度字符串直接比较，指数实际上已恢复 LIVE。改为解析时间后比较，保留原 cutoff 要求；这不是产品 RED。
- 修正后的进程基线：**2 passed，1 warning，6.99 秒**。
- 最终加强文件，包含启动状态等值、原 event/receipt 保留、identity 唯一及四项负向 oracle 控制：**2 passed，1 warning，6.87 秒**。定向 Ruff 通过。警告为既有 Starlette/httpx 弃用提示。各次运行重叠，不能相加。

首次进程运行使用协调后的源码冻结窗口。最终运行仅在测试调整后进行，四个并行 F2 源码 hash 在其前后也保持不变。checkout 为 `7c178184b84b835aa93b40e7120185c95fccaccf` 加另一 writer 未提交的 F2 源码改动，不是隔离的已提交发布版本。本测试 writer 未修改生产源码，也不据此批准 F2 改动。记录的源码指纹：

| `src/trade_plan_monitor/` 下的路径 | SHA256 |
| --- | --- |
| `runtime/production.py` | `7D5FA3724CE7CC0243535B2A7FDCD54E78EB7A4A703FAEFC41F56AF553CEBBB7` |
| `web/monitor_composition.py` | `DBB3381DC4D29F80AAAF755F9340317D3A655D85C8C85649883A059C3404901E` |
| `runtime/recovery.py` | `C090C838BF61F5DA7EB89184C2153AC9D83C00490A9AB49D97BA6F0CC7E5378F` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `runtime/service.py` | `DF3EE4DF221D7FB40088B3CDAD66F263C8AB1D529C2A5774F213AFE41E9FAD43` |
| `runtime/scheduler.py` | `956887081F421DA68CAE222195CD35C3D946785513639C686976C278A542CC30` |
| `runtime/market_indexes.py` | `DBC989CA3DEE64A393F097BE669832B1DBAC25A3E6351E58A318E87D79310F36` |

最终测试 SHA256：`A6760C523D39A3E35E2B5EB3F4481A66DEDB8F39120AB3E38191DD4FF9D7D3F5`。

root 独立评审使用同一专项命令复跑：**2 passed，1 warning，6.97 秒**。定向 Ruff 通过；上方四个 F2 源码指纹及最终 test hash 在运行前后不变。测试/代码 oracle 及双语报告审查无 P1/P2。这是单独的工作区候选证据，不是新增汇总数量，也不批准 F2。

## IRP-04 限制与交接

每个子进程封禁 requests/httpx 网络访问，使用假 SDK/channel 边界、受控时钟及临时 SQLite。正常完成要求 OS 进程正常退出；强制终止仅用于失败清理，且仅针对夹具自己创建的精确进程。不涉及真实行情源、真实通知、用户数据库、push 或部署。

本片补齐旧同进程/直接 deadline 测试缺少的正常进程重启指数 retry 证据，不替代完整 A06 矩阵，也不关闭 S3-02/S3-04 前置门槛。S3-05 保持 OPEN，等待集成前置验收。并行 A07 F2 工作不属本片。不声明全量测试、固定发布版本或生产就绪验收通过。
