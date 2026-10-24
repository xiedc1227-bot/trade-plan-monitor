"""Expanded source-review obligations for the fixed linkage policy version."""


EXPANDED_LINKAGE_POLICY = {
    'market_broken': (
        'I < L20 AND I < M60; L20 = prior 20 sess'
        'ion lows excluding D'
    ),
    'market_weak': (
        'BROKEN false AND I < M20 AND M20 < M20_5'
        '; M20_5 = MA20 five sessions earlier'
    ),
    'market_other': (
        'NORMAL_TRANSITION only when higher state'
        's false; missing necessary inputs UNKNOW'
        'N'
    ),
    'strength': (
        'stock return5 > index return5 AND stock '
        'return20 > index return20 AND close >= M'
        'A20'
    ),
    's1': (
        'S0 AND adjacent two closes in low-buy zo'
        'ne AND close >= previous close AND volum'
        'e <= prior20 mean AND RSI14 > previous R'
        'SI14 AND no higher risk'
    ),
    's2': (
        'S1 AND both closes >= their own day MA20'
    ),
    'routes': (
        'NORMAL_TRANSITION S0 Q0; WEAK S1 floor(0'
        '.5*Q0); exceptions require STRONG and re'
        'main BLOCK_P1'
    ),
    'unknown': (
        'missing necessary inputs pause buying; s'
        'trength is unnecessary for ordinary NORM'
        'AL_TRANSITION or WEAK'
    ),
}

EXPANDED_LINKAGE_POLICY_ZH = {
    'market_broken': (
        '明显破位：I < L20 且 I < M60；L20 为不含 D 的此前 20 '
        '个交易日最低价'
    ),
    'market_weak': (
        '偏弱：明显破位为假，且 I < M20，且 M20 < M20_5；M20_5 '
        '为 5 个交易日前的 MA20'
    ),
    'market_other': (
        '正常或过渡：更高优先级状态均为假；必要输入缺失时为未知'
    ),
    'strength': (
        '相对强势：个股 5 日收益率 > 指数 5 日收益率，且个股 20 日收益率 >'
        ' 指数 20 日收益率，且收盘价 >= MA20'
    ),
    's1': (
        'S1：S0 且相邻两个交易日收盘价均在低吸区，且当日收盘价 >= 前日收盘价，且'
        '当日成交量 <= 此前 20 日均量，且 RSI14 > 前日 RSI14，且无'
        '更高优先级风险'
    ),
    's2': (
        'S2：S1 且两个收盘价分别 >= 各自当日 MA20'
    ),
    'routes': (
        '正常或过渡使用 S0 和 Q0；偏弱使用 S1 和按合法单位向下取整的 0.5*'
        'Q0；例外要求相对强势且保持阻断，等待 P1'
    ),
    'unknown': (
        '必要输入缺失时暂停买入；正常或过渡以及偏弱普通路径不依赖相对强势'
    ),
}
