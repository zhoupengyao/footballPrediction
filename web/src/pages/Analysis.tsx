import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Activity, AlertTriangle, BarChart3, Target, TrendingDown, TrendingUp } from 'lucide-react'
import { getAnalysis } from '../data/client'
import type {
  AnalysisBin,
  AnalysisCase,
  AnalysisData,
  AnalysisMarket,
  AnalysisMarketKey,
  ScoreHitDetail,
} from '../data/types'
import { useAsync } from '../lib/useAsync'
import { formatDateTime, num, pct, signedPct } from '../lib/format'
import {
  CorrectWrongChart,
  DailyLineChart,
  ReliabilityChart,
} from '../components/charts'
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

const TABS: Array<{ key: AnalysisMarketKey; label: string }> = [
  { key: 'HAD', label: '胜平负' },
  { key: 'HHAD', label: '让球' },
  { key: 'SCORE', label: '比分' },
  { key: 'TOTAL_GOALS', label: '总进球' },
  { key: 'HALF_FULL', label: '半全场' },
]

const OPTION_LABELS: Record<string, string> = {
  home: '主胜',
  draw: '平',
  away: '客胜',
}

function fmtCi(low: number | null, high: number | null): string {
  if (low === null || high === null) return '—'
  return `${pct(low, 0)}–${pct(high, 0)}`
}

function gapTone(gap: number | null): string {
  if (gap === null) return 'text-muted'
  return gap < -0.05 ? 'text-danger' : gap > 0.05 ? 'text-pitch' : 'text-slate-300'
}

function GapValue({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted">—</span>
  return (
    <span className={gapTone(value)}>
      {value > 0 ? '+' : ''}{(value * 100).toFixed(1)}%
    </span>
  )
}

function CalibrationTable({ bins }: { bins: AnalysisBin[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-left text-xs">
        <thead className="bg-raised/70 text-[11px] text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">概率区间</th>
            <th className="px-3 py-2 font-medium">样本</th>
            <th className="px-3 py-2 font-medium">命中</th>
            <th className="px-3 py-2 font-medium">未命中</th>
            <th className="px-3 py-2 font-medium">命中率</th>
            <th className="px-3 py-2 font-medium">平均预测</th>
            <th className="px-3 py-2 font-medium">偏差</th>
            <th className="px-3 py-2 font-medium">95% CI</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">
          {bins.map((b) => (
            <tr key={b.label} className={b.n === 0 ? 'opacity-45' : ''}>
              <td className="px-3 py-2 font-mono text-slate-300">{b.label}</td>
              <td className="px-3 py-2 font-mono">{b.n}</td>
              <td className="px-3 py-2 font-mono text-pitch">{b.n ? b.hits : '—'}</td>
              <td className="px-3 py-2 font-mono text-danger">{b.n ? b.misses : '—'}</td>
              <td className="px-3 py-2 font-mono">{pct(b.accuracy)}</td>
              <td className="px-3 py-2 font-mono text-muted">{pct(b.avg_pred)}</td>
              <td className="px-3 py-2 font-mono"><GapValue value={b.gap} /></td>
              <td className="px-3 py-2 font-mono text-muted">{fmtCi(b.ci_low, b.ci_high)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RankBars({ market }: { market: AnalysisMarket }) {
  const rank = market.actual_rank
  if (!rank) return null
  const total = Object.values(rank).reduce((a, b) => a + b, 0)
  if (!total) return null
  const rows = [
    { key: '1', label: '第 1 选择', tone: 'bg-pitch' },
    { key: '2', label: '第 2 选择', tone: 'bg-amber' },
    { key: '3', label: '第 3 选择', tone: 'bg-sky-500' },
    { key: 'other', label: '其他', tone: 'bg-slate-600' },
  ]
  return (
    <div className="space-y-2.5">
      {rows.map((row) => {
        const n = rank[row.key] ?? 0
        return (
          <div key={row.key}>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-muted">{row.label}</span>
              <span className="font-mono text-slate-300">{n} 场 · {pct(n / total, 0)}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-line">
              <div className={`h-full ${row.tone}`} style={{ width: `${(n / total) * 100}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ConfusionTable({ market }: { market: AnalysisMarket }) {
  const confusion = market.confusion
  if (!confusion) return null
  const keys = ['home', 'draw', 'away']
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-left text-xs">
        <thead className="bg-raised/70 text-[11px] text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">预测 \ 实际</th>
            {keys.map((k) => <th key={k} className="px-3 py-2 font-medium">{OPTION_LABELS[k]}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">
          {keys.map((pred) => (
            <tr key={pred}>
              <td className="px-3 py-2 text-slate-300">{OPTION_LABELS[pred]}</td>
              {keys.map((actual) => {
                const n = confusion[pred]?.[actual] ?? 0
                return (
                  <td
                    key={actual}
                    className={`px-3 py-2 font-mono ${pred === actual ? 'text-pitch' : n ? 'text-danger' : 'text-muted'}`}
                  >
                    {n}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CaseList({
  title,
  items,
  mode,
}: {
  title: string
  items: AnalysisCase[]
  mode: 'wrong' | 'hit'
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-200">
        {mode === 'wrong'
          ? <TrendingDown size={13} className="text-danger" />
          : <TrendingUp size={13} className="text-pitch" />}
        {title}
        <span className="text-[10px] text-muted">（{items.length}）</span>
      </div>
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line px-3 py-6 text-center text-[11px] text-muted">
          暂无记录
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={`${item.date}-${item.match_num}-${item.predicted}`} className="rounded-xl border border-line bg-raised/40 p-3">
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <span className="font-mono text-slate-300">{item.date} {item.match_num}</span>
                <span className="font-mono text-slate-300">{pct(item.confidence)}</span>
              </div>
              <div className="mt-1 text-xs text-slate-200">{item.home} vs {item.away}</div>
              <div className="mt-1 text-[11px] text-muted">
                预测 {item.predicted} · 实际 {item.actual} · 比分 {item.result ?? '—'}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ValueBinTable({
  title,
  rows,
}: {
  title: string
  rows: Array<{ label: string; n: number; hits: number; hit_rate: number | null; pnl_unit: number; roi: number | null }>
}) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-slate-200">{title}</div>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-raised/70 text-[11px] text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">区间</th>
              <th className="px-3 py-2 font-medium">注数</th>
              <th className="px-3 py-2 font-medium">命中</th>
              <th className="px-3 py-2 font-medium">命中率</th>
              <th className="px-3 py-2 font-medium">盈亏</th>
              <th className="px-3 py-2 font-medium">ROI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/70">
            {rows.map((row) => (
              <tr key={row.label} className={row.n === 0 ? 'opacity-45' : ''}>
                <td className="px-3 py-2 font-mono text-slate-300">{row.label}</td>
                <td className="px-3 py-2 font-mono">{row.n}</td>
                <td className="px-3 py-2 font-mono text-pitch">{row.n ? row.hits : '—'}</td>
                <td className="px-3 py-2 font-mono">{pct(row.hit_rate)}</td>
                <td className={`px-3 py-2 font-mono ${row.pnl_unit < 0 ? 'text-danger' : 'text-pitch'}`}>
                  {row.n ? `${row.pnl_unit > 0 ? '+' : ''}${row.pnl_unit.toFixed(2)}` : '—'}
                </td>
                <td className={`px-3 py-2 font-mono ${(row.roi ?? 0) < 0 ? 'text-danger' : 'text-pitch'}`}>
                  {row.n ? signedPct(row.roi) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ScoreHitPanel({ detail, matchTotal }: { detail: ScoreHitDetail; matchTotal: number }) {
  const maxBin = Math.max(1, ...detail.prob_bins.map((b) => b.n))
  return (
    <Panel className="mt-5">
      <SectionTitle
        title="比分命中分析"
        hint="3 个预测比分作为一个组合：实际比分命中任意一个，这场就算命中"
        action={<Badge tone="green">命中 {detail.n}/{matchTotal} 场</Badge>}
      />
      {detail.n === 0 ? (
        <EmptyState title="暂无命中比分" hint="当前样本里还没有三个预测比分命中实际的场次。" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="命中场次"
              value={`${detail.n}/${matchTotal}`}
              tone="green"
              hint={`命中率 ${pct(detail.n / Math.max(matchTotal, 1))}`}
            />
            <StatCard label="平均命中比分概率" value={pct(detail.avg_actual_prob, 2)} hint="命中比分自己的概率" />
            <StatCard label="中位数" value={pct(detail.median_actual_prob, 2)} />
            <StatCard
              label="概率范围"
              value={`${pct(detail.min_actual_prob, 1)}–${pct(detail.max_actual_prob, 1)}`}
            />
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-medium text-slate-200">命中比分概率分布</div>
            <div className="space-y-2">
              {detail.prob_bins.map((b) => (
                <div key={b.label} className="flex items-center gap-3">
                  <span className="w-16 text-right font-mono text-[11px] text-muted">{b.label}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                    <div className="h-full bg-pitch" style={{ width: `${(b.n / maxBin) * 100}%` }} />
                  </div>
                  <span className="w-8 font-mono text-[11px] text-slate-300">{b.n}</span>
                </div>
              ))}
            </div>
            <div className="mt-2 text-[11px] text-muted">
              只统计命中的 {detail.n} 场；概率是命中那个比分自己的模型概率，不拆分第几个预测。
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-medium text-slate-200">命中明细</div>
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full text-left text-xs">
                <thead className="bg-raised/70 text-[11px] text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">日期 / 编号</th>
                    <th className="px-3 py-2 font-medium">对阵</th>
                    <th className="px-3 py-2 font-medium">三个预测比分</th>
                    <th className="px-3 py-2 font-medium">实际比分</th>
                    <th className="px-3 py-2 font-medium">命中比分概率</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/70">
                  {detail.cases.map((item, index) => (
                    <tr key={`${item.date}-${item.match_num}-${index}`}>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-muted">{item.date} {item.match_num}</td>
                      <td className="px-3 py-2 text-slate-200">{item.home} vs {item.away}</td>
                      <td className="px-3 py-2 font-mono text-slate-300">{item.top3.join(' / ')}</td>
                      <td className="px-3 py-2 font-mono text-pitch">{item.actual}</td>
                      <td className="px-3 py-2 font-mono text-slate-100">{pct(item.p_actual, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </Panel>
  )
}

export function Analysis() {
  const state = useAsync(getAnalysis, [])
  const [params, setParams] = useSearchParams()
  const requested = params.get('market') as AnalysisMarketKey | null
  const marketKey = TABS.some((tab) => tab.key === requested)
    ? (requested as AnalysisMarketKey)
    : 'HAD'
  const setMarket = (key: AnalysisMarketKey) => {
    const next = new URLSearchParams(params)
    next.set('market', key)
    setParams(next, { replace: true })
  }
  const analysis = state.data
  const market = analysis?.markets[marketKey]
  const scoreDetail = marketKey === 'SCORE' ? market?.hit_detail : null
  const topScoreBin = scoreDetail && scoreDetail.n > 0
    ? [...scoreDetail.prob_bins].sort((a, b) => b.n - a.n)[0]
    : null

  const dailyHAD = useMemo(
    () => (analysis?.daily ?? [])
      .filter((d) => d.n > 0)
      .map((d) => ({ date: d.date, value: d.accuracy })),
    [analysis],
  )

  if (state.loading) return <Loading label="加载命中分析" />
  if (state.error) return <ErrorBox message={state.error} onRetry={state.reload} />
  if (!analysis || !market) return <EmptyState title="暂无分析数据" hint="先录入赛果并导出站点数据。" />

  const sample = analysis.sample
  const smallSample = sample.pre_match_settled < 100

  return (
    <div>
      <PageHeader
        title="命中分析"
        subtitle="统计命中了多少，并检查模型给出的概率是否可信"
        actions={
          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral"><Activity size={11} /> 赛前样本 {sample.pre_match_settled} 场</Badge>
            <Badge tone="neutral">{sample.dates} 个日期</Badge>
            <Badge tone="amber">排除赛后补跑 {sample.excluded_post_kickoff} 场</Badge>
          </div>
        }
      />

      {smallSample ? (
        <div className="mb-5 rounded-xl border border-amber/20 bg-amber/5 px-4 py-3 text-xs leading-relaxed text-amber/90">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>
              当前赛前样本只有 {sample.pre_match_settled} 场，分箱后每个区间可能只有几场。
              所有结论仅作探索，不建议据此优化阈值或重仓。表内已标注样本量和 95% 置信区间。
            </span>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {scoreDetail ? (
          <>
            <StatCard
              label="比分命中"
              value={`${market.hits}/${market.n}`}
              tone="green"
              hint={`命中率 ${pct(market.accuracy)}；任意一个比分中即算`}
            />
            <StatCard label="平均命中比分概率" value={pct(scoreDetail.avg_actual_prob, 2)} hint="命中比分自己的概率" />
            <StatCard label="中位数" value={pct(scoreDetail.median_actual_prob, 2)} />
            <StatCard
              label="概率范围"
              value={`${pct(scoreDetail.min_actual_prob, 1)}–${pct(scoreDetail.max_actual_prob, 1)}`}
            />
            <StatCard
              label="命中最多区间"
              value={topScoreBin?.label ?? '—'}
              tone="amber"
              hint={topScoreBin ? `${topScoreBin.n} 场` : ''}
            />
            <StatCard label="样本场次" value={market.n} hint="每场 3 个预测比分" />
          </>
        ) : (
          <>
            <StatCard label="样本场次" value={market.n} hint={`${market.label} 已结算`} />
            <StatCard label="命中" value={`${market.hits}/${market.n}`} tone="green" hint={`命中率 ${pct(market.accuracy)}`} />
            <StatCard label="平均置信度" value={pct(market.avg_confidence)} hint="Top-pick 概率均值" />
            <StatCard label="校准误差 ECE" value={pct(market.ece)} tone={(market.ece ?? 0) > 0.1 ? 'red' : 'green'} hint="越小越好" />
            <StatCard label="Brier" value={num(market.brier, 3)} hint="多分类；越低越好" />
            <StatCard label="对数损失" value={num(market.log_loss, 3)} hint="越低越好" />
          </>
        )}
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setMarket(tab.key)}
            className={`rounded-xl border px-3 py-2 text-xs transition ${
              marketKey === tab.key
                ? 'border-pitch/40 bg-pitch/10 text-pitch'
                : 'border-line bg-panel text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {marketKey === 'SCORE' && market.hit_detail ? (
        <ScoreHitPanel detail={market.hit_detail} matchTotal={market.n} />
      ) : null}

      {marketKey !== 'SCORE' ? (
        <>
      <Panel className="mt-5">
        <SectionTitle
          title="概率区间校准"
          hint="偏差 = 实际命中率 − 平均预测概率；负值代表模型过度自信"
          action={<Badge tone="neutral">n={market.n}</Badge>}
        />
        <CalibrationTable bins={market.bins} />
        <div className="mt-3 text-[11px] leading-relaxed text-muted">
          解释：如果 50–60% 区间的实际命中率明显低于 50–60%，说明模型在这一档过度自信；如果高于区间，则偏保守。样本量小的区间不要单独下结论。
        </div>
      </Panel>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel>
          <SectionTitle title="可靠性曲线" hint="点越接近虚线，概率越可信；点大小=样本量" />
          <ReliabilityChart bins={market.bins} />
        </Panel>
        <Panel>
          <SectionTitle title="正确 vs 错误分布" hint="同一概率区间里，命中和未命中各多少" />
          <CorrectWrongChart bins={market.bins} />
        </Panel>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        {market.actual_rank ? (
          <Panel>
            <SectionTitle title="实际结果在预测中的排名" hint="第 1 选择=命中；第 2/3 选择=接近但未中" />
            <RankBars market={market} />
          </Panel>
        ) : null}
        {market.confusion ? (
          <Panel>
            <SectionTitle title="混淆矩阵" hint="行=预测，列=实际；对角线为命中" />
            <ConfusionTable market={market} />
          </Panel>
        ) : null}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel>
          <CaseList
            title={`高置信翻车（≥${pct(market.high_conf_threshold, 0)}）`}
            items={market.high_conf_wrong}
            mode="wrong"
          />
        </Panel>
        <Panel>
          <CaseList
            title={`低置信命中（≤${pct(market.low_conf_threshold, 0)}）`}
            items={market.low_conf_hit}
            mode="hit"
          />
        </Panel>
      </div>
        </>
      ) : null}

      <Panel className="mt-5">
        <SectionTitle title="模型层对比" hint="DC / Elo / LightGBM 各自只统计有该层预测的场次" />
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-raised/70 text-[11px] text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">模型层</th>
                <th className="px-3 py-2 font-medium">样本</th>
                <th className="px-3 py-2 font-medium">命中</th>
                <th className="px-3 py-2 font-medium">准确率</th>
                <th className="px-3 py-2 font-medium">平均置信度</th>
                <th className="px-3 py-2 font-medium">ECE</th>
                <th className="px-3 py-2 font-medium">Brier</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/70">
              {Object.entries(analysis.layers).map(([name, layer]) => (
                <tr key={name}>
                  <td className="px-3 py-2 text-slate-200">{name}</td>
                  <td className="px-3 py-2 font-mono text-muted">{layer.n}</td>
                  <td className="px-3 py-2 font-mono text-pitch">{layer.hits}</td>
                  <td className="px-3 py-2 font-mono">{pct(layer.accuracy)}</td>
                  <td className="px-3 py-2 font-mono">{pct(layer.avg_confidence)}</td>
                  <td className="px-3 py-2 font-mono">{pct(layer.ece)}</td>
                  <td className="px-3 py-2 font-mono">{num(layer.brier, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-[11px] text-muted">
          模型层样本通常少于 HAD 全量，因为部分历史报告只有 DC 层。对比时先看样本量。
        </div>
      </Panel>

      <Panel className="mt-5">
        <SectionTitle
          title="价值注：edge 与赔率"
          hint="命中率不等于盈利；这里同时看命中率、单位注盈亏和 ROI"
          action={<Badge tone={(analysis.value.roi ?? 0) < 0 ? 'red' : 'green'}>ROI {signedPct(analysis.value.roi)}</Badge>}
        />
        <div className="mb-4 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-xl border border-line bg-raised/40 p-3">
            <div className="text-[11px] text-muted">注数</div>
            <div className="mt-1 font-mono text-xl text-slate-100">{analysis.value.n}</div>
          </div>
          <div className="rounded-xl border border-line bg-raised/40 p-3">
            <div className="text-[11px] text-muted">命中率</div>
            <div className="mt-1 font-mono text-xl text-pitch">{pct(analysis.value.hit_rate)}</div>
          </div>
          <div className="rounded-xl border border-line bg-raised/40 p-3">
            <div className="text-[11px] text-muted">单位注盈亏</div>
            <div className={`mt-1 font-mono text-xl ${analysis.value.pnl_unit < 0 ? 'text-danger' : 'text-pitch'}`}>
              {analysis.value.pnl_unit > 0 ? '+' : ''}{analysis.value.pnl_unit.toFixed(2)}
            </div>
          </div>
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <ValueBinTable title="按 edge 分组" rows={analysis.value.by_edge} />
          <ValueBinTable title="按赔率分组" rows={analysis.value.by_odds} />
        </div>
      </Panel>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel>
          <SectionTitle title="分联赛命中率" hint="样本少的联赛只作参考" />
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/70 text-[11px] text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">联赛</th>
                  <th className="px-3 py-2 font-medium">样本</th>
                  <th className="px-3 py-2 font-medium">命中</th>
                  <th className="px-3 py-2 font-medium">命中率</th>
                  <th className="px-3 py-2 font-medium">平均置信度</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {analysis.by_league.map((row) => (
                  <tr key={row.div}>
                    <td className="px-3 py-2 text-slate-200">{row.name || row.div}</td>
                    <td className="px-3 py-2 font-mono text-muted">{row.n}</td>
                    <td className="px-3 py-2 font-mono text-pitch">{row.hits}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.accuracy)}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.avg_confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel>
          <SectionTitle title="每日 HAD 命中率" hint="观察模型是否随时间漂移" />
          {dailyHAD.length ? <DailyLineChart data={dailyHAD} label="HAD 命中率" /> : <EmptyState title="暂无每日数据" />}
        </Panel>
      </div>

      <Panel className="mt-5">
        <SectionTitle title="口径与限制" />
        <div className="space-y-2 text-xs leading-relaxed text-muted">
          <div>· 只统计 `settled` 且 `prediction_timing=pre_match`；开赛后补跑不计入。</div>
          <div>· 除比分外，Top-pick 置信度 = 模型最终选择那个选项的概率；命中率 = 该选择实际发生的比例。</div>
          <div>· 比分：3 个预测比分作为一个整体，实际比分命中任意一个，这场就算命中（一场只算 1 次）；不做逐条拆分，也不做组合概率校准。</div>
          <div>· 命中比分概率 = 命中场次里，实际比分自己的模型概率；用来看命中的比分集中在哪个概率区间。</div>
          <div>· 偏差为负表示“过度自信”；ECE 是所有区间偏差的加权平均。</div>
          <div>· Brier / 对数损失只对拥有完整概率分布的玩法计算（HAD/HHAD/总进球/模型层）；比分和半全场不计算 Brier。</div>
          <div>· 样本量小的区间已标注 n 和 95% Wilson 置信区间；不要用 50 场样本反推稳定策略。</div>
          <div>· {analysis.note}</div>
        </div>
      </Panel>

      <div className="mt-5 text-[11px] text-muted">导出时间：{formatDateTime(analysis.generated_at)}</div>
      <div className="mt-3"><Disclaimer /></div>
    </div>
  )
}
