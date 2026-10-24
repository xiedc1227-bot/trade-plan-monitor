# 验证：market-linkage-p1

## MLV1-01 — 范围与授权

用户在 2026-10-24 批准 MLP1-D01–MLP1-D06 并指示分阶段实施。基线 `dbeff32`。本报告只记录已经执行的检查，不记录设想结果。[规格](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md) · [任务](../../tasks/market-linkage-p1.zh-CN.md) · [规范英文版](2026-10-24-market-linkage-p1.md)。

## MLV1-02 — 基线与边界清单

MLP1-T01：已核对实际领域／草稿／编解码／哈希／审核／运行／状态／API／回放边界，记录在双语[契约清单](../specifications/monitoring/CONTRACT-market-linkage-p1.zh-CN.md)。未访问用户数据库或外部数据商。

在 `trade-plan-monitor/` 已执行 V01：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

结果：**91 passed in 1.20s**。Python 启动器出现既有安装位置诊断，但测试正常完成，退出码为 0。此基线不代表 P1 功能验收。其余任务结果仅在实际执行后追加。

## MLV1-03 — 严格 Schema 7 契约（MLP1-T02）

RED：初始契约测试因缺少 Schema 7 模型／分发产生 9 失败／1 通过；新增不完整草稿及共用构造器检查在实现前另有两项预期失败。GREEN：52 项例外／联动／统一领域测试在 1.58s 通过；176 项旧计划／日线／有界编解码测试在 0.45s 通过。由于明确支持 7，未知版本样本改为 8，保留拒绝断言。针对性 Ruff 和空白检查通过。

首次扩大范围误用了不存在的 `test_daily_plan_domain.py`，没有运行测试，随后改为实际文件。默认临时目录初始化失败；明确使用工作区临时目录解决该问题。后续堆栈将剩余等待定位到 Windows `asyncio` 创建 socketpair，允许本机通信后离线测试通过。没有修改应用逻辑绕过环境限制。

已通过命令（临时路径按运行区分）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_unified_plan_domain.py -q --basetemp .test-tmp/p1-t02-accepted
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_bounded_validation_codec.py -q --basetemp .test-tmp/p1-t02-legacy-fixed
```

本项仅验收严格领域／草稿／编解码／哈希切片。来源审核、启用、运行、批准及执行集成仍为未勾选任务。
