import { useCallback, useEffect, useMemo, useState } from "react";
import { MetricCard } from "../features/option-power/components/MetricCard";
import { SnapshotLadder } from "../features/option-power/components/SnapshotLadder";
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
import { useSnapshotAtCursor } from "../features/option-power/useSnapshotAtCursor";
import type { IndicatorInterval, OptionPowerSnapshot } from "../features/option-power/types";
import styles from "./ResearchPage.module.css";

type OptionPowerResearchWorkspaceProps = {
  mode: "live" | "replay";
};

export function OptionPowerResearchWorkspace({
  mode,
}: OptionPowerResearchWorkspaceProps) {
  const [indicatorInterval, setIndicatorInterval] = useState<IndicatorInterval>("1m");
  const [selectedExpiry, setSelectedExpiry] = useState("");
  const [snapshot, setSnapshot] = useState<OptionPowerSnapshot | null>(null);
  const [cursorTime, setCursorTime] = useState("-");
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
      "trade_intensity_ratio_30m",
      "adx_14",
      "plus_di_14",
      "minus_di_14",
      "di_bias_14",
      "choppiness_14",
      "compression_score",
      "expansion_score",
      "compression_expansion_state",
      "session_cvd",
      "cvd_5m_delta",
      "cvd_15m_delta",
      "cvd_5m_slope",
      "cvd_price_alignment",
      "price_cvd_divergence_15m",
    ],
    [],
  );
  const live = useOptionPowerLive(requestedSeries, mode === "live");
  const replay = useOptionPowerReplay(requestedSeries, mode === "replay");

  useEffect(() => {
    if (mode === "live") {
      setSnapshot(live.snapshot);
      return;
    }
    if (replay.snapshot?.snapshot) {
      setSnapshot(replay.snapshot.snapshot);
      if (replay.snapshot.simulated_at) {
        setCursorTime(formatDateTime(replay.snapshot.simulated_at));
      }
    }
  }, [live.snapshot, mode, replay.snapshot]);

  useEffect(() => {
    if (mode === "replay" && replay.session) {
      setReplayStart(toDatetimeLocal(replay.session.start));
      setReplayEnd(toDatetimeLocal(replay.session.end));
    }
  }, [mode, replay.session]);

  useEffect(() => {
    if (snapshot?.generated_at) {
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

  const handleSnapshotUpdate = useCallback((nextSnapshot: OptionPowerSnapshot) => {
    setSnapshot(nextSnapshot);
  }, []);

  const handleCursorTime = useCallback((ts: string) => {
    setCursorTime(formatDateTime(ts));
  }, []);

  const requestSnapshotAt = useSnapshotAtCursor({
    enabled: mode === "replay" || mode === "live",
    mode,
    replaySessionId: replay.session?.session_id ?? null,
    onSnapshot: handleSnapshotUpdate,
    onCursorTime: handleCursorTime,
  });

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

  const selectedContracts = selectExpiry(snapshot, selectedExpiry)?.contracts ?? [];
  const contractTotals = useMemo(
    () => summarizeContractsBySide(selectedContracts),
    [selectedContracts],
  );
  const structureState = useMemo(
    () => seriesValueAt(activeSeries.structure_state ?? [], snapshot?.generated_at ?? null),
    [activeSeries.structure_state, snapshot?.generated_at],
  );
  const sessionTone = toneOf(snapshot?.pressure_index ?? 0);
  const weightedTone = toneOf(snapshot?.pressure_index_weighted ?? 0);
  const headingEyebrow = mode === "live" ? "Research Live" : "Research Replay";
  const headingSubtitle = mode === "live"
    ? "主圖固定看 MTX，副圖同步鋪開 pressure、regime 與 market structure。"
    : "主圖固定看 MTX，下方多副圖一次展開 pressure、regime 與 market structure，先專注觀察整體節奏。";
  const regime = snapshot?.regime ?? null;
  const signalState = useMemo(
    () => signalStateMeta(seriesValueAt(signalPanelSeries[0]?.points ?? [], snapshot?.generated_at ?? null)),
    [signalPanelSeries, snapshot?.generated_at],
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
          structureSeries={structurePanelSeries}
          biasSeries={biasPanelSeries}
          signalSeries={signalPanelSeries}
          contextSeries={contextPanelSeries}
          trendQualitySeries={trendQualityPanelSeries}
          cvdSeries={cvdPanelSeries}
          rangeStateSeries={rangeStatePanelSeries}
          mode={mode}
          onCursorTimeChange={requestSnapshotAt}
        />
      </section>

      <section className={styles.insights}>
        <section className={styles.metricGrid}>
          <MetricCard label="Signal State" value={signalState.label} tone={signalState.tone} />
          <MetricCard label="Intensity 30m" value={formatIntensity(regime?.trade_intensity_ratio_30m ?? 0)} tone={intensityTone(regime?.trade_intensity_ratio_30m ?? 0)} />
          <MetricCard label="Regime" value={formatRegimeLabel(regime?.regime_label ?? "no_data")} tone={regimeTone(regime?.regime_label ?? "no_data")} />
          <MetricCard label="Trend Score" value={formatSigned(regime?.trend_score ?? 0)} tone={toneOf(regime?.trend_score ?? 0)} />
          <MetricCard label="Chop Score" value={formatSigned(regime?.chop_score ?? 0)} tone={toneOf(-(regime?.chop_score ?? 0))} />
          <MetricCard label="Reversal Risk" value={formatSigned(regime?.reversal_risk ?? 0)} tone={toneOf(-(regime?.reversal_risk ?? 0))} />
          <MetricCard label="VWAP Dist" value={formatSignedFloat(regime?.vwap_distance_bps ?? 0, " bps")} tone={toneOf(regime?.vwap_distance_bps ?? 0)} />
          <MetricCard label="Pressure Index" value={formatSigned(snapshot?.pressure_index ?? 0)} tone={sessionTone} />
          <MetricCard
            label="Index Weighted"
            value={formatSigned(snapshot?.pressure_index_weighted ?? 0)}
            tone={weightedTone}
          />
          <MetricCard label="Raw Pressure" value={formatSigned(snapshot?.raw_pressure ?? 0)} tone={toneOf(snapshot?.raw_pressure ?? 0)} />
          <MetricCard
            label="Raw Weighted"
            value={formatSigned(snapshot?.raw_pressure_weighted ?? 0)}
            tone={toneOf(snapshot?.raw_pressure_weighted ?? 0)}
          />
        </section>

        <section className={styles.aggregateGrid}>
          <MetricCard label="Call Cum" value={formatSigned(contractTotals.call.cumulative_power)} tone={toneOf(contractTotals.call.cumulative_power)} />
          <MetricCard label="Put Cum" value={formatSigned(contractTotals.put.cumulative_power)} tone={toneOf(contractTotals.put.cumulative_power)} />
          <MetricCard label="Call 1m" value={formatSigned(contractTotals.call.power_1m_delta)} tone={toneOf(contractTotals.call.power_1m_delta)} />
          <MetricCard label="Put 1m" value={formatSigned(contractTotals.put.power_1m_delta)} tone={toneOf(contractTotals.put.power_1m_delta)} />
        </section>
      </section>

      <section className={styles.expirySection}>
        <SnapshotLadder
          snapshot={snapshot}
          selectedExpiry={selectedExpiry}
          onExpiryChange={setSelectedExpiry}
        />
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
  if (!targetTime) {
    return 0;
  }
  const target = points.find((point) => point.time === targetTime);
  return Number(target?.value ?? 0);
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

function deriveSignalSeries(
  activeSeries: Record<string, { time: string; value: number }[]>,
  interval: IndicatorInterval,
) {
  const pressureIndex = activeSeries.pressure_index ?? [];
  const rawPressure = activeSeries.raw_pressure ?? [];
  const regimeState = activeSeries.regime_state ?? [];
  const structureState = activeSeries.structure_state ?? [];
  const intensity = activeSeries.trade_intensity_ratio_30m ?? [];
  const adx = activeSeries.adx_14 ?? [];
  const choppiness = activeSeries.choppiness_14 ?? [];
  const diBias = activeSeries.di_bias_14 ?? [];
  const cvdSlope = activeSeries.cvd_5m_slope ?? [];
  const cvdAlignment = activeSeries.cvd_price_alignment ?? [];
  const cvdDivergence = activeSeries.price_cvd_divergence_15m ?? [];
  const rangeState = activeSeries.compression_expansion_state ?? [];
  const timeSet = new Set<string>();
  for (const series of [
    pressureIndex,
    rawPressure,
    regimeState,
    structureState,
    intensity,
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
  const adxMap = new Map(adx.map((point) => [point.time, Number(point.value ?? 0)]));
  const choppinessMap = new Map(choppiness.map((point) => [point.time, Number(point.value ?? 0)]));
  const diBiasMap = new Map(diBias.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdSlopeMap = new Map(cvdSlope.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdAlignmentMap = new Map(cvdAlignment.map((point) => [point.time, Number(point.value ?? 0)]));
  const cvdDivergenceMap = new Map(cvdDivergence.map((point) => [point.time, Number(point.value ?? 0)]));
  const rangeStateMap = new Map(rangeState.map((point) => [point.time, Number(point.value ?? 0)]));

  const orderedTimes = Array.from(timeSet).sort();
  const signalPoints = orderedTimes.map((time) => {
    const now = new Date(time);
    const pressureHistory = rollingWindowValues(pressureIndexMap, orderedTimes, now, 30);
    const rawHistory = rollingWindowValues(rawPressureMap, orderedTimes, now, 30);
    const slopeHistory = rollingWindowValues(cvdSlopeMap, orderedTimes, now, 30);
    const pressureAbsHistory = pressureHistory.map((value) => Math.abs(value));
    const rawAbsHistory = rawHistory.map((value) => Math.abs(value));
    const slopeAbsHistory = slopeHistory.map((value) => Math.abs(value));
    const biasValue = deriveBiasValue({
      pressureIndex: pressureIndexMap.get(time) ?? 0,
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
      pressureIndex: pressureIndexMap.get(time) ?? 0,
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
  const intensity = activeSeries.trade_intensity_ratio_30m ?? [];
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
      .map((time) => ({
        time,
        value: deriveBiasValue({
          pressureIndex: pressureIndexMap.get(time) ?? 0,
          regimeState: regimeStateMap.get(time) ?? 0,
          structureState: structureStateMap.get(time) ?? 0,
          intensityRatio: intensityMap.get(time) ?? 0,
        }),
      })),
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
  const cvdSlope = activeSeries.cvd_5m_slope ?? [];
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
  const divergence = activeSeries.price_cvd_divergence_15m ?? [];
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

function deriveSignalStateValue(input: {
  biasValue: number;
  regimeState: number;
  structureState: number;
  intensityRatio: number;
  pressureIndex: number;
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
  const pressureDirection = input.pressureIndex > 0 ? 1 : input.pressureIndex < 0 ? -1 : 0;
  const active = input.intensityRatio >= 0.95;
  const strongPressure = Math.abs(input.pressureIndex) >= input.strongPressureThreshold;
  const supportedRawPressure = Math.abs(input.rawPressure) >= input.rawPressureThreshold;
  const trendBiasDirection = input.diBiasValue > 8 ? 1 : input.diBiasValue < -8 ? -1 : 0;
  const flowDirection = input.cvdSlopeValue > input.flowThreshold ? 1 : input.cvdSlopeValue < -input.flowThreshold ? -1 : 0;
  const trendReady = input.adxValue >= 18 && input.choppinessValue <= 62;
  if (!active || input.biasValue === 0 || input.rangeStateValue < 0) {
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
  if (pressureDirection === input.biasValue) {
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

function deriveBiasValue(input: {
  pressureIndex: number;
  regimeState: number;
  structureState: number;
  intensityRatio: number;
}) {
  const pressureDirection = input.pressureIndex > 0 ? 1 : input.pressureIndex < 0 ? -1 : 0;
  const active = input.intensityRatio >= 0.95;
  if (!active) {
    return 0;
  }
  if (
    input.structureState > 0
    && pressureDirection > 0
    && input.regimeState >= 0
  ) {
    return 1;
  }
  if (
    input.structureState < 0
    && pressureDirection < 0
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
