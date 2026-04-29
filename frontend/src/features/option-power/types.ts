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

export type IndicatorInterval = "1m" | "5m" | "15m" | "30m";
export type ReplayComputeStatus = "pending" | "running" | "ready" | "partial" | "failed" | string;

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
  directional_efficiency_15b: number;
  vwap_cross_count_15b: number;
  tick_imbalance_5b: number;
  trade_intensity_5b: number;
  trade_intensity_ratio_30b: number;
  range_ratio_5b_30b: number;
  adx_14: number;
  plus_di_14: number;
  minus_di_14: number;
  di_bias_14: number;
  choppiness_14: number;
  compression_score: number;
  expansion_score: number;
  compression_expansion_state: string;
  session_cvd: number;
  cvd_5b_delta: number;
  cvd_15b_delta: number;
  cvd_5b_slope: number;
  price_cvd_divergence_15b: string;
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

export type OptionIvPoint = {
  instrument_key: string;
  symbol: string;
  contract_month: string;
  strike_price: number;
  call_put: "call" | "put" | string;
  last_price: number;
  iv: number;
  moneyness: number;
  side: string;
  last_tick_ts: string | null;
};

export type OptionIvExpiry = {
  contract_month: string;
  label: string;
  time_to_expiry_years: number;
  skew: number | null;
  call_wing_iv: number | null;
  put_wing_iv: number | null;
  point_count: number;
  points: OptionIvPoint[];
};

export type OptionIvSurface = {
  generated_at: string;
  underlying_reference_price: number | null;
  underlying_reference_source: string | null;
  skew: number | null;
  skew_intensity: number | null;
  expiries: OptionIvExpiry[];
  status: string;
  warning?: string | null;
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
  iv_surface?: OptionIvSurface | null;
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
  bar_count?: number | null;
  cache_mode?: "memory" | string;
  loaded_window_count?: number;
  supports_windowed_loading?: boolean;
  compute_status?: ReplayComputeStatus;
  computed_until?: string | null;
  progress_ratio?: number;
  checkpoint_count?: number;
  target_window_bars?: number;
  compute_error?: string | null;
};

export type ReplaySeriesResponse = {
  series: IndicatorSeriesMap;
  status: ReplayComputeStatus;
  compute_status: ReplayComputeStatus;
  partial: boolean;
  computed_until: string | null;
  progress_ratio: number;
  checkpoint_count: number;
};

export type ReplayBundleCoverage = {
  anchor: string;
  direction: "prev" | "next" | "around" | string;
  interval: IndicatorInterval | string;
  bar_count: number;
  first_bar_time: string | null;
  last_bar_time: string | null;
  has_prev: boolean;
  has_next: boolean;
};

export type ReplayBundleByBarsResponse = ReplaySeriesResponse & {
  bars: ChartBarPoint[];
  coverage: ReplayBundleCoverage;
  session?: ReplaySession;
};

export type ReplayProgress = {
  status: ReplayComputeStatus;
  compute_status: ReplayComputeStatus;
  computed_until: string | null;
  progress_ratio: number;
  checkpoint_count: number;
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
