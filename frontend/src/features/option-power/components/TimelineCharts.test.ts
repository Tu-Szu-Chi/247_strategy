import { describe, expect, it } from "vitest";
import type { CandlestickData, Logical, LogicalRange, Time } from "lightweight-charts";
import { resolveRequestedVisibleRange } from "./TimelineCharts";

describe("TimelineCharts visible-range loading", () => {
  it("extends the requested range backward when the viewport shows left-side whitespace", () => {
    const bars: CandlestickData[] = [
      { time: 1714554000 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554060 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554120 as Time, open: 1, high: 2, low: 0, close: 1.5 },
    ];
    const logicalRange: LogicalRange = { from: -2.2 as Logical, to: 1.4 as Logical };

    expect(
      resolveRequestedVisibleRange(bars, logicalRange, 1714554000 as Time, 1714554060 as Time),
    ).toEqual({
      start: "2024-05-01T16:57:00",
      end: "2024-05-01T17:01:00",
      hasLeftWhitespace: true,
      hasRightWhitespace: false,
    });
  });

  it("extends the requested range forward when the viewport shows right-side whitespace", () => {
    const bars: CandlestickData[] = [
      { time: 1714554000 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554060 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554120 as Time, open: 1, high: 2, low: 0, close: 1.5 },
    ];
    const logicalRange: LogicalRange = { from: 0.2 as Logical, to: 4.1 as Logical };

    expect(
      resolveRequestedVisibleRange(bars, logicalRange, 1714554000 as Time, 1714554120 as Time),
    ).toEqual({
      start: "2024-05-01T17:00:00",
      end: "2024-05-01T17:05:00",
      hasLeftWhitespace: false,
      hasRightWhitespace: true,
    });
  });

  it("resolves whitespace range from the logical range when no visible data range is available", () => {
    const bars: CandlestickData[] = [
      { time: 1714554000 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554060 as Time, open: 1, high: 2, low: 0, close: 1.5 },
      { time: 1714554120 as Time, open: 1, high: 2, low: 0, close: 1.5 },
    ];
    const logicalRange: LogicalRange = { from: -5.4 as Logical, to: -1.2 as Logical };

    expect(resolveRequestedVisibleRange(bars, logicalRange)).toEqual({
      start: "2024-05-01T16:54:00",
      end: "2024-05-01T16:59:00",
      hasLeftWhitespace: true,
      hasRightWhitespace: false,
    });
  });
});
