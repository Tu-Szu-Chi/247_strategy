const modeLabel = document.getElementById("mode-label");
const sessionIdLabel = document.getElementById("session-id");
const rootsLabel = document.getElementById("roots-label");
const rangeLabel = document.getElementById("range-label");
const cursorTime = document.getElementById("cursor-time");
const replayStartInput = document.getElementById("replay-start");
const replayEndInput = document.getElementById("replay-end");
const replayLoadButton = document.getElementById("replay-load");
const primarySeriesSelect = document.getElementById("primary-series-select");
const secondarySeriesSelect = document.getElementById("secondary-series-select");
const expirySelect = document.getElementById("expiry-select");
const chart = document.getElementById("chart");
const rawPressure = document.getElementById("raw-pressure");
const pressureIndex = document.getElementById("pressure-index");
const rawPressure1m = document.getElementById("raw-pressure-1m");
const pressureIndex1m = document.getElementById("pressure-index-1m");
const pressureIndex5m = document.getElementById("pressure-index-5m");
const pressureAbs = document.getElementById("pressure-abs");
const pressureAbs1m = document.getElementById("pressure-abs-1m");
const pressureAbs5m = document.getElementById("pressure-abs-5m");
const callCumulativePower = document.getElementById("call-cumulative-power");
const putCumulativePower = document.getElementById("put-cumulative-power");
const callPower1m = document.getElementById("call-power-1m");
const putPower1m = document.getElementById("put-power-1m");
const priceChartContainer = document.getElementById("price-chart");
const primaryIndicatorChartContainer = document.getElementById("primary-indicator-chart");
const secondaryIndicatorChartContainer = document.getElementById("secondary-indicator-chart");
const primaryIndicatorTitle = document.getElementById("primary-indicator-title");
const secondaryIndicatorTitle = document.getElementById("secondary-indicator-title");
const displayDateTimeFormatter = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const displayTickFormatter = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

let currentMode = "unknown";
let replaySession = null;
let liveMeta = null;
let currentSnapshot = null;
let selectedExpiry = "";
let priceChart = null;
let primaryIndicatorChart = null;
let secondaryIndicatorChart = null;
let candleSeries = null;
let ma10Series = null;
let ma30Series = null;
let ma60Series = null;
let primaryLineSeries = null;
let secondaryLineSeries = null;
let livePollingHandle = null;
let chartsEnabled = true;
let liveBundlePollingInFlight = false;
let syncingVisibleRange = false;
let timelineHasFitContent = false;
let snapshotRowMap = new Map();
let snapshotEmptyState = null;
let crosshairSnapshotTimeout = null;
let pendingCrosshairSnapshotTs = "";
let lastRequestedSnapshotTs = "";
let lastRenderedSnapshotTs = "";
let snapshotRequestSequence = 0;
let activeSnapshotRequestSequence = 0;

const CROSSHAIR_SNAPSHOT_DEBOUNCE_MS = 120;
const REALTIME_SCROLL_EPSILON = 0.5;

function initCharts() {
  if (typeof LightweightCharts === "undefined") {
    chartsEnabled = false;
    priceChartContainer.innerHTML = `<div class="empty">Chart library not loaded. Live data will still refresh.</div>`;
    primaryIndicatorChartContainer.innerHTML = `<div class="empty">Chart library not loaded. Live data will still refresh.</div>`;
    secondaryIndicatorChartContainer.innerHTML = `<div class="empty">Chart library not loaded. Live data will still refresh.</div>`;
    return;
  }
  priceChart = LightweightCharts.createChart(priceChartContainer, chartOptions(440));
  candleSeries = priceChart.addCandlestickSeries({
    upColor: "#ff6a5a",
    downColor: "#41b883",
    borderVisible: false,
    wickUpColor: "#ff6a5a",
    wickDownColor: "#41b883",
  });
  ma10Series = priceChart.addLineSeries({
    color: "#ffd166",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    priceLineVisible: false,
    lastValueVisible: false,
  });
  ma30Series = priceChart.addLineSeries({
    color: "#7dd3fc",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    priceLineVisible: false,
    lastValueVisible: false,
  });
  ma60Series = priceChart.addLineSeries({
    color: "#c084fc",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    priceLineVisible: false,
    lastValueVisible: false,
  });

  primaryIndicatorChart = LightweightCharts.createChart(primaryIndicatorChartContainer, chartOptions(180));
  primaryLineSeries = primaryIndicatorChart.addLineSeries({
    color: "#ffd166",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    priceLineVisible: false,
  });
  secondaryIndicatorChart = LightweightCharts.createChart(secondaryIndicatorChartContainer, chartOptions(180));
  secondaryLineSeries = secondaryIndicatorChart.addLineSeries({
    color: "#7dd3fc",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    priceLineVisible: false,
  });

  const allCharts = [priceChart, primaryIndicatorChart, secondaryIndicatorChart];
  allCharts.forEach((sourceChart) => {
    sourceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (!range || syncingVisibleRange) {
        return;
      }
      syncingVisibleRange = true;
      allCharts.forEach((targetChart) => {
        if (targetChart !== sourceChart) {
          targetChart.timeScale().setVisibleRange(range);
        }
      });
      syncingVisibleRange = false;
    });
  });

  const syncCrosshair = async (param) => {
    if (!param || !param.time) {
      return;
    }
    const isoTime = toIsoTime(param.time);
    cursorTime.textContent = formatDateTime(isoTime);
    scheduleCrosshairSnapshotLoad(isoTime);
  };
  allCharts.forEach((targetChart) => targetChart.subscribeCrosshairMove(syncCrosshair));
}

function chartOptions(height) {
  return {
    height,
    layout: {
      background: { color: "transparent" },
      textColor: "#eef4ff",
      fontFamily: "IBM Plex Sans, Noto Sans TC, sans-serif",
    },
    localization: {
      timeFormatter: (time) => displayDateTimeFormatter.format(new Date(Number(time) * 1000)),
    },
    grid: {
      vertLines: { color: "rgba(255,255,255,0.05)" },
      horzLines: { color: "rgba(255,255,255,0.06)" },
    },
    crosshair: {
      vertLine: { color: "rgba(255,209,102,0.55)", width: 1 },
      horzLine: { color: "rgba(255,209,102,0.35)", width: 1 },
    },
    rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
    handleScroll: {
      mouseWheel: false,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    handleScale: {
      mouseWheel: false,
      pinch: false,
      axisPressedMouseMove: true,
      axisDoubleClickReset: false,
    },
    timeScale: {
      borderColor: "rgba(255,255,255,0.08)",
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time) => displayTickFormatter.format(new Date(Number(time) * 1000)),
    },
  };
}

async function init() {
  initCharts();
  try {
    await loadLiveBundle(true);
    startLivePolling();
    return;
  } catch (error) {
    // Fall back to replay if live mode is not available yet.
  }
  const replayLoaded = await tryLoadDefaultReplay();
  if (!replayLoaded) {
    modeLabel.textContent = "live-error";
  }
}

async function tryLoadDefaultReplay() {
  try {
    const response = await fetch("/api/option-power/replay/default", { cache: "no-store" });
    if (!response.ok) {
      return false;
    }
    replaySession = await response.json();
    currentMode = "replay";
    modeLabel.textContent = "replay";
    hydrateReplayInputs();
    await loadReplayBundle();
    return true;
  } catch (error) {
    return false;
  }
}

async function createReplay() {
  const response = await fetch("/api/option-power/replay/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start: fromDatetimeLocal(replayStartInput.value),
      end: fromDatetimeLocal(replayEndInput.value),
    }),
  });
  if (!response.ok) {
    throw new Error("Unable to create replay.");
  }
  replaySession = await response.json();
  currentMode = "replay";
  modeLabel.textContent = "replay";
  hydrateReplayInputs();
  await loadReplayBundle();
}

async function loadReplayBundle() {
  if (!replaySession) {
    return;
  }
  sessionIdLabel.textContent = replaySession.session_id;
  rootsLabel.textContent = replaySession.selected_option_roots.join(" + ");
  rangeLabel.textContent = `${formatDateTime(replaySession.start)} -> ${formatDateTime(replaySession.end)}`;

  const requestedSeries = selectedSeriesNames();
  const [barsResponse, seriesResponse, snapshotResponse] = await Promise.all([
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/bars`, { cache: "no-store" }),
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/series?names=${encodeURIComponent(requestedSeries.join(","))}`, { cache: "no-store" }),
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/snapshot-at?ts=${encodeURIComponent(replaySession.start)}`, { cache: "no-store" }),
  ]);

  const bars = await barsResponse.json();
  const indicatorSeries = await seriesResponse.json();
  const snapshotPayload = await snapshotResponse.json();

  renderTimeline(
    bars,
    indicatorSeries[primarySeriesSelect.value] || [],
    indicatorSeries[secondarySeriesSelect.value] || [],
  );
  currentSnapshot = snapshotPayload.snapshot;
  lastRequestedSnapshotTs = replaySession.start;
  lastRenderedSnapshotTs = replaySession.start;
  cursorTime.textContent = formatDateTime(snapshotPayload.simulated_at);
  renderSnapshot();
}

async function loadReplaySnapshotAt(ts) {
  const requestSequence = beginSnapshotRequest(ts);
  if (requestSequence === null) {
    return;
  }
  const response = await fetch(
    `/api/option-power/replay/sessions/${replaySession.session_id}/snapshot-at?ts=${encodeURIComponent(ts)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  if (!shouldApplySnapshotResponse(requestSequence, ts)) {
    return;
  }
  currentSnapshot = payload.snapshot;
  lastRenderedSnapshotTs = ts;
  renderSnapshot();
}

async function loadLiveBundle(strict = false) {
  const requestedSeries = selectedSeriesNames();
  const [metaResponse, barsResponse, seriesResponse, snapshotResponse] = await Promise.all([
    fetch("/api/option-power/live/meta", { cache: "no-store" }),
    fetch("/api/option-power/live/bars", { cache: "no-store" }),
    fetch(`/api/option-power/live/series?names=${encodeURIComponent(requestedSeries.join(","))}`, { cache: "no-store" }),
    fetch("/api/option-power/live/snapshot/latest", { cache: "no-store" }),
  ]);
  if (!metaResponse.ok) {
    throw new Error("Live mode is not available.");
  }
  liveMeta = await metaResponse.json();
  currentMode = "live";
  modeLabel.textContent = "live";
  sessionIdLabel.textContent = liveMeta.run_id || "-";
  rootsLabel.textContent = (liveMeta.selected_option_roots || []).join(" + ");
  rangeLabel.textContent = liveMeta.start && liveMeta.end
    ? `${formatDateTime(liveMeta.start)} -> ${formatDateTime(liveMeta.end)}`
    : "live stream";

  try {
    const snapshotPayload = await snapshotResponse.json();
    currentSnapshot = snapshotPayload.snapshot;
    if (currentSnapshot && currentSnapshot.generated_at) {
      lastRequestedSnapshotTs = currentSnapshot.generated_at;
      lastRenderedSnapshotTs = currentSnapshot.generated_at;
      cursorTime.textContent = formatDateTime(currentSnapshot.generated_at);
    }
    renderSnapshot();
  } catch (error) {
    if (strict) {
      throw error;
    }
    modeLabel.textContent = "live-partial";
  }

  try {
    const bars = await barsResponse.json();
    const indicatorSeries = await seriesResponse.json();
    renderTimeline(
      bars,
      indicatorSeries[primarySeriesSelect.value] || [],
      indicatorSeries[secondarySeriesSelect.value] || [],
    );
  } catch (error) {
    modeLabel.textContent = "live-partial";
  }
}

function startLivePolling() {
  stopLivePolling();
  livePollingHandle = window.setInterval(async () => {
    try {
      await loadLiveBundleLatest();
    } catch (error) {
      modeLabel.textContent = "live-error";
    }
  }, 5000);
}

function stopLivePolling() {
  if (livePollingHandle !== null) {
    window.clearInterval(livePollingHandle);
    livePollingHandle = null;
  }
}

async function loadLiveBundleLatest() {
  if (liveBundlePollingInFlight) {
    return;
  }
  liveBundlePollingInFlight = true;
  try {
    await loadLiveBundle();
  } finally {
    liveBundlePollingInFlight = false;
  }
}

async function loadLiveSnapshotAt(ts) {
  const requestSequence = beginSnapshotRequest(ts);
  if (requestSequence === null) {
    return;
  }
  const response = await fetch(`/api/option-power/live/snapshot-at?ts=${encodeURIComponent(ts)}`, { cache: "no-store" });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  if (!shouldApplySnapshotResponse(requestSequence, ts)) {
    return;
  }
  currentSnapshot = payload.snapshot;
  lastRenderedSnapshotTs = ts;
  renderSnapshot();
}

function scheduleCrosshairSnapshotLoad(ts) {
  if (!ts || ts === pendingCrosshairSnapshotTs || ts === lastRequestedSnapshotTs || ts === lastRenderedSnapshotTs) {
    return;
  }
  pendingCrosshairSnapshotTs = ts;
  if (crosshairSnapshotTimeout !== null) {
    window.clearTimeout(crosshairSnapshotTimeout);
  }
  crosshairSnapshotTimeout = window.setTimeout(async () => {
    crosshairSnapshotTimeout = null;
    const targetTs = pendingCrosshairSnapshotTs;
    pendingCrosshairSnapshotTs = "";
    if (!targetTs) {
      return;
    }
    if (currentMode === "replay" && replaySession) {
      await loadReplaySnapshotAt(targetTs);
    } else if (currentMode === "live") {
      await loadLiveSnapshotAt(targetTs);
    }
  }, CROSSHAIR_SNAPSHOT_DEBOUNCE_MS);
}

function clearScheduledCrosshairSnapshotLoad() {
  pendingCrosshairSnapshotTs = "";
  if (crosshairSnapshotTimeout !== null) {
    window.clearTimeout(crosshairSnapshotTimeout);
    crosshairSnapshotTimeout = null;
  }
}

function beginSnapshotRequest(ts) {
  if (!ts || ts === lastRequestedSnapshotTs || ts === lastRenderedSnapshotTs) {
    return null;
  }
  lastRequestedSnapshotTs = ts;
  snapshotRequestSequence += 1;
  activeSnapshotRequestSequence = snapshotRequestSequence;
  return activeSnapshotRequestSequence;
}

function shouldApplySnapshotResponse(requestSequence, ts) {
  return requestSequence === activeSnapshotRequestSequence && ts === lastRequestedSnapshotTs;
}

function renderTimeline(bars, primaryLineData, secondaryLineData) {
  if (
    !chartsEnabled ||
    !priceChart ||
    !primaryIndicatorChart ||
    !secondaryIndicatorChart ||
    !candleSeries ||
    !ma10Series ||
    !ma30Series ||
    !ma60Series ||
    !primaryLineSeries ||
    !secondaryLineSeries
  ) {
    return;
  }
  const shouldFollowPrice = currentMode === "live" && isNearRealtime(priceChart);
  const shouldFollowPrimary = currentMode === "live" && isNearRealtime(primaryIndicatorChart);
  const shouldFollowSecondary = currentMode === "live" && isNearRealtime(secondaryIndicatorChart);
  const priceVisibleRange = priceChart.timeScale().getVisibleRange();
  const primaryVisibleRange = primaryIndicatorChart.timeScale().getVisibleRange();
  const secondaryVisibleRange = secondaryIndicatorChart.timeScale().getVisibleRange();
  const normalizedBars = (bars || []).map(normalizeBar).filter(Boolean);
  const ma10Data = buildMovingAverageSeries(normalizedBars, 10);
  const ma30Data = buildMovingAverageSeries(normalizedBars, 30);
  const ma60Data = buildMovingAverageSeries(normalizedBars, 60);
  const normalizedPrimaryLineData = (primaryLineData || []).map(normalizeLinePoint).filter(Boolean);
  const normalizedSecondaryLineData = (secondaryLineData || []).map(normalizeLinePoint).filter(Boolean);
  candleSeries.setData(normalizedBars);
  ma10Series.setData(ma10Data);
  ma30Series.setData(ma30Data);
  ma60Series.setData(ma60Data);
  primaryLineSeries.setData(normalizedPrimaryLineData);
  secondaryLineSeries.setData(normalizedSecondaryLineData);
  primaryIndicatorTitle.textContent = prettySeriesName(primarySeriesSelect.value);
  secondaryIndicatorTitle.textContent = prettySeriesName(secondarySeriesSelect.value);
  if (!timelineHasFitContent) {
    priceChart.timeScale().fitContent();
    primaryIndicatorChart.timeScale().fitContent();
    secondaryIndicatorChart.timeScale().fitContent();
    timelineHasFitContent = true;
    return;
  }
  if (shouldFollowPrice) {
    priceChart.timeScale().scrollToRealTime();
  } else if (priceVisibleRange) {
    priceChart.timeScale().setVisibleRange(priceVisibleRange);
  }
  if (shouldFollowPrimary) {
    primaryIndicatorChart.timeScale().scrollToRealTime();
  } else if (primaryVisibleRange) {
    primaryIndicatorChart.timeScale().setVisibleRange(primaryVisibleRange);
  }
  if (shouldFollowSecondary) {
    secondaryIndicatorChart.timeScale().scrollToRealTime();
  } else if (secondaryVisibleRange) {
    secondaryIndicatorChart.timeScale().setVisibleRange(secondaryVisibleRange);
  }
}

function isNearRealtime(targetChart) {
  if (!targetChart) {
    return false;
  }
  const timeScale = targetChart.timeScale();
  if (!timeScale || typeof timeScale.scrollPosition !== "function") {
    return false;
  }
  return Math.abs(Number(timeScale.scrollPosition()) || 0) <= REALTIME_SCROLL_EPSILON;
}

function renderSnapshot() {
  if (!currentSnapshot) {
    return;
  }
  renderPressureValue(rawPressure, currentSnapshot.raw_pressure);
  renderPressureValue(pressureIndex, currentSnapshot.pressure_index);
  renderPressureValue(rawPressure1m, currentSnapshot.raw_pressure_1m);
  renderPressureValue(pressureIndex1m, currentSnapshot.pressure_index_1m);
  renderPressureValue(pressureIndex5m, currentSnapshot.pressure_index_5m);
  renderPressureValue(pressureAbs, currentSnapshot.pressure_abs, { showSign: false, directional: false });
  renderPressureValue(pressureAbs1m, currentSnapshot.pressure_abs_1m, { showSign: false, directional: false });
  renderPressureValue(pressureAbs5m, currentSnapshot.pressure_abs_5m, { showSign: false, directional: false });

  const expiries = currentSnapshot.expiries || [];
  syncExpiryOptions(expiries);
  const currentExpiry = expiries.find((item) => item.contract_month === selectedExpiry) || expiries[0];
  if (!currentExpiry) {
    renderExpiryAggregateCards([]);
    renderEmptySnapshot();
    return;
  }

  selectedExpiry = currentExpiry.contract_month;
  const contracts = currentExpiry.contracts || [];
  renderExpiryAggregateCards(contracts);
  const grouped = groupByStrike(contracts);
  const maxAbsPower = Math.max(1, ...contracts.map((item) => Math.abs(item.cumulative_power || 0)));
  renderSnapshotRows(grouped, maxAbsPower);
}

function normalizeBar(item) {
  if (!item || item.time === null || item.time === undefined) {
    return null;
  }
  const time = toUnixSeconds(item.time);
  const open = Number(item.open);
  const high = Number(item.high);
  const low = Number(item.low);
  const close = Number(item.close);
  if ([time, open, high, low, close].some((value) => Number.isNaN(value))) {
    return null;
  }
  return { time, open, high, low, close };
}

function buildMovingAverageSeries(bars, period) {
  const points = [];
  let rollingSum = 0;
  for (let idx = 0; idx < bars.length; idx += 1) {
    rollingSum += Number(bars[idx].close || 0);
    if (idx >= period) {
      rollingSum -= Number(bars[idx - period].close || 0);
    }
    if (idx < period - 1) {
      continue;
    }
    points.push({
      time: bars[idx].time,
      value: Number((rollingSum / period).toFixed(2)),
    });
  }
  return points;
}

function normalizeLinePoint(item) {
  if (!item || item.time === null || item.time === undefined || item.value === null || item.value === undefined) {
    return null;
  }
  const time = toUnixSeconds(item.time);
  const value = Number(item.value);
  if (Number.isNaN(time) || Number.isNaN(value)) {
    return null;
  }
  return { time, value };
}

function renderEmptySnapshot() {
  if (!snapshotEmptyState) {
    snapshotEmptyState = document.createElement("div");
    snapshotEmptyState.className = "empty";
    snapshotEmptyState.textContent = "該時間點沒有 option snapshot。";
  }
  chart.replaceChildren(snapshotEmptyState);
  snapshotRowMap = new Map();
}

function renderSnapshotRows(grouped, maxAbsPower) {
  if (snapshotEmptyState && chart.contains(snapshotEmptyState)) {
    chart.removeChild(snapshotEmptyState);
  }

  const nextRowMap = new Map();
  grouped.forEach((entry) => {
    const key = String(entry.strike);
    let row = snapshotRowMap.get(key);
    if (!row) {
      row = createSnapshotRow(entry.strike);
    }
    updateSnapshotRow(row, entry, maxAbsPower);
    chart.appendChild(row);
    nextRowMap.set(key, row);
  });

  snapshotRowMap.forEach((row, key) => {
    if (!nextRowMap.has(key)) {
      row.remove();
    }
  });
  snapshotRowMap = nextRowMap;
}

function createSnapshotRow(strike) {
  const row = document.createElement("div");
  row.className = "row";

  const strikeLabel = document.createElement("div");
  strikeLabel.className = "strike-label";
  strikeLabel.textContent = String(strike);
  row.appendChild(strikeLabel);

  row.appendChild(createSnapshotCell("C"));
  row.appendChild(createSnapshotCell("P"));
  return row;
}

function createSnapshotCell(label) {
  const cell = document.createElement("div");
  cell.className = "cell";

  const head = document.createElement("div");
  head.className = "cell-head";

  const labelNode = document.createElement("span");
  labelNode.textContent = label;

  const deltaValue = document.createElement("strong");
  deltaValue.className = "delta";
  deltaValue.textContent = "-";

  head.append(labelNode, deltaValue);

  const barWrap = document.createElement("div");
  barWrap.className = "bar-wrap";

  const midline = document.createElement("div");
  midline.className = "midline";

  const midPrice = document.createElement("div");
  midPrice.className = "mid-price";
  midPrice.textContent = "-";

  const bar = document.createElement("div");
  bar.className = "bar hidden-bar";

  const barValue = document.createElement("div");
  barValue.className = "bar-value";
  barValue.textContent = "-";

  barWrap.append(midline, midPrice, bar, barValue);
  cell.append(head, barWrap);
  return cell;
}

function updateSnapshotRow(row, entry, maxAbsPower) {
  row.firstChild.textContent = String(entry.strike);
  updateSnapshotCell(row.children[1], entry.call, maxAbsPower);
  updateSnapshotCell(row.children[2], entry.put, maxAbsPower);
}

function updateSnapshotCell(cell, contract, maxAbsPower) {
  const deltaValue = cell.querySelector(".delta");
  const midPrice = cell.querySelector(".mid-price");
  const bar = cell.querySelector(".bar");
  const barValue = cell.querySelector(".bar-value");

  if (!contract) {
    deltaValue.className = "delta";
    deltaValue.textContent = "-";
    midPrice.textContent = "-";
    bar.className = "bar hidden-bar";
    bar.style.width = "0%";
    bar.style.left = "";
    bar.style.right = "";
    barValue.textContent = "-";
    return;
  }

  const widthPercent = Math.min(100, (Math.abs(contract.cumulative_power || 0) / maxAbsPower) * 50);
  const isBull = isBullishDirection(contract);
  const deltaClass = deltaDirectionClass(contract);

  deltaValue.className = deltaClass ? `delta ${deltaClass}` : "delta";
  deltaValue.textContent = formatSigned(contract.power_1m_delta);
  midPrice.textContent = formatPrice(contract.last_price);

  bar.className = `bar ${isBull ? "bull" : "bear"}`;
  bar.style.width = `${widthPercent}%`;
  if (isBull) {
    bar.style.left = "50%";
    bar.style.right = "";
  } else {
    bar.style.right = "50%";
    bar.style.left = "";
  }

  barValue.textContent = formatSigned(contract.cumulative_power);
}

function isBullishDirection(contract) {
  const power = Number(contract.cumulative_power || 0);
  return contract.call_put === "put" ? power <= 0 : power >= 0;
}

function deltaDirectionClass(contract) {
  const delta = Number(contract.power_1m_delta || 0);
  if (delta === 0) return "";
  if (contract.call_put === "put") {
    return delta < 0 ? "positive" : "negative";
  }
  return delta > 0 ? "positive" : "negative";
}

function groupByStrike(contracts) {
  const grouped = new Map();
  contracts.forEach((contract) => {
    const key = String(contract.strike_price);
    const current = grouped.get(key) || { strike: contract.strike_price, call: null, put: null };
    if (contract.call_put === "call") current.call = contract;
    else if (contract.call_put === "put") current.put = contract;
    grouped.set(key, current);
  });
  return Array.from(grouped.values()).sort((a, b) => a.strike - b.strike);
}

function syncExpiryOptions(expiries) {
  const values = expiries.map((item) => item.contract_month);
  if (!values.includes(selectedExpiry)) {
    selectedExpiry = values[0] || "";
  }
  expirySelect.innerHTML = "";
  expiries.forEach((expiry) => {
    const option = document.createElement("option");
    option.value = expiry.contract_month;
    option.textContent = expiry.label;
    option.selected = expiry.contract_month === selectedExpiry;
    expirySelect.appendChild(option);
  });
}

function renderPressureValue(element, value, options = {}) {
  const { showSign = true, directional = true } = options;
  const num = Number(value || 0);
  element.textContent = showSign ? formatSigned(num) : formatUnsigned(num);
  element.className = directional ? pressureClass(num) : "pressure-neutral";
}

function renderExpiryAggregateCards(contracts) {
  const totals = summarizeContractsBySide(contracts || []);
  renderPressureValue(callCumulativePower, totals.call.cumulative_power);
  renderPressureValue(putCumulativePower, totals.put.cumulative_power);
  renderPressureValue(callPower1m, totals.call.power_1m_delta);
  renderPressureValue(putPower1m, totals.put.power_1m_delta);
}

function pressureClass(value) {
  if (value > 0) return "pressure-positive";
  if (value < 0) return "pressure-negative";
  return "";
}

function formatSigned(value) {
  const num = Number(value || 0);
  return `${num > 0 ? "+" : ""}${num.toFixed(0)}`;
}

function formatUnsigned(value) {
  const num = Number(value || 0);
  return num.toFixed(0);
}

function formatPrice(value) {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return num >= 100 ? num.toFixed(0) : num.toFixed(1);
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return displayDateTimeFormatter.format(date).replace(/\//g, "-");
}

function toUnixSeconds(value) {
  return Math.floor(new Date(value).getTime() / 1000);
}

function toIsoTime(unixSeconds) {
  return localIsoString(new Date(unixSeconds * 1000));
}

function toDatetimeLocal(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function fromDatetimeLocal(value) {
  if (!value) return "";
  return `${value}:00`;
}

function localIsoString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}

function selectedSeriesNames() {
  return Array.from(new Set([primarySeriesSelect.value, secondarySeriesSelect.value]));
}

function prettySeriesName(name) {
  return String(name || "")
    .split("_")
    .map((part) => part.toUpperCase())
    .join(" ");
}

function summarizeContractsBySide(contracts) {
  const totals = {
    call: { cumulative_power: 0, power_1m_delta: 0 },
    put: { cumulative_power: 0, power_1m_delta: 0 },
  };
  contracts.forEach((contract) => {
    const side = contract.call_put === "put" ? "put" : "call";
    totals[side].cumulative_power += Number(contract.cumulative_power || 0);
    totals[side].power_1m_delta += Number(contract.power_1m_delta || 0);
  });
  return totals;
}

function hydrateReplayInputs() {
  replayStartInput.value = toDatetimeLocal(replaySession.start);
  replayEndInput.value = toDatetimeLocal(replaySession.end);
}

expirySelect.addEventListener("change", () => renderSnapshot());

async function reloadSeriesSelection() {
  clearScheduledCrosshairSnapshotLoad();
  if (currentMode === "replay" && replaySession) {
    await loadReplayBundle();
  } else if (currentMode === "live") {
    await loadLiveBundle(true);
  }
}

primarySeriesSelect.addEventListener("change", reloadSeriesSelection);
secondarySeriesSelect.addEventListener("change", reloadSeriesSelection);

replayLoadButton.addEventListener("click", async () => {
  try {
    stopLivePolling();
    clearScheduledCrosshairSnapshotLoad();
    await createReplay();
  } catch (error) {
    cursorTime.textContent = "load-error";
  }
});

init();
