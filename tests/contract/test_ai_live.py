"""Fail-closed optional AI connectivity and release-evidence contract.

The ordinary offline suite never constructs an HTTP client for this module. A
live probe additionally binds explicit authorization to the normalized endpoint,
model, and connection-test operation before the API key can be materialized.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.models import AIProviderConfig, SecretReference
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.provider import AIProviderError, ProviderTestResult
from trade_plan_monitor.ai.secrets import InMemorySecretStore

_ROOT = Path(__file__).parents[2]
_REPORTS = (
    _ROOT / "docs" / "verification" / "release-acceptance.md",
    _ROOT / "docs" / "verification" / "release-acceptance.zh-CN.md",
)
_READMES = (_ROOT / "README.md", _ROOT / "README.zh-CN.md")
_BASE_URL_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL"
_MODEL_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_MODEL"
_AUTHORIZATION_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256"
_SECRET_ENV = "AI_API_KEY"
_LIVE_SELECTOR = "python -m pytest tests/contract/test_ai_live.py -q -m live"
_AUTHORIZATION_CONTEXT = "trade-plan-monitor:t059:ai-live:test-connection:v1"
_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000059")
_BASELINE = "d8b28b20e59b91b261ce46003effdb01288d832a"
_BACKTEST_ACCEPTANCE_COMMIT = "eee65fd9ede37cee229c0147ba2ddb55a5f311d5"
_REQUIRED_REPORT_TOKENS = (
    "T059",
    "P18",
    "BT008",
    "BC01",
    "C24",
    "Asia/Shanghai",
    "+08:00",
    "Chromium-only",
    "AI_API_KEY",
    _BASE_URL_ENV,
    _MODEL_ENV,
    _AUTHORIZATION_ENV,
    _LIVE_SELECTOR,
    "NOT_RUN_UNAUTHORIZED",
    "PENDING_FINAL_USER_ACCEPTANCE",
    "reminder-only",
    "local-only",
)
_REQUIRED_README_TOKENS = (
    "T059",
    "AI_API_KEY",
    _BASE_URL_ENV,
    _MODEL_ENV,
    _AUTHORIZATION_ENV,
    _LIVE_SELECTOR,
    _AUTHORIZATION_CONTEXT,
)
_REPORT_SECRET_PATTERNS = (
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"AI_API_KEY\s*(?:=|:)\s*[^`\s$]+", re.IGNORECASE),
)
_README_SECRET_PATTERNS = _REPORT_SECRET_PATTERNS[:2]
_CANONICAL_EVIDENCE_PATTERN = re.compile(
    r"<!-- T059-CANONICAL-EVIDENCE-START -->\s*"
    r"```json\s*(?P<payload>\{.*?\})\s*```\s*"
    r"<!-- T059-CANONICAL-EVIDENCE-END -->",
    re.DOTALL,
)


def _fail(code: str) -> None:
    pytest.fail(code, pytrace=False)


def _require_exact_live_selector(mark_expression: str) -> None:
    if mark_expression.strip() != "live":
        pytest.skip("live AI tests require the exact '-m live' selector")


def _candidate_config(base_url: str, model: str) -> AIProviderConfig:
    try:
        config = AIProviderConfig(
            provider_id=_PROVIDER_ID,
            display_name="T059 authorized live target",
            base_url=base_url,
            model=model,
            secret_ref=SecretReference(
                key="ai/provider/t059-live",
                environment_variable=_SECRET_ENV,
            ),
            timeout_seconds=10,
            max_retries=0,
            max_input_chars=1_000,
            max_output_tokens=1,
            temperature=0,
            allow_redirects=False,
            enabled=True,
        )
    except ValidationError:
        _fail("T059_AI_LIVE_CONFIGURATION_INVALID")
    if config.base_url.scheme != "https":
        _fail("T059_AI_LIVE_HTTPS_REQUIRED")
    return config


def _authorization_target(config: AIProviderConfig) -> str:
    normalized_base_url = str(config.base_url).rstrip("/")
    return f"{_AUTHORIZATION_CONTEXT}\n{normalized_base_url}\n{config.model}\n"


def _authorization_digest(config: AIProviderConfig) -> str:
    return hashlib.sha256(_authorization_target(config).encode("utf-8")).hexdigest()


def _authorized_live_target(
    mark_expression: str,
    environment: Mapping[str, str],
) -> tuple[AIProviderConfig, InMemorySecretStore]:
    _require_exact_live_selector(mark_expression)
    base_url = environment.get(_BASE_URL_ENV)
    model = environment.get(_MODEL_ENV)
    if not base_url or not model:
        _fail("T059_AI_LIVE_TARGET_CONFIGURATION_UNAVAILABLE")
    config = _candidate_config(base_url, model)

    supplied_authorization = environment.get(_AUTHORIZATION_ENV, "").strip().casefold()
    expected_authorization = _authorization_digest(config)
    if re.fullmatch(r"[0-9a-f]{64}", supplied_authorization) is None or not hmac.compare_digest(
        supplied_authorization,
        expected_authorization,
    ):
        _fail("T059_AI_LIVE_TARGET_AUTHORIZATION_UNAVAILABLE")

    secret_store = InMemorySecretStore(environment=environment)
    if not secret_store.status(config.secret_ref).configured:
        _fail("T059_AI_LIVE_SECRET_REFERENCE_UNAVAILABLE")
    return config, secret_store


def _canonical_evidence(report: str) -> dict[str, Any]:
    match = _CANONICAL_EVIDENCE_PATTERN.search(report)
    if match is None:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_MISSING")
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")
    if not isinstance(payload, dict):
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")
    return payload


@pytest.fixture(scope="session")
def authorized_ai_live_target(
    request: pytest.FixtureRequest,
) -> tuple[AIProviderConfig, InMemorySecretStore]:
    mark_expression = str(request.config.getoption("markexpr"))
    return _authorized_live_target(mark_expression, os.environ)


def test_ai_live_authorization_is_selector_first_and_target_bound() -> None:
    with pytest.raises(pytest.skip.Exception):
        _authorized_live_target("", {})
    with pytest.raises(pytest.fail.Exception):
        _candidate_config("http://127.0.0.1:18080/v1", "model-a")

    with pytest.raises(
        pytest.fail.Exception,
        match="T059_AI_LIVE_TARGET_AUTHORIZATION_UNAVAILABLE",
    ):
        _authorized_live_target(
            "live",
            {
                _BASE_URL_ENV: "https://ai.example.test/v1",
                _MODEL_ENV: "model-a",
                _AUTHORIZATION_ENV: "é" * 64,
            },
        )

    first = _candidate_config("https://ai.example.test/v1", "model-a")
    changed_model = first.model_copy(update={"model": "model-b"})
    changed_endpoint = first.model_copy(update={"base_url": "https://other.example.test/v1"})
    assert _authorization_digest(first) != _authorization_digest(changed_model)
    assert _authorization_digest(first) != _authorization_digest(changed_endpoint)


def test_release_acceptance_reports_and_operator_guidance_are_complete() -> None:
    for path in _REPORTS:
        if not path.is_file():
            _fail("T059_RELEASE_REPORT_MISSING")

    english_report = _REPORTS[0].read_text(encoding="utf-8")
    chinese_report = _REPORTS[1].read_text(encoding="utf-8")
    for token in _REQUIRED_REPORT_TOKENS:
        if token not in english_report or token not in chinese_report:
            _fail("T059_RELEASE_REPORT_PARITY_MISSING")
    for report in (english_report, chinese_report):
        if any(pattern.search(report) for pattern in _REPORT_SECRET_PATTERNS):
            _fail("T059_RELEASE_REPORT_SECRET_MATERIAL_DETECTED")

    english_evidence = _canonical_evidence(english_report)
    chinese_evidence = _canonical_evidence(chinese_report)
    if english_evidence != chinese_evidence:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_MISMATCH")
    if (
        english_evidence.get("baseline") != _BASELINE
        or english_evidence.get("backtestAcceptanceCommit") != _BACKTEST_ACCEPTANCE_COMMIT
        or english_evidence.get("timezone") != "Asia/Shanghai"
        or english_evidence.get("aiLive") != "NOT_RUN_UNAUTHORIZED"
        or english_evidence.get("releaseDecision") != "PENDING_FINAL_USER_ACCEPTANCE"
    ):
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")

    configured_secret = os.environ.get(_SECRET_ENV)
    if configured_secret and (
        configured_secret in english_report or configured_secret in chinese_report
    ):
        _fail("T059_RELEASE_CONFIGURED_SECRET_DETECTED")

    for path in _READMES:
        readme = path.read_text(encoding="utf-8")
        for token in _REQUIRED_README_TOKENS:
            if token not in readme:
                _fail("T059_RELEASE_README_GUIDANCE_MISSING")
        if any(pattern.search(readme) for pattern in _README_SECRET_PATTERNS):
            _fail("T059_RELEASE_README_SECRET_MATERIAL_DETECTED")
        if configured_secret and configured_secret in readme:
            _fail("T059_RELEASE_README_CONFIGURED_SECRET_DETECTED")


@pytest.mark.live
def test_authorized_openai_compatible_connection(
    authorized_ai_live_target: tuple[AIProviderConfig, InMemorySecretStore],
) -> None:
    config, secret_store = authorized_ai_live_target

    async def scenario() -> ProviderTestResult:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(config.timeout_seconds),
            trust_env=False,
        ) as client:
            provider = OpenAICompatibleProvider(client=client, secret_store=secret_store)
            return await provider.test_connection(config)

    try:
        result = asyncio.run(scenario())
    except AIProviderError as error:
        _fail(f"T059_AI_LIVE_{error.code.value}_ATTEMPTS_{error.attempts}")
    except Exception:
        _fail("T059_AI_LIVE_UNEXPECTED_FAILURE")

    if not result.connected or result.provider_id != config.provider_id or result.attempts != 1:
        _fail("T059_AI_LIVE_CONNECTION_RECEIPT_MISMATCH")
    if set(result.model_dump(mode="json")) != {
        "attempts",
        "connected",
        "model",
        "provider_id",
    }:
        _fail("T059_AI_LIVE_CONNECTION_RECEIPT_UNSAFE")
