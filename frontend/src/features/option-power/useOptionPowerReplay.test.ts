import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useOptionPowerReplay } from "./useOptionPowerReplay";
import type { ReplaySession } from "./types";
import {
  createReplaySession,
  getReplayBundle,
  getReplayBundleByBars,
  getReplayDefault,
  getReplayProgress,
} from "./api";

vi.mock("./api", () => ({
  createReplaySession: vi.fn(),
  getReplayBundle: vi.fn(),
  getReplayBundleByBars: vi.fn(),
  getReplayDefault: vi.fn(),
  getReplayProgress: vi.fn(),
}));

const baseSession: ReplaySession = {
  session_id: "replay-base",
  start: "2026-04-22T09:00:00",
  end: "2026-04-22T10:00:00",
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

const extendedSession: ReplaySession = {
  ...baseSession,
  session_id: "replay-extended",
  start: "2026-04-22T08:00:00",
  end: "2026-04-22T10:00:00",
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
    vi.mocked(getReplayBundleByBars).mockResolvedValue({
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
        coverage: {
          anchor: "2026-04-22T10:00:00",
          direction: "next",
          interval: "1m",
          bar_count: 0,
          first_bar_time: null,
          last_bar_time: null,
          has_prev: true,
          has_next: true,
        },
      },
      coverage: {
        anchor: "2026-04-22T10:00:00",
        direction: "next",
        interval: "1m",
        bar_count: 0,
        first_bar_time: null,
        last_bar_time: null,
        has_prev: true,
        has_next: true,
      },
      session: baseSession,
    });
    vi.mocked(getReplayProgress).mockResolvedValue({
      status: "ready",
      compute_status: "ready",
      computed_until: "2026-04-22T10:00:00",
      progress_ratio: 1,
      checkpoint_count: 721,
    });
  });

  it("creates a larger session when the visible range moves outside the current replay bounds", async () => {
    vi.mocked(createReplaySession).mockResolvedValue(extendedSession);
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-base");
    });

    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T08:30:00",
        "2026-04-22T09:15:00",
      );
    });

    expect(createReplaySession).toHaveBeenCalledWith(
      "2026-04-22T08:00:00",
      "2026-04-22T10:00:00",
    );
    expect(getReplayBundleByBars).toHaveBeenLastCalledWith(
      "replay-extended",
      "2026-04-22T09:00:00",
      "prev",
      300,
      "1m",
      ["raw_pressure"],
    );
  });

  it("extends past the session end when right-side whitespace reaches the current boundary", async () => {
    vi.mocked(createReplaySession).mockResolvedValue({
      ...baseSession,
      session_id: "replay-right-extended",
      end: "2026-04-22T13:00:00",
    });
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-base");
    });

    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T09:30:00",
        "2026-04-22T10:00:00",
        { hasRightWhitespace: true },
      );
    });

    expect(createReplaySession).toHaveBeenCalledWith(
      "2026-04-22T09:00:00",
      "2026-04-22T13:00:00",
    );
    expect(getReplayBundleByBars).toHaveBeenLastCalledWith(
      "replay-right-extended",
      "2026-04-22T10:00:00",
      "next",
      300,
      "1m",
      ["raw_pressure"],
    );
  });
});
