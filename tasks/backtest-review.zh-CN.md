# 回测审阅实施任务

## BT-R01. 契约与索引

- [x] 编码前冻结双语 [BR01–BR06](../docs/specifications/backtesting/SPEC-backtest-review.zh-CN.md) 及组件边界。
- [x] 增加派生元数据、同事务暂存、显式有界旧运行维护。验证发布隔离、重新打开、删除及哈希行为。
- [x] 增加严格上下文 API、签名关系分页并重新生成客户端。验证选择器、缺失身份及过期行为。

依赖：现有已完成结果存储。使用 `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py` 及契约生成检查验证。保留无关费用改动。现有 `tasks/plan.md` 和 `tasks/todo.md` 属于其他工作并保留；本功能使用此独立任务清单。

## BT-R02. 可读结果与导航

- [x] 精简成交、按资金模式展示概览、独立原因／来源及精确诊断／事件链接。
- [x] URL 驱动证据状态、请求取消、关联分页、焦点和已访问游标上一页导航。

依赖：BT-R01。运行聚焦 Vitest、类型检查及构建。独立组件／组合式函数遵循 BR04。不推导逐笔盈亏。

## BT-R03. 验收

- [x] 使用固定 Chrome 联合验证已发布后端与 UI、键盘／历史导航、缺失证据及移动端／桌面布局。
- [x] 完成相关回归、审阅最终差异，双语记录验证结果及剩余边界。

依赖：BT-R02。验收：BR-A01–BR-A04。BR06 中图表／筛选扩展不在本次交付范围。

验证记录：[BR-V01–BR-V04](../docs/verification/2026-10-20-backtest-review.zh-CN.md).
