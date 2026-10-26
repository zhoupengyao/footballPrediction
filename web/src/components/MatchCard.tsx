import { Link } from 'react-router-dom'
import { ChevronRight, Clock, Star } from 'lucide-react'
import type { MatchRecord } from '../data/types'
import { formatDateTime, pct, STATUS_LABELS } from '../lib/format'
import { Badge, HitMark, ProbBar, ValueBadge, cx } from './ui'

export function MatchCard({ match }: { match: MatchRecord }) {
  const pred = match.prediction
  const had = pred?.markets.HAD
  const values = pred?.value_bets ?? []
  const isSettled = match.status === 'settled'
  const isSkipped = match.status === 'skipped'

  return (
    <Link
      to={`/matches/${match.date}/${encodeURIComponent(match.id)}`}
      className={cx(
        'group block rounded-2xl border border-line bg-panel/80 p-4 transition hover:border-pitch/40 hover:bg-raised/60',
        isSkipped && 'opacity-70',
      )}
    >
      <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
        <div className="flex items-center gap-2">
          <span className="font-mono text-slate-300">{match.match_num}</span>
          <span>{match.league.name || match.league.div || '未知联赛'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {values.length > 0 ? (
            <Badge tone="amber"><Star size={10} /> {values.length}</Badge>
          ) : null}
          <Badge tone={isSettled ? 'green' : isSkipped ? 'neutral' : 'blue'}>
            {STATUS_LABELS[match.status]}
          </Badge>
        </div>
      </div>

      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-100">
            {match.home.cn} <span className="px-1 text-slate-500">vs</span> {match.away.cn}
          </div>
          <div className="mt-1 flex items-center gap-1 text-[11px] text-muted">
            <Clock size={11} />
            {formatDateTime(match.kickoff || `${match.date}T${match.time || '00:00'}`)}
          </div>
        </div>
        {isSettled && match.result ? (
          <div className="shrink-0 text-right">
            <div className="font-mono text-lg font-bold tracking-wider text-slate-100">
              {match.result.ft}
            </div>
            <div className="text-[10px] text-muted">
              半场 {match.result.ht || '—'}
            </div>
          </div>
        ) : (
          <ChevronRight size={16} className="mt-1 shrink-0 text-slate-600 group-hover:text-pitch" />
        )}
      </div>

      {!isSkipped && had ? (
        <div className="mt-3">
          <ProbBar probs={had.probs} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted">
              预测 {pct(had.probs?.home)} / {pct(had.probs?.draw)} / {pct(had.probs?.away)}
            </span>
            {isSettled ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                HAD <HitMark value={had.hit} />
              </span>
            ) : null}
            {values[0] ? <ValueBadge edge={values[0].edge} ev={values[0].ev} /> : null}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-[11px] text-muted">
          {match.skip_reason || '未预测'}
        </div>
      )}
    </Link>
  )
}
