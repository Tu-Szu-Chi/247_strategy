import { expect, test, type Page } from "@playwright/test";

const SESSION_START = "2026-04-27T08:45:00";
const SESSION_END = "2026-04-27T13:45:00";
const SESSION_ID = "replay-e2e-session";

test("replay page boots on the requested window and requests viewport-sized bundles", async ({ page }) => {
  const bundleRequests: URL[] = [];
  const sessionCreateRequests: URL[] = [];
  await mockReplayApi(page, bundleRequests, sessionCreateRequests);
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.goto("/research/replay");

  await expect(page.getByText(SESSION_ID)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pressure Index + Regime" })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();

  await expect.poll(() => bundleRequests.length).toBeGreaterThan(0);
  const firstBundle = bundleRequests[0];
  expect(firstBundle.pathname).toContain(`/api/option-power/replay/sessions/${SESSION_ID}/bundle`);
  expect(firstBundle.searchParams.get("start")).toBe(SESSION_START);
  expect(firstBundle.searchParams.get("end")).toBe(SESSION_END);
  expect(firstBundle.searchParams.get("interval")).toBe("5m");
  expect(firstBundle.searchParams.get("max_points")).toBe("2400");
  expect(firstBundle.searchParams.get("request_id")).toMatch(/^bundle-/);

  await page.waitForTimeout(1000);
  expect(bundleRequests).toHaveLength(1);
  expect(sessionCreateRequests).toHaveLength(0);

  const priceChart = page.getByTestId("timeline-chart-price");
  await priceChart.hover();
  await page.mouse.wheel(900, 0);
  await page.waitForTimeout(350);

  expect(sessionCreateRequests).toHaveLength(0);
  for (const request of bundleRequests) {
    const requestedStart = request.searchParams.get("start");
    expect(request.searchParams.get("max_points")).toBeTruthy();
    expect(request.searchParams.get("request_id")).toBeTruthy();
    if (request.pathname.endsWith("/bundle") && requestedStart) {
      expect(new Date(requestedStart).getTime()).toBeGreaterThanOrEqual(new Date(SESSION_START).getTime());
    }
  }
});

async function mockReplayApi(page: Page, bundleRequests: URL[], sessionCreateRequests: URL[]) {
  await page.route("**/api/option-power/replay/default", async (route) => {
    await route.fulfill({ json: replaySession() });
  });
  await page.route("**/api/option-power/replay/sessions?**", async (route) => {
    sessionCreateRequests.push(new URL(route.request().url()));
    await route.fulfill({ json: replaySession() });
  });
  await page.route("**/api/option-power/replay/sessions/*/events", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
      body: [
        "event: progress",
        `data: ${JSON.stringify(progressPayload())}`,
        "",
        "",
      ].join("\n"),
    });
  });
  await page.route("**/api/option-power/replay/sessions/*/progress", async (route) => {
    await route.fulfill({ json: progressPayload() });
  });
  await page.route("**/api/option-power/replay/sessions/*/bundle?**", async (route) => {
    const url = new URL(route.request().url());
    bundleRequests.push(url);
    const start = url.searchParams.get("start") ?? SESSION_START;
    const end = url.searchParams.get("end") ?? SESSION_END;
    const maxPoints = Number(url.searchParams.get("max_points") ?? "2400");
    await route.fulfill({
      json: replayBundle(start, end, maxPoints, url.searchParams.get("request_id")),
    });
  });
  await page.route("**/api/option-power/replay/sessions/*/bundle-by-bars?**", async (route) => {
    const url = new URL(route.request().url());
    const anchor = url.searchParams.get("anchor") ?? SESSION_START;
    const direction = url.searchParams.get("direction") ?? "next";
    const start = direction === "prev" ? addMinutes(anchor, -50) : anchor;
    const end = direction === "prev" ? anchor : addMinutes(anchor, 50);
    await route.fulfill({
      json: {
        ...replayBundle(start, end, Number(url.searchParams.get("max_points") ?? "2400"), url.searchParams.get("request_id")),
        coverage: {
          anchor,
          direction,
          interval: url.searchParams.get("interval") ?? "5m",
          bar_count: Number(url.searchParams.get("bar_count") ?? "50"),
          first_bar_time: start,
          last_bar_time: end,
          has_prev: new Date(start).getTime() > new Date(SESSION_START).getTime(),
          has_next: new Date(end).getTime() < new Date(SESSION_END).getTime(),
        },
        session: replaySession(),
      },
    });
  });
}

function replaySession() {
  return {
    session_id: SESSION_ID,
    start: SESSION_START,
    end: SESSION_END,
    available_start: SESSION_START,
    available_end: "2026-04-27T17:10:00",
    snapshot_interval_seconds: 60,
    option_root: "TXO",
    underlying_symbol: "MTX",
    selected_option_roots: ["TXO"],
    snapshot_count: 301,
    available_series: ["pressure_index", "raw_pressure", "flow_state", "range_state"],
    bar_count: 301,
    cache_mode: "memory",
    loaded_window_count: 1,
    supports_windowed_loading: true,
    compute_status: "ready",
    computed_until: SESSION_END,
    progress_ratio: 1,
    checkpoint_count: 301,
    target_window_bars: 180,
    compute_error: null,
  };
}

function progressPayload() {
  return {
    status: "ready",
    compute_status: "ready",
    computed_until: SESSION_END,
    progress_ratio: 1,
    checkpoint_count: 301,
  };
}

function replayBundle(start: string, end: string, maxPoints: number, requestId: string | null) {
  const bars = buildBars(start, end);
  const points = bars.map((bar, index) => ({
    time: bar.time,
    value: Math.sin(index / 6) * 35,
  }));
  const statePoints = bars.map((bar, index) => ({
    time: bar.time,
    value: index % 20 < 10 ? 1 : -1,
  }));
  return {
    bars,
    series: {
      pressure_index: points,
      raw_pressure: points.map((point) => ({ ...point, value: point.value * 10 })),
      pressure_index_weighted: points.map((point) => ({ ...point, value: point.value * 0.7 })),
      raw_pressure_weighted: points.map((point) => ({ ...point, value: point.value * 7 })),
      regime_state: statePoints,
      structure_state: statePoints,
      trend_score: points,
      chop_score: points.map((point) => ({ ...point, value: Math.abs(point.value) })),
      reversal_risk: points,
      vwap_distance_bps: points,
      trade_intensity_ratio_30b: points.map((point) => ({ ...point, value: Math.abs(point.value) / 10 })),
      adx_14: points,
      plus_di_14: points,
      minus_di_14: points,
      di_bias_14: statePoints,
      choppiness_14: points,
      compression_score: points,
      expansion_score: points,
      compression_expansion_state: statePoints,
      session_cvd: points,
      cvd_5b_delta: points,
      cvd_15b_delta: points,
      cvd_5b_slope: points,
      cvd_price_alignment: statePoints,
      price_cvd_divergence_15b: statePoints,
      iv_skew: points.map((point) => ({ ...point, value: point.value / 100 })),
      trend_quality_score: points,
      trend_bias_state: statePoints,
      flow_impulse_score: points,
      flow_state: statePoints,
      range_state: statePoints,
    },
    coverage: {
      requested_start: start,
      requested_end: end,
      query_start: start,
      query_end: end,
      computed_start: SESSION_START,
      computed_until: SESSION_END,
      complete: true,
      frame_count: bars.length,
      max_points: maxPoints,
      request_id: requestId,
    },
    status: "ready",
    compute_status: "ready",
    partial: false,
    computed_until: SESSION_END,
    progress_ratio: 1,
    checkpoint_count: 301,
  };
}

function buildBars(start: string, end: string) {
  const bars = [];
  const startTs = new Date(start).getTime();
  const endTs = new Date(end).getTime();
  for (let ts = startTs, index = 0; ts <= endTs; ts += 60_000, index += 1) {
    const close = 20_000 + Math.sin(index / 8) * 20 + index * 0.1;
    bars.push({
      time: localIsoString(new Date(ts)),
      open: close - 2,
      high: close + 5,
      low: close - 5,
      close,
      volume: 100 + (index % 40),
    });
  }
  return bars;
}

function addMinutes(value: string, minutes: number) {
  return localIsoString(new Date(new Date(value).getTime() + minutes * 60_000));
}

function localIsoString(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}
