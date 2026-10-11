import type { CollectionItemView, CollectionItemReviewDeclaration, CollectionPreparationView, CollectionPreparationFrozenView, CollectionReviewInput, CollectionItemCorrectionInput, LoopAccountInput, CollectionVersionView, DailyMapping, PreparationFrozenView, PreparationReviewInput, PreparationSource, PreparationView } from "./generated-runtime-status";
import { isCalendarDate, isShanghaiDateTime } from "./shanghaiTime";

const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const integer = (value: unknown, minimum = 0): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const text = (value: unknown, maximum = 2000): value is string => typeof value === "string" && !!value.trim() && Array.from(value).length <= maximum;
const nullable = (value: unknown, check: (value: unknown) => boolean) => value == null || check(value);

/** Bounded JSON shape checks only. The server owns semantic validity and frozen authority. */
function bounded(value: unknown, depth = 0, budget = { remaining: 30_000 }): boolean {
  if (depth > 32 || --budget.remaining < 0) return false;
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "string") return Array.from(value).length <= 150_000;
  if (typeof value === "number") return Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value));
  if (Array.isArray(value)) return value.length <= 2000 && value.every(item => bounded(item, depth + 1, budget));
  return record(value) && Object.entries(value).every(([key, item]) =>
    !["__proto__", "prototype", "constructor"].includes(key) && bounded(item, depth + 1, budget));
}
function span(value: unknown, source: readonly string[]): boolean {
  return record(value) && integer(value.start) && integer(value.end, value.start + 1) &&
    text(value.excerpt, 512) && source.slice(value.start, value.end).join("") === value.excerpt;
}
function fact(value: unknown, source: readonly string[], check: (value: unknown) => boolean): boolean {
  return value === null || record(value) && span(value, source) && check(value.value);
}
function opening(value: unknown, source: readonly string[]): boolean {
  return record(value) && fact(value.inventory_quantity, source, integer) && fact(value.cash_fen, source, integer) &&
    fact(value.snapshot_at, source, isShanghaiDateTime) && Array.isArray(value.lots) && value.lots.length <= 200 &&
    value.lots.every(lot => record(lot) && text(lot.lot_key, 128) && lot.quantity !== null &&
      fact(lot.quantity, source, value => integer(value, 1)) &&
      fact(lot.bucket, source, value => value === "CORE" || value === "TACTICAL") &&
      fact(lot.unit_cost_yuan, source, value => typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value)) &&
      fact(lot.acquired_trade_date, source, isCalendarDate) && fact(lot.sellable_quantity, source, integer));
}
function draft(value: unknown): boolean {
  return record(value) && value.schema_version === 5 && value.execution_mode === "CONDITION_PLAN" &&
    text(value.symbol, 128) && text(value.name) && text(value.plan_id, 128) && integer(value.version, 1) &&
    ["SSE", "SZSE", "BSE"].includes(String(value.market)) && record(value.metadata) && record(value.position) &&
    [value.activation, value.levels, value.monitoring, value.execution_policy].every(item => item === null || record(item)) &&
    Array.isArray(value.ordinary_rules) && value.ordinary_rules.length <= 2 && value.ordinary_rules.every(record) &&
    Array.isArray(value.risk_branches) && value.risk_branches.length <= 2 && value.risk_branches.every(record) &&
    (value.alert_rules === undefined || Array.isArray(value.alert_rules) && value.alert_rules.length <= 10 && value.alert_rules.every(record));
}
function mapping(value: unknown, source?: readonly string[]): boolean {
  return record(value) && value.mapping_version === "daily-mapping-v1" && hash(value.candidate_content_hash) &&
    Array.isArray(value.clauses) && value.clauses.length <= 512 && value.clauses.every(clause => record(clause) &&
      text(clause.clause_id, 128) && (source === undefined || span(clause, source)) &&
      ["POLICY", "INVENTORY_ASSERTION", "BACKGROUND", "UNRESOLVED", "UNSUPPORTED"].includes(String(clause.disposition)) &&
      Array.isArray(clause.paths) && clause.paths.every(path => text(path, 512)) && text(clause.reason)) &&
    Array.isArray(value.bindings) && value.bindings.length <= 2000 && value.bindings.every(binding => record(binding) &&
      text(binding.path, 512) && ["SOURCE", "HUMAN_SUPPLEMENT", "PRODUCT_CONTRACT"].includes(String(binding.origin)) &&
      Array.isArray(binding.clause_ids) && binding.clause_ids.every(id => text(id, 128))) &&
    Array.isArray(value.supplements) && value.supplements.length <= 2000 && value.supplements.every(supplement => record(supplement) &&
      text(supplement.supplement_id, 128) && text(supplement.path, 512) && text(supplement.reason) && hash(supplement.candidate_content_hash));
}
function account(value: unknown): boolean {
  return record(value) && isShanghaiDateTime(value.snapshot_at) && typeof value.inventory_known === "boolean" &&
    record(value.cash) && (value.cash.kind === "UNKNOWN" || value.cash.kind === "KNOWN" && integer(value.cash.balance_fen)) &&
    text(value.evidence) && Array.isArray(value.lots) && value.lots.length <= 200 && value.lots.every(lot => record(lot) &&
      text(lot.lot_key, 128) && ["CORE", "TACTICAL"].includes(String(lot.bucket)) && integer(lot.quantity, 1) &&
      nullable(lot.cost_basis_fen, integer) && nullable(lot.acquired_trade_date, isCalendarDate) && nullable(lot.sellable_quantity, integer)) &&
    (value.opening_mark === null || record(value.opening_mark) && integer(value.opening_mark.price_fen, 1) &&
      isShanghaiDateTime(value.opening_mark.price_at) && isShanghaiDateTime(value.opening_mark.available_at));
}
export function validReviewCandidate(value: unknown, source: string): value is NonNullable<PreparationView["candidate"]> {
  if (source.length > 300_000 || !record(value) || !bounded(value) || !hash(value.candidateHash) || !hash(value.evidenceHash) ||
      !["VALID", "INVALID", "UNRESOLVED"].includes(String(value.validation)) || !Array.isArray(value.issues) ||
      value.issues.length > 128 || !value.issues.every(issue => typeof issue === "string" && Array.from(issue).length <= 512)) return false;
  const points = Array.from(source);
  if (points.length > 150_000) return false;
  if (value.kind === "EXTRACTION") return value.frozen === null && draft(value.draft) && mapping(value.mapping, points) && opening(value.openingAccount, points);
  if (value.kind === "UNAVAILABLE") return value.validation === "INVALID" && [value.draft, value.mapping, value.openingAccount, value.frozen].every(item => item === null);
  if (value.kind !== "FROZEN" || value.draft !== null || value.mapping !== null || value.openingAccount !== null || !record(value.frozen)) return false;
  const frozen = value.frozen;
  return value.validation === "VALID" && frozen.schema_version === "prepared-loop-plan-v1" && text(frozen.preparation_id, 128) &&
    integer(frozen.source_revision, 1) && integer(frozen.extraction_candidate_revision, 1) &&
    hash(frozen.extraction_candidate_hash) && hash(frozen.extraction_evidence_hash) &&
    record(frozen.source) && frozen.source.text === source && isShanghaiDateTime(frozen.source.authored_at) &&
    isShanghaiDateTime(frozen.source.available_at) && isCalendarDate(frozen.source.effective_trade_date) &&
    opening(frozen.opening_evidence, points) && mapping(frozen.mapping, points) && account(frozen.account) &&
    ["SOURCE", "HUMAN_REVIEW"].includes(String(frozen.account_origin)) && record(frozen.version) && draft(frozen.version.snapshot) &&
    text(frozen.version.version_id, 128) && hash(frozen.version.plan_hash);
}
export function validPreparationReviewInput(value: unknown): value is PreparationReviewInput {
  if (!record(value) || !bounded(value) || !record(value.review) || new TextEncoder().encode(JSON.stringify(value)).byteLength > 2 * 1024 * 1024) return false;
  const review = value.review;
  return review.confirmed === true && text(review.evidence) && hash(review.candidate_hash) && hash(review.evidence_hash) &&
    integer(review.expected_revision, 1) && integer(review.expected_source_revision, 1) && integer(review.expected_candidate_revision, 1) &&
    nullable(review.mapping, mapping) && nullable(review.draft, draft) && nullable(review.account, account);
}
export function validPreparationFrozenView(value: unknown): value is PreparationFrozenView {
  if (!record(value) || Object.keys(value).length !== 3 || !text(value.preparationId, 128) || !hash(value.manifestHash) ||
      !record(value.frozen) || !record(value.frozen.source) || typeof value.frozen.source.text !== "string" ||
      value.frozen.preparation_id !== value.preparationId) return false;
  return validReviewCandidate({ kind: "FROZEN", candidateHash: value.manifestHash, evidenceHash: value.frozen.extraction_evidence_hash,
    validation: "VALID", issues: [], draft: null, mapping: null, openingAccount: null, frozen: value.frozen }, value.frozen.source.text);
}
export interface ReviewPreparation {
  readonly preparationId: string;
  readonly revision: number;
  readonly sourceRevision: number;
  readonly candidateRevision: number;
  readonly reviewRevision: number;
  readonly status: string;
  readonly source: Readonly<PreparationSource>;
  readonly candidate: unknown;
}
export interface ReviewChoice { readonly path: string; readonly reason: string; }
export function valueAtPath(value: unknown, path: string): unknown {
  if (!/^[a-z_][a-z0-9_]*(?:(?:\.[a-z_][a-z0-9_]*)|(?:\[\d+\]))*$/.test(path)) return undefined;
  let result = value;
  for (const part of path.replace(/\[(\d+)\]/g, ".$1").split(".")) {
    if (["__proto__", "prototype", "constructor"].includes(part) || result === null || typeof result !== "object" ||
        !Object.hasOwn(result, part)) return undefined;
    result = (result as Record<string, unknown>)[part];
  }
  return result;
}
export function inspectPreparationReview(preparation: ReviewPreparation) {
  const blockers: string[] = [];
  const unknownFacts: string[] = [];
  const supplements: { path: string; value: unknown }[] = [];
  const candidate = preparation.candidate;
  if (!validReviewCandidate(candidate, preparation.source.text) || candidate.kind !== "EXTRACTION" || preparation.status !== "CANDIDATE") {
    return { blockers: ["尚无可审核的完整候选"], unknownFacts, supplements };
  }
  if (!preparation.source.authored_at || !preparation.source.available_at || !preparation.source.effective_trade_date) blockers.push("原文编写时间、可用时间和生效交易日必须明确");
  if (candidate.openingAccount.snapshot_at === null) blockers.push("期初账户快照时间缺失，请修正原文");
  if (candidate.openingAccount.lots.some(lot => lot.bucket === null)) blockers.push("期初持仓归属缺失，请修正原文");
  if (candidate.openingAccount.inventory_quantity === null && candidate.openingAccount.lots.length > 0) blockers.push("实际持仓总量缺失，请修正原文");
  if (candidate.validation === "INVALID") blockers.push("候选验证未通过");
  if (candidate.mapping.clauses.some(clause => ["UNRESOLVED", "UNSUPPORTED"].includes(clause.disposition))) blockers.push("原文仍有未解决或不支持的条款，请修正后重新提取");
  for (const issue of candidate.issues) {
    const match = /^DAILY_SOURCE_BINDING_REQUIRED: (.+)$/.exec(issue);
    if (match) {
      const path = match[1]!; const value = valueAtPath(candidate.draft, path);
      if (value == null) blockers.push(`必要参数缺失：${path}`);
      else if (!supplements.some(item => item.path === path)) supplements.push({ path, value });
    } else if (/^LOOP_ACCOUNT_FACT_REQUIRED: opening_account\.(cash_fen|inventory_quantity|lots\[\d+\]\.(unit_cost_yuan|acquired_trade_date|sellable_quantity|cost_basis_fen))$/.test(issue)) unknownFacts.push(issue.split(": ")[1]!);
    else blockers.push(issue);
  }
  for (const field of ["cash_fen", "inventory_quantity"] as const) {
    const path = `opening_account.${field}`;
    if (candidate.openingAccount[field] === null && !unknownFacts.includes(path)) unknownFacts.push(path);
  }
  candidate.openingAccount.lots.forEach((lot, index) => {
    for (const field of ["unit_cost_yuan", "acquired_trade_date", "sellable_quantity"] as const) {
      const path = `opening_account.lots[${index}].${field}`;
      if (lot[field] === null && !unknownFacts.includes(path)) unknownFacts.push(path);
    }
  });
  return { blockers, unknownFacts, supplements };
}
export function buildPreparationReview(preparation: ReviewPreparation, evidence: string, choices: readonly ReviewChoice[], unknownConfirmed: boolean): PreparationReviewInput {
  const inspected = inspectPreparationReview(preparation);
  const candidate = preparation.candidate;
  if (inspected.blockers.length || !text(evidence) || inspected.unknownFacts.length && unknownConfirmed !== true ||
      !validReviewCandidate(candidate, preparation.source.text) || candidate.kind !== "EXTRACTION" ||
      choices.length !== inspected.supplements.length || new Set(choices.map(choice => choice.path)).size !== choices.length ||
      choices.some(choice => !text(choice.reason) || !inspected.supplements.some(item => item.path === choice.path))) throw new Error("审核说明或当前候选仍不完整");
  const reviewedMapping: DailyMapping = JSON.parse(JSON.stringify(candidate.mapping));
  for (const [index, choice] of choices.entries()) {
    const value = valueAtPath(candidate.draft, choice.path);
    const supplementId = `review-${preparation.candidateRevision}-${index + 1}`;
    reviewedMapping.bindings = reviewedMapping.bindings.filter(binding => binding.path !== choice.path);
    reviewedMapping.supplements = reviewedMapping.supplements.filter(supplement => supplement.path !== choice.path);
    reviewedMapping.supplements.push({ supplement_id: supplementId, path: choice.path, value,
      candidate_content_hash: reviewedMapping.candidate_content_hash, reason: choice.reason.trim() });
    reviewedMapping.bindings.push({ path: choice.path, value, origin: "HUMAN_SUPPLEMENT", unit: "JSON", clause_ids: [], supplement_id: supplementId });
  }
  return { review: { confirmed: true, evidence: evidence.trim(), expected_revision: preparation.revision,
    expected_source_revision: preparation.sourceRevision, expected_candidate_revision: preparation.candidateRevision,
    candidate_hash: candidate.candidateHash, evidence_hash: candidate.evidenceHash, mapping: reviewedMapping } };
}
export function isReviewedPreparation(preparation: ReviewPreparation | null): boolean {
  if (!preparation || preparation.status !== "REVIEWED" || preparation.reviewRevision < 1 ||
      !validReviewCandidate(preparation.candidate, preparation.source.text) || preparation.candidate.kind !== "FROZEN") return false;
  const frozen = preparation.candidate.frozen;
  return frozen.preparation_id === preparation.preparationId && frozen.source_revision === preparation.sourceRevision &&
    frozen.extraction_candidate_revision + 1 === preparation.candidateRevision && frozen.source.source_id === preparation.source.source_id &&
    frozen.source.authored_at === preparation.source.authored_at && frozen.source.available_at === preparation.source.available_at &&
    frozen.source.effective_trade_date === preparation.source.effective_trade_date;
}


export function collectionBinding(item: CollectionItemView): CollectionItemReviewDeclaration {
  if (!item.candidateHash || !item.evidenceHash || !item.candidate) throw new Error("候选证据尚不完整");
  return { source_id: item.sourceId, source_revision: item.sourceRevision, candidate_revision: item.candidateRevision,
    candidate_hash: item.candidateHash, evidence_hash: item.evidenceHash, base_hash: item.baseHash };
}

export function validCollectionVersion(value: unknown): value is CollectionVersionView {
  return record(value) && text(value.sourceId, 128) && integer(value.sourceRevision, 1) && integer(value.candidateRevision, 1) &&
    text(value.versionId, 128) && hash(value.planHash) && hash(value.evidenceHash) && isCalendarDate(value.effectiveTradeDate) &&
    isShanghaiDateTime(value.availableAt) && (value.accountContext === null || record(value.accountContext) &&
      nullable(value.accountContext.core_qty, integer) && nullable(value.accountContext.tactical_qty, integer) &&
      text(value.accountContext.evidence) && Array.isArray(value.accountContext.dependent_rule_ids) && value.accountContext.dependent_rule_ids.every(id => text(id, 128)));
}
export function validCollectionFrozen(value: unknown): value is CollectionPreparationFrozenView {
  return record(value) && bounded(value) && value.schemaVersion === "prepared-loop-plan-v2" && text(value.preparationId, 128) &&
    integer(value.revision, 1) && hash(value.manifestHash) && account(value.account) && isShanghaiDateTime(value.reviewedAt) &&
    ["SOURCE", "HUMAN_REVIEW"].includes(String(value.accountOrigin)) && Array.isArray(value.versions) &&
    value.versions.length > 0 && value.versions.length <= 256 && value.versions.every(validCollectionVersion) &&
    new Set(value.versions.map(version => version.sourceId)).size === value.versions.length;
}
/** Validate projection shape, never re-materialize or infer execution authority in the browser. */
export function validCollectionCandidate(value: unknown, source: string): boolean {
  if (value === null) return true;
  if (!record(value) || !bounded(value) || !hash(value.candidateHash) || !hash(value.evidenceHash) ||
      !["VALID", "INVALID", "UNRESOLVED"].includes(String(value.validation)) || !Array.isArray(value.issues) ||
      value.issues.length > 128 || !value.issues.every(issue => typeof issue === "string" && Array.from(issue).length <= 512)) return false;
  if (value.kind === "INITIAL") return draft(value.draft) && mapping(value.mapping, Array.from(source)) && opening(value.openingAccount, Array.from(source));
  if (value.kind === "UNAVAILABLE") return value.validation === "INVALID";
  if (value.kind === "UPDATE") return record(value.update) && ["FULL_REPLACEMENT", "EXPLICIT_CHANGES", "UNRESOLVED"].includes(String(value.update.scope));
  return ["MATERIALIZED", "CORRECTED"].includes(String(value.kind)) && record(value.review) && draft(value.review.draft) &&
    text(value.review.source_id, 128) && hash(value.review.source_hash) && nullable(value.review.available_at, isShanghaiDateTime) &&
    Array.isArray(value.review.bindings) && value.review.bindings.every(binding => record(binding) && hash(binding.source_hash) &&
      hash(binding.candidate_content_hash) && text(binding.path, 512) && text(binding.source_id, 128) && record(binding.binding) && Array.isArray(binding.clauses)) &&
    Array.isArray(value.review.issues) && value.review.issues.every(issue => text(issue)) &&
    (value.review.changes === undefined || Array.isArray(value.review.changes) && value.review.changes.every(change => record(change) &&
      ["ADD", "MODIFY", "REVOKE", "RETAIN"].includes(String(change.action)) && text(change.target, 512)));
}
export function inspectCollectionReview(value: CollectionPreparationView, items: readonly CollectionItemView[]) {
  const blockers: string[] = [], unknownFacts: string[] = [];
  if (items.length !== value.itemCount || items.some((item, index) => {
    const summary = value.items[index];
    return !summary || item.sourceId !== summary.sourceId || item.sourceRevision !== summary.sourceRevision ||
      item.candidateRevision !== summary.candidateRevision || item.candidateHash !== summary.candidateHash || item.evidenceHash !== summary.evidenceHash || item.baseHash !== summary.baseHash;
  })) blockers.push("请读取当前修订的全部原文和候选后再复核");
  for (const [index, item] of items.entries()) {
    if (!item.source.authored_at || !item.source.available_at || !item.source.effective_trade_date) blockers.push(`第 ${index + 1} 份原文的历史时间与交易日仍不完整`);
    if (!item.candidate || item.validation !== "VALID" || item.candidate.issues.length) blockers.push(`第 ${index + 1} 份候选仍需修正`);
  }
  const first = items[0]?.candidate;
  if (first?.kind === "INITIAL" && first.openingAccount) {
    const facts = first.openingAccount;
    if (!facts.snapshot_at) blockers.push("期初账户快照时间缺失");
    if (!facts.cash_fen) unknownFacts.push("期初现金未知");
    if (!facts.inventory_quantity) unknownFacts.push("期初持仓总量未知");
    for (const lot of facts.lots) if (!lot.unit_cost_yuan || !lot.acquired_trade_date || !lot.sellable_quantity) unknownFacts.push(`${lot.lot_key} 的成本、取得日期或可卖数量未知`);
  }
  return { blockers, unknownFacts, requiresAccount: first?.kind === "CORRECTED" };
}
export function buildCollectionReview(value: CollectionPreparationView, items: readonly CollectionItemView[], evidence: string,
  unknownConfirmed: boolean, reviewedAccount?: LoopAccountInput): CollectionReviewInput {
  const inspection = inspectCollectionReview(value, items);
  if (inspection.blockers.length || !text(evidence) || inspection.unknownFacts.length && !unknownConfirmed ||
      inspection.requiresAccount && !reviewedAccount || reviewedAccount !== undefined && !account(reviewedAccount)) throw new Error("整链复核尚不完整");
  return { schemaVersion: "backtest-preparation-v2", kind: "CHAIN_REVIEW", review: {
    confirmed: true, expected_revision: value.revision, evidence: evidence.trim(), items: items.map(collectionBinding),
    ...(reviewedAccount === undefined ? {} : { account: JSON.parse(JSON.stringify(reviewedAccount)) as LoopAccountInput }),
  } };
}
export function validCollectionReviewInput(value: unknown): value is CollectionReviewInput | CollectionItemCorrectionInput {
  if (!record(value) || !bounded(value) || value.schemaVersion !== "backtest-preparation-v2" || !record(value.review) ||
      value.review.confirmed !== true || !integer(value.review.expected_revision, 1) || !text(value.review.evidence)) return false;
  const binding = (item: unknown) => record(item) && text(item.source_id, 128) && integer(item.source_revision, 1) &&
    integer(item.candidate_revision, 1) && hash(item.candidate_hash) && hash(item.evidence_hash) && (item.base_hash === null || hash(item.base_hash));
  if (value.kind === "CHAIN_REVIEW") return Array.isArray(value.review.items) && value.review.items.length > 0 && value.review.items.length <= 256 &&
    value.review.items.every(binding) && new Set(value.review.items.map(item => item.source_id)).size === value.review.items.length && nullable(value.review.account, account);
  return value.kind === "ITEM_CORRECTION" && binding(value.review.binding) && nullable(value.review.draft, draft) &&
    nullable(value.review.mapping, mapping) && (value.review.update == null || record(value.review.update));
}
