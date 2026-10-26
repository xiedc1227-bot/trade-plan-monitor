"""Bounded YAML and canonical JSON codecs for executable trade plans."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Literal

import yaml
from pydantic import ValidationError

from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.plan_models import ExecutableTradePlan, ExplicitTradePlan, TradePlan

MAX_PLAN_DOCUMENT_BYTES = 256 * 1024
_MAX_PLAN_DOCUMENT_NODES = 10_000
PlanDocumentErrorCode = Literal[
    "DOCUMENT_TOO_LARGE",
    "DUPLICATE_KEY",
    "INVALID_ENCODING",
    "INVALID_SYNTAX",
    "INVALID_ROOT",
    "UNSUPPORTED_VALUE",
    "INVALID_PLAN",
    "UNSUPPORTED_EXECUTION_VERSION",
    "UNSUPPORTED_PLAN_VERSION",
]


class PlanDocumentError(ValueError):
    """One safe, machine-readable failure at the plan document boundary."""

    def __init__(self, code: PlanDocumentErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Retain SafeLoader's tag allowlist while rejecting ambiguous mappings."""

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[object, object]:
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                is_duplicate = key in mapping
            except TypeError as error:
                raise PlanDocumentError(
                    "UNSUPPORTED_VALUE",
                    "Plan document mapping keys must be scalar values.",
                ) from error
            if is_duplicate:
                raise PlanDocumentError(
                    "DUPLICATE_KEY",
                    "Plan document mapping keys must be unique.",
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _normalize_document(document: str | bytes) -> str:
    if isinstance(document, bytes):
        if len(document) > MAX_PLAN_DOCUMENT_BYTES:
            raise PlanDocumentError(
                "DOCUMENT_TOO_LARGE",
                "Plan document exceeds the encoded size limit.",
            )
        try:
            return document.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PlanDocumentError(
                "INVALID_ENCODING",
                "Plan document must be valid UTF-8.",
            ) from error

    if not isinstance(document, str):
        raise TypeError("document must be str or bytes")
    try:
        encoded_size = len(document.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise PlanDocumentError(
            "INVALID_ENCODING",
            "Plan document must be valid UTF-8.",
        ) from error
    if encoded_size > MAX_PLAN_DOCUMENT_BYTES:
        raise PlanDocumentError(
            "DOCUMENT_TOO_LARGE",
            "Plan document exceeds the encoded size limit.",
        )
    return document


def _reject_json_constant(value: str) -> None:
    raise PlanDocumentError(
        "UNSUPPORTED_VALUE",
        f"Non-finite JSON number {value} is not supported.",
    )


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise PlanDocumentError(
                "DUPLICATE_KEY",
                "Plan document mapping keys must be unique.",
            )
        mapping[key] = value
    return mapping


def _validate_data_tree(root: dict[object, object]) -> None:
    stack: list[object] = [root]
    seen_containers: set[int] = set()
    node_count = 0

    while stack:
        value = stack.pop()
        node_count += 1
        if node_count > _MAX_PLAN_DOCUMENT_NODES:
            raise PlanDocumentError(
                "UNSUPPORTED_VALUE",
                "Plan document contains too many values.",
            )

        if isinstance(value, float):
            if not math.isfinite(value):
                raise PlanDocumentError(
                    "UNSUPPORTED_VALUE",
                    "Plan document contains a non-finite number.",
                )
            continue
        if isinstance(value, (str, int, bool, date, datetime)) or value is None:
            continue
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen_containers:
                raise PlanDocumentError(
                    "UNSUPPORTED_VALUE",
                    "Plan document contains a repeated or recursive container.",
                )
            seen_containers.add(identity)
            if not all(isinstance(key, str) for key in value):
                raise PlanDocumentError(
                    "UNSUPPORTED_VALUE",
                    "Plan document mapping keys must be strings.",
                )
            stack.extend(value.values())
            continue
        if isinstance(value, list):
            identity = id(value)
            if identity in seen_containers:
                raise PlanDocumentError(
                    "UNSUPPORTED_VALUE",
                    "Plan document contains a repeated or recursive container.",
                )
            seen_containers.add(identity)
            stack.extend(value)
            continue
        raise PlanDocumentError(
            "UNSUPPORTED_VALUE",
            f"Plan document contains unsupported value type {type(value).__name__}.",
        )


def _validate_plan_data(raw_plan: object) -> ExecutableTradePlan:
    if not isinstance(raw_plan, dict):
        raise PlanDocumentError(
            "INVALID_ROOT",
            "Plan document root must be a mapping.",
        )
    _validate_data_tree(raw_plan)
    schema_version = raw_plan.get("schema_version", 1)
    if type(schema_version) is not int or schema_version not in {1, 2, 3, 4, 5, 6, 7, 8}:
        raise PlanDocumentError(
            "UNSUPPORTED_PLAN_VERSION",
            "Plan document uses an unsupported schema version.",
        )
    if schema_version == 3 and raw_plan.get("execution_version") != "explicit-rules-v1":
        raise PlanDocumentError(
            "UNSUPPORTED_EXECUTION_VERSION",
            "Plan document uses an unsupported execution version.",
        )
    try:
        if schema_version == 8:
            from trade_plan_monitor.domain.p2_policy_models import P2TradePlan
            return P2TradePlan.model_validate(raw_plan)
        if schema_version == 7:
            from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
            return MarketExceptionTradePlan.model_validate(raw_plan)
        if schema_version == 6:
            from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
            return MarketLinkedTradePlan.model_validate(raw_plan)
        if schema_version == 5:
            from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
            return UnifiedTradePlan.model_validate(raw_plan)
        if schema_version == 4:
            if raw_plan.get("execution_version") != "daily-close-v1":
                raise PlanDocumentError(
                    "UNSUPPORTED_EXECUTION_VERSION", "Unsupported daily execution version."
                )
            return DailyTradePlan.model_validate(raw_plan)
        if schema_version == 3:
            return ExplicitTradePlan.model_validate(raw_plan)
        return TradePlan.model_validate(raw_plan)
    except (ValidationError, RecursionError) as error:
        raise PlanDocumentError(
            "INVALID_PLAN",
            "Plan document does not match the executable plan schema.",
        ) from error


def load_plan_json(document: str | bytes) -> ExecutableTradePlan:
    """Parse one bounded JSON object and validate the complete plan schema."""

    normalized = _normalize_document(document)
    try:
        raw_plan = json.loads(
            normalized,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except PlanDocumentError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise PlanDocumentError(
            "INVALID_SYNTAX",
            "Plan document is not valid JSON.",
        ) from error
    return _validate_plan_data(raw_plan)


def load_plan_yaml(document: str | bytes) -> ExecutableTradePlan:
    """Safely parse one bounded YAML object and validate the complete plan schema."""

    normalized = _normalize_document(document)
    loader = _UniqueKeySafeLoader(normalized)
    try:
        raw_plan = loader.get_single_data()
    except PlanDocumentError:
        raise
    except (yaml.YAMLError, RecursionError, ValueError) as error:
        raise PlanDocumentError(
            "INVALID_SYNTAX",
            "Plan document is not valid safe YAML.",
        ) from error
    finally:
        loader.dispose()
    return _validate_plan_data(raw_plan)


def _plan_json_data(plan: ExecutableTradePlan) -> dict[str, object]:
    if not isinstance(plan, TradePlan | ExplicitTradePlan | DailyTradePlan):
        raise TypeError("plan must be an executable trade plan")
    data = plan.model_dump(mode="json")
    if plan.schema_version == 1:
        data.pop("reference_market", None)
    return data


def dump_plan_json(plan: ExecutableTradePlan) -> str:
    """Return compact canonical JSON with recursively sorted object keys."""

    return json.dumps(
        _plan_json_data(plan),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def dump_plan_yaml(plan: ExecutableTradePlan) -> str:
    """Return portable Unicode YAML containing standard tags only."""

    return yaml.safe_dump(
        _plan_json_data(plan),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


__all__ = [
    "MAX_PLAN_DOCUMENT_BYTES",
    "PlanDocumentError",
    "PlanDocumentErrorCode",
    "dump_plan_json",
    "dump_plan_yaml",
    "load_plan_json",
    "load_plan_yaml",
]
