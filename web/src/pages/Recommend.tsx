import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Coins, ListFilter, Sparkles } from 'lucide-react'
import { getManifest, getPerformance, getRecommendations } from '../data/client'
import type { RecommendationItem, Risk } from '../data/types'
import { useAsync } from '../lib/useAsync'
import { formatDateTime, pct, RISK_LABELS, signedPct } from '../lib/format'
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

const RISKS: Risk[] = ['conservative', 'balanced', 'aggressive']

function ItemTable({ items, showReason = true }: { items: RecommendationItem[]; showReason?: boolean }) {
  if (items.length === 0) {
    return <EmptyState title="暂无记录" hint="当前风险档位没有满足条件的候选或观察项。" />
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-left text-xs">
        <thead className="bg-raised/70 text-[11px] text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">编号</th>
            <th className="px-3 py-2 font-medium">联赛</th>
            <th className="px-3 py-2 font-medium">对阵</th>
            <th className="px-3 py-2 font-medium">玩法</th>
            <th className="px-3 py-2 font-medium">选项</th>
            <th className="px-3 py-2 font-medium">赔率</th>
            <th className="px-3 py-2 font-medium">模型</th>
            <th className="px-3 py-2 font-medium">edge</th>
            <th className="px-3 py-2 font-medium">EV</th>
            <th className="px-3 py-2 font-medium">仓位</th>
            {showReason ? <th className="px-3 py-2 font-medium">理由</th> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">
          {items.map((item, index) => (
            <tr key={`${item.match_num}-${item.market}-${item.option}-${index}`}>
              <td className="px-3 py-2 font-mono text-slate-300">{item.match_num}</td>
              <td className="px-3 py-2 text-muted">{item.league}</td>
              <td className="px-3 py-2 text-slate-200">{item.home_cn} vs {item.away_cn}</td>
              <td className="px-3 py-2 text-muted">{item.market}</td>
              <td className="px-3 py-2">{item.option}</td>
              <td className="px-3 py-2 font-mono">{item.odds.toFixed(2)}</td>
              <td className="px-3 py-2 font-mono">{pct(item.model_prob)}</td>
              <td className="px-3 py-2 font-mono text-amber">{pct(item.edge)}</td>
              <td className="px-3 py-2 font-mono">{pct(item.ev)}</td>
              <td className="px-3 py-2 font-mono">{item.stake_pct ? pct(item.stake_pct, 2) : '—'}</td>
              {showReason ? <td className="max-w-64 px-3 py-2 text-[11px] text-muted">{item.reason}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Recommend() {
  const [params, setParams] = useSearchParams()
  const manifestState = useAsync(getManifest, [])
  const manifest = manifestState.data
  const dates = [...(manifest?.dates ?? [])].sort((a, b) => b.date.localeCompare(a.date))
  const selectedDate = params.get('date') || manifest?.latest_prediction_date || manifest?.latest_match_date || ''
  const risk = (params.get('risk') as Risk) || 'conservative'
  const recState = useAsync(
    () => (selectedDate ? getRecommendations(selectedDate) : Promise.resolve(null)),
    [selectedDate],
  )
  const perfState = useAsync(getPerformance, [])
  const payload = recState.data
  const result = payload?.risks?.[risk]
  const perf = perfState.data

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  if (manifestState.loading) return <Loading label="加载推荐" />
  if (manifestState.error) return <ErrorBox message={manifestState.error} onRetry={manifestState.reload} />

  return (
    <div>
      <PageHeader
        title="纸面候选与台账"
        subtitle="风险筛选，不是盈利推荐。历史回测 ROI 为负，请先用台账长期验证。"
        actions={
          <select
            value={selectedDate}
            onChange={(e) => update('date', e.target.value)}
            className="rounded-xl border border-line bg-raised px-3 py-2 text-xs text-slate-200 outline-none focus:border-pitch/50"
          >
            {dates.map((d) => (
              <option key={d.date} value={d.date}>{d.date}</option>
            ))}
          </select>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="累计价值注" value={perf?.overall.value.n ?? 0} hint="已结算" tone="amber" />
        <StatCard label="命中率" value={pct(perf?.overall.value.hit_rate)} tone="green" />
        <StatCard label="单位注盈亏" value={perf ? signedPct(perf.overall.value.roi) : '—'} tone={(perf?.overall.value.roi ?? 0) < 0 ? 'red' : 'green'} hint="ROI" />
        <StatCard label="累计仓位盈亏" value={perf ? signedPct(perf.overall.value.pnl_pct, 2) : '—'} hint="占资金比例" />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        {RISKS.map((r) => (
          <button
            key={r}
            onClick={() => update('risk', r)}
            className={`rounded-xl border px-3 py-2 text-xs transition ${
              risk === r
                ? 'border-pitch/40 bg-pitch/10 text-pitch'
                : 'border-line bg-panel text-slate-400 hover:text-slate-200'
            }`}
          >
            {RISK_LABELS[r]}
            <span className="ml-2 text-[10px] opacity-70">
              {payload?.risks?.[r]?.recommendations.length ?? 0} 注
            </span>
          </button>
        ))}
        <span className="ml-auto text-[11px] text-muted">
          档位说明：稳健只筛 E0 胜平负；均衡/进取放宽阈值。
        </span>
      </div>

      {recState.loading ? <Loading label="加载候选" /> : null}
      {recState.error ? <ErrorBox message={recState.error} onRetry={recState.reload} /> : null}

      {result ? (
        <>
          <div className="mt-5 grid gap-5 lg:grid-cols-[1.6fr_1fr]">
            <Panel>
              <SectionTitle
                title={`${RISK_LABELS[risk]}档候选`}
                hint={`合计建议仓位 ${pct(result.total_stake_pct, 2)} · 生成于 ${formatDateTime(payload?.generated_at)}`}
                action={<Badge tone="amber"><Sparkles size={10} /> {result.recommendations.length} 注</Badge>}
              />
              {result.recommendations.length ? (
                <div className="space-y-3">
                  {result.recommendations.map((item, index) => (
                    <div key={`${item.match_num}-${item.option}-${index}`} className="rounded-xl border border-line bg-raised/40 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-sm font-medium text-slate-100">
                          {item.home_cn} vs {item.away_cn}
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge tone="amber">{item.tier}★</Badge>
                          <span className="text-[11px] text-muted">{item.match_num} · {item.league}</span>
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted">
                        <span>{item.market} · {item.option}</span>
                        <span>赔率 <b className="font-mono text-slate-200">{item.odds.toFixed(2)}</b></span>
                        <span>edge <b className="font-mono text-amber">{pct(item.edge)}</b></span>
                        <span>EV <b className="font-mono text-amber">{pct(item.ev)}</b></span>
                        <span>仓位 <b className="font-mono text-slate-200">{pct(item.stake_pct, 2)}</b></span>
                      </div>
                      <div className="mt-2 text-[11px] leading-relaxed text-muted">{item.reason}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="当前档位无候选注" hint="未发现满足条件的价值机会；观察项仍然保留。" />
              )}
            </Panel>

            <Panel>
              <SectionTitle title="规则速览" hint="可在 config/settings.yaml 调整" />
              <div className="space-y-2 text-xs text-muted">
                <div className="flex items-start gap-2"><ListFilter size={13} className="mt-0.5 text-pitch" />
                  默认只筛胜平负（HAD）单关；让球只观察。
                </div>
                <div className="flex items-start gap-2"><Coins size={13} className="mt-0.5 text-amber" />
                  1/4 Kelly，单注上限 2%，日总仓位上限按档位缩放。
                </div>
                <div className="flex items-start gap-2"><AlertTriangle size={13} className="mt-0.5 text-danger" />
                  历史回测 ROI 为负，候选注仅作为纸面跟踪。
                </div>
              </div>
              <div className="mt-4 rounded-xl border border-line bg-raised/40 p-3 text-[11px] text-muted">
                本页候选由最新预测按三档风险重算；若存在当天的官方 recommend 报告，会附带在 JSON 的 official 字段中。
              </div>
            </Panel>
          </div>

          <Panel className="mt-5">
            <SectionTitle title="观察项（不下注）" hint={`${result.observations.length} 条；有 edge 但未通过联赛/玩法/赔率/EV 过滤`} />
            <ItemTable items={result.observations} />
          </Panel>
        </>
      ) : null}

      <Panel className="mt-5">
        <SectionTitle title="投注台账" hint="来自 data/processed/bet_ledger.parquet；只有真正结算的价值注会进入" />
        {perfState.loading ? <Loading label="加载台账" /> : null}
        {perf?.ledger.length ? (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/70 text-[11px] text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">日期</th>
                  <th className="px-3 py-2 font-medium">编号</th>
                  <th className="px-3 py-2 font-medium">对阵</th>
                  <th className="px-3 py-2 font-medium">玩法</th>
                  <th className="px-3 py-2 font-medium">选项</th>
                  <th className="px-3 py-2 font-medium">赔率</th>
                  <th className="px-3 py-2 font-medium">edge</th>
                  <th className="px-3 py-2 font-medium">命中</th>
                  <th className="px-3 py-2 font-medium">盈亏</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {[...perf.ledger].reverse().slice(0, 100).map((row, index) => (
                  <tr key={`${row.date}-${row.match_num}-${row.market}-${row.option}-${index}`}>
                    <td className="px-3 py-2 font-mono text-muted">{row.date}</td>
                    <td className="px-3 py-2 font-mono text-slate-300">{row.match_num}</td>
                    <td className="px-3 py-2 text-slate-200">{row.home_cn} vs {row.away_cn}</td>
                    <td className="px-3 py-2 text-muted">{row.market}</td>
                    <td className="px-3 py-2">{row.option}</td>
                    <td className="px-3 py-2 font-mono">{row.odds?.toFixed(2) ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-amber">{pct(row.edge)}</td>
                    <td className="px-3 py-2">{row.hit ? <span className="text-pitch">✓</span> : <span className="text-danger">✗</span>}</td>
                    <td className={`px-3 py-2 font-mono ${(row.pnl_unit ?? 0) >= 0 ? 'text-pitch' : 'text-danger'}`}>
                      {row.pnl_unit === null ? '—' : `${row.pnl_unit > 0 ? '+' : ''}${row.pnl_unit.toFixed(2)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="台账还是空的" hint="先录入赛果并运行 reconcile；只有已结算的价值注会被写入。" />
        )}
      </Panel>

      <div className="mt-5"><Disclaimer /></div>
    </div>
  )
}
