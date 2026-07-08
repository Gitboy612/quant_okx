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
} from 'lucide-react'
import { listInstances } from '../api/strategies'
import { getStrategyEvents, deleteStrategyEvents, exportStrategyEvents } from '../api/monitoring'
import { formatInstId } from '../utils/instId'
import Dropdown from '../components/Dropdown'
import { TableSkeleton } from '../components/Skeleton'
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

export default function MonitoringPage() {
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [instancesLoading, setInstancesLoading] = useState(true)
  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(null)
  const [events, setEvents] = useState<StrategyEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    listInstances().then((res) => setInstances(res.data)).catch(() => {}).finally(() => setInstancesLoading(false))
  }, [])

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