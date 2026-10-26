import type { MatchStatus, OptionKey, Timing } from '../data/types'

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(digits)}%`
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

export function odds(value: number | null | undefined): string {
  return num(value, 2)
}

export function optionLabel(key: OptionKey | string | null | undefined): string {
  if (!key) return '—'
  if (key === 'home') return '主胜'
  if (key === 'draw') return '平'
  if (key === 'away') return '客胜'
  return String(key)
}

export function optionShort(key: OptionKey | string | null | undefined): string {
  if (!key) return '—'
  if (key === 'home') return '胜'
  if (key === 'draw') return '平'
  if (key === 'away') return '负'
  return String(key)
}

export const RISK_LABELS: Record<string, string> = {
  conservative: '稳健',
  balanced: '均衡',
  aggressive: '进取',
}

export const MARKET_LABELS: Record<string, string> = {
  HAD: '胜平负',
  HHAD: '让球胜平负',
  SCORE_TOP1: '比分 Top1',
  SCORE_TOP3: '比分 Top3',
  TOTAL_GOALS: '总进球',
  HALF_FULL: '半全场',
  HAD_DC: 'DC 模型',
  HAD_ELO: 'Elo 模型',
  HAD_ML: 'LightGBM',
}

export const STATUS_LABELS: Record<MatchStatus, string> = {
  settled: '已结算',
  pending: '待补赛果',
  skipped: '已跳过',
}

export const TIMING_LABELS: Record<Timing, string> = {
  pre_match: '赛前预测',
  post_kickoff: '开赛后补跑',
  unknown: '时间未知',
  skipped: '未预测',
}

export function formatDate(date: string | null | undefined): string {
  if (!date) return '—'
  const [y, m, d] = date.split('-')
  return `${y}-${m}-${d}`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function hhadLine(line: number | null | undefined): string {
  if (line === null || line === undefined) return '—'
  return line > 0 ? `+${line}` : String(line)
}

export function isStale(date: string | null | undefined): boolean {
  if (!date) return true
  const today = new Date()
  const local = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  return date < local
}
