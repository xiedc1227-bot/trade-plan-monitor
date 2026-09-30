import { isShanghaiDateTime, shanghaiDateTimeKey } from "../api/shanghaiTime";

export const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
export const exact = (value: Record<string, unknown>, keys: readonly string[]): boolean => Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
export const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
export const text = (value: unknown, max = 128): value is string => typeof value === "string" && value.length > 0 && value.length <= max;
export const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
export const uuid4 = (value: unknown): value is string => uuid(value) && value[14] === "4";
export const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
export const symbol = (value: unknown): value is string => typeof value === "string" && /^\d{6}\.(SH|SZ|BJ)$/.test(value);
export const oneOf = (value: unknown, values: readonly string[]): boolean => typeof value === "string" && values.includes(value);
export const nullableTime = (value: unknown): boolean => value === null || isShanghaiDateTime(value);
export const notLater = (value: unknown, ceiling: unknown): boolean => isShanghaiDateTime(value) && isShanghaiDateTime(ceiling) && shanghaiDateTimeKey(value) <= shanghaiDateTimeKey(ceiling);
export const sameTime = (value: unknown, other: unknown): boolean => notLater(value, other) && notLater(other, value);
export const safeGuard = (check: () => boolean): boolean => { try { return check(); } catch { return false; } };

export function equalJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((item, index) => equalJson(item, right[index]));
  if (!isRecord(left) || !isRecord(right)) return false;
  return exact(left, Object.keys(right)) && Object.keys(left).every((key) => equalJson(left[key], right[key]));
}
