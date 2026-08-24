import { shallowReadonly, shallowRef, toRef, toValue, watch } from "vue";
import type { MaybeRefOrGetter, ShallowRef } from "vue";

import type {
  AuthoritativeDecisionView,
  BarView,
  DecisionEvidenceView,
  EvidenceFactView,
  SymbolEventView,
} from "../api/generated";

export interface ChartCandle {
  closeYuan: number;
  highYuan: number;
  lowYuan: number;
  openYuan: number;
  time: string;
  volumeShares: number;
}

export interface ChartPriceLevel {
  evidenceCode: string;
  factKey: string;
  id: string;
  label: string;
  valueYuan: number;
}

export interface ChartIndicator {
  evidenceCode: string;
  factKey: string;
  id: string;
  label: string;
  plotTime: string | null;
  time: string | null;
  value: number | null;
  valueText: string;
}

export interface ChartEpisodeLow {
  label: string;
  time: null;
  valueYuan: number;
}

export interface ChartAlertMarker {
  eventId: string;
  label: string;
  messageText: string | null;
  plotTime: string | null;
  signalType: SymbolEventView["signalType"];
  time: string;
  valueYuan: number | null;
}

export interface ChartEvidenceRow {
  code: string;
  depth: number;
  facts: readonly EvidenceFactView[];
  id: string;
  kind: DecisionEvidenceView["kind"];
  missingInputs: readonly string[];
  outcome: DecisionEvidenceView["outcome"];
}

export interface ChartSeries {
  alertMarkers: readonly ChartAlertMarker[];
  candles: readonly ChartCandle[];
  episodeLow: ChartEpisodeLow | null;
  evidenceRows: readonly ChartEvidenceRow[];
  indicators: readonly ChartIndicator[];
  priceLevels: readonly ChartPriceLevel[];
}

interface UseChartSeriesOptions {
  bars: MaybeRefOrGetter<readonly BarView[]>;
  decision: MaybeRefOrGetter<AuthoritativeDecisionView | null>;
  events: MaybeRefOrGetter<readonly SymbolEventView[]>;
}

interface UseChartSeriesResult {
  series: Readonly<ShallowRef<ChartSeries>>;
}

const emptySeries = freezeSeries({
  alertMarkers: [],
  candles: [],
  episodeLow: null,
  evidenceRows: [],
  indicators: [],
  priceLevels: [],
});

const priceLevelLabels: Readonly<Record<string, string>> = Object.freeze({
  pressure_high_fen: "压力区上界",
  pressure_low_fen: "压力区下界",
  risk_line_fen: "风险线",
  zone_high_fen: "当前区间上界",
  zone_low_fen: "当前区间下界",
});

const indicatorLabels: Readonly<Record<string, string>> = Object.freeze({
  boll_lower_yuan: "布林下轨",
  boll_middle_yuan: "布林中轨",
  boll_upper_yuan: "布林上轨",
  current_macd_histogram_yuan: "当前 MACD 柱",
  indicator_yuan: "指标值",
  latest_boll_lower_yuan: "最新布林下轨",
  previous_macd_histogram_yuan: "前值 MACD 柱",
});

const indicatorTimeFactKeys: Readonly<Record<string, readonly string[]>> = Object.freeze({
  boll_lower_yuan: Object.freeze(["indicator_source_as_of"]),
  boll_middle_yuan: Object.freeze(["indicator_source_as_of"]),
  boll_upper_yuan: Object.freeze(["indicator_source_as_of"]),
  current_macd_histogram_yuan: Object.freeze([
    "current_indicator_date",
    "current_trade_date",
  ]),
  indicator_yuan: Object.freeze(["indicator_source_as_of"]),
  latest_boll_lower_yuan: Object.freeze([]),
  previous_macd_histogram_yuan: Object.freeze(["previous_indicator_date"]),
});

export function useChartSeries(options: UseChartSeriesOptions): UseChartSeriesResult {
  const bars = toRef(options.bars);
  const decision = toRef(options.decision);
  const events = toRef(options.events);
  const series = shallowRef<ChartSeries>(emptySeries);

  watch(
    [bars, decision, events],
    () => {
      series.value = mapChartSeries(
        toValue(options.bars),
        toValue(options.decision),
        toValue(options.events),
      );
    },
    { immediate: true },
  );

  return { series: shallowReadonly(series) };
}

function mapChartSeries(
  bars: readonly BarView[],
  decision: AuthoritativeDecisionView | null,
  events: readonly SymbolEventView[],
): ChartSeries {
  const candles = [...bars]
    .sort((left, right) => compareText(left.barEnd, right.barEnd))
    .map((bar) =>
      Object.freeze({
        closeYuan: fenToYuan(bar.closeFen),
        highYuan: fenToYuan(bar.highFen),
        lowYuan: fenToYuan(bar.lowFen),
        openYuan: fenToYuan(bar.openFen),
        time: bar.barEnd,
        volumeShares: bar.volumeShares,
      }),
    );
  const evidenceRows = decision === null ? [] : flattenEvidence(decision.evidence ?? []);
  const priceLevels = mapPriceLevels(evidenceRows);
  const indicators = mapIndicators(evidenceRows, candles);
  const episodeLow =
    decision?.episodeLowFen === null || decision?.episodeLowFen === undefined
      ? null
      : Object.freeze({
          label: "阶段低点",
          time: null,
          valueYuan: fenToYuan(decision.episodeLowFen),
        });
  const alertMarkers = [...events]
    .filter((event) => event.eventType === "ALERT")
    .sort((left, right) => compareText(left.occurredAt, right.occurredAt))
    .map((event) => {
      const anchor = markerAnchor(event.occurredAt, candles, decision?.priceFen ?? null);
      return Object.freeze({
        eventId: event.eventId,
        label: event.signalType ?? "提醒",
        messageText: event.messageText,
        plotTime: anchor.plotTime,
        signalType: event.signalType,
        time: event.occurredAt,
        valueYuan: anchor.valueYuan,
      });
    });

  return freezeSeries({
    alertMarkers,
    candles,
    episodeLow,
    evidenceRows,
    indicators,
    priceLevels,
  });
}

function flattenEvidence(evidence: readonly DecisionEvidenceView[]): ChartEvidenceRow[] {
  const rows: ChartEvidenceRow[] = [];

  function visit(item: DecisionEvidenceView, depth: number, path: string): void {
    rows.push(
      Object.freeze({
        code: item.code,
        depth,
        facts: Object.freeze(
          (item.facts ?? []).map((fact) => Object.freeze({ ...fact })),
        ),
        id: `${path}:${item.kind}:${item.code}`,
        kind: item.kind,
        missingInputs: Object.freeze([...(item.missingInputs ?? [])]),
        outcome: item.outcome,
      }),
    );
    for (const [index, child] of (item.children ?? []).entries()) {
      visit(child, depth + 1, `${path}.${index}`);
    }
  }

  for (const [index, item] of evidence.entries()) {
    visit(item, 0, String(index));
  }
  return rows;
}

function mapPriceLevels(rows: readonly ChartEvidenceRow[]): ChartPriceLevel[] {
  const levels = new Map<string, ChartPriceLevel>();
  for (const row of rows) {
    for (const fact of row.facts) {
      const label = priceLevelLabels[fact.key];
      if (label === undefined || fact.unit !== "FEN" || typeof fact.value !== "number") {
        continue;
      }
      const id = `${row.code}:${fact.key}:${fact.value}`;
      levels.set(
        id,
        Object.freeze({
          evidenceCode: row.code,
          factKey: fact.key,
          id,
          label,
          valueYuan: fenToYuan(fact.value),
        }),
      );
    }
  }
  return [...levels.values()];
}

function mapIndicators(
  rows: readonly ChartEvidenceRow[],
  candles: readonly ChartCandle[],
): ChartIndicator[] {
  const indicators = new Map<string, ChartIndicator>();
  for (const row of rows) {
    for (const fact of row.facts) {
      const label = indicatorLabels[fact.key];
      if (label === undefined || fact.unit !== "YUAN") {
        continue;
      }
      const value = numericValue(fact.value);
      const time = indicatorTime(row, fact.key);
      const id = `${row.code}:${fact.key}:${String(fact.value)}`;
      indicators.set(
        id,
        Object.freeze({
          evidenceCode: row.code,
          factKey: fact.key,
          id,
          label,
          plotTime: time === null ? null : chartTimeAtOrBefore(time, candles),
          time,
          value,
          valueText: String(fact.value),
        }),
      );
    }
  }
  return [...indicators.values()];
}

function indicatorTime(row: ChartEvidenceRow, indicatorFactKey: string): string | null {
  const timeFactKeys = indicatorTimeFactKeys[indicatorFactKey] ?? [];
  for (const timeFactKey of timeFactKeys) {
    const fact = row.facts.find(
      (candidate) =>
        candidate.key === timeFactKey &&
        (candidate.unit === "DATE" || candidate.unit === "DATETIME") &&
        typeof candidate.value === "string",
    );
    const value = fact?.value;
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return null;
}

function numericValue(value: EvidenceFactView["value"]): number | null {
  if (typeof value === "boolean") {
    return null;
  }
  const valueText = typeof value === "number" ? String(value) : value.trim();
  if (valueText.length === 0) {
    return null;
  }
  const numeric = Number(valueText);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  if (numeric === 0 && !isDecimalZero(valueText)) {
    return null;
  }
  return numeric;
}

function isDecimalZero(value: string): boolean {
  return /^[+-]?(?:0+(?:\.0*)?|\.0+)(?:[eE][+-]?\d+)?$/.test(value);
}

function markerAnchor(
  time: string,
  candles: readonly ChartCandle[],
  fallbackPriceFen: number | null,
): { plotTime: string | null; valueYuan: number | null } {
  let latest: ChartCandle | undefined;
  for (const candle of candles) {
    if (candle.time > time) {
      break;
    }
    latest = candle;
  }
  if (latest !== undefined) {
    return { plotTime: latest.time, valueYuan: latest.closeYuan };
  }
  return {
    plotTime: null,
    valueYuan: fallbackPriceFen === null ? null : fenToYuan(fallbackPriceFen),
  };
}

function chartTimeAtOrBefore(time: string, candles: readonly ChartCandle[]): string | null {
  let latest: string | null = null;
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(time);
  for (const candle of candles) {
    if (dateOnly) {
      const candleDate = candle.time.slice(0, 10);
      if (candleDate < time) {
        continue;
      }
      if (candleDate > time) {
        break;
      }
      latest = candle.time;
      continue;
    }
    const candleTime = candle.time;
    if (candleTime > time) {
      break;
    }
    latest = candle.time;
  }
  return latest;
}

function fenToYuan(value: number): number {
  return value / 100;
}

function compareText(left: string, right: string): number {
  return left === right ? 0 : left < right ? -1 : 1;
}

function freezeSeries(series: {
  alertMarkers: readonly ChartAlertMarker[];
  candles: readonly ChartCandle[];
  episodeLow: ChartEpisodeLow | null;
  evidenceRows: readonly ChartEvidenceRow[];
  indicators: readonly ChartIndicator[];
  priceLevels: readonly ChartPriceLevel[];
}): ChartSeries {
  return Object.freeze({
    alertMarkers: Object.freeze([...series.alertMarkers]),
    candles: Object.freeze([...series.candles]),
    episodeLow: series.episodeLow,
    evidenceRows: Object.freeze([...series.evidenceRows]),
    indicators: Object.freeze([...series.indicators]),
    priceLevels: Object.freeze([...series.priceLevels]),
  });
}
