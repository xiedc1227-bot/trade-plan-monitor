# R07 后续交接：OpenAPI 契约门禁

日期：2026-09-12（Asia/Shanghai）。本文为中文审阅副本；`R07-followup.md` 是语义等价的英文正式交接。

## 完成情况

本后续步骤关闭了 R07 遗留的两项 OpenAPI 契约门禁失败，未改变运行时行为。R07 已批准的人工事件风险路由此前已实现、已生成快照和类型、并在 WEBF14 边界中记录；`beff041` 提交后门禁白名单和当前契约摘要未同步。

## 根因与实现

- `tests/integration/test_openapi_snapshot.py` 的 `APPROVED_PATHS` 遗漏了 `GET /api/v1/manual-event-risk` 和 `POST /api/v1/manual-event-risk-confirmations`。
- 双语 `SPEC-local-web` 的 T041 快照摘要和当前契约描述仍为 R07 之前的值：42 条路径、27 条实时路径，以及 SHA-256 `a742c64992ba80183ecf68b61c0f64d0dc93a1b073b5e79952dab795b2d579a9`。
- 实现提交 `de6d62066db6e20b825816c3ca55196387290b30` 只将两条已批准路径加入白名单，并只更新当前契约描述为 44 条路径（29 条实时、15 条回测）及 SHA-256 `fe3305aaf31db3eb8314675ab74790b40fc6e3ea08f44f69679127434bb001e3`。准确描述较早 42 路径边界的历史 WEBF 陈述保持不变。

## 契约复核

- GET 要求一个股票代码并返回三态 `ManualEventRiskView`。POST 要求 `symbol`、`CLEAR|RISK_PRESENT`、包含边界的 `expiresOn`、`expectedRevision` 及 `Idempotency-Key`，然后返回相同的权威视图。
- 两条路由均在 400、401、403、404、405、409、413、422、429、500 和 503 使用标准 `ErrorResponse`。只有持久化服务将写入绑定到当前活动计划哈希、拒绝过去的到期日、保护 revision、写入审计凭据并回放相同的幂等命令。
- 路由、服务、`openapi.json`、生成 TypeScript、R07 交接以及双语 WEBF14 规格相互一致。当前生成产物此前已与实现匹配，因此无需重新生成写入。

## 验证

- 修复前 RED：`.venv\\Scripts\\python.exe -m pytest tests\\integration\\test_openapi_snapshot.py -q -p no:cacheprovider` 返回 `2 failed, 12 passed`：旧双语 SHA-256 和两条遗漏的已批准路径。
- 修复后 GREEN：`.venv\\Scripts\\python.exe -m pytest tests\\integration\\test_openapi_snapshot.py tests\\integration\\test_manual_event_risk.py -q -p no:cacheprovider` 返回 `17 passed`，另有一条既有 Starlette 弃用警告。
- GREEN：`.venv\\Scripts\\python.exe scripts\\generate_frontend_types.py --check`、`.venv\\Scripts\\ruff.exe check tests\\integration\\test_openapi_snapshot.py` 和 `git diff --check` 均通过。
- 未重跑完整回放/容量套件。前次完整套件记录仍为 `2390 passed, 1 skipped, 4 deselected, 2 failed`；本步骤修复这两项 OpenAPI 门禁失败，不对未执行的完整套件作通过声明。

## 范围、来源与下一步

- 基线父提交为 `979a3ef2011d69c7c7da5adc84b52fd459f9279d`；自有实现文件是快照门禁测试与两份 `SPEC-local-web` 副本。本双语交接对是唯一新增文档。
- 12 个用户自有已修改文件和 4 个 R00 未跟踪产物保持未暂存，且未被纳入。修复前已记录其 SHA-256 清单，并会在交接提交后复核。
- 未使用依赖、外部调用、真实计划、持仓、数据库、凭据、供应商、通知或交易操作。未知任何剩余的 R07 OpenAPI 契约阻断。
- 协调会话应核验本交接对和提交，然后以 `gpt-5.6-sol/high` 启动已批准的 R09 任务。
