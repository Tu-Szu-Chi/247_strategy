import { useCallback, useEffect, useRef, useState } from "react";
import {
  createReplaySession,
  getReplayBundle,
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
const MIN_REPLAY_POINTS = 600;
const MAX_REPLAY_POINTS = 2400;
const REPLAY_POINTS_PER_PIXEL = 2;

type LoadOptions = {
  updateWindow?: boolean;
  showLoading?: boolean;
};

type ReplayLoadedRange = {
  start: string;
  end: string;
};

type ReplayState = {
  bars: ChartBarPoint[];
  session: ReplaySession | null;
  windowStart: string | null;
  windowEnd: string | null;
  loadedStart: string | null;
  loadedEnd: string | null;
  loadedRanges: ReplayLoadedRange[];
  seriesLoadedRanges: ReplayLoadedRange[];
  seriesPendingRanges: ReplayLoadedRange[];
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
    loadedRanges: [],
    seriesLoadedRanges: [],
    seriesPendingRanges: [],
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
  const replayRequestSequenceRef = useRef(0);
  const bundleInFlightRef = useRef<Set<string>>(new Set());

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
      const bundleKey = `${seriesKey}:${session.session_id}:${interval}:${window.start}:${window.end}`;
      const isSameSession = stateRef.current.session?.session_id === session.session_id;
      const isSameInterval = stateRef.current.loadedInterval === interval;
      const canReuseLoadedData = isSameSession && isSameInterval;
      if (bundleInFlightRef.current.has(bundleKey)) {
        return session;
      }
      bundleInFlightRef.current.add(bundleKey);
      setState((current) => ({
        ...current,
        bars: canReuseLoadedData ? current.bars : [],
        session,
        windowStart: updateWindow ? window.start : current.windowStart,
        windowEnd: updateWindow ? window.end : current.windowEnd,
        loadedStart: canReuseLoadedData ? current.loadedStart : null,
        loadedEnd: canReuseLoadedData ? current.loadedEnd : null,
        loadedRanges: canReuseLoadedData ? current.loadedRanges : [],
        seriesLoadedRanges: canReuseLoadedData ? current.seriesLoadedRanges : [],
        seriesPendingRanges: canReuseLoadedData ? current.seriesPendingRanges : [],
        loadedInterval: canReuseLoadedData ? current.loadedInterval : null,
        computeStatus: session.compute_status ?? current.computeStatus,
        computedUntil: session.computed_until ?? current.computedUntil,
        progressRatio: session.progress_ratio ?? current.progressRatio,
        partial: canReuseLoadedData ? current.partial : false,
        loading: showLoading ? true : current.loading,
        error: null,
      }));
      if (!canReuseLoadedData) {
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
        const replayRequestId = nextReplayRequestId(replayRequestSequenceRef, "bundle");
        const bundle = await getReplayBundle(
          session.session_id,
          window.start,
          window.end,
          interval,
          seriesNames,
          controller?.signal,
          replayTargetMaxPoints(),
          replayRequestId,
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
          const loadedRanges = shouldMerge
            ? mergeLoadedRanges(current.loadedRanges, window)
            : [window];
          const seriesLoadedRanges = bundle.seriesStatus.partial
            ? (shouldMerge ? current.seriesLoadedRanges : [])
            : (shouldMerge ? mergeLoadedRanges(current.seriesLoadedRanges, window) : [window]);
          const seriesPendingRanges = bundle.seriesStatus.partial
            ? (shouldMerge ? mergeLoadedRanges(current.seriesPendingRanges, window) : [window])
            : removeCoveredRanges(shouldMerge ? current.seriesPendingRanges : [], window);
          const loadedBounds = loadedRangeBounds(loadedRanges);
          return {
            bars: mergedBars,
            session: current.session,
            windowStart: updateWindow ? window.start : current.windowStart,
            windowEnd: updateWindow ? window.end : current.windowEnd,
            loadedStart: loadedBounds.start,
            loadedEnd: loadedBounds.end,
            loadedRanges,
            seriesLoadedRanges,
            seriesPendingRanges,
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
      } finally {
        bundleInFlightRef.current.delete(bundleKey);
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
    if (!enabled || !state.session) {
      return;
    }
    const sessionId = state.session.session_id;
    let closed = false;
    const reloadLoadedWindow = (
      current: ReplayState,
      reloadKey: string,
    ) => {
      if (
        current.session
        && current.loadedStart
        && current.loadedEnd
        && readyReloadKeyRef.current !== reloadKey
      ) {
        readyReloadKeyRef.current = reloadKey;
        void loadSession(
          current.session,
          interval,
          { start: current.loadedStart, end: current.loadedEnd },
          { updateWindow: false, showLoading: false },
        ).catch(() => {});
      }
    };
    const reloadRange = (
      current: ReplayState,
      range: ReplayLoadedRange,
      reloadKey: string,
    ) => {
      if (
        current.session
        && readyReloadKeyRef.current !== reloadKey
      ) {
        readyReloadKeyRef.current = reloadKey;
        void loadSession(
          current.session,
          interval,
          range,
          { updateWindow: false, showLoading: false },
        ).catch(() => {});
      }
    };
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
      if (shouldReloadReadyWindow) {
        reloadLoadedWindow(current, readyReloadKey);
      }
    };
    const applyRangeReady = (payload: {
      session_id?: string;
      start?: string | null;
      end?: string | null;
      computed_until?: string | null;
      compute_status?: ReplayComputeStatus;
    }) => {
      if (closed || payload.session_id !== sessionId) {
        return;
      }
      const current = stateRef.current;
      if (!current.partial || current.loading) {
        return;
      }
      const computedUntil = payload.computed_until ?? payload.end;
      if (!computedUntil) {
        return;
      }
      const readyRanges = pendingRangesReadyBy(current.seriesPendingRanges, computedUntil);
      for (const range of readyRanges) {
        const reloadKey = `${seriesKey}:${sessionId}:${interval}:${range.start}:${range.end}:range:${computedUntil}`;
        reloadRange(current, range, reloadKey);
      }
    };

    if (typeof EventSource !== "undefined") {
      const events = new EventSource(`/api/option-power/replay/sessions/${sessionId}/events`);
      events.addEventListener("progress", (event) => {
        applyProgress(JSON.parse((event as MessageEvent).data));
      });
      events.addEventListener("range_ready", (event) => {
        applyRangeReady(JSON.parse((event as MessageEvent).data));
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

  return {
    ...state,
    series,
    createSession,
    loadSession,
    shiftWindow,
    resetWindow,
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

function mergeLoadedRanges(
  existing: ReplayLoadedRange[],
  incoming: ReplayLoadedRange,
): ReplayLoadedRange[] {
  return mergeLoadedRangeList([...existing, incoming]);
}

function mergeLoadedRangeList(ranges: ReplayLoadedRange[]): ReplayLoadedRange[] {
  const sortedRanges = ranges
    .filter((range) => range.start && range.end)
    .sort((left, right) => new Date(left.start).getTime() - new Date(right.start).getTime());
  const merged: ReplayLoadedRange[] = [];
  for (const range of sortedRanges) {
    const current = merged[merged.length - 1];
    if (!current) {
      merged.push({ ...range });
      continue;
    }
    const currentEnd = new Date(current.end).getTime();
    const nextStart = new Date(range.start).getTime();
    if (nextStart <= currentEnd + 1000) {
      if (new Date(range.end).getTime() > currentEnd) {
        current.end = range.end;
      }
      continue;
    }
    merged.push({ ...range });
  }
  return merged;
}

function removeCoveredRanges(
  ranges: ReplayLoadedRange[],
  covered: ReplayLoadedRange,
): ReplayLoadedRange[] {
  const coveredStart = new Date(covered.start).getTime();
  const coveredEnd = new Date(covered.end).getTime();
  const remaining: ReplayLoadedRange[] = [];
  for (const range of ranges) {
    const start = new Date(range.start).getTime();
    const end = new Date(range.end).getTime();
    if (end <= coveredStart || start >= coveredEnd) {
      remaining.push(range);
      continue;
    }
    if (start < coveredStart) {
      remaining.push({
        start: range.start,
        end: covered.start,
      });
    }
    if (end > coveredEnd) {
      remaining.push({
        start: covered.end,
        end: range.end,
      });
    }
  }
  return mergeLoadedRangeList(remaining);
}

function pendingRangesReadyBy(
  ranges: ReplayLoadedRange[],
  computedUntil: string,
): ReplayLoadedRange[] {
  const readyUntil = new Date(computedUntil).getTime();
  return ranges.filter((range) => new Date(range.start).getTime() <= readyUntil);
}

function loadedRangeBounds(ranges: ReplayLoadedRange[]) {
  if (ranges.length === 0) {
    return { start: null, end: null };
  }
  return {
    start: ranges[0].start,
    end: ranges[ranges.length - 1].end,
  };
}

function initialReplayWindow(session: ReplaySession) {
  return {
    start: session.start,
    end: session.end,
  };
}

function shiftedReplayWindow(
  session: ReplaySession,
  currentWindow: { start: string; end: string },
  direction: -1 | 1,
) {
  const { start: sessionStartValue, end: sessionEndValue } = replaySessionBounds(session);
  const sessionStart = new Date(sessionStartValue);
  const sessionEnd = new Date(sessionEndValue);
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

function canShiftReplayWindow(
  session: ReplaySession | null,
  edge: string | null,
  direction: -1 | 1,
) {
  if (!session || !edge) {
    return false;
  }
  const { start, end } = replaySessionBounds(session);
  const sessionStart = new Date(start).getTime();
  const sessionEnd = new Date(end).getTime();
  const edgeTs = new Date(edge).getTime();
  if (direction < 0) {
    return edgeTs > sessionStart;
  }
  return edgeTs < sessionEnd;
}

function replaySessionBounds(session: ReplaySession) {
  return {
    start: session.available_start || session.start,
    end: session.available_end || session.end,
  };
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

function replayTargetMaxPoints() {
  if (typeof window === "undefined") {
    return MAX_REPLAY_POINTS;
  }
  const width = Number(window.innerWidth || 0);
  if (!Number.isFinite(width) || width <= 0) {
    return MAX_REPLAY_POINTS;
  }
  return Math.max(
    MIN_REPLAY_POINTS,
    Math.min(MAX_REPLAY_POINTS, Math.ceil(width * REPLAY_POINTS_PER_PIXEL)),
  );
}

function nextReplayRequestId(
  ref: { current: number },
  prefix: string,
) {
  ref.current += 1;
  return `${prefix}-${Date.now()}-${ref.current}`;
}
