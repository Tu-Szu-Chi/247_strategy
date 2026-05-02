import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useOptionPowerReplay } from "./useOptionPowerReplay";
import type { IndicatorInterval, ReplaySession } from "./types";
import {
  createReplaySession,
  getReplayBundle,
  getReplayDefault,
  getReplayProgress,
} from "./api";

vi.mock("./api", () => ({
  createReplaySession: vi.fn(),
  getReplayBundle: vi.fn(),
  getReplayDefault: vi.fn(),
  getReplayProgress: vi.fn(),
}));

const baseSession: ReplaySession = {
  session_id: "replay-base",
  start: "2026-04-22T09:00:00",
  end: "2026-04-22T10:00:00",
  available_start: "2026-04-22T09:00:00",
  available_end: "2026-04-22T10:00:00",
  snapshot_interval_seconds: 5,
  option_root: "AUTO",
  underlying_symbol: "MTX",
  selected_option_roots: ["TXX"],
  snapshot_count: 721,
  compute_status: "ready",
  computed_until: "2026-04-22T10:00:00",
  progress_ratio: 1,
  checkpoint_count: 721,
};

const longSession: ReplaySession = {
  ...baseSession,
  session_id: "replay-long",
  end: "2026-04-22T12:00:00",
  available_end: "2026-04-22T15:00:00",
};

const wideSession: ReplaySession = {
  ...baseSession,
  session_id: "replay-wide",
  start: "2026-04-22T14:00:00",
  end: "2026-04-22T15:00:00",
  available_start: "2026-04-22T08:00:00",
  available_end: "2026-04-22T15:00:00",
};

describe("useOptionPowerReplay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getReplayDefault).mockResolvedValue(baseSession);
    vi.mocked(getReplayBundle).mockResolvedValue({
      bars: [],
      series: {},
      seriesStatus: {
        bars: [],
        series: {},
        status: "ready",
        compute_status: "ready",
        partial: false,
        computed_until: "2026-04-22T10:00:00",
        progress_ratio: 1,
        checkpoint_count: 721,
      },
    });
    vi.mocked(getReplayProgress).mockResolvedValue({
      status: "ready",
      compute_status: "ready",
      computed_until: "2026-04-22T10:00:00",
      progress_ratio: 1,
      checkpoint_count: 721,
    });
  });

  it("loads the initial replay view exactly from the session start/end window", async () => {
    renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(vi.mocked(getReplayBundle)).toHaveBeenCalled();
    });

    expect(vi.mocked(getReplayBundle)).toHaveBeenNthCalledWith(
      1,
      "replay-base",
      "2026-04-22T09:00:00",
      "2026-04-22T10:00:00",
      "1m",
      ["raw_pressure"],
      expect.any(AbortSignal),
      expect.any(Number),
      expect.stringMatching(/^bundle-/),
    );
  });

  it("replaces replay bars when switching interval within the same session", async () => {
    vi.mocked(getReplayBundle)
      .mockResolvedValueOnce({
        bars: [
          {
            time: "2026-04-22T09:00:00",
            open: 100,
            high: 101,
            low: 99,
            close: 100,
            volume: 10,
          },
        ],
        series: {},
        seriesStatus: {
          bars: [],
          series: {},
          status: "ready",
          compute_status: "ready",
          partial: false,
          computed_until: "2026-04-22T10:00:00",
          progress_ratio: 1,
          checkpoint_count: 721,
        },
      })
      .mockResolvedValueOnce({
        bars: [
          {
            time: "2026-04-22T09:00:00",
            open: 100,
            high: 101,
            low: 99,
            close: 100,
            volume: 10,
          },
          {
            time: "2026-04-22T09:01:00",
            open: 101,
            high: 102,
            low: 100,
            close: 101,
            volume: 11,
          },
        ],
        series: {},
        seriesStatus: {
          bars: [],
          series: {},
          status: "ready",
          compute_status: "ready",
          partial: false,
          computed_until: "2026-04-22T10:00:00",
          progress_ratio: 1,
          checkpoint_count: 721,
        },
      });

    const { result, rerender } = renderHook(
      ({ interval }) => useOptionPowerReplay(["raw_pressure"], true, interval),
      { initialProps: { interval: "5m" as IndicatorInterval } },
    );

    await waitFor(() => {
      expect(result.current.bars).toHaveLength(1);
    });

    rerender({ interval: "1m" as IndicatorInterval });

    await waitFor(() => {
      expect(result.current.bars).toHaveLength(2);
    });

    expect(result.current.bars[1]?.time).toBe("2026-04-22T09:01:00");
  });

});
