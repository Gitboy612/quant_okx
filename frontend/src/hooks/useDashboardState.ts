import { useEffect, useState, useRef, useCallback } from 'react'
import { getPnlSummary, listPnlRecords } from '../api/pnl'
import { listInstances, listApiCallLogs } from '../api/strategies'
import { listOrders } from '../api/orders'
import { getAccountBalance, getPositions } from '../api/accounts'
import { useSelectedAccount } from '../hooks/useSelectedAccount'
import { getSettings } from '../api/settings'
import type { PnlSummary, PnlRecord, StrategyInstance, Order, AssetBalance, Position, ApiCallLogItem } from '../types'

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
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [ordersLoading, setOrdersLoading] = useState(true)
  const [logsLoading, setLogsLoading] = useState(true)
  const [kpiLoading, setKpiLoading] = useState(true)
  // PnL 曲线区域加载态：切换策略时重置为 true
  const [pnlLoading, setPnlLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const selectedAccount = accounts.find((a) => a.id === selectedAccountId)

  const loadBaseData = useCallback(() => {
    const sid = selectedStrategyId || undefined
    // PnL 曲线开始加载
    setPnlLoading(true)
    // 传入 strategy_instance_id 以支持按策略筛选汇总
    getPnlSummary(sid ? { strategy_instance_id: sid } : {}).then((res) => { setSummary(res.data); setSummaryLoading(false); setKpiLoading(false) }).catch(() => { setSummaryLoading(false); setKpiLoading(false) })
    // 直接拉取原始数据点（后端上限 5000），不再按时间范围筛选
    listPnlRecords({
      ...(sid ? { strategy_instance_id: sid } : {}),
      limit: 5000,
    }).then((res) => setPnlRecords(res.data)).catch(() => {}).finally(() => setPnlLoading(false))
    listInstances().then((res) => setInstances(res.data)).catch(() => {})
    listOrders(sid ? { strategy_instance_id: sid, status: 'filled', limit: 10, sort_by: 'updated_at' } : { status: 'filled', limit: 10, sort_by: 'updated_at' }).then((res) => {
      setOrders(res.data)
      setOrdersLoading(false)
    }).catch(() => setOrdersLoading(false))
    listOrders(sid ? { strategy_instance_id: sid, status: 'live', limit: 50 } : { status: 'live', limit: 50 }).then((res) => {
      setLiveOrders(res.data)
    }).catch(() => {})
    listApiCallLogs(sid ? { strategy_instance_id: sid, limit: 50 } : { limit: 50 }).then((res) => { setApiLogs(res.data); setLogsLoading(false) }).catch(() => setLogsLoading(false))
  }, [selectedStrategyId])

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
    // 依赖 loadBaseData：selectedStrategyId 变化时触发刷新
  }, [loadBaseData])

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
    assetLoading, positionsLoading, summaryLoading, ordersLoading, logsLoading, kpiLoading, pnlLoading,
    // refresh
    lastRefresh, refreshInterval, effectiveInterval, hasRunning, handleRefreshAssets,
  }
}
