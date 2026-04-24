export type ChartBarPoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

export type ChartSeriesPoint = {
  time: string;
  value: number;
};

export type IndicatorInterval = "5s" | "30s" | "1m" | "5m";

export type OptionPowerContract = {
  instrument_key: string;
  symbol: string;
  contract_month: string;
  strike_price: number;
  call_put: "call" | "put" | string;
  last_price: number | null;
  cumulative_buy_volume: number;
  cumulative_sell_volume: number;
  cumulative_power: number;
  rolling_1m_buy_volume: number;
  rolling_1m_sell_volume: number;
  power_1m_delta: number;
  unknown_volume: number;
  last_tick_ts: string | null;
};

export type OptionPowerExpiry = {
  contract_month: string;
  label: string;
  contracts: OptionPowerContract[];
};

export type OptionPowerSnapshot = {
  type: string;
  generated_at: string;
  run_id: string | null;
  session: string;
  option_root: string;
  underlying_reference_price: number | null;
  raw_pressure: number;
  pressure_index: number;
  raw_pressure_1m: number;
  pressure_index_1m: number;
  pressure_index_5m: number;
  pressure_abs: number;
  pressure_abs_1m: number;
  pressure_abs_5m: number;
  expiries: OptionPowerExpiry[];
  contract_count: number;
  status: string;
  stop_reason?: string | null;
  warning?: string | null;
};

export type ReplaySession = {
  session_id: string;
  start: string;
  end: string;
  snapshot_interval_seconds: number;
  option_root: string;
  underlying_symbol: string;
  selected_option_roots: string[];
  snapshot_count: number;
};

export type SnapshotLookupResponse = {
  index?: number;
  simulated_at?: string;
  snapshot: OptionPowerSnapshot;
};

export type LiveMeta = {
  mode: "live";
  run_id: string | null;
  status: string;
  option_root: string;
  underlying_symbol: string;
  snapshot_count: number;
  bar_count: number;
  start: string | null;
  end: string | null;
  selected_option_roots: string[];
  available_series: string[];
};

export type LiveSnapshotLatestResponse = {
  snapshot: OptionPowerSnapshot;
};

export type IndicatorSeriesMap = Record<string, ChartSeriesPoint[]>;

export type StrikeRow = {
  strike: number;
  call?: OptionPowerContract;
  put?: OptionPowerContract;
};
