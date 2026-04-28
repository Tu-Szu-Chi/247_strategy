import type {
  ChartBarPoint,
  IndicatorSeriesMap,
  IndicatorInterval,
  LiveMeta,
  LiveSnapshotLatestResponse,
  ReplaySession,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new ApiError(response.status, message || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function getLiveBundle(seriesNames: string[], includeBars = true) {
  const names = encodeURIComponent(seriesNames.join(","));
  const [meta, bars, series, latest] = await Promise.all([
    fetchJson<LiveMeta>("/api/option-power/live/meta"),
    includeBars
      ? fetchJson<ChartBarPoint[]>("/api/option-power/live/bars")
      : Promise.resolve([] as ChartBarPoint[]),
    fetchJson<IndicatorSeriesMap>(`/api/option-power/live/series?names=${names}`),
    fetchJson<LiveSnapshotLatestResponse>("/api/option-power/live/snapshot/latest"),
  ]);
  return { meta, bars, series, latest };
}

export async function getReplayDefault(): Promise<ReplaySession> {
  return fetchJson<ReplaySession>("/api/option-power/replay/default");
}

export async function createReplaySession(start: string, end: string): Promise<ReplaySession> {
  const search = new URLSearchParams({ start, end });
  return fetchJson<ReplaySession>(`/api/option-power/replay/sessions?${search.toString()}`, {
    method: "POST",
    body: JSON.stringify({ start, end }),
  });
}

export async function getReplayBundle(
  sessionId: string,
  start: string,
  end: string,
  interval: IndicatorInterval,
  seriesNames: string[],
  signal?: AbortSignal,
) {
  const names = encodeURIComponent(seriesNames.join(","));
  const search = new URLSearchParams({
    start,
    end,
    interval,
  });
  const [bars, series] = await Promise.all([
    fetchJson<ChartBarPoint[]>(`/api/option-power/replay/sessions/${sessionId}/bars?${search.toString()}`, { signal }),
    fetchJson<IndicatorSeriesMap>(
      `/api/option-power/replay/sessions/${sessionId}/series?names=${names}&${search.toString()}`,
      { signal },
    ),
  ]);
  return { bars, series };
}
