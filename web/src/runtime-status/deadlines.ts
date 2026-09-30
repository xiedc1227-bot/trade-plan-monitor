import { shanghaiDateTimeKey } from "../api/shanghaiTime";

/** Only a new authoritative snapshot installs this deadline; heartbeats never extend it. */
export function monotonicDeadline(deadline: string | null, observedAt: string, sentAt: number, receivedAt: number): number | null {
  if (deadline === null) return null;
  if (!Number.isFinite(sentAt) || !Number.isFinite(receivedAt) || receivedAt < sentAt) return receivedAt;
  const serverRemaining = Number((shanghaiDateTimeKey(deadline) - shanghaiDateTimeKey(observedAt)) / 1000n);
  return receivedAt + Math.max(0, Math.floor(serverRemaining - (receivedAt - sentAt)));
}
