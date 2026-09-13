# R14 准备交接

英文原版为 `R14-preparation.md`，本文是等价中文审阅副本。2026-09-13（Asia/Shanghai）在共享的 `trade-plan-monitor` 工作区准备。协调任务对 C6/R13-A 的离线结论在其定义范围内仍为 PASS。**R14-A 真实验证仍为 NOT_RUN。** 本任务未调用真实 AI、行情、webhook、券商、订单、成交、生产数据库或真实持仓。

## 1. 交付物与提交

实现、双语方案与脱敏干运行证据始于提交 `e17eb99e376178674de1662afa5829fc3695228e`；激活后历史恢复位于 `c03f9b48088fd0eea19f0b603f50614739d775ee`；离线生产接线和预算修正位于 `4a4ce1e988348a5d2a8f89d90a22678d4ab29568`：

- `scripts/r14_bounded_acceptance.py` 默认干运行。获批模式先原子占用一次本地会话，在 Git 忽略目录创建隔离 SQLite，在 `127.0.0.1:18765` 有界运行现有应用，只选择已配置的 DeepSeek Pro，并对 AI HTTP 和生产 Tushare SDK 查询设置共享拒绝锁存的物理调用前预算。界面激活后调用一次既有当日恢复服务取得前五根历史，占用 `rt_min_daily` 额度，审计如实标明此步骤由测试触发。仅组合 `InAppChannel`。会话后只停止自身服务并停用隔离的 `003043.SZ` 测试计划。不修改 `config/app.yaml`、生产默认值、Schema、提示词或现有 `8765` 进程。
- [执行方案](../../docs/verification/R14-execution-proposal.zh-CN.md)及[英文原版](../../docs/verification/R14-execution-proposal.md)包含精确范围、命令、复核 oracle、失败处理与价格局限。
- `remediation/evidence/R14-preparation/` 包含白名单预检、未授权拒绝（`exit 2`）、零调用记录、16个受保护文件的基线 hash，以及计入合成供应商调用的 `offline-wiring.json`。早期预检记录的是旧30次查询方案；当前干运行报告60次。文件均不含凭证或原始供应商响应。

## 2. 离线验证与当前事实

- 聚焦命令：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_r14_bounded_acceptance.py tests/integration/test_r14_offline_wiring.py tests/unit/test_live_certification_launcher.py tests/unit/test_live_certification_runner.py tests/unit/test_live_certification_profiles.py tests/unit/test_ai_plan_extraction_v4.py tests/contract/test_tushare_live.py -q -m "not live"` → **34 passed，3项 live 排除**。Ruff 检查和格式检查通过。新增测试用合成 AI HTTP 与 SDK 传输进入真实 FastAPI 生命周期及生产组合，把三个固定原文送入常规提取 API，复核/激活**单独的数值等价合成简写**，调用测试触发的生产恢复，再推进十个生产调度截止点得到两次持久化五分钟求值。精确记录**39**次受控行情查询：`trade_cal=3`、`idx_mins=5`、`rt_idx_min_daily=15`、`index_daily=5`、`rt_min_daily=1`、`rt_min=10`。启动器拒绝测试记录 `BUDGET_DENIED`／退出码1、隔离计划停用和SDK工厂恢复。直连 SDK 传输验证15秒超时和关闭urllib3重试；选定AI绑定及发出请求均使用30秒超时和零重试。不声称真实恢复、AI、SDK、socket/浏览器收悉或行情响应已发生。
- `config/app.yaml` 校验通过，两种凭证字段存在。AI 主机/类型为 `api.deepseek.com`/`DEEPSEEK`；已配置主模型 `deepseek-flash`、附加模型 `deepseek-v4-pro`；行情主机 `api.quicksync.cn`，直连 `connect_ip` 已配置。DeepSeek 当前官方模型列表包含附加 Pro 模型，未列出主模型。字段存在**不证明**余额或权限。2026-09-09 观察到的股票认证旧记录有效至 2026-09-16 14:48:40+08:00；2026-09-11 观察到的指数认证旧记录有效至 2026-09-18 10:20:44+08:00。两者均非本次 R14 新证据。
- 星期日 2026-09-13 预检为 `weekdayWindowEligible=false`、`exchangeOpenDayConfirmed=false`、`isolatedPortAvailable=true`、`ready=false`。拒绝命令返回 `NOT_RUN_AUTHORIZATION_OR_PREFLIGHT`，退出码 `2`；测试专属 `dry-run-probe` 数据库目录不存在。真实调用 AI **0**、行情 **0**。12个已有 tracked 用户改动和4个 R00 untracked 文件均与记录的 SHA-256 基线相同；未暂存任何受保护文件。

## 3. 可审阅的授权边界

修订的**唯一一次会话**使用 `deepseek-v4-pro`，对固定 fixture 输入 `LITERAL`、`SEM-AMB-01`、`SEM-UNS-01` 各一次：最多**3次物理 AI 尝试**（每输入1次、重试0），每次提示词最多**19,000 UTF-8字节**、请求输出**4096 token**。完整中文原文计划与两段短文本将发送至 `api.deepseek.com`。行情仅包括 `003043.SZ`、SSE/SZSE日历和五个生产始终启用的指数代码；`api.quicksync.cn` SDK 最多**60次物理查询**，端点上限 `trade_cal=3`、`stk_limit=0`、`daily=0`、`rt_min_daily=3`、`rt_min=15`、`idx_mins=5`、`rt_idx_min_daily=25`、`index_daily=5`，周期内/传输重试均为0。旧30次查询草案从未获授权；正常双求值离线接线消耗39次，因此由60次方案替代。获批后第一次开市会话须在 2026-09-14/15/16 的13:10–14:30+08:00启动；新调用截止**900秒**，另最多**20秒**关停。只允许本地 IN_APP/浏览器，不允许外部收件人或交易动作。

按当前公开 Pro 高峰价格，并把每次19,000字节暂按19,000 token、每次4096输出 token 规划，合计约**0.124美元**；实际计费输入 token、费用、账户余额及 `api.quicksync.cn` 额度/价格仍未经验证。客户端**无法强制计费输入 token 或美元金额硬上限**。真实运行前账户所有者应确认账户侧消费/额度控制，或明确接受“调用数有界、美元金额无保证”的风险。本任务不应索取密钥，也不应让用户把密钥贴到会话。若获批时间前股票认证过期，本批次不能执行，须另定认证额度。

精确默认只读命令：`.\.venv\Scripts\python.exe scripts\r14_bounded_acceptance.py`。仅在上述具体授权且预检合格后：`.\.venv\Scripts\python.exe scripts\r14_bounded_acceptance.py --execute --authorize R14_3_AI_60_MARKET_IN_APP_15MIN --run-id r14-20260914-a`。代码强制与日期一致的 run ID 和一次本地原子占位；可复用的命令文本**不是授权证明**。交易所开市、原文 oracle 验收、人工复核耗时、消费/额度控制及9月15/16日日期补录仍须操作员/审阅者判断。复制工作区不受本地一次性标记覆盖。

## 4. 验收与剩余工作

原 literal fixture 的9.80–10.00元 BUY 且前五根均量1.5倍、10.80–11.00元 SELL、低于9.50元纯风险阈值均保留，不因现价而调整。`TRADING_DAY=2026-09-14` 及其他政策单独标为人工测试补录，须做当前复核；若会话在9月15/16日，必须另审阅日期补录。浏览器操作员须走常规提取/复核/激活路径，并按原文独立 oracle 人工比对三次真实 AI 输出。测试触发的当日恢复必须报告足够连续的一分钟真实K线，以形成前五根已完成K线；不能称为常规启动恢复。须交叉核对新鲜已完成五分钟K线及前五根历史、单位/时间标签/陈旧/空数据、计划/版本/复核/激活/cutoff/resultHash/eventId、SQLite IN_APP 投递和浏览器实际可见。若15分钟内没有条件自然触发，BUY/SELL/风险分别标 `NOT_OBSERVED`；不得注入伪装真实的合成K线、改阈值或推断 PASS。

本任务未提出授权请求。协调任务须先审阅修订的60次查询边界、双语方案中的13:12–13:27精确容量例子、金额/token局限及剩余离线缺口，再决定如何向用户提出授权。复核缓慢、首次指数批次无效、发布滞后或休市仍可能使一次性会话在双求值前结束；按事实标 `NOT_OBSERVED` 或失败，不延长或重启。测试采用虚拟调度时钟和测试本地服务适配器，真实 Uvicorn/浏览器时序、literal AI 至激活的语义、供应商权限及实际 IN_APP 浏览器收悉仍为 `UNVERIFIED`／`NOT_RUN`。R14-A 与 C7 仍待有界真实证据。
