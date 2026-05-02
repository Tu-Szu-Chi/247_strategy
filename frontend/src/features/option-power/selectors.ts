import type { OptionPowerExpiry, MonitorSnapshot, StrikeRow } from "./types";

export function selectExpiry(
  snapshot: MonitorSnapshot | null,
  selectedExpiry: string,
): OptionPowerExpiry | null {
  const expiries = snapshot?.expiries ?? [];
  return expiries.find((item) => item.contract_month === selectedExpiry) ?? expiries[0] ?? null;
}

export function buildStrikeRows(expiry: OptionPowerExpiry | null): StrikeRow[] {
  if (!expiry) {
    return [];
  }
  const grouped = new Map<number, StrikeRow>();
  for (const contract of expiry.contracts) {
    const strike = Number(contract.strike_price);
    const existing = grouped.get(strike) ?? { strike };
    if (contract.call_put === "call") {
      existing.call = contract;
    } else {
      existing.put = contract;
    }
    grouped.set(strike, existing);
  }
  return [...grouped.values()].sort((left, right) => left.strike - right.strike);
}

export function maxAbsPower(expiry: OptionPowerExpiry | null): number {
  const contracts = expiry?.contracts ?? [];
  return Math.max(1, ...contracts.map((item) => Math.abs(item.cumulative_power || 0)));
}
