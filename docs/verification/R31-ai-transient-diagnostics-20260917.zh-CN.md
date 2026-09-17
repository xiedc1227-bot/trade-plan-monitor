# R31 AI 瞬态诊断报告

英文原版为 `R31-ai-transient-diagnostics-20260917.md`，本文是等价中文审阅副本。状态 **OFFLINE_DIAGNOSIS_COMPLETE / SAFE_CLASSIFICATION_ADDED / R30_CAUSE_UNKNOWN / ZERO_EXTERNAL_CALLS**。

## 范围与证据边界

R31 在不重放 R30、且不进行任何 AI、行情、账户、价格、路由、DNS、TCP、TLS、代理、证书或其他网络探测的前提下，调查 R30 记录的供应商阶段 `PROVIDER_ERROR / TRANSIENT`。仅通过固定安全字段和计数只读检查 `data/r30-ai-timeout-budget-acceptance/r30-20260917-a/` 下保留的 R30 产物。

R30 证明：一次已准入的 AI 物理尝试、零重试、零行情/账户调用、供应商阶段 `TRANSIENT`、`attempts=1`、无响应、无 usage、无 timeout kind、清理完成、audit/journal 一致，且 38 张业务表全部为零行。其 `261` 毫秒是完整有界工作的耗时，不是精确 HTTP 计时。v2 sidecar 未保存瞬态子类型，因此无法还原历史失败究竟属于 HTTP 状态、DNS、TCP、TLS、代理、协议、响应读取、解码还是其他请求错误。供应商是否收到、处理和计费仍未知。

## 准确的 R30 路径

1. `AIBudgetTransport` 校验精确 HTTPS 路由与冻结 v6 请求体，在委托给内部 transport 之前准入并计数物理尝试。保护层拒绝会抛出 `BudgetDenied`；它不是 `httpx.RequestError`，不会通过 provider adapter 变成 `TRANSIENT`。
2. R30 的 `AsyncClient` 在该保护层外设置 `follow_redirects=False`、`trust_env=False`、连接/写入/连接池超时 `30` 秒及读取超时 `60` 秒。默认内部 `AsyncHTTPTransport` 使用 `retries=0` 与 `trust_env=False`。
3. provider 另行应用 `65` 秒 `asyncio.timeout`。其捕获顺序会把 `ConnectTimeout`、`ReadTimeout`、`WriteTimeout`、`PoolTimeout`、整体截止及其他 `httpx.TimeoutException` 保留为带封闭 timeout kind 的 `TIMEOUT`。
4. R31 之前，HTTP `408/5xx` 响应与所有其余 `httpx.RequestError` 都只会变成 `TRANSIENT`。`AIProviderError`、提取诊断和 v2 sidecar 均不保留请求错误子类型或瞬态 HTTP 分组。
5. 严格 schema、mapping 与字面 oracle 仅在取得有效响应信封后运行。它们在 R30 中未运行，不能解释其供应商阶段结果。

## 安全本地环境发现

检查环境使用 Python `3.14.7`、HTTPX `0.28.1`、OpenSSL `3.5.7` 与 certifi `2026.07.22`；certifi 的 `cacert.pem` 路径存在。只读原配置为 `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor\config\app.yaml`，SHA-256 为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`。它配置了 HTTPS 主机 `api.deepseek.com`、存在的 API key 以及模型标识 `deepseek-flash` 与 `deepseek-v4-pro`；未打印或复制密钥值。

R30 binding 选择 `deepseek-v4-pro`，并且只在本地覆盖 `max_retries=0`、`max_output_tokens=8192`、`prompt_version=plan-extract-v6`、整体超时 `65`、transport 超时 `30` 与读取超时 `60`。发送请求体仍为 SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`。

离线检查时，`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`、`SSL_CERT_FILE`、`SSL_CERT_DIR`、`REQUESTS_CA_BUNDLE` 与 `CURL_CA_BUNDLE` 均不存在。与此独立的是，两层 client 都使用 `trust_env=False`。已安装 HTTPX 源码确认：当验证保持为 `True` 时，`trust_env=False` 会绕过环境证书路径并回退到 certifi CA bundle。R31 未禁用 TLS 验证、未增加代理、未改变 CA bundle，也未改变 transport 策略。

## 已实现的诊断契约

R31 增加封闭的 `AIProviderTransientKind` 值，且绝不复制异常正文、响应正文、Header、URL、IP 地址、errno 文本、Pydantic input/context、提示词或凭据：

| 具有结构化证据的来源 | `transientKind` |
|---|---|
| HTTP 408 | `HTTP_408` |
| HTTP 5xx | `HTTP_5XX` |
| `ConnectError` 且有界因果链包含 `socket.gaierror` | `DNS` |
| `ConnectError` 且有界因果链包含 `ssl.SSLError` | `TLS` |
| 其他 `ConnectError` | `CONNECT` |
| `ProxyError` | `PROXY` |
| `ProtocolError` 或 `UnsupportedProtocol` | `PROTOCOL` |
| `ReadError` / `WriteError` / `CloseError` | `READ` / `WRITE` / `CLOSE` |
| `DecodingError` | `DECODING` |
| 其他 `NetworkError` | `NETWORK` |
| 未识别 `RequestError` 或旧式瞬态构造 | `UNKNOWN` |

该类别仅在 `providerErrorCode=TRANSIENT` 时有效。超时和 schema 诊断保留现有契约并输出 `transientKind=null`。新 sidecar 记录使用 `version=3`；R27/R29/R30 评估路径同时接受 v2 与 v3，旧式无子类型瞬态会归一为 `UNKNOWN`。

## 验证

组合聚焦测试通过 **119/119**；明确排除 **2** 个依赖已安装 Web 资产的已知 R15 用例，并出现一条既有 Starlette/httpx 弃用警告。覆盖：

- 所有封闭瞬态分支、有界 DNS/TLS 因果检查、`UNKNOWN` 回退，以及注入密钥不会进入错误状态或 sidecar；
- HTTP 状态重试边界、单次零重试行为、timeout 子类型兼容、schema 诊断、正常成功提取、严格 mapping 与字面 oracle 行为；
- v2 reader 兼容与 v3 sidecar 输出；
- 真实 R30 guard/factory 路径下的一次物理启动、零重试、零行情调用、清理完成、audit 输出及业务表全空。

实现后，所有变更的 Python 源码与测试均通过 Ruff。生产配置、供应商、路由、请求体、提示词、输出上限、超时、重试策略、TLS 验证、代理行为、持仓、计划状态与 R30 证据均未改变。

## 外部调用记账

- AI 请求：`0`；
- 行情请求：`0`；
- 账户、余额、模型列表、路由、价格、DNS、TCP、TLS、代理或证书探测：`0`；
- 重试/重提：`0`；
- R30 重放：`0`；
- 创建或消耗新执行 claim：`0`。

## 下一轮最小建议

不得自动开启或执行 R32。若用户后续要求一次新的真实验收，先为最多 `1` 次 AI POST、`0` 次行情调用与 `0` 次重试准备新的精确审阅包和 claim，同时保持 v6 `LITERAL` 请求体及其 SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c` 不变。新请求能够增加信息，因为再次发生瞬态错误时，会区分上述固定 HTTP/transport 类别，而不再只报告 `TRANSIENT`；取得有效响应时仍会继续严格 schema、mapping 与 oracle 校验。

如果未来尝试报告 `UNKNOWN`，不要仅为重复该结果再发付费请求。应停止，并且仅在能够证明具体本地异常类型时继续扩展离线结构分类。任何新的真实尝试都需要用户重新批准及全新的一次性 claim。
