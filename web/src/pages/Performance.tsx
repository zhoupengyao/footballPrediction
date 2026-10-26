import { useMemo, useState } from 'react'
import { BarChart3, Database, Target, TrendingDown, TrendingUp } from 'lucide-react'
import { getBacktest, getBacktests, getPerformance } from '../data/client'
import type { BacktestDetail, BacktestIndexItem, MarketStat } from '../data/types'
import { useAsync } from '../lib/useAsync'
import { MARKET_LABELS, num, pct, signedPct } from '../lib/format'
import { CalibrationChart, DailyLineChart, EquityChart, ValueCumulativeChart } from '../components/charts'
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

function AccuracyBar({ stat }: { stat: MarketStat | undefined }) {
  const value = stat?.accuracy ?? null
  return (
    <div>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted">样本 {stat?.n ?? 0}</span>
        <span className="font-mono text-slate-200">{pct(value)}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-line">
        <div className="h-full bg-pitch" style={{ width: `${(value ?? 0) * 100}%` }} />
      </div>
    </div>
  )
}

function BacktestMetrics({ bt }: { bt: BacktestDetail }) {
  const o = bt.overall
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard label="样本场次" value={o.n.toLocaleString()} hint={`基准 ${pct(o.baseline_home)}`} />
      <StatCard label="准确率" value={pct(o.accuracy)} tone="green" hint={`对数损失 ${num(o.log_loss, 3)}`} />
      <StatCard label="Brier" value={num(o.brier, 4)} hint={`ECE ${num(o.ece, 4)}`} />
      <StatCard
        label="ROI"
        value={o.has_odds && o.betting ? signedPct(o.betting.roi) : '—'}
        tone={o.has_odds && (o.betting?.roi ?? 0) < 0 ? 'red' : 'green'}
        hint={o.has_odds && o.betting ? `${o.betting.n_bets.toLocaleString()} 注` : '无历史赔率'}
      />
    </div>
  )
}

export function Performance() {
  const perfState = useAsync(getPerformance, [])
  const indexState = useAsync(getBacktests, [])
  const backtests = indexState.data ?? []
  const [btId, setBtId] = useState('')
  const activeId = btId || backtests[0]?.id || ''
  const btState = useAsync(
    () => (activeId ? getBacktest(activeId) : Promise.resolve(null)),
    [activeId],
  )
  const perf = perfState.data
  const bt = btState.data

  const daily = useMemo(() => [...(perf?.daily ?? [])].sort((a, b) => a.date.localeCompare(b.date)), [perf])
  const hadDaily = useMemo(
    () => daily.map((d) => ({ date: d.date, value: d.markets.HAD.accuracy })).filter((d) => d.value !== null),
    [daily],
  )
  const cumulative = useMemo(() => {
    let sum = 0
    return daily.map((d) => {
      sum += d.value?.pnl_unit ?? 0
      return { date: d.date, value: Number(sum.toFixed(2)) }
    })
  }, [daily])

  if (perfState.loading) return <Loading label="加载表现数据" />
  if (perfState.error) return <ErrorBox message={perfState.error} onRetry={perfState.reload} />
  if (!perf) return <EmptyState title="暂无表现数据" />

  const markets = perf.overall.markets
  const hasSettled = perf.overall.stats_settled > 0

  return (
    <div>
      <PageHeader
        title="回测与表现"
        subtitle="实盘纸面命中率、价值注 ROI，以及历史 walk-forward 回测"
        actions={
          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral"><Database size={11} /> 统计样本 {perf.overall.stats_settled}</Badge>
            <Badge tone={perf.overall.value.roi !== null && perf.overall.value.roi < 0 ? 'red' : 'green'}>
              <Target size={11} /> ROI {signedPct(perf.overall.value.roi)}
            </Badge>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="累计比赛" value={perf.overall.total} hint={`已预测 ${perf.overall.predicted}`} />
        <StatCard label="已结算" value={perf.overall.settled} tone="green" hint={`待补 ${perf.overall.pending}`} />
        <StatCard label="HAD 命中率" value={pct(markets.HAD?.accuracy)} tone="green" hint={`${markets.HAD?.hits ?? 0}/${markets.HAD?.n ?? 0}`} />
        <StatCard label="价值注 ROI" value={signedPct(perf.overall.value.roi)} tone={(perf.overall.value.roi ?? 0) < 0 ? 'red' : 'green'} hint={`${perf.overall.value.n} 注`} />
      </div>

      {!hasSettled ? (
        <div className="mt-5">
          <EmptyState
            title="还没有已结算的赛前预测"
            hint="去 data/manual_results/results.csv 录入全场和半场比分，运行 reconcile + export 后这里会出现统计。"
          />
        </div>
      ) : null}

      <Panel className="mt-5">
        <SectionTitle title="五种玩法命中率" hint={`只统计赛前预测且已结算的 ${perf.overall.stats_settled} 场`} />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            'HAD', 'HHAD', 'SCORE_TOP1', 'SCORE_TOP3', 'TOTAL_GOALS', 'HALF_FULL',
            'HAD_DC', 'HAD_ELO', 'HAD_ML',
          ].map((key) => (
            <div key={key} className="rounded-xl border border-line bg-raised/40 p-3">
              <div className="mb-2 text-xs font-medium text-slate-200">{MARKET_LABELS[key] ?? key}</div>
              <AccuracyBar stat={markets[key]} />
            </div>
          ))}
        </div>
      </Panel>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel>
          <SectionTitle title="每日 HAD 命中率" hint="仅显示有结算样本的日期" />
          {hadDaily.length ? <DailyLineChart data={hadDaily} label="HAD 命中率" /> : <EmptyState title="暂无每日命中率" />}
        </Panel>
        <Panel>
          <SectionTitle title="价值注累计盈亏" hint="单位注（1 注 = 1 单位）" />
          {cumulative.length ? <ValueCumulativeChart data={cumulative} /> : <EmptyState title="暂无价值注结算" />}
        </Panel>
      </div>

      <Panel className="mt-5">
        <SectionTitle title="分联赛表现" hint="样本较少的联赛请谨慎解读" />
        {perf.by_league.length ? (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/70 text-[11px] text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">联赛</th>
                  <th className="px-3 py-2 font-medium">预测</th>
                  <th className="px-3 py-2 font-medium">已结算</th>
                  <th className="px-3 py-2 font-medium">HAD</th>
                  <th className="px-3 py-2 font-medium">HHAD</th>
                  <th className="px-3 py-2 font-medium">比分 Top1</th>
                  <th className="px-3 py-2 font-medium">总进球</th>
                  <th className="px-3 py-2 font-medium">半全场</th>
                  <th className="px-3 py-2 font-medium">价值 ROI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {perf.by_league.map((row) => (
                  <tr key={row.div}>
                    <td className="px-3 py-2 text-slate-200">{row.name || row.div}</td>
                    <td className="px-3 py-2 font-mono text-muted">{row.predicted}</td>
                    <td className="px-3 py-2 font-mono text-muted">{row.settled}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.markets.HAD?.accuracy)}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.markets.HHAD?.accuracy)}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.markets.SCORE_TOP1?.accuracy)}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.markets.TOTAL_GOALS?.accuracy)}</td>
                    <td className="px-3 py-2 font-mono">{pct(row.markets.HALF_FULL?.accuracy)}</td>
                    <td className={`px-3 py-2 font-mono ${(row.value.roi ?? 0) < 0 ? 'text-danger' : 'text-pitch'}`}>
                      {row.value.n ? signedPct(row.value.roi) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="暂无分联赛数据" />}
      </Panel>

      <div className="mt-8">
        <PageHeader
          title="历史 walk-forward 回测"
          subtitle="滚动训练、逐场预测；ROI 使用含水位的历史赔率"
          actions={
            <select
              value={activeId}
              onChange={(e) => setBtId(e.target.value)}
              className="rounded-xl border border-line bg-raised px-3 py-2 text-xs text-slate-200 outline-none focus:border-pitch/50"
            >
              {backtests.map((b: BacktestIndexItem) => (
                <option key={b.id} value={b.id}>
                  {b.label} · {b.generated_at?.slice(0, 10)} · {b.n?.toLocaleString() ?? '—'} 场
                </option>
              ))}
            </select>
          }
        />

        {indexState.loading ? <Loading label="加载回测" /> : null}
        {indexState.error ? <ErrorBox message={indexState.error} onRetry={indexState.reload} /> : null}
        {!indexState.loading && backtests.length === 0 ? (
          <EmptyState title="暂无回测报告" hint="运行 python -m src.cli backtest 后再导出。" />
        ) : null}

        {btState.loading ? <Loading label="加载回测详情" /> : null}
        {btState.error ? <ErrorBox message={btState.error} onRetry={btState.reload} /> : null}
        {bt ? (
          <>
            <BacktestMetrics bt={bt} />
            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <Panel>
                <SectionTitle title="校准曲线" hint="越接近虚线校准越好；模型通常偏自信" />
                <CalibrationChart points={bt.overall.calibration} />
              </Panel>
              <Panel>
                <SectionTitle title="资金曲线" hint={bt.overall.has_odds ? '按 EV > 阈值逐场平注' : '该回测没有历史赔率'} />
                {bt.overall.has_odds && bt.equity_curve.length ? (
                  <EquityChart points={bt.equity_curve} />
                ) : <EmptyState title="无赔率，无法计算资金曲线" />}
              </Panel>
            </div>
            <Panel className="mt-5">
              <SectionTitle title="回测分联赛" hint="对数损失 < 1.0986 优于随机；Brier < 0.667 优于随机" />
              <div className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-raised/70 text-[11px] text-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">联赛</th>
                      <th className="px-3 py-2 font-medium">场次</th>
                      <th className="px-3 py-2 font-medium">准确率</th>
                      <th className="px-3 py-2 font-medium">基准</th>
                      <th className="px-3 py-2 font-medium">对数损失</th>
                      <th className="px-3 py-2 font-medium">Brier</th>
                      <th className="px-3 py-2 font-medium">ROI</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/70">
                    {Object.entries(bt.per_league).map(([div, m]) => (
                      <tr key={div}>
                        <td className="px-3 py-2 text-slate-200">{div}</td>
                        <td className="px-3 py-2 font-mono text-muted">{m.n?.toLocaleString()}</td>
                        <td className="px-3 py-2 font-mono">{pct(m.accuracy)}</td>
                        <td className="px-3 py-2 font-mono text-muted">{pct(m.baseline_home)}</td>
                        <td className="px-3 py-2 font-mono">{num(m.log_loss, 4)}</td>
                        <td className="px-3 py-2 font-mono">{num(m.brier, 4)}</td>
                        <td className={`px-3 py-2 font-mono ${(m.betting?.roi ?? 0) < 0 ? 'text-danger' : 'text-pitch'}`}>
                          {m.betting ? signedPct(m.betting.roi) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        ) : null}
      </div>

      <div className="mt-6 flex items-start gap-2 text-xs text-muted">
        {perf.overall.value.roi !== null && perf.overall.value.roi < 0
          ? <TrendingDown size={14} className="mt-0.5 text-danger" />
          : <TrendingUp size={14} className="mt-0.5 text-pitch" />}
        <span>{perf.note}</span>
      </div>
      <div className="mt-3"><Disclaimer /></div>
    </div>
  )
}
