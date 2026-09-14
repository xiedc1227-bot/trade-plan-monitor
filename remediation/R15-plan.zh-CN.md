# R15 离线 AI 提取诊断计划

英文原版为 `R15-plan.md`，本文是等价中文审阅副本。R15 承接 `docs/verification/R14-execution-20260914-supplement.md` 记录的 R14 部分真实执行。原先三次供应商响应未留存，精确原因仍未知。

## 范围与边界

- 仅处理 AI 提取、Web 生命周期和本地诊断持久化路径。不调用收费 AI、行情、Webhook 或真实 `--execute`；不复用 R14 一次性授权，不修改其占位、数据库或已完成证据。
- 保持原有严格提示词/输出契约及全部 3-AI、60-行情、字节、token、日期、单会话门禁。不得将未知输出变成成功或可执行计划。
- 保留 `remediation/evidence/R14-preparation/protected-before.json` 中全部 16 个受保护文件，仅提交 R15 文件。

## 验收清单

- [x] 真实 Web 提取在诊断文件可写时，失败后留下有界持久记录，关联 operation/request ID、原文 SHA-256、配置的 provider/model、prompt version、状态、阶段、安全错误类别、安全路径、finish-reason 类别及可选已验证 usage/尝试次数。缺失值标为 `unknown` 或 null；写入失败以 `WRITE_FAILED` 报告，不改变提取结果。
- [x] 区分供应商失败、非 stop/截断、JSON 语法/重复键/非有限数/预算、schema、field-evidence/mapping 失败。不持久化模型内容、原文、提示词、原始错误、header、token/key 或 Pydantic input/context/message。所有不可信路径和值均通过封闭类别及上限归一化。
- [x] 公开 Web 失败结果仍不暴露草稿或供应商内容。非法提取不能保存或激活计划，不能改变持仓；现有有效计划仍保留。忠实合法结果仍走通常的仅供复核流程。
- [x] 离线测试通过受控 HTTP 传输进入真实 FastAPI lifespan 和生产供应商适配器。每份合成响应标记 `SIMULATED`；结果在生命周期重启后可追溯，并对 stdout、Web 响应和磁盘进行恶意字符串泄漏检查。
- [x] 使用唯一 `--basetemp` 运行聚焦 AI/Web/持久化/启动器及相关契约测试，并执行适用 Ruff 检查。在双语 R15 交接中报告精确命令和限制。

## 诊断保留与访问

仅把元数据存于按配置的 SQLite 路径命名的 JSONL 旁路文件。单条最多 2,048 字节；文件最多保留 512 条和 1 MiB，达到上限时移除最旧记录。文件沿用本地数据库目录访问控制，不通过 HTTP 提供。没有自动按时间删除：有本地文件访问权的运维人员查看后，在诊断审阅完成时随隔离数据库删除。无法对 R14 历史数据库追溯诊断。旁路文件不可用时，普通 Web 启动和提取继续，并在 operation 中报告 `WRITE_FAILED`；专用 R14 有界启动器在诊断文件不可写时拒绝启动付费会话。
