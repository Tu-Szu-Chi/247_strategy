import { useCallback, useEffect, useMemo, useState } from "react";
import { MetricCard } from "../features/option-power/components/MetricCard";
import {
  TimelineCharts,
  type IndicatorPanelSeries,
} from "../features/option-power/components/TimelineCharts";
import {
  INDICATOR_INTERVAL_OPTIONS,
  resampleSeries,
} from "../features/option-power/series";
import { useOptionPowerLive } from "../features/option-power/useOptionPowerLive";
import { useOptionPowerReplay } from "../features/option-power/useOptionPowerReplay";
import type { IndicatorInterval, LiveContractTotals, LiveSnapshotSummary } from "../features/option-power/types";
import styles from "./ResearchPage.module.css";

type OptionPowerResearchWorkspaceProps = {
  mode: "live" | "replay";
};

export const OPTION_POWER_RESEARCH_SERIES = [
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
  "trend_quality_score",
  "trend_bias_state",
  "flow_impulse_score",
  "flow_state",
  "range_state",
  "bias_signal",
  "signal_state",
];

const EMPTY_CONTRACT_TOTALS: LiveContractTotals = {
  call: { cumulative_power: 0, power_1m_delta: 0 },
  put: { cumulative_power: 0, power_1m_delta: 0 },
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
  const [snapshot, setSnapshot] = useState<LiveSnapshotSummary | null>(null);
  const [cursorTime, setCursorTime] = useState("-");
  const [cursorIsoTime, setCursorIsoTime] = useState<string | null>(null);
  const [replayStart, setReplayStart] = useState("");
  const [replayEnd, setReplayEnd] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);

  const requestedSeries = useMemo(() => OPTION_POWER_RESEARCH_SERIES, []);
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

  const handleVisibleRangeChange = useCallback((range: {
    start: string;
    end: string;
    hasLeftWhitespace?: boolean;
    hasRightWhitespace?: boolean;
  }) => {
    if (mode !== "replay") {
      return;
    }
    void replay.ensureWindowForVisibleRange(range.start, range.end, {
      hasLeftWhitespace: range.hasLeftWhitespace,
      hasRightWhitespace: range.hasRightWhitespace,
    }).catch(() => {
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
        points: resampleSeries(activeSeries.trend_quality_score ?? [], indicatorInterval),
        color: "#38bdf8",
      },
      {
        id: "trend_bias_state",
        label: "Trend Bias",
        points: resampleSeries(activeSeries.trend_bias_state ?? [], indicatorInterval),
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
        points: resampleSeries(activeSeries.flow_impulse_score ?? [], indicatorInterval),
        color: "#22c55e",
      },
      {
        id: "flow_state",
        label: "Flow State",
        points: resampleSeries(activeSeries.flow_state ?? [], indicatorInterval),
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
        points: resampleSeries(activeSeries.range_state ?? [], indicatorInterval),
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
        points: resampleSeries(activeSeries.signal_state ?? [], indicatorInterval),
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
        points: resampleSeries(activeSeries.bias_signal ?? [], indicatorInterval),
        color: "#10b981",
        kind: "histogram",
      },
    ],
    [activeSeries, indicatorInterval],
  );

  const activeStatus = mode === "live"
    ? live.meta?.status ?? live.error ?? "-"
    : replay.session
      ? `${replay.computeStatus}${replay.partial ? " (partial)" : ""} ${Math.round(replay.progressRatio * 100)}%`
      : replay.error ?? "-";
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

  const contractTotals = live.contractTotals ?? EMPTY_CONTRACT_TOTALS;
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
          {mode === "replay" ? (
            <MetaRow label="Session" value={replay.session?.session_id ?? "-"} />
          ) : null}
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
                title={!replay.canShiftPrev ? "At replay start" : undefined}
                type="button"
              >
                Prev 3h
              </button>
              <button
                className={styles.button}
                disabled={replay.loading || !replay.canShiftNext}
                onClick={() => void replay.shiftWindow(1)}
                title={!replay.canShiftNext ? "At replay end" : undefined}
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
          viewKey={mode === "replay" ? `${mode}:${replay.session?.session_id ?? ""}:${indicatorInterval}` : mode}
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
