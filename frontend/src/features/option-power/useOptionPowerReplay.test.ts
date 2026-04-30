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

  it("does not create a larger session when the visible range moves outside replay bounds", async () => {
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

    expect(createReplaySession).not.toHaveBeenCalled();
    expect(getReplayBundleByBars).not.toHaveBeenCalled();
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

  it("does not extend the session when right-side whitespace reaches the current boundary", async () => {
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

    expect(createReplaySession).not.toHaveBeenCalled();
    expect(getReplayBundleByBars).not.toHaveBeenCalled();
  });

  it("prefetches next bars when right-side whitespace appears inside the current session", async () => {
    vi.mocked(getReplayDefault).mockResolvedValue(longSession);
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-long");
    });

    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T11:30:00",
        "2026-04-22T12:00:00",
        { hasRightWhitespace: true },
      );
    });

    expect(createReplaySession).not.toHaveBeenCalled();
    expect(getReplayBundleByBars).toHaveBeenLastCalledWith(
      "replay-long",
      "2026-04-22T12:00:00",
      "next",
      50,
      "1m",
      ["raw_pressure"],
      undefined,
      expect.any(Number),
      expect.stringMatching(/^cursor-/),
    );
  });

  it("prefetches previous bars when left-side whitespace appears inside the current session", async () => {
    vi.mocked(getReplayDefault).mockResolvedValue(wideSession);
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-wide");
    });

    await act(async () => {
      await result.current.loadSession(
        wideSession,
        "1m",
        { start: "2026-04-22T14:00:00", end: "2026-04-22T15:00:00" },
        { updateWindow: false, showLoading: false },
      );
    });

    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T14:00:00",
        "2026-04-22T14:30:00",
        { hasLeftWhitespace: true },
      );
    });

    expect(createReplaySession).not.toHaveBeenCalled();
    expect(getReplayBundleByBars).toHaveBeenLastCalledWith(
      "replay-wide",
      "2026-04-22T14:00:00",
      "prev",
      50,
      "1m",
      ["raw_pressure"],
      undefined,
      expect.any(Number),
      expect.stringMatching(/^cursor-/),
    );
  });

  it("does not request another bundle when the buffered visible range is already loaded", async () => {
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-base");
    });

    const initialBundleCalls = vi.mocked(getReplayBundle).mock.calls.length;
    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T09:20:00",
        "2026-04-22T09:40:00",
      );
    });

    expect(getReplayBundle).toHaveBeenCalledTimes(initialBundleCalls);
    expect(getReplayBundleByBars).not.toHaveBeenCalled();
  });

  it("does not repeatedly request a range whose series are still pending compute", async () => {
    vi.mocked(getReplayBundle).mockResolvedValueOnce({
      bars: [],
      series: {},
      seriesStatus: {
        bars: [],
        series: {},
        status: "partial",
        compute_status: "running",
        partial: true,
        computed_until: "2026-04-22T09:05:00",
        progress_ratio: 0.25,
        checkpoint_count: 1,
      },
    });
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.partial).toBe(true);
    });

    const initialBundleCalls = vi.mocked(getReplayBundle).mock.calls.length;
    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T09:20:00",
        "2026-04-22T09:40:00",
      );
    });

    expect(getReplayBundle).toHaveBeenCalledTimes(initialBundleCalls);
  });

  it("tracks disjoint loaded ranges instead of treating their outer bounds as fully loaded", async () => {
    vi.mocked(getReplayDefault).mockResolvedValue(longSession);
    const { result } = renderHook(() => useOptionPowerReplay(["raw_pressure"], true, "1m"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.session?.session_id).toBe("replay-long");
    });

    await act(async () => {
      await result.current.loadSession(
        longSession,
        "1m",
        { start: "2026-04-22T14:00:00", end: "2026-04-22T15:00:00" },
        { updateWindow: false, showLoading: false },
      );
    });

    const callsAfterSecondRange = vi.mocked(getReplayBundle).mock.calls.length;
    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T14:20:00",
        "2026-04-22T14:30:00",
      );
    });
    expect(getReplayBundle).toHaveBeenCalledTimes(callsAfterSecondRange);

    await act(async () => {
      await result.current.ensureWindowForVisibleRange(
        "2026-04-22T13:00:00",
        "2026-04-22T13:10:00",
      );
    });
    expect(getReplayBundle).toHaveBeenCalledTimes(callsAfterSecondRange + 1);
  });
});
