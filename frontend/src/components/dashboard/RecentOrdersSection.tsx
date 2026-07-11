import { motion } from 'framer-motion'
import DataTable from '../DataTable'
import { formatInstId } from '../../utils/instId'
import type { Order } from '../../types'

// 订单表格列定义（同时导出供「未成交委托」复用）
export const orderColumns = [
  {
    key: 'created_at', header: '时间',
    render: (o: Order) => new Date(o.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  },
  { key: 'symbol', header: '交易对', render: (o: Order) => formatInstId(o.symbol) },
  {
    key: 'side', header: '方向',
    render: (o: Order) => (
      <span className={o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}>
        {o.side === 'buy' ? '买入' : o.side === 'sell' ? '卖出' : o.side}
      </span>
    ),
  },
  { key: 'price', header: '价格', render: (o: Order) => o.price?.toFixed(4) ?? '-' },
  { key: 'quantity', header: '数量' },
  { key: 'status', header: '状态' },
]

interface RecentOrdersSectionProps {
  orders: Order[]
  ordersLoading: boolean
}

export default function RecentOrdersSection({ orders, ordersLoading }: RecentOrdersSectionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.55, ease: [0.16, 1, 0.3, 1] }}
      className="glass-panel p-5"
    >
      <h3 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">最近交易</h3>
      <div className="max-h-[400px] overflow-y-auto">
        {ordersLoading ? (
          <div className="flex items-center justify-center py-8 text-[#7B86A2] text-sm">加载中...</div>
        ) : orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-[#7B86A2] text-sm gap-1.5">
            <span className="w-8 h-8 rounded-lg bg-[rgba(0,212,170,0.06)] flex items-center justify-center text-[#505C78] text-xs">--</span>
            <span>暂无交易记录</span>
            <span className="text-[11px] text-[#505C78]">启动策略后交易记录将在此展示</span>
          </div>
        ) : (
          <DataTable columns={orderColumns} data={orders} keyField="id" />
        )}
      </div>
    </motion.div>
  )
}
