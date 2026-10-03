# 规格：plan-index-conditions

> 中文审阅版。英文权威版为 `SPEC-plan-index-conditions.md`；两份文档必须保持语义一致。

## 目标

在现有计划树中增加明确的 Schema v2 参考市场绑定和六种允许的板块指数条件叶子，并基于共用指数快照生成带计划路径的证据。是否使用指数以及使用位置由计划负责，不由工具决定。

## 命令与结构

```powershell
python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py tests/unit/test_decision_engine.py -q
python -m pytest tests/replay/test_decision_replay.py -q
python -m ruff check src/trade_plan_monitor/domain src/trade_plan_monitor/decision src/trade_plan_monitor/market_index
```

```text
src/trade_plan_monitor/domain/plan_models.py       # Schema v1/v2 和条件联合类型
src/trade_plan_monitor/domain/plan_validation.py   # 迁移/绑定/位置校验
src/trade_plan_monitor/decision/models.py          # 可空快照和指数证据
src/trade_plan_monitor/decision/conditions.py      # 六种纯计算和路径
src/trade_plan_monitor/market_index/requirements.py
tests/unit/test_plan_index_conditions.py
```

## 准确 Schema v2 契约

现有 Schema v1 形状和字段名保持不变。Schema v2 是增量扩展：

```yaml
schema_version: 2
symbol: 688001.SH
reference_market:
  selection: AUTO_BOARD
  mapping_version: board-index-map-v1
  index_code: 000688.SH
entry:
  condition:
    type: ALL
    conditions:
      - type: NON_DECREASING_CLOSE
      - type: INDEX_CLOSE_GTE_MA
        index_role: BOARD_REFERENCE
        period: 20
```

- Schema v1 禁止 `reference_market` 和全部指数叶子。
- Schema v2 必须包含一份后端派生的 `reference_market`，即使没有指数叶子也一样，以便监控展示信息性板块参考。
- 导入、AI 草稿接收、保存、激活和回测提交都重新根据 `symbol` 计算绑定，并拒绝不一致。
- 用户和 AI 不能自由提交 `index_code`、`mapping_version`、其他 role 或其他基准。草稿组合层负责生成绑定。
- 只有来源计划明确写出对应规则和参数时，AI 才能返回指数叶子；否则必须保留为未映射文本或警告。

## 允许的叶子与参数

所有叶子固定使用 `index_role: BOARD_REFERENCE`，可放在 `entry`、`reduction`、`risk` 或 `blockers` 下，并继续遵守最大深度 4、总叶子 50 的限制。

| 类型 | 准确字段 | 结果判断 |
|---|---|---|
| `INDEX_CLOSE_GTE_MA` | `period: 2..250` | 完整指数收盘 `>= SMA(period)` |
| `INDEX_CLOSE_LTE_MA` | `period: 2..250` | 完整指数收盘 `<= SMA(period)` |
| `INDEX_MA_NON_DECREASING` | `period: 2..250`、`lookback: 1..60` | 当前 SMA `>=` 回看 SMA |
| `INDEX_MA_NON_INCREASING` | `period: 2..250`、`lookback: 1..60` | 当前 SMA `<=` 回看 SMA |
| `INDEX_RETURN_GTE` | `window`、`window_size: 1..250`、`threshold_ratio` | 涨跌幅 `>= threshold_ratio` |
| `INDEX_RETURN_LTE` | `window`、`window_size: 1..250`、`threshold_ratio` | 涨跌幅 `<= threshold_ratio` |

`window` 只能是 `FIVE_MINUTE_BUCKETS|OFFICIAL_OPEN_DAYS`。`threshold_ratio` 是包含边界 `[-1, 10]` 的有限规范十进制比例；外部边界拒绝 JSON 二进制浮点数、指数形式文本、多余非规范十进制文本、NaN 和 Infinity。

未知参数、公式、role、路径、脚本、表达式、供应商字段和行业身份继续作为非法输入。

## 稳定计划路径

路径使用已保存计划的 snake-case 形状和从零开始的数组索引：

- 策略根：`entry.condition`、`reduction.condition`、`risk.condition` 或 `blockers.condition`；
- 逻辑子项：每一层保存的子项追加 `.conditions[N]`；
- 示例：`entry.condition.conditions[1].conditions[0]`。

路径由确定性树遍历生成，绝不接受 AI/浏览器输入。每条 Schema v2 指数叶子证据都有一个准确路径。调整子项顺序会改变路径和计划哈希。

## 判断与证据

`EvaluationContext` 增加可空 `reference_market_snapshot`。为空时该字段不进入规范 v1 结果序列化，从而保留全部 v1 哈希。包含指数叶子的 Schema v2 计划只能使用 `indexCode`、`mappingVersion`、截止时间、公式哈希和计划绑定全部一致的快照。

`IndexConditionEvidence` 只附加到指数叶子，字段包括：

- `plan_path`、`condition_type`、`index_code`、`mapping_version`、`snapshot_hash`；
- `decision_cutoff`、`data_cutoff`、`formula_id`、`formula_definition_hash` 和参数；
- 精确 `actual_value`、`comparison_value`、`unit=POINTS|RATIO`；
- `outcome=SATISFIED|UNSATISFIED|MISSING_INPUT` 和有序唯一缺失代码。

封闭缺失代码为 `INDEX_SNAPSHOT`、`INDEX_IDENTITY`、`INDEX_CUTOFF`、`INDEX_HEALTH`、`INDEX_FACT`、`INDEX_HISTORY` 和 `INDEX_FORMULA`。`MISSING_INPUT` 不包含猜测值，并且至少列出一个代码。非缺失证据必须包含两侧比较值且没有缺失代码。

现有 `ALL`/`ANY` 三值规则不变，股票和指数子项按同一规则组合。条件位置通过现有策略优先级决定作用。计算器绝不在保存的树之外增加指数谓词。没有指数叶子的计划不产生指数条件证据，执行原有判断，并且不能因为快照为空、过期、有缺口或阻断而改变。

## 哈希与迁移规则

- `plan_sha256` 继续对规范计划 JSON 计算哈希。Schema v2 绑定和叶子自然参与；Schema v1 字节/黄金值不变。
- `IndexConditionEvidence` 只在存在时参与 `decision-result-v1`。v1 可空字段采用 null 时省略的序列化，因此历史 v1 结果哈希保持字节一致。
- Schema v2 回放的证据包含计划哈希以及快照/公式哈希；修改任一相关绑定、条件、截止、事实或指数 K 线都会改变判断/报告身份。
- 任何迁移都不能重写现有计划行、活动版本、结果行、导出或夹具。Schema v2 始终是新不可变计划版本。

## 测试策略

- 使用 RED/GREEN 边界测试覆盖六种叶子、两个等号方向以及全部最小/最大参数。
- Schema v1 中每种叶子都必须拒绝；Schema v2 必须要求并重新计算绑定。
- 证明叶子可以放在四个策略根，并保留准确嵌套路径。
- 证明过期、缺口、缺失、未来、身份不匹配或公式错误的快照返回路径局部 `MISSING_INPUT`。
- 证明两份计划读取同一快照可以得到不同条件结果和最终判断。
- 证明删除全部指数叶子会移除指数影响并保持无条件计划行为。
- 黄金测试保证 Schema v1 计划/结果哈希不变，Schema v2 证据字节确定。

## 边界与成功标准

- 始终：后端生成绑定，保留计划路径，并只使用共用已校验事实。
- 先确认：增加条件、role、范围、路径语法、Schema 版本或公式。
- 禁止：修改 v1、编造 AI 规则、让浏览器判断或增加隐藏全局门槛。
- 指数造成的每个判断影响都能追溯到一个已保存计划路径和准确快照/公式哈希。
