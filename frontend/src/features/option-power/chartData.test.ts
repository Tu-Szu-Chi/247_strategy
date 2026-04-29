import { describe, expect, it } from "vitest";
import { normalizeChartData } from "./chartData";

describe("chart data normalization", () => {
  it("normalizes bars, moving averages, and sorted panel payloads for the chart worker", () => {
    const base = Date.UTC(2026, 3, 16, 1, 0, 0);
    const bars = Array.from({ length: 65 }, (_, index) => ({
      time: new Date(base + index * 60_000).toISOString(),
      open: 100 + index,
      high: 101 + index,
      low: 99 + index,
      close: 100 + index,
      volume: 1000 + index,
    }));

    const normalized = normalizeChartData({
      bars,
      panelData: {
        pressure: [
          {
            id: "pressure_index",
            points: [
              { time: bars[0].time, value: 1 },
              { time: bars[1].time, value: 2 },
            ],
          },
          {
            id: "regime_state",
            kind: "histogram",
            points: [
              { time: bars[0].time, value: -1 },
              { time: bars[1].time, value: 1 },
            ],
          },
        ],
      },
    });

    expect(normalized.bars).toHaveLength(65);
    expect(normalized.volume).toHaveLength(65);
    expect(normalized.ma10).toHaveLength(56);
    expect(normalized.ma30).toHaveLength(36);
    expect(normalized.ma60).toHaveLength(6);
    expect(normalized.panels.pressure.pressure_index).toHaveLength(2);
    expect(normalized.panels.pressure.regime_state[0]).toMatchObject({
      value: -1,
      color: "rgba(168, 85, 247, 0.28)",
    });
  });
});
