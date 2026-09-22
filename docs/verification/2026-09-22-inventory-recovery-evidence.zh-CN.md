# 持仓恢复写入证据 — 2026-09-22

> 英文规范版的中文评审副本。续接 `e08b219`；仅为 RR009 写入前置步骤，不是任意时段重启验收。

## 范围与保留边界

未来人工确认保存完整原始前后行及新建的期初持仓。期初持仓减仓保存完整原始快照、已接受的有效交易日期及每次操作的交易单位。批次买入/减仓及期初持仓减仓追加独立 `POSITION_INVENTORY_CHANGED` 审计，将来源审计和持仓版本关联到完整确认快照。`MISSING`/`STALE` 记录版本推进，不修改确认。`SYNCED` 保持数量更新/上限截取语义、确认时间和成员引用。

`position_inventory_audit.py` 显式列出存储字段，对“版本加确认”对象计算规范 SHA-256 哈希。持仓审计 ID 使用基于来源审计 ID 的 UUID5；时间戳复制自该来源。不可变来源值避免重新加载已过期的 ORM 状态。不增加应用 ID 或时钟调用。既有确认/期初持仓哈希及严格版本 1 批次审计内容不变。新期初持仓快照保留原始时间字符串；旧期初持仓哈希保留 DTO 序列化。不对已接受的成员清单增加写入大小限制。

证据与持仓、持仓版本、监控事件及应用收据共享调用方事务。审计 ID 冲突显式失败，绝不覆盖旧行。不包含迁移、历史猜补、真实行情源、真实通知、回放或生产默认切换。这些哈希证明存储一致性，不防范可写数据库者伪造。存储快照不证明历史完整性，也不授予回放/发送权限。

## 测试先行与独立审查

实现使用 `gpt-6-astra` / `high`；独立设计及最终审查使用 `gpt-6-astra` / `xhigh`。这些设置不证明父任务的模型/推理强度。按用户此前选择，继续跳过额外跨模型审查。

初始写入测试因缺少确认/期初持仓证据及持仓收据而失败 14 项，实现后通过。独立服务测试在确认切片完成、变更收据尚未实现时运行，失败 10 项、通过 6 项。覆盖八种场景的引擎/服务重建，以及证据和已完成幂等收据写入后的故障注入。另加三项 UUID 冲突测试，证明既有行保留及完整命令回滚。

设计审查明确了原始 UTC `+00:00` 与 DTO `Z` 的区别、原始成员 JSON 保真、确认缺失/过期时版本推进及不同交易单位（`100 → 93 → 90`，使用 `7` 后 `3`）。最终审查发现兼容性回归：重新解析存储时间戳会丢失时区/fold。三项测试复现了原本可接受的上海 `fold=1` 时钟被拒绝。修正后直接传递原日期对象，同时保留原始审计字符串；三项均通过。独立最终审查未发现本写入契约内的剩余可操作问题。

两项旧测试假定每条审计都是批次审计。现将批次断言/复制限定为 `POSITION_LOT`；写入测试另外检查审计总数及持仓/来源一一对应。第三项通知事务测试原先预期买入后只有一条审计；现要求两种审计动作，并在回滚后逐列比较全部已存审计。不跳过、删除或减弱测试。一轮运行恰与多文件时钟修正重叠，观察到临时签名不匹配；稳定代码树重跑通过。

## 已执行验证

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_recovery_audit.py -q` | 时钟修正后 18 passed |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_lot_recovery_audit.py tests/integration/test_position_lot_history.py tests/integration/test_position_inventory.py tests/integration/test_position_production_composition.py -q --tb=short` | 168 passed，1 项既有警告；20.23 秒 |
| 独立最终写入/事务/批次审计选择集 | 48 passed，1 项既有警告；7.27 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py -q --tb=short` | 38 passed；5.84 秒 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照和前端类型仍为最新 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3653 passed，4 项既有失败，1 项既有跳过，4 项 live 未选中，1 项既有警告；461.17 秒 |

最终稳定代码树回归包含全部 37 项新增测试，没有新增失败。四项基线失败仍是：规范指数头更新时间（10:36 与 10:38）、待处理收盘指数错误的参考行情健康状态（LIVE 与 BLOCKED）、行情源 TIMEOUT 与 TRANSIENT，以及 R14 模拟请求缺少必填 temperature、在到达模拟传输前被拒绝。本次不修复或豁免这些问题。未改动的重型回测文件及真实行情源测试不在本轮范围内；这不是全套通过或最终验收通过。既有跳过是 Windows/POSIX 所有权边界；警告为 Starlette/httpx 弃用提示。

成对标题及技术字面量一致性检查通过，暂存内容空白检查通过。对全部 13 个变更文件执行限定范围的高置信敏感凭证模式扫描，未发现匹配；这不是完整凭证审计。修改保存为一个本地增量；不包含推送、合并或部署。

## 剩余工作

RR009/C2 仍未完成。下一步为这三种证据形状实现严格有界解码，对旧版/缺失/畸形数据保留未知；随后在明确的截止点/迟报登记策略下，建立来源关联、唯一链条及完整历史持仓。确认根记录没有监控发布，不能照搬单批次根节点规则。风险来源有效时间、顺序执行、最终逐渠道准入、生命周期/状态/UI 集成及实际进程重启验收仍是独立要求。本增量不代表第 3 阶段完成，也不授权进入生产恢复。远端同步和部署仍是独立操作。

一项只读后续调查界定了这些解码器边界，但未批准新的读取契约。读取预算须明确覆盖外层 UTF-8 内容及嵌套成员清单，不能限制写入准入。保留原始字符串用于哈希/状态比较，不假定全部存储数量为 100 的倍数、全部 ID 为 UUID，或重新确认必定改变确认 ID。单条验证不能证明来源存在、交易所日期、成员完整性或历史适用性；跨记录证明及截止点策略仍属独立工作。
