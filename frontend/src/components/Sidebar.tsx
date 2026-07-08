import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  FileText,
  Wallet,
  ScrollText,
  Activity,
  Settings,
  Eye,
} from 'lucide-react'
import qstudioLogoSrc from '../assets/qstudio-logo.jpg'

const links = [
  { to: '/dashboard', icon: LayoutDashboard, label: '仪表盘' },
  { to: '/strategies', icon: TrendingUp, label: '策略管理' },
  { to: '/monitoring', icon: Eye, label: '策略监测' },
  { to: '/orders', icon: FileText, label: '交易记录' },
  { to: '/accounts', icon: Wallet, label: '账户管理' },
  { to: '/api-logs', icon: Activity, label: 'API日志' },
  { to: '/logs', icon: ScrollText, label: '操作日志' },
]

const bottomLinks = [
  { to: '/settings', icon: Settings, label: '系统设置' },
]

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-[260px] z-30 flex flex-col">
      <div className="absolute inset-0 bg-[#050711] border-r border-[rgba(0,212,170,0.06)]" />

      <div className="relative z-10 flex flex-col h-full">
        {/* Logo */}
        <div className="h-16 flex items-center gap-3 px-5 glow-line">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-[#00D4AA]/20 to-[#00D4AA]/5 border border-[#00D4AA]/15">
            <img src={qstudioLogoSrc} alt="Q-Studio" className="w-7 h-7" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-1.5">
              <span className="text-[15px] font-bold tracking-tight bg-gradient-to-r from-[#00D4AA] to-[#00D4AA]/80 bg-clip-text text-transparent">
                Q-Studio
              </span>
              <span className="text-[9px] font-mono font-semibold text-[#00D4AA]/50 bg-[#00D4AA]/8 border border-[#00D4AA]/15 rounded px-1.5 py-0.5 leading-none">
                OKX
              </span>
            </div>
            <span className="text-[9px] text-[#505C78] tracking-[0.2em] uppercase font-medium">Quantitative Platform</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-5 space-y-1 overflow-y-auto">
          <div className="text-[10px] text-[#505C78] uppercase tracking-[0.15em] font-semibold px-4 mb-3">主控台</div>
          {links.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `group relative flex items-center gap-3.5 px-4 py-3 rounded-2xl text-[14px] font-medium transition-all duration-200 ${
                  isActive
                    ? 'text-[#00D4AA]'
                    : 'text-[#7B86A2] hover:text-[#EDF0F7]'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <div className="absolute inset-0 bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.12)] rounded-2xl" />
                  )}
                  <Icon className={`w-[18px] h-[18px] relative z-10 transition-colors duration-200 ${isActive ? 'text-[#00D4AA]' : 'text-[#505C78] group-hover:text-[#7B86A2]'}`} />
                  <span className="relative z-10">{label}</span>
                  {isActive && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-[#00D4AA] rounded-r-full" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Bottom section */}
        <div className="px-3 py-4 border-t border-[rgba(0,212,170,0.06)] space-y-1">
          {bottomLinks.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `group relative flex items-center gap-3.5 px-4 py-3 rounded-2xl text-[14px] font-medium transition-all duration-200 ${
                  isActive
                    ? 'text-[#00D4AA]'
                    : 'text-[#7B86A2] hover:text-[#EDF0F7]'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <div className="absolute inset-0 bg-[rgba(0,212,170,0.08)] border border-[rgba(0,212,170,0.12)] rounded-2xl" />
                  )}
                  <Icon className={`w-[18px] h-[18px] relative z-10 ${isActive ? 'text-[#00D4AA]' : 'text-[#505C78] group-hover:text-[#7B86A2]'}`} />
                  <span className="relative z-10">{label}</span>
                </>
              )}
            </NavLink>
          ))}
          <div className="text-[10px] text-[#505C78] px-4 pt-2 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#00D4AA]/40 animate-pulse" />
            v1.0.0
          </div>
        </div>
      </div>
    </aside>
  )
}
