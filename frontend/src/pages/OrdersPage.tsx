import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { listOrders } from '../api/orders'
import DataTable from '../components/DataTable'
import type { Order } from '../types'

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([])

  useEffect(() => {
    listOrders({ limit: 200 }).then((res) => setOrders(res.data)).catch(() => {})
  }, [])

  const columns = [
    {
      key: 'created_at',
      header: '时间',
      render: (o: Order) => new Date(o.created_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
    },
    { key: 'symbol', header: '交易对' },
    {
      key: 'side',
      header: '方向',
      render: (o: Order) => (
        <span className={`font-mono text-xs ${o.side === 'buy' ? 'text-[#00D4AA]' : 'text-[#FF4757]'}`}>
          {o.side === 'buy' ? '买入' : o.side === 'sell' ? '卖出' : o.side}
        </span>
      ),
    },
    { key: 'order_type', header: '类型' },
    {
      key: 'price',
      header: '价格',
      render: (o: Order) => o.price ? `$${o.price.toFixed(4)}` : '-',
      className: 'font-mono text-xs',
    },
    {
      key: 'quantity',
      header: '数量',
      className: 'font-mono text-xs',
    },
    {
      key: 'filled_quantity',
      header: '已成交',
      className: 'font-mono text-xs',
    },
    { key: 'status', header: '状态' },
  ]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <h2 className="text-sm font-medium text-[#E8E8ED]">交易记录</h2>

      <div className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5">
        <DataTable columns={columns} data={orders} keyField="id" />
      </div>
    </motion.div>
  )
}
