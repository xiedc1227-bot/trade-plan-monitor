# R32 AI 瞬态分类验收执行记录

英文原版为 `R32-ai-transient-acceptance-execution-20260917.md`，本文是等价中文审阅副本。状态 **AI_ACCEPTANCE_FAILED / TERMINAL / NO_RETRY / ISOLATION_PRESERVED**。

## 已授权范围

提案 `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1` 与运行 `r32-20260917-a` 从干净分支 `codex/r32-ai-transient-acceptance` 的提交 `276ef0cff7a68e6f08062b9293fdd5f16e43d3be` 执行。已批准的有序审阅包仍为 `7832b7e80f791c6a9f58fb30e1bd1f18f1958c60e6d845557d9b4f5e0916bfda`；与审阅包绑定的执行证明 SHA-256 为 `2326249e2bcfe9600590b11b7fa0dcb512e3b4352b7bbe49ac7aea3a649e87db`。

已批准限制为一次 `POST https://api.deepseek.com/chat/completions`、零重试或重提、零行情调用、零账户调用，以及 `81s` 父进程硬截止。固定原文、提示词与规范请求体 SHA-256 分别为 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`、`7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba` 和 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`。

## 当前官方复核

执行前，DeepSeek 官方 Chat Completions、Models & Pricing、Thinking Mode 与 JSON Output 文档确认基础 URL `https://api.deepseek.com`、路径 `/chat/completions`、模型 `deepseek-v4-pro`、禁用思考模式、JSON object 输出及所请求输出上限。官方 V4 Pro 峰值价格为缓存未命中输入每百万 token `$1.32`、输出每百万 token `$3.96`；非峰值价格分别为 `$0.66` 与 `$1.98`。按 `20,000` 输入加 `8,192` 输出计算的保守估算为峰值 `$0.05884032`、非峰值 `$0.02942016`。真实分词、缓存拆分、计费、税费及调整仍未知。

## 执行结果

- 开始于 `2026-09-17T12:12:59.744732+08:00`，结束于 `2026-09-17T12:13:34.008455+08:00`；
- 受控耗时 `34,272ms`；
- AI 物理尝试 `1`；网络前拒绝 `0`；行情尝试 `0`；重试/重提 `0`；
- audit 终态 `AI_ACCEPTANCE_FAILED`；
- 提取状态 `INVALID_OUTPUT`，诊断阶段 `schema`，固定路径 `draft.plan_id`，原因 `SCHEMA`，schema 错误类型 `other`；
- provider 结束原因为 `stop`，配置模型匹配，诊断面可见响应 usage 元数据，但没有产生已接受提取的 usage 记录；
- provider 错误、瞬态分类与超时分类均不存在；oracle 状态 `NOT_RUN`；
- 清理 `COMPLETE`；复核回执 `0`；独立计数的 38 张业务表均保持零行；
- claim 为 `CONSUMED`；不允许重试或第二次 POST。

更早一次已授权启动因提权身份最初无法读取 Git 状态，在创建 claim 与网络 I/O 前停止。提交命令级 safe-directory 修正后，提权离线预检返回 `ready=true`。该本地停止消费零物理尝试，不属于 provider 提交。

## 证据

受控本地证据位于 `data/r32-ai-transient-acceptance/r32-20260917-a/`，并继续被 Git 忽略。本文不复现凭据、授权 Header、原始提示词/原文、原始 provider 内容、异常正文或直连 IP 地址。

| 文件 | SHA-256 |
|---|---|
| `claim.json` | `0bc80711d74c2313b01cf335854058a1942540152f9ab0ecd66074e22e21df5f` |
| `audit.json` | `92b8973961cf39f1f7e57586de77c5b40346dd0d5085569684044f696dc7b8f7` |
| `physical-attempts.json` | `1217905754c7c4b3c77634defebad8e1d35074dd3a16f45575baf8839c3637a8` |
| `monitor.ai-extraction-diagnostics.jsonl` | `a0e0acf8f4ff303e4e2762614d322ea625eb3fc183c2866a9ed94194a5de557c` |

R32 已终态结束。不得重试、重提、重放 R30，也不得自动启动 R33。
