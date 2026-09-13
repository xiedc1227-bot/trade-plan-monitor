# R13 独立离线复验交接

日期2026-09-13，Asia/Shanghai。任务 `01a098d6-b8b2-7953-80de-942d4ea78fdd`；协调任务 `01a093fc-f8d3-73d1-b759-ad76c7451697`，host `local`。英文稿为规范输入，本文件为语义等价中文稿。

## 1. 结论与提交

**完整离线验收 NOT PASSED；暂不建议批准 C6。** 已测原计划监控链路、S01–S09／F01–F09和有界N01–N04均具本次离线闭合证据。N05为完整浏览器必选门禁中已确认的P2回测响应式布局失败。最终检查点由协调任务决定。R14为NOT_RUN，未创建后继任务。

- 起始共享工作树：`main/cc328adb4f79b9673705cb67e67520da2dfd667b`，另有12个用户已跟踪修改和4个R00未跟踪文件。
- 新增测试提交：`cab8a3100b7b5512e98cbef58789705434306c0b`。
- 双语报告／矩阵／交接及证据：包含本文件的文档提交，提交并读回后在最终回调提供准确hash。
- 未改业务实现或产品CSS；历史原始／R13失败报告保持不变。

## 2. 文件与实际验证

编写测试：`tests/browser/explicit_server.py`（可选测试专用同根目录／时钟／行情支持）；`web/tests/e2e/r13-active-process-restart.spec.ts`（四种普通UI／OS进程场景）；`web/tests/e2e/backtests.spec.ts`（只新增测量探针，原失败门禁未改）。

报告：`docs/verification/R13-reacceptance.md`及`.zh-CN.md`；`remediation/R13-reacceptance-matrix.md`及`.zh-CN.md`；本双语交接。证据：`remediation/evidence/R13-reacceptance/`，重点命令JSON／日志／XML、`final-sqlite-lineage.json`、`final-journeys/`、`backtest-layout-measurements.json`、`workspace-protection.json`和只读`verify_evidence.py`。大型原始trace保留于本任务自有可视化目录，`trace-archive.json`提供准确旧／新路径及SHA-256映射。

| 门禁 | 实际结果 |
| --- | --- |
| 完整后端，含原R13新增文件，`-m "not live"` | 2634 passed /1 POSIX-ownership skip on Windows /4 live deselected /1 existing warning;2572.52s |
| 完整前端单元 | 644 passed／45文件；5.10s |
| 类型检查／构建／生成类型／限定Ruff | 通过 |
| 初次完整浏览器 | 29 passed／1 failed；2.7m |
| 含四种OS场景和诊断探针的最终完整浏览器 | 34 passed／1 failed；4.5m |
| 未改失败回测布局门禁，五次独立复跑 | 5 failed／0 passed |
| 布局测量探针 | 1次完成，仅诊断执行，不是布局验收通过 |
| harness预期修正后的四种OS专项 | 4 passed；1.8m |
| 最终加强清理错误传播检查 | 4 passed;1.8m; type check passed |
| 最终只读血缘 | 原ALL／修订／四种OS库13事件；均首次IN_APP DELIVERED，规范result／version／revision／cutoff关联正确 |
| 工作树保护 | 本任务起始16文件字节不变；15个原R13 hash不变；dashboard原用户两bar hunk完整 |
| R14／真实AI／真实新鲜行情／实际时段用户可见送达 | NOT_RUN |

重叠数量不累加。后端收集2639，排除4个live，选择2635；最终skip／原因及容量／内存长测结果取已完成运行。live在凭证／客户端fixture前排除，无真实调用或依赖安装。既有runner／TestClient警告不等于浏览器console错误，未引入skip／断言／阈值抑制。

## 3. 闭合与剩余边界

未改写完整原文另附八项明确USER_SUPPLEMENT政策。独立非均匀均量200≠中位数100，证明量200／299拒绝、300／301仅在包含端点价格区间内成立。普通原文→审核→公开激活进入真实后台生产调度器、SQLite及可见BUY／SELL／null风险；ACK保留独立登记库存。SOURCE／人工字段反复普通编辑均可完成当前审核，版本5 ANY／BUY200及8 ALL／BUY100执行各自新意图。旧reviewId／contentHash／revision各自独立409；ANY流程不替代原ALL预期。AI失败、缺项或不支持语义保持旧活动状态或继续阻断。

新增OS证据：普通UI创建／审核／激活、独立登记100／100；显示并ACK BUY10:10；强制终止自有服务PID；核实服务／启动器退出和ECONNREFUSED；以不同PID打开同一临时SQLite，不重seed业务状态。明确EACH_QUALIFYING_BAR时，重放不重复10:10，SELL10:15／风险10:20及同规则BUY10:30仍出现。另三例保留替换版本3、公开停用及次日到期；旧提醒非当前，停用／到期不产生后续事件。到期例推进次日调度至10:15。持久库存字段／revision不变，仅查询cutoff推进。

这是真实OS强制退出恢复，AI／市场边界为fake，不证明生产优雅关闭、掉电、外部exactly-once或真实供应商恢复。首次失败日志保留15s测试关闭／启动器超时，以及后续预期错误（已禁用ACK、查询cutoff、正确不存在的404 runtime）。已测试精确自有进程终止及修正断言，没有产品修复掩盖失败。Windows进程归属检查首次因沙箱访问被拒；具体已授权只读／清理升级成功，确认四个早期已记录PID均已退出。

**N05／P2仍未闭合：** 四个回测页面在320px／200%文字、等待字体及两次渲染后，文档宽稳定338／476／617／411。原完整门禁失败，5／5专项复跑失败。旧诊断先显示的元素属于有意内部滚动导航，完整检查还发现未约束hero／表单／结果内容，不得无依据归因于受保护AppShell hunk。最小后续为相关回测视图／组件grid／flex／控件宽度整改，再跑未改响应式／axe／交互及完整浏览器；不得裁切、缩小文字／宽度、重试掩盖或删除断言。

## 4. 保护与协调

未reset／stash／切分支、暂存用户文件、调用外部供应商／通知渠道、下单、操作真实持仓／生产库、安装依赖、push或发布。完整原文JSON及六份历史R13报告／矩阵／交接与起点一致。12用户修改和4R00未跟踪文件不变，包括dashboard09:35／10:35两bar及第二openPoints1231.25。

全部测试／写入／本地提交／读回后，仅向协调任务发送一次获授权最终回调，提供实际提交／结果和本次NOT PASSED建议。随后不再写入、不建后继、不等待结束。后续真实验证须另行明确供应商／模型／请求数／费用／额度／symbol／endpoints／时间／临时库／复核计划／渠道授权，不索取或猜测秘密。

自编源码／文档／JSON采用限定范围空白检查；原始运行日志保留录制时空白。
