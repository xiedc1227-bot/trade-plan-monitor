# 简化回测服务验证 — 2026-10-18

英文权威版：[2026-10-18-compact-backtest-service.md](2026-10-18-compact-backtest-service.md)。任务：[SC-01–SC-03](../../tasks/compact-backtest-service.zh-CN.md)。

## SC-V01 — 已交付行为

正常回测路由只显示一行精简服务状态及 `服务管理` 按钮。按钮支持键盘，提供展开状态及关联面板信息。刷新、待恢复任务查询、停止服务、更新时间、说明和返回链接收进面板。异常、未知控制、停止中／已停止／未启用及检测到中断任务时展开。用户可收起，不改变服务或任务状态。

组件仍只负责展示；`useBacktestService` 负责状态／历史读取及明确控制。不新增 API 或执行机制。仅在 `canRead=true` 且没有当前已授权任务时，以 `limit=1` 有界查询 `QUEUED`、`RUNNING`、`CANCEL_REQUESTED`。检查成功后，在 `epoch`、`revision`、`generation`、状态或 `authorizedJobIds` 变化前复用结果。可读前不扫描历史。已授权运行中的任务不会被提示为中断任务。

后台 `SERVICE_UNAVAILABLE` / 503 留到既有状态轮询，不将普通元数据竞争变成展开告警。其他查询错误和明确手动查询失败仍显示。迟到历史响应须匹配当前服务身份和组件存活期；控制操作会中止未结束查询。查看、展开或发现历史任务都不会恢复它。待恢复任务仍须勾选并明确点击恢复。保留控制原请求体／键重试、实际排空、原文未知结果确认和任务取消防护。

## SC-V02 — 自动检查

新增回归先在旧常驻展开界面和缺少自动检测时失败。另有回归复现后台忙碌误展开，以及每轮状态轮询重复查询历史，修正后通过。

| 检查 | 结果 |
| --- | --- |
| 服务传输／组合函数／组件套件 | 32 项通过 |
| 前端全量 | 71 个文件、1088 项通过 |
| 类型检查／生产构建 | 通过 |
| 定向真实 Chrome 流程 | 3 条通过：精简展开／键盘／桌面／手机／axe；中断任务和服务异常无自动控制；管理面板收起时任务进度／读取刷新／取消确认／同请求体与键重试 |
| 既有请求／DOM／轮询／图表边界 | 一次记录中通过，后续重复触发 SC-V04 所述导航中断审计 |
| 生产路径集成 | `test_mounted_upload_retry_review_worker_and_causal_result_use_only_market_facts`：1 项通过，保留既有 Starlette/httpx 弃用提示 |
| 既有未知提取取消浏览器案例 | 通过；继续检查导航、明确确认结束及任务占用保留 |

完整前端套件仍覆盖任务进度、取消确认、读取失败、未知取消和同一请求／键重试，未删除相关断言。浏览器契约夹具补齐原本要求的 `Cache-Control: no-store`、当前计划库读取，以及有效且按规范排序的未完成任务分页。保留既有 API／请求／布局断言及时间门槛；路由导航前等待此前网络活动完成。

本地日志和截图位于 `data/verification/2026-10-18-compact-service/`：`unit-final.log`、`build-final.log`、`service-browser-focused.log`、`service-browser-final.log`、`production-integration.log`、`production-browser-final.log`、`service-focused-results/`。供应商凭证、本地数据库和这些生成文件仍被忽略。

## SC-V03 — 实际四份计划结果

实际服务 `http://127.0.0.1:8765` 已加载新生产资源。读取原四份计划运行 `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2`，没有重新提取、回放或改写报告。原收益汇总、计划诊断及规则对照仍可查看。

在 1440、390、320 像素宽度下，正常服务栏高度均为 60.75 像素，仅显示状态和展开入口。Enter 展开管理操作，Space 收起，页面没有横向溢出。没有服务控制或其他写请求，没有页面运行错误。最初实际读取复现后台元数据竞争，由此补充 SC-V02 的回归，没有暗中修复服务。最终检查使用已纠正构建。

依据为同一本地目录下 `actual-browser.json`、`actual-browser-final.log`、`actual-page.txt`、`actual-compact-{width}.png`、`actual-expanded-{width}.png`、`actual-status-{width}.png`。本项验证保留实际报告上的展示，不是新的 AI、行情供应商或收益认证。

## SC-V04 — 保留的验证限制

扩大浏览器检查没有全部通过。既有 320/768/1024/1440 及 200% 布局流程在严格请求失败审计中发现导航中止的读取。使用相同纠正后契约夹具，在未修改的 `e7ead0c` 隔离归档基线上，同一流程也在该审计失败。键盘流程曾间歇报告结果／明细读取中断，在基线对照中通过。没有禁用或重新分类任何请求失败断言。

旧完整上传／重试／修改／审核／运行 Chrome 流程也在未改变的 10000 ms 候选就绪检查点失败：页面保留上次提取中状态和读取错误，临时后端记录已达到 `CANDIDATE`。明确刷新进度仍未在相同门槛内解决。隔离 `e7ead0c` 基线使用旧服务组件／组合函数时，同样复现；对应生产路径集成通过。此项保留为既有浏览器／进度读取验证工作，不据此声称整个端到端套件通过，也不声称此次简化修复了该问题。

保留首次失败于 `browser.log`、`browser-final.log`、`browser-canonical.log`、`existing-browser.log`、`production-browser.log`、`production-browser-rerun.log`。基线输出为 `baseline/baseline-browser.log`、`baseline/baseline-production.log`。此次界面修改无需容量测试或新的实际原文提取／回放。[功能验收记录](2026-10-18-backtest-functional-acceptance.zh-CN.md)保持其基线和已声明限制，本增量不扩大认证。
