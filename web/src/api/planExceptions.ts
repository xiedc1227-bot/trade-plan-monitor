/** Runtime response guards; the server remains the only grant authority. */
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function integer(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) >= 0; }
function quantity(value: unknown): value is number { return integer(value) && value > 0 && value % 100 === 0; }
export function validExceptionResponse(path: string, value: unknown): boolean {
  if (!record(value)) return false;
  if (path.endsWith("/plan-exception-previews")) return typeof value.previewId === "string" && typeof value.previewHash === "string"
    && typeof value.candidateId === "string" && typeof value.bindingHash === "string" && integer(value.expectedRevision)
    && quantity(value.quantity) && typeof value.createdAt === "string" && record(value.current)
    && integer(value.current.inventory_revision) && integer(value.current.evaluation_revision)
    && integer(value.current.capacity) && Array.isArray(value.current.blockers) && !value.current.blockers.length;
  if (!path.endsWith("/plan-exception-decisions") && !path.endsWith("/plan-exception-revocations")) return false;
  if (!integer(value.revision) || !record(value.candidate) || !record(value.event)) return false;
  const c = value.candidate, e = value.event;
  return typeof c.candidate_id === "string" && typeof c.binding_hash === "string" && record(c.binding)
    && ["APPROVED", "REJECTED", "REVOKED"].includes(String(c.state)) && e.to_state === c.state
    && e.candidate_id === c.candidate_id && e.binding_hash === c.binding_hash && e.event_id === c.last_event_id
    && (c.state !== "APPROVED" || quantity(c.frozen_quantity) && c.frozen_quantity === e.quantity && c.approval_id === e.approval_id);
}
