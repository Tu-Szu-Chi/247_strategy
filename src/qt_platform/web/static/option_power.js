const expirySelect = document.getElementById("expiry-select");
const chart = document.getElementById("chart");
const connectionStatus = document.getElementById("connection-status");
const sessionLabel = document.getElementById("session-label");
const rootsLabel = document.getElementById("roots-label");
const snapshotTime = document.getElementById("snapshot-time");
const referencePrice = document.getElementById("reference-price");

let latestSnapshot = null;
let selectedExpiry = "";

async function pollSnapshot() {
  try {
    const response = await fetch("/api/option-power/snapshot", { cache: "no-store" });
    latestSnapshot = await response.json();
    connectionStatus.textContent = "polling";
    render();
  } catch (error) {
    connectionStatus.textContent = "disconnected";
  } finally {
    window.setTimeout(pollSnapshot, 5000);
  }
}

function render() {
  if (!latestSnapshot) {
    return;
  }

  sessionLabel.textContent = latestSnapshot.session || "-";
  rootsLabel.textContent = (latestSnapshot.option_root || "-").replaceAll(",", " + ");
  snapshotTime.textContent = formatTime(latestSnapshot.generated_at);
  referencePrice.textContent = latestSnapshot.underlying_reference_price ?? "-";

  const expiries = latestSnapshot.expiries || [];
  syncExpiryOptions(expiries);
  const currentExpiry = expiries.find((item) => item.contract_month === selectedExpiry) || expiries[0];
  if (!currentExpiry) {
    chart.innerHTML = `<div class="empty">尚未收到任何合約 tick。</div>`;
    return;
  }

  selectedExpiry = currentExpiry.contract_month;
  const contracts = currentExpiry.contracts || [];
  const grouped = groupByStrike(contracts);
  const maxAbsPower = Math.max(
    1,
    ...contracts.map((item) => Math.abs(item.cumulative_power || 0)),
  );

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

function renderCell(contract, maxAbsPower, label) {
  if (!contract) {
    return `
      <div class="cell">
        <div class="cell-head"><span>${label}</span><strong>-</strong></div>
        <div class="bar-wrap"><div class="midline"></div></div>
      </div>
    `;
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
        <div class="bar ${isBull ? "bull" : "bear"}" style="${isBull ? `left:50%;` : `right:50%;`} width:${widthPercent}%;"></div>
        <div class="bar-value">${formatSigned(contract.cumulative_power)}</div>
      </div>
    </div>
  `;
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

expirySelect.addEventListener("change", (event) => {
  selectedExpiry = event.target.value;
  render();
});

pollSnapshot();
