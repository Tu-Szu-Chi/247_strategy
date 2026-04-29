import type { CandlestickData, HistogramData, LineData, Time } from "lightweight-charts";
import type { ChartBarPoint, ChartSeriesPoint } from "./types";

export type ChartDataSeriesInput = {
  id: string;
  points: ChartSeriesPoint[];
  kind?: "line" | "histogram";
};

export type ChartDataInput = {
  bars: ChartBarPoint[];
  panelData: Record<string, ChartDataSeriesInput[]>;
};

export type NormalizedChartData = {
  bars: CandlestickData[];
  volume: HistogramData[];
  ma10: LineData[];
  ma30: LineData[];
  ma60: LineData[];
  panels: Record<string, Record<string, Array<LineData | HistogramData>>>;
};

export function normalizeChartData(input: ChartDataInput): NormalizedChartData {
  const normalizedBars = input.bars.map(normalizeBar).filter(Boolean) as CandlestickData[];
  const normalizedVolume = input.bars.map(normalizeVolume).filter(Boolean) as HistogramData[];
  const panels: NormalizedChartData["panels"] = {};

  for (const [panelId, seriesList] of Object.entries(input.panelData)) {
    panels[panelId] = {};
    for (const series of seriesList) {
      panels[panelId][series.id] = series.kind === "histogram"
        ? series.points.map(normalizeHistogramBand).filter(Boolean) as HistogramData[]
        : series.points.map(normalizeLine).filter(Boolean) as LineData[];
    }
  }

  return {
    bars: normalizedBars,
    volume: normalizedVolume,
    ma10: buildMovingAverageSeries(normalizedBars, 10),
    ma30: buildMovingAverageSeries(normalizedBars, 30),
    ma60: buildMovingAverageSeries(normalizedBars, 60),
    panels,
  };
}

function normalizeBar(item: ChartBarPoint): CandlestickData | null {
  const time = toUnixSeconds(item.time);
  if (Number.isNaN(time)) {
    return null;
  }
  return {
    time: time as Time,
    open: Number(item.open),
    high: Number(item.high),
    low: Number(item.low),
    close: Number(item.close),
  };
}

function normalizeLine(item: ChartSeriesPoint): LineData | null {
  const time = toUnixSeconds(item.time);
  const value = Number(item.value);
  if (Number.isNaN(time) || Number.isNaN(value)) {
    return null;
  }
  return {
    time: time as Time,
    value,
  };
}

function normalizeVolume(item: ChartBarPoint): HistogramData | null {
  const time = toUnixSeconds(item.time);
  const value = Number(item.volume ?? 0);
  if (Number.isNaN(time) || Number.isNaN(value)) {
    return null;
  }
  const isUp = Number(item.close) >= Number(item.open);
  return {
    time: time as Time,
    value,
    color: isUp ? "rgba(248, 113, 113, 0.22)" : "rgba(74, 222, 128, 0.22)",
  };
}

function normalizeHistogramBand(item: ChartSeriesPoint): HistogramData | null {
  const time = toUnixSeconds(item.time);
  const value = Number(item.value);
  if (Number.isNaN(time) || Number.isNaN(value)) {
    return null;
  }
  return {
    time: time as Time,
    value,
    color: value > 0
      ? "rgba(248, 113, 113, 0.28)"
      : value < 0
        ? "rgba(168, 85, 247, 0.28)"
        : "rgba(148, 163, 184, 0.16)",
  };
}

function buildMovingAverageSeries(bars: CandlestickData[], period: number): LineData[] {
  const points: LineData[] = [];
  let rollingSum = 0;
  for (let index = 0; index < bars.length; index += 1) {
    rollingSum += Number(bars[index].close || 0);
    if (index >= period) {
      rollingSum -= Number(bars[index - period].close || 0);
    }
    if (index < period - 1) {
      continue;
    }
    points.push({
      time: bars[index].time,
      value: Number((rollingSum / period).toFixed(2)),
    });
  }
  return points;
}

function toUnixSeconds(value: string) {
  return Math.floor(new Date(value).getTime() / 1000);
}
