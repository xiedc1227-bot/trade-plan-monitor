# 结果尾延迟：有界归因

批准范围：用户实施指令，2026-10-22。[英文主文档](SPEC-result-tail-latency.md)。[提案](PROPOSAL-result-tail-latency.zh-CN.md)。[任务](TASKS-result-tail-latency.zh-CN.md)。

## RLT-S01. 目标与问题

先实现 P0：在真实结果页区分观察者延迟、准入等待、物理执行、证据校验和响应交付。成功请求 >=8 秒由哪些阶段构成？多个逻辑请求是否共享同一物理读取？观察者退出后，受管工作是否仍正确排空？P1 取决于实测重复工作及原有验收门槛。保留已有改动和历史证据。

## RLT-S02. 追踪契约与边界

通过 `TPM_READ_TRACE_DIR` 显式启用；未设置时没有输出端、新文件或诊断响应头。本地窗口持续 1800 秒，最多准入 1024 条追踪、同时活跃 64 条。每条追踪最多保留 64 个固定名称跨度/时间点。内存最多保留 128 条完成追踪。JSONL 记录 <=16384 UTF-8 字节；轮转文件为 1 MiB、保留 2 个备份。未知字段/阶段名和超大记录只在观测层拒绝。所有上限只影响诊断，不影响业务准入、授权或校验。追踪初始化、记录和输出端失败不能改变业务响应。

使用生成的不含业务含义的 trace/physical ID、固定入口/阶段/状态类别、单调时间戳、时长、同步 worker 线程 CPU、计数和字节长度。不记录原文/计划/证据正文、SQL 值、原始 URL、用户提供的 ID、权威令牌或凭据。HTTP 响应头 `X-Read-Trace-ID` 关联浏览器计时与根追踪；共享结果观察者引用同一物理追踪，其 CPU 只记录一次。异步等待不能把事件循环 CPU 算作自身。取消后物理工作仍可观测；不引入完成证明复用。

通过 epoch 锚点关联浏览器与服务器时钟；所有时长/截止时间仍使用单调时钟。WebSocket accept 响应头同样只暴露 `X-Read-Trace-ID`，将连接追踪与心跳/读取子追踪关联，不改变帧、cursor 或周期。线程传播仅绑定诊断上下文，不向物理回测 worker 复制调用者权威/会话上下文。ASGI 正文时间戳表示交接完成，不是远端收到。响应阶段残余包含框架校验/编码、中间件和调度，不计作独占序列化 CPU。

## RLT-S03. 阶段与保护边界

观测 HTTP 入口/响应头/正文完成，metadata/result 准入、worker 提交/开始/完成、结果加入/观察者取消、不可变输入、报告/绑定、全量审计/诊断及显式公开响应校验。单列端点返回与响应头，使框架响应校验/编码及中间件/调度成为明确残余，不能误标为纯序列化 CPU。浏览器分别记录请求/首字节/正文完成/就绪，并关联响应头 ID。在不改变节奏的前提下，为监控读取和心跳增加独立前后权威跨度、快照及 activation 重读跨度。

保留每请求权威、时钟/BEGIN 快照、activation 重读、plan/inventory/risk/calendar/proof 检查及重试预算。保留 monitor 上限、仅在途共享、结果调用者元数据检查、事件 schema/规范字节/哈希、有序保留事件集检查、retention/pin 行为、取消/物理排空、5 秒 metadata 和 60 秒 result 准入等待。不增加缓存 TTL、worker，不缩短保留期，不推迟校验。

## RLT-S04. 测量与 P1 门槛

测量 P0 前后真实成功读取，并以 >=10 轮交替独立读取比较启用/禁用开销；目标 CPU <=2%、wall <=5%。真实所有者健康后，在独立/启动 dashboard/已有客户端心跳/错开到达/排队退出场景分别采集 >=20 次成功观测，并进行有界 2/8 读取压力测试。单列失败、取消观察者及物理完成。浏览器请求使用原有监控协议。捕获的 >=8 秒成功读取应在 5% 内核对完整区间，否则报告无法归因的缺口。禁止用人为 sleep/注入延迟冒充真实慢请求。未复现原始异常值时须明确局限；发布全部样本、中位数和范围/最大值，不以小样本推断百分位。

之后才评估 P1 行内规范字节复用：>=10 轮交替不插桩测量，CPU 和 wall 中位数改善 >=10%，峰值内存退化 <=10%，混合场景退化不超过 10%。保留所有类型/存储/事件/sequence/count/report/input 绑定。此前探索性 wall 改善 9.2% 不达标。证据不足时暂缓 P1，不降低门槛。

新一轮 10 轮可行性比较的 wall 改善为 11.34%、CPU 为 10.94%，因此在已批准范围内进入正式 P1 评估。解码器的共享私有核心返回已验证规范文本；诊断行迭代器将最多 256 KiB、含 bytes 对象开销的编码字节直接交给统一有序集合校验器。超大事件回退原有规范编码，不新增拒绝。现有公开辅助函数保留返回值及全部检查。不引入对象身份缓存或外部传入预验证标记。生产验收仍须通过原有计时/内存/混合/篡改门槛。

正式首轮 10 轮的 wall 改善为 9.998%，不四舍五入即未过门槛。为处理测量波动，预先声明固定追加 20 轮交替测量，将全部 30 轮合并判断并保留初始样本。不能反复测到绿色或降低 10%。编码字节上限在分配前保守检查，包含非 ASCII 最坏大小；摘要消费方和生产方均在请求下一行前释放上一行。发布/数据/时钟语义保持不变。

固定 30 轮后的决定：wall 改善 10.53%、CPU 改善 9.85%，未同时达到 10% 门槛。P1 暂缓，候选源码保存在生产代码之外。最终代码保留原有审计解码和事件集哈希；保留增强的独立完整性测试。不能据此推断 P0 本身加速校验。最终浏览器回归另同步既有日期筛选移除和高级服务折叠的断言，不改变产品 UI 或弱化审计。

## RLT-S05. 实现与验证

共享诊断基础位于 `src/trade_plan_monitor/diagnostics/`，HTTP 集成位于 `web/`，所有权阶段位于 `backtest/thread_lifecycle.py`，证据阶段位于既有校验边界。使用标准库、聚焦且有类型的 Python 辅助函数和既有格式；不增加依赖或迁移。保留现有 FastAPI 响应序列化快速路径。示例：`with read_span("result.audit", cpu=True):` 包裹既有校验调用，不吞掉其异常。

测试：`.venv/Scripts/python.exe -m pytest tests/unit/test_read_tracing.py tests/integration/test_read_trace_ownership.py`；回归：`.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_evidence_sharing.py tests/integration/test_runtime_status_projection.py tests/integration/test_runtime_status_websocket.py tests/integration/test_backtest_thread_ownership.py tests/unit/test_loop_diagnostics.py tests/unit/test_monitor_loop_report.py`；lint：`.venv/Scripts/python.exe -m ruff check src tests`；浏览器：在 `web/` 执行 `npm run test:e2e -- --grep "backtest"`，另做真实所有者 GET 浏览器流程。运行相关完整性/保留/发布套件及触及边界的变异探针。验证追踪脱敏/上限/禁用行为、输出端失败透明性、独立元数据与监控权威、跨线程上下文、同 key 加入、异常/取消/全部观察者退出和排空。始终保留真实数据，不用合成权威替代真实所有者验收。实施指令原本不包含提交/推送；用户后续审查指令已明确授权仅提交并推送 P0，排除并行的 AI 提取改动。
