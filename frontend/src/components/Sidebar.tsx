import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  FileText,
  Wallet,
  ScrollText,
  Zap,
  Activity,
  Settings,
  Eye,
} from 'lucide-react'

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
    <aside className="fixed left-0 top-0 h-screen w-60 bg-[#0C0C14] border-r border-[#1E1E28] flex flex-col z-30">
      <div className="h-16 flex items-center gap-3 px-5 border-b border-[#1E1E28]">
        <Zap className="w-6 h-6 text-[#00D4AA]" />
        <span className="text-lg font-bold tracking-tight">QuantOKX</span>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA]'
                  : 'text-[#6B6B7B] hover:text-[#E8E8ED] hover:bg-[#1A1A24]'
              }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[#1E1E28] space-y-1">
        {bottomLinks.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA]'
                  : 'text-[#6B6B7B] hover:text-[#E8E8ED] hover:bg-[#1A1A24]'
              }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </div>
      <div className="px-3 py-3 border-t border-[#1E1E28]">
        <div className="text-xs text-[#6B6B7B] px-3">v1.0.0</div>
      </div>
    </aside>
  )
}
