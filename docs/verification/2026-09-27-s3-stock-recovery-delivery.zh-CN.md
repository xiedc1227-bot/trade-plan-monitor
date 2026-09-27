# S3 修复显式事实与最终投递准入

## SRD-01 — 范围与状态

基线 `5e56c41` 加未提交 F3-C 源码候选。本 tests-only connected 代表使用 `tests/integration/test_s3_stock_recovery_delivery.py` 及本双语报告，证明真实 scheduled repair → 合法显式评估 → 持久 claim → 实际 `CurrentDeliveryAdmission`。**最终独立源码/测试评审通过，无剩余 P1/P2；报告 parity 已批准。** 本代表不归因任何源码修改。未提交/推送/部署/使用真实服务或用户数据库。

Fixture 使用临时 SQLite、有效认证、真实 composition/scheduler/controller/provider/evaluator/dispatcher、合法 current-bar 显式 BUY 规则和已登记库存。禁止 HTTP。只有物理 SDK 与外部 CONSOLE channel 为假；不是 IN_APP，也不发送真实通知。保留实际最终准入 callable，不替换。计划/配置/时钟来自已提交 helper；不导入未跟踪 A07 helper。

## SRD-02 — 已连接控制

两个用例均从 empty startup 响应开始。真实 scheduler 随后调用 STOCK_RECOVERY；在实际 SDK 调用内断言 deadline kind、所属 runtime task 及精确 `stock-prefix:{symbol}` schedule entry 的 `in_progress`。修复分钟在下一合法评估前已提交，此时显式 ledger/alert 仍不存在。测试不直接调用恢复/评估、不预置 alert/ledger、不 mock evaluator。

真实 target 10:05 于 10:05:12 评估时，合法显式结果提交初始投递资格 HOLD。真实 dispatcher 先提交 CLAIMED，通过另一连接确认后才执行变更：

- Metadata 正控：通过既有 helper 重写认证元数据，并断言磁盘 `semanticRevision` 与已安装 `semantic_revision` 完全相同。真实最终准入允许一次假 CONSOLE 发送并形成 DELIVERED。
- Reactivation 负控：真实 repository deactivate revision 1，再 activate expected revision 2，产生当前 activation revision 3。真实最终准入抑制旧 event，零发送，资格为 SUPPRESS。已经合法提交的 CLAIMED attempt 可以保留，测试明确保留它；不错误要求 attempts 为零。

Claim 时测试快照 `explicit_evaluation_ledger`、`explicit_rule_occurrence_state`、`alert_event`、`minute_bar` 每一列。投递/抑制后四组行值完全相同；原 hash、activation revision 1、event provenance 不变。结果仍为精确 target 10:05、实际 evaluated_at 10:05:12。Runtime generation 不变，无 runner fault。

## SRD-03 — 证据与限制

本片为新增验收代表，不是基线产品 RED。初始 fixture 修正涉及日历设置、composition admission wrapper、实际 rule-state 表名及 JSON 驼峰 `semanticRevision`；均不是产品修复。未削弱失败的产品断言。

最终硬 oracle 及日期/fatal 源码修复后，作者运行下列命令为 **43 passed, 1 warning, 26.18s**，包含两个 delivery 用例：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
```

早期单独两例为 2 passed, 1 warning, 3.09s，发生在追加硬 oracle 前，不作为末版证据。末版源码与 43 用例窗口唯一区别为表达式换行。作者全量 `.venv/Scripts/python.exe -m ruff check src tests scripts` 通过。源码/测试独立评审后继续冻结。本代表不宣称覆盖所有通知通道、所有显式规则变体、跨日 requirement 或 C1 权限调度。

## 最终独立验证

独立 Sol 在 `trade-plan-monitor` 目录针对末版冻结源码/测试运行以下精确命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**。11 个 SHA256（四个源码、七个测试文件）运行前后均与最终冻结值完全一致。Ruff 与 diff 检查通过。最终 F3-C/A07 源码/测试无剩余 P1/P2；startup fatal 掩盖 P2 已关闭。此前独立 155/28.47s 窗口跨 AD22→38608 仅换行修改，不作为最终 fixed-revision 验收；由本次 159 用例覆盖，而非相加。作者与独立窗口保持分列。五组双语报告 parity 已独立核对通过；不宣称整体 C1/C3 已关闭。本次文档更新不修改源码/测试，也不提交。
