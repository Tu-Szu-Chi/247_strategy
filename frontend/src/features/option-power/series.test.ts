import { describe, expect, it } from "vitest";
import { resampleSeries, weightedSeriesName } from "./series";

describe("indicator series resampling", () => {
  it("keeps the latest value in each 1m bucket", () => {
    const points = [
      { time: "2026-04-22T09:00:01", value: 1 },
      { time: "2026-04-22T09:00:20", value: 3 },
      { time: "2026-04-22T09:01:05", value: 8 },
      { time: "2026-04-22T09:01:35", value: 13 },
    ];

    expect(resampleSeries(points, "1m")).toEqual([
      { time: "2026-04-22T09:00:00", value: 3 },
      { time: "2026-04-22T09:01:00", value: 13 },
    ]);
  });

  it("only returns weighted overlay names for pressure series", () => {
    expect(weightedSeriesName("pressure_index")).toBe("pressure_index_weighted");
    expect(weightedSeriesName("raw_pressure")).toBe("raw_pressure_weighted");
    expect(weightedSeriesName("trend_score")).toBeNull();
  });
});
