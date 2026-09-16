# R29 plan-extract-v6 离线准备记录

英文原版为 `R29-v6-extraction-preparation-20260916.md`，本文是等价中文审阅副本。提案 `R29-20260917-V6-LITERAL-ACCEPTANCE-1`；运行 `r29-20260917-a`。状态 **OFFLINE_PREPARATION_COMPLETE / LIVE_NOT_RUN / CLAIM_UNCONSUMED / ZERO_AI / ZERO_MARKET / EXACT_APPROVAL_PENDING**。

## 已准备结果

R29 现已具备失败关闭的一次性候选，在不改变仓库默认值或真实配置的前提下选择 `plan-extract-v6`。它复用生产供应商、提取、严格 schema、服务端映射校验、v2 诊断 sidecar 与字面 oracle。唯一共享修改是让传输提示词字节上限可配置，同时默认值仍为 `19,000`；R29 设置冻结的精确 v6 大小 `19,359`，并继续强制提示词哈希和完整请求体匹配。

执行门禁允许一次 `LITERAL` AI POST、零重试、零行情调用，provider 超时为 30 秒，总边界为 45 秒，清理最多 15 秒。首个终态后停止。回执不确定、模型不匹配、非 stop 结束、供应商/超时、JSON/schema/映射失败、oracle 不匹配、复核回执不匹配、隔离失败或清理失败均不能触发重提。

## 精确外发包

被忽略的本地审阅目录为 `data/r29-v6-extraction-review/`，其中包含精确 material JSON、完整英中审阅副本和 manifest。包 SHA-256 为 `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9`。

| 文件 | SHA-256 |
|---|---|
| `egress-material.json` | `e017fc3d453c943a020cb438644ae05e41f1738d8055ddd4d8c73404187b5bc1` |
| `egress-review.md` | `aadffd35eda02ef3cfe238ed00abd5215fc8c0ade48f012dce19e22055d2b030` |
| `egress-review.zh-CN.md` | `28e493b5a50f31ca20f3d8db88924b62e37f6cd6a2b37a33fcb85e87a69f38b8` |
| `manifest.json` | `ef8d955294d7bac991f104604243887cb4a180968d3e209bec5c956c0f662240` |

该包完整展示合成原文及完整 v6 唯一 user 提示词，二者均不翻译；同时展示请求字段、目的地、单次调用边界、v5/v6 提示词哈希、变化规则摘要和当前保守费用估算。凭据、完整配置、供应商输出、响应 Header、异常正文和直连 IP 均被排除。

## 离线验证

- R29 聚焦套件贡献 `16` 个收集用例，并在组合回归中全部 `16` 个通过。
- R25/R26/R27/R28、供应商、提取、诊断与显式复核组合组共运行 `138` 个用例：`137` 个通过；唯一 R25 预检失败只因隔离 Git worktree 有意不含被忽略的 `config/app.yaml`。没有为了通过测试而复制真实配置。
- 另一次包含 R14 的运行得到 `52` 个通过和两个无关失败：既存 R14 门禁测试缺少其本已要求的 `temperature=0`，且隔离 worktree 缺少被忽略的已安装 Web 资源。R29 未修改任何一项。
- 三个变更 Python 文件的 Ruff 检查通过；两个新增 Python 文件的 Ruff 格式检查通过。既有 R14 文件在 R29 四行改动之外存在更广泛格式漂移，因此未机械重排。
- `git diff --check` 通过，只出现 Git 针对既有 R14 文件的 Windows 换行提示。
- 干跑预检报告 `materialMatchesFrozenV6=true`、`reviewPackageMatchesCandidate=true`、`freshClaimAvailable=true`、`configCopiedIntoWorktree=false` 及 `ready=false`。
- 仍有一个既存 Starlette/httpx 弃用警告。

## 当前实际门禁状态

准备阶段未发起任何 DeepSeek 或行情请求，未探测账户端点，未创建 claim 或数据库，也未改变生产/真实配置。隔离 worktree 起初没有配置来源，且首次干跑快照时代码尚未提交。在精确包获批且用户要求现在运行后，只有本地启动门禁改为 `2026-09-16 13:30–15:00`；已批准外发字节与包哈希保持不变。

用户随后已明确批准把展示包一次发送至 `POST https://api.deepseek.com/chat/completions`、知悉可能费用，并要求现在运行。真实派发前仍必须确保包括最新官方路由/价格复查和显式只读配置路径在内的全部预检门禁为绿。
