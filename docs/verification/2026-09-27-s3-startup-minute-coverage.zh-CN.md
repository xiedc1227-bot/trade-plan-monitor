# S3 真实启动分钟覆盖

## 当前 F3-C 状态

下文历史证据原样保留，不冒作当前失败。F1 `f4a5050` 修复关联 incomplete outcome；F2 `6bcf080` 修复冻结 startup capture；F3-A/B `05487b4`/`5e56c41` 提供有界 owner/executor。当前未提交的 F3-C 接线使**原 13 个用例全部 GREEN**，包括三个 oracle 控制。最终独立源码/测试评审通过，无剩余 P1/P2；报告 parity 已批准。不宣称整体 C1/C3 已关闭。

F2 后加强基线为 **11 passed, 2 failed, 11.51s**，只剩 empty/partial 自主进展失败。两个 progress 现在要求每个真实 scheduler wake 及最终时刻均保持原 runtime generation、无 runner fault。在下一合法评估前，prefix 事实已修复但 decision/claim/risk/outbox/send 仍零，公开状态保持 `AWAITING_FIRST_EVALUATION`；只有真实 target 10:05 于 10:05:12 的评估产生当前业务结果。自动 runner replacement 不能再满足 progress。C2 仍检验真实 10:00:59 至 10:01:13 入场 startup 请求、冻结响应排除及零立即 elapsed replay。

日期/fatal 修复后最新作者验证：下列命令 **43 passed, 1 warning, 26.18s**，包含本文件全部 13 个用例（并非另一次独立 13 用例运行）。三个 connected 代表及完整时序见双语 wiring/identity/authority/delivery 报告。随后源码只有一处格式换行；末版源码/测试独立评审后继续冻结。未删除、skip 或削弱任何原用例/oracle。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
```


## 最终独立验证

独立 Sol 在 `trade-plan-monitor` 目录针对末版冻结源码/测试运行以下精确命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**。11 个 SHA256（四个源码、七个测试文件）运行前后均与最终冻结值完全一致。Ruff 与 diff 检查通过。最终 F3-C/A07 源码/测试无剩余 P1/P2；startup fatal 掩盖 P2 已关闭。此前独立 155/28.47s 窗口跨 AD22→38608 仅换行修改，不作为最终 fixed-revision 验收；由本次 159 用例覆盖，而非相加。作者与独立窗口保持分列。五组双语报告 parity 已独立核对通过；不宣称整体 C1/C3 已关闭。本次文档更新不修改源码/测试，也不提交。

## 历史范围与已审契约

基线：`453cc0c`。本测试片只新增 `tests/integration/test_s3_startup_minute_coverage.py` 及本中英文报告。生产代码、迁移及现有测试均不在修改范围。协调任务的全量离线运行在新增这些文件前已经完成测试收集；新增用例不属于该次运行的结果。C1 仍未关闭，S3-04 保持 OPEN；本片不宣称完成。

独立评审通过的契约使用一个当日旧计划、固定激活身份、真实 composition/controller/scheduler/provider、临时 SQLite、假 SDK/时钟/通知通道，并禁止 HTTP。有效认证提供能力状态；按实际顺序、阶段及进入时刻记录 SDK 调用，不以所谓第二次 `rt_min_daily` 推断业务请求。空响应保留合法字段结构。测试不直接调用恢复/评估，不插入 pending，也不强制设置 `DEGRADED`。

## 用例与预期证据

| ID | 用例 | 执行前预期证据 |
|---|---|---|
| SSMC-A-S | 启动为空，后续历史仍不可用 | 启动分钟精确为空；实时 10:01–10:05 不得生成结果/claim/risk/outbox/发送；公开详情保持 `AWAITING_FIRST_EVALUATION`。预期安全 GREEN。 |
| SSMC-B-S | 启动包含 09:32–10:00，仅缺 09:31；后续历史仍缺该分钟 | 核对精确持久身份，包含完整当前桶；安全断言与 A 相同。预期安全 GREEN。 |
| SSMC-A-P | 启动为空，后续完整历史可用 | 真实调度必须自主重新获取原缺失前缀，并在测试的有限市场时刻上界 10:10:12 前生成一次合法当前决策。预期基线进度 RED。 |
| SSMC-B-P | 启动为部分历史，后续完整历史可用 | 必须自主提交原缺口 09:31，再生成一次合法当前决策。预期基线进度 RED。 |
| SSMC-C1 | 完整前缀另加原始未来行 | 响应时仍未完成的行由真实 provider 过滤。预期 GREEN。 |
| SSMC-C2 | 10:00:59 开始获取，10:01:13 响应 | START 标签的原始 time 10:00 规范化为 bar_end 10:01。响应时已可用，但超出冻结 cutoff 10:00，不得写入 SQLite。预期截止点 RED。仅启动观测前要求零次第二业务获取、零次实时请求。 |
| SSMC-C3 | 新获取从 10:01:13 开始 | 另一轮真实启动获取可按新 cutoff 接受 bar_end 10:01。预期 GREEN。 |
| SSMC-D | 已持久化完整 09:31–10:00，启动响应为空 | 既有事实保留；实时 10:01–10:05 完整后生成一次正确 10:05 决策；再次启动保持相同业务记录。预期 GREEN。 |

安全与进度分别测试，避免提前补齐掩盖不安全结果。进度允许当前合格决策，不要求重放旧 10:00/10:05 决策。`RUNNING` 与单分钟 `LIVE` 只是观测，不作为业务就绪断言。不要求新增 pending 状态：证据为精确持久分钟身份、物理 SDK 进入、decision head、claim/result/outbox 及现有公开响应。

## 隔离与边界

受控时钟释放真实调度器请求的截止时间，不依赖固定 sleep 次数。进度上界为 10:10:12，另设 45 秒真实时间 watchdog、64 次唤醒保护及 10 秒清理上限。这些是测试边界，不是生产恢复 SLA 或公平性保证。安全观测可以在公开的 `RUNTIME_RUNNER_FAILED` 边界停止；另一个保持启用的回归断言会拒绝该故障。进度用例允许真实监督器运行，包括自主替换实例。C2 的十四秒是模拟市场时钟推进，不真实等待十四秒；真实 controller 保留超时及节流配置，因此这不是物理超时边界测试。新一轮获取对照通过真实 provider，不直接调用 `recover_scope`。

## 执行与分类

上述八用例契约已在执行前记录。实际执行暴露了另一处生产故障，因此在同一个新测试文件中增加两个明确的 A/B 故障回归。独立静态评审随后要求增加三个断言自身对照，共十个 composition 用例及三个断言用例。没有将断言标记为 xfail/skip，也没有替换生产行为来获得通过。

| ID | 实际结果 | 证据 |
|---|---|---|
| SSMC-A-S / SSMC-B-S | GREEN，2 例 | 启动身份集合精确；五次真实实时 SDK 调用；没有 decision/claim/risk/outbox/attempt/send；包括故障边界在内，公开详情保持 `AWAITING_FIRST_EVALUATION`。 |
| SSMC-A-F / SSMC-B-F | RED，新暴露的 2 个故障回归 | 10:05 当前桶完整但早期前缀缺失时，公开健康变为 `RUNTIME_RUNNER_FAILED`。预期的数据发布不完整不应成为运行器故障。 |
| SSMC-A-P / SSMC-B-P | GREEN，2 例；原进度 RED 假设在本场景被否定 | 自动替换运行实例后，第二次业务获取于 10:05:12 进入，提交原缺口并生成一次合法 10:05 决策。两例均记录 `generation_changed=True`；SDK 顺序 5 为最初 10:00:15 获取，顺序 15 为 10:05:12 获取。这些是观测，不用于按顺序选择请求。 |
| SSMC-C1 | GREEN | 09:31–10:00 的 30 个规范分钟全部保留，追加的仍属未来的原始行被过滤。 |
| SSMC-C2 | RED | 唯一一次启动业务获取于 10:00:59 进入；实时调用为零，释放的调度 sleep 为零。然而 SQLite 仍包含额外的 `2026-09-08T10:01:00+08:00` 身份，共 31 行，超出冻结的 30 行。 |
| SSMC-C3 | GREEN | 从 10:01:13 开始的新一轮真实获取合法持久化截至 10:01 的全部 31 个身份。 |
| SSMC-D | GREEN | 空响应保留原前缀；得到唯一且匹配的 10:05 result/claim/head、价格 6405 及完整来源前缀；再次真实启动保留分钟身份、全部已观测业务行与投递。不要求零次获取。 |
| SSMC-O | GREEN，3 个断言对照 | 接受 10:05:12 评估的 10:05 目标；拒绝其在 10:10:12 的延迟回放及伪造的旧评估时间。 |

初版测试只等待下一次调度 sleep，因此运行器在 10:05 后停止时发生超时。在不修改生产代码的诊断异常观测中，定位到 `runtime/service.py:2639–2648` 的 `RuntimeDeadlineCoordinator.run_deadline`：旧计划的 `INCOMPLETE` 正确携带 `facts=None`，但协调器将其排除在 `by_symbol` 外，随后抛出 `RuntimeError("deadline evaluation omitted a due plan")`。真实监督器随后重启运行实例。最终测试搭建识别公开故障边界并明确测试该故障；临时诊断追踪和短诊断等待均已移除。这不表示不完整数据生成了错误决策。

实际重启也修正了此前静态推导的进度假设：在这些场景中，历史可用后，真实监督器确实会自动补回，不需要手动调用恢复。这不能证明平稳的局部恢复，因为路径首先导致运行器异常并改变 runtime generation。激活身份始终不变。未来修复后，进度测试不要求必须崩溃或变更 generation 才能通过。

首次完整诊断矩阵为 **3 failed, 7 passed，15.05s**。补充来源前缀/价格检查、故障边界捕获及进度诊断后，下一次运行为 **3 failed, 7 passed，15.00s**。随后对照整理允许 D 在数据已完整时省略行情获取，同时保留其数据与去重断言。

一次重跑在收集阶段被阻断（**1 error，1.04s**）：共享 HEAD `e9c6ac5` 上的并行改动临时使 `production.py:299` 继承尚未定义的 `PermissionEndpointResolver`。该次运行没有执行测试。协调任务确认这是唯一源码 writer 的编辑中间态，并暂停 pytest 直到导入稳定。协调任务解除暂停后，十用例完整重跑为 **3 failed, 7 passed，15.27s**。临时收集阻断已经解除，不属于产品回归或三个覆盖失败之一。本任务没有修改 writer 的文件。

独立 Sol 评审发现原当前决策断言存在 P2：仅要求目标晚于 10:00 且不晚于时钟，可能接受在 10:10:12 回放的 10:05 目标。修订后的断言解析 target/evaluated_at，要求 evaluated_at 等于实际观测到的评估时钟，且目标年龄在 0 至既有 90 秒上限之间。规范 snapshot 还必须携带相同 evaluated_at。D 的再次启动检查保留实际原评估观测时刻，不将旧结果重新标为重启时间。SSMC-O 新增合法 10:05/10:05:12 正控，以及两个合成负控：在 10:10:12 延迟回放 10:05，以及在 10:10:12 观测却伪造评估时间为 10:05:12。这些对照仅验证断言，不替换生产评估或持久结果。合法的当前 10:05 决策仍可通过，generation 变化仍仅作观测。

完整末版文件作者最终验证：**3 failed, 10 passed，15.08s**，包含三个通过的断言对照。独立 Sol 在 HEAD `3c22bff` 上另行复现 **3 failed, 10 passed，14.90s**，Ruff 通过；两次运行不相加。断言 P2 已关闭，测试证据获认可并可进入修复设计，不代表产品 GREEN。两项不完整数据引发运行器故障的失败与一项冻结截止点失败仍未修复。两个进度用例仍观测到自动替换 generation，并确实于 10:05:12 评估 10:05 目标。作者运行开始时共享 HEAD 为 `3c22bff`，含另一任务尚未提交的 SDK 边界源码改动；这是当前共享工作区证据，不是隔离提交版本的认证。Ruff 及三个文件的空白/双语一致性检查通过。三个文件保持未提交；生产修复须另行完成设计评审。其他任务的源码改动及报告不属于本次变更。

在 `trade-plan-monitor/` 执行的命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q -rP --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_startup_minute_coverage.py
git diff --check
```

## 限制

本片仅覆盖身份稳定的单个当日旧计划证券，不证明多范围公平、任意激活/语义变更、跨日恢复、ExplicitTradePlan 覆盖或全部 A07 验收条件。不修改 UI/API 协议、新鲜度阈值或官方收盘恢复行为。
