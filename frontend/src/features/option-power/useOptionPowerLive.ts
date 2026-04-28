import { useEffect, useRef, useState } from "react";
import { ApiError, getLiveBundle } from "./api";
import type { ChartBarPoint, IndicatorSeriesMap, LiveMeta, OptionPowerSnapshot } from "./types";

type LiveState = {
  bars: ChartBarPoint[];
  meta: LiveMeta | null;
  snapshot: OptionPowerSnapshot | null;
  loading: boolean;
  error: string | null;
};

const POLL_MS = 5000;

export function useOptionPowerLive(seriesNames: string[], enabled: boolean, includeBars = true) {
  const seriesKey = seriesNames.join(",");
  const [state, setState] = useState<LiveState>({
    bars: [],
    meta: null,
    snapshot: null,
    loading: enabled,
    error: null,
  });
  const [series, setSeries] = useState<IndicatorSeriesMap>({});
  const timerRef = useRef<number | null>(null);

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
        const bundle = await getLiveBundle(seriesNames, includeBars);
        if (cancelled) {
          return;
        }
        setState({
          bars: bundle.bars,
          meta: bundle.meta,
          snapshot: bundle.latest.snapshot,
          loading: false,
          error: null,
        });
        setSeries(bundle.series);
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
