import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Square,
  Pause,
  Plus,
  Check,
  X,
  AlertTriangle,
  AlertCircle,
  DollarSign,
  Download,
  Trash2,
  RefreshCw,
  Activity,
  Scale,
  ShieldCheck,
} from 'lucide-react'
import { listInstances } from '../api/strategies'
import { getStrategyEvents, deleteStrategyEvents, exportStrategyEvents, getPositionConflicts, getHealthMetrics, getReconcilePositions } from '../api/monitoring'
import type { PositionConflict, HealthMetrics, HealthAlertType, ReconcileResult } from '../api/monitoring'
import { formatInstId } from '../utils/instId'
import Dropdown from '../components/Dropdown'
import { TableSkeleton } from '../components/Skeleton'
import StatusBadge from '../components/StatusBadge'
import type { StrategyInstance, StrategyEvent } from '../types'

const EVENT_ICONS: Record<string, { icon: typeof Play; color: string; label: string }> = {
  started: { icon: Play, color: '#00D4AA', label: '已启动' },
  stopped: { icon: Square, color: '#FF4060', label: '已停止' },
  paused: { icon: Pause, color: '#F0A500', label: '已暂停' },
  resumed: { icon: Play, color: '#4A90D9', label: '已恢复' },
  order_placed: { icon: Plus, color: '#00D4AA', label: '下单' },
  order_filled: { icon: Check, color: '#00D4AA', label: '已成交' },
  order_canceled: { icon: X, color: '#7B86A2', label: '已撤销' },
  order_failed: { icon: AlertTriangle, color: '#FF4060', label: '下单失败' },
  pnl_recorded: { icon: DollarSign, color: '#A855F7', label: '盈亏记录' },
  error: { icon: AlertCircle, color: '#FF4060', label: '错误' },
}

const DEFAULT_EVENT: { icon: typeof Play; color: string; label: string } = {
  icon: Activity,
  color: '#7B86A2',
  label: '事件',
}

const ALERT_TYPE_LABEL: Record<HealthAlertType, string> = {
  margin_warning: '保证金告警',
  position_conflict: '仓位冲突',
  order_latency: '延迟告警',
  capital_usage: '资金告警',
}

// 对冲组配色：同组策略用相同边框颜色（Task 7 SubTask 7.3）
const HEDGE_GROUP_COLORS: Record<string, { border: string; bg: string; text: string; label: string }> = {
  G1: { border: 'border-[#00D4AA]/40', bg: 'bg-[#00D4AA]/5', text: 'text-[#00D4AA]', label: '对冲组 G1' },
  G2: { border: 'border-[#4A90D9]/40', bg: 'bg-[#4A90D9]/5', text: 'text-[#4A90D9]', label: '对冲组 G2' },
  G3: { border: 'border-[#A855F7]/40', bg: 'bg-[#A855F7]/5', text: 'text-[#A855F7]', label: '对冲组 G3' },
  G4: { border: 'border-[#F0A500]/40', bg: 'bg-[#F0A500]/5', text: 'text-[#F0A500]', label: '对冲组 G4' },
}

const getHedgeGroupColor = (groupId: string | null) => {
  if (!groupId) return null
  if (HEDGE_GROUP_COLORS[groupId]) return HEDGE_GROUP_COLORS[groupId]
  // 超出预定义数量时按哈希落到 G1-G4
  const idx = (parseInt(groupId.slice(1)) % 4) + 1
  return HEDGE_GROUP_COLORS[`G${idx}`]
}

export default function MonitoringPage() {
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [instancesLoading, setInstancesLoading] = useState(true)
  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(null)
  const [events, setEvents] = useState<StrategyEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [conflicts, setConflicts] = useState<PositionConflict[]>([])
  const [reconcileResults, setReconcileResults] = useState<ReconcileResult[]>([])
  const [health, setHealth] = useState<HealthMetrics | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    listInstances().then((res) => setInstances(res.data)).catch(() => {}).finally(() => setInstancesLoading(false))
  }, [])

  // 平仓能力检测：从 instances 提取所有 account_id，拉取冲突列表（Task 7: 代数和算法）
  useEffect(() => {
    if (instancesLoading || instances.length === 0) return
    const accountIds = [...new Set(instances.map((i) => i.account_id))]
    Promise.all(accountIds.map((aid) => getPositionConflicts(aid).then((res) => res.data.conflicts).catch(() => [])))
      .then((results) => setConflicts(results.flat()))
      .catch(() => {})
  }, [instances, instancesLoading])

  // 仓位隔离对账：按 (account_id, symbol) 拉取 reconcile 结果（Task 7）
  useEffect(() => {
    if (instancesLoading || instances.length === 0) return
    // 去重 (account_id, symbol) 组合
    const pairs = new Map<string, { accountId: number; symbol: string }>()
    for (const inst of instances) {
      const key = `${inst.account_id}:${inst.symbol}`
      if (!pairs.has(key)) pairs.set(key, { accountId: inst.account_id, symbol: inst.symbol })
    }
    Promise.all(
      [...pairs.values()].map(({ accountId, symbol }) =>
        getReconcilePositions(accountId, symbol).then((res) => res.data).catch(() => null)
      )
    )
      .then((results) => setReconcileResults(results.filter((r): r is ReconcileResult => r !== null)))
      .catch(() => {})
  }, [instances, instancesLoading])

  // 健康指标看板：按 account_id 拉取延迟/资金/保证金/隔离指标（Task 12）
  useEffect(() => {
    if (instancesLoading || instances.length === 0) return
    const accountIds = [...new Set(instances.map((i) => i.account_id))]
    Promise.all(accountIds.map((aid) => getHealthMetrics(aid).then((res) => res.data).catch(() => null)))
      .then((results) => {
        const valid = results.filter((r): r is HealthMetrics => r !== null)
        setHealth({
          strategies: valid.flatMap((r) => r.strategies),
          alerts: valid.flatMap((r) => r.alerts),
        })
      })
      .catch(() => {})
  }, [instances, instancesLoading])

  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (selectedInstanceId !== null) {
      loadEvents()
      pollRef.current = setInterval(loadEvents, 10000)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [selectedInstanceId])

  const loadEvents = () => {
    if (selectedInstanceId === null) return
    setLoading(true)
    getStrategyEvents(selectedInstanceId, 200)
      .then((res) => setEvents(res.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  const handleClear = async () => {
    if (selectedInstanceId === null) return
    if (!window.confirm('确认清空此策略的所有监测事件？此操作不可撤销。')) return
    setClearing(true)
    try {
      await deleteStrategyEvents(selectedInstanceId)
      setEvents([])
    } catch {}
    setClearing(false)
  }

  const handleExport = async () => {
    if (selectedInstanceId === null) return
    setExporting(true)
    try {
      const res = await exportStrategyEvents(selectedInstanceId)
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `strategy_${selectedInstanceId}_events.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {}
    setExporting(false)
  }

  const formatTime = (ts: string) =>
    new Date(ts).toLocaleString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })

  const runningInstances = instances.filter((i) => i.status === 'running' || i.status === 'paused')
  const nonRunningInstances = instances.filter((i) => i.status !== 'running' && i.status !== 'paused')
  const instanceOptions = [
    { value: '', label: '-- 请选择策略 --' },
    ...runningInstances.map((inst) => ({ value: inst.id, label: `${inst.name} (${formatInstId(inst.symbol)})` })),
    ...nonRunningInstances.map((inst) => ({ value: inst.id, label: `${inst.name} (${formatInstId(inst.symbol)}) [${inst.status}]` })),
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#EDF0F7]">策略监测</h2>
      </div>

      {/* 阈值告警卡片（SubTask 12.4） */}
      {health && health.alerts.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <AlertCircle className="w-4 h-4 text-[#FF4060]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">阈值告警</h3>
            <span className="text-[10px] text-[#7B86A2]">{health.alerts.length} 条告警</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {health.alerts.map((alert, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${
                  alert.level === 'critical'
                    ? 'bg-[rgba(255,64,96,0.08)] border border-[#FF4060]/20'
                    : 'bg-[rgba(240,165,0,0.08)] border border-[#F0A500]/20'
                }`}
              >
                <AlertTriangle
                  className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${
                    alert.level === 'critical' ? 'text-[#FF4060]' : 'text-[#F0A500]'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <span
                    className={`font-medium ${
                      alert.level === 'critical' ? 'text-[#FF4060]' : 'text-[#F0A500]'
                    }`}
                  >
                    {ALERT_TYPE_LABEL[alert.type]}
                  </span>
                  <span className="text-[#7B86A2] ml-1">{alert.message}</span>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* 成交延迟面板（SubTask 12.1） */}
      {health && health.strategies.some((s) => s.latency) && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-[#00D4AA]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">成交延迟</h3>
            <span className="text-[10px] text-[#7B86A2]">补单延迟 P50/P95（仅网格策略）</span>
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
            <span className="w-16">策略ID</span>
            <span className="w-28">交易对</span>
            <span className="w-20 text-right">P50</span>
            <span className="w-20 text-right">P95</span>
            <span className="w-16 text-right">样本</span>
            <span className="w-24 text-center">状态</span>
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {health.strategies.filter((s) => s.latency).map((s) => {
              const isWarn = s.latency!.p95 > 2.0
              return (
                <div
                  key={s.instance_id}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                    isWarn
                      ? 'bg-[rgba(240,165,0,0.08)] border border-[#F0A500]/20'
                      : 'bg-[rgba(10,15,30,0.5)]'
                  }`}
                >
                  <span className="font-mono text-[#EDF0F7] w-16">#{s.instance_id}</span>
                  <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(s.symbol)}</span>
                  <span className="font-mono text-[#7B86A2] w-20 text-right">
                    {s.latency!.count > 0 ? `${(s.latency!.p50 * 1000).toFixed(0)}ms` : '-'}
                  </span>
                  <span className={`font-mono w-20 text-right ${isWarn ? 'text-[#F0A500]' : 'text-[#EDF0F7]'}`}>
                    {s.latency!.count > 0 ? `${(s.latency!.p95 * 1000).toFixed(0)}ms` : '-'}
                  </span>
                  <span className="font-mono text-[#7B86A2] w-16 text-right">{s.latency!.count}</span>
                  <span className="w-24 flex justify-center">
                    {isWarn ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#F0A500]/10 text-[#F0A500]">警告</span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#00D4AA]/10 text-[#00D4AA]">正常</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        </motion.div>
      )}

      {/* 资金健康面板（SubTask 12.2） */}
      {health && health.strategies.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-[#00D4AA]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">资金健康</h3>
            <span className="text-[10px] text-[#7B86A2]">使用率 = 持仓名义价值 / (投入 × 杠杆)</span>
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
            <span className="w-16">策略ID</span>
            <span className="w-28">交易对</span>
            <span className="w-24 text-right">投入资金</span>
            <span className="w-24 text-right">持仓名义</span>
            <span className="w-20 text-right">使用率</span>
            <span className="w-24 text-center">状态</span>
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {health.strategies.map((s) => {
              const isWarn = s.capital.usage_rate > 0.8
              return (
                <div
                  key={s.instance_id}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                    isWarn
                      ? 'bg-[rgba(240,165,0,0.08)] border border-[#F0A500]/20'
                      : 'bg-[rgba(10,15,30,0.5)]'
                  }`}
                >
                  <span className="font-mono text-[#EDF0F7] w-16">#{s.instance_id}</span>
                  <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(s.symbol)}</span>
                  <span className="font-mono text-[#7B86A2] w-24 text-right">${s.capital.investment_amount.toFixed(2)}</span>
                  <span className="font-mono text-[#EDF0F7] w-24 text-right">${s.capital.position_value.toFixed(2)}</span>
                  <span className={`font-mono w-20 text-right ${isWarn ? 'text-[#F0A500]' : 'text-[#EDF0F7]'}`}>
                    {(s.capital.usage_rate * 100).toFixed(1)}%
                  </span>
                  <span className="w-24 flex justify-center">
                    {isWarn ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#F0A500]/10 text-[#F0A500]">警告</span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#00D4AA]/10 text-[#00D4AA]">正常</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        </motion.div>
      )}

      {/* 仓位隔离面板（SubTask 12.3） */}
      {health && health.strategies.some((s) => s.isolation) && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-[#00D4AA]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">仓位隔离</h3>
            <span className="text-[10px] text-[#7B86A2]">虚拟 vs 真实持仓差异</span>
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
            <span className="w-16">策略ID</span>
            <span className="w-28">交易对</span>
            <span className="w-24 text-right">差异</span>
            <span className="w-24 text-center">状态</span>
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {health.strategies.filter((s) => s.isolation).map((s) => {
              const isConflict = !s.isolation!.matched
              return (
                <div
                  key={s.instance_id}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                    isConflict
                      ? 'bg-[rgba(255,64,96,0.08)] border border-[#FF4060]/20'
                      : 'bg-[rgba(10,15,30,0.5)]'
                  }`}
                >
                  <span className="font-mono text-[#EDF0F7] w-16">#{s.instance_id}</span>
                  <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(s.symbol)}</span>
                  <span className={`font-mono w-24 text-right ${isConflict ? 'text-[#FF4060]' : 'text-[#EDF0F7]'}`}>
                    {s.isolation!.diff.toFixed(4)}
                  </span>
                  <span className="w-24 flex justify-center">
                    {isConflict ? <StatusBadge status="conflict" /> : <StatusBadge status="running" />}
                  </span>
                </div>
              )
            })}
          </div>
          {/* 冲突策略列表（复用 Task 5 position_conflicts） */}
          {conflicts.filter((c) => c.is_conflict).length > 0 && (
            <div className="mt-3 pt-3 border-t border-[rgba(0,212,170,0.06)]">
              <div className="text-[10px] text-[#505C78] uppercase tracking-wider mb-2">冲突策略</div>
              <div className="flex flex-wrap gap-1.5">
                {conflicts.filter((c) => c.is_conflict).map((c, i) => (
                  <span
                    key={i}
                    className="font-mono text-[10px] px-2 py-0.5 rounded bg-[#FF4060]/10 text-[#FF4060] border border-[#FF4060]/20"
                  >
                    #{c.strategy_instance_id} {formatInstId(c.symbol)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}

      {/* 仓位隔离对账看板（Task 7 SubTask 7.2）：调用 reconcile_positions 端点 */}
      {reconcileResults.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Scale className="w-4 h-4 text-[#00D4AA]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">仓位隔离对账</h3>
            <span className="text-[10px] text-[#7B86A2]">虚拟持仓 vs 真实持仓差异（数据一致性）</span>
          </div>
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
            <span className="w-16">账户ID</span>
            <span className="w-28">交易对</span>
            <span className="w-24 text-right">虚拟持仓和</span>
            <span className="w-24 text-right">真实持仓</span>
            <span className="w-20 text-right">差异</span>
            <span className="w-24 text-center">状态</span>
          </div>
          {/* 列表区域：最大高度 + 内部滚动 */}
          <div className="max-h-72 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-1.5">
              {reconcileResults.map((r, i) => {
                const isMismatch = !r.matched
                return (
                  <div
                    key={i}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                      isMismatch
                        ? 'bg-[rgba(255,64,96,0.08)] border border-[#FF4060]/20'
                        : 'bg-[rgba(10,15,30,0.5)]'
                    }`}
                  >
                    <span className="font-mono text-[#EDF0F7] w-16">#{r.account_id}</span>
                    <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(r.symbol)}</span>
                    <span className="font-mono text-[#7B86A2] w-24 text-right">{r.virtual_total.toFixed(4)}</span>
                    <span className={`font-mono w-24 text-right ${r.real_total >= 0 ? 'text-[#EDF0F7]' : 'text-[#FF4060]'}`}>
                      {r.real_total.toFixed(4)}
                    </span>
                    <span className={`font-mono w-20 text-right ${isMismatch ? 'text-[#FF4060]' : 'text-[#00D4AA]'}`}>
                      {r.diff.toFixed(4)}
                    </span>
                    <span className="w-24 flex justify-center">
                      {isMismatch ? <StatusBadge status="conflict" /> : <StatusBadge status="running" />}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </motion.div>
      )}

      {/* 平仓能力看板（Task 7 SubTask 7.2/7.3）：调用 position_conflicts 端点 + 对冲组标注 */}
      {conflicts.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-panel p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <ShieldCheck className="w-4 h-4 text-[#00D4AA]" />
            <h3 className="text-sm font-medium text-[#EDF0F7]">平仓能力</h3>
            <span className="text-[10px] text-[#7B86A2]">
              每个策略能否独立平掉自己的净持仓（代数和算法）
            </span>
          </div>
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
            <span className="w-16">策略ID</span>
            <span className="w-24">交易对</span>
            <span className="w-20 text-right">真实持仓</span>
            <span className="w-20 text-right">净持仓</span>
            <span className="w-20 text-right">其他占用</span>
            <span className="w-20 text-right">可用量</span>
            <span className="w-16 text-center">对冲组</span>
            <span className="w-20 text-center">状态</span>
          </div>
          {/* 列表区域：最大高度 + 内部滚动 */}
          <div className="max-h-72 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-1.5">
              {conflicts.map((c, i) => {
                const hedgeColor = getHedgeGroupColor(c.hedge_group)
                const hedgeLabel = c.hedge_group || '-'
                return (
                  <div
                    key={i}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs ${
                      c.is_conflict
                        ? 'bg-[rgba(255,64,96,0.08)] border border-[#FF4060]/20'
                        : hedgeColor
                        ? `${hedgeColor.bg} border ${hedgeColor.border}`
                        : 'bg-[rgba(10,15,30,0.5)]'
                    }`}
                  >
                    <span className="font-mono text-[#EDF0F7] w-16">#{c.strategy_instance_id}</span>
                    <span className="font-mono text-[#EDF0F7] w-24 truncate">{formatInstId(c.symbol)}</span>
                    <span className={`font-mono w-20 text-right ${c.real_pos >= 0 ? 'text-[#EDF0F7]' : 'text-[#FF4060]'}`}>
                      {c.real_pos.toFixed(4)}
                    </span>
                    <span className={`font-mono w-20 text-right ${c.net_position >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                      {c.net_position.toFixed(4)}
                    </span>
                    <span className="font-mono text-[#7B86A2] w-20 text-right">{c.others_occupied.toFixed(4)}</span>
                    <span className={`font-mono w-20 text-right ${c.usable <= 0 ? 'text-[#FF4060]' : 'text-[#EDF0F7]'}`}>
                      {c.usable.toFixed(4)}
                    </span>
                    <span className="w-16 flex justify-center">
                      {c.hedge_group ? (
                        <span
                          className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${hedgeColor?.bg} ${hedgeColor?.text} ${hedgeColor?.border}`}
                          title={hedgeColor?.label}
                        >
                          {hedgeLabel}
                        </span>
                      ) : (
                        <span className="font-mono text-[10px] text-[#505C78]">-</span>
                      )}
                    </span>
                    <span className="w-20 flex justify-center">
                      {c.is_conflict ? <StatusBadge status="conflict" /> : <StatusBadge status="running" />}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
          {/* 对冲组图例 */}
          {conflicts.some((c) => c.hedge_group) && (
            <div className="mt-3 pt-3 border-t border-[rgba(0,212,170,0.06)]">
              <div className="text-[10px] text-[#505C78] uppercase tracking-wider mb-2">对冲组图例</div>
              <div className="flex flex-wrap gap-2">
                {[...new Set(conflicts.map((c) => c.hedge_group).filter((g): g is string => g !== null))].map((g) => {
                  const color = getHedgeGroupColor(g)
                  return (
                    <span
                      key={g}
                      className={`font-mono text-[10px] px-2 py-0.5 rounded border ${color?.bg} ${color?.text} ${color?.border}`}
                    >
                      {color?.label}（同账户同 symbol 多空策略组）
                    </span>
                  )
                })}
              </div>
            </div>
          )}
        </motion.div>
      )}

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-panel p-5"
      >
        <div className="flex items-center gap-4 mb-4">
          <label className="text-xs text-[#7B86A2] flex-shrink-0">选择策略</label>
          {instancesLoading ? (
            <div className="flex-1 h-10 bg-[rgba(0,212,170,0.08)] rounded-lg animate-pulse" />
          ) : (
            <Dropdown
              options={instanceOptions}
              value={selectedInstanceId ?? ''}
              onChange={(v) => {
                setSelectedInstanceId(v ? Number(v) : null)
                setEvents([])
              }}
              className="flex-1"
            />
          )}

          {selectedInstanceId && (
            <div className="flex items-center gap-2">
              <button
                onClick={loadEvents}
                disabled={loading}
                className="flex items-center gap-1.5 border border-[rgba(0,212,170,0.08)] text-[#7B86A2] rounded-md px-3 py-2 text-xs hover:bg-[rgba(0,212,170,0.06)] hover:text-[#EDF0F7] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                刷新
              </button>
              <button
                onClick={handleExport}
                disabled={exporting || events.length === 0}
                className="flex items-center gap-1.5 border border-[rgba(0,212,170,0.08)] text-[#00D4AA] rounded-md px-3 py-2 text-xs hover:bg-[#00D4AA]/10 transition-colors disabled:opacity-50"
              >
                <Download className="w-3.5 h-3.5" />
                {exporting ? '导出中...' : '导出CSV'}
              </button>
              <button
                onClick={handleClear}
                disabled={clearing || events.length === 0}
                className="flex items-center gap-1.5 border border-[#FF4060]/20 text-[#FF4060] rounded-md px-3 py-2 text-xs hover:bg-[#FF4060]/10 transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                {clearing ? '清空中...' : '清空'}
              </button>
            </div>
          )}
        </div>

        {selectedInstanceId === null ? (
          <div className="flex flex-col items-center justify-center py-16 text-[#7B86A2] text-sm gap-2">
            <Activity className="w-10 h-10 opacity-30" />
            <span>暂无监测数据，请先选择策略</span>
          </div>
        ) : loading ? (
          <div className="p-4">
            <TableSkeleton rows={5} cols={3} />
          </div>
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-[#7B86A2] text-sm gap-2">
            <Activity className="w-10 h-10 opacity-30" />
            <span>暂无监测数据，请先启动策略</span>
          </div>
        ) : (
          <div className="relative">
            <div className="absolute left-[19px] top-2 bottom-2 w-px bg-[rgba(0,212,170,0.08)]" />
            <div className="space-y-0">
              {events.map((event, idx) => {
                const cfg = EVENT_ICONS[event.event_type] || DEFAULT_EVENT
                const Icon = cfg.icon
                return (
                  <motion.div
                    key={event.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.02 }}
                    className="relative flex items-start gap-4 py-2.5 pl-1"
                  >
                    <div
                      className="relative z-10 flex items-center justify-center w-[38px] h-[38px] rounded-full flex-shrink-0"
                      style={{ backgroundColor: `${cfg.color}15`, border: `1px solid ${cfg.color}30` }}
                    >
                      <Icon className="w-4 h-4" style={{ color: cfg.color }} />
                    </div>
                    <div className="flex-1 min-w-0 pt-1.5">
                      <div className="flex items-center gap-2">
                        <span
                          className="text-xs font-medium px-1.5 py-0.5 rounded"
                          style={{ color: cfg.color, backgroundColor: `${cfg.color}15` }}
                        >
                          {cfg.label}
                        </span>
                        <span className="text-[10px] text-[#7B86A2]">
                          {formatTime(event.created_at)}
                        </span>
                      </div>
                      <p className="text-sm text-[#EDF0F7] mt-1 leading-relaxed">{event.message}</p>
                      {event.details && (
                        <p className="text-xs text-[#7B86A2] mt-0.5 font-mono whitespace-pre-wrap break-all">
                          {event.details}
                        </p>
                      )}
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}