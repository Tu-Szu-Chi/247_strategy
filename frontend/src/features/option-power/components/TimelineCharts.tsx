import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  HistogramData,
  LineStyle,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type Range,
  type Time,
} from "lightweight-charts";
import type { ChartBarPoint, ChartSeriesPoint } from "../types";
import { normalizeChartData, type NormalizedChartData } from "../chartData";
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

export type IndicatorPanelSeries = {
  id: string;
  label: string;
  points: ChartSeriesPoint[];
  color: string;
  dashed?: boolean;
  kind?: "line" | "histogram";
  priceScaleId?: "left" | "right";
};

type TimelineChartsProps = {
  bars: ChartBarPoint[];
  pressureSeries: IndicatorPanelSeries[];
  rawPressureSeries: IndicatorPanelSeries[];
  chopSeries: IndicatorPanelSeries[];
  structureSeries: IndicatorPanelSeries[];
  biasSeries: IndicatorPanelSeries[];
  signalSeries: IndicatorPanelSeries[];
  contextSeries: IndicatorPanelSeries[];
  trendQualitySeries: IndicatorPanelSeries[];
  cvdSeries: IndicatorPanelSeries[];
  rangeStateSeries: IndicatorPanelSeries[];
  ivSkewSeries: IndicatorPanelSeries[];
  visiblePanelIds?: PanelId[];
  mode: "live" | "replay";
  onCursorTimeChange: (ts: string | null) => void;
  onVisibleRangeChange?: (range: { start: string; end: string; hasLeftWhitespace?: boolean; hasRightWhitespace?: boolean }) => void;
  viewKey?: string;
};

type PanelId = "price" | "pressure" | "regime" | "bias" | "signal" | "chop" | "structure" | "context" | "trendQuality" | "cvd" | "rangeState" | "ivSkew";

const PANEL_SPECS: Array<{
  id: PanelId;
  slot: "price" | "indicator";
  label: string;
  title: string;
  legend: string;
  height: number;
}> = [
  {
    id: "price",
    slot: "price",
    label: "Primary",
    title: "MTX Price",
    legend: "MA10 / MA30 / MA60 + volume",
    height: 360,
  },
  {
    id: "pressure",
    slot: "indicator",
    label: "Pressure",
    title: "Pressure Index + Regime",
    legend: "index + weighted + state band",
    height: 132,
  },
  {
    id: "regime",
    slot: "indicator",
    label: "Pressure Raw",
    title: "Raw Pressure",
    legend: "raw + weighted",
    height: 120,
  },
  {
    id: "bias",
    slot: "indicator",
    label: "Bias",
    title: "Bias Signal",
    legend: "long / neutral / short",
    height: 120,
  },
  {
    id: "signal",
    slot: "indicator",
    label: "Signal",
    title: "Signal State",
    legend: "long / neutral / short",
    height: 120,
  },
  {
    id: "chop",
    slot: "indicator",
    label: "Chop",
    title: "Chop Score",
    legend: "chop intensity",
    height: 120,
  },
  {
    id: "structure",
    slot: "indicator",
    label: "Structure",
    title: "Structure State",
    legend: "push up / balanced / push down",
    height: 120,
  },
  {
    id: "context",
    slot: "indicator",
    label: "Context",
    title: "VWAP Distance",
    legend: "distance from session vwap",
    height: 120,
  },
  {
    id: "trendQuality",
    slot: "indicator",
    label: "Trend",
    title: "Trend Quality",
    legend: "quality line + bias state",
    height: 132,
  },
  {
    id: "cvd",
    slot: "indicator",
    label: "Flow",
    title: "Flow Impulse",
    legend: "impulse line + flow state",
    height: 132,
  },
  {
    id: "rangeState",
    slot: "indicator",
    label: "Range",
    title: "Range State",
    legend: "compressed / normal / expanding",
    height: 132,
  },
  {
    id: "ivSkew",
    slot: "indicator",
    label: "IV",
    title: "IV Skew",
    legend: "call wing - put wing",
    height: 132,
  },
];

export function TimelineCharts({
  bars,
  pressureSeries,
  rawPressureSeries,
  chopSeries,
  structureSeries,
  biasSeries,
  signalSeries,
  contextSeries,
  trendQualitySeries,
  cvdSeries,
  rangeStateSeries,
  ivSkewSeries,
  visiblePanelIds,
  mode,
  onCursorTimeChange,
  onVisibleRangeChange,
  viewKey,
}: TimelineChartsProps) {
  const panelData = useMemo<Record<Exclude<PanelId, "price">, IndicatorPanelSeries[]>>(
    () => ({
      pressure: pressureSeries,
      regime: rawPressureSeries,
      bias: biasSeries,
      signal: signalSeries,
      chop: chopSeries,
      structure: structureSeries,
      context: contextSeries,
      trendQuality: trendQualitySeries,
      cvd: cvdSeries,
      rangeState: rangeStateSeries,
      ivSkew: ivSkewSeries,
    }),
    [biasSeries, chopSeries, contextSeries, cvdSeries, ivSkewSeries, pressureSeries, rangeStateSeries, rawPressureSeries, signalSeries, structureSeries, trendQualitySeries],
  );
  const visiblePanelKey = visiblePanelIds?.join(",") ?? "";
  const visiblePanels = useMemo(() => {
    if (!visiblePanelIds?.length) {
      return PANEL_SPECS;
    }
    const allowed = new Set(visiblePanelIds);
    return PANEL_SPECS.filter((panel) => allowed.has(panel.id));
  }, [visiblePanelKey]);
  const panelConfigKey = useMemo(
    () => JSON.stringify(
      visiblePanels.map((panel) => ({
        id: panel.id,
        series: panel.id === "price"
          ? []
          : panelData[panel.id].map((series) => ({
              id: series.id,
              kind: series.kind ?? "line",
              color: series.color,
              dashed: Boolean(series.dashed),
              priceScaleId: series.priceScaleId ?? "right",
            })),
      })),
    ),
    [panelData, visiblePanels],
  );

  const containerRefs = useRef<Record<PanelId, HTMLDivElement | null>>({
    price: null,
    pressure: null,
    regime: null,
    chop: null,
    structure: null,
    bias: null,
    signal: null,
    context: null,
    trendQuality: null,
    cvd: null,
    rangeState: null,
    ivSkew: null,
  });
  const chartsRef = useRef<Record<PanelId, IChartApi | null>>({
    price: null,
    pressure: null,
    regime: null,
    chop: null,
    structure: null,
    bias: null,
    signal: null,
    context: null,
    trendQuality: null,
    cvd: null,
    rangeState: null,
    ivSkew: null,
  });
  const indicatorSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
  const indicatorHistogramRef = useRef<Record<string, ISeriesApi<"Histogram">>>({});
  const priceSeriesRef = useRef<{
    candle: ISeriesApi<"Candlestick"> | null;
    volume: ISeriesApi<"Histogram"> | null;
    ma10: ISeriesApi<"Line"> | null;
    ma30: ISeriesApi<"Line"> | null;
    ma60: ISeriesApi<"Line"> | null;
  }>({
    candle: null,
    volume: null,
    ma10: null,
    ma30: null,
    ma60: null,
  });
  const representativeSeriesRef = useRef<Record<PanelId, ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | ISeriesApi<"Candlestick"> | null>>({
    price: null,
    pressure: null,
    regime: null,
    chop: null,
    structure: null,
    bias: null,
    signal: null,
    context: null,
    trendQuality: null,
    cvd: null,
    rangeState: null,
    ivSkew: null,
  });
  const fittedRef = useRef(false);
  const liveAutoFollowRef = useRef(true);
  const syncingRangeRef = useRef(false);
  const syncingCrosshairRef = useRef(false);
  const suppressVisibleRangeChangeRef = useRef(false);
  const suppressVisibleRangeTimerRef = useRef<number | null>(null);
  const visibleRangeTimeoutRef = useRef<number | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const workerRequestIdRef = useRef(0);
  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange);
  const normalizedDataRef = useRef<NormalizedChartData>(normalizeChartData({
    bars: [],
    panelData: {},
  }));
  const [normalizedData, setNormalizedData] = useState<NormalizedChartData>(() => normalizeChartData({
    bars: [],
    panelData: {},
  }));
  const dataRef = useRef<Record<string, Map<number, LineData | CandlestickData>>>({
    price: new Map(),
    pressure: new Map(),
    regime: new Map(),
    chop: new Map(),
    structure: new Map(),
    bias: new Map(),
    signal: new Map(),
    context: new Map(),
    trendQuality: new Map(),
    cvd: new Map(),
    rangeState: new Map(),
    ivSkew: new Map(),
  });

  useEffect(() => {
    onVisibleRangeChangeRef.current = onVisibleRangeChange;
  }, [onVisibleRangeChange]);

  useEffect(() => {
    normalizedDataRef.current = normalizedData;
  }, [normalizedData]);

  const suppressProgrammaticVisibleRangeChange = () => {
    suppressVisibleRangeChangeRef.current = true;
    if (suppressVisibleRangeTimerRef.current !== null) {
      window.clearTimeout(suppressVisibleRangeTimerRef.current);
    }
    suppressVisibleRangeTimerRef.current = window.setTimeout(() => {
      suppressVisibleRangeChangeRef.current = false;
      suppressVisibleRangeTimerRef.current = null;
    }, 80);
    if (visibleRangeTimeoutRef.current !== null) {
      window.clearTimeout(visibleRangeTimeoutRef.current);
      visibleRangeTimeoutRef.current = null;
    }
  };

  useEffect(() => {
    const hasAllContainers = visiblePanels.every((panel) => containerRefs.current[panel.id]);
    if (!hasAllContainers) {
      return;
    }

    const charts = visiblePanels.reduce<Partial<Record<PanelId, IChartApi>>>((accumulator, panel) => {
      const container = containerRefs.current[panel.id];
      if (!container) {
        throw new Error(`Missing chart container for ${panel.id}`);
      }
      accumulator[panel.id] = createConfiguredChart(container, panel.height);
      return accumulator;
    }, {});

    let candle: ISeriesApi<"Candlestick"> | null = null;
    let volume: ISeriesApi<"Histogram"> | null = null;
    let ma10: ISeriesApi<"Line"> | null = null;
    let ma30: ISeriesApi<"Line"> | null = null;
    let ma60: ISeriesApi<"Line"> | null = null;
    if (charts.price) {
      candle = charts.price.addCandlestickSeries({
        upColor: "#f87171",
        downColor: "#4ade80",
        borderVisible: false,
        wickUpColor: "#f87171",
        wickDownColor: "#4ade80",
        priceScaleId: "right",
        priceLineVisible: false,
      });
      volume = charts.price.addHistogramSeries({
        priceScaleId: "volume",
        priceLineVisible: false,
        lastValueVisible: false,
        base: 0,
      });
      ma10 = charts.price.addLineSeries({
        color: "#fbbf24",
        priceScaleId: "right",
        lineWidth: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ma30 = charts.price.addLineSeries({
        color: "#7dd3fc",
        priceScaleId: "right",
        lineWidth: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ma60 = charts.price.addLineSeries({
        color: "#c084fc",
        priceScaleId: "right",
        lineWidth: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      charts.price.priceScale("right").applyOptions({
        visible: true,
        scaleMargins: {
          top: 0.08,
          bottom: 0.24,
        },
      });
      charts.price.priceScale("volume").applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0.02,
        },
      });
    }

    const indicatorSeries: Record<string, ISeriesApi<"Line">> = {};
    const indicatorHistograms: Record<string, ISeriesApi<"Histogram">> = {};
    for (const panel of visiblePanels) {
      if (panel.id === "price") {
        continue;
      }
      const chart = charts[panel.id];
      if (!chart) {
        continue;
      }
      for (const series of panelData[panel.id]) {
        if (series.kind === "histogram") {
          indicatorHistograms[series.id] = chart.addHistogramSeries({
            priceScaleId: series.priceScaleId ?? "right",
            priceLineVisible: false,
            lastValueVisible: false,
            base: 0,
          });
          continue;
        }
        indicatorSeries[series.id] = chart.addLineSeries({
          color: series.color,
          lineWidth: 2,
          lineStyle: series.dashed ? LineStyle.Dashed : LineStyle.Solid,
          crosshairMarkerVisible: !series.dashed,
          priceLineVisible: false,
          lastValueVisible: !series.dashed,
          priceScaleId: series.priceScaleId ?? "right",
        });
      }
      if (panelData[panel.id].some((series) => series.priceScaleId === "left")) {
        chart.priceScale("left").applyOptions({
          visible: true,
          borderColor: "rgba(148, 163, 184, 0.16)",
          autoScale: true,
        });
      }
    }

    const allCharts = visiblePanels
      .map((panel) => charts[panel.id])
      .filter(Boolean) as IChartApi[];
    for (const sourceChart of allCharts) {
      sourceChart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        if (!logicalRange || syncingRangeRef.current) {
          return;
        }
        syncingRangeRef.current = true;
        for (const targetChart of allCharts) {
          if (targetChart !== sourceChart) {
            try {
              targetChart.timeScale().setVisibleLogicalRange(logicalRange);
            } catch (_error) {
              // ignore bootstrap sync errors
            }
          }
        }
        syncingRangeRef.current = false;
        if (mode === "live") {
          if (suppressVisibleRangeChangeRef.current) {
            return;
          }
          liveAutoFollowRef.current = sourceChart.timeScale().scrollPosition() <= 0.5;
        }
        if (mode === "replay" && onVisibleRangeChangeRef.current) {
          if (suppressVisibleRangeChangeRef.current) {
            return;
          }
          if (!fittedRef.current) {
            return;
          }
          if (visibleRangeTimeoutRef.current !== null) {
            window.clearTimeout(visibleRangeTimeoutRef.current);
          }
          const visibleRange = sourceChart.timeScale().getVisibleRange();
          const requestedRange = resolveRequestedVisibleRange(
            normalizedDataRef.current.bars,
            logicalRange,
            visibleRange?.from as Time | undefined,
            visibleRange?.to as Time | undefined,
          );
          visibleRangeTimeoutRef.current = window.setTimeout(() => {
            onVisibleRangeChangeRef.current?.(requestedRange);
          }, 180);
        }
      });
    }

    for (const panel of visiblePanels) {
      const chart = charts[panel.id];
      if (!chart) {
        continue;
      }
      chart.subscribeCrosshairMove((param) => {
        handleCrosshairMove(
          panel.id,
          param,
          charts,
          representativeSeriesRef.current,
          dataRef.current,
          syncingCrosshairRef,
          onCursorTimeChange,
        );
      });
    }

    const resizeObserver = new ResizeObserver(() => {
      for (const panel of visiblePanels) {
        const container = containerRefs.current[panel.id];
        const chart = charts[panel.id];
        if (container && chart) {
          chart.applyOptions({ width: container.clientWidth });
        }
      }
    });
    for (const panel of visiblePanels) {
      const container = containerRefs.current[panel.id];
      if (container) {
        resizeObserver.observe(container);
      }
    }

    chartsRef.current = {
      price: charts.price ?? null,
      pressure: charts.pressure ?? null,
      regime: charts.regime ?? null,
      chop: charts.chop ?? null,
      structure: charts.structure ?? null,
      bias: charts.bias ?? null,
      signal: charts.signal ?? null,
      context: charts.context ?? null,
      trendQuality: charts.trendQuality ?? null,
      cvd: charts.cvd ?? null,
      rangeState: charts.rangeState ?? null,
      ivSkew: charts.ivSkew ?? null,
    };
    priceSeriesRef.current = { candle, volume, ma10, ma30, ma60 };
    indicatorSeriesRef.current = indicatorSeries;
    indicatorHistogramRef.current = indicatorHistograms;

    return () => {
      if (visibleRangeTimeoutRef.current !== null) {
        window.clearTimeout(visibleRangeTimeoutRef.current);
        visibleRangeTimeoutRef.current = null;
      }
      if (suppressVisibleRangeTimerRef.current !== null) {
        window.clearTimeout(suppressVisibleRangeTimerRef.current);
        suppressVisibleRangeTimerRef.current = null;
      }
      suppressVisibleRangeChangeRef.current = false;
      resizeObserver.disconnect();
      for (const chart of allCharts) {
        chart.remove();
      }
      chartsRef.current = {
        price: null,
        pressure: null,
        regime: null,
        chop: null,
        structure: null,
        bias: null,
        signal: null,
        context: null,
        trendQuality: null,
        cvd: null,
        rangeState: null,
        ivSkew: null,
      };
      indicatorSeriesRef.current = {};
      indicatorHistogramRef.current = {};
      priceSeriesRef.current = {
        candle: null,
        volume: null,
        ma10: null,
        ma30: null,
        ma60: null,
      };
      representativeSeriesRef.current = {
        price: null,
        pressure: null,
        regime: null,
        chop: null,
        structure: null,
        bias: null,
        signal: null,
        context: null,
        trendQuality: null,
        cvd: null,
        rangeState: null,
        ivSkew: null,
      };
      fittedRef.current = false;
    };
  }, [mode, onCursorTimeChange, panelConfigKey, visiblePanels]);

  useEffect(() => {
    fittedRef.current = false;
    liveAutoFollowRef.current = true;
  }, [viewKey]);

  useEffect(() => {
    const requestId = workerRequestIdRef.current + 1;
    workerRequestIdRef.current = requestId;
    const payload = {
      bars,
      panelData,
    };
    if (typeof Worker === "undefined") {
      setNormalizedData(normalizeChartData(payload));
      return;
    }
    if (!workerRef.current) {
      workerRef.current = new Worker(new URL("../chartData.worker.ts", import.meta.url), { type: "module" });
    }
    const worker = workerRef.current;
    const handleMessage = (event: MessageEvent<{ type: string; requestId: number; payload: NormalizedChartData }>) => {
      if (event.data.type !== "normalized" || event.data.requestId !== workerRequestIdRef.current) {
        return;
      }
      setNormalizedData(event.data.payload);
    };
    worker.addEventListener("message", handleMessage);
    worker.postMessage({ type: "normalize", requestId, payload });
    return () => {
      worker.removeEventListener("message", handleMessage);
    };
  }, [bars, panelData]);

  useEffect(() => {
    const normalizedBars = normalizedData.bars;
    const normalizedVolume = normalizedData.volume;
    const showsPricePanel = visiblePanels.some((panel) => panel.id === "price");
    const previousTimeRange = fittedRef.current
      ? capturePrimaryVisibleTimeRange(chartsRef.current)
      : null;
    const previousLogicalRange = fittedRef.current
      ? chartsRef.current.price?.timeScale().getVisibleLogicalRange() ?? null
      : null;
    const shouldRestoreLogicalRange = fittedRef.current && (mode !== "live" || !liveAutoFollowRef.current);
    // Helper for incremental update
    const syncSeriesData = (series: any, newData: any[], existingMap: Map<number, any>, updateMap?: Map<number, any>) => {
      if (newData.length === 0) {
        series.setData([]);
        if (updateMap) updateMap.clear();
        return;
      }
      if (existingMap.size === 0) {
        series.setData(newData);
        if (updateMap) {
          for (const item of newData) updateMap.set(Number(item.time), item);
        }
        return;
      }

      let maxTime = -Infinity;
      let minTime = Infinity;
      for (const t of existingMap.keys()) {
        if (t > maxTime) maxTime = t;
        if (t < minTime) minTime = t;
      }

      const firstNewTime = Number(newData[0].time);
      if (firstNewTime !== minTime || newData.length < existingMap.size - 2) {
        series.setData(newData);
        if (updateMap) {
          updateMap.clear();
          for (const item of newData) updateMap.set(Number(item.time), item);
        }
        return;
      }

      for (let i = 0; i < newData.length; i++) {
        const t = Number(newData[i].time);
        if (t >= maxTime) {
          series.update(newData[i]);
        }
        if (updateMap && t >= maxTime) {
          updateMap.set(t, newData[i]);
        }
      }
    };

    if (showsPricePanel) {
      const { candle, volume, ma10, ma30, ma60 } = priceSeriesRef.current;
      if (!candle || !volume || !ma10 || !ma30 || !ma60) {
        return;
      }
      const existingPriceMap = dataRef.current.price;
      
      syncSeriesData(candle, normalizedBars, existingPriceMap, existingPriceMap);
      
      // We don't need updateMap for these because we only use existingPriceMap to check the timeline
      syncSeriesData(volume, normalizedVolume, existingPriceMap);
      syncSeriesData(ma10, normalizedData.ma10, existingPriceMap);
      syncSeriesData(ma30, normalizedData.ma30, existingPriceMap);
      syncSeriesData(ma60, normalizedData.ma60, existingPriceMap);

      representativeSeriesRef.current.price = candle;
    } else {
      dataRef.current.price.clear();
      representativeSeriesRef.current.price = null;
    }

    for (const panel of visiblePanels) {
      if (panel.id === "price") {
        continue;
      }
      let representativeSet = false;
      const existingPanelMap = dataRef.current[panel.id] || new Map<number, any>();
      
      for (const series of panelData[panel.id]) {
        if (series.kind === "histogram") {
          const target = indicatorHistogramRef.current[series.id];
          if (!target) continue;
          
          const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as HistogramData[];
          syncSeriesData(target, normalized, existingPanelMap, existingPanelMap);
          
          if (!representativeSet && normalized.length > 0) {
            representativeSeriesRef.current[panel.id] = target;
            representativeSet = true;
          }
          continue;
        }
        
        const target = indicatorSeriesRef.current[series.id];
        if (!target) continue;
        
        const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as LineData[];
        syncSeriesData(target, normalized, existingPanelMap, existingPanelMap);
        
        if (!representativeSet && normalized.length > 0) {
          representativeSeriesRef.current[panel.id] = target;
          representativeSet = true;
        }
      }
      
      if (!representativeSet) {
        representativeSeriesRef.current[panel.id] = null;
      }
    }

    const hasRenderableData = (showsPricePanel && normalizedBars.length > 0) || PANEL_SPECS.some((panel) => {
      if (!visiblePanels.some((visiblePanel) => visiblePanel.id === panel.id)) {
        return false;
      }
      if (panel.id === "price") {
        return false;
      }
      return panelData[panel.id].some((series) => series.points.length > 0);
    });
    if (!hasRenderableData) {
      fittedRef.current = false;
      return;
    }

    if (!fittedRef.current) {
      const initialRange = mode === "replay" ? initialReplayVisibleRange(normalizedData) : null;
      suppressProgrammaticVisibleRangeChange();
      for (const panel of visiblePanels) {
        const timeScale = chartsRef.current[panel.id]?.timeScale();
        if (initialRange) {
          timeScale?.setVisibleRange(initialRange);
        } else {
          timeScale?.fitContent();
        }
      }
      fittedRef.current = true;
      return;
    }

    if (mode === "live") {
      if (liveAutoFollowRef.current) {
        suppressProgrammaticVisibleRangeChange();
        for (const panel of visiblePanels) {
          chartsRef.current[panel.id]?.timeScale().scrollToRealTime();
        }
      } else if (shouldRestoreLogicalRange) {
        suppressProgrammaticVisibleRangeChange();
        restoreSyncedVisibleRange(chartsRef.current, visiblePanels, previousTimeRange, previousLogicalRange);
      }
      return;
    }

    if (shouldRestoreLogicalRange) {
      suppressProgrammaticVisibleRangeChange();
      restoreSyncedVisibleRange(chartsRef.current, visiblePanels, previousTimeRange, previousLogicalRange);
    }
  }, [mode, normalizedData, panelData, visiblePanels]);

  useEffect(() => {
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  return (
    <div className={styles.grid}>
      {visiblePanels.map((panel) => (
        <article
          key={panel.id}
          className={`${styles.card} ${panel.slot === "price" ? styles.priceCard : styles.indicatorCard}`}
        >
          <div className={styles.header}>
            <div>
              <p className={styles.label}>{panel.label}</p>
              <h3 className={styles.title}>{panel.title}</h3>
            </div>
            <p className={styles.legend}>{panel.legend}</p>
          </div>
          <div
            ref={(node) => {
              containerRefs.current[panel.id] = node;
            }}
            className={styles.chartBox}
            data-testid={`timeline-chart-${panel.id}`}
          />
          {panel.id === "price" ? null : (
            <div className={styles.seriesLegend}>
              {panelData[panel.id].map((series) => (
                <span key={series.id} className={styles.legendItem}>
                  <span
                    className={styles.legendSwatch}
                    style={{
                      backgroundColor: series.color,
                      opacity: series.dashed ? 0.45 : 1,
                    }}
                  />
                  {series.label}
                </span>
              ))}
            </div>
          )}
        </article>
      ))}
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
    rightPriceScale: {
      visible: true,
      borderColor: "rgba(148, 163, 184, 0.16)",
      autoScale: true,
    },
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

function capturePrimaryVisibleTimeRange(
  charts: Record<PanelId, IChartApi | null>,
) {
  return charts.price?.timeScale().getVisibleRange() ?? null;
}

function restoreSyncedVisibleRange(
  charts: Record<PanelId, IChartApi | null>,
  panels: Array<{ id: PanelId }>,
  timeRange: Range<Time> | null,
  fallbackLogicalRange: LogicalRange | null,
) {
  if (timeRange) {
    for (const panel of panels) {
      try {
        charts[panel.id]?.timeScale().setVisibleRange(timeRange);
      } catch (_error) {
        // Some panels can briefly lack enough series data while they bootstrap.
      }
    }
    return;
  }
  if (!fallbackLogicalRange) {
    return;
  }
  for (const panel of panels) {
    try {
      charts[panel.id]?.timeScale().setVisibleLogicalRange(fallbackLogicalRange);
    } catch (_error) {
      // The previous logical range can briefly be outside the data bounds while panels bootstrap.
    }
  }
}

function initialReplayVisibleRange(data: NormalizedChartData): Range<Time> | null {
  if (data.bars.length < 2) {
    return null;
  }
  return {
    from: data.bars[0].time,
    to: data.bars[data.bars.length - 1].time,
  };
}

export function resolveRequestedVisibleRange(
  bars: CandlestickData[],
  logicalRange: LogicalRange,
  visibleFrom?: Time,
  visibleTo?: Time,
) {
  const leftWhitespaceBars = Math.max(0, Math.ceil(0 - logicalRange.from));
  const rightWhitespaceBars = Math.max(0, Math.ceil(logicalRange.to - (bars.length - 1)));
  const fallbackRange = {
    start: visibleFrom !== undefined ? toIsoTime(visibleFrom) : "",
    end: visibleTo !== undefined ? toIsoTime(visibleTo) : "",
    hasLeftWhitespace: leftWhitespaceBars > 0,
    hasRightWhitespace: rightWhitespaceBars > 0,
  };
  if (bars.length === 0) {
    return fallbackRange;
  }

  const firstBarTime = Number(bars[0].time);
  const lastBarTime = Number(bars[bars.length - 1].time);
  if (Number.isNaN(firstBarTime) || Number.isNaN(lastBarTime)) {
    return fallbackRange;
  }

  const intervalSeconds = inferBarIntervalSeconds(bars);
  const logicalStart = localIsoString(new Date((firstBarTime + Math.floor(logicalRange.from) * intervalSeconds) * 1000));
  const logicalEnd = localIsoString(new Date((firstBarTime + Math.ceil(logicalRange.to) * intervalSeconds) * 1000));

  const requestedStart = leftWhitespaceBars > 0
    ? localIsoString(new Date((firstBarTime - leftWhitespaceBars * intervalSeconds) * 1000))
    : fallbackRange.start || logicalStart;
  const requestedEnd = rightWhitespaceBars > 0
    ? localIsoString(new Date((lastBarTime + rightWhitespaceBars * intervalSeconds) * 1000))
    : fallbackRange.end || logicalEnd;

  return {
    start: requestedStart,
    end: requestedEnd,
    hasLeftWhitespace: leftWhitespaceBars > 0,
    hasRightWhitespace: rightWhitespaceBars > 0,
  };
}

function inferBarIntervalSeconds(bars: CandlestickData[]) {
  if (bars.length < 2) {
    return 60;
  }
  const deltas: number[] = [];
  for (let index = 1; index < bars.length; index += 1) {
    const previous = Number(bars[index - 1].time);
    const current = Number(bars[index].time);
    const delta = current - previous;
    if (delta > 0 && Number.isFinite(delta)) {
      deltas.push(delta);
    }
  }
  if (deltas.length === 0) {
    return 60;
  }
  deltas.sort((left, right) => left - right);
  return deltas[Math.floor(deltas.length / 2)];
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
  source: PanelId,
  param: MouseEventParams<Time>,
  charts: Partial<Record<PanelId, IChartApi>>,
  representatives: Record<PanelId, ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | ISeriesApi<"Candlestick"> | null>,
  data: Record<string, Map<number, LineData | CandlestickData>>,
  syncingCrosshairRef: { current: boolean },
  onCursorTimeChange: (ts: string | null) => void,
) {
  if (syncingCrosshairRef.current) {
    return;
  }
  if (!param.time) {
    syncingCrosshairRef.current = true;
    try {
      for (const panel of PANEL_SPECS) {
        charts[panel.id]?.clearCrosshairPosition();
      }
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
    for (const panel of PANEL_SPECS) {
      if (panel.id === source) {
        continue;
      }
      const point = data[panel.id].get(time);
      const series = representatives[panel.id];
      const chart = charts[panel.id];
      if (!point || !series || !chart) {
        continue;
      }
      if ("close" in point) {
        chart.setCrosshairPosition(Number(point.close), point.time, series);
      } else {
        chart.setCrosshairPosition(Number(point.value), point.time, series);
      }
    }
  } finally {
    syncingCrosshairRef.current = false;
  }
}
