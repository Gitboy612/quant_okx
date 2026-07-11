import { useEffect, useState, useRef, useCallback } from 'react'
import { getPnlSummary, listPnlRecords } from '../api/pnl'
import { listInstances, listApiCallLogs } from '../api/strategies'
import { listOrders } from '../api/orders'
import { getAccountBalance, getPositions } from '../api/accounts'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import { getSettings } from '../api/settings'
import type { PnlSummary, PnlRecord, StrategyInstance, Order, AssetBalance, Position, ApiCallLogItem } from '../types'
import type { TimeRange } from '../components/PnLChart'

export function useDashboardState() {
  const [summary, setSummary] = useState<PnlSummary | null>(null)
  const [pnlRecords, setPnlRecords] = useState<PnlRecord[]>([])
  const [instances, setInstances] = useState<StrategyInstance[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [liveOrders, setLiveOrders] = useState<Order[]>([])
  const [assets, setAssets] = useState<AssetBalance[]>([])
  const [totalEquity, setTotalEquity] = useState<number | null>(null)
  const [apiLogs, setApiLogs] = useState<ApiCallLogItem[]>([])
  const { accounts, selectedAccountId, selectAccount } = useSelectedAccount()
  const [selectedStrategyId, setSelectedStrategyId] = useState<number>(0)
  const [assetLoading, setAssetLoading] = useState(false)
  const [positions, setPositions] = useState<Position[]>([])
  const [positionsLoading, setPositionsLoading] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)
  const [refreshInterval, setRefreshInterval] = useState<number>(0)
  const [timeRange, setTimeRange] = useState<TimeRange>('all')
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [ordersLoading, setOrdersLoading] = useState(true)
  const [logsLoading, setLogsLoading] = useState(true)
  const [kpiLoading, setKpiLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const selectedAccount = accounts.find((a) => a.id === selectedAccountId)

  const computeStartTime = (range: TimeRange): string | undefined => {
    const now = new Date()
    if (range === '24h') {
      const start = new Date(now.getTime() - 24 * 60 * 60 * 1000)
      return start.toISOString()
    }
    if (range === '7d') {
      const start = new Date(now)
      start.setHours(0, 0, 0, 0)
      start.setDate(start.getDate() - 7)
      return start.toISOString()
    }
    if (range === '30d') {
      const start = new Date(now)
      start.setHours(0, 0, 0, 0)
      start.setDate(start.getDate() - 30)
      return start.toISOString()
    }
    // all: 不传 start_time
    return undefined
  }

  const loadBaseData = useCallback(() => {
    const sid = selectedStrategyId || undefined
    getPnlSummary().then((res) => { setSummary(res.data); setSummaryLoading(false); setKpiLoading(false) }).catch(() => { setSummaryLoading(false); setKpiLoading(false) })
    const startTime = computeStartTime(timeRange)
    listPnlRecords({
      ...(sid ? { strategy_instance_id: sid } : {}),
      ...(startTime ? { start_time: startTime } : {}),
    }).then((res) => setPnlRecords(res.data)).catch(() => {})
    listInstances().then((res) => setInstances(res.data)).catch(() => {})
    listOrders(sid ? { strategy_instance_id: sid, status: 'filled', limit: 10, sort_by: 'updated_at' } : { status: 'filled', limit: 10, sort_by: 'updated_at' }).then((res) => {
      setOrders(res.data)
      setOrdersLoading(false)
    }).catch(() => setOrdersLoading(false))
    listOrders(sid ? { strategy_instance_id: sid, status: 'live', limit: 50 } : { status: 'live', limit: 50 }).then((res) => {
      setLiveOrders(res.data)
    }).catch(() => {})
    listApiCallLogs(sid ? { strategy_instance_id: sid, limit: 50 } : { limit: 50 }).then((res) => { setApiLogs(res.data); setLogsLoading(false) }).catch(() => setLogsLoading(false))
  }, [selectedStrategyId, timeRange])

  const loadAssets = useCallback((accountId: number) => {
    setAssetLoading(true)
    setPositionsLoading(true)
    getAccountBalance(accountId).then((br) => {
      setTotalEquity(br.data.total_equity)
      if (br.data.assets) setAssets(br.data.assets)
      setLastRefresh(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
    }).catch(() => {}).finally(() => setAssetLoading(false))
    getPositions(accountId).then((res) => {
      setPositions(res.data)
    }).catch(() => {}).finally(() => setPositionsLoading(false))
  }, [])

  useEffect(() => {
    loadBaseData()
    getSettings().then((res) => {
      const interval = parseInt(res.data.refresh_interval, 10) || 0
      setRefreshInterval(interval)
    }).catch(() => {})
  }, [])

  const hasRunning = instances.some(inst => inst.status === 'running')
  const effectiveInterval = hasRunning ? (refreshInterval as number) * 2 : (refreshInterval as number)

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (refreshInterval > 0 && selectedAccountId) {
      timerRef.current = setInterval(() => {
        loadAssets(selectedAccountId)
        loadBaseData()
      }, effectiveInterval * 1000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [effectiveInterval, refreshInterval, selectedAccountId, loadAssets, loadBaseData])

  const handleAccountChange = (id: number) => {
    selectAccount(id)
    loadAssets(id)
  }

  useEffect(() => {
    if (selectedAccountId) {
      loadAssets(selectedAccountId)
    }
  }, [selectedAccountId, loadAssets])

  const handleRefreshAssets = () => {
    if (selectedAccountId) loadAssets(selectedAccountId)
  }

  return {
    // data
    summary, pnlRecords, instances, orders, liveOrders,
    assets, totalEquity, apiLogs, positions,
    // account
    accounts, selectedAccountId, selectedAccount, handleAccountChange,
    // strategy filter
    selectedStrategyId, setSelectedStrategyId,
    // loading flags
    assetLoading, positionsLoading, summaryLoading, ordersLoading, logsLoading, kpiLoading,
    // refresh
    lastRefresh, refreshInterval, effectiveInterval, hasRunning, handleRefreshAssets,
    // chart
    timeRange, setTimeRange,
  }
}
