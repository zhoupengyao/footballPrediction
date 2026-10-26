import { useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Filter, Search } from 'lucide-react'
import { getHistory, getManifest } from '../data/client'
import type { MatchRecord } from '../data/types'
import { useAsync } from '../lib/useAsync'
import { formatDateTime, optionShort, pct, STATUS_LABELS } from '../lib/format'
import { MatchCard } from '../components/MatchCard'
import {
  Badge,
  EmptyState,
  ErrorBox,
  HitMark,
  Loading,
  PageHeader,
  Panel,
  ProbBar,
  ValueBadge,
} from '../components/ui'

type StatusFilter = 'all' | 'predicted' | 'settled' | 'pending' | 'skipped'

export function Matches() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const manifestState = useAsync(getManifest, [])
  const manifest = manifestState.data
  const selectedDate = params.get('date') || manifest?.latest_match_date || ''
  const historyState = useAsync(
    () => (selectedDate ? getHistory(selectedDate) : Promise.resolve([] as MatchRecord[])),
    [selectedDate],
  )

  const league = params.get('league') || 'all'
  const status = (params.get('status') || 'all') as StatusFilter
  const valueOnly = params.get('value') === '1'
  const query = params.get('q') || ''

  const records = historyState.data ?? []
  const leagues = useMemo(() => {
    const set = new Map<string, string>()
    for (const r of records) {
      if (r.league.div) set.set(r.league.div, r.league.name || r.league.div)
    }
    return [...set.entries()].sort((a, b) => a[1].localeCompare(b[1], 'zh-CN'))
  }, [records])

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase()
    return records.filter((r) => {
      if (league !== 'all' && r.league.div !== league) return false
      if (valueOnly && !(r.prediction?.value_bets.length)) return false
      if (status === 'predicted' && r.status === 'skipped') return false
      if (status !== 'all' && status !== 'predicted' && r.status !== status) return false
      if (text) {
        const hay = `${r.home.cn} ${r.away.cn} ${r.home.matched ?? ''} ${r.away.matched ?? ''} ${r.match_num} ${r.league.name}`.toLowerCase()
        if (!hay.includes(text)) return false
      }
      return true
    })
  }, [records, league, status, valueOnly, query])

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (!value || value === 'all' || value === '0') next.delete(key)
    else next.set(key, value)
    if (key !== 'date' && selectedDate && !next.get('date')) next.set('date', selectedDate)
    setParams(next, { replace: true })
  }

  const dates = useMemo(
    () => [...(manifest?.dates ?? [])].sort((a, b) => b.date.localeCompare(a.date)),
    [manifest],
  )

  return (
    <div>
      <PageHeader
        title="比赛历史"
        subtitle="每场比赛的预测、实际比分与五种玩法命中情况"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">共 {records.length} 场</Badge>
            <Badge tone="green">已结算 {records.filter((r) => r.status === 'settled').length}</Badge>
            <Badge tone="amber">价值 {records.reduce((n, r) => n + (r.prediction?.value_bets.length ?? 0), 0)}</Badge>
          </div>
        }
      />

      <Panel className="mb-5">
        <div className="grid gap-3 md:grid-cols-[160px_1fr_150px_130px_auto] md:items-center">
          <select
            value={selectedDate}
            onChange={(e) => update('date', e.target.value)}
            className="rounded-xl border border-line bg-raised px-3 py-2 text-xs text-slate-200 outline-none focus:border-pitch/50"
          >
            {dates.map((d) => (
              <option key={d.date} value={d.date}>
                {d.date}（{d.total} 场）
              </option>
            ))}
          </select>

          <label className="flex items-center gap-2 rounded-xl border border-line bg-raised px-3 py-2">
            <Search size={14} className="text-muted" />
            <input
              value={query}
              onChange={(e) => update('q', e.target.value)}
              placeholder="搜索球队、编号或联赛"
              className="w-full bg-transparent text-xs text-slate-200 outline-none placeholder:text-slate-600"
            />
          </label>

          <select
            value={league}
            onChange={(e) => update('league', e.target.value)}
            className="rounded-xl border border-line bg-raised px-3 py-2 text-xs text-slate-200 outline-none focus:border-pitch/50"
          >
            <option value="all">全部联赛</option>
            {leagues.map(([div, name]) => (
              <option key={div} value={div}>{name}</option>
            ))}
          </select>

          <select
            value={status}
            onChange={(e) => update('status', e.target.value)}
            className="rounded-xl border border-line bg-raised px-3 py-2 text-xs text-slate-200 outline-none focus:border-pitch/50"
          >
            <option value="all">全部状态</option>
            <option value="predicted">有预测</option>
            <option value="settled">已结算</option>
            <option value="pending">待补赛果</option>
            <option value="skipped">已跳过</option>
          </select>

          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={valueOnly}
              onChange={(e) => update('value', e.target.checked ? '1' : null)}
              className="h-4 w-4 rounded border-line bg-raised accent-pitch"
            />
            <Filter size={13} />
            只看价值
          </label>
        </div>
      </Panel>

      {historyState.loading ? <Loading label="加载比赛" /> : null}
      {historyState.error ? <ErrorBox message={historyState.error} onRetry={historyState.reload} /> : null}

      {!historyState.loading && !historyState.error && (
        <>
          <div className="hidden overflow-hidden rounded-2xl border border-line md:block">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/70 text-[11px] text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">编号 / 联赛</th>
                  <th className="px-4 py-3 font-medium">对阵</th>
                  <th className="px-4 py-3 font-medium">开赛</th>
                  <th className="px-4 py-3 font-medium">HAD</th>
                  <th className="px-4 py-3 font-medium">比分预测</th>
                  <th className="px-4 py-3 font-medium">实际</th>
                  <th className="px-4 py-3 font-medium">价值</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {filtered.map((r) => {
                  const had = r.prediction?.markets.HAD
                  return (
                    <tr
                      key={r.id}
                      onClick={() => navigate(`/matches/${r.date}/${encodeURIComponent(r.id)}`)}
                      className="cursor-pointer bg-panel/40 transition hover:bg-raised/50"
                    >
                      <td className="px-4 py-3">
                        <div className="font-mono text-slate-300">{r.match_num}</div>
                        <div className="mt-0.5 text-[11px] text-muted">{r.league.name || r.league.div}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-200">{r.home.cn} vs {r.away.cn}</div>
                        {r.prediction_timing === 'post_kickoff' ? (
                          <div className="mt-0.5 text-[10px] text-amber">开赛后补跑，不计入命中率</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-muted">
                        {r.time ? r.time.slice(0, 5) : '—'}
                      </td>
                      <td className="w-44 px-4 py-3">
                        {had ? (
                          <div>
                            <ProbBar probs={had.probs} compact />
                            <div className="mt-1 text-[10px] text-muted">
                              预测 {optionShort(had.predicted)} · {pct(had.probs?.home)}/{pct(had.probs?.draw)}/{pct(had.probs?.away)}
                            </div>
                          </div>
                        ) : <span className="text-muted">—</span>}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {r.prediction?.markets.SCORE.predicted ?? '—'}
                      </td>
                      <td className="px-4 py-3">
                        {r.result ? (
                          <div>
                            <span className="font-mono text-sm text-slate-100">{r.result.ft}</span>
                            <span className="ml-2 inline-flex"><HitMark value={had?.hit} /></span>
                          </div>
                        ) : <span className="text-muted">待补</span>}
                      </td>
                      <td className="px-4 py-3">
                        {r.prediction?.value_bets[0] ? (
                          <ValueBadge edge={r.prediction.value_bets[0].edge} />
                        ) : <span className="text-muted">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={r.status === 'settled' ? 'green' : r.status === 'skipped' ? 'neutral' : 'blue'}>
                          {STATUS_LABELS[r.status]}
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="space-y-3 md:hidden">
            {filtered.map((r) => <MatchCard key={r.id} match={r} />)}
          </div>

          {filtered.length === 0 ? (
            <EmptyState title="没有符合条件的比赛" hint="试试切换日期、联赛或清空搜索。" />
          ) : null}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
            <span>显示 {filtered.length} / {records.length} 场</span>
            <Link to="/about" className="text-pitch hover:underline">数据与口径说明</Link>
          </div>
        </>
      )}
    </div>
  )
}
