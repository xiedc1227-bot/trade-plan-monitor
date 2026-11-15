# 计划持续禁买验证 — 2026-11-15

## PBS-V01 — 候选与结论

**PBS 工程验收 PASS：PBS-A01–PBS-A12、PBS-C01–PBS-C03。** A03、A11 最终独立复核均通过。本报告不批准部署或实际监控就绪。

源码候选：`1fe185470ec2f81f01a6c6c9ae289f3eea49598eae4b6cc0388c4e1b68c3ab41`；[29 文件清单](../../build/pbs/t12/final/manifest.json)，基于 `adc382184de9fb11583d858beae27382183570d9`。候选计算为 `json.dumps(manifest, sort_keys=True).encode()` 的 SHA256，使用默认分隔符且无换行。五文件 A11/UI 候选为 `4c4860549ff50ca3d8e6d0a289a5b7796dce255069e66ecc4e29e67483d9c28d`；[A11 清单](../../build/pbs/t12/a11/manifest.json)。报告散列另记，避免循环散列。[最终交接](../../build/pbs/t12/final/handoff.json)与[带散列证据索引](../../build/pbs/t12/final/evidence-index.json)绑定保留材料。

## PBS-V02 — 验收矩阵

| ID | 结论与证据 |
| --- | --- |
| PBS-A01 | PASS：T04/T08 覆盖及来源绑定拒绝区分原始来源与显式澄清；03/04 原文字节不变。 |
| PBS-A02 | PASS：转换/数据适配用例覆盖 2419/2420/2421、仅最低价跌破、完整5分钟K线、区间及口径；实际 A03 收盘 2430/最低 2419 和收盘 2420 均不锁定。 |
| PBS-A03 | PASS：真实 SDK → 已提交 SQL → runtime，对比工程 guard 加既有确认/执行逻辑。09:35/09:40/09:45/09:50 对应收盘 2430/2420/2419/2435，独立预期 BUY 数量为 100/100/0/0。未来收盘 3000 不改写历史结果；最后一步后仍核对全部旧不可变 EVALUATION。原生准备先于同根K线 BUY，失效 READY 且不成交。 |
| PBS-A04 | PASS：状态/恢复/激活用例覆盖反弹、跨日、重启、普通复制、恢复、修正及隔离；最终浏览器替换后保留原触发记录。 |
| PBS-A05 | PASS：T07/T08 覆盖 pending/ready/首笔/次笔 BUY、陈旧/直接请求及提交竞争；最终 runtime 将 READY 失效为数量 0、无 SIMULATION，保留已完成持仓/消耗。 |
| PBS-A06 | PASS：保留风险/通知用例及最终浏览器对比；BUY 持续锁定期间，页面触发 SELL 模拟成交 100 股。 |
| PBS-A07 | PASS：恢复覆盖缺日历/历史/口径、续查/修正/重启。真实调度推进本轮 guard，向另一实际活跃实时请求或真实下一截止点让路，异常/取消时清理预留；串行所有权/物理 join/提交围栏保持。 |
| PBS-A08 | PASS：精确回执/激活/竞争用例及真实页面请求。保存/复核保留旧 active owner；精确激活切换版本。策略开始前不继承 guard 证明；自身 09:45→09:50 覆盖绑定新 owner/source/content/review/revision，产生 runtime BUY READY 100，旧触发保留。不额外等待首根 bar。 |
| PBS-A09 | PASS：T09 只读拦截及最终 readiness API 回归；GET 不采数、不转换 guard。UNVERIFIED、健康与 BUY 资格保持区分。 |
| PBS-A10 | PASS：T10 双 profile 投影/往返及不变历史 golden；不支持的 frozen 操作显式拒绝。生成 profile 检查通过。 |
| PBS-A11 | PASS：最终真实浏览器旅程、四状态 × 四宽度、精确请求绑定、新 owner 证明及正常清理；独立 A11-R01–A11-R04 已关闭。 |
| PBS-A12 | PASS：下列最终定向回归、UI/类型/构建/生成/质量检查，以及冻结源码/证据的独立复核。 |

| 检查点 | 结论及保留的独立证据 |
| --- | --- |
| PBS-C01 | PASS：T01–T04；[T02](../../build/pbs/t12/c01-t02/)、[T03](../../build/pbs/t12/c01-t03/)、[T04](../../build/pbs/t12/c01-t04/independent-evidence.json)。 |
| PBS-C02 | PASS：T05–T08；[最终复核](../../build/pbs/t12/c02-t08/final-review.json)。后续调度修正另由 [A03 复核](../../build/pbs/t12/review-a03/scheduler-review-3.json)验收。 |
| PBS-C03 | PASS：T09–T12；[T09](../../build/pbs/t12/c03-t09/final-review.json)、[T10](../../build/pbs/t12/c03-t10/final-review.json)、[T11](../../build/pbs/t11/final/handoff.json)、[最终 A11 复核](../../build/pbs/t12/review-a11/final.md)及[验证明细](../../build/pbs/t12/review-a11/final06-verification.json)。T09 指纹失败已由 T10 关闭，未修改旧 golden。 |

## PBS-V03 — 命令与最终结果

| 检查 | `build/pbs/t12/` 下的材料 | 结果 |
| --- | --- | --- |
| runtime/recovery/coordinator/admission/lifecycle | `a03/scheduler-final-v2.xml` | 126 PASS；0 failure/error/skip |
| 必需 daily-plan/readiness 加隔离 fixture | `required-final.xml` | 78 PASS = 70 必需 + 8 fixture；0 failure/error/skip |
| 最终 fixture 刷新 | `a11/fixture-final-02.xml` | 8 PASS；与此前 8 项重叠 |
| 最终 UI 的前端 | `a11/frontend-final.xml` | 1841 PASS / 103 文件；0 failure/error/skip |
| 最终真实浏览器 | `a11/browser-final-06.log` | 1 PASS / 40.2 秒 |
| 类型 / 生成 / Ruff / 空白 | `a11/type-final-05.log`、`generated-check.log`、`ruff-final.log`、`final/diff-check.log` | PASS |
| 隔离 Vite 构建 | `a11/build.json`、`a11/build.log` | PASS / 76 文件 |

精确命令与工作目录见 [commands.json](../../build/pbs/t12/final/commands.json)。关键命令从项目根目录执行，最后一条 Node 命令从 `web/` 执行：

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_buy_suspension_runtime.py tests/integration/test_plan_buy_suspension_recovery.py tests/unit/test_recovery_coordinator.py tests/unit/test_request_recovery_admission.py tests/integration/test_runtime_lifecycle.py --basetemp=.pytest_cache/pbs/t12/a03-14 --junitxml=build/pbs/t12/a03/scheduler-final-v2.xml -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_plan_chain.py tests/integration/test_plan_readiness_api.py tests/browser/test_plan_buy_suspension_case.py -m "not live" --basetemp=.pytest_cache/pbs/t12/required-final --junitxml=build/pbs/t12/required-final.xml -q --tb=short
node node_modules/@playwright/test/cli.js test tests/e2e/plan-readiness.spec.ts --grep "PBS real" --output ../build/pbs/t12/a11/browser-final-06 --reporter=line
```

70 项必需用例运行于 scheduler v2 和最终 UI 字节；之后仅修改浏览器观测/清理，再刷新 8 项 fixture 及真实浏览器。重叠或历史运行不累计。构建使用既有 Vite 配置，禁用环境文件，仅排除打包复制 hook，输出 `build/pbs/t12/a11/build-1794751729181/dist`；保留 Vue/contract 插件。两个共享资源目录各 68 文件的前/后/最终散列一致。

## PBS-V04 — 浏览器证明

[最终 trace、24 张视口截图、公开旅程与生命周期](../../build/pbs/t12/a11/browser-final-06/)覆盖真实离线 v13 提取 → 澄清 → 保存 → 复核 → 激活 → 原生跌破 → 反弹 → SELL → 替换。初次提取使用一个 provider double 及真实配置的解析/生命周期。替换明确为 `HUMAN_SYNTHETIC`：既有测试端点仅提供未复核 candidate/source/map。后续澄清、意图、保存、复核、激活均走真实页面控件/公开 API，不注入权力。这不构成自动替换提取正例。

澄清、锁定 guard、替换表单及复核/激活动作分别通过 320/768/1024/1440 × 900 检查：布局稳定、无溢出、44px 控件、键盘/标签/禁用行为及 axe 零违规。最终视口截图保留页头且焦点无遮挡。真实请求匹配已保存 source/content/coverage/review 身份及切换前后 active 指针；新 guard 拥有自身覆盖和绑定。时钟推进时离开 SPA，再打开精确持久化版本；不主张加速推进期间 UI 连续新鲜。

独立 trace 检查无失败 HTTP 状态、外部主机、浏览器错误或页面错误。停止前 Uvicorn 实际 WebSocket 集合从 1→0。最终顺序为 `PAGE_CLOSING → SPA_TRANSPORTS_CLOSED → PAGE_CLOSED → BACKEND_STOPPING → BACKEND_STOPPED`：退出 0、无信号、lifespan 关闭、read owner 0、runtime STOPPED，且无 reset/error 日志。这证明 fixture 有序关闭，不证明任意传输中断韧性或全机进程清点。

## PBS-V05 — 修正与偏差

原生调度自让路导致必要 guard 采集无法进行；专用 pending 检查区分自身任务，并保留其他实时工作及下一截止点优先级。此前未接入的预留在正常/异常/取消路径安装/清理。保留红灯证据，最终 126 项及独立复核通过。RR-PBS01 已同步至 runtime-recovery 双语文档。一条局部 CSS 修正原生 checkbox 标签 44px；[UI 复核](../../build/pbs/t12/review-ui/code-review.json)通过。失败浏览器尝试保留为诊断：替换 normalization 仍被阻止，突断关闭清理失败通过正常离开 SPA 及读取实际 Uvicorn 连接修正，未过滤日志或弱化退出检查。保留既有 Starlette 弃用警告。

[T10 构建偏差](../../build/pbs/t10/final/build-deviation.json)：默认构建经打包复制更新被忽略的共享资源目录。不存在可靠先前备份，不主张恢复。T11/T12 隔离构建没有进一步共享变更，也不撤销该副作用。

## PBS-V06 — 受保护数据与边界

[保护检查](../../build/pbs/t12/final/protected-check.json)核对七项输入未变，含 03/04 原文、历史身份 golden 及提示词。未改写受保护 PMA 历史/任务、frozen 格式或原文。数据库仅为新建 `.pytest_cache/pbs/t12/` 目录。用户数据库操作、真实行情/provider/通知调用及 push 为 0；真实提取预算为 0/48。

原始 03/04 义务、F083、PMA-C05/C07/C08、实际安装/监控就绪及用户数据库上线仍未关闭。Schema10 公开 frozen 导出/准备/回放仍不支持并显式拒绝。PBS 工程验收不授予自动认底、真实交易或更广来源验收。协调方维护任务/检查点状态并提交；本报告作者不 commit 或 push。
