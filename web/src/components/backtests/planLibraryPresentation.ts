import type { DeepReadonly } from "vue";
import type { ReviewedPlanLibraryItem } from "../../api/generated-runtime-status";
import { formatDisplayDateTime } from "../../formatters/dateTime";

type Entry = DeepReadonly<ReviewedPlanLibraryItem>;
/** Display only: original IDs, selection state and composition admission stay unchanged. */
export function planLibraryGroups(items: readonly Entry[]) {
  const byId = new Map(items.map(item => [item.preparationId, item]));
  const sources = new Map<string, Entry[]>();
  const sourceKey = (item: Entry) => `${item.symbol}:${item.effectiveTradeDate}:${item.identity?.sourceHash}`;
  for (const item of items) {
    if (!item.identity) continue;
    const key = sourceKey(item);
    sources.set(key, [...sources.get(key) ?? [], item]);
  }
  function chainRoot(item: Entry): Entry | null {
    const visited = new Set<string>();
    while (item.reviewedBase) {
      if (visited.has(item.preparationId)) return null;
      visited.add(item.preparationId);
      const previous = byId.get(item.reviewedBase.preparation_id);
      if (!previous || previous.manifestHash !== item.reviewedBase.manifest_hash) return null;
      item = previous;
    }
    return item;
  }
  function predecessor(item: Entry): string {
    if (!item.reviewedBase) return "计划链起点，无前序";
    const previous = byId.get(item.reviewedBase.preparation_id);
    if (!previous) return "前序记录未在当前计划库中，须核对准确版本";
    if (previous.manifestHash !== item.reviewedBase.manifest_hash) return "前序版本与当前记录不匹配";
    return `前序：${previous.effectiveTradeDate} · ${previous.name}（${previous.symbol}）`;
  }
  function comparison(item: Entry): string {
    if (!item.identity) return "历史计划，可查看已审核原文与交易条件";
    const peers = (sources.get(sourceKey(item)) ?? []).filter(other => other.preparationId !== item.preparationId);
    if (!peers.length) return "";
    const repeated = peers.some(other => other.identity!.reviewedVersionHash === item.identity!.reviewedVersionHash);
    const different = peers.some(other => other.identity!.planHash !== item.identity!.planHash);
    if (repeated) return `相同审核快照的重复准备${different ? "；另有不同内容版本" : ""}`;
    return different ? "同原文，计划内容不同" : "同原文，计划内容一致，审核版本不同";
  }
  const grouped = new Map<string, { id: string; label: string; entries: { item: Entry; predecessor: string; comparison: string }[] }>();
  for (const item of items) {
    const root = chainRoot(item);
    const id = root?.preparationId ?? `unresolved:${item.preparationId}`;
    let group = grouped.get(id);
    if (!group) {
      const label = root
        ? `${root.name}（${root.symbol}）· ${root.effectiveTradeDate} 起 · 起点审核 ${formatDisplayDateTime(root.reviewedAt)}`
        : `${item.name}（${item.symbol}）· 无法核对计划链起点`;
      group = { id, label, entries: [] }; grouped.set(id, group);
    }
    group.entries.push({ item, predecessor: predecessor(item), comparison: comparison(item) });
  }
  return [...grouped.values()].map(group => ({ ...group, entries: group.entries.sort((a, b) =>
    a.item.effectiveTradeDate.localeCompare(b.item.effectiveTradeDate) || a.item.preparationId.localeCompare(b.item.preparationId)) }));
}

/** Resolve one exact reviewed path; never union branches or infer missing predecessors. */
export function planTimelinePath(items: readonly Entry[], endpointId: string): { items: readonly Entry[]; error: string | null } {
  const byId = new Map(items.map(item => [item.preparationId, item]));
  const reversed: Entry[] = [], seen = new Set<string>();
  let item = byId.get(endpointId);
  const invalid = (error: string) => ({ items: [] as Entry[], error });
  if (!item) return invalid("请选择一条可核对的计划时间线。");
  while (item) {
    if (seen.has(item.preparationId)) return invalid("前序关系存在循环，无法核对时间线。");
    if (reversed.length >= 256) return invalid("时间线超过 256 份计划，暂不能用于本次回测。");
    seen.add(item.preparationId); reversed.push(item);
    if (!item.reviewedBase) break;
    const previous = byId.get(item.reviewedBase.preparation_id);
    if (!previous) return invalid("前序记录未在当前计划库中，无法核对完整时间线。");
    if (previous.manifestHash !== item.reviewedBase.manifest_hash) return invalid("前序版本与当前记录不匹配。");
    item = previous;
  }
  const path = reversed.reverse(), sources = new Set<string>();
  for (const [index, entry] of path.entries()) {
    if (entry.symbol !== path[0]!.symbol) return invalid("时间线包含不同股票，请核对原审核记录。");
    if (sources.has(entry.sourceId)) return invalid("时间线存在重复原文标识。");
    if (index && entry.effectiveTradeDate <= path[index - 1]!.effectiveTradeDate) return invalid("生效交易日必须按更新顺序递增。");
    sources.add(entry.sourceId);
  }
  return { items: path, error: null };
}

export function planTimelineGroups(items: readonly Entry[]) {
  const predecessors = new Set(items.flatMap(item => item.reviewedBase ? [
    `${item.reviewedBase.preparation_id}:${item.reviewedBase.manifest_hash}`,
  ] : []));
  return planLibraryGroups(items).map(group => ({ ...group,
    paths: group.entries.filter(({ item }) => !predecessors.has(`${item.preparationId}:${item.manifestHash}`))
      .map(({ item: endpoint }) => ({ endpoint, ...planTimelinePath(items, endpoint.preparationId) })),
  }));
}
