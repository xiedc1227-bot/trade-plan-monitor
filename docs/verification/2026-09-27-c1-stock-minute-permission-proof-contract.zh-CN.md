# C1 股票分钟权限证明契约

> 对应的规范英文输入为 `2026-09-27-c1-stock-minute-permission-proof-contract.md`；本文件是供人工审阅的中文副本。

## SMP-01 状态与范围

- 日期：2026-09-27。
- 状态：**CONTRACT AND CODE REVIEW PASSED / offline implementation complete**。
- 纳入五项明确化修订后，独立 Sol/xhigh 复审未发现剩余 P1/P2，批准离线实现。这是契约批准，不代表已实现行为或测试通过。
- 两项实现问题修复后，后续独立代码复审通过：291 项分钟测试、297 项相邻测试、32 项扩展反例断言；无剩余 P1/P2。这些评审者结果由协调任务报告，与作者运行分开记录。
- 本文保存协调提案 v3 及其已评审修订。契约批准已记录于上方；不声称真实服务认证。
- 提议范围：两个股票分钟 provider 权限方法及其离线契约测试。本文不授权生产调度、权限控制器接线、数据库迁移、用户数据库访问或真实服务调用。
- 离线实现与最终文档评审已完成；协调任务已授权本薄步八个文件的本地提交。已执行验证记录于配对验证报告。C1 与整体运行时恢复验收仍开放。

## SMP-02 既有规范与已评审规则

既有配对规范 [SPEC-market-data.md](../specifications/monitoring/SPEC-market-data.md) 和 [SPEC-market-data.zh-CN.md](../specifications/monitoring/SPEC-market-data.zh-CN.md) 已确定经认证的 START/END 解释、精确整分钟身份、默认 12 秒宽限、实时／历史标签证据独立，以及股票数值单位与校验。普通分钟读取有意隔离非法身份，并可返回合法子集；本提案不改变该业务行为。

协调提案 v3 增加下述严格整批权限分类：冻结 SDK 开始／返回时刻、允许不作证明的开盘及未完成行、最多两条未完成行，以及正向完成行门槛。在本文之前，恢复出的 v3 记录属于协调文本，而非配对仓库契约。保存为本文不代表独立批准。

历史 `stk_mins` 的 241 行证据不能认证 `rt_min` 或 `rt_min_daily`。离线混合行夹具不能证明真实 `rt_min` 会返回任何已完成证明行；真实响应若仅有形成中行，仍不足以证明。

相关既有边界为 `market_data/tushare.py`、`market_data/sessions.py`、`market_data/models.py`、`runtime/provider_contract.py`、`live_profiles.py` 和 `runtime/request_control.py`。路径相对于 `src/trade_plan_monitor/`。

## SMP-03 已评审接口与不可变结果

```python
probe_current_day_minutes_permission(
    symbol: str, trade_date: date, *, physical_start: Callable[[], datetime]
) -> MinutePermissionEvidence

probe_realtime_minutes_permission(
    symbol: str, trade_date: date, *, physical_start: Callable[[], datetime]
) -> MinutePermissionEvidence
```

这些是本离线薄步实现的已评审签名。每次调用验证一个规范股票代码，最多调用一次对应 SDK（`rt_min_daily` 或 `rt_min`），固定 `freq="1MIN"`，并使用 provider 冻结的、兼容且已认证的 STOCK 源标签。`UNVERIFIED` 在 SDK 调用前拒绝；不能根据数据形状或历史配置推断、替换该标签。

已复核结果为 frozen、slots 的 `MinutePermissionEvidence` dataclass：`operation: Literal['rt_min_daily', 'rt_min']`（不依赖 runtime 枚举）、`symbol: str`、`request_date: date`、`started_at: datetime`、`received_at: datetime`、`source_label: SourceTimeLabel`、`source_dates: tuple[date, ...]`，以及整数 `completed_count`、`opening_count`、`incomplete_count`。来源日期排序去重并覆盖 A/B/C。只从完整已验证数据构造该值。正常返回要求至少一条结构合法 A 行；owner 日历／授权验证前仍是候选。结果不含 ORM 对象、可变 DataFrame、业务 `MinuteBar` 批次或持久授权。

在 `physical_start` 或 SDK 调用前捕获并验证源标签。全部行解释及返回证据均使用同一个局部值；回调／SDK 修改 provider 字段不能改变本次请求的标签。未来 owner 授权检查仍决定该证据能否使用。

## SMP-04 冻结时间

- S 是排队结束后、实际同步 SDK 调用前，由 `physical_start()` 返回的上海时区时刻。R 在 SDK 返回后、解析响应前立即捕获。
- 两者均属于 `trade_date`；要求 `0 <= R - S <= 15s`。15 秒是固定的最大证据区间：超过该区间的结果被拒绝，不代表 SDK 在 15 秒时被强制中断。请求 timeout 配置默认 30 秒、最多允许 120 秒；物理传输／运行时 timeout 政策属于 composition。时钟倒退、跨日返回或无法证明该窗口均不能形成成功证明。超时、取消和撤销检查保持独立；墙钟不等式不能替代它们。
- 完成性只使用 S。R 仅限制返回的普通区间是否可能已经开始。后续验证时间不能扩大区间，也不能将非证明行升级。
- 本提案固定证明宽限为 12 秒、最大证据区间为 15 秒。provider 配置任何非 12 秒 grace 时，在 SDK 调用前拒绝；普通业务读取不变。其他参数下未经评审不能沿用两行上限。
- 分类不扩大生产环境允许启动维护的时段。

## SMP-05 整批验证与 A/B/C 分类

在列名哈希、行转换或遍历前，要求 DataFrame 并检查原始维度：恰好 8 或 9 列，行数满足对应 operation 上限。每个列名必须是精确的内置 `str` 类型、最多 7 字符、唯一且属于允许集合。公共必需列为 `time`、`open`、`close`、`high`、`low`、`vol`、`amount`。`rt_min_daily` 还要求 `ts_code` 或 `code` 中恰好一个；`rt_min` 要求 `ts_code` 并禁止 `code`。唯一可选列为 `freq`，明确允许两个 operation 都缺省；存在时每个值必须是精确字符串 `1MIN`。这些证明方法拒绝未知额外列，不改变普通业务读取的兼容性。

本提案将源 `time` 限定为精确内置 `str` 类型、19 字符的 `YYYY-MM-DD HH:MM:SS`，要求解析／格式化往返完全相等且秒为 `00`，按 Asia/Shanghai 解释。不接受空白、其他格式、小数秒、`datetime` 或 pandas Timestamp。以后增加 datetime 支持，必须明确同等严格的时区／整分钟／纳秒契约并重新评审，不能隐式强转。请求身份也必须是与已验证 symbol 匹配的精确字符串。

数值单元格仅允许精确内置 `str`、`int`、`float` 或 `Decimal` 类型；在调用转换钩子前拒绝 `bool`、子类及任意对象。在 decimal／integer 规范化或展开格式化前，限制原始文本最多 640 字符、decimal coefficient 最多 640 位、计算得到的展开定点表示最多 640 字符（适用时包括符号／小数点）。整数在转十进制字符串前检查上限，拒绝非有限 float／decimal。根据 exponent 计算展开上限而不分配展开结果，包括 zero 和 amount；零值快速路径不能绕过资源检查。A/B/C 的全部数值字段适用同样上限。预检后仍适用既有精确整数分／股数转换上限。这些是提议的证明专用标量限制，不改变普通业务解析。

有界行迭代必须在预检前保留 object 单元格类型。`DataFrame.to_dict` 不适用：它可能在验证器读取单元格前执行数值子类转换钩子。继续支持普通 pandas integer/float 列，但包含 `int`／`float` 子类的 object 单元格必须在不调用其钩子的情况下拒绝。

每行必须具有准确的请求股票、合法来源日期及上述规范整分钟时间戳、合法有限数值、可精确转为正整数分且上下界一致的 OHLC、精确非负整数股数成交量，以及有限非负的元成交额。完成有界标量预检后复用既有精确数值转换，单位不变。B/C payload 与 A 同样严格验证。畸形、外来股票、冲突或重复身份均拒绝，包括内容相同的重复；不能丢弃这些行来制造成功。

| 类别 | 必需时间形状 | 正向完成证据 |
| --- | --- | --- |
| A — `COMPLETED_PROOF` 候选 | 普通、完整位于交易时段内的分钟，规范结束时间为 e，且 `e + 12s <= S`；仍需最终持久开市日验证。 | owner 验证后可以。 |
| B — `OPENING_NON_PROOF` | END 标签、准确 09:30:00、`source_date <= trade_date` 且 `source_at <= R`，每个 `(symbol, date)` 最多一条。 | 不可以。 |
| C — `MINUTE_NON_PROOF` | 普通请求当日分钟，`e + 12s > S` 且区间开始 `b = e - 1min <= R`。 | 不可以。 |

普通结束时间为 09:31–11:30 和 13:01–15:00。START 将源时间加一分钟得到 e；END 使用源时间。因此 START 09:30 是普通 09:31 分钟，不属于 B。START 11:30 和 15:00 映射到交易时段外，必须拒绝。END 11:30 和 15:00 是合法普通结束时间，仍须满足 A/C 时间条件；END 13:00、跨午休分钟和 15:01 非法。

B 不获得业务 bar end、不替代 09:31、不贡献覆盖，也不附加“OHLC 必须相等”或“成交量必须为零”等臆造条件。其时间戳必须在冻结 R 时已发生：当 S/R 为 09:20 时，前一日 A 加今日 09:30 B 会使整批失败；任何未来日期 B 也使整批失败。每个 B 日期仍须通过最终 owner 日历验证。对 `rt_min` 接纳此形状属于提议的安全非证据类别，不代表已观察或认证真实接口返回该形状。

C 包含宽限尚未结束、形成中及调用跨越的分钟。在 R 时已完成的分钟，本次请求仍保持 C。`b > R` 非法。END 源标签本身可以晚于 R，只要区间开始已 `<= R`，且满足其他条件，就可以属于合法 C；这与 B 的 `source_at <= R` 规则不同。在固定 12 秒宽限和 15 秒最大证据区间下，C 最多有两个不同分钟身份：`e > S - 12s` 且 `e <= R + 60s` 的跨度最多 87 秒。三条 C 失败。A 与 C 共用唯一 `(symbol, e)` 身份集合。分类不依赖行顺序，不要求历史连续，也不要求包含最新分钟。

## SMP-06 上限与正向证明谓词

- `rt_min_daily`：正向响应具有 1–241 条原始行，全部属于 `trade_date`；A+C 最多占用 240 个普通交易分钟身份，END 最多允许一个 B。最多两条 C 已包含在这 240 个身份中，不能加在 241 行上限之外。
- `rt_min`：正向响应具有 1–1000 条原始行，可跨多个不晚于 `trade_date` 的来源日期。每个来源日期最终都必须被证明开市。C 仅限 `trade_date`；过去的普通行可为 A，过去的开盘行可为 B。不能施加 241 行、五个日期或新的历史年龄截断。所有 B 均计入 1000 行预算。
- 候选成功要求 schema 与上限合法、每行恰好属于一个合法类别，且 A 至少一条。最终成功还须通过 owner 日历与授权验证。
- 带完整类型列的空帧或合法的仅 B/C 帧属于 `NO_POSITIVE_PROOF`。无 schema 空帧、坏行或超限属于非法。两者均不清除既有 latch，也不制造新的 HTTP 403。

## SMP-07 错误与请求未开始的传播

`NO_POSITIVE_PROOF` 使用私有 `TushareProviderError` 子类，携带 `TushareErrorCode.INVALID_RESPONSE` 和固定安全文本。在解析 catch 外抛出，以便经过既有控制器失败路径仍保留区别。不增加公共诊断字段，不保留原始 payload。runtime `RequestNotStartedError` 在函数内导入，避免模块循环导入。

不能用正常返回 `False`、`None` 或空成功值表达它：现有 `recheck_permission()` 在正常返回且 `validate_after` 成功后会清除对应 operation。既有预约仍由控制器管理；本纯 provider 薄步既不创建，也不清除预约。

将 `physical_start` 放在宽泛供应商错误转换之外，并让原始 `RequestNotStartedError` 在整条调用链中原样传播。范围包括 `_fetch_frame`、`_DefaultTushareQuery` 及客户端 direct route 的宽泛捕获；只有外层回调还不够。已经发生的 SDK 调用不能重新标记为未开始。

必须在泛化 connection error 处理抹掉状态之前，将结构化 HTTP 401/403 分类为权限失败，将 429 分类为限流。其他真实 SDK/HTTP 失败保留脱敏的瞬态、超时和非法响应分类。测试同时覆盖假 SDK 及安装客户端包装配合假 transport：一次尝试、保留原 request-not-started 对象身份、HTTP 分类不丢失。脱敏 provider 异常的消息、属性、`__cause__` 或 `__context__` 中均不能保留原始秘密／payload；仅抑制显示不够。可信本地 request-not-started 哨兵使用固定安全文本并原样传播。

## SMP-08 Owner 日历验证与副作用边界

worker 验证本地时间戳／交易时段结构，返回有界不可变来源日期；不调用 `_is_open_on` 或任何可能读数据库的回调。它不能自行认证持久开市事实。

未来 owner 接线必须对全部 A/B/C 来源日期做有界精确日期检查，包括只有 B 的日期。日期数量不能超过原始行数上限。未知、休市、变化或撤销的日历证据均阻止清锁；相关 calendar epoch、配置、语义、代次、停止及时钟围栏必须保持有效。本文记录该义务，但本薄步不实现生产接线。

provider 不写历史、最新报价、缓存、健康／READY 状态、评估或通知。现有 `_normalized_minutes` 会过滤行并按回执时刻判断完成性，不能作为严格证明解析器。只复用底层验证。不能把 B/C 强行构造成 `MinuteBar`，也不能伪造 `received_at` 来满足该模型。

## SMP-09 已评审决策与剩余门槛

1. **证明专用 schema／标量：**已批准明确的 8/9 列允许集合、两个 operation 的可选 `freq`、仅字符串的规范 19 字符时间、精确数值类型及统一 640 资源上限。普通 `rt_min_daily` 允许缺少 `freq`，能力探测则要求它存在；仅按 SMP-05 明确范围保留缺省容忍。
2. **自定义 grace 与 timeout 明确化：**已批准非 12 秒 grace 在 SDK 前拒绝，并将 15 秒定义为最大证据区间，而非强制 SDK 中断。传输／运行时 timeout composition 仍在本薄步之外。
3. **私有结果／错误表示：**已批准 SMP-03 的 frozen dataclass 和 SMP-07 的私有无证明子类，保留类型化 `INVALID_RESPONSE` 与请求未开始传播。

这些契约决策及 SMP-03/07 的表示已通过独立评审。离线实现已完成，独立代码复审未发现剩余 P1/P2。Owner 接线、生产调度、C1 验收和真实服务认证仍在本次已完成的 provider 薄步之外。

## SMP-10 验收矩阵

| ID | 必需测试边界 |
| --- | --- |
| SMP-RED-01 | A+B、A+C、A+B+C 候选；B、C、B+C 及带类型空帧无正向证明；合法 A 混任意坏行使整批失败。 |
| SMP-RED-02 | END 09:30 与 START 09:30→09:31；相同／冲突重复、错股票／日期、缺列／重复列、非法 OHLC、非整数股数、非法金额及 B/C payload 验证。 |
| SMP-RED-03 | `e + 12s == S`、差一微秒、`b == R`、`b > R`；推进验证时间不能重新分类冻结结果。 |
| SMP-RED-04 | 调用跨分钟产生两条 C 与三条的区别；拒绝 START 11:30/15:00 和 END 13:00，END 11:30/15:00 满足时间条件时合法；END 未来标签但区间开始 `<= R` 可作 C；午休、非规范／非整分钟时间戳及行顺序独立。 |
| SMP-RED-05 | `rt_min_daily` 241/242 及跨日拒绝；`rt_min` 跨日 242/1000/1001，不施加五日或 241 行限制，不要求连续／最新行。 |
| SMP-RED-06 | 假 SDK 及安装客户端包装／假 transport，包含 `_DefaultTushareQuery` 和 direct route：SDK 前撤销零物理调用；原始 `RequestNotStartedError` 原样传播；一次尝试，结构化 401/403/429 先于泛化连接失败分类；cause/context 与 payload 脱敏。 |
| SMP-RED-07 | R-S 准确 15 秒边界、超时长、时钟倒退、跨日返回、排队等待排除；配置 30/120 秒 timeout 不会使超过 15 秒的结果有效，也不代表强制中断。 |
| SMP-RED-08 | worker 零数据库访问和业务写；结果包含全部来源日期；未来 owner 验证拒绝未知／休市／撤销日期，包括仅 B 日期。Owner 接线测试仍属后续薄步。 |
| SMP-RED-09 | 既有普通分钟解析不变；标签 UNVERIFIED 在 SDK 前拒绝；历史证据不能授权实时标签；回调／SDK 将标签改为 END 或 UNVERIFIED 不能改变冻结 START 的分类及返回标签。 |
| SMP-RED-10 | 明确的 `freq` 缺省／存在规则，以及非 12 秒 grace 在 SDK 前拒绝；内部无证明失败不能被误作正常控制器成功。 |
| SMP-RED-11 | S/R 为 09:20 时，前一日 A 加今日 09:30 B，以及未来日期 B，均使整批拒绝；`source_at == R` 的 B 满足此时间边界。 |
| SMP-RED-12 | 行转换前检查列宽；拒绝未知／重复／非字符串列及不支持的身份别名；要求规范 19 字符往返一致；拒绝 datetime/Timestamp；A/B/C 中数值 bool／任意对象及 int/float 子类在零转换钩子调用下拒绝，接受普通数值列；对 A/B/C 中 raw 长度、coefficient、展开、zero 和 amount 的 640 上限测试边界及超限。 |

已执行 RED/GREEN、回归及独立代码评审证据单独记录于配对的 `2026-09-27-c1-stock-minute-permission-proof-verification` 报告。Owner 接线断言仍属后续薄步。本矩阵不关闭生产接线或 C1，也不认证真实服务。
