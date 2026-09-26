# S3 离线回归检查点

> 中文审阅版。规范英文版本：`2026-09-27-s3-offline-regression.md`。

## 范围

协调会话在 DAILY_BARS 内部权限接线提交后，以源码 HEAD `453cc0c` 运行了计划中的离线回归。运行期间，现有源码和测试文件保持不变。新文档及 `tests/integration/test_s3_startup_minute_coverage.py` 在收集完成后并行新增，因此该新测试文件**不包含**在本次结果中。后续 SDK 边界修正也需要各自的验证证据。

只选择了离线测试。未运行真实行情服务测试，未使用真实通知服务，未迁移用户数据库，未推送或部署。大型回测文件严格按 S3-09 命令排除；本次不是不加限制的全部测试运行。

## 已执行命令与结果

| 命令 | 观测结果 |
| --- | --- |
| `.venv/Scripts/python -m pytest -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning**，670.06 秒；退出码 1 |
| `.venv/Scripts/python -m ruff check src tests scripts` | 在该源码检查点全部通过，执行时尚未新增启动覆盖测试文件 |

警告为既有 Starlette/httpx TestClient 弃用提示。定向分片通过不能抵消汇总门禁失败。此前有重叠的命令计数不能与本次相加。

## 失败清单

| 文件 | 失败用例数 | 观测到的失败，尚非最终根因分类 |
| --- | ---: | --- |
| `tests/integration/test_position_production_composition.py` | 3 | 日历权限、创建/重放、关闭/重放场景中，持仓创建返回 HTTP 409，而非预期的 200。 |
| `tests/integration/test_r13_channel_acceptance.py` | 3 | 显式 BUY、SELL、RISK_ALERT 场景记录了零次投递尝试，而非一次。 |
| `tests/unit/test_r14_bounded_acceptance.py` | 1 | `test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt` 在进入假 transport 前抛出 `BudgetDenied`。此前配对基础验证文档已记录模拟载荷缺少必需的 `temperature=0`；本次未修复或豁免该问题。 |
| `tests/unit/test_r17_failure_diagnostics.py` | 11 | 八个失败类别用例和三个异常脱敏用例抛出 `AttributeError`：其 `Pipeline` 测试替身缺少 `refresh_references` 访问的 `_stock_semantics`。 |

已安排只读诊断，通过响应正文、持久化记录和受支持的生产契约，区分测试前提漂移与真实产品回归。不得仅为通过测试而弱化安全守卫或断言。历史通过报告和历史失败仅证明各自检查点的状态，不能证明上述每项失败都早已存在。

## 独立边界发现

独立评审另用真实认证 wrapper、假 SDK 和受控时钟复现了 SDK 启动准入缺口：捕获于 `10:00:00`，最晚启动时间为 `10:00:15`，provider 回调/S 为 `10:00:14`，随后 wrapper 认证耗时两秒，内层 SDK 到 `10:00:16` 才开始。旧 S/R 证明仍可能通过。该内联复现不是已加入汇总运行的测试。已评审的逐调用边界修正及其独立 RED-to-GREEN 矩阵仍是后续工作。

## 门禁状态

**S3-09、C1、C3 和业务第三步仍为 OPEN。** 本检查点记录失败回归证据，不代表最终验收。启动分钟覆盖矩阵、SDK 边界修复、分钟 owner 执行、统一调度接线及更广泛的生命周期/故障门禁，均未因通过子集而获得认证。真实服务验证、第四步 UI 工作及第五步发布验收不属于本检查点。
