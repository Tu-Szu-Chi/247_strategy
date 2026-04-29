import { useCallback, useEffect, useRef, useState } from "react";
import {
  createReplaySession,
  getReplayBundle,
  getReplayBundleByBars,
  getReplayDefault,
  getReplayProgress,
} from "./api";
import type {
  ChartBarPoint,
  IndicatorInterval,
  IndicatorSeriesMap,
  ReplayComputeStatus,
  ReplaySession,
} from "./types";

const INITIAL_REPLAY_WINDOW_HOURS = 3;
const REPLAY_WINDOW_PADDING_MINUTES = 30;
const PREFETCH_EDGE_THRESHOLD_MINUTES = 30;
const CURSOR_PREFETCH_BAR_COUNT = 50;

type LoadOptions = {
  updateWindow?: boolean;
  showLoading?: boolean;
};

type ReplayState = {
  bars: ChartBarPoint[];
  session: ReplaySession | null;
  windowStart: string | null;
  windowEnd: string | null;
  loadedStart: string | null;
  loadedEnd: string | null;
  loadedInterval: IndicatorInterval | null;
  computeStatus: ReplayComputeStatus;
  computedUntil: string | null;
  progressRatio: number;
  partial: boolean;
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
    loadedStart: null,
    loadedEnd: null,
    loadedInterval: null,
    computeStatus: "pending",
    computedUntil: null,
    progressRatio: 0,
    partial: false,
    loading: enabled,
    error: null,
  });
  const [series, setSeries] = useState<IndicatorSeriesMap>({});
  const lastLoadKeyRef = useRef("");
  const stateRef = useRef(state);
  const abortRef = useRef<AbortController | null>(null);
  const foregroundRequestIdRef = useRef(0);
  const readyReloadKeyRef = useRef("");
  const prefetchInFlightRef = useRef<Set<string>>(new Set());
  const cursorInFlightRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const loadSession = useCallback(
    async (
      session: ReplaySession,
      interval: IndicatorInterval,
      requestedWindow?: { start: string; end: string },
      options: LoadOptions = {},
    ) => {
      const updateWindow = options.updateWindow ?? true;
      const showLoading = options.showLoading ?? true;
      const window = requestedWindow ?? initialReplayWindow(session);
      setState((current) => ({
        ...current,
        bars: current.session?.session_id === session.session_id ? current.bars : [],
        session,
        windowStart: updateWindow ? window.start : current.windowStart,
        windowEnd: updateWindow ? window.end : current.windowEnd,
        loadedStart: current.session?.session_id === session.session_id ? current.loadedStart : null,
        loadedEnd: current.session?.session_id === session.session_id ? current.loadedEnd : null,
        loadedInterval: current.session?.session_id === session.session_id ? current.loadedInterval : null,
        computeStatus: session.compute_status ?? current.computeStatus,
        computedUntil: session.computed_until ?? current.computedUntil,
        progressRatio: session.progress_ratio ?? current.progressRatio,
        partial: current.session?.session_id === session.session_id ? current.partial : false,
        loading: showLoading ? true : current.loading,
        error: null,
      }));
      if (stateRef.current.session?.session_id !== session.session_id) {
        setSeries({});
      }
      const controller = showLoading ? new AbortController() : null;
      const requestId = showLoading ? foregroundRequestIdRef.current + 1 : 0;
      if (showLoading) {
        abortRef.current?.abort();
        abortRef.current = controller;
        foregroundRequestIdRef.current = requestId;
      }
      try {
        const bundle = await getReplayBundle(
          session.session_id,
          window.start,
          window.end,
          interval,
          seriesNames,
          controller?.signal,
        );
        if (showLoading && requestId !== foregroundRequestIdRef.current) {
          return session;
        }
        setState((current) => {
          if (current.session?.session_id !== session.session_id) {
            return current;
          }
          const shouldMerge = (
            current.loadedInterval === interval
          );
          const mergedBars = shouldMerge ? mergeBars(current.bars, bundle.bars) : bundle.bars;
          const loadedWindow = shouldMerge
            ? mergeWindows(
                { start: current.loadedStart ?? window.start, end: current.loadedEnd ?? window.end },
                window,
              )
            : window;
          return {
            bars: mergedBars,
            session: current.session,
            windowStart: updateWindow ? window.start : current.windowStart,
            windowEnd: updateWindow ? window.end : current.windowEnd,
            loadedStart: loadedWindow.start,
            loadedEnd: loadedWindow.end,
            loadedInterval: interval,
            computeStatus: bundle.seriesStatus.compute_status,
            computedUntil: bundle.seriesStatus.computed_until,
            progressRatio: bundle.seriesStatus.progress_ratio,
            partial: bundle.seriesStatus.partial,
            loading: showLoading ? false : current.loading,
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
        if ((controller?.signal.aborted ?? false) || (showLoading && requestId !== foregroundRequestIdRef.current)) {
          return session;
        }
        const message = error instanceof Error ? error.message : "Replay bundle load failed.";
        if (showLoading) {
          setState((current) => ({
            ...current,
            loading: false,
            error: message,
          }));
        }
        throw error;
      }
    },
    [seriesKey],
  );

  const loadDefault = useCallback(async (interval: IndicatorInterval) => {
    const session = await getReplayDefault();
    return loadSession(session, interval);
  }, [loadSession]);

  const loadSessionByBars = useCallback(
    async (
      session: ReplaySession,
      direction: "prev" | "next",
      anchor: string,
    ) => {
      const cursorKey = `${seriesKey}:${session.session_id}:${interval}:${direction}:${anchor}:${CURSOR_PREFETCH_BAR_COUNT}`;
      if (cursorInFlightRef.current.has(cursorKey)) {
        return session;
      }
      cursorInFlightRef.current.add(cursorKey);
      setState((current) => ({
        ...current,
        session,
        bars: current.loadedInterval === interval ? current.bars : [],
        loadedStart: current.loadedInterval === interval ? current.loadedStart : null,
        loadedEnd: current.loadedInterval === interval ? current.loadedEnd : null,
        loadedInterval: current.loadedInterval === interval ? current.loadedInterval : null,
        computeStatus: session.compute_status ?? current.computeStatus,
        computedUntil: session.computed_until ?? current.computedUntil,
        progressRatio: session.progress_ratio ?? current.progressRatio,
        error: null,
      }));
      try {
        const bundle = await getReplayBundleByBars(
          session.session_id,
          anchor,
          direction,
          CURSOR_PREFETCH_BAR_COUNT,
          interval,
          seriesNames,
        );
        setState((current) => {
          const responseSession = bundle.session ?? session;
          if (current.session?.session_id !== session.session_id && current.session?.session_id !== responseSession.session_id) {
            return current;
          }
          const hasCoverage = bundle.coverage.first_bar_time && bundle.coverage.last_bar_time;
          const incomingWindow = hasCoverage
            ? {
                start: bundle.coverage.first_bar_time ?? anchor,
                end: bundle.coverage.last_bar_time ?? anchor,
              }
            : null;
          const loadedWindow = incomingWindow
            ? mergeWindows(
                { start: current.loadedStart ?? incomingWindow.start, end: current.loadedEnd ?? incomingWindow.end },
                incomingWindow,
              )
            : { start: current.loadedStart, end: current.loadedEnd };
          return {
            ...current,
            session: responseSession,
            bars: mergeBars(current.bars, bundle.bars),
            loadedStart: loadedWindow.start,
            loadedEnd: loadedWindow.end,
            loadedInterval: interval,
            computeStatus: bundle.seriesStatus.compute_status,
            computedUntil: bundle.seriesStatus.computed_until,
            progressRatio: bundle.seriesStatus.progress_ratio,
            partial: bundle.seriesStatus.partial,
            error: null,
          };
        });
        setSeries((current) => mergeSeriesMaps(current, bundle.series));
        return session;
      } finally {
        cursorInFlightRef.current.delete(cursorKey);
      }
    },
    [interval, seriesKey],
  );

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
    if (!enabled || !state.session) {
      return;
    }
    const sessionId = state.session.session_id;
    let closed = false;
    const applyProgress = (payload: {
      compute_status: ReplayComputeStatus;
      computed_until: string | null;
      progress_ratio: number;
      checkpoint_count: number;
    }) => {
      if (closed) {
        return;
      }
      const current = stateRef.current;
      const shouldReloadReadyWindow = (
        payload.compute_status === "ready"
        && current.partial
        && !current.loading
        && current.session?.session_id === sessionId
        && current.loadedStart
        && current.loadedEnd
      );
      const readyReloadKey = shouldReloadReadyWindow
        ? `${seriesKey}:${sessionId}:${interval}:${current.loadedStart}:${current.loadedEnd}`
        : "";
      setState((current) => ({
        ...current,
        session: current.session?.session_id === sessionId
          ? {
              ...current.session,
              compute_status: payload.compute_status,
              computed_until: payload.computed_until,
              progress_ratio: payload.progress_ratio,
              checkpoint_count: payload.checkpoint_count,
            }
          : current.session,
        computeStatus: payload.compute_status,
        computedUntil: payload.computed_until,
        progressRatio: payload.progress_ratio,
        partial: current.partial,
      }));
      if (
        shouldReloadReadyWindow
        && current.session
        && current.loadedStart
        && current.loadedEnd
        && readyReloadKeyRef.current !== readyReloadKey
      ) {
        readyReloadKeyRef.current = readyReloadKey;
        void loadSession(
          current.session,
          interval,
          { start: current.loadedStart, end: current.loadedEnd },
          { updateWindow: false, showLoading: false },
        ).catch(() => {});
      }
    };

    if (typeof EventSource !== "undefined") {
      const events = new EventSource(`/api/option-power/replay/sessions/${sessionId}/events`);
      events.addEventListener("progress", (event) => {
        applyProgress(JSON.parse((event as MessageEvent).data));
      });
      events.onerror = () => {
        events.close();
      };
      return () => {
        closed = true;
        events.close();
      };
    }

    const controller = new AbortController();
    const poll = window.setInterval(() => {
      void getReplayProgress(sessionId, controller.signal)
        .then(applyProgress)
        .catch(() => {});
    }, 1000);
    return () => {
      closed = true;
      controller.abort();
      window.clearInterval(poll);
    };
  }, [enabled, interval, loadSession, seriesKey, state.session?.session_id]);

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
    async (
      start: string,
      end: string,
      options: { hasLeftWhitespace?: boolean; hasRightWhitespace?: boolean } = {},
    ) => {
      if (!state.session) {
        return null;
      }
      const visibleStart = new Date(start).getTime();
      const visibleEnd = new Date(end).getTime();
      const sessionStart = new Date(state.session.start).getTime();
      const sessionEnd = new Date(state.session.end).getTime();
      const thresholdMs = PREFETCH_EDGE_THRESHOLD_MINUTES * 60 * 1000;
      const wantsPrev = options.hasLeftWhitespace === true || (
        state.loadedStart !== null && visibleStart < new Date(state.loadedStart).getTime()
      );
      const wantsNext = options.hasRightWhitespace === true || (
        state.loadedEnd !== null && visibleEnd > new Date(state.loadedEnd).getTime()
      );
      const needsLargerSession = (
        visibleStart < sessionStart
        || visibleEnd > sessionEnd
        || (options.hasLeftWhitespace === true && visibleStart <= sessionStart + thresholdMs)
        || (options.hasRightWhitespace === true && visibleEnd >= sessionEnd - thresholdMs)
      );
      if (needsLargerSession) {
        const nextSessionRange = replaySessionRangeForVisibleRange(state.session, start, end, options);
        const nextWindowKey = `${nextSessionRange.start}:${nextSessionRange.end}`;
        const prefetchKey = `extend:${state.session.session_id}:${interval}:${nextWindowKey}`;
        if (prefetchInFlightRef.current.has(prefetchKey)) {
          return state.session;
        }
        prefetchInFlightRef.current.add(prefetchKey);
        try {
          const nextSession = await createReplaySession(nextSessionRange.start, nextSessionRange.end);
          if (wantsPrev && state.loadedStart) {
            return loadSessionByBars(nextSession, "prev", state.loadedStart);
          }
          if (wantsNext && state.loadedEnd) {
            return loadSessionByBars(nextSession, "next", state.loadedEnd);
          }
          return loadSession(nextSession, interval, replayWindowForVisibleRange(nextSession, start, end));
        } finally {
          prefetchInFlightRef.current.delete(prefetchKey);
        }
      }
      if (state.loadedStart && state.loadedEnd) {
        const loadedStart = new Date(state.loadedStart).getTime();
        const loadedEnd = new Date(state.loadedEnd).getTime();
        const nearLoadedStart = visibleStart - loadedStart <= thresholdMs && loadedStart > sessionStart;
        const nearLoadedEnd = loadedEnd - visibleEnd <= thresholdMs && loadedEnd < sessionEnd;
        if (
          visibleStart >= loadedStart
          && visibleEnd <= loadedEnd
          && !nearLoadedStart
          && !nearLoadedEnd
        ) {
          return state.session;
        }
      }
      if (wantsPrev && state.loadedStart) {
        return loadSessionByBars(state.session, "prev", state.loadedStart);
      }
      if (wantsNext && state.loadedEnd) {
        return loadSessionByBars(state.session, "next", state.loadedEnd);
      }
      const nextWindow = replayWindowForVisibleRange(state.session, start, end);
      const prefetchKey = `${state.session.session_id}:${interval}:${nextWindow.start}:${nextWindow.end}`;
      if (prefetchInFlightRef.current.has(prefetchKey)) {
        return state.session;
      }
      prefetchInFlightRef.current.add(prefetchKey);
      try {
        return await loadSession(
          state.session,
          interval,
          nextWindow,
          { updateWindow: false, showLoading: false },
        );
      } finally {
        prefetchInFlightRef.current.delete(prefetchKey);
      }
    },
    [interval, loadSession, loadSessionByBars, state.loadedEnd, state.loadedStart, state.session],
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

function replaySessionRangeForVisibleRange(
  session: ReplaySession,
  visibleStart: string,
  visibleEnd: string,
  options: { hasLeftWhitespace?: boolean; hasRightWhitespace?: boolean } = {},
) {
  const sessionStart = new Date(session.start);
  const sessionEnd = new Date(session.end);
  const visibleStartDate = new Date(visibleStart);
  const visibleEndDate = new Date(visibleEnd);
  const paddingMs = REPLAY_WINDOW_PADDING_MINUTES * 60 * 1000;
  const extendMs = INITIAL_REPLAY_WINDOW_HOURS * 60 * 60 * 1000;
  const nextStart = new Date(Math.min(
    sessionStart.getTime(),
    visibleStartDate.getTime() - paddingMs,
    options.hasLeftWhitespace === true ? sessionStart.getTime() - extendMs : sessionStart.getTime(),
  ));
  const nextEnd = new Date(Math.max(
    sessionEnd.getTime(),
    visibleEndDate.getTime() + paddingMs,
    options.hasRightWhitespace === true ? sessionEnd.getTime() + extendMs : sessionEnd.getTime(),
  ));

  return {
    start: toLocalIsoString(nextStart),
    end: toLocalIsoString(nextEnd),
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
