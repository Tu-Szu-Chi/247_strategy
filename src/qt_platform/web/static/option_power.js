const expirySelect = document.getElementById("expiry-select");
const chart = document.getElementById("chart");
const connectionStatus = document.getElementById("connection-status");
const sessionLabel = document.getElementById("session-label");
const rootsLabel = document.getElementById("roots-label");
const snapshotTime = document.getElementById("snapshot-time");
const referencePrice = document.getElementById("reference-price");
const rawPressure = document.getElementById("raw-pressure");
const pressureIndex = document.getElementById("pressure-index");
const rawPressure1m = document.getElementById("raw-pressure-1m");
const pressureIndex1m = document.getElementById("pressure-index-1m");
const replayControls = document.getElementById("replay-controls");
const replayStartInput = document.getElementById("replay-start");
const replayEndInput = document.getElementById("replay-end");
const replayLoadButton = document.getElementById("replay-load");
const replayPlayButton = document.getElementById("replay-play");
const replayPauseButton = document.getElementById("replay-pause");
const replaySpeedSelect = document.getElementById("replay-speed");
const replayProgress = document.getElementById("replay-progress");
const replaySlider = document.getElementById("replay-slider");
const dataMode = document.getElementById("data-mode");

let latestSnapshot = null;
let selectedExpiry = "";
let livePollingHandle = null;
let playbackHandle = null;
let replaySession = null;
let replayIndex = 0;
let isReplayMode = false;
let chartRowMap = new Map();
let chartEmptyState = null;

async function init() {
  const replayAvailable = await tryLoadDefaultReplay();
  if (!replayAvailable) {
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
    isReplayMode = true;
    dataMode.textContent = "replay";
    replayControls.classList.remove("hidden");
    hydrateReplayInputs();
    await loadReplaySnapshot(0);
    return true;
  } catch (error) {
    return false;
  }
}

function startLivePolling() {
  isReplayMode = false;
  dataMode.textContent = "live";
  void pollSnapshot();
}

async function pollSnapshot() {
  try {
    const response = await fetch("/api/option-power/snapshot", { cache: "no-store" });
    latestSnapshot = await response.json();
    connectionStatus.textContent = "polling";
    render();
  } catch (error) {
    connectionStatus.textContent = "disconnected";
  } finally {
    if (!isReplayMode) {
      livePollingHandle = window.setTimeout(pollSnapshot, 5000);
    }
  }
}

async function createReplaySession() {
  stopPlayback();
  const payload = {
    start: fromDatetimeLocal(replayStartInput.value),
    end: fromDatetimeLocal(replayEndInput.value),
  };
  const response = await fetch("/api/option-power/replay/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Unable to create replay session.");
  }
  replaySession = await response.json();
  replayIndex = 0;
  hydrateReplayInputs();
  await loadReplaySnapshot(0);
}

async function loadReplaySnapshot(index) {
  if (!replaySession) {
    return;
  }
  const boundedIndex = Math.max(0, Math.min(index, replaySession.snapshot_count - 1));
  const response = await fetch(
    `/api/option-power/replay/sessions/${replaySession.session_id}/snapshots/${boundedIndex}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error("Unable to load replay snapshot.");
  }
  const payload = await response.json();
  replayIndex = payload.index;
  latestSnapshot = payload.snapshot;
  connectionStatus.textContent = "replay";
  replayProgress.textContent = `${replayIndex + 1} / ${replaySession.snapshot_count}`;
  replaySlider.max = String(Math.max(replaySession.snapshot_count - 1, 0));
  replaySlider.value = String(replayIndex);
  render();
}

function startPlayback() {
  if (!replaySession || replaySession.snapshot_count <= 1) {
    return;
  }
  stopPlayback();
  const speed = Number(replaySpeedSelect.value || 1);
  const stepMs = Math.max(120, 1000 / speed);
  playbackHandle = window.setInterval(async () => {
    if (!replaySession || replayIndex >= replaySession.snapshot_count - 1) {
      stopPlayback();
      return;
    }
    try {
      await loadReplaySnapshot(replayIndex + 1);
    } catch (error) {
      stopPlayback();
      connectionStatus.textContent = "replay-error";
    }
  }, stepMs);
}

function stopPlayback() {
  if (playbackHandle !== null) {
    window.clearInterval(playbackHandle);
    playbackHandle = null;
  }
}

function hydrateReplayInputs() {
  if (!replaySession) {
    return;
  }
  replayStartInput.value = toDatetimeLocal(replaySession.start);
  replayEndInput.value = toDatetimeLocal(replaySession.end);
  replayProgress.textContent = `${replayIndex + 1} / ${replaySession.snapshot_count}`;
  replaySlider.max = String(Math.max(replaySession.snapshot_count - 1, 0));
  replaySlider.value = String(replayIndex);
}

function render() {
  if (!latestSnapshot) {
    return;
  }

  sessionLabel.textContent = latestSnapshot.session || "-";
  rootsLabel.textContent = (latestSnapshot.option_root || "-").replaceAll(",", " + ");
  snapshotTime.textContent = formatTime(latestSnapshot.generated_at);
  referencePrice.textContent = latestSnapshot.underlying_reference_price ?? "-";
  renderPressureValue(rawPressure, latestSnapshot.raw_pressure);
  renderPressureValue(pressureIndex, latestSnapshot.pressure_index);
  renderPressureValue(rawPressure1m, latestSnapshot.raw_pressure_1m);
  renderPressureValue(pressureIndex1m, latestSnapshot.pressure_index_1m);

  const expiries = latestSnapshot.expiries || [];
  syncExpiryOptions(expiries);
  const currentExpiry = expiries.find((item) => item.contract_month === selectedExpiry) || expiries[0];
  if (!currentExpiry) {
    renderEmptyChart();
    return;
  }

  selectedExpiry = currentExpiry.contract_month;
  const contracts = currentExpiry.contracts || [];
  const grouped = groupByStrike(contracts);
  const maxAbsPower = Math.max(
    1,
    ...contracts.map((item) => Math.abs(item.cumulative_power || 0)),
  );
  renderChartRows(grouped, maxAbsPower);
}

function renderEmptyChart() {
  if (!chartEmptyState) {
    chartEmptyState = document.createElement("div");
    chartEmptyState.className = "empty";
    chartEmptyState.textContent = "尚未收到任何合約 tick。";
  }
  chart.replaceChildren(chartEmptyState);
  chartRowMap = new Map();
}

function renderChartRows(grouped, maxAbsPower) {
  if (chartEmptyState && chart.contains(chartEmptyState)) {
    chart.removeChild(chartEmptyState);
  }

  const nextRowMap = new Map();
  grouped.forEach((entry) => {
    const key = String(entry.strike);
    let row = chartRowMap.get(key);
    if (!row) {
      row = createRow(entry.strike);
    }
    updateRow(row, entry, maxAbsPower);
    chart.appendChild(row);
    nextRowMap.set(key, row);
  });

  chartRowMap.forEach((row, key) => {
    if (!nextRowMap.has(key)) {
      row.remove();
    }
  });
  chartRowMap = nextRowMap;
}

function createRow(strike) {
  const row = document.createElement("div");
  row.className = "row";

  const strikeLabel = document.createElement("div");
  strikeLabel.className = "strike-label";
  strikeLabel.textContent = String(strike);
  row.appendChild(strikeLabel);

  row.appendChild(createCell("C"));
  row.appendChild(createCell("P"));
  return row;
}

function createCell(label) {
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

function updateRow(row, entry, maxAbsPower) {
  row.firstChild.textContent = String(entry.strike);
  updateCell(row.children[1], entry.call, maxAbsPower);
  updateCell(row.children[2], entry.put, maxAbsPower);
}

function updateCell(cell, contract, maxAbsPower) {
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
  if (contract.call_put === "put") {
    return power <= 0;
  }
  return power >= 0;
}

function deltaDirectionClass(contract) {
  const delta = Number(contract.power_1m_delta || 0);
  if (delta === 0) {
    return "";
  }
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
    if (contract.call_put === "call") {
      current.call = contract;
    } else if (contract.call_put === "put") {
      current.put = contract;
    }
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

function formatSigned(value) {
  const num = Number(value || 0);
  return `${num > 0 ? "+" : ""}${num.toFixed(0)}`;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-TW", { hour12: false });
}

function formatPrice(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  const num = Number(value);
  if (Number.isNaN(num)) {
    return String(value);
  }
  return num >= 100 ? num.toFixed(0) : num.toFixed(1);
}

function renderPressureValue(element, value) {
  const num = Number(value || 0);
  element.textContent = formatSigned(num);
  element.className = pressureClass(num);
}

function pressureClass(value) {
  if (value > 0) {
    return "pressure-positive";
  }
  if (value < 0) {
    return "pressure-negative";
  }
  return "";
}

function toDatetimeLocal(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function fromDatetimeLocal(value) {
  if (!value) {
    return "";
  }
  return `${value}:00`;
}

expirySelect.addEventListener("change", (event) => {
  selectedExpiry = event.target.value;
  render();
});

replayLoadButton.addEventListener("click", async () => {
  try {
    await createReplaySession();
  } catch (error) {
    connectionStatus.textContent = "replay-error";
  }
});

replayPlayButton.addEventListener("click", () => {
  startPlayback();
});

replayPauseButton.addEventListener("click", () => {
  stopPlayback();
});

replaySlider.addEventListener("input", async (event) => {
  if (!replaySession) {
    return;
  }
  stopPlayback();
  try {
    await loadReplaySnapshot(Number(event.target.value || 0));
  } catch (error) {
    connectionStatus.textContent = "replay-error";
  }
});

init();
