import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Save, Upload, Wifi, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { getSettings, saveSettings, getProxySettings, saveProxySettings, testProxy, importProxyConfig } from '../api/settings'
import type { UserSettings } from '../types'

interface ProxyNode {
  name: string
  server: string
  port: number
  type: string
}

interface ProxySettings {
  proxy_enabled: boolean
  proxy_url: string
  proxy_config_path: string | null
  nodes: ProxyNode[]
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings>({ refresh_interval: '30' })
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  // proxy
  const [proxy, setProxy] = useState<ProxySettings>({
    proxy_enabled: false,
    proxy_url: '',
    proxy_config_path: null,
    nodes: [],
  })
  const [proxySaving, setProxySaving] = useState(false)
  const [proxySaved, setProxySaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; latency_ms?: number } | null>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ ok: boolean; message: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    getSettings().then((res) => setSettings(res.data)).catch(() => {})
    getProxySettings().then((res) => {
      const d = res.data
      setProxy((prev) => ({
        ...prev,
        proxy_enabled: d.proxy_enabled === 'true' || d.proxy_enabled === true,
        proxy_url: d.proxy_url || '',
        proxy_config_path: d.proxy_config_path || null,
        nodes: d.nodes || prev.nodes,
      }))
    }).catch(() => {})
  }, [])

  const handleSave = async () => {
    setLoading(true)
    try {
      await saveSettings({ refresh_interval: settings.refresh_interval })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {}
    setLoading(false)
  }

  const handleProxySave = async () => {
    setProxySaving(true)
    try {
      await saveProxySettings({ proxy_enabled: proxy.proxy_enabled, proxy_url: proxy.proxy_url })
      setProxySaved(true)
      setTimeout(() => setProxySaved(false), 2000)
    } catch {}
    setProxySaving(false)
  }

  const handleTestProxy = async () => {
    if (!proxy.proxy_url) return
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testProxy(proxy.proxy_url)
      setTestResult(res.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestResult({ ok: false, message: detail || '连通性测试失败' })
    }
    setTesting(false)
  }

  const handleImportConfig = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importProxyConfig(file)
      const nodes = res.data.nodes || []
      const msg = res.data.message || `成功导入 ${nodes.length} 个节点`
      setProxy((prev) => ({ ...prev, nodes }))
      setImportResult({ ok: true, message: msg })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setImportResult({ ok: false, message: detail || '导入失败' })
    }
    setImporting(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleNodeSelect = (node: ProxyNode) => {
    const url = node.type === 'socks5' || node.type === 'socks' || node.type === 'socks5h'
      ? `socks5://${node.server}:${node.port}`
      : `http://${node.server}:${node.port}`
    setProxy((prev) => ({ ...prev, proxy_url: url }))
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">系统设置</h2>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-4 uppercase tracking-wide">常规设置</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[#E8E8ED] mb-2">资产自动刷新间隔（秒）</label>
            <p className="text-xs text-[#6B6B7B] mb-3">仪表盘资产余额自动拉取的间隔时间，设为 0 则关闭自动刷新</p>
            <input
              type="number"
              min={0}
              max={3600}
              value={settings.refresh_interval}
              onChange={(e) => setSettings({ ...settings, refresh_interval: e.target.value })}
              className="w-32 bg-[#0C0C14] border border-[#1E1E28] rounded-lg px-4 py-2.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {loading ? '保存中...' : '保存设置'}
            </button>
            {saved && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-[#00D4AA]"
              >
                已保存
              </motion.span>
            )}
          </div>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-4 uppercase tracking-wide">代理设置</h3>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-[#E8E8ED]">启用代理</label>
              <p className="text-xs text-[#6B6B7B] mt-0.5">通过代理访问 OKX API</p>
            </div>
            <button
              onClick={() => setProxy((prev) => ({ ...prev, proxy_enabled: !prev.proxy_enabled }))}
              className={`relative w-10 h-5 rounded-full transition-colors ${
                proxy.proxy_enabled ? 'bg-[#00D4AA]' : 'bg-[#1E1E28]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  proxy.proxy_enabled ? 'translate-x-5' : ''
                }`}
              />
            </button>
          </div>

          <div>
            <label className="text-sm text-[#E8E8ED]">代理地址</label>
            <p className="text-xs text-[#6B6B7B] mt-0.5 mb-2">格式：http://127.0.0.1:7890 或 socks5://127.0.0.1:1080</p>
            <input
              value={proxy.proxy_url}
              onChange={(e) => setProxy((prev) => ({ ...prev, proxy_url: e.target.value }))}
              placeholder="http://127.0.0.1:7890"
              className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-lg px-4 py-2.5 text-sm text-[#E8E8ED] font-mono focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleTestProxy}
              disabled={testing || !proxy.proxy_url}
              className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] disabled:opacity-50 transition-colors"
            >
              {testing ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> 测试中...</>
              ) : (
                <><Wifi className="w-4 h-4" /> 测试连通性</>
              )}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.yaml,.yml,.txt"
              onChange={handleImportConfig}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
              className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] disabled:opacity-50 transition-colors"
            >
              {importing ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> 导入中...</>
              ) : (
                <><Upload className="w-4 h-4" /> 导入配置文件</>
              )}
            </button>
          </div>

          {testResult && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex items-center gap-2 text-sm p-3 rounded-md border ${
                testResult.ok
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                  : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
              }`}
            >
              {testResult.ok ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
              {testResult.message}
              {testResult.latency_ms !== undefined && (
                <span className="text-[#6B6B7B] ml-1">({testResult.latency_ms}ms)</span>
              )}
            </motion.div>
          )}

          {importResult && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex items-center gap-2 text-sm p-3 rounded-md border ${
                importResult.ok
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                  : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
              }`}
            >
              {importResult.ok ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
              {importResult.message}
            </motion.div>
          )}

          {proxy.nodes.length > 0 && (
            <div>
              <label className="text-sm text-[#E8E8ED]">可用节点</label>
              <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {proxy.nodes.map((node, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleNodeSelect(node)}
                    className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors flex items-center gap-2 ${
                      proxy.proxy_url === (node.type === 'socks5' || node.type === 'socks' || node.type === 'socks5h'
                        ? `socks5://${node.server}:${node.port}`
                        : `http://${node.server}:${node.port}`)
                        ? 'bg-[#00D4AA]/10 border border-[#00D4AA]/30 text-[#00D4AA]'
                        : 'bg-[#0C0C14] border border-[#1E1E28] text-[#6B6B7B] hover:text-[#E8E8ED] hover:bg-[#1A1A24]'
                    }`}
                  >
                    <Wifi className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="font-mono truncate">
                      {node.name} ({node.type}://{node.server}:{node.port})
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleProxySave}
              disabled={proxySaving}
              className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {proxySaving ? '保存中...' : '保存代理设置'}
            </button>
            {proxySaved && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-[#00D4AA]"
              >
                已保存
              </motion.span>
            )}
          </div>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">说明</h3>
        <div className="text-sm text-[#6B6B7B] space-y-2">
          <p>自动刷新运行在前端浏览器中，页面关闭即停止。</p>
          <p>刷新间隔过短可能触发 OKX API 频率限制，建议不低于 10 秒。</p>
          <p>代理配置用于访问 OKX API 时使用代理连接，适用于需要科学上网的环境。</p>
        </div>
      </motion.div>
    </div>
  )
}