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
