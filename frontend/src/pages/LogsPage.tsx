import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { listLogs } from '../api/logs'
import type { OperationLog, PaginatedResponse } from '../types'

const actionLabels: Record<string, string> = {
  login: '登录',
  add_account: '添加账户',
  update_account: '更新账户',
  delete_account: '删除账户',
  create_strategy: '创建策略',
  start_strategy: '启动策略',
  pause_strategy: '暂停策略',
  resume_strategy: '恢复策略',
  stop_strategy: '停止策略',
  update_strategy_params: '更新策略参数',
  delete_strategy: '删除策略',
}

export default function LogsPage() {
  const [data, setData] = useState<PaginatedResponse<OperationLog>>({ total: 0, items: [] })

  useEffect(() => {
    listLogs({ limit: 200 }).then((res) => setData(res.data)).catch(() => {})
  }, [])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <h2 className="text-sm font-medium text-[#EDF0F7]">操作日志</h2>

      <div className="glass-panel p-5">
        {data.items.length === 0 ? (
          <div className="py-12 text-center text-[#7B86A2] text-sm">
            暂无操作记录
          </div>
        ) : (
          <div className="space-y-0">
            {data.items.map((log, i) => (
              <motion.div
                key={log.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.03 }}
                className="flex items-start gap-4 py-3 border-b border-[rgba(0,212,170,0.08)]/50 last:border-0"
              >
                <span className="text-xs text-[#7B86A2] font-mono whitespace-nowrap mt-0.5">
                  {new Date(log.created_at).toLocaleString('zh-CN', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="text-sm">{actionLabels[log.action] || log.action}</span>
                  {log.target_type && (
                    <span className="text-xs text-[#7B86A2] ml-2">
                      {log.target_type === 'strategy' ? '策略' : log.target_type === 'account' ? '账户' : log.target_type}
                      {log.target_id ? ` #${log.target_id}` : ''}
                    </span>
                  )}
                </div>
                {log.ip_address && (
                  <span className="text-xs text-[#7B86A2] font-mono">{log.ip_address}</span>
                )}
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}
