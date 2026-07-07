import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { FileText, RefreshCw, ChevronDown, Terminal } from 'lucide-react'
import { listApiCallLogs } from '../api/strategies'
import client from '../api/client'
import type { ApiCallLogItem } from '../types'

interface LogFile {
  name: string
  size: number
  date: string
  modified: string
}

export default function ApiLogsPage() {
  const [logs, setLogs] = useState<ApiCallLogItem[]>([])
  const [files, setFiles] = useState<LogFile[]>([])
  const [fileContent, setFileContent] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadData = () => {
    setLoading(true)
    listApiCallLogs({ limit: 200 }).then((res) => setLogs(res.data)).catch(() => {})
    client.get('/strategies/api-call-logs/files').then((res) => setFiles(res.data)).catch(() => {})
    setLoading(false)
  }

  useEffect(() => { loadData() }, [])

  const loadFileContent = async (filename: string) => {
    if (selectedFile === filename) {
      setSelectedFile(null)
      setFileContent(null)
      return
    }
    setSelectedFile(filename)
    try {
      const res = await client.get(`/strategies/api-call-logs/files/${filename}`, { params: { lines: 300 } })
      setFileContent(res.data.content)
    } catch {
      setFileContent(null)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
    if (bytes > 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return bytes + ' B'
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'success': return 'text-[#00D4AA]'
      case 'network_error': case 'empty_response': case 'exception': return 'text-[#FF4757]'
      case 'error': return 'text-[#F0A500]'
      default: return 'text-[#6B6B7B]'
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">API 调用日志</h2>
        <button
          onClick={loadData}
          className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> 刷新
        </button>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide flex items-center gap-2">
          <FileText className="w-3.5 h-3.5" /> 日志文件（按天保存）
        </h3>
        {files.length === 0 ? (
          <p className="text-sm text-[#6B6B7B]">暂无日志文件，策略运行后自动生成</p>
        ) : (
          <div className="space-y-1">
            {files.map((f) => (
              <div key={f.name}>
                <button
                  onClick={() => loadFileContent(f.name)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md hover:bg-[#1A1A24] transition-colors text-left"
                >
                  <ChevronDown className={`w-3.5 h-3.5 text-[#6B6B7B] transition-transform ${selectedFile === f.name ? 'rotate-180' : ''}`} />
                  <Terminal className="w-4 h-4 text-[#00D4AA]" />
                  <span className="text-sm font-mono flex-1">{f.name}</span>
                  <span className="text-xs text-[#6B6B7B]">{formatSize(f.size)}</span>
                  <span className="text-xs text-[#6B6B7B]">{f.date}</span>
                </button>
                {selectedFile === f.name && fileContent !== null && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    className="overflow-hidden"
                  >
                    <pre className="bg-[#0C0C14] border border-[#1E1E28] rounded-md p-4 mx-3 mb-2 text-xs font-mono text-[#6B6B7B] max-h-96 overflow-auto whitespace-pre-wrap break-all leading-relaxed">
                      {fileContent || '(空文件)'}
                    </pre>
                  </motion.div>
                )}
              </div>
            ))}
          </div>
        )}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide flex items-center gap-2">
          <RefreshCw className="w-3.5 h-3.5" /> 实时调用记录（最近 200 条）
        </h3>
        {logs.length === 0 ? (
          <div className="py-12 text-center text-[#6B6B7B] text-sm">
            {loading ? '加载中...' : '暂无调用记录，策略启动后将自动记录每次 OKX API 请求'}
          </div>
        ) : (
          <div className="overflow-auto max-h-[600px]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[#14141A]">
                <tr className="text-[#6B6B7B] uppercase tracking-wide">
                  <th className="text-left py-2 pr-4 whitespace-nowrap">时间</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">账户</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">方法</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">端点</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">响应码</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">状态</th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">响应</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id} className="border-t border-[#1E1E28]/40 hover:bg-[#1A1A24]/30 transition-colors">
                    <td className="py-2 pr-4 text-[#6B6B7B] font-mono whitespace-nowrap">
                      {new Date(l.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">{l.account_name || '-'}</td>
                    <td className="py-2 pr-4 font-mono whitespace-nowrap">{l.method}</td>
                    <td className="py-2 pr-4 font-mono max-w-[220px] truncate" title={l.endpoint || ''}>
                      {(l.endpoint || '').split('?')[0]}
                    </td>
                    <td className="py-2 pr-4 font-mono whitespace-nowrap">{l.response_code}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <span className={statusColor(l.status)}>{l.status}</span>
                    </td>
                    <td className="py-2 pr-4 max-w-[300px] truncate font-mono text-[#6B6B7B]">
                      {l.response_body ? l.response_body.slice(0, 80) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>
    </div>
  )
}
