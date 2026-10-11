import type { BacktestLoopRunView, BacktestLoopRunSummaryView, BacktestLoopEventView, BacktestLoopFillView, BacktestScheduledRunView, BacktestScheduledRunSummaryView, BacktestScheduledEventView } from "./generated";
import { isCalendarDate, isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";

const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown, min = 0): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min;
const signed = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const identifier = (v: unknown) => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(v);
const symbol = (v: unknown) => typeof v === "string" && /^\d{6}\.(SH|SZ|BJ)$/.test(v);
const nullable = (v: unknown, check: (v: unknown) => boolean) => v === null || check(v);
const decimal = (v: unknown) => typeof v === "string" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(v);
const strings = (v: unknown) => Array.isArray(v) && v.length <= 2000 && v.every(text);
const keys = (v: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []) =>
  required.every(k => Object.hasOwn(v, k)) && Object.keys(v).every(k => required.includes(k) || optional.includes(k));
const bytes = (v: unknown, max: number) => new TextEncoder().encode(JSON.stringify(v)).byteLength <= max;
const sameTime = (a: unknown, b: unknown) => isShanghaiDateTime(a) && isShanghaiDateTime(b) && shanghaiDateTimeKey(a) === shanghaiDateTimeKey(b);

/** Transport shape/bounds and identity checks. Semantic trading and hash verification remain server-owned. */
function bounded(v: unknown, depth = 0, budget = { left: 100_000 }): boolean {
  if (depth > 32 || --budget.left < 0) return false;
  if (v === null || typeof v === "boolean" || typeof v === "string") return true;
  if (typeof v === "number") return Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v));
  if (Array.isArray(v)) return v.length <= 2000 && v.every(item => bounded(item, depth + 1, budget));
  return record(v) && Object.entries(v).every(([k, item]) => !["__proto__", "constructor", "prototype"].includes(k) && bounded(item, depth + 1, budget));
}
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((item, i) => same(item, b[i]));
  return record(a) && record(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => same(a[k], b[k]));
}
function cash(v: unknown): boolean {
  return record(v) && (v.kind === "UNKNOWN" ? keys(v, ["kind"]) :
    v.kind === "KNOWN" && keys(v, ["kind", "balance_fen"]) && integer(v.balance_fen));
}
function lots(v: unknown, opening = false): boolean {
  return Array.isArray(v) && v.length <= 200 && v.every(lot => record(lot) &&
    keys(lot, ["lot_key", "bucket", "quantity", "cost_basis_fen", "acquired_trade_date", ...(opening ? ["evidence", "sellable_quantity"] : [])]) &&
    identifier(lot.lot_key) && ["CORE", "TACTICAL"].includes(String(lot.bucket)) && integer(lot.quantity, 1) &&
    nullable(lot.cost_basis_fen, integer) && nullable(lot.acquired_trade_date, isCalendarDate) &&
    (!opening || text(lot.evidence) && nullable(lot.sellable_quantity, integer)));
}
function account(v: unknown): boolean {
  return record(v) && keys(v, ["revision", "cash", "inventory_known", "lots", "realized_pnl_fen", "paid_fees_fen"]) &&
    integer(v.revision) && cash(v.cash) && typeof v.inventory_known === "boolean" && lots(v.lots) &&
    nullable(v.realized_pnl_fen, signed) && integer(v.paid_fees_fen);
}
function opening(v: unknown): boolean {
  return record(v) && keys(v, ["cash", "evidence", "inventory_known", "lots", "opening_mark", "snapshot_at"]) &&
    cash(v.cash) && text(v.evidence) && typeof v.inventory_known === "boolean" && lots(v.lots, true) && isShanghaiDateTime(v.snapshot_at) &&
    (v.opening_mark === null || record(v.opening_mark) && keys(v.opening_mark, ["price_fen", "price_at", "available_at", "evidence"]) &&
      integer(v.opening_mark.price_fen, 1) && isShanghaiDateTime(v.opening_mark.price_at) && isShanghaiDateTime(v.opening_mark.available_at) && text(v.opening_mark.evidence));
}
function inventory(v: unknown): boolean {
  return record(v) && keys(v, ["symbol", "revision", "known", "total_qty", "core_qty", "tactical_qty", "sellable_core", "sellable_tactical"]) &&
    symbol(v.symbol) && integer(v.revision) && typeof v.known === "boolean" &&
    [v.total_qty, v.core_qty, v.tactical_qty, v.sellable_core, v.sellable_tactical].every(item => nullable(item, integer));
}
const metricKeys = ["initial_equity_fen", "final_equity_fen", "equity_change_fen", "interval_return", "maximum_drawdown", "turnover",
  "cost_pnl_fen", "realized_pnl_fen", "unrealized_pnl_fen", "paid_fees_fen", "slippage_fen", "valuation_valid", "blockers"];
function metrics(v: unknown): boolean {
  return record(v) && keys(v, metricKeys) &&
    [v.initial_equity_fen, v.final_equity_fen].every(item => nullable(item, integer)) &&
    [v.equity_change_fen, v.cost_pnl_fen, v.realized_pnl_fen, v.unrealized_pnl_fen].every(item => nullable(item, signed)) &&
    [v.interval_return, v.maximum_drawdown, v.turnover].every(item => nullable(item, decimal)) &&
    integer(v.paid_fees_fen) && integer(v.slippage_fen) && typeof v.valuation_valid === "boolean" && strings(v.blockers) &&
    (v.valuation_valid || v.interval_return === null);
}
function valuation(v: unknown): boolean {
  return record(v) && keys(v, ["account_revision", "accounting_cost_fen", "at", "available_at", "blockers", "cash_fen", "cost_pnl_fen",
    "equity_fen", "market_value_fen", "position_quantity", "price_at", "price_fen", "realized_pnl_fen", "unrealized_pnl_fen", "valuation_valid"]) &&
    integer(v.account_revision) && isShanghaiDateTime(v.at) && [v.available_at, v.price_at].every(item => nullable(item, isShanghaiDateTime)) &&
    [v.accounting_cost_fen, v.cash_fen, v.equity_fen, v.market_value_fen, v.position_quantity, v.price_fen].every(item => nullable(item, integer)) &&
    [v.cost_pnl_fen, v.realized_pnl_fen, v.unrealized_pnl_fen].every(item => nullable(item, signed)) && strings(v.blockers) && typeof v.valuation_valid === "boolean";
}
function costs(v: unknown): boolean {
  return record(v) && keys(v, ["commission_rate", "minimum_commission_fen", "stamp_duty_rate", "transfer_fee_rate", "buy_slippage_fen", "sell_slippage_fen"], ["formula_version"]) &&
    (v.formula_version === undefined || v.formula_version === "monitor-loop-costs-v1") &&
    [v.commission_rate, v.stamp_duty_rate, v.transfer_fee_rate].every(decimal) &&
    [v.minimum_commission_fen, v.buy_slippage_fen, v.sell_slippage_fen].every(item => integer(item));
}
function receipt(v: unknown): boolean {
  if (!record(v) || !keys(v, ["account", "authority_receipt", "command", "costs", "released_cost_fen", "request_key", "settlement"]) ||
      !account(v.account) || !costs(v.costs) || !nullable(v.released_cost_fen, integer) || !identifier(v.request_key) ||
      !record(v.command) || !record(v.authority_receipt) || !record(v.settlement)) return false;
  const command = v.command, authority = v.authority_receipt, settlement = v.settlement;
  return keys(command, ["cause_id", "expected_cause_revision", "expected_inventory_revision", "plan_version_id", "quantity"]) &&
    identifier(command.cause_id) && identifier(command.plan_version_id) && integer(command.expected_cause_revision) &&
    integer(command.expected_inventory_revision) && integer(command.quantity, 1) &&
    keys(authority, ["inventory", "inventory_revision", "price_fen", "quantity", "side", "signal_id", "simulated_at", "simulation_id"]) &&
    inventory(authority.inventory) && integer(authority.inventory_revision) && integer(authority.price_fen, 1) && integer(authority.quantity, 1) &&
    ["BUY", "SELL"].includes(String(authority.side)) && nullable(authority.signal_id, identifier) && isShanghaiDateTime(authority.simulated_at) && identifier(authority.simulation_id) &&
    keys(settlement, ["commission_fen", "fill_price_fen", "notional_fen", "quantity", "quote_fen", "side", "stamp_duty_fen", "total_fees_fen", "transfer_fee_fen"]) &&
    [settlement.commission_fen, settlement.fill_price_fen, settlement.notional_fen, settlement.quantity, settlement.quote_fen,
      settlement.stamp_duty_fen, settlement.total_fees_fen, settlement.transfer_fee_fen].every(item => integer(item)) &&
    settlement.side === authority.side && settlement.quantity === authority.quantity && command.quantity === authority.quantity;
}
const summaryKeys = ["availability", "completedAt", "datasetHash", "eventEnd", "eventStart", "fillCount", "metrics", "pinned", "planHash",
  "planVersionId", "reportHash", "revision", "runId", "schemaVersion", "status", "symbol"];
function summary(v: Record<string, unknown>): boolean {
  return ["monitor-loop-result-v1", "monitor-loop-result-v2"].includes(String(v.schemaVersion)) && [v.runId, v.reportHash, v.datasetHash, v.planHash].every(hash) &&
    v.planVersionId === null && v.status === "COMPLETED" && symbol(v.symbol) &&
    isCalendarDate(v.eventStart) && isCalendarDate(v.eventEnd) && v.eventStart <= v.eventEnd && isShanghaiDateTime(v.completedAt) &&
    integer(v.fillCount) && integer(v.revision) && typeof v.pinned === "boolean" && metrics(v.metrics) && record(v.availability) &&
    keys(v.availability, ["decisionDetails", "signalDetails", "executionOutcomeDetails", "equitySeries"]) &&
    Object.values(v.availability).every(item => ["AVAILABLE", "EXPIRED", "NOT_RECORDED"].includes(String(item)));
}
export function validLoopRunSummary(v: unknown): v is BacktestLoopRunSummaryView | BacktestScheduledRunSummaryView {
  return record(v) && keys(v, summaryKeys) && bounded(v) && summary(v) && bytes(v, 32 * 1024);
}
export function validLoopRun(v: unknown): v is BacktestLoopRunView {
  if (!record(v) || v.schemaVersion !== "monitor-loop-result-v1" || !keys(v, [...summaryKeys, "costs", "frozenPlan", "openingAccount", "provenance", "report", "response"]) ||
      !bounded(v) || !bytes(v, 4 * 1024 * 1024) || !summary(v) || !opening(v.openingAccount) || !costs(v.costs) ||
      !record(v.provenance) || !record(v.report) || !record(v.frozenPlan) || !record(v.response)) return false;
  const provenance = v.provenance, report = v.report, plan = v.frozenPlan, response = v.response;
  if (!keys(provenance, ["candidateHash", "candidateRevision", "inputHash", "manifestHash", "preparationId", "sourceRevision"]) ||
      ![provenance.candidateHash, provenance.inputHash, provenance.manifestHash].every(hash) || !identifier(provenance.preparationId) ||
      !integer(provenance.candidateRevision, 1) || !integer(provenance.sourceRevision, 1) ||
      !keys(plan, ["available_at", "evidence_hash", "information_cutoff", "plan_hash", "review", "snapshot", "source_hashes", "version_id"], ["authored_at", "authored_date"]) ||
      plan.plan_hash !== v.planHash || !hash(plan.evidence_hash) || !identifier(plan.version_id) ||
      !isShanghaiDateTime(plan.available_at) || !isShanghaiDateTime(plan.information_cutoff) || !Array.isArray(plan.source_hashes) || !plan.source_hashes.every(hash) ||
      !record(plan.review) || plan.review.confirmed !== true || !isShanghaiDateTime(plan.review.reviewed_at) || !text(plan.review.evidence) ||
      !record(plan.snapshot) || plan.snapshot.schema_version !== 5 || plan.snapshot.symbol !== v.symbol ||
      !record(plan.snapshot.position) || !Array.isArray(plan.snapshot.ordinary_rules) || !Array.isArray(plan.snapshot.risk_branches) ||
      !keys(response, ["mode"], ["response_delay_seconds", "fill_model"]) || !["FOLLOW_REMINDERS", "OBSERVE_ONLY", "RECORDED_ACTIONS"].includes(String(response.mode)) ||
      !(response.response_delay_seconds === undefined || integer(response.response_delay_seconds)) ||
      !(response.fill_model === undefined || response.fill_model === "NEXT_ELIGIBLE_MINUTE_CLOSE")) return false;
  if (!keys(report, ["authority_id", "boundary", "cycle", "dataset_hash", "event_count", "event_set_hash", "final_account", "final_inventory",
      "final_valuation", "input_hash", "last_evidence_at", "last_valuation_at", "metrics", "opening_valuation", "plan_hash", "report_hash", "run_id", "symbol"], ["schema_version"]) ||
      !(report.schema_version === undefined || report.schema_version === "backtest-report-v4") ||
      report.run_id !== v.runId || report.dataset_hash !== v.datasetHash || report.plan_hash !== v.planHash || report.report_hash !== v.reportHash ||
      report.input_hash !== provenance.inputHash || report.symbol !== v.symbol || !hash(report.authority_id) || !hash(report.event_set_hash) ||
      !integer(report.event_count) || !account(report.final_account) || !inventory(report.final_inventory) ||
      !valuation(report.final_valuation) || !valuation(report.opening_valuation) || !same(report.metrics, v.metrics) ||
      !nullable(report.last_evidence_at, isShanghaiDateTime) || !isShanghaiDateTime(report.last_valuation_at) || !record(report.boundary) || !record(report.cycle)) return false;
  const boundary = report.boundary, cycle = report.cycle;
  return keys(boundary, ["evidence_cutoff", "origin", "requested_end_date", "resolved_end_date", "started_at", "submitted_at"]) &&
    [boundary.started_at, boundary.submitted_at, boundary.evidence_cutoff].every(isShanghaiDateTime) &&
    nullable(boundary.requested_end_date, isCalendarDate) && boundary.resolved_end_date === v.eventEnd &&
    ["EXPLICIT", "DEFAULTED"].includes(String(boundary.origin)) && keys(cycle, ["attempts", "evaluations", "fills", "intents", "unfilled_intents"]) &&
    Object.values(cycle).every(item => integer(item)) && cycle.fills === v.fillCount;
}
export function validScheduledRun(v: unknown): v is BacktestScheduledRunView {
  if (!record(v) || v.schemaVersion !== "monitor-loop-result-v2" ||
      !keys(v, [...summaryKeys, "costs", "versions", "openingAccount", "provenance", "report", "response"]) ||
      !bounded(v) || !bytes(v, 4 * 1024 * 1024) || !summary(v) || !opening(v.openingAccount) || !costs(v.costs) ||
      !record(v.provenance) || !record(v.report) || !record(v.response)) return false;
  const provenance = v.provenance, report = v.report, response = v.response;
  if (!keys(provenance, ["preparationId", "revision", "inputHash", "manifestHash", "sources"]) ||
      !identifier(provenance.preparationId) || !integer(provenance.revision, 1) || !hash(provenance.inputHash) || !hash(provenance.manifestHash) ||
      !Array.isArray(provenance.sources) || provenance.sources.length < 1 || provenance.sources.length > 256 ||
      !Array.isArray(v.versions) || v.versions.length !== provenance.sources.length ||
      !keys(response, ["mode"], ["response_delay_seconds", "fill_model"]) || !["FOLLOW_REMINDERS", "OBSERVE_ONLY", "RECORDED_ACTIONS"].includes(String(response.mode)) ||
      !(response.response_delay_seconds === undefined || integer(response.response_delay_seconds)) ||
      !(response.fill_model === undefined || response.fill_model === "NEXT_ELIGIBLE_MINUTE_CLOSE")) return false;
  const seenSources = new Set(), seenVersions = new Set();
  for (let i = 0; i < v.versions.length; i++) {
    const source = provenance.sources[i], version = v.versions[i], previous = provenance.sources[i - 1];
    if (!record(source) || !record(version) ||
        !keys(source, ["sourceId", "sourceRevision", "candidateRevision", "sourceHash", "candidateHash", "evidenceHash", "baseHash"]) ||
        !identifier(source.sourceId) || !integer(source.sourceRevision, 1) || !integer(source.candidateRevision, 1) ||
        ![source.sourceHash, source.candidateHash, source.evidenceHash].every(hash) ||
        source.baseHash !== (i === 0 ? null : previous.candidateHash) || seenSources.has(source.sourceId) ||
        !keys(version, ["sourceId", "sourceRevision", "candidateRevision", "versionId", "planHash", "evidenceHash", "effectiveTradeDate", "availableAt", "accountContext"]) ||
        version.sourceId !== source.sourceId || version.sourceRevision !== source.sourceRevision || version.candidateRevision !== source.candidateRevision ||
        !identifier(version.versionId) || seenVersions.has(version.versionId) || !hash(version.planHash) || !hash(version.evidenceHash) ||
        !isCalendarDate(version.effectiveTradeDate) || !isShanghaiDateTime(version.availableAt) ||
        (i === 0 ? version.planHash !== v.planHash : version.effectiveTradeDate <= v.versions[i - 1].effectiveTradeDate)) return false;
    const context = version.accountContext;
    if (context !== null && (!record(context) || !keys(context, ["evidence"], ["core_qty", "tactical_qty", "dependent_rule_ids"]) ||
        !text(context.evidence) || ![context.core_qty, context.tactical_qty].every(q => q === undefined || nullable(q, integer)) ||
        !(context.dependent_rule_ids === undefined || Array.isArray(context.dependent_rule_ids) && context.dependent_rule_ids.length <= 2 && context.dependent_rule_ids.every(identifier)))) return false;
    seenSources.add(source.sourceId); seenVersions.add(version.versionId);
  }
  if (!keys(report, ["report_schema_version", "boundary", "cycle", "dataset_hash", "event_count", "event_set_hash", "final_account", "final_inventory",
      "final_valuation", "input_hash", "last_evidence_at", "last_valuation_at", "metrics", "opening_valuation", "report_hash", "run_id", "symbol"]) ||
      report.report_schema_version !== "backtest-report-v5" || report.run_id !== v.runId || report.dataset_hash !== v.datasetHash || report.report_hash !== v.reportHash ||
      report.input_hash !== provenance.inputHash || report.symbol !== v.symbol || !hash(report.event_set_hash) || !integer(report.event_count, 1) ||
      !account(report.final_account) || !inventory(report.final_inventory) || !valuation(report.final_valuation) || !valuation(report.opening_valuation) ||
      !same(report.metrics, v.metrics) || !nullable(report.last_evidence_at, isShanghaiDateTime) || !isShanghaiDateTime(report.last_valuation_at) ||
      !record(report.boundary) || !record(report.cycle)) return false;
  const boundary = report.boundary, cycle = report.cycle;
  return keys(boundary, ["evidence_cutoff", "origin", "requested_end_date", "resolved_end_date", "started_at", "submitted_at"]) &&
    [boundary.started_at, boundary.submitted_at, boundary.evidence_cutoff].every(isShanghaiDateTime) &&
    String(boundary.started_at).slice(0, 10) === v.eventStart && sameTime(boundary.evidence_cutoff, v.completedAt) &&
    nullable(boundary.requested_end_date, isCalendarDate) && boundary.resolved_end_date === v.eventEnd &&
    ["EXPLICIT", "DEFAULTED"].includes(String(boundary.origin)) && keys(cycle, ["attempts", "evaluations", "fills", "intents", "unfilled_intents"]) &&
    Object.values(cycle).every(item => integer(item)) && cycle.fills === v.fillCount;
}
function payload(v: unknown): boolean {
  if (!record(v)) return false;
  if (v.kind === "STATE") return keys(v, ["kind", "account", "inventory"]) && account(v.account) && inventory(v.inventory);
  if (v.kind === "VALUATION") return keys(v, ["kind", "valuation"]) && valuation(v.valuation);
  if (v.kind === "REQUESTED") return keys(v, ["kind", "cause_id", "intent_id", "ready_at"]) && identifier(v.cause_id) && hash(v.intent_id) && isShanghaiDateTime(v.ready_at);
  if (v.kind === "REMINDED") return keys(v, ["kind", "reminder"]) && record(v.reminder) &&
    keys(v.reminder, ["captured_at", "cause_revision", "event", "inventory_revision", "sequence", "status"]) &&
    isShanghaiDateTime(v.reminder.captured_at) && nullable(v.reminder.cause_revision, integer) && integer(v.reminder.inventory_revision) && integer(v.reminder.sequence, 1) &&
    ["CAPTURED", "SUPPRESSED"].includes(String(v.reminder.status)) && record(v.reminder.event) && identifier(v.reminder.event.event_id) &&
    text(v.reminder.event.message_text) && symbol(v.reminder.event.symbol);
  if (v.kind === "EXECUTED") {
    const attempt = v.attempt;
    return keys(v, ["kind", "attempt"]) && record(attempt) && keys(attempt, ["at", "cause_id", "intent_id", "minute", "reason", "status"], ["receipt"]) &&
      isShanghaiDateTime(attempt.at) && identifier(attempt.cause_id) && hash(attempt.intent_id) && nullable(attempt.reason, text) &&
      record(attempt.minute) && isShanghaiDateTime(attempt.minute.bar_end) && integer(attempt.minute.close_fen, 1) &&
      ["FILLED", "BLOCKED", "CLOSED"].includes(String(attempt.status)) &&
      (attempt.status === "FILLED" ? receipt(attempt.receipt) : attempt.receipt == null);
  }
  return v.kind === "EVALUATED" && keys(v, ["kind", "alerts", "blockers", "conditions", "duplicate", "evaluation_id", "inventory", "minute_target", "official_trade_date", "risk_action", "risks", "signals"]) &&
    strings(v.blockers) && typeof v.duplicate === "boolean" && nullable(v.evaluation_id, hash) && inventory(v.inventory) &&
    nullable(v.minute_target, isShanghaiDateTime) && nullable(v.official_trade_date, isCalendarDate) && record(v.risk_action) &&
    Array.isArray(v.conditions) && v.conditions.every(item => record(item) && text(item.rule_id) && record(item.evidence) &&
      ["SATISFIED", "UNSATISFIED", "MISSING_INPUT"].includes(String(item.evidence.outcome))) &&
    Array.isArray(v.alerts) && v.alerts.every(record) && Array.isArray(v.risks) && v.risks.every(item => record(item) && text(item.status)) &&
    Array.isArray(v.signals) && v.signals.every(item => record(item) && text(item.state) && ["BUY", "SELL"].includes(String(item.side)) &&
      integer(item.planned_qty) && integer(item.executable_qty) && integer(item.simulated_qty) && strings(item.blockers));
}
export function validLoopEvent(v: unknown): v is BacktestLoopEventView {
  if (!record(v) || !keys(v, ["detailId", "event", "eventAt", "kind", "runId", "schemaVersion"]) || v.schemaVersion !== "monitor-loop-event-v1" ||
      v.kind !== "DECISION" || !hash(v.runId) || !isShanghaiDateTime(v.eventAt) || !record(v.event) || !bounded(v) || !bytes(v, 32 * 1024)) return false;
  const event = v.event;
  return keys(event, ["at", "cause_event_id", "event_id", "payload", "run_id", "sequence"], ["schema_version"]) &&
    (event.schema_version === undefined || event.schema_version === "monitor-loop-event-v1") && event.run_id === v.runId && sameTime(event.at, v.eventAt) &&
    hash(event.event_id) && nullable(event.cause_event_id, hash) && integer(event.sequence, 1) &&
    v.detailId === `loop-${String(event.sequence).padStart(6, "0")}-${v.runId.slice(0, 16)}` && payload(event.payload);
}
export function validScheduledEvent(v: unknown): v is BacktestScheduledEventView {
  if (!record(v) || !keys(v, ["detailId", "event", "eventAt", "kind", "runId", "schemaVersion"]) || v.schemaVersion !== "monitor-loop-event-v2" ||
      v.kind !== "DECISION" || !hash(v.runId) || !isShanghaiDateTime(v.eventAt) || !record(v.event) || !bounded(v) || !bytes(v, 32 * 1024)) return false;
  const event = v.event;
  if (!keys(event, ["at", "cause_event_id", "event_id", "payload", "run_id", "sequence", "version_id", "authority_id"], ["schema_version"]) ||
      !(event.schema_version === undefined || event.schema_version === "monitor-loop-event-v2") || event.run_id !== v.runId || !sameTime(event.at, v.eventAt) ||
      !hash(event.event_id) || !nullable(event.cause_event_id, hash) || !integer(event.sequence, 1) || !nullable(event.version_id, identifier) || !nullable(event.authority_id, hash) ||
      v.detailId !== `loop-${String(event.sequence).padStart(6, "0")}-${v.runId.slice(0, 16)}` || !record(event.payload)) return false;
  const p = event.payload;
  if (!["REPLACED", "CONTINUED", "NO_AUTHORITY"].includes(String(p.kind))) return payload(p);
  return keys(p, ["kind", "at", "from_version_id", "version_id", "authority_id"], ["context_mismatches", "blocked_rule_ids", "closed_intent_ids"]) &&
    sameTime(p.at, event.at) && identifier(p.from_version_id) && p.version_id === event.version_id && p.authority_id === event.authority_id &&
    (p.context_mismatches === undefined || Array.isArray(p.context_mismatches) && p.context_mismatches.length <= 2 && p.context_mismatches.every(item =>
      record(item) && keys(item, ["bucket", "stated_qty", "actual_qty"]) && ["CORE", "TACTICAL"].includes(String(item.bucket)) && integer(item.stated_qty) && nullable(item.actual_qty, integer))) &&
    (p.blocked_rule_ids === undefined || Array.isArray(p.blocked_rule_ids) && p.blocked_rule_ids.length <= 2 && p.blocked_rule_ids.every(identifier)) &&
    (p.closed_intent_ids === undefined || Array.isArray(p.closed_intent_ids) && p.closed_intent_ids.every(hash));
}
export function validLoopFill(v: unknown): v is BacktestLoopFillView {
  return record(v) && keys(v, ["eventId", "fillId", "filledAt", "receipt", "runId", "schemaVersion"]) &&
    v.schemaVersion === "monitor-loop-fill-v1" && hash(v.runId) && hash(v.eventId) && identifier(v.fillId) && isShanghaiDateTime(v.filledAt) &&
    receipt(v.receipt) && record(v.receipt) && record(v.receipt.authority_receipt) && v.fillId === v.receipt.authority_receipt.simulation_id &&
    sameTime(v.filledAt, v.receipt.authority_receipt.simulated_at) && bounded(v) && bytes(v, 32 * 1024);
}
