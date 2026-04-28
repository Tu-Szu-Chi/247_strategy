import { useCallback, useEffect, useRef, useState } from "react";
import { createReplaySession, getReplayBundle, getReplayDefault } from "./api";
import type {
  ChartBarPoint,
  IndicatorInterval,
  IndicatorSeriesMap,
  ReplaySession,
} from "./types";

const INITIAL_REPLAY_WINDOW_HOURS = 3;
const REPLAY_WINDOW_PADDING_MINUTES = 30;

type ReplayState = {
  bars: ChartBarPoint[];
  session: ReplaySession | null;
  windowStart: string | null;
  windowEnd: string | null;
  loadedInterval: IndicatorInterval | null;
  loading: boolean;
  error: string | null;
};

export function useOptionPowerReplay(
  seriesNames: string[],
  enabled: boolean,
  interval: IndicatorInterval,
) {
  const seriesKey = seriesNames.join(",");
  const [state, setState] = useState<ReplayState>({
    bars: [],
    session: null,
    windowStart: null,
    windowEnd: null,
    loadedInterval: null,
    loading: enabled,
    error: null,
  });
  const [series, setSeries] = useState<IndicatorSeriesMap>({});
  const lastLoadKeyRef = useRef("");
  const stateRef = useRef(state);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const loadSession = useCallback(
    async (
      session: ReplaySession,
      interval: IndicatorInterval,
      requestedWindow?: { start: string; end: string },
    ) => {
      const window = requestedWindow ?? initialReplayWindow(session);
      setState((current) => ({
        ...current,
        bars: current.session?.session_id === session.session_id ? current.bars : [],
        session,
        windowStart: window.start,
        windowEnd: window.end,
        loadedInterval: current.session?.session_id === session.session_id ? current.loadedInterval : null,
        loading: true,
        error: null,
      }));
      if (stateRef.current.session?.session_id !== session.session_id) {
        setSeries({});
      }
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      requestIdRef.current += 1;
      const requestId = requestIdRef.current;
      try {
        const bundle = await getReplayBundle(
          session.session_id,
          window.start,
          window.end,
          interval,
          seriesNames,
          controller.signal,
        );
        if (requestId !== requestIdRef.current) {
          return session;
        }
        setState((current) => {
          const shouldMerge = (
            current.session?.session_id === session.session_id
            && current.loadedInterval === interval
          );
          const mergedBars = shouldMerge ? mergeBars(current.bars, bundle.bars) : bundle.bars;
          const loadedWindow = shouldMerge
            ? mergeWindows(
                { start: current.windowStart ?? window.start, end: current.windowEnd ?? window.end },
                window,
              )
            : window;
          return {
            bars: mergedBars,
            session,
            windowStart: loadedWindow.start,
            windowEnd: loadedWindow.end,
            loadedInterval: interval,
            loading: false,
            error: null,
          };
        });
        setSeries((current) => (
          stateRef.current.session?.session_id === session.session_id
            && stateRef.current.loadedInterval === interval
            ? mergeSeriesMaps(current, bundle.series)
            : bundle.series
        ));
        lastLoadKeyRef.current = `${seriesKey}:${session.session_id}:${interval}`;
        return session;
      } catch (error) {
        if (controller.signal.aborted || requestId !== requestIdRef.current) {
          return session;
        }
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

  const loadDefault = useCallback(async (interval: IndicatorInterval) => {
    const session = await getReplayDefault();
    return loadSession(session, interval);
  }, [loadSession]);

  const createSession = useCallback(
    async (start: string, end: string) => {
      const session = await createReplaySession(start, end);
      return loadSession(session, interval);
    },
    [interval, loadSession],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      abortRef.current?.abort();
      return;
    }
    const sessionKey = state.session?.session_id ?? "default";
    const loadKey = `${seriesKey}:${sessionKey}:${interval}`;
    if (lastLoadKeyRef.current === loadKey) {
      return;
    }
    const runner = state.session
      ? loadSession(
          state.session,
          interval,
          state.windowStart && state.windowEnd
            ? { start: state.windowStart, end: state.windowEnd }
            : undefined,
        )
      : loadDefault(interval);
    void runner.catch(() => {
      setState((current) => ({
        ...current,
        loading: false,
      }));
    });
  }, [
    enabled,
    interval,
    loadDefault,
    loadSession,
    seriesKey,
    state.session,
  ]);

  const shiftWindow = useCallback(
    async (direction: -1 | 1) => {
      if (!state.session) {
        return null;
      }
      const currentWindow = state.windowStart && state.windowEnd
        ? { start: state.windowStart, end: state.windowEnd }
        : initialReplayWindow(state.session);
      const nextWindow = shiftedReplayWindow(state.session, currentWindow, direction);
      if (
        nextWindow.start === currentWindow.start
        && nextWindow.end === currentWindow.end
      ) {
        return state.session;
      }
      return loadSession(state.session, interval, nextWindow);
    },
    [interval, loadSession, state.session, state.windowEnd, state.windowStart],
  );

  const resetWindow = useCallback(async () => {
    if (!state.session) {
      return null;
    }
    return loadSession(state.session, interval, initialReplayWindow(state.session));
  }, [interval, loadSession, state.session]);

  const ensureWindowForVisibleRange = useCallback(
    async (start: string, end: string) => {
      if (!state.session) {
        return null;
      }
      if (state.windowStart && state.windowEnd) {
        const loadedStart = new Date(state.windowStart).getTime();
        const loadedEnd = new Date(state.windowEnd).getTime();
        const visibleStart = new Date(start).getTime();
        const visibleEnd = new Date(end).getTime();
        if (visibleStart >= loadedStart && visibleEnd <= loadedEnd) {
          return state.session;
        }
      }
      return loadSession(
        state.session,
        interval,
        replayWindowForVisibleRange(state.session, start, end),
      );
    },
    [interval, loadSession, state.session, state.windowEnd, state.windowStart],
  );

  return {
    ...state,
    series,
    createSession,
    loadSession,
    shiftWindow,
    resetWindow,
    ensureWindowForVisibleRange,
    canShiftPrev: canShiftReplayWindow(state.session, state.windowStart, -1),
    canShiftNext: canShiftReplayWindow(state.session, state.windowEnd, 1),
  };
}

function mergeBars(existing: ChartBarPoint[], incoming: ChartBarPoint[]) {
  const merged = new Map<string, ChartBarPoint>();
  for (const bar of existing) {
    merged.set(bar.time, bar);
  }
  for (const bar of incoming) {
    merged.set(bar.time, bar);
  }
  return [...merged.values()].sort((left, right) => left.time.localeCompare(right.time));
}

function mergeSeriesMaps(
  existing: IndicatorSeriesMap,
  incoming: IndicatorSeriesMap,
): IndicatorSeriesMap {
  const merged: IndicatorSeriesMap = { ...existing };
  for (const [name, points] of Object.entries(incoming)) {
    const byTime = new Map<string, { time: string; value: number }>();
    for (const point of existing[name] ?? []) {
      byTime.set(point.time, point);
    }
    for (const point of points) {
      byTime.set(point.time, point);
    }
    merged[name] = [...byTime.values()].sort((left, right) => left.time.localeCompare(right.time));
  }
  return merged;
}

function initialReplayWindow(session: ReplaySession) {
  const start = new Date(session.start);
  const end = new Date(session.end);
  const windowEnd = new Date(start.getTime() + INITIAL_REPLAY_WINDOW_HOURS * 60 * 60 * 1000);
  return {
    start: toLocalIsoString(start),
    end: toLocalIsoString(windowEnd <= end ? windowEnd : end),
  };
}

function shiftedReplayWindow(
  session: ReplaySession,
  currentWindow: { start: string; end: string },
  direction: -1 | 1,
) {
  const sessionStart = new Date(session.start);
  const sessionEnd = new Date(session.end);
  const currentStart = new Date(currentWindow.start);
  const currentEnd = new Date(currentWindow.end);
  const windowMs = currentEnd.getTime() - currentStart.getTime();
  const shiftMs = INITIAL_REPLAY_WINDOW_HOURS * 60 * 60 * 1000 * direction;
  let nextStart = new Date(currentStart.getTime() + shiftMs);
  let nextEnd = new Date(currentEnd.getTime() + shiftMs);

  if (nextStart < sessionStart) {
    nextStart = sessionStart;
    nextEnd = new Date(Math.min(sessionStart.getTime() + windowMs, sessionEnd.getTime()));
  }
  if (nextEnd > sessionEnd) {
    nextEnd = sessionEnd;
    nextStart = new Date(Math.max(sessionStart.getTime(), sessionEnd.getTime() - windowMs));
  }

  return {
    start: toLocalIsoString(nextStart),
    end: toLocalIsoString(nextEnd),
  };
}

function mergeWindows(
  current: { start: string; end: string },
  incoming: { start: string; end: string },
) {
  return {
    start: new Date(current.start).getTime() <= new Date(incoming.start).getTime()
      ? current.start
      : incoming.start,
    end: new Date(current.end).getTime() >= new Date(incoming.end).getTime()
      ? current.end
      : incoming.end,
  };
}

function replayWindowForVisibleRange(
  session: ReplaySession,
  visibleStart: string,
  visibleEnd: string,
) {
  const sessionStart = new Date(session.start);
  const sessionEnd = new Date(session.end);
  const visibleStartDate = new Date(visibleStart);
  const visibleEndDate = new Date(visibleEnd);
  const paddingMs = REPLAY_WINDOW_PADDING_MINUTES * 60 * 1000;
  const windowMs = INITIAL_REPLAY_WINDOW_HOURS * 60 * 60 * 1000;
  let start = new Date(visibleStartDate.getTime() - paddingMs);
  let end = new Date(start.getTime() + windowMs);

  if (end < visibleEndDate) {
    end = new Date(visibleEndDate.getTime() + paddingMs);
    start = new Date(end.getTime() - windowMs);
  }
  if (start < sessionStart) {
    start = sessionStart;
    end = new Date(Math.min(sessionStart.getTime() + windowMs, sessionEnd.getTime()));
  }
  if (end > sessionEnd) {
    end = sessionEnd;
    start = new Date(Math.max(sessionStart.getTime(), sessionEnd.getTime() - windowMs));
  }

  return {
    start: toLocalIsoString(start),
    end: toLocalIsoString(end),
  };
}

function canShiftReplayWindow(
  session: ReplaySession | null,
  edge: string | null,
  direction: -1 | 1,
) {
  if (!session || !edge) {
    return false;
  }
  const sessionStart = new Date(session.start).getTime();
  const sessionEnd = new Date(session.end).getTime();
  const edgeTs = new Date(edge).getTime();
  if (direction < 0) {
    return edgeTs > sessionStart;
  }
  return edgeTs < sessionEnd;
}

function toLocalIsoString(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}
