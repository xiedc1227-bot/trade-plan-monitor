"""Fail-closed optional AI connectivity and release-evidence contract.

The ordinary offline suite never constructs an HTTP client for this module. A
live probe additionally binds explicit authorization to the normalized endpoint,
model, and connection-test operation before the configured project key can be used.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.file_secrets import create_project_secret_store
from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderProfile,
    SecretReference,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.provider import AIProviderError, ProviderTestResult
from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.config import load_application_config

_ROOT = Path(__file__).parents[2]
_REPORTS = (
    _ROOT / "docs" / "verification" / "release-acceptance.md",
    _ROOT / "docs" / "verification" / "release-acceptance.zh-CN.md",
)
_READMES = (_ROOT / "README.md", _ROOT / "README.zh-CN.md")
_BASE_URL_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL"
_MODEL_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_MODEL"
_AUTHORIZATION_ENV = "TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256"
_PROJECT_CONFIG = _ROOT / "config" / "app.yaml"
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
    "ACCEPTED",
    "reminder-only",
    "local-only",
)
_REQUIRED_README_TOKENS = (
    "T059",
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
_REPORT_ACCEPTANCE_MARKERS = (
    (
        "**Status:** `ACCEPTED` on 2026-09-01.",
        "The release decision is `ACCEPTED`.",
        "## 9. C24 release checklist",
        "- [x] The user confirmed final acceptance on 2026-09-01.",
    ),
    (
        "**状态：**2026-09-01 为 `ACCEPTED`。",
        "发布决策为 `ACCEPTED`。",
        "## 9. C24 发布清单",
        "- [x] 用户已于 2026-09-01 确认最终验收。",
    ),
)
_README_ACCEPTANCE_TOKENS = (
    (
        "Tasks `T001` through `T059`",
        "T059 completed final user acceptance on 2026-09-01",
        "C24 is complete",
        "at 4 of 4",
        "`NOT_RUN_UNAUTHORIZED`",
    ),
    (
        "`T001`～`T059`",
        "T059 已于 2026-09-01 完成最终验收",
        "C24 已完成 4/4 项",
        "`NOT_RUN_UNAUTHORIZED`",
    ),
)


def _fail(code: str) -> None:
    pytest.fail(code, pytrace=False)


def _read_utf8_preserving_newlines(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        _fail("T059_RELEASE_DOCUMENT_UTF8_INVALID")


def _require_exact_live_selector(mark_expression: str) -> None:
    if mark_expression.strip() != "live":
        pytest.skip("live AI tests require the exact '-m live' selector")


def _candidate_config(base_url: str, model: str) -> AIProviderConfig:
    try:
        config = AIProviderConfig(
            provider_id=_PROVIDER_ID,
            display_name="T059 authorized DeepSeek target",
            base_url=base_url,
            model=model,
            secret_ref=SecretReference(
                key="ai/provider/configured-default",
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
    secret_store_factory: Callable[[], InMemorySecretStore] | None = None,
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

    if secret_store_factory is None:
        _fail("T059_AI_LIVE_SECRET_REFERENCE_UNAVAILABLE")
    secret_store = secret_store_factory()
    if not secret_store.status(config.secret_ref).configured:
        _fail("T059_AI_LIVE_SECRET_REFERENCE_UNAVAILABLE")
    return config, secret_store


def _canonical_evidence(report: str) -> tuple[str, dict[str, Any]]:
    match = _CANONICAL_EVIDENCE_PATTERN.search(report)
    if match is None:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_MISSING")
    payload_text = match.group("payload")
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")
    if not isinstance(payload, dict):
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")
    return payload_text, payload


def _require_final_acceptance_state(
    reports: tuple[str, str],
    readmes: tuple[str, str],
) -> None:
    for report, markers in zip(reports, _REPORT_ACCEPTANCE_MARKERS, strict=True):
        status_marker, decision_marker, checklist_heading, acceptance_item = markers
        if status_marker not in report or decision_marker not in report:
            _fail("T059_RELEASE_ACCEPTANCE_STATE_INVALID")
        _, heading_separator, checklist_tail = report.partition(checklist_heading)
        checklist, evidence_separator, _ = checklist_tail.partition(
            "<!-- T059-CANONICAL-EVIDENCE-START -->"
        )
        checklist_items = [line for line in checklist.splitlines() if line.startswith("- [")]
        if (
            not heading_separator
            or not evidence_separator
            or len(checklist_items) != 4
            or any(not item.startswith("- [x] ") for item in checklist_items)
            or acceptance_item not in checklist_items
        ):
            _fail("T059_RELEASE_ACCEPTANCE_STATE_INVALID")

    for readme, tokens in zip(readmes, _README_ACCEPTANCE_TOKENS, strict=True):
        if any(token not in readme for token in tokens):
            _fail("T059_RELEASE_ACCEPTANCE_STATE_INVALID")


@pytest.fixture(scope="session")
def authorized_ai_live_target(
    request: pytest.FixtureRequest,
) -> tuple[AIProviderConfig, InMemorySecretStore]:
    mark_expression = str(request.config.getoption("markexpr"))

    def project_secret_store() -> InMemorySecretStore:
        try:
            settings = load_application_config(_PROJECT_CONFIG).ai
            return create_project_secret_store(
                config_path=_PROJECT_CONFIG,
                settings=settings,
            )
        except OSError, ValidationError:
            _fail("T059_AI_LIVE_PROJECT_CONFIGURATION_UNAVAILABLE")

    return _authorized_live_target(mark_expression, os.environ, project_secret_store)


def test_ai_live_authorization_is_selector_first_and_target_bound() -> None:
    with pytest.raises(pytest.skip.Exception):
        _authorized_live_target("", {})
    with pytest.raises(pytest.fail.Exception):
        _candidate_config("http://127.0.0.1:18080/v1", "model-a")

    with pytest.raises(
        pytest.fail.Exception,
        match="T059_AI_LIVE_TARGET_AUTHORIZATION_UNAVAILABLE",
    ):
        secret_factory_called = False

        def forbidden_secret_factory() -> InMemorySecretStore:
            nonlocal secret_factory_called
            secret_factory_called = True
            return InMemorySecretStore(environment={})

        _authorized_live_target(
            "live",
            {
                _BASE_URL_ENV: "https://ai.example.test/v1",
                _MODEL_ENV: "model-a",
                _AUTHORIZATION_ENV: "é" * 64,
            },
            forbidden_secret_factory,
        )
    assert secret_factory_called is False

    first = _candidate_config("https://ai.example.test/v1", "model-a")
    changed_model = first.model_copy(update={"model": "model-b"})
    changed_endpoint = first.model_copy(update={"base_url": "https://other.example.test/v1"})
    assert _authorization_digest(first) != _authorization_digest(changed_model)
    assert _authorization_digest(first) != _authorization_digest(changed_endpoint)

    project_store = InMemorySecretStore(environment={})
    project_store.replace(first.secret_ref, SecretWrite(value="project-file-test-key"))
    authorized_config, authorized_store = _authorized_live_target(
        "live",
        {
            _BASE_URL_ENV: "https://ai.example.test/v1",
            _MODEL_ENV: "model-a",
            _AUTHORIZATION_ENV: _authorization_digest(first),
        },
        lambda: project_store,
    )
    assert authorized_config.model == "model-a"
    assert authorized_store is project_store


def test_final_acceptance_state_guard_rejects_document_regressions() -> None:
    reports = tuple(_read_utf8_preserving_newlines(path) for path in _REPORTS)
    readmes = tuple(_read_utf8_preserving_newlines(path) for path in _READMES)

    with pytest.raises(pytest.fail.Exception, match="T059_RELEASE_ACCEPTANCE_STATE_INVALID"):
        _require_final_acceptance_state(
            (
                reports[0].replace(
                    "**Status:** `ACCEPTED` on 2026-09-01.",
                    "**Status:** `PENDING FINAL USER ACCEPTANCE` on 2026-09-01.",
                    1,
                ),
                reports[1],
            ),
            readmes,
        )
    with pytest.raises(pytest.fail.Exception, match="T059_RELEASE_ACCEPTANCE_STATE_INVALID"):
        _require_final_acceptance_state(
            (
                reports[0],
                reports[1].replace(
                    "- [x] 用户已于 2026-09-01 确认最终验收。",
                    "- [ ] 用户尚未确认最终验收。",
                    1,
                ),
            ),
            readmes,
        )
    with pytest.raises(pytest.fail.Exception, match="T059_RELEASE_ACCEPTANCE_STATE_INVALID"):
        _require_final_acceptance_state(
            reports,
            (
                readmes[0].replace(
                    "T059 completed final user acceptance on 2026-09-01",
                    "T059 is pending final user acceptance",
                    1,
                ),
                readmes[1],
            ),
        )


def test_release_acceptance_reports_and_operator_guidance_are_complete() -> None:
    for path in _REPORTS:
        if not path.is_file():
            _fail("T059_RELEASE_REPORT_MISSING")

    english_report = _read_utf8_preserving_newlines(_REPORTS[0])
    chinese_report = _read_utf8_preserving_newlines(_REPORTS[1])
    readmes = tuple(_read_utf8_preserving_newlines(path) for path in _READMES)
    _require_final_acceptance_state((english_report, chinese_report), readmes)
    for token in _REQUIRED_REPORT_TOKENS:
        if token not in english_report or token not in chinese_report:
            _fail("T059_RELEASE_REPORT_PARITY_MISSING")
    for report in (english_report, chinese_report):
        if any(pattern.search(report) for pattern in _REPORT_SECRET_PATTERNS):
            _fail("T059_RELEASE_REPORT_SECRET_MATERIAL_DETECTED")

    english_evidence_text, english_evidence = _canonical_evidence(english_report)
    chinese_evidence_text, chinese_evidence = _canonical_evidence(chinese_report)
    if english_evidence_text != chinese_evidence_text or english_evidence != chinese_evidence:
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_MISMATCH")
    if (
        english_evidence.get("baseline") != _BASELINE
        or english_evidence.get("backtestAcceptanceCommit") != _BACKTEST_ACCEPTANCE_COMMIT
        or english_evidence.get("timezone") != "Asia/Shanghai"
        or english_evidence.get("aiLive") != "NOT_RUN_UNAUTHORIZED"
        or english_evidence.get("releaseDecision") != "ACCEPTED"
    ):
        _fail("T059_RELEASE_CANONICAL_EVIDENCE_INVALID")

    for readme in readmes:
        for token in _REQUIRED_README_TOKENS:
            if token not in readme:
                _fail("T059_RELEASE_README_GUIDANCE_MISSING")
        if any(pattern.search(readme) for pattern in _README_SECRET_PATTERNS):
            _fail("T059_RELEASE_README_SECRET_MATERIAL_DETECTED")


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
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=secret_store,
                profile=AIProviderProfile.DEEPSEEK,
            )
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
