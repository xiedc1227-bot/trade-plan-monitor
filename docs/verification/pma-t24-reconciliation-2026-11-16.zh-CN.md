# PMA-T24有界对账 — 2026-11-16

状态：**当前状态报告；T24及最终关卡仍开放**。[英文正式输入](pma-t24-reconciliation-2026-11-16.md)。

## T24-01 — 基线与报告边界

实现基线：`3d7354a485b7f99e5847c2dd475e29af785cbafc`；已核对HEAD：`a9341d3a26620e41720d565bb04a867874c6c43b`。本片仅写本报告双语文件，不运行业务测试、不调用provider、不操作数据库、不启动服务、不push或部署。保留原交接双语文件、`.test-artifacts/`及忽略的证据。

| 已接受切片 | Commit / 准确范围 | 结论与限制 |
| --- | --- | --- |
| T13首片 | `25110ed04bbad6890f9880dc59f6bf266cbc1a1a`；[义务矩阵](pma-t13-obligation-matrix-2026-11-16.zh-CN.md)双语文件（2份文档） | 独立文档审查PASS：34个来源分类条目 / 43个跨度引用；完整03/04分类、阻断与有界后续。未冻结语料，未关闭T13/C05。 |
| N01 | `a3a59ec25a9e30d4b3377940dd763d59065827f9`；清单与prompt补充双语文件（4份文档） | 独立文档审查PASS；仅对账PBS guard及已有Schema5准确选择UI。 |
| N02 | `a9341d3a26620e41720d565bb04a867874c6c43b`；PMA任务与操作指南双语文件（4份文档） | 独立文档审查PASS；保留原文/语料/最终关卡及历史报告。 |

## T24-02 — 复用已接受PBS证据

[PBS最终验收](plan-buy-suspension-2026-11-15.zh-CN.md)在候选`1fe185470ec2f81f01a6c6c9ae289f3eea49598eae4b6cc0388c4e1b68c3ab41`上接受PBS-A01–A12 / C01–C03；协调者匹配了manifest全部29个文件hash。复用计数为126个runtime、78个required/fixture、1841个frontend及1次browser journey，覆盖320/768/1024/1440宽度。计数重叠，不能相加当作新测试或当前完整PMA运行。

来源绑定的已批准澄清实现完整5m收盘严格`<2420`分、持续暂停该计划所有后续BUY、普通03→04继承及准确已审替换版本启用。反弹/跨日/重启不解锁。原始03从`2026-09-30T09:30:00+08:00`开始，首个纳入收盘09:35；真正独立04从`2026-10-09T09:30:00+08:00`开始，首个收盘09:35。六项已批准PBS选择保持固定。

原始自动提取、已批准澄清输出、人工改动与最终审查分别记录。PBS首次browser提取通过实际v13 parser使用离线provider double；替换是`HUMAN_SYNTHETIC`，自动替换仍被阻断。两者均不构成自动真实provider验收。

## T24-03 — N03/N04与T14实际状态

N03**未接受**。拟议的三个production owner未改变。未提交的`tests/integration/test_buy_suspension_reviewed_fact_selection.py`在focused运行中报告收集到17例，并非独立collection-only运行。Ruff检查该test及三个owner通过，未单独保存log。这些仅是发现/静态结果。Python3.14.7下，首个TestClient fixture挂在Windows proactor self-pipe → `socket._fallback_socketpair.accept`；20s traceback保存在`build/pma/t13-n03/red-focus.log`。两次pytest均以工具exit1在业务RED/GREEN证据出现前中断，未产生JUnit。这表明环境前置阻断，未测得兼容性失败，也不是支持PASS。

仓库根目录下的focused诊断命令（输出保存在上述log）：
`.venv/Scripts/python.exe -u -m pytest tests/integration/test_buy_suspension_reviewed_fact_selection.py -k 'public_daily_a' -vv -s -o faulthandler_timeout=20 --tb=short --basetemp=.pytest_cache/pma/t13-n03-red-focus --junitxml=build/pma/t13-n03/red-focus.xml`

恢复RED验证前，独立设计审查要求补齐：实际simulated-trade消费证明ONCE不重开；两个真实已审版本隔离旧facts；Schema10自动minute正例回归；拒绝缺失、错误owner或未完成的official-daily observation head。草稿的current-review拒绝应沿既有sanitized FACT使用status422，修正其409预期，不改production错误契约。目标缺口仍是Schema10普通`OFFICIAL_DAILY_CLOSE` / `REVIEWED_FACT` / `TRADE_DATE`，贯通准确原owner/review/observation/runtime/signal消费及guard clear/unknown/latched。不得扩展manual-minute、其他owner/scope或跨requirement权限。N04 UI验收因依赖暂停。

T14仅做只读设计准备。未完成草稿隔离保存在忽略的`build/pma/t14-offline-prep/draft/`；未交付或接受实现及有效RED结果。T13真值/manifest前置冻结后才可放行T14。

## T24-04 — 保留原文、语料与活动关卡

[矩阵](pma-t13-obligation-matrix-2026-11-16.zh-CN.md)保留原始先后关系、首次入场量能/相对强弱硬合取、不同的首次/第二次100权限、末100不授予第三个可执行入场、旧风险实际owner范围及所有非交易约束。准确的定性未满足人工要求是合法候选；不能据此发明数值算法或声称已满足。

X09仍需准确795码点分区`[0,331)` / `[331,630)` / `[630,795)`、原生嵌套图、仅alert的取消语义且不虚构缺失日期。X12需实际独立完整/已审03前序、真实更早风险上下文及忠实普通03→04组合；身份alias、旧快照及人工替换seed不能提供该权限。

12例准备尚未冻结：4份原始主来源、8份构造NL，共11份NL；03是前序上下文，不是第13例。保留正例X01–X09/X12及预定负例X10/X11。全原文载体、独立真值/grader、无损版本化codec及最终输入/输出可行性仍未完成。历史preflight超限不是正确语义阻断；离线200000不提高production50000/output4096/timeout30s限制。

本会话实际provider调用为0。历史记录0/48是协调状态，不是实际共享原子活动账本。未来发送前必须检查该账本并冻结真值/来源/版本/配置/评分；在同一48次物理尝试上限内保留v12 12×2及变更候选12×2，application和SDK/transport retries均为0。离线测试不能关闭C05。

## T24-05 — F083证据与具体最小范围决策

保留完整原始正例F083失败。147项问题的未审03诊断是历史结果；从未到达04。不声称当前post-PBS问题数或完整成功复跑。[实际successor测试](../../tests/integration/test_unified_actual_successor.py)在隔离存储中prepare、显式review/freeze、reread及组合03→04；不构建run input、不打开dataset、不执行public replay。

独立审计确认的最小提议是**新增版本化、不可变的Schema10 preparation载体/投影，支持prepare → serialize → reread → 真实03→04 composition**。保留来源/guard/owner/review身份及继承权限。已有冻结格式保留字节/hash及对Schema10的拒绝；本提议不增加public dataset/run、策略、replay engine或用户状态操作。它自身不能关闭原文/前序/codec/T14/provider/最终关卡。

实施前需对这一具体范围作决策：[PBS-D05及变更规则](../specifications/monitoring/SPEC-plan-buy-suspension.zh-CN.md)、第6/6.1节及[PBS任务](../../tasks/plan-buy-suspension.zh-CN.md)明确排除/拒绝public Schema10 frozen preparation/export/replay。PMA-D04授权真实命名版本的提取契约，不撤销更窄的拒绝边界。若批准最小preparation/composition增量，须同步双语范围/验收；不因此授权public执行。

## T24-06 — 前置完成后的有序候选切片

以下是可审阅候选，**不是实施放行**。先建立实际已审前序/完整原文载体及准确codec/可行性证据；仅在前置满足后冻结每个准确子片。下列代码路径相对`src/trade_plan_monitor/`；以`docs/`或`tests/`开头的路径相对仓库根目录。

| 顺序 | 最多路径切片 | 边界 |
| --- | --- | --- |
| 1 | `docs/specifications/monitoring/SPEC-plan-buy-suspension.md` + `.zh-CN.md`；`docs/specifications/monitoring/SPEC-plan-monitor-assurance.md` + `.zh-CN.md`（4个仓库路径） | 新冻结格式代码前，记录已批准的具体最小范围及验收增量。 |
| 2 | `backtest/plan_schedule.py`、`backtest/preparation_models.py`、`backtest/preparation_review.py`；新增`tests/unit/test_buy_suspension_frozen_preparation_contract.py`、新增`tests/integration/test_buy_suspension_frozen_preparation.py`（5） | 独立版本化不可变prepare/serialize/reread载体；guard/身份忠实，旧拒绝/golden不变。 |
| 3 | `ai/loop_plan_extraction.py`、`backtest/preparation_worker.py`、`backtest/plan_updates.py`、`backtest/plan_library.py`；`tests/integration/test_unified_actual_successor.py`（5） | 实际已审03→04 preparation/composition，包含完整原文义务；不含public dataset/run。前置证据完成后重新确认准确路径。 |

## T24-07 — 开放交付项与报告校验

PMA-T13/T14/T15/T20/T21/T22/T24、H01–H05及C05/C07/C08整体仍开放。R140是历史完整FAILED运行；针对性修复和PBS通过不是新的完整T22 PASS。T20在`WAL_SIDECARS_UNAVAILABLE`后仍未采集实际安装事实；用户存储访问/修复超出当前范围。T21仍需真实提取整合及人工步骤度量。

报告仅作静态校验：双语section ID、标识符/数值边界/本地链接及`git diff --check`。本报告不声称业务测试或provider/安装验收。原始交接、失败、来源字节、受保护任务文件及保留的本地证据均保持完整。
