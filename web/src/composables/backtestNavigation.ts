const visited = new Map<string, string | null>();
let returnTarget = { path: "/backtests", runId: "" };

export function rememberBacktestPage(scope: string, current: string | null, next: string) {
  const key = `${scope}:${next}`;
  visited.delete(key);
  visited.set(key, current);
  while (visited.size > 30) visited.delete(visited.keys().next().value!);
}
export function previousBacktestPage(scope: string, cursor: string | null) {
  return cursor === null ? undefined : visited.get(`${scope}:${cursor}`);
}
export function rememberBacktestReturn(path: string, runId: string) { returnTarget = { path, runId }; }
export function backtestReturnTarget() { return returnTarget; }

/** Shift an exact decimal ratio by two digits; never use binary floats. */
export function backtestPercent(value: string | null): string {
  if (value === null || !/^-?\d+(?:\.\d+)?$/.test(value)) return "不可用";
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace(/^-/, "").split(".");
  const digits = `${whole}${fraction.padEnd(2, "0")}`;
  const end = whole.length + 2;
  const result = `${BigInt(digits.slice(0, end))}${digits.slice(end).replace(/0+$/, "") ? `.${digits.slice(end).replace(/0+$/, "")}` : ""}`;
  return `${negative && result !== "0" ? "-" : ""}${result}%`;
}
