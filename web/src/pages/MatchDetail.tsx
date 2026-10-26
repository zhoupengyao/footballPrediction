import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Clock, Info, MapPin, Star } from 'lucide-react'
import { getHistory } from '../data/client'
import type { MatchRecord, OptionKey } from '../data/types'
import { useAsync } from '../lib/useAsync'
import {
  formatDateTime,
  hhadLine,
  MARKET_LABELS,
  num,
  optionLabel,
  optionShort,
  pct,
  STATUS_LABELS,
  TIMING_LABELS,
} from '../lib/format'
import { CompareHADChart, TTGChart } from '../components/charts'
import {
  Badge,
  Disclaimer,
  EmptyState,
  ErrorBox,
  HitMark,
  Loading,
  Panel,
  ProbBar,
  SectionTitle,
  ValueBadge,
} from '../components/ui'

const OPTIONS: OptionKey[] = ['home', 'draw', 'away']

function findMatch(records: MatchRecord[], id: string): MatchRecord | undefined {
  const decoded = decodeURIComponent(id)
  return records.find((r) => r.id === decoded || r.match_num === decoded)
}

export function MatchDetail() {
  const { date = '', id = '' } = useParams()
  const state = useAsync(
    () => (date ? getHistory(date) : Promise.resolve([] as MatchRecord[])),
    [date],
  )
  const match = state.data ? findMatch(state.data, id) : undefined

  if (state.loading) return <Loading label="加载比赛详情" />
  if (state.error) return <ErrorBox message={state.error} onRetry={state.reload} />
  if (!match) {
    return (
      <EmptyState
        title="没有找到这场比赛"
        hint="可能是链接过期，或该日期的数据尚未导出。"
      />
    )
  }

  const pred = match.prediction
  const had = pred?.markets.HAD
  const hhad = pred?.markets.HHAD
  const score = pred?.markets.SCORE
  const ttg = pred?.markets.TOTAL_GOALS
  const hf = pred?.markets.HALF_FULL
  const result = match.result

  return (
    <div>
      <Link to={`/matches?date=${match.date}`} className="mb-4 inline-flex items-center gap-1 text-xs text-muted hover:text-pitch">
        <ArrowLeft size={13} /> 返回比赛列表
      </Link>

      <Panel className="mb-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
              <Badge tone="neutral">{match.match_num}</Badge>
              <span>{match.league.name || match.league.div}</span>
              <span className="inline-flex items-center gap-1"><Clock size={11} />{formatDateTime(match.kickoff)}</span>
              {match.league.code ? <span className="inline-flex items-center gap-1"><MapPin size={11} />{match.league.code}</span> : null}
            </div>
            <h1 className="mt-3 text-xl font-semibold text-slate-50 sm:text-2xl">
              {match.home.cn} <span className="px-1 text-slate-500">vs</span> {match.away.cn}
            </h1>
            <div className="mt-1 text-xs text-muted">
              {match.home.matched || '—'} / {match.away.matched || '—'}
            </div>
          </div>

          <div className="flex flex-col items-start gap-2 sm:items-end">
            <Badge tone={match.status === 'settled' ? 'green' : match.status === 'skipped' ? 'neutral' : 'blue'}>
              {STATUS_LABELS[match.status]}
            </Badge>
            {pred ? (
              <Badge tone={pred.timing === 'pre_match' ? 'green' : 'amber'}>
                {TIMING_LABELS[pred.timing]}
              </Badge>
            ) : null}
            {result ? (
              <div className="text-right">
                <div className="font-mono text-2xl font-bold text-slate-50">{result.ft}</div>
                <div className="text-[11px] text-muted">半场 {result.ht || '—'}</div>
              </div>
            ) : null}
          </div>
        </div>
      </Panel>

      {match.status === 'skipped' ? (
        <Panel className="mb-5 border-amber/20 bg-amber/5">
          <div className="text-sm text-amber">本场未预测：{match.skip_reason || '未知原因'}</div>
          <div className="mt-1 text-xs text-muted">
            未预测场次不进入命中率统计。若需要预测该联赛，请先扩展训练数据与队名映射。
          </div>
        </Panel>
      ) : null}

      {pred && pred.timing === 'post_kickoff' ? (
        <Panel className="mb-5 border-amber/20 bg-amber/5">
          <div className="text-sm text-amber">这份预测生成于开赛之后，仅作展示，不计入命中率。</div>
          <div className="mt-1 text-xs text-muted">生成时间：{formatDateTime(pred.generated_at)}</div>
        </Panel>
      ) : null}

      {pred && !result ? (
        <Panel className="mb-5 border-sky-400/20 bg-sky-400/5">
          <div className="text-sm text-sky-300">赛果待补：预测已生成，但本地还没有这场比赛的实际比分。</div>
          <div className="mt-1 text-xs text-muted">
            可在 <code className="font-mono">data/manual_results/results.csv</code> 录入全场和半场比分，再运行 reconcile。
          </div>
        </Panel>
      ) : null}

      {result ? (
        <Panel className="mb-5">
          <SectionTitle title="实际结果与玩法命中" hint="✓ 命中 / ✗ 未命中 / — 无数据或无法结算" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'HAD', hit: had?.hit, actual: optionLabel(result.had) },
              { label: '让球', hit: hhad?.hit, actual: `${hhadLine(hhad?.line)} · ${optionLabel(result.hhad)}` },
              { label: '比分 Top1', hit: score?.top1_hit, actual: result.ft },
              { label: '比分 Top3', hit: score?.top3_hit, actual: result.ft },
              { label: '总进球', hit: ttg?.hit, actual: `${result.total_goals ?? '—'} 球` },
              { label: '半全场', hit: hf?.hit, actual: result.half_full || '缺半场比分' },
            ].map((item) => (
              <div key={item.label} className="rounded-xl border border-line bg-raised/40 p-3">
                <div className="flex items-center justify-between text-[11px] text-muted">
                  <span>{item.label}</span>
                  <HitMark value={item.hit} />
                </div>
                <div className="mt-1 text-sm text-slate-100">{item.actual}</div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      {pred ? (
        <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
          <Panel>
            <SectionTitle title="胜平负 HAD" hint="模型概率、竞彩赔率、去水隐含与最终混合" />
            <ProbBar probs={had?.probs ?? null} />
            <div className="mt-4 overflow-hidden rounded-xl border border-line">
              <table className="w-full text-left text-xs">
                <thead className="bg-raised/70 text-[11px] text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">选项</th>
                    <th className="px-3 py-2 font-medium">模型</th>
                    <th className="px-3 py-2 font-medium">赔率</th>
                    <th className="px-3 py-2 font-medium">隐含</th>
                    <th className="px-3 py-2 font-medium">最终</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/70">
                  {OPTIONS.map((key) => (
                    <tr key={key}>
                      <td className="px-3 py-2 text-slate-300">{optionLabel(key)}</td>
                      <td className="px-3 py-2 font-mono">{pct(had?.probs?.[key])}</td>
                      <td className="px-3 py-2 font-mono">{num(had?.odds?.[key])}</td>
                      <td className="px-3 py-2 font-mono text-muted">{pct(had?.implied?.[key])}</td>
                      <td className="px-3 py-2 font-mono text-pitch">{pct(had?.blended?.[key])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 text-xs text-muted">
              预测选项：<span className="text-slate-200">{optionLabel(had?.predicted)}</span>
              {had?.hit !== null ? <span className="ml-2">命中 <HitMark value={had?.hit} /></span> : null}
            </div>
          </Panel>

          <Panel>
            <SectionTitle title="各层概率对比" hint="DC → Elo → ML → 最终混合，越往右越保守" />
            <CompareHADChart
              rows={[
                { label: '最终', probs: had?.probs ?? null },
                { label: 'DC', probs: pred.model_layers.DC?.probs ?? null },
                { label: 'Elo', probs: pred.model_layers.Elo?.probs ?? null },
                { label: 'ML', probs: pred.model_layers.ML?.probs ?? null },
                { label: '市场', probs: had?.implied ?? null },
              ]}
            />
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
              {Object.entries(pred.model_layers).map(([name, layer]) => (
                <div key={name} className="rounded-lg border border-line bg-raised/40 p-2">
                  <div className="text-muted">{name}</div>
                  <div className="mt-1 text-slate-200">{optionShort(layer.predicted)}</div>
                  <HitMark value={layer.hit} />
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <SectionTitle title="让球胜平负 HHAD" hint={hhad?.available ? `让球线 ${hhadLine(hhad.line)}` : '本场无让球数据'} />
            {hhad?.available ? (
              <>
                <ProbBar probs={hhad.probs ?? null} />
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  {OPTIONS.map((key) => (
                    <div key={key} className="rounded-lg border border-line bg-raised/40 p-2">
                      <div className="text-[11px] text-muted">{optionLabel(key)}</div>
                      <div className="mt-1 font-mono text-slate-100">{pct(hhad.probs?.[key])}</div>
                      <div className="text-[10px] text-muted">赔率 {num(hhad.odds?.[key])}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 text-xs text-muted">
                  预测 {optionLabel(hhad.predicted)} · 实际 {optionLabel(result?.hhad)}
                  <span className="ml-2"><HitMark value={hhad.hit} /></span>
                </div>
              </>
            ) : <EmptyState title="无让球数据" />}
          </Panel>

          <Panel>
            <SectionTitle title="比分概率" hint="精确比分 Top3；归并桶不参与命中判定" />
            {score?.top.length ? (
              <div className="grid grid-cols-3 gap-2">
                {score.top.map((item, index) => (
                  <div key={item.score} className="rounded-xl border border-line bg-raised/40 p-3 text-center">
                    <div className="text-[10px] text-muted">Top{index + 1}</div>
                    <div className="mt-1 font-mono text-xl font-semibold text-slate-100">{item.score}</div>
                    <div className="mt-1 text-[11px] text-muted">{pct(item.prob)}</div>
                    {result?.ft === item.score ? <Badge tone="green" className="mt-2">命中</Badge> : null}
                  </div>
                ))}
              </div>
            ) : <EmptyState title="无比分数据" />}
          </Panel>

          <Panel>
            <SectionTitle title="总进球分布" hint={`预测 ${ttg?.predicted ?? '—'} 球；实际 ${result?.total_goals ?? '待补'}`} />
            {ttg?.available ? <TTGChart probs={ttg.probs} /> : <EmptyState title="无总进球数据" />}
            <div className="mt-2 flex items-center gap-2 text-xs text-muted">
              命中 <HitMark value={ttg?.hit} />
            </div>
          </Panel>

          <Panel>
            <SectionTitle title="半全场" hint="需要半场比分才能结算；缺半场时显示“无法结算”" />
            {hf?.available ? (
              <div className="space-y-2">
                {hf.top.map((item, index) => (
                  <div key={item.label} className="flex items-center gap-3">
                    <span className="w-4 text-[10px] text-muted">{index + 1}</span>
                    <div className="flex-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-200">{item.label}</span>
                        <span className="font-mono text-muted">{pct(item.prob)}</span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
                        <div className="h-full bg-pitch" style={{ width: `${(item.prob ?? 0) * 100}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
                <div className="mt-3 text-xs text-muted">
                  预测 {hf.predicted} · 实际 {hf.actual || '缺半场比分'}
                  <span className="ml-2"><HitMark value={hf.hit} /></span>
                </div>
              </div>
            ) : <EmptyState title="无半全场数据" />}
          </Panel>
        </div>
      ) : null}

      {pred?.value_bets.length ? (
        <Panel className="mt-5">
          <SectionTitle title="价值选项" hint="edge = 模型概率 − 去水隐含概率；仓位为 1/4 Kelly 建议" />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/70 text-[11px] text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">玩法</th>
                  <th className="px-3 py-2 font-medium">选项</th>
                  <th className="px-3 py-2 font-medium">赔率</th>
                  <th className="px-3 py-2 font-medium">模型</th>
                  <th className="px-3 py-2 font-medium">隐含</th>
                  <th className="px-3 py-2 font-medium">edge</th>
                  <th className="px-3 py-2 font-medium">EV</th>
                  <th className="px-3 py-2 font-medium">仓位</th>
                  <th className="px-3 py-2 font-medium">结果</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {pred.value_bets.map((b, i) => (
                  <tr key={`${b.market}-${b.option}-${i}`}>
                    <td className="px-3 py-2 text-slate-300">{MARKET_LABELS[b.market] ?? b.market}</td>
                    <td className="px-3 py-2">{b.option_cn}</td>
                    <td className="px-3 py-2 font-mono">{num(b.odds)}</td>
                    <td className="px-3 py-2 font-mono">{pct(b.model_prob)}</td>
                    <td className="px-3 py-2 font-mono text-muted">{pct(b.implied_prob)}</td>
                    <td className="px-3 py-2 font-mono text-amber">{pct(b.edge)}</td>
                    <td className="px-3 py-2 font-mono">{pct(b.ev)}</td>
                    <td className="px-3 py-2 font-mono">{pct(b.stake_pct, 2)}</td>
                    <td className="px-3 py-2">
                      {b.hit === null ? <span className="text-muted">待结算</span> : (
                        <span className="inline-flex items-center gap-1">
                          <HitMark value={b.hit} />
                          <span className={b.pnl_unit && b.pnl_unit > 0 ? 'text-pitch' : 'text-danger'}>
                            {b.pnl_unit === null ? '—' : `${b.pnl_unit > 0 ? '+' : ''}${b.pnl_unit.toFixed(2)}`}
                          </span>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <Panel>
          <SectionTitle title="数据来源" hint="每次预测都保留来源文件，便于追溯" />
          <div className="space-y-2 text-xs text-muted">
            <div>报告：<span className="font-mono text-slate-300">{pred?.source ?? '—'}</span></div>
            <div>生成时间：{formatDateTime(pred?.generated_at)}</div>
            <div>模型：<span className="font-mono text-slate-300">{pred?.model ?? '—'}</span></div>
            <div>队名置信：{pred?.confidence.home ?? '—'} / {pred?.confidence.away ?? '—'}</div>
          </div>
        </Panel>
        <Panel>
          <SectionTitle title="说明" />
          <div className="space-y-2 text-xs leading-relaxed text-muted">
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-pitch" />
              命中率只统计赛前预测且已结算的场次；开赛后补跑不计入。
            </div>
            <div className="flex gap-2"><Star size={13} className="mt-0.5 shrink-0 text-amber" />
              价值选项是统计信号，不是投注指令；历史回测 ROI 为负。
            </div>
          </div>
        </Panel>
      </div>

      <div className="mt-5"><Disclaimer /></div>
    </div>
  )
}
