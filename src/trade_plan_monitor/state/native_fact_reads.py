"""Indexed native TRADE_DATE candidates, without condition or execution authority."""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateIndex

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import ReviewedDailyFact
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import (
    ReviewedFactTarget,
    assess_unbound_fact,
    matches_reviewed_fact_condition,
    resolve_reviewed_fact_target,
)
from trade_plan_monitor.state.daily_models import (
    NATIVE_FACT_AVAILABLE_SQL,
    NATIVE_FACT_GROUP_SQL,
    NATIVE_FACT_INDEX_NAME,
    NATIVE_FACT_ORDER_SQL,
    DailyRecord,
)
from trade_plan_monitor.state.daily_state_models import DailyFactState, ReviewedFactObservation
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError

# Existing evidence output (dashboard/backtest) and readiness output budgets.
# Exceeding either means unknown, never a truncated complete candidate set.
_MAX_FACT_ROWS = 512
_MAX_FACT_BYTES = 1024 * 1024
_RAW_AVAILABLE = NATIVE_FACT_ORDER_SQL[1].removesuffix(" DESC")
_RAW_VERIFIED = NATIVE_FACT_ORDER_SQL[2].removesuffix(" DESC")


def _where(values, *, time_key=None, raw_times=None):
    terms, params = ["kind = 'FACT'"], {}
    for index, (expression, value) in enumerate(zip(NATIVE_FACT_GROUP_SQL, values, strict=False)):
        terms.append(f"({expression}) IS NULL" if value is None else f"({expression})=:g{index}")
        if value is not None:
            params[f"g{index}"] = value
    if time_key is not None:
        terms.append(f"({NATIVE_FACT_AVAILABLE_SQL})=:time_key")
        params["time_key"] = time_key
    if raw_times is not None:
        terms += [f"({_RAW_AVAILABLE})=:available", f"({_RAW_VERIFIED})=:verified"]
        params.update(available=raw_times[0], verified=raw_times[1])
    return " AND ".join(terms), params


def _select(session, columns, where, params, suffix=""):
    return session.execute(
        text(
            f"SELECT {columns} FROM daily_plan_record "
            f"INDEXED BY {NATIVE_FACT_INDEX_NAME} WHERE {where} {suffix}"
        ),
        params,
    )


def _probe(session, values, *, missing_time=False):
    where, params = _where(values)
    if missing_time:
        where += f" AND ({NATIVE_FACT_AVAILABLE_SQL}) IS NULL"
    return _select(session, "1", where, params, "LIMIT 1").first() is not None


def _index_matches(session):
    actual = session.scalar(
        text(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND tbl_name='daily_plan_record' AND name=:name"
        ),
        {"name": NATIVE_FACT_INDEX_NAME},
    )
    if actual is None:
        return False
    index = next(
        value for value in DailyRecord.__table__.indexes if value.name == NATIVE_FACT_INDEX_NAME
    )
    expected = str(CreateIndex(index).compile(dialect=session.bind.dialect))
    return re.sub(r"\s+", " ", actual).strip() == re.sub(r"\s+", " ", expected).strip()


def _candidate(reads, identity, *, plan, target, condition, day, now, observation):
    row = reads.daily(identity)
    if row is None or row["kind"] != "FACT" or row["symbol"] != plan.symbol:
        return None
    fact = DailyFactState.model_validate_json(canonical(row["payload"]))
    if (
        fact.trade_date != day
        or fact.available_at > now
        or fact.verified_at > now
        or not matches_reviewed_fact_condition(
            plan,
            row["payload"],
            condition,
            plan_version_id=target.plan_version_id,
            owner_kind=target.owner_kind,
            owner_id=target.owner_id,
            condition_path=target.condition_path,
        )
    ):
        return None
    if fact.reviewed_fact_target is not None and fact.reviewed_fact_observation != observation:
        return None
    return row


def _read(work, target, day, now, observation):
    reads = ActionOwnerReader(work)
    if not _index_matches(reads.session):
        return None
    details = reads.details(target.plan_version_id)
    plan = load_plan_json(details.payload_json)
    ref = resolve_reviewed_fact_target(plan, target, plan_version_id=details.id)
    condition = ReviewedDailyFact.model_validate_json(ref.definition_json)
    if condition.validity_scope != "TRADE_DATE" or day > now.date():
        return None
    # Pending FACTs may not be used or overwritten by a populate-existing read.
    reads._reject_pending(DailyRecord, symbol=plan.symbol, kind="FACT")
    if _probe(reads.session, (plan.symbol, None)):
        return None  # Malformed JSON/missing native owner cannot be assigned a safe group.
    base = (plan.symbol, details.id, target.content_hash, condition.fact_kind, str(day), "true")
    if _probe(reads.session, (*base, None)):
        return None  # An unsupported target shape must not masquerade as legacy-unbound.
    ordinary = next((rule for rule in plan.ordinary_rules if rule.rule_id == target.owner_id), None)
    if (
        plan.schema_version == 5
        and target.owner_kind == "ORDINARY_RULE"
        and ordinary is not None
        and ordinary.confirmation.kind == "COMPLETED_BAR_CLOSE"
        and observation is None
    ):
        return None
    stamp = "" if observation is None else observation.bar_end.isoformat(timespec="microseconds")
    source = "" if observation is None else observation.source_hash
    groups = [(*base, target.target_hash, stamp, source)]
    # Test both signal-presence shapes before admitting the whole legacy group.
    # Mixed TRADE_DATE/SIGNAL applicability has no seek here and remains unknown.
    decisions = [
        assess_unbound_fact(
            plan,
            dict(
                plan_version_id=details.id,
                content_hash=target.content_hash,
                kind=condition.fact_kind,
                trade_date=str(day),
                verified=True,
                satisfied=True,
                signal_id=signal,
            ),
        )
        for signal in (None, "present")
    ]
    applicable = [
        decision.usable
        and decision.definition_json == ref.definition_json
        and any(
            (item.owner_kind, item.owner_id, item.condition_path)
            == (target.owner_kind, target.owner_id, target.condition_path)
            for item in decision.definitions
        )
        for decision in decisions
    ]
    if applicable[0] != applicable[1]:
        return None
    if applicable[0]:
        groups.append((*base, "", "", ""))
    heads = []
    cached, size = {}, 0
    options = dict(
        plan=plan, target=target, condition=condition, day=day, now=now, observation=observation
    )
    for group in groups:
        if _probe(reads.session, (*group[:7], None)) or _probe(
            reads.session, group, missing_time=True
        ):
            return None
        where, params = _where(group)
        where += f" AND ({NATIVE_FACT_AVAILABLE_SQL})<=:now_key"
        params["now_key"] = now.isoformat(timespec="microseconds")
        head = (
            _select(
                reads.session,
                f"id, ({NATIVE_FACT_AVAILABLE_SQL}) AS time_key, ({_RAW_AVAILABLE}) AS available, "
                f"({_RAW_VERIFIED}) AS verified, length(CAST(payload_json AS BLOB)) AS bytes",
                where,
                params,
                "ORDER BY " + ", ".join(NATIVE_FACT_ORDER_SQL) + " LIMIT 1",
            )
            .mappings()
            .first()
        )
        if head is not None:
            size += head.bytes
            if size > _MAX_FACT_BYTES:
                return None
            candidate = _candidate(reads, head.id, **options)
            if candidate is None:
                return None  # Never scan backward past an invalid or unproven candidate.
            cached[head.id] = candidate
            heads.append((group, head))
    if not heads:
        return ()
    latest = max((head.available, head.verified) for _, head in heads)
    selected = []
    for group, head in heads:
        if (head.available, head.verified) != latest:
            continue
        where, params = _where(group, time_key=head.time_key, raw_times=latest)
        ties = (
            _select(
                reads.session,
                "id, length(CAST(payload_json AS BLOB)) AS bytes",
                where,
                params,
                f"ORDER BY id LIMIT {_MAX_FACT_ROWS + 1}",
            )
            .mappings()
            .all()
        )
        if len(selected) + len(ties) > _MAX_FACT_ROWS:
            return None
        for tie in ties:
            size += 0 if tie.id in cached else tie.bytes
            if size > _MAX_FACT_BYTES:
                return None
            row = cached.get(tie.id) or _candidate(reads, tie.id, **options)
            if row is None:
                return None
            selected.append(row)
    if len(canonical(selected).encode("utf-8")) > _MAX_FACT_BYTES:
        return None
    return tuple(sorted(selected, key=lambda row: row["id"]))


def read_native_trade_date_fact_candidates(
    work,
    *,
    target: ReviewedFactTarget,
    trade_date: date,
    now: datetime,
    observation: ReviewedFactObservation | None = None,
) -> tuple[dict, ...] | None:
    """Read latest ties from the exact targeted and applicable legacy native groups.

    ``()`` is a known empty selected group union; ``None`` is unknown. These are
    candidates, not verified condition truth or an action/readiness grant. The
    consumer still owns source/review binding and, for completed minute targets,
    proof that the supplied observation is actual and the selected union complete.
    Other observation groups are outside this requested candidate union. SIGNAL
    leaves and legacy applicability that depends on signal presence are unsupported.
    """
    try:
        target = ReviewedFactTarget.model_validate_json(target.model_dump_json())
        if type(trade_date) is not date or now.utcoffset() != timedelta(hours=8):
            return None
        if observation is not None:
            observation = ReviewedFactObservation.model_validate_json(observation.model_dump_json())
            if observation.bar_end.date() != trade_date or observation.bar_end > now:
                return None
        with work.daily.session.no_autoflush:
            return _read(work, target, trade_date, now, observation)
    except (
        SourceCoverageAuthorityError,
        RepositoryError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
    ):
        return None
