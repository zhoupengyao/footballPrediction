import { Routes, Route, Link } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Matches } from './pages/Matches'
import { MatchDetail } from './pages/MatchDetail'
import { Recommend } from './pages/Recommend'
import { Performance } from './pages/Performance'
import { Analysis } from './pages/Analysis'
import { About } from './pages/About'

function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="font-mono text-6xl font-bold text-line">404</div>
      <h1 className="mt-4 text-lg font-semibold text-slate-200">页面不存在</h1>
      <p className="mt-2 text-sm text-muted">可能链接过期，或数据尚未导出。</p>
      <Link to="/" className="mt-5 rounded-xl bg-pitch/15 px-4 py-2 text-sm text-pitch hover:bg-pitch/20">
        返回总览
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="matches" element={<Matches />} />
        <Route path="matches/:date/:id" element={<MatchDetail />} />
        <Route path="recommend" element={<Recommend />} />
        <Route path="analysis" element={<Analysis />} />
        <Route path="performance" element={<Performance />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
