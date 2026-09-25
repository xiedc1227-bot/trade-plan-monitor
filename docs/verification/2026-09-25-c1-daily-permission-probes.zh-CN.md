# C1 日级权限探针：离线 provider 证明

## 范围与结果

`DAILY_LIMITS`、`DAILY_BARS` 和 `INDEX_DAILY` 的只读 provider 证明通过独立 Sol/`xhigh` 复审，本切片无剩余 P1/P2 问题。测试使用模拟 SDK 响应。它们**尚未接入生产权限维护**，不选择持久化锚点或调度 300 秒复核，也不清除控制器阻断或写入业务缓存。C1 保持 **OPEN**。

## 证明契约

- `DAILY_LIMITS` 对调用方选出的已持久化、已结束开市日发起 `stk_limit(trade_date=D, fields=trade_date,ts_code,up_limit,down_limit)`。它检查全市场批次的每一行，要求 1–5,800 行、在准确日期 `D` 上唯一的规范六位代码与交易所后缀、有限正数原始价格，以及 `down_limit < up_limit`。不要求命中计划股票。原始价格不转换为 A 股分单位，因此合法的低于一分的 B 股或基金价格可通过。精确的基础文本/数值类型在字符串转换前受检；原始文本、Decimal 系数及定点展开分别受股票本地 640 字符/位规则约束。必需列各出现一次，所有列名唯一，允许唯一的额外列。
- `DAILY_BARS` 对调用方选出的相关股票和已持久化、已结束开市日发起 `daily(ts_code=S, start_date=D, end_date=D)`。沿用现有严格响应 profile 校验整个响应，要求准确 `S/D` 的一条有效官方日线；停牌空响应不能证明权限。持久化股票锚点选择与有界候选轮换仍待后续完成。
- `INDEX_DAILY` 对已认证为 READY 的指数与调用方选出的已持久化、已结束开市日发起 `index_daily(ts_code=I, start_date=D, end_date=D)`。它要求准确 `I/D` 的一条有效官方记录、必需列及全体列名唯一，同时允许唯一的额外列。不修改指数缓存。物理 SDK HTTP 401/403/429 故障被安全分类供控制器使用，不保留原始 token 上下文；`RequestNotStartedError` 原样透传。

## 验证与边界

`tests/unit/test_daily_permission_proofs.py` 在缺失探针、无效整批、640/641 位十进制边界、额外/重复/缺失列、模拟 HTTP 401/403/429 控制器效果及物理调用未开始等 RED→GREEN 检查后，**53 项专项测试通过**。下方相邻命令 **266 项通过**，并排除既有 `test_tushare_provider_errors_use_stable_codes_and_drop_raw_context` 参数组 **14 项**，因为其中 `requests.Timeout` 预期与未改动的 HEAD `TIMEOUT` 映射冲突。两个 provider 文件和新增测试文件的 Ruff 检查及 `git diff --check` 均通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_market_index.py tests/unit/test_market_index_data.py tests/unit/test_tushare_permission_probe.py tests/unit/test_market_data.py tests/unit/test_request_recovery_admission.py -q --tb=short -k "not test_tushare_provider_errors_use_stable_codes_and_drop_raw_context"
```

未请求真实 Tushare 行情、发送外部通知、迁移用户数据库、推送或部署。五个作用域的生产维护接线与独立锚点选择仍开放。另一次独立复审还发现普通指数请求路径及既有指数权限复核存在原始 SDK HTTP 分类缺口；这些问题不属于本纯探针切片。此证据不能关闭 A05、C1 或发布验收。
