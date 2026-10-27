"""Static compatibility with the existing finite evaluator, without acquiring data."""

from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.market_data.daily_indicators import PARAMETERS


def unsupported_native_paths(payload):
    result = []

    def visit(value, path):
        if isinstance(value, dict):
            kind = value.get("type")
            if kind == "DAILY_INDICATOR_COMPARE" and value.get("parameters") != PARAMETERS.get(
                value.get("indicator")
            ):
                result.append(path + ".parameters")
            reference = value.get("reference")
            if isinstance(reference, dict):
                if (reference.get("mode") == "DYNAMIC"
                        and reference.get("parameters") != PARAMETERS.get(
                            reference.get("indicator"))):
                    result.append(path + ".reference.parameters")
                if (reference.get("mode") == "FIXED" and kind in {
                    "DAILY_PRICE_COMPARE", "DAILY_INDICATOR_COMPARE", "DAILY_CLOSE_SEQUENCE",
                } and reference.get("unit") != (
                    "INDICATOR" if kind == "DAILY_INDICATOR_COMPARE" else "FEN"
                )):
                    result.append(path + ".reference.unit")
                if (kind in {"DAILY_PRICE_COMPARE", "DAILY_CLOSE_SEQUENCE"}
                        and reference.get("mode") == "DYNAMIC"
                        and reference.get("indicator") in {"RSI14", "BOLL_BANDWIDTH"}):
                    result.append(path + ".reference.indicator")
            for key, child in value.items():
                visit(child, path + "." + key if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "")
    return tuple(dict.fromkeys(result))


def native_support_issues(payload, source, declarations):
    issues = []
    for path in unsupported_native_paths(payload):
        parent = path.rsplit(".", 1)[0]
        related = [row for row in declarations if row.path == path
                   or row.path.startswith(parent + ".") or path.startswith(row.path + ".")]
        exact = next((row for row in related if row.path == path), None)
        declaration = exact or (related[0] if related else None)
        start = 0 if declaration is None else declaration.start
        end = min(len(source), start + 512) if declaration is None else min(
            declaration.end, start + 512)
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_UNSUPPORTED", path=path,
            start=start, end=end,
            message="Indicator parameters or operand units are outside the registered evaluator."))
    return tuple(issues)
