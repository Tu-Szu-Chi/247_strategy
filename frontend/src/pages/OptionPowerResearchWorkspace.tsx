import { useCallback, useEffect, useMemo, useState } from "react";
import { MetricCard } from "../features/option-power/components/MetricCard";
import {
  TimelineCharts,
  type IndicatorPanelSeries,
} from "../features/option-power/components/TimelineCharts";
import {
  INDICATOR_INTERVAL_OPTIONS,
  resampleSeries,
  summarizeContractsBySide,
} from "../features/option-power/series";
import { selectExpiry } from "../features/option-power/selectors";
import { useOptionPowerLive } from "../features/option-power/useOptionPowerLive";
import { useOptionPowerReplay } from "../features/option-power/useOptionPowerReplay";
import type { IndicatorInterval, OptionPowerSnapshot } from "../features/option-power/types";
import styles from "./ResearchPage.module.css";

type OptionPowerResearchWorkspaceProps = {
  mode: "live" | "replay";
};

export function OptionPowerResearchWorkspace({
  mode,
}: OptionPowerResearchWorkspaceProps) {
  const hiddenLivePanels = useMemo(
    () => new Set(["price", "context", "trendQuality"] as const),
    [],
  );
  const liveShowsPricePanel = !hiddenLivePanels.has("price");
  const [indicatorInterval, setIndicatorInterval] = useState<IndicatorInterval>(
    mode === "replay" ? "5m" : "1m",
  );
  const [selectedExpiry, setSelectedExpiry] = useState("");
  const [snapshot, setSnapshot] = useState<OptionPowerSnapshot | null>(null);
  const [cursorTime, setCursorTime] = useState("-");
  const [cursorIsoTime, setCursorIsoTime] = useState<string | null>(null);
  const [replayStart, setReplayStart] = useState("");
  const [replayEnd, setReplayEnd] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);

  const requestedSeries = useMemo(
    () => [
      "pressure_index",
      "raw_pressure",
      "pressure_index_weighted",
      "raw_pressure_weighted",
      "regime_state",
      "structure_state",
      "trend_score",
      "chop_score",
      "reversal_risk",
      "vwap_distance_bps",
      "trade_intensity_ratio_30b",
      "adx_14",
      "plus_di_14",
      "minus_di_14",
      "di_bias_14",
      "choppiness_14",
      "compression_score",
      "expansion_score",
      "compression_expansion_state",
      "session_cvd",
      "cvd_5b_delta",
      "cvd_15b_delta",
      "cvd_5b_slope",
      "cvd_price_alignment",
      "price_cvd_divergence_15b",
      "iv_skew",
    ],
    [],
  );
  const live = useOptionPowerLive(requestedSeries, mode === "live", liveShowsPricePanel);
  const replay = useOptionPowerReplay(requestedSeries, mode === "replay", indicatorInterval);

  useEffect(() => {
    if (mode === "live") {
      setSnapshot(live.snapshot);
      return;
    }
    setSnapshot(null);
  }, [live.snapshot, mode]);

  useEffect(() => {
    if (mode === "replay" && replay.session) {
      setReplayStart(toDatetimeLocal(replay.session.start));
      setReplayEnd(toDatetimeLocal(replay.session.end));
    }
  }, [mode, replay.session]);

  useEffect(() => {
    if (snapshot?.generated_at) {
      setCursorIsoTime(snapshot.generated_at);
      setCursorTime(formatDateTime(snapshot.generated_at));
    }
  }, [snapshot?.generated_at]);

  useEffect(() => {
    const nextExpiry = snapshot?.expiries?.[0]?.contract_month ?? "";
    if (nextExpiry && !snapshot?.expiries.some((item) => item.contract_month === selectedExpiry)) {
      setSelectedExpiry(nextExpiry);
    }
  }, [selectedExpiry, snapshot]);

  useEffect(() => {
    if (mode === "live") {
      setPageError(live.error);
      return;
    }
    setPageError(replay.error);
  }, [live.error, mode, replay.error]);

  const handleCursorTime = useCallback((ts: string | null) => {
    if (!ts) {
      setCursorIsoTime(null);
      setCursorTime("-");
      return;
    }
    setCursorIsoTime(ts);
    setCursorTime(formatDateTime(ts));
  }, []);

  const handleVisibleRangeChange = useCallback((start: string, end: string) => {
    if (mode !== "replay") {
      return;
    }
    void replay.ensureWindowForVisibleRange(start, end).catch(() => {
      return;
    });
  }, [mode, replay]);

  const activeBars = mode === "live" ? live.bars : replay.bars;
  const activeSeries = mode === "live" ? live.series : replay.series;
  const pressurePanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "pressure_index",
        label: "Pressure Index",
        points: resampleSeries(activeSeries.pressure_index ?? [], indicatorInterval),
        color: "#fbbf24",
      },
      {
        id: "pressure_index_weighted",
        label: "Index Weighted",
        points: resampleSeries(activeSeries.pressure_index_weighted ?? [], indicatorInterval),
        color: "rgba(251, 191, 36, 0.46)",
        dashed: true,
      },
      {
        id: "regime_state",
        label: "Regime State",
        points: resampleSeries(activeSeries.regime_state ?? [], indicatorInterval),
        color: "#fb7185",
        kind: "histogram",
        priceScaleId: "left",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const rawPressurePanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "raw_pressure",
        label: "Raw Pressure",
        points: resampleSeries(activeSeries.raw_pressure ?? [], indicatorInterval),
        color: "#7dd3fc",
      },
      {
        id: "raw_pressure_weighted",
        label: "Raw Weighted",
        points: resampleSeries(activeSeries.raw_pressure_weighted ?? [], indicatorInterval),
        color: "rgba(125, 211, 252, 0.46)",
        dashed: true,
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const structurePanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "structure_state",
        label: "Structure State",
        points: resampleSeries(activeSeries.structure_state ?? [], indicatorInterval),
        color: "#f59e0b",
        kind: "histogram",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const chopPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "chop_score",
        label: "Chop Score",
        points: resampleSeries(activeSeries.chop_score ?? [], indicatorInterval),
        color: "#f472b6",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const contextPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "vwap_distance_bps",
        label: "VWAP Dist",
        points: resampleSeries(activeSeries.vwap_distance_bps ?? [], indicatorInterval),
        color: "#34d399",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const trendQualityPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "trend_quality_score",
        label: "Trend Quality",
        points: deriveTrendQualitySeries(activeSeries, indicatorInterval),
        color: "#38bdf8",
      },
      {
        id: "trend_bias_state",
        label: "Trend Bias",
        points: deriveTrendBiasSeries(activeSeries, indicatorInterval),
        color: "#f59e0b",
        kind: "histogram",
        priceScaleId: "left",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const cvdPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "flow_impulse_score",
        label: "Flow Impulse",
        points: deriveFlowImpulseSeries(activeSeries, indicatorInterval),
        color: "#22c55e",
      },
      {
        id: "flow_state",
        label: "Flow State",
        points: deriveFlowStateSeries(activeSeries, indicatorInterval),
        color: "#eab308",
        kind: "histogram",
        priceScaleId: "left",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const rangeStatePanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "range_state",
        label: "Range State",
        points: deriveRangeStateSeries(activeSeries, indicatorInterval),
        color: "#c084fc",
        kind: "histogram",
        priceScaleId: "left",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const ivSkewPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "iv_skew",
        label: "IV Skew",
        points: resampleSeries(activeSeries.iv_skew ?? [], indicatorInterval),
        color: "#2dd4bf",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const signalPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "signal_state",
        label: "Signal State",
        points: deriveSignalSeries(activeSeries, indicatorInterval),
        color: "#f97316",
        kind: "histogram",
      },
    ],
    [activeSeries, indicatorInterval],
  );
  const biasPanelSeries = useMemo<IndicatorPanelSeries[]>(
    () => [
      {
        id: "bias_signal",
        label: "Bias Signal",
        points: deriveBiasSeries(activeSeries, indicatorInterval),
        color: "#10b981",
        kind: "histogram",
      },
    ],
    [activeSeries, indicatorInterval],
  );

  const activeStatus = mode === "live"
    ? live.meta?.status ?? live.error ?? "-"
    : replay.session?.session_id ?? replay.error ?? "-";
  const rootsLabel = mode === "live"
    ? (live.meta?.selected_option_roots ?? []).join(" + ")
    : (replay.session?.selected_option_roots ?? []).join(" + ");
  const rangeLabel = mode === "live"
    ? live.meta?.start && live.meta?.end
      ? `${formatDateTime(live.meta.start)} -> ${formatDateTime(live.meta.end)}`
      : "live stream"
    : replay.session
      ? `${formatDateTime(replay.session.start)} -> ${formatDateTime(replay.session.end)}`
      : "-";
  const replayWindowLabel = mode === "replay" && replay.windowStart && replay.windowEnd
    ? `${formatDateTime(replay.windowStart)} -> ${formatDateTime(replay.windowEnd)}`
    : "-";

  const selectedContracts = selectExpiry(snapshot, selectedExpiry)?.contracts ?? [];
  const contractTotals = useMemo(
    () => summarizeContractsBySide(selectedContracts),
    [selectedContracts],
  );
  const metricTime = mode === "replay"
    ? cursorIsoTime ?? latestSeriesTime(activeSeries)
    : snapshot?.generated_at ?? null;
  const pressureIndexValue = mode === "live"
    ? snapshot?.pressure_index ?? 0
    : seriesValueAt(activeSeries.pressure_index ?? [], metricTime);
  const pressureIndexWeightedValue = mode === "live"
    ? snapshot?.pressure_index_weighted ?? 0
    : seriesValueAt(activeSeries.pressure_index_weighted ?? [], metricTime);
  const rawPressureValue = mode === "live"
    ? snapshot?.raw_pressure ?? 0
    : seriesValueAt(activeSeries.raw_pressure ?? [], metricTime);
  const rawPressureWeightedValue = mode === "live"
    ? snapshot?.raw_pressure_weighted ?? 0
    : seriesValueAt(activeSeries.raw_pressure_weighted ?? [], metricTime);
  const ivSkewValue = mode === "live"
    ? snapshot?.iv_surface?.skew ?? 0
    : seriesValueAt(activeSeries.iv_skew ?? [], metricTime);
  const sessionTone = toneOf(pressureIndexValue);
  const weightedTone = toneOf(pressureIndexWeightedValue);
  const headingEyebrow = mode === "live" ? "Research Live" : "Research Replay";
  const headingSubtitle = mode === "live"
    ? "Live 先聚焦核心訊號，暫時停掉較重的主圖、trend、context 與 option power 分布區塊。"
    : "主圖固定看 MTX，下方多副圖一次展開 pressure、regime 與 market structure，先專注觀察整體節奏。";
  const regime = snapshot?.regime ?? null;
  const intensityValue = mode === "live"
    ? regime?.trade_intensity_ratio_30b ?? 0
    : seriesValueAt(activeSeries.trade_intensity_ratio_30b ?? [], metricTime);
  const regimeLabel = mode === "live"
    ? regime?.regime_label ?? "no_data"
    : regimeLabelFromState(seriesValueAt(activeSeries.regime_state ?? [], metricTime));
  const trendScoreValue = mode === "live"
    ? regime?.trend_score ?? 0
    : seriesValueAt(activeSeries.trend_score ?? [], metricTime);
  const reversalRiskValue = mode === "live"
    ? regime?.reversal_risk ?? 0
    : seriesValueAt(activeSeries.reversal_risk ?? [], metricTime);
  const vwapDistanceValue = mode === "live"
    ? regime?.vwap_distance_bps ?? 0
    : seriesValueAt(activeSeries.vwap_distance_bps ?? [], metricTime);
  const signalState = useMemo(
    () => signalStateMeta(seriesValueAt(signalPanelSeries[0]?.points ?? [], metricTime)),
    [signalPanelSeries, metricTime],
  );

  async function handleReplayLoad() {
    try {
      setPageError(null);
      await replay.createSession(fromDatetimeLocal(replayStart), fromDatetimeLocal(replayEnd));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Unable to create replay session.");
    }
  }

  return (
    <section className={styles.page}>
      <section className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>{headingEyebrow}</p>
          <h2 className={styles.title}>MTX + Option Power</h2>
          <p className={styles.subtitle}>{headingSubtitle}</p>
        </div>
        <div className={styles.metaCard}>
          <MetaRow label="Mode" value={mode} />
          <MetaRow label="Status" value={activeStatus} />
          <MetaRow label="Roots" value={rootsLabel || "-"} />
          <MetaRow label="Range" value={rangeLabel} />
          <MetaRow label="Cursor" value={cursorTime} />
        </div>
      </section>

      <section className={styles.toolbar}>
        {mode === "replay" ? (
          <>
            <label className={styles.field}>
              <span>Start</span>
              <input
                type="datetime-local"
                value={replayStart}
                disabled={replay.loading}
                onChange={(event) => setReplayStart(event.target.value)}
              />
            </label>

            <label className={styles.field}>
              <span>End</span>
              <input
                type="datetime-local"
                value={replayEnd}
                disabled={replay.loading}
                onChange={(event) => setReplayEnd(event.target.value)}
              />
            </label>

            <button
              className={styles.button}
              data-loading={replay.loading ? "true" : "false"}
              disabled={replay.loading}
              onClick={() => void handleReplayLoad()}
              type="button"
            >
              {replay.loading ? (
                <>
                  <span className={styles.spinner} aria-hidden="true" />
                  <span>Loading Replay...</span>
                </>
              ) : (
                "Load Replay"
              )}
            </button>

            <div className={styles.windowControls}>
              <button
                className={styles.button}
                disabled={replay.loading || !replay.canShiftPrev}
                onClick={() => void replay.shiftWindow(-1)}
                type="button"
              >
                Prev 3h
              </button>
              <button
                className={styles.button}
                disabled={replay.loading || !replay.canShiftNext}
                onClick={() => void replay.shiftWindow(1)}
                type="button"
              >
                Next 3h
              </button>
              <button
                className={styles.button}
                disabled={replay.loading || !replay.session}
                onClick={() => void replay.resetWindow()}
                type="button"
              >
                Reset Window
              </button>
            </div>

            <div className={styles.windowInfo}>
              <span>Window</span>
              <strong>{replayWindowLabel}</strong>
            </div>
          </>
        ) : null}

        <label className={styles.field}>
          <span>Indicator Interval</span>
          <select
            value={indicatorInterval}
            onChange={(event) => setIndicatorInterval(event.target.value as IndicatorInterval)}
          >
            {INDICATOR_INTERVAL_OPTIONS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
      </section>

      {pageError ? <div className={styles.error}>{pageError}</div> : null}

      <section className={styles.workspace}>
        <TimelineCharts
          bars={activeBars}
          pressureSeries={pressurePanelSeries}
          rawPressureSeries={rawPressurePanelSeries}
          chopSeries={chopPanelSeries}
          structureSeries={structurePanelSeries}
          biasSeries={biasPanelSeries}
          signalSeries={signalPanelSeries}
          contextSeries={contextPanelSeries}
          trendQualitySeries={trendQualityPanelSeries}
          cvdSeries={cvdPanelSeries}
          rangeStateSeries={rangeStatePanelSeries}
          ivSkewSeries={ivSkewPanelSeries}
          visiblePanelIds={
            mode === "live"
              ? ["pressure", "regime", "bias", "signal", "chop", "structure", "cvd", "rangeState", "ivSkew"]
              : undefined
          }
          mode={mode}
          onCursorTimeChange={handleCursorTime}
          onVisibleRangeChange={handleVisibleRangeChange}
          viewKey={mode === "replay" ? replay.session?.session_id ?? "replay" : mode}
        />
      </section>

      <section className={styles.insights}>
        <section className={styles.metricGrid}>
          <MetricCard label="Signal State" value={signalState.label} tone={signalState.tone} />
          <MetricCard label="Intensity 30b" value={formatIntensity(intensityValue)} tone={intensityTone(intensityValue)} />
          <MetricCard label="Regime" value={formatRegimeLabel(regimeLabel)} tone={regimeTone(regimeLabel)} />
          <MetricCard label="Trend Score" value={formatSigned(trendScoreValue)} tone={toneOf(trendScoreValue)} />
          <MetricCard label="Reversal Risk" value={formatSigned(reversalRiskValue)} tone={toneOf(-reversalRiskValue)} />
          <MetricCard label="VWAP Dist" value={formatSignedFloat(vwapDistanceValue, " bps")} tone={toneOf(vwapDistanceValue)} />
          <MetricCard label="Pressure Index" value={formatSigned(pressureIndexValue)} tone={sessionTone} />
          <MetricCard label="IV Skew" value={formatVolPoints(ivSkewValue)} tone={toneOf(ivSkewValue)} />
          <MetricCard
            label="Index Weighted"
            value={formatSigned(pressureIndexWeightedValue)}
            tone={weightedTone}
          />
          <MetricCard label="Raw Pressure" value={formatSigned(rawPressureValue)} tone={toneOf(rawPressureValue)} />
          <MetricCard
            label="Raw Weighted"
            value={formatSigned(rawPressureWeightedValue)}
            tone={toneOf(rawPressureWeightedValue)}
          />
        </section>

        {mode === "live" ? (
          <section className={styles.aggregateGrid}>
            <MetricCard label="Call Cum" value={formatSigned(contractTotals.call.cumulative_power)} tone={toneOf(contractTotals.call.cumulative_power)} />
            <MetricCard label="Put Cum" value={formatSigned(contractTotals.put.cumulative_power)} tone={toneOf(contractTotals.put.cumulative_power)} />
            <MetricCard label="Call 1m" value={formatSigned(contractTotals.call.power_1m_delta)} tone={toneOf(contractTotals.call.power_1m_delta)} />
            <MetricCard label="Put 1m" value={formatSigned(contractTotals.put.power_1m_delta)} tone={toneOf(contractTotals.put.power_1m_delta)} />
          </section>
        ) : null}
      </section>
    </section>
  );
}

type MetaRowProps = {
  label: string;
  value: string;
};

function MetaRow({ label, value }: MetaRowProps) {
  return (
    <div className={styles.metaRow}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function toneOf(value: number) {
  if (value > 0) {
    return "positive" as const;
  }
  if (value < 0) {
    return "negative" as const;
  }
  return "neutral" as const;
}

function formatSigned(value: number) {
  return `${value > 0 ? "+" : ""}${Number(value || 0).toFixed(0)}`;
}

function formatSignedFloat(value: number, suffix = "") {
  const normalized = Number(value || 0);
  const prefix = normalized > 0 ? "+" : "";
  return `${prefix}${normalized.toFixed(2)}${suffix}`;
}

function formatVolPoints(value: number) {
  const normalized = Number(value || 0) * 100;
  const prefix = normalized > 0 ? "+" : "";
  return `${prefix}${normalized.toFixed(2)} pts`;
}

function formatRegimeLabel(value: string) {
  if (value === "trend_up") {
    return "Trend Up";
  }
  if (value === "trend_down") {
    return "Trend Down";
  }
  if (value === "chop") {
    return "Chop";
  }
  if (value === "reversal_up") {
    return "Reversal Up";
  }
  if (value === "reversal_down") {
    return "Reversal Down";
  }
  if (value === "transition") {
    return "Transition";
  }
  return "No Data";
}

function regimeTone(value: string) {
  if (value === "trend_up") {
    return "positive" as const;
  }
  if (value === "trend_down" || value === "reversal_down") {
    return "negative" as const;
  }
  return "neutral" as const;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date).replace(/\//g, "-");
}

function toDatetimeLocal(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function fromDatetimeLocal(value: string) {
  return value ? `${value}:00` : "";
}

function formatIntensity(value: number) {
  const ratio = Number(value || 0);
  return `${ratio.toFixed(2)}x ${intensityLabel(ratio)}`;
}

function intensityLabel(value: number) {
  if (value >= 1.35) {
    return "HIGH";
  }
  if (value >= 1.05) {
    return "ACTIVE";
  }
  if (value <= 0.85) {
    return "QUIET";
  }
  return "BASE";
}

function intensityTone(value: number) {
  if (value >= 1.05) {
    return "positive" as const;
  }
  return "neutral" as const;
}

function seriesValueAt(
  points: { time: string; value: number }[],
  targetTime: string | null,
) {
  if (!points.length) {
    return 0;
  }
  if (!targetTime) {
    return Number(points[points.length - 1]?.value ?? 0);
  }
  const targetMs = new Date(targetTime).getTime();
  if (Number.isNaN(targetMs)) {
    return Number(points[points.length - 1]?.value ?? 0);
  }
  let selected = points[0];
  let selectedMs = new Date(selected.time).getTime();
  for (const point of points) {
    const pointMs = new Date(point.time).getTime();
    if (Number.isNaN(pointMs)) {
      continue;
    }
    if (pointMs > targetMs) {
      break;
    }
    selected = point;
    selectedMs = pointMs;
  }
  if (selectedMs > targetMs) {
    return Number(points[0]?.value ?? 0);
  }
  return Number(selected.value ?? 0);
}

function signalStateMeta(value: number) {
  if (value === 1) {
    return { label: "LONG", tone: "positive" as const };
  }
  if (value === -1) {
    return { label: "SHORT", tone: "negative" as const };
  }
  return { label: "-", tone: "neutral" as const };
}

function latestSeriesTime(activeSeries: Record<string, { time: string; value: number }[]>) {
  let latest: string | null = null;
  let latestMs = Number.NEGATIVE_INFINITY;
  for (const points of Object.values(activeSeries)) {
    for (const point of points) {
      const pointMs = new Date(point.time).getTime();
      if (!Number.isNaN(pointMs) && pointMs > latestMs) {
        latest = point.time;
        latestMs = pointMs;
      }
    }
  }
  return latest;
}

function regimeLabelFromState(value: number) {
  if (value > 0) {
    return "trend_up";
  }
  if (value < 0) {
    return "trend_down";
  }
  return "no_data";
}

function deriveSignalSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const pressureIndex = activeSeries.pressure_index ?? [];
  const rawPressure = activeSeries.raw_pressure ?? [];
  const regimeState = activeSeries.regime_state ?? [];
  const structureState = activeSeries.structure_state ?? [];
  const intensity = activeSeries.trade_intensity_ratio_30b ?? [];
  const chop = activeSeries.chop_score ?? [];
  const adx = activeSeries.adx_14 ?? [];
  const choppiness = activeSeries.choppiness_14 ?? [];
  const diBias = activeSeries.di_bias_14 ?? [];
  const cvdSlope = activeSeries.cvd_5b_slope ?? [];
  const cvdAlignment = activeSeries.cvd_price_alignment ?? [];
  const cvdDivergence = activeSeries.price_cvd_divergence_15b ?? [];
  const rangeState = activeSeries.compression_expansion_state ?? [];
  const timeSet = new Set<string>();
  for (const series of [
    pressureIndex,
    rawPressure,
    regimeState,
    structureState,
    intensity,
    chop,
    adx,
    choppiness,
    diBias,
    cvdSlope,
    cvdAlignment,
    cvdDivergence,
    rangeState,
  ]) {
    for (const point of series) {
      timeSet.add(point.time);
    }
  }
  const pressureIndexMap = new Map(pressureIndex.map((point) => [point.time, Number(point.value ?? 0)]));
  const rawPressureMap = new Map(rawPressure.map((point) => [point.time, Number(point.value ?? 0)]));
  const regimeStateMap = new Map(regimeState.map((point) => [point.time, Number(point.value ?? 0)]));
  const structureStateMap = new Map(structureState.map((point) => [point.time, Number(point.value ?? 0)]));
  const intensityMap = new Map(intensity.map((point) => [point.time, Number(point.value ?? 0)]));
  const chopMap = new Map(chop.map((point) => [point.time, Number(point.value ?? 0)]));
  const adxMap = new Map(adx.map((point) => [point.time, Number(point.value ?? 0)]));
  const choppinessMap = new Map(choppiness.map((point) => [point.time, Number(point.value ?? 0)]));
  const diBiasMap = new Map(diBias.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdSlopeMap = new Map(cvdSlope.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdAlignmentMap = new Map(cvdAlignment.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdDivergenceMap = new Map(cvdDivergence.map((point) => [point.time, Number(point.value ?? 0)]));
  const rangeStateMap = new Map(rangeState.map((point) => [point.time, Number(point.value ?? 0)]));

  const orderedTimes = Array.from(timeSet).sort();
  const signalPoints = orderedTimes.map((time, timeIndex) => {
    const previousTime = timeIndex > 0 ? orderedTimes[timeIndex - 1] : null;
    const now = new Date(time);
    const pressureHistory = rollingWindowValues(pressureIndexMap, orderedTimes, now, 30);
    const rawHistory = rollingWindowValues(rawPressureMap, orderedTimes, now, 30);
    const slopeHistory = rollingWindowValues(cvdSlopeMap, orderedTimes, now, 30);
    const pressureAbsHistory = pressureHistory.map((value) => Math.abs(value));
    const rawAbsHistory = rawHistory.map((value) => Math.abs(value));
    const slopeAbsHistory = slopeHistory.map((value) => Math.abs(value));
    const biasValue = deriveBiasValue({
      pressureIndex: pressureIndexMap.get(time) ?? 0,
      previousPressureIndex: previousTime ? (pressureIndexMap.get(previousTime) ?? 0) : null,
      regimeState: regimeStateMap.get(time) ?? 0,
      structureState: structureStateMap.get(time) ?? 0,
      intensityRatio: intensityMap.get(time) ?? 0,
    });
    return {
      time,
      value: deriveSignalStateValue({
      biasValue,
      regimeState: regimeStateMap.get(time) ?? 0,
      structureState: structureStateMap.get(time) ?? 0,
      intensityRatio: intensityMap.get(time) ?? 0,
      chopScore: chopMap.get(time) ?? 0,
      pressureIndex: pressureIndexMap.get(time) ?? 0,
      previousPressureIndex: previousTime ? (pressureIndexMap.get(previousTime) ?? 0) : null,
      rawPressure: rawPressureMap.get(time) ?? 0,
      adxValue: adxMap.get(time) ?? 0,
      choppinessValue: choppinessMap.get(time) ?? 0,
      diBiasValue: diBiasMap.get(time) ?? 0,
      cvdSlopeValue: cvdSlopeMap.get(time) ?? 0,
      cvdAlignmentValue: cvdAlignmentMap.get(time) ?? 0,
      cvdDivergenceValue: cvdDivergenceMap.get(time) ?? 0,
      rangeStateValue: rangeStateMap.get(time) ?? 0,
      strongPressureThreshold: Math.max(rollingQuantile(pressureAbsHistory, 0.60), 3),
      rawPressureThreshold: Math.max(rollingQuantile(rawAbsHistory, 0.55), 3),
      flowThreshold: Math.max(rollingQuantile(slopeAbsHistory, 0.65), 1),
      }),
    };
  });

  return resampleSeries(signalPoints, interval);
}

function deriveBiasSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const pressureIndex = activeSeries.pressure_index ?? [];
  const regimeState = activeSeries.regime_state ?? [];
  const structureState = activeSeries.structure_state ?? [];
  const intensity = activeSeries.trade_intensity_ratio_30b ?? [];
  const timeSet = new Set<string>();
  for (const series of [pressureIndex, regimeState, structureState, intensity]) {
    for (const point of series) {
      timeSet.add(point.time);
    }
  }
  const pressureIndexMap = new Map(pressureIndex.map((point) => [point.time, Number(point.value ?? 0)]));
  const regimeStateMap = new Map(regimeState.map((point) => [point.time, Number(point.value ?? 0)]));
  const structureStateMap = new Map(structureState.map((point) => [point.time, Number(point.value ?? 0)]));
  const intensityMap = new Map(intensity.map((point) => [point.time, Number(point.value ?? 0)]));

  return resampleSeries(
    Array.from(timeSet)
      .sort()
      .map((time, index, orderedTimes) => {
        const previousTime = index > 0 ? orderedTimes[index - 1] : null;
        return {
          time,
          value: deriveBiasValue({
            pressureIndex: pressureIndexMap.get(time) ?? 0,
            previousPressureIndex: previousTime ? (pressureIndexMap.get(previousTime) ?? 0) : null,
            regimeState: regimeStateMap.get(time) ?? 0,
            structureState: structureStateMap.get(time) ?? 0,
            intensityRatio: intensityMap.get(time) ?? 0,
          }),
        };
      }),
    interval,
  );
}

function deriveTrendQualitySeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const adx = activeSeries.adx_14 ?? [];
  const choppiness = activeSeries.choppiness_14 ?? [];
  const timeSet = new Set<string>();
  for (const series of [adx, choppiness]) {
    for (const point of series) {
      timeSet.add(point.time);
    }
  }
  const adxMap = new Map(adx.map((point) => [point.time, Number(point.value ?? 0)]));
  const chopMap = new Map(choppiness.map((point) => [point.time, Number(point.value ?? 0)]));
  return resampleSeries(
    Array.from(timeSet)
      .sort()
      .map((time) => {
        const adxValue = adxMap.get(time) ?? 0;
        const chopValue = chopMap.get(time) ?? 0;
        const trendQuality = clampNumber((adxValue * 1.4 + (100 - chopValue)) / 2.4, 0, 100);
        return { time, value: trendQuality };
      }),
    interval,
  );
}

function deriveTrendBiasSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const adx = activeSeries.adx_14 ?? [];
  const diBias = activeSeries.di_bias_14 ?? [];
  const timeSet = new Set<string>();
  for (const series of [adx, diBias]) {
    for (const point of series) {
      timeSet.add(point.time);
    }
  }
  const adxMap = new Map(adx.map((point) => [point.time, Number(point.value ?? 0)]));
  const diBiasMap = new Map(diBias.map((point) => [point.time, Number(point.value ?? 0)]));
  return resampleSeries(
    Array.from(timeSet)
      .sort()
      .map((time) => {
        const adxValue = adxMap.get(time) ?? 0;
        const biasValue = diBiasMap.get(time) ?? 0;
        let state = 0;
        if (adxValue >= 18 && biasValue >= 8) {
          state = 1;
        } else if (adxValue >= 18 && biasValue <= -8) {
          state = -1;
        }
        return { time, value: state };
      }),
    interval,
  );
}

function deriveFlowImpulseSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const cvdSlope = activeSeries.cvd_5b_slope ?? [];
  const timeSet = new Set<string>();
  for (const point of cvdSlope) {
    timeSet.add(point.time);
  }
  const slopeMap = new Map(cvdSlope.map((point) => [point.time, Number(point.value ?? 0)]));
  const orderedTimes = Array.from(timeSet).sort();
  return resampleSeries(
    orderedTimes.map((time) => {
      const now = new Date(time);
      const slopeHistory = rollingWindowValues(slopeMap, orderedTimes, now, 30).map((value) => Math.abs(value));
      const slopeThreshold = Math.max(rollingQuantile(slopeHistory, 0.8), 1);
      const currentSlope = slopeMap.get(time) ?? 0;
      const impulse = clampNumber((currentSlope / slopeThreshold) * 100, -100, 100);
      return { time, value: impulse };
    }),
    interval,
  );
}

function deriveFlowStateSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const alignment = activeSeries.cvd_price_alignment ?? [];
  const divergence = activeSeries.price_cvd_divergence_15b ?? [];
  const timeSet = new Set<string>();
  for (const series of [alignment, divergence]) {
    for (const point of series) {
      timeSet.add(point.time);
    }
  }
  const alignmentMap = new Map(alignment.map((point) => [point.time, Number(point.value ?? 0)]));
  const divergenceMap = new Map(divergence.map((point) => [point.time, Number(point.value ?? 0)]));
  return resampleSeries(
    Array.from(timeSet)
      .sort()
      .map((time) => {
        const alignmentValue = alignmentMap.get(time) ?? 0;
        const divergenceValue = divergenceMap.get(time) ?? 0;
        if (divergenceValue > 0) {
          return { time, value: 1 };
        }
        if (divergenceValue < 0) {
          return { time, value: -1 };
        }
        return { time, value: alignmentValue };
      }),
    interval,
  );
}

function deriveRangeStateSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const state = activeSeries.compression_expansion_state ?? [];
  return resampleSeries(
    state.map((point) => {
      const value = Number(point.value ?? 0);
      if (value < 0) {
        return { time: point.time, value: -1 };
      }
      if (value > 0) {
        return { time: point.time, value: 1 };
      }
      return { time: point.time, value: 0 };
    }),
    interval,
  );
}

export function deriveSignalStateValue(input: {
  biasValue: number;
  regimeState: number;
  structureState: number;
  intensityRatio: number;
  chopScore: number;
  pressureIndex: number;
  previousPressureIndex: number | null;
  rawPressure: number;
  adxValue: number;
  choppinessValue: number;
  diBiasValue: number;
  cvdSlopeValue: number;
  cvdAlignmentValue: number;
  cvdDivergenceValue: number;
  rangeStateValue: number;
  strongPressureThreshold: number;
  rawPressureThreshold: number;
  flowThreshold: number;
}) {
  const pressureSide = resolvePressureSide(input.pressureIndex);
  const pressureSlope = resolvePressureSlope(input.pressureIndex, input.previousPressureIndex);
  const active = input.intensityRatio >= 0.95;
  const strongPressure = Math.abs(input.pressureIndex) >= input.strongPressureThreshold;
  const supportedRawPressure = Math.abs(input.rawPressure) >= input.rawPressureThreshold;
  const trendBiasDirection = input.diBiasValue > 8 ? 1 : input.diBiasValue < -8 ? -1 : 0;
  const flowDirection = input.cvdSlopeValue > input.flowThreshold ? 1 : input.cvdSlopeValue < -input.flowThreshold ? -1 : 0;
  const trendReady = input.adxValue >= 18 && input.choppinessValue <= 62;
  if (!active || input.biasValue === 0 || input.rangeStateValue < 0 || input.chopScore > 30) {
    return 0;
  }
  const opposingDivergence = input.cvdDivergenceValue === -input.biasValue;
  if (opposingDivergence) {
    return 0;
  }
  let supportScore = 0;
  if (input.structureState === input.biasValue) {
    supportScore += 2;
  }
  if (input.regimeState === input.biasValue) {
    supportScore += 1;
  }
  if (trendBiasDirection === input.biasValue) {
    supportScore += 1;
  }
  if (flowDirection === input.biasValue) {
    supportScore += 1;
  }
  if (input.cvdAlignmentValue === input.biasValue) {
    supportScore += 1;
  }
  if (pressureSupportsBias(pressureSide, pressureSlope, input.biasValue)) {
    supportScore += 1;
  }
  if (trendReady) {
    supportScore += 1;
  }
  if (strongPressure) {
    supportScore += 1;
  }
  if (supportedRawPressure) {
    supportScore += 1;
  }
  if (input.rangeStateValue > 0) {
    supportScore += 1;
  }
  if (supportScore >= 6) {
    return input.biasValue;
  }
  return 0;
}

export function deriveBiasValue(input: {
  pressureIndex: number;
  previousPressureIndex: number | null;
  regimeState: number;
  structureState: number;
  intensityRatio: number;
}) {
  const structureDirection = input.structureState > 0 ? 1 : input.structureState < 0 ? -1 : 0;
  const regimeDirection = input.regimeState > 0 ? 1 : input.regimeState < 0 ? -1 : 0;
  const pressureSide = resolvePressureSide(input.pressureIndex);
  const pressureSlope = resolvePressureSlope(input.pressureIndex, input.previousPressureIndex);
  const active = input.intensityRatio >= 0.95;
  if (!active) {
    return 0;
  }
  if (
    input.structureState > 0
    && pressureSupportsBias(pressureSide, pressureSlope, 1)
    && input.regimeState >= 0
  ) {
    return 1;
  }
  if (
    input.structureState < 0
    && pressureSupportsBias(pressureSide, pressureSlope, -1)
    && input.regimeState <= 0
  ) {
    return -1;
  }
  if (input.structureState > 0 && input.regimeState > 0) {
    return 1;
  }
  if (input.structureState < 0 && input.regimeState < 0) {
    return -1;
  }
  return 0;
}

export function resolvePressureSide(value: number) {
  if (value >= 2) {
    return 1;
  }
  if (value <= -2) {
    return -1;
  }
  return 0;
}

export function resolvePressureSlope(value: number, previousValue: number | null) {
  if (previousValue === null) {
    return 0;
  }
  const delta = value - previousValue;
  if (delta >= 2) {
    return 1;
  }
  if (delta <= -2) {
    return -1;
  }
  return 0;
}

function pressureSupportsBias(side: number, slope: number, bias: number) {
  if (side !== bias) {
    return false;
  }
  if (bias > 0) {
    return slope >= 0;
  }
  return slope <= 0;
}

function rollingWindowValues(
  valueMap: Map<string, number>,
  orderedTimes: string[],
  now: Date,
  minutes: number,
) {
  const cutoff = now.getTime() - minutes * 60 * 1000;
  const values: number[] = [];
  for (const time of orderedTimes) {
    const ts = new Date(time).getTime();
    if (Number.isNaN(ts) || ts < cutoff || ts > now.getTime()) {
      continue;
    }
    values.push(valueMap.get(time) ?? 0);
  }
  return values;
}

function rollingQuantile(values: number[], quantile: number) {
  if (!values.length) {
    return 0;
  }
  const ordered = [...values].sort((left, right) => left - right);
  const index = Math.max(0, Math.min(ordered.length - 1, Math.ceil(quantile * ordered.length) - 1));
  return ordered[index];
}

function clampNumber(value: number, lower: number, upper: number) {
  return Math.max(lower, Math.min(value, upper));
}
