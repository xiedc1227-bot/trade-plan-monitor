# 计划监控就绪安装审计

英文规范版：[plan-readiness-installation.md](plan-readiness-installation.md)。

## T20-A01 — 状态与范围

2026-11-14，实现基线 `69a977b`。**离线工程已验证；实际只读尝试返回 NOT_READY / WAL_SIDECARS_UNAVAILABLE。** root审查冻结四文件并放行已获用户授权的审计后，于02:31:06–02:31:07+08:00执行一次命令。文件头前置检查在打开SQLite连接前停止。实际schema、迁移、计划、审核、启用、评估及渠道均尚未取证；不能称实际安装全面审计或正向就绪通过。未访问既有服务。T20完成标记及共享任务/报告更新仍由root负责。

读取前置成立时，DB-only脚本可记录持久schema/迁移、计划范围、审核/启用、覆盖元数据、原生/legacy评估时间、存活时间及发送尝试元数据。复用已有计划codec、`CoverageInstallation`哈希完整性校验、准确覆盖trigger定义及已有计划/渠道/尝试枚举。模型的 `_Signed` 基类使用 `daily_hash`，不是数字签名。不重建就绪、来源审核权威、当前评估或发送资格。每份报告保持 `PERSISTED_ONLY`、`authorityGranted=false`、`runtimeOwnership=UNKNOWN`、`notificationConfiguration=UNKNOWN`、`installationStatus=NOT_READY`。已记录送达不证明当前渠道或准确义务已经验证。

## T20-A02 — 读取与资源边界

- 仅已有文件：`mode=ro`、`query_only=ON`、单个显式读取事务。不调用应用engine、lifespan、WAL配置、迁移、备份、checkpoint、供应商、求值器或HTTP客户端。不对活动WAL库使用 `immutable=1`。
- WAL头文件要求已有WAL/SHM伴随文件。缺少时在打开SQLite前返回 `WAL_SIDECARS_UNAVAILABLE`；此时schema、迁移及计划事实**尚未取证**。这是未完成的安装观察，不能称全面审计通过。不创建、修复、删除或checkpoint伴随文件。
- 固定表/字段白名单。每节最多100行、最多10个活动引用；超出明确列入 `limitedSections`。计划/审核/覆盖样本优先包含这些准确活动版本ID，其余样本确定排序。当前计划/审核缺项列入 `activeReferenceGaps`。样本不是完整历史或最新结果声明。
- 复用计划codec的256KiB准入上限。SQLite值及序列化输出限制为1MiB，查询最多1,000,000条虚拟机操作及5秒，连接等待最多1秒。可用性/预算超限不产生READY。SQLite值超限使审计不可用，不静默截断计划。
- 不输出原始来源、计划/证据载荷、消息、配置、端点、异常消息或数据库路径。规范化UUID/时间；使用已有闭合枚举及随包迁移名称。不重验原始审核/证明链或交付绑定；适用元数据标为 `NOT_REVALIDATED`。表存在或安装标记哈希完整性有效不是当前来源/审核/运行证明。
- 缺失/旧/不兼容schema直接报告，不创建表。读取失败或中断可能保留部分元数据，同时标记 `UNAVAILABLE_OR_BUDGET_EXCEEDED`，不声称证据完整。不覆盖已有 `audit.json`。

## T20-A03 — 离线验证

在 `D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor` 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_plan_readiness_audit.py -q --basetemp=.pytest_cache/pma-t20-audit-frozen-tmp
.\.venv\Scripts\ruff.exe check scripts/audit_plan_readiness.py tests/integration/test_plan_readiness_audit.py
```

冻结选择：**16项唯一测试通过，2.57秒**，无失败/跳过/xfail/xpass；Ruff通过。测试使用真实临时SQLite及已有临时迁移/种子工具，覆盖缺失/旧/不兼容/损坏文件、哈希完整性标记篡改、真实已保存计划范围与审核、超限计划、已提交WAL事实可见且主库/WAL字节不变、数据库写入被拒、网络/初始化/求值被禁止、WAL缺伴随文件、持久心跳/legacy评估不补足当前owner、历史渠道结果、100行上限、107个保存版本中仍保留活动版本/审核、CLI明确只读及不覆盖输出。这不是全项目回归或实际安装证据。

原始失败保留：RED为1项缺模块收集错误；`green1`为6通过、1项夹具外键失败（缺少父alert，随后补齐）。`green2`通过10项；`final`通过14项；`owner-final`通过16项。这些运行存在重叠，**不累加**到冻结的16项。较早Ruff行长/导入问题已修正，未增加抑制。原三份 `.tmp` 日志经准确解析源/目标路径检查后，原样迁入已忽略的证据目录。

## T20-A04 — 冻结证据

日志位于本地已忽略目录 `.pytest_cache/pma-t20-audit/`；不提交临时数据库/日志。

| 资产 | SHA-256 |
| --- | --- |
| `scripts/audit_plan_readiness.py` | `8d9f60464198a6b478530939833c5136b7fc71dff389d6028fd585b0f1ebc1c1` |
| `tests/integration/test_plan_readiness_audit.py` | `73a8d031a739f044e7b4dc9addb63942d4b07d42e423e11fa0600a057648445d` |
| `t20-audit-red.log` | `5aeacfd196c052edfba15b540d4f7b03b7ab8c93920e2439c3cae2b163b57f05` |
| `t20-audit-green1.log` | `26f03ba96b11e4c685304023b2ac814b142d3d831a1b7a96b3248c5cae964aef` |
| `t20-audit-green2.log` | `dd6e1707a63cadabc8ca035b174c242388bfe6b46507fbe5cde611840082553d` |
| `t20-audit-frozen.log` | `b4a7fa4547ef331d727aaa51ba05b2c8c76786db66f0a51ba21bd2d23e210086` |
| `t20-audit-ruff.log` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |

## T20-A05 — 实际只读尝试及观测限制

已知数据库：`D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor/data/monitor.sqlite3`。未读取配置或凭证。root执行前检查记录位于本地 `.pytest_cache/pma-t20-audit/root-review-before-actual.json`。root放行后，在项目目录准确执行下列命令一次；默认输出无需替换目录：

```powershell
.\.venv\Scripts\python.exe scripts/audit_plan_readiness.py --database data/monitor.sqlite3 --read-only --output-dir .pytest_cache/pma-installation-audit
```

开始：`2026-11-14T02:31:06.0368654+08:00`；结束：`2026-11-14T02:31:07.2404409+08:00`；报告 `computedAt`：`2026-11-14T02:31:07.104418+08:00`。实际退出码：**2**；stdout：`PERSISTED_ONLY NOT_READY`。结果：`database=WAL_SIDECARS_UNAVAILABLE`、`installationStatus=NOT_READY`、`runtimeOwnership=UNKNOWN`、`notificationConfiguration=UNKNOWN`、`authorityGranted=false`。

已有文件具有WAL头，但前置检查时所需WAL/SHM组合不完整。脚本没有打开SQLite。schema及迁移数组、全部记录列表、`limitedSections` 和 `activeReferenceGaps` 均因尚未开始取证而为空：**零条已收集记录不代表数据库实际有零条记录或不存在归属缺项**。覆盖安装状态仍为UNKNOWN。当前owner快照、当前通知配置及当前数据/评估/准确绑定仍缺失。本次不能推断迁移头、已保存计划数量或实际渠道健康。未修复或再次运行命令。

| 本地实际证据 | SHA-256 |
| --- | --- |
| `.pytest_cache/pma-installation-audit/audit.json` | `a45c6d578c96c8aa5ad21c0b2ec6afdf73e4053e32eb790e441bf5bbe9a07db3` |

准确命令、开始/结束、退出码、输出位置及冻结代码哈希保留于 `.pytest_cache/pma-t20-audit/t20-actual-receipt.json`；stdout保留于同目录 `t20-actual-stdout.log`。这些本地文件不提交。Exit2刻意伴随NOT_READY，不是实际安装PASS。保留已有输出；未来运行须明确新的输出位置并由root协调。本次不授权恢复伴随文件、checkpoint、迁移或启动服务。

当前没有明确配置的既有服务地址。公开 `GET /api/v1/plan-versions/{version_id}/monitor-readiness` 已提供自有就绪投影，未来明确配置后可读取。本子片不探测默认端口，也不构建可选HTTP平台。持久时间戳不能代替owner当前快照。实际迁移、审核/启用、库存/成本确认、采集及测试发送仍不属于本审计。

## T20-A06 — 剩余门禁

已记录获授权的实际尝试，但缺少WAL伴随文件前置使必需安装事实尚未取证。**T20实际取证保持未完成。** 离线审计工程通过；实际只读尝试已执行；实际schema/计划/评估/渠道事实未取得；运行就绪未证实。root保留此未完成状态，并可按P07继续T21独立工程，不把本次NOT_READY视为完整实际安装验收。脚本/测试字节与root执行前审核时相同。供应商尝试保持0/48；原始03/04正例验收、C05及最终门禁仍未解决。未提交、改受保护任务、迁移用户库、启动默认服务、真实通知或提取。最终复核、共享报告及完成决定归root，本子片不推进下一任务。
