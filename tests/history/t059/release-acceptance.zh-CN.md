# T059 发布验收证据

> 历史证据说明（截至 2026-09-01）：本报告记录该候选的 T059/C24 发布决定，不声明当前仓库级
> 门禁。下文记录的 AI 凭证流程已被取代：`config/app.yaml` 现在是唯一凭证来源；应用不再读取
> `AI_API_KEY` 或任何其他凭证环境变量。

**状态：**2026-09-01 为 `ACCEPTED`。经另行授权的生产性能修复后，该发布候选的全部已批准
内部离线闸门均为绿色。可选 AI 连通性继续为 `NOT_RUN_UNAUTHORIZED`，用户已于 2026-09-01 完成
最终发布验收。当前仓库级门禁和 LPC012 状态由实时生产链路验收单独记录。

## 1. 决策与证据边界

本报告基于 `d8b28b20e59b91b261ce46003effdb01288d832a`，评估 `T059`、`P18`、`BT008`、
`BC01` 与检查点 `C24`。仓库候选精确包含 12 个正式文件：原始 5 个 T059 文件，加上 7 个另行
授权的 export/capacity 实现与回归文件。它们是双语 README 对、本双语报告对、
`tests/contract/test_ai_live.py`、`src/trade_plan_monitor/` 下的 4 个生产模块及 3 个聚焦回归文件。
依赖、迁移、数据库 schema、API 路径、生成契约、供应商配置及任何已批准性能阈值均未改变。

发布决策为 `ACCEPTED`。这是本报告截至 2026-09-01 记录的历史决定。先前的
`BLOCKED_OFFLINE_PERFORMANCE_GATE` 决策对当时失败的新鲜闸门有效，并针对该候选由下文记录的
RED-first 修复及完整通过闸门取代；随后 `PENDING_FINAL_USER_ACCEPTANCE` 在用户于 2026-09-01
明确验收发布前保持有效。业务时间继续使用 `Asia/Shanghai` 与显式 `+08:00` 语义。对该发布候选，
`C24` 已完成 4/4 项，T059 已完成；这不声明当前仓库级门禁。

## 2. RED 与可选 AI live 闸门

最初的文档 RED 为：

```text
python -m pytest tests/contract/test_ai_live.py -q
1 failed, 1 passed, 1 skipped in 0.14s
T059_RELEASE_REPORT_MISSING
```

离线性能闸门失败后，export profiling 定位到可避免的重复 JSON 解码和逐行 CSV 构造。固定
`>= 5 MiB/s` 阈值保持不变。capacity profiling 随后定位到对未变化日线指标点的重复物化及昂贵的
Windows working-set trimming。RED 测试先证明缺少 prefix reuse、同 identity/不同 OHLC 拒绝、
伪造 prefix 拒绝，以及优化路径与 reference 路径的 report-byte 等价。最小实现使用私有的已签发
DailyBar prefix、精确不可变 bar 对象 identity 检查和普通垃圾回收。公共接口及规范结果字节均未改变。

AI live 测试为可选且自带闸门。普通收集会在读取目标配置前检查精确 marker 表达式，并且绝不构造
HTTP client。真实连接需要 4 个仅存在于当前进程的值：`TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL`、
`TRADE_PLAN_MONITOR_AI_LIVE_MODEL`、`TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256` 和
`AI_API_KEY`。授权是操作 context、规范 HTTPS endpoint、精确 model 与最终换行的 lowercase SHA-256。
精确 selector 为 `python -m pytest tests/contract/test_ai_live.py -q -m live`；只有另行获得操作级联网
授权后才能运行。

本次 T059 没有获得该授权，因此规范结果为 `NOT_RUN_UNAUTHORIZED`。这不会导致确定性监控失败。
未来通过也只能证明有界 Chat Completions envelope 连通性，不能证明 model identity、计划质量、
安全激活或交易正确性。

## 3. 历史发布候选的新鲜离线结果

全部正式 Python 输入均由 Git 跟踪路径构造，并显式加入新的 T059 契约测试。5 个受保护的仅验证
文件均从所有正式 test、lint、format 与 compile 输入中排除。

| 闸门 | 新鲜结果 |
|---|---|
| 排除受保护文件的完整后端套件 | `1949 passed, 4 skipped, 1 warning in 2512.36s` |
| Daily-prefix 聚焦 runner/indicator 套件 | `30 passed in 48.34s` |
| 受影响 capacity 回归 | `106 passed in 53.08s` |
| 精确 ten-symbol/252-day capacity 节点 | `1 passed in 1509.95s` |
| 精确 252-day traced-heap 节点 | `1 passed in 722.73s` |
| 离线 AI provider/drafting 契约 | `106 passed` |
| 已跟踪 SQLite backup/restore 契约 | `9 passed` |
| 前端单元套件 | `26 files, 484 tests passed` |
| 排除受保护文件的 Vue type-check | PASS |
| Production build | PASS |
| 允许的 `Chromium-only` E2E | `6 passed` |
| Ruff check / format | 对已跟踪 Python 加 `tests/contract/test_ai_live.py` 为 PASS |
| `compileall` / `pip check` | PASS / `No broken requirements found` |
| OpenAPI/TypeScript generator `--check` | PASS；current |

唯一 warning 是既有 Starlette `TestClient`/httpx2 deprecation warning。4 个 skip 包含未授权的可选 AI
live probe；没有运行真实 AI、Tushare、Webhook、broker、notification 或其他网络操作。

## 4. 固定性能与资源证据

没有放宽任何验收上限或下限。

| 测量项 | 新鲜观察值 | 固定限制 |
|---|---:|---:|
| 100k export throughput，30 次最小值 | `7.435517829658122 MiB/s` | `>= 5 MiB/s` |
| Export first byte，30 次最大值 | `4.365700006019324 ms` | `<= 250 ms` |
| Export working-memory 增量 | `2,084,864 B` | `<= 256 MiB` |
| 最慢 query p95（`equity`） | `103.6420000018552 ms` | `<= 250 ms` |
| Query database 加 WAL | `298,213,376 B` | `<= 384 MiB` |
| Query working-memory 增量 | `0 B` | `<= 256 MiB` |
| Ten-symbol replay elapsed 范围 | `93.17825320002157–107.31649890000699 s` | 每项 `<= 120 s` |
| Capacity working-set 增量 | `88,616,960 B` | `<= 768 MiB` |
| Capacity market database 加 WAL | `519,028,736 B` | `<= 512 MiB` |
| Capacity result database 加 WAL | `184,909,824 B` | `<= 192 MiB` |
| Capacity traced-heap 增量 | `122,690,533 B` | `<= 384 MiB` |

全部 30 个 export 样本均超过固定下限。daily-prefix 集成测试通过原始完整路径重新计算每个 provisional
和 official context，再逐字节比较每条 decision JSON、完整 canonical report 与 `report_hash`。加入
issued-instance 防伪修复后，新鲜上下文审核没有 P0～P2 问题；剩余 P3 观察仅涉及并未承诺的
no-GIL/其他解释器并发契约。

## 5. 无障碍、安全、soak 与 restore 证据

- **无障碍：**两个允许的已跟踪 Playwright 文件通过全部 6 项 Chromium 测试，覆盖 axe、键盘/
  焦点、reduced motion、响应式 layout 与 200-percent text。Windows NVDA 四路由 checklist 继续使用
  `cb81cf4` 的已验收证据。这是 `Chromium-only` 声明，不声称 Firefox/Gecko。
- **安全：**AI 闸门先检查 selector、绑定 target、仅引用密钥、校验 TLS、忽略 proxy、禁止 redirect、
  限制资源，并把供应商失败脱敏为稳定 code。全部正式 security 断言均通过。一次诊断搜索意外扫描了
  3 个受保护后端验证文件，并显示 restore 文件中的 2 个匹配行。该事件已披露，用户允许继续，搜索
  结果从证据中排除。没有修改、运行、暂存或提交任何受保护文件。
- **Soak/capacity：**10 个 252-day replay、固定存储上限、working-set 上限、traced-heap 上限、query
  latency 及 100k export throughput 均以以上测量值通过。
- **Restore：**全部 9 个已跟踪 SQLite backup/restore 测试通过。已验收 BT050 证据还覆盖 migration
  backup fingerprint 绑定、`PRAGMA integrity_check = ok`、WAL sentinel、replay recovery、lease
  fencing，以及通过已验证文件 restore 而不是猜测 reverse SQL 的 rollback。

## 6. 已批准证据映射

| 已批准边界 | 截至 2026-09-01 的证据与决定 |
|---|---|
| `P18` / `T058` 真实 Tushare | `d8b28b2`：授权 visible-block 分支；5 项能力映射为可见 `ERROR`，应用保持 `DEGRADED` 和只读 |
| `BT008` / `BC01` | `eee65fd`：确定性两股票旅程、live-state zero-diff、零 provider/notification/WebSocket 调用、恢复、保留、pin/unpin 与 initial-lot 证据；`BC01` 继续为 Complete |
| AI provider 边界 | 106 项离线契约通过；可选 live 连接为 `NOT_RUN_UNAUTHORIZED` |
| 浏览器/无障碍 | 484 项单元测试、6 项允许的 Chromium E2E 及已验收 NVDA 证据 |
| Backup/restore | 9 项新鲜已跟踪测试，加已验收 BT050 migration/restore 证据 |
| 完整发布闸门 | 该候选的全部已批准内部闸门均通过；用户已于 2026-09-01 验收发布，C24 四项检查对该历史发布决定全部关闭 |

## 7. 备份、回滚与运行边界

候选不含 migration 或 schema 变更。执行任何数据库恢复前，应使用已验证 SQLite online backup，要求
`PRAGMA integrity_check = ok`，验证 schema 与来源 fingerprint，停止本地进程，并恢复完整已验证
文件集。不得复制正在使用的 `.sqlite3` 文件或编造 reverse SQL。

Rollback 仅限精确 12 个仓库候选文件；不授权删除用户数据或回退已验收 BT050/T058 commit。产品
继续为精确 `127.0.0.1` 上的 `local-only`、`reminder-only`，并且不能下单。历史 fill 是模拟研究
记录，绝不是 broker execution。没有 remote bind、tunnel、high-availability component、automatic
order path 或 live AI decision path 被验收。

## 8. 已知限制与开放决策

- `ACCEPTED`：用户已于 2026-09-01 明确确认最终发布验收；C24 四项检查对该历史发布决定全部关闭，不能作为当前仓库级门禁的声明。
- `NOT_RUN_UNAUTHORIZED`：没有调用可选 AI 连通性；未来调用需要新的精确授权和已配置 target/secret
  reference。
- T058 验收的是 visible-block 结果，不是 provider readiness；不声称当前真实 Tushare 可用。
- 浏览器证据为 `Chromium-only`；Firefox/Gecko 兼容性不在已批准 profile 中。
- 既有 Starlette `TestClient`/httpx2 deprecation warning 继续是唯一 suite warning。
- 5 个仅验证的未跟踪文件继续不进入正式输入和 Git。

## 9. C24 发布清单

- [x] 完整离线 backend/frontend/replay/browser/security/accessibility/soak/restore 闸门对 2026-09-01 发布候选通过。
- [x] `BC01` 继续完成，并具有 live-state isolation 和 bounded-retention 证据。
- [x] 授权 live-contract 证据为双语，可选 AI 连通性继续如实为 `NOT_RUN_UNAUTHORIZED`，且没有削弱
  确定性监控。
- [x] 用户已于 2026-09-01 确认最终验收。

本清单适用于 2026-09-01 发布候选。当前仓库级门禁和 LPC012 状态不属于本历史报告。

<!-- T059-CANONICAL-EVIDENCE-START -->
```json
{
  "aiLive": "NOT_RUN_UNAUTHORIZED",
  "backtestAcceptanceCommit": "eee65fd9ede37cee229c0147ba2ddb55a5f311d5",
  "baseline": "d8b28b20e59b91b261ce46003effdb01288d832a",
  "capacity": {
    "marketDatabaseAndWalBytes": 519028736,
    "maximumReplayElapsedSeconds": 107.31649890000699,
    "minimumReplayElapsedSeconds": 93.17825320002157,
    "resultDatabaseAndWalBytes": 184909824,
    "status": "PASSED",
    "tracedHeapDeltaBytes": 122690533,
    "workingSetDeltaBytes": 88616960
  },
  "chromiumE2E": {
    "passed": 6,
    "status": "PASSED"
  },
  "export": {
    "firstByteMaximumMilliseconds": 4.365700006019324,
    "minimumThroughputMiBPerSecond": 7.435517829658122,
    "requiredMinimumThroughputMiBPerSecond": 5,
    "status": "PASSED"
  },
  "frontendUnit": {
    "passed": 484,
    "status": "PASSED"
  },
  "offlineAI": {
    "passed": 106,
    "status": "PASSED"
  },
  "offlineBackend": {
    "durationSeconds": 2512.36,
    "passed": 1949,
    "skipped": 4,
    "status": "PASSED",
    "warnings": 1
  },
  "releaseDecision": "ACCEPTED",
  "restore": {
    "passed": 9,
    "status": "PASSED"
  },
  "timezone": "Asia/Shanghai",
  "tushareLiveEvidenceCommit": "d8b28b20e59b91b261ce46003effdb01288d832a"
}
```
<!-- T059-CANONICAL-EVIDENCE-END -->
