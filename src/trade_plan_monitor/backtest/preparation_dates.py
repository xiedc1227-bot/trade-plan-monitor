"""Conservative applicability-date extraction from plan text, never file metadata."""

import re
from datetime import date

_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>\d{4})\s*[-/年]\s*)?"
    r"(?P<month>\d{1,2})\s*[-/月]\s*(?P<day>\d{1,2})(?:日)?(?!\d)"
)
_LABEL = re.compile(
    r"(?:生效(?:交易)?日(?:期)?|计划适用日期|适用交易日|执行日期|"
    r"effective\s+(?:trade\s+)?date)\s*(?:为|是|[:：])", re.IGNORECASE,
)
_PLAN = re.compile(r"交易计划|操作计划|执行计划|trading\s+plan", re.IGNORECASE)


def infer_effective_trade_date(text: str) -> date | None:
    """Return one supported calendar day; uncertainty stays explicit for human review.

    Explicit applicability labels take precedence over narrative dates. Otherwise,
    accept dated plan headings or a date-led instruction, never a conditional
    event's date, a retrospective observation, or a relative trading-day guess.
    """
    years = set(re.findall(r"(?<!\d)(\d{4})\s*(?=[年/-])", text))
    segments = re.split(r"[\n。；;]", text)
    selected = []
    if _LABEL.search(text):
        for segment in segments:
            label = _LABEL.search(segment)
            if label:
                selected.append(segment[label.end():])
    else:
        for segment in segments:
            clean = segment.strip().lstrip("#>*- ")
            matches = list(_DATE.finditer(clean))
            if not matches:
                continue
            match = matches[0]
            prefix = clean[:match.start()].strip()
            suffix = clean[match.end():].lstrip("* ：:，,")
            # Headings and direct date-led instructions only. A dated condition
            # inside a rule must not activate the whole plan on that event day.
            heading = (
                len(clean) <= 100 and _PLAN.search(clean)
                and (not prefix or _PLAN.search(prefix))
                and not re.search(
                    r"[，,：:]|如果|若|复盘|回顾|示例|参考|例如|历史|条件|收盘", clean,
                )
            )
            instruction = not prefix and re.match(r"(?:若|执行|开始执行|起执行|起生效)", suffix)
            if heading or instruction:
                selected.append(clean)
    if not selected:
        return None
    candidates = set()
    for segment in selected:
        matches = list(_DATE.finditer(segment))
        if not matches or re.search(r"待定|明天|明日|下一交易日|次日|或|至|到", segment):
            return None
        for match in matches:
            year = match['year'] or (next(iter(years)) if len(years) == 1 else None)
            if year is None:
                return None
            try:
                candidates.add(date(int(year), int(match['month']), int(match['day'])))
            except ValueError:
                return None
    return next(iter(candidates)) if len(candidates) == 1 else None
