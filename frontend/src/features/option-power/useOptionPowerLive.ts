import { useEffect, useRef, useState } from "react";
import { ApiError, getLiveBundle, getLiveLatest } from "./api";
import type {
  ChartBarPoint,
  IndicatorSeriesMap,
  LiveContractTotals,
  LiveMeta,
  LiveSnapshotSummary,
} from "./types";

type LiveState = {
  bars: ChartBarPoint[];
  meta: LiveMeta | null;
  snapshot: LiveSnapshotSummary | null;
  contractTotals: LiveContractTotals | null;
  loading: boolean;
  error: string | null;
};

const POLL_MS = 10000;

export function useOptionPowerLive(seriesNames: string[], enabled: boolean, includeBars = true) {
  const seriesKey = seriesNames.join(",");
  const [state, setState] = useState<LiveState>({
    bars: [],
    meta: null,
    snapshot: null,
    contractTotals: null,
    loading: enabled,
    error: null,
  });
  const [series, setSeries] = useState<IndicatorSeriesMap>({});
  const timerRef = useRef<number | null>(null);
  const latestSnapshotTimeRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    let cancelled = false;

    async function load(initial = false) {
      if (initial) {
        setState((current) => ({ ...current, loading: true, error: null }));
      }
      try {
        if (initial) {
          const bundle = await getLiveBundle(seriesNames, includeBars);
          if (cancelled) {
            return;
          }
          setState({
            bars: bundle.bars,
            meta: bundle.meta,
            snapshot: bundle.latest.snapshot,
            contractTotals: bundle.latest.contract_totals,
            loading: false,
            error: null,
          });
          latestSnapshotTimeRef.current = bundle.latest.snapshot?.generated_at ?? null;
          setSeries(bundle.series);
          return;
        }
        const latest = await getLiveLatest(seriesNames, latestSnapshotTimeRef.current, includeBars);
        if (cancelled) {
          return;
        }
        if (latest.snapshot?.generated_at) {
          latestSnapshotTimeRef.current = latest.snapshot.generated_at;
        }
        setState((current) => ({
          ...current,
          bars: latest.latest_bar ? upsertBar(current.bars, latest.latest_bar) : current.bars,
          snapshot: latest.snapshot ?? current.snapshot,
          contractTotals: latest.contract_totals ?? current.contractTotals,
          loading: false,
          error: null,
        }));
        if (latest.updated) {
          setSeries((current) => mergeSeries(current, latest.series));
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message = error instanceof ApiError && error.status === 404
          ? "Live mode is not enabled on the current backend."
          : error instanceof Error
            ? error.message
            : "Live bundle load failed.";
        setState((current) => ({ ...current, loading: false, error: message }));
      } finally {
        if (!cancelled) {
          timerRef.current = window.setTimeout(() => void load(false), POLL_MS);
        }
      }
    }

    void load(true);

    return () => {
      cancelled = true;
      latestSnapshotTimeRef.current = null;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, includeBars, seriesKey]);

  return {
    ...state,
    series,
  };
}

function upsertBar(bars: ChartBarPoint[], nextBar: ChartBarPoint): ChartBarPoint[] {
  if (!bars.length) {
    return [nextBar];
  }
  const lastBar = bars[bars.length - 1];
  if (lastBar.time === nextBar.time) {
    return [...bars.slice(0, -1), nextBar];
  }
  return [...bars, nextBar];
}

function mergeSeries(current: IndicatorSeriesMap, incoming: IndicatorSeriesMap): IndicatorSeriesMap {
  const merged: IndicatorSeriesMap = { ...current };
  for (const [name, nextPoints] of Object.entries(incoming)) {
    if (!nextPoints.length) {
      continue;
    }
    const existing = merged[name] ?? [];
    const nextPoint = nextPoints[nextPoints.length - 1];
    if (existing.length && existing[existing.length - 1].time === nextPoint.time) {
      merged[name] = [...existing.slice(0, -1), nextPoint];
      continue;
    }
    merged[name] = [...existing, nextPoint];
  }
  return merged;
}
