# R17 单次上午补测方案——待批准

英文原版为 `R17-execution-proposal.md`，本文为等价中文审阅副本。方案 ID 为 `R17-20260915-MORNING-60`，于 2026-09-14 Asia/Shanghai 基于 `32c21584edd5457474ce1f3804b736fa26f7dfff` 准备。**NOT_AUTHORIZED、NOT_RUN：**新的真实尝试须用户直接批准本方案精确范围。旧 R14 授权、会话占位、数据库与观察记录仅为历史，不能复用。R14-A/C7 未通过：三次真实 DeepSeek 均为 `INVALID_OUTPUT`，精确原因未知；R15 现有有界脱敏诊断，R16 的选择性补取仍不能令旧 25 次指数额度覆盖全滞后截止点。

## R17-P1. 拟定唯一会话与人工前置项

拟定 **2026-09-15 10:12 Asia/Shanghai**，允许启动窗口 **10:10:00–10:30:00（含端点）**，仅一次 `r17-20260915-a`。这是拟定日期，**尚未确认交易所开市**，也不是自动任务。任何付费启动前须核对用户直接批准、交易日历/开市、股票与五指数认证有效、已配置模型权限、账户余额/额度、当前供应商价格和 `127.0.0.1:18765` 空闲。默认干运行只检查配置存在及元数据、日期/窗口、认证、端口和固定额度，不调用供应商；不能确认开市、权限、余额、现价或人工批准。不包含认证续期或模型替换。日期/窗口或前提不满足即停止并另提方案；不得自动重跑或换日。

900 秒截止约束从实际会话启动后的**新物理请求**。若 10:12:00 启动，最后一个预定分钟轮询为 10:26:12，10:27:00 到墙钟停点；10:27:12 已超时。服务停止与隔离计划停用共同使用之后**同一个 20 秒异步清理预算**。这是有界清理尝试，并非 OS/进程取消及本地 I/O 一定恰于总 920 秒前结束的保证；失败记为 `SHUTDOWN_FAILED` 或清理 `FAILED`。只停止自身监听，不触碰 8765。防护拒绝后不重启。

## R17-P2. 固定外部与本地边界

| 范围 | 拟定上限与控制 |
| --- | --- |
| DeepSeek | 对仓库中 `LITERAL`、`SEM-AMB-01`、`SEM-UNS-01` 三份原文各物理请求一次 `POST https://api.deepseek.com/chat/completions`；`deepseek-v4-pro`，非思考 JSON 输出，应用及传输均零重试、30 秒超时、每次提示词 19,000 UTF-8 字节、`max_tokens=4096`。完整中文测试计划和两段短原文会离开本机。联网前校验提示词 hash、模型、URL 与载荷形式。供应商错误也消耗一次尝试。不另做连通测试。 |
| 行情 | 仅一个经 TLS 验证的 `api.quicksync.cn` 直连路由，使用配置 token 和 `connect_ip`，SDK/传输零重试、15 秒超时、`003043.SZ`、SSE/SZSE 日历及五个常开指数（`000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`399107.SZ`）。物理 SDK 请求总计最多 **60**。端点上限：`trade_cal=3`、`stk_limit=0`、`daily=0`、`rt_min_daily=2`、`rt_min=15`、`idx_mins=5`、`rt_idx_min_daily=30`、`index_daily=5`，合计 **60**。失败的已启动请求计数，拒绝发生于联网前并触发 AI/行情共用停机。这是旧 60 总额度的**全新待批准**重分配，不是 R14 授权扩展。 |
| 本地/界面/交易 | `data/r17-acceptance/r17-20260915-a/` 下唯一隔离 SQLite 与 JSONL 诊断，唯一浏览器 `http://127.0.0.1:18765`，仅 `InAppChannel`。无 Webhook、邮件、推送、券商、订单、成交或真实库存。若需测试库存，须在隔离库单独标记为合成。不向其他人发信息。 |

日历需三次而非一次：启动 SSE，激活计划后 SSE 和 SZSE。若 10:15/10:20/10:25 三个已完成截止点五指数均滞后一周期、下一分钟可取到，每个截止点指数实时用 `5+5`，共 **30**。首次成功建成历史及日线缓存各用 `idx_mins=5`、`index_daily=5`；缓存失败则防护停机，不宣称新鲜数据。一次明确测试触发的既有生产恢复消耗 `rt_min_daily=2` 中的一次；另一槽位是预留，不是无限重试许可。活跃股票每分钟可轮询至 15 次上限。在 10:15:30 激活的特定情景中，10:16:12–10:26:12 为 11 次股票轮询，总行情物理启动 55 次（`trade_cal=3`、`rt_min_daily=1`、`rt_min=11`、指数 5+30+5）。这是**SIMULATED 容量结果**，非真实额度或价格保证。第四个全滞后截止点、缓存失败、额外日历/股票刷新、供应商错误或时序变化都可能提前停机。不得削减股票刷新、新鲜度、历史窗口、确认要求或全局停机以凑额度。

2026-09-14 查阅的 DeepSeek [官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)列出 Pro 峰值未缓存输入 1.32 美元/百万 token、输出 3.96 美元/百万 token；R14 三次约 0.124 美元是以提示词字节上限等同计费输入 token 的历史规划。它**不是精确金额上限**。[计费 token 以响应 usage 为准](https://api-docs.deepseek.com/quick_start/token_usage/)；客户端提示词字节/输出参数不能硬控美元。行情端点价格未知，总 60 次上限不保证账单不变。批准前用户须确认适当账户侧支出限制，或知情接受可能收费且无精确货币硬帽。

## R17-P3. 原文复核与观察 oracle

逐字使用原 `LITERAL` fixture 原文：`003043.SZ`，仅当**已完成**五分钟 K 线收盘价在 **9.80–10.00 元闭区间且该根成交量 ≥ 前五根已完成连续五分钟 K 线算术均量的 1.5 倍**时提醒 BUY 100；在 **10.80–11.00 元闭区间**基于独立登记的测试库存提醒 SELL 100；低于 **9.50 元**发纯风险提醒。这是历史测试阈值，不代表现价或交易建议。确认既有人审选项 `CONTIGUOUS_TRADING_BARS`、每激活仅一次及冲突政策。**`TRADING_DAY=2026-09-15` 须由人工重新明确补录和批准**；旧 fixture 的 2026-09-14 补录不得沿用，以上补录均不归因于原文或 AI。不为演示修改价格或数量。

经常规本地原文编辑界面提交三份固定文本。R15 的本地 `monitor.ai-extraction-diagnostics.jsonl` 为每次提取记录无内容结果及安全失败类别/finish reason/校验路径；失败则查看，不重试。对可用结果，人工按独立原文子句/偏移、ALL 逻辑、价格、数量、成交量窗口、缺失政策及未支持/模糊表述比对真实模型输出；保存/激活前核对当前 `reviewId`、原文/内容 hash、expected revision 与计划版本。部分、编造、过期审核或未支持计划不得激活。人工 **10:15:30 前**完成审核仅是容量例子的假设。如果真实模型或人工审核赶不上 10:20 和 10:25 两次完整求值，记录 `NOT_OBSERVED`，不得延长。不预设供应商成功。

首次批准的隔离激活后，启动器**一次**调用现有当日恢复，审计记为 `TEST_TRIGGERED_PRODUCTION_RECOVERY`；不能称为自然开机恢复。须核对从 09:30 起至少 45 根连续上午一分钟 K 线、完整五分钟聚合及**前五根**后才能解释 BUY 均量。即使无自然信号，10:20 和 10:25 两次完整求值仍须有持久化 cutoff、计划/审核/版本/revision hash、条件真值与六根 K 线沿袭。陈旧、缺失、重复、未来、错股票或未完成 K 线及不健康指数不可触发动作。某个信号分支须有真实有效的新鲜供应商行、正确 event/result ID、`IN_APP` 首次投递、与 SQLite/API 一致的本地浏览器可见和 ACK，且库存不变，才可通过。仅 SQLite `DELIVERED` 不等于浏览器收悉。真实价格若未自然满足固定规则，缺席的 BUY/SELL/风险分支标 `NOT_OBSERVED`，不得注入 K 线或宣称 PASS。

## R17-P4. 入口、证据与决定

从 `trade-plan-monitor/` 使用已安装环境；支持的入口是**模块**（不支持直接 `python scripts/r17_bounded_acceptance.py`）：

```powershell
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance
.\.venv\Scripts\python.exe -m pytest tests/unit/test_r17_bounded_acceptance.py tests/integration/test_r14_offline_wiring.py -q -m 'not live' --basetemp "$env:TEMP\pytest-r17-review-unique"
# 仅拟议——未获新的直接批准并完成 P1 核对前绝不能运行：
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance --execute --authorize R17_20260915_3_AI_60_MARKET_IN_APP_15MIN --run-id r17-20260915-a
```

`--authorize` 只是代码门禁，**不是批准证据**。执行模式仅在 `data/r17-acceptance/` 下原子建立 `_session_claimed` 和指定 run 文件夹。成功、失败或中断后占位保留；旧 `data/r14-acceptance/_session_claimed` 不得触碰。隔离 SQLite 可能包含原文与供应商行；仅导出有界脱敏审计/诊断摘要。R17 复用现有防护/服务组合，只新增独立日期、口令、run 根目录及拟定端点额度。不修改 `config/app.yaml`、生产库、真实持仓、8765、R14 原方案或证据；不创建自动任务或下一次尝试。

离线证据见 `remediation/evidence/R17-preparation/offline-simulated.json`。R17 下真实 R14-A/C7 验收仍为 **NOT_RUN**。日后真实结果只有经真实 AI 语义审核、新鲜行情、完整持久化求值与浏览器可见收悉，才能逐分支标 `PASS`；否则如实报告 `PARTIAL`、`NOT_OBSERVED` 或 `FAILED`。下一项决定是用户对 P1–P4 的明确批准或修改，包括 30/2 端点重分配及无精确金额硬帽。
