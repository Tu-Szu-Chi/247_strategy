import { describe, expect, it } from "vitest";
import { buildStrikeRows, maxAbsPower, selectExpiry } from "./selectors";
import type { OptionPowerSnapshot } from "./types";

const snapshot: OptionPowerSnapshot = {
  type: "option_power_snapshot",
  generated_at: "2026-04-20T09:00:00",
  run_id: "run-1",
  session: "day",
  option_root: "TX4,TXX",
  underlying_reference_price: 20000,
  raw_pressure: 10,
  pressure_index: 15,
  raw_pressure_weighted: 9,
  pressure_index_weighted: 12,
  contract_count: 2,
  status: "running",
  expiries: [
    {
      contract_month: "202604",
      label: "2026-04",
      contracts: [
        {
          instrument_key: "call",
          symbol: "TX4",
          contract_month: "202604",
          strike_price: 20000,
          call_put: "call",
          last_price: 120,
          cumulative_buy_volume: 10,
          cumulative_sell_volume: 4,
          cumulative_power: 6,
          rolling_1m_buy_volume: 2,
          rolling_1m_sell_volume: 1,
          power_1m_delta: 1,
          unknown_volume: 0,
          last_tick_ts: "2026-04-20T09:00:00",
        },
        {
          instrument_key: "put",
          symbol: "TX4",
          contract_month: "202604",
          strike_price: 20000,
          call_put: "put",
          last_price: 122,
          cumulative_buy_volume: 2,
          cumulative_sell_volume: 8,
          cumulative_power: -6,
          rolling_1m_buy_volume: 0,
          rolling_1m_sell_volume: 2,
          power_1m_delta: -2,
          unknown_volume: 1,
          last_tick_ts: "2026-04-20T09:00:00",
        },
      ],
    },
  ],
};

describe("option power selectors", () => {
  it("selects the requested expiry and groups call/put by strike", () => {
    const expiry = selectExpiry(snapshot, "202604");
    const rows = buildStrikeRows(expiry);
    expect(rows).toHaveLength(1);
    expect(rows[0].call?.instrument_key).toBe("call");
    expect(rows[0].put?.instrument_key).toBe("put");
  });

  it("computes max absolute power for bar scaling", () => {
    const expiry = selectExpiry(snapshot, "202604");
    expect(maxAbsPower(expiry)).toBe(6);
  });
});
