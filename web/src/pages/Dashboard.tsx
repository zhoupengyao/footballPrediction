import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BrainCircuit,
  CalendarDays,
  CircleDollarSign,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react'
import { getHistory, getManifest, getPerformance, getRecommendations } from '../data/client'
import type { MatchRecord } from '../data/types'
import { useAsync } from '../lib/useAsync'
import { formatDateTime, isStale, pct, RISK_LABELS, signedPct } from '../lib/format'
import { MatchCard } from '../components/MatchCard'
import {
  Badge,
  Disclaimer,
  EmptyState,
  ErrorBox,
  Loading,
  PageHeader,
  Panel,
  SectionTitle,
  StatCard,
} from '../components/ui'

function sortForHome(matches: MatchRecord[]): MatchRecord[] {
  return [...matches]
    .filter((m) => m.status !== 'skipped')
    .sort((a, b) => {
      const av = a.prediction?.value_bets.length ?? 0
      const bv = b.prediction?.value_bets.length ?? 0
      if (av !== bv) return bv - av
      return String(a.kickoff || '').localeCompare(String(b.kickoff || ''))
    })
}

export function Dashboard() {
  const manifestState = useAsync(getManifest, [])
  const manifest = manifestState.data
  const latest = manifest?.latest_match_date ?? null
  const latestPred = manifest?.latest_prediction_date ?? null
  const historyState = useAsync(
    () => (latest ? getHistory(latest) : Promise.resolve([] as MatchRecord[])),
    [latest],
  )
  const perfState = useAsync(getPerformance, [])
  const recState = useAsync(
    () => (latestPred ? getRecommendations(latestPred) : Promise.resolve(null)),
    [latestPred],
  )

  if (manifestState.loading) return <Loading label="加载站点数据" />
  if (manifestState.error) {
    return <ErrorBox message={manifestState.error} onRetry={manifestState.reload} />
  }
  if (!manifest) return <EmptyState title="暂无数据" hint="请先在本地运行导出脚本。" />

  const matches = sortForHome(historyState.data ?? [])
  const perf = perfState.data
  const rec = recState.data
  const conservative = rec?.risks.conservative
  const hadAcc = perf?.overall.markets.HAD.accuracy ?? null
  const roi = perf?.overall.value.roi ?? null
  const stale = isStale(latest)

  return (
    <div>
      <PageHeader
        title={manifest.site.name}
        subtitle={manifest.site.tagline}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={stale ? 'amber' : 'green'}>
              <CalendarDays size={11} />
              最新数据 {latest ?? '—'}
            </Badge>
            <Badge tone="neutral">更新于 {formatDateTime(manifest.generated_at)}</Badge>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="最新一期场次" value={manifest.dates.at(-1)?.total ?? 0} hint={latest ?? '—'} />
        <StatCard label="可预测" value={manifest.dates.at(-1)?.predicted ?? 0} tone="blue" />
        <StatCard label="已结算" value={perf?.overall.settled ?? 0} tone="green" hint={`统计样本 ${perf?.overall.stats_settled ?? 0}`} />
        <StatCard label="价值选项" value={perf?.overall.value.n ?? 0} tone="amber" hint={`命中率 ${pct(perf?.overall.value.hit_rate)}`} />
        <StatCard label="HAD 命中率" value={pct(hadAcc)} tone="green" hint={`样本 ${perf?.overall.markets.HAD.n ?? 0}`} />
        <StatCard
          label="价值注 ROI"
          value={roi === null ? '—' : signedPct(roi)}
          tone={roi !== null && roi < 0 ? 'red' : 'amber'}
          hint={`${perf?.overall.value.hits ?? 0}/${perf?.overall.value.n ?? 0} 命中`}
        />
      </div>

      {stale ? (
        <div className="mt-4 rounded-xl border border-amber/20 bg-amber/5 px-4 py-3 text-xs text-amber/90">
          最新预测日期是 {latest}，不是今天。请先运行 <code className="font-mono">fetch-jingcai</code>、
          <code className="font-mono">predict</code>，再导出并 push。
        </div>
      ) : null}

      <div className="mt-6 grid gap-5 lg:grid-cols-[1.65fr_1fr]">
        <Panel>
          <SectionTitle
            title="最新预测"
            hint="优先展示含价值选项的场次；点击查看五种玩法详情"
            action={
              <Link to={`/matches?date=${latest ?? ''}`} className="inline-flex items-center gap-1 text-xs text-pitch hover:underline">
                全部比赛 <ArrowRight size={13} />
              </Link>
            }
          />
          {historyState.loading ? <Loading label="加载比赛" /> : null}
          {historyState.error ? <ErrorBox message={historyState.error} onRetry={historyState.reload} /> : null}
          {!historyState.loading && matches.length === 0 ? (
            <EmptyState title="今天还没有可预测场次" hint="可能快照过期，或本期已全部开赛。" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {matches.slice(0, 6).map((m) => <MatchCard key={m.id} match={m} />)}
            </div>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel>
            <SectionTitle title="模型混合链" hint="概率越往右越保守，价值判断在混合后进行" />
            <div className="space-y-2 text-sm">
              {[
                { icon: BrainCircuit, label: 'Dixon-Coles', desc: '泊松比分 + 时间衰减 + 小样本收缩' },
                { icon: TrendingUp, label: 'Elo', desc: '第二意见，缓解过度自信' },
                { icon: Target, label: 'LightGBM', desc: '13 维滚动特征，第三意见' },
                { icon: CircleDollarSign, label: '去水市场', desc: '与市场隐含概率混合，压制虚假 edge' },
              ].map((step, index) => (
                <div key={step.label} className="flex items-start gap-3 rounded-xl border border-line bg-raised/40 p-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-pitch/10 text-pitch">
                    <step.icon size={14} />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-200">
                      {index + 1}. {step.label}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted">{step.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <SectionTitle
              title="纸面候选"
              hint={conservative ? `${RISK_LABELS.conservative}档 · ${conservative.recommendations.length} 注` : '暂无推荐数据'}
              action={<Link to="/recommend" className="text-xs text-pitch hover:underline">查看明细</Link>}
            />
            {recState.loading ? <Loading label="加载推荐" /> : null}
            {conservative && conservative.recommendations.length > 0 ? (
              <div className="space-y-2">
                {conservative.recommendations.slice(0, 3).map((item) => (
                  <div key={`${item.match_num}-${item.market}-${item.option}`} className="rounded-xl border border-line bg-raised/40 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-medium text-slate-200">
                        {item.home_cn} vs {item.away_cn}
                      </div>
                      <Badge tone="amber"><Sparkles size={10} /> {item.tier}★</Badge>
                    </div>
                    <div className="mt-1 flex items-center justify-between text-[11px] text-muted">
                      <span>{item.match_num} · {item.league}</span>
                      <span className="text-amber">
                        edge +{pct(item.edge)} · EV +{pct(item.ev)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="今日无候选注" hint="未发现满足稳健档条件的 E0 胜平负机会。" />
            )}
          </Panel>
        </div>
      </div>

      <div className="mt-6">
        <Disclaimer />
      </div>
    </div>
  )
}
