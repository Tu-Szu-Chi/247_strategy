import { useCallback, useEffect, useMemo, useState } from "react";
import { MetricCard } from "../features/option-power/components/MetricCard";
import { SnapshotLadder } from "../features/option-power/components/SnapshotLadder";
import { TimelineCharts } from "../features/option-power/components/TimelineCharts";
import {
  INDICATOR_INTERVAL_OPTIONS,
  PRIMARY_SERIES_OPTIONS,
  SECONDARY_SERIES_OPTIONS,
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
  const [primarySeriesName, setPrimarySeriesName] = useState<string>("pressure_index");
  const [secondarySeriesName, setSecondarySeriesName] = useState<string>("raw_pressure");
  const [indicatorInterval, setIndicatorInterval] = useState<IndicatorInterval>("1m");
  const [selectedExpiry, setSelectedExpiry] = useState("");
  const [snapshot, setSnapshot] = useState<OptionPowerSnapshot | null>(null);
  const [cursorTime, setCursorTime] = useState("-");
  const [replayStart, setReplayStart] = useState("");
  const [replayEnd, setReplayEnd] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);

  const requestedSeries = useMemo(
    () => Array.from(new Set([primarySeriesName, secondarySeriesName])),
    [primarySeriesName, secondarySeriesName],
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
  const primarySeries = useMemo(
    () => resampleSeries(activeSeries[primarySeriesName] ?? [], indicatorInterval),
    [activeSeries, indicatorInterval, primarySeriesName],
  );
  const secondarySeries = useMemo(
    () => resampleSeries(activeSeries[secondarySeriesName] ?? [], indicatorInterval),
    [activeSeries, indicatorInterval, secondarySeriesName],
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
  const sessionTone = toneOf(snapshot?.pressure_index ?? 0);
  const headingEyebrow = mode === "live" ? "Research Live" : "Research Replay";
  const headingSubtitle = mode === "live"
    ? "主圖看 MTX，副圖看即時 pressure；頁面只連 live API，不再做 replay fallback。"
    : "主圖看 MTX，下方雙副圖同時比對 index、abs 或 slope；indicator 可切換 5s / 30s / 1m / 5m 聚合。";

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
          <span>Primary</span>
          <select value={primarySeriesName} onChange={(event) => setPrimarySeriesName(event.target.value)}>
            {PRIMARY_SERIES_OPTIONS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Secondary</span>
          <select value={secondarySeriesName} onChange={(event) => setSecondarySeriesName(event.target.value)}>
            {SECONDARY_SERIES_OPTIONS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

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
          primarySeries={primarySeries}
          secondarySeries={secondarySeries}
          mode={mode}
          primarySeriesName={`${primarySeriesName} @ ${indicatorInterval}`}
          secondarySeriesName={`${secondarySeriesName} @ ${indicatorInterval}`}
          onCursorTimeChange={requestSnapshotAt}
        />

        <aside className={styles.sidePanel}>
          <section className={styles.metricGrid}>
            <MetricCard label="Session Raw" value={formatSigned(snapshot?.raw_pressure ?? 0)} tone={sessionTone} />
            <MetricCard label="Session Index" value={formatSigned(snapshot?.pressure_index ?? 0)} tone={sessionTone} />
            <MetricCard label="1m Raw" value={formatSigned(snapshot?.raw_pressure_1m ?? 0)} tone={toneOf(snapshot?.pressure_index_1m ?? 0)} />
            <MetricCard label="1m Index" value={formatSigned(snapshot?.pressure_index_1m ?? 0)} tone={toneOf(snapshot?.pressure_index_1m ?? 0)} />
            <MetricCard label="5m Index" value={formatSigned(snapshot?.pressure_index_5m ?? 0)} tone={toneOf(snapshot?.pressure_index_5m ?? 0)} />
            <MetricCard label="Session Abs" value={formatUnsigned(snapshot?.pressure_abs ?? 0)} />
            <MetricCard label="1m Abs" value={formatUnsigned(snapshot?.pressure_abs_1m ?? 0)} />
            <MetricCard label="5m Abs" value={formatUnsigned(snapshot?.pressure_abs_5m ?? 0)} />
          </section>

          <section className={styles.aggregateGrid}>
            <MetricCard label="Call Cum" value={formatSigned(contractTotals.call.cumulative_power)} tone={toneOf(contractTotals.call.cumulative_power)} />
            <MetricCard label="Put Cum" value={formatSigned(contractTotals.put.cumulative_power)} tone={toneOf(contractTotals.put.cumulative_power)} />
            <MetricCard label="Call 1m" value={formatSigned(contractTotals.call.power_1m_delta)} tone={toneOf(contractTotals.call.power_1m_delta)} />
            <MetricCard label="Put 1m" value={formatSigned(contractTotals.put.power_1m_delta)} tone={toneOf(contractTotals.put.power_1m_delta)} />
          </section>

          <SnapshotLadder
            snapshot={snapshot}
            selectedExpiry={selectedExpiry}
            onExpiryChange={setSelectedExpiry}
          />
        </aside>
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

function formatUnsigned(value: number) {
  return Number(value || 0).toFixed(0);
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
