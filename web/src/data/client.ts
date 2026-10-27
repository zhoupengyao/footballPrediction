import type {
  AnalysisData,
  BacktestDetail,
  BacktestIndexItem,
  DateSummary,
  Manifest,
  MatchRecord,
  OddsDiffIndexItem,
  OddsDiffPayload,
  Performance,
  RecommendationPayload,
} from './types'

const BASE = import.meta.env.BASE_URL || '/'
const DATA_ROOT = `${BASE}data`
let version = ''
const cache = new Map<string, Promise<unknown>>()

async function rawJson<T>(path: string, query = ''): Promise<T> {
  const res = await fetch(`${DATA_ROOT}/${path}${query}`, { cache: 'no-store' })
  if (!res.ok) {
    throw new Error(`数据加载失败：${path}（HTTP ${res.status}）`)
  }
  return (await res.json()) as T
}

export async function getManifest(force = false): Promise<Manifest> {
  if (!force && cache.has('manifest.json')) {
    return cache.get('manifest.json') as Promise<Manifest>
  }
  const promise = rawJson<Manifest>('manifest.json', `?t=${Date.now()}`)
  cache.set('manifest.json', promise)
  const manifest = await promise
  version = manifest.generated_at
  return manifest
}

async function getJson<T>(path: string): Promise<T> {
  if (!version) await getManifest()
  if (cache.has(path)) return cache.get(path) as Promise<T>
  const query = version ? `?v=${encodeURIComponent(version)}` : ''
  const promise = rawJson<T>(path, query)
  cache.set(path, promise)
  return promise
}

export function getHistoryIndex(): Promise<DateSummary[]> {
  return getJson<DateSummary[]>('history/index.json')
}

export function getHistory(date: string): Promise<MatchRecord[]> {
  return getJson<MatchRecord[]>(`history/${date}.json`)
}

export function getRecommendations(date: string): Promise<RecommendationPayload> {
  return getJson<RecommendationPayload>(`recommendations/${date}.json`)
}

export function getPerformance(): Promise<Performance> {
  return getJson<Performance>('performance.json')
}

export function getAnalysis(): Promise<AnalysisData> {
  return getJson<AnalysisData>('analysis.json')
}

export function getBacktests(): Promise<BacktestIndexItem[]> {
  return getJson<BacktestIndexItem[]>('backtests/index.json')
}

export function getBacktest(id: string): Promise<BacktestDetail> {
  return getJson<BacktestDetail>(`backtests/${id}.json`)
}

export function getOddsDiffIndex(): Promise<OddsDiffIndexItem[]> {
  return getJson<OddsDiffIndexItem[]>('odds-diff/index.json')
}

export function getOddsDiff(date: string): Promise<OddsDiffPayload> {
  return getJson<OddsDiffPayload>(`odds-diff/${date}.json`)
}
