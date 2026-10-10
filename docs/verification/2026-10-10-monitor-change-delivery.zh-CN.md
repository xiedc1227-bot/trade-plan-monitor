# 监控修改交付：2026-10-10

英文规范版本：[2026-10-10-monitor-change-delivery.md](2026-10-10-monitor-change-delivery.md)。

## MCD01 授权与边界

用户于 2026-10-10 要求整理已完成的修改并推送至 GitHub。本次交付包含此前总览重试调查、用户要求的页面展示调整及已授权的收市指数修复。目标为 `xiedc1227-bot/trade-plan-monitor` 的 `origin/main`；初始本地与远端提交一致。采用普通提交和快进推送。不重启服务，不增加供应商权限、依赖或采集频率修改。

## MCD02 提交分组

| ID | 内容 |
|---|---|
| C01 | 修正已到期调度唤醒、停止实例健康时间及显式限频消息分类，包含回归测试和中英文调查记录。 |
| C02 | 移除编号英文页标题及总览管理按钮；将连接状态栏放到回测导航上方，保留标题、说明及可访问焦点。 |
| C03 | 保留有效指数数据，单独存储最近采集，增加 `0025_index_close_display` 迁移、幂等启动修复及有界末尾桶恢复预算持久化。 |
| C04 | 增加 `GET /api/v1/market-indexes/overview`、一致只读时段／数据组装、严格有界 DTO、兼容历史、生成契约和 API 验收。 |
| C05 | 总览界面连接原子信封，默认上证指数，分别呈现收市／数据／采集状态，保留缓存并验证实际图表末点及无障碍行为。 |
| C06 | 同步中英文规范、已完成实施任务、发布证据、既有回归局限及本交付记录。 |

共享文件按逻辑内容暂存，不重写工作区内容。提交消息使用 Conventional Commit 前缀、中文标题、一个空行及中文修改条目。

## MCD03 推送前验证

- 后端专项重新回归：183 passed，包含调度、限频处理、组合、持久化、恢复、时段、总览和 OpenAPI 检查。
- 前端完整单元测试重新执行：63 个文件共 942 passed，关闭文件并行。
- 浏览器重新验收：`dashboard.spec.ts`、`index-close-display.spec.ts`、`interface-design.spec.ts` 共 9 passed。
- 类型检查、canonical v2／compatibility v1 生成契约检查、专项 Python lint 及隔离生产构建通过。
- 变异审查仅在隔离测试进程内反转 LIVE 保留条件：A01/A02 两项持久化测试均拒绝错误逻辑。产品源文件及运行服务未改动。
- 候选文件检查覆盖凭据／构建产物、中英文结构和稳定 ID。未修改代码块内既有翻译注释予以保留。数据库文件、备份、凭据、暂存资源及临时审查辅助文件不进入 Git。

## MCD04 既有回归局限

此前完整 integration 运行及最终代码复验见[收市指数修复验收](2026-10-09-index-close-display-repair.zh-CN.md)。仍有两项既有回测生命周期断言要求自动启动，但未改动的实现使用 `LazyBacktestLifecycle`。保留失败记录，不弱化断言或修改无关生命周期。本次交付不宣称后端完整测试全绿。

## MCD05 保留的独立工作

以下五个独立研究文件保持本地未提交状态：

- `docs/verification/2026-10-03-shengxin-backtest.md`
- `docs/verification/2026-10-03-shengxin-backtest.zh-CN.md`
- `scripts/replay_shengxin_research.py`
- `tasks/shengxin-backtest-plan.md`
- `tasks/shengxin-backtest-plan.zh-CN.md`

提交整理期间保留既有源码、配置、生产数据及研究内容。推送后将远端交付提交与本地最终提交核对，不使用强制推送。
