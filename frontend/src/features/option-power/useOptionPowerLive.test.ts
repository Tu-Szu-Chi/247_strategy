import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLiveBundle, getLiveLatest } from "./api";
import { useOptionPowerLive } from "./useOptionPowerLive";

vi.mock("./api", () => ({
  getLiveBundle: vi.fn(),
  getLiveLatest: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

describe("useOptionPowerLive", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(getLiveBundle).mockResolvedValue({
      meta: {
        mode: "live",
        run_id: "live-1",
        status: "running",
        option_root: "AUTO",
        underlying_symbol: "MTX",
        snapshot_count: 1,
        bar_count: 1,
        start: "2026-04-22T09:00:00",
        end: "2026-04-22T09:00:00",
        selected_option_roots: ["TXX"],
        available_series: ["pressure_index"],
      },
      bars: [{ time: "2026-04-22T09:00:00", open: 1, high: 2, low: 1, close: 2, volume: 10 }],
      series: {
        pressure_index: [{ time: "2026-04-22T09:00:00", value: 10 }],
      },
      latest: {
        updated: true,
        snapshot_time: "2026-04-22T09:00:00",
        snapshot: {
          type: "option_power_snapshot",
          generated_at: "2026-04-22T09:00:00",
          run_id: "live-1",
          session: "day",
          option_root: "AUTO",
          underlying_reference_price: 100,
          raw_pressure: 8,
          pressure_index: 10,
          raw_pressure_weighted: 7,
          pressure_index_weighted: 9,
          regime: null,
          iv_surface: null,
          contract_count: 2,
          status: "running",
        },
        contract_totals: {
          call: { cumulative_power: 5, power_1m_delta: 2 },
          put: { cumulative_power: -3, power_1m_delta: -1 },
        },
        series: {},
        latest_bar: { time: "2026-04-22T09:00:00", open: 1, high: 2, low: 1, close: 2, volume: 10 },
      },
    });
    vi.mocked(getLiveLatest).mockResolvedValue({
      updated: true,
      snapshot_time: "2026-04-22T09:00:10",
      snapshot: {
        type: "option_power_snapshot",
        generated_at: "2026-04-22T09:00:10",
        run_id: "live-1",
        session: "day",
        option_root: "AUTO",
        underlying_reference_price: 101,
        raw_pressure: 11,
        pressure_index: 12,
        raw_pressure_weighted: 10,
        pressure_index_weighted: 11,
        regime: null,
        iv_surface: null,
        contract_count: 2,
        status: "running",
      },
      contract_totals: {
        call: { cumulative_power: 8, power_1m_delta: 3 },
        put: { cumulative_power: -4, power_1m_delta: -2 },
      },
      series: {
        pressure_index: [{ time: "2026-04-22T09:00:10", value: 12 }],
      },
      latest_bar: { time: "2026-04-22T09:00:00", open: 1, high: 3, low: 1, close: 3, volume: 15 },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads metadata once and then polls only compact deltas", async () => {
    const { result } = renderHook(() => useOptionPowerLive(["pressure_index"], true, true));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
    expect(getLiveBundle).toHaveBeenCalledTimes(1);
    expect(getLiveLatest).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(10000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getLiveLatest).toHaveBeenCalledTimes(1);
    expect(getLiveLatest).toHaveBeenCalledWith(["pressure_index"], "2026-04-22T09:00:00", true);
    expect(result.current.meta?.run_id).toBe("live-1");
    expect(result.current.snapshot?.generated_at).toBe("2026-04-22T09:00:10");
    expect(result.current.contractTotals?.call.cumulative_power).toBe(8);
    expect(result.current.bars[result.current.bars.length - 1]?.close).toBe(3);
    expect(
      result.current.series.pressure_index[result.current.series.pressure_index.length - 1]?.value,
    ).toBe(12);
  });
});
