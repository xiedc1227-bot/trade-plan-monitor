# 规格：index-identity

> 中文审阅版。英文权威版为 `SPEC-index-identity.md`；两份文档必须保持语义一致。

## 目标

提供第一阶段唯一允许的“已校验 A 股股票代码 → 板块参考指数”映射。映射必须确定、封闭、带版本、无需供应商调用，并且不包含交易判断。

## 技术栈与命令

- Python 3.14、冻结且严格的 Pydantic 值、`StrEnum` 和 pytest。
- 不依赖数据库、时钟、网络、AI、浏览器或供应商。

```powershell
python -m pytest tests/unit/test_market_index_identity.py -q
python -m ruff check src/trade_plan_monitor/market_index tests/unit/test_market_index_identity.py
```

## 项目结构

```text
src/trade_plan_monitor/market_index/
├── __init__.py
└── identity.py
tests/unit/
└── test_market_index_identity.py
```

## 公共契约

`MAPPING_VERSION` 固定为 `board-index-map-v1`。`ReferenceMarketSelection` 固定为 `AUTO_BOARD`。

```python
class Board(StrEnum):
    SSE_MAIN = "SSE_MAIN"
    SZSE_MAIN = "SZSE_MAIN"
    CHINEXT = "CHINEXT"
    STAR_MARKET = "STAR_MARKET"
    BSE = "BSE"

class MarketIndexCode(StrEnum):
    SSE_COMPOSITE = "000001.SH"
    SHENZHEN_COMPONENT = "399001.SZ"
    CHINEXT = "399006.SZ"
    STAR_50 = "000688.SH"
    BSE_50 = "899050.BJ"

class ReferenceMarketBinding(BaseModel):
    selection: Literal["AUTO_BOARD"]
    mapping_version: Literal["board-index-map-v1"]
    index_code: MarketIndexCode

def resolve_board_reference(symbol: str) -> ResolvedMarketIndexIdentity: ...
def validate_reference_market_binding(symbol: str, binding: ReferenceMarketBinding) -> None: ...
```

`ResolvedMarketIndexIdentity` 还公开派生的 `board` 和不可变中文 `display_name`，供投影使用。计划只保存 `selection`、`mapping_version` 和 `index_code`。显示文本和板块是派生事实，不能成为第二套映射来源。

## 固定映射

| 已校验股票规则 | `board` | `index_code` | `display_name` |
|---|---|---|---|
| `.SH` 且前缀不是 `688` 或 `689` | `SSE_MAIN` | `000001.SH` | `上证指数` |
| `.SZ` 且前缀不是 `300` 或 `301` | `SZSE_MAIN` | `399001.SZ` | `深证成指` |
| `.SZ` 且前缀为 `300` 或 `301` | `CHINEXT` | `399006.SZ` | `创业板指` |
| `.SH` 且前缀为 `688` 或 `689` | `STAR_MARKET` | `000688.SH` | `科创50` |
| `.BJ` | `BSE` | `899050.BJ` | `北证50` |

输入必须先匹配现有规范股票格式 `^[0-9]{6}\.(SH|SZ|BJ)$`。分类只使用代码和后缀。禁止使用公司名称、AI 输出、指数成分股身份、远程分类或回退指数。非法或无法分类的输入必须在任何供应商调用前返回稳定校验错误。

## 计划与哈希边界

- 股票代码通过校验后，后端为 Schema v2 草稿派生绑定。
- 导入、保存、激活、回测提交和回放都重新计算绑定；任何不一致都拒绝。
- 规范计划 JSON 准确包含三个绑定字段，因此现有 `plan_sha256` 会覆盖 `schema_version`、`selection`、`mapping_version` 和 `index_code`，不引入第二种计划哈希算法。
- Schema v1 文档永远不增加绑定，并保留字节一致的规范 JSON 和哈希。
- 以后修改映射必须建立新映射版本和新不可变计划版本；绝不原地修改 `board-index-map-v1`。

## 测试策略

- 表驱动覆盖五条准确分支，包括 `688`/`689` 和 `300`/`301` 等号边界。
- 拒绝错误长度、后缀、小写交易所、空白、把指数代码当作股票代码以及任意字符串。
- 证明每个有效股票只解析一次，返回值不可变，并且不存在回退。
- 证明匹配绑定可通过；修改任一映射字段或股票代码都会失败。
- 证明 Schema v1 哈希黄金值不变，Schema v2 绑定会改变计划哈希。

## 边界

- 始终：分类前校验股票代码，并在证据中保留 `board-index-map-v1`。
- 先确认：增加板块、修改绑定、增加用户自选基准或建立新映射版本。
- 禁止：根据名称、成分股、供应商、AI 或行业分类推断；禁止回退到其他指数。

## 成功标准

- 每个规范 `.SH`、`.SZ` 或 `.BJ` 股票代码只映射到一个获批板块指数。
- 非法输入在 I/O 前失败，不能静默选择基准。
- 保存的绑定可重新计算、不可变，并且参与哈希。
- 本模块不存在行业指数或统一市场结论。

## 审核状态

双语板块指数提案和 ADR 0003 已于 `2026-09-02` 获批。当前用户请求授权本规格、实施和离线验证，但不授权提交、推送、安装依赖、部署或真实供应商网络访问。
