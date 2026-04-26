import type { ChartSeriesPoint, IndicatorInterval, OptionPowerContract } from "./types";

export const PRIMARY_SERIES_OPTIONS = [
  "pressure_index",
  "raw_pressure",
  "trend_score",
  "chop_score",
  "reversal_risk",
  "vwap_distance_bps",
  "directional_efficiency_15m",
  "tick_imbalance_5m",
  "trade_intensity_ratio_30m",
  "range_ratio_5m_30m",
] as const;

export const SECONDARY_SERIES_OPTIONS = PRIMARY_SERIES_OPTIONS;

export const INDICATOR_INTERVAL_OPTIONS: IndicatorInterval[] = ["5s", "30s", "1m", "5m"];

const INTERVAL_MS: Record<IndicatorInterval, number> = {
  "5s": 5_000,
  "30s": 30_000,
  "1m": 60_000,
  "5m": 300_000,
};

export function resampleSeries(points: ChartSeriesPoint[], interval: IndicatorInterval): ChartSeriesPoint[] {
  if (!points.length || interval === "5s") {
    return points;
  }
  const bucketMs = INTERVAL_MS[interval];
  const buckets = new Map<number, ChartSeriesPoint>();
  for (const point of points) {
    const bucket = Math.floor(new Date(point.time).getTime() / bucketMs) * bucketMs;
    buckets.set(bucket, {
      time: localIsoString(new Date(bucket)),
      value: Number(point.value),
    });
  }
  return [...buckets.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([, point]) => point);
}

export function prettySeriesName(name: string) {
  if (name === "pressure_index") {
    return "PRESSURE INDEX";
  }
  if (name === "raw_pressure") {
    return "RAW PRESSURE";
  }
  if (name === "trend_score") {
    return "TREND SCORE";
  }
  if (name === "chop_score") {
    return "CHOP SCORE";
  }
  if (name === "reversal_risk") {
    return "REVERSAL RISK";
  }
  return String(name || "")
    .split("_")
    .map((part) => part.toUpperCase())
    .join(" ");
}

export function weightedSeriesName(name: string) {
  if (name === "pressure_index") {
    return "pressure_index_weighted";
  }
  if (name === "raw_pressure") {
    return "raw_pressure_weighted";
  }
  return null;
}

export function summarizeContractsBySide(contracts: OptionPowerContract[]) {
  return contracts.reduce(
    (accumulator, contract) => {
      if (contract.call_put === "call") {
        accumulator.call.cumulative_power += contract.cumulative_power;
        accumulator.call.power_1m_delta += contract.power_1m_delta;
      }
      if (contract.call_put === "put") {
        accumulator.put.cumulative_power += contract.cumulative_power;
        accumulator.put.power_1m_delta += contract.power_1m_delta;
      }
      return accumulator;
    },
    {
      call: { cumulative_power: 0, power_1m_delta: 0 },
      put: { cumulative_power: 0, power_1m_delta: 0 },
    },
  );
}

function localIsoString(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}
