"""Closed whole-source position sentences, with separate cap and retention spans."""

import re
from dataclasses import dataclass

_DIRECTIVE = re.compile(
    r"(?P<cap>(?:调整最大仓位为|仅修改最大仓位(?:为)?)"
    r"(?P<quantity>0|[1-9][0-9]{0,15})股，)(?P<tail>其余规则(?:保留|不变)。)"
)
_MAX_EXACT_INTEGER = 9_007_199_254_740_991


@dataclass(frozen=True, slots=True)
class PositionDirective:
    start: int
    cap_end: int
    end: int
    value: int

    @property
    def tail_start(self):
        return self.cap_end


def parse_position_directive(source):
    """Accept one complete registered sentence; never search a conditional prefix.

    Quantity is an exact safe integer. Native position validation independently
    decides whether that value is executable; recognition is not permission.
    """
    if not isinstance(source, str) or len(source) > 150_000:
        return None
    start, end = len(source) - len(source.lstrip()), len(source.rstrip())
    match = _DIRECTIVE.fullmatch(source[start:end])
    if match is None:
        return None
    value = int(match["quantity"])
    if value > _MAX_EXACT_INTEGER:
        return None
    return PositionDirective(start=start, cap_end=start + match.end("cap"), end=end, value=value)
