"""Validate recorded native inputs, never evaluate a condition or approve execution."""

from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import (
    list_reviewed_fact_targets,
    resolve_reviewed_fact_target,
)
from trade_plan_monitor.market_data.aggregation import expected_five_minute_ends
from trade_plan_monitor.runtime.daily_service import minute_source_current
from trade_plan_monitor.state.daily_models import (
    NATIVE_FACT_AVAILABLE_SQL,
    NATIVE_FACT_ORDER_SQL,
    DailyRecord,
)
from trade_plan_monitor.state.daily_state_models import (
    DailyEvaluationState,
    DailyFactState,
    ReviewedFactObservation,
    reviewed_fact_observation_source_hash,
)
from trade_plan_monitor.state.native_fact_reads import (
    _index_matches,
    _probe,
    _select,
    _where,
    read_native_trade_date_fact_candidates,
)
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.reviewed_fact_authority import signal_fact_evidence_satisfied
from trade_plan_monitor.state.source_action_authority import _condition_evidence_matches
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError


def _revisions(native):
    rows = native.fact_revisions
    return (
        None
        if len({row.id for row in rows}) != len(rows)
        else {row.id: row.revision for row in rows}
    )


def _minute_observation(work, native, target, now):
    if (
        target.kind != "INTRADAY"
        or native.minute_target != target.bucket_end
        or not native.five_minute_bars
        or native.five_minute_bars[-1].bar_end != target.bucket_end
        or not minute_source_current(work.daily.session, native.model_dump(mode="json"), now)
    ):
        return None
    ends = expected_five_minute_ends(target.bucket_end)
    minutes = tuple(row for row in native.minute_prefix if row.bar_end in ends)
    if tuple(row.bar_end for row in minutes) != ends:
        return None
    return ReviewedFactObservation(
        bar_end=target.bucket_end,
        source_hash=reviewed_fact_observation_source_hash(minutes, native.five_minute_bars[-1]),
    )


def recorded_fact_inputs_current(
    work, *, details, owner_kind, owner_id, condition, evidence, snapshot, target, now
):
    """Compare actual recorded leaves with complete current candidates; return raw binding."""
    bindings = []
    try:
        if evidence is None or not _condition_evidence_matches(condition, evidence):
            return False, ()
        pending = [(condition, evidence, "condition")]
        leaves = []
        while pending:
            node, proof, path = pending.pop()
            if node.type in {"ALL", "ANY"}:
                pending.extend(
                    (child, value, f"{path}.conditions[{index}]")
                    for index, (child, value) in enumerate(
                        zip(node.conditions, proof.children, strict=True)
                    )
                )
            elif node.type == "REVIEWED_FACT":
                leaves.append((node, proof, path))
        if not leaves:
            return True, ()
        native = (
            snapshot
            if isinstance(snapshot, DailyEvaluationState)
            else DailyEvaluationState.model_validate_json(canonical(snapshot))
        )
        revisions = _revisions(native)
        if (
            revisions is None
            or target is None
            or native.plan_version_id != details.id
            or native.content_hash != details.content_hash
        ):
            return False, ()
        plan = load_plan_json(details.payload_json)
        catalog = list_reviewed_fact_targets(
            plan, plan_version_id=details.id, content_hash=details.content_hash
        )
        ordinary = next((rule for rule in plan.ordinary_rules if rule.rule_id == owner_id), None)
        scoped_minute = bool(
            plan.schema_version == 5
            and owner_kind == "ORDINARY_RULE"
            and ordinary is not None
            and ordinary.confirmation.kind == "COMPLETED_BAR_CLOSE"
        )
        observation = _minute_observation(work, native, target, now) if scoped_minute else None
        if scoped_minute and observation is None:
            return False, ()
        day = target.bucket_end.date() if target.kind == "INTRADAY" else target.trade_date
        for node, proof, path in sorted(leaves, key=lambda item: item[2]):
            targets = [
                value
                for value in catalog
                if (value.owner_kind, value.owner_id, value.condition_path)
                == (owner_kind, owner_id, path)
            ]
            if len(targets) != 1 or node.validity_scope != "TRADE_DATE":
                return False, tuple(bindings)
            selected = targets[0]
            ref = resolve_reviewed_fact_target(plan, selected, plan_version_id=details.id)
            if ref.definition_json != canonical(node.model_dump(mode="json")):
                return False, tuple(bindings)
            rows = read_native_trade_date_fact_candidates(
                work,
                target=selected,
                trade_date=day,
                now=now,
                observation=observation,
                require_complete_observation_union=not scoped_minute,
            )
            bindings.append(
                (
                    path,
                    selected.model_dump_json(),
                    None if observation is None else observation.model_dump_json(),
                    None if rows is None else canonical(rows),
                )
            )
            if rows is None or len(set(proof.fact_ids)) != len(proof.fact_ids):
                return False, tuple(bindings)
            if {row["id"] for row in rows} != set(proof.fact_ids):
                return False, tuple(bindings)
            assertions = set()
            for row in rows:
                fact = DailyFactState.model_validate_json(canonical(row["payload"]))
                if (
                    row["revision"] != revisions.get(row["id"])
                    or fact.available_at > native.evaluated_at
                    or fact.verified_at > native.evaluated_at
                    or plan.schema_version != 5
                    and fact.reviewed_fact_target is not None
                ):
                    return False, tuple(bindings)
                assertions.add(fact.satisfied)
            compatible = (
                proof.outcome == "SATISFIED"
                and bool(rows)
                and assertions == {True}
                or proof.outcome == "UNSATISFIED"
                and bool(rows)
                and assertions == {False}
                or proof.outcome == "MISSING_INPUT"
                and (
                    proof.reason == "REVIEWED_FACT_REQUIRED"
                    and not rows
                    and not proof.fact_ids
                    or proof.reason == "CONFLICTING_REVIEWED_FACT"
                    and assertions == {True, False}
                )
            )
            if not compatible:
                return False, tuple(bindings)
        return True, tuple(bindings)
    except (
        SourceCoverageAuthorityError,
        RepositoryError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RecursionError,
    ):
        return False, tuple(bindings)


def recorded_quote_controls_current(work, *, details, snapshot, now):
    """Validate native any-FACT quote controls; unsupported signal scopes remain unknown."""
    bindings = []
    try:
        native = snapshot
        quote = native.quote
        revisions = _revisions(native)
        if (
            quote is None
            or revisions is None
            or not quote.tradable
            or not quote.special_state_verified
            or not quote.liquidity_available
        ):
            return False, ()
        reads = ActionOwnerReader(work)
        if not _index_matches(reads.session):
            return False, ()
        reads._reject_pending(DailyRecord, symbol=details.symbol, kind="FACT")
        if _probe(reads.session, (details.symbol, None)):
            return False, ()
        prefix = (details.symbol, details.id, details.content_hash, "SIGNAL_INVALIDATION")
        where, params = _where(prefix)
        signal = _select(reads.session, "id", where, params, "LIMIT 1").first()
        if signal is not None:
            row = reads.daily(signal.id)
            return False, (("SIGNAL_SCOPE_UNSUPPORTED", canonical(row)),)
        bindings.append(("SIGNAL_INVALIDATION", ()))
        witness = False
        for kind in ("TRADABILITY", "FULL_SESSION_SUSPENSION"):
            base = (
                details.symbol,
                details.id,
                details.content_hash,
                kind,
                str(quote.quote_at.date()),
                "true",
            )
            group = (*base, "", "", "")
            if (
                _probe(reads.session, (*base, None))
                or _probe(reads.session, (*group[:7], None))
                or _probe(reads.session, group, missing_time=True)
            ):
                return False, tuple(bindings)
            where, params = _where(group)
            where += f" AND ({NATIVE_FACT_AVAILABLE_SQL})<=:now_key"
            params["now_key"] = now.isoformat(timespec="microseconds")
            candidates = _select(
                reads.session,
                "id, length(CAST(payload_json AS BLOB)) AS bytes",
                where,
                params,
                "ORDER BY " + ", ".join(NATIVE_FACT_ORDER_SQL) + " LIMIT 513",
            ).all()
            if len(candidates) > 512 or sum(row.bytes for row in candidates) > 1024 * 1024:
                return False, tuple(bindings)
            rows = []
            for candidate in candidates:
                row = reads.daily(candidate.id)
                fact = DailyFactState.model_validate_json(canonical(row["payload"]))
                if (
                    row["kind"] != "FACT"
                    or row["symbol"] != details.symbol
                    or fact.plan_version_id != details.id
                    or fact.content_hash != details.content_hash
                    or fact.kind != kind
                    or fact.trade_date != quote.quote_at.date()
                    or fact.available_at > now
                    or fact.verified_at > now
                    or fact.reviewed_fact_target is not None
                    or fact.reviewed_fact_observation is not None
                ):
                    return False, tuple(bindings)
                rows.append(row)
                if (
                    kind == "TRADABILITY"
                    and row["revision"] == revisions.get(row["id"])
                    and fact.available_at <= native.evaluated_at
                    and fact.verified_at <= native.evaluated_at
                ):
                    witness = True
            bindings.append((kind, canonical(rows)))
            if kind == "FULL_SESSION_SUSPENSION" and rows:
                return False, tuple(bindings)
        if len(canonical(bindings).encode()) > 1024 * 1024:
            return False, ()
        return witness, tuple(bindings)
    except (
        SourceCoverageAuthorityError,
        RepositoryError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RecursionError,
    ):
        return False, tuple(bindings)


def recorded_signal_facts_current(work, *, plan, signal, snapshot):
    """Recheck a signal's own original references through the native point authority."""
    bindings = []
    try:
        pending = list(signal["evidence"])
        identities = set()
        while pending:
            proof = pending.pop()
            if proof["condition"]["type"] in {"ALL", "ANY"}:
                pending.extend(proof.get("children", ()))
            elif proof["condition"]["type"] == "REVIEWED_FACT":
                identities.update(proof.get("fact_ids", ()))
        if not identities:
            return True, ()
        if len(identities) > 512:
            return False, ()
        revisions = _revisions(snapshot)
        if revisions is None:
            return False, ()
        reads = ActionOwnerReader(work)
        for identity in sorted(identities):
            row = reads.daily(identity)
            bindings.append(row)
            if row is None or row["kind"] != "FACT" or row["symbol"] != plan.symbol:
                return False, tuple(bindings)
            fact = DailyFactState.model_validate_json(canonical(row["payload"]))
            if (
                row["revision"] != revisions.get(identity)
                or fact.available_at > snapshot.evaluated_at
                or fact.verified_at > snapshot.evaluated_at
            ):
                return False, tuple(bindings)
        if len(canonical(bindings).encode()) > 1024 * 1024:
            return False, ()
        return signal_fact_evidence_satisfied(work, plan, signal), tuple(bindings)
    except (
        SourceCoverageAuthorityError,
        RepositoryError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RecursionError,
    ):
        return False, tuple(bindings)
