import { Database, GitBranch, Info, RefreshCw, ShieldAlert, Trophy } from 'lucide-react'
import { Disclaimer, PageHeader, Panel, SectionTitle } from '../components/ui'

const DATA_SOURCES = [
  { name: '五大联赛', detail: 'football-data.co.uk 镜像 + understat xG', coverage: '英超 / 德甲 / 西甲 / 意甲 / 法甲' },
  { name: '欧战', detail: 'openfootball', coverage: '欧冠 / 欧罗巴 / 欧协联（EUR 合并模型）' },
  { name: 'tier2', detail: 'API-Football（Free）', coverage: '瑞超 / 挪超 / 芬超 / 巴甲' },
  { name: '竞彩赔率', detail: 'sporttery.cn 快照', coverage: 'HAD / HHAD / 比分 / 总进球 / 半全场' },
  { name: '手动赛果', detail: 'data/manual_results/results.csv', coverage: '所有竞彩联赛（自动源缺失时）' },
]

export function About() {
  return (
    <div>
      <PageHeader
        title="关于这个项目"
        subtitle="一个把足球预测研究管线搬到静态网站上的实验"
      />

      <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <Panel>
          <SectionTitle title="它是什么" />
          <div className="space-y-3 text-sm leading-relaxed text-slate-300">
            <p>
              本项目基于 Dixon-Coles 泊松模型、Elo 和 LightGBM 特征模型，计算竞彩足球
              胜平负、让球、比分、总进球、半全场的概率，并与官方赔率比对，输出价值信号。
            </p>
            <p>
              网站本身是静态的：预测、对账、导出都在本地完成，生成 JSON 后 push 到 GitHub，
              由 GitHub Pages 托管。页面不连接数据库，也不在请求时运行模型。
            </p>
            <p className="rounded-xl border border-line bg-raised/40 p-3 text-xs text-muted">
              这样做的原因：竞彩官网抓取和模型推理依赖本地网络与 42MB 模型文件，
              放在 GitHub Actions 里不稳定；静态站则零成本、可追溯、每次更新都是一个 commit。
            </p>
          </div>
        </Panel>

        <Panel>
          <SectionTitle title="模型混合链" />
          <div className="space-y-2">
            {[
              { icon: Trophy, name: 'Dixon-Coles', desc: '泊松比分、时间衰减、小样本收缩；输出比分矩阵' },
              { icon: GitBranch, name: 'Elo', desc: '第二意见，缓解 DC 过度自信' },
              { icon: Database, name: 'LightGBM', desc: '13 维滚动特征，第三意见' },
              { icon: RefreshCw, name: '去水市场', desc: '与市场隐含概率混合，压制虚假 edge' },
            ].map((item) => (
              <div key={item.name} className="flex items-start gap-3 rounded-xl border border-line bg-raised/40 p-3">
                <item.icon size={15} className="mt-0.5 shrink-0 text-pitch" />
                <div>
                  <div className="text-xs font-medium text-slate-200">{item.name}</div>
                  <div className="mt-0.5 text-[11px] text-muted">{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel className="mt-5">
        <SectionTitle title="数据来源与覆盖" hint="首版只展示已有模型的联赛；新联赛训练好后自动纳入" />
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-raised/70 text-[11px] text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">来源</th>
                <th className="px-3 py-2 font-medium">说明</th>
                <th className="px-3 py-2 font-medium">覆盖</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/70">
              {DATA_SOURCES.map((row) => (
                <tr key={row.name}>
                  <td className="px-3 py-2 text-slate-200">{row.name}</td>
                  <td className="px-3 py-2 text-muted">{row.detail}</td>
                  <td className="px-3 py-2 text-muted">{row.coverage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel>
          <SectionTitle title="每天怎么更新" />
          <ol className="space-y-3 text-xs text-muted">
            {[
              '抓取竞彩赔率快照：fetch-jingcai --online',
              '生成预测：predict（自动归档到 reports/archive）',
              '候选筛选：recommend',
              '赛后录赛果：编辑 data/manual_results/results.csv',
              '对账：reconcile --date YYYYMMDD --manual ...',
              '导出：export_web.py --check',
              '提交并推送：git push（GitHub Actions 自动发布 Pages）',
            ].map((step, index) => (
              <li key={step} className="flex gap-3">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-pitch/10 font-mono text-[10px] text-pitch">
                  {index + 1}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel>
          <SectionTitle title="已知限制" />
          <div className="space-y-2 text-xs leading-relaxed text-muted">
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-amber" />
              历史回测 ROI 为负（约 −3% ~ −9%），模型尚未稳定跑赢市场。
            </div>
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-amber" />
              早盘 edge 容易误报，应以临场前 1–2 小时快照为准。
            </div>
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-amber" />
              半全场需要半场比分；缺半场时该玩法不参与统计。
            </div>
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-amber" />
              无模型联赛只显示“未预测”，不会伪造命中率。
            </div>
            <div className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-amber" />
              开赛后补跑的预测会标注，且不计入命中率。
            </div>
          </div>
        </Panel>
      </div>

      <Panel className="mt-5 border-danger/20 bg-danger/5">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div>
            <div className="text-sm font-medium text-danger">重要声明</div>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              本站仅用于统计研究与学习，不构成任何投注建议、收益承诺或荐彩服务。
              竞彩综合返奖率约 73%，长期期望为负。请勿据此重仓真钱，更不要借贷投注。
              数据与模型可能存在错误、延迟或遗漏，请以官方信息为准。
            </p>
          </div>
        </div>
      </Panel>

      <div className="mt-5"><Disclaimer /></div>
    </div>
  )
}
