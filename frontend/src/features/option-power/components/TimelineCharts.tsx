import { useEffect, useRef } from "react";
import {
  ColorType,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { prettySeriesName } from "../series";
import type { ChartBarPoint, ChartSeriesPoint } from "../types";
import styles from "./TimelineCharts.module.css";

const DISPLAY_DATE_TIME = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const DISPLAY_TICK = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

type TimelineChartsProps = {
  bars: ChartBarPoint[];
  primarySeries: ChartSeriesPoint[];
  secondarySeries: ChartSeriesPoint[];
  mode: "live" | "replay";
  primarySeriesName: string;
  secondarySeriesName: string;
  onCursorTimeChange: (ts: string | null) => void;
};

export function TimelineCharts({
  bars,
  primarySeries,
  secondarySeries,
  mode,
  primarySeriesName,
  secondarySeriesName,
  onCursorTimeChange,
}: TimelineChartsProps) {
  const priceRef = useRef<HTMLDivElement | null>(null);
  const primaryRef = useRef<HTMLDivElement | null>(null);
  const secondaryRef = useRef<HTMLDivElement | null>(null);
  const chartsRef = useRef<{
    price: IChartApi | null;
    primary: IChartApi | null;
    secondary: IChartApi | null;
  }>({ price: null, primary: null, secondary: null });
  const seriesRef = useRef<{
    candle: ISeriesApi<"Candlestick"> | null;
    volume: ISeriesApi<"Histogram"> | null;
    ma10: ISeriesApi<"Line"> | null;
    ma30: ISeriesApi<"Line"> | null;
    ma60: ISeriesApi<"Line"> | null;
    primary: ISeriesApi<"Line"> | null;
    secondary: ISeriesApi<"Line"> | null;
  }>({
    candle: null,
    volume: null,
    ma10: null,
    ma30: null,
    ma60: null,
    primary: null,
    secondary: null,
  });
  const fittedRef = useRef(false);
  const syncingRangeRef = useRef(false);
  const syncingCrosshairRef = useRef(false);
  const hasRenderableDataRef = useRef(false);
  const dataRef = useRef<{
    bars: Map<number, CandlestickData>;
    primary: Map<number, LineData>;
    secondary: Map<number, LineData>;
  }>({
    bars: new Map(),
    primary: new Map(),
    secondary: new Map(),
  });

  useEffect(() => {
    if (!priceRef.current || !primaryRef.current || !secondaryRef.current) {
      return;
    }

    const priceChart = createConfiguredChart(priceRef.current, 420);
    const primaryChart = createConfiguredChart(primaryRef.current, 180);
    const secondaryChart = createConfiguredChart(secondaryRef.current, 180);

    const candle = priceChart.addCandlestickSeries({
      upColor: "#f87171",
      downColor: "#4ade80",
      borderVisible: false,
      wickUpColor: "#f87171",
      wickDownColor: "#4ade80",
      priceScaleId: "price",
      priceLineVisible: false,
    });
    const volume = priceChart.addHistogramSeries({
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
      base: 0,
    });
    const ma10 = priceChart.addLineSeries({
      color: "#fbbf24",
      priceScaleId: "price",
      lineWidth: 2,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma30 = priceChart.addLineSeries({
      color: "#7dd3fc",
      priceScaleId: "price",
      lineWidth: 2,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma60 = priceChart.addLineSeries({
      color: "#c084fc",
      priceScaleId: "price",
      lineWidth: 2,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const primary = primaryChart.addLineSeries({
      color: "#fbbf24",
      lineWidth: 2,
      crosshairMarkerVisible: true,
      priceLineVisible: false,
    });
    const secondary = secondaryChart.addLineSeries({
      color: "#7dd3fc",
      lineWidth: 2,
      crosshairMarkerVisible: true,
      priceLineVisible: false,
    });

    const allCharts = [priceChart, primaryChart, secondaryChart];
    for (const sourceChart of allCharts) {
      sourceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (!range || syncingRangeRef.current) {
          return;
        }
        syncingRangeRef.current = true;
        for (const targetChart of allCharts) {
          if (targetChart !== sourceChart) {
            try {
              targetChart.timeScale().setVisibleRange(range);
            } catch (_error) {
              // Lightweight Charts can throw during bootstrap when sibling charts have no data yet.
            }
          }
        }
        syncingRangeRef.current = false;
      });
    }

    chartsRef.current = {
      price: priceChart,
      primary: primaryChart,
      secondary: secondaryChart,
    };
    priceChart.priceScale("price").applyOptions({
      scaleMargins: {
        top: 0.08,
        bottom: 0.24,
      },
    });
    priceChart.priceScale("volume").applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0.02,
      },
    });

    seriesRef.current = { candle, volume, ma10, ma30, ma60, primary, secondary };

    const chartDescriptors = [
      { chart: priceChart, kind: "price" as const },
      { chart: primaryChart, kind: "primary" as const },
      { chart: secondaryChart, kind: "secondary" as const },
    ];

    for (const descriptor of chartDescriptors) {
      descriptor.chart.subscribeCrosshairMove((param) => {
        handleCrosshairMove(
          descriptor.kind,
          param,
          {
            price: priceChart,
            primary: primaryChart,
            secondary: secondaryChart,
          },
          {
            candle,
            primary,
            secondary,
          },
          dataRef.current,
          syncingCrosshairRef,
          onCursorTimeChange,
        );
      });
    }

    const resizeObserver = new ResizeObserver(() => {
      if (priceRef.current) {
        priceChart.applyOptions({ width: priceRef.current.clientWidth });
      }
      if (primaryRef.current) {
        primaryChart.applyOptions({ width: primaryRef.current.clientWidth });
      }
      if (secondaryRef.current) {
        secondaryChart.applyOptions({ width: secondaryRef.current.clientWidth });
      }
    });
    resizeObserver.observe(priceRef.current);
    resizeObserver.observe(primaryRef.current);
    resizeObserver.observe(secondaryRef.current);

    return () => {
      resizeObserver.disconnect();
      priceChart.remove();
      primaryChart.remove();
      secondaryChart.remove();
      chartsRef.current = { price: null, primary: null, secondary: null };
      seriesRef.current = { candle: null, volume: null, ma10: null, ma30: null, ma60: null, primary: null, secondary: null };
      fittedRef.current = false;
      hasRenderableDataRef.current = false;
    };
  }, [onCursorTimeChange]);

  useEffect(() => {
    const { price, primary, secondary } = chartsRef.current;
    const { candle, volume, ma10, ma30, ma60, primary: primaryLine, secondary: secondaryLine } = seriesRef.current;
    if (!price || !primary || !secondary || !candle || !volume || !ma10 || !ma30 || !ma60 || !primaryLine || !secondaryLine) {
      return;
    }

    const normalizedBars = bars.map(normalizeBar).filter(Boolean) as CandlestickData[];
    const normalizedVolume = bars.map(normalizeVolume).filter(Boolean) as HistogramData[];
    const normalizedPrimarySeries = primarySeries.map(normalizeLine).filter(Boolean) as LineData[];
    const normalizedSecondarySeries = secondarySeries.map(normalizeLine).filter(Boolean) as LineData[];
    dataRef.current = {
      bars: new Map(normalizedBars.map((item) => [Number(item.time), item])),
      primary: new Map(normalizedPrimarySeries.map((item) => [Number(item.time), item])),
      secondary: new Map(normalizedSecondarySeries.map((item) => [Number(item.time), item])),
    };
    const hasRenderableData =
      normalizedBars.length > 0 || normalizedPrimarySeries.length > 0 || normalizedSecondarySeries.length > 0;

    candle.setData(normalizedBars);
    volume.setData(normalizedVolume);
    ma10.setData(buildMovingAverageSeries(normalizedBars, 10));
    ma30.setData(buildMovingAverageSeries(normalizedBars, 30));
    ma60.setData(buildMovingAverageSeries(normalizedBars, 60));
    primaryLine.setData(normalizedPrimarySeries);
    secondaryLine.setData(normalizedSecondarySeries);

    if (!hasRenderableData) {
      hasRenderableDataRef.current = false;
      fittedRef.current = false;
      return;
    }

    if (!fittedRef.current || !hasRenderableDataRef.current) {
      price.timeScale().fitContent();
      primary.timeScale().fitContent();
      secondary.timeScale().fitContent();
      fittedRef.current = true;
      hasRenderableDataRef.current = true;
      return;
    }

    if (mode === "live") {
      price.timeScale().scrollToRealTime();
      primary.timeScale().scrollToRealTime();
      secondary.timeScale().scrollToRealTime();
    }
  }, [bars, mode, primarySeries, secondarySeries]);

  return (
    <div className={styles.column}>
      <article className={styles.card}>
        <div className={styles.header}>
          <div>
            <p className={styles.label}>Primary</p>
            <h3 className={styles.title}>MTX Price</h3>
          </div>
          <p className={styles.legend}>MA10 / MA30 / MA60</p>
        </div>
        <div ref={priceRef} className={styles.chartBox} />
      </article>

      <article className={styles.card}>
        <div className={styles.header}>
          <div>
            <p className={styles.label}>Primary Indicator</p>
            <h3 className={styles.title}>{prettySeriesName(primarySeriesName)}</h3>
          </div>
        </div>
        <div ref={primaryRef} className={styles.chartBox} />
      </article>

      <article className={styles.card}>
        <div className={styles.header}>
          <div>
            <p className={styles.label}>Secondary Indicator</p>
            <h3 className={styles.title}>{prettySeriesName(secondarySeriesName)}</h3>
          </div>
        </div>
        <div ref={secondaryRef} className={styles.chartBox} />
      </article>
    </div>
  );
}

function createConfiguredChart(container: HTMLDivElement, height: number) {
  return createChart(container, {
    width: container.clientWidth,
    height,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: "#e2e8f0",
      fontFamily: "IBM Plex Sans, Noto Sans TC, sans-serif",
    },
    grid: {
      vertLines: { color: "rgba(255,255,255,0.05)" },
      horzLines: { color: "rgba(255,255,255,0.06)" },
    },
    crosshair: {
      vertLine: { color: "rgba(245,158,11,0.4)", width: 1 },
      horzLine: { color: "rgba(245,158,11,0.25)", width: 1 },
    },
    rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.16)" },
    localization: {
      timeFormatter: (time: Time) => formatChartTime(time, DISPLAY_DATE_TIME),
    },
    timeScale: {
      borderColor: "rgba(148, 163, 184, 0.16)",
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: Time) => formatChartTime(time, DISPLAY_TICK),
    },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    handleScale: {
      mouseWheel: true,
      pinch: true,
      axisPressedMouseMove: true,
      axisDoubleClickReset: false,
    },
  });
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
  if (Number.isNaN(time)) {
    return null;
  }
  return {
    time: time as Time,
    value: Number(item.value),
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

function toIsoTime(time: Time) {
  if (typeof time === "number") {
    return localIsoString(new Date(time * 1000));
  }
  if (typeof time === "string") {
    return time;
  }
  return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}T00:00:00`;
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

function formatChartTime(time: Time, formatter: Intl.DateTimeFormat) {
  if (typeof time === "number") {
    return formatter.format(new Date(time * 1000)).replace(/\//g, "-");
  }
  if (typeof time === "string") {
    return formatter.format(new Date(time)).replace(/\//g, "-");
  }
  return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
}

function handleCrosshairMove(
  source: "price" | "primary" | "secondary",
  param: MouseEventParams<Time>,
  charts: {
    price: IChartApi;
    primary: IChartApi;
    secondary: IChartApi;
  },
  series: {
    candle: ISeriesApi<"Candlestick">;
    primary: ISeriesApi<"Line">;
    secondary: ISeriesApi<"Line">;
  },
  data: {
    bars: Map<number, CandlestickData>;
    primary: Map<number, LineData>;
    secondary: Map<number, LineData>;
  },
  syncingCrosshairRef: { current: boolean },
  onCursorTimeChange: (ts: string | null) => void,
) {
  if (syncingCrosshairRef.current) {
    return;
  }
  if (!param.time) {
    syncingCrosshairRef.current = true;
    try {
      charts.price.clearCrosshairPosition();
      charts.primary.clearCrosshairPosition();
      charts.secondary.clearCrosshairPosition();
      onCursorTimeChange(null);
    } finally {
      syncingCrosshairRef.current = false;
    }
    return;
  }

  const time = Number(param.time);
  if (Number.isNaN(time)) {
    return;
  }

  syncingCrosshairRef.current = true;
  try {
    onCursorTimeChange(toIsoTime(param.time));
    const priceBar = data.bars.get(time);
    const primaryPoint = data.primary.get(time);
    const secondaryPoint = data.secondary.get(time);

    if (source !== "price" && priceBar) {
      charts.price.setCrosshairPosition(Number(priceBar.close), priceBar.time, series.candle);
    }
    if (source !== "primary" && primaryPoint) {
      charts.primary.setCrosshairPosition(Number(primaryPoint.value), primaryPoint.time, series.primary);
    }
    if (source !== "secondary" && secondaryPoint) {
      charts.secondary.setCrosshairPosition(Number(secondaryPoint.value), secondaryPoint.time, series.secondary);
    }
  } finally {
    syncingCrosshairRef.current = false;
  }
}
