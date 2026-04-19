const modeLabel = document.getElementById("mode-label");
const sessionIdLabel = document.getElementById("session-id");
const rootsLabel = document.getElementById("roots-label");
const rangeLabel = document.getElementById("range-label");
const cursorTime = document.getElementById("cursor-time");
const replayStartInput = document.getElementById("replay-start");
const replayEndInput = document.getElementById("replay-end");
const replayLoadButton = document.getElementById("replay-load");
const seriesSelect = document.getElementById("series-select");
const expirySelect = document.getElementById("expiry-select");
const chart = document.getElementById("chart");
const rawPressure = document.getElementById("raw-pressure");
const pressureIndex = document.getElementById("pressure-index");
const rawPressure1m = document.getElementById("raw-pressure-1m");
const pressureIndex1m = document.getElementById("pressure-index-1m");
const priceChartContainer = document.getElementById("price-chart");
const indicatorChartContainer = document.getElementById("indicator-chart");
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
let indicatorChart = null;
let candleSeries = null;
let lineSeries = null;
let livePollingHandle = null;

function initCharts() {
  priceChart = LightweightCharts.createChart(priceChartContainer, chartOptions(440));
  candleSeries = priceChart.addCandlestickSeries({
    upColor: "#ff6a5a",
    downColor: "#41b883",
    borderVisible: false,
    wickUpColor: "#ff6a5a",
    wickDownColor: "#41b883",
  });

  indicatorChart = LightweightCharts.createChart(indicatorChartContainer, chartOptions(220));
  lineSeries = indicatorChart.addLineSeries({
    color: "#ffd166",
    lineWidth: 2,
    crosshairMarkerVisible: true,
    priceLineVisible: false,
  });

  priceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
    if (range) {
      indicatorChart.timeScale().setVisibleRange(range);
    }
  });
  indicatorChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
    if (range) {
      priceChart.timeScale().setVisibleRange(range);
    }
  });

  const syncCrosshair = async (param) => {
    if (!param || !param.time) {
      return;
    }
    const isoTime = toIsoTime(param.time);
    cursorTime.textContent = formatDateTime(isoTime);
    if (currentMode === "replay" && replaySession) {
      await loadReplaySnapshotAt(isoTime);
    } else if (currentMode === "live") {
      await loadLiveSnapshotAt(isoTime);
    }
  };
  priceChart.subscribeCrosshairMove(syncCrosshair);
  indicatorChart.subscribeCrosshairMove(syncCrosshair);
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
  const replayLoaded = await tryLoadDefaultReplay();
  if (!replayLoaded) {
    await loadLiveBundle();
    startLivePolling();
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

  const [barsResponse, seriesResponse, snapshotResponse] = await Promise.all([
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/bars`, { cache: "no-store" }),
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/series?names=${encodeURIComponent(seriesSelect.value)}`, { cache: "no-store" }),
    fetch(`/api/option-power/replay/sessions/${replaySession.session_id}/snapshot-at?ts=${encodeURIComponent(replaySession.start)}`, { cache: "no-store" }),
  ]);

  const bars = await barsResponse.json();
  const indicatorSeries = await seriesResponse.json();
  const snapshotPayload = await snapshotResponse.json();

  renderTimeline(bars, indicatorSeries[seriesSelect.value] || []);
  currentSnapshot = snapshotPayload.snapshot;
  cursorTime.textContent = formatDateTime(snapshotPayload.simulated_at);
  renderSnapshot();
}

async function loadReplaySnapshotAt(ts) {
  const response = await fetch(
    `/api/option-power/replay/sessions/${replaySession.session_id}/snapshot-at?ts=${encodeURIComponent(ts)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  currentSnapshot = payload.snapshot;
  renderSnapshot();
}

async function loadLiveBundle() {
  const [metaResponse, barsResponse, seriesResponse, snapshotResponse] = await Promise.all([
    fetch("/api/option-power/live/meta", { cache: "no-store" }),
    fetch("/api/option-power/live/bars", { cache: "no-store" }),
    fetch(`/api/option-power/live/series?names=${encodeURIComponent(seriesSelect.value)}`, { cache: "no-store" }),
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

  const bars = await barsResponse.json();
  const indicatorSeries = await seriesResponse.json();
  const snapshotPayload = await snapshotResponse.json();

  renderTimeline(bars, indicatorSeries[seriesSelect.value] || []);
  currentSnapshot = snapshotPayload.snapshot;
  cursorTime.textContent = formatDateTime(currentSnapshot.generated_at);
  renderSnapshot();
}

function startLivePolling() {
  stopLivePolling();
  livePollingHandle = window.setInterval(async () => {
    try {
      await loadLiveBundle();
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

async function loadLiveSnapshotAt(ts) {
  const response = await fetch(`/api/option-power/live/snapshot-at?ts=${encodeURIComponent(ts)}`, { cache: "no-store" });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  currentSnapshot = payload.snapshot;
  renderSnapshot();
}

function renderTimeline(bars, lineData) {
  candleSeries.setData((bars || []).map(normalizeBar));
  lineSeries.setData((lineData || []).map(normalizeLinePoint));
  priceChart.timeScale().fitContent();
  indicatorChart.timeScale().fitContent();
}

function renderSnapshot() {
  if (!currentSnapshot) {
    return;
  }
  renderPressureValue(rawPressure, currentSnapshot.raw_pressure);
  renderPressureValue(pressureIndex, currentSnapshot.pressure_index);
  renderPressureValue(rawPressure1m, currentSnapshot.raw_pressure_1m);
  renderPressureValue(pressureIndex1m, currentSnapshot.pressure_index_1m);

  const expiries = currentSnapshot.expiries || [];
  syncExpiryOptions(expiries);
  const currentExpiry = expiries.find((item) => item.contract_month === selectedExpiry) || expiries[0];
  if (!currentExpiry) {
    chart.innerHTML = `<div class="empty">該時間點沒有 option snapshot。</div>`;
    return;
  }

  selectedExpiry = currentExpiry.contract_month;
  const contracts = currentExpiry.contracts || [];
  const grouped = groupByStrike(contracts);
  const maxAbsPower = Math.max(1, ...contracts.map((item) => Math.abs(item.cumulative_power || 0)));

  chart.innerHTML = "";
  grouped.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div class="strike-label">${entry.strike}</div>
      ${renderCell(entry.call, maxAbsPower, "C")}
      ${renderCell(entry.put, maxAbsPower, "P")}
    `;
    chart.appendChild(row);
  });
}

function normalizeBar(item) {
  return { time: toUnixSeconds(item.time), open: item.open, high: item.high, low: item.low, close: item.close };
}

function normalizeLinePoint(item) {
  return { time: toUnixSeconds(item.time), value: item.value };
}

function renderCell(contract, maxAbsPower, label) {
  if (!contract) {
    return `<div class="cell"><div class="cell-head"><span>${label}</span><strong>-</strong></div><div class="bar-wrap"><div class="midline"></div></div></div>`;
  }
  const widthPercent = Math.min(100, (Math.abs(contract.cumulative_power || 0) / maxAbsPower) * 50);
  const isBull = isBullishDirection(contract);
  const deltaClass = deltaDirectionClass(contract);
  return `
    <div class="cell">
      <div class="cell-head"><span>${label}</span><strong class="delta ${deltaClass}">${formatSigned(contract.power_1m_delta)}</strong></div>
      <div class="bar-wrap">
        <div class="midline"></div>
        <div class="mid-price">${formatPrice(contract.last_price)}</div>
        <div class="bar ${isBull ? "bull" : "bear"}" style="${isBull ? "left:50%;" : "right:50%;"} width:${widthPercent}%;"></div>
        <div class="bar-value">${formatSigned(contract.cumulative_power)}</div>
      </div>
    </div>
  `;
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

function renderPressureValue(element, value) {
  const num = Number(value || 0);
  element.textContent = formatSigned(num);
  element.className = pressureClass(num);
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

function hydrateReplayInputs() {
  replayStartInput.value = toDatetimeLocal(replaySession.start);
  replayEndInput.value = toDatetimeLocal(replaySession.end);
}

expirySelect.addEventListener("change", () => renderSnapshot());

seriesSelect.addEventListener("change", async () => {
  if (currentMode === "replay" && replaySession) {
    await loadReplayBundle();
  } else if (currentMode === "live") {
    await loadLiveBundle();
  }
});

replayLoadButton.addEventListener("click", async () => {
  try {
    stopLivePolling();
    await createReplay();
  } catch (error) {
    cursorTime.textContent = "load-error";
  }
});

init();
