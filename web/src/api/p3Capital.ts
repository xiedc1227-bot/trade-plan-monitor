/** Validate server-owned budget resources before displaying any financial authority. */
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const integer = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const nullable = (value: unknown) => value === null || integer(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const whole = (value: unknown) => integer(value) && Number(value) > 0 && Number(value) % 100 === 0;
function capacity(value: unknown): boolean {
  return record(value) && (["UNBOUNDED", "UNKNOWN"].includes(String(value.mode)) ||
    value.mode === "BOUNDED" && integer(value.remaining_qty) && Number(value.remaining_qty) % 100 === 0);
}
function inventoryLot(value: unknown): boolean {
  return record(value) && typeof value.lot_id === "string" && value.lot_id.length > 0 &&
    ["CORE", "TACTICAL"].includes(String(value.bucket)) && whole(value.quantity);
}
function book(value: unknown): boolean {
  return record(value) && value.version === "capital-book-v1" && digest(value.evidence_hash) &&
    integer(value.revision) && Number(value.revision) > 0 && integer(value.inventory_revision) &&
    typeof value.updated_at === "string" && typeof value.symbol === "string" &&
    Array.isArray(value.lots) && value.lots.length <= 500 && value.lots.every(lot =>
      inventoryLot(lot) && record(lot) && nullable(lot.retained_basis_fen));
}
export function validCapitalAssessment(value: unknown): boolean {
  return record(value) && value.version === "capital-limit-evidence-v1" &&
    ["OPEN_COST_CAP", "MARKET_VALUE_CAP"].includes(String(value.mode)) &&
    ["PASS", "FAIL", "UNKNOWN"].includes(String(value.outcome)) &&
    ["CONFIRMATION", "CURRENT", "EXECUTION"].includes(String(value.phase)) &&
    digest(value.evidence_hash) && digest(value.policy_hash) &&
    integer(value.cap_fen) && Number(value.cap_fen) > 0 &&
    (value.quantity === null || whole(value.quantity)) &&
    ["price_fen", "total_qty", "inventory_revision", "book_revision", "before_fen", "after_fen"]
      .every(key => nullable(value[key])) &&
    (value.remaining_fen === null || Number.isSafeInteger(value.remaining_fen)) &&
    capacity(value.share_capacity) && Array.isArray(value.blockers) &&
    value.blockers.every(code => typeof code === "string");
}
export function validCapitalResponse(path: string, value: unknown): boolean {
  if (!record(value) || value.authorityGranted !== false) return false;
  if (path.includes("/simulation-capital-books/")) return typeof value.symbol === "string" &&
    typeof value.inventoryKnown === "boolean" && integer(value.inventoryRevision) &&
    nullable(value.bookRevision) && nullable(value.retainedBasisFen) &&
    typeof value.computedAt === "string" && Array.isArray(value.inventoryLots) &&
    value.inventoryLots.length <= 500 && value.inventoryLots.every(inventoryLot) &&
    (value.book === null || book(value.book));
  if (path.endsWith("/simulation-capital-openings")) return value.inventoryChanged === false &&
    record(value.event) && digest(value.event.event_hash) && book(value.event.book);
  if (!path.endsWith("/plan-capital-previews")) return false;
  return typeof value.planVersionId === "string" && typeof value.ruleId === "string" &&
    typeof value.computedAt === "string" && (value.quantity === null || whole(value.quantity)) &&
    validCapitalAssessment(value.assessment) && record(value.assessment) &&
    value.assessment.quantity === value.quantity && record(value.evidence) &&
    value.evidence.rule_id === value.ruleId && digest(value.evidence.content_hash) &&
    value.evidence.version === "p2-pretrade-evidence-v1";
}
