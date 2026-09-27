# C1 UPD-S4 — RUNNING 权限调度

## 状态与范围

统一权限配对契约已获批准。本片从 S3/R17 `f4be66ed0a9c7c7815106a0e9de1892e10e5f4a5` 开始；当前基线 `54b70f6` 仅新增进度文档。独立实现评审及最终报告对等性通过，无剩余 P1/P2。S5/DEGRADED、完整 R18、C1/C3 与最终全量门禁仍未关闭。

仅修改两个生产接点：`src/trade_plan_monitor/web/monitor_composition.py` 的 `next_index_permission_at()` 直接适配八 scope 纯缓存 getter（pipeline 不存在时返回 `None`）；`src/trade_plan_monitor/runtime/production.py` 将 `INDEX_PERMISSION` 送入共同单元，保留已授权股票恢复同步及提前返回。不改 scheduler/service/provider/controller/startup，不新增循环或放宽政策。保留 F3 已有的双游标维护处理与投递排除。

新增覆盖位于 `tests/integration/test_unified_permission_running.py`。独立作者的真实调度权限停机测试及报告对属于其自身证据记录。全部使用离线 SDK 边界与临时 SQLite；无真实服务、用户数据库、部署、推送或依赖升级。提交权仍由 root 持有。

本片精确七条路径（独立停机薄片另拥有三条路径）：

- `src/trade_plan_monitor/runtime/production.py`
- `src/trade_plan_monitor/web/monitor_composition.py`
- `tests/integration/test_unified_permission_running.py`
- `tests/integration/test_production_index_historical_permission_probe.py`
- `tests/integration/test_production_index_realtime_permission_probe.py`
- `docs/verification/2026-09-27-c1-permission-running.md`
- `docs/verification/2026-09-27-c1-permission-running.zh-CN.md`

## 连接证据

- 真实 RUNNING composition/scheduler 按轮转顺序执行全部八 scope；仅指数正控在无股票权限或股票 SDK 调用时执行三个指数 scope。每次权限 duty 都是实际 `INDEX_PERMISSION` owned task，恰一次 SDK 调用与持久化确认、仅解除自身权限，runtime/runner/generation 不变，每次释放唤醒均无 runner 故障。
- 每个权限分支比较全部应用表的完整行，仅排除迁移元数据、运行存活与供应商检查点。分支内禁止业务 coordinator 执行及 `dispatch_pending`。合法行情工作独立观察，不混称为权限副作用。
- pipeline/composition 时间 getter 在到期前后均保持纯读取，禁止时钟、认证、session、旧指数 getter 与 B1 访问。无 pipeline 时不会 bootstrap。
- 真实同刻行情期限先执行；权限在 `+1us` 后执行，保留行情游标与原 bar 目标。真实控制器队列阻塞权限请求 8 秒：capture 年龄仍在 15 秒内，但距真实行情期限不足 31.25 秒。SDK 不入场；持久化 300 秒预约与恰一次确认保留，之后执行原行情目标。
- 实际 SDK 在距下一真实行情期限超过 31.25 秒时合法入场。held SDK 释放后分别跨过一个新鲜期限（恰一次原目标，年龄 13 秒）、多个期限（不补放）、上午最后目标超过 90 秒（不补放过期目标）。维护期间进度游标和 elapsed-review 下界均保留原值。在有界虚拟唤醒/held 响应释放前发布真实同 owner heartbeat；不伪造 health、admission、generation 或 scheduler window 结果。

## RED 历史与夹具区分

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_running.py -q --tb=short
```

初始脚手架有两处观察错误：runner 属于 composition，`_running_deadline` 是布尔 `False` 而非 `None`。这是夹具修正，不是产品修复。使用正确测试临时恢复两个原始源码接点后，得到 **3 failed, 1 passed, 1 warning in 4.15s**：实际权限 duty 返回 `SKIPPED` 而非探测，两个纯适配器检查触达旧认证 getter。恢复最小实现后得到 **4 passed, 1 warning in 4.43s**。扩展核心得到 **10 tests passed, 1 warning in 6.72s**；Ruff 通过。警告来自既有 Starlette `httpx` 弃用提示。

首次直接相邻运行得到 **4 failed, 245 passed, 1 warning in 36.44s**。三个历史指数 direct-owner 夹具未预期 S3 已批准的 typed 权限撤销异常；其中 `stopping` 参数实际设置 `admission_revoked=True`，并非仅旧 generation。一个实时指数夹具在 09:35、已知开场期限为 09:35:12 时仍期待 `SKIPPED`，而非 S3 的 `DEFERRED`。Sol/root 仅批准窄范围测试对齐：三个 typed 预期与一个 DEFERRED 预期，保留 raw/block/cursor/SDK 零调用/业务对照，并断言本地 map 与适配器期限精确为 09:35:12，而非通用 +30 秒。普通 generation 退休保持不变。不需要源码变更。这是 S3 direct-entry 政策对齐遗漏，不是 S4 产品 RED。

定向命令得到 **8 tests passed, 63 deselected in 3.01s**，无警告：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py -k 'stale_authority_or_cooldown or first_current_day_five' -q --tb=short
```

## 验证命令与冻结源码

直接相邻命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/unit/test_monitor_runtime.py -q --tb=short
```

最终作者相邻结果为 **249 passed, 1 warning in 36.92s**。限定 Ruff 与 `git diff --check` 通过；两个源码文件和新测试全程保持原哈希。重叠窗口计数不相加。

当前冻结 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `A716E8B068919E5C2AD2D68F19CA65BB115F616795E1CB7E7B2B6822D6B00567` |
| `tests/integration/test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |
| `tests/integration/test_production_index_historical_permission_probe.py` | `CC343D8880097AB98400E9630FCCBABBBD446C48A51A9340E502A9F64B03648B` |
| `tests/integration/test_production_index_realtime_permission_probe.py` | `91AD3514D5B3CFD3E7EE125E159EA24280EFC3A543499E49505D2CAB9521285E` |

## 独立验证

Sol 独立运行上述精确单文件目标命令：**10 passed, 1 warning in 6.72s**。该窗口观察的八个哈希全部保持不变（六个 runtime/composition 源码、RUNNING 测试与独立作者的停机测试）。停机用例单独运行并记录于自身配对报告，不合并虚构为一次 11 用例运行。

Sol 随后在获批夹具迁移后运行上述精确六文件相邻命令：**249 passed, 1 warning in 36.05s**。全部十条观察路径的完整 pre/post JSON 哈希一致（原八条加历史/实时指数夹具）。限定 Ruff 覆盖两个修改源码与 RUNNING/历史指数/实时指数/停机测试；`git diff --check` 通过。静态评审确认两个源码接点与窄夹具变更，无剩余 P1/P2。最终报告对等性通过。

S3/R17 历史结果不冒充 S4 自动调度验收；本次 RUNNING 结果不证明 S5/DEGRADED 行为。
