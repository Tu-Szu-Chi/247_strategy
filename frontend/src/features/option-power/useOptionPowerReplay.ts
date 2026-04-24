import { useCallback, useEffect, useRef, useState } from "react";
import { createReplaySession, getReplayBundle, getReplayDefault } from "./api";
import type { ChartBarPoint, IndicatorSeriesMap, ReplaySession, SnapshotLookupResponse } from "./types";

type ReplayState = {
  bars: ChartBarPoint[];
  session: ReplaySession | null;
  snapshot: SnapshotLookupResponse | null;
  loading: boolean;
  error: string | null;
};

export function useOptionPowerReplay(seriesNames: string[], enabled: boolean) {
  const seriesKey = seriesNames.join(",");
  const [state, setState] = useState<ReplayState>({
    bars: [],
    session: null,
    snapshot: null,
    loading: enabled,
    error: null,
  });
  const [series, setSeries] = useState<IndicatorSeriesMap>({});
  const lastLoadKeyRef = useRef("");

  const loadSession = useCallback(
    async (session: ReplaySession) => {
      setState((current) => ({
        ...current,
        session,
        loading: true,
        error: null,
      }));
      try {
        const bundle = await getReplayBundle(session.session_id, session.start, seriesNames);
        setState({
          bars: bundle.bars,
          session,
          snapshot: bundle.snapshot,
          loading: false,
          error: null,
        });
        setSeries(bundle.series);
        return session;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Replay bundle load failed.";
        setState((current) => ({
          ...current,
          loading: false,
          error: message,
        }));
        throw error;
      }
    },
    [seriesKey],
  );

  const loadDefault = useCallback(async () => {
    const session = await getReplayDefault();
    return loadSession(session);
  }, [loadSession]);

  const createSession = useCallback(
    async (start: string, end: string) => {
      const session = await createReplaySession(start, end);
      return loadSession(session);
    },
    [loadSession],
  );

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const sessionKey = state.session?.session_id ?? "default";
    const loadKey = `${seriesKey}:${sessionKey}`;
    if (lastLoadKeyRef.current === loadKey) {
      return;
    }
    lastLoadKeyRef.current = loadKey;
    const runner = state.session ? loadSession(state.session) : loadDefault();
    void runner.catch(() => {
      setState((current) => ({
        ...current,
        loading: false,
      }));
    });
  }, [enabled, loadDefault, loadSession, seriesKey, state.session]);

  return {
    ...state,
    series,
    createSession,
    loadSession,
  };
}
