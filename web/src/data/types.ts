export type OptionKey = 'home' | 'draw' | 'away'
export type Risk = 'conservative' | 'balanced' | 'aggressive'
export type Timing = 'pre_match' | 'post_kickoff' | 'unknown' | 'skipped'
export type MatchStatus = 'settled' | 'pending' | 'skipped'

export interface Probs {
  home: number | null
  draw: number | null
  away: number | null
}

export interface LeagueInfo {
  div: string
  name: string
  country: string
  tier?: number | null
  has_model: boolean
}

export interface MarketStat {
  n: number
  hits: number
  accuracy: number | null
}

export interface ValueStat {
  n: number
  hits: number
  hit_rate: number | null
  pnl_unit: number
  pnl_pct: number
  staked_pct: number
  roi: number | null
}

export interface DateSummary {
  date: string
  total: number
  predicted: number
  settled: number
  pending: number
  skipped: number
  post_kickoff: number
  value_bets: number
  markets: Record<string, MarketStat>
  value: ValueStat
}

export interface Manifest {
  schema_version: number
  generated_at: string
  site: { name: string; tagline: string }
  latest_match_date: string | null
  latest_prediction_date: string | null
  counts: {
    matches: number
    predicted: number
    settled: number
    pending: number
    skipped: number
    value_bets: number
    dates: number
  }
  dates: DateSummary[]
  leagues: LeagueInfo[]
  sources: string[]
  disclaimer: string
}

export interface HadMarket {
  available: boolean
  probs: Probs | null
  odds: Probs | null
  implied: Probs | null
  blended: Probs | null
  predicted: OptionKey | null
  actual: OptionKey | null
  hit: boolean | null
}

export interface HhadMarket extends HadMarket {
  line: number | null
}

export interface ScoreTop {
  score: string
  prob: number | null
}

export interface ScoreMarket {
  available: boolean
  top: ScoreTop[]
  predicted: string | null
  actual: string | null
  top1_hit: boolean | null
  top3_hit: boolean | null
}

export interface TotalGoalsMarket {
  available: boolean
  probs: Record<string, number | null>
  predicted: string | null
  actual: string | null
  hit: boolean | null
}

export interface HalfFullTop {
  label: string
  prob: number | null
}

export interface HalfFullMarket {
  available: boolean
  top: HalfFullTop[]
  predicted: string | null
  actual: string | null
  hit: boolean | null
}

export interface ModelLayer {
  probs: Probs
  predicted: OptionKey | null
  hit: boolean | null
}

export interface ValueBet {
  market: string
  option: OptionKey | null
  option_cn: string
  odds: number | null
  model_prob: number | null
  implied_prob: number | null
  edge: number | null
  ev: number | null
  stake_pct: number | null
  hit: boolean | null
  pnl_unit: number | null
  pnl_pct: number | null
}

export interface Prediction {
  model: string | null
  generated_at: string
  timing: Timing
  source: string
  xg: { home: number | null; away: number | null }
  confidence: { home: string | null; away: string | null }
  markets: {
    HAD: HadMarket
    HHAD: HhadMarket
    SCORE: ScoreMarket
    TOTAL_GOALS: TotalGoalsMarket
    HALF_FULL: HalfFullMarket
  }
  model_layers: Record<string, ModelLayer>
  value_bets: ValueBet[]
}

export interface MatchResult {
  resolved: boolean
  ft: string
  ht: string | null
  had: OptionKey | null
  hhad: OptionKey | null
  total_goals: string | null
  half_full: string | null
}

export interface MatchRecord {
  id: string
  match_num: string
  date: string
  time: string | null
  kickoff: string | null
  league: { div: string | null; name: string; code: string | null }
  home: { cn: string; matched: string | null }
  away: { cn: string; matched: string | null }
  status: MatchStatus
  skip_reason: string | null
  prediction_timing: Timing
  prediction: Prediction | null
  result: MatchResult | null
}

export interface RecommendationItem {
  match_num: string
  league: string
  div: string
  home_cn: string
  away_cn: string
  market: string
  option: string
  odds: number
  model_prob: number
  implied_prob: number
  edge: number
  ev: number
  tier: number
  reason: string
  stake_pct?: number
  stake_amount?: number
}

export interface RiskResult {
  risk: string
  recommendations: RecommendationItem[]
  observations: RecommendationItem[]
  total_stake_pct: number
  bankroll: number | null
}

export interface RecommendationPayload {
  date: string
  generated_at: string
  source: string
  risks: Record<Risk, RiskResult>
  official?: unknown
}

export interface Performance {
  generated_at: string
  overall: {
    total: number
    predicted: number
    settled: number
    pending: number
    skipped: number
    post_kickoff: number
    stats_settled: number
    markets: Record<string, MarketStat>
    value: ValueStat
  }
  by_league: Array<{
    div: string
    name: string
    total: number
    predicted: number
    settled: number
    markets: Record<string, MarketStat>
    value: ValueStat
  }>
  daily: DateSummary[]
  ledger: LedgerRow[]
  note: string
}

export interface LedgerRow {
  date: string
  match_num: string
  league: string
  div: string
  home_cn: string
  away_cn: string
  market: string
  option: string
  odds: number | null
  model_prob: number | null
  implied_prob: number | null
  edge: number | null
  ev: number | null
  stake_pct: number | null
  hit: boolean | null
  pnl_unit: number | null
  pnl_pct: number | null
}

export interface BacktestIndexItem {
  id: string
  label: string
  generated_at: string
  n: number | null
  accuracy: number | null
  log_loss: number | null
  brier: number | null
  has_odds: boolean | null
  roi: number | null
  file: string
}

export interface CalibrationPoint {
  lo: number
  hi: number
  n: number
  pred_mean: number
  emp_freq: number
}

export interface BacktestOverall {
  n: number
  accuracy: number | null
  baseline_home: number | null
  log_loss: number | null
  brier: number | null
  ece?: number | null
  calibration: CalibrationPoint[]
  has_odds: boolean
  betting?: {
    n_bets: number
    staked: number
    profit: number
    roi: number | null
    hit_rate: number | null
    avg_ev: number | null
    max_drawdown: number
    final_equity: number
  }
}

export interface EquityPoint {
  i: number
  date: string
  equity: number
  bets: number
}

export interface BacktestDetail {
  id: string
  label: string
  generated_at: string
  config: Record<string, unknown>
  overall: BacktestOverall
  per_league: Record<string, BacktestOverall>
  equity_curve: EquityPoint[]
}

export interface OddsDiffOption {
  from: number
  to: number
  delta: number
  delta_pct: number | null
}

export interface OddsDiffMatch {
  match_num: string
  match_id: number | null
  home_cn: string
  away_cn: string
  had: Record<string, OddsDiffOption>
  hhad: Record<string, OddsDiffOption>
  line: number | null
}

export interface OddsDiffPayload {
  date: string
  snapshots: Array<{ file: string; fetched_at: string }>
  matches: OddsDiffMatch[]
}

export interface OddsDiffIndexItem {
  date: string
  snapshots: number
  matches: number
}

export type AnalysisMarketKey = 'HAD' | 'HHAD' | 'SCORE' | 'TOTAL_GOALS' | 'HALF_FULL'

export interface AnalysisBin {
  label: string
  lo: number
  hi: number
  n: number
  hits: number
  misses: number
  accuracy: number | null
  avg_pred: number | null
  avg_actual_prob: number | null
  gap: number | null
  ci_low: number | null
  ci_high: number | null
}

export interface AnalysisCase {
  date: string
  match_num: string
  league: string | null
  home: string
  away: string
  result: string | null
  predicted: string
  actual: string
  confidence: number
  actual_prob: number | null
  hit: boolean
}

export interface ScoreProbBin {
  label: string
  n: number
}

export interface ScoreRankStat {
  rank: number
  n: number
  avg_actual_prob: number | null
  min_actual_prob: number | null
  max_actual_prob: number | null
}

export interface ScoreHitCase {
  date: string
  match_num: string
  league: string | null
  home: string
  away: string
  result: string | null
  top3: string[]
  actual: string
  p_actual: number
  rank: number
  coverage: number
  ratio: number | null
}

export interface ScoreHitDetail {
  n: number
  avg_actual_prob: number | null
  median_actual_prob: number | null
  min_actual_prob: number | null
  max_actual_prob: number | null
  prob_bins: ScoreProbBin[]
  by_rank: ScoreRankStat[]
  ratio: { avg: number | null; min: number | null; max: number | null }
  coverage: { total: number; top1: number; top2: number; top3: number }
  cases: ScoreHitCase[]
}

export interface AnalysisMarket {
  key: string
  label: string
  n: number
  hits: number
  accuracy: number | null
  avg_confidence: number | null
  avg_actual_prob: number | null
  ece: number | null
  brier: number | null
  log_loss: number | null
  bins: AnalysisBin[]
  actual_rank: Record<string, number> | null
  confusion: Record<string, Record<string, number>> | null
  high_conf_threshold: number
  low_conf_threshold: number
  high_conf_wrong: AnalysisCase[]
  low_conf_hit: AnalysisCase[]
  hit_detail?: ScoreHitDetail | null
}

export interface AnalysisValueBin {
  label: string
  n: number
  hits: number
  hit_rate: number | null
  pnl_unit: number
  roi: number | null
}

export interface AnalysisValue {
  n: number
  hits: number
  hit_rate: number | null
  pnl_unit: number
  roi: number | null
  by_edge: AnalysisValueBin[]
  by_odds: AnalysisValueBin[]
}

export interface AnalysisLeague {
  div: string
  name: string
  n: number
  hits: number
  accuracy: number | null
  avg_confidence: number | null
}

export interface AnalysisDaily {
  date: string
  n: number
  hits: number
  accuracy: number | null
  avg_confidence: number | null
  value_n: number
  value_hits: number
  value_roi: number | null
}

export interface AnalysisData {
  generated_at: string
  sample: {
    pre_match_settled: number
    dates: number
    total_history: number
    excluded_post_kickoff: number
  }
  markets: Record<AnalysisMarketKey, AnalysisMarket>
  layers: Record<string, AnalysisMarket>
  value: AnalysisValue
  by_league: AnalysisLeague[]
  daily: AnalysisDaily[]
  note: string
}
