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

export type RegimeLabel =
  | "trend_up"
  | "trend_down"
  | "reversal_up"
  | "reversal_down"
  | "chop"
  | "transition"
  | "no_data"
  | string;

export type RegimeSnapshot = {
  generated_at: string;
  session: string;
  close: number | null;
  session_vwap: number | null;
  vwap_distance_bps: number;
  directional_efficiency_15m: number;
  vwap_cross_count_15m: number;
  tick_imbalance_5m: number;
  trade_intensity_5m: number;
  trade_intensity_ratio_30m: number;
  range_ratio_5m_30m: number;
  adx_14: number;
  plus_di_14: number;
  minus_di_14: number;
  di_bias_14: number;
  choppiness_14: number;
  compression_score: number;
  expansion_score: number;
  compression_expansion_state: string;
  session_cvd: number;
  cvd_5m_delta: number;
  cvd_15m_delta: number;
  cvd_5m_slope: number;
  price_cvd_divergence_15m: string;
  cvd_price_alignment: string;
  trend_score: number;
  chop_score: number;
  reversal_risk: number;
  regime_label: RegimeLabel;
};

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
  raw_pressure_weighted: number;
  pressure_index_weighted: number;
  regime?: RegimeSnapshot | null;
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
  available_series?: string[];
  regime_schema?: Array<Record<string, string>>;
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
