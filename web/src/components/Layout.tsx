import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  CalendarDays,
  Home,
  Info,
  Sparkles,
  Trophy,
} from 'lucide-react'
import { cx } from './ui'

const NAV = [
  { to: '/', label: '总览', icon: Home, end: true },
  { to: '/matches', label: '比赛', icon: CalendarDays },
  { to: '/recommend', label: '推荐', icon: Sparkles },
  { to: '/analysis', label: '分析', icon: Activity },
  { to: '/performance', label: '回测', icon: BarChart3 },
  { to: '/about', label: '关于', icon: Info },
]

export function Layout() {
  const location = useLocation()

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div className="min-h-screen bg-ink text-slate-200">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-panel/80 px-4 py-5 backdrop-blur lg:flex">
        <NavLink to="/" className="flex items-center gap-3 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-pitch/15 text-pitch">
            <Trophy size={19} />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-50">竞彩预测实验室</div>
            <div className="text-[10px] text-muted">研究用途 · 非投注建议</div>
          </div>
        </NavLink>

        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cx(
                  'flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition',
                  isActive
                    ? 'bg-pitch/10 text-pitch'
                    : 'text-slate-400 hover:bg-raised hover:text-slate-200',
                )
              }
            >
              <item.icon size={16} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-xl border border-line bg-raised/60 p-3 text-[11px] leading-relaxed text-muted">
          数据由本地管线生成后 push 到 GitHub。命中率仅统计赛前预测且已结算的场次。
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-ink/85 px-4 backdrop-blur lg:hidden">
        <NavLink to="/" className="flex items-center gap-2">
          <Trophy size={18} className="text-pitch" />
          <span className="text-sm font-semibold text-slate-100">竞彩预测实验室</span>
        </NavLink>
        <span className="text-[10px] text-muted">研究用途</span>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 pb-24 pt-5 sm:px-6 lg:pb-10 lg:pl-64 lg:pr-8">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-panel/95 backdrop-blur lg:hidden">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cx(
                'flex flex-1 flex-col items-center gap-1 py-2 text-[10px]',
                isActive ? 'text-pitch' : 'text-slate-500',
              )
            }
          >
            <item.icon size={18} />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
