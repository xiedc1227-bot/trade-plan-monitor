# 规格：ai-plan-drafting（AI 计划草稿转换）

> 中文审阅版。英文权威版为 `SPEC-ai-plan-drafting.md`；两份文档必须保持语义一致。

## 目标

通过用户可配置的 AI 服务，把粘贴的自然语言交易计划转换为可审核的 `plan-domain` 草稿。AI 只负责信息提取与规范化，不负责激活计划，也不参与盘中决策。

默认服务通过 DeepSeek 的 OpenAI 格式 Chat Completions 端点调用。用户可以修改请求 profile、Base URL、模型、密钥引用和有界请求设置，也可以选择其他经过审核的 OpenAI-compatible 服务。用户可以测试连通性、粘贴中文计划、查看字段证据/假设/遗漏、修改结构化结果、运行确定性校验并通过独立操作激活计划。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- `httpx` 异步 HTTP 客户端
- Pydantic 2：校验 AI 输出和计划草稿
- 内部 `AIProvider` 协议，以及明确的 DeepSeek 与通用 OpenAI-compatible 请求 profile
- `SecretStore` 协议：Web 与 CLI 操作从有大小限制的项目密钥文件装入
- SQLite：只保存非敏感配置和审计元数据

首版不依赖厂商 AI SDK，使用显式 HTTP 适配器降低耦合。

## 命令

```powershell
python -m pytest tests/unit/test_ai_plan_drafting.py -q
python -m pytest tests/integration/test_ai_provider_contract.py -q
python -m ruff check src/trade_plan_monitor/ai tests/unit/test_ai_plan_drafting.py tests/integration/test_ai_provider_contract.py
```

## 项目结构

```text
src/trade_plan_monitor/ai/
├── models.py             # AI 配置、提取结果、证据与问题
├── provider.py           # AIProvider 协议
├── openai_compatible.py  # 有资源上限的 HTTP 适配器
├── prompts.py            # 版本化提示词构造
├── extraction.py         # 草稿提取、解析和校验流程
├── file_secrets.py       # 有大小限制的项目密钥文件读取器
└── secrets.py            # SecretStore 协议和实现
tests/unit/
└── test_ai_plan_drafting.py
tests/integration/
└── test_ai_provider_contract.py
```

## 公共契约

```python
class AIProvider(Protocol):
    async def test_connection(self, config: AIProviderConfig) -> ProviderTestResult: ...
    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse: ...
```

可配置的非敏感字段包括：

- `providerId`、请求 profile、显示名称、服务类型、Base URL 和模型；
- 项目密钥文件/键名引用以及“是否已配置密钥”状态；
- 超时、最大重试次数、最大输入字符、最大输出 Token；
- 温度默认固定为 0，允许范围 0～0.3；
- 提示词版本和启用状态。

首版稳定范围为：Base URL 最长 2,048 个字符；项目密钥文件路径最长 1,024 个字符；密钥文件最大 65,536 字节；超时 1～120 秒（默认 30）；重试 0～2 次（默认 2）；输入 1～200,000 个字符（默认 50,000）；输出 1～16,384 Token（默认 4,096）；温度 0～0.3（默认 0）。重定向不可配置且始终禁用。只有字面值 `localhost`、IPv4 回环地址或 IPv6 回环地址可使用 HTTP，其他地址必须使用 HTTPS。包含账号密码、查询字符串或片段的 Base URL 无效。

### 服务适配器契约

适配器使用 Bearer 鉴权发送 `POST {baseUrl}/chat/completions`，绝不发送工具，只把模型内容作为不可信原始文本返回。通用 `OPENAI_COMPATIBLE` profile 使用 `messages`、`temperature`、`max_completion_tokens` 和 `stream=false`。默认 `DEEPSEEK` profile 遵循 DeepSeek 当前契约：使用 `max_tokens`，设置 `thinking={"type":"disabled"}`，提取计划时增加 `response_format={"type":"json_object"}`，并保持 `stream=false`。DeepSeek 默认值为 `https://api.deepseek.com`、`deepseek-v4-flash` 和项目密钥键 `DEEPSEEK_API_KEY`。文件引用为 `../.env`，相对于 `config/app.yaml` 解析，因此本地工作区读取本项目根目录中被 Git 忽略的密钥文件。

Web 与 CLI 都相对于 YAML 文件解析密钥路径，最多读取 65,536 字节并按严格 UTF-8 解码，只选择一个与 `api_key_ref.key` 精确匹配且非空的赋值，然后放入禁用环境变量后备的进程内密钥库。文件缺失、路径是目录、文件超大、UTF-8 非法、键缺失、值为空或键重复都会安全失败，错误不包含文件内容。Web 组合在启动时只读取一次配置，并在该次服务生命周期内保持不变，通过 `/plans` 提供提取。维护用途的 CLI 保留 `ai test [--config 路径]` 和 `ai extract [--config 路径] --source 文件`；`test` 发送一次有边界的连通性请求，`extract` 读取严格 UTF-8 普通文件、检查字节数和配置字符上限、校验返回草稿并输出，但不会激活计划。

- API Key 只短暂存在于 Authorization Header，并且必须全部为可打印 ASCII 字符。请求发送 `Accept-Encoding: identity`。
- 每次尝试使用配置的超时，完整操作最多执行 `1 + max_retries` 次。传输故障、超时、HTTP 408、429 和 5xx 可重试；数字型 `Retry-After` 和指数退避均封顶 2 秒。取消操作始终向外传播。
- 重定向响应一律拒绝；401/403 映射为鉴权失败；其他不可重试的 4xx 映射为拒绝。服务响应体绝不跨越适配器错误边界。
- 成功响应必须未压缩或使用 identity 编码，并在 JSON 解析前按原始字节读取，最大为 1,048,576 字节。其他内容编码都在不解压的情况下拒绝。
- 私有服务响应模型允许标准响应扩展，包括 Token 明细字段；只把 `prompt_tokens`、`completion_tokens` 和 `total_tokens` 映射到严格的公共 `AIUsage` 值。
- 稳定公共错误码为 `AUTHENTICATION`、`RATE_LIMITED`、`TRANSIENT`、`TIMEOUT`、`INVALID_RESPONSE`、`RESPONSE_TOO_LARGE`、`UNSAFE_REDIRECT`、`CONFIGURATION` 和 `REJECTED`。`AIProviderError` 只暴露错误码、操作和尝试次数，既不保留异常原因，也不保留异常上下文。

公共密钥管理能力被明确限制为只写/状态查询：

```python
class SecretStore(Protocol):
    def replace(self, reference: SecretReference, secret: SecretWrite) -> SecretStatus: ...
    def status(self, reference: SecretReference) -> SecretStatus: ...
```

`SecretStatus` 只暴露是否已配置、来源（`STORE`、`ENVIRONMENT` 或 `NONE`）、固定掩码和替换代数。通用密钥库为了现有集成和隔离测试仍保留环境变量能力，但配置文件驱动的 Web 与 CLI 组合始终以空环境创建密钥库，只插入项目密钥文件中选定的值。具体密钥库把运行时物化能力保持为包内私有，使供应商组装能够鉴权而不扩大公共管理协议。

通用注入式 API 契约可以接收新密钥，但项目配置文件驱动的生产组合对该变更返回 `METHOD_NOT_ALLOWED`，Web 页面也不会发送该请求。任何读取接口都不能返回密钥。日志、错误、审计和计划导出只保留非敏感状态，或旧注入式契约确实需要的引用。

### 提取结果

```python
class PlanExtractionResult(BaseModel):
    request_id: UUID
    provider_id: UUID
    model: str
    prompt_version: str
    source_text_sha256: str
    draft: TradePlanDraft | None
    evidence: list[FieldEvidence]
    assumptions: list[ExtractionIssue]
    warnings: list[ExtractionIssue]
    unmapped_text: list[UnmappedText]
    validation_issues: list[ValidationIssue]
    usage: AIUsage | None
    status: Literal["SUCCEEDED", "INVALID_OUTPUT", "PROVIDER_ERROR", "CANCELLED"]
```

每个非空可执行草稿叶子字段必须关联原文位置或包含至少四个原文字符的证据片段。可选 null 字段无需证据。模型声明的证据仍不可信：每次成功提取都包含激活阻断警告 `AI_EVIDENCE_REVIEW_REQUIRED`，直到可信用户完成审核。

无法支持的说明进入 `unmapped_text`，不能转换成任意公式。无论模型提供什么值，每个模型生成的 `unmapped_text` 项都规范化为 `material=true`，直到可信用户完成审核。

原始模型输出上限为 1,048,576 个 UTF-8 字节、10,000 个 JSON 节点和 64 层深度。重复 JSON Key 和非有限数值都会被拒绝。调用供应商前，包含生成 Schema 的完整渲染提示词必须满足已配置的输入字符上限。供应商取消会从提取函数向上传播；`CANCELLED` 保留给后续编排/API 作业回执，本函数不会合成该状态。

### 提示词契约

提示词必须包含：

- 已发布的计划 Schema 和条件白名单；
- 只返回 JSON 的要求；
- 无法确定时必须报告不确定项，不能猜测；
- 把用户计划明确包裹为不可信数据；
- 不包含密钥、实时持仓或无关报告。

提示词使用不可变版本号，例如 `plan-extract-v1`。修改提示词时必须创建新版本并更新黄金样例。包含生成 Schema 和规范 `GOLDEN_PLAN_SOURCE` 的完整 `plan-extract-v1` 提示词由 SHA-256 `1b42865ce7dda121b64a62e15faa1213dd2be55cf654277f0801cd9c29d0dd22` 锁定；模板或 Schema 的任何变化都必须创建新版本并更新黄金值。

### 审核与激活边界

AI 只能创建草稿。激活必须满足：

- 草稿修订号仍是当前版本；
- 不存在激活阻断错误；
- 用户已确认所有假设和警告；
- 每个重大 `unmapped_text` 都有明确处理结果；
- 请求包含乐观锁修订号和幂等键。

### T037 HTTP 适配器边界

通用本地 API 仍支持注入 `AIOperationService` 和计划提取提交服务。生产 Web 组合改为根据 `config/app.yaml` 构造 `ConfiguredAIWebLifecycle`，在 lifespan 启动时挂接只读 AI 摘要和提取服务，并在关闭时移除。`GET /api/v1/ai-runtime` 只暴露供应商 ID、显示名、安全 Base URL、模型、已配置/启用状态、输入/输出上限和修订号 `0`；不能暴露密钥文件路径、选中的键名或密钥值。

项目配置文件驱动的生产服务对供应商创建/更新、密钥替换和供应商测试返回 `METHOD_NOT_ALLOWED`。计划提取要求 `Idempotency-Key`、供应商 identity 和修订号 `0`；服务为每个意图计算 hash，只回放 Key 与请求都相同的记录，最多保留 1,000 条任务记录，并且最多同时运行一个提取。HTTP 响应只包含有界回执和经过校验的提取视图。额外字段、供应商原始响应体、授权数据和密钥材料都会在序列化前封闭失败。

`POST /api/v1/plan-extractions` 在进程内 Web 服务接收有界工作后返回 `202`；供应商 I/O 在后台任务执行，不在请求处理器中执行，也绝不启用计划。任务状态按设计只存在于当前进程，重启后丢弃。`GET /api/v1/plan-extractions/{id}` 暴露编排状态、经过校验的证据/问题和规范草稿 JSON；绝不暴露模型原始输出。关闭时会取消未完成任务，在关闭过程中记录局部 `CANCELLED` 状态，并释放共享 HTTP 客户端。

### T045 前端录入与审核边界

Vue `PlanWorkbench` 是使用强类型 props/emits 的薄局部组合边界。它只接收只读运行配置，拒绝对已禁用或未配置密钥的供应商执行提取，并发出提取、停止等待和问题处理意图。它没有供应商修改、密钥输入、供应商测试、Pinia 状态、领域规则、激活操作或持久浏览器状态。

`PlanDraftingView` 读取唯一的安全运行摘要，每次提交生成一个幂等 Key，显示 `202` 回执，并轮询精确任务 ID，直到 `SUCCEEDED`、`INVALID_OUTPUT`、`PROVIDER_ERROR` 或 `CANCELLED`。局部同时只运行一组提交/轮询。卸载和“停止等待”会中止浏览器工作；停止浏览器轮询不代表服务端已接收任务被取消。错误文案固定，不能包含供应商响应或密钥材料。

原文编辑器把粘贴计划视为不可信纯文本，并使用配置中的输入字符上限，按与 Python 一致的 Unicode code point 计数。超限编辑被原子拒绝，并恢复上一个完整值。证据绑定到精确的已提交原文快照，过期时隐藏。提取证据、假设、警告、未映射文本、校验问题、用量、错误和规范草稿 JSON 都只通过已转义的 Vue 文本插值渲染。结构化编辑、差异、校验编排和激活仍属于 T046。

## 代码风格

```python
async def extract_plan(
    *,
    request_id: UUID,
    source_text: str,
    config: AIProviderConfig,
    provider: AIProvider,
) -> PlanExtractionResult:
    prompt = build_plan_extraction_prompt(
        source_text,
        prompt_version=config.prompt_version,
    )
    request = PlanExtractionRequest(
        request_id=request_id,
        config=config,
        prompt=prompt,
    )
    raw = await provider.extract_plan(request)
    output = parse_untrusted_output(raw.content)
    return validate_and_build_result(output=output, raw=raw)
```

服务调用、JSON 解析、领域校验和持久化必须分离。模型输出始终是数据，不是命令。

## 测试策略

- 测试配置范围、URL 校验、密钥脱敏、提示词构造、JSON 解析和问题映射。
- 使用假的 DeepSeek profile 和通用 OpenAI-compatible 服务，覆盖请求格式校验、成功、标准响应扩展、非法 JSON、Schema 不匹配、真实超时、401/403、429、5xx、重试、取消、压缩响应和超大输出。
- 在计划文本中加入提示词注入样例，验证其不能改变输出契约或获得工具权限。
- 覆盖缺少日期、边界含糊、存在不支持文本以及华亚智能示例计划。
- 验证 AI 故障不会影响已经激活的监控计划。
- 验证 API、日志、序列化错误和异常链不会返回或保留 API Key 或 Authorization Header。

## 威胁模型与边界

- 信任边界：用户文本、文件配置的 Base URL、模型输出、服务错误体和项目密钥文件。
- 保护资产：AI 密钥、计划完整性、激活权限和费用上限。
- 始终：非本机 AI 地址必须使用 HTTPS；拒绝内嵌账号密码和不安全重定向。
- 始终：限制输入、输出 Token、超时、重试和并发提取数量。
- 始终：模型输出通过 Pydantic 后才允许保存或显示。
- 先确认：新增厂商适配器、工具调用、文件上传或自动联网取材。
- 禁止：向 AI 提供券商、文件系统、Shell、数据库、浏览器或行情工具。
- 禁止：自动激活、静默修复校验错误或在盘中决策时调用 AI。

## 验收标准

- 用户可以在项目文件中配置 AI，重启 Web 后看到安全的只读摘要；密钥值以及其文件/键引用都不会到达页面。
- 中文计划能够生成带原文证据的结构化草稿。
- 不支持或含糊内容明确展示，并在处理前阻止激活。
- 非法或恶意模型输出不能形成可执行规则。
- AI 故障、限流或输出错误不影响活动监控。
- Token、重试和并发限制能够阻止无界消耗。

## 待确认事项

无。Web AI 设置编辑明确不在范围内；Web 与 CLI 都只使用配置的、被 Git 忽略的项目密钥文件，不使用环境变量后备。
