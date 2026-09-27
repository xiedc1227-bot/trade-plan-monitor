# S3 股票恢复 owner — F3-A

## SRO-01 — 状态与范围

基线：`1254761`，包含已验收 F2 `6bcf080`。F3-A 设计及纯 schedule 的窄接口扩展已获批准。独立源码/测试评审通过，无 P1/P2；双语报告 parity 和 root 验收待完成。这是**尚未接线的中间薄片**，不是 F3、A07 或 S3-04 完成。

六个候选路径为 `runtime/production.py`、`runtime/reconciliation.py`、`tests/integration/test_s3_stock_recovery_owner.py`、`tests/unit/test_runtime_reconciliation.py` 及本双语报告。runtime 路径位于 `src/trade_plan_monitor/` 下。

只有显式 `_synchronize_stock_recovery()` 观察本地事实。`next_stock_recovery_at()` 仅返回缓存，不执行 SQL、文件读取、controller 调用、时钟读取或状态修改。未增加默认调用者、请求、后台循环、scheduler/service/composition 接线、provider/controller 修改、业务写入、schema 或依赖修改。启动仍保留已验收 F2 最多 10 个标的的过渡行为；F3-B 执行器、仅 maintenance 的 31.25 秒预留、F3-C 启动最多一次及真实自主进展均为后续独立工作。`MAX_RECOVERY_SCOPES = 32` 不变。

## SRO-02 — 已实现不变量

- 短自有读取最多加载 10 条 ACTIVE 记录，总数超限则拒绝，检查 F2 的精确 plan/activation 身份，并由权威日历确定当天目标。每个 legacy scope 最多包含 240 个精确会话分钟身份，排除午休及未来分钟。missing 来自已提交事实差集，不依赖行数或最大时间戳。
- 独立 `RecoverySchedule` 使用 `stock-prefix:{symbol}`。latest desired capture/requirement、missing 身份、权威权限观测、permission-readiness epoch 和下一 wake 均为有界 owner 缓存。revision 包含精确计划依赖、截止点/日期、source/Event 身份、稳定语义 revision、配置、authority epoch 和 runtime generation；仅刷新观测时间不改变它。
- 精确已提交覆盖可在零获取时成为 READY。explicit 仅保留既有有界当天预取：该缓存不是 explicit 求值就绪，也不增加跨日恢复或 legacy readiness 门槛。
- 既有 RETRY deadline 跨目标变化及晚完成保留。未知目标/日历产生零请求，并使用既有 30 秒间隔作固定本地再观察，只有到期才顺延。
- BLOCKED schedule revision 保持冻结，latest desired 目标在独立缓存推进。只有同一未撤销 binding 下观察到真实 controller blocked→cleared，才增加 readiness epoch 并显式同步新 requirement。业务恢复不探测或解除权限。指数 operation 阻断仍独立。
- source/client/inner-client/Event 使用精确对象身份；语义使用 `semantic_revision`，不是合约对象身份。纯元数据刷新保留 pending、blocked 和 retry 状态。撤销、binding 改变或旧 generation 拒绝同步、不 rearm，并关闭缓存 wake。停用移除 scope。

## SRO-03 — RED 历程与接口纠正

使用 TDD、增量实现、Git 范围隔离和安全边界检查。初始 fixture 错误（错误样例标的、不可修改实例 monkeypatch、遗漏 `work_key`、未来行 `received_at`）单独修正，不计为产品缺陷。

1. 最小 owner 入口/getter 测试：修正标的 fixture 后 **3 failed，1 warning，1.74s**，全部为缺少 API；随后 **3 passed，1 warning，1.62s**。
2. 最初缺少 source/client-inner/authority-epoch 拒绝。最初的 semantic-copy 拒绝 oracle 过严，**不是**产品修复证据。root 要求稳定语义 revision 兼容。三个真实纯元数据刷新正控随后失败（**3 failed，23 passed，1 warning，5.55s**），修正 binding 比较后通过。
3. root 发现经 `claim/complete(PENDING)` 分类本地状态会消耗实际轮转机会。确定性的 A/PENDING、B/future-RETRY、C/PENDING owner 对照真实失败（**1 failed，15 passed，1 warning，3.86s**）。
4. root 与独立 Sol 在扩展源码范围前批准最小 `resolve_local(requirement, result, *, now) -> bool` 接口。12 个新增单元对照及公平性对照为 RED（**13 failed，27 passed，1 warning，3.98s**），随后 **40 passed，1 warning，3.80s**。

`resolve_local` 只修改 `entry.result`，不改变 `_order`、`_owned` 或 identity。它要求精确当前 requirement 且状态为 PENDING 或到期 RETRY；未来 RETRY、READY、BLOCKED 及同一稳定 scope 的任何 owned ticket（包括旧 revision/移除再加入）均保持不变。允许 READY/BLOCKED/严格未来 RETRY，拒绝 PENDING。无关 scope 的本地分类不能替代物理 ticket。owner 不为已知 missing 事实调用它。最终覆盖还包含晚 RETRY floor、有界读取且零业务 SQL 写入、全部会话边界、重新激活/停用，以及 binding 改变后的权威解除。

## SRO-04 — 作者最终验证

全部命令从 `trade-plan-monitor` 执行，使用离线及临时数据库。未使用真实服务、真实用户数据库、推送或部署。下列计数为独立运行，不相加。

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_owner.py', 'tests/unit/test_runtime_reconciliation.py', '-q', '--tb=short']))"
```

**59 passed，1 warning，6.69s**：35 个 owner 测试及 24 个 schedule 测试（既有 12 + 新增 12）。A07 import blocker 证明候选仅依赖已提交 helper。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_frozen_startup_recovery.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_recovery_activation_fences.py tests/integration/test_production_semantic_gate.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_runtime.py -q --tb=short
```

七文件集成批次：**182 passed，1 warning，44.71s**。scheduler/runtime 单元批次：**88 passed，2.36s**。较早命令使用不存在的 `tests/unit/test_runtime_scheduler.py`，没有收集测试，不是通过证据。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

**11 passed，2 failed，11.98s**。仅未修改的 A-empty/B-missing-0931 自主进展用例仍 RED；F2 截止点及原 oracle 对照通过。原 A07 文件未修改。没有通过 runner 换代、压低断言、skip 或 xfail 关闭该缺口。

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/runtime/reconciliation.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_stock_recovery_owner.py
git diff --check
```

二者通过（Ruff 是限定范围，不是全项目）。既有 Starlette/httpx 弃用 warning 不变。此前 3/11/40/50/59 开发运行是最终候选前的窗口，不是独立验收。

## SRO-05 — 冻结候选与独立评审

独立 Sol 源码/测试评审通过，无 P1/P2；实现作者没有提交。独立命令和结果：

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_owner.py', 'tests/unit/test_runtime_reconciliation.py', 'tests/unit/test_recovery_coordinator.py', 'tests/unit/test_recovery_targets.py', '-q', '--tb=short']))"
.venv/Scripts/python.exe -m pytest tests/integration/test_production_semantic_gate.py tests/integration/test_s3_installed_runtime_read_liveness.py -q --tb=short
```

分别为 **107 passed，1 warning，6.88s** 和 **13 passed，1 warning，5.22s**。reviewer 确认四路径 Ruff 命令、diff check 通过，四个源码/测试 hash 未变。reviewer 未重跑原 A07；SRO-04 的 11/2 仅为作者结果，不是独立证据。源码/测试 SHA256：

| 路径 | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `8DE77DBC7982E51EE5D64214B0E730144AC7CD6A9540F2886A2F124F73C4887E` |
| `src/trade_plan_monitor/runtime/reconciliation.py` | `6992DABFFA617B0C1B467363A7753F720C451FAC874837095EB9E387547E1A19` |
| `tests/unit/test_runtime_reconciliation.py` | `E2D37F1267BCBE72E046401D81F963E502FE6F0C9CEEDA285D8626A8F5E6B604` |
| `tests/integration/test_s3_stock_recovery_owner.py` | `BFEB26492D211B17B2F74F67D56C4F2B805EB85B4E31A1E85515DD998490EB8D` |

残余边界：该缓存不是获取/提交权限。F3-B 必须重新捕获，应用 F2 约束、封闭 F3-09 结果矩阵及仅 maintenance 的预留。F3-C 必须提供真实 scheduler/lifecycle ownership，并证明同 generation 的 10:05:12 求值，以及求值前 public readiness 不可操作。既有官方收盘、manual admission 和 120h 政策未修改。
