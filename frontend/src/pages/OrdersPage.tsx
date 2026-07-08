import { useEffect, useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { listOrders } from '../api/orders'
import { listInstances } from '../api/strategies'
import { formatInstId } from '../utils/instId'
import { TableSkeleton } from '../components/Skeleton'
import type { Order, StrategyInstance } from '../types'

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'live', label: '活跃' },
  { value: 'filled', label: '已成交' },
  { value: 'canceled', label: '已撤销' },
]

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedIds, setExpandedIds] = useState<Set<number | string>>(new Set())
  const [statusFilter, setStatusFilter] = useState('')

  const fetchData = () => {
    setLoading(true)
    Promise.all([
      listOrders({ limit: 500, status: statusFilter || undefined }).then((res) => setOrders(res.data)),
      listInstances().then((res) => setInstances(res.data)),
    ]).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
  }, [statusFilter])

  const toggleExpand = (id: number | string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) } else { next.add(id) }
      return next
    })
  }

  const groupedOrders = useMemo(() => {
    const groups: Map<number | string, { name: string; orders: Order[] }> = new Map()

    for (const o of orders) {
      const key = o.strategy_instance_id ?? 'unlinked'
      if (!groups.has(key)) {
        const inst = key === 'unlinked' ? null : instances.find((i) => i.id === key)
        groups.set(key, {
          name: key === 'unlinked' ? '未关联策略' : (inst?.name ?? `策略 #${key}`),
          orders: [],
        })
      }
      groups.get(key)!.orders.push(o)
    }

    return Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === 'unlinked') return 1
      if (b[0] === 'unlinked') return -1
      return Number(b[0]) - Number(a[0])
    })
  }, [orders, instances])

  const formatTime = (ts: string) =>
    new Date(ts).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#EDF0F7]">交易记录</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[#7B86A2]">状态筛选</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md px-3 py-1.5 text-xs text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA]"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="glass-card p-6">
          <TableSkeleton rows={6} cols={5} />
        </div>
      ) : groupedOrders.length === 0 ? (
        <div className="glass-card p-12 text-center text-[#7B86A2] text-sm">
          暂无交易记录，启动策略后交易记录将在此展示
        </div>
      ) : (
        <div className="space-y-2">
          {groupedOrders.map(([key, group]) => {
            const isExpanded = expandedIds.has(key)
            const buyCount = group.orders.filter((o) => o.side === 'buy').length
            const sellCount = group.orders.filter((o) => o.side === 'sell').length

            return (
              <div key={key} className="glass-card overflow-hidden">
                <button
                  onClick={() => toggleExpand(key)}
                  className="w-full flex items-center gap-3 p-4 hover:bg-[rgba(0,212,170,0.06)] transition-colors text-left"
                >
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-[#7B86A2] flex-shrink-0" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-[#7B86A2] flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{group.name}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-[#7B86A2]">
                    <span>共 {group.orders.length} 笔</span>
                    <span className="text-[#00D4AA]">买 {buyCount}</span>
                    <span className="text-[#FF4060]">卖 {sellCount}</span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="border-t border-[rgba(0,212,170,0.08)] overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.8)]">
                          <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">时间</th>
                          <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">交易对</th>
                          <th className="text-left py-2.5 px-3 text-xs text-[#7B86A2] font-medium">方向</th>
                          <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">委托价</th>
                          <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">数量</th>
                          <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">成交价</th>
                          <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">已成交</th>
                          <th className="text-right py-2.5 px-3 text-xs text-[#7B86A2] font-medium">手续费</th>
                          <th className="text-center py-2.5 px-3 text-xs text-[#7B86A2] font-medium">状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.orders.map((o) => (
                          <tr key={o.id} className="border-b border-[rgba(0,212,170,0.08)]/50 hover:bg-[rgba(0,212,170,0.06)] transition-colors">
                            <td className="py-2.5 px-3 text-xs text-[#7B86A2] whitespace-nowrap">{formatTime(o.created_at)}</td>
                            <td className="py-2.5 px-3 text-xs font-mono">{formatInstId(o.symbol)}</td>
                            <td className="py-2.5 px-3">
                              <span className={`font-mono text-xs font-medium ${o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                                {o.side === 'buy' ? '买' : o.side === 'sell' ? '卖' : o.side}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-xs font-mono text-right">{o.price != null ? o.price.toFixed(1) : '-'}</td>
                            <td className="py-2.5 px-3 text-xs font-mono text-right">{o.quantity}</td>
                            <td className="py-2.5 px-3 text-xs font-mono text-right text-[#00D4AA]">
                              {o.fill_px != null ? o.fill_px.toFixed(1) : '-'}
                            </td>
                            <td className="py-2.5 px-3 text-xs font-mono text-right">
                              {o.fill_sz != null ? o.fill_sz : o.filled_quantity}
                            </td>
                            <td className="py-2.5 px-3 text-xs font-mono text-right text-[#7B86A2]">
                              {o.fee != null ? o.fee.toFixed(6) : '-'}
                            </td>
                            <td className="py-2.5 px-3 text-center">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${
                                o.status === 'filled' ? 'bg-[#00D4AA]/10 text-[#00D4AA]' :
                                o.status === 'canceled' ? 'bg-[#7B86A2]/10 text-[#7B86A2]' :
                                'bg-[#F0A500]/10 text-[#F0A500]'
                              }`}>
                                {o.status === 'filled' ? '已成交' : o.status === 'canceled' ? '已撤销' : o.state || o.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </motion.div>
  )
}