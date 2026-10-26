import type { ReactNode } from 'react'
import { Check, Loader2, Minus, X } from 'lucide-react'
import type { Probs } from '../data/types'
import { pct } from '../lib/format'

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function Panel({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cx('rounded-2xl border border-line bg-panel/90 p-5 shadow-panel', className)}>
      {children}
    </div>
  )
}

export function SectionTitle({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'default' | 'green' | 'amber' | 'red' | 'blue'
}) {
  const tones: Record<string, string> = {
    default: 'text-slate-100',
    green: 'text-pitch',
    amber: 'text-amber',
    red: 'text-danger',
    blue: 'text-sky-400',
  }
  return (
    <div className="rounded-2xl border border-line bg-panel/90 p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('mt-1 font-mono text-2xl font-semibold tracking-tight', tones[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-muted">{hint}</div> : null}
    </div>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue'
  className?: string
}) {
  const tones: Record<string, string> = {
    neutral: 'border-line bg-raised text-slate-300',
    green: 'border-pitch/30 bg-pitch/10 text-pitch',
    amber: 'border-amber/30 bg-amber/10 text-amber',
    red: 'border-danger/30 bg-danger/10 text-danger',
    blue: 'border-sky-400/30 bg-sky-400/10 text-sky-300',
  }
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', tones[tone], className)}>
      {children}
    </span>
  )
}

export function ProbBar({ probs, compact = false }: { probs: Probs | null; compact?: boolean }) {
  if (!probs) {
    return <div className="text-xs text-muted">暂无概率</div>
  }
  const home = probs.home ?? 0
  const draw = probs.draw ?? 0
  const away = probs.away ?? 0
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-line">
        <div className="bg-pitch" style={{ width: `${home * 100}%` }} />
        <div className="bg-slate-500" style={{ width: `${draw * 100}%` }} />
        <div className="bg-sky-500" style={{ width: `${away * 100}%` }} />
      </div>
      {!compact ? (
        <div className="mt-1.5 grid grid-cols-3 gap-1 text-[11px]">
          <span className="text-pitch">胜 {pct(probs.home)}</span>
          <span className="text-center text-slate-400">平 {pct(probs.draw)}</span>
          <span className="text-right text-sky-400">负 {pct(probs.away)}</span>
        </div>
      ) : null}
    </div>
  )
}

export function HitMark({ value, showDash = true }: { value: boolean | null | undefined; showDash?: boolean }) {
  if (value === true) return <Check size={15} className="text-pitch" aria-label="命中" />
  if (value === false) return <X size={15} className="text-danger" aria-label="未命中" />
  return showDash ? <Minus size={15} className="text-slate-600" aria-label="未结算" /> : null
}

export function ValueBadge({ edge, ev }: { edge: number | null; ev?: number | null }) {
  if (edge === null || edge === undefined) return null
  const tone = edge >= 0.1 ? 'amber' : edge >= 0.05 ? 'green' : 'neutral'
  return (
    <Badge tone={tone}>
      edge +{pct(edge)}
      {ev !== undefined && ev !== null ? <span className="opacity-70"> · EV +{pct(ev)}</span> : null}
    </Badge>
  )
}

export function Loading({ label = '加载中' }: { label?: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Panel className="border-danger/20 bg-danger/5">
      <div className="text-sm text-danger">{message}</div>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="mt-3 rounded-lg border border-line px-3 py-1.5 text-xs text-slate-200 hover:bg-raised"
        >
          重试
        </button>
      ) : null}
    </Panel>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-panel/50 px-5 py-10 text-center">
      <div className="text-sm font-medium text-slate-300">{title}</div>
      {hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  )
}

export function Disclaimer() {
  return (
    <div className="rounded-xl border border-amber/20 bg-amber/5 px-4 py-3 text-xs leading-relaxed text-amber/90">
      ⚠️ 本页面仅用于统计研究与学习，不构成任何投注建议。竞彩返奖率约 73%，历史回测 ROI 为负。
    </div>
  )
}
